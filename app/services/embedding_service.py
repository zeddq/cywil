"""
Centralized embedding service for Polish legal text following the refactored architecture.
"""
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import hashlib
import numpy as np
from contextlib import asynccontextmanager

from sentence_transformers import SentenceTransformer
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue,
    CreateCollection, OptimizersConfigDiff
)

from ..core.service_interface import ServiceInterface, HealthCheckResult, ServiceStatus
from ..core.database_manager import DatabaseManager
from ..core.config_service import get_config
from ..core.tool_registry import tool_registry, ToolCategory, ToolParameter
from ..core.logger_manager import get_logger


logger = get_logger(__name__)


class EmbeddingService(ServiceInterface):
    """
    Centralized service for generating and managing embeddings for Polish legal text.
    Handles both statute and ruling embeddings with proper resource management.
    """
    
    def __init__(self, db_manager: DatabaseManager):
        super().__init__("EmbeddingService")
        self._db_manager = db_manager
        self._config = get_config()
        self._embedding_model: Optional[SentenceTransformer] = None
        self._qdrant_client: Optional[AsyncQdrantClient] = None
        self._embedding_dim: Optional[int] = None
        
    async def _initialize_impl(self) -> None:
        """Initialize the embedding service"""
        # Initialize embedding model
        logger.info("Loading SentenceTransformer model for Polish legal text")
        loop = asyncio.get_event_loop()
        self._embedding_model = await loop.run_in_executor(
            None, 
            lambda: SentenceTransformer('paraphrase-multilingual-mpnet-base-v2')
        )
        self._embedding_dim = self._embedding_model.get_sentence_embedding_dimension()
        
        # Initialize Qdrant client
        self._qdrant_client = AsyncQdrantClient(
            host=self._config.qdrant.host,
            port=self._config.qdrant.port,
            timeout=self._config.qdrant.timeout,
            api_key=self._config.qdrant.api_key.get_secret_value() if self._config.qdrant.api_key else None,
            https=False
        )
        
        # Ensure collections exist
        await self._ensure_collections()
        
        logger.info(f"EmbeddingService initialized with embedding dimension: {self._embedding_dim}")
    
    async def _shutdown_impl(self) -> None:
        """Shutdown the service gracefully"""
        if self._qdrant_client:
            await self._qdrant_client.close()
        logger.info("EmbeddingService shutdown completed")
    
    async def _health_check_impl(self) -> HealthCheckResult:
        """Check service health"""
        try:
            # Check embedding model
            if not self._embedding_model:
                return HealthCheckResult(
                    status=ServiceStatus.UNHEALTHY,
                    message="Embedding model not initialized"
                )
            
            # Test embedding generation
            test_embedding = await self._generate_embeddings_async(["test text"])
            
            # Check Qdrant connection
            collections = await self._qdrant_client.get_collections()
            
            # Check database connectivity
            async with self._db_manager.get_session() as session:
                from sqlalchemy import text
                await session.execute(text("SELECT 1"))
            
            return HealthCheckResult(
                status=ServiceStatus.HEALTHY,
                message="Embedding service is healthy",
                details={
                    "embedding_model": "loaded",
                    "embedding_dimension": self._embedding_dim,
                    "qdrant_collections": len(collections.collections),
                    "database": "connected",
                    "test_embedding_shape": len(test_embedding[0]) if test_embedding.any() else 0
                }
            )
        except Exception as e:
            return HealthCheckResult(
                status=ServiceStatus.UNHEALTHY,
                message=f"Health check failed: {str(e)}"
            )
    
    async def _ensure_collections(self) -> None:
        """Ensure required Qdrant collections exist"""
        collections_to_create = [
            (self._config.qdrant.collection_statutes, "Statute embeddings"),
            (self._config.qdrant.collection_rulings, "Supreme Court ruling embeddings")
        ]
        
        existing_collections = await self._qdrant_client.get_collections()
        existing_names = {c.name for c in existing_collections.collections}
        
        for collection_name, description in collections_to_create:
            if collection_name not in existing_names:
                await self._create_collection(collection_name, description)
    
    async def _create_collection(self, collection_name: str, description: str) -> None:
        """Create a Qdrant collection with proper configuration"""
        try:
            await self._qdrant_client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=self._embedding_dim,
                    distance=Distance.COSINE
                ),
                optimizers_config=OptimizersConfigDiff(
                    indexing_threshold=20000,
                    memmap_threshold=50000
                )
            )
            
            # Create payload indexes for efficient filtering
            await self._create_payload_indexes(collection_name)
            
            logger.info(f"Created Qdrant collection '{collection_name}': {description}")
            
        except Exception as e:
            logger.error(f"Error creating collection '{collection_name}': {e}")
            raise
    
    async def _create_payload_indexes(self, collection_name: str) -> None:
        """Create payload indexes for efficient filtering"""
        indexes = [
            ("code", "keyword"),
            ("article", "keyword"),
            ("status", "keyword"),
            ("text", "text")
        ]
        
        for field_name, field_schema in indexes:
            try:
                await self._qdrant_client.create_payload_index(
                    collection_name=collection_name,
                    field_name=field_name,
                    field_schema=field_schema
                )
                logger.debug(f"Created index for field '{field_name}' in collection '{collection_name}'")
            except Exception as e:
                logger.warning(f"Failed to create index for field '{field_name}': {e}")
    
    async def _generate_embeddings_async(self, texts: List[str], batch_size: int = 32) -> np.ndarray:
        """Generate embeddings asynchronously"""
        if not self._embedding_model:
            raise RuntimeError("Embedding model not initialized")
        
        loop = asyncio.get_event_loop()
        
        # Run embedding generation in thread pool to avoid blocking
        embeddings = await loop.run_in_executor(
            None,
            lambda: self._embedding_model.encode(
                texts,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=len(texts) > 100,
                batch_size=batch_size
            )
        )
        
        return embeddings
    
    def _prepare_statute_texts(self, chunks: List[Dict[str, Any]]) -> List[str]:
        """Prepare statute texts for embedding with legal context"""
        prepared_texts = []
        
        for chunk in chunks:
            text_parts = []
            
            # Add article reference
            metadata = chunk.get("metadata", {})
            article = metadata.get("article", "")
            code = metadata.get("code", "")
            
            if article and code:
                text_parts.append(f"Art. {article} {code}")
            
            # Add title if present
            if metadata.get("title"):
                text_parts.append(f"[{metadata['title']}]")
            
            # Add section/chapter context
            if metadata.get("section"):
                text_parts.append(f"({metadata['section']})")
            
            # Add main content
            text_parts.append(chunk["text"])
            
            # Combine with proper spacing
            prepared_text = " ".join(text_parts)
            prepared_texts.append(prepared_text)
        
        return prepared_texts
    
    @tool_registry.register(
        name="generate_statute_embeddings",
        description="Generate embeddings for statute chunks and store in Qdrant",
        category=ToolCategory.DOCUMENT,
        parameters=[
            ToolParameter("chunks", "array", "List of statute chunks to process", True),
            ToolParameter("code_type", "string", "Type of code (KC or KPC)", enum=["KC", "KPC"]),
            ToolParameter("force_regenerate", "boolean", "Force regeneration even if embeddings exist", False, False),
            ToolParameter("batch_size", "integer", "Batch size for processing", False, 32)
        ],
        returns="Dictionary with embedding generation statistics"
    )
    async def generate_statute_embeddings(self, chunks: List[Dict[str, Any]], code_type: str, force_regenerate: bool = False, batch_size: int = 32) -> int:
        """
        Generate embeddings for statute chunks and store in Qdrant.
        
        Args:
            chunks: List of statute chunks to process
            code_type: Type of code (KC or KPC)
            force_regenerate: Whether to force regeneration
            batch_size: Batch size for processing
            
        Returns:
            Number of embeddings generated
        """
        if not self._initialized:
            raise RuntimeError("Service not initialized")
        
        logger.info(f"Generating embeddings for {len(chunks)} {code_type} chunks")
        
        # Check if embeddings already exist
        if not force_regenerate:
            existing_count = await self._count_existing_embeddings(
                self._config.qdrant.collection_statutes, 
                code_type
            )
            if existing_count > 0:
                logger.info(f"Found {existing_count} existing embeddings for {code_type}, skipping generation")
                return 0
        
        # Clear existing embeddings if force regenerating
        if force_regenerate:
            await self._clear_embeddings(self._config.qdrant.collection_statutes, code_type)
        
        # Prepare texts for embedding
        prepared_texts = self._prepare_statute_texts(chunks)
        
        # Generate embeddings
        embeddings = await self._generate_embeddings_async(prepared_texts, batch_size)
        
        # Upload to Qdrant
        await self._upload_to_qdrant(
            chunks, 
            embeddings, 
            self._config.qdrant.collection_statutes,
            batch_size
        )
        
        logger.info(f"Generated and stored {len(embeddings)} embeddings for {code_type}")
        return len(embeddings)
    
    @tool_registry.register(
        name="generate_ruling_embeddings",
        description="Generate embeddings for Supreme Court ruling records",
        category=ToolCategory.DOCUMENT,
        parameters=[
            ToolParameter("jsonl_file", "string", "Path to JSONL file containing ruling records"),
            ToolParameter("batch_size", "integer", "Batch size for processing", False, 32)
        ],
        returns="Dictionary with embedding generation statistics"
    )
    async def generate_ruling_embeddings(self, jsonl_file: str, batch_size: int = 32) -> Dict[str, Any]:
        """
        Generate embeddings for Supreme Court ruling records.
        
        Args:
            jsonl_file: Path to JSONL file containing records
            batch_size: Batch size for processing
            
        Returns:
            Dictionary with generation statistics
        """
        if not self._initialized:
            raise RuntimeError("Service not initialized")
        
        jsonl_path = Path(jsonl_file)
        if not jsonl_path.exists():
            raise FileNotFoundError(f"JSONL file not found: {jsonl_file}")
        
        logger.info(f"Generating embeddings for rulings from {jsonl_file}")
        
        # Load records from JSONL
        records = []
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    records.append(json.loads(line))
        
        if not records:
            return {"status": "no_records", "message": "No records found in JSONL file"}
        
        # Prepare texts for embedding
        texts = [record["text"] for record in records]
        
        # Generate embeddings
        embeddings = await self._generate_embeddings_async(texts, batch_size)
        
        # Upload to Qdrant
        await self._upload_rulings_to_qdrant(records, embeddings, batch_size)
        
        result = {
            "status": "success",
            "jsonl_file": str(jsonl_file),
            "records_processed": len(records),
            "embeddings_generated": len(embeddings),
            "collection": self._config.qdrant.collection_rulings
        }
        
        logger.info(f"Generated embeddings for {len(records)} ruling records")
        return result
    
    async def _count_existing_embeddings(self, collection_name: str, code_type: str) -> int:
        """Count existing embeddings for a specific code type"""
        try:
            filter_condition = Filter(
                must=[FieldCondition(key="code", match=MatchValue(value=code_type))]
            )
            
            result = await self._qdrant_client.scroll(
                collection_name=collection_name,
                scroll_filter=filter_condition,
                limit=1,
                with_payload=False
            )
            
            info = await self._qdrant_client.get_collection(collection_name)
            return info.points_count
            
        except Exception as e:
            logger.error(f"Error counting existing embeddings: {e}")
            return 0
    
    async def _clear_embeddings(self, collection_name: str, code_type: str) -> None:
        """Clear existing embeddings for a specific code type"""
        try:
            filter_condition = Filter(
                must=[FieldCondition(key="code", match=MatchValue(value=code_type))]
            )
            
            await self._qdrant_client.delete(
                collection_name=collection_name,
                points_selector=filter_condition
            )
            
            logger.info(f"Cleared existing embeddings for {code_type} from {collection_name}")
            
        except Exception as e:
            logger.error(f"Error clearing embeddings: {e}")
            raise
    
    async def _upload_to_qdrant(self, chunks: List[Dict[str, Any]], embeddings: np.ndarray, 
                               collection_name: str, batch_size: int = 100) -> None:
        """Upload embeddings and metadata to Qdrant"""
        points = []
        
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            # Generate unique ID
            chunk_id = chunk.get("chunk_id", f"chunk_{i}")
            point_id = int(hashlib.md5(chunk_id.encode()).hexdigest()[:8], base=16)
            
            # Prepare payload
            payload = {
                "chunk_id": chunk_id,
                "text": chunk["text"],
                **chunk.get("metadata", {})
            }
            
            # Create point
            point = PointStruct(
                id=point_id,
                vector=embedding.tolist(),
                payload=payload
            )
            points.append(point)
            
            # Upload in batches
            if len(points) >= batch_size:
                await self._qdrant_client.upsert(
                    collection_name=collection_name,
                    points=points
                )
                logger.debug(f"Uploaded batch of {len(points)} points to {collection_name}")
                points = []
        
        # Upload remaining points
        if points:
            await self._qdrant_client.upsert(
                collection_name=collection_name,
                points=points
            )
            logger.debug(f"Uploaded final batch of {len(points)} points to {collection_name}")
    
    async def _upload_rulings_to_qdrant(self, records: List[Dict[str, Any]], 
                                       embeddings: np.ndarray, batch_size: int = 100) -> None:
        """Upload ruling embeddings to Qdrant"""
        points = []
        
        for i, (record, embedding) in enumerate(zip(records, embeddings)):
            # Generate unique ID
            record_id = f"ruling_{i}_{record.get('source_file', 'unknown')}"
            point_id = int(hashlib.md5(record_id.encode()).hexdigest()[:8], base=16)
            
            # Prepare payload
            payload = {
                "record_id": record_id,
                "text": record["text"],
                "source_file": record.get("source_file", ""),
                "section": record.get("section", ""),
                "para_no": record.get("para_no", 0),
                "entities": record.get("entities", [])
            }
            
            # Create point
            point = PointStruct(
                id=point_id,
                vector=embedding.tolist(),
                payload=payload
            )
            points.append(point)
            
            # Upload in batches
            if len(points) >= batch_size:
                await self._qdrant_client.upsert(
                    collection_name=self._config.qdrant.collection_rulings,
                    points=points
                )
                logger.debug(f"Uploaded batch of {len(points)} ruling points")
                points = []
        
        # Upload remaining points
        if points:
            await self._qdrant_client.upsert(
                collection_name=self._config.qdrant.collection_rulings,
                points=points
            )
            logger.debug(f"Uploaded final batch of {len(points)} ruling points")
    
    @tool_registry.register(
        name="get_embedding_statistics",
        description="Get statistics about stored embeddings",
        category=ToolCategory.UTILITY,
        parameters=[
            ToolParameter("collection_name", "string", "Collection name to check", False, None, 
                         ["statutes", "sn_rulings"])
        ],
        returns="Dictionary with embedding statistics"
    )
    async def get_embedding_statistics(self, collection_name: Optional[str] = None) -> Dict[str, Any]:
        """Get statistics about stored embeddings"""
        if not self._initialized:
            raise RuntimeError("Service not initialized")
        
        collections_to_check = []
        if collection_name:
            if collection_name == "statutes":
                collections_to_check = [self._config.qdrant.collection_statutes]
            elif collection_name == "sn_rulings":
                collections_to_check = [self._config.qdrant.collection_rulings]
            else:
                collections_to_check = [collection_name]
        else:
            collections_to_check = [
                self._config.qdrant.collection_statutes,
                self._config.qdrant.collection_rulings
            ]
        
        statistics = {}
        
        for coll_name in collections_to_check:
            try:
                info = await self._qdrant_client.get_collection(coll_name)
                statistics[coll_name] = {
                    "points_count": info.points_count,
                    "indexed_points_count": info.indexed_points_count,
                    "vectors_count": info.vectors_count,
                    "status": info.status.value if info.status else "unknown"
                }
            except Exception as e:
                statistics[coll_name] = {
                    "error": str(e),
                    "status": "error"
                }
        
        return {
            "service_status": "healthy" if self._initialized else "not_initialized",
            "embedding_dimension": self._embedding_dim,
            "collections": statistics
        }
