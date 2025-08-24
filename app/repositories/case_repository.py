
# Async SQLAlchemy/SQLModel session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from uuid import UUID
# FastAPI dependency utilities
from typing import List, Optional, Annotated
from fastapi import Depends

from ..models import Case, Document

from ..dependencies import get_db

class CaseRepository:
    def __init__(self):
        pass

    def with_session(self, session: AsyncSession) -> "CaseRepository":
        """Attach an AsyncSession coming from FastAPI dependency `get_db`."""
        self.db: AsyncSession = session
        return self

    async def get_case(self, case_id: UUID, user_id: UUID) -> Optional[Case]:
        stmt = (
            select(Case)
            .where(Case.id == str(case_id))
            .where(Case.created_by_id == str(user_id))
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_cases(self, user_id: UUID, status: Optional[str] = None) -> List[Case]:
        stmt = select(Case).where(Case.created_by_id == str(user_id))
        if status:
            stmt = stmt.where(Case.status == status)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def create_case(self, case_in: Case, user_id: UUID) -> Case:
        db_case = Case(**case_in.model_dump(), created_by_id=str(user_id))
        self.db.add(db_case)
        await self.db.commit()
        await self.db.refresh(db_case)
        return db_case

    async def update_case(self, case: Case, case_in: Case) -> Case:
        update_data = case_in.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(case, key, value)
        
        await self.db.commit()
        await self.db.refresh(case)
        return case

    async def delete_case(self, case: Case) -> None:
        self.db.delete(case)  # type: ignore[misc]
        await self.db.commit()

    async def create_document(self, doc_in: Document) -> Document:
        db_doc = Document(**doc_in.model_dump())
        self.db.add(db_doc)
        await self.db.commit()
        await self.db.refresh(db_doc)
        return db_doc

    async def list_documents(self, user_id: UUID, case_id: Optional[UUID] = None) -> List[Document]:
        stmt = (
            select(Document)
            .join(Case)
            .where(Case.created_by_id == str(user_id))
        )
        if case_id:
            stmt = stmt.where(Document.case_id == str(case_id))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())


def get_case_repository(db: AsyncSession = Depends(get_db)) -> "CaseRepository":
    return CaseRepository().with_session(db)

CaseRepositoryDep = Annotated[CaseRepository, Depends(get_case_repository)]
