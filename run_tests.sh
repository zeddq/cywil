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
    
    docker-compose exec api python ingest/ingest_pipeline.py
    
    print_success "Ingestion completed"
}

# Validate ingestion
validate_ingestion() {
    print_header "Validating Ingestion"
    
    docker-compose exec api python ingest/ingest_pipeline.py --validate-only
    
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
    echo "  logs               - Show service logs"
    echo "  help               - Show this help"
    echo ""
    echo "Examples:"
    echo "  $0 start"
    echo "  $0 ask \"Jakie są terminy apelacji?\""
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
    "logs")
        docker-compose logs -f "${2:-api}"
        ;;
    "help"|*)
        show_usage
        ;;
esac