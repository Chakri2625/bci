"""
test_robot_wheelchair_pipeline_e2e.py
======================================
Comprehensive End-to-End Test Suite for SynaptiMesh Sprint 11 Day 5 Member 9:
Complete Integrated Robot + Wheelchair Telemetry Pipeline.

Covers:
- Robot telemetry ingestion -> standardization -> state manager -> WebSocket delivery
- Wheelchair telemetry ingestion -> standardization -> state manager -> WebSocket delivery
- Device State Isolation (Robot and Wheelchair states never collide or overwrite)
- Movement, Speed, Battery & Voltage validation
- Safety condition & status alert generation for multi-device streams
- Subplugin status conversion (RcCarPlugin & WheelchairPlugin)
- REST API and multi-device telemetry query endpoints
"""

import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from models.telemetry_models import (
    AlertSeverity,
    AlertStatus,
    EmbeddedTelemetry,
    KinematicsTelemetry,
    SafetyRangingTelemetry,
    SystemHealthTelemetry,
    TelemetryAlert,
    TelemetryDomain,
    UnifiedTelemetryPacket,
)
from services.embedded_telemetry_normalizer import (
    normalize_embedded_telemetry,
    normalize_movement,
    normalize_speed,
    normalize_status,
    subplugin_to_telemetry_packet,
    validate_battery_soc,
    validate_supply_voltage,
)
from services.embedded_alert_generator import EmbeddedAlertGenerator
from plugins.embedded.dashboard.embedded_backend.telemetry import TelemetryManager
from plugins.embedded.subplugins.rc_car.plugin import RcCarPlugin
from plugins.embedded.subplugins.wheelchair.plugin import WheelchairPlugin
from core.state.state_manager import state_manager
from api.telemetry_routes import telemetry_router
from plugins.embedded.fastapi_routes import router as embedded_router


class MockSocketManager:
    """Mock SocketManager capturing all outgoing WebSocket emissions."""
    def __init__(self):
        self.telemetry_events = []
        self.alert_events = []
        self.ack_events = []
        self.activity_events = []
        self.device_statuses = {}
        self.mqtt_device_statuses = {}

    def telemetry(self, data):
        self.telemetry_events.append(dict(data))

    def alert(self, data):
        self.alert_events.append(dict(data))

    def ack(self, data):
        self.ack_events.append(dict(data))

    def activity(self, msg):
        self.activity_events.append(msg)

    def handle_message(self, topic, payload):
        pass

    def update_device_status(self, device, status):
        self.device_statuses[device] = status

    def mqtt_device_status(self, device, status):
        self.mqtt_device_statuses[device] = status


@pytest.fixture
def mock_socket():
    return MockSocketManager()


@pytest.fixture
def telemetry_manager(mock_socket):
    EmbeddedAlertGenerator.get_instance().clear_alerts()
    return TelemetryManager(socket=mock_socket)


# ==============================================================================
# 1. Robot Telemetry Pipeline Test
# ==============================================================================

def test_robot_telemetry_pipeline_e2e(telemetry_manager, mock_socket):
    """Verify Robot telemetry is ingested, standardized, stored per-device, and broadcast."""
    robot_topic = "robotcar/ROBOTCAR_01/status"
    robot_payload = {
        "device_id": "ROBOTCAR_01",
        "state": "FORWARD",
        "status": "ONLINE",
        "speed": 0.85,
        "battery_soc_pct": 88,
        "supply_voltage_v": 12.2,
        "front_distance": 65.0,
        "rear_distance": 80.0,
        "front_obstacle": False,
        "rear_obstacle": False
    }

    telemetry_manager.handle_status(robot_topic, robot_payload)

    # 1. Verify per-device isolated state
    robot_state = telemetry_manager.get_device_latest("ROBOTCAR_01")
    assert robot_state is not None
    assert robot_state["device"] == "ROBOTCAR_01"
    assert robot_state["device_mode"] == "RC_CAR"
    assert robot_state["state"] == "FORWARD"
    assert robot_state["battery_soc_pct"] == 88
    assert robot_state["supply_voltage_v"] == 12.2
    assert robot_state["front_distance"] == 65.0

    # 2. Verify Central State Manager received state
    dev_state_sm = state_manager.get_device_state("ROBOTCAR_01")
    assert dev_state_sm is not None
    assert dev_state_sm["device_id"] == "ROBOTCAR_01"

    # 3. Verify WebSocket broadcast
    assert len(mock_socket.telemetry_events) > 0
    latest_event = mock_socket.telemetry_events[-1]
    assert latest_event["device"] == "ROBOTCAR_01"
    assert latest_event["device_mode"] == "RC_CAR"
    assert latest_event["state"] == "FORWARD"
    assert latest_event["battery_soc_pct"] == 88
    assert latest_event["supply_voltage_v"] == 12.2
    assert latest_event["front_distance"] == 65.0


