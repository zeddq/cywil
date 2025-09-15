import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession

from .core.config_service import get_config
from .core.logger_manager import get_logger, set_user_id
from .core.database_manager import get_database_manager
from .models import User

logger = get_logger(__name__)

# Get configuration
config = get_config()

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


def create_access_token(
    data: Dict[str, Any], expires_delta: Optional[timedelta] = None
) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(
            minutes=config.security.access_token_expire_minutes
        )

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        config.security.secret_key.get_secret_value(),
        algorithm=config.security.algorithm,
    )
    return encoded_jwt


def create_session_token() -> str:
    """Create a secure random session token."""
    return secrets.token_urlsafe(32)


async def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_database_manager),
) -> User:
    """Get the current authenticated user from JWT token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token,
            config.security.secret_key.get_secret_value(),
            algorithms=[config.security.algorithm],
        )
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
            status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user"
        )

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Get current active user."""
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


def check_user_permissions(
    required_roles: Optional[list[str]] = None, allow_own_resource: bool = False
):
    """Dependency to check user permissions."""

    async def permission_checker(
        current_user: User = Depends(get_current_active_user),
        resource_owner_id: Optional[str] = None,
    ) -> User:
        # If allowing own resource access and user owns the resource
        if (
            allow_own_resource
            and resource_owner_id
            and str(current_user.id) == resource_owner_id
        ):
            return current_user

        # Check role-based permissions
        if required_roles and current_user.role not in required_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions"
            )

        return current_user

    return permission_checker


# Commonly used permission dependencies
def require_admin():
    return check_user_permissions(required_roles=["admin"])


def require_lawyer():
    return check_user_permissions(required_roles=["admin", "lawyer"])


def require_paralegal():
    return check_user_permissions(required_roles=["admin", "lawyer", "paralegal"])
