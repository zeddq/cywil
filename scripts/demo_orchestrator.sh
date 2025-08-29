#!/usr/bin/env bash
# Demo script for Pyright Orchestrator system
# Shows complete workflow and available commands

set -euo pipefail

echo "🤖 Pyright Orchestrator with AI Agent Integration Demo"
echo "====================================================="
echo ""

echo "📋 System Overview:"
echo "The orchestrator spawns parallel AI agents to fix Pyright type errors using:"
echo "- Isolated Jujutsu workspaces for each task"
echo "- Claude Code Task tool integration for AI agent spawning"
echo "- Three-phase worker process (Setup → AI Agent → Validate/PR)"
echo "- Allowlist-based file modification guardrails"
echo "- Automatic PR creation and comprehensive reporting"
echo ""

echo "🔍 Current System Status:"
echo "------------------------"
./scripts/orchestrator_status.sh
echo ""

echo "📊 Available Report Files:"
echo "--------------------------"
if [[ -d "pyright_reports" ]]; then
    echo "Total report files: $(find pyright_reports -name "*.txt" 2>/dev/null | wc -l)"
    echo "Files with issues:"
    find pyright_reports -name "report*.txt" -size +0c 2>/dev/null | while read -r file; do
        lines=$(wc -l < "$file")
        echo "  🐛 $(basename "$file"): $lines issues"
    done
else
    echo "❌ No pyright_reports directory found"
fi
echo ""

echo "🧪 Demo Commands:"
echo "----------------"
echo ""

echo "1️⃣  Dry Run (Preview what would happen):"
echo "   ./scripts/pyright_orchestrator.sh --dry-run"
echo ""

echo "2️⃣  Run Single Task (Safe test):"
echo "   # First, create a test workspace to verify everything works"
echo "   jj workspace add test-demo"
echo "   cd .jj-workspaces/test-demo"
echo "   ../../scripts/pyright_worker_prefix.sh --workspace \$(pwd) --bookmark test-demo --allowlist-file ../../pyright_reports/reportMissingImports.txt"
echo ""

echo "3️⃣  Full Orchestrator Run:"
echo "   ./scripts/pyright_orchestrator.sh"
echo ""

echo "4️⃣  Setup Periodic Runs:"
echo "   ./scripts/setup_periodic_orchestrator.sh --dry-run  # Preview"
echo "   ./scripts/setup_periodic_orchestrator.sh             # Actually setup"
echo ""

echo "5️⃣  Monitor Status:"
echo "   ./scripts/orchestrator_status.sh --watch    # Live monitoring"
echo "   ./scripts/orchestrator_status.sh --cleanup  # Clean old files"
echo ""

echo "🏗️  Architecture Components:"
echo "----------------------------"
echo ""
echo "Core Scripts:"
echo "├── scripts/pyright_orchestrator.sh          # Main orchestrator"  
echo "├── scripts/spawn_linter_agent.sh            # AI agent integration"
echo "├── scripts/pyright_worker_prefix.sh         # Phase 1: Setup"
echo "├── scripts/pyright_worker_postfix.sh        # Phase 3: Validate/PR"
echo "├── scripts/setup_periodic_orchestrator.sh   # Cron configuration" 
echo "└── scripts/orchestrator_status.sh           # Monitoring & status"
echo ""
echo "Data Flow:"
echo "├── pyright_reports/                         # Input: Error allowlists"
echo "├── .jj-workspaces/                          # Temp: Isolated workspaces"
echo "├── reports/{timestamp}/                     # Output: Run results"
echo "└── logs/                                    # Logs: Cron execution"
echo ""

echo "🔧 Key Features:"
echo "----------------"
echo "✅ Concurrent AI agent spawning (max 6 workers)"
echo "✅ Isolated Jujutsu workspaces per task"
echo "✅ Claude Code Task tool integration"
echo "✅ Allowlist-based file modification guardrails"
echo "✅ Three-phase worker process with validation"
echo "✅ Automatic GitHub PR creation"
echo "✅ Comprehensive reporting and monitoring"
echo "✅ Cleanup and workspace management"
echo "✅ Cron job setup for periodic runs"
echo ""

echo "⚙️  Configuration:"
echo "------------------"
echo "Environment Variables:"
echo "  BASE_BOOKMARK=${BASE_BOOKMARK:-main}      # Base branch/bookmark"
echo "  MAX_CONCURRENCY=${MAX_CONCURRENCY:-6}    # Max parallel workers"
echo ""
echo "Supported Pyright Error Types (16 total):"
echo "  reportArgumentType, reportMissingImports, reportOptionalMemberAccess"
echo "  reportAttributeAccessIssue, reportCallIssue, reportUndefinedVariable"
echo "  and 10 more... (see docs/PYRIGHT_ORCHESTRATOR.md)"
echo ""

echo "📚 Documentation:"
echo "-----------------"
echo "Complete documentation: docs/PYRIGHT_ORCHESTRATOR.md"
echo ""

echo "🚀 Quick Start:"
echo "---------------"
echo "1. Run dry-run: ./scripts/pyright_orchestrator.sh --dry-run"
echo "2. Check status: ./scripts/orchestrator_status.sh"
echo "3. Run for real: ./scripts/pyright_orchestrator.sh"
echo "4. Setup cron:   ./scripts/setup_periodic_orchestrator.sh"
echo ""

if command -v jj >/dev/null; then
    echo "✅ Jujutsu (jj) is installed"
else
    echo "❌ Jujutsu (jj) not found - install with: brew install jj"
fi

if command -v claude >/dev/null; then
    echo "✅ Claude Code CLI is installed"
else
    echo "❌ Claude Code CLI not found - install from Anthropic"
fi

if command -v gh >/dev/null; then
    echo "✅ GitHub CLI (gh) is installed"
else
    echo "❌ GitHub CLI not found - install with: brew install gh"
fi

if command -v jq >/dev/null; then
    echo "✅ jq is installed"
else
    echo "❌ jq not found - install with: brew install jq"
fi

echo ""
echo "🎯 Ready to orchestrate Pyright fixes with AI agents!"
echo "Run './scripts/pyright_orchestrator.sh --dry-run' to get started safely."