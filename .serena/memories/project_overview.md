# AI Paralegal POC - Project Overview

## Purpose
A proof of concept for an AI-powered paralegal assistant that helps with document analysis, legal research, and case management for Polish legal context.

## Tech Stack
- **Backend**: FastAPI + Langchain + OpenAI SDK
- **AI Models**: OpenAI models (sonnet, etc.) via Claude CLI
- **Embeddings**: sentence-transformers, multilingual-mpnet-base-v2
- **Vector DB**: Qdrant with HNSW indexing
- **SQL Database**: PostgreSQL + asyncpg
- **Task Queue**: Celery
- **Version Control**: Jujutsu (jj) + Git
- **Languages**: Python 3.11+
- **Dependency Management**: Poetry + pip
- **Containerization**: Docker + docker-compose

## Key Components
- **Orchestrator**: Main agent routing requests to specialist tools
- **Specialist Agents**: Domain-specific tools (retrieval, drafting, validation, scheduling)
- **Linter Orchestrator**: Pyright type checking fixes with AI agent integration
- **Embedding Service**: Centralized multilingual embedding generation
- **Database Services**: Connection pooling and transaction management

## Architecture
```
FastAPI + Agents SDK orchestrator
├─ app/ (main application)
├─ ingest/ (document processing)
├─ scripts/ (automation & linting)
├─ tools/ (AI agent tools)
└─ ui/ (frontend interface)
```