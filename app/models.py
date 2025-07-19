from sqlalchemy import Column, JSON
from datetime import datetime
import uuid     
from typing import Optional, List, Dict, Any, Literal
from sqlmodel import SQLModel, Field, Relationship
from enum import Enum
from pydantic import BaseModel
from typing_extensions import TypedDict
from .core.database_manager import DatabaseManager

def generate_uuid():
    return str(uuid.uuid4())

# --- Base Models (Single Source of Truth) ---

class CaseBase(SQLModel):
    reference_number: str = Field(unique=True)
    description: Optional[str] = Field(default=None)
    status: str = Field(default="active")
    case_type: Optional[str] = Field(default=None)
    client_name: str
    client_contact: Dict[str, Any] = Field(default={}, sa_column=Column(JSON))
    opposing_party: Optional[str] = Field(default=None)
    opposing_party_contact: Optional[Dict[str, Any]] = Field(default={}, sa_column=Column(JSON))
    court_name: Optional[str] = Field(default=None)
    court_case_number: Optional[str] = Field(default=None)
    judge_name: Optional[str] = Field(default=None)
    amount_in_dispute: Optional[float] = Field(default=None)
    currency: str = Field(default="PLN")

class DocumentBase(SQLModel):
    document_type: str
    title: str
    file_path: Optional[str] = Field(default=None)
    content: Optional[str] = Field(default=None)
    document_metadata: Dict[str, Any] = Field(default={}, sa_column=Column(JSON))
    citations: List[str] = Field(default=[], sa_column=Column(JSON))
    key_dates: List[str] = Field(default=[], sa_column=Column(JSON))
    status: str = Field(default="draft")
    filed_date: Optional[datetime] = Field(default=None)

class DeadlineBase(SQLModel):
    deadline_type: str
    description: Optional[str] = Field(default=None)
    due_date: datetime
    legal_basis: Optional[str] = Field(default=None)
    is_court_deadline: bool = Field(default=True)
    is_extendable: bool = Field(default=False)
    status: str = Field(default="pending")
    completed_at: Optional[datetime] = Field(default=None)
    reminder_days_before: int = Field(default=7)
    reminder_sent: bool = Field(default=False)

class NoteBase(SQLModel):
    note_type: str
    subject: Optional[str] = Field(default=None)
    content: str
    duration_minutes: Optional[int] = Field(default=None)
    billable: bool = Field(default=True)

class FormTemplateBase(SQLModel):
    category: str
    name: str
    summary: Optional[str] = Field(default=None)
    content: str
    variables: List[str] = Field(default=[], sa_column=Column(JSON)) # This fixes the error
    usage_count: int = Field(default=0)
    last_used: Optional[datetime] = Field(default=None)
    qdrant_id: str = Field(unique=True)

class ResponseHistoryBase(SQLModel):
    thread_id: str
    response_id: str
    input: Dict[str, Any] = Field(default={}, sa_column=Column(JSON))
    output: Dict[str, Any] = Field(default={}, sa_column=Column(JSON))
    previous_response_id: Optional[str] = Field(default=None)

class LegalEntity(TypedDict):
    text: str 
    label: Literal["ORG", "PERSON", "LOC", "DATE", "MNY", "OTH", "LAW_REF", "DOCKET"]
    start: int
    end: int

class RulingMetadata(TypedDict):
    docket: Optional[str]
    date: Optional[str]
    panel: Optional[List[str]]

class RulingParagraph(TypedDict):
    section: Literal["header", "legal_question", "reasoning", "disposition", "body"]
    para_no: int
    text: str
    entities: List[LegalEntity]

class SNRulingBase(SQLModel):
    name: str = Field(description="Ruling name", unique=True, default_factory=generate_uuid)
    qdrant_id: str = Field(description="Qdrant ID", unique=True, default_factory=generate_uuid)
    meta: RulingMetadata = Field(sa_column=Column(JSON), default={})
    paragraphs: List["RulingParagraph"] = Field(description="List of paragraphs", default=[], sa_column=Column(JSON))


# --- Table Models (for Database Interaction) ---

class ResponseHistory(ResponseHistoryBase, table=True):
    __tablename__ = "response_history"
    id: Optional[str] = Field(default_factory=generate_uuid, primary_key=True)
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow, sa_column_kwargs={"onupdate": datetime.utcnow})

