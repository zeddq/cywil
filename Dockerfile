FROM python:3.11-slim

WORKDIR /app

# Install system dependencies and Poetry
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir "poetry>=1.8,<2.0"

# Configure Poetry to install into the system environment (no venv inside container)
ENV POETRY_VIRTUALENVS_CREATE=false
ENV POETRY_NO_INTERACTION=1
# Reduce installer concurrency to lower RAM usage during build
RUN poetry config installer.max-workers 2

# Copy dependency files first for better layer caching
COPY pyproject.toml poetry.lock ./

# Install only main (non-dev) dependencies, synced to lockfile
RUN poetry install --only main --no-ansi --no-root --sync

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p data/uploads data/embeddings data/chunks

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV ENVIRONMENT=production
ENV PYTHONPATH=/app

# Expose port
EXPOSE 8000

# Run the application
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
