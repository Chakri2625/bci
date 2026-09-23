import pytest
import time
import os
import asyncio
from core.managers.lifecycle_tracker import lifecycle_tracker
from core.managers.priority_manager import get_command_priority, PriorityLevel
from core.logging.execution_logger import execution_logger
from core.orchestration.ecosystem_orchestrator import ecosystem_orchestrator

@pytest.fixture(autouse=True)
def setup_teardown():
    # Clear lifecycle tracker before each test
    lifecycle_tracker._executions.clear()
    
    # Ensure test log file is clean if needed, though we append
    yield

def test_priority_assignment():
    """Test existing PriorityManager integration"""
    assert get_command_priority("OPEN_CHROME") == PriorityLevel.NORMAL
    assert get_command_priority("STOP") == PriorityLevel.CRITICAL
    assert get_command_priority("UNKNOWN_CMD") == PriorityLevel.NORMAL

def test_lifecycle_tracker_priority_storage():
    """Test LifecycleTracker stores priority"""
    exec_id = lifecycle_tracker.start_execution("TEST_CMD", priority="HIGH")
    exec_info = lifecycle_tracker.get_execution(exec_id)
    assert exec_info["command"] == "TEST_CMD"
    assert exec_info["priority"] == "HIGH"
    assert exec_info["status"] == "PENDING"

def test_execution_event_logging():
    """Test end-to-end execution logging through Orchestrator"""
    # Use a safe command like 'TEST' which should fail validation but get logged as received and failed
    res = asyncio.run(ecosystem_orchestrator.process_command("TEST_COMMAND"))
    
    assert res["command"] == "TEST_COMMAND"
    # Should fail validation because TEST_COMMAND is not a valid sequence or action
    assert res["status"] in ("failed", "invalid")
    
    # Find the execution in tracker
    executions = lifecycle_tracker.get_all_executions()
    assert len(executions) >= 1
    exec_vals = list(executions.values())
    last_exec = exec_vals[-1]
    
    assert last_exec["command"] == "TEST_COMMAND"
    assert last_exec["priority"] == "NORMAL"
    assert last_exec["status"] == "FAILED"
    
    # Check log file
    log_file = os.path.join("data", "logs", "execution_events.log")
    assert os.path.exists(log_file)
    with open(log_file, "r") as f:
        content = f.read()
        assert "[EVENT=COMMAND_RECEIVED]" in content
        assert "[CMD=TEST_COMMAND]" in content
        assert "[EVENT=PRIORITY_ASSIGNED]" in content
        assert "[PRIORITY=NORMAL]" in content
        assert "[EVENT=EXECUTION_FAILED]" in content

def test_parallel_execution_event_isolation():
    """Test parallel execution event logging"""
    res = asyncio.run(ecosystem_orchestrator.process_command(["TEST_CMD_A", "TEST_CMD_B"]))
    assert isinstance(res, list)
    
    executions = lifecycle_tracker.get_all_executions()
    
    found_a = False
    found_b = False
    for ex in executions.values():
        if ex["command"] == "TEST_CMD_A":
            found_a = True
        if ex["command"] == "TEST_CMD_B":
            found_b = True
            
    assert found_a and found_b
