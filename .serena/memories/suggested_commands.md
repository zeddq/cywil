# Suggested Commands

## Development Commands
```bash
# Activate virtual environment (if using venv)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start services
docker-compose up -d

# Run application
cd app && python main.py

# Run Celery worker
python run_celery_worker.py
```

## Linting & Formatting
```bash
# Run all linters
./scripts/lint-all.sh

# Run pyright type checking
pyright

# Run black formatting
black .

# Run pylint
pylint app/

# Generate pyright reports by rule
python scripts/pyright_report_by_rule.py
```

## Testing
```bash
# Run tests
pytest

# Run with coverage
pytest --cov
```

## Linter Orchestrator (Main Feature)
```bash
# Start the periodic pyright orchestrator with AI agent integration
./concurrency_gate_script.sh

# Check individual pyright reports
ls pyright_reports/report*.txt
```

## Jujutsu (Version Control)
```bash
# Fetch updates
jj git fetch

# Create new workspace
jj workspace add path/to/workspace

# Push bookmark
jj git push --bookmark branch-name
```

## Database Operations
```bash
# Run migrations
python run_migrations.py

# Initialize database
python init_database.py
```