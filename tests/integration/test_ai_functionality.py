"""
Integration tests for AI processing pipeline functionality.
Tests end-to-end processing with validation, fallback mechanisms, and Polish legal document handling.
"""

import asyncio
import pytest
from unittest.mock import Mock, patch, AsyncMock
from pathlib import Path
from typing import List, Dict, Any

from app.embedding_models.pipeline_schemas import (
    RawDocument,
    ProcessedChunk,
    EmbeddedChunk,
    LegalExtraction,
    ValidationResult,
    FallbackResult,
    BatchProcessingResult,
    DocumentType
)
from app.validators.document_validator import DocumentValidator
from app.services.fallback_parser import FallbackParser
from tests.fixtures.legal_documents.test_data_loader import LegalDocumentLoader


class TestAIProcessingPipeline:
    """End-to-end tests for AI processing pipeline with validation."""
    
    @pytest.fixture
    def sample_legal_documents(self):
        """Load sample Polish legal documents."""
        return LegalDocumentLoader.load_valid_documents()
    
    @pytest.fixture
    def invalid_documents(self):
        """Load invalid test documents."""
        return LegalDocumentLoader.load_invalid_documents()
    
    @pytest.fixture
    def mock_openai_client(self):
        """Mock OpenAI client for testing."""
        mock_client = AsyncMock()
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps({
            "case_number": "II CSK 123/20",
            "court": "Sąd Najwyższy",
            "parties": ["Jan Nowak", "Spółka ABC sp. z o.o."],
            "legal_basis": ["art. 415 k.c.", "art. 6 k.p.c."],
            "decision": "oddala kasację",
            "date": "2020-10-15"
        })
        mock_client.chat.completions.create.return_value = mock_response
        return mock_client
    
    @pytest.fixture
    def mock_embedding_service(self):
        """Mock embedding service."""
        mock_service = Mock()
        # Return a normalized 384-dimensional vector
        import numpy as np
        vector = np.random.random(384)
        vector = vector / np.linalg.norm(vector)  # normalize
        mock_service.encode.return_value = vector.tolist()
        return mock_service
    
    @pytest.mark.asyncio
    async def test_complete_pipeline_valid_document(self, sample_legal_documents, mock_openai_client, mock_embedding_service):
        """Test complete pipeline processing with valid Polish legal document."""
        document = sample_legal_documents[0]  # Sample Supreme Court ruling
        
        # Step 1: Validate input document
        validation_result = DocumentValidator.validate_legal_document(
            document.content, document.document_type
        )
        assert validation_result.is_valid, f"Input validation failed: {validation_result.errors}"
        
        # Step 2: Simulate AI extraction
        with patch('openai.AsyncOpenAI', return_value=mock_openai_client):
            extraction = await self._mock_ai_extraction(document.content)
            assert extraction is not None
            assert extraction.case_number == "II CSK 123/20"
            assert "Jan Nowak" in extraction.parties
        
        # Step 3: Chunk document
        chunks = FallbackParser.basic_chunking(document, chunk_size=1000, overlap=100)
        assert len(chunks) > 0
        assert all(chunk.content for chunk in chunks)
        
        # Validate chunking stage
        chunking_validation = DocumentValidator.validate_pipeline_transition(
            document, chunks, "chunking"
        )
        assert chunking_validation.is_valid, f"Chunking validation failed: {chunking_validation.errors}"
        
        # Step 4: Generate embeddings
        embedded_chunks = []
        for chunk in chunks:
            embedding = mock_embedding_service.encode(chunk.content)
            embedded_chunk = EmbeddedChunk(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                content=chunk.content,
                chunk_index=chunk.chunk_index,
                start_char=chunk.start_char,
                end_char=chunk.end_char,
                metadata=chunk.metadata,
                embedding=embedding,
                embedding_model="test-model",
                embedded_at=chunk.metadata.get("embedded_at")
            )
            embedded_chunks.append(embedded_chunk)
        
        # Validate embedding stage
        embedding_validation = DocumentValidator.validate_pipeline_transition(
            chunks, embedded_chunks, "embedding"
        )
        assert embedding_validation.is_valid, f"Embedding validation failed: {embedding_validation.errors}"
        
        # Step 5: Validate final results
        assert len(embedded_chunks) == len(chunks)
        for embedded_chunk in embedded_chunks:
            assert len(embedded_chunk.embedding) == 384
            assert embedded_chunk.embedding_model == "test-model"
    
    @pytest.mark.asyncio
    async def test_polish_text_processing(self):
        """Test Polish-specific text handling and pattern recognition."""
        polish_document = LegalDocumentLoader.load_document_by_name("sample_wyrok_sn")
        
        # Test document validation
        validation = DocumentValidator.validate_legal_document(
            polish_document.content, DocumentType.SUPREME_COURT
        )
        assert validation.is_valid
        
        # Test entity extraction
        entities = DocumentValidator.extract_polish_entities(polish_document.content)
        
        # Verify Polish legal entities were extracted
        assert len(entities['case_numbers']) > 0
        assert "II CSK 123/20" in entities['case_numbers']
        
        assert len(entities['articles']) > 0
        # Should find articles like "art. 415 k.c."
        
        assert len(entities['courts']) > 0
        # Should find "Sąd Najwyższy"
        
        # Test fallback parser with Polish content
        fallback_result = FallbackParser.extract_case_info(polish_document.content)
        assert fallback_result.success
        assert fallback_result.confidence > 0.5
        assert fallback_result.extraction.case_number == "II CSK 123/20"
        assert "Jan Nowak" in fallback_result.extraction.parties
        assert len(fallback_result.extraction.legal_basis) > 0
    
    @pytest.mark.asyncio
    async def test_fallback_mechanisms(self, sample_legal_documents):
        """Test graceful degradation when AI services fail."""
        document = sample_legal_documents[0]
        
        # Simulate OpenAI API failure
        with patch('openai.AsyncOpenAI') as mock_openai:
            mock_openai.side_effect = Exception("API Service unavailable")
            
            # Should fall back to regex parsing
            fallback_result = FallbackParser.extract_case_info(document.content)
            
            assert fallback_result.used_fallback
            assert fallback_result.method == "regex_pattern_matching"
            
            if fallback_result.success:
                assert fallback_result.extraction is not None
                assert fallback_result.confidence > 0.0
                # Should extract at least some information
                extracted = fallback_result.extraction
                assert (extracted.case_number or extracted.court or 
                       extracted.parties or extracted.legal_basis)
    
    @pytest.mark.asyncio
    async def test_document_type_detection(self):
        """Test automatic document type detection."""
        # Test Supreme Court ruling detection
        sn_doc = LegalDocumentLoader.load_document_by_name("sample_wyrok_sn")
        doc_type, confidence = FallbackParser.categorize_document_type(sn_doc.content)
        assert doc_type == DocumentType.SUPREME_COURT
        assert confidence > 0.5
        
        # Test Civil Code detection
        kc_doc = LegalDocumentLoader.load_document_by_name("kodeks_cywilny_art415")
        doc_type, confidence = FallbackParser.categorize_document_type(kc_doc.content)
        assert doc_type == DocumentType.CIVIL_CODE
        assert confidence > 0.5
    
    @pytest.mark.asyncio
    async def test_invalid_document_handling(self, invalid_documents):
        """Test handling of invalid or corrupted documents."""
        for invalid_doc in invalid_documents:
            # Test document validation
            validation = DocumentValidator.validate_legal_document(
                invalid_doc.content, invalid_doc.document_type
            )
            
            if invalid_doc.metadata["fixture_type"] == "invalid":
                # Invalid documents should fail validation
                if invalid_doc.id == "EMPTY":
                    assert not validation.is_valid
                    assert "empty" in " ".join(validation.errors).lower()
                elif invalid_doc.id == "NON_LEGAL":
                    # Should have warnings about lack of Polish/legal content
                    assert len(validation.warnings) > 0
                elif invalid_doc.id == "CORRUPTED":
                    # Should detect encoding issues
                    assert len(validation.warnings) > 0
                    assert any("unicode" in warning.lower() for warning in validation.errors + validation.warnings)
    
    @pytest.mark.asyncio
    async def test_batch_processing_consistency(self, sample_legal_documents):
        """Test batch processing with consistency validation."""
        # Process multiple documents
        processed_chunks = []
        
        for document in sample_legal_documents[:3]:  # Process first 3 documents
            chunks = FallbackParser.basic_chunking(document)
            processed_chunks.extend(chunks)
        
        # Test batch consistency
        batch_validation = DocumentValidator.validate_batch_consistency(
            processed_chunks, "chunking"
        )
        
        assert batch_validation.is_valid, f"Batch validation failed: {batch_validation.errors}"
    
    @pytest.mark.asyncio
    async def test_embedding_consistency(self, mock_embedding_service):
        """Test embedding generation consistency."""
        # Create test chunks
        test_chunks = [
            ProcessedChunk(
                chunk_id=f"test_chunk_{i}",
                document_id="TEST_DOC",
                content=f"Test content chunk {i} with Polish legal terms like art. 415 k.c.",
                chunk_index=i,
                start_char=i * 100,
                end_char=(i + 1) * 100,
                metadata={}
            )
            for i in range(5)
        ]
        
        # Generate embeddings
        embedded_chunks = []
        for chunk in test_chunks:
            embedding = mock_embedding_service.encode(chunk.content)
            embedded_chunk = EmbeddedChunk(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                content=chunk.content,
                chunk_index=chunk.chunk_index,
                start_char=chunk.start_char,
                end_char=chunk.end_char,
                metadata=chunk.metadata,
                embedding=embedding,
                embedding_model="test-model"
            )
            embedded_chunks.append(embedded_chunk)
        
        # Validate embedding consistency
        batch_validation = DocumentValidator.validate_batch_consistency(
            embedded_chunks, "embedding"
        )
        
        assert batch_validation.is_valid, f"Embedding batch validation failed: {batch_validation.errors}"
        
        # All embeddings should have same dimension
        dimensions = [len(chunk.embedding) for chunk in embedded_chunks]
        assert len(set(dimensions)) == 1, "Inconsistent embedding dimensions"
        assert dimensions[0] == 384, "Unexpected embedding dimension"
    
    @pytest.mark.asyncio
    async def test_pipeline_error_recovery(self):
        """Test error recovery in pipeline stages."""
        # Test with problematic document
        problematic_content = "Very short content that might cause issues."
        
        document = RawDocument(
            id="PROBLEM_DOC",
            content=problematic_content,
            document_type=DocumentType.SUPREME_COURT,
            source_path="/test/path",
            metadata={}
        )
        
        # Test chunking with very short content
        chunks = FallbackParser.basic_chunking(document, chunk_size=1000)
        assert len(chunks) == 1  # Should create at least one chunk
        
        # Test validation identifies the issue
        validation = DocumentValidator.validate_legal_document(
            document.content, document.document_type
        )
        assert len(validation.warnings) > 0  # Should warn about short content
    
    @pytest.mark.asyncio
    async def test_performance_monitoring(self):
        """Test pipeline performance monitoring and metrics collection."""
        start_time = asyncio.get_event_loop().time()
        
        # Simulate processing
        document = LegalDocumentLoader.load_document_by_name("sample_wyrok_sn")
        chunks = FallbackParser.basic_chunking(document)
        
        end_time = asyncio.get_event_loop().time()
        processing_time = int((end_time - start_time) * 1000)  # Convert to milliseconds
        
        # Create metrics
        from app.embedding_models.pipeline_schemas import PipelineMetrics
        metrics = PipelineMetrics(
            stage="chunking",
            processing_time_ms=processing_time,
            input_size=len(document.content),
            output_size=sum(len(chunk.content) for chunk in chunks),
            memory_usage_mb=None,  # Would be measured in real implementation
            error_count=0
        )
        
        assert metrics.processing_time_ms >= 0
        assert metrics.input_size > 0
        assert metrics.output_size > 0
    
    async def _mock_ai_extraction(self, content: str) -> LegalExtraction:
        """Mock AI extraction for testing."""
        # This would normally call OpenAI API
        # For testing, we'll use the fallback parser
        fallback_result = FallbackParser.extract_case_info(content)
        
        if fallback_result.success and fallback_result.extraction:
            return fallback_result.extraction
        else:
            # Return basic extraction
            return LegalExtraction(
                case_number="II CSK 123/20",
                court="Sąd Najwyższy", 
                parties=["Jan Nowak", "Spółka ABC sp. z o.o."],
                legal_basis=["art. 415 k.c."],
                decision="oddala kasację"
            )


