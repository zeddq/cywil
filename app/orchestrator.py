from typing import List, Dict, Any, Optional
import asyncio
from openai import AsyncOpenAI
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
    init_vector_db
)
from .config import settings
from .database import get_db, AsyncSessionLocal
from .models import Case, Document, Deadline, Note
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Initialize logging
logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = AsyncOpenAI(api_key=settings.openai_api_key)

# Tool definitions for OpenAI Function Calling
TOOL_DEFINITIONS = [
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

class ParalegalAgent:
    def __init__(self):
        self.tools_map = {
            "search_statute": search_statute,
            "draft_document": draft_document,
            "compute_deadline": compute_deadline,
            "validate_document": validate_against_statute
        }
        # Initialize vector DB
        init_vector_db(settings.qdrant_host, settings.qdrant_port)
        # Store conversation history for context
        self.conversations = {}
    
    def get_system_prompt(self):
        """Get the system prompt for the assistant"""
        return """You are an expert Polish legal assistant specializing in civil law (Kodeks cywilny) and civil procedure (Kodeks postępowania cywilnego). 

Your responsibilities:
1. Answer legal questions with precise citations to relevant articles
2. Draft legal documents following Polish legal standards
3. Calculate procedural deadlines accurately
4. Validate documents against current statutes

Always:
- Cite specific articles (e.g., "art. 415 KC")
- Use proper Polish legal terminology
- Consider both substantive and procedural aspects
- Provide practical, actionable advice

Never:
- Provide advice on criminal law cases
- Guarantee legal outcomes
- Replace the need for a licensed attorney in court"""
    
    async def handle_tool_calls(self, tool_calls: List[Dict], audit_trail: List[Dict]) -> List[Dict]:
        """Process tool calls from the assistant"""
        tool_messages = []
        
        for tool_call in tool_calls:
            function_name = tool_call["function"]["name"]
            tool_call_id = tool_call["id"]
            
            try:
                arguments = json.loads(tool_call["function"]["arguments"])
            except json.JSONDecodeError:
                arguments = {}
            
            # Create audit entry for tool call
            audit_entry = {
                "timestamp": datetime.now().isoformat(),
                "type": "tool_call",
                "tool_name": function_name,
                "tool_call_id": tool_call_id,
                "arguments": arguments
            }
            
            # Execute the corresponding tool
            if function_name in self.tools_map:
                try:
                    start_time = datetime.now()
                    if asyncio.iscoroutinefunction(self.tools_map[function_name]):
                        result = await self.tools_map[function_name](**arguments)
                    else:
                        result = self.tools_map[function_name](**arguments)
                    
                    execution_time = (datetime.now() - start_time).total_seconds()
                    
                    # Add result to audit entry
                    audit_entry["result"] = result
                    audit_entry["execution_time_seconds"] = execution_time
                    audit_entry["status"] = "success"
                    
                    tool_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": json.dumps(result, ensure_ascii=False)
                    })
                except Exception as e:
                    # Log error in audit trail
                    audit_entry["error"] = str(e)
                    audit_entry["status"] = "error"
                    audit_entry["execution_time_seconds"] = (datetime.now() - start_time).total_seconds()
                    
                    tool_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": json.dumps({"error": str(e)})
                    })
            else:
                audit_entry["status"] = "error"
                audit_entry["error"] = f"Unknown tool: {function_name}"
                
                tool_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps({"error": f"Unknown tool: {function_name}"})
                })
            
            # Add to audit trail
            audit_trail.append(audit_entry)
            logger.info(f"Tool call audit: {json.dumps(audit_entry, ensure_ascii=False)}")
        
        return tool_messages
    
    async def process_message(self, user_message: str, thread_id: Optional[str] = None, case_id: Optional[str] = None) -> Dict[str, Any]:
        """Process a user message and return the assistant's response"""
        # Initialize audit trail for this interaction
        audit_trail = []
        interaction_start = datetime.now()
        
        # Create audit entry for user message
        audit_trail.append({
            "timestamp": interaction_start.isoformat(),
            "type": "user_message",
            "content": user_message,
            "thread_id": thread_id,
            "case_id": case_id
        })
        
        # Use thread_id as conversation_id for maintaining context
        conversation_id = thread_id or f"conv_{datetime.now().timestamp()}"
        
        # Initialize conversation history if needed
        if conversation_id not in self.conversations:
            self.conversations[conversation_id] = [
                {"role": "system", "content": self.get_system_prompt()}
            ]
            audit_trail.append({
                "timestamp": datetime.now().isoformat(),
                "type": "conversation_created",
                "conversation_id": conversation_id
            })
        
        # Get conversation history
        messages = self.conversations[conversation_id].copy()
        
        # Add user message to history
        messages.append({"role": "user", "content": user_message})
        
        # Keep conversation history manageable (last 10 exchanges)
        if len(messages) > 21:  # 1 system + 10 exchanges * 2 messages each
            messages = [messages[0]] + messages[-20:]  # Keep system prompt + last 10 exchanges
        
        try:
            # Call Responses API
            logger.info("Calling OpenAI Responses API")
            response = await client.responses.create(
                model=settings.openai_model,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                temperature=0.1
            )
            
            audit_trail.append({
                "timestamp": datetime.now().isoformat(),
                "type": "api_call",
                "model": settings.openai_model,
                "usage": response.usage.dict() if hasattr(response, 'usage') and response.usage else None
            })
            
            # Get the assistant's message
            assistant_message = response.choices[0].message
            
            # Handle tool calls if present
            if hasattr(assistant_message, 'tool_calls') and assistant_message.tool_calls:
                # Add assistant message with tool calls to conversation
                messages.append(assistant_message.dict() if hasattr(assistant_message, 'dict') else 
                              {"role": "assistant", "content": None, "tool_calls": assistant_message.tool_calls})
                
                # Process tool calls
                tool_messages = await self.handle_tool_calls(
                    assistant_message.tool_calls,
                    audit_trail
                )
                
                # Add tool results to messages
                messages.extend(tool_messages)
                
                # Get final response after tool execution
                logger.info("Calling OpenAI Responses API again with tool results")
                final_response = await client.responses.create(
                    model=settings.openai_model,
                    messages=messages,
                    temperature=0.1
                )
                
                audit_trail.append({
                    "timestamp": datetime.now().isoformat(),
                    "type": "api_call_with_tools",
                    "usage": final_response.usage.dict() if hasattr(final_response, 'usage') and final_response.usage else None
                })
                
                assistant_message = final_response.choices[0].message
            
            # Extract response text
            response_text = assistant_message.content or ""
            
            # Add assistant response to conversation history
            messages.append({"role": "assistant", "content": response_text})
            
            # Update stored conversation
            self.conversations[conversation_id] = messages
            
            # Add assistant response to audit trail
            audit_trail.append({
                "timestamp": datetime.now().isoformat(),
                "type": "assistant_response",
                "content": response_text
            })
            
            # Calculate total interaction time
            interaction_time = (datetime.now() - interaction_start).total_seconds()
            
            # Create complete audit record
            audit_record = {
                "interaction_id": f"{conversation_id}_{datetime.now().timestamp()}",
                "thread_id": conversation_id,
                "case_id": case_id,
                "start_time": interaction_start.isoformat(),
                "end_time": datetime.now().isoformat(),
                "duration_seconds": interaction_time,
                "status": "success",
                "user_message": user_message,
                "assistant_response": response_text,
                "audit_trail": audit_trail
            }
            
            # Save audit record
            await self.save_audit_record(audit_record)
            
            return {
                "response": response_text,
                "thread_id": conversation_id,
                "status": "success",
                "audit_id": audit_record["interaction_id"]
            }
            
        except Exception as e:
            # Handle error case
            logger.error(f"Error processing message: {str(e)}")
            audit_trail.append({
                "timestamp": datetime.now().isoformat(),
                "type": "error",
                "error": str(e)
            })
            
            audit_record = {
                "interaction_id": f"{conversation_id}_{datetime.now().timestamp()}",
                "thread_id": conversation_id,
                "case_id": case_id,
                "start_time": interaction_start.isoformat(),
                "end_time": datetime.now().isoformat(),
                "duration_seconds": (datetime.now() - interaction_start).total_seconds(),
                "status": "error",
                "user_message": user_message,
                "assistant_response": None,
                "error": str(e),
                "audit_trail": audit_trail
            }
            
            await self.save_audit_record(audit_record)
            
            return {
                "response": "Nie mogłem przetworzyć zapytania. Błąd: " + str(e),
                "thread_id": conversation_id,
                "status": "error",
                "audit_id": audit_record["interaction_id"]
            }
    
    async def save_audit_record(self, audit_record: Dict[str, Any]) -> None:
        """Save audit record to database"""
        async with AsyncSessionLocal() as session:
            # Save as a note with detailed audit information
            note = Note(
                case_id=audit_record.get("case_id"),
                note_type="ai_audit",
                subject=f"AI Interaction Audit - {audit_record['interaction_id']}",
                content=json.dumps(audit_record, ensure_ascii=False, indent=2)
            )
            session.add(note)
            await session.commit()
            
            # Also log to file for debugging
            logger.info(f"Audit record saved: {audit_record['interaction_id']}")
            logger.debug(f"Full audit record: {json.dumps(audit_record, ensure_ascii=False, indent=2)}")
    
    async def save_case_context(self, case_id: str, context: Dict[str, Any]) -> None:
        """Save case context to database"""
        async with AsyncSessionLocal() as session:
            # Save as a note
            note = Note(
                case_id=case_id,
                note_type="ai_interaction",
                subject="AI Assistant Context",
                content=json.dumps(context, ensure_ascii=False)
            )
            session.add(note)
            await session.commit()
    
    async def load_case_context(self, case_id: str) -> Optional[Dict[str, Any]]:
        """Load case context from database"""
        async with AsyncSessionLocal() as session:
            # Get latest AI interaction note
            result = await session.execute(
                select(Note)
                .where(Note.case_id == case_id)
                .where(Note.note_type == "ai_interaction")
                .order_by(Note.created_at.desc())
                .limit(1)
            )
            note = result.scalar_one_or_none()
            
            if note:
                return json.loads(note.content)
            return None
    
    async def get_audit_records(self, thread_id: Optional[str] = None, case_id: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieve audit records for debugging"""
        async with AsyncSessionLocal() as session:
            query = select(Note).where(Note.note_type == "ai_audit")
            
            # Filter by case_id if provided
            if case_id:
                query = query.where(Note.case_id == case_id)
            
            # Order by creation time and limit
            query = query.order_by(Note.created_at.desc()).limit(limit)
            
            result = await session.execute(query)
            notes = result.scalars().all()
            
            audit_records = []
            for note in notes:
                record = json.loads(note.content)
                # Filter by thread_id if provided
                if thread_id and record.get("thread_id") != thread_id:
                    continue
                audit_records.append(record)
            
            return audit_records
    
    async def get_audit_summary(self, interaction_id: str) -> Optional[Dict[str, Any]]:
        """Get a summary of a specific interaction for debugging"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Note)
                .where(Note.note_type == "ai_audit")
                .where(Note.subject.like(f"%{interaction_id}%"))
                .limit(1)
            )
            note = result.scalar_one_or_none()
            
            if note:
                audit_record = json.loads(note.content)
                # Create a summary
                summary = {
                    "interaction_id": audit_record["interaction_id"],
                    "duration_seconds": audit_record["duration_seconds"],
                    "status": audit_record["status"],
                    "user_message": audit_record["user_message"][:100] + "..." if len(audit_record["user_message"]) > 100 else audit_record["user_message"],
                    "tool_calls": [],
                    "errors": []
                }
                
                # Extract tool calls and errors from audit trail
                for entry in audit_record["audit_trail"]:
                    if entry["type"] == "tool_call":
                        summary["tool_calls"].append({
                            "tool": entry["tool_name"],
                            "status": entry.get("status", "unknown"),
                            "execution_time": entry.get("execution_time_seconds", 0)
                        })
                    elif entry["type"] == "error" or entry.get("status") == "error":
                        summary["errors"].append(entry.get("error", "Unknown error"))
                
                return summary
            return None

