#!/usr/bin/env python3
"""
Test script for Celery monitoring and worker signals.
"""
import time
import random
import asyncio
from typing import Dict, Any, List
from datetime import datetime

from app.worker.celery_app import celery_app
from app.worker.tasks.example import (
    add,
    unreliable_task,
    long_running_task,
    batch_processor
)
from app.worker.monitoring import monitor
from app.core.logger_manager import get_logger

logger = get_logger(__name__)


def test_basic_task():
    """Test basic task execution with monitoring."""
    print("\n=== Testing Basic Task Execution ===")
    
    # Submit task
    result = add.delay(5, 3)
    print(f"Submitted task: {result.id}")
    
    # Check status via monitor
    time.sleep(0.5)
    status = monitor.get_task_status(result.id)
    print(f"Task status from monitor: {status}")
    
    # Wait for result
    final_result = result.get(timeout=10)
    print(f"Final result: {final_result}")
    
    # Check performance stats
    perf_stats = monitor.get_performance_stats("example.add")
    print(f"Performance stats: {perf_stats}")


def test_retry_mechanism():
    """Test automatic retry with exponential backoff."""
    print("\n=== Testing Retry Mechanism ===")
    
    # Submit unreliable task that will likely fail and retry
    result = unreliable_task.delay(failure_rate=0.8)
    print(f"Submitted unreliable task: {result.id}")
    
    # Monitor retries
    for i in range(20):
        time.sleep(1)
        status = monitor.get_task_status(result.id)
        if status:
            print(f"Attempt {i+1}: Status = {status.get('status')}, Retries = {status.get('retry_count', 0)}")
            
            if status.get('status') in ['SUCCESS', 'FAILURE']:
                break
    
    try:
        final_result = result.get(timeout=30)
        print(f"Task succeeded after retries: {final_result}")
    except Exception as e:
        print(f"Task failed after max retries: {e}")


def test_time_limits():
    """Test task time limits and timeouts."""
    print("\n=== Testing Time Limits ===")
    
    # Test task that respects time limit
    result1 = long_running_task.delay(duration=5)
    print(f"Submitted task within limits: {result1.id}")
    
    try:
        final_result = result1.get(timeout=20)
        print(f"Task completed: {final_result}")
    except Exception as e:
        print(f"Task failed: {e}")
    
    # Test task that exceeds time limit
    result2 = long_running_task.delay(duration=20)  # Will exceed 15s hard limit
    print(f"Submitted task exceeding limits: {result2.id}")
    
    try:
        final_result = result2.get(timeout=20)
        print(f"Task completed: {final_result}")
    except Exception as e:
        print(f"Task terminated due to time limit: {e}")


def test_batch_processing():
    """Test batch processing with rate limiting."""
    print("\n=== Testing Batch Processing ===")
    
    # Submit multiple batch tasks
    items = list(range(100))
    batch_size = 20
    
    results = []
    for i in range(0, len(items), batch_size):
        batch = items[i:i+batch_size]
        result = batch_processor.delay(batch)
        results.append(result)
        print(f"Submitted batch {i//batch_size + 1}: {result.id}")
    
    # Wait for all batches
    for i, result in enumerate(results):
        try:
            batch_result = result.get(timeout=30)
            print(f"Batch {i+1} completed: {batch_result}")
        except Exception as e:
            print(f"Batch {i+1} failed: {e}")


def test_worker_health():
    """Test worker health monitoring."""
    print("\n=== Testing Worker Health ===")
    
    # Get worker status
    worker_status = monitor.get_worker_status()
    print(f"Active workers: {list(worker_status.keys())}")
    
    for hostname, metrics in worker_status.items():
        print(f"\nWorker: {hostname}")
        print(f"  - Started: {metrics.get('started_at')}")
        print(f"  - Tasks executed: {metrics.get('tasks_executed')}")
        print(f"  - Success rate: {metrics.get('tasks_success', 0) / max(metrics.get('tasks_executed', 1), 1) * 100:.1f}%")
        print(f"  - Current tasks: {len(metrics.get('current_tasks', {}))}")
    
    # Perform health check
    health = monitor.health_check()
    print(f"\nOverall health: {health.get('healthy')}")
    
    if health.get('errors'):
        print("Health issues:")
        for error in health['errors']:
            print(f"  - {error}")


def test_error_tracking():
    """Test error tracking and dead letter queue."""
    print("\n=== Testing Error Tracking ===")
    
    # Force some tasks to fail
    def failing_task():
        raise ValueError("Intentional failure for testing")
    
    # Register and execute failing task
    task = celery_app.task(name="test.failing_task")(failing_task)
    
    failed_results = []
    for i in range(3):
        result = task.delay()  # type: ignore[attr-defined]
        failed_results.append(result)
        print(f"Submitted failing task {i+1}: {result.id}")
    
    # Wait for failures
    time.sleep(5)
    
    # Check error summary
    errors = monitor.get_error_summary(limit=5)
    print(f"\nRecent errors: {len(errors)}")
    
    for error in errors:
        print(f"\nError in {error.get('task_name')}:")
        print(f"  - Exception: {error.get('exception')}")
        print(f"  - Timestamp: {error.get('timestamp')}")


