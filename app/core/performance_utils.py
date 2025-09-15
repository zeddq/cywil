"""
Performance optimization utilities for the AI Paralegal system.
"""

import asyncio
import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, TypeVar

from .logging_utils import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


@dataclass
class CacheEntry:
    """Cache entry with TTL support"""

    value: Any
    expires_at: datetime
    hits: int = 0

    @property
    def is_expired(self) -> bool:
        return datetime.now() > self.expires_at


class AsyncCache:
    """
    Async-safe cache with TTL support and metrics.
    """

    def __init__(self, max_size: int = 1000, default_ttl: timedelta = timedelta(minutes=15)):
        self._cache: Dict[str, CacheEntry] = {}
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0

    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        async with self._lock:
            entry = self._cache.get(key)

            if entry is None:
                self._misses += 1
                return None

            if entry.is_expired:
                del self._cache[key]
                self._misses += 1
                return None

            entry.hits += 1
            self._hits += 1
            return entry.value

    async def set(self, key: str, value: Any, ttl: Optional[timedelta] = None) -> None:
        """Set value in cache"""
        async with self._lock:
            # Evict oldest entries if at capacity
            if len(self._cache) >= self._max_size:
                # Remove expired entries first
                expired_keys = [k for k, v in self._cache.items() if v.is_expired]
                for k in expired_keys:
                    del self._cache[k]

                # If still over capacity, remove least recently used
                if len(self._cache) >= self._max_size:
                    lru_key = min(self._cache.items(), key=lambda x: x[1].hits)[0]
                    del self._cache[lru_key]

            expires_at = datetime.now() + (ttl or self._default_ttl)
            self._cache[key] = CacheEntry(value=value, expires_at=expires_at)

    async def clear(self) -> None:
        """Clear all cache entries"""
        async with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def get_metrics(self) -> Dict[str, Any]:
        """Get cache metrics"""
        total_requests = self._hits + self._misses
        hit_rate = self._hits / total_requests if total_requests > 0 else 0

        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": hit_rate,
            "total_requests": total_requests,
        }


def cached_result(
    ttl: timedelta = timedelta(minutes=15),
    key_func: Optional[Callable] = None,
    cache_instance: Optional[AsyncCache] = None,
):
    """
    Decorator for caching async function results.

    Args:
        ttl: Time to live for cached results
        key_func: Function to generate cache key from arguments
        cache_instance: Specific cache instance to use
    """
    # Use default cache if none provided
    if cache_instance is None:
        cache_instance = AsyncCache()

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Generate cache key
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                # Default key generation
                key_parts = [func.__name__]
                key_parts.extend(str(arg) for arg in args)
                key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
                cache_key = hashlib.md5(":".join(key_parts).encode()).hexdigest()

            # Try to get from cache
            cached_value = await cache_instance.get(cache_key)
            if cached_value is not None:
                logger.debug(f"Cache hit for {func.__name__} with key {cache_key}")
                return cached_value

            # Execute function
            result = await func(*args, **kwargs)

            # Store in cache
            await cache_instance.set(cache_key, result, ttl)
            logger.debug(f"Cached result for {func.__name__} with key {cache_key}")

            return result

        # Attach cache instance for metrics access
        setattr(wrapper, 'cache', cache_instance)
        return wrapper

    return decorator


class BatchProcessor:
    """
    Batches multiple items for efficient batch processing.
    """

    def __init__(self, process_func: Callable, max_batch_size: int = 10, max_wait_time: timedelta = timedelta(seconds=1)):
        self._process_func = process_func
        self._max_batch_size = max_batch_size
        self._max_wait_time = max_wait_time
        self._pending_items: List[tuple] = []
        self._lock = asyncio.Lock()
        self._timer_task: Optional[asyncio.Task] = None
        self._running = False
        self._stop_event = asyncio.Event()

    async def start(self):
        """Start the batch processor"""
        self._running = True
        self._stop_event.clear()

    async def stop(self):
        """Stop the batch processor and process any remaining items"""
        self._running = False
        async with self._lock:
            if self._pending_items:
                await self._process_batch()
        self._stop_event.set()

    async def add_item(self, item) -> Any:
        """Add item to batch and return future for result"""
        if not self._running:
            raise RuntimeError("BatchProcessor not started")
            
        future = asyncio.Future()

        async with self._lock:
            self._pending_items.append((item, future))

            # Start timer if not running
            if self._timer_task is None or self._timer_task.done():
                self._timer_task = asyncio.create_task(self._process_after_timeout())

            # Process immediately if batch is full
            if len(self._pending_items) >= self._max_batch_size:
                await self._process_batch()

        return future

    async def _process_after_timeout(self):
        """Process batch after timeout"""
        await asyncio.sleep(self._max_wait_time.total_seconds())
        async with self._lock:
            if self._pending_items and self._running:
                await self._process_batch()

    async def _process_batch(self):
        """Process pending items in batch"""
        if not self._pending_items:
            return

        batch = self._pending_items[:]
        self._pending_items.clear()

        # Extract items and futures
        items = [item for item, _ in batch]
        futures = [future for _, future in batch]

        try:
            # Process batch
            results = await self._process_func(items)
            
            # Set results for futures
            for i, future in enumerate(futures):
                future.set_result(results[i])
                
            logger.info(f"Processed batch of {len(batch)} items")
            
        except Exception as e:
            # Set exception for all futures
            for future in futures:
                future.set_exception(e)


