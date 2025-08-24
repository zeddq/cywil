"""
Consolidated authentication routes - merges the best of both implementations.
Uses working JWT logic from auth.py with proper service structure.
"""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr
from sqlmodel import Session, select
from sqlmodel import func

from ..auth import (
    create_access_token,
    create_session_token,
    get_current_active_user,
    get_current_user,
    get_password_hash,
    verify_password,
)
from ..core.config_service import get_config
from ..core.database_manager import DatabaseManager
from ..core.logger_manager import correlation_context, get_logger, set_user_id
from ..models import User, UserRole, UserSession

logger = get_logger(__name__)
router = APIRouter(prefix="/api/auth", tags=["Authentication"])
config = get_config()


# Request/Response models
class UserRegister(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    secret_key: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    is_active: bool
    is_verified: bool
    created_at: datetime


class UserUpdate(BaseModel):
    is_active: Optional[bool] = None
    is_verified: Optional[bool] = None
    role: Optional[UserRole] = None


class UserListResponse(BaseModel):
    users: list[UserResponse]
    total: int


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class RegistrationKeyResponse(BaseModel):
    key: str
    created_at: datetime


def require_admin() -> User:
    """Dependency to require admin role."""
    def check_admin(current_user: User = Depends(get_current_active_user)) -> User:
        if current_user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required"
            )
        return current_user
    return Depends(check_admin)


@router.post("/register", response_model=UserResponse)
async def register(
    user_data: UserRegister, 
    request: Request,
    session: Session = Depends(DatabaseManager.get_session)
):
    """Register a new user."""
    with correlation_context():
        logger.info(
            "User registration attempt",
            extra={
                "extra_fields": {
                    "event": "registration_attempt",
                    "email": user_data.email,
                    "ip_address": request.client.host if request.client else "unknown",
                }
            },
        )

        try:
            # Check if registration is enabled
            if not config.security.registration_enabled:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, 
                    detail="Registration is currently disabled"
                )

            # Validate secret key
            valid_keys = config.security.registration_keys
            if user_data.secret_key not in valid_keys:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, 
                    detail="Invalid registration key"
                )

            # Check if user already exists
            existing_user = session.exec(select(User).where(User.email == user_data.email)).first()
            if existing_user:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, 
                    detail="Email already registered"
                )

            # Create new user
            hashed_password = get_password_hash(user_data.password)
            new_user = User(
                email=user_data.email,
                full_name=user_data.full_name,
                hashed_password=hashed_password
            )

            session.add(new_user)
            session.commit()
            session.refresh(new_user)

            # Ensure user was properly created
            if new_user.id is None or new_user.created_at is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="User creation failed"
                )

            logger.info(
                f"User registered successfully: {new_user.email}",
                extra={
                    "extra_fields": {
                        "event": "registration_success",
                        "user_id": str(new_user.id),
                        "email": new_user.email,
                    }
                },
            )

            return UserResponse(
                id=str(new_user.id),
                email=new_user.email,
                full_name=new_user.full_name,
                role=new_user.role.value,
                is_active=new_user.is_active,
                is_verified=new_user.is_verified,
                created_at=new_user.created_at,
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                f"Registration failed: {str(e)}",
                extra={
                    "extra_fields": {
                        "event": "registration_error",
                        "email": user_data.email,
                        "error": str(e),
                    }
                },
            )
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/login", response_model=Token)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(DatabaseManager.get_session),
):
    """Login and receive access and refresh tokens."""
    with correlation_context():
        logger.info(
            "Login attempt",
            extra={
                "extra_fields": {
                    "event": "login_attempt",
                    "username": form_data.username,
                    "ip_address": request.client.host if request.client else "unknown",
                }
            },
        )

        # Find user by email
        user = session.exec(select(User).where(User.email == form_data.username)).first()

        if not user or not verify_password(form_data.password, user.hashed_password):
            logger.warning(
                f"Login failed: invalid credentials for {form_data.username}",
                extra={
                    "extra_fields": {
                        "event": "login_failed",
                        "username": form_data.username,
                        "reason": "invalid_credentials",
                    }
                },
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail="User account is inactive"
            )

        # Update last login
        user.last_login = datetime.now(UTC)
        session.add(user)

        # Create access token
        access_token_expires = timedelta(minutes=config.security.access_token_expire_minutes)
        access_token = create_access_token(
            data={
                "sub": str(user.id),
                "user_id": str(user.id), 
                "email": user.email, 
                "role": user.role.value
            },
            expires_delta=access_token_expires,
        )

        # Create refresh token (longer lived)
        refresh_token_expires = timedelta(days=7)  # 7 days for refresh token
        refresh_token = create_access_token(
            data={
                "sub": str(user.id),
                "user_id": str(user.id), 
                "email": user.email,
                "type": "refresh"
            },
            expires_delta=refresh_token_expires,
        )

        # Create session record
        session_token = create_session_token()
        if user.id is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="User ID is unexpectedly None"
            )
            
        user_session = UserSession(
            user_id=user.id,
            token=session_token,
            expires_at=datetime.now(UTC) + access_token_expires
        )
        session.add(user_session)
        session.commit()

        set_user_id(request, str(user.id))
        logger.info(
            f"User logged in successfully: {user.email}",
            extra={
                "extra_fields": {
                    "event": "login_success",
                    "user_id": str(user.id),
                    "email": user.email,
                }
            },
        )

        return Token(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=config.security.access_token_expire_minutes * 60,
        )


