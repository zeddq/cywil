"""
Routes for case, document, and deadline management.
"""

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status

from ..auth import get_current_active_user
from ..models import Case, Document, User
from ..services.case_management_service import (
    CaseManagementService,
    get_case_management_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Case Management"])




@router.post("/cases", response_model=Case, status_code=status.HTTP_201_CREATED)
async def create_case(
    case: Case,
    case_service: CaseManagementService = Depends(get_case_management_service),
    user: User = Depends(get_current_active_user),
):
    """Create a new legal case"""
    return await case_service.create_case(case_in=case, user=user)


@router.get("/cases", response_model=List[Case])
async def list_cases(
    status: Optional[str] = None,
    case_service: CaseManagementService = Depends(get_case_management_service),
    user: User = Depends(get_current_active_user),
):
    """List all cases for the current user"""
    return await case_service.list_cases(user=user, status=status)


@router.get("/cases/{case_id}", response_model=Case)
async def get_case(
    case_id: UUID,
    case_service: CaseManagementService = Depends(get_case_management_service),
    user: User = Depends(get_current_active_user),
):
    """Get a specific case by ID"""
    case = await case_service.get_case(case_id=case_id, user=user)
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    return case


@router.put("/cases/{case_id}", response_model=Case)
async def update_case(
    case_id: UUID,
    case_update: Case,
    case_service: CaseManagementService = Depends(get_case_management_service),
    user: User = Depends(get_current_active_user),
):
    """Update a case"""
    case = await case_service.update_case(case_id=case_id, case_in=case_update, user=user)
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    return case


@router.delete("/cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_case(
    case_id: UUID,
    case_service: CaseManagementService = Depends(get_case_management_service),
    user: User = Depends(get_current_active_user),
):
    """Delete a case"""
    success = await case_service.delete_case(case_id=case_id, user=user)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")


@router.post("/documents", response_model=Document, status_code=status.HTTP_201_CREATED)
async def create_document(
    document: Document,
    case_service: CaseManagementService = Depends(get_case_management_service),
    user: User = Depends(get_current_active_user),
):
    """Create a new document"""
    new_doc = await case_service.create_document(doc_in=document, user=user)
    if not new_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Case not found for this user"
        )
    return new_doc


@router.get("/documents", response_model=List[Document])
async def list_documents(
    case_id: Optional[UUID] = None,
    case_service: CaseManagementService = Depends(get_case_management_service),
    user: User = Depends(get_current_active_user),
):
    """List documents, optionally filtered by case ID"""
    return await case_service.list_documents(user=user, case_id=case_id)


@router.post("/upload/{case_id}", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    case_id: UUID,
    file: UploadFile,
    case_service: CaseManagementService = Depends(get_case_management_service),
    user: User = Depends(get_current_active_user),
):
    """Upload a legal document for processing"""
    document = await case_service.upload_document(case_id=case_id, file=file, user=user)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Case not found for this user"
        )

    # In a real app, you might want to enqueue this for background processing.
    # For now, we'll just return the document.
    return {"filename": file.filename, "status": "uploaded", "document_id": document.id}
