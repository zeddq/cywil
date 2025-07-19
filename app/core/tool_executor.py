"""
Tool execution with circuit breaker pattern and retry logic.
"""
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
import asyncio
import logging
from functools import wraps
import json
from fastapi import Request
from typing import Annotated
from fastapi import Depends

from .config_service import get_config, ConfigService
from .tool_registry import tool_registry
from .exceptions import (
    ToolExecutionError,
    ToolNotFoundError,
    ServiceUnavailableError,
    ValidationError
)
from .service_interface import ServiceInterface, HealthCheckResult, ServiceStatus

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"      # Failing, reject calls
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker"""
    failure_threshold: int = 5
    recovery_timeout: timedelta = timedelta(seconds=60)
    success_threshold: int = 3
    timeout: timedelta = timedelta(seconds=30)


@dataclass
class ToolMetrics:
    """Metrics for tool execution"""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    total_duration_ms: float = 0
    last_failure: Optional[datetime] = None
    last_success: Optional[datetime] = None
    
    @property
    def average_duration_ms(self) -> float:
        """Calculate average execution duration"""
        if self.successful_calls == 0:
            return 0
        return self.total_duration_ms / self.successful_calls
    
    @property
    def failure_rate(self) -> float:
        """Calculate failure rate"""
        if self.total_calls == 0:
            return 0
        return self.failed_calls / self.total_calls


class CircuitBreaker:
    """Circuit breaker for tool execution"""
    
    def __init__(self, name: str, config: CircuitBreakerConfig):
        self.name = name
        self.config = config
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.metrics = ToolMetrics()
        
    def can_execute(self) -> bool:
        """Check if execution is allowed"""
        if self.state == CircuitState.CLOSED:
            return True
            
        elif self.state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if self.last_failure_time and \
               datetime.now() - self.last_failure_time > self.config.recovery_timeout:
                logger.info(f"Circuit breaker {self.name} transitioning to HALF_OPEN")
                self.state = CircuitState.HALF_OPEN
                self.success_count = 0
                return True
            return False
            
        else:  # HALF_OPEN
            return True
    
    def record_success(self, duration_ms: float):
        """Record successful execution"""
        self.metrics.total_calls += 1
        self.metrics.successful_calls += 1
        self.metrics.total_duration_ms += duration_ms
        self.metrics.last_success = datetime.now()
        
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.config.success_threshold:
                logger.info(f"Circuit breaker {self.name} recovered, transitioning to CLOSED")
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                
    def record_failure(self, error: Exception):
        """Record failed execution"""
        self.metrics.total_calls += 1
        self.metrics.failed_calls += 1
        self.metrics.last_failure = datetime.now()
        self.last_failure_time = datetime.now()
        
        if self.state == CircuitState.CLOSED:
            self.failure_count += 1
            if self.failure_count >= self.config.failure_threshold:
                logger.warning(f"Circuit breaker {self.name} tripped, transitioning to OPEN")
                self.state = CircuitState.OPEN
                
        elif self.state == CircuitState.HALF_OPEN:
            # Single failure in half-open state reopens circuit
            logger.warning(f"Circuit breaker {self.name} failed during recovery, reopening")
            self.state = CircuitState.OPEN
            self.failure_count = 0


class RetryConfig:
    """Configuration for retry logic"""
    
    def __init__(self, 
                 max_retries: int = 3,
                 initial_delay: float = 1.0,
                 max_delay: float = 60.0,
                 exponential_base: float = 2.0,
                 jitter: bool = True):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
    
    def get_delay(self, attempt: int) -> float:
        """Calculate delay for retry attempt"""
        delay = min(
            self.initial_delay * (self.exponential_base ** attempt),
            self.max_delay
        )
        
        if self.jitter:
            # Add random jitter (±25%)
            import random
            jitter_range = delay * 0.25
            delay += random.uniform(-jitter_range, jitter_range)
            
        return max(0, delay)


class ToolExecutor(ServiceInterface):
    """
    Executes tools with circuit breaker pattern, retry logic, and monitoring.
    """
    
    def __init__(self, config_service: ConfigService):
        super().__init__("ToolExecutor")
        self._config = config_service.config
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._default_breaker_config = CircuitBreakerConfig()
        self._default_retry_config = RetryConfig()
        self._middleware: List[Callable] = []
        
    async def _initialize_impl(self) -> None:
        """Initialize tool executor"""
        # Create circuit breakers for registered tools
        for tool in tool_registry.list_tools():
            self._circuit_breakers[tool.name] = CircuitBreaker(
                tool.name,
                self._default_breaker_config
            )
        logger.info(f"Initialized {len(self._circuit_breakers)} circuit breakers")
        
    async def _shutdown_impl(self) -> None:
        """Cleanup resources"""
        pass
        
    async def _health_check_impl(self) -> HealthCheckResult:
        """Check executor health"""
        details = {
            "total_tools": len(self._circuit_breakers),
            "open_circuits": sum(1 for cb in self._circuit_breakers.values() 
                               if cb.state == CircuitState.OPEN),
            "half_open_circuits": sum(1 for cb in self._circuit_breakers.values() 
                                    if cb.state == CircuitState.HALF_OPEN)
        }
        
        # Calculate overall metrics
        total_calls = sum(cb.metrics.total_calls for cb in self._circuit_breakers.values())
        failed_calls = sum(cb.metrics.failed_calls for cb in self._circuit_breakers.values())
        
        details["total_executions"] = total_calls
        details["failure_rate"] = failed_calls / total_calls if total_calls > 0 else 0
        
        # Health is degraded if too many circuits are open
        open_ratio = details["open_circuits"] / details["total_tools"] if details["total_tools"] > 0 else 0
        
        if open_ratio > 0.5:
            status = ServiceStatus.UNHEALTHY
            message = f"{details['open_circuits']} circuits open"
        elif open_ratio > 0.2:
            status = ServiceStatus.DEGRADED
            message = f"{details['open_circuits']} circuits open"
        else:
            status = ServiceStatus.HEALTHY
            message = "Tool executor is healthy"
            
        return HealthCheckResult(
            status=status,
            message=message,
            details=details
        )
    
    def add_middleware(self, middleware: Callable):
        """Add middleware for tool execution"""
        self._middleware.append(middleware)
        
    def configure_circuit_breaker(self, tool_name: str, config: CircuitBreakerConfig):
        """Configure circuit breaker for specific tool"""
        if tool_name in self._circuit_breakers:
            self._circuit_breakers[tool_name].config = config
        else:
            self._circuit_breakers[tool_name] = CircuitBreaker(tool_name, config)
            
    def configure_retry(self, config: RetryConfig):
        """Configure default retry behavior"""
        self._default_retry_config = config
        
    async def execute_tool(self, 
                          name: str, 
                          arguments: Dict[str, Any],
                          retry_config: Optional[RetryConfig] = None) -> Any:
        """
        Execute a tool with circuit breaker and retry logic.
        
        Args:
            name: Tool name
            arguments: Tool arguments
            retry_config: Optional retry configuration override
            
        Returns:
            Tool execution result
            
        Raises:
            ToolNotFoundError: Tool not found
            ServiceUnavailableError: Circuit breaker is open
            ToolExecutionError: Tool execution failed after retries
        """
        # Get circuit breaker
        circuit_breaker = self._circuit_breakers.get(name)
        if not circuit_breaker:
            # Create default circuit breaker for unknown tools
            circuit_breaker = CircuitBreaker(name, self._default_breaker_config)
            self._circuit_breakers[name] = circuit_breaker
            
        # Check circuit breaker
        if not circuit_breaker.can_execute():
            raise ServiceUnavailableError(
                f"Tool '{name}' is currently unavailable (circuit open)",
                {"tool": name, "state": circuit_breaker.state.value}
            )
            
        # Get retry configuration
        retry_config = retry_config or self._default_retry_config
        
        # Execute with retries
        last_error = None
        for attempt in range(retry_config.max_retries + 1):
            try:
                # Execute tool
                start_time = asyncio.get_event_loop().time()
                result = await self._execute_with_middleware(name, arguments)
                duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                
                # Record success
                circuit_breaker.record_success(duration_ms)
                
                return result
                
            except (ToolNotFoundError, ValidationError) as e:
                # Don't retry for these errors
                circuit_breaker.record_failure(e)
                raise
                
            except Exception as e:
                last_error = e
                circuit_breaker.record_failure(e)
                
                if attempt < retry_config.max_retries:
                    delay = retry_config.get_delay(attempt)
                    logger.warning(
                        f"Tool '{name}' failed (attempt {attempt + 1}/{retry_config.max_retries + 1}), "
                        f"retrying in {delay:.1f}s: {str(e)}"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Tool '{name}' failed after {retry_config.max_retries + 1} attempts")
                    
        # All retries exhausted
        raise ToolExecutionError(
            name, 
            f"Failed after {retry_config.max_retries + 1} attempts: {str(last_error)}",
            call_id=arguments.get("call_id")
        )
        
    async def _execute_with_middleware(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Execute tool with middleware chain"""
        # Build execution chain
        async def execute():
            return await tool_registry.execute_tool(name, arguments)
            
        # Apply middleware in reverse order
        chain = execute
        for middleware in reversed(self._middleware):
            chain = middleware(chain, name, arguments)
            
        return await chain
        
    def get_metrics(self, tool_name: Optional[str] = None) -> Dict[str, Any]:
        """Get execution metrics"""
        if tool_name:
            cb = self._circuit_breakers.get(tool_name)
            if not cb:
                return {}
                
            return {
                "tool": tool_name,
                "state": cb.state.value,
                "metrics": {
                    "total_calls": cb.metrics.total_calls,
                    "successful_calls": cb.metrics.successful_calls,
                    "failed_calls": cb.metrics.failed_calls,
                    "failure_rate": cb.metrics.failure_rate,
                    "average_duration_ms": cb.metrics.average_duration_ms,
                    "last_failure": cb.metrics.last_failure.isoformat() if cb.metrics.last_failure else None,
                    "last_success": cb.metrics.last_success.isoformat() if cb.metrics.last_success else None
                }
            }
        else:
            # Aggregate metrics
            total_metrics = ToolMetrics()
            circuit_states = {"closed": 0, "open": 0, "half_open": 0}
            
            for cb in self._circuit_breakers.values():
                total_metrics.total_calls += cb.metrics.total_calls
                total_metrics.successful_calls += cb.metrics.successful_calls
                total_metrics.failed_calls += cb.metrics.failed_calls
                total_metrics.total_duration_ms += cb.metrics.total_duration_ms
                circuit_states[cb.state.value] += 1
                
            return {
                "total_tools": len(self._circuit_breakers),
                "circuit_states": circuit_states,
                "aggregate_metrics": {
                    "total_calls": total_metrics.total_calls,
                    "successful_calls": total_metrics.successful_calls,
                    "failed_calls": total_metrics.failed_calls,
                    "failure_rate": total_metrics.failure_rate,
                    "average_duration_ms": total_metrics.average_duration_ms
                }
            }
            
    def reset_circuit(self, tool_name: str):
        """Manually reset a circuit breaker"""
        cb = self._circuit_breakers.get(tool_name)
        if cb:
            cb.state = CircuitState.CLOSED
            cb.failure_count = 0
            cb.success_count = 0
            logger.info(f"Circuit breaker for '{tool_name}' manually reset")


