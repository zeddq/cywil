# Ingestion Service Implementation Notes

## Overview

This implementation integrates the existing ingestion code from the `ingest/` directory into Celery tasks for asynchronous processing. The service handles:

1. **Statute Ingestion**: Processing Polish civil law PDFs (KC/KPC)
2. **Supreme Court Rulings**: Processing SN rulings using OpenAI o3 model
3. **Embedding Generation**: Creating vector embeddings for semantic search

## Key Components

### Statute Tasks (`statute_tasks.py`)

- **`ingest_statute_pdf`**: Processes a single statute PDF using `pdf2chunks.py`
  - Extracts articles with hierarchical structure
  - Creates chunks suitable for embedding
  - Saves to JSON files in `data/chunks/`

- **`ingest_all_statutes`**: Processes both KC and KPC PDFs
  - Looks for PDFs in `data/pdfs/statutes/`
  - Calls `ingest_statute_pdf` for each statute

- **`get_statute_ingestion_status`**: Returns status of processed statutes

### Ruling Tasks (`ruling_tasks.py`)

- **`process_single_ruling`**: Processes one Supreme Court ruling PDF
  - Uses o3 model for intelligent parsing
  - Extracts metadata and entities
  - Outputs to JSONL format

- **`process_ruling_batch`**: Batch processes ruling PDFs
  - Handles multiple PDFs concurrently
  - Uses OpenAI batch API for efficiency

- **`get_ruling_processing_status`**: Returns processing statistics

### Embedding Tasks (`embedding_tasks.py`)

- **`generate_statute_embeddings`**: Creates embeddings for statute chunks
  - Uses multilingual SBERT model
  - Stores in Qdrant vector database
  - Creates indexes for hybrid search

- **`generate_ruling_embeddings`**: Processes ruling JSONL files
  - Stores in both PostgreSQL and Qdrant
  - Maintains relationships between rulings and paragraphs

- **`get_embedding_statistics`**: Returns Qdrant collection statistics

## Data Flow

1. **PDFs** → **Parsing** → **Chunks/JSONL** → **Embeddings** → **Vector DB**

2. **Statutes Flow**:
   ```
   kodeks_cywilny.pdf → PolishStatuteParser → KC_chunks.json → Embeddings → Qdrant
   ```

3. **Rulings Flow**:
   ```
   ruling.pdf → o3 Processing → ruling.jsonl → Embeddings → Qdrant + PostgreSQL
   ```

## Configuration

### Environment Variables
- `QDRANT_HOST`: Qdrant server host (default: "qdrant")
- `QDRANT_PORT`: Qdrant server port (default: 6333)
- `OPENAI_API_KEY`: Required for o3 model and embeddings
- `DATABASE_URL`: PostgreSQL connection string
- `REDIS_URL`: Redis connection for Celery

### File Paths
- Statute PDFs: `data/pdfs/statutes/`
- Ruling PDFs: `data/pdfs/sn-rulings/`
- Chunks output: `data/chunks/`
- JSONL output: `data/jsonl/`

## API Usage

### Trigger Full Pipeline
```bash
POST /pipeline/full
{
  "statute_force_update": false,
  "ruling_pdf_directory": "/app/data/pdfs/sn-rulings"
}
```

### Process Statutes Only
```bash
POST /ingest/statutes
{
  "force_update": false
}
```

### Generate Embeddings
```bash
POST /embeddings/generate/KC
{
  "force_regenerate": false
}
```

## Notes

- The implementation reuses existing ingestion logic from `ingest/` directory
- Celery tasks are synchronous wrappers around async ingestion code
- Database operations use the existing models and managers
- Error handling preserves original exceptions for debugging
- File paths are relative to the project root

## Future Improvements

1. Add progress tracking for long-running tasks
2. Implement chunked processing for very large PDFs
3. Add retry logic for failed OpenAI API calls
4. Support incremental updates instead of full reprocessing
5. Add validation for PDF content before processing