"""
Celery tasks for statute ingestion operations.
"""

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.logger_manager import get_logger
from app.worker.celery_app import celery_app
from app.worker.service_registry import get_worker_services

# Import ingestion modules from same directory
from .pdf2chunks import process_statute_pdf

logger = get_logger(__name__)


def run_async(coro):
    """Helper to run async code in sync context"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="statute_tasks.ingest_statute_pdf")
def ingest_statute_pdf(pdf_path: str, code_type: str, force_update: bool = False) -> Dict[str, Any]:
    """
    Ingest a single statute PDF file.

    Args:
        pdf_path: Path to the PDF file
        code_type: Type of statute (KC or KPC)
        force_update: Whether to force update existing data

    Returns:
        Result dictionary with ingestion status and details
    """
    logger.info(f"Starting ingestion of {code_type} from {pdf_path}")

    try:
        # Check if chunks already exist
        output_dir = Path("data/chunks")
        output_file = output_dir / f"{code_type}_chunks.json"

        if output_file.exists() and not force_update:
            logger.info(f"Chunks already exist for {code_type}, skipping ingestion")
            with open(output_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {
                "status": "exists",
                "code_type": code_type,
                "statistics": data.get("statistics", {}),
                "chunks_file": str(output_file),
            }

        # Process the PDF
        chunks, stats = process_statute_pdf(pdf_path, code_type, str(output_dir))

        return {
            "status": "completed",
            "code_type": code_type,
            "statistics": stats,
            "chunks_file": str(output_file),
            "chunks_count": len(chunks),
        }

    except Exception as e:
        logger.error(f"Error ingesting statute PDF: {e}", exc_info=True)
        return {"status": "error", "error": str(e), "code_type": code_type, "pdf_path": pdf_path}


@celery_app.task(name="statute_tasks.ingest_all_statutes")
def ingest_all_statutes(force_update: bool = False) -> Dict[str, Any]:
    """
    Ingest all available statute PDFs (KC and KPC).

    Args:
        force_update: Whether to force update existing data

    Returns:
        Result dictionary with status for each statute
    """
    logger.info("Starting ingestion of all statutes")

    try:
        results = {}

        # Define statute sources
        statutes_config = {
            "KC": {"filename": "kodeks_cywilny.pdf", "name": "Kodeks Cywilny"},
            "KPC": {
                "filename": "kodeks_postepowania_cywilnego.pdf",
                "name": "Kodeks Postępowania Cywilnego",
            },
        }

        pdf_dir = Path("data/pdfs/statutes")

        for code_type, config in statutes_config.items():
            pdf_path = pdf_dir / config["filename"]

            if pdf_path.exists():
                logger.info(f"Ingesting {code_type} from {pdf_path}")
                result = ingest_statute_pdf.apply_async(
                    args=[str(pdf_path), code_type, force_update]
                ).get()
                results[code_type] = result
            else:
                logger.warning(f"PDF not found for {code_type} at {pdf_path}")
                results[code_type] = {"status": "error", "error": f"PDF not found at {pdf_path}"}

        return {"status": "completed", "results": results}

    except Exception as e:
        logger.error(f"Error ingesting statutes: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


@celery_app.task(name="statute_tasks.get_ingestion_status")
def get_statute_ingestion_status() -> Dict[str, Any]:
    """
    Get the current status of statute ingestion.

    Returns:
        Status dictionary with details for each statute
    """
    logger.info("Getting statute ingestion status")

    try:
        status = {}
        output_dir = Path("data/chunks")

        for code_type in ["KC", "KPC"]:
            chunks_file = output_dir / f"{code_type}_chunks.json"

            if chunks_file.exists():
                with open(chunks_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                status[code_type] = {
                    "status": "ingested",
                    "created_at": data.get("created_at"),
                    "statistics": data.get("statistics", {}),
                    "chunks_count": len(data.get("chunks", [])),
                }
            else:
                status[code_type] = {"status": "not_ingested", "message": "Chunks file not found"}

        return {"status": "success", "statute_status": status}

    except Exception as e:
        logger.error(f"Error getting ingestion status: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


@celery_app.task(name="statute_tasks.cleanup_statute_data")
def cleanup_statute_data(code_type: Optional[str] = None) -> Dict[str, Any]:
    """
    Clean up statute data from the database and filesystem.

    Args:
        code_type: Optional specific statute to clean up (KC or KPC)

    Returns:
        Result dictionary with cleanup status
    """
    logger.info(f"Cleaning up statute data: {code_type or 'all'}")

    async def _process():
        # Get shared services from worker registry

        services = get_worker_services()

        db_manager = services.db_manager
        service = None

        try:
            service = services.statute_ingestion
            await service.initialize()

            # This would need implementation in StatuteIngestionService
            # For now, return a placeholder
            return {
                "status": "not_implemented",
                "message": "Cleanup functionality needs to be implemented",
            }

        except Exception as e:
            logger.error(f"Error cleaning up statute data: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}
        finally:
            if service:
                await service.shutdown()
            if db_manager:
                await db_manager.shutdown()

    return run_async(_process())
