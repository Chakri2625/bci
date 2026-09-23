"""
embedded_telemetry_normalizer.py
================================
Standardizes raw Embedded device data, robotics kinematics, battery/power metrics,
and operational status into the unified SynaptiMesh telemetry envelope format
(UnifiedTelemetryPacket & EmbeddedTelemetry).

Unifies movement, speed, battery, and status into one clear, consistent schema.
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union

from models.telemetry_models import (
    BusTelemetry,
    EmbeddedTelemetry,
    ImuTelemetry,
    KinematicsTelemetry,
    SafetyRangingTelemetry,
    SystemHealthTelemetry,
    TelemetryDomain,
    UnifiedTelemetryPacket,
)

logger = logging.getLogger("services.embedded_telemetry_normalizer")

_seq_counter = 0


def _get_next_sequence() -> int:
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def _extract_float(val: Any) -> Optional[float]:
    if val is None or isinstance(val, bool):
        return None
    try:
        if isinstance(val, str):
            cleaned = val.strip().rstrip("%Vvms/").strip()
            num = float(cleaned)
        else:
            num = float(val)
        if math.isnan(num) or math.isinf(num):
            return None
        return num
    except (ValueError, TypeError):
        return None


def _extract_int(val: Any) -> Optional[int]:
    if val is None or isinstance(val, bool):
        return None
    try:
        if isinstance(val, str):
            cleaned = val.strip().rstrip("%Vv").strip()
            num = float(cleaned)
        else:
            num = float(val)
        if math.isnan(num) or math.isinf(num):
            return None
        return int(round(num))
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


# ==============================================================================
# Validation & Normalization Helpers
# ==============================================================================

def validate_battery_soc(value: Any) -> Optional[int]:
    """
    Validates battery state of charge (SoC) percentage.
    Rules:
    - Rejects boolean values (True / False).
    - Accepts numeric values (int, float) and numeric strings (e.g. 75, 75.0, "75", "75%").
    - Valid range is 0 to 100 inclusive.
    - 0 and 100 must remain valid.
    - Rejects negative values and values > 100.
    - Malformed or out-of-range values return None safely without crashing.
    """
    if value is None or isinstance(value, bool):
        return None

    try:
        if isinstance(value, str):
            cleaned = value.strip().rstrip("%").strip()
            num = float(cleaned)
        else:
            num = float(value)

        if math.isnan(num) or math.isinf(num):
            return None

        soc_int = int(round(num))
        if 0 <= soc_int <= 100:
            return soc_int
        return None
    except (ValueError, TypeError):
        return None


def validate_supply_voltage(value: Any) -> Optional[float]:
    """
    Validates main supply / battery voltage in Volts.
    Preserves supply voltage >= 0.0V.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, str):
            cleaned = value.strip().rstrip("Vv").strip()
            val = float(cleaned)
        else:
            val = float(value)

        if math.isnan(val) or math.isinf(val):
            return None
        if val >= 0.0:
            return round(val, 2)
        return None
    except (ValueError, TypeError):
        return None


