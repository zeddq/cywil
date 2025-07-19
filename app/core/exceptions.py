"""
Custom exception hierarchy for the AI Paralegal system.
"""
from typing import Optional, Dict, Any


class ParalegalException(Exception):
    """Base exception for all paralegal-specific errors"""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConfigurationError(ParalegalException):
    """Raised when there's a configuration problem"""
    pass


class ServiceError(ParalegalException):
    """Base class for service-related errors"""
    
    def __init__(self, service_name: str, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(f"Service '{service_name}' error: {message}", details)
        self.service_name = service_name


class ServiceNotInitializedError(ServiceError):
    """Raised when attempting to use an uninitialized service"""
    
    def __init__(self, service_name: str):
        super().__init__(service_name, "Service not initialized")


class ServiceHealthCheckError(ServiceError):
    """Raised when a service health check fails"""
    pass

class ServiceUnavailableError(ServiceError):
    """Raised when a service is unavailable"""
    pass


class ToolError(ParalegalException):
    """Base class for tool execution errors"""
    
    def __init__(self, tool_name: str, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(f"Tool '{tool_name}' error: {message}", details)
        self.tool_name = tool_name


class ToolNotFoundError(ToolError):
    """Raised when a requested tool doesn't exist"""
    
    def __init__(self, tool_name: str):
        super().__init__(tool_name, "Tool not found")


class ToolExecutionError(ToolError):
    """Raised when tool execution fails"""
    
    def __init__(self, tool_name: str, message: str, call_id: Optional[str] = None):
        details = {"call_id": call_id} if call_id else {}
        super().__init__(tool_name, message, details)
        self.call_id = call_id


class ValidationError(ToolError):
    """Raised when tool arguments fail validation"""
    
    def __init__(self, tool_name: str, validation_errors: Dict[str, Any]):
        super().__init__(tool_name, "Validation failed", {"errors": validation_errors})
        self.validation_errors = validation_errors


class DatabaseError(ParalegalException):
    """Base class for database-related errors"""
    pass


class DatabaseConnectionError(DatabaseError):
    """Raised when database connection fails"""
    pass


class DatabaseTransactionError(DatabaseError):
    """Raised when a database transaction fails"""
    pass


class VectorDatabaseError(ParalegalException):
    """Base class for vector database errors"""
    pass


class CollectionNotFoundError(VectorDatabaseError):
    """Raised when a vector database collection doesn't exist"""
    
    def __init__(self, collection_name: str):
        super().__init__(f"Collection '{collection_name}' not found")
        self.collection_name = collection_name


class EmbeddingError(ParalegalException):
    """Raised when embedding generation fails"""
    pass


class LLMError(ParalegalException):
    """Base class for LLM-related errors"""
    pass


class LLMTimeoutError(LLMError):
    """Raised when LLM request times out"""
    
    def __init__(self, model: str, timeout: int):
        super().__init__(f"LLM request to '{model}' timed out after {timeout}s")
        self.model = model
        self.timeout = timeout


class LLMRateLimitError(LLMError):
    """Raised when hitting LLM rate limits"""
    
    def __init__(self, model: str, retry_after: Optional[int] = None):
        message = f"Rate limit exceeded for model '{model}'"
        if retry_after:
            message += f", retry after {retry_after}s"
        super().__init__(message, {"retry_after": retry_after})
        self.model = model
        self.retry_after = retry_after


class DocumentError(ParalegalException):
    """Base class for document-related errors"""
    pass


class TemplateNotFoundError(DocumentError):
    """Raised when a document template doesn't exist"""
    
    def __init__(self, template_name: str):
        super().__init__(f"Template '{template_name}' not found")
        self.template_name = template_name


class DocumentGenerationError(DocumentError):
    """Raised when document generation fails"""
    pass


class SearchError(ParalegalException):
    """Base class for search-related errors"""
    pass


class NoResultsError(SearchError):
    """Raised when search returns no results"""
    
    def __init__(self, query: str, search_type: str = "general"):
        super().__init__(f"No results found for query: {query}")
        self.query = query
        self.search_type = search_type


class CaseError(ParalegalException):
    """Base class for case management errors"""
    pass


class CaseNotFoundError(CaseError):
    """Raised when a case doesn't exist"""
    
    def __init__(self, case_id: str):
        super().__init__(f"Case '{case_id}' not found")
        self.case_id = case_id


class DeadlineError(CaseError):
    """Raised when there's an error with deadline calculation"""
    pass


class AuthenticationError(ParalegalException):
    """Raised for authentication failures"""
    pass


class AuthorizationError(ParalegalException):
    """Raised for authorization failures"""
    pass


class ExternalServiceError(ParalegalException):
    """Raised when an external service fails"""
    
    def __init__(self, service: str, message: str, status_code: Optional[int] = None):
        details = {"status_code": status_code} if status_code else {}
        super().__init__(f"External service '{service}' error: {message}", details)
        self.service = service
        self.status_code = status_code
