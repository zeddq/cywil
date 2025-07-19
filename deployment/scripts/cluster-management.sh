#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
NAMESPACE="ai-paralegal"
BACKUP_DIR="${BACKUP_DIR:-./backups}"

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

# Parse command line arguments
OPERATION=""
REMOTE_HOST=""

usage() {
    echo "Usage: $0 [OPTIONS] COMMAND"
    echo ""
    echo "Commands:"
    echo "  status          Show cluster and application status"
    echo "  logs            Show application logs"
    echo "  restart         Restart all services"
    echo "  backup          Backup databases and configurations"
    echo "  restore         Restore from backup"
    echo "  scale           Scale application replicas"
    echo "  debug           Enter debug shell in app container"
    echo "  health          Check health of all services"
    echo "  reset           Reset cluster (WARNING: deletes all data)"
    echo ""
    echo "Options:"
    echo "  -h, --host      SSH hostname for remote operations"
    echo "  -n, --namespace Kubernetes namespace (default: ai-paralegal)"
    echo ""
    exit 1
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--host)
            REMOTE_HOST="$2"
            shift 2
            ;;
        -n|--namespace)
            NAMESPACE="$2"
            shift 2
            ;;
        status|logs|restart|backup|restore|scale|debug|health|reset)
            OPERATION="$1"
            shift
            ;;
        *)
            print_error "Unknown option: $1"
            usage
            ;;
    esac
done

if [ -z "$OPERATION" ]; then
    print_error "No command specified"
    usage
fi

# Execute kubectl command (local or remote)
exec_kubectl() {
    if [ -n "$REMOTE_HOST" ]; then
        ssh "$REMOTE_HOST" kubectl "$@"
    else
        kubectl "$@"
    fi
}

# Show cluster status
show_status() {
    print_step "Cluster Status"
    
    print_status "Nodes:"
    exec_kubectl get nodes
    
    echo ""
    print_status "Deployments:"
    exec_kubectl get deployments -n "$NAMESPACE"
    
    echo ""
    print_status "Pods:"
    exec_kubectl get pods -n "$NAMESPACE" -o wide
    
    echo ""
    print_status "Services:"
    exec_kubectl get services -n "$NAMESPACE"
    
    echo ""
    print_status "Persistent Volumes:"
    exec_kubectl get pvc -n "$NAMESPACE"
}

# Show logs
show_logs() {
    print_step "Application Logs"
    
    # Get pod name
    POD=$(exec_kubectl get pods -n "$NAMESPACE" -l app=ai-paralegal -o jsonpath='{.items[0].metadata.name}')
    
    if [ -z "$POD" ]; then
        print_error "No application pod found"
        exit 1
    fi
    
    # Tail logs
    print_status "Tailing logs from pod: $POD"
    exec_kubectl logs -f "$POD" -n "$NAMESPACE"
}

# Restart all services
restart_services() {
    print_step "Restarting All Services"
    
    print_status "Restarting database services..."
    exec_kubectl rollout restart deployment/postgres -n "$NAMESPACE"
    exec_kubectl rollout restart deployment/redis -n "$NAMESPACE"
    exec_kubectl rollout restart deployment/qdrant -n "$NAMESPACE"
    
    print_status "Waiting for databases to be ready..."
    exec_kubectl rollout status deployment/postgres -n "$NAMESPACE"
    exec_kubectl rollout status deployment/redis -n "$NAMESPACE"
    exec_kubectl rollout status deployment/qdrant -n "$NAMESPACE"
    
    print_status "Restarting application..."
    exec_kubectl rollout restart deployment/ai-paralegal-app -n "$NAMESPACE"
    exec_kubectl rollout status deployment/ai-paralegal-app -n "$NAMESPACE"
    
    print_status "All services restarted successfully!"
}