class ConnectionPoolOptimizer:
    """
    Optimizes database connection pool settings based on usage patterns.
    """

    def __init__(
        self,
        min_size: int = 5,
        max_size: int = 20,
        adjustment_interval: timedelta = timedelta(minutes=5),
    ):
        self.min_size = min_size
        self.max_size = max_size
        self.adjustment_interval = adjustment_interval
        self._usage_history: List[int] = []
        self._last_adjustment = datetime.now()

    def record_usage(self, active_connections: int):
        """Record connection usage"""
        self._usage_history.append(active_connections)

        # Keep only recent history (last hour)
        max_history = 3600 // self.adjustment_interval.seconds
        if len(self._usage_history) > max_history:
            self._usage_history = self._usage_history[-max_history:]

    def get_optimal_pool_size(self) -> Dict[str, int | float]:
        """Calculate optimal pool size based on usage"""
        if not self._usage_history:
            return {"min": self.min_size, "max": self.max_size}

        # Calculate statistics
        avg_usage = sum(self._usage_history) / len(self._usage_history)
        max_usage = max(self._usage_history)

        # Recommend pool sizes
        recommended_min = max(self.min_size, int(avg_usage * 0.8))
        recommended_max = min(self.max_size, max(int(max_usage * 1.2), recommended_min + 5))

        return {
            "min": recommended_min,
            "max": recommended_max,
            "current_avg": avg_usage,
            "current_max": max_usage,
        }


class QueryOptimizer:
    """
    Analyzes and optimizes database queries using caching and pattern analysis.
    """

    def __init__(self):
        self._query_cache = query_cache
        self._query_patterns: Dict[str, int] = defaultdict(int)

    async def optimize_query(self, query: str, params: Dict[str, Any], execute_func: Callable) -> Any:
        """
        Optimizes and executes a query, using caching.
        """
        key_parts = [query]
        key_parts.extend(f"{k}={v}" for k, v in sorted(params.items()))
        cache_key = hashlib.md5(":".join(key_parts).encode()).hexdigest()

        cached_value = await self._query_cache.get(cache_key)
        if cached_value is not None:
            return cached_value

        result = await execute_func(query, params)
        await self._query_cache.set(cache_key, result)
        return result

    def _normalize_query(self, query: str) -> str:
        """Normalize query for statistics grouping"""
        import re
        
        # Replace quoted strings
        normalized = re.sub(r"'[^']*'", "'?'", query)
        # Replace numbers
        normalized = re.sub(r"\b\d+\b", "?", normalized)
        # Remove extra whitespace
        normalized = " ".join(normalized.split())

        return normalized

    def analyze_pattern(self, query: str):
        """Analyzes a query to identify its pattern."""
        pattern = self._normalize_query(query)
        self._query_patterns[pattern] += 1

    def get_patterns(self) -> List[Dict[str, Any]]:
        """Returns identified query patterns and their counts."""
        patterns = [
            {"pattern": pattern, "count": count}
            for pattern, count in self._query_patterns.items()
        ]
        patterns.sort(key=lambda x: x["count"], reverse=True)
        return patterns


class EmbeddingBatcher:
    """
    Batches embedding generation requests for efficiency.
    """

    def __init__(self, embedder, batch_size: int = 32, max_wait: float = 0.5):
        self._embedder = embedder
        self._cache = embedding_cache
        
        # Create process function for BatchProcessor
        async def process_embeddings(texts: List[str]) -> List[List[float]]:
            # Check cache first
            cached_results = {}
            uncached_texts = []
            uncached_indices = []
            
            for i, text in enumerate(texts):
                cache_key = hashlib.md5(text.encode()).hexdigest()
                cached_embedding = await self._cache.get(cache_key)
                if cached_embedding is not None:
                    cached_results[i] = cached_embedding
                else:
                    uncached_texts.append(text)
                    uncached_indices.append(i)
            
            # Generate embeddings for uncached texts
            if uncached_texts:
                embeddings = await asyncio.to_thread(
                    self._embedder.encode, uncached_texts, batch_size=len(uncached_texts)
                )
                
                # Cache new embeddings
                for text, embedding, idx in zip(uncached_texts, embeddings, uncached_indices):
                    cache_key = hashlib.md5(text.encode()).hexdigest()
                    embedding_list = embedding.tolist()
                    await self._cache.set(cache_key, embedding_list)
                    cached_results[idx] = embedding_list
            
            # Return results in original order
            return [cached_results[i] for i in range(len(texts))]
        
        self._batch_processor = BatchProcessor(
            process_func=process_embeddings,
            max_batch_size=batch_size,
            max_wait_time=timedelta(seconds=max_wait)
        )

    async def start(self):
        """Start the embedding batcher"""
        await self._batch_processor.start()

    async def stop(self):
        """Stop the embedding batcher"""
        await self._batch_processor.stop()

    async def get_embedding(self, text: str) -> List[float]:
        """Get embedding for text, batching with other requests"""
        # Check cache first
        cache_key = hashlib.md5(text.encode()).hexdigest()
        cached_embedding = await self._cache.get(cache_key)
        if cached_embedding is not None:
            return cached_embedding
        
        # Use batch processor for uncached embeddings
        future = await self._batch_processor.add_item(text)
        result = await future
        return result


# Query result cache
query_cache = AsyncCache(max_size=500, default_ttl=timedelta(minutes=30))

# Embedding cache with longer TTL
embedding_cache = AsyncCache(max_size=1000, default_ttl=timedelta(hours=2))


def optimize_query_with_cache(ttl: timedelta = timedelta(minutes=30)):
    """Decorator to cache database query results"""
    return cached_result(ttl=ttl, cache_instance=query_cache)


def optimize_embedding_with_cache(ttl: timedelta = timedelta(hours=2)):
    """Decorator to cache embedding results"""
    return cached_result(ttl=ttl, cache_instance=embedding_cache)
