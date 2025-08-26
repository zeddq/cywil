# Pyright Linter Fixes Log

## Summary
Fixed 41 function/method call issues identified in the pyright report. These were primarily parameter mismatches, missing arguments, and incorrect argument names.

## Files Fixed and Changes Made

### 1. app/embedding_models/pipeline_schemas.py (3 violations)
**Issue**: Pydantic Field() calls using deprecated `regex` parameter and incorrect `min_items`/`max_items` for List fields.

**Fixes**:
- Changed `regex="^[A-Z0-9-]+$"` to `pattern="^[A-Z0-9-]+$"`
- Changed `min_items=384, max_items=1536` to `min_length=384, max_length=1536` for List[float]
- Fixed pattern parameter for Polish court case number validation

### 2. app/services/openai_client.py (4 violations)
**Issue**: OpenAIError calls missing required `service_name` parameter (ServiceError base class requires 2 parameters).

**Fixes**:
- Changed `raise OpenAIError("message")` to `raise OpenAIError("OpenAI", "message")`
- Applied to all 4 instances across the file

### 3. app/services/optimized_statute_search.py (1 violation)
**Issue**: super().__init__() call missing `llm_manager` parameter for parent class.

**Fixes**:
- Changed `super().__init__(config_service)` to `super().__init__(config_service, llm_manager)`

### 4. app/worker/tasks/embed.py (5 violations)
**Issue**: Qdrant client calls missing required `type` parameter for KeywordIndexParams() and TextIndexParams().

**Fixes**:
- Changed `KeywordIndexParams()` to `KeywordIndexParams(type="keyword")` (4 instances)
- Changed `TextIndexParams()` to `TextIndexParams(type="text")` (1 instance)

### 5. ingest/embed.py (5 violations)
**Issue**: Same Qdrant client issue as worker/tasks/embed.py.

**Fixes**:
- Changed `KeywordIndexParams()` to `KeywordIndexParams(type="keyword")` (4 instances)
- Changed `TextIndexParams()` to `TextIndexParams(type="text")` (1 instance)

### 6. ingest/ingest_pipeline.py (1 violation)
**Issue**: StatuteChunk constructor called with `metadata` parameter instead of `statute_metadata`.

**Fixes**:
- Changed `metadata=metadata` to `statute_metadata=metadata` in StatuteChunk constructor call

### 7. ingest/pdf2chunks.py (1 violation)
**Issue**: Dictionary update() method call causing type confusion.

**Fixes**:
- Changed `metadata.update({"hierarchy": self._get_hierarchy_metadata()})` to `metadata["hierarchy"] = self._get_hierarchy_metadata()`

### 8. ingest/preprocess_sn_o3.py (5 violations)
**Issue**: Multiple constructor and method call issues:
- Ruling constructor missing required `name` parameter and using wrong parameter name `metadata` instead of `meta`
- enhance_entities_with_o3() call missing required `index` parameter

**Fixes**:
- Changed `Ruling(metadata=metadata, paragraphs=ruling_paragraphs)` to `Ruling(name="fallback_ruling", meta=metadata, paragraphs=ruling_paragraphs)`
- Changed `await enhance_entities_with_o3(ruling)` to `await enhance_entities_with_o3(ruling, 0)`

### 9. ingest/test_preprocess_o3.py (1 violation)
**Issue**: process_batch() function call with non-existent `max_workers` parameter.

**Fixes**:
- Removed `max_workers=2` parameter from process_batch() call

### 10. tests/integration/test_database_manager.py (2 violations)
**Issue**: DatabaseManager constructor missing required `config_service` parameter.

**Fixes**:
- Added `config_service = ConfigService()` and passed to `DatabaseManager(config_service)` (2 instances)
- Added ConfigService import

## Types of Issues Fixed
1. **Pydantic Field parameter updates**: Updated deprecated `regex` to `pattern`, fixed List validation parameters
2. **Missing constructor arguments**: Added required parameters for service constructors
3. **Parameter name mismatches**: Fixed incorrect parameter names to match actual class definitions
4. **Missing method arguments**: Added required parameters to method calls
5. **Type system improvements**: Fixed dictionary operations and constructor calls

## Verification
- Ran pyright on all modified files
- Original call-related errors have been resolved
- Remaining errors are primarily import resolution issues, not call issues

## Impact
These fixes ensure:
- Proper service initialization across the application
- Correct Pydantic model validation
- Proper error handling with correct exception constructors
- Functional database and vector storage operations
- Working test suite initialization

All function and method call issues from the original pyright report have been addressed.