# Backup databases
backup_databases() {
    print_step "Backing Up Databases"
    
    # Create backup directory
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_PATH="$BACKUP_DIR/backup_$TIMESTAMP"
    mkdir -p "$BACKUP_PATH"
    
    # Backup PostgreSQL
    print_status "Backing up PostgreSQL..."
    POSTGRES_POD=$(exec_kubectl get pods -n "$NAMESPACE" -l app=postgres -o jsonpath='{.items[0].metadata.name}')
    
    if [ -n "$POSTGRES_POD" ]; then
        if [ -n "$REMOTE_HOST" ]; then
            ssh "$REMOTE_HOST" "kubectl exec $POSTGRES_POD -n $NAMESPACE -- pg_dumpall -U \$POSTGRES_USER" > "$BACKUP_PATH/postgres_dump.sql"
        else
            kubectl exec "$POSTGRES_POD" -n "$NAMESPACE" -- pg_dumpall -U '$POSTGRES_USER' > "$BACKUP_PATH/postgres_dump.sql"
        fi
        print_status "PostgreSQL backed up to: $BACKUP_PATH/postgres_dump.sql"
    fi
    
    # Backup Qdrant
    print_status "Backing up Qdrant..."
    QDRANT_POD=$(exec_kubectl get pods -n "$NAMESPACE" -l app=qdrant -o jsonpath='{.items[0].metadata.name}')
    
    if [ -n "$QDRANT_POD" ]; then
        # Create snapshot via API
        exec_kubectl exec "$QDRANT_POD" -n "$NAMESPACE" -- curl -X POST "http://localhost:6333/snapshots"
        print_status "Qdrant snapshot created"
    fi
    
    # Backup configurations
    print_status "Backing up configurations..."
    exec_kubectl get configmap ai-paralegal-config -n "$NAMESPACE" -o yaml > "$BACKUP_PATH/configmap.yaml"
    exec_kubectl get ingress ai-paralegal-ingress -n "$NAMESPACE" -o yaml > "$BACKUP_PATH/ingress.yaml"
    
    print_status "Backup completed: $BACKUP_PATH"
}

# Restore from backup
restore_backup() {
    print_step "Restoring from Backup"
    
    # List available backups
    if [ ! -d "$BACKUP_DIR" ]; then
        print_error "No backup directory found"
        exit 1
    fi
    
    print_status "Available backups:"
    ls -la "$BACKUP_DIR"
    
    read -p "Enter backup directory name to restore: " BACKUP_NAME
    RESTORE_PATH="$BACKUP_DIR/$BACKUP_NAME"
    
    if [ ! -d "$RESTORE_PATH" ]; then
        print_error "Backup not found: $RESTORE_PATH"
        exit 1
    fi
    
    # Restore PostgreSQL
    if [ -f "$RESTORE_PATH/postgres_dump.sql" ]; then
        print_status "Restoring PostgreSQL..."
        POSTGRES_POD=$(exec_kubectl get pods -n "$NAMESPACE" -l app=postgres -o jsonpath='{.items[0].metadata.name}')
        
        if [ -n "$REMOTE_HOST" ]; then
            cat "$RESTORE_PATH/postgres_dump.sql" | ssh "$REMOTE_HOST" "kubectl exec -i $POSTGRES_POD -n $NAMESPACE -- psql -U \$POSTGRES_USER"
        else
            kubectl exec -i "$POSTGRES_POD" -n "$NAMESPACE" -- psql -U '$POSTGRES_USER' < "$RESTORE_PATH/postgres_dump.sql"
        fi
    fi
    
    print_status "Restore completed from: $RESTORE_PATH"
}

# Scale application
scale_app() {
    print_step "Scaling Application"
    
    read -p "Enter number of replicas: " REPLICAS
    
    if ! [[ "$REPLICAS" =~ ^[0-9]+$ ]]; then
        print_error "Invalid number of replicas"
        exit 1
    fi
    
    exec_kubectl scale deployment/ai-paralegal-app --replicas="$REPLICAS" -n "$NAMESPACE"
    exec_kubectl rollout status deployment/ai-paralegal-app -n "$NAMESPACE"
    
    print_status "Application scaled to $REPLICAS replicas"
}

