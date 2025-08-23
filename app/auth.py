from datetime import datetime, timedelta, UTC
from typing import Optional, Dict, Any
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session, select
from .dependencies import get_db
from .models import User, UserSession   
from .config import settings
import secrets
from .core.logger_manager import get_logger, set_user_id

logger = get_logger(__name__)

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Hash a password."""
    return pwd_context.hash(password)

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

def create_session_token() -> str:
    """Create a secure random session token."""
    return secrets.token_urlsafe(32)

async def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_db)
) -> User:
    """Get the current authenticated user from JWT token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        logger.debug(f"Decoded token: {payload}")
        user_id: Optional[str] = payload.get("user_id")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    user = await session.get(User, user_id)
    if user is None:
        logger.error(f"User not found: {user_id}")
        raise credentials_exception
    logger.debug(f"User found: {user.model_dump_json(indent=2)}")
    set_user_id(request, str(user.id))
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
    
    return user

async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Get current active user."""
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

def check_user_permissions(
    required_roles: list[str] = None,
    allow_own_resource: bool = False
):
    """Dependency to check user permissions."""
    async def permission_checker(
        current_user: User = Depends(get_current_active_user),
        resource_owner_id: Optional[str] = None
    ) -> User:
        # If allowing own resource access and user owns the resource
        if allow_own_resource and resource_owner_id and str(current_user.id) == resource_owner_id:
            return current_user
        
        # Check role-based permissions
        if required_roles and current_user.role not in required_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not enough permissions"
            )
        
        return current_user
    
    return permission_checker

# Commonly used permission dependencies
def require_admin(current_user: User = Depends(get_current_active_user)):
    check_user_permissions(required_roles=["admin"], current_user=current_user)

def require_lawyer(current_user: User = Depends(get_current_active_user)):
    check_user_permissions(required_roles=["admin", "lawyer"], current_user=current_user)

def require_paralegal(current_user: User = Depends(get_current_active_user)):
    check_user_permissions(required_roles=["admin", "lawyer", "paralegal"], current_user=current_user)
