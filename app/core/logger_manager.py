"""
Centralized logger configuration and retrieval.
This module provides a simplified interface for setting up and using context-aware loggers.
"""

import logging
import logging.config
import json
import traceback
import asyncio
from functools import wraps
from contextlib import AbstractAsyncContextManager
import uuid
from typing import Dict, Any, Optional
from datetime import datetime
import sys
import os
from typing import Callable
import contextlib

from opentelemetry import trace
from opentelemetry.trace import Span, SpanContext
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from starlette.requests import Request
from .tool_executor import ToolExecutor
from .exceptions import ToolExecutionError

service_name: str = "ai-paralegal-backend"

resource = Resource.create({
    "service.name": service_name,
    "service.version": "dev",
})

provider = TracerProvider(resource=resource)
trace.set_tracer_provider(provider)

# ---------------------------------------------------------------------------
# StructuredFormatter – JSON formatter augmented with OTel span context
# ---------------------------------------------------------------------------
class StructuredFormatter(logging.Formatter):
    """
    JSON formatter for structured logging with correlation ID support.
    """
    # default format string can still be overridden when you
    # instantiate the formatter.
    DEFAULT_FMT = "%(asctime)s %(levelname)s [corr=%(correlation_id)s] " \
                  "%(name)s:%(message)s"

    def __init__(self, fmt: str | None = None, datefmt: str | None = None,
                 style: str = "%"):
        super().__init__(fmt or self.DEFAULT_FMT, datefmt=datefmt, style=style)

    def _span_stack(self):
        """
        Return a list of span-ids from current → root, e.g. ["c3", "b2", "a1"]
        """
        stack = []
        span = trace.get_current_span()
        while span:
            if isinstance(span, Span) or issubclass(type(span), Span):
                ctx = span.get_span_context()
                if ctx and ctx.is_valid:
                    stack.append(format(ctx.span_id, "016x"))
            elif isinstance(span, SpanContext):
                if span.is_valid:
                    stack.append(format(span.span_id, "016x"))
            else:
                break

            if hasattr(span, 'parent'):
                span = span.parent  # .parent is a SpanContext or None
            else:
                break
        return "->".join(reversed(stack))

    def format(self, record: logging.LogRecord) -> str:
        # Safeguard: make sure the record has the attributes the
        # format string expects, otherwise logging raises KeyError.
        record.__dict__.setdefault("correlation_id", "∅")
        record.__dict__.setdefault("user_id", "<anon>")
        record.__dict__.setdefault("client_addr", "unknown")
        record.__dict__.setdefault("request_line", "--not found--")
        record.__dict__.setdefault("status_code", "none")
        record.__dict__.setdefault("span_stack", self._span_stack())

        # Example: add a RFC3339 timestamp field.
        record.rfc3339 = datetime.utcnow().isoformat()

        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add extra fields
        if hasattr(record, 'extra_fields'):
            log_data.update(record.extra_fields)
        if hasattr(record, 'user_id'):
            log_data["user_id"] = record.user_id
        if hasattr(record, 'correlation_id'):
            log_data["correlation_id"] = record.correlation_id
        if hasattr(record, 'trace_id'):
            log_data["trace_id"] = record.trace_id
        if hasattr(record, 'client_addr'):
            log_data["client_addr"] = record.client_addr
        if hasattr(record, 'request_line'):
            log_data["request_line"] = record.request_line
        if hasattr(record, 'status_code'):
            log_data["status_code"] = record.status_code

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": traceback.format_exception(*record.exc_info)
            }

        for key, value in log_data.items():
            record.__dict__[key] = value

        # Delegate the actual text formatting to the base class.
        return super().format(record)


# class ContextualLogger(logging.LoggerAdapter):
#     """
#     Logger adapter that automatically includes context variables.
#     """
    
