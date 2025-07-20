"""
Supreme Court ruling ingestion service following the refactored architecture.
"""
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from concurrent.futures import ThreadPoolExecutor
import uuid

from ..core.service_interface import ServiceInterface, HealthCheckResult, ServiceStatus
from ..core.database_manager import DatabaseManager
from ..core.config_service import get_config
from ..core.tool_registry import tool_registry, ToolCategory, ToolParameter
from ..core.logger_manager import get_logger


logger = get_logger(__name__)


class SupremeCourtIngestService(ServiceInterface):
    """
    Service for ingesting Polish Supreme Court rulings following the refactored architecture.
    Modernizes the o3-based processing pipeline with proper dependency injection.
    """
    
    def __init__(self, db_manager: DatabaseManager):
        super().__init__("SupremeCourtIngestService")
        self._db_manager = db_manager
        self._config = get_config()
        self._thread_pool = ThreadPoolExecutor(max_workers=4)
        
    async def _initialize_impl(self) -> None:
        """Initialize the Supreme Court ingestion service"""
        # Ensure data directories exist
        self._ensure_directories()
        
        # Test OpenAI API key
        try:
            from openai import OpenAI
            self._openai_client = OpenAI(api_key=self._config.openai.api_key.get_secret_value())
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}")
            raise
        
        logger.info("SupremeCourtIngestService initialized successfully")
    
    async def _shutdown_impl(self) -> None:
        """Shutdown the service gracefully"""
        if hasattr(self, '_thread_pool'):
            self._thread_pool.shutdown(wait=True)
        logger.info("SupremeCourtIngestService shutdown completed")
    
    async def _health_check_impl(self) -> HealthCheckResult:
        """Check service health"""
        try:
            # Check database connectivity
            async with self._db_manager.get_session() as session:
                from sqlalchemy import text
                await session.execute(text("SELECT 1"))
            
            # Check OpenAI API
            openai_status = "available"
            try:
                # Simple test to check if API key is valid
                models = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self._openai_client.models.list()
                )
                openai_status = "connected"
            except Exception as e:
                openai_status = f"error: {str(e)}"
            
            # Check data directories
            jsonl_dir = self._config.storage.get_path(self._config.storage.jsonl_dir)
            pdfs_dir = self._config.storage.get_path(self._config.storage.pdfs_dir)
            
            return HealthCheckResult(
                status=ServiceStatus.HEALTHY,
                message="Supreme Court ingest service is healthy",
                details={
                    "database": "connected",
                    "openai_api": openai_status,
                    "jsonl_directory": str(jsonl_dir),
                    "pdfs_directory": str(pdfs_dir),
                    "directories_exist": jsonl_dir.exists() and pdfs_dir.exists()
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
            self._config.storage.jsonl_dir,
            self._config.storage.pdfs_dir,
            "sn-rulings"  # subdirectory for SN ruling PDFs
        ]
        
        for directory in directories:
            if directory == "sn-rulings":
                path = self._config.storage.get_path(self._config.storage.pdfs_dir) / "sn-rulings"
                path.mkdir(parents=True, exist_ok=True)
            else:
                self._config.storage.get_path(directory)
    
    @tool_registry.register(
        name="process_sn_ruling",
        description="Process a single Supreme Court ruling PDF using o3 model",
        category=ToolCategory.VECTOR_DB,
        parameters=[
            ToolParameter("pdf_path", "string", "Path to the PDF file to process"),
            ToolParameter("use_batch", "boolean", "Whether to use batch processing for efficiency", False, False)
        ],
        returns="Dictionary with processing results and extracted ruling data"
    )
    async def process_sn_ruling(self, pdf_path: str, use_batch: bool = False) -> Dict[str, Any]:
        """
        Process a single Supreme Court ruling PDF using o3 model.
        
        Args:
            pdf_path: Path to the PDF file
            use_batch: Whether to use batch processing
            
        Returns:
            Dictionary with processing results
        """
        if not self._initialized:
            raise RuntimeError("Service not initialized")
        
        logger.info(f"Processing SN ruling: {pdf_path}")
        
        pdf_file = Path(pdf_path)
        if not pdf_file.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
        start_time = datetime.now()
        
        try:
            # Process the PDF using the existing o3 pipeline
            if use_batch:
                result = await self._process_with_batch([pdf_file])
                records = result.get("records", [])
            else:
                records = await self._process_single_pdf(pdf_file)
            
            # Save to JSONL output
            output_path = await self._save_ruling_to_jsonl(records, pdf_file.stem)
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            return {
                "status": "success",
                "pdf_path": str(pdf_path),
                "records_extracted": len(records),
                "output_path": str(output_path),
                "processing_time_seconds": duration,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error processing SN ruling {pdf_path}: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "pdf_path": str(pdf_path)
            }
    
    @tool_registry.register(
        name="process_sn_rulings_batch",
        description="Process multiple Supreme Court ruling PDFs in batch using o3 model",
        category=ToolCategory.VECTOR_DB,
        parameters=[
            ToolParameter("pdf_directory", "string", "Directory containing PDF files to process"),
            ToolParameter("max_workers", "integer", "Maximum number of concurrent workers", False, 3),
            ToolParameter("file_pattern", "string", "File pattern to match (e.g., '*.pdf')", False, "*.pdf")
        ],
        returns="Dictionary with batch processing results"
    )
    async def process_sn_rulings_batch(self, pdf_directory: str, max_workers: int = 3, file_pattern: str = "*.pdf") -> Dict[str, Any]:
        """
        Process multiple Supreme Court ruling PDFs in batch.
        
        Args:
            pdf_directory: Directory containing PDF files
            max_workers: Maximum number of concurrent workers
            file_pattern: File pattern to match
            
        Returns:
            Dictionary with batch processing results
        """
        if not self._initialized:
            raise RuntimeError("Service not initialized")
        
        pdf_dir = Path(pdf_directory)
        if not pdf_dir.exists():
            raise FileNotFoundError(f"PDF directory not found: {pdf_directory}")
        
        # Find PDF files
        pdf_files = list(pdf_dir.glob(file_pattern))
        if not pdf_files:
            return {
                "status": "no_files",
                "message": f"No files found matching pattern '{file_pattern}' in {pdf_directory}"
            }
        
        logger.info(f"Found {len(pdf_files)} PDF files to process")
        
        start_time = datetime.now()
        results = {
            "start_time": start_time.isoformat(),
            "total_files": len(pdf_files),
            "processed_files": [],
            "failed_files": [],
            "statistics": {}
        }
        
        # Process files with semaphore to control concurrency
        semaphore = asyncio.Semaphore(max_workers)
        
        async def process_file(pdf_file: Path) -> Dict[str, Any]:
            async with semaphore:
                try:
                    return await self.process_sn_ruling(str(pdf_file), use_batch=False)
                except Exception as e:
                    logger.error(f"Error processing {pdf_file}: {e}")
                    return {
                        "status": "error",
                        "error": str(e),
                        "pdf_path": str(pdf_file)
                    }
        
        # Process all files concurrently
        file_results = await asyncio.gather(
            *[process_file(pdf_file) for pdf_file in pdf_files],
            return_exceptions=True
        )
        
        # Collect results
        total_records = 0
        for result in file_results:
            if isinstance(result, Exception):
                results["failed_files"].append({
                    "error": str(result),
                    "pdf_path": "unknown"
                })
            elif result.get("status") == "success":
                results["processed_files"].append(result)
                total_records += result.get("records_extracted", 0)
            else:
                results["failed_files"].append(result)
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        results.update({
            "end_time": end_time.isoformat(),
            "total_duration": str(end_time - start_time),
            "processing_time_seconds": duration,
            "statistics": {
                "total_files": len(pdf_files),
                "successful": len(results["processed_files"]),
                "failed": len(results["failed_files"]),
                "total_records_extracted": total_records,
                "average_time_per_file": duration / len(pdf_files) if pdf_files else 0
            }
        })
        
        logger.info(f"Batch processing completed: {results['statistics']}")
        return results
    
    async def _process_single_pdf(self, pdf_file: Path) -> List[Dict[str, Any]]:
        """Process a single PDF file using the existing o3 pipeline"""
        # Import and adapt the existing o3 processing logic
        from ...ingest.preprocess_sn_o3 import preprocess_sn_rulings
        
        # Run the async processing
        try:
            records = await preprocess_sn_rulings(pdf_file)
            return records
        except Exception as e:
            logger.error(f"Error in o3 processing: {e}")
            # Fallback to simpler processing if o3 fails
            return await self._fallback_pdf_processing(pdf_file)
    
    async def _process_with_batch(self, pdf_files: List[Path]) -> Dict[str, Any]:
        """Process multiple PDFs using batch processing"""
        # Import and adapt the existing batch processing logic
        from ...ingest.preprocess_sn_o3 import process_batch
        
        # Run the batch processing
        try:
            result = await process_batch(pdf_files)
            return {"records": result or []}
        except Exception as e:
            logger.error(f"Error in batch processing: {e}")
            # Fallback to individual processing
            all_records = []
            for pdf_file in pdf_files:
                try:
                    records = await self._process_single_pdf(pdf_file)
                    all_records.extend(records)
                except Exception as file_e:
                    logger.error(f"Error processing {pdf_file}: {file_e}")
            return {"records": all_records}
    
    async def _fallback_pdf_processing(self, pdf_file: Path) -> List[Dict[str, Any]]:
        """Fallback processing method when o3 processing fails"""
        logger.warning(f"Using fallback processing for {pdf_file}")
        
        # Simple PDF text extraction as fallback
        try:
            import fitz  # PyMuPDF
            
            doc = fitz.open(pdf_file)
            full_text = ""
            
            for page in doc:
                full_text += page.get_text()
            
            doc.close()
            
            # Create a basic record
            record = {
                "source_file": pdf_file.name,
                "section": "body",
                "para_no": 1,
                "text": full_text,
                "entities": [],
                "processing_method": "fallback"
            }
            
            return [record]
            
        except Exception as e:
            logger.error(f"Fallback processing failed for {pdf_file}: {e}")
            return []
    
    async def _save_ruling_to_jsonl(self, records: List[Dict[str, Any]], filename: str) -> Path:
        """Save ruling records to JSONL format"""
        output_dir = self._config.storage.get_path(self._config.storage.jsonl_dir)
        output_path = output_dir / f"{filename}.jsonl"
        
        # Save to JSONL format
        with open(output_path, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        
        logger.info(f"Saved {len(records)} records to {output_path}")
        return output_path
    
    @tool_registry.register(
        name="merge_sn_rulings",
        description="Merge multiple JSONL files into a single consolidated file",
        category=ToolCategory.UTILITY,
        parameters=[
            ToolParameter("output_filename", "string", "Name for the merged output file", False, "merged_sn_rulings.jsonl"),
            ToolParameter("input_pattern", "string", "Pattern to match input files", False, "*.jsonl")
        ],
        returns="Dictionary with merge results"
    )
    async def merge_sn_rulings(self, output_filename: str = "merged_sn_rulings.jsonl", input_pattern: str = "*.jsonl") -> Dict[str, Any]:
        """
        Merge multiple JSONL files into a single consolidated file.
        
        Args:
            output_filename: Name for the merged output file
            input_pattern: Pattern to match input files
            
        Returns:
            Dictionary with merge results
        """
        if not self._initialized:
            raise RuntimeError("Service not initialized")
        
        jsonl_dir = self._config.storage.get_path(self._config.storage.jsonl_dir)
        input_files = list(jsonl_dir.glob(input_pattern))
        
        if not input_files:
            return {
                "status": "no_files",
                "message": f"No files found matching pattern '{input_pattern}'"
            }
        
        logger.info(f"Merging {len(input_files)} JSONL files")
        
        all_records = []
        processed_files = []
        
        for jsonl_file in input_files:
            try:
                with open(jsonl_file, "r", encoding="utf-8") as f:
                    file_records = []
                    for line in f:
                        if line.strip():
                            file_records.append(json.loads(line))
                    
                    all_records.extend(file_records)
                    processed_files.append({
                        "file": str(jsonl_file),
                        "records": len(file_records)
                    })
            except Exception as e:
                logger.error(f"Error processing {jsonl_file}: {e}")
        
        # Write merged file
        output_path = jsonl_dir / output_filename
        with open(output_path, "w", encoding="utf-8") as f:
            for record in all_records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        
        result = {
            "status": "success",
            "output_file": str(output_path),
            "total_records": len(all_records),
            "input_files_processed": len(processed_files),
            "input_files": processed_files
        }
        
        logger.info(f"Merged {len(all_records)} records from {len(processed_files)} files into {output_path}")
        return result
    
    @tool_registry.register(
        name="get_sn_processing_status",
        description="Get current processing status for Supreme Court rulings",
        category=ToolCategory.UTILITY,
        parameters=[],
        returns="Dictionary with processing status and statistics"
    )
    async def get_sn_processing_status(self) -> Dict[str, Any]:
        """Get current processing status for Supreme Court rulings"""
        if not self._initialized:
            raise RuntimeError("Service not initialized")
        
        # Check directories
        jsonl_dir = self._config.storage.get_path(self._config.storage.jsonl_dir)
        pdfs_dir = self._config.storage.get_path(self._config.storage.pdfs_dir) / "sn-rulings"
        
        # Count files
        jsonl_files = list(jsonl_dir.glob("*.jsonl"))
        pdf_files = list(pdfs_dir.glob("*.pdf")) if pdfs_dir.exists() else []
        
        # Calculate statistics
        total_records = 0
        for jsonl_file in jsonl_files:
            try:
                with open(jsonl_file, "r", encoding="utf-8") as f:
                    total_records += sum(1 for line in f if line.strip())
            except Exception as e:
                logger.error(f"Error reading {jsonl_file}: {e}")
        
        return {
            "service_status": "healthy" if self._initialized else "not_initialized",
            "directories": {
                "jsonl_dir": str(jsonl_dir),
                "pdfs_dir": str(pdfs_dir),
                "jsonl_exists": jsonl_dir.exists(),
                "pdfs_exists": pdfs_dir.exists()
            },
            "file_counts": {
                "jsonl_files": len(jsonl_files),
                "pdf_files": len(pdf_files)
            },
            "statistics": {
                "total_records_processed": total_records,
                "processing_rate": f"{total_records / max(len(jsonl_files), 1):.1f} records/file" if jsonl_files else "N/A"
            }
        }
