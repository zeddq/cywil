"""
Tool registry pattern for managing legal AI tools with OpenAI function calling.
"""

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from enum import StrEnum
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Type

from pydantic import BaseModel, Field, create_model

logger = logging.getLogger(__name__)


class ToolCategory(StrEnum):
    """Categories of tools available in the system"""

    SEARCH = "search"
    DOCUMENT = "document"
    CASE_MANAGEMENT = "case_management"
    ANALYSIS = "analysis"
    UTILITY = "utility"
    VECTOR_DB = "vector_db"


@dataclass
class ToolParameter:
    """Definition of a tool parameter"""

    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None
    enum: Optional[List[str]] = None

    def to_openai_schema(self) -> Dict[str, Any]:
        """Convert to OpenAI function parameter schema"""
        schema: Dict[str, Any] = {"type": self.type, "description": self.description}
        if self.default is not None:
            schema["default"] = self.default
        if self.enum:
            schema["enum"] = list(self.enum)  # Ensure it's a proper list for JSON serialization
        return schema


@dataclass
class ToolDefinition:
    """Complete definition of a tool"""

    name: str
    description: str
    category: ToolCategory
    parameters: List[ToolParameter]
    function: Callable
    returns: str = "Dictionary with results"
    examples: List[str] = field(default_factory=list)

    def to_openai_schema(self) -> Dict[str, Any]:
        """Convert to OpenAI function calling schema"""
        properties = {}
        required = []

        for param in self.parameters:
            properties[param.name] = param.to_openai_schema()
            if param.required:
                required.append(param.name)

        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }

    def create_pydantic_model(self) -> Type[BaseModel]:
        """Create a Pydantic model for this tool's parameters"""
        fields = {}
        for param in self.parameters:
            field_type = str  # Default
            if param.type == "integer":
                field_type = int
            elif param.type == "boolean":
                field_type = bool
            elif param.type == "array":
                field_type = List[str]
            elif param.type == "object":
                field_type = Dict[str, Any]

            if param.required:
                fields[param.name] = (field_type, Field(description=param.description))
            else:
                fields[param.name] = (
                    Optional[field_type],
                    Field(default=param.default, description=param.description),
                )

        return create_model(f"{self.name}_params", **fields)


