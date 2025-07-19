# AI Paralegal Architecture Documentation

## System Overview

The AI Paralegal system is built with a modular, service-oriented architecture that separates concerns and enables scalability, maintainability, and reliability.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                        Client Layer                         │
├─────────────────┬─────────────────┬───────────────────────┤
│   Web Browser   │  Mobile App     │   API Clients         │
└─────────────────┴─────────────────┴───────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                      API Gateway                            │
│              (FastAPI + WebSocket + SSE)                    │
├─────────────────────────────────────────────────────────────┤
│  • Request Routing      • Authentication                   │
│  • Rate Limiting        • CORS Handling                    │
│  • Request Logging      • Response Caching                 │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                   Orchestration Layer                       │
├─────────────────┬─────────────────┬───────────────────────┤
│ ParalegalAgent  │ StreamingHandler │  ConversationManager │
│                 │                   │                       │
│ • Request       │ • Protocol       │ • State Management   │
│   Coordination  │   Handling       │ • History Tracking   │
│ • Tool Selection│ • Event Parsing  │ • Case Linking      │
└─────────────────┴─────────────────┴───────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    Tool Execution Layer                     │
├─────────────────────────────────────────────────────────────┤
│                      ToolExecutor                           │
│  • Circuit Breaker    • Retry Logic                        │
│  • Load Balancing     • Metrics Collection                 │
│  • Middleware Chain   • Error Recovery                     │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    Service Layer                            │
├──────────────┬──────────────┬──────────────┬──────────────┤
│StatuteSearch │DocumentGen   │CaseManagement│SupremeCourt  │
│              │              │              │              │
│• Vector      │• Template    │• CRUD Ops    │• Rulings     │
│  Search      │  Processing  │• Deadlines   │  Search      │
│• Hybrid      │• AI Enhancement│• Reminders │• Analysis    │
└──────────────┴──────────────┴──────────────┴──────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                 Infrastructure Layer                        │
├────────────────┬────────────────┬──────────────────────────┤
│ DatabaseManager│  LLMManager    │  Performance Utils       │
│                │                │                          │
│• Connection    │• OpenAI Client │• Caching                │
│  Pooling       │• Embedding     │• Batching               │
│• Transactions  │  Cache         │• Optimization           │
└────────────────┴────────────────┴──────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    Storage Layer                            │
├─────────────────┬─────────────────┬───────────────────────┤
│   PostgreSQL    │     Qdrant      │       Redis           │
│                 │                 │                       │
│• Cases          │• KC/KPC         │• Session State        │
│• History        │  Embeddings     │• Cache                │
│• Templates      │• SN Rulings     │• Pub/Sub              │
└─────────────────┴─────────────────┴───────────────────────┘
```

## Component Architecture

### 1. API Gateway Layer

**Technology**: FastAPI with async support

**Responsibilities**:
- HTTP request handling
- WebSocket connections
- Server-Sent Events streaming
- Request validation
- Response formatting
- CORS and security headers

**Key Components**:
- `app/main_refactored.py` - Main FastAPI application
- Pydantic models for request/response validation
- Middleware for logging and correlation IDs

### 2. Orchestration Layer

**ParalegalAgent** (`app/orchestrator_refactored.py`)
- Coordinates between components
- Manages conversation flow
- Handles tool selection and execution
- Error recovery and fallback logic

**StreamingHandler** (`app/core/streaming_handler.py`)
- Parses OpenAI streaming responses
- Supports custom processors
- Handles all event types
- Buffers and aggregates responses

**ConversationManager** (`app/core/conversation_manager.py`)
- Maintains conversation state
- Persists history to PostgreSQL
- Links conversations to cases
- Redis caching with fallback

### 3. Tool Execution Layer

**ToolExecutor** (`app/core/tool_executor.py`)

Circuit Breaker Pattern:
```
CLOSED → (failures > threshold) → OPEN
  ↑                                 ↓
  ← (success > threshold) ← HALF_OPEN
```

**Features**:
- Fault tolerance with circuit breakers
- Exponential backoff retry
- Concurrent execution control
- Metrics and monitoring
- Middleware pipeline

### 4. Service Layer

Each service follows the same pattern:

```python
class Service(ServiceInterface):
    async def initialize()
    async def health_check()
    async def shutdown()
    # Service-specific methods
```

**Services**:
1. **StatuteSearchService**: Legal statute retrieval
2. **DocumentGenerationService**: Document creation
3. **CaseManagementService**: Case and deadline tracking
4. **SupremeCourtService**: Supreme Court rulings

### 5. Infrastructure Layer

**DatabaseManager**:
- Async SQLAlchemy with connection pooling
- Unit of Work pattern for transactions
- Automatic session management

**LLMManager**:
- OpenAI client management
- Embedding generation with caching
- Model selection and fallback

**Performance Utils**:
- Async-safe caching
- Batch processing
- Query optimization
- Connection pool tuning

### 6. Storage Layer

**PostgreSQL**:
- Primary data storage
- ACID compliance
- Full-text search capabilities

**Qdrant**:
- Vector database for semantic search
- Stores embeddings for KC/KPC articles
- Supreme Court rulings vectors

**Redis**:
- Session state management
- Response caching
- Pub/Sub for real-time features

## Data Flow

### 1. Request Processing Flow

```
Client Request
    ↓