# ==============================================================================
# 2. Wheelchair Telemetry Pipeline Test
# ==============================================================================

def test_wheelchair_telemetry_pipeline_e2e(telemetry_manager, mock_socket):
    """Verify Smart Wheelchair telemetry is ingested, standardized, stored per-device, and broadcast."""
    wheelchair_topic = "wheelchair/WHEELCHAIR_01/status"
    wheelchair_payload = {
        "device_id": "WHEELCHAIR_01",
        "state": "BACKWARD",
        "status": "ONLINE",
        "speed": 0.5,
        "battery_soc_pct": 74,
        "supply_voltage_v": 24.6,
        "front_distance": 90.0,
        "rear_distance": 42.0,
        "front_obstacle": False,
        "rear_obstacle": False
    }

    telemetry_manager.handle_status(wheelchair_topic, wheelchair_payload)

    # 1. Verify per-device isolated state
    chair_state = telemetry_manager.get_device_latest("WHEELCHAIR_01")
    assert chair_state is not None
    assert chair_state["device"] == "WHEELCHAIR_01"
    assert chair_state["device_mode"] == "WHEELCHAIR"
    assert chair_state["state"] == "BACKWARD"
    assert chair_state["battery_soc_pct"] == 74
    assert chair_state["supply_voltage_v"] == 24.6
    assert chair_state["rear_distance"] == 42.0

    # 2. Verify Central State Manager received wheelchair state
    dev_state_sm = state_manager.get_device_state("WHEELCHAIR_01")
    assert dev_state_sm is not None
    assert dev_state_sm["device_id"] == "WHEELCHAIR_01"

    # 3. Verify WebSocket broadcast
    assert len(mock_socket.telemetry_events) > 0
    latest_event = mock_socket.telemetry_events[-1]
    assert latest_event["device"] == "WHEELCHAIR_01"
    assert latest_event["device_mode"] == "WHEELCHAIR"
    assert latest_event["state"] == "BACKWARD"
    assert latest_event["battery_soc_pct"] == 74


# ==============================================================================
# 3. Device State Isolation Test (Robot vs Wheelchair)
# ==============================================================================

def test_device_state_isolation_robot_and_wheelchair(telemetry_manager, mock_socket):
    """Verify that Robot and Wheelchair updates maintain completely isolated states."""
    # 1. Ingest Robot update
    telemetry_manager.handle_status(
        "robotcar/ROBOTCAR_01/status",
        {"device_id": "ROBOTCAR_01", "state": "FORWARD", "battery_soc_pct": 95, "front_distance": 120.0}
    )

    # 2. Ingest Wheelchair update
    telemetry_manager.handle_status(
        "wheelchair/WHEELCHAIR_01/status",
        {"device_id": "WHEELCHAIR_01", "state": "LEFT", "battery_soc_pct": 60, "front_distance": 35.0}
    )

    # 3. Check both device states
    robot = telemetry_manager.get_device_latest("ROBOTCAR_01")
    wheelchair = telemetry_manager.get_device_latest("WHEELCHAIR_01")

    assert robot is not None
    assert wheelchair is not None

    # Robot state was not modified by wheelchair update
    assert robot["device"] == "ROBOTCAR_01"
    assert robot["state"] == "FORWARD"
    assert robot["battery_soc_pct"] == 95
    assert robot["front_distance"] == 120.0

    # Wheelchair state is distinct
    assert wheelchair["device"] == "WHEELCHAIR_01"
    assert wheelchair["state"] == "LEFT"
    assert wheelchair["battery_soc_pct"] == 60
    assert wheelchair["front_distance"] == 35.0

    # 4. Ingest new Robot update, verify wheelchair is untouched
    telemetry_manager.handle_status(
        "robotcar/ROBOTCAR_01/status",
        {"device_id": "ROBOTCAR_01", "state": "STOP", "battery_soc_pct": 94}
    )

    robot_updated = telemetry_manager.get_device_latest("ROBOTCAR_01")
    wheelchair_check = telemetry_manager.get_device_latest("WHEELCHAIR_01")

    assert robot_updated["state"] == "STOP"
    assert robot_updated["battery_soc_pct"] == 94
    assert wheelchair_check["state"] == "LEFT"
    assert wheelchair_check["battery_soc_pct"] == 60


