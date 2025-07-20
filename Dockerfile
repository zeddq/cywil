FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip and install dependencies
COPY requirements-short.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements-short.txt

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
