"""
Comprehensive tests for ToolExecutor with circuit breaker and retry logic.
"""
import pytest
import asyncio
import logging
from unittest.mock import Mock, AsyncMock, patch, call
from datetime import datetime, timedelta
from typing import Dict, Any

from app.core.tool_executor import (
    ToolExecutor, CircuitBreaker, CircuitState, CircuitBreakerConfig,
    RetryConfig, ToolMetrics, logging_middleware, timing_middleware, validation_middleware
)
from app.core.exceptions import (
    ToolExecutionError, ToolNotFoundError, ServiceUnavailableError, ValidationError
)
from app.core.service_interface import ServiceStatus


@pytest.fixture
def mock_config_service():
    """Mock ConfigService for testing"""
    config_service = Mock()
    config_service.config = Mock()
    return config_service


@pytest.fixture
async def tool_executor(mock_config_service):
    """Create ToolExecutor instance"""
    executor = ToolExecutor(mock_config_service)
    yield executor


@pytest.fixture
def mock_tool_registry():
    """Mock tool registry"""
    registry = Mock()
    
    # Mock tool definitions - fix: ensure tool.name returns string, not Mock
    tools = []
    for name in ["test_tool", "critical_tool", "flaky_tool"]:
        tool = Mock()
        tool.name = name  # Set name attribute directly to return string
        tools.append(tool)
    
    registry.list_tools.return_value = tools
    
    return registry


class TestCircuitBreaker:
    """Test circuit breaker functionality"""
    
    def test_circuit_breaker_initial_state(self):
        """Test circuit breaker starts in CLOSED state"""
        config = CircuitBreakerConfig()
        cb = CircuitBreaker("test", config)
        
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
        assert cb.success_count == 0
        assert cb.can_execute()
    
    def test_circuit_breaker_open_after_failures(self):
        """Test circuit opens after reaching failure threshold"""
        config = CircuitBreakerConfig(failure_threshold=3)
        cb = CircuitBreaker("test", config)
        
        # Record failures
        for i in range(3):
            cb.record_failure(Exception(f"Error {i}"))
        
        assert cb.state == CircuitState.OPEN
        assert cb.failure_count == 3
        assert not cb.can_execute()
        assert cb.metrics.failed_calls == 3
    
    def test_circuit_breaker_recovery_timeout(self):
        """Test circuit moves to HALF_OPEN after recovery timeout"""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout=timedelta(seconds=0.1)
        )
        cb = CircuitBreaker("test", config)
        
        # Open the circuit
        cb.record_failure(Exception("Error 1"))
        cb.record_failure(Exception("Error 2"))
        
        assert cb.state == CircuitState.OPEN
        assert not cb.can_execute()
        
        # Wait for recovery timeout
        import time
        time.sleep(0.2)
        
        # Should transition to HALF_OPEN
        assert cb.can_execute()
        assert cb.state == CircuitState.HALF_OPEN
    
    def test_circuit_breaker_recovery_success(self):
        """Test circuit recovers to CLOSED after success threshold"""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            success_threshold=2,
            recovery_timeout=timedelta(seconds=0)
        )
        cb = CircuitBreaker("test", config)
        
        # Open and move to HALF_OPEN
        cb.record_failure(Exception("Error 1"))
        cb.record_failure(Exception("Error 2"))
        cb.state = CircuitState.HALF_OPEN  # Force state
        
        # Record successes
        cb.record_success(100.0)
        assert cb.state == CircuitState.HALF_OPEN
        
        cb.record_success(150.0)
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
    
    def test_circuit_breaker_reopen_on_half_open_failure(self):
        """Test circuit reopens on failure during HALF_OPEN"""
        config = CircuitBreakerConfig()
        cb = CircuitBreaker("test", config)
        
        cb.state = CircuitState.HALF_OPEN
        cb.record_failure(Exception("Error"))
        
        assert cb.state == CircuitState.OPEN
        assert cb.failure_count == 0  # Reset on reopen
    
    def test_circuit_breaker_metrics(self):
        """Test circuit breaker metrics tracking"""
        config = CircuitBreakerConfig()
        cb = CircuitBreaker("test", config)
        
        # Record mixed results
        cb.record_success(100.0)
        cb.record_success(200.0)
        cb.record_failure(Exception("Error"))
        cb.record_success(150.0)
        
        metrics = cb.metrics
        assert metrics.total_calls == 4
        assert metrics.successful_calls == 3
        assert metrics.failed_calls == 1
        assert metrics.average_duration_ms == 150.0  # (100+200+150)/3
        assert metrics.failure_rate == 0.25  # 1/4


