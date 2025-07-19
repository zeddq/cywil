"""
Centralized LLM and embedding management with caching and retry logic.
"""
from typing import Optional, Dict, Any, List
from ..core.logger_manager import get_logger
import hashlib
import json
from functools import lru_cache
from tenacity import retry, stop_after_attempt, wait_exponential
from langchain_openai import ChatOpenAI
from sentence_transformers import SentenceTransformer
import numpy as np
from fastapi import Request
from typing import Annotated
from fastapi import Depends

from .service_interface import ServiceInterface, HealthCheckResult, ServiceStatus
from .config_service import ConfigService
from .logger_manager import service_operation_logger

logger = get_logger(__name__)

class EmbeddingCache:
    """Simple in-memory cache for embeddings"""
    
    def __init__(self, max_size: int = 1000):
        self._cache: Dict[str, List[float]] = {}
        self._max_size = max_size
        self._access_order: List[str] = []
    
    def get(self, text: str) -> Optional[List[float]]:
        """Get embedding from cache"""
        key = self._hash_text(text)
        if key in self._cache:
            # Move to end (most recently used)
            self._access_order.remove(key)
            self._access_order.append(key)
            return self._cache[key]
        return None
    
    def put(self, text: str, embedding: List[float]):
        """Store embedding in cache"""
        key = self._hash_text(text)
        
        # Evict oldest if at capacity
        if len(self._cache) >= self._max_size and key not in self._cache:
            oldest = self._access_order.pop(0)
            del self._cache[oldest]
        
        self._cache[key] = embedding
        if key in self._access_order:
            self._access_order.remove(key)
        self._access_order.append(key)
    
    @staticmethod
    def _hash_text(text: str) -> str:
        """Create hash key for text"""
        return hashlib.md5(text.encode()).hexdigest()
    
    def clear(self):
        """Clear the cache"""
        self._cache.clear()
        self._access_order.clear()


