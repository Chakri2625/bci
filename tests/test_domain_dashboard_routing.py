import pytest
from fastapi.testclient import TestClient
from main import app
from core.state.state_manager import state_manager
from core.managers.command_lock_manager import command_lock_manager
from core.routing.rule_router import resolve_command

client = TestClient(app)

@pytest.fixture(autouse=True)
def cleanup_state_and_locks():
    state_manager.states.clear()
    command_lock_manager._locks.clear()
    yield
    command_lock_manager._locks.clear()


def test_level1_domain_resolutions():
    """Verify that level 1 commands resolve to the 4 canonical domains."""
    state = {"current_level": 1, "active_domain": None}
    
    res_py = resolve_command("PUSH", state)
    assert res_py["type"] == "transition"
    assert res_py["domain"] == "PYTHON"
    assert res_py["level"] == 2

    res_emb = resolve_command("PULL", state)
    assert res_emb["type"] == "transition"
    assert res_emb["domain"] == "EMBEDDED"
    assert res_emb["level"] == 2

    res_iot = resolve_command("LEFT", state)
    assert res_iot["type"] == "transition"
    assert res_iot["domain"] == "IOT"
    assert res_iot["level"] == 2

    res_aiml = resolve_command("RIGHT", state)
    assert res_aiml["type"] == "transition"
    assert res_aiml["domain"] == "AIML"
    assert res_aiml["level"] == 2


def test_domain_endpoints_health():
    """Verify all authoritative team dashboard routes return 200 OK."""
    routes = ["/", "/iot", "/embedded", "/embedded/car-control", "/aiml"]
    for route in routes:
        res = client.get(route)
        assert res.status_code == 200, f"Route {route} failed with status {res.status_code}"


def test_reset_navigation_via_query_param():
    """Verify that /?reset=1 resets the session back to Level 1 Domain Selection."""
    state_manager.update_state("default", {
        "current_level": 2,
        "active_domain": "IOT",
        "active_app": "LIGHT"
    })
    
    res = client.get("/?reset=1")
    assert res.status_code == 200
    st = state_manager.get_state("default")
    assert st["current_level"] == 1
    assert st["active_domain"] is None


def test_bci_command_domain_transitions():
    """Verify dispatching domain commands via /api/v1/bci/command returns resolved domain transitions."""
    # Reset lock and state
    command_lock_manager.reset_lock("default")
    state_manager.update_state("default", {"current_level": 1, "active_domain": None})
    
    # Send LEFT for IoT domain
    res = client.post("/api/v1/bci/command", json={"command": "left", "session_id": "default"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["resolved"]["domain"] == "IOT"
    assert data["state"]["active_domain"] == "IOT"
    assert data["state"]["current_level"] == 2
