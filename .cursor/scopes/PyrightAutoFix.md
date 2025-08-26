## Pyright Auto-Fix Workflow Spec (Agent-Driven, Aggressive Mode)

### Purpose & Problem
- Reduce Pyright violations aggressively with safe-but-broader edits applied directly (no auto-fix scripts).
- Act immediately after each discovery run when HEAD advances (≤ every 30 minutes).

### Success Criteria
- Clear downward trend in total violations on each cycle when feasible.
- Tests are executed after fixes and results are logged (non-blocking).
- Commits occur when the post-fix report shows fewer violations than the previous baseline.

### Expanded Scope (Aggressive Mode)
- Dependencies
  - Install/upgrade dependencies into `.venv` from `requirements.txt` and `requirements-test.txt` to resolve import issues.
  - May pin minor versions as needed (only if strictly required for import resolution).
- Import corrections
  - Replace incorrect internal imports (e.g., `app.models.pipeline_schemas` → `app.embedding_models.pipeline_schemas`).
  - Normalize relative imports to absolute `app.*` where appropriate (e.g., `..models.pipeline_schemas` → `app.embedding_models.pipeline_schemas`).
  - Fix mixed package/module import paths in tests to reference production modules consistently.
- Pyright configuration
  - Adjust `pyrightconfig.json` `extraPaths`, `venvPath`/`venv`, and test roots if needed to reflect the workspace layout.
  - Do not loosen error severities beyond project standards, but may mark specific noisy rules as information where appropriate.
- Optional value guards (Phase B)
  - Apply minimal `None` checks for `reportOptionalMemberAccess`/`reportOptionalCall` in simple assignments/expressions when it clearly removes false-positive risk.
  - Keep changes localized and behavior-neutral.
- Limited stubs
  - Add minimal type-only stubs for third-party packages not strictly required at runtime to quiet type checker noise (as a last resort).

### Constraints & Safeguards
- Prefer correctness-preserving edits; avoid behavior changes.
- Keep edits small and reviewable; batch related import fixes together.
- If no reduction is achieved, revert edits for that cycle. Test failures are logged and non-blocking.
- Maintain idempotency and avoid thrashing.

### Process Per Cycle
1) Monitor detects a new commit and runs discovery.
2) Agent reviews `pyright_reports` outputs.
3) Perform aggressive edits:
   - Install deps, correct imports, adjust `pyrightconfig.json`, and apply Phase B guards where safe.
4) Re-run discovery.
5) If violations reduced:
   - Run tests; record results (non-blocking).
   - Commit with `chore(pyright): agent aggressive fixes (-N)` and optionally push.
   - Log details and test summary to `reports/pyright_monitor_latest.md`.
6) If not reduced: revert and log.

### Testing & Validation
- Run `pytest -q` if available; log failures (non-blocking).

### Rollback Strategy
- Revert working copy if no reduction is achieved.

---

This aggressive mode will be used for upcoming manual fix cycles to accelerate reduction of violations.