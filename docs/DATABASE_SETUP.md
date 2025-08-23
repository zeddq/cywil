# Database Setup Guide for AI Paralegal POC

## Overview

This guide explains how to set up and initialize the PostgreSQL database for the AI Paralegal POC application.

## Problem

The application is failing with errors like:
- `relation "form_templates" does not exist`
- `relation "cases" does not exist`

This happens because the database tables haven't been created yet.

## Solution

### Prerequisites

1. PostgreSQL must be running (locally or via Docker)
2. Database connection configured in `.env` file
3. Python environment with all dependencies installed

### Option 1: Using the Database Initialization Script (Recommended)

Run the initialization script to create all necessary tables:

```bash
python init_database.py
```

This script will:
- Check for existing tables
- Create all required tables if they don't exist
- Show a list of all created tables

### Option 2: Using Alembic Migrations

For a more controlled approach using database migrations:

```bash
python run_migrations.py
```

This script will:
- Check current migration status
- Create initial tables if needed
- Generate new migrations for any model changes
- Apply all pending migrations

### Option 3: Manual Setup

If the scripts don't work, you can manually initialize the database:

1. **Start a Python shell in the project directory:**
   ```bash
   python
   ```

2. **Run the initialization code:**
   ```python
   import asyncio
   from sqlmodel import SQLModel
   from app.core.database_manager import DatabaseManager
   from app.core.config_service import ConfigService
   
   async def init():
       config = ConfigService()
       db = DatabaseManager(config)
       await db.startup()
       async with db.engine.begin() as conn:
           await conn.run_sync(SQLModel.metadata.create_all)
       await db.shutdown()
   
   asyncio.run(init())
   ```

### Option 4: Using Docker Compose

If using Docker Compose, the database should be initialized automatically when the app starts. However, if it fails:

1. **Ensure the database service is running:**
   ```bash
   docker-compose up -d postgres
   ```

2. **Restart the application:**
   ```bash
   docker-compose restart app
   ```

## Database Schema

The following tables will be created:

- `users` - User authentication and profiles
- `user_sessions` - Active user sessions
- `cases` - Legal cases
- `documents` - Case documents
- `deadlines` - Case deadlines
- `notes` - Case notes
- `form_templates` - Legal document templates
- `statute_chunks` - Statute text chunks for search
- `sn_rulings` - Supreme Court rulings
- `response_history` - Chat response history

## Troubleshooting

### Connection Issues

If you get connection errors, check:
1. PostgreSQL is running: `pg_isready -h localhost -p 5432`
2. Database exists: `psql -U paralegal -d paralegal -c '\l'`
3. `.env` file has correct `DATABASE_URL`

### Permission Issues

If you get permission errors:
1. Ensure the database user has CREATE TABLE permissions
2. Grant permissions if needed:
   ```sql
   GRANT ALL PRIVILEGES ON DATABASE paralegal TO paralegal;
   ```

### Alembic Issues

If Alembic migrations fail:
1. Check if `alembic_version` table exists
2. Reset Alembic if needed:
   ```bash
   alembic stamp head
   ```

## Verification

After setup, verify the tables exist:

```bash
psql -U paralegal -d paralegal -c '\dt'
```

You should see all the tables listed above.

## Next Steps

Once the database is initialized:
1. The application should start without errors
2. You can begin ingesting statutes and templates
3. The API endpoints will be functional

For production deployments, consider:
- Setting up proper database backups
- Configuring connection pooling
- Setting up monitoring and alerts