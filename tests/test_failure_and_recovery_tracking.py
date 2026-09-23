import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import asyncio
import time
from core.state.state_manager import state_manager
from core.orchestration.ecosystem_orchestrator import ecosystem_orchestrator
from core.navigation.sequence_validator import sequence_validator
from core.managers.lifecycle_tracker import lifecycle_tracker


@pytest.fixture(autouse=True)
def setup_teardown():
    """Reset state before and after each test."""
    state_manager.reset_state()
    state_manager.clear_failure_history()
    lifecycle_tracker.clear()
    yield
    state_manager.reset_state()
    state_manager.clear_failure_history()
    lifecycle_tracker.clear()


@pytest.mark.asyncio
async def test_01_normal_execution_no_false_failure():
    """Test 1: Normal command execution should not record any false failures."""
    res = await ecosystem_orchestrator.process_command("PUSH", session="test_norm")
    assert res["status"] == "success"
    
    ft = state_manager.get_failure_tracking()
    assert ft["active_failures_count"] == 0
    assert ft["total_failures_recorded"] == 0
    assert len(ft["failure_history"]) == 0
    assert ft["last_failure"] is None
    
    dom_health = state_manager.get_domain_health("DESKTOP")
    assert dom_health["status"] == "READY"
    assert dom_health["failure_reason"] is None
    assert dom_health["recovery_status"] == "NONE"


@pytest.mark.asyncio
async def test_02_execution_failure_recording():
    """Test 2: Direct or handler execution failure records structured details."""
    rec = state_manager.record_failure(
        command_id="cmd_fail_01",
        domain="DESKTOP",
        affected_component="Desktop Handler",
        failure_type="EXECUTION_ERROR",
        failure_reason="Failed to launch target application: Chrome",
        error_source="DesktopPlugin",
        recovery_status="RECOVERY_FAILED",
        session="test_exec_fail"
    )
    assert rec["command_id"] == "cmd_fail_01"
    assert rec["domain"] == "DESKTOP"
    assert rec["affected_component"] == "Desktop Handler"
    assert rec["failure_type"] == "EXECUTION_ERROR"
    assert rec["failure_reason"] == "Failed to launch target application: Chrome"
    assert rec["recovery_status"] == "RECOVERY_FAILED"
    
    # StateManager snapshot verification
    ft = state_manager.get_failure_tracking()
    assert ft["total_failures_recorded"] == 1
    assert ft["last_failure"]["command_id"] == "cmd_fail_01"
    
    dom_health = state_manager.get_domain_health("DESKTOP")
    assert dom_health["domain"] == "DESKTOP"
    assert dom_health["status"] == "DEGRADED"
    assert dom_health["affected_component"] == "Desktop Handler"
    assert dom_health["failure_reason"] == "Failed to launch target application: Chrome"


@pytest.mark.asyncio
async def test_03_domain_failure_fault_isolation():
    """Test 3: Fault isolation - failure in IoT does not degrade other domains."""
    state_manager.record_failure(
        command_id="cmd_iot_fault",
        domain="IOT",
        affected_component="IoT Handler",
        failure_type="DEVICE_OFFLINE",
        failure_reason="MQTT relay timeout on DEV-101",
        error_source="IoTPlugin",
        recovery_status="RECOVERY_FAILED",
        session="test_isolation"
    )
    
    # IoT should be degraded
    iot_health = state_manager.get_domain_health("IOT")
    assert iot_health["status"] == "DEGRADED"
    assert iot_health["failure_reason"] == "MQTT relay timeout on DEV-101"
    assert iot_health["affected_component"] == "IoT Handler"
    
    # Other domains MUST remain READY and healthy (Fault Isolation preserved)
    for other in ["DESKTOP", "EMBEDDED", "AIML", "MEDIA", "BCI"]:
        other_health = state_manager.get_domain_health(other)
        assert other_health["status"] == "READY", f"Domain {other} degraded unexpectedly!"
        assert other_health["failure_reason"] is None
        assert other_health["recovery_status"] == "NONE"


