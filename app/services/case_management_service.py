from typing import List, Optional, Annotated, Dict, Any
from uuid import UUID
from fastapi import UploadFile, Request, Depends
import os
import logging
from datetime import datetime, timedelta

from ..models import Case, Document, User
from ..core.config_service import get_config
from ..core.service_interface import ServiceInterface, ServiceStatus, HealthCheckResult
from ..repositories.case_repository import CaseRepositoryDep
from ..core.tool_registry import tool_registry, ToolCategory, ToolParameter

logger = logging.getLogger(__name__)

settings = get_config()

class CaseManagementService(ServiceInterface):
    def __init__(self):
        super().__init__("CaseManagementService")

    def with_case_repository(self, case_repository: CaseRepositoryDep) -> "CaseManagementService":
        self.case_repository = case_repository
        return self
    
    async def _shutdown_impl(self):
        pass

    async def _health_check_impl(self) -> HealthCheckResult:
        return HealthCheckResult(status=ServiceStatus.HEALTHY, message="CaseManagementService is healthy")

    async def _initialize_impl(self):
        self._initialized = True

    async def create_case(self, case_in: Case, user: User) -> Case:
        return await self.case_repository.create_case(case_in=case_in, user_id=user.id)

    async def list_cases(self, user: User, status: Optional[str] = None) -> List[Case]:
        return await self.case_repository.list_cases(user_id=user.id, status=status)

    async def get_case(self, case_id: UUID, user: User) -> Optional[Case]:
        return await self.case_repository.get_case(case_id=case_id, user_id=user.id)
    
    @tool_registry.register(
        name="describe_case",
        description="Retrieve and describe a specific case by its ID, providing key details",
        category=ToolCategory.CASE_MANAGEMENT,
        parameters=[
            ToolParameter("case_id", "string", "The UUID of the case to describe"),
        ],
        returns="Detailed description of the case, or an error if not found"
    )
    async def describe_case(self, case_id: UUID) -> Dict[str, Any]:
        """Describe case without user context for tool usage"""
        # For tool usage, we need to handle this differently since tools don't have user context
        # In a real application, this would need proper authentication/authorization
        from sqlalchemy import select
        from ..database import DatabaseManager
        
        db_manager = DatabaseManager()
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(Case).where(Case.id == case_id)
            )
            case = result.scalar_one_or_none()
            
        if not case:
            logger.warning(f"Case with ID {case_id} not found.")
            return {"error": f"Case with ID {case_id} not found."}
        
        return {
            "case_id": str(case.id),
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
            "created_at": case.created_at.isoformat() if case.created_at else None,
            "updated_at": case.updated_at.isoformat() if case.updated_at else None,
        }

    # @tool_registry.register(
    #     name="update_case",
    #     description="Update details of an existing case. Provide only the fields you wish to change",
    #     category=ToolCategory.CASE_MANAGEMENT,
    #     parameters=[
    #         ToolParameter("case_id", "string", "The UUID of the case to update"),
    #         ToolParameter("title", "string", "New title for the case", False),
    #         ToolParameter("description", "string", "New description for the case", False),
    #         ToolParameter("status", "string", "New status for the case", False),
    #         ToolParameter("case_type", "string", "New case type", False),
    #         ToolParameter("client_name", "string", "New client name", False),
    #         ToolParameter("client_contact", "string", "New client contact", False),
    #         ToolParameter("opposing_party", "string", "New opposing party", False),
    #         ToolParameter("court_name", "string", "New court name", False),
    #         ToolParameter("court_case_number", "string", "New court case number", False),
    #     ],
    #     returns="Updated case details or error if not found"
    # )
    # async def update_case(self, case_id: UUID, user: Optional[User] = None, **kwargs) -> Dict[str, Any]:
    #     """Update case with flexible parameters for tool usage"""
    #     # Handle both user-context and tool-context calls
    #     if user:
    #         case = await self.get_case(case_id=case_id, user=user)
    #     else:
    #         # Tool context - direct DB access
    #         from sqlalchemy import select
    #         from ..database import DatabaseManager
            
    #         db_manager = DatabaseManager()
    #         async with db_manager.get_session() as session:
    #             result = await session.execute(
    #                 select(Case).where(Case.id == case_id)
    #             )
    #             case = result.scalar_one_or_none()
                
    #             if not case:
    #                 logger.warning(f"Attempted to update non-existent case {case_id}")
    #                 return {"error": f"Case with ID {case_id} not found"}
                
    #             # Update fields
    #             for field, value in kwargs.items():
    #                 if value is not None and hasattr(case, field):
    #                     setattr(case, field, value)
                
    #             case.updated_at = datetime.now()
    #             await session.commit()
    #             await session.refresh(case)
                
    #             return {
    #                 "case_id": str(case.id),
    #                 "reference_number": case.reference_number,
    #                 "title": case.title,
    #                 "description": case.description,
    #                 "status": case.status,
    #                 "updated_at": case.updated_at.isoformat(),
    #                 "message": "Case updated successfully"
    #             }
    
    # # Keep original method for API usage
    # async def update_case_api(self, case_id: UUID, case_in: Case, user: User) -> Optional[Case]:
    #     case = await self.get_case(case_id=case_id, user=user)
    #     if not case:
    #         return None
    #     return await self.case_repository.update_case(case=case, case_in=case_in)

    async def delete_case(self, case_id: UUID, user: User) -> bool:
        case = await self.get_case(case_id=case_id, user=user)
        if not case:
            return False
        await self.case_repository.delete_case(case=case)
        return True

    async def create_document(self, doc_in: Document, user: User) -> Optional[Document]:
        # Verify case belongs to user
        case = await self.get_case(case_id=doc_in.case_id, user=user)
        if not case:
            return None
        return await self.case_repository.create_document(doc_in=doc_in)

    async def list_documents(self, user: User, case_id: Optional[UUID] = None) -> List[Document]:
        return await self.case_repository.list_documents(user_id=user.id, case_id=case_id)

    async def upload_document(self, case_id: UUID, file: UploadFile, user: User) -> Optional[Document]:
        case = await self.get_case(case_id=case_id, user=user)
        if not case:
            return None
            
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        
        file_path = os.path.join(settings.UPLOAD_DIR, file.filename)
        content = await file.read()
        with open(file_path, "wb+") as file_object:
            file_object.write(content)
            
        doc_in = Document(
            case_id=case_id,
            document_type="uploaded",
            title=file.filename,
            file_path=file_path,
            metadata={"original_filename": file.filename, "size": len(content)}
        )
        return await self.case_repository.create_document(doc_in=doc_in)
    
    @tool_registry.register(
        name="schedule_reminder",
        description="Schedule a reminder for a specific case at a given time",
        category=ToolCategory.CASE_MANAGEMENT,
        parameters=[
            ToolParameter("case_id", "string", "The UUID of the case for which to schedule a reminder"),
            ToolParameter("reminder_date", "string", "The date/time for the reminder in ISO format"),
            ToolParameter("note", "string", "The text content of the reminder"),
        ],
        returns="Confirmation of reminder scheduling"
    )
    async def schedule_reminder(self, case_id: UUID, reminder_date: str, note: str) -> Dict[str, Any]:
        """Schedule a reminder for a case - tool version without user context"""
        # Validate case exists
        from sqlalchemy import select
        from ..database import DatabaseManager
        
        db_manager = DatabaseManager()
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(Case).where(Case.id == case_id)
            )
            case = result.scalar_one_or_none()
            
        if not case:
            logger.warning(f"Attempted to schedule reminder for non-existent case {case_id}")
            return {"status": "error", "message": f"Case with ID {case_id} not found"}
        
        try:
            parsed_time = datetime.fromisoformat(reminder_date)
        except ValueError:
            return {"status": "error", "message": "Invalid reminder_date format. Use ISO format"}
        
        # In a real application, this would persist the reminder
        # For POC, we'll just log it and return success
        reminder_id = f"rem_{case_id}_{datetime.now().timestamp()}"
        logger.info(f"Reminder scheduled for case {case_id} at {parsed_time}: '{note}'")
        
        return {
            "reminder_id": reminder_id,
            "case_id": str(case_id),
            "scheduled_for": parsed_time.isoformat(),
            "note": note,
            "created_at": datetime.now().isoformat(),
            "status": "scheduled"
        }
    
    @tool_registry.register(
        name="compute_deadline",
        description="Calculate legal deadlines based on event type and date",
        category=ToolCategory.CASE_MANAGEMENT,
        parameters=[
            ToolParameter("event_type", "string", "Type of legal event", enum=["payment", "appeal", "complaint", "response_to_claim", "cassation"]),
            ToolParameter("event_date", "string", "Date of the event in ISO format"),
        ],
        returns="Computed deadline with details"
    )
    async def compute_deadline(self, event_type: str, event_date: str) -> Dict[str, Any]:
        """Compute legal deadline based on Polish civil procedure rules"""
        deadlines = {
            "payment": {
                "days": 3 * 365,  # 3 years for general claims
                "description": "Termin przedawnienia roszczenia (art. 118 KC)",
                "is_business_days": False
            },
            "appeal": {
                "days": 14,  # 14 days
                "description": "Termin na wniesienie apelacji (art. 369 KPC)",
                "is_business_days": True
            },
            "complaint": {
                "days": 7,  # 7 days
                "description": "Termin na wniesienie zażalenia (art. 394 § 2 KPC)",
                "is_business_days": True
            },
            "response_to_claim": {
                "days": 14,  # 14 days in summary proceedings
                "description": "Termin na sprzeciw od nakazu zapłaty (art. 505³ KPC)",
                "is_business_days": True
            },
            "cassation": {
                "days": 60,  # 2 months
                "description": "Termin na wniesienie skargi kasacyjnej (art. 398⁵ KPC)",
                "is_business_days": True
            }
        }
        
        # Get deadline info
        deadline_info = deadlines.get(event_type)
        if not deadline_info:
            return {"error": f"Unknown event type: {event_type}. Valid types: {list(deadlines.keys())}"}
        
        try:
            # Parse event date
            event_datetime = datetime.fromisoformat(event_date)
        except ValueError:
            return {"error": "Invalid event_date format. Use ISO format"}
        
        # Calculate deadline date
        deadline_days = deadline_info["days"]
        deadline_date = event_datetime
        
        if deadline_info["is_business_days"]:
            # Add business days
            days_added = 0
            while days_added < deadline_days:
                deadline_date += timedelta(days=1)
                # Skip weekends
                if deadline_date.weekday() < 5:  # Monday-Friday
                    days_added += 1
        else:
            # Add calendar days
            deadline_date = event_datetime + timedelta(days=deadline_days)
        
        return {
            "event_type": event_type,
            "event_date": event_date,
            "deadline_date": deadline_date.isoformat(),
            "days_until_deadline": deadline_days,
            "description": deadline_info["description"],
            "is_business_days": deadline_info["is_business_days"]
        } 

def get_case_management_service(request: Request, case_repository: CaseRepositoryDep) -> CaseManagementService:
    return request.app.state.manager.inject_service(CaseManagementService).with_case_repository(case_repository)

CaseManagementServiceDep = Annotated[CaseManagementService, Depends(get_case_management_service)]
