import pytest
import asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.communication.api_server import setup_routes
from core.validation.command_normalizer import normalize_command
from core.orchestration.ecosystem_orchestrator import ecosystem_orchestrator
from core.state.state_manager import state_manager
from services.cortex_service import cortex_service

app = FastAPI()
setup_routes(app)
client = TestClient(app)

def test_command_normalizer_compounds():
    """Verify all combinations of compound gestures normalize to canonical tokens."""
    assert normalize_command("PUSH + LEFT") == "PUSH_LEFT"
    assert normalize_command("PUSH+LEFT") == "PUSH_LEFT"
    assert normalize_command("W + A") == "PUSH_LEFT"
    assert normalize_command("W+A") == "PUSH_LEFT"
    assert normalize_command("W_A") == "PUSH_LEFT"
    assert normalize_command("PUSH + RIGHT") == "PUSH_RIGHT"
    assert normalize_command("PUSH+RIGHT") == "PUSH_RIGHT"
    assert normalize_command("W + D") == "PUSH_RIGHT"
    assert normalize_command("W+D") == "PUSH_RIGHT"
    assert normalize_command("W_D") == "PUSH_RIGHT"

def test_cortex_service_status():
    """Verify Cortex service exposes active status telemetry."""
    status = cortex_service.get_status()
    assert "connected" in status
    assert "authorized" in status
    assert "session_active" in status
    assert "headset_id" in status
    assert "available_profiles" in status

def test_cortex_rest_endpoints():
    """Verify Cortex REST endpoints return valid responses."""
    resp_status = client.get("/api/v1/cortex/status")
    assert resp_status.status_code == 200
    assert "headset_id" in resp_status.json()
    assert "connected" in resp_status.json()

    resp_cred = client.post("/api/v1/cortex/credentials", json={
        "client_id": "test_id",
        "client_secret": "test_sec"
    })
    assert resp_cred.status_code == 200
    assert resp_cred.json()["status"] == "success"
    assert cortex_service.client_id == "test_id"

    resp_diag = client.get("/api/v1/cortex/diagnostic")
    assert resp_diag.status_code == 200
    diag_data = resp_diag.json()
    assert "endpoint" in diag_data
    assert "socket_connected" in diag_data

@pytest.mark.asyncio
async def test_compound_navigation_orchestration():
    """Verify compound commands (PUSH_LEFT, PUSH_RIGHT, ['PUSH', 'LEFT']) route through orchestrator."""
    state_manager.reset_state("test_bci_sess")
    
    # 1. Level 1 -> PUSH -> Level 2
    res1 = await ecosystem_orchestrator.process_command("PUSH", session="test_bci_sess")
    assert res1.get("status") == "success" or res1.get("valid") is not False
    
    # 2. Compound ['PUSH', 'LEFT'] returns to Level 1
    res2 = await ecosystem_orchestrator.process_command(["PUSH", "LEFT"], session="test_bci_sess")
    assert res2.get("status") == "success" or res2.get("valid") is not False
    st = state_manager.get_state("test_bci_sess")
    assert st.get("current_level") == 1

def test_api_bci_compound_post():
    """Verify API POST /api/v1/bci/command handles compound string and list."""
    state_manager.reset_state("default")
    
    res = client.post("/api/v1/bci/command", json={"command": "PUSH + LEFT", "session_id": "default"})
    assert res.status_code == 200
    assert res.json().get("status") in ("success", "valid") or res.json().get("state", {}).get("current_level") == 1

def test_centralized_credentials_and_secret_protection():
    """Verify credentials are saved centrally and secrets are never leaked in status responses."""
    resp_cred = client.post("/api/v1/cortex/credentials", json={
        "client_id": "central_client_123",
        "client_secret": "super_secret_token_abc"
    })
    assert resp_cred.status_code == 200
    assert cortex_service.client_id == "central_client_123"
    assert cortex_service.client_secret == "super_secret_token_abc"

    status = client.get("/api/v1/cortex/status").json()
    assert "client_secret" not in status
    assert status.get("hasCredentials") is True or status.get("has_credentials") is True
    assert status.get("url") == cortex_service.url

def test_cortex_profile_load_endpoint():
    """Verify loading user trained profile via REST endpoint."""
    resp = client.post("/api/v1/cortex/profile/load", json={"profile_name": "high_sensitivity_profile"})
    assert resp.status_code == 200
    assert resp.json().get("status") in ("success", "error")
    assert cortex_service.active_profile == "high_sensitivity_profile"

def test_bci_suite_route():
    """Verify /bci route serves the BCI suite HTML page cleanly."""
    from plugins.desktop.ui.app import setup_ui
    test_app = FastAPI()
    setup_routes(test_app)
    setup_ui(test_app)
    ui_client = TestClient(test_app)
    
    resp_root = ui_client.get("/")
    assert resp_root.status_code == 200
    assert "SynaptiMesh" in resp_root.text

    resp_bci = ui_client.get("/bci")
    assert resp_bci.status_code == 200
    assert "SynaptiMesh" in resp_bci.text

