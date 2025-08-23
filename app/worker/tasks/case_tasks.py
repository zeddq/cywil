"""
Celery tasks for case management operations.
"""
import asyncio
import logging
from typing import Dict, Any, List, Optional
from uuid import UUID
from datetime import datetime
import json

from app.worker.celery_app import celery_app
from app.core.database_manager import DatabaseManager
from app.core.config_service import ConfigService
from app.core.logger_manager import get_logger
from app.services.case_management_service import CaseManagementService
from app.models import Case, Document, CaseStatus

logger = get_logger(__name__)

def run_async(coro):
    """Helper to run async code in sync context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    name="worker.tasks.case_tasks.create_case",
    bind=True,
    max_retries=3,
    default_retry_delay=60
)
def create_case(self, case_data: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """
    Create a new case asynchronously.
    
    Args:
        case_data: Dictionary containing case information
        user_id: ID of the user creating the case
        
    Returns:
        Result dictionary with created case details
    """
    logger.info(f"Creating new case for user {user_id}")
    
    async def _process():
        config_service = ConfigService()
        db_manager = DatabaseManager(config_service)
        service = None
        
        try:
            await db_manager.initialize()
            service = CaseManagementService(db_manager)
            await service.initialize()
            
            # Create case object
            case = Case(**case_data)
            case.user_id = user_id
            case.created_at = datetime.utcnow()
            case.updated_at = datetime.utcnow()
            
            # Save to database
            async with db_manager.get_session() as session:
                session.add(case)
                await session.commit()
                await session.refresh(case)
            
            return {
                "status": "success",
                "case_id": str(case.id),
                "reference_number": case.reference_number,
                "title": case.title,
                "created_at": case.created_at.isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error creating case: {e}", exc_info=True)
            raise self.retry(exc=e)
        finally:
            if service:
                await service.shutdown()
            if db_manager:
                await db_manager.shutdown()
    
    return run_async(_process())


@celery_app.task(
    name="worker.tasks.case_tasks.update_case_status",
    bind=True,
    max_retries=3
)
def update_case_status(self, case_id: str, new_status: str, user_id: str) -> Dict[str, Any]:
    """
    Update the status of a case.
    
    Args:
        case_id: UUID of the case to update
        new_status: New status value
        user_id: ID of the user making the update
        
    Returns:
        Result dictionary with update status
    """
    logger.info(f"Updating case {case_id} status to {new_status}")
    
    async def _process():
        config_service = ConfigService()
        db_manager = DatabaseManager(config_service)
        
        try:
            await db_manager.initialize()
            
            async with db_manager.get_session() as session:
                # Fetch the case
                from sqlalchemy import select
                stmt = select(Case).where(
                    Case.id == case_id,
                    Case.user_id == user_id
                )
                result = await session.execute(stmt)
                case = result.scalar_one_or_none()
                
                if not case:
                    return {
                        "status": "error",
                        "error": f"Case {case_id} not found or access denied"
                    }
                
                # Update status
                old_status = case.status
                case.status = new_status
                case.updated_at = datetime.utcnow()
                
                await session.commit()
                
                return {
                    "status": "success",
                    "case_id": case_id,
                    "old_status": old_status,
                    "new_status": new_status,
                    "updated_at": case.updated_at.isoformat()
                }
                
        except Exception as e:
            logger.error(f"Error updating case status: {e}", exc_info=True)
            raise self.retry(exc=e)
        finally:
            if db_manager:
                await db_manager.shutdown()
    
    return run_async(_process())


@celery_app.task(
    name="worker.tasks.case_tasks.add_document_to_case",
    bind=True,
    max_retries=3
)
def add_document_to_case(
    self,
    case_id: str,
    document_data: Dict[str, Any],
    user_id: str
) -> Dict[str, Any]:
    """
    Add a document to a case.
    
    Args:
        case_id: UUID of the case
        document_data: Document information
        user_id: ID of the user adding the document
        
    Returns:
        Result dictionary with document details
    """
    logger.info(f"Adding document to case {case_id}")
    
    async def _process():
        config_service = ConfigService()
        db_manager = DatabaseManager(config_service)
        
        try:
            await db_manager.initialize()
            
            async with db_manager.get_session() as session:
                # Verify case exists and user has access
                from sqlalchemy import select
                stmt = select(Case).where(
                    Case.id == case_id,
                    Case.user_id == user_id
                )
                result = await session.execute(stmt)
                case = result.scalar_one_or_none()
                
                if not case:
                    return {
                        "status": "error",
                        "error": f"Case {case_id} not found or access denied"
                    }
                
                # Create document
                document = Document(**document_data)
                document.case_id = case_id
                document.uploaded_by = user_id
                document.created_at = datetime.utcnow()
                document.updated_at = datetime.utcnow()
                
                session.add(document)
                await session.commit()
                await session.refresh(document)
                
                return {
                    "status": "success",
                    "document_id": str(document.id),
                    "case_id": case_id,
                    "document_type": document.document_type,
                    "created_at": document.created_at.isoformat()
                }
                
        except Exception as e:
            logger.error(f"Error adding document to case: {e}", exc_info=True)
            raise self.retry(exc=e)
        finally:
            if db_manager:
                await db_manager.shutdown()
    
    return run_async(_process())


@celery_app.task(
    name="worker.tasks.case_tasks.search_cases",
    bind=True
)
def search_cases(
    self,
    query: str,
    user_id: str,
    filters: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Search cases based on query and filters.
    
    Args:
        query: Search query string
        user_id: ID of the user performing search
        filters: Optional filters (status, date_range, etc.)
        
    Returns:
        Search results with matching cases
    """
    logger.info(f"Searching cases for user {user_id} with query: {query}")
    
    async def _process():
        config_service = ConfigService()
        db_manager = DatabaseManager(config_service)
        
        try:
            await db_manager.initialize()
            
            async with db_manager.get_session() as session:
                from sqlalchemy import select, or_, and_
                
                # Base query
                stmt = select(Case).where(Case.user_id == user_id)
                
                # Add text search
                if query:
                    stmt = stmt.where(
                        or_(
                            Case.title.ilike(f"%{query}%"),
                            Case.description.ilike(f"%{query}%"),
                            Case.reference_number.ilike(f"%{query}%"),
                            Case.client_name.ilike(f"%{query}%")
                        )
                    )
                
                # Apply filters
                if filters:
                    if "status" in filters:
                        stmt = stmt.where(Case.status == filters["status"])
                    if "case_type" in filters:
                        stmt = stmt.where(Case.case_type == filters["case_type"])
                    if "date_from" in filters:
                        stmt = stmt.where(Case.created_at >= filters["date_from"])
                    if "date_to" in filters:
                        stmt = stmt.where(Case.created_at <= filters["date_to"])
                
                result = await session.execute(stmt)
                cases = result.scalars().all()
                
                return {
                    "status": "success",
                    "query": query,
                    "count": len(cases),
                    "cases": [
                        {
                            "id": str(case.id),
                            "reference_number": case.reference_number,
                            "title": case.title,
                            "status": case.status,
                            "case_type": case.case_type,
                            "client_name": case.client_name,
                            "created_at": case.created_at.isoformat()
                        }
                        for case in cases
                    ]
                }
                
        except Exception as e:
            logger.error(f"Error searching cases: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e)
            }
        finally:
            if db_manager:
                await db_manager.shutdown()
    
    return run_async(_process())


