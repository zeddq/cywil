"""
Compatibility shim: export ServiceContainer and a module-level singleton
named service_container for tests expecting app.core.service_container.
"""

from .service_interface import ServiceContainer as _ServiceContainer

# Module-level singleton for legacy tests
service_container = _ServiceContainer()

__all__ = ["service_container", "_ServiceContainer"]
