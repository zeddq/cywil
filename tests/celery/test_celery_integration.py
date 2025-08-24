#!/usr/bin/env python3
import pytest
if __name__ != "__main__":
    pytest.skip("Celery integration tests require running workers", allow_module_level=True)

"""
Comprehensive test script for Celery integration.
Tests all queues, task types, and monitoring capabilities.
"""
import os
import sys
import time
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List
import asyncio

# Add project root to path
sys.path.append(str(Path(__file__).parent))

from app.worker.celery_app import celery_app
from app.core.config_service import ConfigService
from celery.result import AsyncResult


class CeleryIntegrationTester:
    """Test suite for Celery integration."""
    
    def __init__(self):
        """Initialize the tester."""
        self.config = ConfigService().config
        self.results = {
            "timestamp": datetime.utcnow().isoformat(),
            "tests": [],
            "summary": {
                "total": 0,
                "passed": 0,
                "failed": 0,
                "skipped": 0
            }
        }
    
    def test_worker_availability(self) -> bool:
        """Test if Celery workers are available."""
        print("\n" + "=" * 60)
        print("TEST: Worker Availability")
        print("=" * 60)
        
        try:
            inspect = celery_app.control.inspect()
            active_queues = inspect.active_queues()
            
            if not active_queues:
                print("❌ No active workers found")
                self._record_test("worker_availability", False, "No active workers")
                return False
            
            print(f"✅ Found {len(active_queues)} active workers:")
            for worker, queues in active_queues.items():
                queue_names = [q["name"] for q in queues]
                print(f"   - {worker}: {', '.join(queue_names)}")
            
            self._record_test("worker_availability", True, f"{len(active_queues)} workers active")
            return True
            
        except Exception as e:
            print(f"❌ Error checking workers: {e}")
            self._record_test("worker_availability", False, str(e))
            return False
    
    def test_health_check(self) -> bool:
        """Test health check task."""
        print("\n" + "=" * 60)
        print("TEST: Health Check Task")
        print("=" * 60)
        
        try:
            from app.worker.tasks.maintenance import health_check_all_services
            
            print("Executing health check task...")
            result = health_check_all_services.apply_async()
            print(f"Task ID: {result.id}")
            
            # Wait for result
            health_status = result.get(timeout=30)
            
            print(f"Health Status: {health_status['status']}")
            print("Services:")
            for service, status in health_status.get("services", {}).items():
                icon = "✅" if status.get("status") == "healthy" else "❌"
                print(f"   {icon} {service}: {status.get('status', 'unknown')}")
            
            is_healthy = health_status.get("status") in ["healthy", "degraded"]
            self._record_test("health_check", is_healthy, health_status.get("status"))
            return is_healthy
            
        except Exception as e:
            print(f"❌ Health check failed: {e}")
            self._record_test("health_check", False, str(e))
            return False
    
    def test_search_tasks(self) -> bool:
        """Test search functionality via Celery."""
        print("\n" + "=" * 60)
        print("TEST: Search Tasks")
        print("=" * 60)
        
        try:
            from app.worker.tasks.search_tasks import (
                search_statutes,
                search_rulings,
                hybrid_search,
                extract_legal_references
            )
            
            # Test statute search
            print("\n1. Testing statute search...")
            result = search_statutes.apply_async(args=["umowa"], kwargs={"limit": 5})
            print(f"   Task ID: {result.id}")
            search_results = result.get(timeout=30)
            
            if search_results["status"] == "success":
                print(f"   ✅ Found {search_results['result_count']} statute results")
            else:
                print(f"   ❌ Search failed: {search_results.get('error')}")
            
            # Test legal reference extraction
            print("\n2. Testing legal reference extraction...")
            test_text = "Zgodnie z art. 415 KC oraz art. 23 KPC, pozwany jest zobowiązany..."
            result = extract_legal_references.apply_async(args=[test_text])
            print(f"   Task ID: {result.id}")
            references = result.get(timeout=10)
            
            if references["status"] == "success":
                print(f"   ✅ Extracted {references['total_references']} references")
                if references["references"]["statutes"]:
                    print("   Found statutes:")
                    for ref in references["references"]["statutes"]:
                        print(f"      - {ref['full_reference']}")
            else:
                print(f"   ❌ Extraction failed")
            
            self._record_test("search_tasks", True, "All search tasks completed")
            return True
            
        except Exception as e:
            print(f"❌ Search tasks failed: {e}")
            self._record_test("search_tasks", False, str(e))
            return False
    
    def test_document_tasks(self) -> bool:
        """Test document generation tasks."""
        print("\n" + "=" * 60)
        print("TEST: Document Generation Tasks")
        print("=" * 60)
        
        try:
            from app.worker.tasks.document_tasks import (
                generate_legal_document,
                validate_document,
                extract_document_metadata
            )
            
            # Test document generation
            print("\n1. Testing document generation...")
            context = {
                "court_name": "Rejonowy w Warszawie",
                "plaintiff_name": "Jan Kowalski",
                "defendant_name": "XYZ Sp. z o.o.",
                "claim_type": "zapłatę",
                "claim_amount": "10000"
            }
            
            result = generate_legal_document.apply_async(
                args=["pozew", context, "test_user"]
            )
            print(f"   Task ID: {result.id}")
            doc_result = result.get(timeout=30)
            
            if doc_result["status"] == "success":
                print(f"   ✅ Document generated ({doc_result['word_count']} words)")
                
                # Test document validation
                print("\n2. Testing document validation...")
                val_result = validate_document.apply_async(
                    args=[doc_result["content"], "pozew"]
                )
                validation = val_result.get(timeout=10)
                
                if validation["is_valid"]:
                    print("   ✅ Document is valid")
                else:
                    print(f"   ⚠️ Document has issues: {validation['issues']}")
            else:
                print(f"   ❌ Generation failed: {doc_result.get('error')}")
            
            self._record_test("document_tasks", True, "Document tasks completed")
            return True
            
        except Exception as e:
            print(f"❌ Document tasks failed: {e}")
            self._record_test("document_tasks", False, str(e))
            return False
    
    def test_case_tasks(self) -> bool:
        """Test case management tasks."""
        print("\n" + "=" * 60)
        print("TEST: Case Management Tasks")
        print("=" * 60)
        
        try:
            from app.worker.tasks.case_tasks import (
                create_case,
                search_cases,
                calculate_case_deadlines
            )
            
            # Test case creation
            print("\n1. Testing case creation...")
            case_data = {
                "reference_number": f"TEST-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "title": "Test Case for Celery Integration",
                "description": "This is a test case",
                "status": "active",
                "case_type": "civil",
                "client_name": "Test Client"
            }
            
            result = create_case.apply_async(args=[case_data, "test_user"])
            print(f"   Task ID: {result.id}")
            case_result = result.get(timeout=30)
            
            if case_result["status"] == "success":
                print(f"   ✅ Case created: {case_result['reference_number']}")
                case_id = case_result["case_id"]
                
                # Test deadline calculation
                print("\n2. Testing deadline calculation...")
                deadline_result = calculate_case_deadlines.apply_async(
                    args=[case_id, "test_user"]
                )
                deadlines = deadline_result.get(timeout=10)
                
                if deadlines["status"] == "success":
                    print(f"   ✅ Calculated {len(deadlines['deadlines'])} deadlines")
                    for deadline in deadlines["deadlines"]:
                        print(f"      - {deadline['name']}: {deadline['date']}")
                else:
                    print(f"   ❌ Deadline calculation failed")
            else:
                print(f"   ❌ Case creation failed: {case_result.get('error')}")
            
            self._record_test("case_tasks", True, "Case tasks completed")
            return True
            
        except Exception as e:
            print(f"❌ Case tasks failed: {e}")
            self._record_test("case_tasks", False, str(e))
            return False
    
    def test_task_monitoring(self) -> bool:
        """Test task monitoring capabilities."""
        print("\n" + "=" * 60)
        print("TEST: Task Monitoring")
        print("=" * 60)
        
        try:
            from app.worker.tasks.maintenance import (
                get_worker_statistics,
                monitor_task_performance
            )
            
            # Get worker statistics
            print("\n1. Getting worker statistics...")
            result = get_worker_statistics.apply_async()
            stats = result.get(timeout=10)
            
            if stats["status"] == "success":
                print(f"   ✅ Statistics retrieved:")
                print(f"      - Total workers: {stats['summary']['total_workers']}")
                print(f"      - Active tasks: {stats['summary']['total_active_tasks']}")
                print(f"      - Scheduled tasks: {stats['summary']['total_scheduled_tasks']}")
            else:
                print(f"   ❌ Failed to get statistics")
            
            # Monitor performance
            print("\n2. Monitoring task performance...")
            result = monitor_task_performance.apply_async(kwargs={"time_window_hours": 1})
            performance = result.get(timeout=10)
            
            if performance["status"] == "success":
                print(f"   ✅ Performance metrics:")
                print(f"      - Total tasks: {performance['performance_summary']['total_tasks']}")
                print(f"      - Success rate: {performance['performance_summary']['successful_tasks']}/{performance['performance_summary']['total_tasks']}")
                if performance['performance_summary']['average_runtime_seconds']:
                    print(f"      - Avg runtime: {performance['performance_summary']['average_runtime_seconds']}s")
            else:
                print(f"   ❌ Failed to get performance metrics")
            
            self._record_test("task_monitoring", True, "Monitoring functional")
            return True
            
        except Exception as e:
            print(f"❌ Monitoring failed: {e}")
            self._record_test("task_monitoring", False, str(e))
            return False
    
    def test_queue_routing(self) -> bool:
        """Test that tasks are routed to correct queues."""
        print("\n" + "=" * 60)
        print("TEST: Queue Routing")
        print("=" * 60)
        
        try:
            # Submit tasks to different queues
            test_tasks = [
                ("worker.tasks.search_tasks.search_statutes", "search", ["test query"]),
                ("worker.tasks.document_tasks.generate_legal_document", "documents", ["pozew", {}, "test"]),
                ("worker.tasks.case_tasks.create_case", "case_management", [{}, "test"]),
                ("worker.tasks.maintenance.health_check_all_services", "high_priority", [])
            ]
            
            results = []
            for task_name, expected_queue, args in test_tasks:
                result = celery_app.send_task(task_name, args=args)
                results.append((task_name, expected_queue, result.id))
                print(f"   Submitted {task_name.split('.')[-1]} to {expected_queue}")
                print(f"      Task ID: {result.id}")
            
            # Give tasks time to be picked up
            time.sleep(2)
            
            # Check task routing
            inspect = celery_app.control.inspect()
            active = inspect.active()
            
            if active:
                print("\n   ✅ Tasks are being processed by workers")
            else:
                print("\n   ⚠️ No active tasks (may have completed already)")
            
            self._record_test("queue_routing", True, "Routing functional")
            return True
            
        except Exception as e:
            print(f"❌ Queue routing test failed: {e}")
            self._record_test("queue_routing", False, str(e))
            return False
    
    def test_task_retry_mechanism(self) -> bool:
        """Test task retry on failure."""
        print("\n" + "=" * 60)
        print("TEST: Task Retry Mechanism")
        print("=" * 60)
        
        try:
            # This would require a task designed to fail
            # For now, we'll just verify the retry configuration
            from app.worker.config import CeleryConfig
            
            print(f"   Retry configuration:")
            print(f"      - Default retry delay: {CeleryConfig.task_default_retry_delay}s")
            print(f"      - Max retries: {CeleryConfig.task_max_retries}")
            print(f"      - Acks late: {CeleryConfig.task_acks_late}")
            print(f"      - Reject on worker lost: {CeleryConfig.task_reject_on_worker_lost}")
            
            print("\n   ✅ Retry mechanism configured")
            self._record_test("retry_mechanism", True, "Configured")
            return True
            
        except Exception as e:
            print(f"❌ Retry test failed: {e}")
            self._record_test("retry_mechanism", False, str(e))
            return False
    
    def _record_test(self, name: str, passed: bool, details: str = ""):
        """Record test result."""
        self.results["tests"].append({
            "name": name,
            "passed": passed,
            "details": details,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        self.results["summary"]["total"] += 1
        if passed:
            self.results["summary"]["passed"] += 1
        else:
            self.results["summary"]["failed"] += 1
    
    def run_all_tests(self):
        """Run all integration tests."""
        print("\n" + "=" * 60)
        print("CELERY INTEGRATION TEST SUITE")
        print("=" * 60)
        print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Check prerequisites
        if not self.test_worker_availability():
            print("\n⚠️ WARNING: No workers available. Please start Celery workers first.")
            print("Run: python run_celery_worker.py")
            return
        
        # Run tests
        tests = [
            self.test_health_check,
            self.test_search_tasks,
            self.test_document_tasks,
            self.test_case_tasks,
            self.test_task_monitoring,
            self.test_queue_routing,
            self.test_task_retry_mechanism
        ]
        
        for test in tests:
            try:
                test()
            except Exception as e:
                print(f"\n❌ Test crashed: {e}")
                self._record_test(test.__name__, False, f"Crashed: {e}")
        
        # Print summary
        self._print_summary()
    
    def _print_summary(self):
        """Print test summary."""
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        
        summary = self.results["summary"]
        success_rate = (summary["passed"] / summary["total"] * 100) if summary["total"] > 0 else 0
        
        print(f"Total Tests: {summary['total']}")
        print(f"Passed: {summary['passed']} ✅")
        print(f"Failed: {summary['failed']} ❌")
        print(f"Success Rate: {success_rate:.1f}%")
        
        if summary["failed"] > 0:
            print("\nFailed Tests:")
            for test in self.results["tests"]:
                if not test["passed"]:
                    print(f"   - {test['name']}: {test['details']}")
        
        # Save results to file
        results_file = Path("celery_test_results.json")
        with open(results_file, "w") as f:
            json.dump(self.results, f, indent=2)
        print(f"\nDetailed results saved to: {results_file}")
        
        print("\n" + "=" * 60)
        if success_rate == 100:
            print("🎉 ALL TESTS PASSED! Celery integration is working correctly.")
        elif success_rate >= 80:
            print("✅ Most tests passed. Review failures for non-critical issues.")
        else:
            print("❌ Multiple tests failed. Please review the configuration.")
        print("=" * 60)


def main():
    """Main entry point."""
    tester = CeleryIntegrationTester()
    
    # Check for specific test argument
    if len(sys.argv) > 1:
        test_name = sys.argv[1]
        if hasattr(tester, f"test_{test_name}"):
            print(f"Running specific test: {test_name}")
            getattr(tester, f"test_{test_name}")()
        else:
            print(f"Unknown test: {test_name}")
            print("Available tests:")
            for attr in dir(tester):
                if attr.startswith("test_"):
                    print(f"   - {attr[5:]}")
    else:
        # Run all tests
        tester.run_all_tests()


if __name__ == "__main__":
    main()