@celery_app.task(
    name="worker.tasks.case_tasks.calculate_case_deadlines",
    bind=True
)
def calculate_case_deadlines(self, case_id: str, user_id: str) -> Dict[str, Any]:
    """
    Calculate legal deadlines for a case based on its type and events.
    
    Args:
        case_id: UUID of the case
        user_id: ID of the user
        
    Returns:
        Dictionary with calculated deadlines
    """
    logger.info(f"Calculating deadlines for case {case_id}")
    
    async def _process():
        config_service = ConfigService()
        db_manager = DatabaseManager(config_service)
        
        try:
            await db_manager.initialize()
            
            async with db_manager.get_session() as session:
                from sqlalchemy import select
                stmt = select(Case).where(
                    Case.id == case_id,
                    Case.user_id == user_id
                )
                result = await session.execute(stmt)
                case = result.scalar_one_or_none()
                
                if not case:
                    return {
                        "status": "error",
                        "error": f"Case {case_id} not found"
                    }
                
                # Calculate deadlines based on case type
                deadlines = []
                from datetime import timedelta
                
                if case.case_type == "civil":
                    # Civil case deadlines
                    deadlines.extend([
                        {
                            "name": "Response filing deadline",
                            "date": (case.created_at + timedelta(days=30)).isoformat(),
                            "description": "Deadline to file response to complaint"
                        },
                        {
                            "name": "Discovery deadline",
                            "date": (case.created_at + timedelta(days=90)).isoformat(),
                            "description": "Deadline to complete discovery"
                        }
                    ])
                elif case.case_type == "criminal":
                    # Criminal case deadlines
                    deadlines.extend([
                        {
                            "name": "Arraignment",
                            "date": (case.created_at + timedelta(days=14)).isoformat(),
                            "description": "Arraignment hearing date"
                        },
                        {
                            "name": "Preliminary hearing",
                            "date": (case.created_at + timedelta(days=30)).isoformat(),
                            "description": "Preliminary hearing date"
                        }
                    ])
                
                return {
                    "status": "success",
                    "case_id": case_id,
                    "case_type": case.case_type,
                    "deadlines": deadlines
                }
                
        except Exception as e:
            logger.error(f"Error calculating deadlines: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e)
            }
        finally:
            if db_manager:
                await db_manager.shutdown()
    
    return run_async(_process())


