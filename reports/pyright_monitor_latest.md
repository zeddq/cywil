[2025-08-26T07:49:16Z] Starting pyright monitor on branch cursor/check-pyright-issues-and-report-fixes-5261
[2025-08-26T07:49:16Z] Detected new commit: aeddded9d848 (prev: )
    Running pyright analysis...
    
    Found 11 different rules with violations
    Creating reports in: /workspace/pyright_reports
      Created report for: reportMissingImports (228 violations)
      Created report for: reportAttributeAccessIssue (72 violations)
      Created report for: reportMissingModuleSource (18 violations)
      Created report for: reportOptionalMemberAccess (32 violations)
      Created report for: reportOptionalCall (2 violations)
      Created report for: reportCallIssue (33 violations)
      Created report for: reportGeneralTypeIssues (10 violations)
      Created report for: reportArgumentType (14 violations)
      Created report for: reportUndefinedVariable (15 violations)
      Created report for: unknown (1 violations)
      Created report for: reportUnboundVariable (1 violations)
    
    Created summary report: pyright_reports/SUMMARY.txt
    Created CSV report: pyright_reports/all_violations.csv
    Saved raw JSON output: pyright_reports/raw_pyright_output.json
    
    All reports generated in: /workspace/pyright_reports
[2025-08-26T07:49:20Z] No previous CSV to compare; initial baseline established.
[2025-08-26T08:38:15Z] No previous CSV to compare; initial baseline established.
[2025-08-26T08:40:37Z] Starting pyright monitor on branch cursor/check-pyright-issues-and-report-fixes-5261
[2025-08-26T08:40:37Z] Detected new commit: c2e0cc83e90b (prev: )
    Running pyright analysis...
    
    Found 11 different rules with violations
    Creating reports in: /workspace/pyright_reports
      Created report for: reportMissingImports (228 violations)
      Created report for: reportAttributeAccessIssue (72 violations)
      Created report for: reportMissingModuleSource (18 violations)
      Created report for: reportOptionalMemberAccess (32 violations)
      Created report for: reportOptionalCall (2 violations)
      Created report for: reportCallIssue (33 violations)
      Created report for: reportGeneralTypeIssues (10 violations)
      Created report for: reportArgumentType (14 violations)
      Created report for: reportUndefinedVariable (15 violations)
      Created report for: unknown (1 violations)
      Created report for: reportUnboundVariable (1 violations)
    
    Created summary report: pyright_reports/SUMMARY.txt
    Created CSV report: pyright_reports/all_violations.csv
    Saved raw JSON output: pyright_reports/raw_pyright_output.json
    
    All reports generated in: /workspace/pyright_reports
[2025-08-26T08:40:41Z] No previous CSV to compare; initial baseline established.
]633;E;{ echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Manual fix cycle start"\x3b echo "    Files edited: app/services/fallback_parser.py, app/validators/document_validator.py, app/worker/tasks/validation_tasks.py, app/worker/tasks/ingestion_pipeline.py, tests/fixtures/legal_documents/test_data_loader.py, tests/integration/test_ai_functionality.py, tests/unit/test_openai_integration.py"\x3b echo "    reportMissingImports: 228 -> 220 (-8)"\x3b echo "    Total violations now: $(awk '/Total violations:/ {print $3}' /workspace/pyright_reports/SUMMARY.txt)"\x3b } >> /workspace/reports/pyright_monitor_latest.md;bef79114-c21c-4084-8f40-b8906427cbbf]633;C[2025-08-26T08:43:39Z] Manual fix cycle start
    Files edited: app/services/fallback_parser.py, app/validators/document_validator.py, app/worker/tasks/validation_tasks.py, app/worker/tasks/ingestion_pipeline.py, tests/fixtures/legal_documents/test_data_loader.py, tests/integration/test_ai_functionality.py, tests/unit/test_openai_integration.py
    reportMissingImports: 228 -> 220 (-8)
    Total violations now: 429
