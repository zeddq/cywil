#!/bin/bash
# Docker setup script for Cursor background agents

echo "Setting up Docker in Cursor background agent environment..."

# Install Docker if not already installed
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    
    # Add user to docker group
    if [ -n "$USER" ]; then
        usermod -aG docker $USER || true
    fi
fi

# Create Docker directories
mkdir -p ~/.docker/data ~/.docker/exec ~/.docker/run

# Configure Docker daemon for rootless mode with VFS storage driver
cat > ~/.docker/daemon.json <<EOF
{
  "storage-driver": "vfs",
  "data-root": "$HOME/.docker/data",
  "exec-root": "$HOME/.docker/exec",
  "pidfile": "$HOME/.docker/docker.pid",
  "hosts": ["unix://$HOME/.docker/docker.sock"],
  "iptables": false,
  "ip-forward": false,
  "ip-masq": false,
  "bridge": "none",
  "userland-proxy": true,
  "userland-proxy-path": "/usr/libexec/docker-proxy"
}
EOF

# Try rootless mode first
if command -v dockerd-rootless.sh &> /dev/null; then
    echo "Starting Docker in rootless mode..."
    export DOCKER_HOST=unix://$HOME/.docker/docker.sock
    dockerd-rootless.sh --experimental &> ~/.docker/docker-rootless.log &
    DOCKER_PID=$!
    sleep 5
    
    if docker ps &> /dev/null; then
        echo "Docker started successfully in rootless mode!"
        echo "Docker PID: $DOCKER_PID"
        exit 0
    else
        echo "Rootless mode failed, trying regular dockerd..."
        kill $DOCKER_PID 2>/dev/null || true
    fi
fi

# Fallback to regular dockerd with custom paths
echo "Starting Docker daemon..."
dockerd \
    --data-root="$HOME/.docker/data" \
    --exec-root="$HOME/.docker/exec" \
    --pidfile="$HOME/.docker/docker.pid" \
    --host="unix://$HOME/.docker/docker.sock" \
    --iptables=false \
    --ip-forward=false \
    --ip-masq=false \
    --bridge=none \
    &> ~/.docker/docker.log &

DOCKER_PID=$!
echo "Docker PID: $DOCKER_PID"

# Wait for Docker to start
echo "Waiting for Docker to start..."
for i in {1..30}; do
    if docker ps &> /dev/null; then
        echo "Docker is running!"
        docker version
        break
    fi
    echo -n "."
    sleep 1
done

# Check if Docker started successfully
if ! docker ps &> /dev/null; then
    echo "Failed to start Docker. Check ~/.docker/docker.log for details"
    cat ~/.docker/docker.log
    exit 1
fi

echo "Docker setup complete!"
