"""
API routes module for the refactored application.
"""
from .auth_routes_refactored import router as auth_router
from .case_management_routes import router as case_management_router

__all__ = [
    'auth_router',
    'case_management_router'
]
