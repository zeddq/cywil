#!/bin/bash

# AI Paralegal Testing Scripts
# This script provides convenient ways to test the AI Paralegal system

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
API_URL="http://localhost:8000"
DOCKER_COMPOSE_FILE="docker-compose.yml"

# Helper functions
print_header() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

# Check if Docker services are running
check_services() {
    print_header "Checking Services"
    
    if ! docker-compose ps | grep -q "Up"; then
        print_warning "Docker services not running. Starting services..."
        docker-compose up -d
        sleep 10
    fi
    
    # Check API health
    if curl -s "$API_URL/health" > /dev/null 2>&1; then
        print_success "API is responding at $API_URL"
    else
        print_error "API is not responding at $API_URL"
        print_warning "Make sure services are running: docker-compose up -d"
        exit 1
    fi
}

# Run ingestion pipeline
run_ingestion() {
    print_header "Running Data Ingestion Pipeline"
    
    docker-compose exec -e POSTGRES_HOST=postgres -e REDIS_HOST=redis api python ingest/ingest_pipeline.py --qdrant-host=qdrant --qdrant-port=6333
    
    print_success "Ingestion completed"
}

# Validate ingestion
validate_ingestion() {
    print_header "Validating Ingestion"
    
    docker-compose exec -e POSTGRES_HOST=postgres -e REDIS_HOST=redis api python ingest/ingest_pipeline.py --validate-only --qdrant-host=qdrant --qdrant-port=6333
    
    print_success "Validation completed"
}

# Test CLI (direct Python)
test_cli() {
    print_header "Testing CLI Interface"
    
    echo -e "${YELLOW}Running example CLI queries...${NC}"
    docker-compose exec api python test_cli.py --examples
    
    print_success "CLI tests completed"
}

# Test API endpoints
test_api() {
    print_header "Testing API Endpoints"
    
    echo -e "${YELLOW}Running API tests...${NC}"
    python test_api.py --examples --base-url "$API_URL"
    
    print_success "API tests completed"
}

# Interactive chat via API
interactive_api() {
    print_header "Starting Interactive API Chat"
    
    echo -e "${YELLOW}Starting interactive mode...${NC}"
    echo -e "${YELLOW}Use 'quit' to exit${NC}"
    python test_api.py -i --base-url "$API_URL"
}

# Interactive chat via CLI
interactive_cli() {
    print_header "Starting Interactive CLI Chat"
    
    echo -e "${YELLOW}Starting interactive mode...${NC}"
    echo -e "${YELLOW}Use 'quit' to exit${NC}"
    docker-compose exec api python test_cli.py -i
}

# Quick question via API
quick_question() {
    if [ -z "$1" ]; then
        echo "Usage: $0 ask \"Your question here\""
        exit 1
    fi
    
    print_header "Quick Question"
    
    python test_api.py -c "$1" --base-url "$API_URL"
}

# Quick question via CLI
quick_question_cli() {
    if [ -z "$1" ]; then
        echo "Usage: $0 ask-cli \"Your question here\""
        exit 1
    fi
    
    print_header "Quick Question (CLI)"
    
    docker-compose exec api python test_cli.py -q "$1"
}

# Search documents using search_documents() function
search_documents() {
    if [ -z "$1" ]; then
        echo "Usage: $0 search \"Your search query here\""
        exit 1
    fi
    
    print_header "Searching Documents"
    
    docker-compose exec -e POSTGRES_HOST=postgres -e REDIS_HOST=redis api python -c "
import sys
sys.path.append('/app')
from app.tools import search_documents
import json

query = '$1'
print(f'Searching for: {query}')
print('-' * 50)

results = search_documents(query)
if results:
    for i, result in enumerate(results, 1):
        print(f'{i}. {result.get(\"citation\", \"N/A\")}')
        print(f'   Score: {result.get(\"score\", \"N/A\"):.4f}')
        print(f'   Text: {result.get(\"text\", \"N/A\")[:200]}...')
        print()
else:
    print('No results found.')
"
}

# Get audit records using orchestrator's get_audit_records() function
get_audit_records() {
    print_header "Getting Audit Records"
    
    # Parse optional arguments
    THREAD_ID=""
    CASE_ID=""
    LIMIT=""
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --thread-id)
                THREAD_ID="$2"
                shift 2
                ;;
            --case-id)
                CASE_ID="$2"
                shift 2
                ;;
            --limit)
                LIMIT="$2"
                shift 2
                ;;
            *)
                echo "Unknown option: $1"
                echo "Usage: $0 audit [--thread-id THREAD_ID] [--case-id CASE_ID] [--limit LIMIT]"
                exit 1
                ;;
        esac
    done
    
    docker-compose exec -e POSTGRES_HOST=postgres -e REDIS_HOST=redis api python -c "
