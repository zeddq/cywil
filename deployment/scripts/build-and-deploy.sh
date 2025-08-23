#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DOCKER_REGISTRY="${DOCKER_REGISTRY:-localhost:5000}"
IMAGE_NAME="${IMAGE_NAME:-ai-paralegal}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
NAMESPACE="ai-paralegal"

# Component selection
COMPONENT="${COMPONENT:-all}"  # all, backend, ui

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
FORCE_BUILD=false
SKIP_TESTS=false

usage() {
    echo "Usage: $0 [OPTIONS] COMMAND"
    echo ""
    echo "Commands:"
    echo "  build           Build Docker image locally"
    echo "  deploy          Deploy to Kubernetes cluster"
    echo "  full            Build and deploy"
    echo "  redeploy        Redeploy existing image"
    echo "  update-image    Update pod images from working copy"
    echo ""
    echo "Options:"
    echo "  -h, --host      SSH hostname for remote operations"
    echo "  -f, --force     Force rebuild even if no changes"
    echo "  -s, --skip-tests Skip running tests before build"
    echo "  -t, --tag       Docker image tag (default: latest)"
    echo "  -r, --registry  Docker registry (default: localhost:5000)"
    echo "  -c, --component Component to build/deploy (all, backend, ui) (default: all)"
    echo ""
    exit 1
}

ssh_prefix="eval"
run_remote_command() {
    $ssh_prefix "$@"
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--host)
            REMOTE_HOST="$2"
            ssh_prefix="ssh -t $REMOTE_HOST"
            shift 2
            ;;
        -f|--force)
            FORCE_BUILD=true
            shift
            ;;
        -s|--skip-tests)
            SKIP_TESTS=true
            shift
            ;;
        -t|--tag)
            IMAGE_TAG="$2"
            shift 2
            ;;
        -r|--registry)
            DOCKER_REGISTRY="$2"
            shift 2
            ;;
        -c|--component)
            COMPONENT="$2"
            shift 2
            ;;
        build|deploy|full|redeploy|update-image)
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

# Build backend Docker image
build_backend_image() {
    print_step "Building backend Docker image..."
    
    cd "$PROJECT_ROOT"
    
    # Run tests if not skipped
    if [ "$SKIP_TESTS" = false ]; then
        print_status "Running tests..."
        if command -v pytest &> /dev/null; then
            pytest tests/ -v --tb=short || {
                print_error "Tests failed!"
                exit 1
            }
        else
            print_warning "pytest not found, skipping tests"
        fi
    fi
    
    # Check if Dockerfile exists
    if [ ! -f "$PROJECT_ROOT/deployment/docker/Dockerfile" ]; then
        print_error "Dockerfile not found at deployment/docker/Dockerfile"
        exit 1
    fi
    
    # Build image
    print_status "Building image: $DOCKER_REGISTRY/$IMAGE_NAME:$IMAGE_TAG"
    docker build -f $PROJECT_ROOT/deployment/docker/Dockerfile -t "$DOCKER_REGISTRY/$IMAGE_NAME:$IMAGE_TAG" .
    
    # Tag as latest if not already
    if [ "$IMAGE_TAG" != "latest" ]; then
        docker tag "$DOCKER_REGISTRY/$IMAGE_NAME:$IMAGE_TAG" "$DOCKER_REGISTRY/$IMAGE_NAME:latest"
    fi
    
    print_status "Backend image built successfully"
}

# Build UI Docker image
build_ui_image() {
    print_step "Building UI Docker image..."
    
    cd "$PROJECT_ROOT/ui"
    
    # Check if Dockerfile exists
    if [ ! -f "Dockerfile" ]; then
        print_error "UI Dockerfile not found at ui/Dockerfile"
        exit 1
    fi
    
    # Build image
    print_status "Building image: $DOCKER_REGISTRY/ai-paralegal-ui:$IMAGE_TAG"
    docker build -t "$DOCKER_REGISTRY/ai-paralegal-ui:$IMAGE_TAG" .
    
    # Tag as latest if not already
    if [ "$IMAGE_TAG" != "latest" ]; then
        docker tag "$DOCKER_REGISTRY/ai-paralegal-ui:$IMAGE_TAG" "$DOCKER_REGISTRY/ai-paralegal-ui:latest"
    fi
    
    print_status "UI image built successfully"
}

# Build Docker images based on component selection
build_image() {
    case "$COMPONENT" in
        backend)
            build_backend_image
            ;;
        ui)
            build_ui_image
            ;;
        all)
            build_backend_image
            build_ui_image
            ;;
        *)
            print_error "Unknown component: $COMPONENT"
            exit 1
            ;;
    esac
}

