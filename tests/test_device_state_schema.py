"""
test_device_state_schema.py
===========================
Comprehensive tests for Member 4: Device-State JSON Schema and Models.
Tests validation, serialization, enum constraints, optional fields,
JSON schema conformity, and mapping from existing device-state structures across
IoT, Embedded, Robotics, and BCI domains.
"""

import json
from pathlib import Path
import pytest
from pydantic import ValidationError

from models.device_models import (
    BciDeviceState,
    ConnectionStatus,
    DeviceDomain,
    DeviceProtocol,
    DeviceState,
    DeviceType,
    EmbeddedKinematicState,
    IotRelayState,
    NetworkInfo,
    OperationalStatus,
)
from plugins.iot.device_manager import Device


SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "device_state_schema.json"


# ===========================================================================
# 1. Valid IoT Device State Tests
# ===========================================================================

def test_iot_device_state_valid():
    """Test standard IoT relay node device state creation and serialization."""
    net_info = NetworkInfo(
        ip_address="192.168.1.105",
        mac_address="24:6F:28:B2:A1:04",
        wifi_rssi_dbm=-58,
        uptime_seconds=3600
    )
    
    relay_state = IotRelayState(light="ON", fan="OFF", pump="OFF", power_state="ACTIVE").model_dump()

    device = DeviceState(
        device_id="ESP32_RELAY_01",
        device_name="Living Room Hub",
        domain=DeviceDomain.IOT,
        device_type=DeviceType.SMART_RELAY,
        protocol=DeviceProtocol.MQTT,
        connection_status=ConnectionStatus.ONLINE,
        operational_status=OperationalStatus.IDLE,
        capabilities=["left_light_on", "left_light_off", "toggle_fan", "toggle_pump"],
        last_seen_timestamp=1789540000.0,
        last_seen_iso="2026-09-17T06:30:00Z",
        firmware_version="2.0.0-unified",
        network_info=net_info,
        state=relay_state,
        metadata={"location": "Living Room", "system": "ESP32"}
    )

    data = device.to_dict()
    assert data["device_id"] == "ESP32_RELAY_01"
    assert data["domain"] == "IOT"
    assert data["device_type"] == "SMART_RELAY"
    assert data["protocol"] == "MQTT"
    assert data["connection_status"] == "ONLINE"
    assert data["operational_status"] == "IDLE"
    assert "left_light_on" in data["capabilities"]
    assert data["network_info"]["ip_address"] == "192.168.1.105"
    assert data["state"]["light"] == "ON"
    assert data["metadata"]["location"] == "Living Room"


# ===========================================================================
# 2. Valid Embedded / Robotics Device State Tests
# ===========================================================================

def test_embedded_rc_car_state_valid():
    """Test ESP32 RC Car robotics device state."""
    net_info = NetworkInfo(
        ip_address="192.168.4.1",
        mac_address="98:A3:16:BF:2C:C0",
        wifi_rssi_dbm=-45
    )

    car_state = EmbeddedKinematicState(
        motion_state="FORWARD",
        speed_mode="FAST",
        steering_angle_deg=15.0,
        emergency_stop=False,
        last_command="FORWARD"
    ).model_dump()

    device = DeviceState(
        device_id="ROBOT_CAR_ESP32",
        device_name="SynaptiMesh 3D RC Car",
        domain=DeviceDomain.ROBOTICS,
        device_type=DeviceType.RC_CAR,
        protocol=DeviceProtocol.MQTT,
        connection_status=ConnectionStatus.ONLINE,
        operational_status=OperationalStatus.EXECUTING,
        capabilities=["FORWARD", "BACKWARD", "LEFT", "RIGHT", "LEFT360", "RIGHT360", "STOP"],
        firmware_version="1.4.2-robotics",
        network_info=net_info,
        state=car_state,
        metadata={"motor_driver": "L298N", "mcu": "ESP32"}
    )

    data = device.to_dict()
    assert data["domain"] == "ROBOTICS"
    assert data["device_type"] == "RC_CAR"
    assert data["state"]["motion_state"] == "FORWARD"
    assert data["state"]["speed_mode"] == "FAST"
    assert data["operational_status"] == "EXECUTING"