@router.post("/refresh", response_model=Token)
async def refresh_token(
    token_data: RefreshTokenRequest,
    session: Session = Depends(DatabaseManager.get_session),
):
    """Refresh access token using refresh token."""
    with correlation_context():
        try:
            # Decode refresh token
            payload = jwt.decode(
                token_data.refresh_token,
                config.security.secret_key.get_secret_value(),
                algorithms=[config.security.algorithm],
            )
            
            # Validate token type
            if payload.get("type") != "refresh":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token type"
                )
            
            user_id: str | None = payload.get("user_id", None)
            if not user_id:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token"
                )
                
            # Get user
            user = session.get(User, user_id)
            if not user or not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found or inactive"
                )

            # Create new tokens
            access_token_expires = timedelta(minutes=config.security.access_token_expire_minutes)
            access_token = create_access_token(
                data={
                    "sub": str(user.id),
                    "user_id": str(user.id),
                    "email": user.email,
                    "role": user.role.value
                },
                expires_delta=access_token_expires,
            )

            # Create new refresh token
            refresh_token_expires = timedelta(days=7)
            new_refresh_token = create_access_token(
                data={
                    "sub": str(user.id),
                    "user_id": str(user.id),
                    "email": user.email,
                    "type": "refresh"
                },
                expires_delta=refresh_token_expires,
            )

            logger.info(
                "Token refreshed successfully",
                extra={"extra_fields": {"event": "token_refresh_success", "user_id": str(user.id)}},
            )

            return Token(
                access_token=access_token,
                refresh_token=new_refresh_token,
                token_type="bearer",
                expires_in=config.security.access_token_expire_minutes * 60,
            )

        except JWTError:
            logger.error(
                "Token refresh failed: invalid token",
                extra={"extra_fields": {"event": "token_refresh_error", "error": "invalid_token"}},
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token"
            )
        except Exception as e:
            logger.error(
                f"Token refresh failed: {str(e)}",
                extra={"extra_fields": {"event": "token_refresh_error", "error": str(e)}},
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token"
            )


@router.post("/logout")
async def logout(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(DatabaseManager.get_session),
):
    """Logout the current user by invalidating their sessions."""
    with correlation_context():
        # Delete all user sessions
        user_sessions = session.exec(
            select(UserSession).where(UserSession.user_id == current_user.id)
        ).all()

        for user_session in user_sessions:
            session.delete(user_session)

        session.commit()

        logger.info(
            f"User logged out: {current_user.email}",
            extra={
                "extra_fields": {
                    "event": "logout",
                    "user_id": str(current_user.id),
                    "email": current_user.email,
                }
            },
        )

        return {"message": "Successfully logged out"}


@router.get("/me", response_model=UserResponse)
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    """Get current user information."""
    if current_user.id is None or current_user.created_at is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Current user data is invalid"
        )

    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role.value,
        is_active=current_user.is_active,
        is_verified=current_user.is_verified,
        created_at=current_user.created_at,
    )


