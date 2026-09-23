"""
iot_telemetry_normalizer.py
===========================
Standardizes raw IoT device data, sensor readings, and activity events
into the unified SynaptiMesh telemetry envelope format (UnifiedTelemetryPacket & IotTelemetry).
Task 3 — IoT Telemetry Standardization.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union

from models.telemetry_models import (
    ConnectivityMetrics,
    EnergyMetrics,
    EnvironmentalSensors,
    IotTelemetry,
    RelayStates,
    TelemetryDomain,
    UnifiedTelemetryPacket,
)

logger = logging.getLogger("services.iot_telemetry_normalizer")

_seq_counter = 0


def _get_next_sequence() -> int:
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def _extract_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _extract_int(val: Any) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _extract_bool(val: Any) -> Optional[bool]:
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes", "on")
    return bool(val)


def normalize_iot_telemetry(
    raw_payload: Dict[str, Any],
    device_id: Optional[str] = None,
    session_id: str = "default",
    trace_id: Optional[str] = None,
) -> UnifiedTelemetryPacket:
    """
    Convert raw IoT device/sensor payload into standard UnifiedTelemetryPacket with IotTelemetry.
    Handles legacy, flat, nested, and firmware 2.0.0-unified structures.
    """
    if not isinstance(raw_payload, dict):
        raw_payload = {}

    target_id = (
        device_id
        or raw_payload.get("device_id")
        or raw_payload.get("deviceId")
        or raw_payload.get("mac")
        or "UNKNOWN_IOT_DEVICE"
    )

    states_obj = raw_payload.get("states", {})
    if not isinstance(states_obj, dict):
        states_obj = {}

    # 1. Relays
    light = str(
        states_obj.get("light")
        or raw_payload.get("light")
        or raw_payload.get("Left_light")
        or "OFF"
    ).upper()
    fan = str(
        states_obj.get("fan")
        or raw_payload.get("fan")
        or raw_payload.get("Left_fan")
        or "OFF"
    ).upper()
    pump = str(
        states_obj.get("pump")
        or raw_payload.get("pump")
        or raw_payload.get("Left_pump")
        or "OFF"
    ).upper()

    relays = RelayStates(
        light=light if light in ("ON", "OFF", "TOGGLE") else "OFF",
        fan=fan if fan in ("ON", "OFF", "TOGGLE") else "OFF",
        pump=pump if pump in ("ON", "OFF", "TOGGLE") else "OFF",
    )

    # 2. Environmental Sensors
    temp = _extract_float(
        raw_payload.get("temperature_celsius")
        or raw_payload.get("temp")
        or raw_payload.get("temperature")
    )
    humidity = _extract_float(
        raw_payload.get("humidity_pct")
        or raw_payload.get("humidity")
    )
    lux = _extract_float(
        raw_payload.get("ambient_light_lux")
        or raw_payload.get("lux")
        or raw_payload.get("light_level")
    )
    motion = _extract_bool(
        raw_payload.get("motion_detected")
        if "motion_detected" in raw_payload
        else raw_payload.get("motion")
    )

    env_sensors = None
    if temp is not None or humidity is not None or lux is not None or motion is not None:
        env_sensors = EnvironmentalSensors(
            temperature_celsius=temp,
            humidity_pct=humidity,
            ambient_light_lux=lux,
            motion_detected=motion,
        )

    # 3. Energy Metrics
    voltage = _extract_float(raw_payload.get("voltage_v") or raw_payload.get("voltage"))
    current = _extract_float(raw_payload.get("current_a") or raw_payload.get("current"))
    power = _extract_float(raw_payload.get("power_watts") or raw_payload.get("power"))
    energy = _extract_float(raw_payload.get("energy_kwh") or raw_payload.get("energy"))

    energy_metrics = None
    if voltage is not None or current is not None or power is not None or energy is not None:
        energy_metrics = EnergyMetrics(
            voltage_v=voltage,
            current_a=current,
            power_watts=power,
            energy_kwh=energy,
        )

    # 4. Connectivity Diagnostics
    rssi = _extract_int(raw_payload.get("wifi_rssi_dbm") or raw_payload.get("rssi"))
    ip = raw_payload.get("ip_address") or raw_payload.get("ip")
    uptime = _extract_int(raw_payload.get("uptime_seconds") or raw_payload.get("uptime"))
    protocol = str(raw_payload.get("protocol", "MQTT")).upper()

    connectivity = ConnectivityMetrics(
        protocol=protocol,
        wifi_rssi_dbm=rssi,
        ip_address=ip,
        uptime_seconds=uptime,
    )

    # Operational status
    is_online = raw_payload.get("online", True)
    status_str = "ONLINE" if is_online else "OFFLINE"
    if "status" in raw_payload:
        raw_st = str(raw_payload["status"]).upper()
        if raw_st in ("ONLINE", "OFFLINE", "DEGRADED", "ERROR"):
            status_str = raw_st

    iot_payload = IotTelemetry(
        device_type=raw_payload.get("device_type", "SMART_RELAY"),
        firmware_version=raw_payload.get("firmware", raw_payload.get("firmware_version", "2.0.0-unified")),
        status=status_str,
        relays=relays,
        environmental_sensors=env_sensors,
        energy_metrics=energy_metrics,
        connectivity=connectivity,
    )

    # Timestamp
    ts_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if "timestamp" in raw_payload:
        val = raw_payload["timestamp"]
        if isinstance(val, (int, float)):
            ts_sec = val / 1000.0 if val > 10000000000 else float(val)
            try:
                ts_iso = datetime.fromtimestamp(ts_sec, tz=timezone.utc).isoformat().replace("+00:00", "Z")
            except Exception:
                pass
        elif isinstance(val, str) and len(val) >= 10:
            ts_iso = val

    packet = UnifiedTelemetryPacket(
        telemetry_id=f"TEL-IOT-{uuid.uuid4().hex[:12]}",
        timestamp=ts_iso,
        source_domain=TelemetryDomain.IOT,
        source_id=target_id,
        session_id=session_id,
        trace_id=trace_id,
        sequence_number=_get_next_sequence(),
        payload=iot_payload,
    )

    return packet


def device_to_telemetry_packet(
    device_obj: Any,
    session_id: str = "default",
    trace_id: Optional[str] = None,
) -> UnifiedTelemetryPacket:
    """
    Convert a DeviceManager Device instance into a standardized UnifiedTelemetryPacket.
    """
    if hasattr(device_obj, "__dict__"):
        d_dict = getattr(device_obj, "__dict__")
    elif isinstance(device_obj, dict):
        d_dict = device_obj
    else:
        d_dict = {}

    dev_id = d_dict.get("device_id") or "UNKNOWN_IOT"
    return normalize_iot_telemetry(
        raw_payload=d_dict,
        device_id=dev_id,
        session_id=session_id,
        trace_id=trace_id,
    )
