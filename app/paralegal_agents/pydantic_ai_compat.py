"""
Compatibility layer for pydantic_ai
"""

from typing import Any, Callable, Optional
from pydantic_ai import Agent, RunContext, Tool
from pydantic_ai.result import RunUsage

# Re-exports
__all__ = [
    'Agent',
    'RunContext',
    'RunContextWrapper',
    'RunHooks',
    'Runner',
    'Tool',
    'Usage',
    'function_tool',
]

# Aliases for compatibility
RunContextWrapper = RunContext
Usage = RunUsage

# Placeholder classes for missing functionality
class RunHooks:
    """Placeholder for RunHooks functionality"""
    pass

class Runner:
    """Placeholder for Runner functionality"""
    pass

def function_tool(func: Callable) -> Callable:
    """
    Decorator to convert a function into a tool.
    For now, just return the function as-is since pydantic_ai handles tools differently.
    """
    # In pydantic_ai, tools are registered differently
    # For now, just mark the function and return it
    func._is_tool = True
    return func