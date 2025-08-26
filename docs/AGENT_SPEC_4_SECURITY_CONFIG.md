# Agent Specification: Configuration Security Quick-Fix

## Agent ID: PHASE1-SECURITY-CONFIG
## Priority: CRITICAL - MUST COMPLETE FIRST
## Estimated Duration: 4-6 hours
## Dependencies: None (foundational)

## Objective
Establish secure configuration management, replace hardcoded secrets, add input validation, implement circuit breakers, and establish structured logging foundation.

## Scope
### Files to Modify
- `/app/core/config_service.py` (major refactor)
- `/app/worker/tasks/preprocess_sn_o3.py` (security updates)
- **NEW:** `/app/core/circuit_breaker.py` (create)
- **NEW:** `/app/core/logging_config.py` (create)
- **NEW:** `/app/validators/input_validator.py` (create)

### Files to Create
- `.env.example` (template for secrets)
- `docker-compose.override.yml.example` (local dev config)
- `/app/core/security_utils.py` (input sanitization)

### Exclusions
- Do NOT modify AI service implementations
- Do NOT touch embedding model code
- Do NOT change database connections

## Technical Requirements

### 1. Secure Configuration Service
```python
# app/core/config_service.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, validator, SecretStr
from typing import Optional, List
import os
from pathlib import Path

class SecuritySettings(BaseSettings):
    """Security-related configuration"""
    
    # API Keys (never log these)
    openai_api_key: SecretStr = Field(..., description="OpenAI API Key")
    qdrant_api_key: Optional[SecretStr] = Field(None, description="Qdrant API Key")
    
    # Security settings
    allowed_file_extensions: List[str] = Field(
        default=[".pdf", ".txt", ".docx"],
        description="Allowed file types for upload"
    )
    max_file_size_mb: int = Field(
        default=50,
        ge=1, le=500,
        description="Maximum file size in MB"
    )
    max_pdf_pages: int = Field(
        default=1000,
        ge=1, le=10000,
        description="Maximum PDF pages to process"
    )
    
    # Rate limiting
    api_rate_limit: int = Field(
        default=100,
        ge=1, le=10000,
        description="API calls per minute"
    )
    concurrent_requests: int = Field(
        default=10,
        ge=1, le=100,
        description="Max concurrent API requests"
    )
    
    @validator('openai_api_key')
    def validate_openai_key(cls, v):
        key = v.get_secret_value()
        if not key.startswith('sk-'):
            raise ValueError('OpenAI API key must start with sk-')
        if len(key) < 50:
            raise ValueError('OpenAI API key appears invalid')
        return v

class DatabaseSettings(BaseSettings):
    """Database configuration"""
    
    postgres_host: str = Field(default="localhost")
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = Field(..., min_length=1)
    postgres_user: str = Field(..., min_length=1)
    postgres_password: SecretStr = Field(...)
    
    qdrant_host: str = Field(default="localhost")
    qdrant_port: int = Field(default=6333, ge=1, le=65535)
    qdrant_collection: str = Field(default="legal_documents")

class LoggingSettings(BaseSettings):
    """Logging configuration"""
    
    log_level: str = Field(default="INFO", regex="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    log_format: str = Field(default="json")
    log_file: Optional[str] = Field(None)
    enable_audit_log: bool = Field(default=True)
    mask_sensitive_data: bool = Field(default=True)

class Settings(BaseSettings):
    """Main application settings"""
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=False,
        extra='forbid'  # Prevent typos
    )
    
    # Environment
    environment: str = Field(default="development", regex="^(development|staging|production)$")
    debug: bool = Field(default=False)
    
    # Nested settings
    security: SecuritySettings = SecuritySettings()
    database: DatabaseSettings = DatabaseSettings()
    logging: LoggingSettings = LoggingSettings()
    
    # Application settings
    app_name: str = Field(default="AI Paralegal POC")
    app_version: str = Field(default="1.0.0")
    
    @validator('environment')
    def validate_production_settings(cls, v, values):
        if v == 'production':
            if values.get('debug', False):
                raise ValueError('Debug must be False in production')
        return v

# Singleton instance
settings = Settings()

# Security check on startup
def validate_security():
    """Validate security configuration"""
    errors = []
    
    if settings.environment == 'production':
        if not settings.security.openai_api_key.get_secret_value():
            errors.append("OpenAI API key required in production")
        if settings.debug:
            errors.append("Debug mode not allowed in production")
    
    # Check file permissions
    env_file = Path('.env')
    if env_file.exists():
        stat = env_file.stat()
        if oct(stat.st_mode)[-3:] != '600':
            errors.append(f".env file permissions too open: {oct(stat.st_mode)}")
    
    if errors:
        raise ValueError(f"Security validation failed: {'; '.join(errors)}")
```

