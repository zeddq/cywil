from typing import List, Dict, Any, Optional
import asyncio
from openai import AsyncOpenAI
from openai.types.responses import ResponseFunctionToolCall
import json
from datetime import datetime
import logging
from .tools import (
    search_statute,
    summarize_passages, 
    draft_document,
    validate_against_statute,
    compute_deadline,
    schedule_reminder,
    init_vector_db,
    list_available_templates,
    find_template,
    describe_case,
    update_case
)
from .config import settings
from .database import get_db, AsyncSessionLocal
from .models import Case, Document, Deadline, Note
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

"""
───────────────────────────────────────────────────────────────────────────────
FIX NOTES
─────────
* Upgraded to **Responses API** semantics.
  * Replaced `response.choices[0].message` access with `response.output` / `response.output_text`.
  * Added `previous_response_id` chaining instead of resending full history after the 1st turn.
  * Updated function‑calling flow:
      • Model returns `type == "function_call"` items ➔ we execute the mapped Python function.
      • We answer with a `type == "function_call_output"` item.
  * `handle_tool_calls` now emits `function_call_output` items, matching the new spec.
* Conversation state now only keeps `last_response_id`; full transcripts are optional.
* All OpenAI calls now pass `input=` rather than the legacy `messages=` param.
───────────────────────────────────────────────────────────────────────────────
"""

# Initialize logging
logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = AsyncOpenAI(api_key=settings.openai_api_key)

# Tool definitions for OpenAI Function Calling
TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "type": "function",
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
    },
    {
        "type": "function",
        "name": "draft_document",
        "description": "Draft legal documents using templates from database",
        "parameters": {
            "type": "object",
            "properties": {
                "doc_type": {"type": "string", "description": "Type of document - use list_available_templates first to see options"},
                "facts": {"type": "object", "description": "Facts needed for the document"},
                "goals": {"type": "array", "items": {"type": "string"}, "description": "Goals of the document"}
            },
            "required": ["doc_type", "facts", "goals"]
        }
    },
    {
        "type": "function",
        "name": "list_available_templates",
        "description": "List all available document templates",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "type": "function", 
        "name": "find_template",
        "description": "Find a specific template by type",
        "parameters": {
            "type": "object",
            "properties": {
                "template_type": {"type": "string", "description": "Type of template to find"}
            },
            "required": ["template_type"]
        }
    },
    {
        "type": "function",
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
    },
    {
        "type": "function",
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
    },
    {
        "type": "function",
        "name": "describe_case",
        "description": "Describe a case based on its ID (or all cases if no ID is provided)",
        "parameters": {
            "type": "object",
            "properties": {
                "case_id": {"type": "string", "description": "ID of the case to describe (leave empty to describe all cases)"},     
            },
        }
    },
    {
        "type": "function",
        "name": "update_case",
        "description": "Update a case based on its ID and description", # TODO: add more fields to update           
        "parameters": {
            "type": "object",
            "properties": {
                "case_id": {"type": "string", "description": "ID of the case to update"},
                "description": {"type": "string", "description": "New description of the case"},
            },
            "required": ["case_id", "description"]
        }
    }
]

def flatten_tool_outputs(tool_outputs: List[Dict[str, Any]]) -> str:
    return "\n".join([json.dumps(output) for output in tool_outputs])