# Push backend image to registry
push_backend_image() {
    print_step "Pushing backend image to registry..."
    
    # Check if registry is remote
    if [[ "$DOCKER_REGISTRY" != "localhost"* ]]; then
        print_status "Logging in to registry..."
        docker login "$DOCKER_REGISTRY"
    fi
    
    # Push image
    docker push "$DOCKER_REGISTRY/$IMAGE_NAME:$IMAGE_TAG"
    
    if [ "$IMAGE_TAG" != "latest" ]; then
        docker push "$DOCKER_REGISTRY/$IMAGE_NAME:latest"
    fi
    
    print_status "Backend image pushed successfully"
}

# Push UI image to registry
push_ui_image() {
    print_step "Pushing UI image to registry..."
    
    # Check if registry is remote
    if [[ "$DOCKER_REGISTRY" != "localhost"* ]]; then
        print_status "Logging in to registry..."
        docker login "$DOCKER_REGISTRY"
    fi
    
    # Push image
    docker push "$DOCKER_REGISTRY/ai-paralegal-ui:$IMAGE_TAG"
    
    if [ "$IMAGE_TAG" != "latest" ]; then
        docker push "$DOCKER_REGISTRY/ai-paralegal-ui:latest"
    fi
    
    print_status "UI image pushed successfully"
}

# Push images based on component selection
push_image() {
    case "$COMPONENT" in
        backend)
            push_backend_image
            ;;
        ui)
            push_ui_image
            ;;
        all)
            push_backend_image
            push_ui_image
            ;;
        *)
            print_error "Unknown component: $COMPONENT"
            exit 1
            ;;
    esac
}

# Deploy to Kubernetes
deploy_to_k8s() {
    print_step "Deploying to Kubernetes..."
    
    # Check if kubectl is available
    if ! command -v kubectl &> /dev/null; then
        print_error "kubectl not found. Please install kubectl first."
        exit 1
    fi
    
    # Create namespace if it doesn't exist
    kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
    
    # Apply configurations in order
    print_status "Applying Kubernetes manifests..."
    
    # Secrets (only if not exists)
    if ! kubectl get secret ai-paralegal-secrets -n "$NAMESPACE" &> /dev/null; then
        print_warning "Creating secrets template. Please update with actual values!"
        kubectl apply -f "$PROJECT_ROOT/deployment/k8s/secrets.yaml"
    fi
    
    # ConfigMap
    kubectl apply -f "$PROJECT_ROOT/deployment/k8s/configmap.yaml"
    
    # Database deployments (only for backend or all)
    if [ "$COMPONENT" = "backend" ] || [ "$COMPONENT" = "all" ]; then
        kubectl apply -f "$PROJECT_ROOT/deployment/k8s/postgres-deployment.yaml"
        kubectl apply -f "$PROJECT_ROOT/deployment/k8s/redis-deployment.yaml"
        kubectl apply -f "$PROJECT_ROOT/deployment/k8s/qdrant-deployment.yaml"
        
        # Wait for databases to be ready
        print_status "Waiting for databases to be ready..."
        kubectl wait --for=condition=available --timeout=300s deployment/postgres -n "$NAMESPACE"
        kubectl wait --for=condition=available --timeout=300s deployment/redis -n "$NAMESPACE"
        kubectl wait --for=condition=available --timeout=300s deployment/qdrant -n "$NAMESPACE"
    fi
    
    # Deploy backend
    if [ "$COMPONENT" = "backend" ] || [ "$COMPONENT" = "all" ]; then
        # Update app deployment with correct image
        sed "s|image: localhost:5000/ai-paralegal:latest|image: $DOCKER_REGISTRY/$IMAGE_NAME:$IMAGE_TAG|g" \
            "$PROJECT_ROOT/deployment/k8s/app-deployment.yaml" | kubectl apply -f -
    fi
    
    # Deploy UI
    if [ "$COMPONENT" = "ui" ] || [ "$COMPONENT" = "all" ]; then
        # Update UI deployment with correct image
        sed "s|image: localhost:5000/ai-paralegal-ui:latest|image: $DOCKER_REGISTRY/ai-paralegal-ui:$IMAGE_TAG|g" \
            "$PROJECT_ROOT/deployment/k8s/ui-deployment.yaml" | kubectl apply -f -
    fi
    
    # Apply ingress (always apply for proper routing)
    kubectl apply -f "$PROJECT_ROOT/deployment/k8s/ingress.yaml"
    
    # Wait for deployments to be ready
    if [ "$COMPONENT" = "backend" ] || [ "$COMPONENT" = "all" ]; then
        print_status "Waiting for backend application to be ready..."
        kubectl wait --for=condition=available --timeout=300s deployment/ai-paralegal-app -n "$NAMESPACE"
    fi
    
    if [ "$COMPONENT" = "ui" ] || [ "$COMPONENT" = "all" ]; then
        print_status "Waiting for UI application to be ready..."
        kubectl wait --for=condition=available --timeout=300s deployment/ai-paralegal-ui -n "$NAMESPACE"
    fi
    
    print_status "Deployment completed successfully!"
    kubectl get all -n "$NAMESPACE"
}

