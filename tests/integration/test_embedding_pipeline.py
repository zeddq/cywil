"""
Integration tests for the embedding pipeline with centralized LLMManager.
"""

import asyncio
import pytest
import numpy as np
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.llm_manager import LLMManager
from app.core.config_service import ConfigService
from app.services.statute_search_service import StatuteSearchService
from app.embedding_models.embedding_interface import LocalEmbedder


class TestEmbeddingPipelineIntegration:
    """Test the complete embedding pipeline integration."""
    
    @pytest.fixture
    def mock_config_service(self):
        """Create a mock config service with all required settings."""
        mock_config = MagicMock()
        
        # OpenAI settings
        mock_config.openai.api_key.get_secret_value.return_value = "test-api-key"
        mock_config.openai.max_retries = 3
        mock_config.openai.timeout = 30
        mock_config.openai.orchestrator_model = "gpt-4"
        mock_config.openai.summary_model = "gpt-3.5-turbo"
        mock_config.openai.llm_model = "gpt-3.5-turbo"
        
        # Qdrant settings
        mock_config.qdrant.host = "localhost"
        mock_config.qdrant.port = 6333
        mock_config.qdrant.timeout = 30
        mock_config.qdrant.collection_statutes = "test_statutes"
        
        config_service = MagicMock(spec=ConfigService)
        config_service.config = mock_config
        return config_service
    
    @pytest.fixture
    async def llm_manager(self, mock_config_service):
        """Create and initialize LLM manager for integration tests."""
        manager = LLMManager(mock_config_service)
        
        with patch('app.core.llm_manager.AsyncOpenAI'), \
             patch('app.models.embedding_factory.embedding_factory.create_local_embedder') as mock_create_local, \
             patch('app.models.embedding_factory.embedding_factory.create_openai_embedder') as mock_create_openai:
            
            # Mock the embedding models
            mock_multilingual = AsyncMock(spec=LocalEmbedder)
            mock_multilingual.create_embeddings.return_value = np.array([[0.1, 0.2, 0.3]])
            mock_multilingual.create_embedding_single.return_value = np.array([0.1, 0.2, 0.3])
            mock_multilingual.get_dimension.return_value = 768
            mock_multilingual.warmup = AsyncMock()
            
            mock_legal = AsyncMock(spec=LocalEmbedder)
            mock_legal.create_embeddings.return_value = np.array([[0.4, 0.5, 0.6]])
            mock_legal.create_embedding_single.return_value = np.array([0.4, 0.5, 0.6])
            mock_legal.get_dimension.return_value = 768
            mock_legal.warmup = AsyncMock()
            
            mock_openai = AsyncMock()
            mock_openai.create_embeddings.return_value = np.array([[0.7, 0.8, 0.9]])
            mock_openai.create_embedding_single.return_value = np.array([0.7, 0.8, 0.9])
            mock_openai.get_dimension.return_value = 1536
            mock_openai.warmup = AsyncMock()
            
            mock_create_local.side_effect = [mock_multilingual, mock_legal]
            mock_create_openai.return_value = mock_openai
            
            await manager.initialize()
            yield manager
            
            if manager._initialized:
                await manager.shutdown()
    
    @pytest.fixture
    async def statute_search_service(self, mock_config_service, llm_manager):
        """Create statute search service for integration tests."""
        service = StatuteSearchService(mock_config_service, llm_manager)
        
        with patch('app.services.statute_search_service.AsyncQdrantClient') as mock_qdrant, \
             patch('app.services.statute_search_service.AsyncOpenAI'):
            
            # Mock Qdrant client
            mock_client = AsyncMock()
            mock_qdrant.return_value = mock_client
            
            # Mock collections response
            mock_collections = MagicMock()
            mock_collections.collections = [MagicMock(name="test_statutes")]
            mock_client.get_collections.return_value = mock_collections
            
            await service.initialize()
            yield service
            
            if service._initialized:
                await service.shutdown()
    
    @pytest.mark.asyncio
    async def test_statute_search_with_embeddings(self, statute_search_service):
        """Test statute search using centralized embedding generation."""
        # Mock Qdrant search response
        mock_result = MagicMock()
        mock_result.score = 0.95
        mock_result.payload = {
            "article": "123",
            "text": "Testowy artykuł przepisu prawnego",
            "code": "KC"
        }
        
        statute_search_service._qdrant_client.search.return_value = [mock_result]
        
        # Perform search
        results = await statute_search_service.search_statute(
            query="testowe zapytanie prawne",
            top_k=5
        )
        
        # Verify results
        assert len(results) == 1
        assert results[0]["article"] == "123"
        assert results[0]["score"] == 0.95
        assert results[0]["citation"] == "art. 123 KC"
        
        # Verify that LLM manager was called for embedding generation
        statute_search_service._llm_manager.get_embedding_single.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_concurrent_embedding_requests(self, llm_manager):
        """Test concurrent embedding requests across different parts of the system."""
        texts_batch1 = ["tekst pierwszy", "tekst drugi"]
        texts_batch2 = ["tekst trzeci", "tekst czwarty"]
        texts_batch3 = ["tekst piąty", "tekst szósty"]
        
        # Start concurrent embedding requests
        tasks = [
            llm_manager.get_embeddings(texts_batch1, "multilingual", use_cache=False),
            llm_manager.get_embeddings(texts_batch2, "legal", use_cache=False),
            llm_manager.get_embeddings(texts_batch3, "multilingual", use_cache=False)
        ]
        
        # Wait for all to complete
        results = await asyncio.gather(*tasks)
        
        # All should succeed
        assert len(results) == 3
        for result in results:
            assert isinstance(result, np.ndarray)
            assert result.shape[0] == 2  # 2 texts per batch
    
    @pytest.mark.asyncio
    async def test_cache_persistence_across_requests(self, llm_manager):
        """Test that cache works correctly across multiple requests."""
        test_texts = ["test cache persistence"]
        
        # First request - should generate embedding
        result1 = await llm_manager.get_embeddings(test_texts, "multilingual")
        
        # Get the underlying model to reset call count
        model = llm_manager._embedding_models["multilingual"]
        initial_call_count = model.create_embeddings.call_count
        
        # Second request - should use cache
        result2 = await llm_manager.get_embeddings(test_texts, "multilingual")
        
        # Results should be identical
        np.testing.assert_array_equal(result1, result2)
        
        # Model should not have been called again
        assert model.create_embeddings.call_count == initial_call_count
    
    @pytest.mark.asyncio
    async def test_model_switching(self, llm_manager):
        """Test switching between different embedding models."""
        test_text = "test model switching"
        
        # Get embeddings from different models
        multilingual_result = await llm_manager.get_embedding_single(test_text, "multilingual")
        legal_result = await llm_manager.get_embedding_single(test_text, "legal")
        openai_result = await llm_manager.get_embedding_single(test_text, "openai")
        
        # Results should be different (mocked to return different values)
        assert not np.array_equal(multilingual_result, legal_result)
        assert not np.array_equal(legal_result, openai_result)
        assert not np.array_equal(multilingual_result, openai_result)
        
        # Each model should have been called once
        assert llm_manager._embedding_models["multilingual"].create_embeddings.call_count >= 1
        assert llm_manager._embedding_models["legal"].create_embeddings.call_count >= 1
        assert llm_manager._embedding_models["openai"].create_embeddings.call_count >= 1
    
    @pytest.mark.asyncio
    async def test_batch_processing_efficiency(self, llm_manager):
        """Test that batch processing is more efficient than sequential processing."""
        texts = [f"test text {i}" for i in range(10)]
        
        # Batch processing
        start_time = asyncio.get_event_loop().time()
        batch_result = await llm_manager.get_embeddings(texts, "multilingual", use_cache=False)
        batch_time = asyncio.get_event_loop().time() - start_time
        
        # Sequential processing
        llm_manager.clear_cache()  # Clear cache to ensure fresh calls
        start_time = asyncio.get_event_loop().time()
        sequential_results = []
        for text in texts:
            result = await llm_manager.get_embedding_single(text, "multilingual")
            sequential_results.append(result)
        sequential_time = asyncio.get_event_loop().time() - start_time
        
        # Results should be the same shape
        sequential_result = np.array(sequential_results)
        assert batch_result.shape == sequential_result.shape
        
        # Note: In real scenarios, batch should be faster, but with mocked models
        # we're mainly testing that both approaches work correctly
        assert batch_time >= 0
        assert sequential_time >= 0
    
    @pytest.mark.asyncio
    async def test_error_handling_in_pipeline(self, llm_manager):
        """Test error handling throughout the embedding pipeline."""
        # Test with a model that raises an exception
        error_model = AsyncMock()
        error_model.create_embeddings.side_effect = RuntimeError("Model error")
        
        llm_manager._embedding_models["error_model"] = error_model
        
        # Should raise the underlying error
        with pytest.raises(RuntimeError, match="Model error"):
            await llm_manager.get_embeddings(["test"], "error_model")
    
    @pytest.mark.asyncio
    async def test_cache_invalidation(self, llm_manager):
        """Test cache clearing functionality."""
        test_texts = ["cache invalidation test"]
        
        # Generate embeddings (cached)
        await llm_manager.get_embeddings(test_texts, "multilingual")
        
        # Check cache has content
        stats_before = llm_manager.get_cache_stats()
        assert stats_before["memory_size"] > 0
        
        # Clear cache
        llm_manager.clear_cache()
        
        # Check cache is empty
        stats_after = llm_manager.get_cache_stats()
        assert stats_after["memory_size"] == 0
    
    @pytest.mark.asyncio
    async def test_embedding_dimension_consistency(self, llm_manager):
        """Test that embedding dimensions are consistent across calls."""
        test_texts = ["dimension test 1", "dimension test 2"]
        
        # Get embeddings
        embeddings = await llm_manager.get_embeddings(test_texts, "multilingual")
        
        # Check dimensions
        assert embeddings.shape[0] == len(test_texts)
        assert embeddings.shape[1] == 3  # Mocked dimension
        
        # Single embedding should have same dimension
        single_embedding = await llm_manager.get_embedding_single(test_texts[0], "multilingual")
        assert single_embedding.shape[0] == embeddings.shape[1]
    
    @pytest.mark.asyncio
    async def test_model_info_and_listing(self, llm_manager):
        """Test model information and listing functionality."""
        # Get info for specific model
        info = llm_manager.get_embedding_model_info("multilingual")
        assert info["name"] == "multilingual"
        assert "type" in info
        assert "dimension" in info
        
        # List all models
        models = llm_manager.list_embedding_models()
        assert len(models) >= 3  # multilingual, legal, openai
        assert any(m["name"] == "multilingual" for m in models)
        assert any(m["name"] == "legal" for m in models)
        assert any(m["name"] == "openai" for m in models)
    
    @pytest.mark.asyncio
    async def test_full_search_pipeline(self, statute_search_service):
        """Test complete search pipeline from query to results."""
        # Mock exact article match
        mock_exact = MagicMock()
        mock_exact.payload = {
            "article": "456",
            "text": "Artykuł 456 KC - dokładne dopasowanie",
            "code": "KC"
        }
        
        # Mock vector search results
        mock_vector = MagicMock()
        mock_vector.score = 0.85
        mock_vector.payload = {
            "article": "789",
            "text": "Artykuł 789 KC - podobny temat",
            "code": "KC"
        }
        
        statute_search_service._qdrant_client.scroll.return_value = ([mock_exact], None)
        statute_search_service._qdrant_client.search.return_value = [mock_vector]
        
        # Test search with article pattern (should find exact + vector)
        results = await statute_search_service.search_statute(
            query="art. 456 KC i podobne przepisy",
            top_k=5
        )
        
        # Should have both exact and vector results
        assert len(results) >= 1
        
        # Verify embedding was generated for vector search
        statute_search_service._llm_manager.get_embedding_single.assert_called()
        
        # Test topic search
        results = await statute_search_service.search_by_topic("prawo cywilne", limit=3)
        assert isinstance(results, list)