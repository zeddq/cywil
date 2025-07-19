#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
K3S_VERSION="${K3S_VERSION:-v1.28.5+k3s1}"
INSTALL_DIR="/usr/local/bin"
DATA_DIR="/var/lib/rancher/k3s"

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

ssh_prefix="eval"
ssh_suffix=""

# Check if VM hostname is provided
if [ -z "$1" ]; then
    print_status "Installing k3s locally..."
    INSTALL_MODE="local"
    # Check if running as root (required for Docker and k3s installation)
    if [[ $EUID -ne 0 ]]; then
        print_error "This script must be run as root (use sudo)"
        print_error "Usage: sudo $0 [hostname]"
        exit 1
    fi
else
    print_status "Installing k3s on remote host: $1"
    INSTALL_MODE="remote"
    REMOTE_HOST="$1"
    ssh_prefix="ssh -t $REMOTE_HOST"
fi

# Install k3s function
install_k3s() {
    print_status "Installing k3s version: $K3S_VERSION"
    
    if [ "$INSTALL_MODE" = "local" ]; then
        # Local installation
        curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="$K3S_VERSION" sh -s - \
            --write-kubeconfig-mode 644 \
            --disable traefik \
            --node-name ai-paralegal-node
        
        # Wait for k3s to be ready
        print_status "Waiting for k3s to be ready..."
        kubectl wait --for=condition=Ready node/ai-paralegal-node --timeout=300s
        
        # Copy kubeconfig for non-root access
        mkdir -p $HOME/.kube
        cp /etc/rancher/k3s/k3s.yaml $HOME/.kube/config
        chmod 600 $HOME/.kube/config
        
    else
        # Remote installation via SSH
        # ssh "$REMOTE_HOST" "curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION='$K3S_VERSION' sh -s - \
        #     --write-kubeconfig-mode 644 \
        #     --disable traefik \
        #     --node-name ai-paralegal-node"
        
        # Copy kubeconfig from remote
        # print_status "Copying kubeconfig from remote host..."
        # mkdir -p $HOME/.kube
        # scp "$REMOTE_HOST:/etc/rancher/k3s/k3s.yaml" $HOME/.kube/config
        
        # # Update server address in kubeconfig
        # REMOTE_IP=$(ssh "$REMOTE_HOST" "hostname -I | awk '{print \$1}'")
        # sed -i "s/127.0.0.1/$REMOTE_IP/g" $HOME/.kube/config
        chmod 600 $HOME/.kube/config
    fi
}

run_remote_command() {
    $ssh_prefix "$@"
}

# Install system dependencies
install_system_deps() {
    print_status "Installing system dependencies..."
    
    run_remote_command echo "Installing system dependencies..."
    # Update package list
    run_remote_command apt-get update
    
    # Install essential packages
    run_remote_command apt-get install -y \
        curl \
        wget \
        tar \
        gzip \
        ca-certificates \
        gnupg \
        lsb-release \
        apt-transport-https
    
    # Install Docker if not present
    if ! run_remote_command command -v docker &> /dev/null; then
        print_status "Installing Docker..."
        
        # Add Docker's official GPG key
        run_remote_command mkdir -p /etc/apt/keyrings
        run_remote_command "curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg"
        
        # Add Docker repository
        run_remote_command 'echo \
          "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
          $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null'
        
        # Update package list and install Docker
        run_remote_command apt-get update
        run_remote_command apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
        
        # Start and enable Docker service
        run_remote_command systemctl start docker
        run_remote_command systemctl enable docker
        
        # Add current user to docker group (if not root)
        if [ "$EUID" -ne 0 ]; then
            run_remote_command 'usermod -aG docker $USER'
            print_warning "User added to docker group. Please logout and login again for changes to take effect."
        fi
        
        print_status "Docker installed successfully"
    else
        print_status "Docker already installed"
    fi
    
    # Setup local Docker registry for k3s
    setup_local_registry
}

