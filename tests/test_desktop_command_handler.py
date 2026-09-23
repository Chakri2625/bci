import pytest
from unittest.mock import AsyncMock, MagicMock
from plugin_sdk.interfaces.desktop_plugin import DesktopPluginInterface
from plugins.desktop.plugin import DesktopPlugin, DesktopCommandHandler


class MockSubplugin(DesktopPluginInterface):
    """Deterministic mock subplugin that mirrors existing subplugin behavior."""

    def __init__(self, plugin_id: str, commands: list):
        self.plugin_id = plugin_id
        self.COMMANDS = commands
        self.execute = AsyncMock(
            return_value={"status": "success", "message": f"{plugin_id}: Executed successfully"}
        )
        self.get_widget = MagicMock(return_value={"widget_id": f"{plugin_id}_widget"})


@pytest.fixture
def mock_subplugins():
    """Create isolated mock subplugins with the EXACT commands from subplugin definitions."""
    return {
        "chrome": MockSubplugin(
            "chrome",
            ["open_predefined_article", "scroll_up", "scroll_down", "open_search_bar", "close_app"],
        ),
        "youtube": MockSubplugin(
            "youtube",
            ["previous_video", "next_video", "toggle_play_pause", "search", "close_app", "volume_up", "volume_down"],
        ),
        "notepad": MockSubplugin(
            "notepad",
            ["open_notepad", "save_file", "close_app"],
        ),
        "email": MockSubplugin(
            "email",
            ["compose_email", "send_email", "close_app"],
        ),
    }


@pytest.fixture
def handler(mock_subplugins):
    """Return a DesktopPlugin instance initialized with deterministic mock subplugins."""
    return DesktopPlugin(subplugins=mock_subplugins)


# 1. Valid Chrome command routes correctly
@pytest.mark.asyncio
async def test_valid_chrome_command_routes_correctly(handler, mock_subplugins):
    payload = {"domain": "DESKTOP", "app": "CHROME"}
    res = await handler.execute("open_search_bar", payload)

    assert res["status"] == "success"
    assert res["app"] == "CHROME"
    assert res["command"] == "open_search_bar"
    mock_subplugins["chrome"].execute.assert_awaited_once_with("open_search_bar", payload)


# 2. Valid YouTube command routes correctly
@pytest.mark.asyncio
async def test_valid_youtube_command_routes_correctly(handler, mock_subplugins):
    payload = {"domain": "PYTHON", "app": "YOUTUBE"}
    res = await handler.execute("toggle_play_pause", payload)

    assert res["status"] == "success"
    assert res["app"] == "YOUTUBE"
    assert res["command"] == "toggle_play_pause"
    mock_subplugins["youtube"].execute.assert_awaited_once_with("toggle_play_pause", payload)


# 3. Valid Notepad command routes correctly
@pytest.mark.asyncio
async def test_valid_notepad_command_routes_correctly(handler, mock_subplugins):
    payload = {"domain": "DESKTOP", "app": "NOTEPAD"}
    res = await handler.execute("open_notepad", payload)

    assert res["status"] == "success"
    assert res["app"] == "NOTEPAD"
    assert res["command"] == "open_notepad"
    mock_subplugins["notepad"].execute.assert_awaited_once_with("open_notepad", payload)


# 4. Valid Gmail/Email command routes correctly
@pytest.mark.asyncio
async def test_valid_gmail_and_email_routes_correctly(handler, mock_subplugins):
    # Test GMAIL routing
    payload_gmail = {"domain": "DESKTOP", "app": "GMAIL"}
    res_gmail = await handler.execute("compose_email", payload_gmail)
    assert res_gmail["status"] == "success"
    assert res_gmail["app"] == "GMAIL"
    assert res_gmail["command"] == "compose_email"
    mock_subplugins["email"].execute.assert_awaited_with("compose_email", payload_gmail)

    # Test EMAIL routing
    payload_email = {"domain": "DESKTOP", "app": "EMAIL"}
    res_email = await handler.execute("send_email", payload_email)
    assert res_email["status"] == "success"
    assert res_email["app"] == "EMAIL"
    assert res_email["command"] == "send_email"
    mock_subplugins["email"].execute.assert_awaited_with("send_email", payload_email)


