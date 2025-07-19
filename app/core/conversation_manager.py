"""
Conversation state management with Redis support.
"""
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import json
import logging
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
import redis.asyncio as redis
from sqlalchemy import select, desc
from fastapi import Request
from typing import Annotated
from fastapi import Depends

from .database_manager import DatabaseManager
from .config_service import ConfigService
from .service_interface import ServiceInterface, HealthCheckResult, ServiceStatus
from ..models import ResponseHistory, Case

logger = logging.getLogger(__name__)


@dataclass
class ConversationState:
    """State of a conversation"""
    conversation_id: str
    last_response_id: Optional[str] = None
    case_id: Optional[str] = None
    user_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "conversation_id": self.conversation_id,
            "last_response_id": self.last_response_id,
            "case_id": self.case_id,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConversationState':
        """Create from dictionary"""
        return cls(
            conversation_id=data["conversation_id"],
            last_response_id=data.get("last_response_id"),
            case_id=data.get("case_id"),
            user_id=data.get("user_id"),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            metadata=data.get("metadata", {})
        )


class ConversationManager(ServiceInterface):
    """
    Manages conversation state and history with Redis caching and PostgreSQL persistence.
    """
    
    def __init__(self, db_manager: DatabaseManager, config_service: ConfigService):
        super().__init__("ConversationManager")
        self._config = config_service.config
        self._db_manager = db_manager
        self._redis_client: Optional[redis.Redis] = None
        self._cache_ttl = timedelta(hours=24)  # Conversation cache TTL
    
    async def _initialize_impl(self) -> None:
        """Initialize Redis connection"""
        try:
            self._redis_client = await redis.from_url(
                self._config.redis.url,
                encoding="utf-8",
                decode_responses=True
            )
            # Test connection
            await self._redis_client.ping()
            logger.info("Redis connection established")
        except Exception as e:
            logger.warning(f"Redis not available, using in-memory cache: {e}")
            self._redis_client = None
            self._memory_cache: Dict[str, ConversationState] = {}
    
    async def _shutdown_impl(self) -> None:
        """Cleanup resources"""
        if self._redis_client:
            await self._redis_client.close()
    
    async def _health_check_impl(self) -> HealthCheckResult:
        """Check service health"""
        details = {}
        
        # Check Redis
        if self._redis_client:
            try:
                await self._redis_client.ping()
                details["redis"] = "connected"
            except:
                details["redis"] = "disconnected"
        else:
            details["redis"] = "not configured"
        
        # Check database
        try:
            async with self._db_manager.get_session() as session:
                await session.execute(select(ResponseHistory).limit(1))
            details["database"] = "connected"
        except:
            details["database"] = "error"
            return HealthCheckResult(
                status=ServiceStatus.UNHEALTHY,
                message="Database connection failed",
                details=details
            )
        
        return HealthCheckResult(
            status=ServiceStatus.HEALTHY,
            message="Conversation manager is healthy",
            details=details
        )
    
    async def get_or_create_conversation(self, 
                                       conversation_id: str,
                                       user_id: Optional[str] = None,
                                       case_id: Optional[str] = None) -> ConversationState:
        """Get existing conversation or create new one"""
        # Try cache first
        state = await self._get_from_cache(conversation_id)
        if state:
            return state
        
        # Check database
        state = await self._get_from_db(conversation_id)
        if state:
            await self._save_to_cache(state)
            return state
        
        # Create new
        state = ConversationState(
            conversation_id=conversation_id,
            user_id=user_id,
            case_id=case_id
        )
        await self._save_to_cache(state)
        return state
    
    async def update_conversation(self, 
                                state: ConversationState,
                                response_id: Optional[str] = None) -> None:
        """Update conversation state"""
        if response_id:
            state.last_response_id = response_id
        state.updated_at = datetime.now()
        
        await self._save_to_cache(state)
    
    async def save_response_history(self,
                                  conversation_id: str,
                                  response_id: str,
                                  input_data: Any,
                                  output: Any,
                                  previous_response_id: Optional[str] = None) -> None:
        """Save response history to database"""
        async with self._db_manager.get_session() as session:
            history = ResponseHistory(
                thread_id=conversation_id,
                response_id=response_id,
                input=input_data,
                output=output,
                previous_response_id=previous_response_id
            )
            session.add(history)
            await session.commit()
    
    async def get_conversation_history(self, 
                                     conversation_id: str,
                                     limit: int = 10) -> List[Dict[str, Any]]:
        """Get conversation history from database"""
        async with self._db_manager.get_session() as session:
            result = await session.execute(
                select(ResponseHistory)
                .where(ResponseHistory.thread_id == conversation_id)
                .order_by(desc(ResponseHistory.created_at))
                .limit(limit)
            )
            
            history = []
            for record in reversed(result.scalars().all()):
                history.append({
                    "response_id": record.response_id,
                    "input": record.input,
                    "output": record.output,
                    "created_at": record.created_at.isoformat()
                })
            
            return history
    
    async def link_to_case(self, conversation_id: str, case_id: str) -> None:
        """Link conversation to a case"""
        state = await self.get_or_create_conversation(conversation_id)
        state.case_id = case_id
        await self.update_conversation(state)
        
        # Update case with conversation reference
        async with self._db_manager.get_session() as session:
            result = await session.execute(
                select(Case).where(Case.id == case_id)
            )
            case = result.scalar_one_or_none()
            
            if case:
                # Store conversation ID in case metadata
                if not case.metadata:
                    case.metadata = {}
                
                conversations = case.metadata.get("conversation_ids", [])
                if conversation_id not in conversations:
                    conversations.append(conversation_id)
                    case.metadata["conversation_ids"] = conversations
                    
                await session.commit()
    
    async def get_case_conversations(self, case_id: str) -> List[str]:
        """Get all conversation IDs linked to a case"""
        async with self._db_manager.get_session() as session:
            result = await session.execute(
                select(Case).where(Case.id == case_id)
            )
            case = result.scalar_one_or_none()
            
            if case and case.metadata:
                return case.metadata.get("conversation_ids", [])
            return []
    
    async def cleanup_expired_conversations(self, older_than: timedelta = timedelta(days=30)) -> int:
        """Clean up old conversations"""
        cutoff_date = datetime.now() - older_than
        
        async with self._db_manager.get_session() as session:
            # Get expired conversations
            result = await session.execute(
                select(ResponseHistory.thread_id)
                .where(ResponseHistory.created_at < cutoff_date)
                .distinct()
            )
            
            expired_ids = [row[0] for row in result]
            
            if expired_ids:
                # Delete from cache
                for conv_id in expired_ids:
                    await self._delete_from_cache(conv_id)
                
                # Note: Not deleting from database to preserve history
                logger.info(f"Cleaned up {len(expired_ids)} expired conversations from cache")
            
            return len(expired_ids)
    
    # Cache operations
    async def _get_from_cache(self, conversation_id: str) -> Optional[ConversationState]:
        """Get conversation from cache"""
        if self._redis_client:
            try:
                data = await self._redis_client.get(f"conv:{conversation_id}")
                if data:
                    return ConversationState.from_dict(json.loads(data))
            except Exception as e:
                logger.error(f"Redis get error: {e}")
        else:
            # In-memory fallback
            return self._memory_cache.get(conversation_id)
        
        return None
    
    async def _save_to_cache(self, state: ConversationState) -> None:
        """Save conversation to cache"""
        if self._redis_client:
            try:
                await self._redis_client.setex(
                    f"conv:{state.conversation_id}",
                    self._cache_ttl,
                    json.dumps(state.to_dict())
                )
            except Exception as e:
                logger.error(f"Redis set error: {e}")
        else:
            # In-memory fallback
            self._memory_cache[state.conversation_id] = state
    
    async def _delete_from_cache(self, conversation_id: str) -> None:
        """Delete conversation from cache"""
        if self._redis_client:
            try:
                await self._redis_client.delete(f"conv:{conversation_id}")
            except Exception as e:
                logger.error(f"Redis delete error: {e}")
        else:
            # In-memory fallback
            self._memory_cache.pop(conversation_id, None)
    
    async def _get_from_db(self, conversation_id: str) -> Optional[ConversationState]:
        """Reconstruct conversation state from database"""
        async with self._db_manager.get_session() as session:
            # Get latest response
            result = await session.execute(
                select(ResponseHistory)
                .where(ResponseHistory.thread_id == conversation_id)
                .order_by(desc(ResponseHistory.created_at))
                .limit(1)
            )
            
            latest = result.scalar_one_or_none()
            if latest:
                # Try to extract metadata from responses
                metadata = {}
                if isinstance(latest.input, list) and latest.input:
                    # Extract any metadata from input
                    for item in latest.input:
                        if isinstance(item, dict) and "metadata" in item:
                            metadata.update(item["metadata"])
                
                return ConversationState(
                    conversation_id=conversation_id,
                    last_response_id=latest.response_id,
                    created_at=latest.created_at,
                    updated_at=latest.created_at,
                    metadata=metadata
                )
        
        return None
    
    @asynccontextmanager
    async def conversation_context(self, conversation_id: str):
        """Context manager for conversation operations"""
        state = await self.get_or_create_conversation(conversation_id)
        try:
            yield state
        finally:
            await self.update_conversation(state)

def get_conversation_manager(request: Request) -> ConversationManager:
    return request.app.state.manager.inject_service(ConversationManager)

ConversationManagerDep = Annotated[ConversationManager, Depends(get_conversation_manager)]