class TestRetryConfig:
    """Test retry configuration and delay calculation"""
    
    def test_exponential_backoff(self):
        """Test exponential backoff calculation"""
        config = RetryConfig(
            initial_delay=1.0,
            exponential_base=2.0,
            max_delay=10.0,
            jitter=False
        )
        
        assert config.get_delay(0) == 1.0  # 1 * 2^0
        assert config.get_delay(1) == 2.0  # 1 * 2^1
        assert config.get_delay(2) == 4.0  # 1 * 2^2
        assert config.get_delay(3) == 8.0  # 1 * 2^3
        assert config.get_delay(4) == 10.0  # Capped at max_delay
    
    def test_jitter_addition(self):
        """Test jitter adds randomness to delay"""
        config = RetryConfig(
            initial_delay=1.0,
            jitter=True
        )
        
        delays = [config.get_delay(1) for _ in range(10)]
        
        # All delays should be different due to jitter
        assert len(set(delays)) > 1
        
        # All delays should be within expected range (2.0 ± 25%)
        for delay in delays:
            assert 1.5 <= delay <= 2.5


class TestToolExecutorInitialization:
    """Test ToolExecutor initialization"""
    
    @pytest.mark.asyncio
    async def test_initialization(self, tool_executor, mock_tool_registry):
        """Test executor initialization creates circuit breakers"""
        with patch('app.core.tool_executor.tool_registry', mock_tool_registry):
            await tool_executor.initialize()
            
            assert tool_executor._initialized
            assert len(tool_executor._circuit_breakers) == 3
            assert "test_tool" in tool_executor._circuit_breakers
            assert "critical_tool" in tool_executor._circuit_breakers
            assert "flaky_tool" in tool_executor._circuit_breakers


class TestToolExecution:
    """Test tool execution with circuit breaker and retry"""
    
    @pytest.mark.asyncio
    async def test_successful_execution(self, tool_executor, mock_tool_registry):
        """Test successful tool execution"""
        tool_executor._initialized = True
        
        # Mock tool execution
        mock_tool_registry.execute_tool = AsyncMock(return_value={"result": "success"})
        
        with patch('app.core.tool_executor.tool_registry', mock_tool_registry):
            result = await tool_executor.execute_tool("test_tool", {"arg": "value"})
            
            assert result == {"result": "success"}
            mock_tool_registry.execute_tool.assert_called_once_with("test_tool", {"arg": "value"})
            
            # Check metrics
            cb = tool_executor._circuit_breakers["test_tool"]
            assert cb.metrics.successful_calls == 1
            assert cb.metrics.failed_calls == 0
    
    @pytest.mark.asyncio
    async def test_circuit_open_error(self, tool_executor):
        """Test execution fails when circuit is open"""
        tool_executor._initialized = True
        
        # Open the circuit
        cb = CircuitBreaker("test_tool", CircuitBreakerConfig())
        cb.state = CircuitState.OPEN
        tool_executor._circuit_breakers["test_tool"] = cb
        
        with pytest.raises(ServiceUnavailableError) as exc_info:
            await tool_executor.execute_tool("test_tool", {})
        
        assert "currently unavailable" in str(exc_info.value)
        assert exc_info.value.details["state"] == "open"
    
    @pytest.mark.asyncio
    async def test_retry_on_failure(self, tool_executor, mock_tool_registry):
        """Test retry logic on transient failures"""
        tool_executor._initialized = True
        tool_executor._default_retry_config = RetryConfig(
            max_retries=2,
            initial_delay=0.01,
            jitter=False
        )
        
        # Mock tool to fail twice then succeed
        call_count = 0
        async def mock_execute(name, args):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception(f"Transient error {call_count}")
            return {"result": "success"}
        
        mock_tool_registry.execute_tool = mock_execute
        
        with patch('app.core.tool_executor.tool_registry', mock_tool_registry):
            result = await tool_executor.execute_tool("test_tool", {})
            
            assert result == {"result": "success"}
            assert call_count == 3
    
    @pytest.mark.asyncio
    async def test_no_retry_on_validation_error(self, tool_executor, mock_tool_registry):
        """Test that validation errors are not retried"""
        tool_executor._initialized = True
        
        # Mock validation error
        mock_tool_registry.execute_tool = AsyncMock(
            side_effect=ValidationError("test_tool", {"field": "required"})
        )
        
        with patch('app.core.tool_executor.tool_registry', mock_tool_registry):
            with pytest.raises(ValidationError):
                await tool_executor.execute_tool("test_tool", {})
            
            # Should only call once (no retry)
            assert mock_tool_registry.execute_tool.call_count == 1
    
    @pytest.mark.asyncio
    async def test_retry_exhaustion(self, tool_executor, mock_tool_registry):
        """Test error when all retries are exhausted"""
        tool_executor._initialized = True
        tool_executor._default_retry_config = RetryConfig(
            max_retries=2,
            initial_delay=0.01
        )
        
        # Mock persistent failure
        mock_tool_registry.execute_tool = AsyncMock(side_effect=Exception("Persistent error"))
        
        with patch('app.core.tool_executor.tool_registry', mock_tool_registry):
            with pytest.raises(ToolExecutionError) as exc_info:
                await tool_executor.execute_tool("test_tool", {"call_id": "123"})
            
            assert "Failed after 3 attempts" in str(exc_info.value)
            assert exc_info.value.call_id == "123"
            assert mock_tool_registry.execute_tool.call_count == 3