class Case(CaseBase, table=True):
    __tablename__ = "cases"
    id: Optional[str] = Field(default_factory=generate_uuid, primary_key=True)
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow, sa_column_kwargs={"onupdate": datetime.utcnow})
    closed_at: Optional[datetime] = Field(default=None)
    created_by_id: Optional[str] = Field(default=None, foreign_key="users.id")

    documents: List["Document"] = Relationship(back_populates="case")
    deadlines: List["Deadline"] = Relationship(back_populates="case")
    notes: List["Note"] = Relationship(back_populates="case")
    created_by_user: Optional["User"] = Relationship(back_populates="created_cases")

class Document(DocumentBase, table=True):
    __tablename__ = "documents"
    id: Optional[str] = Field(default_factory=generate_uuid, primary_key=True)
    case_id: str = Field(foreign_key="cases.id")
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow, sa_column_kwargs={"onupdate": datetime.utcnow})

    case: Case = Relationship(back_populates="documents")

class Deadline(DeadlineBase, table=True):
    __tablename__ = "deadlines"
    id: Optional[str] = Field(default_factory=generate_uuid, primary_key=True)
    case_id: str = Field(foreign_key="cases.id")
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow, sa_column_kwargs={"onupdate": datetime.utcnow})

    case: Case = Relationship(back_populates="deadlines")

class Note(NoteBase, table=True):
    __tablename__ = "notes"
    id: Optional[str] = Field(default_factory=generate_uuid, primary_key=True)
    case_id: Optional[str] = Field(foreign_key="cases.id", default=None)
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow, sa_column_kwargs={"onupdate": datetime.utcnow})

    case: Optional[Case] = Relationship(back_populates="notes")

class StatuteChunk(SQLModel, table=True):
    __tablename__ = "statute_chunks"
    id: Optional[str] = Field(default_factory=generate_uuid, primary_key=True)
    code: str
    article: str
    paragraph: Optional[str] = Field(default=None)
    text: str
    embedding_id: Optional[str] = Field(default=None)
    effective_date: Optional[datetime] = Field(default=None)
    last_amendment: Optional[datetime] = Field(default=None)
    statute_metadata: Dict[str, Any] = Field(default={}, sa_column=Column(JSON))
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow, sa_column_kwargs={"onupdate": datetime.utcnow})

class FormTemplate(FormTemplateBase, table=True):
    __tablename__ = "form_templates"
    id: Optional[str] = Field(default_factory=generate_uuid, primary_key=True)
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow, sa_column_kwargs={"onupdate": datetime.utcnow})

class SNRuling(SNRulingBase, table=True):
    __tablename__ = "sn_rulings"
    id: Optional[str] = Field(default_factory=generate_uuid, primary_key=True)
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow, sa_column_kwargs={"onupdate": datetime.utcnow})

# --- User Authentication Models ---

class UserRole(str, Enum):
    admin = "admin"
    lawyer = "lawyer"
    paralegal = "paralegal"
    client = "client"

class UserBase(SQLModel):
    email: str = Field(unique=True, index=True)
    full_name: str
    role: UserRole = Field(default=UserRole.client)
    is_active: bool = Field(default=True)
    is_verified: bool = Field(default=False)

class User(UserBase, table=True):
    __tablename__ = "users"
    id: Optional[str] = Field(default_factory=generate_uuid, primary_key=True)
    hashed_password: str
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow, sa_column_kwargs={"onupdate": datetime.utcnow})
    last_login: Optional[datetime] = Field(default=None)
    
    # Relationships
    sessions: List["UserSession"] = Relationship(back_populates="user")
    created_cases: List["Case"] = Relationship(back_populates="created_by_user")

class UserSession(SQLModel, table=True):
    __tablename__ = "user_sessions"
    id: Optional[str] = Field(default_factory=generate_uuid, primary_key=True)
    user_id: str = Field(foreign_key="users.id")
    token: str = Field(unique=True, index=True)
    expires_at: datetime
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    
    user: User = Relationship(back_populates="sessions")

# Pydantic models for request/response
class ChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None
    
class ToolResult(BaseModel):
    name: str
    status: str
    call_id: str

class ChatResponse(BaseModel):
    response: str
    thread_id: str
    status: str
    tool_results: List[ToolResult]

def init_db(db_manager: DatabaseManager):
    """Initialize the database"""
    SQLModel.metadata.create_all(db_manager.sync_engine)
