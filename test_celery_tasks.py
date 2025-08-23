#!/usr/bin/env python3
"""
Test script to verify Celery tasks are working correctly
"""
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent))

from app.worker.tasks.statute_tasks import get_statute_ingestion_status
from app.worker.tasks.ruling_tasks import get_ruling_processing_status
from app.worker.tasks.embedding_tasks import get_embedding_statistics


def test_tasks():
    """Test basic Celery task functionality"""
    print("Testing Celery tasks...")
    
    # Test statute status
    print("\n1. Testing statute ingestion status...")
    result = get_statute_ingestion_status.apply_async()
    print(f"Task ID: {result.id}")
    print(f"Result: {result.get(timeout=10)}")
    
    # Test ruling status
    print("\n2. Testing ruling processing status...")
    result = get_ruling_processing_status.apply_async()
    print(f"Task ID: {result.id}")
    print(f"Result: {result.get(timeout=10)}")
    
    # Test embedding statistics
    print("\n3. Testing embedding statistics...")
    result = get_embedding_statistics.apply_async()
    print(f"Task ID: {result.id}")
    print(f"Result: {result.get(timeout=10)}")
    
    print("\nAll tests completed!")


if __name__ == "__main__":
    test_tasks()