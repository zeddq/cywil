"""Tool wrappers for OpenAI Agent SDK integration.

This module wraps existing tool functions from the service layer into
SDK-compatible tool objects using the @function_tool decorator.
"""
from typing import Dict, Any, List, Optional, Literal
import json
import logging
from datetime import datetime, timedelta

from agents import function_tool  # type: ignore
from pydantic import Field, ConfigDict
from openai import BaseModel

from ..core import ServiceLifecycleManager
from ..services import (
    SupremeCourtService,
    StatuteSearchService,
    DocumentGenerationService,
    CaseManagementService,
)

logger = logging.getLogger(__name__)

class BaseModelWithForbiddenExtra(BaseModel):
    model_config = ConfigDict(extra='forbid')  # type: ignore


class SearchSNRulingsFilters(BaseModelWithForbiddenExtra):
    date_from: Optional[str] = Field(default=None, description="Date from")
    date_to: Optional[str] = Field(default=None, description="Date to")
    section: Optional[str] = Field(default=None, description="Section")

# Pydantic models for tool parameters (for better type validation)
class SearchSNRulingsParams(BaseModelWithForbiddenExtra):
    """Parameters for Supreme Court rulings search."""
    query: str = Field(description="Search query in Polish")
    top_k: int = Field(default=5, description="Number of results to return")
    filters: SearchSNRulingsFilters = Field(default=SearchSNRulingsFilters(), description="Optional filters (date_from, date_to, section)")

class SearchSNRulingsResult(BaseModelWithForbiddenExtra):
    """Result for Supreme Court rulings search."""
    docket: str = Field(description="Docket number")
    date: str = Field(description="Date of the ruling")
    panel: str = Field(description="Panel of the ruling")
    excerpt: str = Field(description="Excerpt from the ruling")
    section: str = Field(description="Section of the ruling")
    score: float = Field(description="Score of the ruling")
    match_type: str = Field(description="Match type")


class SearchStatuteParams(BaseModelWithForbiddenExtra):
    """Parameters for statute search."""
    query: str = Field(description="Search query in Polish")
    top_k: int = Field(default=5, description="Number of results to return")
    code: Optional[str] = Field(default=None, description="Specific code to search (KC or KPC)")

class SearchStatuteResult(BaseModelWithForbiddenExtra):
    """Result for statute search."""
    code: str = Field(description="Code of the statute")
    title: str = Field(description="Title of the statute")
    excerpt: str = Field(description="Excerpt from the statute")

class DraftDocumentData(BaseModelWithForbiddenExtra):
    """Data for document drafting."""
    facts: List[str] = Field(description="Facts needed for the document")
    goals: List[str] = Field(description="Goals of the document")

class DraftDocumentParams(BaseModelWithForbiddenExtra):
    """Parameters for document drafting."""
    template_name: str = Field(description="Name of document template to use")
    data: DraftDocumentData = Field(description="Data to populate the template")
    format: str = Field(default="markdown", description="Output format (markdown or html)")


class ComputeDeadlineParams(BaseModelWithForbiddenExtra):
    """Parameters for deadline computation."""
    event_date: str = Field(description="Date of the event (YYYY-MM-DD)")
    deadline_type: str = Field(description="Type of deadline to compute")
    working_days: bool = Field(default=False, description="Whether to count only working days")

class SummarizePassagesPassage(BaseModelWithForbiddenExtra):
    """Passage for summarization."""
    article: str = Field(description="Article number")
    text: str = Field(description="Text of the passage")
    citation: str = Field(description="Citation of the passage")    

class SummarizePassagesParams(BaseModelWithForbiddenExtra):
    """Parameters for passage summarization."""
    passages: List[SummarizePassagesPassage] = Field(description="List of passages with article, text, citation")


class ValidateAgainstStatuteParams(BaseModelWithForbiddenExtra):
    """Parameters for document validation against statutes."""
    draft: str = Field(description="Draft document text to validate")
    citations: List[str] = Field(description="Legal citations referenced in the document")


class DescribeCaseParams(BaseModelWithForbiddenExtra):
    """Parameters for case description."""
    case_id: Optional[str] = Field(default=None, description="Specific case ID to describe")


class UpdateCaseParams(BaseModelWithForbiddenExtra):
    """Parameters for case update."""
    key: Literal['reference_number', 'id'] = Field(description="Key type to use for case lookup")
    id: Optional[str] = Field(default=None, description="Case ID")
    reference_number: Optional[str] = Field(default=None, description="Case reference number")
    title: Optional[str] = Field(default=None, description="Case title")
    description: Optional[str] = Field(default=None, description="Case description")
    status: Optional[str] = Field(default=None, description="Case status")
    case_type: Optional[str] = Field(default=None, description="Case type")
    client_name: Optional[str] = Field(default=None, description="Client name")
    client_contact: Optional[str] = Field(default=None, description="Client contact")
    opposing_party: Optional[str] = Field(default=None, description="Opposing party")
    opposing_party_contact: Optional[str] = Field(default=None, description="Opposing party contact")
    court_name: Optional[str] = Field(default=None, description="Court name")
    court_case_number: Optional[str] = Field(default=None, description="Court case number")
    judge_name: Optional[str] = Field(default=None, description="Judge name")
    amount_in_dispute: Optional[str] = Field(default=None, description="Amount in dispute")
    currency: Optional[str] = Field(default=None, description="Currency")


