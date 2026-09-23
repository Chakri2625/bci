"""
tests/test_battery_telemetry.py
================================
Tests for Robot/Wheelchair Battery-Status Telemetry Ingestion on SynaptiMesh Server.
Covers:
- Battery validation function (valid, boundary, negative, >100, malformed, boolean)
- Missing battery field handling
- Wheelchair status payloads with battery
- Robot car status payloads with battery
- Simultaneous voltage + battery preservation
- Model normalization into SystemHealthTelemetry and EmbeddedTelemetry
- Full pipeline: MQTT -> TelemetryManager -> Normalized Telemetry -> WebSocket emission
- Regression tests for existing ACK and movement/status handling
"""

import json
import pytest
from unittest.mock import MagicMock

from models.telemetry_models import (
    EmbeddedTelemetry,
    SystemHealthTelemetry,
    UnifiedTelemetryPacket,
    TelemetryDomain,
)
from plugins.embedded.dashboard.embedded_backend.telemetry import (
    TelemetryManager,
    validate_battery_soc,
    validate_supply_voltage,
)
from plugins.embedded.dashboard.embedded_backend.mqtt_client import MQTTClient


# ==============================================================================
# 1. Battery Validation Function Tests
# ==============================================================================

def test_battery_validation_valid():
    """Valid value: battery_soc_pct = 75."""
    assert validate_battery_soc(75) == 75
    assert validate_battery_soc(75.0) == 75
    assert validate_battery_soc("75") == 75
    assert validate_battery_soc("75%") == 75
    assert validate_battery_soc(" 75 % ") == 75


def test_battery_validation_boundary_zero():
    """Boundary value: battery_soc_pct = 0."""
    assert validate_battery_soc(0) == 0
    assert validate_battery_soc(0.0) == 0
    assert validate_battery_soc("0") == 0
    assert validate_battery_soc("0%") == 0


def test_battery_validation_boundary_hundred():
    """Boundary value: battery_soc_pct = 100."""
    assert validate_battery_soc(100) == 100
    assert validate_battery_soc(100.0) == 100
    assert validate_battery_soc("100") == 100
    assert validate_battery_soc("100%") == 100


def test_battery_validation_negative():
    """Negative values: rejected safely."""
    assert validate_battery_soc(-10) is None
    assert validate_battery_soc(-1) is None
    assert validate_battery_soc("-10") is None
    assert validate_battery_soc("-10%") is None


def test_battery_validation_greater_than_100():
    """Values > 100: rejected safely."""
    assert validate_battery_soc(105) is None
    assert validate_battery_soc(101) is None
    assert validate_battery_soc("150") is None
    assert validate_battery_soc("105%") is None


def test_battery_validation_malformed():
    """Malformed values: rejected safely."""
    assert validate_battery_soc("unknown") is None
    assert validate_battery_soc("N/A") is None
    assert validate_battery_soc("") is None
    assert validate_battery_soc([]) is None
    assert validate_battery_soc({}) is None


def test_battery_validation_boolean():
    """Boolean values: rejected safely (must not be treated as 0 or 1)."""
    assert validate_battery_soc(True) is None
    assert validate_battery_soc(False) is None


def test_battery_validation_none():
    """None value: returns None."""
    assert validate_battery_soc(None) is None


# ==============================================================================
# 2. TelemetryManager Ingestion & Missing Battery Handling
# ==============================================================================

def test_missing_battery_field_preserves_normal_telemetry():
    """Missing battery field must not break normal telemetry processing."""
    mock_socket = MagicMock()
    tm = TelemetryManager(mock_socket)

    topic = "robotcar/98:A3:16:BF:2C:C0/status"
    payload = json.dumps({"status": "CAR FORWARD EXECUTED", "state": "FORWARD"})

    tm.handle_telemetry(topic, payload)

    assert tm.latest["device"] == "98:A3:16:BF:2C:C0"
    assert tm.latest["state"] == "FORWARD"
    assert tm.latest["battery_soc_pct"] is None

    # Telemetry should still be emitted through socket
    mock_socket.telemetry.assert_called_once()
    emitted = mock_socket.telemetry.call_args[0][0]
    assert emitted["device"] == "98:A3:16:BF:2C:C0"
    assert emitted["state"] == "FORWARD"
    assert "battery_soc_pct" not in emitted


