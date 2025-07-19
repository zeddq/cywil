"""
Performance optimization utilities for the AI Paralegal system.
"""
import asyncio
from typing import Dict, Any, List, Optional, TypeVar, Callable, Set
from datetime import datetime, timedelta
from functools import wraps, lru_cache
import hashlib
import json
from dataclasses import dataclass
from collections import defaultdict
import logging

from .logging_utils import get_logger


logger = get_logger(__name__)

T = TypeVar('T')


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
            "total_requests": total_requests
        }


def cached_result(
    ttl: timedelta = timedelta(minutes=15),
    key_func: Optional[Callable] = None,
    cache_instance: Optional[AsyncCache] = None
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
        wrapper.cache = cache_instance
        return wrapper
    
    return decorator


class BatchProcessor:
    """
    Batches multiple async operations for efficient execution.
    """
    
    def __init__(self, 
                 batch_size: int = 10,
                 batch_timeout: float = 0.1,
                 max_concurrent: int = 5):
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout
        self.max_concurrent = max_concurrent
        self._pending: List[tuple] = []
        self._lock = asyncio.Lock()
        self._timer_task: Optional[asyncio.Task] = None
        
    async def add(self, coro, *args, **kwargs) -> Any:
        """Add coroutine to batch"""
        future = asyncio.Future()
        
        async with self._lock:
            self._pending.append((coro, args, kwargs, future))
            
            # Start timer if not running
            if self._timer_task is None or self._timer_task.done():
                self._timer_task = asyncio.create_task(self._process_after_timeout())
            
            # Process immediately if batch is full
            if len(self._pending) >= self.batch_size:
                await self._process_batch()
        
        return await future
    
    async def _process_after_timeout(self):
        """Process batch after timeout"""
        await asyncio.sleep(self.batch_timeout)
        async with self._lock:
            if self._pending:
                await self._process_batch()
    
    async def _process_batch(self):
        """Process pending operations in batch"""
        if not self._pending:
            return
            
        batch = self._pending[:]
        self._pending.clear()
        
        # Create tasks with semaphore for concurrency control
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        async def run_with_semaphore(coro, args, kwargs, future):
            async with semaphore:
                try:
                    result = await coro(*args, **kwargs)
                    future.set_result(result)
                except Exception as e:
                    future.set_exception(e)
        
        # Run all tasks concurrently
        tasks = [
            asyncio.create_task(run_with_semaphore(coro, args, kwargs, future))
            for coro, args, kwargs, future in batch
        ]
        
        await asyncio.gather(*tasks, return_exceptions=True)
        
        logger.info(f"Processed batch of {len(batch)} operations")


class ConnectionPoolOptimizer:
    """
    Optimizes database connection pool settings based on usage patterns.
    """
    
    def __init__(self, 
                 min_size: int = 5,
                 max_size: int = 20,
                 adjustment_interval: timedelta = timedelta(minutes=5)):
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
    
    def get_optimal_pool_size(self) -> Dict[str, int]:
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
            "current_max": max_usage
        }


class QueryOptimizer:
    """
    Analyzes and optimizes database queries.
    """
    
    def __init__(self):
        self._query_stats: Dict[str, List[float]] = defaultdict(list)
        self._slow_query_threshold = 1.0  # seconds
        
    def record_query(self, query: str, duration: float):
        """Record query execution time"""
        # Normalize query for grouping
        normalized = self._normalize_query(query)
        self._query_stats[normalized].append(duration)
        
        if duration > self._slow_query_threshold:
            logger.warning(
                f"Slow query detected",
                extra={
                    "extra_fields": {
                        "query": query[:200],
                        "duration_seconds": duration,
                        "normalized": normalized
                    }
                }
            )
    
    def _normalize_query(self, query: str) -> str:
        """Normalize query for statistics grouping"""
        # Remove specific values to group similar queries
        import re
        
        # Replace quoted strings
        normalized = re.sub(r"'[^']*'", "'?'", query)
        # Replace numbers
        normalized = re.sub(r'\b\d+\b', '?', normalized)
        # Remove extra whitespace
        normalized = ' '.join(normalized.split())
        
        return normalized
    
    def get_slow_queries(self, top_n: int = 10) -> List[Dict[str, Any]]:
        """Get slowest queries"""
        slow_queries = []
        
        for query, durations in self._query_stats.items():
            if durations:
                avg_duration = sum(durations) / len(durations)
                if avg_duration > self._slow_query_threshold:
                    slow_queries.append({
                        "query": query,
                        "avg_duration": avg_duration,
                        "max_duration": max(durations),
                        "execution_count": len(durations)
                    })
        
        # Sort by average duration
        slow_queries.sort(key=lambda x: x["avg_duration"], reverse=True)
        
        return slow_queries[:top_n]


class EmbeddingBatcher:
    """
    Batches embedding generation requests for efficiency.
    """
    
    def __init__(self, embedder, batch_size: int = 32, max_wait: float = 0.5):
        self.embedder = embedder
        self.batch_size = batch_size
        self.max_wait = max_wait
        self._pending: List[tuple] = []
        self._lock = asyncio.Lock()
        self._processor_task: Optional[asyncio.Task] = None
        
    async def get_embedding(self, text: str) -> List[float]:
        """Get embedding for text, batching with other requests"""
        future = asyncio.Future()
        
        async with self._lock:
            self._pending.append((text, future))
            
            # Start processor if not running
            if self._processor_task is None or self._processor_task.done():
                self._processor_task = asyncio.create_task(self._process_embeddings())
            
            # Process immediately if batch is full
            if len(self._pending) >= self.batch_size:
                asyncio.create_task(self._process_embeddings())
        
        return await future
    
    async def _process_embeddings(self):
        """Process pending embedding requests"""
        await asyncio.sleep(self.max_wait)
        
        async with self._lock:
            if not self._pending:
                return
                
            batch = self._pending[:self.batch_size]
            self._pending = self._pending[self.batch_size:]
            
        # Extract texts
        texts = [text for text, _ in batch]
        
        try:
            # Generate embeddings in batch
            embeddings = await asyncio.to_thread(
                self.embedder.encode, 
                texts,
                batch_size=self.batch_size
            )
            
            # Distribute results
            for i, (_, future) in enumerate(batch):
                future.set_result(embeddings[i].tolist())
                
            logger.info(f"Generated {len(batch)} embeddings in batch")
            
        except Exception as e:
            # Set exception for all futures
            for _, future in batch:
                future.set_exception(e)


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
