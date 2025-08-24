# Attribute Access Issues Debug Report

## Issues Identified:
1. **Unknown Attribute Access** on various classes:
   - BaseModel attributes (name, age, active) in test files
   - QueryOptimizer methods and attributes (_query_cache, _query_patterns, optimize_query, analyze_pattern)
   - EmbeddingBatcher methods and attributes (_embedder, _batch_processor, _cache, start, stop)
   - Various core service classes missing expected attributes

2. **Patterns Observed**:
   - Private attribute access issues (underscore prefixed)
   - Method access on dynamically created classes
   - Test mock/fixture attribute access

## Files to Debug:
- `/Volumes/code/cywil/ai-paralegal-poc/tests/unit/test_performance_utils.py`
- `/Volumes/code/cywil/ai-paralegal-poc/tests/unit/test_tool_registry.py`
- Various core service files with attribute access issues

## Specific Errors:
```
Cannot access attribute "_query_cache" for class "QueryOptimizer"
Cannot access attribute "name" for class "BaseModel"
Cannot access attribute "start" for class "EmbeddingBatcher"
```

## Debug Session Command:
Use mcp debug tool to analyze class attribute definitions and fix missing method/property declarations.