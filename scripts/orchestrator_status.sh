#!/usr/bin/env bash
# Monitoring and status script for Pyright orchestrator
# Shows current status, recent runs, and workspace health

set -euo pipefail

usage() {
    cat <<'EOF'
Pyright Orchestrator Status Monitor

Usage:
  orchestrator_status.sh [OPTIONS]

Options:
  --reports NUM           Number of recent reports to show (default: 5)
  --logs NUM             Number of log lines to show (default: 50)
  --workspaces           Show current workspace status
  --cleanup              Clean up old reports and abandoned workspaces
  --watch                Watch mode - refresh status every 30 seconds
  --help                 Show this help

Commands:
  # Show current status
  ./orchestrator_status.sh

  # Show more detailed logs
  ./orchestrator_status.sh --logs 100

  # Clean up old files
  ./orchestrator_status.sh --cleanup

  # Watch live status
  ./orchestrator_status.sh --watch
EOF
}

# Default values
REPORTS_COUNT=5
LOGS_COUNT=50
SHOW_WORKSPACES=false
CLEANUP=false
WATCH_MODE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --reports)     REPORTS_COUNT="$2"; shift 2 ;;
        --logs)        LOGS_COUNT="$2"; shift 2 ;;
        --workspaces)  SHOW_WORKSPACES=true; shift ;;
        --cleanup)     CLEANUP=true; shift ;;
        --watch)       WATCH_MODE=true; shift ;;
        --help|-h)     usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

PROJECT_PATH="$(pwd)"