### 2. Circuit Breaker Implementation
```python
# app/core/circuit_breaker.py
from enum import Enum
from typing import Callable, Any, Optional
import asyncio
import time
from collections import deque
import logging

logger = logging.getLogger(__name__)

class CircuitState(Enum):
    CLOSED = "closed"        # Normal operation
    OPEN = "open"           # Blocking requests
    HALF_OPEN = "half_open" # Testing recovery

class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open"""
    pass

class CircuitBreaker:
    """Circuit breaker for external service calls"""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: type = Exception,
        name: str = "default"
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.name = name
        
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = None
        self._success_count = 0
        self._call_times = deque(maxlen=100)  # Track response times
        
    @property
    def state(self) -> CircuitState:
        """Get current circuit state"""
        if self._state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self._state = CircuitState.HALF_OPEN
                logger.info(f"Circuit breaker {self.name}: OPEN -> HALF_OPEN")
        return self._state
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to try recovery"""
        return (
            self._last_failure_time and
            time.time() - self._last_failure_time >= self.recovery_timeout
        )
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection"""
        if self.state == CircuitState.OPEN:
            raise CircuitBreakerError(f"Circuit breaker {self.name} is OPEN")
        
        start_time = time.time()
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
            
        except self.expected_exception as e:
            self._on_failure()
            raise e
        finally:
            self._call_times.append(time.time() - start_time)
    
    def _on_success(self):
        """Handle successful call"""
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= 3:  # Require multiple successes
                self._reset()
        else:
            self._failure_count = max(0, self._failure_count - 1)
    
    def _on_failure(self):
        """Handle failed call"""
        self._failure_count += 1
        self._last_failure_time = time.time()
        
        if self._failure_count >= self.failure_threshold:
            self._trip()
    
    def _trip(self):
        """Open the circuit breaker"""
        self._state = CircuitState.OPEN
        logger.warning(f"Circuit breaker {self.name}: CLOSED -> OPEN (failures: {self._failure_count})")
    
    def _reset(self):
        """Close the circuit breaker"""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        logger.info(f"Circuit breaker {self.name}: HALF_OPEN -> CLOSED")
    
    def get_stats(self) -> dict:
        """Get circuit breaker statistics"""
        avg_response_time = sum(self._call_times) / len(self._call_times) if self._call_times else 0
        return {
            'name': self.name,
            'state': self.state.value,
            'failure_count': self._failure_count,
            'avg_response_time': avg_response_time,
            'total_calls': len(self._call_times)
        }

# Global circuit breakers
CIRCUIT_BREAKERS = {
    'openai': CircuitBreaker(
        failure_threshold=3,
        recovery_timeout=30.0,
        name='openai'
    ),
    'qdrant': CircuitBreaker(
        failure_threshold=5,
        recovery_timeout=60.0,
        name='qdrant'
    )
}
```