@router.put("/me", response_model=UserResponse)
async def update_current_user(
    user_update: UserUpdate,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(DatabaseManager.get_session),
):
    """Update current user's profile (limited fields)."""
    # For security, users can only update their full_name
    # Admin-only fields like is_active, role are handled by admin endpoints
    
    user_data = user_update.model_dump(exclude_unset=True)
    
    # Users can't modify their own role/status
    if "is_active" in user_data or "role" in user_data or "is_verified" in user_data:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify role or status through this endpoint"
        )

    current_user.updated_at = datetime.now(UTC)
    session.add(current_user)
    session.commit()
    session.refresh(current_user)

    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role.value,
        is_active=current_user.is_active,
        is_verified=current_user.is_verified,
        created_at=current_user.created_at,
    )


@router.post("/change-password")
async def change_password(
    password_data: PasswordChangeRequest,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(DatabaseManager.get_session),
):
    """Change current user's password."""
    # Verify current password
    if not verify_password(password_data.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )

    # Update password
    current_user.hashed_password = get_password_hash(password_data.new_password)
    current_user.updated_at = datetime.now(UTC)
    session.add(current_user)
    session.commit()

    logger.info(
        f"Password changed successfully for: {current_user.email}",
        extra={
            "extra_fields": {
                "event": "password_change_success",
                "user_id": str(current_user.id),
                "email": current_user.email,
            }
        },
    )

    return {"message": "Password changed successfully"}


@router.get("/verify-token")
async def verify_token(current_user: User = Depends(get_current_user)):
    """Verify if the current token is valid."""
    return {
        "valid": True,
        "user_id": str(current_user.id),
        "email": current_user.email,
        "role": current_user.role.value,
    }


# Admin endpoints
@router.get("/admin/users", response_model=UserListResponse)
async def get_all_users(
    skip: int = 0,
    limit: int = 100,
    current_user: User = require_admin(),
    session: Session = Depends(DatabaseManager.get_session),
):
    """Get all users (admin only)."""
    # Get total count
    total_users = session.exec(select(func.count()).select_from(User)).one()

    # Get users with pagination
    users = session.exec(
        select(User).offset(skip).limit(limit).order_by(User.created_at.desc())  # type: ignore
    ).all()

    user_responses = [
        UserResponse(
            id=str(user.id),
            email=user.email,
            full_name=user.full_name,
            role=user.role.value,
            is_active=user.is_active,
            is_verified=user.is_verified,
            created_at=user.created_at,
        )
        for user in users
    ]

    return UserListResponse(users=user_responses, total=total_users)


@router.patch("/admin/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    user_update: UserUpdate,
    current_user: User = require_admin(),
    session: Session = Depends(DatabaseManager.get_session),
):
    """Update user details (admin only)."""
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Update fields if provided
    if user_update.is_active is not None:
        user.is_active = user_update.is_active

    if user_update.is_verified is not None:
        user.is_verified = user_update.is_verified

    if user_update.role is not None:
        user.role = user_update.role

    user.updated_at = datetime.now(UTC)
    session.add(user)
    session.commit()
    session.refresh(user)

    return UserResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        role=user.role.value,
        is_active=user.is_active,
        is_verified=user.is_verified,
        created_at=user.created_at,
    )


@router.delete("/admin/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    current_user: User = require_admin(),
    session: Session = Depends(DatabaseManager.get_session),
):
    """Delete a user (admin only)."""
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Prevent admin from deleting themselves
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account"
        )

    session.delete(user)
    session.commit()


@router.post("/admin/registration-keys/generate", response_model=RegistrationKeyResponse)
async def generate_registration_key(current_user: User = require_admin()):
    """Generate a new registration secret key (admin only)."""
    import string
    
    # Generate a secure random key
    alphabet = string.ascii_letters + string.digits
    key = "".join(secrets.choice(alphabet) for _ in range(32))

    return RegistrationKeyResponse(key=key, created_at=datetime.now(UTC))


@router.get("/admin/registration-keys/status")
async def get_registration_status(current_user: User = require_admin()):
    """Get current registration configuration status (admin only)."""
    # Get current keys but mask them for security
    valid_keys = config.security.registration_keys
    masked_keys = [f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "***" for key in valid_keys]

    return {
        "registration_enabled": config.security.registration_enabled,
        "number_of_active_keys": len(valid_keys),
        "masked_keys": masked_keys,
        "note": "To add new keys, update the REGISTRATION_SECRET_KEYS environment variable",
    }
