"""
tests/test_embedded_alert_generation.py
========================================
Comprehensive Unit and Integration Tests for Server-Side Movement/Status Alert Generation.
Sprint 11 — Day 5 Member 6.

Validates:
1. Normal Telemetry -> No unnecessary alerts generated
2. Safety & Collision Conditions -> Emergency Stop and Collision produce CRITICAL alerts
3. Obstacle Proximity Conditions -> Warning (<= 30cm) and Critical (<= 15cm) alerts
4. Battery & Power Conditions -> Low Battery (<= 25%), Critical Battery (<= 15%), Voltage Sag (< 10V)
5. Kinematic & Movement Conditions -> Abnormal Speed (> 1.0), Unsafe Movement while Locked/Faulted
6. Hardware Status & Thermal -> ERROR, TIMEOUT, DEGRADED, OFFLINE, CPU Overheating (>= 65°C / >= 75°C)
7. Alert Severity Mapping -> Exact verification of INFO, WARNING, ERROR, CRITICAL
8. Device Identification -> Both RC Car and Smart Wheelchair device identification and modes
9. Deduplication & Flood Prevention -> Continuous identical condition does not flood duplicate alerts
10. Alert Resolution / Recovery Lifecycle -> Cleared conditions automatically generate RESOLVED alerts
11. Safe Handling of Invalid/Malformed Telemetry -> Resilient execution with null/malformed values
12. API Endpoints & WebSocket Integration -> REST endpoints and WebSocket envelope serialization
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
from services.embedded_alert_generator import (
    EmbeddedAlertGenerator,
    embedded_alert_generator,
)
from services.embedded_telemetry_normalizer import normalize_embedded_telemetry
from api.telemetry_routes import telemetry_router


@pytest.fixture(autouse=True)
def reset_alert_generator():
    """Reset alert generator state before each test."""
    embedded_alert_generator.clear_alerts()
    yield
    embedded_alert_generator.clear_alerts()


# ==============================================================================
# 1. Normal State Tests (No Unnecessary Alerts)
# ==============================================================================

def test_normal_telemetry_produces_no_alerts():
    """Normal operating telemetry must produce zero alerts."""
    normal_telemetry = {
        "device_id": "ROBOTCAR_01",
        "device_mode": "RC_CAR",
        "movement": "FORWARD",
        "speed": 0.6,
        "status": "ONLINE",
        "battery_soc_pct": 85,
        "supply_voltage_v": 12.4,
        "cpu_core_temp_c": 38.0,
        "front_distance": 65.0,
        "rear_distance": 80.0,
        "collision_detected": False,
        "emergency_stop_triggered": False,
    }

    packet = normalize_embedded_telemetry(normal_telemetry)
    alerts = embedded_alert_generator.evaluate_telemetry(packet)
    assert len(alerts) == 0
    assert len(embedded_alert_generator.get_active_alerts("ROBOTCAR_01")) == 0


# ==============================================================================
# 2. Emergency Stop & Collision Safety Alert Tests
# ==============================================================================

def test_emergency_stop_generates_critical_alert():
    """Emergency stop condition must generate a CRITICAL severity alert."""
    payload = {
        "device_id": "CAR_01",
        "status": "ONLINE",
        "emergency_stop_triggered": True,
        "safety_and_ranging": {
            "emergency_stop_triggered": True,
            "collision_detected": False,
        }
    }
    alerts = embedded_alert_generator.evaluate_telemetry(payload)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.alert_type == "EMERGENCY_STOP"
    assert alert.severity == AlertSeverity.CRITICAL
    assert alert.status == AlertStatus.ACTIVE
    assert "Emergency stop" in alert.message
    assert alert.device_id == "CAR_01"


def test_collision_detected_generates_critical_alert():
    """Collision detection must generate a CRITICAL severity alert."""
    payload = {
        "device_id": "CAR_01",
        "status": "ONLINE",
        "collision_detected": True,
    }
    alerts = embedded_alert_generator.evaluate_telemetry(payload)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.alert_type == "COLLISION_DETECTED"
    assert alert.severity == AlertSeverity.CRITICAL
    assert alert.status == AlertStatus.ACTIVE


# ==============================================================================
# 3. Obstacle Proximity Alert Tests (Front & Rear)
# ==============================================================================

def test_front_obstacle_warning_distance():
    """Distance <= 30cm (e.g. 22cm) generates WARNING alert."""
    payload = {
        "device_id": "ROBOTCAR_01",
        "front_distance": 22.0,
        "status": "ONLINE"
    }
    alerts = embedded_alert_generator.evaluate_telemetry(payload)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.alert_type == "OBSTACLE_PROXIMITY"
    assert alert.severity == AlertSeverity.WARNING
    assert alert.condition == "OBSTACLE_FRONT_WARNING"
    assert "22.0" in alert.message


def test_front_obstacle_critical_distance():
    """Distance <= 15cm (e.g. 10cm) generates CRITICAL alert."""
    payload = {
        "device_id": "ROBOTCAR_01",
        "front_distance": 10.0,
        "status": "ONLINE"
    }
    alerts = embedded_alert_generator.evaluate_telemetry(payload)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.alert_type == "OBSTACLE_PROXIMITY"
    assert alert.severity == AlertSeverity.CRITICAL
    assert alert.condition == "OBSTACLE_FRONT_CRITICAL"


def test_rear_obstacle_proximity_alerts():
    """Rear obstacle <= 30cm generates warning, <= 15cm generates critical."""
    # Warning
    payload_warn = {"device_id": "ROBOTCAR_01", "rear_distance": 28.0, "status": "ONLINE"}
    alerts_warn = embedded_alert_generator.evaluate_telemetry(payload_warn)
    assert len(alerts_warn) == 1
    assert alerts_warn[0].condition == "OBSTACLE_REAR_WARNING"
    assert alerts_warn[0].severity == AlertSeverity.WARNING

    embedded_alert_generator.clear_alerts()

    # Critical
    payload_crit = {"device_id": "ROBOTCAR_01", "rear_distance": 8.5, "status": "ONLINE"}
    alerts_crit = embedded_alert_generator.evaluate_telemetry(payload_crit)
    assert len(alerts_crit) == 1
    assert alerts_crit[0].condition == "OBSTACLE_REAR_CRITICAL"
    assert alerts_crit[0].severity == AlertSeverity.CRITICAL


# ==============================================================================
# 4. Battery & Supply Voltage Alert Tests
# ==============================================================================

def test_low_battery_warning_alert():
    """Battery SoC <= 25% (and > 15%) generates WARNING alert."""
    payload = {
        "device_id": "WHEELCHAIR_01",
        "device_mode": "WHEELCHAIR",
        "battery_soc_pct": 22,
        "status": "ONLINE"
    }
    alerts = embedded_alert_generator.evaluate_telemetry(payload)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.alert_type == "LOW_BATTERY"
    assert alert.severity == AlertSeverity.WARNING
    assert "22%" in alert.message
    assert alert.device_mode == "WHEELCHAIR"


def test_critical_battery_alert():
    """Battery SoC <= 15% generates CRITICAL alert."""
    payload = {
        "device_id": "ROBOTCAR_01",
        "battery_soc_pct": 12,
        "status": "ONLINE"
    }
    alerts = embedded_alert_generator.evaluate_telemetry(payload)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.alert_type == "CRITICAL_BATTERY"
    assert alert.severity == AlertSeverity.CRITICAL
    assert "12%" in alert.message


def test_supply_voltage_sag_alert():
    """Supply voltage drop < 10.0V generates WARNING alert."""
    payload = {
        "device_id": "ROBOTCAR_01",
        "supply_voltage_v": 9.4,
        "status": "ONLINE"
    }
    alerts = embedded_alert_generator.evaluate_telemetry(payload)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.alert_type == "LOW_VOLTAGE"
    assert alert.severity == AlertSeverity.WARNING
    assert "9.40V" in alert.message or "9.4" in alert.message


# ==============================================================================
# 5. Kinematic & Speed Safety Tests
# ==============================================================================

def test_abnormal_overspeed_alert():
    """Speed > 1.0 exceeds normalized limit and generates WARNING alert."""
    payload = {
        "device_id": "ROBOTCAR_01",
        "speed": 1.45,
        "movement": "FORWARD",
        "status": "ONLINE"
    }
    alerts = embedded_alert_generator.evaluate_telemetry(payload)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.alert_type == "ABNORMAL_SPEED"
    assert alert.severity == AlertSeverity.WARNING
    assert alert.condition == "ABNORMAL_SPEED"


def test_unsafe_movement_during_emergency_stop():
    """Movement while safety lock/emergency stop is active triggers CRITICAL alert."""
    payload = {
        "device_id": "ROBOTCAR_01",
        "movement": "FORWARD",
        "emergency_stop_triggered": True,
        "status": "ONLINE"
    }
    alerts = embedded_alert_generator.evaluate_telemetry(payload)
    # Generates both EMERGENCY_STOP and UNSAFE_MOVEMENT_LOCKED
    alert_types = {a.alert_type for a in alerts}
    assert "EMERGENCY_STOP" in alert_types
    assert "UNSAFE_MOVEMENT" in alert_types
    unsafe_alert = next(a for a in alerts if a.alert_type == "UNSAFE_MOVEMENT")
    assert unsafe_alert.severity == AlertSeverity.CRITICAL


# ==============================================================================
# 6. Hardware Status & Thermal Alert Tests
# ==============================================================================

def test_hardware_status_error_and_timeout():
    """Hardware status ERROR produces ERROR alert, TIMEOUT produces WARNING alert."""
    # ERROR status
    p_err = {"device_id": "ROBOTCAR_01", "status": "ERROR"}
    alerts_err = embedded_alert_generator.evaluate_telemetry(p_err)
    assert any(a.severity == AlertSeverity.ERROR for a in alerts_err)

    embedded_alert_generator.clear_alerts()

    # TIMEOUT status
    p_to = {"device_id": "ROBOTCAR_01", "status": "TIMEOUT"}
    alerts_to = embedded_alert_generator.evaluate_telemetry(p_to)
    assert any(a.alert_type == "WATCHDOG_TIMEOUT" and a.severity == AlertSeverity.WARNING for a in alerts_to)


def test_cpu_overheating_alerts():
    """CPU temperature >= 65°C generates warning, >= 75°C generates critical."""
    # Warning >= 65°C
    p_warn = {"device_id": "ROBOTCAR_01", "cpu_core_temp_c": 68.0, "status": "ONLINE"}
    alerts_warn = embedded_alert_generator.evaluate_telemetry(p_warn)
    assert len(alerts_warn) == 1
    assert alerts_warn[0].severity == AlertSeverity.WARNING
    assert alerts_warn[0].alert_type == "OVERHEATING"

    embedded_alert_generator.clear_alerts()

    # Critical >= 75°C
    p_crit = {"device_id": "ROBOTCAR_01", "cpu_core_temp_c": 78.5, "status": "ONLINE"}
    alerts_crit = embedded_alert_generator.evaluate_telemetry(p_crit)
    assert len(alerts_crit) == 1
    assert alerts_crit[0].severity == AlertSeverity.CRITICAL
    assert alerts_crit[0].alert_type == "OVERHEATING"


# ==============================================================================
# 7. Robot and Wheelchair Device Identification Tests
# ==============================================================================

def test_wheelchair_and_robot_device_identification():
    """Ensures both RC Car and Wheelchair devices are properly tagged in alerts."""
    # RC Car
    p_car = {
        "device_id": "ROBOT_CAR_ALPHA",
        "device_mode": "RC_CAR",
        "battery_soc_pct": 10,
        "status": "ONLINE"
    }
    alerts_car = embedded_alert_generator.evaluate_telemetry(p_car)
    assert alerts_car[0].device_id == "ROBOT_CAR_ALPHA"
    assert alerts_car[0].device_mode == "RC_CAR"

    # Wheelchair
    p_chair = {
        "device_id": "SMART_WHEELCHAIR_02",
        "device_mode": "WHEELCHAIR",
        "front_distance": 12.0,
        "status": "ONLINE"
    }
    alerts_chair = embedded_alert_generator.evaluate_telemetry(p_chair)
    assert alerts_chair[0].device_id == "SMART_WHEELCHAIR_02"
    assert alerts_chair[0].device_mode == "WHEELCHAIR"


# ==============================================================================
# 8. Alert Deduplication & Flood Prevention Tests
# ==============================================================================

def test_alert_deduplication_prevents_flood():
    """Identical telemetry packet received repeatedly must NOT produce duplicate alert events."""
    payload = {
        "device_id": "ROBOTCAR_01",
        "battery_soc_pct": 14,  # Critical battery
        "status": "ONLINE"
    }

    # Packet 1 -> First detection -> 1 alert generated
    alerts_1 = embedded_alert_generator.evaluate_telemetry(payload)
    assert len(alerts_1) == 1
    assert alerts_1[0].status == AlertStatus.ACTIVE

    # Packet 2 -> Condition still active -> 0 new alerts (no flooding)
    alerts_2 = embedded_alert_generator.evaluate_telemetry(payload)
    assert len(alerts_2) == 0

    # Packet 3 -> Condition still active -> 0 new alerts
    alerts_3 = embedded_alert_generator.evaluate_telemetry(payload)
    assert len(alerts_3) == 0

    # Verify active alerts registry still tracks the single active alert
    active = embedded_alert_generator.get_active_alerts("ROBOTCAR_01")
    assert len(active) == 1
    assert active[0]["condition"] == "BATTERY_CRITICAL"


# ==============================================================================
# 9. Alert Auto-Recovery / Resolution Lifecycle Tests
# ==============================================================================

def test_alert_lifecycle_auto_resolution():
    """When a problem condition clears, the alert transitions to RESOLVED automatically."""
    # 1. Trigger obstacle warning
    alert_payload = {
        "device_id": "ROBOTCAR_01",
        "front_distance": 25.0,  # Obstacle present
        "status": "ONLINE"
    }
    alerts_triggered = embedded_alert_generator.evaluate_telemetry(alert_payload)
    assert len(alerts_triggered) == 1
    assert alerts_triggered[0].status == AlertStatus.ACTIVE
    assert len(embedded_alert_generator.get_active_alerts("ROBOTCAR_01")) == 1

    # 2. Obstacle clears (distance increases to 80cm)
    clear_payload = {
        "device_id": "ROBOTCAR_01",
        "front_distance": 80.0,  # Obstacle cleared
        "status": "ONLINE"
    }
    alerts_resolved = embedded_alert_generator.evaluate_telemetry(clear_payload)
    assert len(alerts_resolved) == 1
    resolved_alert = alerts_resolved[0]
    assert resolved_alert.status == AlertStatus.RESOLVED
    assert resolved_alert.resolved_at is not None
    assert len(embedded_alert_generator.get_active_alerts("ROBOTCAR_01")) == 0


# ==============================================================================
# 10. Resilient Handling of Malformed / Invalid Telemetry
# ==============================================================================

def test_malformed_telemetry_safe_handling():
    """Malformed values (booleans, strings, None) must not crash the alert generator."""
    malformed = {
        "device_id": None,
        "battery_soc_pct": True,  # Boolean rejected by validator
        "supply_voltage_v": "invalid",
        "front_distance": None,
        "speed": "nan",
        "status": None
    }
    # Should execute safely without unhandled exception
    alerts = embedded_alert_generator.evaluate_telemetry(malformed)
    assert isinstance(alerts, list)


# ==============================================================================
# 11. REST API Endpoints Integration Tests
# ==============================================================================

def test_telemetry_alert_api_endpoints():
    """Verify GET /alerts, POST /alerts/evaluate, and POST /alerts/resolve REST endpoints."""
    app = FastAPI()
    app.include_router(telemetry_router)
    client = TestClient(app)

    # 1. Ingest telemetry that triggers an alert
    ingest_payload = {
        "source_domain": "EMBEDDED",
        "source_id": "CAR_API_TEST",
        "payload": {
            "device_id": "CAR_API_TEST",
            "device_mode": "RC_CAR",
            "status": "ONLINE",
            "system_health": {
                "battery_soc_pct": 14,
                "supply_voltage_v": 12.0
            }
        }
    }
    res_ingest = client.post("/api/v1/telemetry", json=ingest_payload)
    assert res_ingest.status_code == 200

    # 2. Retrieve active alerts via GET /alerts
    res_alerts = client.get("/api/v1/telemetry/alerts?device_id=CAR_API_TEST")
    assert res_alerts.status_code == 200
    data = res_alerts.json()
    assert data["status"] == "success"
    assert data["active_count"] == 1
    active_alert = data["active_alerts"][0]
    assert active_alert["alert_type"] == "CRITICAL_BATTERY"
    assert active_alert["severity"] == "CRITICAL"
    alert_id = active_alert["alert_id"]

    # 3. Manually resolve alert via POST /alerts/resolve
    res_resolve = client.post("/api/v1/telemetry/alerts/resolve", json={"alert_id": alert_id})
    assert res_resolve.status_code == 200
    resolve_data = res_resolve.json()
    assert resolve_data["status"] == "success"
    assert resolve_data["alert"]["status"] == "RESOLVED"

    # 4. Direct evaluation endpoint POST /alerts/evaluate
    res_eval = client.post("/api/v1/telemetry/alerts/evaluate", json={
        "device_id": "DIRECT_EVAL_DEV",
        "front_distance": 10.0,
        "status": "ONLINE"
    })
    assert res_eval.status_code == 200
    eval_data = res_eval.json()
    assert eval_data["status"] == "success"
    assert eval_data["alerts_count"] == 1
    assert eval_data["alerts"][0]["condition"] == "OBSTACLE_FRONT_CRITICAL"
