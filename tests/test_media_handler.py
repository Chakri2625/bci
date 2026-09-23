import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from plugin_sdk.interfaces.base_plugin import BasePlugin
from plugin_sdk.interfaces.media_plugin import MediaPluginInterface
from plugins.media.plugin import MediaManagerPlugin, MediaHandler
from plugins.media.providers.base_provider import BaseMediaProvider
from plugins.media.providers.youtube_provider import YouTubeProvider
from plugins.media.providers.jiosaavn_provider import JioSaavnProvider
from plugins.media.logger import media_logger
from core.state.state_manager import state_manager


class MockMediaProvider(BaseMediaProvider):
    provider_name = "MOCK_PROVIDER"

    def __init__(self, should_succeed=True):
        self.should_succeed = should_succeed
        self.last_action = None
        self.last_payload = None

    def get_supported_actions(self):
        return ["PLAY", "PAUSE", "TOGGLE_PLAY_PAUSE", "NEXT", "PREVIOUS", "SEARCH", "VOLUME_UP"]

    async def execute(self, action, payload=None):
        self.last_action = action
        self.last_payload = payload
        if self.should_succeed:
            return {
                "status": "SUCCESS",
                "success": True,
                "action": action,
                "message": f"Mock {action} executed successfully",
                "details": {"payload": payload},
            }
        else:
            return {
                "status": "FAILED",
                "success": False,
                "action": action,
                "error": "Mock provider error",
                "message": "Mock provider failed",
            }


@pytest.fixture(autouse=True)
def clean_state():
    state_manager.states.clear()
    if os.path.exists(media_logger.log_path):
        try:
            os.remove(media_logger.log_path)
        except Exception:
            pass
    media_logger._ensure_file_exists()
    yield
    state_manager.states.clear()


def test_media_plugin_interface_and_inheritance():
    """Verify MediaPluginInterface inherits from BasePlugin and MediaManagerPlugin conforms."""
    assert issubclass(MediaPluginInterface, BasePlugin)
    handler = MediaManagerPlugin()
    assert isinstance(handler, MediaPluginInterface)
    assert isinstance(handler, BasePlugin)
    assert handler.plugin_id == "media"


def test_provider_base_class_and_conformance():
    """Verify built-in providers inherit from BaseMediaProvider."""
    yt = YouTubeProvider()
    js = JioSaavnProvider()
    mock_p = MockMediaProvider()

    assert isinstance(yt, BaseMediaProvider)
    assert isinstance(js, BaseMediaProvider)
    assert isinstance(mock_p, BaseMediaProvider)
    assert yt.provider_name == "YOUTUBE"
    assert js.provider_name == "JIOSAAVN"


def test_dynamic_provider_registration():
    """Verify providers can be registered, retrieved, and unregistered dynamically."""
    handler = MediaManagerPlugin()
    mock_p = MockMediaProvider()

    handler.register_provider("CUSTOM_MUSIC", mock_p)
    assert handler.get_provider("CUSTOM_MUSIC") is mock_p
    assert "CUSTOM_MUSIC" in handler.get_supported_providers()

    handler.unregister_provider("CUSTOM_MUSIC")
    assert handler.get_provider("CUSTOM_MUSIC") is None


def test_bci_gesture_resolution():
    """Verify BCI commands (PUSH, PULL, LEFT, RIGHT) map to correct media actions."""
    handler = MediaManagerPlugin()
    mock_p = MockMediaProvider()
    handler.register_provider("TEST_APP", mock_p)

    payload = {"app": "TEST_APP", "session": "sess_1"}

    # PUSH -> PREVIOUS
    res_push = asyncio.run(handler.execute("PUSH", payload))
    assert res_push["status"] == "success"
    assert res_push["action"] == "PREVIOUS"
    assert mock_p.last_action == "PREVIOUS"

    # PULL -> NEXT
    res_pull = asyncio.run(handler.execute("PULL", payload))
    assert res_pull["status"] == "success"
    assert res_pull["action"] == "NEXT"
    assert mock_p.last_action == "NEXT"

    # LEFT -> TOGGLE_PLAY_PAUSE
    res_left = asyncio.run(handler.execute("LEFT", payload))
    assert res_left["status"] == "success"
    assert res_left["action"] == "TOGGLE_PLAY_PAUSE"
    assert mock_p.last_action == "TOGGLE_PLAY_PAUSE"

    # RIGHT -> SEARCH
    res_right = asyncio.run(handler.execute("RIGHT", payload))
    assert res_right["status"] == "success"
    assert res_right["action"] == "SEARCH"
    assert mock_p.last_action == "SEARCH"