@celery_app.task(
    name="worker.tasks.case_tasks.generate_case_summary",
    bind=True
)
def generate_case_summary(self, case_id: str, user_id: str) -> Dict[str, Any]:
    """
    Generate a comprehensive summary of a case including all documents and events.
    
    Args:
        case_id: UUID of the case
        user_id: ID of the user
        
    Returns:
        Comprehensive case summary
    """
    logger.info(f"Generating summary for case {case_id}")
    
    async def _process():
        config_service = ConfigService()
        db_manager = DatabaseManager(config_service)
        
        try:
            await db_manager.initialize()
            
            async with db_manager.get_session() as session:
                from sqlalchemy import select
                from sqlalchemy.orm import selectinload
                
                # Fetch case with related data
                stmt = select(Case).where(
                    Case.id == case_id,
                    Case.user_id == user_id
                ).options(selectinload(Case.documents))
                
                result = await session.execute(stmt)
                case = result.scalar_one_or_none()
                
                if not case:
                    return {
                        "status": "error",
                        "error": f"Case {case_id} not found"
                    }
                
                # Generate summary
                summary = {
                    "status": "success",
                    "case": {
                        "id": str(case.id),
                        "reference_number": case.reference_number,
                        "title": case.title,
                        "description": case.description,
                        "status": case.status,
                        "case_type": case.case_type,
                        "client_name": case.client_name,
                        "client_contact": case.client_contact,
                        "opposing_party": case.opposing_party,
                        "court_name": case.court_name,
                        "court_case_number": case.court_case_number,
                        "created_at": case.created_at.isoformat(),
                        "updated_at": case.updated_at.isoformat(),
                        "documents_count": len(case.documents) if hasattr(case, 'documents') else 0,
                        "documents": [
                            {
                                "id": str(doc.id),
                                "document_type": doc.document_type,
                                "file_name": doc.file_name,
                                "created_at": doc.created_at.isoformat()
                            }
                            for doc in (case.documents if hasattr(case, 'documents') else [])
                        ]
                    }
                }
                
                return summary
                
        except Exception as e:
            logger.error(f"Error generating case summary: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e)
            }
        finally:
            if db_manager:
                await db_manager.shutdown()
    
    return run_async(_process())