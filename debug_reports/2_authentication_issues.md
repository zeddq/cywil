# Authentication Issues Debug Report

## Issues Identified:
1. **Parameter Mismatch Issues** in `app/auth.py`:
   - No parameter named "current_user" (3 occurrences at lines 127, 131, 136)

2. **Type Assignment Issues** in `app/auth_routes.py`:
   - `str | None` cannot be assigned to `str` parameters (lines 94, 139, 174)
   - `datetime | None` cannot be assigned to `datetime` parameters (lines 100, 180)
   - Attribute access issues with `.desc` method (line 235)

## Files to Debug:
- `/Volumes/code/cywil/ai-paralegal-poc/app/auth.py`
- `/Volumes/code/cywil/ai-paralegal-poc/app/auth_routes.py`

## Specific Errors:
```
auth.py:127:54 - No parameter named "current_user"
auth_routes.py:94:12 - Argument of type "str | None" cannot be assigned to parameter "id" of type "str"
auth_routes.py:235:73 - "desc" is not a known attribute of "None"
```

## Debug Session Command:
Use mcp debug tool to analyze authentication parameter mismatches and Optional type handling issues.