# Setup local Docker registry
setup_local_registry() {
    print_status "Setting up local Docker registry..."
    
    # Check if registry is already running
    if run_remote_command 'docker ps | grep -q "registry:2"'; then
        print_status "Local Docker registry already running"
        return
    fi
    
    # Create registry container
    run_remote_command "docker run -d \
        --name registry \
        --restart=always \
        -p 5000:5000 \
        -v /var/lib/registry:/var/lib/registry \
        registry:2"
    
    # Wait for registry to be ready
    sleep 5
    
    # Test registry
    if run_remote_command 'curl -s http://localhost:5000/v2/ | grep -q "{}"'; then
        print_status "Local Docker registry is running on port 5000"
    else
        print_warning "Local Docker registry may not be ready yet"
    fi
}

# Install required tools
install_tools() {
    print_status "Installing required tools..."
    
    # Check if kubectl is installed
    if ! run_remote_command command -v kubectl &> /dev/null; then
        print_status "Installing kubectl..."
        run_remote_command 'curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"'
        run_remote_command 'chmod +x kubectl'
        run_remote_command 'mv kubectl $INSTALL_DIR/'
    fi
    
    # Check if helm is installed
    if ! run_remote_command command -v helm &> /dev/null; then
        print_status "Installing helm..."
        run_remote_command 'curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash'
    fi
}

# Setup storage class
setup_storage() {
    print_status "Setting up local-path storage..."
    
    # Apply local-path-provisioner
    kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.24/deploy/local-path-storage.yaml
    
    # Wait for deployment
    kubectl wait --for=condition=available --timeout=300s deployment/local-path-provisioner -n local-path-storage
    
    # Set as default storage class
    kubectl patch storageclass local-path -p '{"metadata": {"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'
}

# Install ingress controller
install_ingress() {
    print_status "Installing Traefik ingress controller..."
    
    # Add Traefik helm repo
    helm repo add traefik https://helm.traefik.io/traefik
    helm repo update
    
    # Install Traefik
    helm upgrade --install traefik traefik/traefik \
        --namespace kube-system \
        --set ports.web.port=80 \
        --set ports.websecure.port=443 \
        --set service.type=LoadBalancer
}

# Setup monitoring (optional)
setup_monitoring() {
    print_status "Setting up basic monitoring..."
    
    # Install metrics-server
    kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
    
    # Patch metrics-server for self-signed certs
    kubectl patch deployment metrics-server -n kube-system --type='json' \
        -p='[{"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--kubelet-insecure-tls"}]'
}

# Main installation
main() {
    print_status "Starting k3s cluster setup..."
    
    # Install system dependencies first
    install_system_deps
    
    # Install tools
    install_tools
    
    # Install k3s
    install_k3s
    
    # Setup storage
    setup_storage
    
    # Install ingress
    install_ingress
    
    # Optional: Setup monitoring
    read -p "Do you want to install monitoring components? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        setup_monitoring
    fi
    
    print_status "k3s cluster setup completed!"
    print_status "Cluster info:"
    kubectl cluster-info
    kubectl get nodes
    
    print_status "Setup summary:"
    echo "✓ k3s cluster installed and running"
    echo "✓ Docker installed and configured"
    echo "✓ Local Docker registry running on port 5000"
    echo "✓ kubectl and helm installed"
    echo "✓ Local-path storage provisioner configured"
    echo "✓ Traefik ingress controller installed"
    
    if [ "$INSTALL_MODE" = "remote" ]; then
        print_warning "Remember to update your /etc/hosts file with:"
        echo "$REMOTE_IP paralegal.local grafana.paralegal.local prometheus.paralegal.local"
    else
        print_warning "Remember to update your /etc/hosts file with:"
        echo "127.0.0.1 paralegal.local grafana.paralegal.local prometheus.paralegal.local"
    fi
    
    print_status "Next steps:"
    echo "1. Deploy AI Paralegal: ./build-and-deploy.sh full"
    echo "2. Check status: ./cluster-management.sh status"
    echo "3. Access app: http://paralegal.local"
}

# Run main function
main
