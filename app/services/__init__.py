"""
Service initialization and dependency injection setup.
"""

import logging
from typing import Any, Dict

from ..core.conversation_manager import ConversationManager
from ..core.database_manager import DatabaseManager
from ..core.llm_manager import LLMManager
from ..core.tool_executor import ToolExecutor
from ..core.tool_registry import tool_registry
from .case_management_service import CaseManagementService
from .document_generation_service import DocumentGenerationService
from .statute_search_service import StatuteSearchService
from .supreme_court_service import SupremeCourtService

logger = logging.getLogger(__name__)


def get_tool_schemas(categories=None) -> list[Dict[str, Any]]:
    """
    Get OpenAI function schemas for all registered tools.

    Args:
        categories: Optional list of tool categories to filter by

    Returns:
        List of OpenAI function schemas
    """
    return tool_registry.get_openai_schemas(categories)


async def execute_tool(name: str, arguments: Dict[str, Any]) -> Any:
    """
    Execute a tool by name with given arguments.

    Args:
        name: Tool name
        arguments: Tool arguments

    Returns:
        Tool execution result
    """
    return await tool_registry.execute_tool(name, arguments)


# Export commonly used services
__all__ = [
    "get_tool_schemas",
    "execute_tool",
    "StatuteSearchService",
    "DocumentGenerationService",
    "CaseManagementService",
    "SupremeCourtService",
    "DatabaseManager",
    "LLMManager",
    "ConversationManager",
    "ToolExecutor",
    "tool_registry",
]
