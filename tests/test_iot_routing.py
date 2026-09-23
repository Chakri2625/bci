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
    PLUGINS.clear()
    load_plugins()
    yield
    command_lock_manager._locks.clear()

def test_iot_domain_routing():
    # Transition to IOT domain (Level 1 -> 2) via LEFT (A)
    response = client.post("/api/v1/bci/command", json={"command": "left"})
    assert response.status_code == 200
    data = response.json()
    assert data["resolved"]["domain"] == "IOT"

def test_iot_level2_to_3_routing():
    from core.managers.command_lock_manager import command_lock_manager
    # Transition to specific apps
    for cmd, app_target in [("push", "LIGHT"), ("pull", "FAN"), ("left", "PUMP")]:
        command_lock_manager._locks.clear()
        state_manager.update_state("default", {"current_level": 2, "active_domain": "IOT"})
        response = client.post("/api/v1/bci/command", json={"command": cmd, "session_id": "default"})
        assert response.status_code == 200
        data = response.json()
        assert data["resolved"]["app"] == app_target

def test_iot_level3_light_actions():
    from core.managers.command_lock_manager import command_lock_manager
    state_manager.update_state("default", {"current_level": 3, "active_domain": "IOT", "active_app": "LIGHT"})
    
    command_lock_manager._locks.clear()
    response = client.post("/api/v1/bci/command", json={"command": "RIGHT", "device_id": "test1", "session_id": "default"})
    assert response.status_code == 200
    assert response.json()["resolved"]["action"] == "Left_light_on"
    
    command_lock_manager._locks.clear()
    response = client.post("/api/v1/bci/command", json={"command": "LEFT", "device_id": "test1", "session_id": "default"})
    assert response.status_code == 200
    assert response.json()["resolved"]["action"] == "Left_light_off"

def test_iot_level3_fan_actions():
    from core.managers.command_lock_manager import command_lock_manager
    state_manager.update_state("default", {"current_level": 3, "active_domain": "IOT", "active_app": "FAN"})
    
    command_lock_manager._locks.clear()
    response = client.post("/api/v1/bci/command", json={"command": "RIGHT", "device_id": "test1", "session_id": "default"})
    assert response.status_code == 200
    assert response.json()["resolved"]["action"] == "Left_fan_on"
    
def test_iot_level3_pump_actions():
    from core.managers.command_lock_manager import command_lock_manager
    state_manager.update_state("default", {"current_level": 3, "active_domain": "IOT", "active_app": "PUMP"})
    
    command_lock_manager._locks.clear()
    response = client.post("/api/v1/bci/command", json={"command": "LEFT", "device_id": "test1", "session_id": "default"})
    assert response.status_code == 200
    assert response.json()["resolved"]["action"] == "Left_pump_off"

def test_missing_device_id_error():
    from core.managers.command_lock_manager import command_lock_manager
    command_lock_manager._locks.clear()
    state_manager.update_state("default", {"current_level": 3, "active_domain": "IOT", "active_app": "LIGHT"})
    
    # Missing device_id payload should return an error gracefully
    response = client.post("/api/v1/bci/command", json={"command": "RIGHT", "session_id": "default"})
    assert response.status_code == 200
    data = response.json()
    assert data["action_result"]["status"] == "failed"
    assert "missing" in data["action_result"]["error"].lower()