def test_embedded_wheelchair_state_valid():
    """Test smart wheelchair embedded device state."""
    wheelchair_state = {
        "motion_state": "STOP",
        "speed_mode": "SLOW",
        "drive_mode": "INDOOR",
        "battery_soc_pct": 92
    }

    device = DeviceState(
        device_id="WHEELCHAIR_01",
        device_name="Smart Wheelchair Unit 1",
        domain=DeviceDomain.EMBEDDED,
        device_type=DeviceType.WHEELCHAIR,
        protocol=DeviceProtocol.MQTT,
        connection_status=ConnectionStatus.ONLINE,
        operational_status=OperationalStatus.IDLE,
        capabilities=["FORWARD", "BACKWARD", "LEFT", "RIGHT", "STOP"],
        state=wheelchair_state
    )

    assert device.domain == "EMBEDDED"
    assert device.device_type == "WHEELCHAIR"
    assert device.state["drive_mode"] == "INDOOR"


# ===========================================================================
# 3. Valid BCI Device State Tests
# ===========================================================================

def test_bci_device_state_valid():
    """Test BCI Headset device state."""
    headset_state = BciDeviceState(
        battery_pct=88,
        signal_quality_summary="EXCELLENT",
        active_profile="Mubee_Neutral_Push_Left",
        headset_model="Emotiv EPOC X"
    ).model_dump()

    device = DeviceState(
        device_id="EPOCX-98214",
        device_name="Emotiv EPOC X Headset",
        domain=DeviceDomain.BCI,
        device_type=DeviceType.BCI_HEADSET,
        protocol=DeviceProtocol.BLE,
        connection_status=ConnectionStatus.ONLINE,
        operational_status=OperationalStatus.IDLE,
        capabilities=["RAW_EEG", "MENTAL_COMMANDS", "FREQUENCY_BANDS", "CONTACT_QUALITY"],
        state=headset_state,
        metadata={"channels_count": 14, "sampling_rate_hz": 128}
    )

    data = device.to_dict()
    assert data["domain"] == "BCI"
    assert data["device_type"] == "BCI_HEADSET"
    assert data["protocol"] == "BLE"
    assert data["state"]["battery_pct"] == 88
    assert data["state"]["signal_quality_summary"] == "EXCELLENT"


# ===========================================================================
# 4. Invalid Enum and Constraint Validation Tests
# ===========================================================================

def test_invalid_domain_raises_validation_error():
    with pytest.raises(ValidationError):
        DeviceState(
            device_id="DEV_01",
            domain="INVALID_DOMAIN",  # Not in DeviceDomain enum
            device_type=DeviceType.SMART_RELAY
        )


def test_invalid_device_type_raises_validation_error():
    with pytest.raises(ValidationError):
        DeviceState(
            device_id="DEV_01",
            domain=DeviceDomain.IOT,
            device_type="FLYING_DRONE"  # Not in DeviceType enum
        )


def test_invalid_protocol_raises_validation_error():
    with pytest.raises(ValidationError):
        DeviceState(
            device_id="DEV_01",
            domain=DeviceDomain.IOT,
            device_type=DeviceType.SMART_RELAY,
            protocol="FTP_PROTOCOL"  # Not in DeviceProtocol enum
        )


def test_invalid_connection_status_raises_validation_error():
    with pytest.raises(ValidationError):
        DeviceState(
            device_id="DEV_01",
            domain=DeviceDomain.IOT,
            device_type=DeviceType.SMART_RELAY,
            connection_status="HALF_ONLINE"  # Not in ConnectionStatus enum
        )


def test_invalid_operational_status_raises_validation_error():
    with pytest.raises(ValidationError):
        DeviceState(
            device_id="DEV_01",
            domain=DeviceDomain.IOT,
            device_type=DeviceType.SMART_RELAY,
            operational_status="BLOCKED_PERMANENTLY"  # Not in OperationalStatus enum
        )


# ===========================================================================
# 5. Defaults and Optional Fields Tests
# ===========================================================================

def test_device_state_defaults():
    """Test that default values are correctly populated for minimal input."""
    device = DeviceState(
        device_id="DEV_MINIMAL",
        domain=DeviceDomain.IOT,
        device_type=DeviceType.SMART_RELAY
    )

    assert device.protocol == "MQTT"
    assert device.connection_status == "ONLINE"
    assert device.operational_status == "IDLE"
    assert device.capabilities == []
    assert device.state == {}
    assert device.metadata == {}
    assert device.last_seen_timestamp > 0
    assert "Z" in device.last_seen_iso


# ===========================================================================
# 6. JSON Schema Export & Conformity Tests
# ===========================================================================

