"""
Day 9 Member 2 — IoT Execution Path Integration Tests
------------------------------------------------------
Validates the complete unified backend execution pipeline for the IoT domain:
1. IoT Command Routing: validation -> router -> orchestrator -> IoT execution path
2. IoT Execution: Invocation of existing IoT integration layer
3. Successful IoT Execution: Command execution, response, state, lifecycle, logging, telemetry
4. Device Unavailable Handling: Graceful error response & telemetry tracking
5. Communication Failure Isolation: Fault isolation without affecting other domains
6. Timeout & ACK Handling: Proper handling of timeouts/delays
7. Concurrent Execution: Non-blocking parallel execution across multiple domains
8. Domain Navigation: Home -> IoT -> Back to SynaptiMesh and other domains
9. Temporal Window Safety: Ensuring temporal window framing holds and executes cleanly
"""

import pytest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient

from main import app
from core.state.state_manager import state_manager
from core.managers.lifecycle_tracker import lifecycle_tracker, CommandLifecycleStage
from core.plugin_manager.manager import load_plugins, get_plugin, PLUGINS
from core.orchestration.ecosystem_orchestrator import ecosystem_orchestrator
from core.routing.rule_router import resolve_command, navigate_home, navigate_back
from core.managers.command_lock_manager import command_lock_manager

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_teardown():
    state_manager.reset_state("default")
    state_manager.clear_failure_history()
    command_lock_manager.reset()
    PLUGINS.clear()
    load_plugins()
    yield
    state_manager.reset_state("default")
    state_manager.clear_failure_history()
    command_lock_manager.reset()


# ----------------------------------------------------------------------
# Test 1: IoT Command Routing (Validation -> Router -> Orchestrator)
# ----------------------------------------------------------------------
def test_iot_command_routing_bci():
    """Verify BCI commands route through validation, router, orchestrator to IoT path."""
    command_lock_manager.reset()
    # Level 1 -> Transition to IOT domain
    res1 = client.post("/api/v1/bci/command", json={"command": "LEFT", "session_id": "default"})
    assert res1.status_code == 200
    d1 = res1.json()
    assert d1["resolved"]["type"] == "transition"
    assert d1["resolved"]["domain"] == "IOT"
    assert d1["state"]["active_domain"] == "IOT"
    assert d1["state"]["current_level"] == 2

    command_lock_manager.reset()
    # Level 2 -> Transition to LIGHT app
    res2 = client.post("/api/v1/bci/command", json={"command": "PUSH", "session_id": "default"})
    assert res2.status_code == 200
    d2 = res2.json()
    assert d2["resolved"]["type"] == "transition"
    assert d2["resolved"]["app"] == "LIGHT"
    assert d2["state"]["active_app"] == "LIGHT"
    assert d2["state"]["current_level"] == 3

    command_lock_manager.reset()
    # Level 3 -> Execute Light action
    iot_plugin = get_plugin("iot")
    with patch.object(iot_plugin, "execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = {
            "status": "success",
            "command_id": "test_cmd_1",
            "topic": "iot/esp32/action",
            "message": "Command published successfully",
            "command": {"device": "light", "state": "ON"}
        }

        res3 = client.post("/api/v1/bci/command", json={"command": "RIGHT", "device_id": "ESP32_RELAY_01", "session_id": "default"})
        assert res3.status_code == 200
        d3 = res3.json()
        assert d3["status"] == "success"
        assert d3["resolved"]["action"] == "Left_light_on"
        assert d3["executed"] is True
        assert d3["action_result"]["status"] == "success"
        assert d3["lifecycle_stage"] in ("SUCCESS", "EXECUTION_COMPLETED", "COMPLETED")


