"""
Document generation service for creating legal documents from templates.
"""
from typing import List, Dict, Any, Optional, Annotated
from datetime import datetime
import logging
from langchain_openai import ChatOpenAI
from fastapi import Request, Depends

from ..core.service_interface import ServiceInterface, HealthCheckResult, ServiceStatus
from ..core.config_service import get_config
from ..core.tool_registry import tool_registry, ToolCategory, ToolParameter
from ..core.database_manager import DatabaseManagerDep
from ..models import FormTemplate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from .statute_search_service import StatuteSearchServiceDep
from .supreme_court_service import SupremeCourtServiceDep

logger = logging.getLogger(__name__)


class DocumentGenerationService(ServiceInterface):
    """
    Service for generating legal documents using templates and AI assistance.
    """
    
    def __init__(self, db_manager: DatabaseManagerDep, statute_search_service: StatuteSearchServiceDep, sn_rulings_service: SupremeCourtServiceDep):
        super().__init__("DocumentGenerationService")
        self._config = get_config()
        self._db_manager = db_manager
        self._statute_search = statute_search_service
        self._sn_rulings = sn_rulings_service
        self._llm: Optional[ChatOpenAI] = None
    
    async def _initialize_impl(self) -> None:
        """Initialize LLM client"""
        self._llm = ChatOpenAI(
            model=self._config.openai.llm_model,
            api_key=self._config.openai.api_key.get_secret_value()
        )
    
    async def _shutdown_impl(self) -> None:
        """Cleanup resources"""
        pass
    
    async def _health_check_impl(self) -> HealthCheckResult:
        """Check service health"""
        try:
            # Check template access
            async with self._db_manager.get_session() as session:
                result = await session.execute(
                    select(FormTemplate).limit(1)
                )
                _ = result.scalar()
            
            return HealthCheckResult(
                status=ServiceStatus.HEALTHY,
                message="Document generation service is healthy"
            )
        except Exception as e:
            return HealthCheckResult(
                status=ServiceStatus.UNHEALTHY,
                message=f"Health check failed: {str(e)}"
            )
    
    @tool_registry.register(
        name="list_available_templates",
        description="List all available document templates",
        category=ToolCategory.DOCUMENT,
        parameters=[],
        returns="List of available templates with metadata"
    )
    async def list_available_templates(self) -> List[Dict[str, Any]]:
        """List all available templates"""
        if not self._initialized:
            raise RuntimeError("Service not initialized")
        
        async with self._db_manager.get_session() as session:
            result = await session.execute(select(FormTemplate))
            templates = result.scalars().all()
            
            return [
                {
                    'id': t.id,
                    'name': t.name,
                    'category': t.category,
                    'summary': t.summary,
                    'variables': t.variables,
                    'usage_count': t.usage_count,
                    'last_used': t.last_used.isoformat() if t.last_used else None
                }
                for t in templates
            ]
    
    @tool_registry.register(
        name="find_template",
        description="Find a specific template by type",
        category=ToolCategory.DOCUMENT,
        parameters=[
            ToolParameter("template_type", "string", "Type of template to find")
        ],
        returns="Template details or None if not found"
    )
    async def find_template(self, template_type: str) -> Optional[Dict[str, Any]]:
        """Find template by type"""
        if not self._initialized:
            raise RuntimeError("Service not initialized")
        
        async with self._db_manager.get_session() as session:
            result = await session.execute(
                select(FormTemplate).where(FormTemplate.name == template_type)
            )
            template = result.scalar_one_or_none()
            
            if template:
                return {
                    'id': template.id,
                    'name': template.name,
                    'category': template.category,
                    'content': template.content,
                    'variables': template.variables,
                    'summary': template.summary
                }
            return None
    
    @tool_registry.register(
        name="draft_document",
        description="Draft legal documents using templates from database",
        category=ToolCategory.DOCUMENT,
        parameters=[
            ToolParameter("doc_type", "string", "Type of document - use list_available_templates first"),
            ToolParameter("facts", "object", "Facts needed for the document"),
            ToolParameter("goals", "array", "Goals of the document")
        ],
        returns="Generated document with content and metadata"
    )
    async def draft_document(self, doc_type: str, facts: Dict[str, Any], goals: List[str]) -> Dict[str, Any]:
        """Generate legal documents based on type, facts, and goals"""
        if not self._initialized:
            raise RuntimeError("Service not initialized")
        
        # Find template
        template_data = await self.find_template(doc_type)
        if not template_data:
            logger.error(f"No template found for doc_type: {doc_type}")
            return {"error": f"No template found for document type: {doc_type}"}
        
        logger.info(f"Using template for {doc_type}")
        
        # Update usage statistics
        await self._update_template_usage(template_data['id'])
        
        # Get relevant statutes
        statute_query = f"{doc_type} wymogi formalne przepisy"
        relevant_statutes = await self._statute_search.search_statute(statute_query, top_k=3)
        
        # Fill template with facts
        filled_template = self._fill_template(template_data['content'], facts)
        
        # Get relevant Supreme Court rulings
        rulings = await self._sn_rulings.search_sn_rulings(filled_template, top_k=3)
        ruling_details = {}
        for ruling in rulings:
            if ruling.docket not in ruling_details:
                full_ruling = await self._sn_rulings.get_sn_ruling(ruling.docket)
                if full_ruling:
                    ruling_details[ruling.docket] = full_ruling
        
        # Generate enhanced document with AI
        final_document = await self._enhance_document_with_ai(
            filled_template, ruling_details, doc_type
        )
        
        return {
            "document_type": doc_type,
            "content": final_document,
            "citations": [s["citation"] for s in relevant_statutes],
            "template_variables": template_data['variables'],
            "metadata": {
                "created_at": datetime.now().isoformat(),
                "facts": facts,
                "goals": goals,
                "template_source": "database",
                "rulings_used": list(ruling_details.keys())
            }
        }
    
    def _fill_template(self, template_content: str, facts: Dict[str, Any]) -> str:
        """Fill template placeholders with facts"""
        filled = template_content
        for key, value in facts.items():
            filled = filled.replace(f"[[{key}]]", str(value))
        return filled
    
    async def _enhance_document_with_ai(self, template: str, rulings: Dict[str, Any], doc_type: str) -> str:
        """Enhance document with AI using Supreme Court rulings"""
        rulings_text = self._format_rulings_for_prompt(rulings)
        
        prompt = f"""
Jako ekspert prawa cywilnego pomagający w tworzeniu dokumentów profesjonalnym prawnikom uzupełnij poniższe pismo przy pomocy wyroków Sądu Najwyższego.
Wyroki Sądu Najwyższego zostały wybrane na podstawie zawartości dokumentu. Użyj tylko tych wyroków, które są istotne dla dokumentu. Wyroki występują w kolejności od najbardziej istotnych do najmniej istotnych.

Wymagania:
1. Uzupełnienie powinno być integralną częścią dokumentu.
2. Uzupełnienie powinno być dokładne i zawierać wszystkie istotne informacje dla danego dokumentu.
3. Uzupełnienie powinno być oparte na wyrokach Sądu Najwyzszego.
4. Zwrócony tekst powinien być finalną wersją dokumentu.
5. Uzupełnienie powinno być zgodne z prawem.
6. Pamiętaj o zachowaniu oryginalnej struktury dokumentu.
7. Postaraj się naprawić wszystkie błedy w dokumencie (np. błędy w cytowaniu przepisów, błędy w strukturze dokumentu, błędy w ortografii i gramatyce).

Wyroki Sądu Najwyzszego:
{rulings_text}

Dokument:
{template}
"""
        
        logger.info(f"Enhancing {doc_type} document with AI")
        response = await self._llm.ainvoke(prompt)
        return response.content
    
    def _format_rulings_for_prompt(self, rulings: Dict[str, Any]) -> str:
        """Format Supreme Court rulings for prompt"""
        formatted = []
        for docket, ruling in rulings.items():
            formatted.append(f"Wyrok {docket}")
            # Add ruling details here based on the actual structure
        return "\n\n".join(formatted)
    
    async def _update_template_usage(self, template_id: str):
        """Update template usage statistics"""
        async with self._db_manager.get_session() as session:
            result = await session.execute(
                select(FormTemplate).where(FormTemplate.id == template_id)
            )
            template = result.scalar_one_or_none()
            
            if template:
                template.usage_count = (template.usage_count or 0) + 1
                template.last_used = datetime.now()
                await session.commit()
    
    @tool_registry.register(
        name="analyze_contract",
        description="Analyze a legal contract to extract key information, summarize clauses, or identify potential issues",
        category=ToolCategory.ANALYSIS,
        parameters=[
            ToolParameter("contract_content", "string", "The full text content of the contract to analyze", True),
            ToolParameter("analysis_type", "string", "Type of analysis requested ('summary', 'key_clauses', 'risk_assessment')", False, "summary", enum=["summary", "key_clauses", "risk_assessment"]),
        ],
        returns="Detailed analysis of the contract based on the requested type"
    )
    async def analyze_contract(self, contract_content: str, analysis_type: str = "summary") -> Dict[str, Any]:
        if not self._initialized:
            raise RuntimeError("Service not initialized")
        
        logger.info(f"Analyzing contract with type: {analysis_type}")
        
        prompt_template = """
        Jako doświadczony prawnik specjalizujący się w analizie umów, przeanalizuj poniższą treść umowy.
        
        Treść umowy:
        ---
        {contract_content}
        ---
        
        Rodzaj analizy: {analysis_type}
        
        W zależności od rodzaju analizy:
        - Jeśli 'summary': Podsumuj kluczowe postanowienia umowy, jej cel oraz główne zobowiązania stron.
        - Jeśli 'key_clauses': Wypisz najważniejsze klauzule umowy (np. dotyczące płatności, odpowiedzialności, rozwiązania umowy) i krótko opisz ich znaczenie.
        - Jeśli 'risk_assessment': Zidentyfikuj potencjalne ryzyka prawne lub niejasności w umowie i zasugeruj, jak można je zminimalizować.
        
        Zwróć wynik analizy w języku polskim.
        """
        
        prompt = prompt_template.format(contract_content=contract_content, analysis_type=analysis_type)
        
        try:
            response = await self._llm.ainvoke(prompt)
            return {
                "status": "success",
                "analysis_type": analysis_type,
                "contract_analysis": response.content,
                "analyzed_at": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error during contract analysis: {e}", exc_info=True)
            return {
                "status": "error",
                "message": f"Failed to analyze contract: {str(e)}",
                "analysis_type": analysis_type
            }
    
    @tool_registry.register(
        name="validate_against_statute",
        description="Validate legal document against statutes",
        category=ToolCategory.DOCUMENT,
        parameters=[
            ToolParameter("draft", "string", "Draft document text"),
            ToolParameter("citations", "array", "Legal citations to validate")
        ],
        returns="Validation results with issues and suggestions"
    )
    async def validate_against_statute(self, draft: str, citations: List[str]) -> Dict[str, Any]:
        """Validate draft document against cited statutes"""
        if not self._initialized:
            raise RuntimeError("Service not initialized")
        
        validation_results = {
            "is_valid": True,
            "issues": [],
            "suggestions": []
        }
        
        # Extract article references
        import re
        article_pattern = r'art\.\s*(\d+[\w§]*)\s*(KC|KPC|k\.c\.|k\.p\.c\.)'
        found_citations = re.findall(article_pattern, draft, re.IGNORECASE)
        parsed_citations = re.findall(article_pattern, "\n".join(citations), re.IGNORECASE)
        
        # Verify each citation
        for article, code in found_citations + parsed_citations:
            search_results = await self._statute_search.search_statute(f"art. {article} {code}", top_k=1, code=code)
            
            if not search_results:
                validation_results["is_valid"] = False
                validation_results["issues"].append(
                    f"Nie znaleziono art. {article} {code} - możliwy błąd w cytowaniu"
                )
            else:
                # Validate context
                article_text = search_results[0]["text"]
                is_valid = await self._validate_citation_context(draft, search_results[0], article_text)
                
                if not is_valid:
                    validation_results["is_valid"] = False
                    validation_results["issues"].append(
                        f"Nieprawidłowe powołanie się na {search_results[0]['citation']}"
                    )
        
        return validation_results
    
    async def _validate_citation_context(self, draft: str, citation_info: Dict[str, Any], article_text: str) -> bool:
        """Validate if citation is used correctly in context"""
        validation_prompt = f"""Sprawdź czy poniższy fragment dokumentu prawidłowo powołuje się na przepis:

Fragment dokumentu: {draft[:800]}...

Cytowany przepis - {citation_info['citation']}: {article_text}

Czy cytat jest prawidłowy? Odpowiedz TAK lub NIE i podaj krótkie uzasadnienie."""
        
        logger.info("Validating citation context")
        response = await self._llm.ainvoke(validation_prompt)
        return "TAK" in response.content

def get_document_generation_service(request: Request, db_manager: DatabaseManagerDep, statute_search_service: StatuteSearchServiceDep, sn_rulings_service: SupremeCourtServiceDep) -> DocumentGenerationService:
    return request.app.state.manager.inject_service(DocumentGenerationService)

DocumentGenerationServiceDep = Annotated[DocumentGenerationService, Depends(get_document_generation_service)]