# ==============================================================================
# 3. Wheelchair Status Payload with Battery
# ==============================================================================

def test_wheelchair_status_payload_with_battery():
    """Wheelchair status topic and payload containing battery information."""
    mock_socket = MagicMock()
    tm = TelemetryManager(mock_socket)

    topic = "wheelchair/wheelchair-01/status"
    payload = json.dumps({
        "status": "ONLINE",
        "battery_soc_pct": 68,
        "state": "STOP"
    })

    tm.handle_telemetry(topic, payload)

    assert tm.latest["device"] == "wheelchair-01"
    assert tm.latest["battery_soc_pct"] == 68
    assert tm.latest["normalized_telemetry"]["device_mode"] == "WHEELCHAIR"
    assert tm.latest["normalized_telemetry"]["system_health"]["battery_soc_pct"] == 68

    mock_socket.telemetry.assert_called_once()
    emitted = mock_socket.telemetry.call_args[0][0]
    assert emitted["device"] == "wheelchair-01"
    assert emitted["battery_soc_pct"] == 68


def test_wheelchair_telemetry_mesh_topic():
    """Wheelchair status published on mesh/chair/telemetry topic."""
    mock_socket = MagicMock()
    tm = TelemetryManager(mock_socket)

    topic = "mesh/chair/telemetry"
    payload = json.dumps({
        "status": "ONLINE",
        "battery": 82,
        "supply_voltage_v": 24.2
    })

    tm.handle_telemetry(topic, payload)

    assert tm.latest["device"] == "chair"
    assert tm.latest["battery_soc_pct"] == 82
    assert tm.latest["supply_voltage_v"] == 24.2
    assert tm.latest["normalized_telemetry"]["device_mode"] == "WHEELCHAIR"


# ==============================================================================
# 4. Robot Status Payload with Battery
# ==============================================================================

def test_robot_status_payload_with_battery():
    """Robot status topic and payload containing battery information."""
    mock_socket = MagicMock()
    tm = TelemetryManager(mock_socket)

    topic = "robotcar/98:A3:16:BF:2C:C0/status"
    payload = json.dumps({
        "status": "CAR FORWARD EXECUTED",
        "battery_soc_pct": 75,
        "state": "FORWARD",
        "front_distance": 45.5
    })

    tm.handle_telemetry(topic, payload)

    assert tm.latest["device"] == "98:A3:16:BF:2C:C0"
    assert tm.latest["battery_soc_pct"] == 75
    assert tm.latest["front_distance"] == 45.5
    assert tm.latest["state"] == "FORWARD"
    assert tm.latest["normalized_telemetry"]["device_mode"] == "RC_CAR"

    mock_socket.telemetry.assert_called_once()
    emitted = mock_socket.telemetry.call_args[0][0]
    assert emitted["device"] == "98:A3:16:BF:2C:C0"
    assert emitted["battery_soc_pct"] == 75
    assert emitted["front_distance"] == 45.5


# ==============================================================================
# 5. Simultaneous Voltage and Battery Preservation
# ==============================================================================

def test_voltage_and_battery_together():
    """Preserves both supply voltage and battery SoC when present."""
    mock_socket = MagicMock()
    tm = TelemetryManager(mock_socket)

    topic = "robotcar/98:A3:16:BF:2C:C0/status"
    payload = json.dumps({
        "status": "ONLINE",
        "battery_soc_pct": 90,
        "supply_voltage_v": 12.6,
        "system_health": {
            "free_heap_bytes": 195400,
            "cpu_core_temp_c": 38.5
        }
    })

    tm.handle_telemetry(topic, payload)

    assert tm.latest["battery_soc_pct"] == 90
    assert tm.latest["supply_voltage_v"] == 12.6

    norm = tm.latest["normalized_telemetry"]
    assert norm["system_health"]["battery_soc_pct"] == 90
    assert norm["system_health"]["supply_voltage_v"] == 12.6
    assert norm["system_health"]["free_heap_bytes"] == 195400

    emitted = mock_socket.telemetry.call_args[0][0]
    assert emitted["battery_soc_pct"] == 90
    assert emitted["supply_voltage_v"] == 12.6


