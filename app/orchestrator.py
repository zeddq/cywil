from typing import List, Dict, Any, Optional
import asyncio
from openai import AsyncOpenAI
from openai.types.beta import Thread
from openai.types.beta.threads import Run
import json
from datetime import datetime
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
        self.assistant = None
        self.tools_map = {
            "search_statute": search_statute,
            "draft_document": draft_document,
            "compute_deadline": compute_deadline,
            "validate_document": validate_against_statute
        }
        # Initialize vector DB
        init_vector_db(settings.qdrant_host, settings.qdrant_port)
    
    async def initialize(self):
        """Create or retrieve the assistant"""
        # Check if assistant already exists
        assistants = await client.beta.assistants.list()
        for assistant in assistants.data:
            if assistant.name == "Polish Legal Assistant":
                self.assistant = assistant
                return
        
        # Create new assistant
        self.assistant = await client.beta.assistants.create(
            name="Polish Legal Assistant",
            instructions="""You are an expert Polish legal assistant specializing in civil law (Kodeks cywilny) and civil procedure (Kodeks postępowania cywilnego). 

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
- Replace the need for a licensed attorney in court""",
            model=settings.openai_model,
            tools=TOOL_DEFINITIONS
        )
    
    async def handle_tool_calls(self, run: Run, thread_id: str) -> None:
        """Process tool calls from the assistant"""
        if not run.required_action:
            return
        
        tool_outputs = []
        
        for tool_call in run.required_action.submit_tool_outputs.tool_calls:
            function_name = tool_call.function.name
            arguments = json.loads(tool_call.function.arguments)
            
            # Execute the corresponding tool
            if function_name in self.tools_map:
                try:
                    if asyncio.iscoroutinefunction(self.tools_map[function_name]):
                        result = await self.tools_map[function_name](**arguments)
                    else:
                        result = self.tools_map[function_name](**arguments)
                    
                    tool_outputs.append({
                        "tool_call_id": tool_call.id,
                        "output": json.dumps(result, ensure_ascii=False)
                    })
                except Exception as e:
                    tool_outputs.append({
                        "tool_call_id": tool_call.id,
                        "output": json.dumps({"error": str(e)})
                    })
        
        # Submit tool outputs
        if tool_outputs:
            await client.beta.threads.runs.submit_tool_outputs(
                thread_id=thread_id,
                run_id=run.id,
                tool_outputs=tool_outputs
            )
    
    async def process_message(self, user_message: str, thread_id: Optional[str] = None) -> Dict[str, Any]:
        """Process a user message and return the assistant's response"""
        if not self.assistant:
            await self.initialize()
        
        # Create or retrieve thread
        if not thread_id:
            thread = await client.beta.threads.create()
            thread_id = thread.id
        
        # Add user message
        await client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=user_message
        )
        
        # Create and run
        run = await client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=self.assistant.id
        )
        
        # Wait for completion
        while run.status in ["queued", "in_progress", "requires_action"]:
            if run.status == "requires_action":
                await self.handle_tool_calls(run, thread_id)
            
            await asyncio.sleep(1)
            run = await client.beta.threads.runs.retrieve(
                thread_id=thread_id,
                run_id=run.id
            )
        
        # Get messages
        messages = await client.beta.threads.messages.list(thread_id=thread_id)
        assistant_messages = [msg for msg in messages.data if msg.role == "assistant"]
        
        if assistant_messages:
            latest_message = assistant_messages[0]
            response_text = ""
            for content in latest_message.content:
                if content.type == "text":
                    response_text += content.text.value
            
            return {
                "response": response_text,
                "thread_id": thread_id,
                "status": "success"
            }
        
        return {
            "response": "Nie mogłem przetworzyć zapytania.",
            "thread_id": thread_id,
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
        agent = ParalegalAgent()
        
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
