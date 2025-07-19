# AI Paralegal POC - Architecture Overview

## System Architecture

```
┌─────────────┐      user question / docs   ┌──────────────┐
│  Chat UI /  │  ─────────────────────────▶ │  Orchestrator│
│  API layer  │                            └────┬─────────┘
└─────────────┘                                 │(tool-calls)
                                                ▼
         ┌──────────────────────────────────────────────────────────┐
         │                   Specialist Agents                      │
         ├──────────┬──────────────┬──────────────┬────────────────┤
         │Retrieval │  Drafting    │ Validation   │  Scheduler     │
         │(RAG over │  (pleadings, │ (fact/law    │ (deadlines,    │
         │ KC & KPC)│ letters)     │ cross-check) │ reminders)     │
         └──────────┴──────────────┴──────────────┴────────────────┘
                                                │
                                                ▼
         ┌──────────────────────────────┐   ┌────────────┐
         │   Vector DB (Qdrant)         │   │  PostgreSQL│
         │   KC / KPC embeddings        │   │  Case data │
         └──────────────────────────────┘   └────────────┘
```

## Core Components

**Orchestrator**: Main agent that routes requests to specialist tools  
**Specialist Agents**: Domain-specific tools (retrieval, drafting, validation, scheduling)  
**Storage**: Qdrant for embeddings, PostgreSQL for structured data

## Key Services

1. **StatuteIngestionService**: Processes KC/KPC PDFs, chunks at article boundaries
2. **SupremeCourtIngestService**: Processes SN rulings with o3 model
3. **EmbeddingService**: Centralized embedding generation with multilingual model
4. **DatabaseManager**: Connection pooling and transaction management
5. **ConfigService**: Centralized configuration with environment validation

## Core Tools

- `search_statute(query, top_k)`: Hybrid search over KC/KPC chunks
- `draft_document(type, facts, goals)`: Generate legal documents
- `validate_against_statute(draft, citations[])`: Verify legal accuracy
- `compute_deadline(event_type, date)`: Calculate legal deadlines
- `schedule_reminder(case_id, date, note)`: Set up case reminders

## Control Flow

1. Intent detection → Q&A, drafting, deadline calculation
2. Dynamic tool chaining without user permission requests
3. Self-verification loop for all generated content
4. Source attribution for compliance

## Data Ingestion Pipeline

| Step | Tech | Notes |
|------|------|-------|
| Parse PDFs | pdfplumber | Preserve article numbers |
| Chunk | Custom splitter | Split at Art./§ boundaries |
| Embed | multilingual-mpnet-base-v2 | Polish-aware embeddings |
| Index | Qdrant (HNSW) | Cosine similarity |
| Lexical | PostgreSQL + pg_trgm | Keyword fallback |

## Security & Compliance

- In-country storage (Poland/EU) for GDPR compliance
- Role-based access with JWT propagation
- Audit logging of all tool calls and sources
- PII detection before responses

## Technical Stack

- **Backend**: FastAPI + Langchain + OpenAI SDK
- **Embeddings**: paraphrase-multilingual-mpnet-base-v2
- **Vector DB**: Qdrant with HNSW indexing
- **SQL**: PostgreSQL + asyncpg
- **Config**: Pydantic settings with validation
- **Services**: Async/await pattern with health checks

## UI Stack (Future)

- **Framework**: Next.js 14 + TypeScript
- **Styling**: Tailwind CSS + shadcn/ui
- **State**: Zustand
- **Streaming**: EventSource for real-time updates

## Example Flow

User: "Mam fakturę na 45 000 zł z 22 kwietnia, dłużnik nie płaci. Jakie mam terminy i jaki pozew mam złożyć?"

1. `compute_deadline('payment', '2025-04-22')` → 3-year limitation (art. 118 KC)
2. `draft_document('pozew_upominawczy', facts)` → Generate court filing
3. `validate_against_statute(draft)` → Verify citations
4. Return response with deadline, draft link, and reminder option