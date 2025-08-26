"""
Optimized version of StatuteSearchService with performance improvements.
"""

import asyncio
import re
from datetime import timedelta
from typing import Any, Dict, List, Optional

from qdrant_client.models import Condition, FieldCondition, Filter, MatchValue

from ..core.logger_manager import get_logger
from ..core.llm_manager import LLMManager
from ..core.config_service import ConfigService
from ..core.performance_utils import (
    BatchProcessor,
    EmbeddingBatcher,
    optimize_query_with_cache,
)
from .statute_search_service import StatuteSearchService

logger = get_logger(__name__)


class OptimizedStatuteSearchService(StatuteSearchService):
    """
    Optimized version with caching, batching, and concurrent execution.
    """

    def __init__(self, config_service: ConfigService, llm_manager: LLMManager):
        super().__init__(config_service, llm_manager)
        self._llm_manager = llm_manager
        self._embedding_batcher: Optional[EmbeddingBatcher] = None
        # Create a simple batch processor function for embeddings
        async def process_batch(items):
            return await self._process_embedding_batch(items)
        self._batch_processor = BatchProcessor(process_batch, max_batch_size=5, max_wait_time=timedelta(seconds=0.1))

    async def _initialize_impl(self) -> None:
        """Initialize with optimizations"""
        await super()._initialize_impl()

        # Create embedding batcher using LLM manager instead of direct embedder
        self._embedding_batcher = EmbeddingBatcher(self._llm_manager, batch_size=16, max_wait=0.2)

        logger.info("Optimized statute search service initialized")

    async def _process_embedding_batch(self, items):
        """Process a batch of embedding requests"""
        # This would be implemented with actual batch processing logic
        # For now, just process them individually using LLM manager
        if not self._llm_manager._initialized:
            raise RuntimeError("LLM Manager not initialized")
        results = []
        for item in items:
            # Use LLM manager's embedding functionality
            result = await self._llm_manager.get_embedding_single(item, model_name="multilingual")
            results.append(result)
        return results

    @optimize_query_with_cache(ttl=timedelta(hours=1))
    async def search_statute(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Cached version of statute search.
        Cache key includes query and top_k to handle different result sizes.
        """
        return await self._search_statute_impl(query, top_k)

    async def _search_statute_impl(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        """Implementation of statute search with optimizations"""
        logger.info(f"Searching statutes for: {query[:100]}...")

        # Check for article reference pattern
        article_pattern = r"art\.?\s*(\d+)\s*(§\s*\d+)?\s*(k\.?[cp]\.?|kodeks[u]?\s+(cywilnego|postępowania\s+cywilnego))?"
        article_match = re.search(article_pattern, query.lower())

        if article_match:
            # Exact article search - no embedding needed
            article_num = article_match.group(1)
            code_hint = article_match.group(3)

            results = await self._find_exact_article(article_num, code_hint)
            if results:
                return results[:top_k]

        # Semantic search with batched embeddings
        return await self._semantic_search_optimized(query, top_k)

    async def _find_exact_article(
        self, article_num: str, code_hint: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Find exact article with optimized query"""
        # Build filter conditions with proper typing
        conditions: List[Condition] = [
            FieldCondition(key="article", match=MatchValue(value=article_num))
        ]

        # Add code filter if hint provided
        if code_hint:
            if "kpc" in code_hint or "postępowania" in code_hint:
                conditions.append(
                    FieldCondition(key="code", match=MatchValue(value="KPC"))
                )
            else:
                conditions.append(
                    FieldCondition(key="code", match=MatchValue(value="KC"))
                )

        exact_filter = Filter(must=conditions)

        # Use scroll for exact matches (more efficient than search)
        if self._qdrant_client is None:
            raise RuntimeError("Qdrant client not initialized")
        exact_results, _ = await self._qdrant_client.scroll(
            collection_name=self._config.qdrant.collection_statutes,
            scroll_filter=exact_filter,
            limit=10,
            with_payload=True,
        )

        results = []
        for point in exact_results:
            if point.payload is not None:
                results.append(
                {
                    "article": point.payload.get("article"),
                    "text": point.payload.get("text"),
                    "code": point.payload.get("code"),
                    "citation": f"art. {point.payload.get('article')} {point.payload.get('code')}",
                    "score": 1.0,
                }
            )

        return results

    async def _semantic_search_optimized(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        """Semantic search with batched embeddings"""
        # Use batched embedding generation
        if self._embedding_batcher is None:
            raise RuntimeError("Embedding batcher not initialized")
        query_embedding = await self._embedding_batcher.get_embedding(query)

        # Search with optimized parameters
        if self._qdrant_client is None:
            raise RuntimeError("Qdrant client not initialized")
        results = await self._qdrant_client.search(
            collection_name=self._config.qdrant.collection_statutes,
            query_vector=query_embedding,
            limit=top_k,
            with_payload=True,
            score_threshold=0.7,  # Filter out low-relevance results
        )

        formatted_results = []
        for result in results:
            if result.payload is not None:
                formatted_results.append(
                {
                    "article": result.payload.get("article"),
                    "text": result.payload.get("text"),
                    "code": result.payload.get("code"),
                    "citation": f"art. {result.payload.get('article')} {result.payload.get('code')}",
                    "score": result.score,
                }
            )

        return formatted_results

    async def search_multiple_statutes(
        self, queries: List[str], top_k: int = 5
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Batch search for multiple queries concurrently.
        Useful when checking multiple legal references at once.
        """

        async def search_single(query):
            return query, await self.search_statute(query, top_k)

        # Execute searches concurrently
        tasks = [search_single(q) for q in queries]
        results = await asyncio.gather(*tasks)

        return dict(results)

    @optimize_query_with_cache(ttl=timedelta(minutes=30))
    async def summarize_passages(self, passages: List[Dict[str, Any]]) -> str:
        """Cached passage summarization"""
        # Create cache key from passage citations
        cache_key = "|".join(p.get("citation", "") for p in passages)

        return await self._summarize_passages_impl(passages)

    async def _summarize_passages_impl(self, passages: List[Dict[str, Any]]) -> str:
        """Implementation of passage summarization"""
        if not passages:
            return "Nie znaleziono odpowiednich przepisów."

        # Format passages
        formatted_passages = []
        for p in passages:
            formatted_passages.append(f"{p['citation']}:\n{p['text']}")

        passages_text = "\n\n".join(formatted_passages)

        prompt = f"""Podsumuj poniższe przepisy prawne w jasny i zwięzły sposób:

{passages_text}

Podsumowanie (max 3 akapity):"""

        response = await self._llm_manager.generate_completion(prompt)
        return response or "Nie można wygenerować podsumowania."

    async def prefetch_common_articles(self, articles: List[str]) -> None:
        """
        Prefetch commonly accessed articles into cache.
        Useful for warming cache with frequently used statutes.
        """
        tasks = []
        for article in articles:
            # Create queries for both KC and KPC
            tasks.append(self.search_statute(f"art. {article} KC", top_k=1))
            tasks.append(self.search_statute(f"art. {article} KPC", top_k=1))

        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info(f"Prefetched {len(articles)} common articles into cache")

    def get_cache_metrics(self) -> Dict[str, Any]:
        """Get cache performance metrics"""
        search_cache = getattr(self.search_statute, 'cache', None)
        summary_cache = getattr(self.summarize_passages, 'cache', None)
        
        return {
            "search_cache": search_cache.get_metrics() if search_cache else {"error": "cache not available"},
            "summary_cache": summary_cache.get_metrics() if summary_cache else {"error": "cache not available"},
        }


# Common articles to prefetch on startup
COMMON_ARTICLES = [
    "415",  # Delict liability
    "471",  # Contract performance
    "488",  # Payment deadline
    "481",  # Delay damages
    "365",  # Contract freedom
    "84",  # Legal persons
    "118",  # Prescription
    "353",  # Contract obligations
]


async def create_optimized_statute_search(config_service: ConfigService, llm_manager: LLMManager) -> OptimizedStatuteSearchService:
    """
    Factory function to create and initialize optimized service.
    """
    service = OptimizedStatuteSearchService(config_service, llm_manager)
    await service.initialize()

    # Prefetch common articles in background
    asyncio.create_task(service.prefetch_common_articles(COMMON_ARTICLES))

    return service
