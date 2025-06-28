from sqlalchemy import Column, String, DateTime, Text, JSON, ForeignKey, Integer, Boolean, Float, ARRAY
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime, UTC
import uuid     
from typing import Optional, List, Dict, Any
from sqlmodel import SQLModel, Field, Relationship

def generate_uuid():
    return str(uuid.uuid4())

# --- Base Models (Single Source of Truth) ---

class CaseBase(SQLModel):
    case_number: str = Field(unique=True)
    title: str
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


# --- Table Models (for Database Interaction) ---

class Case(CaseBase, table=True):
    __tablename__ = "cases"
    id: Optional[str] = Field(default_factory=generate_uuid, primary_key=True)
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow, sa_column_kwargs={"onupdate": datetime.utcnow})
    closed_at: Optional[datetime] = Field(default=None)

    documents: List["Document"] = Relationship(back_populates="case")
    deadlines: List["Deadline"] = Relationship(back_populates="case")
    notes: List["Note"] = Relationship(back_populates="case")

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