class ParalegalAgent:
    """Chat agent powered by the OpenAI *Responses* endpoint."""

    def __init__(self):
        # Map function names → callables we execute locally
        self.tools_map = {
            "search_statute": search_statute,
            "draft_document": draft_document,
            "compute_deadline": compute_deadline,
            "describe_case": describe_case,
            "update_case": update_case,
            "validate_document": validate_against_statute,
            "list_available_templates": list_available_templates,
            "find_template": find_template,
        }
        init_vector_db(settings.qdrant_host, settings.qdrant_port)
        # last_response_id per conversation
        self.conversations: Dict[str, str] = {}

    # ────────────────────────────────────────────────────────────────────
    # PROMPTS
    # ────────────────────────────────────────────────────────────────────
    def get_system_prompt(self) -> List[Dict[str, Any]]:
        return {
                "role": "developer",
                "content": """
# ROLE                
You are an expert Polish legal assistant specializing in civil law (Kodeks cywilny) and civil procedure (Kodeks postępowania cywilnego).


# RESPONSIBILITIES
Your responsibilities (you can use tools to help you):
- Answer legal questions with precise citations to relevant articles
- Draft legal documents following Polish legal standards
- Provide information about available templates and their usage
- Provide information about user's cases
- Calculate procedural deadlines accurately
- Validate documents against current statutes

## ALWAYS
- Cite specific articles (e.g., \"art. 415 KC\")
- Use proper Polish legal terminology
- Consider both substantive and procedural aspects
- Provide practical, actionable advice

## NEVER
- Provide advice on criminal law cases
- Guarantee legal outcomes
- Replace the need for a licensed attorney in court"


# THINKING PROCESS
- Your thinking should be thorough and so it's fine if it's very long. You can think step by step before and after each action you decide to take.
- You MUST plan extensively before each function call, and reflect extensively on the outcomes of the previous function calls. DO NOT do this entire process by making function calls only, as this can impair your ability to solve the problem and think insightfully.
"""}

    # ────────────────────────────────────────────────────────────────────
    # HANDLING FUNCTION CALLS
    # ────────────────────────────────────────────────────────────────────
    async def handle_tool_calls(
        self,
        function_calls: List[ResponseFunctionToolCall],
        audit_trail: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Execute model-requested functions and return *function_call_output* items."""
        outputs: List[Dict[str, Any]] = []

        for fc in function_calls:
            call_id = fc.call_id
            name = fc.name
            try:
                args = json.loads(fc.arguments)
            except json.JSONDecodeError:
                args = {}

            trail_entry = {
                "timestamp": datetime.now().isoformat(),
                "type": "tool_call",
                "tool_name": name,
                "tool_call_id": call_id,
                "arguments": args,
            }

            # Execute matching python function, sync or async
            try:
                start = datetime.now()
                func = self.tools_map.get(name)
                if func is None:
                    raise ValueError(f"Unknown tool: {name}")

                result = await func(**args) if asyncio.iscoroutinefunction(func) else func(**args)
                duration = (datetime.now() - start).total_seconds()
                trail_entry.update(status="success", execution_time_seconds=duration, result=result)
            except Exception as exc:
                duration = (datetime.now() - start).total_seconds()
                result = {"error": str(exc)}
                trail_entry.update(status="error", execution_time_seconds=duration, error=str(exc))

            audit_trail.append(trail_entry)
            logger.info("Tool call audit: %s", json.dumps(trail_entry, ensure_ascii=False))

            outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": str(result),
                }
            )

        return outputs

    # ────────────────────────────────────────────────────────────────────
    # MAIN MESSAGE HANDLER
    # ────────────────────────────────────────────────────────────────────
    async def process_message(
        self,
        user_message: str,
        thread_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        audit_trail: List[Dict[str, Any]] = []
        start_time = datetime.now()
        conversation_id = thread_id or f"conv_{start_time.timestamp()}"

        audit_trail.append(
            {
                "timestamp": start_time.isoformat(),
                "type": "user_message",
                "content": user_message,
                "conversation_id": conversation_id,
            }
        )

        # Determine if we already have context for this conversation
        prev_resp_id = self.conversations.get(conversation_id)
        user_message_input = {"role": "user", "content": user_message}
        all_inputs = [self.get_system_prompt(), user_message_input]

        # ── 1️⃣ FIRST/CONTINUATION CALL ────────────────────────────────
        try:
            logger.info("Calling OpenAI Responses API (initial)")
            response = await client.responses.create(
                model=settings.openai_orchestrator_model,
                input=all_inputs,
                previous_response_id=prev_resp_id,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                temperature=0.1,
            )
            prev_resp_id = response.id

            audit_trail.append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "type": "api_call_initial",
                    "usage": str(getattr(response, "usage", None)),
                }
            )

            # Persist last response ID for the thread
            self.conversations[conversation_id] = prev_resp_id

            while True:
                # Split model output into text + function calls
                function_calls = [item for item in response.output if item.type == "function_call"]

                # ── 2️⃣ IF TOOL CALLS PRESENT ──────────────────────────────
                if function_calls:
                    tool_outputs = await self.handle_tool_calls(function_calls, audit_trail)
                    all_inputs = tool_outputs
                    logger.info(f"All inputs: {all_inputs}")

                    logger.info("Calling OpenAI Responses API (after tool outputs)")
                    response = await client.responses.create(
                        model=settings.openai_orchestrator_model,
                        previous_response_id=prev_resp_id,
                        input=all_inputs,
                        temperature=0.1,
                    )
                    prev_resp_id = response.id

                    audit_trail.append(
                        {
                            "timestamp": datetime.now().isoformat(),
                            "type": "api_call_follow_up",
                            "usage": str(getattr(response, "usage", None)),
                        }
                    )

                    # Update last response id
                    self.conversations[conversation_id] = prev_resp_id

                    # Extract text from follow‑up
                    assistant_response_text = response.output_text or ""
                else:
                    assistant_response_text = response.output_text or ""
                    break

            # ── 3️⃣ Persist audit log ──────────────────────────────────
            duration = (datetime.now() - start_time).total_seconds()
            interaction_id = f"{conversation_id}_{datetime.now().timestamp()}"

            full_audit_record = {
                "interaction_id": interaction_id,
                "conversation_id": conversation_id,
                "start_time": start_time.isoformat(),
                "end_time": datetime.now().isoformat(),
                "duration_seconds": duration,
                "status": "success",
                "user_message": user_message,
                "assistant_response": assistant_response_text,
                "audit_trail": audit_trail,
            }

            await self.save_audit_record(full_audit_record)

            return {
                "response": assistant_response_text,
                "thread_id": conversation_id,
                "status": "success",
                "audit_id": interaction_id,
            }

        except Exception as e:
            logger.exception("Error processing message: %s", e)
            audit_trail.append(
                {"timestamp": datetime.now().isoformat(), "type": "error", "error": str(e)}
            )
            duration = (datetime.now() - start_time).total_seconds()
            interaction_id = f"{conversation_id}_{datetime.now().timestamp()}"
            error_record = {
                "interaction_id": interaction_id,
                "conversation_id": conversation_id,
                "case_id": case_id,
                "start_time": start_time.isoformat(),
                "end_time": datetime.now().isoformat(),
                "duration_seconds": duration,
                "status": "error",
                "user_message": user_message,
                "assistant_response": None,
                "error": str(e),
                "audit_trail": audit_trail,
            }
            await self.save_audit_record(error_record)
            return {
                "response": f"Nie mogłem przetworzyć zapytania. Błąd: {e}",
                "thread_id": conversation_id,
                "status": "error",
                "audit_id": interaction_id,
            }

    # ────────────────────────────────────────────────────────────────────
    # DATABASE HELPERS (unchanged except for small typing tweaks)
    # ────────────────────────────────────────────────────────────────────
    async def save_audit_record(self, record: Dict[str, Any]) -> None:
        async with AsyncSessionLocal() as session:
            note = Note(
                case_id=record.get("case_id"),
                note_type="ai_audit",
                subject=f"AI Interaction Audit - {record['interaction_id']}",
                content=json.dumps(record, ensure_ascii=False, indent=2),
            )
            session.add(note)
            await session.commit()
            logger.debug("Audit record saved: %s", record["interaction_id"])

    async def save_ai_interaction(self, context: Dict[str, Any]) -> None:
        async with AsyncSessionLocal() as session:
            note = Note(
                note_type="ai_interaction",
                subject="AI Assistant Context",
                content=json.dumps(context, ensure_ascii=False),
            )
            session.add(note)
            await session.commit()

    async def load_ai_interaction(self) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Note)
                .where(Note.note_type == "ai_interaction")
                .order_by(Note.created_at.desc())
                .limit(1)
            )
            note = result.scalar_one_or_none()
            return json.loads(note.content) if note else None

    async def get_audit_records(
        self, *, conversation_id: Optional[str] = None, case_id: Optional[str] = None, limit: int = 10
    ) -> List[Dict[str, Any]]:
        async with AsyncSessionLocal() as session:
            query = select(Note).where(Note.note_type == "ai_audit")
            if case_id:
                query = query.where(Note.case_id == case_id)
            query = query.order_by(Note.created_at.desc()).limit(limit)
            result = await session.execute(query)
            notes = result.scalars().all()
            audits: List[Dict[str, Any]] = []
            for n in notes:
                rec = json.loads(n.content)
                if conversation_id and rec.get("conversation_id") != conversation_id:
                    continue
                audits.append(rec)
            return audits

    async def get_audit_summary(self, interaction_id: str) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Note)
                .where(Note.note_type == "ai_audit")
                .where(Note.subject.like(f"%{interaction_id}%"))
                .limit(1)
            )
            note = result.scalar_one_or_none()
            if not note:
                return None
            record = json.loads(note.content)
            summary = {
                "interaction_id": record["interaction_id"],
                "duration_seconds": record["duration_seconds"],
                "status": record["status"],
                "user_message": (
                    record["user_message"][:97] + "..." if len(record["user_message"]) > 100 else record["user_message"]
                ),
                "tool_calls": [],
                "errors": [],
            }
            for entry in record["audit_trail"]:
                if entry.get("type") == "tool_call":
                    summary["tool_calls"].append(
                        {
                            "tool": entry.get("tool_name"),
                            "status": entry.get("status", "unknown"),
                            "execution_time": entry.get("execution_time_seconds", 0),
                        }
                    )
                if entry.get("type") == "error" or entry.get("status") == "error":
                    summary["errors"].append(entry.get("error", "Unknown error"))
            return summary

# ────────────────────────────────────────────────────────────────────────
# Example standalone execution for quick manual test (dev‑only)
# ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    async def _demo():
        agent = ParalegalAgent()
        reply = await agent.process_message(
            "Jakie są terminy na wniesienie apelacji w postępowaniu cywilnym?"
        )
        print(reply["response"][:500])

    asyncio.run(_demo())
