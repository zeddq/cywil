# MCP Configuration Integration Plan

## Overview
This document provides a detailed plan for integrating MCP server configurations from `/Users/cezary/.claude.json` into the global MCP configuration file while preserving existing settings, maintaining proper JSON structure, avoiding duplicates, and creating backups.

## Current State Analysis

### Source Configuration (`/Users/cezary/.claude.json`)
The source file contains the following MCP server configurations:

1. **sequential-thinking**
   - Command: `npx`
   - Args: `["-y", "@modelcontextprotocol/server-sequential-thinking"]`
   - Environment: None

2. **serena**
   - Command: `sh`
   - Args: `["-c", "exec $(which uvx || echo uvx) --from git+https://github.com/oraios/serena serena start-mcp-server --context agent"]`
   - Environment: None

3. **ai-paralegal**
   - Command: `sh`
   - Args: `["-c", "exec $(which uvx || echo uvx) --from git+https://github.com/BeehiveInnovations/zen-mcp-server.git zen-mcp-server"]`
   - Environment: 
     - `OPENAI_API_KEY: "${OPENAI_API_KEY}"`
     - `GOOGLE_API_KEY: "${GOOGLE_API_KEY}"`
     - `REDIS_URL: "${REDIS_URL}"`
     - `XAI_API_KEY: "${XAI_API_KEY}"`
     - `GOOGLE_ALLOWED_MODELS: "gemini-2.5-pro"`
     - `OPENAI_ALLOWED_MODELS: "gpt-5"`
     - `GROK_ALLOWED_MODELS: "grok-4"`

4. **web-rag**
   - Command: `sh`
   - Args: `["-c", "cd /Users/cezary/ragger && /Users/cezary/ragger/.venv/bin/python -m rag_mcp.server"]`
   - Environment:
     - `CHROMA_PERSIST_DIR: "/Users/cezary/ragger/data/chroma"`
     - `CHROMA_COLLECTION: "web_rag"`

### Target Global Configuration
- Path: `../../../../Users/cezary/Library/Application Support/Cursor/User/globalStorage/rooveterinaryinc.roo-cline/settings/mcp_settings.json`
- Current state: Empty `mcpServers` object
- Structure: Standard MCP configuration format

## Integration Strategy

### 1. Backup Creation
- Create backup file: `mcp_settings.json.backup`
- Preserve original configuration in case of rollback needed

### 2. Duplicate Detection Logic
- Compare server names (keys in `mcpServers` object)
- If duplicate found, keep existing configuration in target
- Log which servers were skipped due to duplicates

### 3. Configuration Merging Process
1. Read source configuration from `.claude.json`
2. Read target global configuration 
3. Extract `mcpServers` section from source
4. For each server in source:
   - Check if server name exists in target
   - If not exists, add to target
   - If exists, skip and log
5. Validate final JSON structure
6. Write merged configuration to target

### 4. Validation Requirements
- Ensure valid JSON syntax
- Verify required fields for each server:
  - `command` (required)
  - `args` (optional but recommended)
  - `env` (optional)
- Check that all server names are unique
- Validate environment variable references (${VAR_NAME} format)

## Implementation Steps

### Step 1: Create Backup
```bash
cp "mcp_settings.json" "mcp_settings.json.backup"
```

### Step 2: Extract Source Configurations
From `/Users/cezary/.claude.json`, extract the `mcpServers` section:
```json
{
  "sequential-thinking": { ... },
  "serena": { ... },
  "ai-paralegal": { ... },
  "web-rag": { ... }
}
```

### Step 3: Merge Configurations
Target structure after merge:
```json
{
  "mcpServers": {
    "sequential-thinking": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"]
    },
    "serena": {
      "command": "sh",
      "args": ["-c", "exec $(which uvx || echo uvx) --from git+https://github.com/oraios/serena serena start-mcp-server --context agent"]
    },
    "ai-paralegal": {
      "command": "sh",
      "args": ["-c", "exec $(which uvx || echo uvx) --from git+https://github.com/BeehiveInnovations/zen-mcp-server.git zen-mcp-server"],
      "env": {
        "OPENAI_API_KEY": "${OPENAI_API_KEY}",
        "GOOGLE_API_KEY": "${GOOGLE_API_KEY}",
        "REDIS_URL": "${REDIS_URL}",
        "XAI_API_KEY": "${XAI_API_KEY}",
        "GOOGLE_ALLOWED_MODELS": "gemini-2.5-pro",
        "OPENAI_ALLOWED_MODELS": "gpt-5",
        "GROK_ALLOWED_MODELS": "grok-4"
      }
    },
    "web-rag": {
      "command": "sh",
      "args": ["-c", "cd /Users/cezary/ragger && /Users/cezary/ragger/.venv/bin/python -m rag_mcp.server"],
      "env": {
        "CHROMA_PERSIST_DIR": "/Users/cezary/ragger/data/chroma",
        "CHROMA_COLLECTION": "web_rag"
      }
    }
  }
}
```

### Step 4: Validation Checklist
- [ ] Valid JSON syntax
- [ ] All server names are unique
- [ ] All servers have required `command` field
- [ ] Environment variables use proper `${VAR_NAME}` syntax
- [ ] File paths are absolute where needed
- [ ] No circular dependencies or references

### Step 5: Error Handling
- If backup creation fails: abort operation
- If source file is malformed: report specific error
- If merge creates invalid JSON: rollback from backup
- If target file cannot be written: preserve original

## Expected Outcome

After successful integration:
1. Global MCP configuration will contain all 4 server configurations
2. Original global configuration will be preserved as backup
3. No duplicate server entries will exist
4. All environment variables will be properly referenced
5. JSON structure will be valid and properly formatted

## Verification Steps

1. Verify backup file exists and contains original configuration
2. Parse merged configuration to ensure valid JSON
3. Check that all expected servers are present
4. Validate that no duplicates exist
5. Test that environment variable syntax is correct
6. Confirm file permissions are preserved

## Rollback Procedure

If issues occur:
1. Stop any running MCP servers
2. Restore original configuration: `cp mcp_settings.json.backup mcp_settings.json`
3. Verify restored configuration is valid
4. Restart MCP services if needed

## Security Considerations

- Environment variables contain sensitive API keys
- Ensure proper file permissions on configuration files
- Validate that all referenced paths and commands are safe
- Check that environment variable references don't expose secrets

---

This plan provides a comprehensive roadmap for safely integrating MCP server configurations while maintaining system stability and security.