class ToolRegistry:
    """
    Central registry for all tools available to the AI system.
    Manages tool registration, validation, and execution.
    """

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        self._categories: Dict[ToolCategory, List[str]] = {cat: [] for cat in ToolCategory}
        self._middleware: List[Callable] = []
        logger.info("Tool registry initialized")

    def register(
        self,
        name: str,
        description: str,
        category: ToolCategory,
        parameters: List[ToolParameter],
        returns: str = "Dictionary with results",
        examples: Optional[List[str]] = None,
    ) -> Callable:
        """
        Decorator to register a tool function.

        Example:
            @tool_registry.register(
                name="search_statute",
                description="Search legal statutes",
                category=ToolCategory.SEARCH,
                parameters=[
                    ToolParameter("query", "string", "Search query"),
                    ToolParameter("top_k", "integer", "Number of results", False, 5)
                ]
            )
            async def search_statute(query: str, top_k: int = 5):
                ...
        """

        def decorator(func: Callable) -> Callable:
            # Validate function signature matches parameters
            sig = inspect.signature(func)
            param_names = set(p.name for p in parameters)
            func_params = set(sig.parameters.keys())

            # Allow 'self' parameter for class methods
            func_params.discard("self")

            if param_names != func_params:
                raise ValueError(
                    f"Tool '{name}' parameter mismatch. "
                    f"Defined: {param_names}, Function has: {func_params}"
                )

            # Create tool definition
            tool_def = ToolDefinition(
                name=name,
                description=description,
                category=category,
                parameters=parameters,
                function=func,
                returns=returns,
                examples=examples or [],
            )

            # Register the tool
            self._tools[name] = tool_def
            self._categories[category].append(name)

            logger.info(f"Registered tool '{name}' in category {category.value}")

            # Return wrapped function that includes middleware
            @wraps(func)
            async def wrapper(*args, **kwargs):
                # Apply middleware
                for middleware in self._middleware:
                    kwargs = await middleware(name, kwargs)

                # Execute function
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)

                return result

            return wrapper

        return decorator

    def add_middleware(self, middleware: Callable):
        """
        Add middleware to be applied to all tool executions.
        Middleware should be async and accept (tool_name, kwargs) and return modified kwargs.
        """
        self._middleware.append(middleware)

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Get a tool definition by name"""
        return self._tools.get(name)

    def list_tools(self, category: Optional[ToolCategory] = None) -> List[ToolDefinition]:
        """List all tools, optionally filtered by category"""
        if category:
            tool_names = self._categories.get(category, [])
            return [self._tools[name] for name in tool_names]
        return list(self._tools.values())

    def get_openai_schemas(
        self, categories: Optional[List[ToolCategory]] = None
    ) -> List[Dict[str, Any]]:
        """Get OpenAI function schemas for tools"""
        tools = self.list_tools()
        if categories:
            tools = [t for t in tools if t.category in categories]
        return [tool.to_openai_schema() for tool in tools]

    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Execute a tool by name with given arguments"""
        tool = self.get_tool(name)
        if not tool:
            raise ValueError(f"Tool '{name}' not found")

        # Validate arguments using Pydantic
        model_class = tool.create_pydantic_model()
        try:
            validated_args = model_class(**arguments)
        except Exception as e:
            raise ValueError(f"Invalid arguments for tool '{name}': {e}")

        # Execute the tool function
        try:
            if asyncio.iscoroutinefunction(tool.function):
                result = await tool.function(**validated_args.model_dump())
            else:
                result = tool.function(**validated_args.model_dump())

            logger.info(f"Successfully executed tool '{name}'")
            return result
        except Exception as e:
            logger.error(f"Error executing tool '{name}': {e}")
            raise

    def validate_tool_call(self, name: str, arguments: Dict[str, Any]) -> bool:
        """Validate a tool call without executing it"""
        tool = self.get_tool(name)
        if not tool:
            return False

        try:
            model_class = tool.create_pydantic_model()
            model_class(**arguments)
            return True
        except:
            return False

    def get_tool_documentation(self, name: str) -> Dict[str, Any]:
        """Get detailed documentation for a tool"""
        tool = self.get_tool(name)
        if not tool:
            return {}

        return {
            "name": tool.name,
            "description": tool.description,
            "category": tool.category.value,
            "parameters": [
                {
                    "name": p.name,
                    "type": p.type,
                    "description": p.description,
                    "required": p.required,
                    "default": p.default,
                    "enum": p.enum,
                }
                for p in tool.parameters
            ],
            "returns": tool.returns,
            "examples": tool.examples,
            "schema": tool.to_openai_schema(),
        }

    def export_registry(self) -> Dict[str, Any]:
        """Export the entire registry as a dictionary"""
        return {
            "tools": {name: self.get_tool_documentation(name) for name in self._tools},
            "categories": {cat.value: self._categories[cat] for cat in ToolCategory},
        }

    def import_tools_from_module(self, module):
        """Import all registered tools from a module"""
        # This is handled automatically by decorators
        pass


# Global registry instance
tool_registry = ToolRegistry()


# Middleware example: logging
async def logging_middleware(tool_name: str, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Log all tool executions"""
    logger.debug(f"Executing tool '{tool_name}' with args: {list(kwargs.keys())}")
    return kwargs


# Middleware example: parameter validation
async def validation_middleware(tool_name: str, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Additional parameter validation"""
    # Add any custom validation logic here
    return kwargs


# Add default middleware
tool_registry.add_middleware(logging_middleware)
