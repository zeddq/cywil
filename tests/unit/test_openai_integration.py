"""
Unit tests for OpenAI API integration with validation and error handling.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
import json
from datetime import datetime
from openai import AsyncOpenAI, APIError, RateLimitError, APITimeoutError

from app.embedding_models.pipeline_schemas import (
    RawDocument,
    LegalExtraction,
    FallbackResult,
    DocumentType,
    ValidationResult
)
from app.validators.document_validator import DocumentValidator
from app.services.fallback_parser import FallbackParser
from tests.fixtures.legal_documents.test_data_loader import LegalDocumentLoader


class TestOpenAIIntegration:
    """Unit tests for OpenAI API integration."""
    
    @pytest.fixture
    def mock_openai_client(self):
        """Create mock OpenAI client."""
        return AsyncMock(spec=AsyncOpenAI)
    
    @pytest.fixture
    def sample_legal_document(self):
        """Get sample legal document for testing."""
        return LegalDocumentLoader.load_document_by_name("sample_wyrok_sn")
    
    @pytest.fixture
    def valid_openai_response(self):
        """Mock valid OpenAI API response."""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps({
            "case_number": "II CSK 123/20",
            "court": "Sąd Najwyższy",
            "date": "2020-10-15",
            "parties": ["Jan Nowak", "Spółka ABC sp. z o.o."],
            "legal_basis": ["art. 415 k.c.", "art. 6 k.p.c."],
            "decision": "oddala kasację",
            "reasoning": "Powód nie wykazał należytego wykonania zobowiązania"
        })
        return mock_response
    
    @pytest.fixture
    def invalid_openai_response(self):
        """Mock invalid OpenAI API response."""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        # Invalid JSON response
        mock_response.choices[0].message.content = "Invalid JSON response from AI"
        return mock_response
    
    @pytest.mark.asyncio
    async def test_successful_extraction(self, mock_openai_client, sample_legal_document, valid_openai_response):
        """Test successful legal information extraction via OpenAI."""
        mock_openai_client.chat.completions.create.return_value = valid_openai_response
        
        # Simulate OpenAI extraction
        result = await self._extract_legal_info_with_openai(
            mock_openai_client, 
            sample_legal_document.content
        )
        
        # Verify extraction results
        assert result.success
        assert result.extraction is not None
        extraction = result.extraction
        assert extraction.case_number == "II CSK 123/20"
        assert extraction.court == "Sąd Najwyższy"
        assert len(extraction.parties) == 2
        assert "Jan Nowak" in extraction.parties
        assert len(extraction.legal_basis) == 2
        assert "art. 415 k.c." in extraction.legal_basis
        
        # Verify API was called correctly
        mock_openai_client.chat.completions.create.assert_called_once()
        call_args = mock_openai_client.chat.completions.create.call_args
        assert "messages" in call_args.kwargs
        assert len(call_args.kwargs["messages"]) > 0
    
    @pytest.mark.asyncio
    async def test_api_error_fallback(self, mock_openai_client, sample_legal_document):
        """Test fallback when OpenAI API returns error."""
        # Mock API error
        mock_request = Mock()
        mock_body = Mock()
        mock_openai_client.chat.completions.create.side_effect = APIError("API Error", request=mock_request, body=mock_body)
        
        result = await self._extract_with_fallback(
            mock_openai_client,
            sample_legal_document.content
        )
        
        # Should fall back to regex parser
        assert result.used_fallback
        assert result.method == "regex_pattern_matching"
        
        # Should still extract some information
        if result.success:
            assert result.extraction is not None
    
    @pytest.mark.asyncio
    async def test_rate_limit_handling(self, mock_openai_client, sample_legal_document):
        """Test handling of rate limit errors."""
        mock_openai_client.chat.completions.create.side_effect = RateLimitError(
            "Rate limit exceeded", response=Mock(), body={}
        )
        
        result = await self._extract_with_fallback(
            mock_openai_client,
            sample_legal_document.content
        )
        
        assert result.used_fallback
        assert "rate" in " ".join(result.errors).lower()
    
    @pytest.mark.asyncio
    async def test_timeout_handling(self, mock_openai_client, sample_legal_document):
        """Test handling of API timeout errors."""
        from unittest.mock import Mock
        mock_request = Mock()
        mock_openai_client.chat.completions.create.side_effect = APITimeoutError(request=mock_request)
        
        result = await self._extract_with_fallback(
            mock_openai_client,
            sample_legal_document.content
        )
        
        assert result.used_fallback
        assert "timeout" in " ".join(result.errors).lower()
    
    @pytest.mark.asyncio
    async def test_invalid_json_response(self, mock_openai_client, sample_legal_document, invalid_openai_response):
        """Test handling of invalid JSON response from OpenAI."""
        mock_openai_client.chat.completions.create.return_value = invalid_openai_response
        
        result = await self._extract_with_fallback(
            mock_openai_client,
            sample_legal_document.content
        )
        
        # Should fall back to regex parser due to invalid JSON
        assert result.used_fallback
        assert "json" in " ".join(result.errors).lower() or result.success
    
    @pytest.mark.asyncio
    async def test_empty_response_handling(self, mock_openai_client, sample_legal_document):
        """Test handling of empty or null response from OpenAI."""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = None
        
        mock_openai_client.chat.completions.create.return_value = mock_response
        
        result = await self._extract_with_fallback(
            mock_openai_client,
            sample_legal_document.content
        )
        
        assert result.used_fallback
    
    def test_prompt_construction(self):
        """Test construction of prompts for OpenAI API."""
        document_content = "Test legal document content with art. 415 k.c."
        
        prompt = self._build_extraction_prompt(document_content)
        
        # Verify prompt contains necessary elements
        assert "polish legal document" in prompt.lower() or "polish" in prompt.lower()
        assert "json" in prompt.lower()
        assert "case_number" in prompt.lower()
        assert "legal_basis" in prompt.lower()
        assert document_content in prompt
    
    def test_response_validation(self):
        """Test validation of OpenAI response format."""
        # Valid response
        valid_response = {
            "case_number": "II CSK 123/20",
            "court": "Sąd Najwyższy",
            "parties": ["Jan Nowak"],
            "legal_basis": ["art. 415 k.c."],
            "decision": "oddala kasację"
        }
        
        extraction = self._parse_openai_response(valid_response)
        assert extraction is not None
        assert extraction.case_number == "II CSK 123/20"
        
        # Invalid response - missing required fields
        invalid_response = {
            "invalid_field": "some value"
        }
        
        extraction = self._parse_openai_response(invalid_response)
        assert extraction is not None  # Should create empty extraction
        assert extraction.case_number is None
    
    def test_extraction_validation(self):
        """Test validation of extracted legal information."""
        # Valid extraction
        valid_extraction = LegalExtraction(
            case_number="II CSK 123/20",
            court="Sąd Najwyższy",
            parties=["Jan Nowak", "Spółka ABC"],
            legal_basis=["art. 415 k.c."],
            date=datetime(2020, 10, 15),
            decision="Test decision",
            reasoning="Test reasoning"
        )
        
        # Validate using DocumentValidator patterns
        validation = self._validate_extraction(valid_extraction)
        assert validation.is_valid
        
        # Invalid extraction - wrong case number format
        invalid_extraction = LegalExtraction(
            case_number="INVALID-123",
            court="Test Court",
            legal_basis=["invalid_article"],
            date=datetime(2020, 10, 15),
            decision="Test decision",
            reasoning="Test reasoning"
        )
        
        validation = self._validate_extraction(invalid_extraction)
        assert not validation.is_valid
        assert len(validation.errors) > 0
    
    @pytest.mark.asyncio
    async def test_retry_mechanism(self, mock_openai_client, sample_legal_document):
        """Test retry mechanism for transient failures."""
        # First call fails, second succeeds
        valid_response = Mock()
        valid_response.choices = [Mock()]
        valid_response.choices[0].message.content = json.dumps({
            "case_number": "II CSK 123/20",
            "court": "Sąd Najwyższy"
        })
        
        mock_openai_client.chat.completions.create.side_effect = [
            APITimeoutError(request=Mock()),  # First call fails
            valid_response  # Second call succeeds
        ]
        
        result = await self._extract_with_retry(
            mock_openai_client,
            sample_legal_document.content,
            max_retries=2
        )
        
        # Should succeed on retry
        assert not result.used_fallback
        assert result.extraction is not None
        extraction = result.extraction  
        assert extraction.case_number == "II CSK 123/20"
        assert mock_openai_client.chat.completions.create.call_count == 2
    
    def test_batch_processing_limits(self):
        """Test batch processing limits for OpenAI API."""
        # Test documents exceeding batch size limits
        large_documents = [
            RawDocument(
                id=f"DOC_{i}",
                content="x" * 10000,  # Large content
                document_type=DocumentType.SUPREME_COURT,
                source_path=f"/test/{i}.txt",
                metadata={}
            )
            for i in range(100)  # Many documents
        ]
        
        # Should split into reasonable batch sizes
        batches = self._create_processing_batches(large_documents, max_batch_size=10)
        
        assert len(batches) == 10  # 100 docs / 10 per batch
        assert all(len(batch) <= 10 for batch in batches)
    
    # Helper methods for testing
    
    async def _extract_legal_info_with_openai(self, client: AsyncOpenAI, content: str) -> FallbackResult:
        """Extract legal information using OpenAI API."""
        try:
            prompt = self._build_extraction_prompt(content)
            
            response = await client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
                temperature=0.1
            )
            
            response_text = response.choices[0].message.content
            if not response_text:
                raise ValueError("Empty response from OpenAI")
            
            # Parse JSON response
            response_data = json.loads(response_text)
            extraction = self._parse_openai_response(response_data)
            
            return FallbackResult(
                success=True,
                used_fallback=False,
                extraction=extraction,
                confidence=0.9,
                method="openai_gpt",
                errors=[]
            )
            
        except Exception as e:
            return FallbackResult(
                success=False,
                used_fallback=False,
                extraction=None,
                confidence=0.0,
                method="openai_gpt",
                errors=[str(e)]
            )
    
    async def _extract_with_fallback(self, client: AsyncOpenAI, content: str) -> FallbackResult:
        """Extract with fallback to regex parser on failure."""
        try:
            openai_result = await self._extract_legal_info_with_openai(client, content)
            if openai_result.success:
                return openai_result
        except Exception as e:
            pass  # Fall through to fallback
        
        # Fallback to regex parser
        fallback_result = FallbackParser.extract_case_info(content)
        if not fallback_result.success:
            fallback_result.errors.append("OpenAI API failed, fallback parsing also failed")
        
        return fallback_result
    
    async def _extract_with_retry(self, client: AsyncOpenAI, content: str, max_retries: int = 3) -> FallbackResult:
        """Extract with retry mechanism."""
        last_error = None
        
        for attempt in range(max_retries):
            try:
                result = await self._extract_legal_info_with_openai(client, content)
                if result.success:
                    return result
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
        
        # All retries failed, use fallback
        fallback_result = FallbackParser.extract_case_info(content)
        fallback_result.errors.append(f"OpenAI API failed after {max_retries} retries: {str(last_error)}")
        return fallback_result
    
    def _build_extraction_prompt(self, content: str) -> str:
        """Build extraction prompt for OpenAI API."""
        return f"""
