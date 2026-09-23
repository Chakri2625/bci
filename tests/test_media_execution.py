"""
Tests for Media Execution Service (Member 4 - Day 5 Implementation)
Verifies all media execution operations, lifecycle status tracking,
parameter validation, and standardized responses.
"""

import pytest
from unittest.mock import MagicMock, patch

from services.media_execution_service import (
    MediaExecutionService,
    MediaExecutionStatus,
    MediaAction,
    MediaExecutionContext,
    get_media_execution_service,
)


@pytest.fixture
def media_service():
    """Create a fresh MediaExecutionService instance for testing."""
    return MediaExecutionService()


def test_media_service_initialization(media_service):
    """Verify service initializes with supported actions and providers."""
    assert media_service is not None
    supported = media_service.get_supported_actions()
    assert "PLAY" in supported
    assert "PAUSE" in supported
    assert "STOP" in supported
    assert "TOGGLE_PLAY_PAUSE" in supported
    assert "NEXT_TRACK" in supported
    assert "PREVIOUS_TRACK" in supported
    assert "VOLUME_UP" in supported
    assert "VOLUME_DOWN" in supported
    assert "MUTE" in supported
    assert "SEARCH" in supported
    assert "APP_CONTROL" in supported


def test_play_execution(media_service):
    """Test play operation execution."""
    with patch.object(media_service, "_os_key_press", return_value=True):
        res = media_service.play(query="Rock", app="YOUTUBE")
        assert res["success"] is True
        assert res["action"] == "PLAY"
        assert res["status"] == "SUCCESS"
        assert "command_id" in res
        assert "execution_time_ms" in res
        assert res["metadata"]["app"] == "YOUTUBE"


def test_pause_and_stop_execution(media_service):
    """Test pause and stop operations."""
    with patch.object(media_service, "_os_key_press", return_value=True):
        res_pause = media_service.pause()
        assert res_pause["success"] is True
        assert res_pause["action"] == "PAUSE"
        assert res_pause["status"] == "SUCCESS"

        res_stop = media_service.stop()
        assert res_stop["success"] is True
        assert res_stop["action"] == "STOP"
        assert res_stop["status"] == "SUCCESS"


def test_toggle_play_pause(media_service):
    """Test toggle play/pause operation."""
    with patch.object(media_service, "_os_key_press", return_value=True):
        res = media_service.toggle_play_pause()
        assert res["success"] is True
        assert res["action"] == "TOGGLE_PLAY_PAUSE"
        assert res["status"] == "SUCCESS"


def test_next_and_previous_track(media_service):
    """Test track navigation."""
    with patch.object(media_service, "_os_key_press", return_value=True):
        res_next = media_service.next_track()
        assert res_next["success"] is True
        assert res_next["action"] == "NEXT_TRACK"

        res_prev = media_service.previous_track()
        assert res_prev["success"] is True
        assert res_prev["action"] == "PREVIOUS_TRACK"


def test_volume_controls(media_service):
    """Test volume adjustment operations."""
    with patch.object(media_service, "_os_key_press", return_value=True):
        # Step increase
        res_up = media_service.volume_increase(step=10)
        assert res_up["success"] is True
        assert res_up["action"] == "VOLUME_UP"
        assert res_up["details"]["step"] == 10

        # Step decrease
        res_down = media_service.volume_decrease(step=5)
        assert res_down["success"] is True
        assert res_down["action"] == "VOLUME_DOWN"
        assert res_down["details"]["step"] == 5

        # Set specific level
        res_set = media_service.set_volume(level=75)
        assert res_set["success"] is True
        assert res_set["action"] == "SET_VOLUME"
        assert res_set["details"]["level"] == 75

        # Mute / Unmute
        res_mute = media_service.mute()
        assert res_mute["success"] is True
        assert res_mute["action"] == "MUTE"

        res_unmute = media_service.unmute()
        assert res_unmute["success"] is True
        assert res_unmute["action"] == "UNMUTE"


def test_search_media(media_service):
    """Test media search dispatch."""
    mock_provider = MagicMock()
    # Mock synchronous return or execution
    media_service._providers["YOUTUBE"] = mock_provider
    with patch("webbrowser.open", return_value=True):
        res = media_service.search(query="Taylor Swift", app="YOUTUBE")
        assert res["success"] is True
        assert res["action"] == "SEARCH"
        assert res["details"]["query"] == "Taylor Swift"


def test_app_control(media_service):
    """Test app launch and focus control."""
    with patch("webbrowser.open", return_value=True):
        res = media_service.app_control(app_name="YOUTUBE", action="OPEN")
        assert res["success"] is True
        assert res["action"] == "APP_CONTROL"
        assert res["details"]["app_name"] == "YOUTUBE"


def test_generic_execute_command(media_service):
    """Test dispatch via generic execute_command router."""
    with patch.object(media_service, "_os_key_press", return_value=True):
        res = media_service.execute_command(
            action="volume_increase",
            payload={"step": 8, "session": "test_sess"},
            command_id="cmd_vol_100",
        )
        assert res["success"] is True
        assert res["command_id"] == "cmd_vol_100"
        assert res["action"] in ["VOLUME_UP", "VOLUME_INCREASE"]
        assert res["status"] == "SUCCESS"


def test_unsupported_action_handling(media_service):
    """Test error handling and isolation for unsupported actions."""
    res = media_service.execute_command(
        action="FLY_TO_MARS",
        payload={},
        command_id="cmd_invalid_999",
    )
    assert res["success"] is False
    assert res["status"] == "FAILED"
    assert res["command_id"] == "cmd_invalid_999"
    assert "Unsupported media action" in res["error"]


def test_error_isolation_on_exception(media_service):
    """Test that unexpected exceptions during execution are caught and wrapped cleanly."""
    with patch.object(media_service, "_exec_play", side_effect=RuntimeError("Audio hardware crashed")):
        res = media_service.execute_command(
            action="PLAY",
            payload={},
            command_id="cmd_crash_01",
        )
        assert res["success"] is False
        assert res["status"] == "FAILED"
        assert res["command_id"] == "cmd_crash_01"
        assert "Audio hardware crashed" in res["error"]


def test_history_and_singleton():
    """Test telemetry history recording and singleton getter."""
    svc = get_media_execution_service()
    with patch.object(svc, "_os_key_press", return_value=True):
        svc.pause()
        svc.resume()

    history = svc.get_history(limit=5)
    assert len(history) >= 2
    assert history[-1]["action"] in ["RESUME", "PLAY"]