# 5. Missing payload returns structured error
@pytest.mark.asyncio
async def test_missing_payload_error(handler):
    res = await handler.execute("open_search_bar", None)

    assert res["status"] == "error"
    assert res["app"] is None
    assert res["command"] == "open_search_bar"
    assert "Payload is required" in res["message"]


# 6. Payload is not a dictionary returns structured error
@pytest.mark.asyncio
async def test_payload_not_dictionary_error(handler):
    res_str = await handler.execute("open_search_bar", "invalid_string_payload")
    assert res_str["status"] == "error"
    assert "Payload must be a dictionary" in res_str["message"]

    res_list = await handler.execute("open_search_bar", ["item1", "item2"])
    assert res_list["status"] == "error"
    assert "Payload must be a dictionary" in res_list["message"]


# 7. Missing app in payload returns structured error
@pytest.mark.asyncio
async def test_missing_app_in_payload_error(handler):
    res_missing = await handler.execute("open_search_bar", {"domain": "DESKTOP"})
    assert res_missing["status"] == "error"
    assert "Payload missing app info" in res_missing["message"]

    res_empty_app = await handler.execute("open_search_bar", {"domain": "DESKTOP", "app": "   "})
    assert res_empty_app["status"] == "error"
    assert "must be a non-empty string" in res_empty_app["message"]

    res_non_str_app = await handler.execute("open_search_bar", {"domain": "DESKTOP", "app": 12345})
    assert res_non_str_app["status"] == "error"
    assert "must be a non-empty string" in res_non_str_app["message"]


# 8. Unsupported application returns clear error
@pytest.mark.asyncio
async def test_unsupported_application_error(handler):
    payload = {"app": "SPOTIFY"}
    res = await handler.execute("play", payload)

    assert res["status"] == "error"
    assert res["app"] == "SPOTIFY"
    assert "unsupported or not registered" in res["message"]


# 9. Missing registered subplugin returns clear error
@pytest.mark.asyncio
async def test_missing_registered_subplugin_error(handler, mock_subplugins):
    # Remove chrome from loaded subplugins
    del mock_subplugins["chrome"]

    payload = {"app": "CHROME"}
    res = await handler.execute("open_search_bar", payload)

    assert res["status"] == "error"
    assert res["app"] == "CHROME"
    assert "Subplugin for CHROME not found" in res["message"]


# 10. Unknown command returns clear error before forwarding
@pytest.mark.asyncio
async def test_unknown_command_rejected_before_forwarding(handler, mock_subplugins):
    payload = {"app": "CHROME"}
    res = await handler.execute("non_existent_command", payload)

    assert res["status"] == "error"
    assert res["app"] == "CHROME"
    assert res["command"] == "non_existent_command"
    assert "Unknown or unsupported command" in res["message"]
    # Ensure it was NOT forwarded to subplugin
    mock_subplugins["chrome"].execute.assert_not_awaited()


# 11. Subplugin execution failure caught safely without crashing Master Hub
@pytest.mark.asyncio
async def test_subplugin_execution_exception_handled_safely(handler, mock_subplugins):
    mock_subplugins["chrome"].execute.side_effect = RuntimeError("Selenium driver crashed unexpectedly")

    payload = {"app": "CHROME"}
    res = await handler.execute("scroll_down", payload)

    assert res["status"] == "error"
    assert res["app"] == "CHROME"
    assert res["command"] == "scroll_down"
    assert "Subplugin execution error" in res["message"]
    assert "Selenium driver crashed unexpectedly" in res["message"]


# 12. Successful result structure conformance
@pytest.mark.asyncio
async def test_successful_result_structure(handler, mock_subplugins):
    mock_subplugins["youtube"].execute.return_value = {
        "status": "success",
        "message": "YouTube: Video paused",
        "custom_metric": 42,
    }

    payload = {"app": "YOUTUBE"}
    res = await handler.execute("toggle_play_pause", payload)

    assert res["status"] == "success"
    assert res["app"] == "YOUTUBE"
    assert res["command"] == "toggle_play_pause"
    assert res["message"] == "YouTube: Video paused"
    assert "result" in res
    assert res["custom_metric"] == 42