def test_json_schema_file_exists_and_valid():
    """Verify that schemas/device_state_schema.json exists and matches DeviceState."""
    assert SCHEMA_PATH.exists(), f"Schema file not found at {SCHEMA_PATH}"
    
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema_data = json.load(f)

    assert "$defs" in schema_data
    assert "DeviceDomain" in schema_data["$defs"]
    assert "DeviceType" in schema_data["$defs"]
    assert "DeviceProtocol" in schema_data["$defs"]
    assert "ConnectionStatus" in schema_data["$defs"]
    assert "OperationalStatus" in schema_data["$defs"]

    generated = DeviceState.model_json_schema()
    assert generated["title"] == schema_data["title"]


def test_jsonschema_instance_validation():
    """Validate instances against the JSON Schema using jsonschema validator."""
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema library not installed, skipping jsonschema validation.")

    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema_data = json.load(f)

    device = DeviceState(
        device_id="ESP32_RELAY_02",
        domain=DeviceDomain.IOT,
        device_type=DeviceType.SMART_RELAY,
        capabilities=["left_light_on"],
        state={"light": "ON"}
    )
    
    instance = json.loads(device.model_dump_json())
    # Should not raise
    jsonschema.validate(instance=instance, schema=schema_data)


# ===========================================================================
# 7. Integration & Mapping from Existing Structures Tests
# ===========================================================================

def test_mapping_from_iot_device_dataclass():
    """Test factory mapping from plugins.iot.device_manager.Device."""
    legacy_device = Device(
        device_id="ESP32_RELAY_01",
        mac="24:6F:28:B2:A1:04",
        system="ESP32",
        light="ON",
        fan="OFF",
        pump="OFF",
        firmware="2.0.0-unified",
        last_seen="12:00:00",
        last_seen_timestamp=1789540000.0,
        online=True,
        wifi_rssi_dbm=-62,
        ip_address="192.168.1.55",
        uptime_seconds=1800
    )

    mapped_state = DeviceState.from_iot_device(legacy_device)

    assert mapped_state.device_id == "ESP32_RELAY_01"
    assert mapped_state.domain == "IOT"
    assert mapped_state.device_type == "SMART_RELAY"
    assert mapped_state.connection_status == "ONLINE"
    assert mapped_state.state["light"] == "ON"
    assert mapped_state.state["fan"] == "OFF"
    assert mapped_state.network_info.ip_address == "192.168.1.55"
    assert mapped_state.network_info.mac_address == "24:6F:28:B2:A1:04"
    assert mapped_state.firmware_version == "2.0.0-unified"


def test_mapping_from_offline_iot_device():
    """Test mapping offline IoT device sets connection and operational status."""
    offline_device = {
        "device_id": "ESP32_OFFLINE",
        "mac": "24:6F:28:00:00:00",
        "online": False,
        "light": "OFF",
        "fan": "OFF",
        "pump": "OFF"
    }

    mapped = DeviceState.from_iot_device(offline_device)
    assert mapped.connection_status == "OFFLINE"
    assert mapped.operational_status == "ERROR"


def test_mapping_from_embedded_status():
    """Test factory mapping from embedded RC car and Wheelchair status payloads."""
    car_status = {
        "status": "ONLINE",
        "online": True,
        "state": "FORWARD",
        "speed_mode": "FAST",
        "last_command": "FORWARD",
        "ip_address": "192.168.4.1",
        "mac_address": "98:A3:16:BF:2C:C0"
    }

    mapped_car = DeviceState.from_embedded_status("CAR_01", car_status, target_type="RC_CAR")
    assert mapped_car.domain == "ROBOTICS"
    assert mapped_car.device_type == "RC_CAR"
    assert mapped_car.connection_status == "ONLINE"
    assert mapped_car.state["motion_state"] == "FORWARD"
    assert mapped_car.state["speed_mode"] == "FAST"
    assert "FORWARD" in mapped_car.capabilities
    assert "LEFT360" in mapped_car.capabilities

    chair_status = {
        "status": "ONLINE",
        "state": "STOP",
        "speed_mode": "NORMAL"
    }
    mapped_chair = DeviceState.from_embedded_status("CHAIR_01", chair_status, target_type="WHEELCHAIR")
    assert mapped_chair.domain == "EMBEDDED"
    assert mapped_chair.device_type == "WHEELCHAIR"
    assert "LEFT360" not in mapped_chair.capabilities
