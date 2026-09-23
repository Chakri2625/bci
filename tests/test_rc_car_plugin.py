import pytest
from fastapi.testclient import TestClient
from main import app
from core.state.state_manager import state_manager
from core.plugin_manager.manager import get_plugin, load_plugins, PLUGINS

client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_state():
    from core.managers.command_lock_manager import command_lock_manager
    state_manager.states.clear()
    command_lock_manager._locks.clear()
    if hasattr(command_lock_manager, "_active_combo_locks"):
        command_lock_manager._active_combo_locks.clear()
    PLUGINS.clear()
    load_plugins()
    yield
    command_lock_manager._locks.clear()
    if hasattr(command_lock_manager, "_active_combo_locks"):
        command_lock_manager._active_combo_locks.clear()

def test_plugin_discovery():
    # Verify embedded plugin is loaded
    embedded = get_plugin("embedded")
    assert embedded is not None
    assert "rc_car" in embedded.subplugins

def test_embedded_domain_routing():
    # Transition to embedded domain
    response = client.post("/api/v1/bci/command", json={"command": "pull"})
    assert response.status_code == 200
    data = response.json()
    assert data["resolved"]["domain"] == "EMBEDDED"
    
    # Transition to RC_CAR plugin
    response = client.post("/api/v1/bci/command", json={"command": "push"})
    assert response.status_code == 200
    data = response.json()
    assert data["resolved"]["app"] == "RC_CAR"

def test_rc_car_push_forward():
    # Setup state
    state_manager.update_state("default", {"current_level": 3, "active_domain": "EMBEDDED", "active_app": "RC_CAR"})
    
    # Send PUSH command
    response = client.post("/api/v1/bci/command", json={"command": "push"})
    assert response.status_code == 200
    data = response.json()
    
    # The rule router maps PUSH to FORWARD for RC_CAR
    assert data["resolved"]["action"] == "FORWARD"
    
    # The plugin executes and command processor logs it (or rejects if low confidence, but test uses default 1.0)
    assert data["action_result"]["action"] == "FORWARD"
    assert data["action_result"]["status"] == "success"

def test_rc_car_status_api():
    response = client.get("/api/v1/embedded/rc_car/status")
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "rc_car"
    assert "movement" in data["status"]

def test_rc_car_stop_api():
    response = client.post("/api/v1/embedded/rc_car/stop")
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "STOP"
    assert data["status"] == "success"

def test_json_automation_api():
    payload = {
        "domain": "embedded",
        "plugin": "rc_car",
        "commands": [
            {"command": "push", "delay": 0.1},
            {"command": "stop", "delay": 0.1}
        ]
    }
    response = client.post("/api/v1/automation/execute", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "started"

def test_rc_car_offline_status():
    embedded = get_plugin("embedded")
    rc_car = embedded.subplugins["rc_car"]
    
    # Simulate device reporting OFFLINE
    rc_car.sender.last_device_status = "OFFLINE"
    
    # Verify sender and plugin report not connected
    assert rc_car.sender.is_connected() is False
    assert rc_car.is_connected() is False
    assert embedded.is_connected() is False
    
    # Verify health endpoint returns embedded offline
    health_resp = client.get("/api/v1/health")
    assert health_resp.status_code == 200
    health_data = health_resp.json()
    assert health_data["domains"]["embedded"]["online"] is False
    
    # Verify rc_car status API returns OFFLINE
    status_resp = client.get("/api/v1/embedded/rc_car/status")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["status"]["connected"] is False
    assert status_data["status"]["status"] == "OFFLINE"

