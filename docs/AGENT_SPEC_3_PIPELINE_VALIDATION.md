# Agent Specification: Processing Pipeline Validation

## Agent ID: PHASE1-PIPELINE-VALIDATION
## Priority: CRITICAL
## Estimated Duration: 6-8 hours  
## Dependencies: Agents 1 & 2 should be partially complete

## Objective
Create comprehensive validation framework and tests for AI processing pipelines, ensuring data integrity, Polish legal document accuracy, and fallback mechanisms.

## Scope
### Files to Create
- **NEW:** `/tests/integration/test_ai_functionality.py`
- **NEW:** `/tests/unit/test_openai_integration.py`
- **NEW:** `/app/models/pipeline_schemas.py`
- **NEW:** `/app/validators/document_validator.py`
- **NEW:** `/tests/fixtures/legal_documents/` (test data)

### Files to Modify
- `/app/worker/tasks/ingestion_pipeline.py` (add validation)
- `/app/services/statute_search_service.py` (add validation)

### Exclusions
- Do NOT refactor existing business logic
- Do NOT modify database schemas
- Do NOT change API contracts

## Technical Requirements

### 1. Data Model Definitions
```python
# app/models/pipeline_schemas.py
from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict
from datetime import datetime
from enum import Enum

class DocumentType(str, Enum):
    SUPREME_COURT = "sn_ruling"
    CIVIL_CODE = "kc_article"
    CIVIL_PROCEDURE = "kpc_article"
    CONTRACT = "contract"
    PLEADING = "pleading"

class RawDocument(BaseModel):
    """Input document for processing"""
    id: str = Field(..., regex="^[A-Z0-9-]+$")
    content: str = Field(..., min_length=10, max_length=1000000)
    document_type: DocumentType
    source_path: str
    metadata: Dict[str, any] = {}
    
    @validator('content')
    def validate_not_empty(cls, v):
        if not v.strip():
            raise ValueError('Document content cannot be empty')
        return v

class ProcessedChunk(BaseModel):
    """Document chunk after processing"""
    chunk_id: str
    document_id: str
    content: str = Field(..., min_length=1, max_length=4000)
    chunk_index: int = Field(..., ge=0)
    start_char: int = Field(..., ge=0)
    end_char: int
    metadata: Dict[str, any]
    
    @validator('end_char')
    def validate_char_range(cls, v, values):
        if 'start_char' in values and v <= values['start_char']:
            raise ValueError('end_char must be greater than start_char')
        return v

class EmbeddedChunk(ProcessedChunk):
    """Chunk with embedding vector"""
    embedding: List[float] = Field(..., min_items=384, max_items=1536)
    embedding_model: str
    embedded_at: datetime
    
    @validator('embedding')
    def validate_embedding_normalized(cls, v):
        import numpy as np
        norm = np.linalg.norm(v)
        if not 0.99 < norm < 1.01:
            raise ValueError(f'Embedding not normalized: {norm}')
        return v

class LegalExtraction(BaseModel):
    """Extracted legal information"""
    case_number: Optional[str] = Field(None, regex="^[IVX]+ [A-Z]+ \d+/\d+$")
    court: Optional[str]
    date: Optional[datetime]
    parties: List[str] = []
    legal_basis: List[str] = []  # Article references
    decision: Optional[str]
    reasoning: Optional[str]
    
    @validator('legal_basis')
    def validate_article_format(cls, v):
        import re
        pattern = r'^(art\.|§)\s*\d+'
        for ref in v:
            if not re.match(pattern, ref, re.IGNORECASE):
                raise ValueError(f'Invalid article reference: {ref}')
        return v
```

