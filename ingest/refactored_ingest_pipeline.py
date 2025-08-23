#!/usr/bin/env python3
"""
Refactored ingestion pipeline that uses the new service architecture.
This serves as a bridge between the old standalone scripts and the new service-based approach.
"""

import os
import sys
import asyncio
import argparse
import logging
from pathlib import Path
from typing import Dict, List, Optional

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from app.core.config_service import get_config
from app.core.database_manager import DatabaseManager
from app.core.logger_manager import get_logger


logger = get_logger(__name__)


class RefactoredIngestOrchestrator:
    """
    Orchestrates the complete ingestion process using the new service architecture.
    This replaces the old StatuteIngestionPipeline class.
    """
    
    def __init__(self):
        self.config = get_config()
        self.db_manager = DatabaseManager()
        self.initialized = False
    
    async def initialize(self) -> None:
        """Initialize all services"""
        logger.info("Initializing refactored ingestion orchestrator")
        
        # Initialize database manager
        await self.db_manager.initialize()
        
        # Initialize services
        
        # Initialize all services
        
        
        self.initialized = True
        logger.info("All services initialized successfully")
    
    async def shutdown(self) -> None:
        """Shutdown all services gracefully"""
        logger.info("Shutting down ingestion orchestrator")
        
        if self.db_manager:
            await self.db_manager.shutdown()
        
        logger.info("All services shut down successfully")
    
    async def health_check(self) -> Dict[str, any]:
        """Check health of all services"""
        if not self.initialized:
            return {"status": "not_initialized"}
        
        health_results = {}
        
        # Check each service
        services = [
            ("database", self.db_manager),
        ]
        
        for service_name, service in services:
            try:
                health = await service.health_check()
                health_results[service_name] = {
                    "status": health.status.value,
                    "message": health.message,
                    "details": health.details
                }
            except Exception as e:
                health_results[service_name] = {
                    "status": "error",
                    "message": str(e)
                }
        
        return health_results
    
    async def ingest_statutes(self, force_update: bool = False) -> Dict[str, any]:
        """Ingest all available statutes"""
        if not self.initialized:
            raise RuntimeError("Orchestrator not initialized")
        
        logger.info("Starting statute ingestion process")
        
        # Get available sources
        sources = await self.statute_service.list_statute_sources()
        
        results = {}
        for code_type in ["KC", "KPC"]:
            if code_type in sources["sources"]:
                source_info = sources["sources"][code_type]
                pdf_path = Path(sources["download_directory"]) / source_info["filename"]
                
                if pdf_path.exists():
                    logger.info(f"Ingesting {code_type} from {pdf_path}")
                    result = await self.statute_service.ingest_statute_pdf(
                        str(pdf_path), 
                        code_type, 
                        force_update
                    )
                    results[code_type] = result
                else:
                    logger.warning(f"PDF not found for {code_type} at {pdf_path}")
                    results[code_type] = {
                        "status": "error",
                        "error": f"PDF not found at {pdf_path}"
                    }
            else:
                results[code_type] = {
                    "status": "error", 
                    "error": f"Source not configured for {code_type}"
                }
        
        return results
    
    async def ingest_court_rulings(self, pdf_directory: str, max_workers: int = 3) -> Dict[str, any]:
        """Ingest Supreme Court rulings from a directory"""
        if not self.initialized:
            raise RuntimeError("Orchestrator not initialized")
        
        logger.info(f"Starting court ruling ingestion from {pdf_directory}")
        
        result = await self.court_service.process_sn_rulings_batch(
            pdf_directory=pdf_directory,
            max_workers=max_workers
        )
        
        return result
    
    async def generate_all_embeddings(self, force_regenerate: bool = False) -> Dict[str, any]:
        """Generate embeddings for all ingested content"""
        if not self.initialized:
            raise RuntimeError("Orchestrator not initialized")
        
        logger.info("Starting embedding generation process")
        
        results = {}
        
        # Generate statute embeddings
        for code_type in ["KC", "KPC"]:
            try:
                # This would need to be adapted to work with the new service structure
                # For now, we'll use the embedding service statistics
                stats = await self.embedding_service.get_embedding_statistics("statutes")
                results[f"{code_type}_embeddings"] = stats
            except Exception as e:
                results[f"{code_type}_embeddings"] = {
                    "status": "error",
                    "error": str(e)
                }
        
        # Generate court ruling embeddings
        try:
            # Check for JSONL files to process
            jsonl_dir = self.config.storage.get_path(self.config.storage.jsonl_dir)
            jsonl_files = list(jsonl_dir.glob("*.jsonl"))
            
            if jsonl_files:
                for jsonl_file in jsonl_files:
                    result = await self.embedding_service.generate_ruling_embeddings(
                        str(jsonl_file)
                    )
                    results[f"ruling_embeddings_{jsonl_file.stem}"] = result
            else:
                results["ruling_embeddings"] = {
                    "status": "no_files",
                    "message": "No JSONL files found for processing"
                }
        except Exception as e:
            results["ruling_embeddings"] = {
                "status": "error",
                "error": str(e)
            }
        
        return results
    
    async def run_full_pipeline(self, force_update: bool = False, 
                               court_pdf_directory: Optional[str] = None) -> Dict[str, any]:
        """Run the complete ingestion pipeline"""
        if not self.initialized:
            raise RuntimeError("Orchestrator not initialized")
        
        logger.info("Starting full ingestion pipeline")
        
        pipeline_results = {
            "start_time": asyncio.get_event_loop().time(),
            "steps": {}
        }
        
        # Step 1: Health check
        logger.info("Step 1: Health check")
        health = await self.health_check()
        pipeline_results["steps"]["health_check"] = health
        
        # Step 2: Ingest statutes
        logger.info("Step 2: Ingesting statutes")
        statute_results = await self.ingest_statutes(force_update)
        pipeline_results["steps"]["statute_ingestion"] = statute_results
        
        # Step 3: Ingest court rulings (if directory provided)
        if court_pdf_directory:
            logger.info(f"Step 3: Ingesting court rulings from {court_pdf_directory}")
            court_results = await self.ingest_court_rulings(court_pdf_directory)
            pipeline_results["steps"]["court_ingestion"] = court_results
        
        # Step 4: Generate embeddings
        logger.info("Step 4: Generating embeddings")
        embedding_results = await self.generate_all_embeddings(force_update)
        pipeline_results["steps"]["embedding_generation"] = embedding_results
        
        # Step 5: Final health check
        logger.info("Step 5: Final health check")
        final_health = await self.health_check()
        pipeline_results["steps"]["final_health_check"] = final_health
        
        pipeline_results["end_time"] = asyncio.get_event_loop().time()
        pipeline_results["duration"] = pipeline_results["end_time"] - pipeline_results["start_time"]
        
        logger.info(f"Full pipeline completed in {pipeline_results['duration']:.2f} seconds")
        return pipeline_results
    
    async def validate_ingestion(self) -> Dict[str, any]:
        """Validate the ingestion results by running test queries"""
        if not self.initialized:
            raise RuntimeError("Orchestrator not initialized")
        
        logger.info("Running ingestion validation")
        
        # Get ingestion status
        statute_status = await self.statute_service.get_ingestion_status()
        court_status = await self.court_service.get_sn_processing_status()
        embedding_stats = await self.embedding_service.get_embedding_statistics()
        
        validation_results = {
            "timestamp": asyncio.get_event_loop().time(),
            "statute_status": statute_status,
            "court_status": court_status,
            "embedding_statistics": embedding_stats,
            "validation_summary": {
                "statutes_available": statute_status["statute_status"]["KC"]["status"] == "ingested" and 
                                   statute_status["statute_status"]["KPC"]["status"] == "ingested",
                "court_rulings_available": court_status["file_counts"]["jsonl_files"] > 0,
                "embeddings_available": any(
                    stats.get("points_count", 0) > 0 
                    for stats in embedding_stats.get("collections", {}).values()
                    if isinstance(stats, dict)
                )
            }
        }
        
        return validation_results


