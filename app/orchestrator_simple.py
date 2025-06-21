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
client = AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

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

class SimpleParalegalAgent:
    def __init__(self):
        self.tools_map = {
            "search_statute": search_statute,
            "draft_document": draft_document,
            "compute_deadline": compute_deadline,
            "validate_document": validate_against_statute
        }
        # Initialize vector DB
        init_vector_db(settings.qdrant_host, settings.qdrant_port)
        self.conversation_history = []
    
    async def process_message(self, user_message: str, thread_id: Optional[str] = None) -> Dict[str, Any]:
        """Process a user message and return the assistant's response"""
        if not client or not settings.openai_api_key:
            return {
                "response": "Błąd: Brak klucza API OpenAI. Ustaw zmienną środowiskową OPENAI_API_KEY.",
                "thread_id": thread_id or "no-api-key",
                "status": "error"
            }
        
        try:
            # Add user message to history
            self.conversation_history.append({"role": "user", "content": user_message})
            
            # Keep only last 10 messages for context
            messages = [{"role": "system", "content": """You are an expert Polish legal assistant specializing in civil law (Kodeks cywilny) and civil procedure (Kodeks postępowania cywilnego). 

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
- Replace the need for a licensed attorney in court"""}]
            messages.extend(self.conversation_history[-10:])
            
            # Call OpenAI Chat Completion with tools
            logger.info("Calling OpenAI API for chat completion with tools")
            response = await client.chat.completions.create(
                model=settings.openai_orchestrator_model,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto"
            )
            
            assistant_message = response.choices[0].message
            
            # Handle tool calls if any
            if assistant_message.tool_calls:
                # Add assistant's message with tool calls to history
                self.conversation_history.append({
                    "role": "assistant",
                    "content": assistant_message.content or "",
                    "tool_calls": assistant_message.tool_calls
                })
                
                # Execute tool calls
                tool_results = []
                for tool_call in assistant_message.tool_calls:
                    function_name = tool_call.function.name
                    arguments = json.loads(tool_call.function.arguments)
                    
                    if function_name in self.tools_map:
                        try:
                            if asyncio.iscoroutinefunction(self.tools_map[function_name]):
                                result = await self.tools_map[function_name](**arguments)
                            else:
                                result = self.tools_map[function_name](**arguments)
                            
                            tool_results.append({
                                "tool_call_id": tool_call.id,
                                "role": "tool",
                                "name": function_name,
                                "content": json.dumps(result, ensure_ascii=False)
                            })
                        except Exception as e:
                            tool_results.append({
                                "tool_call_id": tool_call.id,
                                "role": "tool",
                                "name": function_name,
                                "content": json.dumps({"error": str(e)})
                            })
                
                # Add tool results to conversation
                for result in tool_results:
                    self.conversation_history.append(result)
                
                # Get final response with tool results
                messages = [{"role": "system", "content": SYSTEM_PROMPT}]
                messages.extend(self.conversation_history[-15:])  # Include more context with tool results
                
                logger.info("Calling OpenAI API for final response with tool results")
                final_response = await client.chat.completions.create(
                    model=settings.openai_orchestrator_model,
                    messages=messages
                )
                
                final_message = final_response.choices[0].message.content
                self.conversation_history.append({"role": "assistant", "content": final_message})
                
                return {
                    "response": final_message,
                    "thread_id": thread_id or "simple-chat",
                    "status": "success"
                }
            else:
                # No tool calls, just return the response
                response_text = assistant_message.content
                self.conversation_history.append({"role": "assistant", "content": response_text})
                
                return {
                    "response": response_text,
                    "thread_id": thread_id or "simple-chat",
                    "status": "success"
                }
                
        except Exception as e:
            return {
                "response": f"Wystąpił błąd: {str(e)}",
                "thread_id": thread_id or "error",
                "status": "error"
            }
    
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

# Example usage
if __name__ == "__main__":
    async def test_agent():
        agent = SimpleParalegalAgent()
        
        # Test Q&A
        response = await agent.process_message(
            "Jakie są terminy na wniesienie apelacji w postępowaniu cywilnym?"
        )
        print("Q&A Response:", response)
        
        # Test document drafting
        response = await agent.process_message(
            "Przygotuj wezwanie do zapłaty za fakturę na 45,000 zł z kwietnia 2025"
        )
        print("Draft Response:", response)
    
    asyncio.run(test_agent())