import sys
import asyncio
sys.path.append('/app')
from app.orchestrator import ParalegalAgent
import json

async def get_audits():
    agent = ParalegalAgent()
    
    # Build arguments dictionary
    kwargs = {}
    if '$THREAD_ID':
        kwargs['thread_id'] = '$THREAD_ID'
    if '$CASE_ID':
        kwargs['case_id'] = '$CASE_ID'
    if '$LIMIT':
        kwargs['limit'] = int('$LIMIT')
    
    print('Getting audit records with arguments:', kwargs)
    print('-' * 50)
    
    try:
        records = await agent.get_audit_records(**kwargs)
        
        if records:
            for i, record in enumerate(records, 1):
                print(f'{i}. Interaction: {record.get(\"interaction_id\", \"N/A\")}')
                print(f'   Status: {record.get(\"status\", \"N/A\")}')
                print(f'   Duration: {record.get(\"duration_seconds\", 0):.2f}s')
                print(f'   User Message: {record.get(\"user_message\", \"N/A\")[:100]}...')
                print(f'   Case ID: {record.get(\"case_id\", \"None\")}')
                print(f'   Thread ID: {record.get(\"thread_id\", \"N/A\")}')
                
                # Count tool calls in audit trail
                tool_calls = [entry for entry in record.get('audit_trail', []) if entry.get('type') == 'tool_call']
                print(f'   Tool Calls: {len(tool_calls)}')
                
                for tool in tool_calls:
                    status = tool.get('status', 'unknown')
                    exec_time = tool.get('execution_time_seconds', 0)
                    print(f'     - {tool.get(\"tool_name\", \"unknown\")}: {status} ({exec_time:.2f}s)')
                
                print()
        else:
            print('No audit records found.')
            
    except Exception as e:
        print(f'Error: {str(e)}')

asyncio.run(get_audits())
"
}

# Show usage
show_usage() {
    echo "AI Paralegal Testing Script"
    echo ""
    echo "Usage: $0 [command] [options]"
    echo ""
    echo "Commands:"
    echo "  start              - Start Docker services"
    echo "  stop               - Stop Docker services"
    echo "  restart            - Restart Docker services"
    echo "  status             - Check service status"
    echo "  ingest             - Run data ingestion pipeline"
    echo "  validate           - Validate ingestion results"
    echo "  test-cli           - Test CLI interface"
    echo "  test-api           - Test API endpoints"
    echo "  chat-api           - Interactive chat via API"
    echo "  chat-cli           - Interactive chat via CLI"
    echo "  ask \"question\"     - Quick question via API"
    echo "  ask-cli \"question\" - Quick question via CLI"
    echo "  search \"query\"     - Search documents using search_documents()"
    echo "  audit [options]    - Get audit records from orchestrator"
    echo "  logs               - Show service logs"
    echo "  help               - Show this help"
    echo ""
    echo "Examples:"
    echo "  $0 start"
    echo "  $0 ask \"Jakie są terminy apelacji?\""
    echo "  $0 search \"roszczenie o zapłatę\""
    echo "  $0 audit --limit 5"
    echo "  $0 audit --case-id case_123 --limit 10"
    echo "  $0 audit --thread-id thread_abc"
    echo "  $0 chat-api"
    echo "  $0 test-api"
}

# Main script logic
case "${1:-help}" in
    "start")
        print_header "Starting Services"
        docker-compose up -d
        print_success "Services started"
        ;;
    "stop")
        print_header "Stopping Services"
        docker-compose down
        print_success "Services stopped"
        ;;
    "restart")
        print_header "Restarting Services"
        docker-compose restart
        print_success "Services restarted"
        ;;
    "status")
        print_header "Service Status"
        docker-compose ps
        check_services
        ;;
    "ingest")
        check_services
        run_ingestion
        ;;
    "validate")
        check_services
        validate_ingestion
        ;;
    "test-cli")
        check_services
        test_cli
        ;;
    "test-api")
        check_services
        test_api
        ;;
    "chat-api")
        check_services
        interactive_api
        ;;
    "chat-cli")
        check_services
        interactive_cli
        ;;
    "ask")
        check_services
        quick_question "$2"
        ;;
    "ask-cli")
        check_services
        quick_question_cli "$2"
        ;;
    "search")
        check_services
        search_documents "$2"
        ;;
    "audit")
        check_services
        shift  # Remove 'audit' from arguments
        get_audit_records "$@"
        ;;
    "logs")
        docker-compose logs -f "${2:-api}"
        ;;
    "help"|*)
        show_usage
        ;;
esac
