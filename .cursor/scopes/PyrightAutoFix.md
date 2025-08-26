## Pyright Auto-Fix Workflow Spec (Agent-Driven)

### Purpose & Problem
- Reduce Pyright violations continuously by performing safe, deterministic edits directly (no auto-fix scripts).
- Act immediately after each discovery run triggered by the monitor when HEAD advances (at most every 30 minutes).

### Success Criteria
- Violations trend downward; each successful cycle yields a net reduction in `pyright_reports/all_violations.csv` rows.
- Unit tests pass locally before committing (if tests exist and can run).
- Only commit when:
  - The post-fix Pyright report shows fewer violations than the previous baseline, AND
  - Tests pass (or no test failures are introduced).
- Each cycle appends a clear entry to `reports/pyright_monitor_latest.md` with before/after counts, files changed, and rules affected.

### Scope (Initial Phases)
- Phase A (Low-risk, deterministic; default ON):
  1) Import path normalization (internal modules)
     - Update import lines to correct internal paths (e.g., `app.models.pipeline_schemas` → `app.embedding_models.pipeline_schemas`).
     - Limit to single-line `import` or `from ... import ...` statements.
     - Skip ambiguous multi-line or side-effect imports unless unambiguous.
  2) Pyright configuration hardening
     - Ensure `pyrightconfig.json` is correct (e.g., `extraPaths`, `venvPath`/`venv`).
     - Do not loosen error rules; only improve resolution.
- Phase B (Optional, guarded; enabled when explicitly requested)
  - Add minimal `None` checks for `reportOptionalMemberAccess`/`reportOptionalCall` where an isolated assignment or expression is implicated.
  - Only small, surgical edits; avoid behavior changes.

### Constraints & Safeguards
- Make the smallest change necessary; do not modify business logic beyond what the rule requires.
- Avoid broad refactors or multi-line structural edits in Phase A.
- If changes do not reduce violations or tests fail, revert edits.
- Rate-limit to once per new commit (aligned with monitor cadence).
- Maintain idempotency; repeated runs should not thrash files.

### Technical Considerations
- Inputs
  - `pyright_reports/*.txt` and `pyright_reports/all_violations.csv` from `scripts/pyright_report_by_rule.py`.
- Approach (no auto-fix scripts)
  - The engineer (agent) reviews the latest reports, identifies safe targets, and performs edits directly in the codebase.
  - Use search/grep and the editor for precise, line-scoped changes.

### Process Per Cycle
1) Monitor detects a new commit and runs the discovery script.
2) Agent reviews `pyright_reports/SUMMARY.txt` and per-rule `*.txt` files.
3) Agent performs Phase A edits (and Phase B if explicitly enabled).
4) Re-run the discovery script.
5) If violations reduced AND tests pass:
   - Commit with message like `chore(pyright): agent fixes (-N)`.
   - Optionally push if configured.
   - Log details (before/after, rules impacted, files changed) to `reports/pyright_monitor_latest.md`.
6) If not reduced or tests fail:
   - Revert changes and log outcome.

### Monitor Integration
- The monitor continues to run the discovery script on new commits and writes logs.
- The agent acts immediately after each discovery run to apply fixes; no auto-fix scripts are invoked by the monitor.
- All actions and outcomes are recorded in `reports/pyright_monitor_latest.md`.

### Testing & Validation
- Run local unit tests via `pytest -q` if available; failures abort and trigger revert.
- No interactive prompts; deterministic edits only.

### Rollback Strategy
- Revert the working copy if reductions are not achieved or tests fail.
- Do not accumulate partial edits across cycles.

### Implementation Notes
- Remove reliance on any auto-fix script; fixes are human-in-the-loop edits.
- Keep a short, curated list of known safe import path corrections (tracked in commit messages or in a developer note) to speed up future cycles.

---

Does this capture your intent? If so, I will proceed with agent-driven fixes after each discovery run and follow the commit/push/logging gates above.