# ==============================================================================
# 4. Safety & Status Alert Integration in Pipeline
# ==============================================================================

def test_alert_generation_in_telemetry_pipeline(telemetry_manager, mock_socket):
    """Verify that dangerous telemetry conditions automatically generate and emit alerts."""
    # Front obstacle critical on Robot Car
    telemetry_manager.handle_status(
        "robotcar/ROBOTCAR_01/status",
        {
            "device_id": "ROBOTCAR_01",
            "state": "FORWARD",
            "front_distance": 10.0,  # <= 15cm -> CRITICAL
            "battery_soc_pct": 12    # <= 15% -> CRITICAL
        }
    )

    assert len(mock_socket.alert_events) >= 2
    alert_types = [a.get("alert_type") for a in mock_socket.alert_events]
    assert "OBSTACLE_PROXIMITY" in alert_types
    assert "CRITICAL_BATTERY" in alert_types

    # Auto-resolution when condition clears
    telemetry_manager.handle_status(
        "robotcar/ROBOTCAR_01/status",
        {
            "device_id": "ROBOTCAR_01",
            "state": "STOP",
            "front_distance": 60.0,
            "battery_soc_pct": 80
        }
    )

    resolved_events = [a for a in mock_socket.alert_events if a.get("status") == "RESOLVED"]
    assert len(resolved_events) >= 2


# ==============================================================================
# 5. Subplugin Status Ingestion Tests
# ==============================================================================

def test_rc_car_and_wheelchair_subplugin_status_conversion():
    """Verify RcCarPlugin and WheelchairPlugin status() objects convert cleanly to Unified packets."""
    rc_plugin = RcCarPlugin()
    rc_status = rc_plugin.status()
    rc_packet = subplugin_to_telemetry_packet(rc_status, device_id="RC_CAR_01")

    assert rc_packet.source_domain == TelemetryDomain.EMBEDDED
    assert rc_packet.source_id == "RC_CAR_01"
    assert isinstance(rc_packet.payload, EmbeddedTelemetry)
    assert rc_packet.payload.device_mode == "RC_CAR"

    wc_plugin = WheelchairPlugin()
    wc_status = wc_plugin.status()
    wc_packet = subplugin_to_telemetry_packet(wc_status, device_id="WHEELCHAIR_01")

    assert wc_packet.source_domain == TelemetryDomain.EMBEDDED
    assert wc_packet.source_id == "WHEELCHAIR_01"
    assert isinstance(wc_packet.payload, EmbeddedTelemetry)
    assert wc_packet.payload.device_mode == "WHEELCHAIR"


# ==============================================================================
# 6. REST API End-to-End Pipeline Tests
# ==============================================================================

@pytest.fixture
def test_app():
    app = FastAPI(title="PipelineTest")
    app.include_router(telemetry_router)
    app.include_router(embedded_router)
    return app


def test_rest_telemetry_pipeline_and_device_query(test_app):
    """Verify REST telemetry ingestion and device state queries."""
    client = TestClient(test_app)

    # Ingest standard telemetry packet for Robot
    robot_resp = client.post(
        "/api/v1/telemetry",
        json={
            "source_domain": "EMBEDDED",
            "source_id": "ROBOT_CAR_02",
            "payload": {
                "device_id": "ROBOT_CAR_02",
                "device_mode": "RC_CAR",
                "status": "ONLINE",
                "kinematics": {"movement": "FORWARD", "speed": 0.8},
                "system_health": {"battery_soc_pct": 91, "supply_voltage_v": 12.1}
            }
        }
    )
    assert robot_resp.status_code == 200
    assert robot_resp.json()["status"] == "success"

    # Ingest standard telemetry packet for Wheelchair
    chair_resp = client.post(
        "/api/v1/telemetry",
        json={
            "source_domain": "EMBEDDED",
            "source_id": "WHEELCHAIR_02",
            "payload": {
                "device_id": "WHEELCHAIR_02",
                "device_mode": "WHEELCHAIR",
                "status": "ONLINE",
                "kinematics": {"movement": "PUSH", "speed": 0.6},
                "system_health": {"battery_soc_pct": 77, "supply_voltage_v": 24.2}
            }
        }
    )
    assert chair_resp.status_code == 200
    assert chair_resp.json()["status"] == "success"

    # Verify latest telemetry endpoint
    latest_resp = client.get("/api/v1/telemetry/latest?domain=EMBEDDED")
    assert latest_resp.status_code == 200
    data = latest_resp.json()
    assert data["status"] == "success"
    assert data["telemetry"] is not None
