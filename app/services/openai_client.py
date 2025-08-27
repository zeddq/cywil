"""
OpenAI SDK Integration Service
"""

import asyncio
import json
import logging
from typing import Awaitable, Any, Callable, Dict, List, Optional, Type, TypeVar, Union

from openai import AsyncOpenAI, OpenAI
from openai.types.chat import ChatCompletion
from openai.types.responses import ParsedResponse
from pydantic import BaseModel
from tenacity import (
    retry,
    stop_after_attempt,
    wait_random_exponential,
    retry_if_exception_type,
)

from app.core.config_service import get_config
from app.core.exceptions import ServiceError

logger = logging.getLogger(__name__)


class OpenAIError(ServiceError):
    """OpenAI service specific errors"""

    pass


class OpenAIService:
    """
    OpenAI SDK service with retry logic, error handling, and structured output parsing.
    """

    def __init__(self):
        """Initialize OpenAI client with configuration"""
        self.config = get_config()
        api_key = self.config.openai.api_key.get_secret_value()

        if not api_key:
            raise OpenAIError("OpenAI", "OpenAI API key is required but not configured")

        # Initialize both sync and async clients
        self.client = OpenAI(
            api_key=api_key,
            max_retries=self.config.openai.max_retries,
            timeout=self.config.openai.timeout,
        )

        self.async_client = AsyncOpenAI(
            api_key=api_key,
            max_retries=self.config.openai.max_retries,
            timeout=self.config.openai.timeout,
        )

        logger.info("OpenAI service initialized successfully")

    T = TypeVar("T")

    @retry(
        wait=wait_random_exponential(min=1, max=60),
        stop=stop_after_attempt(6),
        retry=retry_if_exception_type(
            (Exception,)  # Catch all OpenAI exceptions for retry
        ),
        reraise=True,
    )
    def call_with_retry(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Wrapper for API calls with exponential backoff"""
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"OpenAI API call failed: {e}")
            # Let tenacity handle the retry
            raise

    @retry(
        wait=wait_random_exponential(min=1, max=60),
        stop=stop_after_attempt(6),
        retry=retry_if_exception_type(
            (Exception,)  # Catch all OpenAI exceptions for retry
        ),
        reraise=True,
    )
    async def async_call_with_retry(
        self, func: Callable[..., Awaitable[T]], *args, **kwargs
    ) -> T:
        """Async wrapper for API calls with exponential backoff"""
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            logger.error(f"OpenAI API call failed: {e}")
            # Let tenacity handle the retry
            raise

    def parse_structured_output(
        self,
        model: str,
        messages: List[Dict[str, str]],
        response_format: Type[BaseModel],
        **kwargs,
    ) -> BaseModel:
        """
        Parse structured output using OpenAI's beta.chat.completions.parse

        Args:
            model: The model to use (e.g., "o3-mini")
            messages: List of messages in OpenAI format
            response_format: Pydantic model class for structured output
            **kwargs: Additional arguments to pass to the API

        Returns:
            Parsed response as the specified Pydantic model
        """
        try:
            # Use the new structured output parsing
            response = self.call_with_retry(
                self.client.responses.parse,
                model=model,
                input=messages,
                response_format=response_format,
                **kwargs,
            )

            if response.output_parsed is None:
                logger.warning(
                    "Structured output parsing returned None, attempting fallback"
                )
                return self._fallback_parse(
                    response.choices[0].message.content or "", response_format
                )

            return response.parsed

        except Exception as e:
            logger.error(f"Failed to parse structured output: {e}")
            # Attempt fallback parsing if structured parsing fails
            try:
                regular_response = self.call_with_retry(
                    self.client.chat.completions.create,
                    model=model,
                    messages=messages,
                    **kwargs,
                )
                content = regular_response.choices[0].message.content or ""
                return self._fallback_parse(content, response_format)
            except Exception as fallback_error:
                logger.error(f"Fallback parsing also failed: {fallback_error}")
                raise OpenAIError(
                    "OpenAI",
                    f"Both structured and fallback parsing failed: {e}, {fallback_error}",
                )

    async def async_parse_structured_output(
        self,
        model: str,
        messages: List[Dict[str, str]],
        response_format: Type[BaseModel],
        **kwargs,
    ) -> BaseModel:
        """
        Async version of parse_structured_output
        """
        try:
            # Use the new structured output parsing
            response = await self.async_call_with_retry(
                self.async_client.responses.parse,
                model=model,
                input=messages,
                response_format=response_format,
                **kwargs,
            )

            if response.output_parsed is None:
                logger.warning(
                    "Structured output parsing returned None, attempting fallback"
                )
                return self._fallback_parse(
                    "".join(str(response.output)), response_format
                )

            return response.output_parsed

        except Exception as e:
            logger.error(f"Failed to parse structured output: {e}")
            # Attempt fallback parsing if structured parsing fails
            try:
                regular_response = await self.async_call_with_retry(
                    self.async_client.chat.completions.create,
                    model=model,
                    messages=messages,
                    **kwargs,
                )
                content = "".join(str(regular_response.choices[0].message.content))
                return self._fallback_parse(content, response_format)
            except Exception as fallback_error:
                logger.error(f"Fallback parsing also failed: {fallback_error}")
                raise OpenAIError(
                    "OpenAI",
                    f"Both structured and fallback parsing failed: {e}, {fallback_error}",
                )

    def _fallback_parse(
        self, content: str, response_format: Type[BaseModel]
    ) -> BaseModel:
        """
        Fallback JSON parsing when structured output fails

        Args:
            content: Raw response content from OpenAI
            response_format: Pydantic model class

        Returns:
            Parsed response as the specified Pydantic model
        """
        try:
            # Clean up the content - remove markdown code blocks if present
            cleaned_content = content.strip()
            if cleaned_content.startswith("```json"):
                cleaned_content = cleaned_content[7:]
            if cleaned_content.startswith("```"):
                cleaned_content = cleaned_content[3:]
            if cleaned_content.endswith("```"):
                cleaned_content = cleaned_content[:-3]

            # Try to parse as JSON
            parsed_json = json.loads(cleaned_content.strip())
            return response_format.model_validate(parsed_json)

        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse JSON from response: {e}")
            logger.debug(f"Raw content: {content}")
            raise OpenAIError("OpenAI", f"Failed to parse response as JSON: {e}")

    def create_completion(
        self, model: str, messages: List[Dict[str, str]], **kwargs
    ) -> ChatCompletion:
        """
        Create a standard chat completion

        Args:
            model: The model to use
            messages: List of messages in OpenAI format
            **kwargs: Additional arguments to pass to the API

        Returns:
            ChatCompletion response
        """
        return self.call_with_retry(
            self.client.chat.completions.create,
            model=model,
            messages=messages,
            **kwargs,
        )

    async def async_create_completion(
        self, model: str, messages: List[Dict[str, str]], **kwargs
    ) -> ChatCompletion:
        """
        Async version of create_completion
        """
        return await self.async_call_with_retry(
            self.async_client.chat.completions.create,
            model=model,
            messages=messages,
            **kwargs,
        )

    def responses_parse(
        self, model: str, input: List[Dict[str, str]], **kwargs
    ) -> ParsedResponse:
        """
        Parse responses using OpenAI's beta.chat.completions.parse
        """
        return self.call_with_retry(
            self.client.responses.parse, model=model, input=input, **kwargs
        )

    async def async_responses_parse(
        self, model: str, input: List[Dict[str, str]], **kwargs
    ) -> ParsedResponse:
        """
        Async version of responses_parse
        """
        return await self.async_call_with_retry(
            self.async_client.responses.parse, model=model, input=input, **kwargs
        )

    def process_document(
        self,
        document_text: str,
        model: str = "o3-mini",
        response_format: Optional[Type[BaseModel]] = None,
        prompt_template: str = "",
        **kwargs,
    ) -> Union[BaseModel, str]:
        """
        High-level document processing method

        Args:
            document_text: The document text to process
            model: OpenAI model to use
            response_format: Optional Pydantic model for structured output
            prompt_template: Template for the prompt
            **kwargs: Additional arguments

        Returns:
            Structured response if response_format provided, otherwise raw string
        """
        if not prompt_template:
            prompt_template = "Analyze the following document:\n\n{document_text}"

        prompt = prompt_template.format(document_text=document_text)
        messages = [{"role": "user", "content": prompt}]

        if response_format:
            return self.parse_structured_output(
                model=model,
                messages=messages,
                response_format=response_format,
                **kwargs,
            )
        else:
            response = self.create_completion(model=model, messages=messages, **kwargs)
            content = response.choices[0].message.content
            if content is None:
                raise OpenAIError("OpenAI", "Received empty response content from API")
            return content

    async def async_process_document(
        self,
        document_text: str,
        model: str = "o3-mini",
        response_format: Optional[Type[BaseModel]] = None,
        prompt_template: str = "",
        **kwargs,
    ) -> Union[BaseModel, str]:
        """
        Async version of process_document
        """
        if not prompt_template:
            prompt_template = "Analyze the following document:\n\n{document_text}"

        prompt = prompt_template.format(document_text=document_text)
        messages = [{"role": "user", "content": prompt}]

        if response_format:
            return await self.async_parse_structured_output(
                model=model,
                messages=messages,
                response_format=response_format,
                **kwargs,
            )
        else:
            response = await self.async_create_completion(
                model=model, messages=messages, **kwargs
            )
            content = response.choices[0].message.content
            if content is None:
                raise OpenAIError("OpenAI", "Received empty response content from API")
            return content


# Global service instance
_openai_service: Optional[OpenAIService] = None


def get_openai_service() -> OpenAIService:
    """Get or create OpenAI service singleton"""
    global _openai_service
    if _openai_service is None:
        _openai_service = OpenAIService()
    return _openai_service
