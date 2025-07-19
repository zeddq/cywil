"""
Database optimization scripts and indexes for improved performance.
"""
from sqlalchemy import text, Index
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from .database_manager import DatabaseManager
from .logging_utils import get_logger


logger = get_logger(__name__)


class DatabaseOptimizer:
    """
    Manages database optimizations including indexes and query improvements.
    """
    
    def __init__(self, db_manager: DatabaseManager):
        self._db_manager = db_manager
        
    async def create_indexes(self) -> None:
        """Create performance indexes on database tables"""
        async with self._db_manager.get_session() as session:
            try:
                # Response History indexes
                await self._create_index(
                    session,
                    "idx_response_history_thread_created",
                    "response_history",
                    ["thread_id", "created_at DESC"]
                )
                
                await self._create_index(
                    session,
                    "idx_response_history_response_id",
                    "response_history",
                    ["response_id"]
                )
                
                # Cases indexes
                await self._create_index(
                    session,
                    "idx_cases_reference_number",
                    "cases",
                    ["reference_number"]
                )
                
                await self._create_index(
                    session,
                    "idx_cases_status_updated",
                    "cases",
                    ["status", "updated_at DESC"]
                )
                
                await self._create_index(
                    session,
                    "idx_cases_client_name",
                    "cases",
                    ["client_name"]
                )
                
                # Templates indexes
                await self._create_index(
                    session,
                    "idx_templates_category_usage",
                    "templates",
                    ["category", "usage_count DESC"]
                )
                
                await self._create_index(
                    session,
                    "idx_templates_name",
                    "templates",
                    ["name"],
                    unique=True
                )
                
                # Deadlines indexes
                await self._create_index(
                    session,
                    "idx_deadlines_case_due",
                    "deadlines",
                    ["case_id", "due_date"]
                )
                
                await self._create_index(
                    session,
                    "idx_deadlines_status_due",
                    "deadlines",
                    ["status", "due_date"]
                )
                
                # Partial index for active deadlines
                await session.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_deadlines_active_due
                    ON deadlines (due_date)
                    WHERE status IN ('pending', 'overdue')
                """))
                
                await session.commit()
                logger.info("Database indexes created successfully")
                
            except Exception as e:
                logger.error(f"Error creating indexes: {e}")
                await session.rollback()
                raise
    
    async def _create_index(self, session: AsyncSession, name: str, 
                           table: str, columns: list, unique: bool = False) -> None:
        """Create a single index"""
        columns_str = ", ".join(columns)
        unique_str = "UNIQUE" if unique else ""
        
        query = f"""
        CREATE {unique_str} INDEX IF NOT EXISTS {name}
        ON {table} ({columns_str})
        """
        
        await session.execute(text(query))
        logger.debug(f"Created index {name} on {table}")
    
    async def analyze_tables(self) -> None:
        """Run ANALYZE on tables to update statistics"""
        async with self._db_manager.get_session() as session:
            tables = ["response_history", "cases", "templates", "deadlines"]
            
            for table in tables:
                await session.execute(text(f"ANALYZE {table}"))
                logger.debug(f"Analyzed table {table}")
            
            await session.commit()
            logger.info("Database statistics updated")
    
    async def get_slow_queries(self) -> list:
        """Get slow queries from PostgreSQL"""
        async with self._db_manager.get_session() as session:
            # Query for slow queries (> 1 second)
            result = await session.execute(text("""
                SELECT 
                    query,
                    calls,
                    mean_exec_time,
                    total_exec_time,
                    stddev_exec_time
                FROM pg_stat_statements
                WHERE mean_exec_time > 1000  -- milliseconds
                ORDER BY mean_exec_time DESC
                LIMIT 20
            """))
            
            slow_queries = []
            for row in result:
                slow_queries.append({
                    "query": row.query[:200],  # Truncate long queries
                    "calls": row.calls,
                    "mean_time_ms": row.mean_exec_time,
                    "total_time_ms": row.total_exec_time,
                    "stddev_time_ms": row.stddev_exec_time
                })
            
            return slow_queries
    
    async def get_index_usage(self) -> list:
        """Get index usage statistics"""
        async with self._db_manager.get_session() as session:
            result = await session.execute(text("""
                SELECT 
                    schemaname,
                    tablename,
                    indexname,
                    idx_scan,
                    idx_tup_read,
                    idx_tup_fetch
                FROM pg_stat_user_indexes
                ORDER BY idx_scan DESC
            """))
            
            index_stats = []
            for row in result:
                index_stats.append({
                    "schema": row.schemaname,
                    "table": row.tablename,
                    "index": row.indexname,
                    "scans": row.idx_scan,
                    "tuples_read": row.idx_tup_read,
                    "tuples_fetched": row.idx_tup_fetch
                })
            
            return index_stats
    
    async def optimize_connection_pool(self) -> Dict[str, Any]:
        """Get connection pool recommendations"""
        async with self._db_manager.get_session() as session:
            # Get current connection stats
            result = await session.execute(text("""
                SELECT 
                    count(*) as total_connections,
                    count(*) FILTER (WHERE state = 'active') as active_connections,
                    count(*) FILTER (WHERE state = 'idle') as idle_connections,
                    count(*) FILTER (WHERE state = 'idle in transaction') as idle_in_transaction
                FROM pg_stat_activity
                WHERE datname = current_database()
            """))
            
            stats = result.first()
            
            # Get database settings
            settings_result = await session.execute(text("""
                SELECT name, setting 
                FROM pg_settings 
                WHERE name IN ('max_connections', 'shared_buffers', 'effective_cache_size')
            """))
            
            settings = {row.name: row.setting for row in settings_result}
            
            return {
                "current_connections": {
                    "total": stats.total_connections,
                    "active": stats.active_connections,
                    "idle": stats.idle_connections,
                    "idle_in_transaction": stats.idle_in_transaction
                },
                "database_settings": settings,
                "recommendations": {
                    "pool_min": max(5, stats.active_connections),
                    "pool_max": min(20, int(settings.get("max_connections", "100")) // 5),
                    "pool_timeout": 30,
                    "pool_recycle": 3600
                }
            }


# Optimized query templates
class OptimizedQueries:
    """Collection of optimized query templates"""
    
    @staticmethod
    def get_case_with_deadlines() -> str:
        """Optimized query to get case with all deadlines"""
        return """
        SELECT 
            c.*,
            array_agg(
                json_build_object(
                    'id', d.id,
                    'description', d.description,
                    'due_date', d.due_date,
                    'status', d.status
                ) ORDER BY d.due_date
            ) FILTER (WHERE d.id IS NOT NULL) as deadlines
        FROM cases c
        LEFT JOIN deadlines d ON c.id = d.case_id
        WHERE c.id = :case_id
        GROUP BY c.id
        """
    
    @staticmethod
    def get_recent_responses() -> str:
        """Optimized query for recent responses with pagination"""
        return """
        SELECT 
            response_id,
            thread_id,
            created_at,
            input,
            output
        FROM response_history
        WHERE thread_id = :thread_id
        ORDER BY created_at DESC
        LIMIT :limit
        OFFSET :offset
        """
    
    @staticmethod
    def search_cases_optimized() -> str:
        """Optimized case search with full-text search"""
        return """
        SELECT 
            id,
            reference_number,
            title,
            client_name,
            status,
            updated_at,
            ts_rank(
                to_tsvector('polish', coalesce(title, '') || ' ' || coalesce(description, '')),
                plainto_tsquery('polish', :search_term)
            ) as relevance
        FROM cases
        WHERE 
            to_tsvector('polish', coalesce(title, '') || ' ' || coalesce(description, ''))
            @@ plainto_tsquery('polish', :search_term)
            OR reference_number ILIKE :search_pattern
            OR client_name ILIKE :search_pattern
        ORDER BY relevance DESC, updated_at DESC
        LIMIT :limit
        """


async def setup_database_optimizations(db_manager: DatabaseManager) -> None:
    """
    Setup all database optimizations.
    Should be called during application startup.
    """
    optimizer = DatabaseOptimizer(db_manager)
    
    try:
        # Create indexes
        await optimizer.create_indexes()
        
        # Update statistics
        await optimizer.analyze_tables()
        
        logger.info("Database optimizations completed successfully")
        
    except Exception as e:
        logger.error(f"Failed to setup database optimizations: {e}")
        # Don't fail startup, optimizations are not critical
        pass
