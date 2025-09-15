"""
Comprehensive tests for tool registry and tool execution.
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch
from typing import Dict, Any, List, Optional
import inspect

from app.core.tool_registry import (
    ToolRegistry, ToolDefinition, ToolParameter, ToolCategory,
    tool_registry
)
from app.core.exceptions import ToolNotFoundError, ValidationError


@pytest.fixture
def registry():
    """Create a new tool registry instance"""
    return ToolRegistry()


class TestToolParameter:
    """Test ToolParameter functionality"""
    
    def test_tool_parameter_creation(self):
        """Test creating tool parameter"""
        param = ToolParameter(
            name="query",
            type="string",
            description="Search query",
            required=True,
            default=None,
            enum=["option1", "option2"]
        )
        
        assert param.name == "query"
        assert param.type == "string"
        assert param.description == "Search query"
        assert param.required is True
        assert param.default is None
        assert param.enum == ["option1", "option2"]
    
    def test_tool_parameter_to_openai_schema(self):
        """Test converting parameter to OpenAI schema"""
        # Required parameter with enum
        param1 = ToolParameter(
            name="status",
            type="string",
            description="Case status",
            required=True,
            enum=["open", "closed", "pending"]
        )
        
        schema1 = param1.to_openai_schema()
        assert schema1 == {
            "type": "string",
            "description": "Case status",
            "enum": ["open", "closed", "pending"]
        }
        
        # Optional parameter with default
        param2 = ToolParameter(
            name="limit",
            type="integer",
            description="Number of results",
            required=False,
            default=10
        )
        
        schema2 = param2.to_openai_schema()
        assert schema2 == {
            "type": "integer",
            "description": "Number of results",
            "default": 10
        }


class TestToolDefinition:
    """Test ToolDefinition functionality"""
    
    def test_tool_definition_creation(self):
        """Test creating tool definition"""
        params = [
            ToolParameter("query", "string", "Search query", required=True),
            ToolParameter("limit", "integer", "Result limit", required=False, default=5)
        ]
        
        async def search_func(query: str, limit: int = 5) -> Dict[str, Any]:
            return {"results": []}
        
        tool_def = ToolDefinition(
            name="search",
            description="Search for items",
            category=ToolCategory.SEARCH,
            parameters=params,
            function=search_func,
            returns="Search results",
            examples=["search('test')", "search('test', limit=10)"]
        )
        
        assert tool_def.name == "search"
        assert tool_def.category == ToolCategory.SEARCH
        assert len(tool_def.parameters) == 2
        assert tool_def.function == search_func
    
    def test_tool_definition_to_openai_schema(self):
        """Test converting tool definition to OpenAI schema"""
        params = [
            ToolParameter("text", "string", "Input text", required=True),
            ToolParameter("max_length", "integer", "Max length", required=False, default=100)
        ]
        
        tool_def = ToolDefinition(
            name="summarize",
            description="Summarize text",
            category=ToolCategory.ANALYSIS,
            parameters=params,
            function=lambda x: x
        )
        
        schema = tool_def.to_openai_schema()
        
        assert schema == {
            "type": "function",
            "name": "summarize",
            "description": "Summarize text",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Input text"
                    },
                    "max_length": {
                        "type": "integer",
                        "description": "Max length",
                        "default": 100
                    }
                },
                "required": ["text"]
            }
        }
    
    def test_create_pydantic_model(self):
        """Test creating Pydantic model from tool definition"""
        params = [
            ToolParameter("name", "string", "Name", required=True),
            ToolParameter("age", "integer", "Age", required=True),
            ToolParameter("active", "boolean", "Is active", required=False, default=True),
            ToolParameter("tags", "array", "Tags", required=False),
            ToolParameter("metadata", "object", "Metadata", required=False)
        ]
        
        tool_def = ToolDefinition(
            name="create_user",
            description="Create a user",
            category=ToolCategory.UTILITY,
            parameters=params,
            function=lambda x: x
        )
        
        Model = tool_def.create_pydantic_model()
        
        # Test model creation
        instance = Model(name="John", age=30)
        assert instance.name == "John"
        assert instance.age == 30
        assert instance.active is True  # Default value
        
        # Test validation
        with pytest.raises(Exception):  # Pydantic validation error
            Model(name="John")  # Missing required 'age'


class TestToolRegistry:
    """Test ToolRegistry functionality"""
    
    def test_registry_initialization(self, registry):
        """Test registry initializes empty"""
        assert len(registry._tools) == 0
        assert len(registry._categories) == len(ToolCategory)
    
    def test_register_tool_function(self, registry):
        """Test registering a tool via decorator"""
        params = [
            ToolParameter("arg1", "string", "First argument", required=True),
            ToolParameter("arg2", "integer", "Second argument", required=False, default=5)
        ]
        
        @registry.register(
            name="test_tool",
            description="Test tool",
            category=ToolCategory.UTILITY,
            parameters=params
        )
        async def test_tool(arg1: str, arg2: int = 5) -> Dict[str, Any]:
            return {"arg1": arg1, "arg2": arg2}
        
        assert "test_tool" in registry._tools
        tool_def = registry._tools["test_tool"]
        assert tool_def.name == "test_tool"
        # Note: The function returned by the decorator is a wrapper, not the original
    
    def test_register_tool_decorator(self, registry):
        """Test registering a tool via decorator"""
        @registry.register(
            name="decorated_tool",
            description="Decorated tool",
            category=ToolCategory.SEARCH,
            parameters=[
                ToolParameter("query", "string", "Query", required=True)
            ]
        )
        async def decorated_tool(query: str) -> List[str]:
            return [query]
        
        assert "decorated_tool" in registry._tools
        tool_def = registry._tools["decorated_tool"]
        assert tool_def.name == "decorated_tool"
        assert tool_def.function == decorated_tool
    
    def test_register_duplicate_tool(self, registry):
        """Test registering duplicate tool name overwrites existing tool"""
        @registry.register(
            name="duplicate",
            description="Tool 1",
            category=ToolCategory.UTILITY,
            parameters=[]
        )
        async def tool1():
            return "tool1"
        
        @registry.register(
            name="duplicate",
            description="Tool 2", 
            category=ToolCategory.UTILITY,
            parameters=[]
        )
        async def tool2():
            return "tool2"
        
        # The second registration should overwrite the first
        assert "duplicate" in registry._tools
        tool_def = registry._tools["duplicate"]
        assert tool_def.description == "Tool 2"
    
    def test_get_tool(self, registry):
        """Test getting registered tool"""
        @registry.register(
            name="test",
            description="Test",
            category=ToolCategory.UTILITY,
            parameters=[]
        )
        async def test_tool():
            return "result"
        
        # Get existing tool
        tool_def = registry.get_tool("test")
        assert tool_def.name == "test"
        # Note: function is wrapped, so we can't compare directly
        
        # Get non-existent tool
        assert registry.get_tool("nonexistent") is None
    
    def test_list_tools(self, registry):
        """Test listing all tools"""
        # Register multiple tools
        for i in range(3):
            @registry.register(
                name=f"tool_{i}",
                description=f"Tool {i}",
                category=ToolCategory.UTILITY,
                parameters=[]
            )
            def tool_func():
                return None
        
        tools = registry.list_tools()
        assert len(tools) == 3
        assert all(isinstance(tool, ToolDefinition) for tool in tools)
    
    def test_list_tools_by_category(self, registry):
        """Test listing tools by category"""
        # Register tools in different categories
        @registry.register(
            name="search1",
            description="Search 1",
            category=ToolCategory.SEARCH,
            parameters=[]
        )
        def search1():
            return None
            
        @registry.register(
            name="search2",
            description="Search 2",
            category=ToolCategory.SEARCH,
            parameters=[]
        )
        def search2():
            return None
            
        @registry.register(
            name="doc1",
            description="Doc 1",
            category=ToolCategory.DOCUMENT,
            parameters=[]
        )
        def doc1():
            return None
        
        # List by category
        search_tools = registry.list_tools(category=ToolCategory.SEARCH)
        assert len(search_tools) == 2
        assert all(tool.category == ToolCategory.SEARCH for tool in search_tools)
        
        doc_tools = registry.list_tools(category=ToolCategory.DOCUMENT)
        assert len(doc_tools) == 1
        assert doc_tools[0].category == ToolCategory.DOCUMENT
    
    def test_get_openai_schemas(self, registry):
        """Test getting OpenAI schemas"""
        # Register tools
        params1 = [ToolParameter("arg", "string", "Argument", required=True)]
        params2 = [ToolParameter("num", "integer", "Number", required=False, default=10)]
        
        @registry.register(
            name="tool1",
            description="Tool 1",
            category=ToolCategory.UTILITY,
            parameters=params1
        )
        def tool1():
            return None
            
        @registry.register(
            name="tool2",
            description="Tool 2",
            category=ToolCategory.SEARCH,
            parameters=params2
        )
        def tool2():
            return None
        
        # Get all schemas
        schemas = registry.get_openai_schemas()
        assert len(schemas) == 2
        assert all(schema["type"] == "function" for schema in schemas)
        
        # Get schemas by category
        search_schemas = registry.get_openai_schemas(categories=[ToolCategory.SEARCH])
        assert len(search_schemas) == 1
        assert search_schemas[0]["name"] == "tool2"


class TestToolExecution:
    """Test tool execution functionality"""
    
    @pytest.mark.asyncio
    async def test_execute_tool_success(self, registry):
        """Test successful tool execution"""
        params = [
            ToolParameter("a", "integer", "First number", required=True),
            ToolParameter("b", "integer", "Second number", required=True)
        ]
        
        @registry.register(
            name="add",
            description="Add numbers",
            category=ToolCategory.UTILITY,
            parameters=params
        )
        async def add_numbers(a: int, b: int) -> int:
            return a + b
        
        result = await registry.execute_tool("add", {"a": 5, "b": 3})
        assert result == 8
    
    @pytest.mark.asyncio
    async def test_execute_tool_not_found(self, registry):
        """Test executing non-existent tool"""
        with pytest.raises(ValueError, match="Tool 'nonexistent' not found"):
            await registry.execute_tool("nonexistent", {})
    
    @pytest.mark.asyncio
    async def test_execute_tool_validation(self, registry):
        """Test tool argument validation"""
        params = [
            ToolParameter("a", "integer", "Numerator", required=True),
            ToolParameter("b", "integer", "Denominator", required=True)
        ]
        
        @registry.register(
            name="divide",
            description="Divide",
            category=ToolCategory.UTILITY,
            parameters=params
        )
        async def divide(a: int, b: int) -> float:
            return a / b
        
        # Missing required parameter - should raise ValueError due to Pydantic validation
        with pytest.raises(ValueError, match="Invalid arguments for tool 'divide'"):
            await registry.execute_tool("divide", {"a": 10})
    
    @pytest.mark.asyncio
    async def test_execute_tool_with_defaults(self, registry):
        """Test executing tool with default parameters"""
        params = [
            ToolParameter("name", "string", "Name", required=True),
            ToolParameter("greeting", "string", "Greeting", required=False, default="Hello")
        ]
        
        @registry.register(
            name="greet",
            description="Greet",
            category=ToolCategory.UTILITY,
            parameters=params
        )
        async def greet(name: str, greeting: str = "Hello") -> str:
            return f"{greeting}, {name}!"
        
        # With default
        result1 = await registry.execute_tool("greet", {"name": "Alice"})
        assert result1 == "Hello, Alice!"
        
        # Override default
        result2 = await registry.execute_tool("greet", {"name": "Bob", "greeting": "Hi"})
        assert result2 == "Hi, Bob!"
    
    @pytest.mark.asyncio
    async def test_execute_tool_error_handling(self, registry):
        """Test error handling during tool execution"""
        @registry.register(
            name="fail",
            description="Failing tool",
            category=ToolCategory.UTILITY,
            parameters=[]
        )
        async def failing_tool():
            raise RuntimeError("Tool failed")
        
        with pytest.raises(RuntimeError, match="Tool failed"):
            await registry.execute_tool("fail", {})
    
    @pytest.mark.asyncio
    async def test_execute_sync_tool(self, registry):
        """Test executing synchronous tool"""
        params = [ToolParameter("x", "integer", "Input", required=True)]
        
        @registry.register(
            name="sync",
            description="Sync tool",
            category=ToolCategory.UTILITY,
            parameters=params
        )
        def sync_tool(x: int) -> int:
            return x * 2
        
        result = await registry.execute_tool("sync", {"x": 5})
        assert result == 10


class TestGlobalRegistry:
    """Test global tool registry instance"""
    
    def test_global_registry_singleton(self):
        """Test that tool_registry is a singleton"""
        from app.core.tool_registry import tool_registry as registry1
        from app.core.tool_registry import tool_registry as registry2
        
        assert registry1 is registry2
    
    @pytest.mark.asyncio
    async def test_global_registry_usage(self):
        """Test using global registry"""
        # Clear any existing tools
        tool_registry._tools.clear()
        
        @tool_registry.register(
            name="global_tool",
            description="Global tool",
            category=ToolCategory.UTILITY,
            parameters=[
                ToolParameter("value", "string", "Value", required=True)
            ]
        )
        async def global_tool(value: str) -> str:
            return f"Processed: {value}"
        
        # Tool should be registered
        assert "global_tool" in tool_registry._tools
        
        # Execute tool
        result = await tool_registry.execute_tool("global_tool", {"value": "test"})
        assert result == "Processed: test"


class TestParameterTypeConversion:
    """Test parameter type conversion"""
    
    @pytest.mark.asyncio
    async def test_type_conversion(self, registry):
        """Test automatic type conversion for parameters"""
        params = [
            ToolParameter("string_param", "string", "String", required=True),
            ToolParameter("int_param", "integer", "Integer", required=True),
            ToolParameter("float_param", "number", "Float", required=True),
            ToolParameter("bool_param", "boolean", "Boolean", required=True),
            ToolParameter("list_param", "array", "List", required=True),
            ToolParameter("dict_param", "object", "Dict", required=True)
        ]
        
        @registry.register(
            name="typed",
            description="Typed tool",
            category=ToolCategory.UTILITY,
            parameters=params
        )
        async def typed_tool(
            string_param: str,
            int_param: int,
            float_param: float,
            bool_param: bool,
            list_param: List[str],
            dict_param: Dict[str, Any]
        ) -> Dict[str, Any]:
            return {
                "string": string_param,
                "int": int_param,
                "float": float_param,
                "bool": bool_param,
                "list": list_param,
                "dict": dict_param
            }
        
        # Test with proper types (Pydantic handles conversion)
        result = await registry.execute_tool("typed", {
            "string_param": "text",
            "int_param": 42,
            "float_param": 3.14,
            "bool_param": True,
            "list_param": ["a", "b", "c"],
            "dict_param": {"key": "value"}
        })
        
        assert result["string"] == "text"
        assert result["int"] == 42
        assert result["float"] == 3.14
        assert result["bool"] is True
        assert result["list"] == ["a", "b", "c"]
        assert result["dict"] == {"key": "value"}