class LLMManager(ServiceInterface):
    """
    Centralized manager for LLM and embedding operations.
    Provides caching, retry logic, and model management.
    """
    
    def __init__(self, config_service: ConfigService):
        super().__init__("LLMManager")
        self._config = config_service.config
        self._llm_clients: Dict[str, ChatOpenAI] = {}
        self._embedders: Dict[str, SentenceTransformer] = {}
        self._embedding_cache = EmbeddingCache(max_size=5000)
    
    async def _initialize_impl(self) -> None:
        """Initialize LLM clients and embedding models"""
        # Initialize default LLM clients
        api_key = self._config.openai.api_key.get_secret_value()
        
        self._llm_clients["orchestrator"] = ChatOpenAI(
            model=self._config.openai.orchestrator_model,
            api_key=api_key,
            max_retries=self._config.openai.max_retries,
            timeout=self._config.openai.timeout
        )
        
        self._llm_clients["summary"] = ChatOpenAI(
            model=self._config.openai.summary_model,
            api_key=api_key,
            max_retries=self._config.openai.max_retries,
            timeout=self._config.openai.timeout
        )
        
        self._llm_clients["default"] = ChatOpenAI(
            model=self._config.openai.llm_model,
            api_key=api_key,
            max_retries=self._config.openai.max_retries,
            timeout=self._config.openai.timeout,
            verbose=True
        )
        
        # Initialize embedding models
        logger.info("Loading embedding models")
        self._embedders["multilingual"] = SentenceTransformer('paraphrase-multilingual-mpnet-base-v2')
        self._embedders["legal"] = SentenceTransformer('Stern5497/sbert-legal-xlm-roberta-base')
        
        logger.info("LLM Manager initialized with models")
    
    async def _shutdown_impl(self) -> None:
        """Cleanup resources"""
        self._embedding_cache.clear()
        self._llm_clients.clear()
        self._embedders.clear()
    
    async def _health_check_impl(self) -> HealthCheckResult:
        """Check service health"""
        try:
            # Test embedding generation
            test_embedding = self.get_embedding("test", "multilingual")
            logger.info(f"Test embedding: {test_embedding}")
            
            # Test LLM availability
            test_prompt = "Respond with 'OK'"
            response = await self.generate_completion(test_prompt, "default", max_tokens=10)
            logger.info(f"Test response: {response}")
            
            return HealthCheckResult(
                status=ServiceStatus.HEALTHY,
                message="LLM Manager is healthy",
                details={
                    "llm_models": list(self._llm_clients.keys()),
                    "embedding_models": list(self._embedders.keys()),
                    "cache_size": len(self._embedding_cache._cache)
                }
            )
        except Exception as e:
            return HealthCheckResult(
                status=ServiceStatus.UNHEALTHY,
                message=f"Health check failed: {str(e)}"
            )
    
    def get_llm_client(self, model_type: str = "default") -> ChatOpenAI:
        """Get LLM client by type"""
        if model_type not in self._llm_clients:
            logger.warning(f"Unknown model type '{model_type}', using default")
            model_type = "default"
        return self._llm_clients[model_type]
    
    @service_operation_logger("LLMManager")
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def generate_completion(self, 
                                 prompt: str, 
                                 model_type: str = "default",
                                 max_tokens: Optional[int] = None,
                                 **kwargs) -> str:
        """Generate text completion with retry logic"""
        client = self.get_llm_client(model_type)
        
        logger.debug(f"Generating completion with {model_type} model")
        
        # Create proper message format for ChatOpenAI
        from langchain_core.messages import HumanMessage
        messages = [HumanMessage(content=prompt)]
        
        invoke_kwargs = {
            "max_tokens": max_tokens,
            **kwargs
        }
            
        response = await client.ainvoke(messages, **invoke_kwargs)
        
        return response.content
    
    @service_operation_logger("LLMManager")
    def get_embedding(self, 
                     text: str, 
                     model_type: str = "multilingual",
                     use_cache: bool = True) -> List[float]:
        """Get text embedding with caching"""
        # Check cache first
        if use_cache:
            cached = self._embedding_cache.get(text)
            if cached is not None:
                logger.debug("Returning cached embedding")
                return cached
        
        # Generate embedding
        if model_type not in self._embedders:
            logger.warning(f"Unknown embedder type '{model_type}', using multilingual")
            model_type = "multilingual"
        
        embedder = self._embedders[model_type]
        embedding = embedder.encode(text).tolist()
        
        # Cache the result
        if use_cache:
            self._embedding_cache.put(text, embedding)
        
        return embedding
    
    @service_operation_logger("LLMManager")
    def get_embeddings_batch(self, 
                           texts: List[str], 
                           model_type: str = "multilingual",
                           use_cache: bool = True) -> List[List[float]]:
        """Get embeddings for multiple texts efficiently"""
        embeddings = []
        texts_to_encode = []
        cache_indices = []
        
        # Check cache for each text
        for i, text in enumerate(texts):
            if use_cache:
                cached = self._embedding_cache.get(text)
                if cached is not None:
                    embeddings.append(cached)
                else:
                    texts_to_encode.append(text)
                    cache_indices.append(i)
            else:
                texts_to_encode.append(text)
        
        # Batch encode uncached texts
        if texts_to_encode:
            embedder = self._embedders.get(model_type, self._embedders["multilingual"])
            new_embeddings = embedder.encode(texts_to_encode).tolist()
            
            # Cache new embeddings
            if use_cache:
                for text, embedding in zip(texts_to_encode, new_embeddings):
                    self._embedding_cache.put(text, embedding)
            
            # Merge with cached embeddings in correct order
            if use_cache and cache_indices:
                result = [None] * len(texts)
                cached_idx = 0
                new_idx = 0
                
                for i in range(len(texts)):
                    if i in cache_indices:
                        result[i] = new_embeddings[new_idx]
                        new_idx += 1
                    else:
                        result[i] = embeddings[cached_idx]
                        cached_idx += 1
                
                return result
            else:
                return new_embeddings
        
        return embeddings
    
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
    
    def find_most_similar(self, 
                         query_embedding: List[float], 
                         candidate_embeddings: List[List[float]], 
                         top_k: int = 5) -> List[tuple[int, float]]:
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
        return {
            "size": len(self._embedding_cache._cache),
            "max_size": self._embedding_cache._max_size,
            "hit_rate": "Not tracked"  # Could be enhanced to track hits/misses
        }
    

def get_llm_manager(request: Request) -> LLMManager:
    return request.app.state.manager.inject_service(LLMManager)

LLMManagerDep = Annotated[LLMManager, Depends(get_llm_manager)]
