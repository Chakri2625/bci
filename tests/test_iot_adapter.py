import pytest
import asyncio
from unittest.mock import patch, AsyncMock
from core.communication.iot_adapter import iot_adapter

def test_successful_dispatch():
    # Mock successful plugin execution
    with patch("core.communication.iot_adapter.execute", new_callable=AsyncMock) as mock_execute:
        mock_execute.return_value = {"status": "success"}
        
        result = asyncio.run(iot_adapter.dispatch_command(
            command_id="cmd_1",
            action="MOVE_FORWARD",
            device_id="dev_1",
            direction="FORWARD",
            priority=2,
            timestamp=12345.0
        ))
        
        assert result["success"] is True
        assert result["status"] == "success"
        assert result["command_id"] == "cmd_1"
        
        mock_execute.assert_called_once_with("iot", "MOVE_FORWARD", {
            "command_id": "cmd_1",
            "action": "MOVE_FORWARD",
            "device_id": "dev_1",
            "direction": "FORWARD",
            "priority": 2,
            "timestamp": 12345.0
        })

def test_transport_failure():
    # Mock execution raising an exception
    with patch("core.communication.iot_adapter.execute", new_callable=AsyncMock) as mock_execute:
        mock_execute.side_effect = Exception("Connection Refused")
        
        result = asyncio.run(iot_adapter.dispatch_command(
            command_id="cmd_2",
            action="STOP",
            device_id="dev_1"
        ))
        
        assert result["success"] is False
        assert result["status"] == "failed"
        assert "Connection Refused" in result["error"]
        assert result["command_id"] == "cmd_2"

def test_unavailable_response():
    # Mock execution returning error status (e.g. plugin not found)
    with patch("core.communication.iot_adapter.execute", new_callable=AsyncMock) as mock_execute:
        mock_execute.return_value = {"status": "error", "message": "Plugin not found"}
        
        result = asyncio.run(iot_adapter.dispatch_command(
            command_id="cmd_3",
            action="TURN_LEFT",
            device_id="dev_1"
        ))
        
        assert result["success"] is False
        assert result["status"] == "error"
        assert result["error"] == "Plugin not found"
        assert result["command_id"] == "cmd_3"

def test_empty_response():
    # Mock execution returning None
    with patch("core.communication.iot_adapter.execute", new_callable=AsyncMock) as mock_execute:
        mock_execute.return_value = None
        
        result = asyncio.run(iot_adapter.dispatch_command(
            command_id="cmd_4",
            action="TURN_RIGHT",
            device_id="dev_1"
        ))
        
        assert result["success"] is False
        assert result["status"] == "failed"
        assert "no response from IoT plugin" in result["error"]
        assert result["command_id"] == "cmd_4"

def test_malformed_outbound_data():
    # Missing action
    result = asyncio.run(iot_adapter.dispatch_command(
        command_id="cmd_5",
        action="",
        device_id="dev_1"
    ))
    
    assert result["success"] is False
    assert result["status"] == "failed"
    assert "malformed outbound data: missing action or device_id" in result["error"]
    assert result["command_id"] == "cmd_5"
    
    # Missing device_id
    result2 = asyncio.run(iot_adapter.dispatch_command(
        command_id="cmd_6",
        action="STOP",
        device_id=""
    ))
    
    assert result2["success"] is False
    assert result2["status"] == "failed"
    assert "malformed outbound data: missing action or device_id" in result2["error"]
    assert result2["command_id"] == "cmd_6"
