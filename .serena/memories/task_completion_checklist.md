# Task Completion Checklist

When completing development tasks:

## Code Quality
- [ ] Run linters: `./scripts/lint-all.sh`
- [ ] Fix pyright type errors: `pyright`
- [ ] Format code: `black .`
- [ ] Check pylint warnings: `pylint app/`

## Testing
- [ ] Run unit tests: `pytest`
- [ ] Check test coverage: `pytest --cov`
- [ ] Manual testing if applicable

## For Linter Orchestrator Tasks
- [ ] Check pyright reports: `ls pyright_reports/report*.txt`
- [ ] Validate allowlist files exist and contain relevant paths
- [ ] Test worker scripts: `scripts/pyright_worker_prefix.sh --help`
- [ ] Verify jj workspaces are clean: `jj workspace list`

## Git/Jujutsu
- [ ] Commit changes with descriptive message
- [ ] Push to appropriate branch/bookmark
- [ ] Create PR if needed via `gh pr create`

## Database (if applicable)
- [ ] Run migrations: `python run_migrations.py`
- [ ] Check database schema integrity

## Services
- [ ] Restart services if configuration changed: `docker-compose restart`
- [ ] Verify health checks pass