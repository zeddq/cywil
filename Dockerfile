FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-pol \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download spaCy Polish model
RUN python -m spacy download pl_core_news_sm

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p data/uploads data/embeddings data/chunks

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV ENVIRONMENT=production

# Expose port
EXPOSE 8000
# EXPOSE 5678

# RUN pip install debugpy

# Run the application
CMD ["uvicorn", "app.routes:app", "--host", "0.0.0.0", "--port", "8000"]
# CMD ["python", "-m", "debugpy", "--listen", "0.0.0.0:5678", "-m", "uvicorn", "app.routes:app", "--host", "0.0.0.0", "--port", "8000"]
