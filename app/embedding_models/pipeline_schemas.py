"""
Pydantic models for AI processing pipeline data validation.
Ensures data integrity and proper format validation through all pipeline stages.
"""

import re
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
from pydantic import BaseModel, Field, validator


class DocumentType(str, Enum):
    """Supported document types in the processing pipeline."""
    SUPREME_COURT = "sn_ruling"
    CIVIL_CODE = "kc_article"
    CIVIL_PROCEDURE = "kpc_article"
    CONTRACT = "contract"
    PLEADING = "pleading"


class RawDocument(BaseModel):
    """Input document for processing pipeline."""
    id: str = Field(..., regex="^[A-Z0-9-]+$", description="Unique document identifier")
    content: str = Field(..., min_length=10, max_length=1000000, description="Document text content")
    document_type: DocumentType = Field(..., description="Type of document being processed")
    source_path: str = Field(..., description="Path to original source file")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional document metadata")
    
    @validator('content')
    def validate_not_empty(cls, v):
        """Ensure document content is not empty or whitespace only."""
        if not v.strip():
            raise ValueError('Document content cannot be empty')
        return v
    
    @validator('source_path')
    def validate_source_path(cls, v):
        """Validate source path format."""
        if not v or len(v.strip()) == 0:
            raise ValueError('Source path cannot be empty')
        return v


class ProcessedChunk(BaseModel):
    """Document chunk after processing."""
    chunk_id: str = Field(..., description="Unique chunk identifier")
    document_id: str = Field(..., description="Parent document identifier")
    content: str = Field(..., min_length=1, max_length=4000, description="Chunk text content")
    chunk_index: int = Field(..., ge=0, description="Order index of chunk in document")
    start_char: int = Field(..., ge=0, description="Starting character position in document")
    end_char: int = Field(..., description="Ending character position in document")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Chunk-specific metadata")
    
    @validator('end_char')
    def validate_char_range(cls, v, values):
        """Ensure end_char is greater than start_char."""
        if 'start_char' in values and v <= values['start_char']:
            raise ValueError('end_char must be greater than start_char')
        return v
    
    @validator('content')
    def validate_chunk_content(cls, v):
        """Validate chunk content is meaningful."""
        if not v.strip():
            raise ValueError('Chunk content cannot be empty')
        return v


class EmbeddedChunk(ProcessedChunk):
    """Chunk with embedding vector."""
    embedding: List[float] = Field(
        ..., 
        min_items=384, 
        max_items=1536,
        description="Vector embedding of the chunk content"
    )
    embedding_model: str = Field(..., description="Name of the embedding model used")
    embedded_at: datetime = Field(default_factory=datetime.now, description="Timestamp of embedding generation")
    
    @validator('embedding')
    def validate_embedding_normalized(cls, v):
        """Ensure embedding vector is properly normalized."""
        norm = np.linalg.norm(v)
        if not 0.95 < norm < 1.05:  # Allow some tolerance for float precision
            raise ValueError(f'Embedding not normalized: {norm:.4f}')
        return v
    
    @validator('embedding_model')
    def validate_embedding_model(cls, v):
        """Validate embedding model name."""
        if not v or len(v.strip()) == 0:
            raise ValueError('Embedding model name cannot be empty')
        return v


class LegalExtraction(BaseModel):
    """Extracted legal information from documents."""
    case_number: Optional[str] = Field(
        None, 
        regex=r"^[IVX]+ [A-Z]+ \d+/\d+$",
        description="Polish court case number format"
    )
    court: Optional[str] = Field(None, description="Court name")
    date: Optional[datetime] = Field(None, description="Document or ruling date")
    parties: List[str] = Field(default_factory=list, description="Legal parties involved")
    legal_basis: List[str] = Field(default_factory=list, description="Article references cited")
    decision: Optional[str] = Field(None, description="Court decision or outcome")
    reasoning: Optional[str] = Field(None, description="Legal reasoning or justification")
    
    @validator('legal_basis')
    def validate_article_format(cls, v):
        """Validate Polish legal article reference format."""
        pattern = r'^(art\.|§)\s*\d+'
        for ref in v:
            if not re.match(pattern, ref, re.IGNORECASE):
                raise ValueError(f'Invalid article reference format: {ref}')
        return v
    
    @validator('parties')
    def validate_parties(cls, v):
        """Ensure parties list doesn't contain empty strings."""
        return [party.strip() for party in v if party.strip()]
    
    @validator('case_number')
    def validate_case_number_format(cls, v):
        """Validate Polish case number format if provided."""
        if v and not re.match(r"^[IVX]+ [A-Z]+ \d+/\d+$", v):
            raise ValueError(f'Invalid Polish case number format: {v}')
        return v


