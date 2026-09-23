"""
test_embedded_telemetry_standard.py
====================================
Comprehensive tests for Standardized Embedded Telemetry Schema and Normalizer
covering movement, speed, battery, status, subplugin conversions, and API integration.
"""

import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from models.telemetry_models import (
    EmbeddedTelemetry,
    KinematicsTelemetry,
    SafetyRangingTelemetry,
    SystemHealthTelemetry,
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
from plugins.embedded.subplugins.rc_car.plugin import RcCarPlugin
from plugins.embedded.subplugins.wheelchair.plugin import WheelchairPlugin
from api.telemetry_routes import telemetry_router


# ==============================================================================
# 1. Movement Normalization Tests
# ==============================================================================

def test_movement_normalization_directions():
    assert normalize_movement("FORWARD") == "FORWARD"
    assert normalize_movement("BACKWARD") == "BACKWARD"
    assert normalize_movement("LEFT") == "LEFT"
    assert normalize_movement("RIGHT") == "RIGHT"
    assert normalize_movement("LEFT360") == "LEFT360"
    assert normalize_movement("RIGHT360") == "RIGHT360"
    assert normalize_movement("STOP") == "STOP"
    assert normalize_movement("IDLE") == "IDLE"


def test_movement_normalization_bci_and_legacy_aliases():
    # BCI commands
    assert normalize_movement("PUSH") == "FORWARD"
    assert normalize_movement("PULL") == "BACKWARD"
    
    # Legacy strings
    assert normalize_movement("CAR FORWARD EXECUTED") == "FORWARD"
    assert normalize_movement("CAR BACKWARD EXECUTED") == "BACKWARD"
    assert normalize_movement("FRONT OBSTACLE DETECTED") == "STOP"
    assert normalize_movement("REVERSE") == "BACKWARD"
    assert normalize_movement("SPIN_LEFT") == "LEFT360"
    assert normalize_movement("SPIN_RIGHT") == "RIGHT360"


# ==============================================================================
# 2. Speed Normalization Tests
# ==============================================================================

def test_speed_normalization_scalar():
    assert normalize_speed(0.75, movement="FORWARD") == 0.75
    assert normalize_speed("0.45", movement="FORWARD") == 0.45
    assert normalize_speed(0.0, movement="FORWARD") == 0.0


def test_speed_normalization_pwm():
    # 255 PWM -> ~1.0
    assert normalize_speed(None, movement="FORWARD", speed_pwm=255) == 1.0
    # 128 PWM -> ~0.502
    assert normalize_speed(None, movement="FORWARD", speed_pwm=128) == 0.502


def test_speed_normalization_speed_modes():
    assert normalize_speed(None, movement="FORWARD", speed_mode="SLOW") == 0.3
    assert normalize_speed(None, movement="FORWARD", speed_mode="NORMAL") == 0.6
    assert normalize_speed(None, movement="FORWARD", speed_mode="FAST") == 0.85
    assert normalize_speed(None, movement="FORWARD", speed_mode="TURBO") == 1.0
    assert normalize_speed(None, movement="STOP", speed_mode="TURBO") == 0.0


# ==============================================================================
# 3. Status Normalization Tests
# ==============================================================================

def test_status_normalization():
    assert normalize_status("ONLINE") == "ONLINE"
    assert normalize_status("OFFLINE") == "OFFLINE"
    assert normalize_status("DISCONNECTED") == "OFFLINE"
    assert normalize_status("EXECUTING", movement="FORWARD") == "MOVING"
    assert normalize_status("EXECUTING", movement="STOP") == "ONLINE"
    assert normalize_status("TIMEOUT") == "TIMEOUT"
    assert normalize_status("ERROR") == "ERROR"
    assert normalize_status("DEGRADED") == "DEGRADED"
    assert normalize_status(None, movement="FORWARD") == "MOVING"
    assert normalize_status(None, movement="STOP") == "ONLINE"


# ==============================================================================
# 4. Battery & Supply Voltage Validation Tests
# ==============================================================================

def test_battery_and_voltage_validation():
    # Battery valid
    assert validate_battery_soc(85) == 85
    assert validate_battery_soc("92%") == 92
    assert validate_battery_soc(0) == 0
    assert validate_battery_soc(100) == 100

    # Battery invalid
    assert validate_battery_soc(-5) is None
    assert validate_battery_soc(110) is None
    assert validate_battery_soc(True) is None
    assert validate_battery_soc(False) is None
    assert validate_battery_soc("invalid") is None

    # Voltage
    assert validate_supply_voltage(12.6) == 12.6
    assert validate_supply_voltage("24.0V") == 24.0
    assert validate_supply_voltage(0.0) == 0.0
    assert validate_supply_voltage(-3.3) is None
    assert validate_supply_voltage(True) is None


# ==============================================================================
# 5. Full Embedded Telemetry Normalization Tests
# ==============================================================================

def test_normalize_embedded_telemetry_dict():
    raw = {
        "device_id": "ROBOTCAR_01",
        "movement": "FORWARD",
        "speed": 0.65,
        "speed_pwm": 180,
        "speed_mode": "NORMAL",
        "battery_soc_pct": 88,
        "supply_voltage_v": 12.4,
        "free_heap_bytes": 192000,
        "cpu_core_temp_c": 38.5,
        "front_distance": 45.0,
        "status": "ONLINE"
    }

    packet = normalize_embedded_telemetry(raw)
    assert isinstance(packet, UnifiedTelemetryPacket)
    assert packet.source_domain == TelemetryDomain.EMBEDDED
    assert packet.source_id == "ROBOTCAR_01"

    payload = packet.payload
    assert isinstance(payload, EmbeddedTelemetry)
    assert payload.device_id == "ROBOTCAR_01"
    assert payload.status == "ONLINE"
    assert payload.device_mode == "RC_CAR"

    # Movement and Speed unified
    assert payload.kinematics.movement == "FORWARD"
    assert payload.kinematics.state == "MOVING_FORWARD"
    assert payload.kinematics.speed == 0.65
    assert payload.kinematics.speed_pwm == 180
    assert payload.kinematics.speed_mode == "NORMAL"

    # Battery unified
    assert payload.system_health.battery_soc_pct == 88
    assert payload.system_health.supply_voltage_v == 12.4
    assert payload.system_health.free_heap_bytes == 192000
    assert payload.system_health.cpu_core_temp_c == 38.5

    # Safety and Ranging
    assert payload.safety_and_ranging is not None
    assert payload.safety_and_ranging.ultrasonic_front_distance_cm == 45.0


def test_normalize_embedded_telemetry_wheelchair():
    raw = {
        "device_id": "WHEELCHAIR_01",
        "device_mode": "WHEELCHAIR",
        "command": "PUSH",
        "speed": 0.8,
        "battery": 74,
        "voltage": 24.2,
        "status": "MOVING"
    }

    packet = normalize_embedded_telemetry(raw)
    payload = packet.payload
    assert payload.device_mode == "WHEELCHAIR"
    assert payload.kinematics.movement == "FORWARD"
    assert payload.kinematics.speed == 0.8
    assert payload.system_health.battery_soc_pct == 74
    assert payload.system_health.supply_voltage_v == 24.2
    assert payload.status == "MOVING"


def test_normalize_embedded_telemetry_raw_mqtt_string():
    raw_str = "CAR FORWARD EXECUTED"
    packet = normalize_embedded_telemetry(raw_str, device_id="CAR-02")
    payload = packet.payload
    assert payload.device_id == "CAR-02"
    assert payload.kinematics.movement == "FORWARD"
    assert payload.kinematics.state == "MOVING_FORWARD"
    assert payload.status == "ONLINE"


# ==============================================================================
# 6. Subplugin Conversion Tests
# ==============================================================================

def test_rc_car_subplugin_conversion():
    rc = RcCarPlugin()
    st = rc.status()
    packet = subplugin_to_telemetry_packet(st, device_id="RC_CAR_TEST")
    payload = packet.payload

    assert packet.source_domain == TelemetryDomain.EMBEDDED
    assert payload.device_mode == "RC_CAR"
    assert payload.kinematics.movement == "STOP"
    assert payload.kinematics.speed == 0.0
    assert payload.status in ("STOPPED", "OFFLINE", "ONLINE", "TIMEOUT")


def test_wheelchair_subplugin_conversion():
    wc = WheelchairPlugin()
    st = wc.status()
    packet = subplugin_to_telemetry_packet(st, device_id="WHEELCHAIR_TEST")
    payload = packet.payload

    assert packet.source_domain == TelemetryDomain.EMBEDDED
    assert payload.device_mode == "WHEELCHAIR"
    assert payload.kinematics.movement == "STOP"
    assert payload.status in ("STOPPED", "ONLINE", "MOVING")


# ==============================================================================
# 7. Telemetry API Endpoint Tests with Standardized Embedded Telemetry
# ==============================================================================

def test_embedded_telemetry_api_pipeline():
    app = FastAPI()
    app.include_router(telemetry_router)
    client = TestClient(app)

    # 1. Ingest valid Embedded packet
    embedded_payload = {
        "source_domain": "EMBEDDED",
        "source_id": "CAR_REST_01",
        "session_id": "SES-EMB-100",
        "payload": {
            "device_id": "CAR_REST_01",
            "device_mode": "RC_CAR",
            "mcu_architecture": "ESP32-WROOM-32",
            "firmware_version": "2.0.0-unified",
            "status": "ONLINE",
            "system_health": {
                "free_heap_bytes": 180000,
                "cpu_core_temp_c": 40.2,
                "battery_soc_pct": 91,
                "supply_voltage_v": 12.5
            },
            "kinematics": {
                "movement": "FORWARD",
                "state": "MOVING_FORWARD",
                "speed": 0.6,
                "speed_mode": "NORMAL",
                "motor_left_pwm": 180,
                "motor_right_pwm": 180
            },
            "safety_and_ranging": {
                "ultrasonic_front_distance_cm": 60.0,
                "collision_detected": False
            }
        }
    }

    res = client.post("/api/v1/telemetry", json=embedded_payload)
    assert res.status_code == 200
    res_data = res.json()
    assert res_data["status"] == "success"
    assert res_data["domain"] == "EMBEDDED"

    # 2. Retrieve latest EMBEDDED telemetry
    latest_res = client.get("/api/v1/telemetry/latest?domain=EMBEDDED")
    assert latest_res.status_code == 200
    latest_data = latest_res.json()
    assert latest_data["status"] == "success"
    assert latest_data["domain"] == "EMBEDDED"
    
    p = latest_data["telemetry"]["payload"]
    assert p["device_id"] == "CAR_REST_01"
    assert p["status"] == "ONLINE"
    assert p["kinematics"]["movement"] == "FORWARD"
    assert p["kinematics"]["speed"] == 0.6
    assert p["system_health"]["battery_soc_pct"] == 91
    assert p["system_health"]["supply_voltage_v"] == 12.5


# ==============================================================================
# 8. Schema Export Verification for Unified Embedded Fields
# ==============================================================================

def test_embedded_schema_definitions():
    schema = UnifiedTelemetryPacket.model_json_schema()
    defs = schema["$defs"]

    assert "EmbeddedTelemetry" in defs
    assert "KinematicsTelemetry" in defs
    assert "SystemHealthTelemetry" in defs

    emb_props = defs["EmbeddedTelemetry"]["properties"]
    assert "device_id" in emb_props
    assert "status" in emb_props
    assert "firmware_version" in emb_props
    assert "system_health" in emb_props
    assert "kinematics" in emb_props

    kin_props = defs["KinematicsTelemetry"]["properties"]
    assert "movement" in kin_props
    assert "state" in kin_props
    assert "speed" in kin_props
    assert "speed_pwm" in kin_props
    assert "speed_mode" in kin_props
    assert "motor_left_pwm" in kin_props
    assert "motor_right_pwm" in kin_props

    health_props = defs["SystemHealthTelemetry"]["properties"]
    assert "battery_soc_pct" in health_props
    assert "supply_voltage_v" in health_props
    assert "free_heap_bytes" in health_props