class ScheduleReminderParams(BaseModelWithForbiddenExtra):
    """Parameters for scheduling reminders."""
    case_id: str = Field(description="Case ID to associate reminder with")
    reminder_date: str = Field(description="Date for the reminder (YYYY-MM-DD)")
    note: str = Field(description="Note/description for the reminder")


class GetSNRulingParams(BaseModelWithForbiddenExtra):
    """Parameters for getting a specific Supreme Court ruling."""
    docket: str = Field(description="Docket number of the ruling")


class AnalyzeContractParams(BaseModelWithForbiddenExtra):
    """Parameters for contract analysis."""
    text: str = Field(description="Contract text to analyze")


defs= [
    {
        "type": "function",
        "function": {
            "name": "search_statute",
            "description": "Search Polish civil law statutes (KC/KPC) using hybrid search",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query in Polish"},
                    "top_k": {"type": "integer", "description": "Number of results to return", "default": 5},
                    "code": {"type": "string", "description": "Specific code to search (KC or KPC)", "enum": ["KC", "KPC"]}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function", 
        "function": {
            "name": "draft_document",
            "description": "Draft legal documents like pozew, wezwanie do zapłaty",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_type": {"type": "string", "description": "Type of document", "enum": ["pozew_upominawczy", "wezwanie_do_zaplaty"]},
                    "facts": {"type": "object", "description": "Facts needed for the document"},
                    "goals": {"type": "array", "items": {"type": "string"}, "description": "Goals of the document"}
                },
                "required": ["doc_type", "facts", "goals"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compute_deadline",
            "description": "Calculate legal deadlines based on Polish procedural law",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_type": {"type": "string", "description": "Type of legal event", "enum": ["payment", "appeal", "complaint", "response_to_claim", "cassation"]},
                    "event_date": {"type": "string", "description": "Date of the event in ISO format"}
                },
                "required": ["event_type", "event_date"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "validate_document",
            "description": "Validate legal document against statutes",
            "parameters": {
                "type": "object",
                "properties": {
                    "draft": {"type": "string", "description": "Draft document text"},
                    "citations": {"type": "array", "items": {"type": "string"}, "description": "Legal citations to validate"}
                },
                "required": ["draft", "citations"]
            }
        }
    }
]

logger.info(f"SearchSNRulingsParams: {SearchSNRulingsParams.model_json_schema()}")

# Tool wrapper functions
@function_tool(
    name_override="search_sn_rulings",
    
)
async def search_sn_rulings_tool(params: SearchSNRulingsParams) -> str:
    """
    Search Supreme Court rulings and return formatted results.

    Args:
        params: Query and filters for the search

    Returns:
        list of rulings, each with docket, date, panel, excerpt, section, score, and match_type
        Example:
        [
            {
                "docket": "1234567890",
                "date": "2021-01-01",
                "panel": "1234567890",
                "excerpt": "Excerpt from the ruling", 
                "section": "Section of the ruling",
                "score": 0.95,
                "match_type": "semantic"
            }
        ]
    """
    try:
        service = ServiceLifecycleManager.inject_service(SupremeCourtService)
        results = await service.search_sn_rulings(
            query=params.query,
            top_k=params.top_k,
            filters=params.filters
        )
        
        # Convert results to JSON-serializable format
        formatted_results: List[SearchSNRulingsResult] = []
        for ruling in results:
            formatted_results.append(SearchSNRulingsResult(
                docket=ruling.docket,
                date=ruling.date,
                panel=ruling.panel,
                excerpt=ruling.paragraphs.text if ruling.paragraphs else "",
                section=ruling.paragraphs.section if ruling.paragraphs else "",
                score=ruling.score,
                match_type=ruling.match_type
                ))
        
        return formatted_results
    except Exception as e:
        logger.error(f"Error in search_sn_rulings_tool: {e}")
        return []


@function_tool(
    name_override="search_statute",
)
async def search_statute_tool(params: SearchStatuteParams) -> str:
    """Search civil law statutes and return relevant articles.
    
    Args:
        params: Query and filters for the search

    Returns:
        JSON list of statutes, each with code, title, and excerpt
        Example:
        ```[
            {
                "code": "KC",
                "title": "Title of the statute", 
                "excerpt": "Excerpt from the statute"
            },
            ...
        ]
        ```
    """
    try:
        service = ServiceLifecycleManager.inject_service(StatuteSearchService)
        results = await service.search_statute(
            query=params.query,
            top_k=params.top_k,
            code=params.code
        )
        
        return results
    except Exception as e:
        logger.error(f"Error in search_statute_tool: {e}")
        return []


@function_tool(
    name_override="draft_document",
)
async def draft_document_tool(params: DraftDocumentParams) -> str:
    """
    Generate legal documents from templates.
    
    Args:
        params: Template name, data, and format for the document

    Returns:
        JSON with document details
    """
    try:
        service = ServiceLifecycleManager.inject_service(DocumentGenerationService)
        result = await service.draft_document(
            template_name=params.template_name,
            data=params.data,
            format=params.format
        )
        
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error in draft_document_tool: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@function_tool(
    name_override="compute_deadline",
)
async def compute_deadline_tool(params: ComputeDeadlineParams) -> str:
    """
    Compute legal deadlines based on event date and type.
    
    Args:
        params: Event date, deadline type, and working days

    Returns:
        JSON with deadline details
    """
    try:
        # This is a simplified implementation - in reality this would call
        # a deadline calculation service
        from datetime import datetime, timedelta
        
        event_dt = datetime.strptime(params.event_date, "%Y-%m-%d")
        
        # Example deadline calculations
        deadline_days = {
            "apelacja": 14,  # Appeal deadline
            "zażalenie": 7,  # Complaint deadline
            "sprzeciw": 14,  # Objection deadline
            "odpowiedź_na_pozew": 14,  # Response to lawsuit
        }
        
        days = deadline_days.get(params.deadline_type, 30)
        
        if params.working_days:
            # Simplified working days calculation
            deadline = event_dt
            days_added = 0
            while days_added < days:
                deadline += timedelta(days=1)
                if deadline.weekday() < 5:  # Monday-Friday
                    days_added += 1
        else:
            deadline = event_dt + timedelta(days=days)
        
        result = {
            "event_date": params.event_date,
            "deadline_type": params.deadline_type,
            "deadline_date": deadline.strftime("%Y-%m-%d"),
            "days": days,
            "working_days": params.working_days
        }
        
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error in compute_deadline_tool: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@function_tool(
    name_override="summarize_sn_rulings",
)
async def summarize_sn_rulings_tool(rulings_json: str) -> str:
    """
    Summarize multiple Supreme Court rulings.
    
    Args:
        rulings_json: JSON list of rulings to summarize

    Returns:
        Summarized text explaining key legal principles
    """
    try:
        service = ServiceLifecycleManager.inject_service(SupremeCourtService)
        
        # Parse the rulings from JSON
        rulings_data = json.loads(rulings_json)
        
        # Convert back to RulingPayload objects for the service
        from ..services.supreme_court_service import RulingPayload, RulingParagraphPayload
        
        rulings = []
        for data in rulings_data:
            rulings.append(RulingPayload(
                docket=data["docket"],
                date=data.get("date"),
                panel=data.get("panel", []),
                paragraphs=RulingParagraphPayload(
                    section=data.get("section", ""),
                    para_no=0,
                    text=data.get("excerpt", ""),
                    entities=[]
                ),
                score=data.get("score", 0.0),
                match_type=data.get("match_type", "semantic")
            ))
        
        summary = await service.summarize_sn_rulings(rulings)
        return summary
    except Exception as e:
        logger.error(f"Error in summarize_sn_rulings_tool: {e}")
        return f"Error summarizing rulings: {str(e)}"


@function_tool(
    name_override="summarize_passages",
)
async def summarize_passages_tool(params: SummarizePassagesParams) -> str:
    """
    Few-shot legal abstractive summary → coherent answer paragraphs.
    
    Args:
        params: List of passages with article, text, and citation
        
    Returns:
        Summarized text explaining key legal principles
    """
    try:
        service = ServiceLifecycleManager.inject_service(StatuteSearchService)
        summary = await service.summarize_passages(params.passages)
        return summary
    except Exception as e:
        logger.error(f"Error in summarize_passages_tool: {e}")
        return f"Error summarizing passages: {str(e)}"


@function_tool(
    name_override="validate_against_statute",
)
async def validate_against_statute_tool(params: ValidateAgainstStatuteParams) -> str:
    """
    Validate draft document against cited statutes.
    
    Args:
        params: Draft document text and list of legal citations to validate
        
    Returns:
        JSON validation result with is_valid, issues, and suggestions
    """
    try:
        service = ServiceLifecycleManager.inject_service(DocumentGenerationService)
        result = await service.validate_against_statute(
            draft=params.draft,
            citations=params.citations
        )
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error in validate_against_statute_tool: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@function_tool(
    name_override="describe_case",
)
async def describe_case_tool(params: DescribeCaseParams) -> str:
    """
    Describe case details.
    
    Args:
        params: Optional case ID to describe specific case
        
    Returns:
        JSON with case details or list of all cases
    """
    try:
        service = ServiceLifecycleManager.inject_service(CaseManagementService)
        result = await service.describe_case(case_id=params.case_id)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error in describe_case_tool: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@function_tool(
    name_override="update_case",
)
async def update_case_tool(params: UpdateCaseParams) -> str:
    """
    Update case details.
    
    Args:
        params: Various case fields to update
        
    Returns:
        JSON with success status
    """
    try:
        service = ServiceLifecycleManager.inject_service(CaseManagementService)
        result = await service.update_case(
            key=params.key,
            id=params.id,
            reference_number=params.reference_number,
            title=params.title,
            description=params.description,
            status=params.status,
            case_type=params.case_type,
            client_name=params.client_name,
            client_contact=params.client_contact,
            opposing_party=params.opposing_party,
            opposing_party_contact=params.opposing_party_contact,
            court_name=params.court_name,
            court_case_number=params.court_case_number,
            judge_name=params.judge_name,
            amount_in_dispute=params.amount_in_dispute,
            currency=params.currency
        )
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error in update_case_tool: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)

