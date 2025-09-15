# Sub-Agent Task: Fix EmbeddingBatcher Tests

**Model**: Claude 3.5 Sonnet (Sonnet 4)

**Priority**: High

**Context**:
The AI Paralegal application has failing EmbeddingBatcher tests in `/workspace/tests/unit/test_performance_utils.py`.

**Failed Tests**:
- `test_embedding_generation_single` 
- `test_embedding_caching`
- `test_embedding_batch_processing`

**Error Patterns**:
1. `assert <Future pending> == [0.1, 0.2, 0.3]` - Test is comparing a Future object to a list
2. `assert 0 == 1` - Mock embedder is never called
3. `TypeError: 'Mock' object is not iterable` - Mock setup issue

**Root Cause Analysis**:
The EmbeddingBatcher returns Futures that need to be awaited, but the tests are not properly awaiting them. Additionally, the mock setup for `aembed_documents` isn't working correctly with the async batch processing.

**Code Locations**:
- Implementation: `/workspace/app/core/performance_utils.py` (EmbeddingBatcher class, around line 371)
- Tests: `/workspace/tests/unit/test_performance_utils.py` (lines 456, 481, 516)

**Required Fixes**:
1. Fix the test to properly await the Future returned by `get_embedding()`
2. Fix the mock setup to work with async iteration
3. Ensure the batch processor inside EmbeddingBatcher starts correctly
4. Fix the `process_embeddings` function to handle the mock return value properly

**Environment Note**:
- Docker commands must be run with `sudo` (e.g., `sudo docker ps`, `sudo docker compose up`)
- The virtual environment is at `.venv` and should be activated before running tests

**Test Command**:
```bash
cd /workspace && source .venv/bin/activate
python -m pytest tests/unit/test_performance_utils.py::TestEmbeddingBatcher -v --no-cov
```

**Success Criteria**:
All 3 EmbeddingBatcher tests should pass.

**Instructions**:
1. Read the EmbeddingBatcher implementation in `/workspace/app/core/performance_utils.py`
2. Understand how it uses BatchProcessor internally
3. Fix the tests to properly await futures and set up mocks correctly
4. The issue might be that `get_embedding` returns a Future that needs to be awaited
5. Run the tests to verify your fixes work