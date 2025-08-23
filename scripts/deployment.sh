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

login() {
    print_header "Logging in"
    curl -d "username=zeddq1@gmail.com&password=ahciwd123" "$API_URL/api/auth/login" | jq -r .access_token | tee auth_token.txt
    print_success "Logged in"
}

# Check if Docker services are running
check_services() {
    print_header "Checking Services"
    
    if ! docker-compose ps | grep -q "Up"; then
        print_warning "Docker services not running. Starting services..."
        docker-compose up -d
        sleep 10
    fi

    login
    
    # Check API health
    if curl -H "Authorization: Bearer $(cat auth_token.txt)" "$API_URL/health" | jq . ; then
        print_success "API is responding at $API_URL"
    else
        print_error "API is not responding at $API_URL"
        print_warning "Make sure services are running: docker-compose up -d"
        exit 1
    fi
}

run_api() {
    print_header "Running API"
    source ../venv/bin/activate
    POSTGRES_HOST=localhost QDRANT_HOST=localhost python test_api.py "$@"
    print_success "API completed"
}

# Run ingestion pipeline
run_ingestion() {
    print_header "Running Data Ingestion Pipeline"
    
    docker-compose exec -e POSTGRES_HOST=localhost -e REDIS_HOST=redis api python ingest/ingest_pipeline.py --qdrant-host=localhost --qdrant-port=6333
    
    print_success "Ingestion completed"
}

# Run ingestion pipeline for templates
run_ingestion_templates() {
    print_header "Running Data Ingestion Pipeline for Templates"
    
    docker-compose exec -e POSTGRES_HOST=postgres -e REDIS_HOST=redis -e QDRANT_HOST=qdrant -e QDRANT_PORT=6333 api python ingest/templates.py
    
    print_success "Ingestion for templates completed"
}

# Run ingestion pipeline for templates
run_ingestion_rulings() {
    print_header "Running Data Ingestion Pipeline for Rulings"
    
    docker-compose exec -e POSTGRES_HOST=postgres -e REDIS_HOST=redis -e QDRANT_HOST=qdrant -e QDRANT_PORT=6333 api python ingest/sn.py
    
    print_success "Ingestion for rulings completed"
}

# Validate ingestion
validate_ingestion() {
    print_header "Validating Ingestion"
    
    docker-compose exec -e POSTGRES_HOST=postgres -e REDIS_HOST=redis api python ingest/ingest_pipeline.py --validate-only --qdrant-host=qdrant --qdrant-port=6333
    
    print_success "Validation completed"
}

# Search documents using internal search_documents() function
# This bypasses the API for direct testing
search_documents() {
    if [ -z "$1" ]; then
        echo "Usage: $0 search "Your search query here""
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

print("For API testing, use the dedicated 'test_api.py' script.")
echo "Example: python test_api.py --help"
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

# Create a case
create_case() {
    # Default values for optional fields
    DESCRIPTION=""
    OPPOSING_PARTY=""
    AMOUNT_IN_DISPUTE="null"

    # Parse named arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --case-number)
                reference_number="$2"
                shift 2
                ;;
            --title)
                TITLE="$2"
                shift 2
                ;;
            --description)
                DESCRIPTION="$2"
                shift 2
                ;;
            --case-type)
                CASE_TYPE="$2"
                shift 2
                ;;
            --client-name)
                CLIENT_NAME="$2"
                shift 2
                ;;
            --client-contact)
                CLIENT_CONTACT="$2"
                shift 2
                ;;
            --opposing-party)
                OPPOSING_PARTY="$2"
                shift 2
                ;;
            --amount-in-dispute)
                AMOUNT_IN_DISPUTE="$2"
                shift 2
                ;;
            *)
                echo "Unknown option: $1"
                show_usage
                exit 1
                ;;
        esac
    done

    # Validate required arguments
    if [ -z "$reference_number" ] || [ -z "$TITLE" ] || [ -z "$CASE_TYPE" ] || [ -z "$CLIENT_NAME" ] || [ -z "$CLIENT_CONTACT" ]; then
        echo "Error: Missing required arguments for create-case."
        echo "Usage: $0 create-case --case-number <num> --title <title> --case-type <type> --client-name <name> --client-contact <json> [options]"
        exit 1
    fi

    # Construct JSON payload
    JSON_PAYLOAD=$(printf '{
        "reference_number": "%s",
        "title": "%s",
        "description": "%s",
        "case_type": "%s",
        "client_name": "%s",
        "client_contact": %s,
        "opposing_party": "%s",
        "amount_in_dispute": %s
    }' "$reference_number" "$TITLE" "$DESCRIPTION" "$CASE_TYPE" "$CLIENT_NAME" "$CLIENT_CONTACT" "$OPPOSING_PARTY" "$AMOUNT_IN_DISPUTE")

    login

    print_header "Creating Case via API"
    curl -H "Authorization: Bearer $(cat auth_token.txt)" -X POST -H "Content-Type: application/json" -d "$JSON_PAYLOAD" "$API_URL/cases"
    echo ""
    print_success "Case creation request sent"
}