def normalize_movement(raw_val: Any) -> str:
    """
    Normalizes direction and motor actions into canonical movement keywords:
    FORWARD, BACKWARD, LEFT, RIGHT, LEFT360, RIGHT360, STOP, IDLE.
    Handles legacy BCI commands (PUSH -> FORWARD, PULL -> BACKWARD).
    """
    if not raw_val:
        return "STOP"

    val_str = str(raw_val).strip().upper()

    if val_str in ("FORWARD", "PUSH", "CAR_FORWARD", "MOVING_FORWARD", "FORWARDS"):
        return "FORWARD"
    if val_str in ("BACKWARD", "PULL", "CAR_BACKWARD", "MOVING_BACKWARD", "BACKWARDS", "REVERSE"):
        return "BACKWARD"
    if val_str in ("LEFT360", "SPIN_LEFT", "ROTATE_LEFT_360"):
        return "LEFT360"
    if val_str in ("RIGHT360", "SPIN_RIGHT", "ROTATE_RIGHT_360"):
        return "RIGHT360"
    if val_str in ("LEFT", "TURNING_LEFT", "TURN_LEFT"):
        return "LEFT"
    if val_str in ("RIGHT", "TURNING_RIGHT", "TURN_RIGHT"):
        return "RIGHT"
    if val_str in ("IDLE", "STANDBY"):
        return "IDLE"
    if val_str in ("STOP", "STOPPED", "EMERGENCY_STOP", "HALT", "BLOCKED", "OBSTACLE", "NOT EXECUTED", "INITIALIZED", "NONE", "--", "OFFLINE", "DISCONNECTED", "ONLINE"):
        return "STOP"

    # Search for embedded tokens
    if "LEFT360" in val_str or "SPIN_LEFT" in val_str:
        return "LEFT360"
    if "RIGHT360" in val_str or "SPIN_RIGHT" in val_str:
        return "RIGHT360"
    if "FORWARD" in val_str or "PUSH" in val_str:
        return "FORWARD"
    if "BACKWARD" in val_str or "PULL" in val_str or "REVERSE" in val_str:
        return "BACKWARD"
    if "LEFT" in val_str:
        return "LEFT"
    if "RIGHT" in val_str:
        return "RIGHT"
    if "STOP" in val_str or "OBSTACLE" in val_str or "BLOCKED" in val_str:
        return "STOP"

    return "STOP"


def normalize_kinematic_state(movement: str) -> str:
    """
    Translates movement command into high-level kinematic state.
    """
    mov = movement.upper()
    if mov == "FORWARD":
        return "MOVING_FORWARD"
    if mov == "BACKWARD":
        return "MOVING_BACKWARD"
    if mov == "LEFT":
        return "TURNING_LEFT"
    if mov == "RIGHT":
        return "TURNING_RIGHT"
    if mov in ("LEFT360", "RIGHT360"):
        return "ROTATING_360"
    if mov == "IDLE":
        return "IDLE"
    return "STOPPED"


def normalize_speed(
    raw_speed: Any,
    movement: str = "STOP",
    speed_mode: str = "NORMAL",
    speed_pwm: Optional[int] = None
) -> float:
    """
    Calculates standardized speed scalar (float).
    """
    if movement in ("STOP", "IDLE"):
        return 0.0

    parsed = _extract_float(raw_speed)
    if parsed is not None:
        return round(parsed, 3)

    if speed_pwm is not None and speed_pwm > 0:
        return round(float(speed_pwm) / 255.0, 3)

    # Default speeds by speed mode
    mode_map = {
        "SLOW": 0.3,
        "NORMAL": 0.6,
        "MEDIUM": 0.6,
        "FAST": 0.85,
        "TURBO": 1.0
    }
    return mode_map.get(speed_mode.upper(), 0.6)


def normalize_status(raw_val: Any, movement: str = "STOP") -> str:
    """
    Standardizes operational status to one of:
    ONLINE, OFFLINE, DEGRADED, ERROR, MOVING, STOPPED, TIMEOUT, ACTIVE, IDLE.
    """
    if not raw_val:
        return "MOVING" if movement not in ("STOP", "IDLE") else "ONLINE"

    st_str = str(raw_val).strip().upper()

    if st_str in ("ONLINE", "OFFLINE", "DEGRADED", "ERROR", "MOVING", "STOPPED", "TIMEOUT", "ACTIVE", "IDLE"):
        return st_str

    if "TIMEOUT" in st_str:
        return "TIMEOUT"
    if "OFFLINE" in st_str or "DISCONNECTED" in st_str:
        return "OFFLINE"
    if "ERROR" in st_str or "FAULT" in st_str:
        return "ERROR"
    if "DEGRADED" in st_str:
        return "DEGRADED"
    if "EXECUTING" in st_str or "RUNNING" in st_str or "MOVING" in st_str:
        return "MOVING" if movement != "STOP" else "ONLINE"

    return "ONLINE"


# ==============================================================================
# Main Normalizer Function
# ==============================================================================

