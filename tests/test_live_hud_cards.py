import pytest
import time
from fastapi.testclient import TestClient
from main import app
from core.state.state_manager import state_manager
from core.managers.lifecycle_tracker import lifecycle_tracker
from core.orchestration.ecosystem_orchestrator import ecosystem_orchestrator
from core.managers.command_lock_manager import command_lock_manager

client = TestClient(app)

@pytest.fixture(autouse=True)
def clean_state():
    state_manager.reset_state()
    state_manager.clear_failure_history()
    lifecycle_tracker.clear()
    command_lock_manager.reset()
    yield
    state_manager.reset_state()
    state_manager.clear_failure_history()
    lifecycle_tracker.clear()
    command_lock_manager.reset()

def test_hud_card_1_execution_timing_lifecycle():
    """Verify Card 1 (Execution Timing) fields: start time, completion time, duration, domain target."""
    response = client.post("/api/v1/bci/command", json={"command": "PUSH", "session_id": "hud_sess"})
    assert response.status_code == 200
    data = response.json()
    
    assert data["status"] == "success"
    cid = data.get("command_id")
    assert cid is not None
    
    # Timing payload check
    timing = data.get("timing")
    assert timing is not None
    assert timing["command"] == "PUSH"
    assert timing["started_at_iso"] is not None
    assert timing["completed_at_iso"] is not None
    assert timing["duration_ms"] is not None
    assert timing["duration_ms"] >= 0.0
    
    # Direct endpoint verification
    timing_res = client.get(f"/api/v1/lifecycle/{cid}/timing")
    assert timing_res.status_code == 200
    t_data = timing_res.json()["timing"]
    assert t_data["command_id"] == cid
    assert t_data["status"] in ("SUCCESS", "COMPLETED", "EXECUTION_COMPLETED")

def test_hud_card_2_execution_performance_latencies():
    """Verify Card 2 (Execution Performance) fields: proc latency, exec latency, active tasks, bottleneck status."""
    # Before command: optimal state
    sys_res0 = client.get("/api/v1/state/system")
    assert sys_res0.status_code == 200
    sys_data0 = sys_res0.json()
    assert sys_data0["active_tasks_count"] == 0
    assert sys_data0["performance"]["bottleneck_status"] == "OPTIMAL"
    
    # Execute commands
    client.post("/api/v1/bci/command", json={"command": "PUSH", "session_id": "perf_sess"})
    
    sys_res1 = client.get("/api/v1/state/system")
    sys_data1 = sys_res1.json()
    perf1 = sys_data1["performance"]
    
    assert perf1["total_measured_commands"] >= 1
    assert perf1["recent_processing_latency_ms"] >= 0.0
    assert perf1["recent_execution_latency_ms"] >= 0.0
    assert perf1["avg_processing_latency_ms"] >= 0.0
    assert perf1["avg_execution_latency_ms"] >= 0.0
    assert perf1["bottleneck_status"] == "OPTIMAL"
    assert isinstance(perf1["bottleneck_indicators"], list)

def test_hud_card_3_fault_and_recovery_tracking():
    """Verify Card 3 (Fault & Recovery) fields: subsystem, recovery stage, failure reason, active failures."""
    # 1. Initial nominal state
    sys_res = client.get("/api/v1/state/system")
    ft0 = sys_res.json()["failure_tracking"]
    assert ft0["active_failures_count"] == 0
    
    # 2. Trigger an invalid command
    bad_resp = client.post("/api/v1/bci/command", json={"command": "INVALID_TELEMETRY_CMD", "session_id": "fault_sess"})
    assert bad_resp.status_code in (400, 200)
    
    # 3. Verify structured failure was recorded
    ft_res = client.get("/api/v1/state/failures")
    assert ft_res.status_code == 200
    ft_data = ft_res.json()
    assert ft_data["total_failures_recorded"] >= 1
    assert ft_data["last_failure"] is not None
    assert ft_data["last_failure"]["affected_component"] == "Validation Engine"
    assert "Invalid command" in ft_data["last_failure"]["failure_reason"]
    
    # 4. Recovery / clearing state
    clear_res = client.post("/api/v1/state/failures/clear")
    assert clear_res.status_code == 200
    
    ft_cleared = client.get("/api/v1/state/failures").json()
    assert ft_cleared["active_failures_count"] == 0
    assert ft_cleared["last_failure"] is None
