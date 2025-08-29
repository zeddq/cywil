"""
"""
Validation tasks for the ingestion pipeline.
"""

import time
from typing import Any, Dict, List

from app.core.logger_manager import get_logger
from app.embedding_models.pipeline_schemas import (
    RawDocument,
    ProcessedChunk, 
    EmbeddedChunk,
    ValidationResult,
)
from app.validators.document_validator import DocumentValidator
from app.services.fallback_parser import FallbackParser
from app.worker.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="validation.validate_document_batch")
def validate_document_batch(documents: List[Dict[str, Any]], stage: str) -> Dict[str, Any]:
    """
    Validate a batch of documents at a specific pipeline stage.
    
    Args:
        documents: List of document data to validate
        stage: Pipeline stage name
        
    Returns:
        Validation results summary
    """
    logger.info(f"Validating batch of {len(documents)} documents at stage: {stage}")
    
    validation_results = []
    errors = []
    warnings = []
    
    try:
        for doc_data in documents:
            try:
                # Convert dict to appropriate model for validation
                if stage == "input":
                    document = RawDocument(**doc_data)
                    validation = DocumentValidator.validate_legal_document(
                        document.content, document.document_type
                    )
                elif stage == "chunking":
                    # Validate chunks
                    chunks = [ProcessedChunk(**chunk_data) for chunk_data in doc_data.get("chunks", [])]
                    input_doc = RawDocument(**doc_data.get("document", {}))
                    validation = DocumentValidator.validate_pipeline_transition(
                        input_doc, chunks, "chunking"
                    )
                elif stage == "embedding":
                    # Validate embeddings
                    embedded_chunks = [EmbeddedChunk(**chunk_data) for chunk_data in doc_data.get("chunks", [])]
                    validation = DocumentValidator.validate_batch_consistency(
                        embedded_chunks, "embedding"
                    )
                else:
                    validation = ValidationResult(
                        is_valid=True,
                        errors=[],
                        warnings=[f"Unknown validation stage: {stage}"],
                        stage=stage
                    )
                
                validation_results.append({
                    "document_id": doc_data.get("id", "unknown"),
                    "is_valid": validation.is_valid,
                    "errors": validation.errors,
                    "warnings": validation.warnings
                })
                
                errors.extend(validation.errors)
                warnings.extend(validation.warnings)
                
            except Exception as e:
                error_msg = f"Validation error for document {doc_data.get('id', 'unknown')}: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)
                validation_results.append({
                    "document_id": doc_data.get("id", "unknown"),
                    "is_valid": False,
                    "errors": [error_msg],
                    "warnings": []
                })
        
        # Calculate summary statistics
        valid_count = sum(1 for result in validation_results if result["is_valid"])
        invalid_count = len(validation_results) - valid_count
        
        return {
            "status": "completed",
            "stage": stage,
            "total_documents": len(documents),
            "valid_documents": valid_count,
            "invalid_documents": invalid_count,
            "total_errors": len(errors),
            "total_warnings": len(warnings),
            "validation_results": validation_results,
            "summary_errors": list(set(errors))[:10],  # Limit to avoid huge responses
            "summary_warnings": list(set(warnings))[:10]
        }
        
    except Exception as e:
        logger.error(f"Batch validation failed: {str(e)}")
        return {
            "status": "error",
            "stage": stage,
            "error": str(e),
            "total_documents": len(documents),
            "valid_documents": 0,
            "invalid_documents": len(documents)
        }


@celery_app.task(name="validation.validate_pipeline_stage")
def validate_pipeline_stage(
    input_data: Dict[str, Any], 
    output_data: Dict[str, Any], 
    stage: str
) -> Dict[str, Any]:
    """
    Validate data integrity between pipeline stages.
    
    Args:
        input_data: Input data to the stage
        output_data: Output data from the stage
        stage: Pipeline stage name
        
    Returns:
        Validation result
    """
    logger.info(f"Validating pipeline stage: {stage}")
    
    try:
        validation = DocumentValidator.validate_pipeline_transition(
            input_data, output_data, stage
        )
        
        return {
            "status": "completed",
            "stage": stage,
            "is_valid": validation.is_valid,
            "errors": validation.errors,
            "warnings": validation.warnings,
            "timestamp": validation.timestamp.isoformat()
        }
        
    except Exception as e:
        logger.error(f"Pipeline stage validation failed: {str(e)}")
        return {
            "status": "error",
            "stage": stage,
            "error": str(e),
            "is_valid": False
        }


@celery_app.task(name="validation.extract_with_fallback")
def extract_with_fallback(document_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract legal information with fallback to regex parsing.
    
    Args:
        document_data: Document data to process
        
    Returns:
        Extraction result with fallback information
    """
    logger.info(f"Extracting information from document: {document_data.get('id', 'unknown')}")
    
    try:
        document = RawDocument(**document_data)
        
        # First validate the document
        validation = DocumentValidator.validate_legal_document(
            document.content, document.document_type
        )
        
        if not validation.is_valid:
            logger.warning(f"Document validation failed: {validation.errors}")
        
        # Use fallback parser (in real implementation, try OpenAI first)
        fallback_result = FallbackParser.extract_case_info(document.content)
        
        return {
            "status": "completed",
            "document_id": document.id,
            "extraction_success": fallback_result.success,
            "used_fallback": fallback_result.used_fallback,
            "confidence": fallback_result.confidence,
            "method": fallback_result.method,
            "extraction": fallback_result.extraction.dict() if fallback_result.extraction else None,
            "errors": fallback_result.errors,
            "validation_errors": validation.errors,
            "validation_warnings": validation.warnings
        }
        
    except Exception as e:
        logger.error(f"Extraction failed: {str(e)}")
        return {
            "status": "error",
            "document_id": document_data.get("id", "unknown"),
            "error": str(e),
            "extraction_success": False
        }


