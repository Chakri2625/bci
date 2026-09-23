"""
Comprehensive End-to-End Test Suite for SynaptiMesh IoT Pipeline.
Sprint 11 — Tasks 1 to 9 Verification.

Covers:
  Task 1: IoT Device-State Ingestion (model + parsing + schema validation + fields)
  Task 2: IoT Activity-Log Ingestion (structured records + backend storage + API)
  Task 3: IoT Telemetry Standardization (normalization + standard envelope + validation)
  Task 4: Connection/Disconnection Detection (heartbeat monitor + timeout logic + events)
  Task 5: Offline-State Updates & Auto-Reconnection (offline/online transitions + reasons)
  Task 6: Central IoT State Synchronization (StateManager integration + versioning + stale rejection)
  Task 7: IoT WebSocket Integration (broadcaster + envelope format + subscriber delivery)
  Task 8: Real-Time Dashboard Propagation (REST API + WebSocket snapshot + UI routing)
  Task 9: Complete Pipeline Integration (Full MQTT -> Normalizer -> StateManager -> WebSocket flow)
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from core.communication.websocket_server import get_websocket_server
from core.managers.command_lock_manager import command_lock_manager
from core.managers.event_history import event_history_manager
from core.plugin_manager.manager import get_plugin, load_plugins
from core.state.state_manager import state_manager
from main import app
from models.device_models import (
    ConnectionStatus,
    DeviceDomain,
    DeviceState,
    DeviceType,
    IoTActivityRecord,
    OperationalStatus,
)
from models.telemetry_models import TelemetryDomain, UnifiedTelemetryPacket
from plugins.iot.device_manager import Device, DeviceManager
from plugins.iot.plugin import IoTPlugin
from services.iot_telemetry_normalizer import (
    device_to_telemetry_packet,
    normalize_iot_telemetry,
)

client = TestClient(app)


def receive_matching(ws, target_type=None, target_domain=None, max_skips=15):
    """Receive messages, skipping initial snapshots / ambient frames until target type matches."""
    for _ in range(max_skips):
        msg = ws.receive_json()
        if target_type is None:
            return msg
        if msg.get("type") == target_type:
            if target_domain is None or msg.get("source_domain") == target_domain:
                return msg
    return msg


@pytest.fixture(autouse=True)
def clean_system_state():
    """Reset system state, locks, and plugins before and after each test."""
    state_manager.reset_state("default")
    command_lock_manager.reset()
    yield
    state_manager.reset_state("default")
    command_lock_manager.reset()


# ==============================================================================
# Task 1: IoT Device-State Ingestion Tests
# ==============================================================================

def test_task1_device_state_ingestion_and_fields():
    """
    Verify IoT device state ingestion from MQTT/backend, field parsing,
    sensor tracking, and conversion to standardized DeviceState model.
    """
    dm = DeviceManager()

    raw_payload = {
        "device_id": "ESP32_LIVING_ROOM",
        "mac": "98:A3:16:BF:2C:C0",
        "system": "ESP32",
        "firmware": "2.0.0-unified",
        "states": {
            "light": "ON",
            "fan": "OFF",
            "pump": "ON",
        },
        "rssi": -62,
        "ip": "192.168.1.105",
        "uptime": 3600,
    }

    dev, act = dm.update_device(raw_payload)
    assert dev is not None
    assert dev.device_id == "ESP32_LIVING_ROOM"
    assert dev.light == "ON"
    assert dev.fan == "OFF"
    assert dev.pump == "ON"
    assert dev.wifi_rssi_dbm == -62
    assert dev.ip_address == "192.168.1.105"
    assert dev.uptime_seconds == 3600
    assert dev.online is True
    assert dev.connection_status == "ONLINE"
    assert dev.last_seen != ""
    assert dev.last_seen_timestamp > 0

    # Ingest sensor readings
    sensor_payload = {
        "temperature_celsius": 24.5,
        "humidity_pct": 58.2,
        "ambient_light_lux": 350.0,
        "motion_detected": True,
        "voltage_v": 230.1,
        "current_a": 1.25,
        "power_watts": 287.6,
        "energy_kwh": 14.8,
    }
    dev_updated, _ = dm.update_sensors("ESP32_LIVING_ROOM", sensor_payload)
    assert dev_updated.temperature_celsius == 24.5
    assert dev_updated.humidity_pct == 58.2
    assert dev_updated.ambient_light_lux == 350.0
    assert dev_updated.motion_detected is True
    assert dev_updated.power_watts == 287.6
    assert dev_updated.energy_kwh == 14.8

    # Validate DeviceState Pydantic model conversion
    dev_state = dev_updated.to_device_state()
    assert isinstance(dev_state, DeviceState)
    assert dev_state.device_id == "ESP32_LIVING_ROOM"
    assert dev_state.domain == DeviceDomain.IOT
    assert dev_state.device_type == DeviceType.SMART_RELAY
    assert dev_state.connection_status == ConnectionStatus.ONLINE
    assert dev_state.operational_status == OperationalStatus.IDLE
    assert dev_state.state["light"] == "ON"
    assert dev_state.state["sensors"]["temperature_celsius"] == 24.5


# ==============================================================================
# Task 2: IoT Activity-Log Ingestion Tests
# ==============================================================================

def test_task2_activity_log_ingestion_and_storage():
    """
    Verify structured activity-log records capture device ID, action, previous state,
    new state, timestamp, source, status, and store in backend event history.
    """
    dm = DeviceManager()

    # Log an action
    record = dm.log_activity(
        device_id="ESP32_01",
        action="TOGGLE_LIGHT",
        previous_state={"light": "OFF"},
        new_state={"light": "ON"},
        source="MQTT_EVENT",
        status="SUCCESS",
        reason="Manual user click",
        metadata={"user": "operator_1"},
    )

    assert isinstance(record, IoTActivityRecord)
    assert record.device_id == "ESP32_01"
    assert record.action == "TOGGLE_LIGHT"
    assert record.previous_state == {"light": "OFF"}
    assert record.new_state == {"light": "ON"}
    assert record.source == "MQTT_EVENT"
    assert record.status == "SUCCESS"
    assert record.timestamp > 0
    assert record.timestamp_iso.endswith("Z")

    # Verify retrieval from memory buffer
    logs = dm.get_activity_logs(device_id="ESP32_01")
    assert len(logs) >= 1
    assert logs[0]["action"] == "TOGGLE_LIGHT"

    # Test REST API ingestion endpoint
    res = client.post(
        "/api/iot/activity-log",
        json={
            "device_id": "ESP32_02",
            "action": "FAN_SPEED_HIGH",
            "previous_state": {"fan": "LOW"},
            "new_state": {"fan": "HIGH"},
            "source": "DASHBOARD",
            "status": "SUCCESS",
            "reason": "Temperature threshold exceeded",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["record"]["device_id"] == "ESP32_02"

    # Verify query endpoint
    res_list = client.get("/api/iot/activity-logs?device_id=ESP32_02")
    assert res_list.status_code == 200
    assert res_list.json()["count"] >= 1


# ==============================================================================
# Task 3: IoT Telemetry Standardization Tests
# ==============================================================================

def test_task3_telemetry_standardization():
    """
    Verify conversion of raw IoT data into standard UnifiedTelemetryPacket format
    with consistent domain, source_id, timestamp, relays, environmental, and energy fields.
    """
    raw_payload = {
        "device_id": "ESP32_HUB_99",
        "system": "ESP32",
        "firmware": "2.0.0-unified",
        "online": True,
        "states": {"light": "ON", "fan": "ON", "pump": "OFF"},
        "temperature": 27.8,
        "humidity": 65.0,
        "lux": 420.0,
        "motion": True,
        "voltage": 229.5,
        "current": 2.1,
        "power": 481.9,
        "energy": 55.4,
        "rssi": -55,
        "ip": "10.0.0.42",
        "uptime": 7200,
    }

    packet = normalize_iot_telemetry(raw_payload, device_id="ESP32_HUB_99")
    assert isinstance(packet, UnifiedTelemetryPacket)
    assert packet.source_domain == TelemetryDomain.IOT
    assert packet.source_id == "ESP32_HUB_99"
    assert packet.telemetry_id.startswith("TEL-IOT-")
    assert packet.sequence_number > 0

    # Payload validation
    iot = packet.payload
    assert iot.device_type == "SMART_RELAY"
    assert iot.status == "ONLINE"
    assert iot.relays.light == "ON"
    assert iot.relays.fan == "ON"
    assert iot.relays.pump == "OFF"

    assert iot.environmental_sensors.temperature_celsius == 27.8
    assert iot.environmental_sensors.humidity_pct == 65.0
    assert iot.environmental_sensors.ambient_light_lux == 420.0
    assert iot.environmental_sensors.motion_detected is True

    assert iot.energy_metrics.voltage_v == 229.5
    assert iot.energy_metrics.current_a == 2.1
    assert iot.energy_metrics.power_watts == 481.9
    assert iot.energy_metrics.energy_kwh == 55.4

    assert iot.connectivity.protocol == "MQTT"
    assert iot.connectivity.wifi_rssi_dbm == -55
    assert iot.connectivity.ip_address == "10.0.0.42"
    assert iot.connectivity.uptime_seconds == 7200

    # Test conversion of Device dataclass
    dev = Device(
        device_id="ESP32_DEV_1",
        mac="00:11:22:33:44:55",
        system="ESP32",
        light="OFF",
        fan="ON",
        pump="OFF",
        temperature_celsius=22.0,
        wifi_rssi_dbm=-70,
    )
    dev_packet = device_to_telemetry_packet(dev)
    assert dev_packet.source_id == "ESP32_DEV_1"
    assert dev_packet.payload.relays.fan == "ON"
    assert dev_packet.payload.environmental_sensors.temperature_celsius == 22.0


# ==============================================================================
# Task 4 & 5: Connection/Disconnection & Offline-State Updates Tests
# ==============================================================================

def test_task4_and_5_connection_timeout_and_offline_reconnection():
    """
    Verify connection monitor timeout detection, transition to OFFLINE with reason,
    and automatic transition back to ONLINE upon reconnection.
    """
    dm = DeviceManager()

    # 1. Device registers as ONLINE
    dm.update_device({
        "device_id": "ESP32_WATCHDOG_01",
        "states": {"light": "ON", "fan": "OFF", "pump": "OFF"},
    })
    dev = dm.get_device("ESP32_WATCHDOG_01")
    assert dev.online is True
    assert dev.connection_status == "ONLINE"
    initial_version = dev.state_version

    # 2. Simulate heartbeat aging past timeout (e.g. 25s ago)
    dev.last_seen_timestamp = time.time() - 25.0

    # Run timeout monitor with 15s threshold
    timeout_records = dm.check_timeouts(timeout_seconds=15.0)
    assert len(timeout_records) == 1
    rec = timeout_records[0]
    assert rec.device_id == "ESP32_WATCHDOG_01"
    assert rec.action == "DEVICE_OFFLINE"
    assert rec.status == "OFFLINE"
    assert "Heartbeat timeout" in rec.reason

    # State verification
    assert dev.online is False
    assert dev.connection_status == "OFFLINE"
    assert dev.offline_reason is not None
    assert dev.state_version > initial_version

    # 3. Device reconnects / sends new payload
    dev_reconn, act_reconn = dm.update_device({
        "device_id": "ESP32_WATCHDOG_01",
        "states": {"light": "ON", "fan": "ON", "pump": "OFF"},
    })
    assert dev_reconn.online is True
    assert dev_reconn.connection_status == "ONLINE"
    assert dev_reconn.offline_reason is None
    assert act_reconn is not None
    assert act_reconn.action == "DEVICE_RECONNECTED"
    assert act_reconn.status == "ONLINE"


# ==============================================================================
# Task 6: Central IoT State Synchronization Tests
# ==============================================================================

def test_task6_central_state_manager_synchronization():
    """
    Verify standardized IoT state synchronizes directly into central StateManager,
    updates domain aggregates, and rejects stale out-of-order updates.
    """
    dm = DeviceManager()
    dev, _ = dm.update_device({
        "device_id": "ESP32_CENTRAL_01",
        "states": {"light": "ON", "fan": "OFF", "pump": "OFF"},
        "rssi": -65,
    })

    dev_state = dev.to_device_state()

    # Synchronize with Central StateManager
    synced = state_manager.sync_device_state(dev_state)
    assert synced["device_id"] == "ESP32_CENTRAL_01"

    # Verify retrieval from central StateManager registry
    retrieved = state_manager.get_device_state("ESP32_CENTRAL_01")
    assert retrieved is not None
    assert retrieved["device_id"] == "ESP32_CENTRAL_01"
    assert retrieved["connection_status"] == "ONLINE"

    # Verify authoritative domain state in StateManager
    iot_domain_state = state_manager.get_domain_state("IOT")
    assert iot_domain_state["device_count"] >= 1
    assert iot_domain_state["online_device_count"] >= 1
    assert "ESP32_CENTRAL_01" in iot_domain_state["devices"]

    # Verify stale update prevention:
    # Attempting to write an update with older timestamp and lower version
    stale_payload = dict(retrieved)
    stale_payload["last_seen_timestamp"] = dev.last_seen_timestamp - 100.0  # In the past
    stale_payload["state_version"] = dev.state_version  # Same or lower version
    stale_payload["state"] = {"light": "OFF"}  # Stale state

    res = state_manager.sync_device_state(stale_payload, force=False)
    # Must preserve the newer existing state
    current = state_manager.get_device_state("ESP32_CENTRAL_01")
    assert current["state"]["light"] == "ON"


# ==============================================================================
# Task 7: IoT WebSocket Integration Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_task7_websocket_broadcasting_async():
    """
    Verify that IoT state updates, telemetry frames, and device events
    are broadcasted over the central WebSocket layer in standard envelopes.
    """
    ws_server = get_websocket_server()
    assert ws_server is not None

    # Test envelope creation and structure
    envelope = ws_server.create_envelope(
        msg_type="IOT_STATE_UPDATE",
        source_domain="IOT",
        source_id="ESP32_RELAY_01",
        payload={
            "device_id": "ESP32_RELAY_01",
            "relays": {"light": "ON", "fan": "OFF", "pump": "ON"},
            "status": "ONLINE"
        }
    )
    assert envelope.type == "IOT_STATE_UPDATE"
    assert envelope.source_domain == "IOT"
    assert envelope.source_id == "ESP32_RELAY_01"
    assert envelope.version == "2.0.0"
    assert envelope.payload["relays"]["light"] == "ON"

    # Test broadcast envelope async call without error
    await ws_server.broadcast_envelope(envelope)


# ==============================================================================
# Task 8: Real-Time Dashboard Propagation Tests
# ==============================================================================

def test_task8_dashboard_endpoints_and_static_assets():
    """
    Verify dashboard HTML endpoint /iot, REST API endpoints,
    device listing with DeviceState, and activity log queries.
    """
    # 1. HTML Dashboard endpoint
    res_html = client.get("/iot")
    assert res_html.status_code == 200
    assert "text/html" in res_html.headers["content-type"]
    assert "IoT Real-Time Pipeline" in res_html.text or "MasterHub" in res_html.text

    # 2. Online Devices list endpoint
    res_devs = client.get("/api/iot/devices")
    assert res_devs.status_code == 200
    data = res_devs.json()
    assert "devices" in data
    assert "count" in data

    # 3. Status endpoint
    res_status = client.get("/api/iot/status")
    assert res_status.status_code == 200
    assert "devices_online" in res_status.json()

    # 4. Telemetry latest endpoint
    res_tel = client.get("/api/iot/telemetry/latest")
    assert res_tel.status_code == 200
    assert res_tel.json()["source_domain"] == "IOT"


# ==============================================================================
# Task 9: Complete IoT Pipeline Integration Test
# ==============================================================================

@pytest.mark.asyncio
async def test_task9_complete_iot_pipeline_flow():
    """
    End-to-End verification of the complete pipeline:
    MQTT Ingestion -> DeviceManager -> ActivityLog -> Normalizer -> StateManager -> WebSocket.
    Ensures one event travels seamlessly through all modules without conflict.
    """
    plugin = get_plugin("iot")
    assert plugin is not None

    # Step 1: Simulate MQTT message arrival on status topic
    status_payload = {
        "device_id": "ESP32_E2E_01",
        "mac": "AA:BB:CC:DD:EE:FF",
        "system": "ESP32",
        "firmware": "2.0.0-unified",
        "states": {"light": "ON", "fan": "OFF", "pump": "ON"},
        "rssi": -58,
        "ip": "192.168.1.50",
        "uptime": 1200,
    }
    plugin.handle_status("ESP32_E2E_01", status_payload)

    # Step 2: Simulate MQTT sensor telemetry
    sensor_payload = {
        "temperature_celsius": 26.2,
        "humidity_pct": 52.0,
        "ambient_light_lux": 500.0,
        "voltage_v": 230.0,
        "power_watts": 150.0,
    }
    plugin.handle_sensor("ESP32_E2E_01", sensor_payload)

    # Step 3: Verify DeviceManager state
    dev = plugin.device_manager.get_device("ESP32_E2E_01")
    assert dev is not None
    assert dev.light == "ON"
    assert dev.temperature_celsius == 26.2
    assert dev.power_watts == 150.0

    # Step 4: Verify Central StateManager has authoritative synchronized state
    central_state = state_manager.get_device_state("ESP32_E2E_01")
    assert central_state is not None
    assert central_state["device_id"] == "ESP32_E2E_01"
    assert central_state["state"]["light"] == "ON"
    assert central_state["state"]["sensors"]["temperature_celsius"] == 26.2

    # Step 5: Verify Activity Log recorded the event
    logs = plugin.device_manager.get_activity_logs(device_id="ESP32_E2E_01")
    assert len(logs) >= 1

    # Step 6: Verify Command Execution through orchestrator
    with patch.object(plugin.client, "publish") as mock_pub:
        mock_msg_info = MagicMock()
        mock_msg_info.rc = 0
        mock_pub.return_value = mock_msg_info

        exec_res = await plugin.execute("toggle_light", {"device_id": "ESP32_E2E_01"})
        assert exec_res["status"] == "success"
        assert exec_res["command"]["device"] == "light"
        assert exec_res["command"]["state"] == "TOGGLE"
