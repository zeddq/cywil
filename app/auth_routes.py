from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select
from datetime import datetime, timedelta, UTC
from typing import Optional
from pydantic import BaseModel, EmailStr

from .core.database_manager import DatabaseManager
from .models import User, UserSession, UserRole
from .auth import (
    verify_password,
    get_password_hash,
    create_access_token,
    create_session_token,
    get_current_user,
    get_current_active_user,
    require_admin
)
from .config import settings

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

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
    token_type: str
    expires_in: int

class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    is_active: bool
    is_verified: bool
    created_at: datetime

@router.post("/register", response_model=UserResponse)
async def register(
    user_data: UserRegister,
    session: Session = Depends(DatabaseManager.get_session)
):
    """Register a new user."""
    # Check if registration is enabled
    if not settings.registration_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is currently disabled"
        )
    
    # Validate secret key
    valid_keys = [key.strip() for key in settings.registration_secret_keys.split(',')]
    if user_data.secret_key not in valid_keys:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid registration key"
        )
    
    # Check if user already exists
    existing_user = session.exec(
        select(User).where(User.email == user_data.email)
    ).first()
    
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
    
    return UserResponse(
        id=new_user.id,
        email=new_user.email,
        full_name=new_user.full_name,
        role=new_user.role.value,
        is_active=new_user.is_active,
        is_verified=new_user.is_verified,
        created_at=new_user.created_at
    )

@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(DatabaseManager.get_session)
):
    """Login and receive an access token."""
    # Find user by email
    user = session.exec(
        select(User).where(User.email == form_data.username)
    ).first()
    
    if not user or not verify_password(form_data.password, user.hashed_password):
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
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id), "email": user.email, "role": user.role.value},
        expires_delta=access_token_expires
    )
    
    # Create session record
    session_token = create_session_token()
    user_session = UserSession(
        user_id=user.id,
        token=session_token,
        expires_at=datetime.now(UTC) + access_token_expires
    )
    session.add(user_session)
    session.commit()
    
    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )

@router.post("/logout")
async def logout(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(DatabaseManager.get_session)
):
    """Logout the current user by invalidating their sessions."""
    # Delete all user sessions
    user_sessions = session.exec(
        select(UserSession).where(UserSession.user_id == current_user.id)
    ).all()
    
    for user_session in user_sessions:
        session.delete(user_session)
    
    session.commit()
    
    return {"message": "Successfully logged out"}

@router.get("/me", response_model=UserResponse)
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    """Get current user information."""
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role.value,
        is_active=current_user.is_active,
        is_verified=current_user.is_verified,
        created_at=current_user.created_at
    )

@router.post("/refresh", response_model=Token)
async def refresh_token(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(DatabaseManager.get_session)
):
    """Refresh the access token."""
    # Create new access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(current_user.id), "email": current_user.email, "role": current_user.role.value},
        expires_delta=access_token_expires
    )
    
    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )

# Admin endpoints
class UserUpdate(BaseModel):
    is_active: Optional[bool] = None
    is_verified: Optional[bool] = None
    role: Optional[UserRole] = None

class UserListResponse(BaseModel):
    users: list[UserResponse]
    total: int

@router.get("/admin/users", response_model=UserListResponse)
async def get_all_users(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(require_admin),
    session: Session = Depends(DatabaseManager.get_session)
):
    """Get all users (admin only)."""
    from sqlmodel import func
    
    # Get total count
    total_users = session.exec(
        select(func.count()).select_from(User)
    ).one()
    
    # Get users with pagination
    users = session.exec(
        select(User)
        .offset(skip)
        .limit(limit)
        .order_by(User.created_at.desc())
    ).all()
    
    user_responses = [
        UserResponse(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=user.role.value,
            is_active=user.is_active,
            is_verified=user.is_verified,
            created_at=user.created_at
        )
        for user in users
    ]
    
    return UserListResponse(users=user_responses, total=total_users)

@router.patch("/admin/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    user_update: UserUpdate,
    current_user: User = Depends(require_admin),
    session: Session = Depends(DatabaseManager.get_session)
):
    """Update user details (admin only)."""
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
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
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role.value,
        is_active=user.is_active,
        is_verified=user.is_verified,
        created_at=user.created_at
    )

@router.delete("/admin/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    current_user: User = Depends(require_admin),
    session: Session = Depends(DatabaseManager.get_session)
):
    """Delete a user (admin only)."""
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Prevent admin from deleting themselves
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account"
        )
    
    session.delete(user)
    session.commit()

# Registration Key Management
import secrets
import string

class RegistrationKeyResponse(BaseModel):
    key: str
    created_at: datetime

@router.post("/admin/registration-keys/generate", response_model=RegistrationKeyResponse)
async def generate_registration_key(
    current_user: User = Depends(require_admin)
):
    """Generate a new registration secret key (admin only)."""
    # Generate a secure random key
    alphabet = string.ascii_letters + string.digits
    key = ''.join(secrets.choice(alphabet) for _ in range(32))
    
    # Return the key (admin should manually add it to environment variables)
    return RegistrationKeyResponse(
        key=key,
        created_at=datetime.now(UTC)
    )

@router.get("/admin/registration-keys/status")
async def get_registration_status(
    current_user: User = Depends(require_admin)
):
    """Get current registration configuration status (admin only)."""
    # Get current keys but mask them for security
    valid_keys = [key.strip() for key in settings.registration_secret_keys.split(',')]
    masked_keys = [f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "***" for key in valid_keys]
    
    return {
        "registration_enabled": settings.registration_enabled,
        "number_of_active_keys": len(valid_keys),
        "masked_keys": masked_keys,
        "note": "To add new keys, update the REGISTRATION_SECRET_KEYS environment variable"
    }
