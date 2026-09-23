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

def test_embedded_plugin_loaded():
    embedded = get_plugin("embedded")
    assert embedded is not None
    assert "rc_car" in embedded.subplugins

def test_dashboard_route_serves_html():
    response = client.get("/")
    assert response.status_code == 200
    assert "SynaptiMesh" in response.text
    assert "rc-car-canvas" in response.text
    assert "rc-car-ui" in response.text

def test_navigation_to_embedded_domain_and_rc_car():
    from core.managers.command_lock_manager import command_lock_manager
    # Level 1 -> PULL (Selects EMBEDDED)
    command_lock_manager._locks.clear()
    res = client.post("/api/v1/bci/command", json={"command": "pull", "session_id": "default"})
    assert res.status_code == 200
    data = res.json()
    assert data["resolved"]["domain"] == "EMBEDDED"
    assert data["resolved"]["level"] == 2
    assert data["state"]["current_level"] == 2
    assert data["state"]["active_domain"] == "EMBEDDED"

    # Level 2 -> PUSH (Selects RC_CAR)
    command_lock_manager._locks.clear()
    res = client.post("/api/v1/bci/command", json={"command": "push", "session_id": "default"})
    assert res.status_code == 200
    data = res.json()
    assert data["resolved"]["app"] == "RC_CAR"
    assert data["resolved"]["level"] == 3
    assert data["state"]["current_level"] == 3
    assert data["state"]["active_app"] == "RC_CAR"

def test_rc_car_telemetry_status_endpoint():
    res = client.get("/api/v1/embedded/rc_car/status")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == "rc_car"
    assert "status" in data
    status = data["status"]
    assert "movement" in status
    assert "speed_mode" in status
    assert "speed_pwm" in status
    assert "front_distance" in status
    assert "rear_distance" in status

def test_rc_car_speed_endpoint():
    res = client.post("/api/v1/embedded/rc_car/speed", json={"speed_mode": "FAST"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["speed_mode"] == "FAST"

    # Verify status reflects new speed
    status_res = client.get("/api/v1/embedded/rc_car/status")
    assert status_res.json()["status"]["speed_mode"] == "FAST"
    assert status_res.json()["status"]["speed_pwm"] == 255

def test_rc_car_bci_actions_in_level_3():
    from core.managers.command_lock_manager import command_lock_manager
    state_manager.update_state("default", {
        "current_level": 3,
        "active_domain": "EMBEDDED",
        "active_app": "RC_CAR"
    })

    # PUSH -> FORWARD
    command_lock_manager._locks.clear()
    res = client.post("/api/v1/bci/command", json={"command": "push", "session_id": "default"})
    assert res.status_code == 200
    assert res.json()["action_result"]["action"] == "FORWARD"

    # PULL -> BACKWARD
    command_lock_manager._locks.clear()
    res = client.post("/api/v1/bci/command", json={"command": "pull", "session_id": "default"})
    assert res.status_code == 200
    assert res.json()["action_result"]["action"] == "BACKWARD"

    # LEFT -> LEFT
    command_lock_manager._locks.clear()
    res = client.post("/api/v1/bci/command", json={"command": "left", "session_id": "default"})
    assert res.status_code == 200
    assert res.json()["action_result"]["action"] == "LEFT"

    # RIGHT -> RIGHT
    command_lock_manager._locks.clear()
    res = client.post("/api/v1/bci/command", json={"command": "right", "session_id": "default"})
    assert res.status_code == 200
    assert res.json()["action_result"]["action"] == "RIGHT"

    # STOP
    res = client.post("/api/v1/embedded/rc_car/stop")
    assert res.status_code == 200
    assert res.json()["action"] == "STOP"

def test_navigation_manager_embedded_action():
    from core.navigation.manager import navigation_manager
    state_manager.update_state("default", {
        "current_level": 3,
        "active_domain": "EMBEDDED",
        "active_app": "RC_CAR"
    })
    
    import asyncio
    resp = asyncio.run(navigation_manager.process_navigation("PUSH", "default"))
    assert resp.status == "success"
    assert resp.action_result["action"] == "FORWARD"