class TestMiddleware:
    """Test middleware functionality"""
    
    @pytest.mark.asyncio
    async def test_middleware_execution_order(self, tool_executor):
        """Test middleware executes in correct order"""
        tool_executor._initialized = True
        
        execution_order = []
        
        def middleware1(next_handler, tool_name, args):
            async def handler():
                execution_order.append("middleware1_before")
                result = await next_handler()
                execution_order.append("middleware1_after")
                return result
            return handler
        
        def middleware2(next_handler, tool_name, args):
            async def handler():
                execution_order.append("middleware2_before")
                result = await next_handler()
                execution_order.append("middleware2_after")
                return result
            return handler
        
        tool_executor.add_middleware(middleware1)
        tool_executor.add_middleware(middleware2)
        
        # Mock tool execution
        async def mock_execute(name, args):
            execution_order.append("tool_execute")
            return {"result": "success"}
        
        with patch('app.core.tool_executor.tool_registry.execute_tool', mock_execute):
            await tool_executor.execute_tool("test_tool", {})
        
        # Middleware should execute in reverse order (last added first)
        assert execution_order == [
            "middleware2_before",
            "middleware1_before",
            "tool_execute",
            "middleware1_after",
            "middleware2_after"
        ]
    
    @pytest.mark.asyncio
    async def test_logging_middleware(self, tool_executor, caplog):
        """Test logging middleware functionality"""
        tool_executor._initialized = True
        tool_executor.add_middleware(logging_middleware)
        
        # Mock successful execution
        async def mock_execute(name, args):
            return {"result": "success"}
        
        # Capture the specific logger used by the middleware
        with caplog.at_level(logging.INFO, logger='app.core.tool_executor'):
            with patch('app.core.tool_executor.tool_registry.execute_tool', mock_execute):
                await tool_executor.execute_tool("test_tool", {"arg1": "value1"})
        
        # Check logs
        assert "Executing tool 'test_tool'" in caplog.text
        assert "completed successfully" in caplog.text
    
    @pytest.mark.asyncio
    async def test_validation_middleware(self, tool_executor):
        """Test validation middleware"""
        tool_executor._initialized = True
        tool_executor.add_middleware(validation_middleware)
        
        with pytest.raises(ValidationError) as exc_info:
            await tool_executor.execute_tool("test_tool", {})
        
        # ValidationError message is "Validation failed", details contain "Tool requires arguments"
        assert "Validation failed" in str(exc_info.value)