def test_direct_media_action_passthrough():
    """Verify direct media actions (PLAY, PAUSE, VOLUME_UP, etc.) pass through directly."""
    handler = MediaManagerPlugin()
    mock_p = MockMediaProvider()
    handler.register_provider("TEST_APP", mock_p)

    payload = {"app": "TEST_APP", "session": "sess_2"}

    for act in ["PLAY", "PAUSE", "STOP", "RESUME", "VOLUME_UP", "VOLUME_DOWN", "MUTE"]:
        res = asyncio.run(handler.execute(act, payload))
        assert res["status"] == "success"
        assert res["action"] == act
        assert mock_p.last_action == act


def test_invalid_and_empty_command_validation():
    """Verify invalid or empty commands return structured error without throwing."""
    handler = MediaManagerPlugin()

    res_empty = asyncio.run(handler.execute("", {"app": "YOUTUBE"}))
    assert res_empty["status"] == "error"
    assert res_empty["success"] is False
    assert "non-empty" in res_empty["message"]

    res_none = asyncio.run(handler.execute(None, {}))
    assert res_none["status"] == "error"
    assert res_none["success"] is False


def test_provider_error_isolation():
    """Verify provider failures are cleanly captured and returned with error status."""
    handler = MediaManagerPlugin()
    failing_provider = MockMediaProvider(should_succeed=False)
    handler.register_provider("FAIL_APP", failing_provider)

    res = asyncio.run(handler.execute("PLAY", {"app": "FAIL_APP"}))
    assert res["status"] == "error"
    assert res["success"] is False
    assert "error" in res
    assert "Mock provider failed" in res["message"] or "Mock provider error" in res["error"]


def test_provider_exception_boundary():
    """Verify that unhandled exceptions inside a provider do not crash the handler."""
    handler = MediaManagerPlugin()
    exploding_provider = MagicMock(spec=BaseMediaProvider)
    exploding_provider.execute = AsyncMock(side_effect=RuntimeError("Subsystem crashed"))
    handler.register_provider("CRASH_APP", exploding_provider)

    res = asyncio.run(handler.execute("PLAY", {"app": "CRASH_APP"}))
    assert res["status"] == "error"
    assert res["success"] is False
    assert "Subsystem crashed" in res["error"]


def test_youtube_provider_integration_with_desktop():
    """Verify YouTubeProvider formats and delegates to desktop subplugin."""
    yt_provider = YouTubeProvider()
    mock_desktop_res = {"status": "success", "message": "Video playing"}

    with patch("plugins.media.providers.youtube_provider.execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_desktop_res
        res = asyncio.run(yt_provider.execute("TOGGLE_PLAY_PAUSE", {"app": "YOUTUBE"}))

        assert res["status"] == "SUCCESS"
        assert res["success"] is True
        assert res["action"] == "TOGGLE_PLAY_PAUSE"
        mock_exec.assert_called_once_with("desktop", "toggle_play_pause", {"app": "YOUTUBE"})


def test_activity_logger_integration():
    """Verify that successful and failed actions are logged to media_logger."""
    handler = MediaManagerPlugin()
    mock_p = MockMediaProvider(should_succeed=True)
    handler.register_provider("LOG_APP", mock_p)

    asyncio.run(handler.execute("LEFT", {"app": "LOG_APP", "session": "log_sess"}))

    log_data = media_logger._read_log()
    assert len(log_data["history"]) >= 1
    last_entry = log_data["history"][-1]
    assert last_entry["session_id"] == "log_sess"
    assert last_entry["action"] == "TOGGLE_PLAY_PAUSE"
    assert last_entry["status"] == "SUCCESS"
