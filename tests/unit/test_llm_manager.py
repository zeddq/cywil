"""
Unit tests for the centralized LLMManager service.
"""

import asyncio
import pytest
import numpy as np
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.llm_manager import LLMManager, TwoTierCache
from app.core.config_service import ConfigService
from app.embedding_models.embedding_interface import LocalEmbedder


class TestTwoTierCache:
    """Test the two-tier caching system."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.cache = TwoTierCache(memory_size=3)
    
    def test_memory_cache_basic_operations(self):
        """Test basic memory cache operations."""
        # Test put and get
        embedding = np.array([1.0, 2.0, 3.0])
        self.cache.put("key1", embedding)
        
        result = self.cache.get("key1")
        assert result is not None
        np.testing.assert_array_equal(result, embedding)
    
    def test_memory_cache_lru_eviction(self):
        """Test LRU eviction in memory cache."""
        # Fill cache to capacity
        for i in range(3):
            embedding = np.array([float(i), float(i), float(i)])
            self.cache.put(f"key{i}", embedding)
        
        # Add one more item - should evict oldest (key0)
        embedding = np.array([3.0, 3.0, 3.0])
        self.cache.put("key3", embedding)
        
        # key0 should be evicted
        assert self.cache.get("key0") is None
        # Others should still be there
        assert self.cache.get("key1") is not None
        assert self.cache.get("key2") is not None
        assert self.cache.get("key3") is not None
    
    def test_memory_cache_access_order(self):
        """Test that accessing items updates LRU order."""
        # Fill cache
        for i in range(3):
            embedding = np.array([float(i), float(i), float(i)])
            self.cache.put(f"key{i}", embedding)
        
        # Access key0 to make it most recently used
        self.cache.get("key0")
        
        # Add new item - should evict key1 (oldest)
        embedding = np.array([3.0, 3.0, 3.0])
        self.cache.put("key3", embedding)
        
        # key0 should still be there, key1 should be evicted
        assert self.cache.get("key0") is not None
        assert self.cache.get("key1") is None
    
    def test_cache_stats(self):
        """Test cache statistics."""
        stats = self.cache.get_stats()
        assert stats["memory_size"] == 0
        assert stats["memory_max_size"] == 3
        
        # Add some items
        for i in range(2):
            embedding = np.array([float(i), float(i), float(i)])
            self.cache.put(f"key{i}", embedding)
        
        stats = self.cache.get_stats()
        assert stats["memory_size"] == 2
    
    def test_clear_cache(self):
        """Test cache clearing."""
        embedding = np.array([1.0, 2.0, 3.0])
        self.cache.put("key1", embedding)
        
        assert self.cache.get("key1") is not None
        
        self.cache.clear()
        assert self.cache.get("key1") is None
        
        stats = self.cache.get_stats()
        assert stats["memory_size"] == 0


class TestLLMManager:
    """Test the centralized LLMManager."""
    
    @pytest.fixture
    def mock_config_service(self):
        """Create a mock config service."""
        mock_config = MagicMock()
        mock_config.openai.api_key.get_secret_value.return_value = "test-api-key"
        mock_config.openai.max_retries = 3
        mock_config.openai.timeout = 30
        mock_config.openai.orchestrator_model = "gpt-4"
        mock_config.openai.summary_model = "gpt-3.5-turbo"
        mock_config.openai.llm_model = "gpt-3.5-turbo"
        
        config_service = MagicMock(spec=ConfigService)
        config_service.config = mock_config
        return config_service
    
    @pytest.fixture
    def llm_manager(self, mock_config_service):
        """Create LLM manager for testing."""
        return LLMManager(mock_config_service)
    
    @pytest.mark.asyncio
    async def test_initialization(self, llm_manager):
        """Test LLM manager initialization."""
        with patch('app.core.llm_manager.AsyncOpenAI'), \
             patch('app.models.embedding_factory.embedding_factory.create_local_embedder') as mock_create_local, \
             patch('app.models.embedding_factory.embedding_factory.create_openai_embedder') as mock_create_openai:
            
            # Mock the embedding models
            mock_multilingual = AsyncMock(spec=LocalEmbedder)
            mock_legal = AsyncMock(spec=LocalEmbedder)
            mock_openai = AsyncMock()
            
            mock_create_local.side_effect = [mock_multilingual, mock_legal]
            mock_create_openai.return_value = mock_openai
            
            await llm_manager.initialize()
            
            assert llm_manager._initialized
            assert "multilingual" in llm_manager._embedding_models
            assert "legal" in llm_manager._embedding_models
            assert "openai" in llm_manager._embedding_models
    
    @pytest.mark.asyncio
    async def test_get_embeddings_caching(self, llm_manager):
        """Test embedding generation with caching."""
        # Mock the embedding model
        mock_model = AsyncMock()
        mock_embeddings = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
        mock_model.create_embeddings.return_value = mock_embeddings
        
        llm_manager._initialized = True
        llm_manager._embedding_models = {"multilingual": mock_model}
        
        texts = ["test1", "test2"]
        
        # First call should generate embeddings
        result1 = await llm_manager.get_embeddings(texts, "multilingual")
        np.testing.assert_array_equal(result1, mock_embeddings)
        mock_model.create_embeddings.assert_called_once_with(texts, 32)
        
        # Second call should use cache
        mock_model.create_embeddings.reset_mock()
        result2 = await llm_manager.get_embeddings(texts, "multilingual")
        np.testing.assert_array_equal(result2, mock_embeddings)
        mock_model.create_embeddings.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_get_embedding_single(self, llm_manager):
        """Test single embedding generation."""
        mock_model = AsyncMock()
        mock_embeddings = np.array([[1.0, 2.0, 3.0]])
        mock_model.create_embeddings.return_value = mock_embeddings
        
        llm_manager._initialized = True
        llm_manager._embedding_models = {"multilingual": mock_model}
        
        result = await llm_manager.get_embedding_single("test text")
        np.testing.assert_array_equal(result, mock_embeddings[0])
    
    @pytest.mark.asyncio
    async def test_get_embeddings_fallback_model(self, llm_manager):
        """Test fallback to default model when unknown model requested."""
        mock_model = AsyncMock()
        mock_embeddings = np.array([[1.0, 2.0, 3.0]])
        mock_model.create_embeddings.return_value = mock_embeddings
        
        llm_manager._initialized = True
        llm_manager._embedding_models = {"multilingual": mock_model}
        
        # Request unknown model - should fallback to multilingual
        result = await llm_manager.get_embeddings(["test"], "unknown_model")
        np.testing.assert_array_equal(result, mock_embeddings)
        mock_model.create_embeddings.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_concurrent_embedding_requests(self, llm_manager):
        """Test concurrent embedding requests with semaphore limiting."""
        mock_model = AsyncMock()
        mock_embeddings = np.array([[1.0, 2.0, 3.0]])
        
        # Add delay to simulate processing time
        async def slow_create_embeddings(*args, **kwargs):
            await asyncio.sleep(0.1)
            return mock_embeddings
        
        mock_model.create_embeddings.side_effect = slow_create_embeddings
        
        llm_manager._initialized = True
        llm_manager._embedding_models = {"multilingual": mock_model}
        
        # Start multiple concurrent requests
        tasks = []
        for i in range(5):
            task = asyncio.create_task(
                llm_manager.get_embeddings([f"test{i}"], "multilingual", use_cache=False)
            )
            tasks.append(task)
        
        # Wait for all to complete
        results = await asyncio.gather(*tasks)
        
        # All should succeed
        assert len(results) == 5
        for result in results:
            np.testing.assert_array_equal(result, mock_embeddings)
    
    def test_compute_similarity(self, llm_manager):
        """Test cosine similarity computation."""
        vec1 = [1.0, 0.0, 0.0]
        vec2 = [0.0, 1.0, 0.0]
        vec3 = [1.0, 0.0, 0.0]
        
        # Orthogonal vectors should have similarity 0
        similarity = llm_manager.compute_similarity(vec1, vec2)
        assert abs(similarity) < 1e-6
        
        # Identical vectors should have similarity 1
        similarity = llm_manager.compute_similarity(vec1, vec3)
        assert abs(similarity - 1.0) < 1e-6
    
    def test_find_most_similar(self, llm_manager):
        """Test finding most similar embeddings."""
        query = [1.0, 0.0, 0.0]
        candidates = [
            [1.0, 0.0, 0.0],  # identical - highest similarity
            [0.0, 1.0, 0.0],  # orthogonal - lowest similarity
            [0.5, 0.5, 0.0],  # partial match
        ]
        
        results = llm_manager.find_most_similar(query, candidates, top_k=2)
        
        # Should return indices 0 and 2 (highest similarities)
        assert len(results) == 2
        assert results[0][0] == 0  # Index of most similar
        assert results[1][0] == 2  # Index of second most similar
        assert results[0][1] > results[1][1]  # Similarities in descending order
    
    @pytest.mark.asyncio
    async def test_health_check(self, llm_manager):
        """Test health check functionality."""
        with patch.object(llm_manager, 'get_embeddings') as mock_get_embeddings, \
             patch.object(llm_manager, 'generate_completion') as mock_generate:
            
            mock_get_embeddings.return_value = np.array([[1.0, 2.0, 3.0]])
            mock_generate.return_value = "OK"
            
            llm_manager._initialized = True
            llm_manager._embedding_models = {"multilingual": MagicMock()}
            llm_manager._llm_clients = {"default": {"model": "gpt-3.5-turbo"}}
            
            result = await llm_manager._health_check_impl()
            
            assert result.status.value == "healthy"
            assert "embedding_models" in result.details
            assert "llm_models" in result.details
    
    def test_cache_stats(self, llm_manager):
        """Test cache statistics reporting."""
        llm_manager._embedding_models = {"multilingual": MagicMock()}
        
        stats = llm_manager.get_cache_stats()
        
        assert "memory_size" in stats
        assert "memory_max_size" in stats
        assert "models_loaded" in stats
        assert "factory_models" in stats
    
    def test_embedding_model_info(self, llm_manager):
        """Test getting embedding model information."""
        mock_model = MagicMock()
        mock_model.get_dimension.return_value = 768
        
        llm_manager._embedding_models = {"multilingual": mock_model}
        
        info = llm_manager.get_embedding_model_info("multilingual")
        
        assert info["name"] == "multilingual"
        assert info["dimension"] == 768
        assert "type" in info
    
    def test_list_embedding_models(self, llm_manager):
        """Test listing all embedding models."""
        mock_model1 = MagicMock()
        mock_model1.get_dimension.return_value = 768
        mock_model2 = MagicMock()
        mock_model2.get_dimension.return_value = 384
        
        llm_manager._embedding_models = {
            "multilingual": mock_model1,
            "legal": mock_model2
        }
        
        models = llm_manager.list_embedding_models()
        
        assert len(models) == 2
        assert any(m["name"] == "multilingual" for m in models)
        assert any(m["name"] == "legal" for m in models)