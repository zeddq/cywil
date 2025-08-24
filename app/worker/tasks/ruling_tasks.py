"""
Celery tasks for Supreme Court ruling ingestion operations.
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.logger_manager import get_logger
from app.worker.celery_app import celery_app
from app.worker.service_registry import get_worker_services

# Import ingestion modules from same directory
from .preprocess_sn_o3 import preprocess_sn_rulings, process_batch

logger = get_logger(__name__)


def run_async(coro):
    """Helper to run async code in sync context"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="ruling_tasks.process_single_ruling")
def process_single_ruling(pdf_path: str) -> Dict[str, Any]:
    """
    Process a single Supreme Court ruling PDF.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        Result dictionary with processing status and extracted data
    """
    logger.info(f"Processing single ruling: {pdf_path}")

    async def _process():
        try:
            pdf_file = Path(pdf_path)
            if not pdf_file.exists():
                raise FileNotFoundError(f"PDF file not found: {pdf_path}")

            # Process the ruling using o3
            records = await preprocess_sn_rulings(pdf_file)

            return {
                "status": "completed",
                "pdf_path": pdf_path,
                "records_count": len(records),
                "output_file": str(Path("data/jsonl") / f"{pdf_file.stem}.jsonl"),
            }

        except Exception as e:
            logger.error(f"Error processing ruling: {e}", exc_info=True)
            return {"status": "error", "error": str(e), "pdf_path": pdf_path}

    return run_async(_process())


@celery_app.task(name="ruling_tasks.process_ruling_batch")
def process_ruling_batch(pdf_directory: str, max_workers: int = 3) -> Dict[str, Any]:
    """
    Process a batch of Supreme Court ruling PDFs from a directory.

    Args:
        pdf_directory: Directory containing PDF files
        max_workers: Maximum number of concurrent workers

    Returns:
        Result dictionary with batch processing statistics
    """
    logger.info(f"Processing ruling batch from: {pdf_directory}")

    async def _process():
        try:
            pdf_dir = Path(pdf_directory)
            if not pdf_dir.exists():
                raise FileNotFoundError(f"Directory not found: {pdf_directory}")

            # Get all PDF files
            pdf_files = list(pdf_dir.glob("*.pdf"))
            pdf_files = [p for p in pdf_files if p.is_file()]

            logger.info(f"Found {len(pdf_files)} PDF files to process")

            if not pdf_files:
                return {
                    "status": "completed",
                    "message": "No PDF files found",
                    "processed_count": 0,
                }

            # Process batch using o3
            await process_batch(pdf_files)

            return {
                "status": "completed",
                "pdf_directory": pdf_directory,
                "processed_count": len(pdf_files),
                "message": "Batch processing initiated",
            }

        except Exception as e:
            logger.error(f"Error processing ruling batch: {e}", exc_info=True)
            return {"status": "error", "error": str(e), "pdf_directory": pdf_directory}

    return run_async(_process())


@celery_app.task(name="ruling_tasks.get_processing_status")
def get_ruling_processing_status() -> Dict[str, Any]:
    """
    Get the current status of Supreme Court ruling processing.

    Returns:
        Status dictionary with processing statistics
    """
    logger.info("Getting ruling processing status")

    try:
        jsonl_dir = Path("data/jsonl")
        pdf_dir = Path("data/pdfs/sn-rulings")

        # Count JSONL files
        jsonl_files = list(jsonl_dir.glob("*.jsonl")) if jsonl_dir.exists() else []

        # Count PDF files
        pdf_files = list(pdf_dir.glob("*.pdf")) if pdf_dir.exists() else []

        # Get final rulings file info
        final_rulings_file = jsonl_dir / "final_sn_rulings.jsonl"
        final_rulings_count = 0
        if final_rulings_file.exists():
            with open(final_rulings_file, "r") as f:
                final_rulings_count = sum(1 for line in f if line.strip())

        return {
            "status": "success",
            "file_counts": {
                "pdf_files": len(pdf_files),
                "jsonl_files": len(jsonl_files),
                "final_rulings": final_rulings_count,
            },
            "directories": {"pdf_directory": str(pdf_dir), "jsonl_directory": str(jsonl_dir)},
        }

    except Exception as e:
        logger.error(f"Error getting processing status: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


@celery_app.task(name="ruling_tasks.reprocess_failed_rulings")
def reprocess_failed_rulings() -> Dict[str, Any]:
    """
    Reprocess any failed ruling PDFs.

    Returns:
        Result dictionary with reprocessing statistics
    """
    logger.info("Reprocessing failed rulings")

    async def _process():
        # Get shared services from worker registry
        services = get_worker_services()
        db_manager = services.db_manager

        try:
            return {
                "status": "completed",
                "message": "Reprocessing functionality needs to be implemented",
            }
        except Exception as e:
            logger.error(f"Error reprocessing failed rulings: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}
        finally:
            if db_manager:
                await db_manager.shutdown()

    return run_async(_process())


@celery_app.task(name="ruling_tasks.export_rulings_jsonl")
def export_rulings_jsonl(
    output_path: str, filters: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Export processed rulings to JSONL format.

    Args:
        output_path: Path for the output JSONL file
        filters: Optional filters for selecting rulings

    Returns:
        Result dictionary with export statistics
    """
    logger.info(f"Exporting rulings to JSONL: {output_path}")

    async def _process():
        # Get shared services from worker registry

        services = get_worker_services()
        db_manager = services.db_manager

        try:
            return {
                "status": "not_implemented",
                "message": "Export functionality needs to be implemented",
                "output_path": output_path,
            }

        except Exception as e:
            logger.error(f"Error exporting rulings: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}
        finally:
            if db_manager:
                await db_manager.shutdown()

    return run_async(_process())
