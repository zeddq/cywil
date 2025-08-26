"""
AI Client Factory for managing different AI providers
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Type, Union
from enum import Enum

from pydantic import BaseModel

from app.services.openai_client import OpenAIService


class AIProvider(str, Enum):
    """Supported AI providers"""
    OPENAI = "openai"
    # Future providers can be added here
    # ANTHROPIC = "anthropic"
    # GOOGLE = "google"


class AIClientInterface(ABC):
    """Abstract interface for AI clients"""
    
    @abstractmethod
    def parse_structured_output(
        self,
        model: str,
        messages: List[Dict[str, str]],
        response_format: Type[BaseModel],
        **kwargs
    ) -> BaseModel:
        """Parse structured output from the AI provider"""
        pass
    
    @abstractmethod
    async def async_parse_structured_output(
        self,
        model: str,
        messages: List[Dict[str, str]],
        response_format: Type[BaseModel],
        **kwargs
    ) -> BaseModel:
        """Async version of parse_structured_output"""
        pass
    
    @abstractmethod
    def create_completion(
        self,
        model: str,
        messages: List[Dict[str, str]],
        **kwargs
    ):
        """Create a completion from the AI provider"""
        pass
    
    @abstractmethod
    async def async_create_completion(
        self,
        model: str,
        messages: List[Dict[str, str]],
        **kwargs
    ):
        """Async version of create_completion"""
        pass
    
    @abstractmethod
    def process_document(
        self,
        document_text: str,
        model: str,
        response_format: Optional[Type[BaseModel]] = None,
        prompt_template: str = "",
        **kwargs
    ) -> Union[BaseModel, str]:
        """High-level document processing"""
        pass
    
    @abstractmethod
    async def async_process_document(
        self,
        document_text: str,
        model: str,
        response_format: Optional[Type[BaseModel]] = None,
        prompt_template: str = "",
        **kwargs
    ) -> Union[BaseModel, str]:
        """Async version of process_document"""
        pass


class OpenAIClientAdapter(AIClientInterface):
    """Adapter for OpenAI service to implement the common interface"""
    
    def __init__(self, openai_service: OpenAIService):
        self.service = openai_service
    
    def parse_structured_output(
        self,
        model: str,
        messages: List[Dict[str, str]],
        response_format: Type[BaseModel],
        **kwargs
    ) -> BaseModel:
        return self.service.parse_structured_output(model, messages, response_format, **kwargs)
    
    async def async_parse_structured_output(
        self,
        model: str,
        messages: List[Dict[str, str]],
        response_format: Type[BaseModel],
        **kwargs
    ) -> BaseModel:
        return await self.service.async_parse_structured_output(model, messages, response_format, **kwargs)
    
    def create_completion(
        self,
        model: str,
        messages: List[Dict[str, str]],
        **kwargs
    ):
        return self.service.create_completion(model, messages, **kwargs)
    
    async def async_create_completion(
        self,
        model: str,
        messages: List[Dict[str, str]],
        **kwargs
    ):
        return await self.service.async_create_completion(model, messages, **kwargs)
    
    def process_document(
        self,
        document_text: str,
        model: str,
        response_format: Optional[Type[BaseModel]] = None,
        prompt_template: str = "",
        **kwargs
    ) -> Union[BaseModel, str]:
        return self.service.process_document(document_text, model, response_format, prompt_template, **kwargs)
    
    async def async_process_document(
        self,
        document_text: str,
        model: str,
        response_format: Optional[Type[BaseModel]] = None,
        prompt_template: str = "",
        **kwargs
    ) -> Union[BaseModel, str]:
        return await self.service.async_process_document(document_text, model, response_format, prompt_template, **kwargs)


class AIClientFactory:
    """Factory for creating AI clients"""
    
    _clients: Dict[AIProvider, AIClientInterface] = {}
    
    @classmethod
    def get_client(cls, provider: AIProvider = AIProvider.OPENAI) -> AIClientInterface:
        """
        Get an AI client for the specified provider
        
        Args:
            provider: The AI provider to use
        
        Returns:
            AIClientInterface implementation for the provider
        
        Raises:
            ValueError: If the provider is not supported
        """
        if provider in cls._clients:
            return cls._clients[provider]
        
        if provider == AIProvider.OPENAI:
            from app.services.openai_client import get_openai_service
            client = OpenAIClientAdapter(get_openai_service())
            cls._clients[provider] = client
            return client
        
        # Future providers can be added here
        # elif provider == AIProvider.ANTHROPIC:
        #     return AnthropicClientAdapter()
        # elif provider == AIProvider.GOOGLE:
        #     return GoogleClientAdapter()
        
        raise ValueError(f"Unsupported AI provider: {provider}")
    
    @classmethod
    def get_openai_client(cls) -> OpenAIService:
        """Convenience method to get OpenAI client directly"""
        from app.services.openai_client import get_openai_service
        return get_openai_service()
    
    @classmethod
    def clear_cache(cls):
        """Clear the client cache (useful for testing)"""
        cls._clients.clear()


# Convenience function
def get_ai_client(provider: AIProvider = AIProvider.OPENAI) -> AIClientInterface:
    """Get an AI client instance"""
    return AIClientFactory.get_client(provider)