# @logging_middleware("schedule_reminder")
@function_tool(
    name_override="schedule_reminder",
)
async def schedule_reminder_tool(params: ScheduleReminderParams) -> str:
    """
    Schedule case reminder.
    
    Args:
        params: Case ID, reminder date, and reminder note
        
    Returns:
        JSON with reminder details
    """
    try:
        service = ServiceLifecycleManager.inject_service(CaseManagementService)
        result = await service.schedule_reminder(
            case_id=params.case_id,
            reminder_date=params.reminder_date,
            note=params.note
        )
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error in schedule_reminder_tool: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@function_tool(
    name_override="get_sn_ruling",
)
async def get_sn_ruling_tool(params: GetSNRulingParams) -> str:
    """
    Get Supreme Court ruling details.
    
    Args:
        params: Docket number
        
    Returns:
        JSON with ruling details
    """
    try:
        service = ServiceLifecycleManager.inject_service(SupremeCourtService)
        result = await service.get_sn_ruling(docket=params.docket)
        if result:
            # Convert to JSON-serializable format
            ruling_dict = {
                "docket": result.docket,
                "date": result.date.isoformat() if result.date else None,
                "panel": result.panel,
                "paragraphs": [
                    {
                        "section": p.section,
                        "para_no": p.para_no,
                        "text": p.text,
                        "entities": p.entities
                    }
                    for p in result.paragraphs
                ] if result.paragraphs else []
            }
            return json.dumps(ruling_dict, ensure_ascii=False, indent=2)
        else:
            return json.dumps({"error": f"Ruling {params.docket} not found"}, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error in get_sn_ruling_tool: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@function_tool(
    name_override="analyze_contract",
)
async def analyze_contract_tool(params: AnalyzeContractParams) -> str:
    """
    Analyze contract text.
    
    Args:
        params: Contract text to analyze
        
    Returns:
        JSON with key terms, potential issues, and recommendations
    """
    try:
        # Since there's no ContractAnalysisService, we'll use the logic from tools.py
        import re
        
        key_terms = []
        issues = []
        
        # Check for essential contract elements
        if "strony" not in params.text.lower() and "strona" not in params.text.lower():
            issues.append("Brak wyraźnego określenia stron umowy")
        
        if "przedmiot" not in params.text.lower():
            issues.append("Brak określenia przedmiotu umowy")
        
        if "termin" not in params.text.lower():
            issues.append("Brak określenia terminów wykonania")
        
        # Extract key monetary values
        money_pattern = r'(\d+(?:\s*\d+)*(?:,\d+)?)\s*(?:zł|złotych|PLN)'
        amounts = re.findall(money_pattern, params.text)
        if amounts:
            key_terms.extend([f"Kwota: {amount}" for amount in amounts])
        
        result = {
            "key_terms": key_terms,
            "potential_issues": issues,
            "recommendations": [
                "Sprawdź zgodność z art. 353¹ KC (swoboda umów)",
                "Zweryfikuj kompletność essentialia negotii"
            ] if issues else []
        }
        
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error in analyze_contract_tool: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def get_all_tools() -> List[Any]:
    """Get all SDK-wrapped tools for the agent."""
    return [
        search_sn_rulings_tool,
        search_statute_tool,
        draft_document_tool,
        compute_deadline_tool,
        summarize_sn_rulings_tool,
        summarize_passages_tool,
        validate_against_statute_tool,
        describe_case_tool,
        update_case_tool,
        schedule_reminder_tool,
        get_sn_ruling_tool,
        analyze_contract_tool,
    ] 
