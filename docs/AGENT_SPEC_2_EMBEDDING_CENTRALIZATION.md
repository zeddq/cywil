# Agent Specification: Embedding Model Centralization

## Agent ID: PHASE1-EMBEDDING-CENTRAL
## Priority: CRITICAL  
## Estimated Duration: 6-8 hours
## Dependencies: Task 4 (Configuration) should complete first

## Objective
Consolidate all embedding logic into a centralized LLMManager service with proper async patterns, removing duplicate SentenceTransformer instances and implementing caching.

## Scope
### Files to Modify
- `/app/core/llm_manager.py` (major refactor)
- `/app/services/statute_search_service.py` (update to use centralized service)
- **NEW:** `/app/models/embedding_interface.py` (create)
- **NEW:** `/app/models/embedding_factory.py` (create)

### Exclusions  
- Do NOT modify OpenAI client code (handled by Agent 1)
- Do NOT touch PDF processing logic
- Do NOT modify database schemas

## Technical Requirements

### 1. Abstract Embedding Interface
```python
# app/models/embedding_interface.py
from abc import ABC, abstractmethod
from typing import List, Optional
import numpy as np

class EmbeddingModel(ABC):
    @abstractmethod
    async def create_embeddings(
        self, 
        texts: List[str],
        batch_size: int = 32
    ) -> np.ndarray:
        """Generate embeddings for text batch"""
        pass
    
    @abstractmethod
    def get_dimension(self) -> int:
        """Return embedding vector dimension"""
        pass
    
    @abstractmethod
    async def create_embedding_single(
        self,
        text: str
    ) -> np.ndarray:
        """Generate embedding for single text"""
        pass
```

### 2. Embedding Implementations
```python
# app/models/local_embedder.py
from sentence_transformers import SentenceTransformer
import asyncio

class LocalEmbedder(EmbeddingModel):
    def __init__(self, model_name: str = "paraphrase-multilingual-mpnet-base-v2"):
        self.model = SentenceTransformer(model_name)
        self._lock = asyncio.Lock()
    
    async def create_embeddings(self, texts, batch_size=32):
        async with self._lock:
            # Run CPU-intensive operation in thread pool
            loop = asyncio.get_event_loop()
            embeddings = await loop.run_in_executor(
                None, 
                self.model.encode,
                texts,
                batch_size
            )
            return embeddings
```

### 3. Centralized LLM Manager
```python
# app/core/llm_manager.py
from typing import Dict, Optional
import hashlib
import pickle
from pathlib import Path

class LLMManager:
    def __init__(self, cache_dir: Optional[Path] = None):
        self._models: Dict[str, EmbeddingModel] = {}
        self._cache_dir = cache_dir or Path(".embedding_cache")
        self._cache_dir.mkdir(exist_ok=True)
        self._memory_cache = {}  # LRU cache for recent embeddings
        
    async def get_embeddings(
        self,
        texts: List[str],
        model_name: str = "default",
        use_cache: bool = True
    ) -> np.ndarray:
        """Main entry point for all embedding requests"""
        
        # Check cache first
        if use_cache:
            cache_key = self._get_cache_key(texts, model_name)
            if cached := self._get_from_cache(cache_key):
                return cached
        
        # Get or create model
        model = self._get_model(model_name)
        
        # Generate embeddings
        embeddings = await model.create_embeddings(texts)
        
        # Cache results
        if use_cache:
            self._save_to_cache(cache_key, embeddings)
        
        return embeddings
```

### 4. Async Pattern Requirements
- All embedding operations must be async
- CPU-intensive operations run in thread pool executor
- Implement connection pooling for external services
- Add semaphore for concurrent request limiting

## Implementation Steps

1. **Create Embedding Interface** (1 hour)
   - Define abstract base class
   - Document expected behavior
   - Add type hints throughout

2. **Implement Model Adapters** (2 hours)
   - LocalEmbedder for SentenceTransformers
   - OpenAIEmbedder for text-embedding-3-small
   - HuggingFaceEmbedder for future models

3. **Refactor LLMManager** (3 hours)
   - Singleton pattern with lazy initialization
   - Model registry and factory
   - Two-tier caching (memory + disk)
   - Async/await throughout

4. **Update Search Service** (1 hour)
   - Replace direct model usage
   - Use LLMManager.get_embeddings()
   - Add performance metrics

5. **Add Cache Management** (1 hour)
   - LRU eviction for memory cache
   - TTL for disk cache
   - Cache warming on startup
   - Cache statistics endpoint

## Success Criteria

### Functional
- [ ] Single SentenceTransformer instance across application
- [ ] All embedding calls go through LLMManager
- [ ] Cache hit rate > 30% in production
- [ ] Support for multiple embedding models

### Performance
- [ ] Memory usage reduced by 50%
- [ ] Embedding generation < 100ms for cached
- [ ] Batch processing 10x faster than sequential
- [ ] No blocking I/O in async contexts

## Testing Requirements

### Unit Tests
```python
# tests/unit/test_llm_manager.py
- test_singleton_pattern
- test_model_registry
- test_cache_operations
- test_async_embedding_generation
- test_batch_processing
```

### Integration Tests
```python
# tests/integration/test_embedding_pipeline.py
- test_statute_search_with_embeddings
- test_concurrent_embedding_requests
- test_cache_persistence
- test_model_switching
```

## Conflict Avoidance

### File Isolation
- This agent owns: `/app/core/llm_manager.py`, `/app/models/embedding_*.py`
- Read-only: Configuration files
- Coordinate: Changes to search service

### Resource Management
- Use named locks for model loading
- Implement resource pooling
- Add circuit breakers for external services

## Performance Optimization

### Caching Strategy
```python
# Two-tier cache configuration
MEMORY_CACHE_SIZE = 1000  # Recent embeddings
DISK_CACHE_TTL = 86400    # 24 hours
CACHE_KEY_ALGORITHM = "sha256"
```

### Batching Configuration
```python
DEFAULT_BATCH_SIZE = 32
MAX_BATCH_SIZE = 128
BATCH_TIMEOUT_MS = 100  # Combine requests within window
```

## Monitoring & Alerts

- Cache hit/miss ratio
- Embedding generation latency (p50, p95, p99)
- Memory usage per model
- Queue depth for batch processing
- Model load time on cold start

## Dependencies

### Python Packages
```toml
sentence-transformers = "^2.2.2"
numpy = "^1.24.0"
aiofiles = "^23.2.1"
diskcache = "^5.6.3"  # For persistent caching
```

### System Requirements
- 4GB RAM minimum for model loading
- 10GB disk space for cache
- CPU with AVX support for optimal performance

## Migration Path

1. **Phase 1**: Wrapper around existing code
2. **Phase 2**: Gradual migration of services
3. **Phase 3**: Remove old implementations
4. **Phase 4**: Performance optimization

## Notes for Implementation

1. **Model Loading**: Lazy load models on first use
2. **Memory Management**: Implement model unloading after inactivity
3. **Polish Language**: Ensure multilingual model support
4. **Backwards Compatibility**: Keep old interfaces during migration