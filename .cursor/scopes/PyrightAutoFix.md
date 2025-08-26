## Pyright Auto-Fix Workflow Spec

### Purpose & Problem
- Automate safe and deterministic fixes for a subset of Pyright linter violations after each discovery run, reducing total violations over time without risking functionality.
- Integrate with the existing `scripts/pyright_monitor.sh` so fixes are attempted only when HEAD advances and at most every 30 minutes.

### Success Criteria
- Violations trend downward; each successful run produces a net reduction in `pyright_reports/all_violations.csv` row count.
- Unit tests pass locally before committing (if tests exist in the repo and can run in CI/local env).
- Only commit changes when:
  - Pyright report after fixes shows fewer violations than the previous baseline, AND
  - Tests pass (or no tests fail if present).
- Each fix run appends a clear entry to `reports/pyright_monitor_latest.md`, including before/after counts, changed files, and rules affected.

### Scope (Initial Phases)
- Phase A (Low-risk, deterministic):
  1) Import path normalization (internal modules):
     - Maintain a mapping file for known import rewrites (e.g., `app.models.pipeline_schemas` → `app.embedding_models.pipeline_schemas`).
     - Apply text-level, line-scoped rewrites only to import statements and `from ... import ...` lines.
     - Skip ambiguous cases (multi-line imports, aliased imports with side effects) unless exact match.
  2) Pyright config hardening:
     - Ensure `pyrightconfig.json` includes reasonable `extraPaths` and `venvPath`/`venv` when applicable.
     - Do not loosen error rules; only add paths to improve import resolution.
- Phase B (Optional, guarded; can be enabled later):
  - Add explicit `None` checks for `reportOptionalMemberAccess`/`reportOptionalCall` where a single, isolated expression is implicated.
  - Only performed via AST-aware transform (e.g., `libcst`) and behind a feature flag; default OFF initially due to behavioral risk.

### Constraints & Safeguards
- Never modify business logic beyond the minimal change needed to satisfy the rule.
- Never introduce broad refactors or multi-line structural edits in Phase A.
- If a change does not reduce violations or tests fail, revert edits (per-run working copy is reset).
- Rate-limit to once per new commit (aligned with the monitor cadence).
- Maintain idempotency: running the fixer repeatedly should not thrash files.

### Technical Considerations
- Inputs:
  - `pyright_reports/*.txt` and `pyright_reports/all_violations.csv` produced by `scripts/pyright_report_by_rule.py`.
- Components:
  - `scripts/pyright_autofix.py`: orchestrates fix steps.
  - `scripts/pyright_autofix.mapping.yml`: declarative import-rewrite map (Phase A).
- Process per cycle:
  1) Detect new commit in monitor.
  2) Run discovery script (already implemented).
  3) Run `pyright_autofix.py` with Phase A steps enabled.
  4) If changes made, re-run discovery script.
  5) If net violations reduced AND tests pass:
     - Create a commit with message like `chore(pyright): auto-fix imports (-N)`.
     - Append detailed summary to `reports/pyright_monitor_latest.md`.
     - Optionally push (disabled by default; can be enabled via env var `AUTO_PUSH=1`).
  6) If not reduced or tests fail: revert changes; log outcome.

### Out of Scope (for now)
- Large-scale refactors, API signature changes, behavior-altering transforms.
- Auto-adding new third-party dependencies to `requirements*.txt`.
- Editing generated files or vendored third-party code.

### Configuration & Flags
- Environment variables:
  - `AUTO_PUSH` (default: empty/disabled): when set, push commits after successful local commit.
  - `AUTOFIX_PHASE_B` (default: 0): enable Phase B transforms when set to `1`.
- Files:
  - `scripts/pyright_autofix.mapping.yml`: list of exact string import rewrites, e.g.:
    ```yaml
    imports:
      - from: "from app.models.pipeline_schemas import"
        to:   "from app.embedding_models.pipeline_schemas import"
      - from: "import app.models.pipeline_schemas"
        to:   "import app.embedding_models.pipeline_schemas"
    ```

### Monitor Integration
- Extend `scripts/pyright_monitor.sh` to invoke `pyright_autofix.py` immediately after each discovery run on a new commit.
- The fixer will:
  - Apply mapped import rewrites.
  - Re-run `scripts/pyright_report_by_rule.py`.
  - Decide to commit or revert based on reduction and tests.
- All actions are logged to `reports/pyright_monitor_latest.md`.

### Testing & Validation
- Local unit tests via `pytest -q` if available; failures abort and revert.
- Dry-run mode for the fixer supported (`--dry-run`) to preview changes in logs.
- CI-friendly: No interactive prompts.

### Rollback Strategy
- Use a temporary branch or stash-like workflow per cycle; revert on non-reduction or test failures.
- Do not accumulate partial edits across cycles.

### Implementation Plan
- Step 1: Implement `scripts/pyright_autofix.mapping.yml` with the known import rewrites.
- Step 2: Implement `scripts/pyright_autofix.py` (Phase A only):
  - Parse CSV; identify offending files.
  - Apply line-scoped import rewrites when matched exactly.
  - Track modified files.
  - Re-run pyright discovery; compute deltas.
  - Optionally run tests; gate commit.
  - Commit with structured message; log details.
- Step 3: Integrate into `scripts/pyright_monitor.sh` with a guarded call.
- Step 4 (optional): Add Phase B behind flag using `libcst` for AST-safe transforms.

---

Does this capture your intent? Any changes needed? Spec looks good? Type "GO!" when ready for me to implement Phase A and integrate it with the monitor.