# Sub-Agent Task: Fix BatchProcessor Tests

**Model**: Claude 3.5 Sonnet (Sonnet 4)

**Priority**: High

**Context**: 
The AI Paralegal application at `/workspace` has failing BatchProcessor tests in `/workspace/tests/unit/test_performance_utils.py`.

**Failed Tests**:
- `test_batch_processing_by_size`
- `test_batch_processing_by_timeout`
- `test_batch_processor_error_handling`
- `test_batch_processor_stop`

**Error Pattern**:
```python
RuntimeError: BatchProcessor not started
```

**Root Cause Analysis**:
The tests are trying to use `await processor.add_item(i)` immediately after creating the processor, but the processor's `_running` flag is False because `start()` hasn't completed yet. The test creates a task with `asyncio.create_task(processor.start())` but doesn't wait for it to initialize.

**Code Location**: 
- Implementation: `/workspace/app/core/performance_utils.py` (BatchProcessor class, around line 187)
- Tests: `/workspace/tests/unit/test_performance_utils.py` (lines 247, 283, 316, 347)

**Required Fixes**:
1. Modify the BatchProcessor class to properly handle the startup sequence
2. Update the tests to ensure the processor is running before adding items
3. Consider adding an `await processor.wait_until_ready()` method or similar

**Test Command**:
```bash
cd /workspace && source .venv/bin/activate
python -m pytest tests/unit/test_performance_utils.py::TestBatchProcessor -v --no-cov
```

**Success Criteria**:
All 4 BatchProcessor tests should pass.

**Instructions**:
1. First read the BatchProcessor implementation in `/workspace/app/core/performance_utils.py`
2. Read the failing tests to understand what they expect
3. Implement the minimal fix needed - likely adding a way to wait for the processor to be ready
4. Run the tests to verify your fix works
5. Ensure no other tests are broken by your changes