# AI Paralegal Audit Logs and Conversation History

This document explains how to retrieve and analyze audit logs and conversation history from the AI Paralegal system.

## Overview

The AI Paralegal system stores conversation history in two ways:

1. **Database Storage**: AI interactions are saved as notes in the PostgreSQL database
2. **In-Memory Storage**: Recent conversation context is maintained in memory during active sessions

## Retrieving Audit Logs

### Using get_audit_logs.py

The `get_audit_logs.py` script provides comprehensive access to stored conversations:

```bash
# Make the script executable
chmod +x get_audit_logs.py

# Get all AI interactions
python get_audit_logs.py --all

# Get interactions for a specific case
python get_audit_logs.py --case-id "UUID-HERE"

# Get recent interactions (last 24 hours)
python get_audit_logs.py --recent 24

# Get summary statistics
python get_audit_logs.py --summary

# Get detailed output with full content
python get_audit_logs.py --all --verbose

# Output as JSON for further processing
python get_audit_logs.py --all --json > audit_logs.json

# Limit number of results
python get_audit_logs.py --all --limit 10
```

### Example Output

```
Found 15 total AI interactions (limit: 50)
================================================================================
Interaction ID: 123e4567-e89b-12d3-a456-426614174000
Date/Time: 2025-06-14T10:30:00
Case: TEST/2025/001 - Test Case - Invoice Payment
Thread ID: thread_abc123
----------------------------------------
USER QUERY:
Jakie są terminy na wniesienie apelacji?
----------------------------------------
AI RESPONSE:
Terminy na wniesienie apelacji określa Kodeks postępowania cywilnego (KPC)...
================================================================================
```

## Database Schema

AI interactions are stored in the `notes` table with the following structure:

```sql
-- Notes table (stores AI interactions)
CREATE TABLE notes (
    id UUID PRIMARY KEY,
    case_id UUID REFERENCES cases(id),
    note_type VARCHAR(50),  -- Set to 'ai_interaction' for AI logs
    subject VARCHAR(200),   -- Set to 'AI Assistant Context'
    content TEXT,          -- JSON containing conversation data
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

The JSON content includes:
```json
{
    "last_query": "User's question",
    "last_response": "AI's response",
    "thread_id": "OpenAI thread identifier",
    "timestamp": "2025-06-14T10:30:00Z"
}
```

## Direct Database Access

You can also query the database directly:

```bash
# Using Docker
docker-compose exec postgres psql -U paralegal -d paralegal

# SQL query to get recent AI interactions
SELECT 
    n.created_at,
    m.case_number,
    m.title as case_title,
    n.content::json->>'last_query' as user_query,
    n.content::json->>'last_response' as ai_response
FROM notes n
LEFT JOIN cases m ON n.case_id = m.id
WHERE n.note_type = 'ai_interaction'
ORDER BY n.created_at DESC
LIMIT 10;
```

## Testing Conversation Flow

To test and observe conversation flow:

```bash
# Run a demo conversation
python get_current_conversation.py --demo

# Use the test scripts
./run_tests.sh ask "First question"
./run_tests.sh ask "Follow-up question"

# Then retrieve the logs
python get_audit_logs.py --recent 1
```

## Monitoring and Analysis

### Real-time Monitoring

Monitor API logs in real-time:
```bash
# Watch API logs
./run_tests.sh logs api

# Or using Docker directly
docker-compose logs -f api
```

### Export for Analysis

Export conversation data for analysis:
```bash
# Export all interactions as JSON
python get_audit_logs.py --all --json > conversations.json

# Export specific case conversations
python get_audit_logs.py --case-id "UUID" --json > case_conversations.json

# Process with jq or other tools
python get_audit_logs.py --all --json | jq '.[] | {query: .last_query, response: .last_response}'
```

## Security Considerations

1. **Access Control**: Audit logs contain sensitive legal information. Ensure proper access controls.

2. **Data Retention**: Consider implementing data retention policies for compliance.

3. **Anonymization**: When sharing logs, consider anonymizing client information.

4. **Encryption**: Database should be encrypted at rest for sensitive legal data.

## Limitations

Current implementation limitations:

1. **Single Interaction Storage**: Only the last query/response pair is stored per case
2. **No Tool Call Details**: Tool calls and their results are not persisted
3. **Limited Metadata**: User identity, IP address, and session info not captured
4. **No Token Usage**: API token usage and costs not tracked

## Future Improvements

Recommended enhancements for production:

1. **Dedicated Audit Table**: Create a specialized table for conversation history
2. **Complete Thread Storage**: Store entire conversation threads, not just last interaction
3. **Tool Call Logging**: Persist tool calls and their results
4. **Compliance Features**: Add fields required for legal compliance (user ID, IP, session)
5. **Performance Metrics**: Track response times, token usage, and costs
6. **Search Capabilities**: Add full-text search across conversation history

## API Endpoints for Audit Logs

Currently, audit logs are accessed via database queries. For production, consider adding these API endpoints:

```
GET /api/audit-logs              # List all audit logs with pagination
GET /api/audit-logs/{id}         # Get specific audit log
GET /api/cases/{id}/conversations  # Get all conversations for a case
GET /api/threads/{id}/messages   # Get all messages in a thread
POST /api/audit-logs/search      # Search audit logs
```
