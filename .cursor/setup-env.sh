#!/bin/bash
# Environment setup script for Cursor background agents

echo "Setting up Python virtual environment..."

# Create virtual environment if it doesn't exist
if [ ! -d "$HOME/.venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$HOME/.venv"
fi

# Activate virtual environment
source "$HOME/.venv/bin/activate"

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install requirements
if [ -f "requirements.txt" ]; then
    echo "Installing Python requirements..."
    pip install -r requirements.txt
else
    echo "No requirements.txt found, skipping Python package installation"
fi

# Set up environment variables
export DOCKER_HOST="unix://$HOME/.docker/docker.sock"
export PYTHONPATH="/app:$PYTHONPATH"
export PATH="$HOME/.venv/bin:$PATH"

# Create necessary directories
mkdir -p data/uploads data/embeddings data/chunks

echo "Python environment setup complete!"
echo "Virtual environment: $HOME/.venv"
echo "Python: $(which python)"
echo "Pip: $(which pip)"
