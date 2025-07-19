"""
Statute ingestion service for Polish civil law (KC/KPC) following the refactored architecture.
"""
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

from ..core.service_interface import ServiceInterface, HealthCheckResult, ServiceStatus
from ..core.database_manager import DatabaseManager
from ..core.config_service import get_config
from ..core.tool_registry import tool_registry, ToolCategory, ToolParameter
from ..core.logger_manager import get_logger
from ..models import StatuteChunk


logger = get_logger(__name__)


class StatuteIngestionService(ServiceInterface):
    """
    Service for ingesting Polish civil law statutes (KC/KPC) into the system.
    Follows the refactored architecture with proper dependency injection.
    """
    
    def __init__(self, db_manager: DatabaseManager):
        super().__init__("StatuteIngestionService")
        self._db_manager = db_manager
        self._config = get_config()
        self._embedding_service: Optional['EmbeddingService'] = None
        
    async def _initialize_impl(self) -> None:
        """Initialize the statute ingestion service"""
        # Embedding service will be injected or imported when available
        try:
            from .embedding_service import EmbeddingService
            self._embedding_service = EmbeddingService(self._db_manager)
            await self._embedding_service.initialize()
        except ImportError:
            logger.warning("EmbeddingService not available, will use basic processing")
        
        # Ensure data directories exist
        self._ensure_directories()
        
        logger.info("StatuteIngestionService initialized successfully")
    
    async def _shutdown_impl(self) -> None:
        """Shutdown the service gracefully"""
        if self._embedding_service:
            await self._embedding_service.shutdown()
        logger.info("StatuteIngestionService shutdown completed")
    
    async def _health_check_impl(self) -> HealthCheckResult:
        """Check service health"""
        try:
            # Check database connectivity
            async with self._db_manager.get_session() as session:
                from sqlalchemy import text
                # Simple query to test connection
                await session.execute(text("SELECT 1"))
            
            # Check embedding service if available
            embedding_status = "available"
            if self._embedding_service:
                embedding_health = await self._embedding_service.health_check()
                if embedding_health.status != ServiceStatus.HEALTHY:
                    embedding_status = "unhealthy"
            else:
                embedding_status = "unavailable"
            
            # Check data directories
            chunks_dir = self._config.storage.get_path(self._config.storage.chunks_dir)
            pdfs_dir = self._config.storage.get_path(self._config.storage.pdfs_dir)
            
            return HealthCheckResult(
                status=ServiceStatus.HEALTHY,
                message="Statute ingestion service is healthy",
                details={
                    "database": "connected",
                    "embedding_service": embedding_status,
                    "chunks_directory": str(chunks_dir),
                    "pdfs_directory": str(pdfs_dir),
                    "directories_exist": chunks_dir.exists() and pdfs_dir.exists()
                }
            )
        except Exception as e:
            return HealthCheckResult(
                status=ServiceStatus.UNHEALTHY,
                message=f"Health check failed: {str(e)}"
            )
    
    def _ensure_directories(self) -> None:
        """Ensure required directories exist"""
        directories = [
            self._config.storage.chunks_dir,
            self._config.storage.pdfs_dir,
            "statutes"  # subdirectory for statute PDFs
        ]
        
        for directory in directories:
            path = self._config.storage.get_path(directory)
            if directory == "statutes":
                path = self._config.storage.get_path(self._config.storage.pdfs_dir) / "statutes"
                path.mkdir(parents=True, exist_ok=True)
    
    @tool_registry.register(
        name="ingest_statute_pdf",
        description="Ingest a statute PDF (KC or KPC) into the system",
        category=ToolCategory.DOCUMENT,
        parameters=[
            ToolParameter("pdf_path", "string", "Path to the PDF file to ingest"),
            ToolParameter("code_type", "string", "Type of code (KC or KPC)", enum=["KC", "KPC"]),
            ToolParameter("force_update", "boolean", "Force update even if already exists", False, False)
        ],
        returns="Dictionary with ingestion statistics and results"
    )
    async def ingest_statute_pdf(self, pdf_path: str, code_type: str, force_update: bool = False) -> Dict[str, Any]:
        """
        Ingest a statute PDF file into the system.
        
        Args:
            pdf_path: Path to the PDF file
            code_type: Type of code (KC or KPC)
            force_update: Whether to force update if already exists
            
        Returns:
            Dictionary with ingestion statistics
        """
        if not self._initialized:
            raise RuntimeError("Service not initialized")
        
        logger.info(f"Starting ingestion of {code_type} from {pdf_path}")
        
        pdf_file = Path(pdf_path)
        if not pdf_file.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
        start_time = datetime.now()
        
        try:
            # Check if already ingested (unless force_update)
            if not force_update:
                existing_count = await self._check_existing_chunks(code_type)
                if existing_count > 0:
                    logger.info(f"Code {code_type} already has {existing_count} chunks, skipping (use force_update=True to override)")
                    return {
                        "status": "skipped",
                        "reason": "already_exists",
                        "existing_chunks": existing_count,
                        "code_type": code_type
                    }
            
            # Process PDF into chunks
            logger.info(f"Processing PDF for {code_type}")
            chunks = await self._process_pdf_to_chunks(pdf_path, code_type)
            
            # Save chunks to database
            logger.info(f"Saving {len(chunks)} chunks to database")
            await self._save_chunks_to_db(chunks, code_type)
            
            # Generate embeddings if embedding service is available
            embeddings_generated = 0
            if self._embedding_service:
                logger.info("Generating embeddings for chunks")
                embeddings_generated = await self._embedding_service.generate_statute_embeddings(chunks, code_type)
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            # Return statistics
            stats = {
                "status": "success",
                "code_type": code_type,
                "pdf_path": str(pdf_path),
                "chunks_processed": len(chunks),
                "embeddings_generated": embeddings_generated,
                "processing_time_seconds": duration,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat()
            }
            
            logger.info(f"Successfully ingested {code_type}: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"Error ingesting {code_type} from {pdf_path}: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "code_type": code_type,
                "pdf_path": str(pdf_path)
            }
    
    async def _check_existing_chunks(self, code_type: str) -> int:
        """Check if chunks already exist for a code type"""
        async with self._db_manager.get_session() as session:
            from sqlalchemy import select, func
            
            query = select(func.count(StatuteChunk.id)).where(StatuteChunk.code == code_type)
            result = await session.execute(query)
            return result.scalar() or 0
    
    async def _process_pdf_to_chunks(self, pdf_path: str, code_type: str) -> List[Dict[str, Any]]:
        """
        Process PDF file into chunks using the existing pdf2chunks logic.
        This is a placeholder - the actual implementation would import and adapt
        the existing pdf2chunks.process_statute_pdf function.
        """
        # Import the existing PDF processing logic
        from ...ingest.pdf2chunks import process_statute_pdf
        
        # Run the synchronous PDF processing in a thread pool
        loop = asyncio.get_event_loop()
        chunks, stats = await loop.run_in_executor(
            None, 
            process_statute_pdf, 
            pdf_path, 
            code_type, 
            str(self._config.storage.get_path(self._config.storage.chunks_dir))
        )
        
        return chunks
    
    async def _save_chunks_to_db(self, chunks: List[Dict[str, Any]], code_type: str) -> None:
        """Save chunks to PostgreSQL database using DatabaseManager"""
        async with self._db_manager.transaction() as session:
            # Clear existing chunks for this code type if doing an update
            from sqlalchemy import delete
            delete_query = delete(StatuteChunk).where(StatuteChunk.code == code_type)
            await session.execute(delete_query)
            
            # Insert new chunks
            for chunk in chunks:
                metadata = chunk.get("metadata", {})
                
                db_chunk = StatuteChunk(
                    code=code_type,
                    article=metadata.get("article", ""),
                    paragraph=metadata.get("paragraph"),
                    text=chunk["text"],
                    embedding_id=chunk.get("chunk_id"),
                    metadata=metadata
                )
                
                session.add(db_chunk)
            
            await session.commit()
            logger.info(f"Saved {len(chunks)} chunks to database for {code_type}")
    
    @tool_registry.register(
        name="list_statute_sources",
        description="List available statute sources for download",
        category=ToolCategory.UTILITY,
        parameters=[],
        returns="Dictionary of available statute sources with URLs"
    )
    async def list_statute_sources(self) -> Dict[str, Any]:
        """List available statute sources for download"""
        # This would be expanded to include actual official sources
        sources = {
            "KC": {
                "name": "Kodeks Cywilny",
                "url": "https://isap.sejm.gov.pl/isap.nsf/download.xsp/WDU19640160093/U/D19640093Lj.pdf",
                "filename": "kodeks_cywilny.pdf",
                "description": "Polish Civil Code"
            },
            "KPC": {
                "name": "Kodeks Postępowania Cywilnego",
                "url": "https://isap.sejm.gov.pl/isap.nsf/download.xsp/WDU19640430296/U/D19640296Lj.pdf",
                "filename": "kodeks_postepowania_cywilnego.pdf",
                "description": "Polish Civil Procedure Code"
            }
        }
        
        return {
            "sources": sources,
            "download_directory": str(self._config.storage.get_path(self._config.storage.pdfs_dir) / "statutes"),
            "status": "available"
        }
    
    @tool_registry.register(
        name="get_ingestion_status",
        description="Get current ingestion status for all statute types",
        category=ToolCategory.UTILITY,
        parameters=[],
        returns="Dictionary with ingestion status for each statute type"
    )
    async def get_ingestion_status(self) -> Dict[str, Any]:
        """Get current ingestion status for all statute types"""
        if not self._initialized:
            raise RuntimeError("Service not initialized")
        
        status = {}
        for code_type in ["KC", "KPC"]:
            chunk_count = await self._check_existing_chunks(code_type)
            status[code_type] = {
                "chunks_count": chunk_count,
                "status": "ingested" if chunk_count > 0 else "not_ingested",
                "last_updated": None  # Could be enhanced to track actual update times
            }
        
        return {
            "statute_status": status,
            "service_status": "healthy" if self._initialized else "not_initialized"
        }
    
    async def run_full_ingestion_pipeline(self, force_update: bool = False) -> Dict[str, Any]:
        """
        Run the complete ingestion pipeline for all available statutes.
        This is an internal method, not exposed as a tool.
        """
        if not self._initialized:
            raise RuntimeError("Service not initialized")
        
        start_time = datetime.now()
        results = {
            "start_time": start_time.isoformat(),
            "statutes": {}
        }
        
        # Get available sources
        sources = await self.list_statute_sources()
        
        # Process each statute
        for code_type, source_info in sources["sources"].items():
            logger.info(f"Processing {code_type}")
            
            # Check if PDF exists
            pdf_path = Path(sources["download_directory"]) / source_info["filename"]
            
            if not pdf_path.exists():
                logger.warning(f"PDF not found for {code_type} at {pdf_path}")
                results["statutes"][code_type] = {
                    "status": "error",
                    "error": f"PDF not found at {pdf_path}"
                }
                continue
            
            # Ingest the statute
            try:
                ingest_result = await self.ingest_statute_pdf(
                    str(pdf_path), 
                    code_type, 
                    force_update
                )
                results["statutes"][code_type] = ingest_result
                
            except Exception as e:
                logger.error(f"Error processing {code_type}: {e}")
                results["statutes"][code_type] = {
                    "status": "error",
                    "error": str(e)
                }
        
        end_time = datetime.now()
        results["end_time"] = end_time.isoformat()
        results["total_duration"] = str(end_time - start_time)
        
        return results