# 13. Case-insensitive application normalization
@pytest.mark.asyncio
async def test_case_insensitive_app_normalization(handler, mock_subplugins):
    for raw_app in ["chrome", "Chrome", "CHROME", "  chrome  "]:
        mock_subplugins["chrome"].execute.reset_mock()
        payload = {"app": raw_app}
        res = await handler.execute("close_app", payload)

        assert res["status"] == "success"
        assert res["command"] == "close_app"
        mock_subplugins["chrome"].execute.assert_awaited_once()


# 14. Special command get_widgets works
@pytest.mark.asyncio
async def test_get_widgets_special_command(handler):
    res = await handler.execute("get_widgets")

    assert res["status"] == "success"
    assert "widgets" in res
    assert len(res["widgets"]) == 4


# 15. Invalid command string validation
@pytest.mark.asyncio
async def test_invalid_command_string(handler):
    for invalid_cmd in ["", "   ", None, 1234]:
        res = await handler.execute(invalid_cmd, {"app": "CHROME"})
        assert res["status"] == "error"
        assert "Command must be a non-empty string" in res["message"]


# 16. Subplugin returning error status is preserved
@pytest.mark.asyncio
async def test_subplugin_returning_error_status(handler, mock_subplugins):
    mock_subplugins["notepad"].execute.return_value = {
        "status": "error",
        "message": "Notepad is not open",
    }

    payload = {"app": "NOTEPAD"}
    res = await handler.execute("save_file", payload)

    assert res["status"] == "error"
    assert res["app"] == "NOTEPAD"
    assert res["command"] == "save_file"
    assert res["message"] == "Notepad is not open"


# 17. Class alias verification
def test_desktop_command_handler_alias():
    assert DesktopCommandHandler is DesktopPlugin


# 18. COMMAND card appears only once per command ID
@pytest.mark.asyncio
async def test_command_card_appears_only_once_per_command(handler, mock_subplugins, monkeypatch):
    logged_cards = []
    monkeypatch.setattr("plugins.desktop.plugin._log_card", lambda card: logged_cards.append(card))

    payload = {"app": "YOUTUBE", "command_id": "CMD-2001"}
    await handler.execute("toggle_play_pause", payload)
    await handler.execute("toggle_play_pause", payload)

    # Count how many COMMAND and RESULT cards were logged for CMD-2001
    command_cards = [c for c in logged_cards if "COMMAND" in c and "CMD-2001" in c]
    result_cards = [c for c in logged_cards if "RESULT" in c and "CMD-2001" in c]

    assert len(command_cards) == 1, f"COMMAND card should appear only once, found {len(command_cards)}"
    assert len(result_cards) == 2, f"RESULT card should appear for each execution finish, found {len(result_cards)}"


# 19. RESULT card displays SUCCESS/FAILED, Execution: COMPLETE/FAILED, and final result
@pytest.mark.asyncio
async def test_result_card_shows_status_execution_and_result(handler, mock_subplugins, monkeypatch):
    logged_cards = []
    monkeypatch.setattr("plugins.desktop.plugin._log_card", lambda card: logged_cards.append(card))

    # 19a. Success case
    mock_subplugins["youtube"].execute.return_value = {
        "status": "success",
        "message": "Song is playing",
    }
    payload_success = {"app": "YOUTUBE", "command_id": "CMD-3001"}
    await handler.execute("search", payload_success)

    success_card = next(c for c in logged_cards if "RESULT" in c and "CMD-3001" in c)
    assert "Status    : SUCCESS" in success_card
    assert "Execution : COMPLETE" in success_card
    assert "Result    : Song is playing" in success_card

    # 19b. Failure case from subplugin
    mock_subplugins["youtube"].execute.return_value = {
        "status": "error",
        "message": "Search failed: timeout",
    }
    payload_failure = {"app": "YOUTUBE", "command_id": "CMD-3002"}
    await handler.execute("search", payload_failure)

    failure_card = next(c for c in logged_cards if "RESULT" in c and "CMD-3002" in c)
    assert "Status    : FAILED" in failure_card
    assert "Execution : FAILED" in failure_card
    assert "Result    : Search failed: tim..." in failure_card