### 3. Input Validation
```python
# app/validators/input_validator.py
from typing import BinaryIO, Dict, Any, List
import magic
from pathlib import Path
import hashlib
from pydantic import BaseModel, Field, validator

class FileValidationResult(BaseModel):
    is_valid: bool
    file_type: str
    file_size: int
    errors: List[str] = []
    warnings: List[str] = []
    metadata: Dict[str, Any] = {}

class InputValidator:
    """Validate all user inputs for security"""
    
    ALLOWED_MIME_TYPES = {
        'application/pdf': ['.pdf'],
        'text/plain': ['.txt'],
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx']
    }
    
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
    
    @classmethod
    def validate_file(cls, file_content: bytes, filename: str) -> FileValidationResult:
        """Comprehensive file validation"""
        result = FileValidationResult(
            is_valid=True,
            file_type='unknown',
            file_size=len(file_content)
        )
        
        # Size check
        if len(file_content) > cls.MAX_FILE_SIZE:
            result.errors.append(f"File too large: {len(file_content)} bytes")
            result.is_valid = False
        
        if len(file_content) == 0:
            result.errors.append("Empty file")
            result.is_valid = False
            return result
        
        # MIME type detection
        try:
            mime_type = magic.from_buffer(file_content, mime=True)
            result.file_type = mime_type
            
            if mime_type not in cls.ALLOWED_MIME_TYPES:
                result.errors.append(f"Unsupported file type: {mime_type}")
                result.is_valid = False
            
            # Extension validation
            file_ext = Path(filename).suffix.lower()
            expected_exts = cls.ALLOWED_MIME_TYPES.get(mime_type, [])
            if file_ext not in expected_exts:
                result.warnings.append(
                    f"Extension {file_ext} doesn't match detected type {mime_type}"
                )
        
        except Exception as e:
            result.errors.append(f"MIME detection failed: {str(e)}")
            result.is_valid = False
        
        # PDF-specific validation
        if mime_type == 'application/pdf':
            pdf_validation = cls._validate_pdf(file_content)
            result.errors.extend(pdf_validation.get('errors', []))
            result.warnings.extend(pdf_validation.get('warnings', []))
            result.metadata.update(pdf_validation.get('metadata', {}))
            
            if pdf_validation.get('errors'):
                result.is_valid = False
        
        # Security checks
        security_check = cls._security_scan(file_content, filename)
        if not security_check['safe']:
            result.errors.extend(security_check['threats'])
            result.is_valid = False
        
        return result
    
    @classmethod
    def _validate_pdf(cls, content: bytes) -> Dict[str, Any]:
        """PDF-specific validation"""
        result = {'errors': [], 'warnings': [], 'metadata': {}}
        
        # Check for PDF signature
        if not content.startswith(b'%PDF-'):
            result['errors'].append("Invalid PDF signature")
            return result
        
        try:
            import PyPDF2
            from io import BytesIO
            
            pdf_reader = PyPDF2.PdfReader(BytesIO(content))
            
            # Page count
            page_count = len(pdf_reader.pages)
            result['metadata']['page_count'] = page_count
            
            if page_count > 1000:
                result['errors'].append(f"Too many pages: {page_count}")
            elif page_count > 500:
                result['warnings'].append(f"Large document: {page_count} pages")
            
            # Check for encryption
            if pdf_reader.is_encrypted:
                result['errors'].append("Encrypted PDFs not supported")
            
            # Extract basic metadata
            if pdf_reader.metadata:
                result['metadata']['title'] = pdf_reader.metadata.get('/Title', '')
                result['metadata']['author'] = pdf_reader.metadata.get('/Author', '')
        
        except Exception as e:
            result['errors'].append(f"PDF parsing error: {str(e)}")
        
        return result
    
    @classmethod
    def _security_scan(cls, content: bytes, filename: str) -> Dict[str, Any]:
        """Basic security scanning"""
        threats = []
        
        # File hash for malware checking (future integration)
        file_hash = hashlib.sha256(content).hexdigest()
        
        # Check for suspicious patterns
        dangerous_patterns = [
            b'<script',
            b'javascript:',
            b'vbscript:',
            b'data:text/html',
            b'\x00',  # Null bytes
        ]
        
        for pattern in dangerous_patterns:
            if pattern in content.lower():
                threats.append(f"Suspicious content pattern: {pattern.decode('utf-8', errors='ignore')}")
        
        # Filename validation
        if any(char in filename for char in ['..', '/', '\\', '<', '>', '|']):
            threats.append("Unsafe filename characters")
        
        return {
            'safe': len(threats) == 0,
            'threats': threats,
            'file_hash': file_hash
        }
    
    @classmethod
    def sanitize_text(cls, text: str, max_length: int = 10000) -> str:
        """Sanitize text input"""
        if not text:
            return ""
        
        # Remove null bytes and control characters
        text = ''.join(char for char in text if ord(char) >= 32 or char in '\n\r\t')
        
        # Truncate if too long
        if len(text) > max_length:
            text = text[:max_length] + "...[truncated]"
        
        return text.strip()
```

### 4. Structured Logging
```python
# app/core/logging_config.py
import logging
import sys
from typing import Any, Dict
import json
import traceback
from datetime import datetime
from pathlib import Path

class SecurityFilter(logging.Filter):
    """Filter to mask sensitive data"""
    
    SENSITIVE_KEYS = {
        'password', 'api_key', 'secret', 'token', 'auth',
        'openai_api_key', 'postgres_password'
    }
    
    def filter(self, record: logging.LogRecord) -> bool:
        if hasattr(record, 'extra'):
            self._mask_sensitive(record.extra)
        
        # Mask in message
        if hasattr(record, 'msg') and isinstance(record.msg, str):
            for key in self.SENSITIVE_KEYS:
                if key in record.msg.lower():
                    record.msg = record.msg.replace(
                        record.msg, 
                        "[SENSITIVE DATA MASKED]"
                    )
        
        return True
    
    def _mask_sensitive(self, data: Dict[str, Any]):
        """Recursively mask sensitive keys"""
        for key, value in data.items():
            if isinstance(key, str) and any(sensitive in key.lower() for sensitive in self.SENSITIVE_KEYS):
                data[key] = "[MASKED]"
            elif isinstance(value, dict):
                self._mask_sensitive(value)

class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging"""
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }
        
        # Add extra fields
        if hasattr(record, 'extra'):
            log_data['extra'] = record.extra
        
        # Add exception info
        if record.exc_info:
            log_data['exception'] = {
                'type': record.exc_info[0].__name__,
                'message': str(record.exc_info[1]),
                'traceback': traceback.format_exception(*record.exc_info)
            }
        
        return json.dumps(log_data, ensure_ascii=False, default=str)

def setup_logging(settings):
    """Configure application logging"""
    
    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.logging.log_level.upper()))
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    if settings.logging.log_format == 'json':
        console_handler.setFormatter(JSONFormatter())
    else:
        console_handler.setFormatter(
            logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
        )
    
    # Add security filter
    if settings.logging.mask_sensitive_data:
        console_handler.addFilter(SecurityFilter())
    
    root_logger.addHandler(console_handler)
    
    # File handler (if configured)
    if settings.logging.log_file:
        file_handler = logging.FileHandler(settings.logging.log_file)
        file_handler.setFormatter(JSONFormatter())
        if settings.logging.mask_sensitive_data:
            file_handler.addFilter(SecurityFilter())
        root_logger.addHandler(file_handler)
    
    # Audit logger (separate from main logs)
    if settings.logging.enable_audit_log:
        audit_logger = logging.getLogger('audit')
        audit_handler = logging.FileHandler('logs/audit.log')
        audit_handler.setFormatter(JSONFormatter())
        audit_logger.addHandler(audit_handler)
        audit_logger.setLevel(logging.INFO)
        audit_logger.propagate = False  # Don't send to root logger
    
    # Set levels for noisy libraries
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('openai').setLevel(logging.INFO)

def get_audit_logger():
    """Get audit logger instance"""
    return logging.getLogger('audit')
```

