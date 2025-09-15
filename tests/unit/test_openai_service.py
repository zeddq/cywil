"""
Unit tests for OpenAI service
"""

import json
import pytest
from unittest.mock import Mock, patch, AsyncMock
from pydantic import BaseModel, Field
from typing import List

from app.services.openai_client import OpenAIService, OpenAIError, get_openai_service
from app.core.config_service import get_config


# Test model for structured output
class TestModel(BaseModel):
    message: str = Field(description="A test message")
    count: int = Field(description="A test count")


class TestModelList(BaseModel):
    items: List[TestModel] = Field(description="List of test models")


class TestOpenAIService:
    """Test suite for OpenAI service"""

    @pytest.fixture
    def mock_config(self):
        """Mock configuration"""
        with patch('app.services.openai_client.get_config') as mock:
            config = Mock()
            config.openai.api_key.get_secret_value.return_value = "test-api-key"
            config.openai.max_retries = 3
            config.openai.timeout = 60
            mock.return_value = config
            yield config

    @pytest.fixture
    def openai_service(self, mock_config):
        """Create OpenAI service instance"""
        with patch('app.services.openai_client.OpenAI') as mock_openai:
            with patch('app.services.openai_client.AsyncOpenAI') as mock_async_openai:
                service = OpenAIService()
                service.client = Mock()
                service.async_client = AsyncMock()
                yield service

    def test_init_with_valid_api_key(self, mock_config):
        """Test initialization with valid API key"""
        with patch('app.services.openai_client.OpenAI'):
            with patch('app.services.openai_client.AsyncOpenAI'):
                service = OpenAIService()
                assert service is not None

    def test_init_without_api_key(self):
        """Test initialization fails without API key"""
        with patch('app.services.openai_client.get_config') as mock_config:
            config = Mock()
            config.openai.api_key.get_secret_value.return_value = ""
            mock_config.return_value = config
            
            with pytest.raises(OpenAIError, match="OpenAI API key is required"):
                OpenAIService()

    def test_parse_structured_output_success(self, openai_service):
        """Test successful structured output parsing"""
        # Mock successful response
        mock_response = Mock()
        mock_response.parsed = TestModel(message="test", count=42)
        
        openai_service.client.beta.chat.completions.parse.return_value = mock_response
        
        messages = [{"role": "user", "content": "Test message"}]
        result = openai_service.parse_structured_output(
            model="o3-mini",
            messages=messages,
            response_format=TestModel
        )
        
        assert isinstance(result, TestModel)
        assert result.message == "test"
        assert result.count == 42

    def test_parse_structured_output_none_response(self, openai_service):
        """Test structured output parsing when response.parsed is None"""
        # Mock response with None parsed
        mock_response = Mock()
        mock_response.parsed = None
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = '{"message": "fallback", "count": 1}'
        
        openai_service.client.beta.chat.completions.parse.return_value = mock_response
        
        messages = [{"role": "user", "content": "Test message"}]
        result = openai_service.parse_structured_output(
            model="o3-mini",
            messages=messages,
            response_format=TestModel
        )
        
        assert isinstance(result, TestModel)
        assert result.message == "fallback"
        assert result.count == 1

    def test_parse_structured_output_fallback(self, openai_service):
        """Test fallback parsing when structured parsing fails"""
        # Mock structured parsing failure
        openai_service.client.beta.chat.completions.parse.side_effect = Exception("API Error")
        
        # Mock fallback regular completion
        mock_fallback_response = Mock()
        mock_fallback_response.choices = [Mock()]
        mock_fallback_response.choices[0].message.content = '{"message": "fallback", "count": 1}'
        
        openai_service.client.chat.completions.create.return_value = mock_fallback_response
        
        messages = [{"role": "user", "content": "Test message"}]
        result = openai_service.parse_structured_output(
            model="o3-mini",
            messages=messages,
            response_format=TestModel
        )
        
        assert isinstance(result, TestModel)
        assert result.message == "fallback"
        assert result.count == 1

    def test_parse_structured_output_complete_failure(self, openai_service):
        """Test complete failure of both structured and fallback parsing"""
        # Mock both parsing methods failing
        openai_service.client.beta.chat.completions.parse.side_effect = Exception("API Error")
        openai_service.client.chat.completions.create.side_effect = Exception("Fallback Error")
        
        messages = [{"role": "user", "content": "Test message"}]
        
        with pytest.raises(OpenAIError):
            openai_service.parse_structured_output(
                model="o3-mini",
                messages=messages,
                response_format=TestModel
            )

    @pytest.mark.asyncio
    async def test_async_parse_structured_output_success(self, openai_service):
        """Test async structured output parsing"""
        # Mock successful response
        mock_response = Mock()
        mock_response.parsed = TestModel(message="async_test", count=99)
        
        openai_service.async_client.beta.chat.completions.parse.return_value = mock_response
        
        messages = [{"role": "user", "content": "Test message"}]
        result = await openai_service.async_parse_structured_output(
            model="o3-mini",
            messages=messages,
            response_format=TestModel
        )
        
        assert isinstance(result, TestModel)
        assert result.message == "async_test"
        assert result.count == 99

    def test_fallback_parse_json(self, openai_service):
        """Test JSON fallback parsing"""
        content = '{"message": "parsed", "count": 5}'
        result = openai_service._fallback_parse(content, TestModel)
        
        assert isinstance(result, TestModel)
        assert result.message == "parsed"
        assert result.count == 5

    def test_fallback_parse_with_markdown(self, openai_service):
        """Test JSON fallback parsing with markdown code blocks"""
        content = '```json\n{"message": "markdown", "count": 3}\n```'
        result = openai_service._fallback_parse(content, TestModel)
        
        assert isinstance(result, TestModel)
        assert result.message == "markdown"
        assert result.count == 3

    def test_fallback_parse_invalid_json(self, openai_service):
        """Test fallback parsing with invalid JSON"""
        content = 'invalid json content'
        
        with pytest.raises(OpenAIError, match="Failed to parse response as JSON"):
            openai_service._fallback_parse(content, TestModel)

    def test_create_completion(self, openai_service):
        """Test basic completion creation"""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "Test response"
        
        openai_service.client.chat.completions.create.return_value = mock_response
        
        messages = [{"role": "user", "content": "Test message"}]
        result = openai_service.create_completion(
            model="o3-mini",
            messages=messages
        )
        
        assert result == mock_response

    @pytest.mark.asyncio
    async def test_async_create_completion(self, openai_service):
        """Test async completion creation"""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "Async test response"
        
        openai_service.async_client.chat.completions.create.return_value = mock_response
        
        messages = [{"role": "user", "content": "Test message"}]
        result = await openai_service.async_create_completion(
            model="o3-mini",
            messages=messages
        )
        
        assert result == mock_response

    def test_process_document_structured(self, openai_service):
        """Test document processing with structured output"""
        mock_response = Mock()
        mock_response.parsed = TestModel(message="document processed", count=1)
        
        openai_service.client.beta.chat.completions.parse.return_value = mock_response
        
        result = openai_service.process_document(
            document_text="Test document",
            model="o3-mini",
            response_format=TestModel,
            prompt_template="Analyze: {document_text}"
        )
        
        assert isinstance(result, TestModel)
        assert result.message == "document processed"

    def test_process_document_text_only(self, openai_service):
        """Test document processing with text-only output"""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "Document analysis complete"
        
        openai_service.client.chat.completions.create.return_value = mock_response
        
        result = openai_service.process_document(
            document_text="Test document",
            model="o3-mini",
        )
        
        assert result == "Document analysis complete"

    @pytest.mark.asyncio
    async def test_async_process_document(self, openai_service):
        """Test async document processing"""
        mock_response = Mock()
        mock_response.parsed = TestModel(message="async document processed", count=2)
        
        openai_service.async_client.beta.chat.completions.parse.return_value = mock_response
        
        result = await openai_service.async_process_document(
            document_text="Test document",
            model="o3-mini",
            response_format=TestModel
        )
        
        assert isinstance(result, TestModel)
        assert result.message == "async document processed"

    def test_retry_logic_success_after_failure(self, openai_service):
        """Test that retry logic works when call fails then succeeds"""
        # First call fails, second succeeds
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "Success after retry"
        
        openai_service.client.chat.completions.create.side_effect = [
            Exception("First attempt fails"),
            mock_response
        ]
        
        messages = [{"role": "user", "content": "Test message"}]
        result = openai_service.create_completion(
            model="o3-mini",
            messages=messages
        )
        
        assert result == mock_response

    def test_get_openai_service_singleton(self, mock_config):
        """Test singleton pattern for get_openai_service"""
        with patch('app.services.openai_client.OpenAI'):
            with patch('app.services.openai_client.AsyncOpenAI'):
                service1 = get_openai_service()
                service2 = get_openai_service()
                
                assert service1 is service2