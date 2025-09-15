# Development environment Dockerfile with all setup changes
FROM python:3.13-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc g++ libpq-dev git curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Install base system dependencies
RUN apt-get update && apt-get install -y \
    # Build tools
    build-essential \
    gcc \
    g++ \
    # PostgreSQL client libraries
    libpq-dev \
    postgresql-client \
    # Other utilities
    curl \
    wget \
    git \
    vim \
    sudo \
    # Docker dependencies
    apt-transport-https \
    ca-certificates \
    gnupg \
    lsb-release \
    && rm -rf /var/lib/apt/lists/*

# Install Docker
RUN curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null && \
    apt-get update && \
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin && \
    rm -rf /var/lib/apt/lists/*

# Configure Docker to not use iptables (to avoid network bridge issues)
RUN mkdir -p /etc/docker && \
    echo '{\n  "iptables": false,\n  "bridge": "none"\n}' > /etc/docker/daemon.json

RUN useradd -m -s /bin/bash developer && echo 'developer ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers
USER developer
WORKDIR /home/developer
ENV PATH="/home/developer/.local/bin:$PATH"

# Set environment variables for development
ENV DATABASE_URL="postgresql+asyncpg://paralegal:paralegal@localhost:5432/paralegal"
ENV REDIS_URL="redis://localhost:6379/0"
ENV QDRANT_HOST="localhost"
ENV QDRANT_PORT="6333"
ENV USE_CELERY="false"
ENV ENVIRONMENT="development"

# Expose ports
EXPOSE 8000

# Add a startup script
RUN echo '#!/bin/bash\n\
cd /workspace && \
pip install --upgrade pip && \
    pip install -r requirements.txt && \
    # Install additional dependencies that were added during testing
    pip install \
    email-validator \
    psycopg2-binary \
    python-json-logger \
    pdfplumber \
    pytest-httpx \
    httpx \
    qdrant-client\n\
echo "Starting AI Paralegal development environment..."\n\
echo ""\n\
echo "To start Docker services, run:"\n\
echo "  sudo docker compose -f docker-compose.dev.yml up -d"\n\
echo ""\n\
echo "To run tests:"\n\
echo "  source .venv/bin/activate"\n\
echo "  python -m pytest tests/unit/test_performance_utils.py -v --no-cov"\n\
echo ""\n\
echo "To start the API:"\n\
echo "  source .venv/bin/activate"\n\
echo "  python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"\n\
echo ""\n\
exec /bin/bash\n' > /home/developer/startup.sh && \
    chmod +x /home/developer/startup.sh
