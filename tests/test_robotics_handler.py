import pytest
from fastapi.testclient import TestClient
from main import app
from core.state.state_manager import state_manager
from core.plugin_manager.manager import get_plugin, load_plugins, PLUGINS

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_state():
    state_manager.states.clear()
    PLUGINS.clear()
    load_plugins()


def _enter_device(device_app: str):
    """Helper: put session state directly at Level 3, EMBEDDED domain, given app."""
    state_manager.update_state("default", {
        "current_level": 3,
        "active_domain": "EMBEDDED",
        "active_app": device_app
    })


# ---------------------------------------------------------------------------
# Test 1-4: PUSH/PULL/LEFT/RIGHT -> internal robotics operation (RC_CAR)
# ---------------------------------------------------------------------------

def test_1_push_maps_to_forward():
    _enter_device("RC_CAR")
    response = client.post("/api/v1/bci/command", json={"command": "push"})
    assert response.status_code == 200
    data = response.json()
    assert data["resolved"]["action"] == "FORWARD"
    assert data["action_result"]["status"] == "success"


def test_2_pull_maps_to_backward_and_embedded_behavior():
    # From the top level, PULL activates the Embedded domain (device selection).
    response = client.post("/api/v1/bci/command", json={"command": "pull"})
    assert response.status_code == 200
    data = response.json()
    assert data["resolved"]["type"] == "transition"
    assert data["resolved"]["domain"] == "EMBEDDED"

    # Once inside a device (RC_CAR), PULL means "move backward".
    _enter_device("RC_CAR")
    response = client.post("/api/v1/bci/command", json={"command": "pull"})
    data = response.json()
    assert data["resolved"]["action"] == "BACKWARD"
    assert data["action_result"]["status"] == "success"


def test_3_left_maps_to_turn_left():
    _enter_device("RC_CAR")
    response = client.post("/api/v1/bci/command", json={"command": "left"})
    data = response.json()
    assert data["resolved"]["action"] == "LEFT"
    assert data["action_result"]["status"] == "success"


def test_4_right_maps_to_turn_right():
    _enter_device("RC_CAR")
    response = client.post("/api/v1/bci/command", json={"command": "right"})
    data = response.json()
    assert data["resolved"]["action"] == "RIGHT"
    assert data["action_result"]["status"] == "success"


# ---------------------------------------------------------------------------
# Test 5-6: CAR and WHEELCHAIR are the available Embedded devices
# ---------------------------------------------------------------------------

def test_5_car_available_in_embedded_device_layer():
    state_manager.update_state("default", {"current_level": 2, "active_domain": "EMBEDDED"})
    response = client.post("/api/v1/bci/command", json={"command": "push"})
    data = response.json()
    assert data["resolved"]["app"] == "RC_CAR"

    embedded = get_plugin("embedded")
    assert "rc_car" in embedded.subplugins


def test_6_wheelchair_available_in_embedded_device_layer():
    state_manager.update_state("default", {"current_level": 2, "active_domain": "EMBEDDED"})
    response = client.post("/api/v1/bci/command", json={"command": "pull"})
    data = response.json()
    assert data["resolved"]["app"] == "WHEELCHAIR"

    embedded = get_plugin("embedded")
    assert "wheelchair" in embedded.subplugins

    # And WHEELCHAIR responds to the same movement mapping as RC_CAR.
    _enter_device("WHEELCHAIR")
    response = client.post("/api/v1/bci/command", json={"command": "push"})
    data = response.json()
    assert data["resolved"]["action"] == "FORWARD"
    assert data["action_result"]["status"] == "success"


# ---------------------------------------------------------------------------
# Test 7: Desktop/media apps must NOT be exposed as Embedded devices
# ---------------------------------------------------------------------------

def test_7_desktop_apps_not_exposed_in_embedded_domain():
    embedded = get_plugin("embedded")
    disallowed = {"chrome", "mail", "gmail", "email", "youtube", "notepad", "calculator", "calendar", "outlook"}
    assert disallowed.isdisjoint(set(embedded.subplugins.keys()))

    # And the Level 2 EMBEDDED device map only ever resolves to CAR/WHEELCHAIR.
    state_manager.update_state("default", {"current_level": 2, "active_domain": "EMBEDDED"})
    for cmd in ("push", "pull", "left", "right"):
        response = client.post("/api/v1/bci/command", json={"command": cmd})
        data = response.json()
        app = data["resolved"].get("app")
        if app is not None:
            assert app in ("RC_CAR", "WHEELCHAIR")


# ---------------------------------------------------------------------------
# Test 8: Unknown robotics command fails gracefully
# ---------------------------------------------------------------------------

def test_8_unknown_robotics_command_fails_gracefully():
    _enter_device("RC_CAR")
    response = client.post("/api/v1/bci/command", json={"command": "jump"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "invalid"
    assert data["executed"] is False


# ---------------------------------------------------------------------------
# Test 9: Invalid/missing command fails gracefully
# ---------------------------------------------------------------------------

def test_9_missing_command_field_rejected():
    response = client.post("/api/v1/bci/command", json={})
    # FastAPI/pydantic rejects a missing required field at the schema level.
    assert response.status_code == 422


def test_9b_empty_command_string_fails_gracefully():
    _enter_device("RC_CAR")
    response = client.post("/api/v1/bci/command", json={"command": ""})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "invalid"


# ---------------------------------------------------------------------------
# Test 10: Robotics execution failure returns controlled failure, no crash
# ---------------------------------------------------------------------------

def test_10_robotics_execution_failure_is_contained(monkeypatch):
    _enter_device("RC_CAR")
    embedded = get_plugin("embedded")
    rc_car = embedded.subplugins["rc_car"]

    def boom(command, confidence):
        raise RuntimeError("simulated hardware failure")

    monkeypatch.setattr(rc_car.processor, "process_command", boom)

    response = client.post("/api/v1/bci/command", json={"command": "push"})
    assert response.status_code == 200
    data = response.json()
    # The orchestrator must not crash/500; the failure is reported in-band.
    assert data["action_result"]["status"] in ("failed", "FAILED")


# ---------------------------------------------------------------------------
# Additional: STOP works for both devices via the dedicated stop endpoint
# ---------------------------------------------------------------------------

def test_rc_car_stop_endpoint():
    response = client.post("/api/v1/embedded/rc_car/stop")
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "STOP"
    assert data["status"] == "success"
