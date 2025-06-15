from sqlalchemy import Column, String, DateTime, Text, JSON, ForeignKey, Integer, Boolean, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
import uuid

Base = declarative_base()

def generate_uuid():
    return str(uuid.uuid4())

class Case(Base):
    """Legal case/case tracking"""
    __tablename__ = "cases"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    case_number = Column(String, unique=True, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text)
    status = Column(String, default="active")  # active, closed, archived
    case_type = Column(String)  # litigation, contract, advisory
    
    # Client information
    client_name = Column(String, nullable=False)
    client_contact = Column(JSON)  # phone, email, address
    
    # Opposing party
    opposing_party = Column(String)
    opposing_party_contact = Column(JSON)
    
    # Court information
    court_name = Column(String)
    court_case_number = Column(String)
    judge_name = Column(String)
    
    # Financial
    amount_in_dispute = Column(Float)
    currency = Column(String, default="PLN")
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    closed_at = Column(DateTime)
    
    # Relationships
    documents = relationship("Document", back_populates="case")
    deadlines = relationship("Deadline", back_populates="case")
    notes = relationship("Note", back_populates="case")
    
class Document(Base):
    """Documents associated with cases"""
    __tablename__ = "documents"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    case_id = Column(String, ForeignKey("cases.id"))
    
    document_type = Column(String)  # pozew, odpowiedź, wyrok, umowa
    title = Column(String, nullable=False)
    file_path = Column(String)
    content = Column(Text)
    
    # Metadata
    document_metadata = Column(JSON)
    citations = Column(JSON)  # Extracted legal citations
    key_dates = Column(JSON)  # Important dates mentioned
    
    # Status
    status = Column(String, default="draft")  # draft, final, filed
    filed_date = Column(DateTime)
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    
    # Relationships
    case = relationship("Case", back_populates="documents")
    
class Deadline(Base):
    """Legal deadlines and reminders"""
    __tablename__ = "deadlines"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    case_id = Column(String, ForeignKey("cases.id"))
    
    deadline_type = Column(String)  # appeal, response, statute_of_limitations
    description = Column(Text)
    due_date = Column(DateTime, nullable=False)
    
    # Legal basis
    legal_basis = Column(String)  # e.g., "art. 369 KPC"
    is_court_deadline = Column(Boolean, default=True)
    is_extendable = Column(Boolean, default=False)
    
    # Status
    status = Column(String, default="pending")  # pending, completed, missed
    completed_at = Column(DateTime)
    
    # Reminder settings
    reminder_days_before = Column(Integer, default=7)
    reminder_sent = Column(Boolean, default=False)
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    
    # Relationships
    case = relationship("Case", back_populates="deadlines")
    
class Note(Base):
    """Case notes and activities"""
    __tablename__ = "notes"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    case_id = Column(String, ForeignKey("cases.id"))
    
    note_type = Column(String)  # meeting, phone_call, research, court_hearing
    subject = Column(String)
    content = Column(Text)
    
    # Activity tracking
    duration_minutes = Column(Integer)
    billable = Column(Boolean, default=True)
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    
    # Relationships
    case = relationship("Case", back_populates="notes")
    
class StatuteChunk(Base):
    """Chunked statute text for vector search"""
    __tablename__ = "statute_chunks"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    
    # Source information
    code = Column(String, nullable=False)  # KC, KPC
    article = Column(String, nullable=False)  # Article number
    paragraph = Column(String)  # Paragraph if applicable
    
    # Content
    text = Column(Text, nullable=False)
    embedding_id = Column(String)  # Reference to vector in Qdrant
    
    # Metadata
    effective_date = Column(DateTime)
    last_amendment = Column(DateTime)
    statute_metadata = Column(JSON)
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    
class Template(Base):
    """Document templates"""
    __tablename__ = "templates"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    
    template_type = Column(String, nullable=False)  # pozew, umowa, etc.
    name = Column(String, nullable=False)
    description = Column(Text)
    
    # Template content
    content = Column(Text, nullable=False)
    variables = Column(JSON)  # List of variables used in template
    
    # Usage tracking
    usage_count = Column(Integer, default=0)
    last_used = Column(DateTime)
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
