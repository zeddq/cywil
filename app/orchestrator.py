from typing import List, Dict, Any, Optional, AsyncGenerator, Literal
import asyncio
from openai import AsyncOpenAI, AsyncStream
from langchain.tools import tool
from langchain_openai import ChatOpenAI, 
from openai.types.responses import ResponseFunctionToolCall, ResponseInProgressEvent, ResponseCompletedEvent, \
    ResponseCreatedEvent, ResponseOutputItemAddedEvent, ResponseOutputItemDoneEvent, ResponseFunctionCallArgumentsDeltaEvent, \
        ResponseFunctionCallArgumentsDoneEvent, ResponseStreamEvent, ResponseOutputMessage, ResponseTextDeltaEvent, ResponseTextDoneEvent
from openai.types.responses.response_input_param import FunctionCallOutput
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
from pydantic import BaseModel
from langchain_core.messages import BaseMessageChunk, ToolMessage
from typing import AsyncIterator
"""
───────────────────────────────────────────────────────────────────────────────
FIX NOTES
─────────
* Upgraded to **Responses API** semantics.
  * Replaced `response.choices[0].message` access with `response.output` / `response.output_text`.
  * Added `previous_response_id` chaining instead of resending full history after the 1st turn.
  * Updated function calling flow:
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
client = ChatOpenAI(api_key=settings.openai_api_key, model=settings.openai_orchestrator_model)

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
                "status": {"type": "string", "description": "New status of the case"},
                "case_type": {"type": "string", "description": "New type of the case"},
                "client_name": {"type": "string", "description": "New name of the client"},
                "client_contact": {"type": "string", "description": "New contact of the client"},
                "opposing_party": {"type": "string", "description": "New name of the opposing party"},
                "opposing_party_contact": {"type": "string", "description": "New contact of the opposing party"},
                "court_name": {"type": "string", "description": "New name of the court"},
                "court_case_number": {"type": "string", "description": "New case number of the court"},
                "judge_name": {"type": "string", "description": "New name of the judge"},
                "amount_in_dispute": {"type": "string", "description": "New amount in dispute"},
                "currency": {"type": "string", "description": "New currency of the case"},
            },
            "required": ["case_id"]
        }
    },
    {
        "type": "function",
        "name": "recover_from_tool_error",
        "description": "Recover from a tool error",
        "parameters": {
            "type": "object",
            "properties": {
                "conversation_history": {"type": "array", "items": {"type": "object"}, "description": "The conversation history leading up to the error"},
                "failed_function_call": {"type": "object", "description": "The function call that failed (full function_tool object)"},
                "error_message": {"type": "string", "description": "The error message returned by the tool"},
            },
            "required": ["conversation_history", "failed_function_call", "error_message"]
        }
    }
]

client.bind_tools(TOOL_DEFINITIONS)

def flatten_tool_outputs(tool_outputs: List[Dict[str, Any]]) -> str:
    return "\n".join([json.dumps(output) for output in tool_outputs])

class ChatStreamResponse(BaseModel):
    type: Literal["text_chunk", "tool_call_start", "tool_call_complete", "full_message"]
    content: str | List[Dict[str, Any]] | None = None
    thread_id: str | None = None
    status: Literal["streaming", "error", "success"]

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
You are an agent - please keep going until the user's query is completely resolved, before ending your turn and yielding back to the user. Only terminate your turn when you are sure that the problem is solved.

# THINKING PROCESS
- Your thinking should be thorough and so it's fine if it's very long. You can think step by step before and after each action you decide to take.
- You MUST plan extensively before each function call, and reflect extensively on the outcomes of the previous function calls. DO NOT do this entire process by making function calls only, as this can impair your ability to solve the problem and think insightfully.

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
"""}

    # ────────────────────────────────────────────────────────────────────
    # HANDLING FUNCTION CALLS
    # ────────────────────────────────────────────────────────────────────
    async def handle_tool_calls(
        self,
        function_calls: List[Any],
        audit_trail: List[Dict[str, Any]],
    ) -> List[ToolMessage]:
        """Execute model-requested functions and return *function_call_output* items."""
        outputs: List[ToolMessage] = []

        for fc in function_calls:
            call_id = fc.id
            name = fc.name
            try:
                args = json.loads(fc.arguments) if fc.arguments else {}
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

            outputs.append(ToolMessage(content=str(result), tool_call_id=call_id))

        return outputs


    def _handle_chunk(self, chunk: BaseMessageChunk) -> ChatStreamResponse | None:
        if chunk.content:
            return ChatStreamResponse(type="text_chunk", content=chunk.content, status="streaming")
        
        return None

    # ────────────────────────────────────────────────────────────────────
    # MAIN MESSAGE HANDLER
    # ────────────────────────────────────────────────────────────────────
    async def process_message(
        self,
        user_message: str,
        thread_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Process a message and return complete response."""
        async for chunk in self.process_message_stream(user_message, thread_id):
            pass  # Consume the stream
        return chunk  # Return the final result

    # ────────────────────────────────────────────────────────────────────
    # MAIN MESSAGE STREAMING HANDLER
    # ────────────────────────────────────────────────────────────────────
    async def process_message_stream(
        self,
        user_message: str,
        db: AsyncSession,
        thread_id: Optional[str] = None,
    ) -> AsyncGenerator[ChatStreamResponse, None]:
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

        # ── 1️⃣ FIRST/CONTINUATION CALL WITH STREAMING ────────────────────────────────
        try:
            logger.info("Calling OpenAI Responses API (initial) with streaming")

            response: AsyncIterator[BaseMessageChunk] = await client.astream(all_inputs,
                use_responses_api=True,
                previous_response_id=prev_resp_id,
                temperature=0.0,
            )            
            logger.info(response)
            
            accumulated_response = ""
            current_tool_calls: List[Any] = []
            
            first_chunk = True
            last_chunk = False
            async for chunk in response:
                logger.info(chunk)
                if first_chunk:
                    merged_chunks = chunk
                else:
                    merged_chunks = merged_chunks + chunk
                parsed = self._handle_chunk(chunk)
                if parsed:
                    if parsed.thread_id:
                        prev_resp_id = parsed.thread_id
                        self.conversations[conversation_id] = prev_resp_id
                    if parsed.status == "streaming":
                        parsed.thread_id = conversation_id
                        yield parsed
                    last_chunk = parsed.status == "success"
                    first_chunk = False

            if merged_chunks:
                for tool_call in merged_chunks.additional_kwargs.get("tool_calls", []):
                    current_tool_calls.append(tool_call)

            if not last_chunk or current_tool_calls:
                audit_trail.append(
                    {
                        "timestamp": datetime.now().isoformat(),
                        "type": "api_call_initial",
                        "streaming": True,
                    }
                )

                while current_tool_calls:
                    # ── 2️⃣ HANDLE TOOL CALLS ──────────────────────────────
                    yield ChatStreamResponse(type="tool_call_start",
                                             content=[{"name": tc.name, "call_id": tc.call_id} for tc in current_tool_calls],
                                            thread_id=conversation_id, status="streaming")
                    
                    tool_outputs = await self.handle_tool_calls(current_tool_calls, audit_trail)
                    all_inputs = tool_outputs
                    
                    yield ChatStreamResponse(type="tool_call_complete",
                                             content=[{"output": tc['output'], "call_id": tc['call_id']} for tc in tool_outputs],
                                             thread_id=conversation_id, status="streaming")

                    logger.info("Calling OpenAI Responses API (after tool outputs) with streaming")
                    response = await client.astream(
                        all_inputs,
                        use_responses_api=True,
                        previous_response_id=prev_resp_id,
                        temperature=0.0,
                    )
                    
                    current_tool_calls = []
                    
                    last_chunk = False
                    async for chunk in response:
                        parsed = self._handle_chunk(chunk, current_tool_calls)
                        if parsed:
                            if parsed.thread_id:
                                prev_resp_id = parsed.thread_id
                                self.conversations[conversation_id] = prev_resp_id
                            if parsed.status == "streaming":
                                yield parsed
                            last_chunk = parsed.status == "success"

                    audit_trail.append(
                        {
                            "timestamp": datetime.now().isoformat(),
                            "type": "api_call_follow_up",
                            "streaming": True,
                        }
                    )
                    if last_chunk and not current_tool_calls:
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
                    "assistant_response": accumulated_response,
                    "audit_trail": audit_trail,
                }

                await self.save_audit_record(full_audit_record, db)

                # Final complete response
                yield ChatStreamResponse(type="text_chunk", content=accumulated_response, thread_id=conversation_id, status="success")

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
                "start_time": start_time.isoformat(),
                "end_time": datetime.now().isoformat(),
                "duration_seconds": duration,
                "status": "error",
                "user_message": user_message,
                "assistant_response": None,
                "error": str(e),
                "audit_trail": audit_trail,
            }
            await self.save_audit_record(error_record, db)
            yield ChatStreamResponse(type="text_chunk", content=f"Nie mogłem przetworzyć zapytania. Błąd: {e}",
                                     thread_id=conversation_id, status="error")

    # ────────────────────────────────────────────────────────────────────
    # DATABASE HELPERS (unchanged except for small typing tweaks)
    # ────────────────────────────────────────────────────────────────────
    async def save_audit_record(self, record: Dict[str, Any], db: AsyncSession) -> None:
        note = Note(
            note_type="ai_audit",
            subject=f"AI Interaction Audit - {record['interaction_id']}",
            content=json.dumps(record, ensure_ascii=False, indent=2),
        )
        if record.get("case_id"):
            note.case_id = record["case_id"]
        db.add(note)
        await db.commit()
        logger.debug("Audit record saved: %s", record["interaction_id"])

    async def save_ai_interaction(self, context: Dict[str, Any], db: AsyncSession) -> None:
        note = Note(
            note_type="ai_interaction",
            subject="AI Assistant Context",
            content=json.dumps(context, ensure_ascii=False),
        )
        db.add(note)
        await db.commit()

    async def load_ai_interaction(self, db: AsyncSession) -> Optional[Dict[str, Any]]:
        result = await db.execute(
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