# Update image from working copy via SSH
update_from_working_copy() {
    print_step "Updating image from working copy..."
    
    if [ -z "$REMOTE_HOST" ]; then
        print_error "Remote host not specified. Use -h option."
        exit 1
    fi
    
    # Create temporary build context
    TEMP_DIR=$(mktemp -d)
    trap "rm -rf $TEMP_DIR" EXIT
    
    print_status "Creating build context..."
    cd "$PROJECT_ROOT"
    
    # Copy necessary files
    cp -r app "$TEMP_DIR/"
    cp requirements-short.txt "$TEMP_DIR/requirements.txt"
    cp deployment/docker/Dockerfile "$TEMP_DIR/"
    cp deployment/docker/.dockerignore "$TEMP_DIR/"
    
    # Create tarball
    print_status "Creating tarball..."
    tar -czf "$TEMP_DIR/build-context.tar.gz" -C "$TEMP_DIR" \
        app requirements.txt Dockerfile .dockerignore
    
    # Copy to remote host
    print_status "Copying to remote host..."
    scp "$TEMP_DIR/build-context.tar.gz" "$REMOTE_HOST:/tmp/"
    
    # Build on remote host
    print_status "Building image on remote host..."
    ssh "$REMOTE_HOST" << 'EOF'
        set -e
        cd /tmp
        mkdir -p ai-paralegal-build
        cd ai-paralegal-build
        tar -xzf ../build-context.tar.gz
        
        # Build image
        docker build -f Dockerfile -t ai-paralegal:latest .
        
        # Tag and push to local registry
        docker tag ai-paralegal:latest localhost:5000/ai-paralegal:latest
        docker push localhost:5000/ai-paralegal:latest
        
        # Clean up
        cd /
        rm -rf /tmp/ai-paralegal-build /tmp/build-context.tar.gz
EOF
    
    # Update deployment
    print_status "Updating Kubernetes deployment..."

    kubectl delete deployment/ai-paralegal-app -n "$NAMESPACE"
    kubectl apply -f "$PROJECT_ROOT/deployment/k8s/app-deployment.yaml"
    # kubectl rollout restart deployment/ai-paralegal-app -n "$NAMESPACE"
    # kubectl rollout status deployment/ai-paralegal-app -n "$NAMESPACE"
    
    print_status "Update completed successfully!"
}

# Redeploy pods
redeploy_pods() {
    print_step "Redeploying pods..."
    
    case "$COMPONENT" in
        backend)
            kubectl rollout restart deployment/ai-paralegal-app -n "$NAMESPACE"
            kubectl rollout status deployment/ai-paralegal-app -n "$NAMESPACE"
            ;;
        ui)
            kubectl rollout restart deployment/ai-paralegal-ui -n "$NAMESPACE"
            kubectl rollout status deployment/ai-paralegal-ui -n "$NAMESPACE"
            ;;
        all)
            kubectl rollout restart deployment/ai-paralegal-app -n "$NAMESPACE"
            kubectl rollout restart deployment/ai-paralegal-ui -n "$NAMESPACE"
            kubectl rollout status deployment/ai-paralegal-app -n "$NAMESPACE"
            kubectl rollout status deployment/ai-paralegal-ui -n "$NAMESPACE"
            ;;
        *)
            print_error "Unknown component: $COMPONENT"
            exit 1
            ;;
    esac
    
    print_status "Pods redeployed successfully!"
}

# Main execution
case "$OPERATION" in
    build)
        build_image
        ;;
    deploy)
        deploy_to_k8s
        ;;
    full)
        build_image
        push_image
        deploy_to_k8s
        ;;
    redeploy)
        redeploy_pods
        ;;
    update-image)
        update_from_working_copy
        ;;
    *)
        print_error "Unknown operation: $OPERATION"
        usage
        ;;
esac
