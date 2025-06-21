from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from typing import List, Optional, Dict, Any, Type
from pydantic import BaseModel, create_model
from datetime import datetime, timedelta
import os
from .orchestrator import ParalegalAgent
from .database import get_db, init_db
from .models import Case, CaseBase, Document, DocumentBase, Deadline, DeadlineBase, Note
from .config import settings
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
import json
import logging
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Paralegal API", version="1.0.0")

# --- Model Factory ---
def make_optional(model: Type[BaseModel]) -> Type[BaseModel]:
    """
    Dynamically creates a new Pydantic model from an existing one,
    making all fields optional and providing a default of None.
    """
    fields = {
        name: (Optional[field.annotation], None)
        for name, field in model.model_fields.items()
    }
    return create_model(f"Optional{model.__name__}", **fields)


# Initialize agent
agent = ParalegalAgent()

# OAuth2 scheme for authentication (simplified for POC)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Pydantic models for request/response
class ChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    thread_id: str
    status: str

# --- API Models ---

# Case Models
class CaseCreate(CaseBase):
    pass

CaseUpdate = make_optional(CaseBase)

# Document Models
class DocumentCreate(DocumentBase):
    case_id: str

DocumentUpdate = make_optional(DocumentBase)

# Deadline Models
class DeadlineCreate(DeadlineBase):
    case_id: str

# --- CORS MIDDLEWARE ---
# This is needed to allow the frontend (running on localhost:3000)
# to communicate with the backend (running on localhost:8000)
origins = [
    "http://localhost",
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    """Initialize database on startup"""
    await init_db()

@app.get("/")
async def root():
    logger.info("Request to root endpoint /")
    response = {
        "message": "AI Paralegal API is running",
        "version": "1.0.0",
        "status": "operational"
    }
    logger.info(f"Root endpoint returning: {response}")
    return response

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, db: AsyncSession = Depends(get_db)):
    """
    Main chat endpoint for interacting with the AI paralegal
    """
    logger.info(f"Chat request received: {request.model_dump_json()}")
    try:
        result = await agent.process_message(request.message, request.thread_id)
        logger.info(f"Result from agent: {result}")

        if result["status"] == "success":
            await agent.save_ai_interaction({
                "last_query": request.message,
                "last_response": result["response"],
                "thread_id": result["thread_id"],
                "timestamp": datetime.now().isoformat()
            })
        
        response = ChatResponse(**result)
        logger.info(f"Chat request returning: {response.model_dump_json()}")
        return response
    
    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    case_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Upload a legal document for processing"""
    logger.info(f"Upload document request received. Filename: '{file.filename}', Case ID: {case_id}")
    os.makedirs(settings.upload_dir, exist_ok=True)
    
    file_path = os.path.join(settings.upload_dir, file.filename)
    with open(file_path, "wb+") as file_object:
        content = await file.read()
        file_object.write(content)
    
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
        
        response = {
            "filename": file.filename,
            "status": "uploaded",
            "document_id": document.id,
            "case_id": case_id
        }
        logger.info(f"Upload document returning: {response}")
        return response
    
    response = {"filename": file.filename, "status": "uploaded"}
    logger.info(f"Upload document returning: {response}")
    return response

@app.post("/cases", response_model=Case)
async def create_case(case: CaseCreate, db: AsyncSession = Depends(get_db)):
    """Create a new legal case"""
    logger.info(f"Create case request received: {case.model_dump_json()}")
    
    db_case = Case.model_validate(case)
    try:
        db.add(db_case)
        await db.commit()
        await db.refresh(db_case)
        logger.info(f"Created case: {db_case.id}")
        return db_case
    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating case: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/cases/{case_id}", response_model=Case)
async def update_case(case_id: str, case_update: CaseUpdate, db: AsyncSession = Depends(get_db)):
    """Update an existing legal case"""
    logger.info(f"Update case request received for case_id: {case_id} with data: {case_update.model_dump_json()}")
    db_case = await db.get(Case, case_id)
    if not db_case:
        logger.warning(f"Update case failed: case with id {case_id} not found.")
        raise HTTPException(status_code=404, detail="Case not found")

    update_data = case_update.model_dump()
    for key, value in update_data.items():
        setattr(db_case, key, value)

    try:
        db.add(db_case)
        await db.commit()
        await db.refresh(db_case)
        logger.info(f"Updated case: {db_case.id}")
        return db_case
    except Exception as e:
        await db.rollback()
        logger.error(f"Error updating case {case_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/cases")
async def list_cases(
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
) -> List[Case]:
    """List all cases with optional filtering"""
    logger.info(f"List cases request received with status: {status}")
    query = select(Case)
    if status:
        query = query.where(Case.status == status)
    
    result = await db.execute(query)
    cases = result.scalars().all()
    logger.info(f"List cases returning {len(cases)} cases.")
    return cases

@app.get("/cases/{case_id}")
async def get_case(case_id: str, db: AsyncSession = Depends(get_db)) -> Case:
    """Get detailed information about a specific case"""
    logger.info(f"Get case request received for case_id: {case_id}")
    case = await db.get(Case, case_id)
    if not case:
        logger.warning(f"Get case failed: case with id {case_id} not found.")
        raise HTTPException(status_code=404, detail="Case not found")
    
    logger.info(f"Get case returning case: {case.id}")
    return case

@app.delete("/cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_case(case_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a case and all its associated data"""
    logger.info(f"Delete case request received for case_id: {case_id}")
    case = await db.get(Case, case_id)
    if not case:
        logger.warning(f"Delete case failed: case with id {case_id} not found.")
        raise HTTPException(status_code=404, detail="Case not found")

    try:
        await db.execute(delete(Note).where(Note.case_id == case_id))
        await db.execute(delete(Deadline).where(Deadline.case_id == case_id))
        await db.execute(delete(Document).where(Document.case_id == case_id))
        
        await db.delete(case)
        await db.commit()
        logger.info(f"Delete case successful for case_id: {case_id}")
    except Exception as e:
        await db.rollback()
        logger.error(f"Error deleting case {case_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error deleting case: {e}")

