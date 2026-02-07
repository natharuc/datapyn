# PyQt6 QThread Safety in Tests

## Problem
PyQt6 tests with QThread/Workers can crash in CI with:
```
Fatal Python error: Aborted
Thread 0x00007f9db5ffd6c0 (most recent call first):
  <no Python frame>
```

This happens when:
1. Workers/threads are not properly cleaned up
2. QApplication event loop conflicts with pytest
3. Threads remain running after test completion

## Solution
Use the `safe_qthread_cleanup` fixture in `conftest.py`:

```python
def test_worker_functionality(qtbot, safe_qthread_cleanup):
    """Test QThread worker with automatic cleanup"""
    # Create worker and thread
    worker, thread = safe_qthread_cleanup.create_worker(MyWorker, arg1, arg2)
    
    # Connect signals
    results = []
    worker.finished.connect(lambda r: results.append(r))
    
    # Start thread
    thread.started.connect(worker.run)
    thread.start()
    
    # Wait for completion
    qtbot.waitUntil(lambda: len(results) > 0, timeout=5000)
    
    # Verify results
    assert results[0] == expected_value
    
    # Cleanup is automatic via fixture!
```

## How It Works
1. `create_worker()` registers all threads/workers
2. Fixture's cleanup ensures:
   - `thread.quit()` called
   - Waits up to 5s for graceful shutdown
   - Falls back to `thread.terminate()` if needed
   - Clears all references

## Benefits
- No manual cleanup needed
- Prevents CI crashes
- Consistent across all tests
- Safe timeout handling