class TestMetrics:
    """Test metrics collection and reporting"""
    
    @pytest.mark.asyncio
    async def test_individual_tool_metrics(self, tool_executor):
        """Test metrics for individual tool"""
        tool_executor._initialized = True
        
        # Create circuit breaker with some metrics
        cb = CircuitBreaker("test_tool", CircuitBreakerConfig())
        cb.record_success(100.0)
        cb.record_success(200.0)
        cb.record_failure(Exception("Error"))
        tool_executor._circuit_breakers["test_tool"] = cb
        
        metrics = tool_executor.get_metrics("test_tool")
        
        assert metrics["tool"] == "test_tool"
        assert metrics["state"] == "closed"
        assert metrics["metrics"]["total_calls"] == 3
        assert metrics["metrics"]["successful_calls"] == 2
        assert metrics["metrics"]["failed_calls"] == 1
        assert metrics["metrics"]["failure_rate"] == 1/3
        assert metrics["metrics"]["average_duration_ms"] == 150.0
    
    @pytest.mark.asyncio
    async def test_aggregate_metrics(self, tool_executor):
        """Test aggregate metrics across all tools"""
        tool_executor._initialized = True
        
        # Create multiple circuit breakers
        cb1 = CircuitBreaker("tool1", CircuitBreakerConfig())
        cb1.record_success(100.0)
        cb1.state = CircuitState.CLOSED
        
        cb2 = CircuitBreaker("tool2", CircuitBreakerConfig())
        cb2.record_failure(Exception("Error"))
        cb2.state = CircuitState.OPEN
        
        cb3 = CircuitBreaker("tool3", CircuitBreakerConfig())
        cb3.state = CircuitState.HALF_OPEN
        
        tool_executor._circuit_breakers = {
            "tool1": cb1,
            "tool2": cb2,
            "tool3": cb3
        }
        
        metrics = tool_executor.get_metrics()
        
        assert metrics["total_tools"] == 3
        assert metrics["circuit_states"]["closed"] == 1
        assert metrics["circuit_states"]["open"] == 1
        assert metrics["circuit_states"]["half_open"] == 1
        assert metrics["aggregate_metrics"]["total_calls"] == 2
        assert metrics["aggregate_metrics"]["successful_calls"] == 1
        assert metrics["aggregate_metrics"]["failed_calls"] == 1


class TestHealthCheck:
    """Test health check functionality"""
    
    @pytest.mark.asyncio
    async def test_healthy_state(self, tool_executor):
        """Test health check with all circuits closed"""
        tool_executor._initialized = True
        
        # Create healthy circuit breakers
        for name in ["tool1", "tool2", "tool3"]:
            cb = CircuitBreaker(name, CircuitBreakerConfig())
            tool_executor._circuit_breakers[name] = cb
        
        result = await tool_executor.health_check()
        
        assert result.status == ServiceStatus.HEALTHY
        assert result.details["open_circuits"] == 0
        assert result.details["total_tools"] == 3
    
    @pytest.mark.asyncio
    async def test_degraded_state(self, tool_executor):
        """Test health check with some circuits open"""
        tool_executor._initialized = True
        
        # Create mix of states (30% open)
        for i in range(10):
            cb = CircuitBreaker(f"tool{i}", CircuitBreakerConfig())
            if i < 3:
                cb.state = CircuitState.OPEN
            tool_executor._circuit_breakers[f"tool{i}"] = cb
        
        result = await tool_executor.health_check()
        
        assert result.status == ServiceStatus.DEGRADED
        assert result.details["open_circuits"] == 3
        assert "3 circuits open" in result.message
    
    @pytest.mark.asyncio
    async def test_unhealthy_state(self, tool_executor):
        """Test health check with majority circuits open"""
        tool_executor._initialized = True
        
        # Create mostly open circuits (60% open)
        for i in range(10):
            cb = CircuitBreaker(f"tool{i}", CircuitBreakerConfig())
            if i < 6:
                cb.state = CircuitState.OPEN
            tool_executor._circuit_breakers[f"tool{i}"] = cb
        
        result = await tool_executor.health_check()
        
        assert result.status == ServiceStatus.UNHEALTHY
        assert result.details["open_circuits"] == 6


class TestManualOperations:
    """Test manual circuit breaker operations"""
    
    def test_manual_circuit_reset(self, tool_executor):
        """Test manual circuit reset"""
        tool_executor._initialized = True
        
        # Create open circuit
        cb = CircuitBreaker("test_tool", CircuitBreakerConfig())
        cb.state = CircuitState.OPEN
        cb.failure_count = 5
        tool_executor._circuit_breakers["test_tool"] = cb
        
        # Reset circuit
        tool_executor.reset_circuit("test_tool")
        
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
        assert cb.success_count == 0
    
    def test_configure_circuit_breaker(self, tool_executor):
        """Test configuring circuit breaker for specific tool"""
        custom_config = CircuitBreakerConfig(
            failure_threshold=10,
            recovery_timeout=timedelta(minutes=5)
        )
        
        tool_executor.configure_circuit_breaker("critical_tool", custom_config)
        
        cb = tool_executor._circuit_breakers["critical_tool"]
        assert cb.config.failure_threshold == 10
        assert cb.config.recovery_timeout == timedelta(minutes=5)