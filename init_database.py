#!/usr/bin/env python3
"""
Database initialization script for AI Paralegal POC.
Creates all necessary tables if they don't exist.
"""

import sys
import os
import asyncio
from pathlib import Path

# Add the app directory to the Python path
sys.path.insert(0, str(Path(__file__).parent))

from sqlmodel import SQLModel
from app.core.database_manager import DatabaseManager
from app.core.config_service import ConfigService
from app.models import (
    Case, Document, Deadline, Note, FormTemplate, StatuteChunk,
    User, UserSession, ResponseHistory, SNRuling
)
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def create_tables():
    """Create all database tables."""
    try:
        # Initialize config service
        config_service = ConfigService()
        
        # Initialize database manager
        db_manager = DatabaseManager(config_service)
        await db_manager.initialize()
        
        logger.info("Creating database tables...")
        
        # Create all tables using SQLModel
        async with db_manager.async_engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        
        logger.info("✅ All database tables created successfully!")
        
        # List created tables
        async with db_manager.async_engine.connect() as conn:
            result = await conn.execute(
                """
                SELECT tablename FROM pg_tables 
                WHERE schemaname = 'public' 
                ORDER BY tablename;
                """
            )
            tables = result.fetchall()
            
            logger.info("\nCreated tables:")
            for table in tables:
                logger.info(f"  - {table[0]}")
        
        await db_manager.shutdown()
        
    except Exception as e:
        logger.error(f"❌ Error creating database tables: {e}")
        raise


async def check_existing_tables():
    """Check which tables already exist in the database."""
    try:
        config_service = ConfigService()
        db_manager = DatabaseManager(config_service)
        await db_manager.initialize()
        
        async with db_manager.async_engine.connect() as conn:
            result = await conn.execute(
                """
                SELECT tablename FROM pg_tables 
                WHERE schemaname = 'public' 
                ORDER BY tablename;
                """
            )
            tables = result.fetchall()
            
            if tables:
                logger.info("\nExisting tables in database:")
                for table in tables:
                    logger.info(f"  - {table[0]}")
            else:
                logger.info("\nNo tables found in database.")
        
        await db_manager.shutdown()
        return [table[0] for table in tables]
        
    except Exception as e:
        logger.error(f"Error checking existing tables: {e}")
        raise


async def main():
    """Main function to initialize database."""
    logger.info("AI Paralegal POC - Database Initialization")
    logger.info("=" * 50)
    
    # Check existing tables
    existing_tables = await check_existing_tables()
    
    if 'form_templates' in existing_tables and 'cases' in existing_tables:
        logger.info("\n✅ Required tables 'form_templates' and 'cases' already exist!")
        logger.info("Database is properly initialized.")
    else:
        logger.info("\n⚠️  Some required tables are missing. Creating tables...")
        await create_tables()
    
    logger.info("\n✅ Database initialization complete!")


if __name__ == "__main__":
    asyncio.run(main())