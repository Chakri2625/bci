from fastapi.testclient import TestClient
from main import app
from core.state.state_manager import state_manager
import pytest
import logging
from io import StringIO

client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_state():
    from core.managers.command_lock_manager import command_lock_manager
    state_manager.states.clear()
    command_lock_manager._locks.clear()
    yield
    command_lock_manager._locks.clear()

def test_navigation_state_initial():
    response = client.get("/api/navigation/state")
    assert response.status_code == 200
    data = response.json()
    assert data["current_level"] == 1
    assert data["current_domain"] is None

def test_valid_push_navigation():
    # Push on level 1 selects Python domain
    response = client.post("/api/navigation/command", json={"command": "push"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["command"] == "PUSH"
    assert data["target_domain"] == "PYTHON"

def test_valid_pull_navigation():
    # Pull on level 1 selects Embedded domain
    response = client.post("/api/navigation/command", json={"command": "pull"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["target_domain"] == "EMBEDDED"

def test_valid_w_navigation_normalization():
    # "w" alias on level 1 selects Python domain, just like PUSH
    response = client.post("/api/navigation/command", json={"command": "w"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["command"] == "PUSH"
    assert data["target_domain"] == "PYTHON"

def test_valid_left_navigation():
    # Left on level 1 selects IoT domain
    response = client.post("/api/navigation/command", json={"command": "left"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["target_domain"] == "IOT"

def test_valid_right_navigation():
    # Right on level 1 selects AIML
    response = client.post("/api/navigation/command", json={"command": "right"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["target_domain"] == "AIML"

def test_invalid_command():
    # Invalid command
    response = client.post("/api/navigation/command", json={"command": "jump"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["error"] == "invalid command"

def test_invalid_domain_transition():
    # If we are in Domain Selection (level 1), and we send an invalid command like "PUSH_LEFT"
    # "PUSH_LEFT" is technically in VALID_COMMANDS but gives navigate_home which is a valid response,
    # however "JUMP" gives invalid command before it hits transition logic.
    # What if we send PULL when at level 2 in Python domain?
    # Python domain map: PUSH: YOUTUBE, PULL: CHROME, LEFT: NOTEPAD, RIGHT: GMAIL.
    # It has valid transitions. Let's just create an invalid transition condition by adding a mock state
    # where rule_router returns no_action.
    state_manager.update_state("default", {"current_level": 5, "active_domain": "INVALID"})
    response = client.post("/api/navigation/command", json={"command": "push"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["error"] == "invalid transition"

def test_navigation_reset():
    client.post("/api/navigation/command", json={"command": "push"})
    response = client.post("/api/navigation/reset")
    assert response.status_code == 200
    data = response.json()
    assert data["current_level"] == 1
    assert data["current_domain"] is None

def test_logging(caplog):
    with caplog.at_level(logging.INFO, logger="synaptimesh"):
        client.post("/api/navigation/command", json={"command": "push"})
        log_records = [record.message for record in caplog.records]
        assert "[Navigation] command=push" in log_records
        assert "[target_domain=PYTHON]" in log_records
        assert "[status=success]" in log_records

def test_duplicate_navigation_command():
    # Same command twice in a row shouldn't crash
    client.post("/api/navigation/command", json={"command": "push"})
    response = client.post("/api/navigation/command", json={"command": "push"})
    assert response.status_code == 200