#     def process(self, msg, kwargs):
#         """Add context to log records"""
#         pass


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance wrapped in a contextual adapter.
    """
    logger = logging.getLogger(name)
    return logger

def set_request_id(request_id: str) -> None:
    """Set request ID for the current context"""

def set_user_id(request: Request, user_id: str) -> None:
    """Set user ID for the current context"""
    span = trace.get_current_span()
    if span is not None:
        span.set_attribute("user_id", user_id)
    request.headers["X-User-ID"] = user_id

def log_execution_time(logger: Optional[logging.Logger] = None):
    """
    Decorator that logs function execution time.
    """
    def decorator(func):
        nonlocal logger
        if logger is None:
            logger = get_logger(func.__module__)
        
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = asyncio.get_event_loop().time()
            try:
                result = await func(*args, **kwargs)
                duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                logger.info(
                    f"{func.__name__} completed",
                    extra={
                        "function": func.__name__,
                        "duration_ms": duration_ms,
                        "status": "success"
                    }
                )
                return result
            except Exception as e:
                duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                logger.error(
                    f"{func.__name__} failed",
                    extra={
                        "function": func.__name__,
                        "duration_ms": duration_ms,
                        "status": "error",
                        "error_type": type(e).__name__
                    },
                    exc_info=True
                )
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            import time
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.time() - start_time) * 1000
                logger.info(
                    f"{func.__name__} completed",
                    extra={
                        "function": func.__name__,
                        "duration_ms": duration_ms,
                        "status": "success"
                    }
                )
                return result
            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                logger.error(
                    f"{func.__name__} failed",
                    extra={
                        "function": func.__name__,
                        "duration_ms": duration_ms,
                        "status": "error",
                        "error_type": type(e).__name__
                    },
                    exc_info=True
                )
                raise
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


def log_method_calls(cls):
    """
    Class decorator that logs all method calls with timing.
    """
    for name, method in cls.__dict__.items():
        if callable(method) and not name.startswith('_'):
            setattr(cls, name, log_execution_time()(method))
    return cls


# Structured log entry helpers
def log_tool_execution(
    logger: logging.Logger,
    tool_name: str,
    status: str,
    duration_ms: Optional[float] = None,
    error: Optional[Exception] = None,
    **kwargs
) -> None:
    """Log tool execution with structured data"""
    extra_fields = {
        "event": "tool_execution",
        "tool_name": tool_name,
        "status": status,
        **kwargs
    }
    
    if duration_ms is not None:
        extra_fields["duration_ms"] = duration_ms
    
    if status == "success":
        logger.info(f"Tool {tool_name} executed successfully", extra={"extra_fields": extra_fields})
    else:
        logger.error(
            f"Tool {tool_name} failed: {str(error)}",
            extra={"extra_fields": extra_fields},
            exc_info=error
        )


def log_api_request(
    logger: logging.Logger,
    method: str,
    endpoint: str,
    status_code: Optional[int] = None,
    duration_ms: Optional[float] = None,
    error: Optional[Exception] = None,
    **kwargs
) -> None:
    """Log API request with structured data"""
    extra_fields = {
        "event": "api_request",
        "method": method,
        "endpoint": endpoint,
        **kwargs
    }
    
    if status_code is not None:
        extra_fields["status_code"] = status_code
        span = trace.get_current_span()
        if span:
            span.set_attribute("status_code", status_code)

    if duration_ms is not None:
        extra_fields["duration_ms"] = duration_ms
    
    if error:
        logger.error(
            f"{method} {endpoint} failed",
            extra={"extra_fields": extra_fields},
            exc_info=error
        )
    else:
        logger.info(
            f"{method} {endpoint} - {status_code}",
            extra={"extra_fields": extra_fields}
        )


def log_service_operation(
    logger: logging.Logger,
    service: str,
    operation: str,
    status: str,
    duration_ms: Optional[float] = None,
    **kwargs
) -> None:
    """Log service operation with structured data"""
    extra_fields = {
        "event": "service_operation",
        "service": service,
        "operation": operation,
        "status": status,
        **kwargs
    }
    
    if duration_ms is not None:
        extra_fields["duration_ms"] = duration_ms
    
    level = logging.INFO if status == "success" else logging.ERROR
    logger.log(
        level,
        f"{service}.{operation} - {status}",
        extra={"extra_fields": extra_fields}
    )

@contextlib.contextmanager
def correlation_context(correlation_id: Optional[str] = None):
    """
    Context manager for correlation ID management.
    """
    correlation_id = correlation_id or str(uuid.uuid4())
    
    try:
        yield correlation_id
    finally:
        pass


def get_logging_config(level: str = "INFO", json_format: bool = True) -> Dict[str, Any]:
    """
    Returns a dictionary for Python's logging.config.dictConfig.
    
    Args:
        level: The root logging level, e.g., "INFO", "DEBUG".
        json_format: If True, use a structured JSON formatter. Otherwise, use a human-readable console format.
    """

    structuredjson = {
        "()": StructuredFormatter,
    }
    structured = {
                "()": StructuredFormatter,
                "fmt": "%(asctime)s - [%(correlation_id)s] [trace=%(otelTraceID)s span=%(span_stack)s]"
                    " user_id=%(user_id)s - %(message)s (%(module)s.%(function)s:%(lineno)d)",
            }
    
    formatter = structuredjson if json_format else structured
    
    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": StructuredFormatter,
                "fmt": "%(asctime)s - [%(correlation_id)s] [trace=%(otelTraceID)s span=%(span_stack)s]"
                    " user_id=%(user_id)s - %(message)s (%(module)s.%(function)s:%(lineno)d)",
            },
            "access": {
                "()": StructuredFormatter,
                "fmt":  "%(asctime)s - [%(correlation_id)s] [trace=%(otelTraceID)s span=%(span_stack)s] "
                    "%(client_addr)s user_id=%(user_id)s - %(request_line)s %(status_code)s (%(module)s.%(function)s:%(lineno)d)",
            },
            "structured": formatter,
        },
        "handlers": {
            "default": {
                "formatter": "structured" if json_format else "default",
                "class": "logging.StreamHandler",
                "stream": sys.stdout,
            },
            "access": {
                "formatter": "structured" if json_format else "access",
                "class": "logging.StreamHandler",
                "stream": sys.stdout,
            },
        },
        "loggers": {
            "": {  # Root logger
                "handlers": ["default"],
                "level": level,
            },
            "uvicorn": {
                "handlers": ["default"],
                "level": level,
                "propagate": False,
            },
            "uvicorn.error": {
                "level": level,
            },
            "uvicorn.access": {
                "handlers": ["access"],
                "level": level,
                "propagate": False,
            },
            "app": { # Your application's logger
                "handlers": ["default"],
                "level": level,
                "propagate": False,
            },
        },
    }
    return config


def _copy_custom_attributes(span, record):
    """
    Runs for every LogRecord emitted while a span is current.
    Pick any attributes you want to surface in your logs.
    """
    if span:
        record.user_id  = span.attributes.get("user_id", "<anon>")
        record.correlation_id = span.attributes.get("correlation_id", "<none>")
        record.client_addr = span.attributes.get("client_addr", "unknown")
        record.request_line = span.attributes.get("request_line", "--not found--")
        record.status_code = span.attributes.get("status_code", "none")

LoggingInstrumentor().instrument(
    # set basicConfig() for you and inject otelTraceID / otelSpanID automatically
    set_logging_format=False,
    # logging_format= "%(asctime)s %(levelname)s "
    #     "trace=%(otelTraceID)s span=%(otelSpanID)s "
    #     "user_id=%(user_id)s correlation_id=%(correlation_id)s ‑ %(message)s",
    log_hook=_copy_custom_attributes,
)

logging.config.dictConfig(get_logging_config("DEBUG", False))

processor = BatchSpanProcessor(ConsoleSpanExporter())
provider.add_span_processor(processor)


def get_logger(name: str) -> logging.Logger:
    """
    Retrieves a logger instance that is wrapped with a ContextualLogger adapter.
    This adapter automatically injects correlation IDs and other context into log records.

    This is the preferred way to get a logger within the application.

    Args:
        name: The name of the logger, typically __name__.

    Returns:
        A context-aware logger instance.
    """
    logger = logging.getLogger(name)
    return logger

logger = get_logger(__name__)

tracer = trace.get_tracer(__name__)


def tool_logging_middleware(next_handler: Callable, tool_name: str, arguments: Dict[str, Any]):
    """
    Middleware that logs tool execution with correlation ID.
    """
    async def handler():
        start_time = asyncio.get_event_loop().time()
        
        # Log tool invocation
        logger.info(
            f"Executing tool: {tool_name}",
            extra={
                "extra_fields": {
                    "event": "tool_invocation",
                    "tool_name": tool_name,
                    "arguments": list(arguments.keys()),
                    "has_call_id": "call_id" in arguments
                }
            }
        )
        
        try:
            result = await next_handler()
            duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000
            
            # Log successful execution
            log_tool_execution(
                logger,
                tool_name,
                "success",
                duration_ms=duration_ms,
                call_id=arguments.get("call_id", None)  
            )
            
            return result
            
        except Exception as e:
            duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000
            
            # Log failed execution
            log_tool_execution(
                logger,
                tool_name,
                "error",
                duration_ms=duration_ms,
                error=e,
                call_id=arguments.get("call_id", None),
                error_type=type(e).__name__
            )
            
            raise
    
    return handler


def correlation_middleware(next_handler: Callable, tool_name: str, arguments: Dict[str, Any]):
    """
    Middleware that ensures correlation ID is set for tool execution.
    """
    async def handler():
        # Extract correlation ID from arguments if present
        correlation_id = arguments.get("correlation_id", None)
        user_id = arguments.get("user_id", "anon")
        
        async with correlation_context(correlation_id):
            if user_id:
                set_user_id(user_id)
            return await next_handler()
    
    return handler


def error_tracking_middleware(next_handler: Callable, tool_name: str, arguments: Dict[str, Any]):
    """
    Middleware that tracks errors and adds context for debugging.
    """
    async def handler():
        try:
            return await next_handler()
        except ToolExecutionError:
            # Already properly formatted, just re-raise
            raise
        except Exception as e:
            # Add context to generic exceptions
            logger.error(
                f"Unexpected error in tool {tool_name}",
                extra={
                    "extra_fields": {
                        "event": "tool_error",
                        "tool_name": tool_name,
                        "error_type": type(e).__name__,
                        "arguments": list(arguments.keys())
                    }
                },
                exc_info=True
            )
            
            # Wrap in ToolExecutionError with context
            raise ToolExecutionError(
                tool_name,
                f"Unexpected error: {str(e)}",
                call_id=arguments.get("call_id", None),
                details={"original_error": type(e).__name__}
            )
    
    return handler


class LoggingToolExecutor(ToolExecutor):
    """
    Extended ToolExecutor with built-in logging middleware.
    """
    
    def __init__(self):
        super().__init__()
        self.logger = get_logger(__name__)
        
        # Add logging middleware by default
        self.add_middleware(tool_logging_middleware)
        self.add_middleware(error_tracking_middleware)
        self.add_middleware(correlation_middleware)
    
    async def execute_tool(self, 
                          name: str, 
                          arguments: Dict[str, Any],
                          retry_config: Optional[Any] = None) -> Any:
        """Execute tool with enhanced logging"""
        # Log circuit breaker state
        circuit_breaker = self._circuit_breakers.get(name)
        if circuit_breaker:
            self.logger.debug(
                f"Circuit breaker state for {name}: {circuit_breaker.state.value}",
                extra={
                    "extra_fields": {
                        "event": "circuit_breaker_check",
                        "tool_name": name,
                        "state": circuit_breaker.state.value,
                        "failure_count": circuit_breaker.failure_count
                    }
                }
            )
        
        return await super().execute_tool(name, arguments, retry_config)


def log_api_middleware(app):
    """
    FastAPI middleware for logging API requests.
    """
    from fastapi import Request, Response
    import time
    import uuid
    
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        # Generate request ID
        request_id = str(uuid.uuid4())
        client_addr = request.client.host if request.client else "unknown"
        request_line = f"{request.method} {request.url.path}"
        
        # Set correlation context
        with correlation_context() as correlation_id:
            with tracer.start_as_current_span("http_request", attributes={"correlation_id": correlation_id,
                                                                          "client_addr": client_addr,
                                                                          "request_id": request_id,
                                                                          "request_line": request_line}):        # Log request
                start_time = time.time()
                
                logger.info(
                    f"{request.method} {request.url.path}",
                    extra={
                        "extra_fields": {
                            "event": "api_request_start",
                            "method": request.method,
                            "path": request.url.path,
                            "request_id": request_id,
                            "client_host": request.client.host if request.client else "unknown"
                        }
                    }
                )
                
                try:
                    # Process request
                    response = await call_next(request)
                    duration_ms = (time.time() - start_time) * 1000
                    
                    # Log response
                    log_api_request(
                        logger,
                        request.method,
                        request.url.path,
                        status_code=response.status_code,
                        duration_ms=duration_ms,
                        request_id=request_id
                    )
                    
                    # Add correlation ID to response headers
                    response.headers["X-Correlation-ID"] = correlation_id
                    response.headers["X-Request-ID"] = request_id
                    
                    return response
                    
                except Exception as e:
                    duration_ms = (time.time() - start_time) * 1000
                    
                    # Log error
                    log_api_request(
                        logger,
                        request.method,
                        request.url.path,
                        duration_ms=duration_ms,
                        error=e,
                        request_id=request_id
                    )
                    
                    raise


def service_operation_logger(service_name: str):
    """
    Decorator for logging service operations.
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            operation_name = func.__name__
            start_time = asyncio.get_event_loop().time()
            
            logger.debug(
                f"Starting {service_name}.{operation_name}",
                extra={
                    "extra_fields": {
                        "event": "service_operation_start",
                        "service": service_name,
                        "operation": operation_name
                    }
                }
            )
            
            try:
                result = await func(*args, **kwargs)
                duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                
                log_service_operation(
                    logger,
                    service_name,
                    operation_name,
                    "success",
                    duration_ms=duration_ms
                )
                
                return result
                
            except Exception as e:
                duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                
                log_service_operation(
                    logger,
                    service_name,
                    operation_name,
                    "error",
                    duration_ms=duration_ms,
                    error_type=type(e).__name__
                )
                
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            import time
            operation_name = func.__name__
            start_time = time.time()
            
            logger.debug(
                f"Starting {service_name}.{operation_name}",
                extra={
                    "extra_fields": {
                        "event": "service_operation_start",
                        "service": service_name,
                        "operation": operation_name
                    }
                }
            )
            
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.time() - start_time) * 1000
                
                log_service_operation(
                    logger,
                    service_name,
                    operation_name,
                    "success",
                    duration_ms=duration_ms
                )
                
                return result
                
            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                
                log_service_operation(
                    logger,
                    service_name,
                    operation_name,
                    "error",
                    duration_ms=duration_ms,
                    error_type=type(e).__name__
                )
                
                raise
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator
