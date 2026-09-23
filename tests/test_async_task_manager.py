import pytest
import asyncio
import time
from core.managers.async_task_manager import async_task_manager

@pytest.fixture(autouse=True)
def cleanup_tasks():
    # Setup
    async_task_manager._tasks.clear()
    yield
    # Teardown
    async_task_manager._tasks.clear()

def test_1_and_2_submission_and_unique_id():
    async def run():
        async def dummy_coro():
            return "done"
            
        task_id1 = async_task_manager.submit(dummy_coro())
        task_id2 = async_task_manager.submit(dummy_coro())
        
        assert task_id1 is not None
        assert task_id2 is not None
        assert task_id1 != task_id2
        assert type(task_id1) == str
    asyncio.run(run())

def test_3_initial_task_status():
    async def run():
        async def dummy_coro():
            await asyncio.sleep(0.1)
            return "done"
            
        task_id = async_task_manager.submit(dummy_coro())
        status_info = async_task_manager.get_status(task_id)
        
        assert status_info is not None
        assert status_info["status"] == "PENDING"
        assert status_info["result"] is None
    asyncio.run(run())

def test_4_and_9_lifecycle_and_result():
    async def run():
        async def dummy_coro():
            await asyncio.sleep(0.01)
            return "success_result"
            
        task_id = async_task_manager.submit(dummy_coro())
        
        # Await it directly to observe SUCCESS
        statuses = await async_task_manager.wait_for_tasks([task_id])
        assert len(statuses) == 1
        assert statuses[0]["status"] == "SUCCESS"
        assert statuses[0]["result"] == "success_result"
        assert statuses[0]["error"] is None
    asyncio.run(run())

def test_5_and_6_failed_task_and_exception():
    async def run():
        async def failing_coro():
            await asyncio.sleep(0.01)
            raise ValueError("Test error")
            
        task_id = async_task_manager.submit(failing_coro())
        
        statuses = await async_task_manager.wait_for_tasks([task_id])
        assert len(statuses) == 1
        assert statuses[0]["status"] == "FAILED"
        assert statuses[0]["result"] is None
        assert "Test error" in statuses[0]["error"]
    asyncio.run(run())

def test_7_cancellation():
    async def run():
        async def long_coro():
            await asyncio.sleep(1.0)
            return "done"
            
        task_id = async_task_manager.submit(long_coro())
        
        # Cancel it
        cancelled = async_task_manager.cancel(task_id)
        assert cancelled is True
        
        statuses = await async_task_manager.wait_for_tasks([task_id])
        assert statuses[0]["status"] == "CANCELLED"
        assert statuses[0]["error"] == "Task was cancelled"
    asyncio.run(run())

def test_8_get_status():
    # Tested inherently in initial_task_status, but explicitly checking missing task
    status = async_task_manager.get_status("invalid_id")
    assert status is None

def test_10_cleanup():
    async def run():
        async def dummy_coro():
            return "done"
            
        task_id = async_task_manager.submit(dummy_coro())
        await async_task_manager.wait_for_tasks([task_id])
        
        # Cleanup
        async_task_manager.cleanup_completed()
        assert async_task_manager.get_status(task_id) is None
    asyncio.run(run())

def test_11_and_12_multiple_tasks_and_concurrency():
    async def run():
        async def slow_coro(idx):
            await asyncio.sleep(0.1)
            return f"done_{idx}"
            
        start_time = time.time()
        
        task_ids = [async_task_manager.submit(slow_coro(i)) for i in range(3)]
        
        statuses = await async_task_manager.wait_for_tasks(task_ids)
        
        duration = time.time() - start_time
        
        assert len(statuses) == 3
        assert all(s["status"] == "SUCCESS" for s in statuses)
        assert statuses[0]["result"] == "done_0"
        
        # If running sequentially, it would take 0.3s.
        # If concurrent, it should take ~0.1s.
        assert duration < 0.2
    asyncio.run(run())
