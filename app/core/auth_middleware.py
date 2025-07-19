"""
Authentication middleware for FastAPI using the AuthService.
"""
from typing import Optional, List
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.auth_service import AuthService
from ..models import User, UserRole
from .logger_manager import get_logger


logger = get_logger(__name__)

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

# HTTP Bearer scheme (alternative)
bearer_scheme = HTTPBearer(auto_error=False)


class AuthMiddleware:
    def __init__(self, auth_service: AuthService):
        self.auth_service: AuthService = auth_service
        # Convenience functions for common role requirements
        self.require_admin = self.require_roles([UserRole.admin])
        self.require_lawyer = self.require_roles([UserRole.lawyer])
        self.require_paralegal = self.require_roles([UserRole.paralegal, UserRole.lawyer, UserRole.admin])

    async def get_current_user(
        self,
        token: Optional[str] = Depends(oauth2_scheme),
        bearer: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    ) -> Optional[User]:
        """
        Get the current authenticated user from JWT token.
        Supports both OAuth2 password bearer and HTTP bearer schemes.
        """
        # Try to get token from either scheme
        access_token = token
        if not access_token and bearer:
            access_token = bearer.credentials
            
        if not access_token:
            return None
            
        try:
            # Decode token
            payload = self.auth_service.decode_token(access_token)
            
            # Verify it's an access token
            if payload.get("type") != "access":
                logger.warning("Invalid token type received")
                return None
                
            # Get user
            user_id = payload.get("sub")
            if not user_id:
                logger.warning("Token missing user ID")
                return None
                
            user = await self.auth_service.get_user_by_id(user_id)
            if not user:
                logger.warning(f"User not found: {user_id}")
                return None
                
            if not user.is_active:
                logger.warning(f"Inactive user attempted access: {user.email}")
                return None
                
            return user
            
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return None


    async def require_user(
        self,
        current_user: Optional[User] = Depends(get_current_user)
    ) -> User:
        """Require an authenticated user"""
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return current_user


    async def require_active_user(
        self,
        current_user: User = Depends(require_user)
    ) -> User:
        """Require an active authenticated user"""
        if not current_user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Inactive user account"
            )
        return current_user


    async def require_verified_user(
        self,
        current_user: User = Depends(require_active_user)
    ) -> User:
        """Require a verified authenticated user"""
        if not current_user.is_verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Email verification required"
            )
        return current_user

    def get_auth_service(self) -> AuthService:
        return self.auth_service

    def require_roles(self, allowed_roles: List[UserRole]):
        """
        Dependency factory to require specific user roles.
        
        Usage:
            @app.get("/admin", dependencies=[Depends(require_roles([UserRole.ADMIN]))])
        """
        async def role_checker(
            self,
            current_user: User = Depends(self.require_active_user),
            auth_service: AuthService = Depends(self.get_auth_service)
        ) -> User:
            try:
                auth_service.check_permissions(current_user, allowed_roles)
                return current_user
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=str(e)
                )
        
        return role_checker

    def require_resource_owner(self, allow_roles: Optional[List[UserRole]] = None):
        """
        Dependency factory to require resource ownership or specific roles.
        
        Usage:
            @app.put("/cases/{case_id}")
            async def update_case(
                case_id: str,
                user: User = Depends(require_resource_owner([UserRole.ADMIN]))
            ):
                # User must own the case OR be an admin
        """
        async def ownership_checker(
            request: Request,
            current_user: User = Depends(self.require_active_user),
            auth_service: AuthService = Depends(self.get_auth_service)
        ) -> User:
            # Extract resource owner ID from path parameters
            # This assumes the resource has an owner_id field
            resource_owner_id = request.path_params.get("user_id")
            
            # If no specific owner ID in path, check if resource has owner
            # This would need to be customized based on your resource structure
            
            try:
                auth_service.check_permissions(
                    current_user,
                    allow_roles,
                    resource_owner_id=resource_owner_id,
                    allow_own_resource=True
                )
                return current_user
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=str(e)
                )
        
        return ownership_checker


async def auth_middleware(request: Request, call_next):
    """
    Middleware to attach authenticated user to request object.
    This allows accessing request.user throughout the application.
    """
    # Try to get current user
    auth_service = request.app.state.manager.inject_service(AuthService)

    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
    
    if token:
        try:
            payload = auth_service.decode_token(token)
            if payload.get("type") == "access":
                user_id = payload.get("sub")
                if user_id:
                    user = await auth_service.get_user_by_id(user_id)
                    if user and user.is_active:
                        request.state.user = user
        except Exception:
            # Silent fail - user remains unauthenticated
            pass
    
    response = await call_next(request)
    return response
