#!/bin/bash

# Stop MCP servers

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Base directory
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$BASE_DIR"

echo -e "${YELLOW}Stopping MCP Servers...${NC}"
echo "========================================"

# Function to stop a server
stop_server() {
    local name=$1
    local pid_file="logs/mcp_${name}.pid"
    
    echo -e "${YELLOW}Stopping $name...${NC}"
    
    if [ -f "$pid_file" ]; then
        pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid"
            echo -e "${GREEN}  ✅ $name stopped (PID: $pid)${NC}"
            rm "$pid_file"
        else
            echo -e "${YELLOW}  ⚠️  $name was not running (stale PID: $pid)${NC}"
            rm "$pid_file"
        fi
    else
        # Try to find and kill by name
        if pgrep -f "$name" > /dev/null; then
            pkill -f "$name"
            echo -e "${GREEN}  ✅ $name stopped${NC}"
        else
            echo -e "${YELLOW}  ⚠️  $name is not running${NC}"
        fi
    fi
}

# Stop all servers
stop_server "sequential-thinking"
stop_server "serena"
stop_server "ai-paralegal"
stop_server "web-rag"

# Also try to kill any zen-mcp-server processes
if pgrep -f "zen-mcp-server" > /dev/null; then
    pkill -f "zen-mcp-server"
    echo -e "${GREEN}  ✅ Stopped zen-mcp-server processes${NC}"
fi

# Kill any rag_mcp.server processes
if pgrep -f "rag_mcp.server" > /dev/null; then
    pkill -f "rag_mcp.server"
    echo -e "${GREEN}  ✅ Stopped rag_mcp.server processes${NC}"
fi

echo ""
echo -e "${GREEN}All MCP servers stopped${NC}"
