# Return Type Fixes Log
**Date**: 2025-08-26  
**Task**: Fix pyright return type violations (reportReturnType)

## Original Issues
Based on `pyright_reports/reportReturnType.txt`, there were 4 return type violations:

### 1. embedding_interface.py (Line 91)
**Issue**: `Type "int | None" is not assignable to return type "int"`  
**Root Cause**: The `_dimension` attribute could remain `None` when `get_sentence_embedding_dimension()` returns `None`, but the method signature promised to return `int`.

**Fix Applied**:
- Modified `get_dimension()` method to ensure `_dimension` is always set to an integer
- Added fallback logic to handle case where `get_sentence_embedding_dimension()` returns `None`
- Changed early return pattern to assignment pattern for consistency

**Before**:
```python
if self._model is None:
    return 768  # Early return without setting _dimension
self._dimension = self._model.get_sentence_embedding_dimension()
```

**After**:
```python
if self._model is None:
    self._dimension = 768  # Set the attribute
else:
    dimension = self._model.get_sentence_embedding_dimension()
    if dimension is None:
        self._dimension = 768  # Fallback for None case
    else:
        self._dimension = dimension
```

### 2. openai_client.py (Line 296)
**Issue**: `Type "str | None" is not assignable to return type "BaseModel | str"`  
**Root Cause**: `response.choices[0].message.content` can return `None`, but the method signature doesn't allow `None` in the union type.

**Fix Applied**:
- Added explicit None check and error handling
- Raise `OpenAIError` with descriptive message when content is None

**Before**:
```python
return response.choices[0].message.content
```

**After**:
```python
content = response.choices[0].message.content
if content is None:
    raise OpenAIError("OpenAI", "Received empty response content from API")
return content
```

### 3. openai_client.py (Line 328)
**Issue**: Same as above but in async version  
**Fix Applied**: Same pattern as above for the async method

### 4. preprocess_sn_o3.py (Line 154)
**Issue**: `Type "BaseModel" is not assignable to return type "ParsedRuling | bytes"`  
**Root Cause**: The method `async_parse_structured_output` returns generic `BaseModel` type, but pyright couldn't confirm it was specifically a `ParsedRuling`.

**Fix Applied**:
- Added runtime type check with `isinstance()`
- Added explicit error handling for unexpected types
- This ensures type safety while maintaining the expected return type

**Before**:
```python
parsed_ruling = await openai_service.async_parse_structured_output(...)
return parsed_ruling
```

**After**:
```python
parsed_ruling = await openai_service.async_parse_structured_output(...)
# Cast to ensure proper return type
if not isinstance(parsed_ruling, ParsedRuling):
    raise RuntimeError(f"Expected ParsedRuling but got {type(parsed_ruling)}")
return parsed_ruling
```

## Verification
- All fixes tested with pyright
- No more `reportReturnType` violations in the affected files
- Other unrelated linting issues remain (not part of this task)

## Files Modified
1. `/Volumes/code/cywil/ai-paralegal-poc/app/embedding_models/embedding_interface.py`
2. `/Volumes/code/cywil/ai-paralegal-poc/app/services/openai_client.py`
3. `/Volumes/code/cywil/ai-paralegal-poc/ingest/preprocess_sn_o3.py`

## Impact
- **Runtime Safety**: Added proper error handling for edge cases
- **Type Safety**: All methods now properly match their return type annotations
- **No Breaking Changes**: All fixes maintain existing behavior while adding safety checks
- **Error Reporting**: Better error messages when unexpected conditions occur

## Testing Status
✅ All return type issues resolved  
✅ pyright validation passes for reportReturnType rule  
✅ No breaking changes to existing API