def test_performance_monitoring():
    """Test performance monitoring across multiple tasks."""
    print("\n=== Testing Performance Monitoring ===")
    
    # Submit various tasks to generate performance data
    tasks_to_test = [
        ("add", lambda: add.delay(random.randint(1, 100), random.randint(1, 100))),
        ("long_running", lambda: long_running_task.delay(random.randint(1, 5))),
        ("batch", lambda: batch_processor.delay(list(range(random.randint(5, 20)))))
    ]
    
    print("Submitting tasks for performance testing...")
    
    for name, task_func in tasks_to_test:
        for i in range(5):
            try:
                result = task_func()
                print(f"  - {name} task {i+1}: {result.id}")
                result.get(timeout=10)
            except Exception as e:
                print(f"  - {name} task {i+1} failed: {e}")
    
    # Get performance statistics
    print("\nPerformance Statistics:")
    
    for task_name in ["example.add", "example.long_running_task", "example.batch_processor"]:
        stats = monitor.get_performance_stats(task_name)
        if stats.get('count'):
            print(f"\n{task_name}:")
            print(f"  - Executions: {stats.get('count')}")
            print(f"  - Avg duration: {stats.get('avg_duration', 0):.2f}s")
            print(f"  - Min duration: {stats.get('min_duration', 0):.2f}s")
            print(f"  - Max duration: {stats.get('max_duration', 0):.2f}s")


def test_queue_management():
    """Test queue management and routing."""
    print("\n=== Testing Queue Management ===")
    
    # Get queue lengths
    queue_lengths = monitor.get_queue_lengths()
    print(f"Current queue lengths: {queue_lengths}")
    
    # Submit tasks to different queues
    from app.worker.config import CeleryConfig
    
    # Submit to high priority queue
    high_priority_result = add.apply_async(
        args=[10, 20],
        queue="high_priority",
        priority=10
    )
    print(f"Submitted to high_priority queue: {high_priority_result.id}")
    
    # Submit to default queue
    default_result = add.apply_async(
        args=[5, 5],
        queue="default",
        priority=5
    )
    print(f"Submitted to default queue: {default_result.id}")
    
    # Wait for completion
    time.sleep(2)
    
    # Check queue lengths again
    new_queue_lengths = monitor.get_queue_lengths()
    print(f"Updated queue lengths: {new_queue_lengths}")


def run_all_tests():
    """Run all monitoring tests."""
    print("=" * 60)
    print("CELERY MONITORING TEST SUITE")
    print("=" * 60)
    
    tests = [
        ("Basic Task Execution", test_basic_task),
        ("Retry Mechanism", test_retry_mechanism),
        ("Time Limits", test_time_limits),
        ("Batch Processing", test_batch_processing),
        ("Worker Health", test_worker_health),
        ("Error Tracking", test_error_tracking),
        ("Performance Monitoring", test_performance_monitoring),
        ("Queue Management", test_queue_management)
    ]
    
    failed_tests = []
    
    for test_name, test_func in tests:
        try:
            print(f"\n{'=' * 60}")
            print(f"Running: {test_name}")
            print('=' * 60)
            test_func()
            print(f"✓ {test_name} passed")
        except Exception as e:
            print(f"✗ {test_name} failed: {e}")
            failed_tests.append((test_name, e))
            import traceback
            traceback.print_exc()
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Total tests: {len(tests)}")
    print(f"Passed: {len(tests) - len(failed_tests)}")
    print(f"Failed: {len(failed_tests)}")
    
    if failed_tests:
        print("\nFailed tests:")
        for test_name, error in failed_tests:
            print(f"  - {test_name}: {error}")
    
    # Final health check
    print("\n" + "=" * 60)
    print("FINAL SYSTEM HEALTH CHECK")
    print("=" * 60)
    
    health = monitor.health_check()
    print(f"System healthy: {health.get('healthy')}")
    
    if health.get('workers'):
        print(f"Active workers: {len(health['workers'])}")
    
    if health.get('errors'):
        print("Issues detected:")
        for error in health['errors']:
            print(f"  - {error}")
    
    return len(failed_tests) == 0


if __name__ == "__main__":
    # Make sure Celery workers are running before running tests
    print("Make sure Celery workers are running:")
    print("  celery -A app.worker.celery_app worker --loglevel=info")
    print("")
    
    input("Press Enter to start tests...")
    
    success = run_all_tests()
    
    if success:
        print("\n✓ All tests passed successfully!")
        exit(0)
    else:
        print("\n✗ Some tests failed. Check the output above.")
        exit(1)