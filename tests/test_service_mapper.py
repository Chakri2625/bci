"""
Tests for Command Service Mapper (Member 5 - Day 5 Implementation)
Verifies domain routing, metadata preservation, lifecycle tracking,
error isolation, and unsupported command handling.
"""

import pytest
import time
from unittest.mock import MagicMock

from services.command_service_mapper import (
    CommandServiceMapper,
    Domain,
    MappingStatus,
    get_command_service_mapper,
)


@pytest.fixture
def mapper():
    """Create a fresh CommandServiceMapper for testing."""
    return CommandServiceMapper()


def test_service_mapper_initialization(mapper):
    """Verify mapper initializes with registered domains."""
    assert mapper is not None
    domains = mapper.get_registered_domains()
    assert "MEDIA" in domains


def test_route_to_media_service(mapper):
    """Test routing a MEDIA domain command preserves metadata and executes."""
    mock_media_svc = MagicMock()
    mock_media_svc.execute_command.return_value = {
        "status": "SUCCESS",
        "success": True,
        "message": "Playback paused",
        "details": {"state": "paused"},
    }
    mapper.register_service("MEDIA", mock_media_svc)

    res = mapper.map_and_execute(
        command_id="cmd_media_001",
        domain="MEDIA",
        action="PAUSE",
        parameters={"session": "sess_123"},
        priority=2,
        session_id="sess_123",
        device_id="dev_speaker",
    )

    assert res["command_id"] == "cmd_media_001"
    assert res["domain"] == "MEDIA"
    assert res["action"] == "pause"
    assert res["success"] is True
    assert res["status"] == "SUCCESS"
    assert res["metadata"]["priority"] == 2
    assert res["metadata"]["session_id"] == "sess_123"
    assert res["metadata"]["device_id"] == "dev_speaker"
    assert res["execution_time_ms"] >= 0
    mock_media_svc.execute_command.assert_called_once()


def test_route_to_desktop_service(mapper):
    """Test routing a DESKTOP domain command."""
    mock_desktop = MagicMock()
    mock_desktop.execute.return_value = {"status": "success", "message": "App opened"}
    mapper.register_service("DESKTOP", mock_desktop)

    res = mapper.map_and_execute(
        command_id="cmd_desk_002",
        domain="DESKTOP",
        action="open_app",
        parameters={"app": "notepad"},
    )

    assert res["command_id"] == "cmd_desk_002"
    assert res["domain"] == "DESKTOP"
    assert res["action"] == "open_app"
    assert res["success"] is True
    assert res["status"] == "SUCCESS"


def test_route_to_iot_service(mapper):
    """Test routing an IOT domain command with device_id."""
    mock_iot = MagicMock()
    mock_iot.execute.return_value = {"status": "success", "device": "ESP32_RELAY_01", "state": "ON"}
    mapper.register_service("IOT", mock_iot)

    res = mapper.map_and_execute(
        command_id="cmd_iot_003",
        domain="IOT",
        action="TURN_ON",
        parameters={"device_id": "ESP32_RELAY_01"},
        device_id="ESP32_RELAY_01",
    )

    assert res["command_id"] == "cmd_iot_003"
    assert res["domain"] == "IOT"
    assert res["success"] is True
    assert res["status"] == "SUCCESS"
    assert res["metadata"]["device_id"] == "ESP32_RELAY_01"


def test_custom_action_handler_registration(mapper):
    """Test registering a custom action handler override."""
    def custom_handler(action, params, ctx):
        return {"handled_by": "custom_handler", "custom_param": params.get("foo")}

    mapper.register_action_handler("MEDIA", "custom_action", custom_handler)

    res = mapper.map_and_execute(
        command_id="cmd_custom_004",
        domain="MEDIA",
        action="custom_action",
        parameters={"foo": "bar"},
    )

    assert res["command_id"] == "cmd_custom_004"
    assert res["success"] is True
    assert res["result"]["handled_by"] == "custom_handler"
    assert res["result"]["custom_param"] == "bar"


def test_unsupported_domain_error_handling(mapper):
    """Test that an unmapped domain returns structured error response with preserved metadata."""
    res = mapper.map_and_execute(
        command_id="cmd_unsupported_005",
        domain="QUANTUM_TELEPORT",
        action="BEAM_ME_UP",
        parameters={"coords": [10, 20]},
        priority=3,
        session_id="enterprise_bridge",
    )

    assert res["command_id"] == "cmd_unsupported_005"
    assert res["domain"] == "QUANTUM_TELEPORT"
    assert res["action"] == "beam_me_up"
    assert res["success"] is False
    assert res["status"] == "UNSUPPORTED"
    assert "Unsupported or unregistered domain" in res["error"]
    assert res["metadata"]["priority"] == 3
    assert res["metadata"]["session_id"] == "enterprise_bridge"


def test_empty_domain_error_handling(mapper):
    """Test handling of empty domain string."""
    res = mapper.map_and_execute(
        command_id="cmd_empty_006",
        domain="",
        action="NOOP",
    )
    assert res["command_id"] == "cmd_empty_006"
    assert res["success"] is False
    assert res["status"] == "FAILED"
    assert "Empty or missing domain" in res["error"]


def test_service_exception_isolation(mapper):
    """Test that a throwing service method does not crash the mapper and returns structured error."""
    mock_broken_svc = MagicMock()
    mock_broken_svc.execute_command.side_effect = Exception("Service crashed unexpectedly")
    mapper.register_service("EMBEDDED", mock_broken_svc)

    res = mapper.map_and_execute(
        command_id="cmd_crash_007",
        domain="EMBEDDED",
        action="DRIVE_FORWARD",
    )

    assert res["command_id"] == "cmd_crash_007"
    assert res["success"] is False
    assert res["status"] == "FAILED"
    assert "Service crashed unexpectedly" in res["error"]


def test_execution_history_tracking(mapper):
    """Test that history buffer tracks executions."""
    mock_svc = MagicMock()
    mock_svc.execute_command.return_value = {"success": True}
    mapper.register_service("MEDIA", mock_svc)

    mapper.map_and_execute(command_id="hist_1", domain="MEDIA", action="PLAY")
    mapper.map_and_execute(command_id="hist_2", domain="MEDIA", action="PAUSE")

    history = mapper.get_history(limit=10)
    assert len(history) >= 2
    cmd_ids = [h["command_id"] for h in history]
    assert "hist_1" in cmd_ids
    assert "hist_2" in cmd_ids


def test_singleton_getter():
    """Verify singleton instance."""
    s1 = get_command_service_mapper()
    s2 = get_command_service_mapper()
    assert s1 is s2
