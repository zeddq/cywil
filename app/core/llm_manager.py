"""
Centralized LLM and embedding management with caching and retry logic.
"""

import asyncio
import hashlib
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

import numpy as np
from fastapi import Depends, Request
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from ..core.logger_manager import get_logger
from ..embedding_models import EmbeddingModel, embedding_factory
from .config_service import ConfigService
from .logger_manager import service_operation_logger
from .service_interface import HealthCheckResult, ServiceInterface, ServiceStatus

logger = get_logger(__name__)

# Simple two-tier cache without external dependencies
class TwoTierCache:
    """Two-tier caching system with memory (LRU) and basic disk persistence."""
    
    def __init__(self, memory_size: int = 1000, cache_dir: Optional[Path] = None):
        self._memory_cache: Dict[str, Any] = {}
        self._memory_access_order: List[str] = []
        self._memory_max_size = memory_size
        
        # Basic disk cache directory (without external dependency)
        self._cache_dir = cache_dir or Path(".embedding_cache")
        self._cache_dir.mkdir(exist_ok=True)
    
    def get(self, key: str) -> Optional[np.ndarray]:
        """Get from cache, checking memory first, then basic disk cache."""
        # Check memory cache
        if key in self._memory_cache:
            # Move to end (most recently used)
            self._memory_access_order.remove(key)
            self._memory_access_order.append(key)
            return self._memory_cache[key]
        
        # Check simple disk cache
        try:
            cache_file = self._cache_dir / f"{key}.npy"
            if cache_file.exists():
                embedding = np.load(cache_file)
                # Promote to memory cache
                self._put_memory(key, embedding)
                return embedding
        except Exception as e:
            logger.warning(f"Disk cache read error: {e}")
        
        return None
    
    def put(self, key: str, embedding: np.ndarray) -> None:
        """Store in both memory and basic disk cache."""
        self._put_memory(key, embedding)
        
        # Store in basic disk cache
        try:
            cache_file = self._cache_dir / f"{key}.npy"
            np.save(cache_file, embedding)
        except Exception as e:
            logger.warning(f"Disk cache write error: {e}")
    
    def _put_memory(self, key: str, embedding: np.ndarray) -> None:
        """Store in memory cache with LRU eviction."""
        # Evict oldest if at capacity
        if len(self._memory_cache) >= self._memory_max_size and key not in self._memory_cache:
            oldest = self._memory_access_order.pop(0)
            del self._memory_cache[oldest]
        
        self._memory_cache[key] = embedding
        if key in self._memory_access_order:
            self._memory_access_order.remove(key)
        self._memory_access_order.append(key)
    
    def clear(self) -> None:
        """Clear both caches."""
        self._memory_cache.clear()
        self._memory_access_order.clear()
        # Clear disk cache files
        try:
            for cache_file in self._cache_dir.glob("*.npy"):
                cache_file.unlink()
        except Exception as e:
            logger.warning(f"Error clearing disk cache: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        disk_files = 0
        try:
            disk_files = len(list(self._cache_dir.glob("*.npy")))
        except:
            pass
        
        return {
            "memory_size": len(self._memory_cache),
            "memory_max_size": self._memory_max_size,
            "disk_size": disk_files,
        }


class LLMManager(ServiceInterface):
    """
    Centralized manager for LLM and embedding operations.
    Provides caching, retry logic, and model management with async patterns.
    """

    def __init__(self, config_service: ConfigService):
        super().__init__("LLMManager")
        self._config = config_service.config
        self._llm_clients: Dict[str, Dict[str, Any]] = {}
        self._openai_client: Optional[AsyncOpenAI] = None
        
        # Centralized embedding management
        self._embedding_models: Dict[str, EmbeddingModel] = {}
        self._embedding_cache = TwoTierCache(memory_size=5000)
        
        # Concurrency control
        self._embedding_semaphore = asyncio.Semaphore(10)
        self._model_locks: Dict[str, asyncio.Lock] = {}

    async def _initialize_impl(self) -> None:
        """Initialize LLM clients and embedding models"""
        # Initialize OpenAI client
        api_key = self._config.openai.api_key.get_secret_value()
        self._openai_client = AsyncOpenAI(
            api_key=api_key,
            max_retries=self._config.openai.max_retries,
            timeout=self._config.openai.timeout,
        )

        # Store model configurations
        self._llm_clients["orchestrator"] = {"model": self._config.openai.orchestrator_model}
        self._llm_clients["summary"] = {"model": self._config.openai.summary_model}
        self._llm_clients["default"] = {"model": self._config.openai.llm_model}

        # Initialize embedding models using factory (single instances)
        logger.info("Loading embedding models")
        
        # Multilingual model for general use
        self._embedding_models["multilingual"] = embedding_factory.create_local_embedder(
            "paraphrase-multilingual-mpnet-base-v2",
            cache_key="multilingual"
        )
        
        # Legal-specific model
        self._embedding_models["legal"] = embedding_factory.create_local_embedder(
            "Stern5497/sbert-legal-xlm-roberta-base",
            cache_key="legal"
        )
        
        # OpenAI embedder option
        self._embedding_models["openai"] = embedding_factory.create_openai_embedder(
            api_key,
            "text-embedding-3-small",
            cache_key="openai"
        )

        # Warm up models
        await self._warmup_models()
        
        logger.info("LLM Manager initialized with centralized embedding models")

    async def _warmup_models(self) -> None:
        """Warm up embedding models by running test inferences."""
        logger.info("Warming up embedding models...")
        warmup_tasks = []
        
        for name, model in self._embedding_models.items():
            async def warmup_model(model_name: str, embedding_model: EmbeddingModel):
                try:
                    await embedding_model.warmup()
                    logger.info(f"Warmed up {model_name} embedding model")
                except Exception as e:
                    logger.warning(f"Failed to warm up {model_name}: {e}")
            
            warmup_tasks.append(warmup_model(name, model))
        
        await asyncio.gather(*warmup_tasks, return_exceptions=True)

    async def _shutdown_impl(self) -> None:
        """Cleanup resources"""
        self._embedding_cache.clear()
        self._llm_clients.clear()
        self._embedding_models.clear()
        self._model_locks.clear()

    async def _health_check_impl(self) -> HealthCheckResult:
        """Check service health"""
        try:
            # Test embedding generation
            test_embedding = await self.get_embeddings(["test"], "multilingual", use_cache=False)
            logger.info(f"Test embedding shape: {test_embedding.shape}")

            # Test LLM availability
            test_prompt = "Respond with 'OK'"
            response = await self.generate_completion(test_prompt, "default", max_tokens=10)
            logger.info(f"Test response: {response}")

            return HealthCheckResult(
                status=ServiceStatus.HEALTHY,
                message="LLM Manager is healthy",
                details={
                    "llm_models": list(self._llm_clients.keys()),
                    "embedding_models": list(self._embedding_models.keys()),
                    "cache_stats": self._embedding_cache.get_stats(),
                },
            )
        except Exception as e:
            return HealthCheckResult(
                status=ServiceStatus.UNHEALTHY, message=f"Health check failed: {str(e)}"
            )

    def get_model_config(self, model_type: str = "default") -> Dict[str, Any]:
        """Get model configuration by type"""
        if model_type not in self._llm_clients:
            logger.warning(f"Unknown model type '{model_type}', using default")
            model_type = "default"
        return self._llm_clients[model_type]

    @service_operation_logger("LLMManager")
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def generate_completion(
        self, prompt: str, model_type: str = "default", max_tokens: Optional[int] = None, **kwargs
    ) -> Optional[str]:
        """Generate text completion with retry logic"""
        model_config = self.get_model_config(model_type)

        logger.debug(f"Generating completion with {model_type} model")

        # Create proper message format for OpenAI
        messages = [{"role": "user", "content": prompt}]

        # Prepare completion kwargs
        completion_kwargs = {"model": model_config["model"], "messages": messages, **kwargs}

        if max_tokens is not None:
            completion_kwargs["max_tokens"] = max_tokens

        if self._openai_client is None:
            raise RuntimeError("OpenAI client not initialized")
        response = await self._openai_client.chat.completions.create(**completion_kwargs)

        return response.choices[0].message.content

    def _get_cache_key(self, texts: List[str], model_name: str) -> str:
        """Generate cache key for text batch."""
        text_hash = hashlib.sha256('||'.join(texts).encode()).hexdigest()
        return f"{model_name}_{text_hash}"

    @service_operation_logger("LLMManager")
    async def get_embeddings(
        self,
        texts: List[str],
        model_name: str = "multilingual",
        use_cache: bool = True,
        batch_size: int = 32
    ) -> np.ndarray:
        """
        Main entry point for all embedding requests with centralized caching.
        """
        async with self._embedding_semaphore:  # Limit concurrent requests
            # Check cache first
            if use_cache:
                cache_key = self._get_cache_key(texts, model_name)
                cached = self._embedding_cache.get(cache_key)
                if cached is not None:
                    logger.debug(f"Returning cached embeddings for {len(texts)} texts")
                    return cached

            # Get model
            model = self._get_embedding_model(model_name)
            
            # Generate embeddings
            logger.debug(f"Generating embeddings for {len(texts)} texts with {model_name}")
            embeddings = await model.create_embeddings(texts, batch_size)
            
            # Cache results
            if use_cache:
                self._embedding_cache.put(cache_key, embeddings)
            
            return embeddings

    @service_operation_logger("LLMManager")
    async def get_embedding_single(
        self,
        text: str,
        model_name: str = "multilingual",
        use_cache: bool = True
    ) -> np.ndarray:
        """Get embedding for single text."""
        result = await self.get_embeddings([text], model_name, use_cache)
        return result[0]

    def _get_embedding_model(self, model_name: str) -> EmbeddingModel:
        """Get embedding model by name with fallback."""
        if model_name not in self._embedding_models:
            logger.warning(f"Unknown embedding model '{model_name}', using multilingual")
            model_name = "multilingual"
        return self._embedding_models[model_name]

    # Backward compatibility methods
    def get_embedding(
        self, text: str, model_type: str = "multilingual", use_cache: bool = True
    ) -> List[float]:
        """Get text embedding with caching (backward compatibility)"""
        import asyncio
        
        try:
            embedding = asyncio.run(self.get_embedding_single(text, model_type, use_cache))
        except RuntimeError:
            # Already in event loop
            raise RuntimeError("Use await get_embedding_single() from async context")
        
        return embedding.tolist()

    def get_embeddings_batch(
        self, texts: List[str], model_type: str = "multilingual", use_cache: bool = True
    ) -> List[List[float]]:
        """Get embeddings for multiple texts efficiently (backward compatibility)"""
        import asyncio
        
        try:
            embeddings = asyncio.run(self.get_embeddings(texts, model_type, use_cache))
        except RuntimeError:
            raise RuntimeError("Use await get_embeddings() from async context")
        
        return embeddings.tolist()

    def compute_similarity(self, embedding1: List[float], embedding2: List[float]) -> float:
        """Compute cosine similarity between two embeddings"""
        vec1 = np.array(embedding1)
        vec2 = np.array(embedding2)

        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    def find_most_similar(
        self, query_embedding: List[float], candidate_embeddings: List[List[float]], top_k: int = 5
    ) -> List[tuple[int, float]]:
        """Find most similar embeddings from candidates"""
        similarities = []

        for i, candidate in enumerate(candidate_embeddings):
            similarity = self.compute_similarity(query_embedding, candidate)
            similarities.append((i, similarity))

        # Sort by similarity (descending)
        similarities.sort(key=lambda x: x[1], reverse=True)

        return similarities[:top_k]

    def clear_cache(self):
        """Clear embedding cache"""
        self._embedding_cache.clear()
        logger.info("Embedding cache cleared")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        base_stats = self._embedding_cache.get_stats()
        return {
            **base_stats,
            "models_loaded": list(self._embedding_models.keys()),
            "factory_models": embedding_factory.list_models(),
        }

    def get_embedding_model_info(self, model_name: str) -> Dict[str, Any]:
        """Get information about specific embedding model."""
        model = self._get_embedding_model(model_name)
        return {
            "name": model_name,
            "type": type(model).__name__,
            "dimension": model.get_dimension(),
        }

    def list_embedding_models(self) -> List[Dict[str, Any]]:
        """List all available embedding models."""
        return [
            self.get_embedding_model_info(name) 
            for name in self._embedding_models.keys()
        ]


def get_llm_manager(request: Request) -> LLMManager:
    return request.app.state.manager.inject_service(LLMManager)


LLMManagerDep = Annotated[LLMManager, Depends(get_llm_manager)]