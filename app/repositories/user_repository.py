from fastapi import Depends
from uuid import UUID
from typing import Optional, Annotated

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..models import User
from ..dependencies import get_db

class UserRepository:
    def __init__(self):
        pass

    def with_session(self, session: AsyncSession) -> "UserRepository":
        self.db: AsyncSession = session
        return self 

    async def get_user(self, user_id: UUID) -> Optional[User]:
        stmt = select(User).where(User.id == str(user_id))
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_by_email(self, email: str) -> Optional[User]:
        stmt = select(User).where(User.email == email)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_user(self, user_data: dict, hashed_password: str) -> User:
        db_user = User(
            email=user_data["email"],
            full_name=user_data.get("full_name"),
            hashed_password=hashed_password,
        )
        self.db.add(db_user)
        await self.db.commit()
        await self.db.refresh(db_user)
        return db_user

    async def update_user(
        self,
        user: User,
        full_name: Optional[str] = None,
        hashed_password: Optional[str] = None,
    ) -> User:
        if full_name:
            user.full_name = full_name
        if hashed_password:
            user.hashed_password = hashed_password

        await self.db.commit()
        await self.db.refresh(user)
        return user 

def get_user_repository(db: AsyncSession = Depends(get_db)) -> "UserRepository":
    return UserRepository().with_session(db)

UserRepositoryDep = Annotated[UserRepository, Depends(get_user_repository)]