# ==============================================================================
# 6. Full Pipeline: MQTT Message -> TelemetryManager -> Normalized -> WebSocket
# ==============================================================================

def test_full_pipeline_mqtt_to_websocket():
    """
    End-to-end server ingestion flow:
    MQTT Client callback
    -> TelemetryManager
    -> Battery Validation
    -> SystemHealthTelemetry & EmbeddedTelemetry Normalization
    -> SocketManager / WebSocket emission
    """
    mock_socket = MagicMock()
    tm = TelemetryManager(mock_socket)

    mqtt_client = MQTTClient()
    mqtt_client.add_message_listener(tm.handle_telemetry)

    # Simulate incoming Paho MQTT message object
    class FakeMsg:
        def __init__(self, topic: str, payload_bytes: bytes):
            self.topic = topic
            self.payload = payload_bytes

    incoming_payload = {
        "status": "ONLINE",
        "battery_soc_pct": 75,
        "supply_voltage_v": 12.4,
        "state": "STOP"
    }

    raw_msg = FakeMsg(
        topic="robotcar/98:A3:16:BF:2C:C0/status",
        payload_bytes=json.dumps(incoming_payload).encode("utf-8")
    )

    # Trigger Paho on_message callback
    mqtt_client.on_message(None, None, raw_msg)

    # Verify TelemetryManager processed it
    assert tm.latest["device"] == "98:A3:16:BF:2C:C0"
    assert tm.latest["battery_soc_pct"] == 75
    assert tm.latest["supply_voltage_v"] == 12.4

    # Verify normalization into SystemHealthTelemetry and EmbeddedTelemetry
    norm = tm.latest["normalized_telemetry"]
    assert norm["device_mode"] == "RC_CAR"
    assert norm["system_health"]["battery_soc_pct"] == 75
    assert norm["system_health"]["supply_voltage_v"] == 12.4

    # Verify WebSocket emission
    mock_socket.telemetry.assert_called_once()
    emitted = mock_socket.telemetry.call_args[0][0]
    assert emitted["device"] == "98:A3:16:BF:2C:C0"
    assert emitted["battery_soc_pct"] == 75
    assert emitted["supply_voltage_v"] == 12.4


# ==============================================================================
# 7. Regression Tests: ACK & Movement Handling Not Broken
# ==============================================================================

def test_existing_ack_handling_preserved():
    """Verifies that device ACK processing is not broken."""
    mock_socket = MagicMock()
    tm = TelemetryManager(mock_socket)

    topic = "robotcar/98:A3:16:BF:2C:C0/ack"
    payload = "CAR FORWARD EXECUTED"

    tm.handle_telemetry(topic, payload)

    assert tm.latest["device"] == "98:A3:16:BF:2C:C0"
    assert tm.latest["ack"] == "CAR FORWARD EXECUTED"
    assert tm.latest["last_command"] == "CAR FORWARD EXECUTED"

    mock_socket.ack.assert_called_once()
    ack_data = mock_socket.ack.call_args[0][0]
    assert ack_data["ack"] == "CAR FORWARD EXECUTED"
    assert ack_data["device"] == "98:A3:16:BF:2C:C0"


def test_existing_movement_state_detection_preserved():
    """Verifies that movement states from legacy strings continue working."""
    mock_socket = MagicMock()
    tm = TelemetryManager(mock_socket)

    tm.handle_telemetry("robotcar/car1/status", "CAR FORWARD EXECUTED")
    assert tm.latest["state"] == "FORWARD"

    tm.handle_telemetry("robotcar/car1/status", "CAR BACKWARD EXECUTED")
    assert tm.latest["state"] == "BACKWARD"

    tm.handle_telemetry("robotcar/car1/status", "FRONT OBSTACLE DETECTED")
    assert tm.latest["state"] == "STOP"