show_status() {
    local timestamp
    timestamp="$(date)"
    
    echo "=== Pyright Orchestrator Status ($timestamp) ==="
    echo ""
    
    # Check if in correct directory
    if [[ ! -f "scripts/pyright_orchestrator.sh" ]]; then
        echo "ERROR: Not in project directory (orchestrator script not found)"
        return 1
    fi
    
    # Cron job status
    echo "## Cron Job Status"
    if crontab -l 2>/dev/null | grep -q "pyright_orchestrator"; then
        echo "✅ Cron job is configured:"
        crontab -l 2>/dev/null | grep "pyright_orchestrator" | sed 's/^/   /'
    else
        echo "❌ No cron job configured"
    fi
    echo ""
    
    # Recent reports
    echo "## Recent Reports (last $REPORTS_COUNT)"
    if [[ -d "reports" ]]; then
        # Find recent report directories
        mapfile -t recent_reports < <(find reports -maxdepth 1 -type d -name "*T*Z" 2>/dev/null | sort -r | head -n "$REPORTS_COUNT")
        
        if [[ ${#recent_reports[@]} -gt 0 ]]; then
            for report_dir in "${recent_reports[@]}"; do
                local report_time tasks_count success_count
                report_time="$(basename "$report_dir")"
                
                # Count tasks
                if [[ -d "$report_dir/tasks" ]]; then
                    tasks_count=$(find "$report_dir/tasks" -name "*.log" 2>/dev/null | wc -l)
                    success_count=$(find "$report_dir/tasks" -name "*.summary.md" 2>/dev/null | wc -l)
                else
                    tasks_count=0
                    success_count=0
                fi
                
                echo "  📊 $report_time - $success_count/$tasks_count tasks completed"
                
                # Show merged report summary if exists
                if [[ -f "$report_dir/merged_report.md" ]]; then
                    local tasks_processed
                    tasks_processed=$(grep "Tasks Processed:" "$report_dir/merged_report.md" 2>/dev/null | cut -d' ' -f3 || echo "?")
                    echo "     └── Merged report: $tasks_processed tasks processed"
                fi
            done
        else
            echo "  No reports found"
        fi
    else
        echo "  Reports directory not found"
    fi
    echo ""
    
    # Current pyright reports status
    echo "## Current Pyright Reports"
    if [[ -d "pyright_reports" ]]; then
        echo "  Total report files: $(find pyright_reports -name "*.txt" 2>/dev/null | wc -l)"
        echo "  Non-empty reports: $(find pyright_reports -name "*.txt" -size +0c 2>/dev/null | wc -l)"
        echo ""
        echo "  Report files with issues:"
        find pyright_reports -name "report*.txt" -size +0c 2>/dev/null | while read -r file; do
            local line_count
            line_count=$(wc -l < "$file")
            echo "    📄 $(basename "$file"): $line_count lines"
        done
    else
        echo "  ❌ Pyright reports directory not found"
    fi
    echo ""
    
    # Workspace status
    if $SHOW_WORKSPACES || [[ -d ".jj-workspaces" ]]; then
        echo "## Workspace Status"
        if [[ -d ".jj-workspaces" ]]; then
            local workspace_count
            workspace_count=$(find .jj-workspaces -maxdepth 1 -type d -name "ws-*" 2>/dev/null | wc -l)
            echo "  Active workspaces: $workspace_count"
            
            if (( workspace_count > 0 )); then
                echo "  Workspace list:"
                find .jj-workspaces -maxdepth 1 -type d -name "ws-*" 2>/dev/null | sort | while read -r ws; do
                    local ws_name age
                    ws_name="$(basename "$ws")"
                    if [[ -d "$ws" ]]; then
                        age="$(find "$ws" -maxdepth 0 -type d -printf '%TY-%Tm-%Td %TH:%TM' 2>/dev/null || echo "unknown")"
                        echo "    🔧 $ws_name (created: $age)"
                    fi
                done
            fi
        else
            echo "  No workspaces directory found"
        fi
        echo ""
    fi
    
    # Recent logs
    echo "## Recent Logs (last $LOGS_COUNT lines)"
    if [[ -f "logs/orchestrator_cron.log" ]]; then
        echo "  From: logs/orchestrator_cron.log"
        echo "  ---"
        tail -n "$LOGS_COUNT" "logs/orchestrator_cron.log" | sed 's/^/  /'
    else
        echo "  No cron log found at: logs/orchestrator_cron.log"
    fi
}

cleanup_old_files() {
    echo "=== Cleanup Mode ==="
    echo ""
    
    # Clean up old report directories (keep last 10)
    if [[ -d "reports" ]]; then
        echo "## Cleaning up old reports (keeping last 10)"
        mapfile -t all_reports < <(find reports -maxdepth 1 -type d -name "*T*Z" 2>/dev/null | sort -r)
        
        if [[ ${#all_reports[@]} -gt 10 ]]; then
            for (( i=10; i<${#all_reports[@]}; i++ )); do
                echo "  Removing: ${all_reports[i]}"
                rm -rf "${all_reports[i]}"
            done
        else
            echo "  No old reports to clean up"
        fi
    fi
    
    # Clean up abandoned workspaces
    if [[ -d ".jj-workspaces" ]]; then
        echo ""
        echo "## Cleaning up abandoned workspaces"
        
        # Find workspaces older than 24 hours
        find .jj-workspaces -maxdepth 1 -type d -name "ws-*" -mtime +1 2>/dev/null | while read -r ws; do
            local ws_name
            ws_name="$(basename "$ws")"
            echo "  Removing old workspace: $ws_name"
            jj workspace forget "$ws_name" 2>/dev/null || true
            rm -rf "$ws" || true
        done
    fi
    
    # Clean up old log files (keep last 1MB)
    if [[ -f "logs/orchestrator_cron.log" ]]; then
        echo ""
        echo "## Rotating log files"
        local log_size
        log_size="$(stat -c%s "logs/orchestrator_cron.log" 2>/dev/null || echo 0)"
        
        if (( log_size > 1048576 )); then  # 1MB
            echo "  Rotating large log file (${log_size} bytes)"
            tail -n 1000 "logs/orchestrator_cron.log" > "logs/orchestrator_cron.log.tmp"
            mv "logs/orchestrator_cron.log.tmp" "logs/orchestrator_cron.log"
        else
            echo "  Log file size OK (${log_size} bytes)"
        fi
    fi
    
    echo ""
    echo "Cleanup completed"
}

# Main execution
if $CLEANUP; then
    cleanup_old_files
elif $WATCH_MODE; then
    echo "Watch mode - press Ctrl+C to exit"
    echo ""
    while true; do
        clear
        show_status
        sleep 30
    done
else
    show_status
fi