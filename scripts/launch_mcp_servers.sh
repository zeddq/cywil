#!/bin/bash

# Launch MCP servers defined in .mcp.json
# This script starts the MCP servers in separate background processes

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Base directory
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$BASE_DIR"

echo -e "${GREEN}Starting MCP Servers...${NC}"
echo "========================================"

# Function to start a server
start_server() {
    local name=$1
    local command=$2
    local args=$3
    
    echo -e "${YELLOW}Starting $name...${NC}"
    
    # Check if the server is already running
    if pgrep -f "$name" > /dev/null; then
        echo -e "${YELLOW}  ⚠️  $name is already running${NC}"
    else
        # Start the server in background
        nohup $command $args > "logs/mcp_${name}.log" 2>&1 &
        local pid=$!
        echo -e "${GREEN}  ✅ $name started (PID: $pid)${NC}"
        echo "$pid" > "logs/mcp_${name}.pid"
    fi
}

# Create logs directory if it doesn't exist
mkdir -p logs

# 1. Sequential Thinking Server
start_server "sequential-thinking" \
    "npx" \
    "-y @modelcontextprotocol/server-sequential-thinking"

# 2. Serena Server
start_server "serena" \
    "sh" \
    "-c 'exec $(which uvx || echo uvx) --from git+https://github.com/oraios/serena serena start-mcp-server --context agent --mode interactive'"

# 3. AI Paralegal Server (Zen MCP Server)
# Export required environment variables
export OPENAI_API_KEY="${OPENAI_API_KEY}"
export GOOGLE_API_KEY="${GOOGLE_API_KEY}"
export REDIS_URL="${REDIS_URL}"
export XAI_API_KEY="${XAI_API_KEY}"
export GOOGLE_ALLOWED_MODELS="gemini-2.5-pro,gemini-2.5-flash"
export OPENAI_ALLOWED_MODELS="gpt-5,gpt-5-mini,gpt-5-nanoi,o3-pro"
export GROK_ALLOWED_MODELS="grok-4"

start_server "ai-paralegal" \
    "sh" \
    "-c 'exec $(which uvx || echo uvx) --from git+https://github.com/BeehiveInnovations/zen-mcp-server.git zen-mcp-server'"

# 4. Web RAG Server
export CHROMA_PERSIST_DIR="/Users/cezary/ragger/data/chroma"
export CHROMA_COLLECTION="web_rag"

# Note: Web RAG server requires specific directory
if [ -d "/Users/cezary/ragger" ]; then
    echo -e "${YELLOW}Starting web-rag...${NC}"
    cd /Users/cezary/ragger
    if [ -f ".venv/bin/python" ]; then
        nohup .venv/bin/python -m rag_mcp.server > "$BASE_DIR/logs/mcp_web-rag.log" 2>&1 &
        local pid=$!
        echo -e "${GREEN}  ✅ web-rag started (PID: $pid)${NC}"
        echo "$pid" > "$BASE_DIR/logs/mcp_web-rag.pid"
    else
        echo -e "${RED}  ❌ Web RAG virtual environment not found at /Users/cezary/ragger/.venv${NC}"
    fi
    cd "$BASE_DIR"
else
    echo -e "${RED}  ❌ Web RAG directory not found at /Users/cezary/ragger${NC}"
fi

echo ""
echo -e "${GREEN}MCP Server Status:${NC}"
echo "========================================"
echo "Check logs in: $BASE_DIR/logs/"
echo ""
echo "To stop servers, run: $BASE_DIR/scripts/stop_mcp_servers.sh"
echo "To check status, run: $BASE_DIR/scripts/status_mcp_servers.sh"
