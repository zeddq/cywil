"""
Comprehensive tests for performance utilities including caching and batching.
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta
from typing import List, Any

from app.core.performance_utils import (
    AsyncCache, CacheEntry, BatchProcessor, QueryOptimizer,
    EmbeddingBatcher, query_cache, embedding_cache, cached_query
)


class TestCacheEntry:
    """Test CacheEntry functionality"""
    
    def test_cache_entry_creation(self):
        """Test creating cache entry"""
        expires_at = datetime.now() + timedelta(minutes=5)
        entry = CacheEntry(value="test_value", expires_at=expires_at)
        
        assert entry.value == "test_value"
        assert entry.expires_at == expires_at
        assert entry.hits == 0
        assert not entry.is_expired
    
    def test_cache_entry_expiration(self):
        """Test cache entry expiration check"""
        # Create expired entry
        expires_at = datetime.now() - timedelta(minutes=5)
        entry = CacheEntry(value="test_value", expires_at=expires_at)
        
        assert entry.is_expired
        
        # Create non-expired entry
        expires_at = datetime.now() + timedelta(minutes=5)
        entry = CacheEntry(value="test_value", expires_at=expires_at)
        
        assert not entry.is_expired


class TestAsyncCache:
    """Test AsyncCache functionality"""
    
    @pytest.mark.asyncio
    async def test_cache_initialization(self):
        """Test cache initialization"""
        cache = AsyncCache(max_size=100, default_ttl=timedelta(minutes=10))
        
        assert cache._max_size == 100
        assert cache._default_ttl == timedelta(minutes=10)
        assert len(cache._cache) == 0
        assert cache._hits == 0
        assert cache._misses == 0
    
    @pytest.mark.asyncio
    async def test_cache_set_and_get(self):
        """Test basic cache set and get operations"""
        cache = AsyncCache()
        
        # Set value
        await cache.set("key1", "value1")
        
        # Get value
        value = await cache.get("key1")
        assert value == "value1"
        assert cache._hits == 1
        assert cache._misses == 0
        
        # Get non-existent key
        value = await cache.get("key2")
        assert value is None
        assert cache._hits == 1
        assert cache._misses == 1
    
    @pytest.mark.asyncio
    async def test_cache_ttl(self):
        """Test cache TTL functionality"""
        cache = AsyncCache(default_ttl=timedelta(seconds=0.1))
        
        # Set value with short TTL
        await cache.set("key1", "value1")
        
        # Should be available immediately
        value = await cache.get("key1")
        assert value == "value1"
        
        # Wait for expiration
        await asyncio.sleep(0.2)
        
        # Should be expired
        value = await cache.get("key1")
        assert value is None
        assert "key1" not in cache._cache
    
    @pytest.mark.asyncio
    async def test_cache_custom_ttl(self):
        """Test setting custom TTL per entry"""
        cache = AsyncCache(default_ttl=timedelta(minutes=10))
        
        # Set with custom TTL
        await cache.set("key1", "value1", ttl=timedelta(seconds=0.1))
        
        # Should expire based on custom TTL
        await asyncio.sleep(0.2)
        value = await cache.get("key1")
        assert value is None
    
    @pytest.mark.asyncio
    async def test_cache_eviction_expired_first(self):
        """Test cache evicts expired entries first when at capacity"""
        cache = AsyncCache(max_size=3)
        
        # Fill cache with one expired entry
        expires_soon = datetime.now() - timedelta(seconds=1)
        cache._cache["expired"] = CacheEntry("old", expires_soon)
        
        await cache.set("key1", "value1")
        await cache.set("key2", "value2")
        await cache.set("key3", "value3")  # Should evict expired entry
        
        assert len(cache._cache) == 3
        assert "expired" not in cache._cache
        assert all(key in cache._cache for key in ["key1", "key2", "key3"])
    
    @pytest.mark.asyncio
    async def test_cache_lru_eviction(self):
        """Test LRU eviction when cache is full"""
        cache = AsyncCache(max_size=3)
        
        # Fill cache
        await cache.set("key1", "value1")
        await cache.set("key2", "value2")
        await cache.set("key3", "value3")
        
        # Access key1 and key3 to increase hits
        await cache.get("key1")
        await cache.get("key3")
        await cache.get("key3")  # key3 has most hits
        
        # Add new key, should evict key2 (least recently used)
        await cache.set("key4", "value4")
        
        assert len(cache._cache) == 3
        assert "key2" not in cache._cache
        assert all(key in cache._cache for key in ["key1", "key3", "key4"])
    
    @pytest.mark.asyncio
    async def test_cache_clear(self):
        """Test clearing cache"""
        cache = AsyncCache()
        
        # Add some entries
        await cache.set("key1", "value1")
        await cache.set("key2", "value2")
        cache._hits = 5
        cache._misses = 2
        
        # Clear cache
        await cache.clear()
        
        assert len(cache._cache) == 0
        assert cache._hits == 0
        assert cache._misses == 0
    
    @pytest.mark.asyncio
    async def test_cache_metrics(self):
        """Test cache metrics calculation"""
        cache = AsyncCache()
        
        # Generate some activity
        await cache.set("key1", "value1")
        await cache.get("key1")  # Hit
        await cache.get("key1")  # Hit
        await cache.get("key2")  # Miss
        await cache.get("key3")  # Miss
        
        metrics = cache.get_metrics()
        
        assert metrics["size"] == 1
        assert metrics["hits"] == 2
        assert metrics["misses"] == 2
        assert metrics["hit_rate"] == 0.5
        assert metrics["total_requests"] == 4
    
    @pytest.mark.asyncio
    async def test_cache_concurrent_access(self):
        """Test concurrent cache access"""
        cache = AsyncCache()
        
        # Concurrent writes
        async def write_to_cache(key, value):
            await cache.set(key, value)
            return await cache.get(key)
        
        # Run concurrent operations
        tasks = [write_to_cache(f"key{i}", f"value{i}") for i in range(10)]
        results = await asyncio.gather(*tasks)
        
        assert all(results[i] == f"value{i}" for i in range(10))
        assert len(cache._cache) == 10


class TestBatchProcessor:
    """Test BatchProcessor functionality"""
    
    @pytest.mark.asyncio
    async def test_batch_processor_initialization(self):
        """Test batch processor initialization"""
        async def process_batch(items):
            return [item * 2 for item in items]
        
        processor = BatchProcessor(
            process_func=process_batch,
            max_batch_size=10,
            max_wait_time=timedelta(seconds=1)
        )
        
        assert processor._max_batch_size == 10
        assert processor._max_wait_time == timedelta(seconds=1)
        assert len(processor._pending_items) == 0
    
    @pytest.mark.asyncio
    async def test_batch_processing_by_size(self):
        """Test batch processing triggered by size"""
        results = []
        
        async def process_batch(items):
            results.append(items)
            return [item * 2 for item in items]
        
        processor = BatchProcessor(
            process_func=process_batch,
            max_batch_size=3,
            max_wait_time=timedelta(seconds=10)
        )
        
        # Start processor
        process_task = asyncio.create_task(processor.start())
        
        try:
            # Add items to trigger batch
            futures = []
            for i in range(3):
                future = await processor.add_item(i)
                futures.append(future)
            
            # Wait for processing
            processed = await asyncio.gather(*futures)
            
            assert processed == [0, 2, 4]
            assert len(results) == 1
            assert results[0] == [0, 1, 2]
            
        finally:
            await processor.stop()
            await process_task
    
    @pytest.mark.asyncio
    async def test_batch_processing_by_timeout(self):
        """Test batch processing triggered by timeout"""
        results = []
        
        async def process_batch(items):
            results.append(items)
            return [item * 2 for item in items]
        
        processor = BatchProcessor(
            process_func=process_batch,
            max_batch_size=10,
            max_wait_time=timedelta(seconds=0.1)
        )
        
        # Start processor
        process_task = asyncio.create_task(processor.start())
        
        try:
            # Add items (not enough to trigger by size)
            futures = []
            for i in range(2):
                future = await processor.add_item(i)
                futures.append(future)
            
            # Wait for timeout to trigger processing
            processed = await asyncio.gather(*futures)
            
            assert processed == [0, 2]
            assert len(results) == 1
            assert results[0] == [0, 1]
            
        finally:
            await processor.stop()
            await process_task
    
    @pytest.mark.asyncio
    async def test_batch_processor_error_handling(self):
        """Test error handling in batch processing"""
        async def process_batch(items):
            if 3 in items:
                raise ValueError("Cannot process 3")
            return [item * 2 for item in items]
        
        processor = BatchProcessor(
            process_func=process_batch,
            max_batch_size=5
        )
        
        process_task = asyncio.create_task(processor.start())
        
        try:
            # Add items including error trigger
            futures = []
            for i in range(5):
                future = await processor.add_item(i)
                futures.append(future)
            
            # Should raise error for all items in batch
            with pytest.raises(ValueError, match="Cannot process 3"):
                await asyncio.gather(*futures)
                
        finally:
            await processor.stop()
            await process_task
    
    @pytest.mark.asyncio
    async def test_batch_processor_stop(self):
        """Test stopping batch processor processes remaining items"""
        results = []
        
        async def process_batch(items):
            results.append(items)
            return [item * 2 for item in items]
        
        processor = BatchProcessor(
            process_func=process_batch,
            max_batch_size=10,
            max_wait_time=timedelta(seconds=10)
        )
        
        process_task = asyncio.create_task(processor.start())
        
        # Add items (not enough to trigger)
        futures = []
        for i in range(3):
            future = await processor.add_item(i)
            futures.append(future)
        
        # Stop should process remaining items
        await processor.stop()
        await process_task
        
        # Check results
        processed = await asyncio.gather(*futures)
        assert processed == [0, 2, 4]
        assert len(results) == 1


class TestQueryOptimizer:
    """Test QueryOptimizer functionality"""
    
    @pytest.mark.asyncio
    async def test_query_optimizer_initialization(self):
        """Test query optimizer initialization"""
        optimizer = QueryOptimizer()
        
        assert isinstance(optimizer._query_cache, AsyncCache)
        assert optimizer._query_cache._max_size == 500
        assert optimizer._query_patterns == {}
    
    @pytest.mark.asyncio
    async def test_optimize_query_caching(self):
        """Test query optimization with caching"""
        optimizer = QueryOptimizer()
        
        # Mock query execution
        execution_count = 0
        async def mock_execute(query, params):
            nonlocal execution_count
            execution_count += 1
            return f"Result for {params['id']}"
        
        # First execution
        query = "SELECT * FROM table WHERE id = :id"
        params = {"id": 123}
        
        result1 = await optimizer.optimize_query(query, params, mock_execute)
        assert result1 == "Result for 123"
        assert execution_count == 1
        
        # Second execution (should use cache)
        result2 = await optimizer.optimize_query(query, params, mock_execute)
        assert result2 == "Result for 123"
        assert execution_count == 1  # Not incremented
    
    @pytest.mark.asyncio
    async def test_query_pattern_analysis(self):
        """Test query pattern analysis"""
        optimizer = QueryOptimizer()
        
        # Analyze similar queries
        queries = [
            "SELECT * FROM users WHERE id = 1",
            "SELECT * FROM users WHERE id = 2",
            "SELECT * FROM users WHERE id = 3",
            "SELECT * FROM posts WHERE user_id = 1",
            "SELECT * FROM posts WHERE user_id = 2",
        ]
        
        for query in queries:
            optimizer.analyze_pattern(query)
        
        patterns = optimizer.get_patterns()
        
        # Should identify patterns
        assert len(patterns) > 0
        
        # Should have user and post patterns
        user_patterns = [p for p in patterns if "users" in p["pattern"]]
        post_patterns = [p for p in patterns if "posts" in p["pattern"]]
        
        assert len(user_patterns) > 0
        assert len(post_patterns) > 0
        assert user_patterns[0]["count"] == 3
        assert post_patterns[0]["count"] == 2


class TestEmbeddingBatcher:
    """Test EmbeddingBatcher functionality"""
    
    @pytest.mark.asyncio
    async def test_embedding_batcher_initialization(self):
        """Test embedding batcher initialization"""
        mock_embedder = Mock()
        batcher = EmbeddingBatcher(mock_embedder, batch_size=5)
        
        assert batcher._embedder == mock_embedder
        assert batcher._batch_processor._max_batch_size == 5
        assert isinstance(batcher._cache, AsyncCache)
    
    @pytest.mark.asyncio
    async def test_embedding_generation_single(self):
        """Test single embedding generation"""
        mock_embedder = Mock()
        mock_embedder.aembed_documents = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
        
        batcher = EmbeddingBatcher(mock_embedder)
        
        # Start batcher
        await batcher.start()
        
        try:
            embedding = await batcher.get_embedding("test text")
            
            assert embedding == [0.1, 0.2, 0.3]
            mock_embedder.aembed_documents.assert_called_once_with(["test text"])
            
        finally:
            await batcher.stop()
    
    @pytest.mark.asyncio
    async def test_embedding_caching(self):
        """Test embedding caching"""
        mock_embedder = Mock()
        call_count = 0
        
        async def mock_embed(texts):
            nonlocal call_count
            call_count += 1
            return [[0.1 * i, 0.2 * i, 0.3 * i] for i in range(len(texts))]
        
        mock_embedder.aembed_documents = mock_embed
        
        batcher = EmbeddingBatcher(mock_embedder)
        await batcher.start()
        
        try:
            # First call
            embedding1 = await batcher.get_embedding("test text")
            assert call_count == 1
            
            # Second call (should use cache)
            embedding2 = await batcher.get_embedding("test text")
            assert call_count == 1  # Not incremented
            assert embedding1 == embedding2
            
        finally:
            await batcher.stop()
    
    @pytest.mark.asyncio
    async def test_embedding_batch_processing(self):
        """Test batch processing of embeddings"""
        mock_embedder = Mock()
        processed_batches = []
        
        async def mock_embed(texts):
            processed_batches.append(texts)
            return [[0.1 * i, 0.2 * i, 0.3 * i] for i in range(len(texts))]
        
        mock_embedder.aembed_documents = mock_embed
        
        batcher = EmbeddingBatcher(mock_embedder, batch_size=3)
        await batcher.start()
        
        try:
            # Generate multiple embeddings concurrently
            tasks = []
            for i in range(3):
                task = batcher.get_embedding(f"text {i}")
                tasks.append(task)
            
            embeddings = await asyncio.gather(*tasks)
            
            # Should process as single batch
            assert len(processed_batches) == 1
            assert len(processed_batches[0]) == 3
            assert len(embeddings) == 3
            
        finally:
            await batcher.stop()


class TestGlobalCaches:
    """Test global cache instances"""
    
    @pytest.mark.asyncio
    async def test_query_cache_singleton(self):
        """Test query_cache is a singleton"""
        from app.core.performance_utils import query_cache as cache1
        from app.core.performance_utils import query_cache as cache2
        
        assert cache1 is cache2
    
    @pytest.mark.asyncio
    async def test_embedding_cache_singleton(self):
        """Test embedding_cache is a singleton"""
        from app.core.performance_utils import embedding_cache as cache1
        from app.core.performance_utils import embedding_cache as cache2
        
        assert cache1 is cache2


class TestCachedQueryDecorator:
    """Test cached_query decorator"""
    
    @pytest.mark.asyncio
    async def test_cached_query_decorator(self):
        """Test cached_query decorator functionality"""
        call_count = 0
        
        @cached_query(ttl=timedelta(seconds=1))
        async def expensive_query(param1, param2):
            nonlocal call_count
            call_count += 1
            return f"Result: {param1} + {param2}"
        
        # First call
        result1 = await expensive_query("a", "b")
        assert result1 == "Result: a + b"
        assert call_count == 1
        
        # Second call (cached)
        result2 = await expensive_query("a", "b")
        assert result2 == "Result: a + b"
        assert call_count == 1  # Not incremented
        
        # Different parameters
        result3 = await expensive_query("c", "d")
        assert result3 == "Result: c + d"
        assert call_count == 2
        
        # Wait for TTL expiration
        await asyncio.sleep(1.1)
        
        # Should execute again
        result4 = await expensive_query("a", "b")
        assert result4 == "Result: a + b"
        assert call_count == 3