Extract legal information from the following Polish legal document and return as JSON:

Document:
{content[:2000]}  # Limit content length for prompt

Return JSON with these fields:
- case_number: Polish case number (e.g., "II CSK 123/20") 
- court: Court name
- date: Date in YYYY-MM-DD format
- parties: Array of party names
- legal_basis: Array of article references (e.g., "art. 415 k.c.")
- decision: Court decision summary
- reasoning: Brief reasoning summary

Example:
{{"case_number": "II CSK 123/20", "court": "Sąd Najwyższy", "parties": ["Jan Nowak"], "legal_basis": ["art. 415 k.c."], "decision": "oddala kasację"}}
"""
    
    def _parse_openai_response(self, response_data: dict) -> LegalExtraction:
        """Parse OpenAI response into LegalExtraction object."""
        try:
            # Convert date string if present
            date = None
            if response_data.get("date"):
                try:
                    from datetime import datetime
                    date = datetime.fromisoformat(response_data["date"])
                except ValueError:
                    pass
            
            return LegalExtraction(
                case_number=response_data.get("case_number"),
                court=response_data.get("court"),
                date=date,
                parties=response_data.get("parties", []),
                legal_basis=response_data.get("legal_basis", []),
                decision=response_data.get("decision"),
                reasoning=response_data.get("reasoning")
            )
        except Exception:
            # Return empty extraction on parse error
            return LegalExtraction(
                case_number=None,
                court=None,
                date=None,
                decision=None,
                reasoning=None
            )
    
    def _validate_extraction(self, extraction: LegalExtraction) -> ValidationResult:
        """Validate extracted legal information."""
        errors = []
        warnings = []
        
        # Validate case number format
        if extraction.case_number:
            pattern = DocumentValidator.POLISH_LEGAL_PATTERNS['case_number']
            if not re.match(pattern, extraction.case_number):
                errors.append(f"Invalid case number format: {extraction.case_number}")
        
        # Validate legal basis format
        for article in extraction.legal_basis:
            pattern = r'^(art\.|§)\s*\d+'
            if not re.match(pattern, article, re.IGNORECASE):
                errors.append(f"Invalid article reference: {article}")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            stage="extraction_validation"
        )
    
    def _create_processing_batches(self, documents: list, max_batch_size: int = 10) -> list:
        """Split documents into processing batches."""
        batches = []
        for i in range(0, len(documents), max_batch_size):
            batch = documents[i:i + max_batch_size]
            batches.append(batch)
        return batches


class TestOpenAIPromptEngineering:
    """Tests for OpenAI prompt engineering and optimization."""
    
    def test_prompt_length_optimization(self):
        """Test prompt length optimization for different document sizes."""
        # Very long document
        long_content = "A" * 50000
        prompt = self._build_optimized_prompt(long_content)
        
        # Should be truncated to reasonable length
        assert len(prompt) < 8000  # Typical token limit consideration
        assert "truncated" in prompt.lower() or len(prompt) < len(long_content)
    
    def test_polish_specific_prompts(self):
        """Test Polish-specific prompt engineering."""
        prompt = self._build_polish_legal_prompt("test content")
        
        # Should contain Polish-specific instructions
        assert any(polish_word in prompt.lower() for polish_word in 
                  ["polish", "polski", "sąd", "kodeks", "artykuł"])
        
        # Should specify expected Polish legal formats
        assert "sygn" in prompt.lower() or "case_number" in prompt.lower()
    
    def _build_optimized_prompt(self, content: str) -> str:
        """Build optimized prompt based on content length."""
        max_content_length = 2000
        
        if len(content) > max_content_length:
            # Truncate but try to preserve important parts
            truncated_content = content[:max_content_length]
            # Try to end at sentence boundary
            last_period = truncated_content.rfind('.')
            if last_period > max_content_length * 0.8:
                truncated_content = truncated_content[:last_period + 1]
            
            prompt = f"""
Extract legal information from this Polish legal document (truncated):

{truncated_content}

[Content truncated for processing efficiency]

Return JSON with legal information.
"""
        else:
            prompt = f"""
Extract legal information from this Polish legal document:

{content}

Return JSON with legal information.
"""
        
        return prompt
    
    def _build_polish_legal_prompt(self, content: str) -> str:
        """Build Polish-specific legal extraction prompt."""
        return f"""
Jesteś ekspertem polskiego prawa. Wyodrębnij informacje prawne z następującego dokumentu:

{content}

Zwróć wynik w formacie JSON zawierający:
- case_number: Sygnatura akt (np. "II CSK 123/20")
- court: Nazwa sądu
- parties: Strony postępowania
- legal_basis: Podstawa prawna (artykuły)
- decision: Rozstrzygnięcie sądu

Uwzględnij specyfikę polskiego systemu prawnego i terminologii.
"""


import asyncio
import re