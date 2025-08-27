"""
Abstract interface for embedding models to support multiple backends.
"""

import asyncio
from abc import ABC, abstractmethod
from typing import List, Optional, Any

import numpy as np


class EmbeddingModel(ABC):
    """Abstract base class for embedding models."""
    
    @abstractmethod
    async def create_embeddings(
        self, 
        texts: List[str],
        batch_size: int = 32
    ) -> np.ndarray:
        """Generate embeddings for text batch."""
        pass
    
    @abstractmethod
    def get_dimension(self) -> int:
        """Return embedding vector dimension."""
        pass
    
    @abstractmethod
    async def create_embedding_single(
        self,
        text: str
    ) -> np.ndarray:
        """Generate embedding for single text."""
        pass

    @abstractmethod
    async def warmup(self) -> None:
        """Warm up the model by running a test inference."""
        pass


class LocalEmbedder(EmbeddingModel):
    """SentenceTransformer-based embedder with async support."""
    
    def __init__(self, model_name: str = "paraphrase-multilingual-mpnet-base-v2"):
        self.model_name = model_name
        self._model: Optional[Any] = None
        self._lock = asyncio.Lock()
        self._dimension: Optional[int] = None
    
    async def _ensure_model_loaded(self):
        """Lazy load the model on first use."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            async with self._lock:
                if self._model is None:  # Double-check locking pattern
                    loop = asyncio.get_event_loop()
                    self._model = await loop.run_in_executor(
                        None, SentenceTransformer, self.model_name
                    )
    
    async def create_embeddings(
        self, 
        texts: List[str], 
        batch_size: int = 32
    ) -> np.ndarray:
        """Generate embeddings for text batch with async support."""

        await self._ensure_model_loaded()

        def _embedding_function():
            if self._model is None:
                raise RuntimeError("Model not initialized")
            return self._model.encode(texts, batch_size=batch_size, convert_to_numpy=True)
        
        if self._model is None:
            raise RuntimeError("Model not initialized")
        # Run CPU-intensive operation in thread pool
        loop = asyncio.get_event_loop()
        model = self._model
        if model is None:
            raise RuntimeError("Model not initialized")
        embeddings = await loop.run_in_executor(
            None, 
            _embedding_function
        )
        return embeddings
    
    async def create_embedding_single(self, text: str) -> np.ndarray:
        """Generate embedding for single text."""
        result = await self.create_embeddings([text])
        return result[0]
    
    def get_dimension(self) -> int:
        """Return embedding vector dimension."""
        if self._dimension is None:
            if self._model is None:
                # Default dimension for multilingual-mpnet-base-v2
                self._dimension = 768
            else:
                dimension = self._model.get_sentence_embedding_dimension()
                if dimension is None:
                    # Fallback in case sentence transformer returns None
                    self._dimension = 768
                else:
                    self._dimension = dimension
        return self._dimension if self._dimension is not None else 0
    
    async def warmup(self) -> None:
        """Warm up the model by running a test inference."""
        await self.create_embedding_single("test warmup")


class OpenAIEmbedder(EmbeddingModel):
    """OpenAI API-based embedder."""
    
    def __init__(self, api_key: str, model_name: str = "text-embedding-3-small"):
        self.model_name = model_name
        self._api_key = api_key
        self._client: Optional[Any] = None
        self._dimension = 1536  # Default for text-embedding-3-small
    
    async def _ensure_client_initialized(self):
        """Lazy initialize OpenAI client."""
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(api_key=self._api_key)
    
    async def create_embeddings(
        self, 
        texts: List[str], 
        batch_size: int = 32
    ) -> np.ndarray:
        """Generate embeddings using OpenAI API."""
        await self._ensure_client_initialized()
        
        # Ensure client is initialized
        if self._client is None:
            raise RuntimeError("OpenAI client not initialized")
            
        # Process in batches to avoid API limits
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            response = await self._client.embeddings.create(
                model=self.model_name,
                input=batch
            )
            batch_embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(batch_embeddings)
        
        return np.array(all_embeddings)
    
    async def create_embedding_single(self, text: str) -> np.ndarray:
        """Generate embedding for single text."""
        result = await self.create_embeddings([text])
        return result[0]
    
    def get_dimension(self) -> int:
        """Return embedding vector dimension."""
        return self._dimension
    
    async def warmup(self) -> None:
        """Warm up by testing API connection."""
        await self.create_embedding_single("test warmup")


class HuggingFaceEmbedder(EmbeddingModel):
    """HuggingFace Transformers-based embedder for future extension."""
    
    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model: Optional[Any] = None
        self._tokenizer: Optional[Any] = None
        self._lock = asyncio.Lock()
        self._dimension: Optional[int] = None
    
    async def _ensure_model_loaded(self):
        """Lazy load the model on first use."""
        if self._model is None:
            async with self._lock:
                if self._model is None:
                    from transformers import AutoModel, AutoTokenizer
                    import torch
                    
                    loop = asyncio.get_event_loop()
                    self._tokenizer, self._model = await loop.run_in_executor(
                        None, 
                        lambda: (
                            AutoTokenizer.from_pretrained(self.model_name),
                            AutoModel.from_pretrained(self.model_name)
                        )
                    )
                    # Set to eval mode for inference
                    if self._model is not None:
                        self._model.eval()
    
    async def create_embeddings(
        self, 
        texts: List[str], 
        batch_size: int = 32
    ) -> np.ndarray:
        """Generate embeddings using HuggingFace model."""
        await self._ensure_model_loaded()
        
        import torch
        
        def _encode_batch(batch_texts):
            with torch.no_grad():
                if self._tokenizer is None or self._model is None:
                    raise RuntimeError("Model or tokenizer not initialized")
                
                inputs = self._tokenizer(
                    batch_texts, 
                    return_tensors="pt", 
                    padding=True, 
                    truncation=True,
                    max_length=512
                )
                outputs = self._model(**inputs)
                # Use mean pooling
                embeddings = torch.mean(outputs.last_hidden_state, dim=1)
                return embeddings.cpu().numpy()
        
        # Process in batches
        all_embeddings = []
        loop = asyncio.get_event_loop()
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            batch_embeddings = await loop.run_in_executor(None, _encode_batch, batch)
            all_embeddings.append(batch_embeddings)
        
        return np.vstack(all_embeddings)
    
    async def create_embedding_single(self, text: str) -> np.ndarray:
        """Generate embedding for single text."""
        result = await self.create_embeddings([text])
        return result[0]
    
    def get_dimension(self) -> int:
        """Return embedding vector dimension."""
        if self._dimension is None:
            # This would need to be determined from the actual model
            self._dimension = 768  # Common default
        return self._dimension
    
    async def warmup(self) -> None:
        """Warm up the model by running a test inference."""
        await self.create_embedding_single("test warmup")
