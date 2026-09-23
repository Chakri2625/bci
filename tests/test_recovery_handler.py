import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from main import app
from core.state.state_manager import state_manager
from core.navigation.recovery_handler import recovery_handler, RecoveryResult

client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_state():
    state_manager.states.clear()


# ==============================================================================
# Unit Tests for RecoveryHandler Class
# ==============================================================================

def test_recovery_handler_rejected_command():
    # Setup state
    state_manager.update_state("default", {"current_level": 2, "active_domain": "PYTHON", "active_app": None})
    initial_state = dict(state_manager.get_state("default"))

    res = recovery_handler.handle_rejected_command("INVALID_CMD", "invalid command", "default")
    assert res.attempted is True
    assert res.status == "not_required"
    assert res.action == "none"
    assert res.error == "invalid command"
    
    # Verify state was not corrupted
    current_state = state_manager.get_state("default")
    assert current_state["current_level"] == initial_state["current_level"]
    assert current_state["active_domain"] == initial_state["active_domain"]


def test_recovery_handler_invalid_transition():
    # Setup valid state snapshot
    previous_state = {"current_level": 2, "active_domain": "PYTHON", "active_app": None}
    state_manager.update_state("default", {"current_level": 99, "active_domain": "CORRUPTED", "active_app": "BAD"})

    res = recovery_handler.handle_invalid_transition("PUSH", "invalid transition", previous_state, "default")
    assert res.attempted is True
    assert res.status == "recovered"
    assert res.action == "restore_previous_state"
    
    # Verify previous valid state was restored
    current_state = state_manager.get_state("default")
    assert current_state["current_level"] == 2
    assert current_state["active_domain"] == "PYTHON"
    assert current_state["active_app"] is None


def test_recovery_handler_execution_failure_with_snapshot():
    previous_state = {"current_level": 2, "active_domain": "EMBEDDED", "active_app": None}
    state_manager.update_state("default", {"current_level": 3, "active_domain": "EMBEDDED", "active_app": "RC_CAR"})

    res = recovery_handler.handle_execution_failure("PUSH", "Plugin crashed", previous_state, "default")
    assert res.attempted is True
    assert res.status == "recovered"
    assert res.action == "restore_previous_state"
    
    current_state = state_manager.get_state("default")
    assert current_state["current_level"] == 2
    assert current_state["active_domain"] == "EMBEDDED"
    assert current_state["active_app"] is None


def test_recovery_handler_execution_failure_fallback_navigate_back():
    # No snapshot provided, state at level 3 -> should navigate_back to level 2
    state_manager.update_state("default", {"current_level": 3, "active_domain": "PYTHON", "active_app": "YOUTUBE"})

    res = recovery_handler.handle_execution_failure("PUSH", "Plugin crashed", None, "default")
    assert res.attempted is True
    assert res.status == "recovered"
    assert res.action == "navigate_back"
    
    current_state = state_manager.get_state("default")
    assert current_state["current_level"] == 2
    assert current_state["active_app"] is None


def test_recovery_handler_execution_failure_fallback_navigate_home():
    # State at level 2 -> should navigate_back to level 1 Home
    state_manager.update_state("default", {"current_level": 2, "active_domain": "PYTHON", "active_app": None})

    res = recovery_handler.handle_execution_failure("PUSH", "Plugin crashed", None, "default")
    assert res.attempted is True
    assert res.status == "recovered"
    assert res.action == "navigate_back"
    
    current_state = state_manager.get_state("default")
    assert current_state["current_level"] == 1
    assert current_state["active_domain"] is None


def test_recovery_handler_handle_exception():
    previous_state = {"current_level": 1, "active_domain": None, "active_app": None}
    state_manager.update_state("default", {"current_level": 2, "active_domain": "AIML", "active_app": None})

    exc = RuntimeError("Hardware connection lost")
    res = recovery_handler.handle_exception("PUSH", exc, previous_state, "default")
    assert res.attempted is True
    assert res.status == "recovered"
    assert "Hardware connection lost" in res.error
    assert state_manager.get_state("default")["current_level"] == 1


def test_recovery_handler_handle_timeout():
    previous_state = {"current_level": 2, "active_domain": "IOT", "active_app": None}
    state_manager.update_state("default", {"current_level": 3, "active_domain": "IOT", "active_app": "SENSOR"})

    res = recovery_handler.handle_timeout("PUSH", 2.0, previous_state, "default")
    assert res.attempted is True
    assert res.status == "recovered"
    assert "timeout after 2.0s" in res.error
    assert state_manager.get_state("default")["current_level"] == 2


def test_recovery_handler_recover_to_safe_state():
    state_manager.update_state("default", {"current_level": 3, "active_domain": "PYTHON", "active_app": "GMAIL"})

    res = recovery_handler.recover_to_safe_state("default")
    assert res.attempted is True
    assert res.status == "recovered"
    assert res.action == "navigate_home"
    
    current_state = state_manager.get_state("default")
    assert current_state["current_level"] == 1
    assert current_state["active_domain"] is None
    assert current_state["active_app"] is None


# ==============================================================================
# Integration Tests: Path A (/api/navigation/command)
# ==============================================================================

def test_api_navigation_invalid_command_recovery():
    state_manager.update_state("default", {"current_level": 2, "active_domain": "PYTHON", "active_app": None})
    
    response = client.post("/api/navigation/command", json={"command": "FLY"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["error"] == "invalid command"
    assert data["recovery_attempted"] is True
    assert data["recovery_status"] == "not_required"
    assert data["recovery_action"] == "none"
    
    # State remains intact
    assert data["state"]["current_level"] == 2
    assert data["state"]["active_domain"] == "PYTHON"


def test_api_navigation_invalid_transition_recovery():
    # Corrupted / invalid level where router returns no_action
    state_manager.update_state("default", {"current_level": 5, "active_domain": "UNKNOWN"})
    
    response = client.post("/api/navigation/command", json={"command": "PUSH"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["error"] == "invalid transition"
    assert data["recovery_attempted"] is True
    assert data["recovery_status"] == "recovered"


# ==============================================================================
# Integration Tests: Path B (/api/v1/bci/command)
# ==============================================================================

def test_api_bci_invalid_transition_recovery():
    state_manager.update_state("default", {"current_level": 5, "active_domain": "UNKNOWN"})
    
    response = client.post("/api/v1/bci/command", json={"command": "PUSH"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "no_action"
    assert data["recovery_attempted"] is True
    assert data["recovery_status"] == "recovered"


def test_api_bci_execution_failure_recovery():
    state_manager.update_state("default", {"current_level": 3, "active_domain": "PYTHON", "active_app": "NOTEPAD"})
    
    with patch("core.communication.api_server.execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = {"status": "error", "message": "Failed to open notepad"}
        
        response = client.post("/api/v1/bci/command", json={"command": "PUSH"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        assert data["recovery_attempted"] is True
        assert data["recovery_status"] == "recovered"
        assert data["recovery_action"] == "restore_previous_state"
        assert data["state"]["current_level"] == 3
        assert data["state"]["active_app"] == "NOTEPAD"


def test_api_bci_exception_recovery():
    state_manager.update_state("default", {"current_level": 3, "active_domain": "PYTHON", "active_app": "NOTEPAD"})
    
    with patch("core.communication.api_server.execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.side_effect = RuntimeError("Plugin bridge crashed")
        
        response = client.post("/api/v1/bci/command", json={"command": "PUSH"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        assert "Plugin bridge crashed" in data["error"]
        assert data["recovery_attempted"] is True
        assert data["recovery_status"] == "recovered"
        assert data["recovery_action"] == "restore_previous_state"
