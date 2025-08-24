"""
Compatibility shim: provide get_logger delegating to logger_manager.get_logger.
"""

from .logger_manager import get_logger  # re-export

__all__ = ["get_logger"]