# Enter debug shell
debug_shell() {
    print_step "Debug Shell"
    
    # Get pod name
    POD=$(exec_kubectl get pods -n "$NAMESPACE" -l app=ai-paralegal -o jsonpath='{.items[0].metadata.name}')
    
    if [ -z "$POD" ]; then
        print_error "No application pod found"
        exit 1
    fi
    
    print_status "Entering debug shell in pod: $POD"
    exec_kubectl exec -it "$POD" -n "$NAMESPACE" -- /bin/bash
}

# Health check
health_check() {
    print_step "Health Check"
    
    # Check PostgreSQL
    print_status "Checking PostgreSQL..."
    POSTGRES_POD=$(exec_kubectl get pods -n "$NAMESPACE" -l app=postgres -o jsonpath='{.items[0].metadata.name}')
    if [ -n "$POSTGRES_POD" ]; then
        if exec_kubectl exec "$POSTGRES_POD" -n "$NAMESPACE" -- pg_isready -U postgres; then
            echo "✓ PostgreSQL is healthy"
        else
            echo "✗ PostgreSQL is not healthy"
        fi
    fi
    
    # Check Redis
    print_status "Checking Redis..."
    REDIS_POD=$(exec_kubectl get pods -n "$NAMESPACE" -l app=redis -o jsonpath='{.items[0].metadata.name}')
    if [ -n "$REDIS_POD" ]; then
        if exec_kubectl exec "$REDIS_POD" -n "$NAMESPACE" -- redis-cli ping | grep -q PONG; then
            echo "✓ Redis is healthy"
        else
            echo "✗ Redis is not healthy"
        fi
    fi
    
    # Check Qdrant
    print_status "Checking Qdrant..."
    QDRANT_POD=$(exec_kubectl get pods -n "$NAMESPACE" -l app=qdrant -o jsonpath='{.items[0].metadata.name}')
    if [ -n "$QDRANT_POD" ]; then
        if exec_kubectl exec "$QDRANT_POD" -n "$NAMESPACE" -- curl -s http://localhost:6333/health | grep -q true; then
            echo "✓ Qdrant is healthy"
        else
            echo "✗ Qdrant is not healthy"
        fi
    fi
    
    # Check Application
    print_status "Checking Application..."
    APP_POD=$(exec_kubectl get pods -n "$NAMESPACE" -l app=ai-paralegal -o jsonpath='{.items[0].metadata.name}')
    if [ -n "$APP_POD" ]; then
        if exec_kubectl exec "$APP_POD" -n "$NAMESPACE" -- curl -s http://localhost:8000/health | grep -q ok; then
            echo "✓ Application is healthy"
        else
            echo "✗ Application is not healthy"
        fi
    fi
}

# Reset cluster
reset_cluster() {
    print_step "Reset Cluster"
    
    print_warning "This will delete all data and reset the cluster!"
    read -p "Are you sure? Type 'yes' to continue: " CONFIRM
    
    if [ "$CONFIRM" != "yes" ]; then
        print_status "Reset cancelled"
        exit 0
    fi
    
    print_status "Deleting namespace..."
    exec_kubectl delete namespace "$NAMESPACE" --wait=true
    
    print_status "Cluster reset completed"
}

# Main execution
case "$OPERATION" in
    status)
        show_status
        ;;
    logs)
        show_logs
        ;;
    restart)
        restart_services
        ;;
    backup)
        backup_databases
        ;;
    restore)
        restore_backup
        ;;
    scale)
        scale_app
        ;;
    debug)
        debug_shell
        ;;
    health)
        health_check
        ;;
    reset)
        reset_cluster
        ;;
    *)
        print_error "Unknown operation: $OPERATION"
        usage
        ;;
esac