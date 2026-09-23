"""
End-to-End Integration Tests for Day 5 (Member 4 & Member 5)
Verifies:
1. Media Execution Service integrated into Media Plugin
2. Command Service Mapper routing cross-domain commands
3. End-to-end BCI command execution via Ecosystem Orchestrator
4. Preserved metadata and telemetry lifecycle
"""

import pytest
import asyncio
from unittest.mock import MagicMock, patch

from core.routing.rule_router import resolve_command
from core.state.state_manager import state_manager
from core.orchestration.ecosystem_orchestrator import ecosystem_orchestrator
from core.plugin_manager.manager import load_plugins, get_plugin, PLUGINS
from services.media_execution_service import get_media_execution_service
from services.command_service_mapper import get_command_service_mapper


@pytest.fixture(autouse=True)
def setup_integration_env():
    PLUGINS.clear()
    state_manager.states.clear()
    load_plugins()

    # Mock desktop actions to prevent physical OS window actions during automated testing
    async def mock_desktop_execute(command, payload=None):
        return {"status": "success", "message": f"Mocked desktop {command}"}

    mock_desktop = MagicMock()
    mock_desktop.execute = mock_desktop_execute
    PLUGINS["desktop"] = mock_desktop

    yield

    PLUGINS.clear()
    state_manager.states.clear()


def test_end_to_end_media_bci_flow():
    """Test full BCI flow: BCI Command -> Router -> Media Plugin -> MediaExecutionService -> Response."""
    # 1. Setup session in MEDIA domain / YOUTUBE app
    session_id = "day5_integration_sess"
    state_manager.update_state(session_id, {
        "current_level": 3,
        "active_domain": "PYTHON",
        "active_app": "YOUTUBE",
    })

    # 2. Process BCI command 'LEFT' (maps to TOGGLE_PLAY_PAUSE for YOUTUBE)
    result = asyncio.run(ecosystem_orchestrator.process_command("LEFT", session=session_id))

    assert result["status"] == "success"
    assert result["resolved"]["domain"] == "MEDIA"
    assert result["resolved"]["app"] == "YOUTUBE"
    assert result["executed"] is True


def test_mapper_and_media_service_integration():
    """Test CommandServiceMapper dispatching directly to MediaExecutionService."""
    mapper = get_command_service_mapper()
    media_svc = get_media_execution_service()
    mapper.register_service("MEDIA", media_svc)

    with patch.object(media_svc, "_os_key_press", return_value=True):
        res = mapper.map_and_execute(
            command_id="day5_cmd_001",
            domain="MEDIA",
            action="VOLUME_UP",
            parameters={"step": 15},
            priority=1,
            session_id="integration_user",
        )

        assert res["command_id"] == "day5_cmd_001"
        assert res["domain"] == "MEDIA"
        assert res["success"] is True
        assert res["status"] == "SUCCESS"
        assert res["result"]["details"]["step"] == 15
        assert res["metadata"]["session_id"] == "integration_user"


def test_mapper_cross_domain_dispatch():
    """Test mapper handling multi-domain commands sequentially with metadata retention."""
    mapper = get_command_service_mapper()
    
    # Mock services
    mock_iot = MagicMock()
    mock_iot.execute.return_value = {"status": "success", "device_id": "FAN_01", "state": "ON"}
    
    mock_media = MagicMock()
    mock_media.execute_command.return_value = {"status": "SUCCESS", "success": True, "action": "PLAY"}
    
    mock_desktop = MagicMock()
    mock_desktop.execute.return_value = {"status": "success", "app": "notepad"}

    mapper.register_service("IOT", mock_iot)
    mapper.register_service("MEDIA", mock_media)
    mapper.register_service("DESKTOP", mock_desktop)

    # 1. Execute IoT
    r_iot = mapper.map_and_execute(command_id="cmd_iot_1", domain="IOT", action="TOGGLE", parameters={"device_id": "FAN_01"})
    assert r_iot["success"] is True
    assert r_iot["domain"] == "IOT"

    # 2. Execute Media
    r_med = mapper.map_and_execute(command_id="cmd_med_2", domain="MEDIA", action="PLAY", parameters={"query": "Jazz"})
    assert r_med["success"] is True
    assert r_med["domain"] == "MEDIA"

    # 3. Execute Desktop
    r_dsk = mapper.map_and_execute(command_id="cmd_dsk_3", domain="DESKTOP", action="open_app", parameters={"app": "notepad"})
    assert r_dsk["success"] is True
    assert r_dsk["domain"] == "DESKTOP"

    # Verify history
    history = mapper.get_history(limit=5)
    history_domains = [h["domain"] for h in history]
    assert "IOT" in history_domains
    assert "MEDIA" in history_domains
    assert "DESKTOP" in history_domains