API Gateway (correlation ID assigned)
    ↓
Orchestrator (conversation context loaded)
    ↓
Tool Selection (based on intent)
    ↓
Tool Executor (circuit breaker check)
    ↓
Service Layer (business logic)
    ↓
Storage Layer (data retrieval/storage)
    ↓
Response Assembly
    ↓
Client Response
```

### 2. Streaming Response Flow

```
OpenAI Stream
    ↓
StreamingHandler (parse chunks)
    ↓
Event Processors (metrics, accumulation)
    ↓
Event Emission (SSE/WebSocket)
    ↓
Client Update
```

### 3. Tool Execution Flow

```
Tool Request
    ↓
Circuit Breaker Check
    ├─ OPEN → ServiceUnavailableError
    └─ CLOSED/HALF_OPEN ↓
        Middleware Pipeline
            ↓
        Tool Registry Lookup
            ↓
        Argument Validation
            ↓
        Service Execution
            ├─ Success → Update Metrics
            └─ Failure → Retry Logic
                ├─ Retry → Exponential Backoff
                └─ Exhausted → Error Response
```

## Design Patterns

### 1. Dependency Injection

```python
class Service:
    def __init__(self, db_manager: DatabaseManager):
        self._db_manager = db_manager
```

Benefits:
- Testability
- Loose coupling
- Configuration flexibility

### 2. Repository Pattern

```python
async def get_case(self, case_id: str) -> Case:
    async with self._db_manager.get_session() as session:
        return await session.get(Case, case_id)
```

Benefits:
- Data access abstraction
- Consistent interface
- Easy to mock for testing

### 3. Circuit Breaker Pattern

States: CLOSED → OPEN → HALF_OPEN → CLOSED

Benefits:
- Fault tolerance
- Fast failure
- Automatic recovery

### 4. Middleware Pattern

```python
async def middleware(next_handler, *args):
    # Pre-processing
    result = await next_handler(*args)
    # Post-processing
    return result
```

Benefits:
- Cross-cutting concerns
- Composable behavior
- Clean separation

### 5. Observer Pattern

Stream processors observe and react to events:

```python
class StreamProcessor(Protocol):
    def process_event(self, event: StreamEvent) -> Optional[StreamEvent]
```

## Scalability Considerations

### Horizontal Scaling

1. **Stateless Services**: All services are stateless
2. **External State**: Redis/PostgreSQL for shared state
3. **Load Balancing**: Can run multiple instances

### Vertical Scaling

1. **Connection Pooling**: Configurable pool sizes
2. **Batch Processing**: Reduces API calls
3. **Caching**: Multiple cache layers

### Performance Optimizations

1. **Database Indexes**: On frequently queried columns
2. **Embedding Cache**: LRU cache for vectors
3. **Query Result Cache**: TTL-based caching
4. **Concurrent Execution**: Async/await throughout

## Security Architecture

### Authentication & Authorization

1. **User Identification**: Header-based (X-User-ID)
2. **Future**: OAuth2/JWT implementation
3. **Admin Endpoints**: Token-based protection

### Data Protection

1. **Input Validation**: Pydantic models
2. **SQL Injection Prevention**: Parameterized queries
3. **XSS Prevention**: Output encoding
4. **CORS Configuration**: Restricted origins

### Audit & Compliance

1. **Correlation IDs**: Full request tracing
2. **Structured Logging**: JSON format
3. **Data Retention**: Configurable policies
4. **Error Sanitization**: No sensitive data in logs

## Monitoring & Observability

### Metrics Collection

1. **Tool Metrics**: Success/failure rates, latency
2. **Circuit Breaker States**: Open/closed/half-open
3. **Cache Hit Rates**: Performance monitoring
4. **Database Performance**: Query times, pool usage

### Logging Strategy

1. **Structured Logs**: JSON with correlation IDs
2. **Log Levels**: Configurable per service
3. **Performance Logs**: Execution times
4. **Error Context**: Full stack traces

### Health Checks

1. **Service Health**: Each service self-reports
2. **Dependency Health**: Database, Redis, Qdrant
3. **Aggregate Health**: Overall system status

## Deployment Architecture

### Container Architecture

```
┌─────────────────┐
│   Application   │
│   Container     │
├─────────────────┤
│ • FastAPI App   │
│ • All Services  │
│ • Python 3.11   │
└─────────────────┘
        │
        ├── PostgreSQL Container
        ├── Redis Container
        └── Qdrant Container
```

### Environment Configuration

1. **Development**: Local containers
2. **Staging**: Kubernetes cluster
3. **Production**: Auto-scaling groups

### CI/CD Pipeline

1. **Build**: Docker image creation
2. **Test**: Automated test suite
3. **Deploy**: Rolling updates
4. **Monitor**: Health check validation

## Future Architecture Considerations

### Microservices Migration

Current monolith can be split into:
1. Statute Service
2. Document Service
3. Case Service
4. Chat Service

### Event-Driven Architecture

1. Event Bus (Kafka/RabbitMQ)
2. Event Sourcing for audit trail
3. CQRS for read/write separation

### Multi-Tenant Support

1. Tenant isolation at database level
2. Per-tenant resource limits
3. Tenant-specific configurations

### AI Model Management

1. Model versioning
2. A/B testing framework
3. Model performance monitoring
4. Fallback strategies