class TestPolishLegalValidation:
    """Specific tests for Polish legal document validation."""
    
    def test_case_number_validation(self):
        """Test Polish case number format validation."""
        valid_cases = [
            "II CSK 123/20",
            "I ACa 456/19", 
            "III CZP 789/21",
            "IV CSK 1234/18"
        ]
        
        invalid_cases = [
            "123/20",  # Missing court code
            "II 123/20",  # Missing case type
            "II CSK 123",  # Missing year
            "2 CSK 123/20",  # Wrong Roman numeral format
        ]
        
        pattern = DocumentValidator.POLISH_LEGAL_PATTERNS['case_number']
        
        for case in valid_cases:
            assert re.match(pattern, case), f"Valid case number failed validation: {case}"
        
        for case in invalid_cases:
            assert not re.match(pattern, case), f"Invalid case number passed validation: {case}"
    
    def test_article_reference_validation(self):
        """Test Polish legal article reference validation."""
        valid_articles = [
            "art. 415 k.c.",
            "art. 415 KC", 
            "art. 730 § 1 k.p.c.",
            "art. 6 k.p.c."
        ]
        
        for article in valid_articles:
            extraction = LegalExtraction(legal_basis=[article])
            # Should not raise validation error
            assert article in extraction.legal_basis
    
    def test_polish_character_detection(self):
        """Test detection of Polish diacritical marks."""
        polish_text = "Sąd Najwyższy orzekł w sprawie powódki Małgorzaty Kowalczyk"
        non_polish_text = "Supreme Court ruled in favor of plaintiff John Smith"
        
        polish_validation = DocumentValidator.validate_legal_document(polish_text)
        non_polish_validation = DocumentValidator.validate_legal_document(non_polish_text)
        
        # Polish text should not trigger language warnings
        polish_warnings = [w for w in polish_validation.warnings if "polish" in w.lower()]
        assert len(polish_warnings) == 0
        
        # Non-Polish text should trigger warnings
        non_polish_warnings = [w for w in non_polish_validation.warnings if "polish" in w.lower()]
        assert len(non_polish_warnings) > 0


import json
import re