@app.post("/documents", response_model=Document)
async def create_document(document: DocumentCreate, db: AsyncSession = Depends(get_db)):
    """Create a new document"""
    logger.info(f"Create document request received: {document.model_dump_json()}")
    db_document = Document.model_validate(document)
    db.add(db_document)
    await db.commit()
    await db.refresh(db_document)
    logger.info(f"Create document returning: {db_document.id}")
    return db_document

@app.put("/documents/{document_id}", response_model=Document)
async def update_document(document_id: str, doc_update: DocumentUpdate, db: AsyncSession = Depends(get_db)):
    """Update an existing document"""
    logger.info(f"Update document request received for document_id: {document_id} with data: {doc_update.model_dump_json(exclude_unset=True)}")
    db_doc = await db.get(Document, document_id)
    if not db_doc:
        logger.warning(f"Update document failed: document with id {document_id} not found.")
        raise HTTPException(status_code=404, detail="Document not found")

    update_data = doc_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_doc, key, value)

    db.add(db_doc)
    await db.commit()
    await db.refresh(db_doc)
    logger.info(f"Updated document: {db_doc.id}")
    return db_doc

@app.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a document by its ID"""
    logger.info(f"Delete document request received for document_id: {document_id}")
    doc = await db.get(Document, document_id)
    if not doc:
        logger.warning(f"Delete document failed: document with id {document_id} not found.")
        raise HTTPException(status_code=404, detail="Document not found")
    
    try:
        await db.delete(doc)
        await db.commit()
        logger.info(f"Delete document successful for document_id: {document_id}")
    except Exception as e:
        await db.rollback()
        logger.error(f"Error deleting document {document_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error deleting document: {e}")

@app.get("/documents")
async def list_documents(case_id: Optional[str] = None, db: AsyncSession = Depends(get_db)) -> List[Document]:
    """List all documents, optionally filtered by case_id"""
    logger.info(f"List documents request received with case_id: {case_id}")
    query = select(Document)
    if case_id:
        query = query.where(Document.case_id == case_id)

    result = await db.execute(query)
    documents = result.scalars().all()

    logger.info(f"List documents returning {len(documents)} documents.")
    return documents

@app.post("/deadlines", response_model=Deadline)
async def create_deadline(deadline: DeadlineCreate, db: AsyncSession = Depends(get_db)):
    """Create a new deadline"""
    logger.info(f"Create deadline request received: {deadline.model_dump_json()}")
    db_deadline = Deadline.model_validate(deadline)
    db.add(db_deadline)
    await db.commit()
    await db.refresh(db_deadline)
    
    if deadline.reminder_days_before > 0:
        reminder_date = deadline.due_date - timedelta(days=deadline.reminder_days_before)
        await agent.schedule_reminder(
            case_id=deadline.case_id,
            reminder_date=reminder_date.isoformat(),
            note=f"Reminder: {deadline.description} - Due: {deadline.due_date}"
        )
    
    logger.info(f"Create deadline returning: {db_deadline.id}")
    return db_deadline

@app.get("/deadlines/upcoming")
async def get_upcoming_deadlines(
    days: int = 30,
    db: AsyncSession = Depends(get_db)
) -> List[Deadline]:
    """Get upcoming deadlines within specified days"""
    logger.info(f"Get upcoming deadlines request received with days: {days}")
    cutoff_date = datetime.now() + timedelta(days=days)
    
    result = await db.execute(
        select(Deadline)
        .where(Deadline.due_date <= cutoff_date)
        .where(Deadline.status == "pending")
        .order_by(Deadline.due_date)
    )
    deadlines = result.scalars().all()
    
    logger.info(f"Get upcoming deadlines returning {len(deadlines)} deadlines.")
    return deadlines

@app.post("/query")
async def query_documents(query: str, db: AsyncSession = Depends(get_db)):
    """Query the document database using AI"""
    logger.info(f"Query documents request received with query: '{query}'")
    try:
        result = await agent.process_message(
            f"Wyszukaj przepisy związane z: {query}"
        )
        response = {"query": query, "results": result}
        logger.info(f"Query documents returning result for query: '{query}'")
        return response
    except Exception as e:
        logger.error(f"Error in query_documents endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    logger.info("Health check request received")
    response = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "database": "connected",
            "ai_agent": "initialized",
            "vector_db": "connected"
        }
    }
    logger.info(f"Health check returning: {response}")
    return response