class ValidationResult(BaseModel):
    """Result of document or pipeline validation."""
    is_valid: bool = Field(..., description="Whether validation passed")
    errors: List[str] = Field(default_factory=list, description="List of validation errors")
    warnings: List[str] = Field(default_factory=list, description="List of validation warnings")
    stage: str = Field(..., description="Pipeline stage where validation occurred")
    timestamp: datetime = Field(default_factory=datetime.now, description="When validation was performed")
    
    @validator('stage')
    def validate_stage(cls, v):
        """Ensure stage name is provided."""
        if not v or len(v.strip()) == 0:
            raise ValueError('Validation stage cannot be empty')
        return v


class PipelineMetrics(BaseModel):
    """Metrics for pipeline performance monitoring."""
    stage: str = Field(..., description="Pipeline stage name")
    processing_time_ms: int = Field(..., ge=0, description="Processing time in milliseconds")
    input_size: int = Field(..., ge=0, description="Size of input data")
    output_size: int = Field(..., ge=0, description="Size of output data")
    memory_usage_mb: Optional[float] = Field(None, ge=0, description="Memory usage in MB")
    error_count: int = Field(default=0, ge=0, description="Number of errors encountered")
    timestamp: datetime = Field(default_factory=datetime.now, description="When metrics were recorded")
    
    @validator('stage')
    def validate_stage_name(cls, v):
        """Validate stage name format."""
        if not v or len(v.strip()) == 0:
            raise ValueError('Stage name cannot be empty')
        return v


class FallbackResult(BaseModel):
    """Result from fallback parsing when AI services fail."""
    success: bool = Field(..., description="Whether fallback parsing succeeded")
    used_fallback: bool = Field(default=True, description="Indicates fallback was used")
    extraction: Optional[LegalExtraction] = Field(None, description="Extracted information")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score of extraction")
    method: str = Field(..., description="Fallback method used")
    errors: List[str] = Field(default_factory=list, description="Any errors during fallback")
    
    @validator('method')
    def validate_method(cls, v):
        """Validate fallback method name."""
        if not v or len(v.strip()) == 0:
            raise ValueError('Fallback method cannot be empty')
        return v
    
    @validator('confidence')
    def validate_confidence_range(cls, v):
        """Ensure confidence is between 0 and 1."""
        if not 0.0 <= v <= 1.0:
            raise ValueError(f'Confidence must be between 0.0 and 1.0, got {v}')
        return v


class BatchProcessingResult(BaseModel):
    """Result of batch document processing."""
    total_documents: int = Field(..., ge=0, description="Total number of documents processed")
    successful: int = Field(..., ge=0, description="Number of successfully processed documents")
    failed: int = Field(..., ge=0, description="Number of failed documents")
    skipped: int = Field(default=0, ge=0, description="Number of skipped documents")
    processing_time_seconds: float = Field(..., ge=0, description="Total processing time")
    errors: List[Dict[str, str]] = Field(default_factory=list, description="List of errors with details")
    metrics: Optional[PipelineMetrics] = Field(None, description="Performance metrics")
    
    @validator('failed')
    def validate_failed_count(cls, v, values):
        """Ensure failed count is consistent with error list."""
        if 'errors' in values and len(values['errors']) != v:
            raise ValueError(f'Failed count ({v}) does not match error list length ({len(values["errors"])})')
        return v
    
    @validator('total_documents')
    def validate_total_consistency(cls, v, values):
        """Ensure total equals sum of successful, failed, and skipped."""
        if all(key in values for key in ['successful', 'failed', 'skipped']):
            expected_total = values['successful'] + values['failed'] + values['skipped']
            if v != expected_total:
                raise ValueError(f'Total documents ({v}) does not match sum of successful + failed + skipped ({expected_total})')
        return v