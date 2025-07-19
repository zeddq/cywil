# AI Paralegal API Documentation

## Overview

The AI Paralegal API provides legal assistance capabilities for Polish civil law, including statute searches, document generation, case management, and Supreme Court rulings analysis.

**Base URL**: `http://localhost:8000`

## Authentication

Currently, the API uses header-based user identification:

```http
X-User-ID: user123
```

Future versions will implement OAuth2/JWT authentication.

## Endpoints

### Health Check

Check the health status of all services.

```http
GET /health
```

**Response**:
```json
{
  "status": "healthy",
  "services": [
    {
      "name": "DatabaseManager",
      "status": "healthy",
      "details": {...}
    }
  ],
  "tool_metrics": {
    "total_tools": 12,
    "open_circuits": 0,
    "aggregate_metrics": {...}
  },
  "version": "2.0.0"
}
```

### Chat

Process a chat message with AI assistance.

```http
POST /chat
Content-Type: application/json
X-User-ID: user123

{
  "message": "Jakie są terminy na apelację?",
  "thread_id": "conv-123",
  "case_id": "case-456"
}
```

**Request Body**:
- `message` (string, required): User's message
- `thread_id` (string, optional): Conversation thread ID for context
- `case_id` (string, optional): Associated case ID

**Response**:
```json
{
  "content": "Termin na wniesienie apelacji wynosi...",
  "thread_id": "conv-123",
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
  "tool_results": [
    {
      "name": "search_statute",
      "status": "completed",
      "call_id": "call-789"
    }
  ]
}
```

### Chat Stream (SSE)

Stream chat responses using Server-Sent Events.

```http
POST /chat/stream
Content-Type: application/json
X-User-ID: user123

{
  "message": "Napisz pozew o zapłatę",
  "thread_id": "conv-123"
}
```

**Response** (Server-Sent Events):
```
data: {"type": "correlation", "correlation_id": "550e8400-e29b-41d4-a716-446655440000"}

data: {"type": "text_delta", "content": "Zgodnie z "}

data: {"type": "text_delta", "content": "art. 415 KC..."}

data: {"type": "tool_calls", "tools": [{"name": "draft_document", "id": "call-123", "status": "completed"}]}

data: {"type": "message_complete", "content": "Przygotowałem projekt pozwu..."}

data: {"type": "stream_complete", "metrics": {"chunks_received": 45, "text_deltas": 20}}

data: [DONE]
```

### WebSocket Chat

Real-time bidirectional chat communication.

```
ws://localhost:8000/ws/chat?user_id=user123
```

**Send**:
```json
{
  "message": "Oblicz termin przedawnienia",
  "thread_id": "conv-123",
  "case_id": "case-456"
}
```