### 2. Validation Service
```python
# app/validators/document_validator.py
from typing import Any, List, Tuple
import re
from pydantic import ValidationError

class DocumentValidator:
    """Validates documents at pipeline boundaries"""
    
    POLISH_LEGAL_PATTERNS = {
        'case_number': r'[IVX]+ [A-Z]+ \d+/\d+',
        'article': r'art\.\s*\d+',
        'paragraph': r'§\s*\d+',
        'statute_ref': r'(k\.c\.|k\.p\.c\.|k\.k\.|k\.p\.k\.)'
    }
    
    @classmethod
    def validate_legal_document(cls, content: str) -> Tuple[bool, List[str]]:
        """Validate Polish legal document format"""
        errors = []
        
        # Check for required sections
        required_sections = ['Sygn. akt', 'WYROK', 'UZASADNIENIE']
        for section in required_sections:
            if section not in content:
                errors.append(f"Missing required section: {section}")
        
        # Validate case number format
        if not re.search(cls.POLISH_LEGAL_PATTERNS['case_number'], content):
            errors.append("No valid case number found")
        
        # Check for legal references
        if not re.search(cls.POLISH_LEGAL_PATTERNS['article'], content):
            errors.append("No article references found")
        
        return len(errors) == 0, errors
    
    @classmethod
    def validate_pipeline_transition(
        cls,
        input_data: Any,
        output_data: Any,
        stage: str
    ) -> Tuple[bool, List[str]]:
        """Validate data between pipeline stages"""
        errors = []
        
        # Stage-specific validations
        if stage == "chunking":
            if not output_data.chunks:
                errors.append("No chunks produced")
            total_length = sum(len(c.content) for c in output_data.chunks)
            if total_length < len(input_data.content) * 0.9:
                errors.append("Significant content loss during chunking")
        
        elif stage == "embedding":
            for chunk in output_data:
                if not chunk.embedding:
                    errors.append(f"Missing embedding for chunk {chunk.chunk_id}")
        
        elif stage == "extraction":
            if not output_data.legal_basis and "art." in input_data.content:
                errors.append("Failed to extract legal references")
        
        return len(errors) == 0, errors
```

### 3. Integration Tests
```python
# tests/integration/test_ai_functionality.py
import pytest
import asyncio
from pathlib import Path

class TestAIProcessingPipeline:
    """End-to-end tests for AI processing"""
    
    @pytest.fixture
    def sample_legal_document(self):
        """Load real Polish legal document"""
        path = Path("tests/fixtures/legal_documents/sample_wyrok.pdf")
        return path.read_bytes()
    
    @pytest.mark.asyncio
    async def test_complete_pipeline(self, sample_legal_document):
        """Test document from input to vector store"""
        # 1. Parse PDF
        parsed = await parse_pdf(sample_legal_document)
        assert parsed.content
        assert len(parsed.content) > 100
        
        # 2. Validate document
        is_valid, errors = DocumentValidator.validate_legal_document(
            parsed.content
        )
        assert is_valid, f"Validation failed: {errors}"
        
        # 3. Process with AI
        extraction = await extract_legal_info(parsed.content)
        assert extraction.case_number
        assert extraction.legal_basis
        
        # 4. Chunk document
        chunks = await chunk_document(parsed.content)
        assert len(chunks) > 0
        assert all(c.content for c in chunks)
        
        # 5. Generate embeddings
        embedded = await generate_embeddings(chunks)
        assert all(len(c.embedding) == 384 for c in embedded)
        
        # 6. Store in vector DB
        stored = await store_embeddings(embedded)
        assert stored.success
        
        # 7. Verify retrieval
        results = await search_similar("wyrok sądu")
        assert len(results) > 0
    
    @pytest.mark.asyncio
    async def test_polish_text_processing(self):
        """Test Polish-specific text handling"""
        polish_text = """Sygn. akt II CSK 123/20
        WYROK
        Sąd Najwyższy w składzie:
        SSN Jan Kowalski
        po rozpoznaniu sprawy z powództwa Jana Nowaka
        przeciwko Spółce ABC sp. z o.o.
        o zapłatę
        oddala kasację.
        UZASADNIENIE
        Powód domagał się zapłaty kwoty 100.000 zł 
        na podstawie art. 415 k.c."""
        
        extraction = await extract_legal_info(polish_text)
        assert extraction.case_number == "II CSK 123/20"
        assert "art. 415 k.c." in extraction.legal_basis
        assert extraction.parties == ["Jan Nowak", "Spółka ABC sp. z o.o."]
    
    @pytest.mark.asyncio
    async def test_fallback_mechanisms(self):
        """Test graceful degradation on API failures"""
        # Simulate OpenAI API failure
        with mock.patch('openai.ChatCompletion.create',
                       side_effect=APIError("Service unavailable")):
            
            result = await process_with_fallback(sample_document)
            assert result.success
            assert result.used_fallback
            assert result.extraction  # Basic extraction still works
```