# Delete a case
delete_case() {
    if [ -z "$1" ]; then
        echo "Usage: $0 delete-case <case_id>"
        exit 1
    fi
    print_header "Deleting Case via API"
    login
    curl -H "Authorization: Bearer $(cat auth_token.txt)" -X DELETE "$API_URL/cases/$1"
    echo ""
    print_success "Case deletion request sent"
}

# Create a document
create_document() {
    METADATA="{}" # Default to empty JSON object

    # Parse named arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --case-id)
                CASE_ID="$2"
                shift 2
                ;;
            --document-type)
                DOCUMENT_TYPE="$2"
                shift 2
                ;;
            --title)
                TITLE="$2"
                shift 2
                ;;
            --content)
                CONTENT="$2"
                shift 2
                ;;
            --metadata)
                METADATA="$2"
                shift 2
                ;;
            *)
                echo "Unknown option: $1"
                show_usage
                exit 1
                ;;
        esac
    done

    # Validate required arguments
    if [ -z "$CASE_ID" ] || [ -z "$DOCUMENT_TYPE" ] || [ -z "$TITLE" ] || [ -z "$CONTENT" ]; then
        echo "Error: Missing required arguments for create-document."
        echo "Usage: $0 create-document --case-id <id> --document-type <type> --title <title> --content <content> [options]"
        exit 1
    fi

    # Construct JSON payload
    JSON_PAYLOAD=$(printf '{
        "case_id": "%s",
        "document_type": "%s",
        "title": "%s",
        "content": "%s",
        "metadata": %s
    }' "$CASE_ID" "$DOCUMENT_TYPE" "$TITLE" "$CONTENT" "$METADATA")

    print_header "Creating Document via API"
    login
    curl -H "Authorization: Bearer $(cat auth_token.txt)" -X POST -H "Content-Type: application/json" -d "$JSON_PAYLOAD" "$API_URL/documents"
    echo ""
    print_success "Document creation request sent"
}

# Delete a document
delete_document() {
    if [ -z "$1" ]; then
        echo "Usage: $0 delete-document <document_id>"
        exit 1
    fi
    print_header "Deleting Document via API"
    login
    curl -H "Authorization: Bearer $(cat auth_token.txt)" -X DELETE "$API_URL/documents/$1"
    echo ""
    print_success "Document deletion request sent"
}

# List cases
list_cases() {
    print_header "Listing Cases via API"
    STATUS_PARAM=""
    if [ -n "$1" ]; then
        if [[ "$1" == --status ]]; then
            STATUS_PARAM="?status=$2"
        else
            echo "Unknown option: $1"
            show_usage
            exit 1
        fi
    fi
    login
    curl -H "Authorization: Bearer $(cat auth_token.txt)" -s -X GET "$API_URL/cases$STATUS_PARAM" | jq .
    echo ""
    print_success "List cases request sent"
}

