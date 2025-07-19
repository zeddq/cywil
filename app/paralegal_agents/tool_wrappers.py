"""Tool wrappers for OpenAI Agent SDK integration.

This module wraps existing tool functions from the service layer into
SDK-compatible tool objects using the @tool decorator.
"""
from typing import Dict, Any, List, Optional
import json
import logging

from agents import tool  # type: ignore
from pydantic import BaseModel, Field

from ..core import inject_service
from ..services import (
    SupremeCourtService,
    StatuteSearchService,
    DocumentGenerationService,
    CaseManagementService,
)

logger = logging.getLogger(__name__)


# Pydantic models for tool parameters (for better type validation)
class SearchSNRulingsParams(BaseModel):
    """Parameters for Supreme Court rulings search."""
    query: str = Field(description="Search query in Polish")
    top_k: int = Field(default=5, description="Number of results to return")
    filters: Optional[Dict[str, Any]] = Field(default=None, description="Optional filters (date_from, date_to, section)")

class SearchSNRulingsResult(BaseModel):
    """Result for Supreme Court rulings search."""
    docket: str = Field(description="Docket number")
    date: str = Field(description="Date of the ruling")
    panel: str = Field(description="Panel of the ruling")
    excerpt: str = Field(description="Excerpt from the ruling")
    section: str = Field(description="Section of the ruling")
    score: float = Field(description="Score of the ruling")
    match_type: str = Field(description="Match type")


class SearchStatuteParams(BaseModel):
    """Parameters for statute search."""
    query: str = Field(description="Search query in Polish")
    top_k: int = Field(default=5, description="Number of results to return")
    code: Optional[str] = Field(default=None, description="Specific code to search (KC or KPC)")

class SearchStatuteResult(BaseModel):
    """Result for statute search."""
    code: str = Field(description="Code of the statute")
    title: str = Field(description="Title of the statute")
    excerpt: str = Field(description="Excerpt from the statute")

class DraftDocumentParams(BaseModel):
    """Parameters for document drafting."""
    template_name: str = Field(description="Name of document template to use")
    data: Dict[str, Any] = Field(description="Data to populate the template")
    format: str = Field(default="markdown", description="Output format (markdown or html)")


class ComputeDeadlineParams(BaseModel):
    """Parameters for deadline computation."""
    event_date: str = Field(description="Date of the event (YYYY-MM-DD)")
    deadline_type: str = Field(description="Type of deadline to compute")
    working_days: bool = Field(default=False, description="Whether to count only working days")


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

# Tool wrapper functions
@tool(
    name="search_sn_rulings",
)
async def search_sn_rulings_tool(params: SearchSNRulingsParams) -> List[SearchSNRulingsResult]:
    """
    Search Supreme Court rulings and return formatted results.

    Args:
        query: Search query in Polish
        top_k: Number of results to return
        filters: Optional filters (date_from, date_to, section)

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
        service = inject_service(SupremeCourtService)
        results = await service.search_sn_rulings(
            query=params.query,
            top_k=params.top_k,
            filters=params.filters
        )
        
        # Convert results to JSON-serializable format
        formatted_results = []
        for ruling in results:
            formatted_results.append({
                "docket": ruling.docket,
                "date": ruling.date,
                "panel": ruling.panel,
                "excerpt": ruling.paragraphs.text if ruling.paragraphs else "",
                "section": ruling.paragraphs.section if ruling.paragraphs else "",
                "score": ruling.score,
                "match_type": ruling.match_type
            })
        
        return formatted_results
    except Exception as e:
        logger.error(f"Error in search_sn_rulings_tool: {e}")
        return []


@tool(
    name="search_statute",
)
async def search_statute_tool(params: SearchStatuteParams) -> str:
    """Search civil law statutes and return relevant articles.
    
    Args:
        query: Search query in Polish
        top_k: Number of results to return
        code: Specific code to search (KC or KPC)

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
        service = inject_service(StatuteSearchService)
        results = await service.search_statute(
            query=params.query,
            top_k=params.top_k,
            code=params.code
        )
        
        return results
    except Exception as e:
        logger.error(f"Error in search_statute_tool: {e}")
        return []


@tool(
    name="draft_document",
    description="Draft legal documents using templates"
)
async def draft_document_tool(params: DraftDocumentParams) -> str:
    """Generate legal documents from templates."""
    try:
        service = inject_service(DocumentGenerationService)
        result = await service.draft_document(
            template_name=params.template_name,
            data=params.data,
            format=params.format
        )
        
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error in draft_document_tool: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool(
    name="compute_deadline",
    description="Calculate procedural deadlines according to Polish civil procedure"
)
async def compute_deadline_tool(params: ComputeDeadlineParams) -> str:
    """Compute legal deadlines based on event date and type."""
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


@tool(
    name="summarize_sn_rulings",
    description="Summarize Supreme Court rulings with focus on legal principles"
)
async def summarize_sn_rulings_tool(rulings_json: str) -> str:
    """Summarize multiple Supreme Court rulings."""
    try:
        service = inject_service(SupremeCourtService)
        
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


def get_all_tools() -> List[Any]:
    """Get all SDK-wrapped tools for the agent."""
    return [
        search_sn_rulings_tool,
        search_statute_tool,
        draft_document_tool,
        compute_deadline_tool,
        summarize_sn_rulings_tool,
    ] 
