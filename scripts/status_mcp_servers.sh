#!/bin/bash

# Check status of MCP servers

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Base directory
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$BASE_DIR"

echo -e "${BLUE}MCP Server Status${NC}"
echo "========================================"

# Function to check server status
check_server() {
    local name=$1
    local display_name=$2
    local pid_file="logs/mcp_${name}.pid"
    
    printf "%-25s" "$display_name:"
    
    if [ -f "$pid_file" ]; then
        pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            echo -e "${GREEN}✅ Running${NC} (PID: $pid)"
            
            # Show last few log lines if available
            if [ -f "logs/mcp_${name}.log" ]; then
                echo "  Last log entries:"
                tail -n 3 "logs/mcp_${name}.log" | sed 's/^/    /'
            fi
        else
            echo -e "${RED}❌ Stopped${NC} (stale PID file)"
        fi
    else
        # Try to find by process name
        if pgrep -f "$name" > /dev/null; then
            pids=$(pgrep -f "$name" | tr '\n' ' ')
            echo -e "${YELLOW}⚠️  Running${NC} (PIDs: $pids - no PID file)"
        else
            echo -e "${RED}❌ Not running${NC}"
        fi
    fi
    echo ""
}

# Check all servers
check_server "sequential-thinking" "Sequential Thinking"
check_server "serena" "Serena"
check_server "ai-paralegal" "AI Paralegal (Zen)"
check_server "web-rag" "Web RAG"

# Check for orphaned processes
echo -e "${BLUE}Checking for orphaned MCP processes...${NC}"
echo "----------------------------------------"

orphans_found=false

# Check for zen-mcp-server
if pgrep -f "zen-mcp-server" > /dev/null; then
    pids=$(pgrep -f "zen-mcp-server" | tr '\n' ' ')
    echo -e "${YELLOW}Found zen-mcp-server processes:${NC} PIDs: $pids"
    orphans_found=true
fi

# Check for rag_mcp.server
if pgrep -f "rag_mcp.server" > /dev/null; then
    pids=$(pgrep -f "rag_mcp.server" | tr '\n' ' ')
    echo -e "${YELLOW}Found rag_mcp.server processes:${NC} PIDs: $pids"
    orphans_found=true
fi

# Check for modelcontextprotocol
if pgrep -f "modelcontextprotocol" > /dev/null; then
    pids=$(pgrep -f "modelcontextprotocol" | tr '\n' ' ')
    echo -e "${YELLOW}Found modelcontextprotocol processes:${NC} PIDs: $pids"
    orphans_found=true
fi

if [ "$orphans_found" = false ]; then
    echo -e "${GREEN}No orphaned processes found${NC}"
fi

echo ""
echo "========================================"
echo "Log files location: $BASE_DIR/logs/"
echo "To start servers: ./scripts/launch_mcp_servers.sh"
echo "To stop servers:  ./scripts/stop_mcp_servers.sh"
