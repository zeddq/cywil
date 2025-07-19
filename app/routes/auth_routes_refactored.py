"""
Authentication routes using the refactored AuthService.
"""
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr

from ..services.auth_service import get_auth_service, AuthServiceDep
from ..auth import get_current_user
from ..core.logger_manager import get_logger, correlation_context, set_user_id
from ..services.auth_service import AuthService
from ..models import UserRole, User


logger = get_logger(__name__)

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
    full_name: Optional[str] = None
    password: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

def require_user(request: Request) -> User:
    return request.state.user

def require_active_user(user: User = Depends(require_user)) -> User:
    if user.is_active:
        return user
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User is not active"
        )

@router.post("/register", response_model=UserResponse)
async def register(
    user_data: UserRegister,
    request: Request,
    auth_service: AuthServiceDep
):
    """Register a new user."""
    with correlation_context():
        logger.info(
            "User registration attempt",
            extra={
                "extra_fields": {
                    "event": "registration_attempt",
                    "email": user_data.email,
                    "ip_address": request.client.host
                }
            }
        )
        
        try:
            # Validate registration key
            if not await auth_service.validate_registration_key(user_data.secret_key):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid registration key"
                )
            
            # Create user
            new_user = await auth_service.create_user(
                email=user_data.email,
                password=user_data.password,
                full_name=user_data.full_name,
                role=UserRole.PARALEGAL  # Default role
            )
            
            logger.info(
                f"User registered successfully: {new_user.email}",
                extra={
                    "extra_fields": {
                        "event": "registration_success",
                        "user_id": str(new_user.id),
                        "email": new_user.email
                    }
                }
            )
            
            return UserResponse(
                id=str(new_user.id),
                email=new_user.email,
                full_name=new_user.full_name,
                role=new_user.role.value,
                is_active=new_user.is_active,
                is_verified=new_user.is_verified,
                created_at=new_user.created_at
            )
            
        except Exception as e:
            logger.error(
                f"Registration failed: {str(e)}",
                extra={
                    "extra_fields": {
                        "event": "registration_error",
                        "email": user_data.email,
                        "error": str(e)
                    }
                }
            )
            if isinstance(e, HTTPException):
                raise
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )


@router.post("/login", response_model=Token)
async def login(
    request: Request,
    auth_service: AuthServiceDep,
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    """Login with email and password."""
    with correlation_context():
        logger.info(
            "Login attempt",
            extra={
                "extra_fields": {
                    "event": "login_attempt",
                    "username": form_data.username,
                    "ip_address": request.client.host
                }
            }
        )
        
        # Authenticate user
        user = await auth_service.authenticate_user(
            email=form_data.username,  # OAuth2 form uses 'username' field
            password=form_data.password
        )
        
        if not user:
            logger.warning(
                f"Login failed: invalid credentials for {form_data.username}",
                extra={
                    "extra_fields": {
                        "event": "login_failed",
                        "username": form_data.username,
                        "reason": "invalid_credentials"
                    }
                }
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Generate tokens
        tokens = auth_service.generate_tokens(user)
        
        # Create session
        session_token = auth_service.create_session_token()
        await auth_service.create_user_session(str(user.id), session_token)
        
        set_user_id(request, str(user.id))
        logger.info(
            f"User logged in successfully: {user.email}",
            extra={
                "extra_fields": {
                    "event": "login_success",
                    "user_id": str(user.id),
                    "email": user.email
                }
            }
        )
        
        return Token(**tokens)


@router.post("/refresh", response_model=Token)
async def refresh_token(
    token_data: RefreshTokenRequest,
    auth_service: AuthServiceDep,
    current_user = Depends(require_active_user),
):
    """Refresh access token using refresh token."""
    with correlation_context():
        try:
            tokens = await auth_service.refresh_access_token(token_data.refresh_token)
            
            logger.info(
                "Token refreshed successfully",
                extra={
                    "extra_fields": {
                        "event": "token_refresh_success"
                    }
                }
            )
            
            return Token(**tokens)
            
        except Exception as e:
            logger.error(
                f"Token refresh failed: {str(e)}",
                extra={
                    "extra_fields": {
                        "event": "token_refresh_error",
                        "error": str(e)
                    }
                }
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token"
            )

@router.post("/logout")
async def logout(
    current_user = Depends(require_active_user),
):
    """Logout current user."""
    with correlation_context():
        set_user_id(str(current_user.id))
        
        # TODO: Revoke current session token
        # This requires extracting the session token from the request
        
        logger.info(
            f"User logged out: {current_user.email}",
            extra={
                "extra_fields": {
                    "event": "logout",
                    "user_id": str(current_user.id),
                    "email": current_user.email
                }
            }
        )
        
        return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user = Depends(require_active_user)
):
    """Get current user information."""
    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role.value,
        is_active=current_user.is_active,
        is_verified=current_user.is_verified,
        created_at=current_user.created_at
    )


@router.put("/me", response_model=UserResponse)
async def update_current_user(
    user_update: UserUpdate,
    auth_service: AuthServiceDep,
    current_user = Depends(require_active_user),
):
    """Update current user's profile."""
    with correlation_context():
        set_user_id(str(current_user.id))
        
        # Prepare update data
        update_data = user_update.model_dump(exclude_unset=True)
        
        # Update user
        updated_user = await auth_service.update_user(str(current_user.id), **update_data)
        
        if not updated_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        logger.info(
            f"User profile updated: {updated_user.email}",
            extra={
                "extra_fields": {
                    "event": "profile_update",
                    "user_id": str(updated_user.id),
                    "fields_updated": list(update_data.keys())
                }
            }
        )
        
        return UserResponse(
            id=str(updated_user.id),
            email=updated_user.email,
            full_name=updated_user.full_name,
            role=updated_user.role.value,
            is_active=updated_user.is_active,
            is_verified=updated_user.is_verified,
            created_at=updated_user.created_at
        )


@router.post("/change-password")
async def change_password(
    password_data: ChangePasswordRequest,
    auth_service: AuthServiceDep,
    current_user = Depends(require_active_user),
):
    """Change current user's password."""
    with correlation_context():
        set_user_id(str(current_user.id))
        
        # Verify current password
        if not auth_service.verify_password(password_data.current_password, current_user.hashed_password):
            logger.warning(
                f"Password change failed: incorrect current password for {current_user.email}",
                extra={
                    "extra_fields": {
                        "event": "password_change_failed",
                        "user_id": str(current_user.id),
                        "reason": "incorrect_password"
                    }
                }
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect"
            )
        
        # Update password
        await auth_service.update_user(
            str(current_user.id),
            password=password_data.new_password
        )
        
        logger.info(
            f"Password changed successfully for: {current_user.email}",
            extra={
                "extra_fields": {
                    "event": "password_change_success",
                    "user_id": str(current_user.id),
                    "email": current_user.email
                }
            }
        )
        
        return {"message": "Password changed successfully"}


@router.get("/verify-token")
async def verify_token(
    current_user = Depends(get_current_user)
):
    """Verify if the current token is valid."""
    if current_user:
        return {
            "valid": True,
            "user_id": str(current_user.id),
            "email": current_user.email,
            "role": current_user.role.value
        }
    else:
        return {"valid": False}