def normalize_embedded_telemetry(
    raw_payload: Union[Dict[str, Any], str],
    device_id: Optional[str] = None,
    session_id: str = "default",
    trace_id: Optional[str] = None,
) -> UnifiedTelemetryPacket:
    """
    Convert raw Embedded device / sensor / subplugin payload into a standard UnifiedTelemetryPacket
    with standardized EmbeddedTelemetry.

    Unifies:
    - Movement (FORWARD, BACKWARD, LEFT, RIGHT, STOP, LEFT360, RIGHT360, IDLE)
    - Speed (speed scalar, speed_mode, speed_pwm, motor PWMs, velocity)
    - Battery (battery_soc_pct 0-100%, supply_voltage_v >= 0.0V, health metrics)
    - Status (ONLINE, OFFLINE, MOVING, STOPPED, TIMEOUT, DEGRADED, ERROR, ACTIVE, IDLE)
    """
    parsed: Dict[str, Any] = {}

    if isinstance(raw_payload, dict):
        parsed = raw_payload
    elif isinstance(raw_payload, str):
        raw_str = raw_payload.strip()
        if raw_str.startswith("{") and raw_str.endswith("}"):
            try:
                parsed = json.loads(raw_str)
            except Exception:
                parsed = {"status": raw_str}
        else:
            parsed = {"status": raw_str}

    # 1. Device and Architecture Identity
    target_id = (
        device_id
        or parsed.get("device_id")
        or parsed.get("deviceId")
        or parsed.get("device")
        or parsed.get("car_id")
        or parsed.get("source_id")
        or "ROBOTCAR_01"
    )

    dev_str = f"{target_id} {parsed.get('device_mode', '')}".lower()
    if "chair" in dev_str or "wheelchair" in dev_str:
        default_mode = "WHEELCHAIR"
    elif "arm" in dev_str or "robotic_arm" in dev_str:
        default_mode = "ROBOTIC_ARM"
    else:
        default_mode = "RC_CAR"

    device_mode = parsed.get("device_mode") or default_mode
    mcu_arch = parsed.get("mcu_architecture") or "ESP32-WROOM-32"
    firmware_ver = parsed.get("firmware_version") or parsed.get("firmware") or "2.0.0-unified"

    # 2. Movement & Kinematic Action
    raw_movement = (
        parsed.get("movement")
        or parsed.get("command")
        or parsed.get("action")
        or parsed.get("state")
        or parsed.get("last_motor_action")
        or parsed.get("status")
        or ""
    )
    movement = normalize_movement(raw_movement)
    state = parsed.get("device_state") or normalize_kinematic_state(movement)

    # 3. Speed & PWM Controls
    speed_mode = str(parsed.get("speed_mode") or "NORMAL").upper()
    speed_pwm = _extract_int(parsed.get("speed_pwm"))
    motor_left = _extract_int(parsed.get("motor_left_pwm")) or 0
    motor_right = _extract_int(parsed.get("motor_right_pwm")) or 0

    if speed_pwm is None and (motor_left != 0 or motor_right != 0):
        speed_pwm = max(abs(motor_left), abs(motor_right))

    speed = normalize_speed(
        raw_speed=parsed.get("speed") or parsed.get("linear_velocity_mps"),
        movement=movement,
        speed_mode=speed_mode,
        speed_pwm=speed_pwm
    )

    steering = _extract_float(parsed.get("steering_angle_deg") or parsed.get("steering")) or 0.0
    velocity_mps = _extract_float(parsed.get("linear_velocity_mps"))

    kinematics = KinematicsTelemetry(
        movement=movement,
        state=state,
        speed=speed,
        speed_pwm=speed_pwm,
        speed_mode=speed_mode if speed_mode in ("SLOW", "NORMAL", "MEDIUM", "FAST", "TURBO") else "NORMAL",
        motor_left_pwm=motor_left,
        motor_right_pwm=motor_right,
        steering_angle_deg=steering if -90.0 <= steering <= 90.0 else 0.0,
        linear_velocity_mps=velocity_mps,
        wheel_encoder_left_ticks=_extract_int(parsed.get("wheel_encoder_left_ticks")),
        wheel_encoder_right_ticks=_extract_int(parsed.get("wheel_encoder_right_ticks")),
    )

    # 4. Battery & System Health
    raw_bat = None
    for k in ("battery_soc_pct", "battery", "battery_pct", "battery_level", "soc"):
        if k in parsed:
            raw_bat = parsed[k]
            break
    if raw_bat is None and isinstance(parsed.get("system_health"), dict):
        sh = parsed["system_health"]
        for k in ("battery_soc_pct", "battery", "battery_pct", "battery_level", "soc"):
            if k in sh:
                raw_bat = sh[k]
                break

    raw_volt = None
    for k in ("supply_voltage_v", "supply_voltage", "voltage", "voltage_v"):
        if k in parsed:
            raw_volt = parsed[k]
            break
    if raw_volt is None and isinstance(parsed.get("system_health"), dict):
        sh = parsed["system_health"]
        for k in ("supply_voltage_v", "supply_voltage", "voltage", "voltage_v"):
            if k in sh:
                raw_volt = sh[k]
                break

    validated_battery = validate_battery_soc(raw_bat)
    validated_voltage = validate_supply_voltage(raw_volt)

    sh_dict = parsed.get("system_health") if isinstance(parsed.get("system_health"), dict) else parsed
    free_heap = _extract_int(sh_dict.get("free_heap_bytes")) or 0
    cpu_temp = _extract_float(sh_dict.get("cpu_core_temp_c") or sh_dict.get("temperature"))
    loop_hz = _extract_float(sh_dict.get("loop_frequency_hz"))

    system_health = SystemHealthTelemetry(
        free_heap_bytes=free_heap,
        cpu_core_temp_c=cpu_temp,
        supply_voltage_v=validated_voltage,
        battery_soc_pct=validated_battery,
        loop_frequency_hz=loop_hz,
    )

    # 5. Operational Status
    raw_status = parsed.get("status") or parsed.get("last_status") or parsed.get("device_status")
    status = normalize_status(raw_status, movement=movement)

    # 6. Safety & Ranging Telemetry
    front_dist = _extract_float(
        parsed.get("front_distance")
        or parsed.get("ultrasonic_front_distance_cm")
        or (parsed.get("safety_and_ranging", {}).get("ultrasonic_front_distance_cm") if isinstance(parsed.get("safety_and_ranging"), dict) else None)
    )
    rear_dist = _extract_float(
        parsed.get("rear_distance")
        or parsed.get("ultrasonic_rear_distance_cm")
        or (parsed.get("safety_and_ranging", {}).get("ultrasonic_rear_distance_cm") if isinstance(parsed.get("safety_and_ranging"), dict) else None)
    )
    collision = _extract_bool(
        parsed.get("collision_detected")
        or parsed.get("front_obstacle")
        or parsed.get("rear_obstacle")
        or (parsed.get("safety_and_ranging", {}).get("collision_detected") if isinstance(parsed.get("safety_and_ranging"), dict) else False)
    ) or False
    estop = _extract_bool(
        parsed.get("emergency_stop_triggered")
        or (parsed.get("safety_and_ranging", {}).get("emergency_stop_triggered") if isinstance(parsed.get("safety_and_ranging"), dict) else False)
    ) or False

    safety_and_ranging = None
    if front_dist is not None or rear_dist is not None or collision or estop:
        safety_and_ranging = SafetyRangingTelemetry(
            ultrasonic_front_distance_cm=front_dist,
            ultrasonic_rear_distance_cm=rear_dist,
            collision_detected=collision,
            emergency_stop_triggered=estop,
        )

    # 7. IMU Sensors (Optional)
    imu_dict = parsed.get("imu_sensors") if isinstance(parsed.get("imu_sensors"), dict) else parsed
    accel_x = _extract_float(imu_dict.get("accel_x_g") or imu_dict.get("accel_x"))
    accel_y = _extract_float(imu_dict.get("accel_y_g") or imu_dict.get("accel_y"))
    accel_z = _extract_float(imu_dict.get("accel_z_g") or imu_dict.get("accel_z"))
    gyro_r = _extract_float(imu_dict.get("gyro_roll_deg_s") or imu_dict.get("gyro_roll"))
    gyro_p = _extract_float(imu_dict.get("gyro_pitch_deg_s") or imu_dict.get("gyro_pitch"))
    gyro_y = _extract_float(imu_dict.get("gyro_yaw_deg_s") or imu_dict.get("gyro_yaw"))

    imu_sensors = None
    if any(v is not None for v in (accel_x, accel_y, accel_z, gyro_r, gyro_p, gyro_y)):
        imu_sensors = ImuTelemetry(
            accel_x_g=accel_x,
            accel_y_g=accel_y,
            accel_z_g=accel_z,
            gyro_roll_deg_s=gyro_r,
            gyro_pitch_deg_s=gyro_p,
            gyro_yaw_deg_s=gyro_y,
        )

    # 8. Bus Telemetry (Optional)
    bus_dict = parsed.get("bus_telemetry") if isinstance(parsed.get("bus_telemetry"), dict) else parsed
    protocol = str(bus_dict.get("protocol") or "MQTT").upper()
    baud = _extract_int(bus_dict.get("baud_rate") or bus_dict.get("baud"))
    rx_over = _extract_int(bus_dict.get("rx_buffer_overflows")) or 0
    crc_errs = _extract_int(bus_dict.get("packet_crc_errors")) or 0
    rtt = _extract_float(bus_dict.get("round_trip_latency_ms") or bus_dict.get("latency_ms"))

    bus_telemetry = None
    if protocol or baud is not None or rtt is not None or rx_over > 0 or crc_errs > 0:
        bus_telemetry = BusTelemetry(
            protocol=protocol,
            baud_rate=baud,
            rx_buffer_overflows=rx_over,
            packet_crc_errors=crc_errs,
            round_trip_latency_ms=rtt,
        )

    # Build EmbeddedTelemetry payload
    embedded_payload = EmbeddedTelemetry(
        device_id=target_id,
        device_mode=device_mode,
        mcu_architecture=mcu_arch,
        firmware_version=firmware_ver,
        status=status,
        system_health=system_health,
        kinematics=kinematics,
        imu_sensors=imu_sensors,
        safety_and_ranging=safety_and_ranging,
        bus_telemetry=bus_telemetry,
    )

    # Timestamp
    ts_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if "timestamp" in parsed:
        val = parsed["timestamp"]
        if isinstance(val, (int, float)):
            ts_sec = val / 1000.0 if val > 10000000000 else float(val)
            try:
                ts_iso = datetime.fromtimestamp(ts_sec, tz=timezone.utc).isoformat().replace("+00:00", "Z")
            except Exception:
                pass
        elif isinstance(val, str) and len(val) >= 10:
            ts_iso = val

    packet = UnifiedTelemetryPacket(
        telemetry_id=f"TEL-EMB-{uuid.uuid4().hex[:12]}",
        timestamp=ts_iso,
        source_domain=TelemetryDomain.EMBEDDED,
        source_id=target_id,
        session_id=session_id,
        trace_id=trace_id,
        sequence_number=_get_next_sequence(),
        payload=embedded_payload,
    )

    return packet


def subplugin_to_telemetry_packet(
    subplugin_status: Dict[str, Any],
    device_id: Optional[str] = None,
    session_id: str = "default",
    trace_id: Optional[str] = None,
) -> UnifiedTelemetryPacket:
    """
    Convert output from RcCarPlugin.status() or WheelchairPlugin.status()
    into a standardized UnifiedTelemetryPacket.
    """
    if not isinstance(subplugin_status, dict):
        subplugin_status = {}

    target_id = (
        device_id
        or subplugin_status.get("device_id")
        or subplugin_status.get("device")
        or "EMBEDDED_DEV"
    )

    return normalize_embedded_telemetry(
        raw_payload=subplugin_status,
        device_id=target_id,
        session_id=session_id,
        trace_id=trace_id,
    )