**Receive**:
```json
{
  "type": "text_delta",
  "content": "Termin przedawnienia...",
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Metrics

Get application and service metrics.

```http
GET /metrics
```

**Response**:
```json
{
  "tools": {
    "total_tools": 12,
    "circuit_states": {
      "closed": 10,
      "open": 1,
      "half_open": 1
    },
    "aggregate_metrics": {
      "total_calls": 1523,
      "successful_calls": 1456,
      "failed_calls": 67,
      "failure_rate": 0.044,
      "average_duration_ms": 245.3
    }
  },
  "services": {
    "healthy": true,
    "services": [...]
  },
  "application": {
    "version": "2.0.0",
    "uptime_seconds": 3600
  }
}
```

### Reset Circuit Breaker (Admin)

Manually reset a circuit breaker for a specific tool.

```http
POST /admin/reset-circuit/{tool_name}
X-Admin-Token: admin-secret
```

**Response**:
```json
{
  "status": "success",
  "tool": "search_statute"
}
```

## Tools Reference

### search_statute

Search Polish civil law statutes (KC/KPC).

**Parameters**:
- `query` (string): Search query
- `top_k` (integer): Number of results (default: 5)

**Example**:
```json
{
  "query": "art. 415 KC",
  "top_k": 3
}
```

### draft_document

Generate legal documents from templates.

**Parameters**:
- `doc_type` (string): Document type (e.g., "pozew_o_zaplate")
- `facts` (object): Case facts for the document
- `goals` (array): Legal goals to achieve

**Example**:
```json
{
  "doc_type": "pozew_o_zaplate",
  "facts": {
    "powod": "Jan Kowalski",
    "pozwany": "ABC Sp. z o.o.",
    "kwota": "10000 PLN"
  },
  "goals": ["Odzyskanie należności", "Odsetki ustawowe"]
}
```

### compute_deadline

Calculate legal deadlines.

**Parameters**:
- `event_type` (string): Type of deadline (e.g., "appeal", "payment")
- `date` (string): Starting date (ISO format)

**Example**:
```json
{
  "event_type": "appeal",
  "date": "2024-01-15"
}
```

### search_sn_rulings

Search Supreme Court rulings.

**Parameters**:
- `query` (string): Search query
- `top_k` (integer): Number of results
- `filters` (object): Optional filters

**Example**:
```json
{
  "query": "szkoda niemajątkowa",
  "top_k": 5,
  "filters": {
    "date_from": "2020-01-01",
    "section": "Cywilna"
  }
}
```

## Error Responses

### 400 Bad Request
```json
{
  "detail": "Invalid request parameters",
  "errors": [
    {
      "field": "message",
      "message": "Field is required"
    }
  ]
}
```

### 500 Internal Server Error
```json
{
  "detail": "Nie mogłem przetworzyć zapytania: Service unavailable",
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### 503 Service Unavailable
```json
{
  "detail": "Tool 'search_statute' is currently unavailable (circuit open)",
  "retry_after": 60
}
```

## Rate Limiting

Currently not implemented. Future versions will include:
- 100 requests per minute per user
- 1000 requests per hour per user
- WebSocket connections limited to 5 per user

## Correlation IDs

All requests are tracked with correlation IDs for distributed tracing:

1. Automatically generated if not provided
2. Returned in response headers: `X-Correlation-ID`
3. Included in all log entries
4. Used for debugging across services

## WebSocket Protocol

### Connection
```
ws://localhost:8000/ws/chat?user_id=USER_ID
```

### Message Format
```json
{
  "message": "string",
  "thread_id": "string (optional)",
  "case_id": "string (optional)"
}
```

### Event Types
- `stream_start`: Conversation started
- `text_delta`: Partial text response
- `message_complete`: Full message ready
- `tool_calls`: Tools being executed
- `stream_complete`: Processing finished
- `error`: Error occurred

## Examples

### Python Client
```python
import httpx
import json

async with httpx.AsyncClient() as client:
    response = await client.post(
        "http://localhost:8000/chat",
        json={
            "message": "Jak złożyć apelację?",
            "thread_id": "conv-123"
        },
        headers={"X-User-ID": "user123"}
    )
    result = response.json()
    print(result["content"])
```

### JavaScript/TypeScript Client
```typescript
const response = await fetch('http://localhost:8000/chat', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-User-ID': 'user123'
  },
  body: JSON.stringify({
    message: 'Jak złożyć apelację?',
    thread_id: 'conv-123'
  })
});

const result = await response.json();
console.log(result.content);
```

### Server-Sent Events Client
```javascript
const evtSource = new EventSource('/chat/stream', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-User-ID': 'user123'
  },
  body: JSON.stringify({
    message: 'Napisz pozew'
  })
});

evtSource.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'text_delta') {
    console.log(data.content);
  }
};
```

## Monitoring

### Health Checks
- `/health` - Overall system health
- `/metrics` - Detailed metrics

### Logging
All requests include correlation IDs in structured JSON logs:

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "level": "INFO",
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "user123",
  "message": "Chat request processed",
  "duration_ms": 245.3
}
```

## Deployment

See [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) for production deployment instructions.