### 4. Fallback Parser Implementation
```python
# app/services/fallback_parser.py
class FallbackParser:
    """Regex-based parser for when AI fails"""
    
    @staticmethod
    def extract_case_info(text: str) -> Dict:
        """Extract basic info using patterns"""
        result = {}
        
        # Case number
        case_match = re.search(r'Sygn\.\s*akt\s*([IVX]+ [A-Z]+ \d+/\d+)', text)
        if case_match:
            result['case_number'] = case_match.group(1)
        
        # Date
        date_match = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', text)
        if date_match:
            result['date'] = f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}"
        
        # Legal references
        articles = re.findall(r'art\.\s*\d+\s*(?:§\s*\d+)?\s*k\.c\.', text)
        result['legal_basis'] = articles
        
        return result
```

## Implementation Steps

1. **Create Schema Models** (2 hours)
   - Define Pydantic models for each stage
   - Add comprehensive validators
   - Document field constraints

2. **Build Validation Service** (2 hours)
   - Pattern matching for Polish legal text
   - Stage transition validators
   - Error aggregation and reporting

3. **Implement Fallback Parser** (1 hour)
   - Regex patterns for common structures
   - Basic extraction without AI
   - Confidence scoring

4. **Write Integration Tests** (2 hours)
   - End-to-end pipeline test
   - Polish language specific tests
   - Failure scenario tests

5. **Create Test Fixtures** (1 hour)
   - Sample legal documents
   - Edge case documents
   - Invalid document examples

## Success Criteria

### Coverage
- [ ] 90% code coverage for pipeline code
- [ ] All pipeline stages have validators
- [ ] Fallback parser handles 80% of documents
- [ ] Polish legal format validation accurate

### Reliability
- [ ] Zero data loss through pipeline
- [ ] All validation errors are actionable
- [ ] Graceful degradation on AI failure
- [ ] Consistent output format

## Testing Requirements

### Test Data
```
tests/fixtures/legal_documents/
├── valid/
│   ├── wyrok_cywilny.pdf
│   ├── postanowienie.pdf
│   └── kodeks_cywilny_art415.txt
├── invalid/
│   ├── corrupted.pdf
│   ├── empty.pdf
│   └── non_legal.pdf
└── edge_cases/
    ├── very_long.pdf (>1000 pages)
    ├── scanned_image.pdf
    └── mixed_language.pdf
```

## Conflict Avoidance

### Testing Strategy
- Run tests in isolated containers
- Use test database separate from dev
- Mock external service calls
- Parallel test execution

### File Coordination
- This agent owns: All test files
- Read-only: Service implementations
- No modifications: Production code

## Performance Benchmarks

```python
BENCHMARKS = {
    'pdf_parsing': 1000,      # pages per minute
    'validation': 10000,      # docs per second
    'extraction': 100,        # docs per minute
    'embedding': 1000,        # chunks per minute
    'e2e_pipeline': 50        # docs per minute
}
```

## Monitoring & Metrics

- Validation error rate by document type
- Pipeline stage latency percentiles
- Fallback parser usage rate
- Test execution time trends
- Memory usage during batch processing

## Dependencies

### Python Packages
```toml
pytest = "^7.4.0"
pytest-asyncio = "^0.21.0"
pytest-cov = "^4.1.0"
pytest-mock = "^3.11.0"
faker = "^19.0.0"  # Generate test data
```

## Notes for Implementation

1. **Test Data**: Use real anonymized Polish legal documents
2. **Performance**: Run performance tests separately
3. **CI/CD**: Integrate tests into pipeline
4. **Documentation**: Generate test report for each run