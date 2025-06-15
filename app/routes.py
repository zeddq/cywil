from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from datetime import datetime, timedelta
import os
from .orchestrator import ParalegalAgent
from .database import get_db, init_db
from .models import Case, Document, Deadline, Note
from .config import settings
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Paralegal API", version="1.0.0")

# Initialize agent
agent = ParalegalAgent()

# OAuth2 scheme for authentication (simplified for POC)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Pydantic models for request/response
class ChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None
    case_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    thread_id: str
    status: str

class CaseCreate(BaseModel):
    case_number: str
    title: str
    description: Optional[str] = None
    case_type: str
    client_name: str
    client_contact: Dict[str, Any]
    opposing_party: Optional[str] = None
    amount_in_dispute: Optional[float] = None

class DocumentCreate(BaseModel):
    case_id: str
    document_type: str
    title: str
    content: str
    metadata: Optional[Dict[str, Any]] = {}

class DeadlineCreate(BaseModel):
    case_id: str
    deadline_type: str
    description: str
    due_date: datetime
    legal_basis: Optional[str] = None
    reminder_days_before: int = 7

@app.on_event("startup")
async def startup_event():
    """Initialize database on startup"""
    await init_db()

@app.get("/")
async def root():
    return {
        "message": "AI Paralegal API is running",
        "version": "1.0.0",
        "status": "operational"
    }

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, db: AsyncSession = Depends(get_db)):
    """
    Main chat endpoint for interacting with the AI paralegal
    """
    try:
        # Load case context if provided
        if request.case_id:
            context = await agent.load_case_context(request.case_id)
            if context:
                # Prepend context to message
                request.message = f"[Context for case {request.case_id}: {json.dumps(context)}]\n\n{request.message}"
        logger.info(f"Request message: {request.message}")
        # Process message
        result = await agent.process_message(request.message, request.thread_id, request.case_id)
        logger.info(f"Result: {result}")
        # Save interaction to case if provided
        if request.case_id and result["status"] == "success":
            await agent.save_case_context(request.case_id, {
                "last_query": request.message,
                "last_response": result["response"],
                "thread_id": result["thread_id"],
                "timestamp": datetime.now().isoformat()
            })
        
        return ChatResponse(**result)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    case_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Upload a legal document for processing"""
    # Create upload directory
    os.makedirs(settings.upload_dir, exist_ok=True)
    
    # Save file
    file_path = os.path.join(settings.upload_dir, file.filename)
    with open(file_path, "wb+") as file_object:
        content = await file.read()
        file_object.write(content)
    
    # Create document record if case_id provided
    if case_id:
        document = Document(
            case_id=case_id,
            document_type="uploaded",
            title=file.filename,
            file_path=file_path,
            metadata={"original_filename": file.filename, "size": len(content)}
        )
        db.add(document)
        await db.commit()
        await db.refresh(document)
        
        return {
            "filename": file.filename,
            "status": "uploaded",
            "document_id": document.id,
            "case_id": case_id
        }
    
    return {"filename": file.filename, "status": "uploaded"}

@app.post("/cases", response_model=Dict[str, Any])
async def create_case(case: CaseCreate, db: AsyncSession = Depends(get_db)):
    """Create a new legal case"""
    db_case = Case(**case.dict())
    db.add(db_case)
    await db.commit()
    await db.refresh(db_case)
    
    return {
        "id": db_case.id,
        "case_number": db_case.case_number,
        "title": db_case.title,
        "created_at": db_case.created_at.isoformat()
    }

@app.get("/cases")
async def list_cases(
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """List all cases with optional filtering"""
    query = select(Case)
    if status:
        query = query.where(Case.status == status)
    
    result = await db.execute(query)
    cases = result.scalars().all()
    
    return {
        "cases": [
            {
                "id": m.id,
                "case_number": m.case_number,
                "title": m.title,
                "status": m.status,
                "client_name": m.client_name,
                "created_at": m.created_at.isoformat()
            }
            for m in cases
        ]
    }

@app.get("/cases/{case_id}")
async def get_case(case_id: str, db: AsyncSession = Depends(get_db)):
    """Get detailed information about a specific case"""
    result = await db.execute(
        select(Case).where(Case.id == case_id)
    )
    case = result.scalar_one_or_none()
    
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    
    # Get related documents and deadlines
    docs_result = await db.execute(
        select(Document).where(Document.case_id == case_id)
    )
    documents = docs_result.scalars().all()
    
    deadlines_result = await db.execute(
        select(Deadline).where(Deadline.case_id == case_id)
    )
    deadlines = deadlines_result.scalars().all()
    
    return {
        "case": {
            "id": case.id,
            "case_number": case.case_number,
            "title": case.title,
            "description": case.description,
            "status": case.status,
            "client_name": case.client_name,
            "opposing_party": case.opposing_party,
            "amount_in_dispute": case.amount_in_dispute
        },
        "documents": [
            {
                "id": d.id,
                "title": d.title,
                "document_type": d.document_type,
                "created_at": d.created_at.isoformat()
            }
            for d in documents
        ],
        "deadlines": [
            {
                "id": dl.id,
                "description": dl.description,
                "due_date": dl.due_date.isoformat(),
                "status": dl.status
            }
            for dl in deadlines
        ]
    }

@app.post("/documents", response_model=Dict[str, Any])
async def create_document(document: DocumentCreate, db: AsyncSession = Depends(get_db)):
    """Create a new document"""
    db_document = Document(**document.dict())
    db.add(db_document)
    await db.commit()
    await db.refresh(db_document)
    
    return {
        "id": db_document.id,
        "case_id": db_document.case_id,
        "title": db_document.title,
        "created_at": db_document.created_at.isoformat()
    }

@app.post("/deadlines", response_model=Dict[str, Any])
async def create_deadline(deadline: DeadlineCreate, db: AsyncSession = Depends(get_db)):
    """Create a new deadline"""
    db_deadline = Deadline(**deadline.dict())
    db.add(db_deadline)
    await db.commit()
    await db.refresh(db_deadline)
    
    # Schedule reminder if requested
    if deadline.reminder_days_before > 0:
        reminder_date = deadline.due_date - timedelta(days=deadline.reminder_days_before)
        await agent.schedule_reminder(
            case_id=deadline.case_id,
            reminder_date=reminder_date.isoformat(),
            note=f"Reminder: {deadline.description} - Due: {deadline.due_date}"
        )
    
    return {
        "id": db_deadline.id,
        "case_id": db_deadline.case_id,
        "description": db_deadline.description,
        "due_date": db_deadline.due_date.isoformat(),
        "reminder_scheduled": deadline.reminder_days_before > 0
    }

@app.get("/deadlines/upcoming")
async def get_upcoming_deadlines(
    days: int = 30,
    db: AsyncSession = Depends(get_db)
):
    """Get upcoming deadlines within specified days"""
    cutoff_date = datetime.now() + timedelta(days=days)
    
    result = await db.execute(
        select(Deadline)
        .where(Deadline.due_date <= cutoff_date)
        .where(Deadline.status == "pending")
        .order_by(Deadline.due_date)
    )
    deadlines = result.scalars().all()
    
    return {
        "deadlines": [
            {
                "id": dl.id,
                "case_id": dl.case_id,
                "description": dl.description,
                "due_date": dl.due_date.isoformat(),
                "days_until": (dl.due_date - datetime.now()).days,
                "legal_basis": dl.legal_basis
            }
            for dl in deadlines
        ]
    }

@app.post("/query")
async def query_documents(query: str, db: AsyncSession = Depends(get_db)):
    """Query the document database using AI"""
    try:
        # Use the agent to search statutes
        result = await agent.process_message(
            f"Wyszukaj przepisy związane z: {query}"
        )
        return {"query": query, "results": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Health check endpoint
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "database": "connected",
            "ai_agent": "initialized",
            "vector_db": "connected"
        }
    }
