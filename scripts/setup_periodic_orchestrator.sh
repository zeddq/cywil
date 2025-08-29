#!/usr/bin/env bash
# Setup script for periodic Pyright orchestrator
# Configures cron job and validates environment

set -euo pipefail

usage() {
    cat <<'EOF'
Setup Periodic Pyright Orchestrator

Usage:
  setup_periodic_orchestrator.sh [OPTIONS]

Options:
  --cron-schedule SCHEDULE   Cron schedule (default: "0 2 * * *" - daily at 2 AM)
  --project-path PATH        Project directory path (default: current directory)
  --user USER               User to run cron job as (default: current user)
  --dry-run                 Show what would be configured without making changes
  --remove                  Remove existing cron job
  --help                    Show this help

Examples:
  # Setup daily run at 2 AM
  ./setup_periodic_orchestrator.sh

  # Setup run every 6 hours
  ./setup_periodic_orchestrator.sh --cron-schedule "0 */6 * * *"

  # Remove existing cron job
  ./setup_periodic_orchestrator.sh --remove
EOF
}

# Default values
CRON_SCHEDULE="0 2 * * *"  # Daily at 2 AM
PROJECT_PATH="$(pwd)"
USER="$(whoami)"
DRY_RUN=false
REMOVE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --cron-schedule) CRON_SCHEDULE="$2"; shift 2 ;;
        --project-path)  PROJECT_PATH="$2"; shift 2 ;;
        --user)          USER="$2"; shift 2 ;;
        --dry-run)       DRY_RUN=true; shift ;;
        --remove)        REMOVE=true; shift ;;
        --help|-h)       usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

# Resolve absolute path
PROJECT_PATH="$(cd "$PROJECT_PATH" && pwd)"
ORCHESTRATOR_SCRIPT="$PROJECT_PATH/scripts/pyright_orchestrator.sh"
CRON_WRAPPER="$PROJECT_PATH/scripts/cron_orchestrator_wrapper.sh"

echo "=== Pyright Orchestrator Setup ==="
echo "Project path: $PROJECT_PATH"
echo "User: $USER"

if $REMOVE; then
    echo "=== Removing existing cron job ==="
    if $DRY_RUN; then
        echo "Would remove cron job containing 'pyright_orchestrator'"
    else
        # Remove any existing cron job for this orchestrator
        (crontab -l 2>/dev/null | grep -v "pyright_orchestrator" || true) | crontab -
        echo "Cron job removed (if it existed)"
    fi
    exit 0
fi

# Validate environment
echo "=== Validating environment ==="

if [[ ! -f "$ORCHESTRATOR_SCRIPT" ]]; then
    echo "ERROR: Orchestrator script not found: $ORCHESTRATOR_SCRIPT" >&2
    exit 1
fi

if [[ ! -x "$ORCHESTRATOR_SCRIPT" ]]; then
    echo "ERROR: Orchestrator script not executable: $ORCHESTRATOR_SCRIPT" >&2
    exit 1
fi

# Check required commands
for cmd in jj jq claude gh; do
    if ! command -v "$cmd" >/dev/null; then
        echo "WARNING: Command not found: $cmd (may be needed for full functionality)" >&2
    fi
done

# Verify git repository
if [[ ! -d "$PROJECT_PATH/.jj" ]]; then
    echo "ERROR: Not a Jujutsu repository: $PROJECT_PATH" >&2
    exit 1
fi

# Check pyright reports directory
if [[ ! -d "$PROJECT_PATH/pyright_reports" ]]; then
    echo "ERROR: Pyright reports directory not found: $PROJECT_PATH/pyright_reports" >&2
    exit 1
fi

echo "Environment validation passed"

# Create cron wrapper script
echo "=== Creating cron wrapper script ==="

if ! $DRY_RUN; then
    cat > "$CRON_WRAPPER" <<EOF
#!/usr/bin/env bash
# Cron wrapper for Pyright orchestrator
# Ensures proper environment and logging

set -euo pipefail

# Change to project directory
cd "$PROJECT_PATH"

# Setup PATH to include common locations
export PATH="/usr/local/bin:/opt/homebrew/bin:\$PATH"

# Log file with timestamp
LOG_FILE="$PROJECT_PATH/logs/orchestrator_cron.log"
mkdir -p "\$(dirname "\$LOG_FILE")"

# Run orchestrator with logging
echo "=== Orchestrator cron run started at \$(date) ===" >> "\$LOG_FILE"
echo "Environment: USER=\$(whoami), PATH=\$PATH" >> "\$LOG_FILE"

if "$ORCHESTRATOR_SCRIPT" >> "\$LOG_FILE" 2>&1; then
    echo "=== Orchestrator cron run completed successfully at \$(date) ===" >> "\$LOG_FILE"
else
    echo "=== Orchestrator cron run FAILED at \$(date) ===" >> "\$LOG_FILE"
fi

echo "" >> "\$LOG_FILE"
EOF

    chmod +x "$CRON_WRAPPER"
    echo "Cron wrapper created: $CRON_WRAPPER"
else
    echo "Would create cron wrapper: $CRON_WRAPPER"
fi

# Setup cron job
echo "=== Setting up cron job ==="
CRON_COMMAND="$CRON_SCHEDULE $CRON_WRAPPER # pyright_orchestrator"

if $DRY_RUN; then
    echo "Would add cron job:"
    echo "  $CRON_COMMAND"
else
    # Remove any existing orchestrator cron job and add new one
    (
        crontab -l 2>/dev/null | grep -v "pyright_orchestrator" || true
        echo "$CRON_COMMAND"
    ) | crontab -
    
    echo "Cron job added:"
    echo "  $CRON_COMMAND"
fi

# Create logs directory
echo "=== Setting up logging ==="
LOG_DIR="$PROJECT_PATH/logs"

if ! $DRY_RUN; then
    mkdir -p "$LOG_DIR"
    echo "Log directory created: $LOG_DIR"
else
    echo "Would create log directory: $LOG_DIR"
fi

# Final summary
echo "=== Setup Complete ==="
echo "Cron schedule: $CRON_SCHEDULE"
echo "Project path: $PROJECT_PATH"
echo "Orchestrator script: $ORCHESTRATOR_SCRIPT"
echo "Cron wrapper: $CRON_WRAPPER"
echo "Log directory: $LOG_DIR"

echo ""
echo "To monitor cron runs:"
echo "  tail -f $LOG_DIR/orchestrator_cron.log"

echo ""
echo "To test manually:"
echo "  $ORCHESTRATOR_SCRIPT --dry-run"

echo ""
echo "To remove cron job:"
echo "  $0 --remove"