# Example usage
if __name__ == "__main__":
    async def test_agent():
        agent = ParalegalAgent()
        
        # Test Q&A with audit
        print("=== Testing Q&A with Audit ===")
        response = await agent.process_message(
            "Jakie są terminy na wniesienie apelacji w postępowaniu cywilnym?"
        )
        print("Q&A Response:", response["response"][:200] + "...")
        print("Audit ID:", response.get("audit_id"))
        
        # Get audit summary
        if response.get("audit_id"):
            summary = await agent.get_audit_summary(response["audit_id"])
            print("\nAudit Summary:")
            print(f"- Duration: {summary['duration_seconds']:.2f}s")
            print(f"- Tool calls: {len(summary['tool_calls'])}")
            for tool in summary['tool_calls']:
                print(f"  - {tool['tool']}: {tool['status']} ({tool['execution_time']:.2f}s)")
        
        # Test document drafting
        print("\n=== Testing Document Drafting with Audit ===")
        response = await agent.process_message(
            "Przygotuj wezwanie do zapłaty za fakturę na 45,000 zł z kwietnia 2025"
        )
        print("Draft Response:", response["response"][:200] + "...")
        print("Audit ID:", response.get("audit_id"))
        
        # Get recent audit records
        print("\n=== Recent Audit Records ===")
        recent_audits = await agent.get_audit_records(limit=5)
        for audit in recent_audits:
            print(f"- {audit['interaction_id']}: {audit['status']} ({audit['duration_seconds']:.2f}s)")
    
    asyncio.run(test_agent())