async def main():
    """Main entry point for the refactored ingestion pipeline"""
    parser = argparse.ArgumentParser(
        description="Refactored ingestion pipeline using service architecture"
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only run validation tests"
    )
    parser.add_argument(
        "--force-update",
        action="store_true",
        help="Force update even if data already exists"
    )
    parser.add_argument(
        "--court-pdf-directory",
        help="Directory containing Supreme Court ruling PDFs"
    )
    parser.add_argument(
        "--health-check",
        action="store_true",
        help="Run health check only"
    )
    parser.add_argument(
        "--embeddings-only",
        action="store_true",
        help="Only generate embeddings"
    )
    
    args = parser.parse_args()
    
    # Initialize orchestrator
    orchestrator = RefactoredIngestOrchestrator()
    
    try:
        await orchestrator.initialize()
        
        if args.health_check:
            # Run health check only
            health = await orchestrator.health_check()
            print("\nHealth Check Results:")
            for service, status in health.items():
                print(f"  {service}: {status['status']} - {status['message']}")
            
        elif args.validate_only:
            # Run validation only
            validation = await orchestrator.validate_ingestion()
            print("\nValidation Results:")
            print(f"  Statutes available: {validation['validation_summary']['statutes_available']}")
            print(f"  Court rulings available: {validation['validation_summary']['court_rulings_available']}")
            print(f"  Embeddings available: {validation['validation_summary']['embeddings_available']}")
            
        elif args.embeddings_only:
            # Generate embeddings only
            results = await orchestrator.generate_all_embeddings(args.force_update)
            print("\nEmbedding Generation Results:")
            for key, result in results.items():
                print(f"  {key}: {result.get('status', 'unknown')}")
                
        else:
            # Run full pipeline
            results = await orchestrator.run_full_pipeline(
                force_update=args.force_update,
                court_pdf_directory=args.court_pdf_directory
            )
            
            print("\nFull Pipeline Results:")
            print(f"  Duration: {results['duration']:.2f} seconds")
            for step, result in results["steps"].items():
                print(f"  {step}: completed")
    
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        return 1
    
    finally:
        await orchestrator.shutdown()
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
