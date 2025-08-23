#!/usr/bin/env python3
"""
Test script to verify the migration from Langchain to OpenAI SDK is complete.
This script tests that all core services can initialize without Langchain.
"""

import asyncio
import os
import sys
from pathlib import Path

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent))

# Set required environment variables for testing
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("QDRANT_HOST", "localhost")
os.environ.setdefault("QDRANT_PORT", "6333")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/db")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("QDRANT_API_KEY", "test-qdrant-key")

async def test_imports():
    """Test that all modules can be imported without Langchain."""
    print("Testing imports...")
    
    try:
        # Test core services
        from app.core.config_service import ConfigService
        from app.core.llm_manager import LLMManager
        from app.core.database_manager import DatabaseManager
        from app.core.conversation_manager import ConversationManager
        from app.core.tool_executor import ToolExecutor
        print("✓ Core services imported successfully")
        
        # Test domain services
        from app.services.statute_search_service import StatuteSearchService
        from app.services.supreme_court_service import SupremeCourtService
        from app.services.document_generation_service import DocumentGenerationService
        from app.services.case_management_service import CaseManagementService
        print("✓ Domain services imported successfully")
        
        # Test agent
        from app.paralegal_agents.refactored_agent_sdk import ParalegalAgentSDK
        print("✓ Agent imported successfully")
        
        # Test main app
        from app.main import app
        print("✓ Main app imported successfully")
        
        return True
        
    except ImportError as e:
        print(f"✗ Import error: {e}")
        if "langchain" in str(e).lower():
            print("  ERROR: Langchain dependency still present!")
        return False
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        return False

async def test_service_initialization():
    """Test that services can be initialized without Langchain."""
    print("\nTesting service initialization...")
    
    try:
        from app.core.config_service import ConfigService
        from app.core.llm_manager import LLMManager
        
        # Initialize config
        config_service = ConfigService()
        print("✓ ConfigService initialized")
        
        # Initialize LLM Manager (this previously used Langchain)
        llm_manager = LLMManager(config_service)
        print("✓ LLMManager initialized (no Langchain)")
        
        # Test that LLMManager can be initialized
        await llm_manager.initialize()
        print("✓ LLMManager initialize() called successfully")
        
        return True
        
    except Exception as e:
        print(f"✗ Service initialization error: {e}")
        if "langchain" in str(e).lower():
            print("  ERROR: Langchain dependency detected during initialization!")
        return False

def check_requirements():
    """Check that Langchain is commented out in requirements.txt."""
    print("\nChecking requirements.txt...")
    
    req_file = Path(__file__).parent / "requirements.txt"
    if not req_file.exists():
        print("✗ requirements.txt not found")
        return False
    
    with open(req_file) as f:
        lines = f.readlines()
    
    langchain_found = False
    for line in lines:
        if "langchain" in line.lower() and not line.strip().startswith("#"):
            print(f"✗ Uncommented Langchain dependency found: {line.strip()}")
            langchain_found = True
    
    if not langchain_found:
        print("✓ No active Langchain dependencies in requirements.txt")
        return True
    return False

def check_removed_files():
    """Check that deprecated orchestrator files have been removed."""
    print("\nChecking for removed files...")
    
    removed_files = [
        "app/orchestrator_refactored.py",
        "app/orchestrator_simple.py"
    ]
    
    all_removed = True
    for file_path in removed_files:
        full_path = Path(__file__).parent / file_path
        if full_path.exists():
            print(f"✗ File still exists: {file_path}")
            all_removed = False
        else:
            print(f"✓ File removed: {file_path}")
    
    return all_removed

async def main():
    """Run all migration tests."""
    print("=" * 60)
    print("AI Paralegal POC - Langchain to OpenAI SDK Migration Test")
    print("=" * 60)
    
    results = []
    
    # Run tests
    results.append(("Import Test", await test_imports()))
    results.append(("Service Initialization Test", await test_service_initialization()))
    results.append(("Requirements Check", check_requirements()))
    results.append(("File Removal Check", check_removed_files()))
    
    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    all_passed = True
    for test_name, passed in results:
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"{test_name}: {status}")
        if not passed:
            all_passed = False
    
    print("=" * 60)
    if all_passed:
        print("✓ All migration tests passed!")
        print("The system has been successfully migrated from Langchain to OpenAI SDK.")
    else:
        print("✗ Some tests failed. Please review the errors above.")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())