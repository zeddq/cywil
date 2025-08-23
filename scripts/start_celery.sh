#!/bin/bash

# Script to start Celery workers with proper configuration
# Usage: ./scripts/start_celery.sh [worker|beat|flower|all]

set -e

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Set default mode
MODE=${1:-worker}

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Starting Celery components...${NC}"

case $MODE in
    worker)
        echo -e "${YELLOW}Starting Celery worker...${NC}"
        celery -A app.worker.celery_app worker \
            --loglevel=info \
            --concurrency=4 \
            --queues=default,high_priority,ingestion,embeddings,case_management,documents,search \
            --hostname=worker@%h
        ;;
    
    beat)
        echo -e "${YELLOW}Starting Celery beat scheduler...${NC}"
        celery -A app.worker.celery_app beat \
            --loglevel=info
        ;;
    
    flower)
        echo -e "${YELLOW}Starting Flower monitoring...${NC}"
        celery -A app.worker.celery_app flower \
            --port=5555 \
            --broker_api=redis://localhost:6379/0
        ;;
    
    all)
        echo -e "${YELLOW}Starting all Celery components...${NC}"
        
        # Start worker in background
        celery -A app.worker.celery_app worker \
            --loglevel=info \
            --concurrency=4 \
            --queues=default,high_priority,ingestion,embeddings,case_management,documents,search \
            --hostname=worker@%h \
            --detach \
            --pidfile=/tmp/celery_worker.pid
        
        # Start beat in background
        celery -A app.worker.celery_app beat \
            --loglevel=info \
            --detach \
            --pidfile=/tmp/celery_beat.pid
        
        # Start flower in foreground
        celery -A app.worker.celery_app flower \
            --port=5555 \
            --broker_api=redis://localhost:6379/0
        ;;
    
    stop)
        echo -e "${YELLOW}Stopping Celery components...${NC}"
        
        # Stop worker
        if [ -f /tmp/celery_worker.pid ]; then
            kill $(cat /tmp/celery_worker.pid) 2>/dev/null || true
            rm -f /tmp/celery_worker.pid
            echo -e "${GREEN}Worker stopped${NC}"
        fi
        
        # Stop beat
        if [ -f /tmp/celery_beat.pid ]; then
            kill $(cat /tmp/celery_beat.pid) 2>/dev/null || true
            rm -f /tmp/celery_beat.pid
            echo -e "${GREEN}Beat stopped${NC}"
        fi
        ;;
    
    *)
        echo -e "${RED}Usage: $0 [worker|beat|flower|all|stop]${NC}"
        echo "  worker - Start Celery worker"
        echo "  beat   - Start Celery beat scheduler"
        echo "  flower - Start Flower monitoring UI"
        echo "  all    - Start all components"
        echo "  stop   - Stop all components"
        exit 1
        ;;
esac