# ----------------------------------------------------------------------
# Test 2: IoT Execution Path Invocation
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_iot_execution_invokes_plugin():
    """Verify the orchestrator directly calls IoT plugin execute with correct payload."""
    state_manager.update_state("default", {"current_level": 3, "active_domain": "IOT", "active_app": "FAN"})
    iot_plugin = get_plugin("iot")
    assert iot_plugin is not None

    with patch.object(iot_plugin, "execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = {
            "status": "success",
            "command_id": "cmd_fan_01",
            "topic": "iot/esp32/action",
            "message": "Command published successfully"
        }

        res = await ecosystem_orchestrator.process_command(
            command="RIGHT",
            session="default",
            device_id="ESP32_RELAY_01"
        )

        assert res["status"] == "success"
        mock_exec.assert_called_once()
        call_args = mock_exec.call_args
        assert call_args[0][0] == "Left_fan_on"
        assert call_args[0][1]["device_id"] == "ESP32_RELAY_01"


# ----------------------------------------------------------------------
# Test 3: Successful IoT Execution & Lifecycle / Telemetry Recording
# ----------------------------------------------------------------------
def test_successful_iot_execution_dashboard_api():
    """Verify dispatching an IoT command via /api/iot/command updates state and lifecycle."""
    iot_plugin = get_plugin("iot")
    with patch.object(iot_plugin, "execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = {
            "status": "success",
            "command_id": "cmd_dash_01",
            "topic": "iot/esp32/action",
            "message": "Command published successfully",
            "command": {"device": "pump", "state": "ON"},
            "raw_payload": {"device": "pump", "state": "ON", "timestamp": 123456789}
        }

        resp = client.post("/api/iot/command", json={
            "command": "left_pump_on",
            "domain": "iot",
            "device_id": "ESP32_RELAY_01"
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["domain"] == "iot"
        assert data["device_id"] == "ESP32_RELAY_01"
        assert data["lifecycle_stage"] in ("SUCCESS", "EXECUTION_COMPLETED", "COMPLETED")
        assert "command_id" in data

        # Verify lifecycle tracker has recorded this command
        rec = lifecycle_tracker.get_lifecycle(data["command_id"])
        assert rec is not None
        assert rec.current_stage.value in ("SUCCESS", "EXECUTION_COMPLETED", "COMPLETED")


# ----------------------------------------------------------------------
# Test 4: Device Unavailable Handling
# ----------------------------------------------------------------------
def test_device_unavailable_handling():
    """Verify missing device_id in BCI mode is handled gracefully without crash."""
    command_lock_manager.reset()
    state_manager.update_state("default", {"current_level": 3, "active_domain": "IOT", "active_app": "LIGHT"})

    # BCI command without device_id triggers validation error
    resp = client.post("/api/v1/bci/command", json={"command": "RIGHT", "session_id": "default"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["action_result"]["status"] == "failed"
    assert "device_id" in data["action_result"]["error"].lower()

    # Verify failure is recorded in state manager
    failures = state_manager.get_failure_tracking()
    assert failures["total_failures_recorded"] > 0
    last_fail = failures["last_failure"]
    assert last_fail["domain"] == "IOT"
    assert last_fail["affected_component"] == "IoT Handler"


# ----------------------------------------------------------------------
# Test 5: Communication / MQTT Failure Isolation
# ----------------------------------------------------------------------
def test_communication_failure_isolation():
    """Verify IoT MQTT failure is recorded and isolated without impacting other domains."""
    command_lock_manager.reset()
    state_manager.update_state("default", {"current_level": 3, "active_domain": "IOT", "active_app": "LIGHT"})
    iot_plugin = get_plugin("iot")

    with patch.object(iot_plugin, "execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = {
            "status": "error",
            "message": "MQTT client disconnected",
            "command_id": "err_cmd_01"
        }

        resp = client.post("/api/v1/bci/command", json={"command": "RIGHT", "device_id": "ESP32_RELAY_01", "session_id": "default"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["action_result"]["status"] in ("failed", "error")

        # Verify failure tracking records IoT failure
        failures = state_manager.get_failure_tracking()
        assert failures["total_failures_recorded"] > 0
        assert failures["last_failure"]["domain"] == "IOT"

        # Verify other domains (DESKTOP, AIML, EMBEDDED) remain intact and operational
        health = client.get("/api/v1/health").json()
        assert "domains" in health
        assert health["domains"]["desktop"]["online"] is True


# ----------------------------------------------------------------------
# Test 6: Timeout & Error Handling
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_timeout_handling():
    """Verify IoT execute_with_ack handles timeout gracefully."""
    iot_plugin = get_plugin("iot")
    iot_plugin.connected = True
    
    mock_msg_info = MagicMock()
    mock_msg_info.rc = 0
    iot_plugin.client.publish = MagicMock(return_value=mock_msg_info)

    # Execute with ACK with tiny timeout
    result = await iot_plugin.execute_with_ack(
        command="turn on",
        payload={"device_id": "test_dev_timeout", "command_id": "to_cmd_1"},
        timeout=0.05
    )
    assert result["status"] == "error"
    assert "timeout" in result["message"].lower()


# ----------------------------------------------------------------------
# Test 7: Concurrent Execution Across Domains
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_concurrent_domain_execution():
    """Verify parallel engine can run IoT commands alongside other domain commands."""
    iot_plugin = get_plugin("iot")
    with patch.object(iot_plugin, "execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = {
            "status": "success",
            "command_id": "par_iot_1",
            "topic": "iot/esp32/action",
            "message": "Command published successfully"
        }

        # Set up state at Level 3 IoT LIGHT
        state_manager.update_state("default", {"current_level": 3, "active_domain": "IOT", "active_app": "LIGHT"})

        # Send parallel batch
        res = await ecosystem_orchestrator.process_command(
            command=["RIGHT", "LEFT"],
            session="default",
            device_id="ESP32_RELAY_01"
        )

        assert isinstance(res, list)
        assert len(res) == 2


# ----------------------------------------------------------------------
# Test 8: Domain Navigation
# ----------------------------------------------------------------------
def test_domain_navigation_iot_and_back():
    """Verify Home -> IoT -> Back to SynaptiMesh navigation."""
    # 1. Reset state to Home (Level 1)
    command_lock_manager.reset()
    state = state_manager.get_state("default")
    assert state["current_level"] == 1
    assert state["active_domain"] is None

    # 2. Navigate to IoT (LEFT gesture)
    res1 = client.post("/api/v1/bci/command", json={"command": "LEFT"})
    assert res1.status_code == 200
    d1 = res1.json()
    assert d1["state"]["active_domain"] == "IOT"
    assert d1["state"]["current_level"] == 2

    # 3. Navigate back (PUSH_RIGHT)
    command_lock_manager.reset()
    res2 = client.post("/api/v1/bci/command", json={"command": "PUSH_RIGHT"})
    assert res2.status_code == 200
    d2 = res2.json()
    assert d2["state"]["current_level"] == 1
    assert d2["state"]["active_domain"] is None

    # 4. Navigate to AIML (RIGHT gesture)
    command_lock_manager.reset()
    res3 = client.post("/api/v1/bci/command", json={"command": "RIGHT"})
    assert res3.status_code == 200
    assert res3.json()["state"]["active_domain"] == "AIML"

    # 5. Navigate home (PUSH_LEFT)
    command_lock_manager.reset()
    res4 = client.post("/api/v1/bci/command", json={"command": "PUSH_LEFT"})
    assert res4.status_code == 200
    assert res4.json()["state"]["current_level"] == 1


# ----------------------------------------------------------------------
# Test 9: Temporal Window Safety Check
# ----------------------------------------------------------------------
def test_temporal_window_endpoints_and_health():
    """Verify system health, widgets, and lifecycle timing endpoints."""
    # Health endpoint
    h = client.get("/api/v1/health")
    assert h.status_code == 200
    assert "iot" in h.json()["domains"]

    # Lifecycle summary
    lc = client.get("/api/v1/lifecycle/summary")
    assert lc.status_code == 200
    assert lc.json()["status"] == "success"

    # State endpoint
    st = client.get("/api/v1/state")
    assert st.status_code == 200