@pytest.mark.asyncio
async def test_04_recovery_lifecycle_transitions():
    """Test 4: Recovery lifecycle transitions (PENDING -> RETRYING/RECOVERING -> RECOVERED)."""
    # 1. Failure occurs (PENDING)
    state_manager.record_failure(
        command_id="cmd_rec_01",
        domain="EMBEDDED",
        affected_component="RC Car Motor Driver",
        failure_type="TIMEOUT_ERROR",
        failure_reason="Hardware ping timeout",
        error_source="EmbeddedPlugin",
        recovery_status="PENDING",
        session="test_rec"
    )
    emb_st = state_manager.get_domain_health("EMBEDDED")
    assert emb_st["recovery_status"] == "PENDING"
    
    # 2. Recovery begins (RETRYING)
    state_manager.update_recovery_status(
        command_id="cmd_rec_01",
        domain="EMBEDDED",
        affected_component="RC Car Motor Driver",
        recovery_status="RETRYING",
        attempt=2,
        reason="Resending motor control packet",
        session="test_rec"
    )
    emb_st = state_manager.get_domain_health("EMBEDDED")
    assert emb_st["status"] == "RECOVERING"
    assert emb_st["recovery_status"] == "RETRYING"
    assert emb_st["recovery_attempt"] == 2
    
    # 3. Recovery succeeds (RECOVERED)
    state_manager.update_recovery_status(
        command_id="cmd_rec_01",
        domain="EMBEDDED",
        affected_component="RC Car Motor Driver",
        recovery_status="RECOVERED",
        attempt=2,
        reason="Heartbeat re-established successfully",
        session="test_rec"
    )
    emb_st = state_manager.get_domain_health("EMBEDDED")
    assert emb_st["status"] == "READY"
    assert emb_st["recovery_status"] == "RECOVERED"
    assert emb_st["failure_reason"] is None


@pytest.mark.asyncio
async def test_05_concurrent_failures_safety():
    """Test 5: Multiple concurrent failures on distinct domains do not overwrite each other."""
    async def fail_domain(dom, comp, reason, cid):
        state_manager.record_failure(
            command_id=cid,
            domain=dom,
            affected_component=comp,
            failure_type="TEST_ERROR",
            failure_reason=reason,
            error_source="TestRunner",
            recovery_status="RECOVERY_FAILED"
        )
        await asyncio.sleep(0.01)

    tasks = [
        fail_domain("IOT", "IoT Handler", "IoT node 101 unresponsive", "cmd_c1"),
        fail_domain("DESKTOP", "Desktop Handler", "Subprocess exit code 1", "cmd_c2"),
        fail_domain("AIML", "Audio Engine", "Microphone stream disconnected", "cmd_c3"),
    ]
    await asyncio.gather(*tasks)

    ft = state_manager.get_failure_tracking()
    assert ft["total_failures_recorded"] == 3
    assert len(ft["failure_history"]) == 3

    # Verify per-domain health isolation
    iot_h = state_manager.get_domain_health("IOT")
    assert iot_h["failure_reason"] == "IoT node 101 unresponsive"
    assert iot_h["affected_component"] == "IoT Handler"

    desk_h = state_manager.get_domain_health("DESKTOP")
    assert desk_h["failure_reason"] == "Subprocess exit code 1"
    assert desk_h["affected_component"] == "Desktop Handler"

    aiml_h = state_manager.get_domain_health("AIML")
    assert aiml_h["failure_reason"] == "Microphone stream disconnected"
    assert aiml_h["affected_component"] == "Audio Engine"

    # Embedded should remain unaffected
    emb_h = state_manager.get_domain_health("EMBEDDED")
    assert emb_h["status"] == "READY"


@pytest.mark.asyncio
async def test_06_timeout_failure_tracking():
    """Test 6: Execution timeout failure tracking."""
    state_manager.record_failure(
        command_id="cmd_time_01",
        domain="MEDIA",
        affected_component="Media Handler",
        failure_type="TIMEOUT",
        failure_reason="Execution timeout exceeded (10.0s)",
        error_source="ExecutionController",
        recovery_status="RECOVERY_FAILED",
        session="test_timeout"
    )
    ft = state_manager.get_failure_tracking()
    assert ft["last_failure"]["failure_type"] == "TIMEOUT"
    assert "timeout exceeded" in ft["last_failure"]["failure_reason"]
    assert ft["last_failure"]["affected_component"] == "Media Handler"


