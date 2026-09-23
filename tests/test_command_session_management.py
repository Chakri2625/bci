import pytest
import asyncio
import uuid
from fastapi.testclient import TestClient
from fastapi import FastAPI
from core.communication.api_server import router
from core.state.state_manager import state_manager
from core.orchestration.ecosystem_orchestrator import ecosystem_orchestrator

app = FastAPI()
app.include_router(router)
client = TestClient(app)

@pytest.fixture(autouse=True)
def clean_state():
    # Clear state before each test
    state_manager.states.clear()
    yield

def test_orchestrator_generates_command_id_if_missing():
    # Test A: Command ID generated when not supplied
    session = "test_session_A"
    
    # Process a command without providing command_id
    asyncio.run(ecosystem_orchestrator.process_command("PUSH", session=session))
    
    state = state_manager.get_state(session)
    assert "commands" in state
    assert len(state["commands"]) == 1
    
    # The single key in commands should be a UUID-like string (or just dynamically generated)
    command_ids = list(state["commands"].keys())
    assert command_ids[0] is not None
    assert state["commands"][command_ids[0]]["command"] == "PUSH"

def test_identical_commands_different_ids():
    # Test B: Two identical commands receive different command IDs
    session = "test_session_B"
    
    asyncio.run(ecosystem_orchestrator.process_command("PUSH", session=session))
    asyncio.run(ecosystem_orchestrator.process_command("PUSH", session=session))
    
    state = state_manager.get_state(session)
    assert len(state["commands"]) == 2
    
    command_ids = list(state["commands"].keys())
    assert command_ids[0] != command_ids[1]
    
    # Both are PUSH commands
    assert state["commands"][command_ids[0]]["command"] == "PUSH"
    assert state["commands"][command_ids[1]]["command"] == "PUSH"

def test_api_session_generation():
    # Test C & G: Session ID generated when no session supplied via API
    # Since we can't easily capture the randomly generated UUID from the API response directly,
    # we can check that a new session was created in state_manager that isn't 'default'
    initial_sessions = set(state_manager.states.keys())
    
    response = client.post("/api/v1/bci/command", json={"command": "PUSH"})
    assert response.status_code == 200
    
    current_sessions = set(state_manager.states.keys())
    new_sessions = current_sessions - initial_sessions
    
    assert len(new_sessions) == 1
    new_session_id = new_sessions.pop()
    
    # Ensure it's not "default"
    assert new_session_id != "default"
    
    state = state_manager.get_state(new_session_id)
    assert len(state["commands"]) == 1

def test_api_legacy_session_compatibility():
    # Test D & G: Multiple commands using the same session ID remain associated
    session = "legacy_session_123"
    
    client.post(f"/api/v1/bci/command?session={session}", json={"command": "PUSH"})
    client.post(f"/api/v1/bci/command?session={session}", json={"command": "LEFT"})
    
    state = state_manager.get_state(session)
    assert len(state["commands"]) == 2
    
    cmds = [cmd_info["command"] for cmd_info in state["commands"].values()]
    assert "PUSH" in cmds
    assert "LEFT" in cmds

def test_api_explicit_session_and_command_id():
    # Test explicitly passing IDs
    session_id = "explicit_sess_001"
    command_id = "explicit_cmd_001"
    
    response = client.post(
        "/api/v1/bci/command", 
        json={
            "command": "RIGHT",
            "session_id": session_id,
            "command_id": command_id
        }
    )
    assert response.status_code == 200
    
    state = state_manager.get_state(session_id)
    assert command_id in state["commands"]
    assert state["commands"][command_id]["command"] == "RIGHT"
    assert state["commands"][command_id]["status"] == "RECEIVED"

def test_command_history_behavior_preserved():
    # Test F: Existing command history behavior remains functional
    session = "test_history_session"
    
    for i in range(25):
        asyncio.run(ecosystem_orchestrator.process_command(f"CMD_{i}", session=session))
        
    state = state_manager.get_state(session)
    
    # History should be capped at 20
    assert len(state["command_history"]) == 20
    assert state["command_history"][-1] == "CMD_24"
    assert state["command_history"][0] == "CMD_5"
    
    # All 25 commands should have generated unique command IDs in the commands dict
    assert len(state["commands"]) == 25

def test_parallel_commands_generate_unique_ids():
    # Verify that parallel commands (list of strings) generate unique IDs per command
    session_id = "parallel_session"
    
    response = client.post(
        "/api/v1/bci/command", 
        json={
            "commands": ["PUSH", "LEFT", "RIGHT"],
            "session_id": session_id
        }
    )
    assert response.status_code == 200
    
    state = state_manager.get_state(session_id)
    assert len(state["commands"]) == 3
    
    cmds = [cmd_info["command"] for cmd_info in state["commands"].values()]
    assert "PUSH" in cmds
    assert "LEFT" in cmds
    assert "RIGHT" in cmds
