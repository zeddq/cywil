from typing import List, Optional, Annotated
from uuid import UUID
from fastapi import UploadFile, Request, Depends
import os

from ..models import Case, Document, User
from ..core.config_service import get_config
from ..core.service_interface import ServiceInterface, ServiceStatus, HealthCheckResult
from ..repositories.case_repository import CaseRepositoryDep

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

    async def update_case(self, case_id: UUID, case_in: Case, user: User) -> Optional[Case]:
        case = await self.get_case(case_id=case_id, user=user)
        if not case:
            return None
        return await self.case_repository.update_case(case=case, case_in=case_in)

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

def get_case_management_service(request: Request, case_repository: CaseRepositoryDep) -> CaseManagementService:
    return request.app.state.manager.inject_service(CaseManagementService).with_case_repository(case_repository)

CaseManagementServiceDep = Annotated[CaseManagementService, Depends(get_case_management_service)]
