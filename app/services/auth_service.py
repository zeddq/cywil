from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Annotated
from fastapi import Request, Depends
from jose import jwt, JWTError
from passlib.context import CryptContext

from ..models import User
from ..core.config_service import get_config, ConfigService
from ..core.service_interface import ServiceInterface, ServiceStatus, HealthCheckResult
from ..repositories.user_repository import UserRepositoryDep

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class AuthService(ServiceInterface):
    def __init__(self, config_service: ConfigService):
        super().__init__("AuthService")
        self._config = config_service.config

    async def _initialize_impl(self):
        pass

    async def _shutdown_impl(self):
        pass

    async def _health_check_impl(self) -> HealthCheckResult:
        return HealthCheckResult(status=ServiceStatus.HEALTHY, message="AuthService is healthy")

    def with_user_repository(self, user_repository: UserRepositoryDep) -> "AuthService":
        self.user_repository = user_repository
        return self

    def get_password_hash(self, password: str) -> str:
        return pwd_context.hash(password)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return pwd_context.verify(plain_password, hashed_password)

    async def validate_registration_key(self, key: str) -> bool:
        # This is a placeholder. In a real application, this should be a secure check.
        return key == self._config.security.secret_key

    async def create_user(self, email: str, password: str, full_name: str, role: str) -> User:
        hashed_password = self.get_password_hash(password)
        # Note: Pydantic models are for validation, not direct instantiation.
        # We create a dictionary of the data to pass to the repository.
        user_data = {"email": email, "full_name": full_name}
        return await self.user_repository.create_user(user_data=user_data, hashed_password=hashed_password)

    async def authenticate_user(self, email: str, password: str) -> Optional[User]:
        user = await self.user_repository.get_user_by_email(email)
        if not user or not self.verify_password(password, user.hashed_password):
            return None
        return user

    def create_access_token(self, data: dict, expires_delta: Optional[timedelta] = None) -> str:
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=self._config.security.access_token_expire_minutes)
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, self._config.security.secret_key.get_secret_value(), algorithm=self._config.security.algorithm)
        return encoded_jwt

    def generate_tokens(self, user: User) -> Dict[str, Any]:
        access_token_expires = timedelta(minutes=self._config.security.access_token_expire_minutes)
        access_token = self.create_access_token(
            data={"sub": user.email, "user_id": str(user.id), "role": user.role.value},
            expires_delta=access_token_expires
        )
        # In a real app, you would have a refresh token as well
        return {
            "access_token": access_token,
            "refresh_token": "fake-refresh-token", # Placeholder
            "token_type": "bearer",
            "expires_in": int(access_token_expires.total_seconds())
        }
    
    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        # This is a placeholder. A real implementation would validate the refresh token
        # and create a new access token.
        try:
            # In a real app, you would have a separate secret for refresh tokens
            payload = jwt.decode(refresh_token, self._config.security.secret_key.get_secret_value(), algorithms=[self._config.security.algorithm])
            # In a real app, you'd check if the refresh token is valid/revoked from a DB
            user = await self.user_repository.get_user_by_email(payload.get("sub"))
            if not user:
                raise Exception("User not found")
            return self.generate_tokens(user)
        except JWTError:
            raise Exception("Invalid refresh token")

    async def update_user(self, user: User, full_name: Optional[str] = None, password: Optional[str] = None) -> User:
        hashed_password = self.get_password_hash(password) if password else None
        return await self.user_repository.update_user(user, full_name=full_name, hashed_password=hashed_password)

    async def change_password(self, user: User, current_password: str, new_password: str) -> bool:
        if not self.verify_password(current_password, user.hashed_password):
            return False
        
        new_hashed_password = self.get_password_hash(new_password)
        await self.user_repository.update_user(user, hashed_password=new_hashed_password)
        return True

    async def create_user_session(self, user_id: str, session_token: str):
        # Placeholder for session management logic, e.g., storing in Redis.
        # In a real app, you would store the session token with an expiry.
        print(f"Creating session for user {user_id} with token {session_token}")
        pass
    
    def create_session_token(self) -> str:
        # Placeholder for creating a secure session token.
        import secrets
        return secrets.token_hex(32) 

    def get_user_by_id(self, user_id: str) -> User:
        return self.user_repository.get_user_by_id(user_id)


def get_auth_service(request: Request, user_repository: UserRepositoryDep) -> AuthService:
    return request.app.state.manager.inject_service(AuthService).with_user_repository(user_repository)

AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