# List documents
list_documents() {
    print_header "Listing Documents via API"
    CASE_ID_PARAM=""
    if [ -n "$1" ]; then
        if [[ "$1" == --case-id ]]; then
            CASE_ID_PARAM="?case_id=$2"
        else
            echo "Unknown option: $1"
            show_usage
            exit 1
        fi
    fi
    login
    curl -H "Authorization: Bearer $(cat auth_token.txt)" -s -X GET "$API_URL/documents$CASE_ID_PARAM" | jq .
    echo ""
    print_success "List documents request sent"
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
    echo "  api                - Run test_api.py with correct env"
    echo "  ingest             - Run data ingestion pipeline"
    echo "  ingest-templates   - Run data ingestion pipeline for templates"
    echo "  ingest-rulings     - Run data ingestion pipeline for rulings"
    echo "  validate           - Validate ingestion results"
    echo "  search \"query\"     - Search documents using search_documents()"
    echo "  audit [options]    - Get audit records from orchestrator"
    echo "  create-case [options] - Create a new case via API"
    echo "  delete-case <id>   - Delete a case via API"
    echo "  create-document [options] - Create a new document for a case via API"
    echo "  delete-document <id> - Delete a document via API"
    echo "  list-cases [--status <status>] - List cases via API"
    echo "  list-documents [--case-id <id>] - List documents via API"
    echo "  logs               - Show service logs"
    echo "  help               - Show this help"
    echo ""
    echo "Examples:"
    echo "  $0 start"
    echo "  $0 search \"roszczenie o zapłatę\""
    echo "  $0 audit --limit 5"
    echo "  $0 audit --case-id case_123 --limit 10"
    echo "  $0 audit --thread-id thread_abc"
    echo "  $0 create-case --case-number \"2024/01\" --title \"Test Case\" --case-type \"litigation\" --client-name \"John Doe\" --client-contact '{\"email\": \"j.doe@example.com\"}'"
    echo "  $0 create-document --case-id <case_id> --title \"My Doc\" --document-type \"pozew\" --content \"This is the document content.\""
    echo "  $0 delete-case <case_id>"
    echo "  $0 list-cases"
    echo "  $0 list-cases --status active"
    echo "  $0 list-documents --case-id <case_id>"
}

# Main execution block
if [ -z "$1" ]; then
    show_usage
    exit 1
fi

case "${1:-help}" in
    "start")
        print_header "Starting Services"
        docker-compose -f docker-compose.prod.yml up -d
        print_success "Services started"
        ;;
    "start-dev")
        print_header "Starting Services"
        docker-compose -f docker-compose.yml up --build -d
        print_success "Services started"
        ;;
    "stop")
        print_header "Stopping Services"
        docker-compose -f docker-compose.prod.yml down
        print_success "Services stopped"
        ;;
    "stop-dev")
        print_header "Stopping Services"
        docker-compose down
        print_success "Services stopped"
        ;;
    "restart-dev")
        print_header "Restarting Services"
        docker-compose -f docker-compose.yml down
        docker-compose -f docker-compose.yml up --build
        print_success "Services restarted"
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
    "api")
        shift
        run_api "$@"
        ;;        
    "ingest")
        check_services
        run_ingestion
        ;;
    "ingest-templates")
        check_services
        run_ingestion_templates
        ;;
    "ingest-rulings")
        check_services
        run_ingestion_rulings
        ;;
    "validate")
        check_services
        validate_ingestion
        ;;
    "search")
        shift
        search_documents "$@"
        ;;
    "audit")
        shift
        get_audit_records "$@"
        ;;
    "create-case")
        shift
        create_case "$@"
        ;;
    "delete-case")
        shift
        delete_case "$@"
        ;;
    "create-document")
        shift
        create_document "$@"
        ;;
    "delete-document")
        shift
        delete_document "$@"
        ;;
    "list-cases")
        shift
        list_cases "$@"
        ;;
    "list-documents")
        shift
        list_documents "$@"
        ;;
    "logs")
        shift
        docker-compose logs -f "$@"
        ;;
    "help"|*)
        show_usage
        ;;
esac
