"""
Supreme Court (Sąd Najwyższy) rulings search and analysis service.
"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import re
import logging
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue, Range
from sentence_transformers import SentenceTransformer
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate
from sqlalchemy import select
from fastapi import Request, Depends
from typing import Annotated

from ..core.service_interface import ServiceInterface, HealthCheckResult, ServiceStatus
from ..core.config_service import get_config, ConfigService
from ..core.tool_registry import tool_registry, ToolCategory, ToolParameter
from ..core.database_manager import DatabaseManager
from ..models import SNRuling, RulingParagraph

logger = logging.getLogger(__name__)


@dataclass
class RulingParagraphPayload:
    """Data structure for ruling paragraph information"""
    section: str
    para_no: int
    text: str
    entities: List[Dict[str, Any]]


@dataclass
class RulingPayload:
    """Data structure for ruling search results"""
    docket: str
    date: Optional[int]
    panel: List[str]
    paragraphs: RulingParagraphPayload
    match_type: str = "semantic"
    score: float = 0.0


class SupremeCourtService(ServiceInterface):
    """
    Service for searching and analyzing Polish Supreme Court rulings.
    """
    
    def __init__(self, db_manager: DatabaseManager, config_service: ConfigService):
        super().__init__("SupremeCourtService")
        self._config = config_service.config
        self._db_manager = db_manager
        self._qdrant_client: Optional[AsyncQdrantClient] = None
        self._embedder: Optional[SentenceTransformer] = None
        self._llm: Optional[ChatOpenAI] = None
        
    async def _initialize_impl(self) -> None:
        """Initialize Qdrant client and models"""
        print(f"self._config.qdrant.api_key.get_secret_value() {self._config.qdrant.api_key.get_secret_value()}")
        # Initialize Qdrant client
        self._qdrant_client = AsyncQdrantClient(
            host=self._config.qdrant.host,
            port=self._config.qdrant.port,
            timeout=self._config.qdrant.timeout,
            api_key=self._config.qdrant.api_key.get_secret_value() if hasattr(self._config.qdrant, 'api_key') else None,
            https=False  # Explicitly disable HTTPS since Qdrant is configured without TLS
        )
        
        # Initialize embedding model for Supreme Court rulings
        logger.info("Loading legal embedding model")
        self._embedder = SentenceTransformer('Stern5497/sbert-legal-xlm-roberta-base')
        
        # Initialize LLM for summarization
        self._llm = ChatOpenAI(
            model=self._config.openai.summary_model,
            api_key=self._config.openai.api_key.get_secret_value()
        )
        
        # Verify collection exists
        collections = await self._qdrant_client.get_collections()
        collection_names = [c.name for c in collections.collections]
        
        if self._config.qdrant.collection_rulings not in collection_names:
            logger.warning(f"Collection '{self._config.qdrant.collection_rulings}' not found in Qdrant")
    
    async def _shutdown_impl(self) -> None:
        """Cleanup resources"""
        if self._qdrant_client:
            await self._qdrant_client.close()
    
    async def _health_check_impl(self) -> HealthCheckResult:
        """Check service health"""
        try:
            # Check Qdrant connection
            collections = await self._qdrant_client.get_collections()
            
            # Check embedding model
            test_embedding = self._embedder.encode("test wyrok")
            
            return HealthCheckResult(
                status=ServiceStatus.HEALTHY,
                message="Supreme Court service is healthy",
                details={
                    "qdrant_collections": len(collections.collections),
                    "embedding_dim": len(test_embedding)
                }
            )
        except Exception as e:
            return HealthCheckResult(
                status=ServiceStatus.UNHEALTHY,
                message=f"Health check failed: {str(e)}"
            )
    
    @tool_registry.register(
        name="search_sn_rulings",
        description="Search Polish Supreme Court (Sąd Najwyższy) rulings using semantic search",
        category=ToolCategory.SEARCH,
        parameters=[
            ToolParameter("query", "string", "Search query in Polish"),
            ToolParameter("top_k", "integer", "Number of results to return", False, 5),
            ToolParameter("filters", "object", "Optional filters (date_from, date_to, section)", False)
        ],
        returns="List of relevant rulings with metadata and excerpts"
    )
    async def search_sn_rulings(self, query: str, top_k: int = 5, 
                               filters: Optional[Dict[str, Any]] = None) -> List[RulingPayload]:
        """Search Supreme Court rulings with semantic search"""
        if not self._initialized:
            raise RuntimeError("Service not initialized")
        
        # Check for exact docket number search
        docket_pattern = r'([IVX]+\s+[A-Z]+\s+\d+/\d+)'
        docket_match = re.search(docket_pattern, query)
        formatted_results: List[RulingPayload] = []
        
        if docket_match:
            # Try exact docket match first
            docket_num = docket_match.group(1)
            logger.info(f"Attempting exact match for docket number {docket_num}")
            
            exact_results = await self._find_by_docket(docket_num)
            formatted_results.extend(exact_results)
            
            if len(formatted_results) >= top_k:
                return formatted_results[:top_k]
            
            top_k -= len(formatted_results)
        
        # Semantic search for remaining results
        if top_k > 0:
            semantic_results = await self._semantic_search(query, top_k * 3, filters)
            
            # Group by ruling and format
            for result in semantic_results:
                if len(formatted_results) >= top_k:
                    break
                    
                formatted_results.append(RulingPayload(
                    docket=result.payload.get("docket"),
                    date=result.payload.get("date"),
                    panel=result.payload.get("panel", []),
                    paragraphs=RulingParagraphPayload(
                        section=result.payload.get("section"),
                        para_no=result.payload.get("para_no"),
                        text=result.payload.get("text"),
                        entities=result.payload.get("entities", [])
                    ),
                    score=result.score,
                    match_type="semantic"
                ))
        
        return formatted_results[:top_k]
    
    async def _find_by_docket(self, docket_num: str) -> List[RulingPayload]:
        """Find ruling by exact docket number"""
        exact_filter = Filter(
            must=[FieldCondition(key="docket", match=MatchValue(value=docket_num))]
        )
        
        exact_results, _ = await self._qdrant_client.scroll(
            collection_name=self._config.qdrant.collection_rulings,
            scroll_filter=exact_filter,
            limit=100,  # Get all paragraphs from this ruling
            with_payload=True
        )
        
        results = []
        for point in exact_results:
            results.append(RulingPayload(
                docket=point.payload.get("docket"),
                date=point.payload.get("date"),
                panel=point.payload.get("panel", []),
                paragraphs=RulingParagraphPayload(
                    section=point.payload.get("section"),
                    para_no=point.payload.get("para_no"),
                    text=point.payload.get("text"),
                    entities=point.payload.get("entities", [])
                ),
                score=1.0,
                match_type="exact_docket"
            ))
        
        return results
    
    async def _semantic_search(self, query: str, limit: int, 
                              filters: Optional[Dict[str, Any]]) -> List[Any]:
        """Perform semantic search on rulings"""
        # Generate embedding
        logger.info(f"Generating embedding for query: {query[:100]}...")
        query_embedding = self._embedder.encode(query).tolist()
        
        # Build filters
        search_filter = None
        must_conditions = []
        
        if filters:
            if "date_from" in filters:
                must_conditions.append(FieldCondition(
                    key="date",
                    range=Range(gte=filters["date_from"])
                ))
            if "date_to" in filters:
                must_conditions.append(FieldCondition(
                    key="date",
                    range=Range(lte=filters["date_to"])
                ))
            if "section" in filters:
                must_conditions.append(FieldCondition(
                    key="section",
                    match=MatchValue(value=filters["section"])
                ))
        
        if must_conditions:
            search_filter = Filter(must=must_conditions)
        
        # Search
        results = await self._qdrant_client.search(
            collection_name=self._config.qdrant.collection_rulings,
            query_vector=query_embedding,
            query_filter=search_filter,
            limit=limit,
            with_payload=True
        )
        
        return results
    
    async def get_sn_ruling(self, docket: str) -> Optional[SNRuling]:
        """Get complete Supreme Court ruling by docket number"""
        if not self._initialized:
            raise RuntimeError("Service not initialized")
        
        async with self._db_manager.get_session() as session:
            result = await session.execute(
                select(SNRuling).where(SNRuling.docket == docket)
            )
            return result.scalar_one_or_none()
    
    @tool_registry.register(
        name="summarize_sn_rulings",
        description="Summarize Supreme Court rulings with focus on legal principles",
        category=ToolCategory.ANALYSIS,
        parameters=[
            ToolParameter("rulings", "array", "List of rulings to summarize")
        ],
        returns="Summary focusing on legal principles and precedents"
    )
    async def summarize_sn_rulings(self, rulings: List[RulingPayload]) -> str:
        """Summarize Supreme Court rulings"""
        if not self._initialized:
            raise RuntimeError("Service not initialized")
        
        # Prepare rulings text
        rulings_text = ""
        for ruling in rulings:
            rulings_text += f"\n\nWyrok {ruling.docket}"
            if ruling.date:
                rulings_text += f" z dnia {ruling.date}"
            rulings_text += "\n"
            
            if ruling.paragraphs.text:
                rulings_text += ruling.paragraphs.text
        
        prompt = PromptTemplate(
            template="""Jako ekspert prawa cywilnego, przeanalizuj poniższe orzeczenia Sądu Najwyższego:

{rulings}

Podsumowanie powinno zawierać:
1. Kluczowe tezy prawne z każdego orzeczenia
2. Ustalone precedensy i ich znaczenie
3. Praktyczne zastosowanie w kontekście prawnym
4. Cytowanie sygnatur akt

Podsumowanie:""",
            input_variables=["rulings"]
        )
        
        logger.info("Generating Supreme Court rulings summary")
        response = await self._llm.ainvoke(prompt.format(rulings=rulings_text))
        return response.content
    
    async def get_ruling_paragraphs(self, docket: str, section: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all paragraphs from a specific ruling"""
        filter_conditions = [FieldCondition(key="docket", match=MatchValue(value=docket))]
        if section:
            filter_conditions.append(FieldCondition(key="section", match=MatchValue(value=section)))
        
        search_filter = Filter(must=filter_conditions)
        
        results, _ = await self._qdrant_client.scroll(
            collection_name=self._config.qdrant.collection_rulings,
            scroll_filter=search_filter,
            limit=1000,
            with_payload=True
        )
        
        paragraphs = []
        for result in results:
            paragraphs.append({
                "section": result.payload.get("section"),
                "para_no": result.payload.get("para_no"),
                "text": result.payload.get("text"),
                "entities": result.payload.get("entities", [])
            })
        
        # Sort by paragraph number
        paragraphs.sort(key=lambda x: x["para_no"])
        return paragraphs
    
    async def analyze_ruling_relevance(self, ruling_docket: str, context: str) -> Dict[str, Any]:
        """Analyze how relevant a ruling is to a given context"""
        ruling = await self.get_sn_ruling(ruling_docket)
        if not ruling:
            return {"error": f"Ruling {ruling_docket} not found"}
        
        prompt = f"""Przeanalizuj poniższy wyrok Sądu Najwyższego w kontekście podanej sprawy:

Sygnatura: {ruling.docket}
Data: {ruling.date}

Kontekst sprawy:
{context}

Oceń:
1. Czy wyrok ma zastosowanie do podanego kontekstu?
2. Które tezy z wyroku są istotne?
3. Jak można wykorzystać ten precedens?

Analiza:"""
        
        response = await self._llm.ainvoke(prompt)
        
        return {
            "docket": ruling_docket,
            "relevance_analysis": response.content,
            "analyzed_at": datetime.now().isoformat()
        }

def get_supreme_court_service(request: Request) -> SupremeCourtService:
    return request.app.state.manager.inject_service(SupremeCourtService)

SupremeCourtServiceDep = Annotated[SupremeCourtService, Depends(get_supreme_court_service)]
