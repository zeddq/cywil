"""
Celery tasks for orchestrating the complete ingestion pipeline with validation.
"""

from typing import Any, Dict, Optional, List

from celery import chain, chord, group

from app.core.logger_manager import get_logger
from app.worker.celery_app import celery_app
from app.embedding_models.pipeline_schemas import (
    RawDocument, 
    ProcessedChunk, 
    EmbeddedChunk, 
    ValidationResult,
    BatchProcessingResult,
    PipelineMetrics,
    DocumentType
)
from app.validators.document_validator import DocumentValidator
from app.services.fallback_parser import FallbackParser

from .ruling_tasks import process_ruling_batch
from .statute_tasks import generate_statute_embeddings, ingest_all_statutes

logger = get_logger(__name__)


@celery_app.task(name="ingestion_pipeline.run_full_pipeline")
def run_full_pipeline(
    statute_force_update: bool = False,
    ruling_pdf_directory: Optional[str] = None,
    max_ruling_workers: int = 3,
) -> Dict[str, Any]:
    """
    Run the complete ingestion pipeline orchestrating all components.

    Args:
        statute_force_update: Whether to force update statute data
        ruling_pdf_directory: Optional directory containing ruling PDFs
        max_ruling_workers: Maximum concurrent workers for ruling processing

    Returns:
        Pipeline execution results
    """
    logger.info("Starting full ingestion pipeline")

    pipeline_tasks = []

    # Step 1: Ingest statutes
    statute_task = ingest_all_statutes.si(force_update=statute_force_update)
    pipeline_tasks.append(statute_task)

    # Step 2: Generate statute embeddings (after statutes are ingested)
    embedding_tasks_group = group(
        generate_statute_embeddings.si("KC", force_regenerate=statute_force_update),
        generate_statute_embeddings.si("KPC", force_regenerate=statute_force_update),
    )

    # Chain statute ingestion with embedding generation
    statute_chain = chain(statute_task, embedding_tasks_group)

    # Step 3: Process rulings if directory provided
    if ruling_pdf_directory:
        ruling_task = process_ruling_batch.si(
            pdf_directory=ruling_pdf_directory, max_workers=max_ruling_workers
        )

        # Run statutes and rulings in parallel
        parallel_tasks = group(statute_chain, ruling_task)

        # Final step: Generate ruling embeddings after processing
        # This would need the JSONL output path from ruling processing
        # For now, we'll run the parallel tasks
        result = chord(parallel_tasks)(aggregate_pipeline_results.s())
        return {"status": "started", "task_id": str(result.id) if hasattr(result, 'id') else "unknown"}
    else:
        # Just run statute pipeline
        result = statute_chain.apply_async()
        return {"status": "started", "task_id": str(result.id) if hasattr(result, 'id') else "unknown"}


@celery_app.task(name="ingestion_pipeline.aggregate_pipeline_results")
def aggregate_pipeline_results(results: list) -> Dict[str, Any]:
    """
    Aggregate results from parallel pipeline tasks.

    Args:
        results: List of task results

    Returns:
        Aggregated pipeline results
    """
    logger.info("Aggregating pipeline results")

    aggregated = {"status": "completed", "components": {}}

    # Process results based on their structure
    for idx, result in enumerate(results):
        if isinstance(result, list):
            # This is from a group task
            for sub_idx, sub_result in enumerate(result):
                aggregated["components"][f"task_{idx}_{sub_idx}"] = sub_result
        else:
            aggregated["components"][f"task_{idx}"] = result

    # Check for any errors
    errors = []
    for component_name, component_result in aggregated["components"].items():
        if isinstance(component_result, dict) and component_result.get("status") == "error":
            errors.append(
                {
                    "component": component_name,
                    "error": component_result.get("error", "Unknown error"),
                }
            )

    if errors:
        aggregated["status"] = "completed_with_errors"
        aggregated["errors"] = errors

    return aggregated


@celery_app.task(name="ingestion_pipeline.run_statute_pipeline")
def run_statute_pipeline(force_update: bool = False) -> Dict[str, Any]:
    """
    Run only the statute ingestion pipeline.

    Args:
        force_update: Whether to force update existing data

    Returns:
        Pipeline execution results
    """
    logger.info("Starting statute ingestion pipeline")

    # Chain statute ingestion with embedding generation
    pipeline = chain(
        ingest_all_statutes.si(force_update=force_update),
        group(
            generate_statute_embeddings.si("KC", force_regenerate=force_update),
            generate_statute_embeddings.si("KPC", force_regenerate=force_update),
        ),
    )

    result = pipeline.apply_async()
    return {"status": "started", "task_id": str(result.id) if hasattr(result, 'id') else "unknown"}


@celery_app.task(name="ingestion_pipeline.run_ruling_pipeline")
def run_ruling_pipeline(
    pdf_directory: str, max_workers: int = 3, generate_embeddings: bool = True
) -> Dict[str, Any]:
    """
    Run only the ruling ingestion pipeline.

    Args:
        pdf_directory: Directory containing ruling PDFs
        max_workers: Maximum concurrent workers
        generate_embeddings: Whether to generate embeddings after processing

    Returns:
        Pipeline execution results
    """
    logger.info(f"Starting ruling ingestion pipeline for: {pdf_directory}")

    tasks = [process_ruling_batch.si(pdf_directory=pdf_directory, max_workers=max_workers)]

    if generate_embeddings:
        # This would need to determine the JSONL output path
        # For now, just run the processing task
        pass

    if len(tasks) > 1:
        pipeline = chain(*tasks)
        result = pipeline.apply_async()
        return {"status": "started", "task_id": str(result.id) if hasattr(result, 'id') else "unknown"}
    else:
        result = tasks[0].apply_async()
        return {"status": "started", "task_id": str(result.id) if hasattr(result, 'id') else "unknown"}


@celery_app.task(name="ingestion_pipeline.get_pipeline_status")
def get_pipeline_status() -> Dict[str, Any]:
    """
    Get the current status of all ingestion components.

    Returns:
        Comprehensive status report
    """
    logger.info("Getting pipeline status")

    # Run status checks in parallel
    status_group = group(
        get_statute_ingestion_status.si(),
        get_ruling_processing_status.si(),
        get_embedding_statistics.si(),
    )

    return status_group.apply_async()


from .embedding_tasks import get_embedding_statistics
from .ruling_tasks import get_ruling_processing_status

# Import status tasks
from .statute_tasks import get_statute_ingestion_status