# Middleware examples
def logging_middleware(next_handler, tool_name: str, arguments: Dict[str, Any]):
    """Middleware that logs tool execution"""
    async def handler():
        logger.info(f"Executing tool '{tool_name}' with args: {list(arguments.keys())}")
        try:
            result = await next_handler()
            logger.info(f"Tool '{tool_name}' completed successfully")
            return result
        except Exception as e:
            logger.error(f"Tool '{tool_name}' failed: {str(e)}")
            raise
    return handler


def timing_middleware(next_handler, tool_name: str, arguments: Dict[str, Any]):
    """Middleware that tracks execution time"""
    async def handler():
        start = asyncio.get_event_loop().time()
        try:
            return await next_handler()
        finally:
            duration = asyncio.get_event_loop().time() - start
            logger.debug(f"Tool '{tool_name}' executed in {duration * 1000:.1f}ms")
    return handler


def validation_middleware(next_handler, tool_name: str, arguments: Dict[str, Any]):
    """Middleware that validates tool arguments"""
    async def handler():
        # Could add custom validation logic here
        if not arguments:
            raise ValidationError(f"Tool '{tool_name}' requires arguments")
        return await next_handler()
    return handler

def get_tool_executor(request: Request) -> ToolExecutor:
    return request.app.state.manager.inject_service(ToolExecutor)

ToolExecutorDep = Annotated[ToolExecutor, Depends(get_tool_executor)]