@celery_app.task(name="validation.process_with_validation")
def process_with_validation(
    documents: List[Dict[str, Any]], 
    enable_validation: bool = True,
    use_fallback: bool = True
) -> Dict[str, Any]:
    """
    Process documents with comprehensive validation at each stage.
    
    Args:
        documents: List of documents to process
        enable_validation: Whether to enable validation
        use_fallback: Whether to use fallback parsing
        
    Returns:
        Processing results with validation metrics
    """
    logger.info(f"Processing {len(documents)} documents with validation enabled: {enable_validation}")
    
    processing_metrics = []
    results = []
    
    try:
        start_time = time.time()
        
        # Stage 1: Input validation
        if enable_validation:
            validation_task = validate_document_batch.si(documents, "input")
            validation_result = validation_task.apply().get()
            
            if validation_result["status"] == "error":
                return {
                    "status": "error",
                    "stage": "input_validation",
                    "error": validation_result["error"]
                }
            
            processing_metrics.append({
                "stage": "input_validation",
                "valid_documents": validation_result["valid_documents"],
                "invalid_documents": validation_result["invalid_documents"],
                "errors": len(validation_result["summary_errors"]),
                "warnings": len(validation_result["summary_warnings"])
            })
        
        # Stage 2: Document processing (chunking, extraction)
        processed_documents = []
        for doc_data in documents:
            try:
                # Create chunks
                document = RawDocument(**doc_data)
                chunks = FallbackParser.basic_chunking(document)
                
                # Extract legal information
                if use_fallback:
                    extraction_result = extract_with_fallback.si(doc_data).apply().get()
                else:
                    extraction_result = {"extraction": None, "used_fallback": False}
                
                processed_doc = {
                    "document": doc_data,
                    "chunks": [chunk.dict() for chunk in chunks],
                    "extraction": extraction_result.get("extraction"),
                    "processing_info": {
                        "used_fallback": extraction_result.get("used_fallback", False),
                        "confidence": extraction_result.get("confidence", 0.0),
                        "method": extraction_result.get("method", "unknown")
                    }
                }
                
                processed_documents.append(processed_doc)
                results.append({
                    "document_id": doc_data["id"],
                    "status": "success",
                    "chunk_count": len(chunks),
                    "extraction_success": extraction_result.get("extraction_success", False)
                })
                
            except Exception as e:
                logger.error(f"Processing failed for document {doc_data.get('id')}: {str(e)}")
                results.append({
                    "document_id": doc_data.get("id", "unknown"),
                    "status": "error",
                    "error": str(e)
                })
        
        # Stage 3: Post-processing validation
        if enable_validation and processed_documents:
            chunking_validation = validate_document_batch.si(processed_documents, "chunking").apply().get()
            
            processing_metrics.append({
                "stage": "chunking_validation",
                "valid_documents": chunking_validation["valid_documents"],
                "invalid_documents": chunking_validation["invalid_documents"]
            })
        
        end_time = time.time()
        processing_time = int((end_time - start_time) * 1000)  # milliseconds
        
        # Calculate summary statistics
        successful_docs = len([r for r in results if r["status"] == "success"])
        failed_docs = len([r for r in results if r["status"] == "error"])
        
        return {
            "status": "completed",
            "total_documents": len(documents),
            "successful": successful_docs,
            "failed": failed_docs,
            "processing_time_ms": processing_time,
            "validation_enabled": enable_validation,
            "fallback_used": use_fallback,
            "results": results,
            "metrics": processing_metrics
        }
        
    except Exception as e:
        logger.error(f"Batch processing with validation failed: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "total_documents": len(documents),
            "successful": 0,
            "failed": len(documents)
        }