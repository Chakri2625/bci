import pytest
import asyncio
from core.managers.command_group_manager import command_group_manager
from core.managers.async_task_manager import async_task_manager

@pytest.fixture(autouse=True)
def setup_teardown():
    # Setup
    command_group_manager._groups.clear()
    async_task_manager.cleanup_completed()
    yield
    # Teardown
    command_group_manager._groups.clear()
    async_task_manager.cleanup_completed()

async def dummy_coro(delay=0.1, result="success", should_fail=False):
    await asyncio.sleep(delay)
    if should_fail:
        raise ValueError("Failed")
    return result

def test_create_group():
    group_id = command_group_manager.create_group()
    assert group_id is not None
    
    status = command_group_manager.get_group_status(group_id)
    assert status["total"] == 0
    assert status["is_finished"] is True

def test_add_and_wait_for_group():
    async def run():
        group_id = command_group_manager.create_group()
        
        task_ids = command_group_manager.add_tasks_to_group(
            group_id, 
            [dummy_coro(0.1, "res1"), dummy_coro(0.2, "res2")]
        )
        
        assert len(task_ids) == 2
        
        status = command_group_manager.get_group_status(group_id)
        assert status["total"] == 2
        assert status["completed"] == 0
        assert status["is_finished"] is False
        
        final_status = await command_group_manager.wait_for_group(group_id)
        
        assert final_status["total"] == 2
        assert final_status["completed"] == 2
        assert final_status["successful"] == 2
        assert final_status["failed"] == 0
        assert final_status["is_finished"] is True
        
        results = [r["result"] for r in final_status["results"]]
        assert "res1" in results
        assert "res2" in results
    asyncio.run(run())

def test_group_with_failures():
    async def run():
        group_id = command_group_manager.create_group()
        
        command_group_manager.add_tasks_to_group(
            group_id, 
            [dummy_coro(0.1, "res1"), dummy_coro(0.1, should_fail=True)]
        )
        
        final_status = await command_group_manager.wait_for_group(group_id)
        
        assert final_status["completed"] == 2
        assert final_status["successful"] == 1
        assert final_status["failed"] == 1
        assert final_status["is_finished"] is True
    asyncio.run(run())

def test_cancel_group():
    async def run():
        group_id = command_group_manager.create_group()
        
        command_group_manager.add_tasks_to_group(
            group_id, 
            [dummy_coro(2.0, "res1"), dummy_coro(2.0, "res2")]
        )
        
        # Cancel the group before it completes
        cancelled = command_group_manager.cancel_group(group_id)
        assert cancelled is True
        
        final_status = await command_group_manager.wait_for_group(group_id)
        
        # Tasks are cancelled
        assert final_status["completed"] == 2
        assert final_status["failed"] == 2 # cancelled counts as failed
        assert final_status["status"] == "COMPLETED" # Group is marked completed after cancel
    asyncio.run(run())
