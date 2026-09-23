import pytest
import asyncio
import os
import json
from unittest.mock import patch, MagicMock

# Import the core components
from core.routing.rule_router import resolve_command
from core.state.state_manager import state_manager
from core.orchestration.ecosystem_orchestrator import ecosystem_orchestrator
from core.plugin_manager.manager import load_plugins, get_plugin, execute, PLUGINS
from plugins.media.logger import media_logger

@pytest.fixture(autouse=True)
def setup_environment():
    # Setup
    PLUGINS.clear()
    state_manager.states.clear()
    
    # Load plugins (this will load media plugin and real desktop plugin)
    load_plugins()
    
    # Mock the desktop plugin execute function to avoid actual browser automation
    async def mock_execute(command, payload=None):
        if command in ["previous_video", "next_video", "toggle_play_pause", "search"]:
            return {"status": "success", "message": f"Mocked {command}"}
        return {"status": "error", "message": "Unknown command"}
        
    mock_desktop = MagicMock()
    mock_desktop.execute = mock_execute
    PLUGINS["desktop"] = mock_desktop
    
    # Clean up the test log file if it exists
    if os.path.exists(media_logger.log_path):
        os.remove(media_logger.log_path)
    media_logger._ensure_file_exists()

    yield
    
    # Teardown
    PLUGINS.clear()

def test_routing_youtube_to_media():
    """Test that DynamicRouter routes YouTube commands to MEDIA domain"""
    state = {"current_level": 3, "active_domain": "PYTHON", "active_app": "YOUTUBE"}
    
    result_push = resolve_command("PUSH", state)
    assert result_push["domain"] == "MEDIA"
    assert result_push["action"] == "PUSH"
    
    result_left = resolve_command("LEFT", state)
    assert result_left["domain"] == "MEDIA"
    assert result_left["action"] == "LEFT"

def test_media_manager_youtube_integration():
    """Test full integration from Media Manager to YouTube provider"""
    media_plugin = get_plugin("media")
    assert media_plugin is not None
    
    # Setup state
    state_manager.update_state("test_session", {
        "current_level": 3,
        "active_domain": "PYTHON",
        "active_app": "YOUTUBE"
    })
    
    payload = {
        "session": "test_session",
        "domain": "MEDIA", # as resolved by router
        "app": "YOUTUBE"
    }
    
    # 1. Test LEFT -> TOGGLE_PLAY_PAUSE
    result = asyncio.run(media_plugin.execute("LEFT", payload))
    
    print("Test LEFT result:", result)
    assert result["success"] is True
    assert result["domain"] == "MEDIA"
    assert result["application"] == "YOUTUBE"
    assert result["action"] == "TOGGLE_PLAY_PAUSE"
    assert "Mocked toggle_play_pause" in result["message"]
    
    # 2. Test RIGHT -> SEARCH
    result2 = asyncio.run(media_plugin.execute("RIGHT", payload))
    assert result2["action"] == "SEARCH"
    assert result2["success"] is True
    
    # Check if logs were created
    log_data = media_logger._read_log()
    assert len(log_data["history"]) == 2
    assert log_data["history"][0]["action"] == "TOGGLE_PLAY_PAUSE"
    assert log_data["history"][1]["action"] == "SEARCH"

def test_media_manager_jiosaavn_integration():
    """Test full integration from Media Manager to JioSaavn provider"""
    media_plugin = get_plugin("media")
    assert media_plugin is not None
    
    # Setup state
    state_manager.update_state("test_session_aiml", {
        "current_level": 3,
        "active_domain": "AIML",
        "active_app": "JIOSAAVN"
    })
    
    payload = {
        "session": "test_session_aiml",
        "domain": "MEDIA",
        "app": "JIOSAAVN"
    }
    
    # Test PLAY -> TOGGLE_PLAY_PAUSE mapping
    result = asyncio.run(media_plugin.execute("LEFT", payload))
    
    assert result["success"] is False  # Controlled failure since not implemented
    assert result["domain"] == "MEDIA"
    assert result["application"] == "JIOSAAVN"
    assert result["action"] == "TOGGLE_PLAY_PAUSE"
    assert "error" in result
