# AI Paralegal Audit Logs - Quick Start Guide

## How to Get Conversation History

The AI Paralegal system stores all conversations with the LLM in the database. Here's how to retrieve them:

### 1. Quick Commands

```bash
# Get summary of all interactions
docker-compose exec api python /app/get_audit_logs.py --summary

# View all interactions with full details
docker-compose exec api python /app/get_audit_logs.py --all --verbose

# Get interactions from last 24 hours
docker-compose exec api python /app/get_audit_logs.py --recent 24

# Export all interactions as JSON
docker-compose exec api python /app/get_audit_logs.py --all --json > conversations.json

# Get interactions for a specific case
docker-compose exec api python /app/get_audit_logs.py --case-id "UUID-HERE"
```

### 2. What's Stored

Each AI interaction stores:
- **User Query**: The question asked by the user
- **AI Response**: The full response from the LLM
- **Thread ID**: Conversation context identifier
- **Case ID**: Link to legal case (if applicable)
- **Timestamp**: When the interaction occurred

### 3. Example Output

```
================================================================================
Interaction ID: 15ec162c-6fb5-464f-9762-ad5ee0d263dd
Date/Time: 2025-06-14T01:36:45.909196
Case: TEST/2025/001 - Test Case - Invoice Payment
Thread ID: simple-chat
----------------------------------------
USER QUERY:
Jakie są następne kroki w tej sprawie?
----------------------------------------
AI RESPONSE:
[Full AI response with legal advice and citations]
================================================================================
```

### 4. Direct Database Access

For advanced queries, access the PostgreSQL database directly:

```bash
# Connect to database
docker-compose exec postgres psql -U paralegal -d paralegal

# View recent AI interactions
SELECT 
    created_at,
    content::json->>'last_query' as query,
    content::json->>'last_response' as response
FROM notes 
WHERE note_type = 'ai_interaction'
ORDER BY created_at DESC
LIMIT 10;
```

### 5. Current Limitations

- Only stores the last query/response per case
- Tool calls and intermediate steps not persisted
- No user identity or session tracking
- Token usage and costs not recorded

### 6. Files Created

- `/get_audit_logs.py` - Main script for retrieving audit logs
- `/docs/AUDIT_LOGS.md` - Detailed documentation
- `/get_current_conversation.py` - Demo script for conversation flow

Use these tools to monitor, audit, and analyze all AI paralegal interactions for compliance and quality assurance.
