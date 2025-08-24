"""
Statute search service for Polish civil law (KC/KPC) with vector and hybrid search.
"""

import logging
import re
from typing import Annotated, Any, Dict, List, Optional

from fastapi import Depends, Request
from openai import AsyncOpenAI
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Condition, FieldCondition, Filter, MatchValue
from sentence_transformers import SentenceTransformer

from ..core.config_service import ConfigService
from ..core.service_interface import HealthCheckResult, ServiceInterface, ServiceStatus
from ..core.tool_registry import ToolCategory, ToolParameter, tool_registry

logger = logging.getLogger(__name__)


class StatuteSearchService(ServiceInterface):
    """
    Service for searching Polish civil law statutes using hybrid search (vector + keyword).
    """

    def __init__(self, config_service: ConfigService):
        super().__init__("StatuteSearchService")
        self._config = config_service.config
        self._qdrant_client: Optional[AsyncQdrantClient] = None
        self._embedder: Optional[SentenceTransformer] = None
        self._openai_client: Optional[AsyncOpenAI] = None

    async def _initialize_impl(self) -> None:
        """Initialize Qdrant client and embedding model"""
        # Initialize Qdrant client
        self._qdrant_client = AsyncQdrantClient(
            host=self._config.qdrant.host,
            port=self._config.qdrant.port,
            timeout=self._config.qdrant.timeout,
            api_key=(
                self._config.qdrant.api_key.get_secret_value() if self._config.qdrant.api_key else None
                if hasattr(self._config.qdrant, "api_key")
                else None
            ),
            https=False,  # Explicitly disable HTTPS since Qdrant is configured without TLS
        )

        # Initialize embedding model
        logger.info("Loading SentenceTransformer model")
        self._embedder = SentenceTransformer("paraphrase-multilingual-mpnet-base-v2")

        # Initialize OpenAI client for summarization
        self._openai_client = AsyncOpenAI(api_key=self._config.openai.api_key.get_secret_value())

        # Verify collections exist
        collections = await self._qdrant_client.get_collections()
        collection_names = [c.name for c in collections.collections]

        if self._config.qdrant.collection_statutes not in collection_names:
            logger.warning(
                f"Collection '{self._config.qdrant.collection_statutes}' not found in Qdrant"
            )

    async def _shutdown_impl(self) -> None:
        """Cleanup resources"""
        if self._qdrant_client:
            await self._qdrant_client.close()

    async def _health_check_impl(self) -> HealthCheckResult:
        """Check service health"""
        try:
            # Check Qdrant connection
            if self._qdrant_client is None:
                raise RuntimeError("Qdrant client not initialized")
            collections = await self._qdrant_client.get_collections()

            # Check embedding model
            embedder = self._embedder
            if embedder is None:
                raise RuntimeError("Embedding model not initialized")
            test_embedding = embedder.encode("test")

            return HealthCheckResult(
                status=ServiceStatus.HEALTHY,
                message="Statute search service is healthy",
                details={
                    "qdrant_collections": len(collections.collections),
                    "embedding_dim": len(test_embedding),
                },
            )
        except Exception as e:
            return HealthCheckResult(
                status=ServiceStatus.UNHEALTHY, message=f"Health check failed: {str(e)}"
            )

    @tool_registry.register(
        name="search_statute",
        description="Search Polish civil law statutes (KC/KPC) using hybrid search",
        category=ToolCategory.SEARCH,
        parameters=[
            ToolParameter("query", "string", "Search query in Polish"),
            ToolParameter("top_k", "integer", "Number of results to return", False, 5),
            ToolParameter(
                "code", "string", "Specific code to search (KC or KPC)", False, None, ["KC", "KPC"]
            ),
        ],
        returns="List of statute articles with text and citations",
    )
    async def search_statute(
        self, query: str, top_k: int = 5, code: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Hybrid BM25+vector search over KC/KPC chunks.
        Returns JSON with article, text, and citation.
        """
        if not self._initialized:
            raise RuntimeError("Service not initialized")

        # Check if query is looking for a specific article
        article_pattern = r"art\.?\s*(\d+[\w§]*)\s*(KC|KPC|k\.c\.|k\.p\.c\.)?"
        article_match = re.search(article_pattern, query, re.IGNORECASE)

        formatted_results = []

        if article_match:
            # Handle exact article search
            article_num = article_match.group(1)
            requested_code = article_match.group(2)

            if requested_code:
                requested_code = (
                    requested_code.upper().replace("K.C.", "KC").replace("K.P.C.", "KPC")
                )
                code = requested_code

            # Try exact match first
            logger.info(f"Attempting exact match for article {article_num} {code or ''}")

            exact_match = await self._find_exact_article(article_num, code)
            if exact_match:
                formatted_results.append(exact_match)
                if top_k == 1:
                    return formatted_results
                top_k -= 1

        # Vector search for remaining results
        if top_k > 0:
            vector_results = await self._vector_search(
                query,
                top_k,
                code,
                exclude_article=(
                    article_match.group(1) if article_match and formatted_results else None
                ),
            )
            formatted_results.extend(vector_results)

        return formatted_results[:top_k]

    async def _find_exact_article(
        self, article_num: str, code: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Find exact article match"""
        must_conditions: List[Condition] = [
            FieldCondition(key="article", match=MatchValue(value=article_num))
        ]
        if code:
            must_conditions.append(FieldCondition(key="code", match=MatchValue(value=code)))

        exact_filter = Filter(must=must_conditions)

        client = self._qdrant_client
        if client is None:
            raise RuntimeError("Qdrant client not initialized")

        points, _ = await client.scroll(
            collection_name=self._config.qdrant.collection_statutes,
            scroll_filter=exact_filter,
            limit=1,
            with_payload=True,
        )

        if points:
            exact_match = points[0]
            payload = exact_match.payload or {}
            return {
                "article": payload.get("article"),
                "text": payload.get("text"),
                "citation": f"art. {payload.get('article')} {payload.get('code')}",
                "score": 1.0,
            }
        return None

    async def _vector_search(
        self, query: str, top_k: int, code: Optional[str], exclude_article: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Perform vector similarity search"""
        # Generate embedding
        logger.info(f"Generating embedding for query: {query[:100]}...")
        embedder = self._embedder
        if embedder is None:
            raise RuntimeError("Embedding model not initialized")
        query_embedding = embedder.encode(query).tolist()

        # Build filter
        search_filter = None
        if code:
            search_filter = Filter(must=[FieldCondition(key="code", match=MatchValue(value=code))])

        # Search
        client = self._qdrant_client
        if client is None:
            raise RuntimeError("Qdrant client not initialized")
        results = await client.search(
            collection_name=self._config.qdrant.collection_statutes,
            query_vector=query_embedding,
            query_filter=search_filter,
            limit=top_k + (1 if exclude_article else 0),  # Get extra if we need to exclude
            with_payload=True,
        )

        # Format results
        formatted_results = []
        for result in results:
            # Skip if this is the excluded article
            payload = result.payload or {}
            if exclude_article and payload.get("article") == exclude_article:
                continue

            formatted_results.append(
                {
                    "article": payload.get("article"),
                    "text": payload.get("text"),
                    "citation": f"art. {payload.get('article')} {payload.get('code')}",
                    "score": result.score,
                }
            )

        return formatted_results

    @tool_registry.register(
        name="summarize_passages",
        description="Summarize legal passages into coherent explanation",
        category=ToolCategory.ANALYSIS,
        parameters=[ToolParameter("passages", "array", "List of passages to summarize")],
        returns="Summarized explanation in Polish",
    )
    async def summarize_passages(self, passages: List[Dict[str, Any]]) -> str:
        """
        Few-shot legal abstractive summary → coherent answer paragraphs.
        """
        if not self._initialized:
            raise RuntimeError("Service not initialized")

        # Prepare passages text
        passages_text = "\n\n".join([f"{p['citation']}: {p['text']}" for p in passages])

        prompt = f"""Jako ekspert prawa cywilnego, podsumuj następujące przepisy w sposób jasny i zwięzły:

{passages_text}

Podsumowanie powinno:
1. Wyjaśnić kluczowe zasady prawne
2. Zachować precyzję terminologiczną
3. Wskazać praktyczne zastosowanie
4. Cytować konkretne artykuły

Podsumowanie:"""

        logger.info("Generating legal summary")
        openai_client = self._openai_client
        if openai_client is None:
            raise RuntimeError("OpenAI client not initialized")
        response = await openai_client.chat.completions.create(
            model=self._config.openai.summary_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,
        )
        return response.choices[0].message.content or ""

    async def get_article_by_number(self, article_num: str, code: str) -> Optional[Dict[str, Any]]:
        """Get a specific article by its number and code"""
        return await self._find_exact_article(article_num, code)

    async def search_by_topic(self, topic: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search statutes by legal topic"""
        return await self._vector_search(topic, limit, None, None)


def get_statute_search_service(request: Request) -> StatuteSearchService:
    return request.app.state.manager.inject_service(StatuteSearchService)


StatuteSearchServiceDep = Annotated[StatuteSearchService, Depends(get_statute_search_service)]
