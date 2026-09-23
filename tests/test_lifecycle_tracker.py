import pytest
import asyncio
from core.managers.lifecycle_tracker import lifecycle_tracker, LifecycleTracker
from core.managers.async_task_manager import async_task_manager
from core.orchestration.ecosystem_orchestrator import ecosystem_orchestrator
from core.state.state_manager import state_manager

@pytest.fixture
def clean_tracker():
    # Use a fresh instance for testing isolation
    return LifecycleTracker()

def test_execution_creation_and_pending_state(clean_tracker):
    eid = clean_tracker.start_execution("test_cmd", domain="test_domain", app="test_app")
    exec_info = clean_tracker.get_execution(eid)
    
    assert exec_info is not None
    assert exec_info["execution_id"] == eid
    assert exec_info["command"] == "test_cmd"
    assert exec_info["domain"] == "test_domain"
    assert exec_info["app"] == "test_app"
    assert exec_info["status"] == "PENDING"
    assert exec_info["start_time"] is not None
    assert exec_info["end_time"] is None

def test_pending_to_running(clean_tracker):
    eid = clean_tracker.start_execution("test_cmd")
    success = clean_tracker.update_status(eid, "RUNNING")
    
    assert success is True
    assert clean_tracker.get_execution(eid)["status"] == "RUNNING"

def test_running_to_success_with_result(clean_tracker):
    eid = clean_tracker.start_execution("test_cmd")
    clean_tracker.update_status(eid, "RUNNING")
    
    success = clean_tracker.update_status(eid, "SUCCESS", result={"data": "ok"})
    
    assert success is True
    exec_info = clean_tracker.get_execution(eid)
    assert exec_info["status"] == "SUCCESS"
    assert exec_info["result"] == {"data": "ok"}
    assert exec_info["end_time"] is not None

def test_running_to_failed_with_error(clean_tracker):
    eid = clean_tracker.start_execution("test_cmd")
    clean_tracker.update_status(eid, "RUNNING")
    
    success = clean_tracker.update_status(eid, "FAILED", error="Some error")
    
    assert success is True
    exec_info = clean_tracker.get_execution(eid)
    assert exec_info["status"] == "FAILED"
    assert exec_info["error"] == "Some error"
    assert exec_info["end_time"] is not None

def test_running_to_cancelled(clean_tracker):
    eid = clean_tracker.start_execution("test_cmd")
    clean_tracker.update_status(eid, "RUNNING")
    
    success = clean_tracker.update_status(eid, "CANCELLED")
    
    assert success is True
    exec_info = clean_tracker.get_execution(eid)
    assert exec_info["status"] == "CANCELLED"
    assert exec_info["end_time"] is not None

def test_invalid_state_transition(clean_tracker):
    eid = clean_tracker.start_execution("test_cmd")
    clean_tracker.update_status(eid, "SUCCESS")
    
    # Try transitioning out of terminal state
    success = clean_tracker.update_status(eid, "RUNNING")
    assert success is False
    assert clean_tracker.get_execution(eid)["status"] == "SUCCESS"
    
    # Try invalid state
    success = clean_tracker.update_status(eid, "INVALID_STATE")
    assert success is False

def test_status_lookup(clean_tracker):
    eid1 = clean_tracker.start_execution("cmd1")
    eid2 = clean_tracker.start_execution("cmd2")
    
    clean_tracker.update_status(eid1, "SUCCESS")
    clean_tracker.update_status(eid2, "FAILED")
    
    assert clean_tracker.get_execution(eid1)["status"] == "SUCCESS"
    assert clean_tracker.get_execution(eid2)["status"] == "FAILED"
    assert clean_tracker.get_execution("nonexistent") is None

def test_multiple_concurrent_executions(clean_tracker):
    async def _test():
        async def simulate_execution(i):
            eid = clean_tracker.start_execution(f"cmd_{i}")
            clean_tracker.update_status(eid, "RUNNING")
            await asyncio.sleep(0.01)
            clean_tracker.update_status(eid, "SUCCESS", result=i)
            return eid

        tasks = [simulate_execution(i) for i in range(10)]
        eids = await asyncio.gather(*tasks)
        
        all_execs = clean_tracker.get_all_executions()
        assert len(all_execs) == 10
        for eid in eids:
            assert all_execs[eid]["status"] == "SUCCESS"
    asyncio.run(_test())

def test_cleanup_removal(clean_tracker):
    for i in range(15):
        eid = clean_tracker.start_execution(f"cmd_{i}")
        clean_tracker.update_status(eid, "SUCCESS")
        
    assert len(clean_tracker.get_all_executions()) == 15
    clean_tracker.cleanup_completed(keep_latest=10)
    assert len(clean_tracker.get_all_executions()) == 10

def test_interaction_with_async_task_manager(clean_tracker):
    async def _test():
        # Lifecycle tracker observes, but does not execute.
        # AsyncTaskManager executes, but does not care about domain/app payload logic.
        eid = clean_tracker.start_execution("test_cmd")
        clean_tracker.update_status(eid, "RUNNING")
        
        async def my_task():
            return "done"
            
        # Submit to task manager
        task_id = async_task_manager.submit(my_task())
        statuses = await async_task_manager.wait_for_tasks([task_id])
        
        # Update lifecycle tracker based on task manager output
        if statuses[0]["status"] == "SUCCESS":
            clean_tracker.update_status(eid, "SUCCESS", result=statuses[0]["result"])
            
        exec_info = clean_tracker.get_execution(eid)
        assert exec_info["status"] == "SUCCESS"
        assert exec_info["result"] == "done"
    asyncio.run(_test())

def test_orchestration_architecture_integration():
    async def _test():
        # Test a complete execution path using the orchestrator
        session_id = "test_lifecycle_session"
        
        # Clear lifecycle tracker for isolation
        lifecycle_tracker._executions.clear()
        
        # 1. Invalid command
        res1 = await ecosystem_orchestrator.process_command("INVALID_NONSENSE_CMD", session=session_id)
        assert res1["status"] == "invalid"
        
        # Check that lifecycle tracker recorded it as FAILED
        all_execs = lifecycle_tracker.get_all_executions()
        invalid_execs = [e for e in all_execs.values() if e["command"] == "INVALID_NONSENSE_CMD"]
        assert len(invalid_execs) == 1
        assert invalid_execs[0]["status"] == "FAILED"
        assert "Invalid command" in invalid_execs[0]["error"]
        
        # 2. Valid command (Navigation)
        res2 = await ecosystem_orchestrator.process_command("PUSH", session=session_id)
        assert res2["status"] == "success"
        
        # Check that lifecycle tracker recorded it as SUCCESS
        nav_execs = [e for e in lifecycle_tracker.get_all_executions().values() if e["command"] == "PUSH"]
        assert len(nav_execs) == 1
        assert nav_execs[0]["status"] == "SUCCESS"
        assert nav_execs[0]["result"]["action"] == "transition"
    asyncio.run(_test())

