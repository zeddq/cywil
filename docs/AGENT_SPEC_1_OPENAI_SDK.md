# Agent Specification: OpenAI SDK Integration Fix

## Agent ID: PHASE1-OPENAI-SDK
## Priority: CRITICAL
## Estimated Duration: 8-12 hours
## Dependencies: Task 4 (Configuration) should complete first

## Objective
Replace all LangChain placeholder implementations with functional OpenAI SDK v1.x calls, ensuring proper error handling, retries, and structured output parsing.

## Scope
### Files to Modify
- `/ingest/preprocess_sn_o3.py`
- `/app/worker/tasks/preprocess_sn_o3.py`
- **NEW:** `/app/services/openai_client.py` (create)
- **NEW:** `/app/core/ai_client_factory.py` (create)

### Exclusions
- Do NOT modify embedding-related code (handled by Agent 2)
- Do NOT modify configuration loading (handled by Agent 4)
- Assume configuration service provides `OPENAI_API_KEY` via environment

## Technical Requirements

### 1. Client Initialization Pattern
```python
# app/services/openai_client.py
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_random_exponential
from app.core.config_service import settings

class OpenAIService:
    def __init__(self):
        self.client = OpenAI(
            api_key=settings.OPENAI_API_KEY,
            max_retries=3,
            timeout=30.0
        )
    
    @retry(
        wait=wait_random_exponential(min=1, max=60),
        stop=stop_after_attempt(6)
    )
    def call_with_retry(self, func, *args, **kwargs):
        """Wrapper for API calls with exponential backoff"""
        try:
            return func(*args, **kwargs)
        except (APIStatusError, APITimeoutError) as e:
            # Log error details
            raise
```

### 2. Structured Output Implementation
```python
# Use client.beta.chat.completions.parse() for structured outputs
from pydantic import BaseModel

class LegalExtraction(BaseModel):
    case_number: str
    parties: list[str]
    legal_basis: list[str]
    decision: str

response = client.beta.chat.completions.parse(
    model="o3-mini",
    messages=[...],
    response_format=LegalExtraction
)
```

### 3. Error Handling Requirements
- Catch and handle: `APIStatusError`, `APITimeoutError`, `APIConnectionError`
- Implement circuit breaker pattern for repeated failures
- Log all API errors with request/response details (excluding sensitive data)
- Provide fallback parsing for when structured output fails

## Implementation Steps

1. **Create OpenAI Service Module** (2 hours)
   - Single source of truth for client initialization
   - Retry logic with exponential backoff
   - Error categorization and logging

2. **Create AI Client Factory** (1 hour)
   - Factory pattern for different AI providers
   - OpenAI as primary implementation
   - Interface for future providers

3. **Refactor preprocess_sn_o3.py files** (4 hours)
   - Remove all LangChain imports and classes
   - Replace with OpenAI SDK calls via service
   - Update structured output parsing
   - Add fallback JSON parsing

4. **Update Worker Tasks** (2 hours)
   - Ensure async compatibility
   - Add task-specific error handling
   - Implement progress tracking

5. **Add Monitoring** (1 hour)
   - API call metrics (latency, success rate)
   - Token usage tracking
   - Error rate monitoring

## Success Criteria

### Functional
- [ ] Zero `NotImplementedError` exceptions in OpenAI-related code
- [ ] All o3-mini model calls successfully process test documents
- [ ] Structured output parsing works for legal document extraction
- [ ] Fallback parsing activates when structured output fails

### Non-Functional
- [ ] API calls retry with exponential backoff
- [ ] All errors logged with appropriate context
- [ ] Response time < 5 seconds for standard document
- [ ] Memory usage stable during batch processing

## Testing Requirements

### Unit Tests
```python
# tests/unit/test_openai_service.py
- test_client_initialization
- test_retry_on_timeout
- test_structured_output_parsing
- test_fallback_parsing
- test_error_handling
```

### Integration Tests
```python
# tests/integration/test_openai_integration.py
- test_end_to_end_document_processing
- test_polish_legal_document_extraction
- test_batch_processing_stability
- test_concurrent_api_calls
```

## Conflict Avoidance

### File Isolation
- This agent owns: `/app/services/openai_client.py`, `/app/core/ai_client_factory.py`
- Shared files: Use file locking or coordinate via version control
- Import dependencies: Read-only access to config_service

### API Boundaries
- Expose clear service interface: `OpenAIService.process_document()`
- Other agents import service, not implementation details
- Version service methods if interface changes needed

## Rollback Plan

1. Keep original LangChain code in `*.backup` files
2. Feature flag for switching between implementations
3. Parallel deployment with A/B testing capability
4. Database migration scripts if schema changes needed

## Monitoring & Alerts

- Alert if error rate > 5% over 5 minutes
- Alert if response time p95 > 10 seconds
- Alert if token usage exceeds budget threshold
- Daily report of processing statistics

## Dependencies

### Python Packages
```toml
openai = "^1.35.0"
tenacity = "^8.2.3"
pydantic = "^2.5.0"
```

### External Services
- OpenAI API (requires valid API key)
- Logging infrastructure (existing)
- Metrics collection (existing)

## Notes for Implementation

1. **Priority Order**: Start with client initialization, then factory, then refactoring
2. **Coordination**: Wait for Config agent to complete before starting
3. **Communication**: Update team channel when service interface is defined
4. **Documentation**: Update API docs as methods are implemented