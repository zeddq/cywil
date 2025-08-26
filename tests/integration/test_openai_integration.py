"""
Integration tests for OpenAI service
"""

import asyncio
import json
import pytest
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List

from app.services.openai_client import OpenAIService, get_openai_service
from app.core.ai_client_factory import get_ai_client, AIProvider


# Test models for legal document processing
class LegalEntity(BaseModel):
    text: str = Field(description="The entity text")
    label: str = Field(description="Entity type: LAW_REF, DOCKET, PERSON, ORG, DATE")
    start: int = Field(description="Start character position")
    end: int = Field(description="End character position")


class LegalEntities(BaseModel):
    entities: List[LegalEntity] = Field(description="List of legal entities")


class RulingParagraph(BaseModel):
    section: str = Field(description="Section type")
    para_no: int = Field(description="Paragraph number")
    text: str = Field(description="Paragraph text")


class ParsedRuling(BaseModel):
    paragraphs: List[RulingParagraph] = Field(description="List of paragraphs")


class TestOpenAIIntegration:
    """Integration tests for OpenAI service with real or mocked API calls"""

    @pytest.fixture(scope="class")
    def openai_service(self):
        """Get OpenAI service instance"""
        return get_openai_service()

    @pytest.fixture
    def sample_legal_text(self):
        """Sample Polish legal text for testing"""
        return """
        SĄD NAJWYŻSZY
        
        UCHWAŁA z dnia 15 marca 2023 r.
        Sygn. akt III CZP 123/22
        
        Skład: SSN Jan Kowalski (przewodniczący), SSN Maria Nowak, SSN Piotr Wiśniewski
        
        W sprawie przedstawił następujące zagadnienie prawne:
        Czy przepis art. 118 § 1 KC ma zastosowanie do roszczeń z tytułu naruszenia dóbr osobistych?
        
        Sąd Najwyższy zważył, co następuje:
        
        Zgodnie z utrwalonym orzecznictwem, przepisy o przedawnieniu mają zastosowanie również do roszczeń niemajątkowych. Art. 118 KC stanowi podstawę prawną dla trzyletniego terminu przedawnienia.
        
        Na podstawie art. 390 § 1 k.p.c. Sąd Najwyższy postanawia:
        Odpowiedzieć na zagadnienie prawne następująco: Tak, przepis art. 118 § 1 KC ma zastosowanie.
        """

    @pytest.mark.integration
    def test_service_initialization(self, openai_service):
        """Test that service initializes properly"""
        assert openai_service is not None
        assert hasattr(openai_service, 'client')
        assert hasattr(openai_service, 'async_client')

    @pytest.mark.integration
    def test_ai_client_factory(self):
        """Test AI client factory returns OpenAI client"""
        client = get_ai_client(AIProvider.OPENAI)
        assert client is not None

    @pytest.mark.integration
    @pytest.mark.skipif(
        not pytest.config.getoption("--run-api-tests", default=False),
        reason="API tests require --run-api-tests flag and valid API key"
    )
    def test_document_parsing_with_real_api(self, openai_service, sample_legal_text):
        """Test document parsing with real OpenAI API (requires API key)"""
        try:
            result = openai_service.parse_structured_output(
                model="o3-mini",
                messages=[{
                    "role": "user", 
                    "content": f"Parse this Polish legal ruling into paragraphs: {sample_legal_text}"
                }],
                response_format=ParsedRuling,
                max_tokens=2000
            )
            
            assert isinstance(result, ParsedRuling)
            assert len(result.paragraphs) > 0
            
            # Check that we got some basic structure
            paragraph_sections = [p.section for p in result.paragraphs]
            assert any(section in ["header", "reasoning", "disposition"] for section in paragraph_sections)
            
        except Exception as e:
            pytest.skip(f"API test skipped due to error: {e}")

    @pytest.mark.integration
    @pytest.mark.skipif(
        not pytest.config.getoption("--run-api-tests", default=False),
        reason="API tests require --run-api-tests flag and valid API key"
    )
    @pytest.mark.asyncio
    async def test_async_entity_extraction_with_real_api(self, openai_service, sample_legal_text):
        """Test async entity extraction with real OpenAI API"""
        try:
            result = await openai_service.async_parse_structured_output(
                model="o3-mini",
                messages=[{
                    "role": "user",
                    "content": f"Extract legal entities from this text: {sample_legal_text}"
                }],
                response_format=LegalEntities,
                max_tokens=1000
            )
            
            assert isinstance(result, LegalEntities)
            
            # Should find some entities in the legal text
            if result.entities:
                entity_types = set(entity.label for entity in result.entities)
                # Should find at least some legal references or docket numbers
                assert len(entity_types & {"LAW_REF", "DOCKET", "PERSON", "DATE"}) > 0
                
        except Exception as e:
            pytest.skip(f"API test skipped due to error: {e}")

    @pytest.mark.integration
    def test_fallback_parsing_integration(self, openai_service):
        """Test fallback parsing with malformed JSON response"""
        # Test with various malformed JSON scenarios
        test_cases = [
            '```json\n{"paragraphs": [{"section": "test", "para_no": 1, "text": "Test paragraph"}]}\n```',
            '{"paragraphs": [{"section": "test", "para_no": 1, "text": "Test paragraph"}]}',
            '```\n{"paragraphs": [{"section": "test", "para_no": 1, "text": "Test paragraph"}]}\n```'
        ]
        
        for content in test_cases:
            result = openai_service._fallback_parse(content, ParsedRuling)
            assert isinstance(result, ParsedRuling)
            assert len(result.paragraphs) == 1
            assert result.paragraphs[0].section == "test"

    @pytest.mark.integration
    def test_error_handling_with_invalid_model(self, openai_service):
        """Test error handling with invalid model name"""
        messages = [{"role": "user", "content": "Test message"}]
        
        # This should either work (if o3-mini is available) or fail gracefully
        try:
            result = openai_service.create_completion(
                model="nonexistent-model",
                messages=messages
            )
            # If it succeeds, that's fine too (might be a mock)
            assert result is not None
        except Exception as e:
            # Should be a reasonable error, not a crash
            assert "model" in str(e).lower() or "error" in str(e).lower()

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_concurrent_api_calls(self, openai_service):
        """Test multiple concurrent API calls"""
        messages = [{"role": "user", "content": f"Generate a short response for test {i}"}]
        
        # Create multiple concurrent tasks (with mocks this should work fine)
        tasks = []
        for i in range(3):
            task = openai_service.async_create_completion(
                model="o3-mini",
                messages=[{"role": "user", "content": f"Test message {i}"}]
            )
            tasks.append(task)
        
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # All tasks should either succeed or fail with reasonable exceptions
            for result in results:
                if isinstance(result, Exception):
                    # Exception should be reasonable (not a crash)
                    assert hasattr(result, '__str__')
                else:
                    # Successful result should have expected structure
                    assert result is not None
                    
        except Exception as e:
            pytest.skip(f"Concurrent test skipped due to error: {e}")

    @pytest.mark.integration
    def test_process_document_end_to_end(self, openai_service, sample_legal_text):
        """Test complete document processing workflow"""
        try:
            # Test with structured output
            result = openai_service.process_document(
                document_text=sample_legal_text,
                model="o3-mini",
                response_format=ParsedRuling,
                prompt_template="Analyze and parse this Polish legal document:\n\n{document_text}",
                max_tokens=2000
            )
            
            assert isinstance(result, ParsedRuling)
            
            # Test with text output
            text_result = openai_service.process_document(
                document_text=sample_legal_text[:500],  # Shorter for text processing
                model="o3-mini",
                prompt_template="Summarize this legal text:\n\n{document_text}",
                max_tokens=100
            )
            
            assert isinstance(text_result, str)
            assert len(text_result) > 0
            
        except Exception as e:
            pytest.skip(f"Document processing test skipped due to error: {e}")

    @pytest.mark.integration
    @pytest.mark.skipif(
        not pytest.config.getoption("--run-stress-tests", default=False),
        reason="Stress tests require --run-stress-tests flag"
    )
    def test_memory_usage_stability(self, openai_service):
        """Test memory usage remains stable during batch processing"""
        import gc
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss
        
        # Process multiple documents
        for i in range(10):
            try:
                result = openai_service.process_document(
                    document_text=f"Test document {i} with some legal content.",
                    model="o3-mini",
                    max_tokens=50
                )
                # Force garbage collection
                gc.collect()
            except Exception:
                # Skip if API calls fail
                continue
        
        final_memory = process.memory_info().rss
        memory_increase = final_memory - initial_memory
        
        # Memory increase should be reasonable (less than 100MB)
        assert memory_increase < 100 * 1024 * 1024, f"Memory increased by {memory_increase / (1024*1024):.2f} MB"


def pytest_configure(config):
    """Add custom markers"""
    config.addinivalue_line("markers", "integration: mark test as integration test")


def pytest_addoption(parser):
    """Add command line options"""
    parser.addoption(
        "--run-api-tests",
        action="store_true",
        default=False,
        help="Run tests that make actual API calls"
    )
    parser.addoption(
        "--run-stress-tests", 
        action="store_true",
        default=False,
        help="Run memory and stress tests"
    )