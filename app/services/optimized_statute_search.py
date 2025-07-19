"""
Optimized version of StatuteSearchService with performance improvements.
"""
from typing import List, Dict, Any, Optional
import asyncio
from datetime import timedelta
import re

from qdrant_client.models import Filter, FieldCondition, MatchValue

from ..core import get_config, inject_service
from ..core.llm_manager import LLMManager
from ..core.logger_manager import get_logger
from ..core.performance_utils import (
    optimize_query_with_cache,
    optimize_embedding_with_cache,
    EmbeddingBatcher,
    BatchProcessor
)
from .statute_search_service import StatuteSearchService


logger = get_logger(__name__)


class OptimizedStatuteSearchService(StatuteSearchService):
    """
    Optimized version with caching, batching, and concurrent execution.
    """
    
    def __init__(self):
        super().__init__()
        self._embedding_batcher: Optional[EmbeddingBatcher] = None
        self._batch_processor = BatchProcessor(
            batch_size=5,
            batch_timeout=0.1,
            max_concurrent=3
        )
        
    async def _initialize_impl(self) -> None:
        """Initialize with optimizations"""
        await super()._initialize_impl()
        
        # Create embedding batcher
        self._embedding_batcher = EmbeddingBatcher(
            self._embedder,
            batch_size=16,
            max_wait=0.2
        )
        
        logger.info("Optimized statute search service initialized")
    
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
        article_pattern = r'art\.?\s*(\d+)\s*(§\s*\d+)?\s*(k\.?[cp]\.?|kodeks[u]?\s+(cywilnego|postępowania\s+cywilnego))?'
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
    
    async def _find_exact_article(self, article_num: str, code_hint: Optional[str]) -> List[Dict[str, Any]]:
        """Find exact article with optimized query"""
        # Build filter
        exact_filter = Filter(
            must=[FieldCondition(key="article", match=MatchValue(value=article_num))]
        )
        
        # Add code filter if hint provided
        if code_hint:
            if 'kpc' in code_hint or 'postępowania' in code_hint:
                exact_filter.must.append(
                    FieldCondition(key="code", match=MatchValue(value="KPC"))
                )
            else:
                exact_filter.must.append(
                    FieldCondition(key="code", match=MatchValue(value="KC"))
                )
        
        # Use scroll for exact matches (more efficient than search)
        exact_results, _ = await self._qdrant_client.scroll(
            collection_name=self._config.qdrant.collection_statutes,
            scroll_filter=exact_filter,
            limit=10,
            with_payload=True
        )
        
        results = []
        for point in exact_results:
            results.append({
                "article": point.payload.get("article"),
                "text": point.payload.get("text"),
                "code": point.payload.get("code"),
                "citation": f"art. {point.payload.get('article')} {point.payload.get('code')}",
                "score": 1.0
            })
        
        return results
    
    async def _semantic_search_optimized(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        """Semantic search with batched embeddings"""
        # Use batched embedding generation
        query_embedding = await self._embedding_batcher.get_embedding(query)
        
        # Search with optimized parameters
        results = await self._qdrant_client.search(
            collection_name=self._config.qdrant.collection_statutes,
            query_vector=query_embedding,
            limit=top_k,
            with_payload=True,
            score_threshold=0.7  # Filter out low-relevance results
        )
        
        formatted_results = []
        for result in results:
            formatted_results.append({
                "article": result.payload.get("article"),
                "text": result.payload.get("text"),
                "code": result.payload.get("code"),
                "citation": f"art. {result.payload.get('article')} {result.payload.get('code')}",
                "score": result.score
            })
        
        return formatted_results
    
    async def search_multiple_statutes(self, queries: List[str], top_k: int = 5) -> Dict[str, List[Dict[str, Any]]]:
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
        
        response = await self._llm.ainvoke(prompt)
        return response.content
    
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
        return {
            "search_cache": self.search_statute.cache.get_metrics(),
            "summary_cache": self.summarize_passages.cache.get_metrics()
        }


# Common articles to prefetch on startup
COMMON_ARTICLES = [
    "415",  # Delict liability
    "471",  # Contract performance
    "488",  # Payment deadline
    "481",  # Delay damages
    "365",  # Contract freedom
    "84",   # Legal persons
    "118",  # Prescription
    "353",  # Contract obligations
]


async def create_optimized_statute_search() -> OptimizedStatuteSearchService:
    """
    Factory function to create and initialize optimized service.
    """
    service = OptimizedStatuteSearchService()
    await service.initialize()
    
    # Prefetch common articles in background
    asyncio.create_task(service.prefetch_common_articles(COMMON_ARTICLES))
    
    return service