## Implementation Steps

1. **Environment Setup** (1 hour)
   - Create .env.example template
   - Set up environment validation
   - Add security checks

2. **Configuration Refactor** (1.5 hours)
   - Replace existing config system
   - Add Pydantic validation
   - Implement secret management

3. **Circuit Breaker Implementation** (1 hour)
   - Create circuit breaker class
   - Add to external service calls
   - Configure for OpenAI and Qdrant

4. **Input Validation System** (1.5 hours)
   - File type validation
   - Security scanning
   - PDF-specific checks

5. **Structured Logging Setup** (1 hour)
   - JSON formatter
   - Security filtering
   - Audit logging

## Success Criteria

### Security
- [ ] No secrets in version control
- [ ] All API keys loaded from environment
- [ ] File upload validation active
- [ ] Circuit breakers prevent cascading failures

### Configuration
- [ ] Single source of configuration truth
- [ ] Type validation for all settings
- [ ] Environment-specific configuration
- [ ] Startup validation passes

### Logging
- [ ] Structured JSON logs
- [ ] Sensitive data masked
- [ ] Audit trail for all actions
- [ ] Configurable log levels

## Testing Requirements

```python
# tests/unit/test_security_config.py
class TestSecurityConfig:
    def test_openai_key_validation(self):
        # Test invalid keys are rejected
        pass
    
    def test_file_validation(self):
        # Test file type detection
        pass
    
    def test_circuit_breaker(self):
        # Test failure threshold
        pass
    
    def test_logging_masking(self):
        # Test sensitive data masking
        pass
```

## Environment Template

```bash
# .env.example
# Copy to .env and fill in actual values

# OpenAI Configuration
OPENAI_API_KEY=sk-your-key-here

# Database Configuration
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=ai_paralegal
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your-password

# Qdrant Configuration
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_API_KEY=your-qdrant-key

# Application Settings
ENVIRONMENT=development
DEBUG=true
LOG_LEVEL=INFO
LOG_FORMAT=json

# Security Settings
MAX_FILE_SIZE_MB=50
MAX_PDF_PAGES=1000
API_RATE_LIMIT=100
CONCURRENT_REQUESTS=10
```

## Deployment Checklist

- [ ] .env file created with proper permissions (600)
- [ ] All secrets configured
- [ ] Environment validation passes
- [ ] Logging directory exists
- [ ] Circuit breaker thresholds configured
- [ ] File upload limits appropriate

## Conflict Avoidance

### File Isolation
- This agent owns: All security and config files
- Creates foundation: Other agents import from here
- No conflicts: First to complete

### Breaking Changes
- Use feature flags for gradual rollout
- Maintain backwards compatibility during transition
- Clear migration path documented

## Monitoring & Alerts

- Configuration loading errors
- Circuit breaker state changes  
- File validation failures
- Security scan alerts
- Audit log anomalies

## Dependencies

```toml
pydantic-settings = "^2.1.0"
python-magic = "^0.4.27"
PyPDF2 = "^3.0.1"
python-dotenv = "^1.0.0"
```

## Notes for Implementation

1. **Execute First**: Other agents depend on this configuration
2. **Security Priority**: Never commit secrets
3. **Validation**: Start application fails if config invalid
4. **Logging**: Set up before other services start