@pytest.mark.asyncio
async def test_07_retry_failure_exhaustion():
    """Test 7: Retry progression to exhaustion."""
    # Attempt 1 -> RETRYING
    state_manager.update_recovery_status(
        command_id="cmd_retry_01",
        domain="IOT",
        affected_component="IoT Handler",
        recovery_status="RETRYING",
        attempt=1,
        reason="Retrying after socket disconnect"
    )
    # Attempt 2 -> RETRYING
    state_manager.update_recovery_status(
        command_id="cmd_retry_01",
        domain="IOT",
        affected_component="IoT Handler",
        recovery_status="RETRYING",
        attempt=2,
        reason="Retrying after socket disconnect"
    )
    # Attempt 3 -> RECOVERY_FAILED
    state_manager.update_recovery_status(
        command_id="cmd_retry_01",
        domain="IOT",
        affected_component="IoT Handler",
        recovery_status="RECOVERY_FAILED",
        attempt=3,
        reason="Retries exhausted (3/3)"
    )
    
    iot_h = state_manager.get_domain_health("IOT")
    assert iot_h["recovery_status"] == "RECOVERY_FAILED"
    assert iot_h["recovery_attempt"] == 3
    assert iot_h["status"] == "DEGRADED"


@pytest.mark.asyncio
async def test_08_invalid_command_validation_failure_tracking():
    """Test 8: Invalid command sequence triggers Validation Engine failure tracking."""
    # S (PULL) from Level 1 root is invalid without transition
    res = await ecosystem_orchestrator.process_command("PULL", session="test_invalid_seq")
    assert res["status"] in ("invalid", "success")  # if Level 1 PULL is transition or invalid
    
    # Test an explicitly invalid command
    res_bad = await ecosystem_orchestrator.process_command("INVALID_XYZ_ACTION", session="test_invalid_seq")
    assert res_bad["status"] == "invalid"
    
    ft = state_manager.get_failure_tracking()
    assert ft["total_failures_recorded"] >= 1
    assert ft["last_failure"]["affected_component"] == "Validation Engine"
    assert ft["last_failure"]["failure_type"] == "VALIDATION_ERROR"
    assert ft["last_failure"]["error_source"] == "SequenceValidator"


@pytest.mark.asyncio
async def test_09_state_manager_system_state_exposure():
    """Test 9: System state snapshot automatically contains failure_tracking schema."""
    sys_state = state_manager.get_system_state()
    assert "failure_tracking" in sys_state
    ft = sys_state["failure_tracking"]
    assert "last_failure" in ft
    assert "active_failures_count" in ft
    assert "total_failures_recorded" in ft
    assert "recovery_summary" in ft
    assert "failure_history" in ft


@pytest.mark.asyncio
async def test_10_clear_failure_history():
    """Test 10: Clearing failure history globally and per-domain."""
    state_manager.record_failure("c1", "IOT", "IoT Handler", "ERR", "IoT fail")
    state_manager.record_failure("c2", "DESKTOP", "Desktop Handler", "ERR", "Desktop fail")
    
    assert state_manager.get_failure_tracking()["total_failures_recorded"] == 2
    
    # Clear only IoT
    state_manager.clear_failure_history(domain="IOT")
    assert state_manager.get_domain_health("IOT")["failure_reason"] is None
    assert state_manager.get_domain_health("IOT")["status"] == "READY"
    assert state_manager.get_domain_health("DESKTOP")["failure_reason"] == "Desktop fail"
    
    # Clear all
    state_manager.clear_failure_history()
    assert len(state_manager.get_failure_tracking()["failure_history"]) == 0
    assert state_manager.get_failure_tracking()["last_failure"] is None
    assert state_manager.get_domain_health("DESKTOP")["failure_reason"] is None


if __name__ == "__main__":
    pytest.main(["-v", __file__])
