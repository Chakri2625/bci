"""
services/embedded_alert_generator.py
====================================
Server-side movement, speed, battery, safety, and status alert generation engine
for the SynaptiMesh Embedded / Robotics Domain (RC Car, Smart Wheelchair, MCUs).
Sprint 11 — Day 5 Member 6 Implementation.

Responsibilities:
- Evaluates standardized embedded telemetry against established safety and status rules.
- Generates normalized dashboard-facing TelemetryAlert objects.
- Manages complete alert lifecycle (TRIGGERED -> ACTIVE -> RESOLVED / CLEARED).
- Prevents alert flooding via condition change detection and per-device state tracking.
- Seamlessly broadcasts alerts over WebSocketServer, EventBus, and StateManager.
- Provides thread-safe, non-blocking execution suitable for high-frequency telemetry.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import uuid

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

logger = logging.getLogger("services.embedded_alert_generator")


# ==============================================================================
# Established Safety & Alert Thresholds (Preserving Project Conventions)
# ==============================================================================

# Distance thresholds (Sonar / Ultrasonic)
OBSTACLE_CRITICAL_DISTANCE_CM = 15.0   # Immediate collision risk / emergency proximity
OBSTACLE_WARNING_DISTANCE_CM = 30.0    # Warning threat / sonar proximity zone

# Battery State of Charge (SoC %)
BATTERY_CRITICAL_SOC_PCT = 15          # Critical battery shutdown threshold
BATTERY_LOW_SOC_PCT = 25               # Low battery advisory warning

# Supply Voltage (Volts)
SUPPLY_VOLTAGE_SAG_THRESHOLD_V = 10.0  # Main DC supply sag warning

# Microcontroller Core Temperature (°C)
CPU_TEMP_CRITICAL_C = 75.0             # Silicon thermal throttling / critical
CPU_TEMP_WARNING_C = 65.0              # Elevated temperature warning

# Memory Heap (Bytes)
FREE_HEAP_LOW_BYTES = 20000            # ESP32 low RAM heap pressure

# Speed Limits
MAX_SAFE_SPEED_SCALAR = 1.0            # Max allowed normalized speed scalar


class EmbeddedAlertGenerator:
    """
    Centralized Server-Side Alert Generator for Embedded & Robotics Telemetry.
    Evaluates movement, speed, battery, safety ranging, and hardware health conditions.
    """

    _instance: Optional[EmbeddedAlertGenerator] = None
    _lock = threading.RLock()

    @classmethod
    def get_instance(cls) -> EmbeddedAlertGenerator:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __new__(cls) -> EmbeddedAlertGenerator:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(EmbeddedAlertGenerator, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return

        self._lock = threading.RLock()
        # Active alerts mapping: device_id -> {condition_key: TelemetryAlert}
        self._active_alerts: Dict[str, Dict[str, TelemetryAlert]] = {}
        # Historical circular alert buffer
        self._alert_history: deque = deque(maxlen=200)
        self._initialized = True
        logger.info("[ALERT GENERATOR] Embedded Alert Generator service initialized")

    # ---------------------------------------------------------------------------
    # Core Telemetry Evaluation
    # ---------------------------------------------------------------------------

    def evaluate_telemetry(
        self,
        telemetry: Union[UnifiedTelemetryPacket, EmbeddedTelemetry, Dict[str, Any], str],
        device_id: Optional[str] = None,
        auto_broadcast: bool = True
    ) -> List[TelemetryAlert]:
        """
        Evaluate incoming embedded telemetry, generate new alerts, resolve cleared alerts,
        and manage alert lifecycle state transitions without flooding duplicate events.

        Returns a list of state-transition alerts (newly triggered or newly resolved).
        """
        try:
            parsed = self._extract_telemetry_fields(telemetry, fallback_device_id=device_id)
        except Exception as err:
            logger.warning(f"[ALERT GENERATOR] Failed to extract telemetry for alert evaluation: {err}")
            return []

        target_device_id = parsed["device_id"]
        device_mode = parsed["device_mode"]
        kinematics = parsed["kinematics"]
        system_health = parsed["system_health"]
        safety = parsed["safety"]
        status = parsed["status"]
        bus = parsed["bus"]

        # Evaluate conditions against established rules
        detected_conditions = self._evaluate_conditions(
            device_id=target_device_id,
            device_mode=device_mode,
            kinematics=kinematics,
            system_health=system_health,
            safety=safety,
            status=status,
            bus=bus
        )

        transition_alerts: List[TelemetryAlert] = []

        with self._lock:
            device_active = self._active_alerts.setdefault(target_device_id, {})
            current_condition_keys = set(detected_conditions.keys())
            previous_condition_keys = set(device_active.keys())

            # 1. Process Newly Emerged Conditions
            for cond_key, alert_blueprint in detected_conditions.items():
                if cond_key not in device_active:
                    # New alert trigger
                    alert = TelemetryAlert(
                        alert_type=alert_blueprint["alert_type"],
                        severity=alert_blueprint["severity"],
                        device_id=target_device_id,
                        device_mode=device_mode,
                        domain=TelemetryDomain.EMBEDDED,
                        message=alert_blueprint["message"],
                        condition=cond_key,
                        status=AlertStatus.ACTIVE,
                        metadata=alert_blueprint["metadata"]
                    )
                    device_active[cond_key] = alert
                    self._alert_history.append(alert.to_dict())
                    transition_alerts.append(alert)
                    logger.info(f"[ALERT GENERATED] [{alert.severity.value}] {alert.device_id}: {alert.message}")
                else:
                    # Condition continues to be active -> update metadata if metrics changed, but avoid duplicate alert event flood
                    existing_alert = device_active[cond_key]
                    existing_alert.metadata.update(alert_blueprint["metadata"])

            # 2. Process Automatically Resolved Conditions
            cleared_keys = previous_condition_keys - current_condition_keys
            for cleared_key in cleared_keys:
                resolved_alert = device_active.pop(cleared_key)
                resolved_alert.status = AlertStatus.RESOLVED
                resolved_alert.resolved_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                self._alert_history.append(resolved_alert.to_dict())
                transition_alerts.append(resolved_alert)
                logger.info(f"[ALERT RESOLVED] {resolved_alert.device_id}: Condition '{cleared_key}' resolved")

        # 3. Broadcast transitions over WebSocket and system pipelines
        if auto_broadcast and transition_alerts:
            for alert in transition_alerts:
                self._dispatch_alert(alert)

        return transition_alerts

    # ---------------------------------------------------------------------------
    # Condition Evaluator
    # ---------------------------------------------------------------------------

    def _evaluate_conditions(
        self,
        device_id: str,
        device_mode: str,
        kinematics: Dict[str, Any],
        system_health: Dict[str, Any],
        safety: Dict[str, Any],
        status: str,
        bus: Dict[str, Any]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Evaluate all safety, movement, battery, and hardware rules.
        Returns a dictionary of active condition descriptors keyed by condition identifier.
        """
        conditions: Dict[str, Dict[str, Any]] = {}

        # 1. EMERGENCY STOP
        if safety.get("emergency_stop_triggered") is True:
            conditions["EMERGENCY_STOP"] = {
                "alert_type": "EMERGENCY_STOP",
                "severity": AlertSeverity.CRITICAL,
                "message": f"Emergency stop engaged on {device_id}",
                "metadata": {"device_id": device_id, "emergency_stop": True}
            }

        # 2. COLLISION DETECTED
        if safety.get("collision_detected") is True:
            conditions["COLLISION_DETECTED"] = {
                "alert_type": "COLLISION_DETECTED",
                "severity": AlertSeverity.CRITICAL,
                "message": f"Collision detected on {device_id}",
                "metadata": {"device_id": device_id, "collision": True}
            }

        # 3. OBSTACLE PROXIMITY (Front & Rear)
        front_dist = safety.get("ultrasonic_front_distance_cm")
        if front_dist is not None and front_dist > 0.0:
            if front_dist <= OBSTACLE_CRITICAL_DISTANCE_CM:
                conditions["OBSTACLE_FRONT_CRITICAL"] = {
                    "alert_type": "OBSTACLE_PROXIMITY",
                    "severity": AlertSeverity.CRITICAL,
                    "message": f"Critical front obstacle at {front_dist:.1f} cm on {device_id}",
                    "metadata": {"front_distance_cm": front_dist, "zone": "FRONT_CRITICAL"}
                }
            elif front_dist <= OBSTACLE_WARNING_DISTANCE_CM:
                conditions["OBSTACLE_FRONT_WARNING"] = {
                    "alert_type": "OBSTACLE_PROXIMITY",
                    "severity": AlertSeverity.WARNING,
                    "message": f"Front obstacle detected within {front_dist:.1f} cm on {device_id}",
                    "metadata": {"front_distance_cm": front_dist, "zone": "FRONT_WARNING"}
                }

        rear_dist = safety.get("ultrasonic_rear_distance_cm")
        if rear_dist is not None and rear_dist > 0.0:
            if rear_dist <= OBSTACLE_CRITICAL_DISTANCE_CM:
                conditions["OBSTACLE_REAR_CRITICAL"] = {
                    "alert_type": "OBSTACLE_PROXIMITY",
                    "severity": AlertSeverity.CRITICAL,
                    "message": f"Critical rear obstacle at {rear_dist:.1f} cm on {device_id}",
                    "metadata": {"rear_distance_cm": rear_dist, "zone": "REAR_CRITICAL"}
                }
            elif rear_dist <= OBSTACLE_WARNING_DISTANCE_CM:
                conditions["OBSTACLE_REAR_WARNING"] = {
                    "alert_type": "OBSTACLE_PROXIMITY",
                    "severity": AlertSeverity.WARNING,
                    "message": f"Rear obstacle detected within {rear_dist:.1f} cm on {device_id}",
                    "metadata": {"rear_distance_cm": rear_dist, "zone": "REAR_WARNING"}
                }

        # 4. BATTERY HEALTH & STATE OF CHARGE
        battery_soc = system_health.get("battery_soc_pct")
        if battery_soc is not None:
            if battery_soc <= BATTERY_CRITICAL_SOC_PCT:
                conditions["BATTERY_CRITICAL"] = {
                    "alert_type": "CRITICAL_BATTERY",
                    "severity": AlertSeverity.CRITICAL,
                    "message": f"Critical battery level: {battery_soc}% on {device_id}",
                    "metadata": {"battery_soc_pct": battery_soc, "supply_voltage_v": system_health.get("supply_voltage_v")}
                }
            elif battery_soc <= BATTERY_LOW_SOC_PCT:
                conditions["BATTERY_LOW"] = {
                    "alert_type": "LOW_BATTERY",
                    "severity": AlertSeverity.WARNING,
                    "message": f"Low battery warning: {battery_soc}% on {device_id}",
                    "metadata": {"battery_soc_pct": battery_soc, "supply_voltage_v": system_health.get("supply_voltage_v")}
                }

        # 5. SUPPLY VOLTAGE SAG
        voltage_v = system_health.get("supply_voltage_v")
        if voltage_v is not None and 0.0 < voltage_v < SUPPLY_VOLTAGE_SAG_THRESHOLD_V:
            conditions["SUPPLY_VOLTAGE_SAG"] = {
                "alert_type": "LOW_VOLTAGE",
                "severity": AlertSeverity.WARNING,
                "message": f"Low supply voltage sag ({voltage_v:.2f}V) detected on {device_id}",
                "metadata": {"supply_voltage_v": voltage_v}
            }

        # 6. HARDWARE OPERATIONAL STATUS
        norm_status = str(status).upper().strip()
        if norm_status in ("ERROR", "FAULT"):
            conditions["HARDWARE_FAULT"] = {
                "alert_type": "HARDWARE_FAULT",
                "severity": AlertSeverity.ERROR,
                "message": f"Hardware error status reported by {device_id}",
                "metadata": {"status": norm_status}
            }
        elif norm_status == "TIMEOUT":
            conditions["WATCHDOG_TIMEOUT"] = {
                "alert_type": "WATCHDOG_TIMEOUT",
                "severity": AlertSeverity.WARNING,
                "message": f"Hardware communication watchdog timeout on {device_id}",
                "metadata": {"status": norm_status}
            }
        elif norm_status == "DEGRADED":
            conditions["HARDWARE_DEGRADED"] = {
                "alert_type": "HARDWARE_FAULT",
                "severity": AlertSeverity.WARNING,
                "message": f"Degraded operational performance on {device_id}",
                "metadata": {"status": norm_status}
            }
        elif norm_status in ("OFFLINE", "DISCONNECTED"):
            conditions["DEVICE_OFFLINE"] = {
                "alert_type": "OFFLINE",
                "severity": AlertSeverity.WARNING,
                "message": f"Device {device_id} is offline or disconnected",
                "metadata": {"status": norm_status}
            }

        # 7. THERMAL SENSING (CPU Overheating)
        cpu_temp = system_health.get("cpu_core_temp_c")
        if cpu_temp is not None:
            if cpu_temp >= CPU_TEMP_CRITICAL_C:
                conditions["CPU_OVERHEATING_CRITICAL"] = {
                    "alert_type": "OVERHEATING",
                    "severity": AlertSeverity.CRITICAL,
                    "message": f"Critical MCU thermal threshold exceeded: {cpu_temp:.1f}°C on {device_id}",
                    "metadata": {"cpu_core_temp_c": cpu_temp}
                }
            elif cpu_temp >= CPU_TEMP_WARNING_C:
                conditions["CPU_OVERHEATING_WARNING"] = {
                    "alert_type": "OVERHEATING",
                    "severity": AlertSeverity.WARNING,
                    "message": f"Elevated MCU temperature warning: {cpu_temp:.1f}°C on {device_id}",
                    "metadata": {"cpu_core_temp_c": cpu_temp}
                }

        # 8. MEMORY PRESSURE (Heap Exhaustion)
        free_heap = system_health.get("free_heap_bytes")
        if free_heap is not None and 0 < free_heap < FREE_HEAP_LOW_BYTES:
            conditions["LOW_HEAP_MEMORY"] = {
                "alert_type": "HARDWARE_FAULT",
                "severity": AlertSeverity.WARNING,
                "message": f"Low MCU heap memory warning ({free_heap} bytes) on {device_id}",
                "metadata": {"free_heap_bytes": free_heap}
            }

        # 9. SPEED & KINEMATIC INTEGRITY
        speed = kinematics.get("speed")
        movement = kinematics.get("movement", "STOP").upper()

        if speed is not None and speed > MAX_SAFE_SPEED_SCALAR:
            conditions["ABNORMAL_SPEED"] = {
                "alert_type": "ABNORMAL_SPEED",
                "severity": AlertSeverity.WARNING,
                "message": f"Abnormal speed ({speed:.2f}) exceeds max safe velocity on {device_id}",
                "metadata": {"speed": speed, "max_limit": MAX_SAFE_SPEED_SCALAR}
            }

        # Unsafe movement command while locked / stopped / faulted
        if movement in ("FORWARD", "BACKWARD", "LEFT", "RIGHT", "LEFT360", "RIGHT360"):
            if safety.get("emergency_stop_triggered") is True or safety.get("collision_detected") is True:
                conditions["UNSAFE_MOVEMENT_LOCKED"] = {
                    "alert_type": "UNSAFE_MOVEMENT",
                    "severity": AlertSeverity.CRITICAL,
                    "message": f"Unsafe movement command '{movement}' rejected during active safety lock on {device_id}",
                    "metadata": {"movement": movement, "emergency_stop": safety.get("emergency_stop_triggered"), "collision": safety.get("collision_detected")}
                }
            elif norm_status in ("ERROR", "TIMEOUT"):
                conditions["UNSAFE_MOVEMENT_FAULTED"] = {
                    "alert_type": "UNSAFE_MOVEMENT",
                    "severity": AlertSeverity.WARNING,
                    "message": f"Movement attempt '{movement}' while device is in faulted state ({norm_status}) on {device_id}",
                    "metadata": {"movement": movement, "status": norm_status}
                }

        # 10. BUS COMMUNICATION ERRORS
        crc_errors = bus.get("packet_crc_errors", 0) or 0
        rx_overflows = bus.get("rx_buffer_overflows", 0) or 0
        if crc_errors > 25 or rx_overflows > 0:
            conditions["BUS_ERRORS"] = {
                "alert_type": "HARDWARE_FAULT",
                "severity": AlertSeverity.WARNING,
                "message": f"Bus communication errors detected (CRC: {crc_errors}, Overflow: {rx_overflows}) on {device_id}",
                "metadata": {"crc_errors": crc_errors, "rx_overflows": rx_overflows}
            }

        return conditions

    # ---------------------------------------------------------------------------
    # Telemetry Normalization & Field Extraction
    # ---------------------------------------------------------------------------

    def _extract_telemetry_fields(
        self,
        raw_telemetry: Union[UnifiedTelemetryPacket, EmbeddedTelemetry, Dict[str, Any], str],
        fallback_device_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Normalize any telemetry representation into a uniform inspection dictionary."""
        # 1. Handle UnifiedTelemetryPacket
        if isinstance(raw_telemetry, UnifiedTelemetryPacket):
            payload = raw_telemetry.payload
            dev_id = raw_telemetry.source_id or fallback_device_id or "EMBEDDED_DEV"
            if isinstance(payload, EmbeddedTelemetry):
                return {
                    "device_id": payload.device_id or dev_id,
                    "device_mode": payload.device_mode,
                    "status": payload.status,
                    "kinematics": payload.kinematics.model_dump(exclude_none=True) if payload.kinematics else {},
                    "system_health": payload.system_health.model_dump(exclude_none=True) if payload.system_health else {},
                    "safety": payload.safety_and_ranging.model_dump(exclude_none=True) if payload.safety_and_ranging else {},
                    "bus": payload.bus_telemetry.model_dump(exclude_none=True) if payload.bus_telemetry else {},
                }
            elif isinstance(payload, dict):
                return self._extract_dict_fields(payload, fallback_device_id=dev_id)

        # 2. Handle EmbeddedTelemetry
        if isinstance(raw_telemetry, EmbeddedTelemetry):
            return {
                "device_id": raw_telemetry.device_id or fallback_device_id or "EMBEDDED_DEV",
                "device_mode": raw_telemetry.device_mode,
                "status": raw_telemetry.status,
                "kinematics": raw_telemetry.kinematics.model_dump(exclude_none=True) if raw_telemetry.kinematics else {},
                "system_health": raw_telemetry.system_health.model_dump(exclude_none=True) if raw_telemetry.system_health else {},
                "safety": raw_telemetry.safety_and_ranging.model_dump(exclude_none=True) if raw_telemetry.safety_and_ranging else {},
                "bus": raw_telemetry.bus_telemetry.model_dump(exclude_none=True) if raw_telemetry.bus_telemetry else {},
            }

        # 3. Handle Dictionary or string payload
        if isinstance(raw_telemetry, dict):
            # Check if nested in UnifiedTelemetryPacket dict format
            if "source_domain" in raw_telemetry and "payload" in raw_telemetry:
                inner_payload = raw_telemetry["payload"]
                src_id = raw_telemetry.get("source_id") or fallback_device_id
                if isinstance(inner_payload, dict):
                    return self._extract_dict_fields(inner_payload, fallback_device_id=src_id)

            return self._extract_dict_fields(raw_telemetry, fallback_device_id=fallback_device_id)

        # 4. Fallback string
        from services.embedded_telemetry_normalizer import normalize_embedded_telemetry
        packet = normalize_embedded_telemetry(str(raw_telemetry), device_id=fallback_device_id)
        return self._extract_telemetry_fields(packet)

    def _extract_dict_fields(self, data: Dict[str, Any], fallback_device_id: Optional[str] = None) -> Dict[str, Any]:
        """Extract structured fields from a raw dictionary."""
        dev_id = (
            fallback_device_id
            or data.get("device_id")
            or data.get("deviceId")
            or data.get("device")
            or data.get("car_id")
            or "ROBOTCAR_01"
        )
        mode = data.get("device_mode")
        if not mode:
            mode = "WHEELCHAIR" if "chair" in str(dev_id).lower() else "RC_CAR"

        # Kinematics
        kin_dict = data.get("kinematics") if isinstance(data.get("kinematics"), dict) else {}
        movement = kin_dict.get("movement") or data.get("movement") or data.get("command") or data.get("action") or "STOP"
        speed = kin_dict.get("speed") if "speed" in kin_dict else data.get("speed")
        speed_mode = kin_dict.get("speed_mode") or data.get("speed_mode") or "NORMAL"

        # System Health
        sh_dict = data.get("system_health") if isinstance(data.get("system_health"), dict) else {}
        battery_soc = sh_dict.get("battery_soc_pct") if "battery_soc_pct" in sh_dict else (
            data.get("battery_soc_pct") or data.get("battery") or data.get("battery_level") or data.get("soc")
        )
        supply_voltage = sh_dict.get("supply_voltage_v") if "supply_voltage_v" in sh_dict else (
            data.get("supply_voltage_v") or data.get("voltage") or data.get("supply_voltage")
        )
        free_heap = sh_dict.get("free_heap_bytes") if "free_heap_bytes" in sh_dict else data.get("free_heap_bytes")
        cpu_temp = sh_dict.get("cpu_core_temp_c") if "cpu_core_temp_c" in sh_dict else (
            data.get("cpu_core_temp_c") or data.get("temperature")
        )

        # Safety & Ranging
        safety_dict = data.get("safety_and_ranging") if isinstance(data.get("safety_and_ranging"), dict) else {}
        front_dist = safety_dict.get("ultrasonic_front_distance_cm") if "ultrasonic_front_distance_cm" in safety_dict else (
            data.get("ultrasonic_front_distance_cm") or data.get("front_distance")
        )
        rear_dist = safety_dict.get("ultrasonic_rear_distance_cm") if "ultrasonic_rear_distance_cm" in safety_dict else (
            data.get("ultrasonic_rear_distance_cm") or data.get("rear_distance")
        )
        collision = safety_dict.get("collision_detected") if "collision_detected" in safety_dict else (
            data.get("collision_detected") or data.get("front_obstacle") or data.get("rear_obstacle") or False
        )
        estop = safety_dict.get("emergency_stop_triggered") if "emergency_stop_triggered" in safety_dict else (
            data.get("emergency_stop_triggered") or False
        )

        # Bus telemetry
        bus_dict = data.get("bus_telemetry") if isinstance(data.get("bus_telemetry"), dict) else {}
        crc_err = bus_dict.get("packet_crc_errors", 0) or data.get("packet_crc_errors", 0)
        rx_over = bus_dict.get("rx_buffer_overflows", 0) or data.get("rx_buffer_overflows", 0)

        # Status
        status = str(data.get("status") or data.get("last_status") or "ONLINE")

        def _clean_float(v: Any) -> Optional[float]:
            if v is None or isinstance(v, bool):
                return None
            try:
                return float(v)
            except (ValueError, TypeError):
                return None

        def _clean_int(v: Any) -> Optional[int]:
            if v is None or isinstance(v, bool):
                return None
            try:
                return int(v)
            except (ValueError, TypeError):
                return None

        return {
            "device_id": str(dev_id),
            "device_mode": str(mode),
            "status": status,
            "kinematics": {
                "movement": str(movement).upper(),
                "speed": _clean_float(speed),
                "speed_mode": str(speed_mode).upper(),
            },
            "system_health": {
                "battery_soc_pct": _clean_int(battery_soc),
                "supply_voltage_v": _clean_float(supply_voltage),
                "free_heap_bytes": _clean_int(free_heap),
                "cpu_core_temp_c": _clean_float(cpu_temp),
            },
            "safety": {
                "ultrasonic_front_distance_cm": _clean_float(front_dist),
                "ultrasonic_rear_distance_cm": _clean_float(rear_dist),
                "collision_detected": bool(collision),
                "emergency_stop_triggered": bool(estop),
            },
            "bus": {
                "packet_crc_errors": _clean_int(crc_err) or 0,
                "rx_buffer_overflows": _clean_int(rx_over) or 0,
            }
        }

    # ---------------------------------------------------------------------------
    # Event & WebSocket Pipeline Integration
    # ---------------------------------------------------------------------------

    def _dispatch_alert(self, alert: TelemetryAlert):
        """
        Broadcast alert to all connected dashboard WebSocket clients and backend bus.
        """
        alert_dict = alert.to_dict()

        # 1. Primary WebSocket Server broadcast
        try:
            from core.communication.websocket_server import websocket_server
            envelope = websocket_server.create_envelope(
                msg_type="ALERT",
                source_domain="EMBEDDED",
                source_id=alert.device_id,
                payload=alert_dict
            )
            websocket_server.broadcast_envelope_sync(envelope)
        except Exception as ws_err:
            logger.debug(f"[ALERT GENERATOR] WebSocketServer broadcast notice: {ws_err}")

        # 2. EventBus notification & Event History mirroring
        try:
            from core.events.event_bus import event_bus
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    loop.create_task(event_bus.publish("EMBEDDED_ALERT", alert_dict))
            except RuntimeError:
                pass
        except Exception as bus_err:
            logger.debug(f"[ALERT GENERATOR] EventBus notice: {bus_err}")

        # 3. StateManager fault isolation update on CRITICAL/ERROR alerts
        if alert.severity in (AlertSeverity.CRITICAL, AlertSeverity.ERROR) and alert.status == AlertStatus.ACTIVE:
            try:
                from core.state.state_manager import state_manager
                state_manager.record_failure(
                    domain="EMBEDDED",
                    affected_component=alert.device_id,
                    failure_type=alert.alert_type,
                    failure_reason=alert.message,
                    recovery_status="PENDING",
                    metadata=alert_dict
                )
            except Exception as sm_err:
                logger.debug(f"[ALERT GENERATOR] StateManager failure recording notice: {sm_err}")
        elif alert.status == AlertStatus.RESOLVED:
            try:
                from core.state.state_manager import state_manager
                state_manager.update_recovery_status(
                    domain="EMBEDDED",
                    affected_component=alert.device_id,
                    recovery_status="RECOVERED",
                    reason=f"Alert '{alert.condition}' resolved"
                )
            except Exception as sm_err:
                logger.debug(f"[ALERT GENERATOR] StateManager recovery recording notice: {sm_err}")

    # ---------------------------------------------------------------------------
    # Query & Administration API
    # ---------------------------------------------------------------------------

    def get_active_alerts(self, device_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve all currently active alerts, optionally filtered by device."""
        with self._lock:
            if device_id:
                dev_alerts = self._active_alerts.get(device_id, {})
                return [a.to_dict() for a in dev_alerts.values()]

            all_active = []
            for dev_alerts in self._active_alerts.values():
                for a in dev_alerts.values():
                    all_active.append(a.to_dict())
            return all_active

    def get_alert_history(self, limit: int = 50, device_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve recent alert history with optional device filtering."""
        with self._lock:
            history = list(self._alert_history)
            if device_id:
                history = [a for a in history if a.get("device_id") == device_id]
            return history[-limit:]

    def resolve_alert(self, alert_id: str, reason: str = "MANUAL_RESOLVE") -> Optional[TelemetryAlert]:
        """Manually resolve an active alert by ID."""
        with self._lock:
            for dev_id, dev_alerts in self._active_alerts.items():
                for cond_key, alert in list(dev_alerts.items()):
                    if alert.alert_id == alert_id:
                        del dev_alerts[cond_key]
                        alert.status = AlertStatus.RESOLVED
                        alert.resolved_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                        alert.metadata["resolve_reason"] = reason
                        self._alert_history.append(alert.to_dict())
                        self._dispatch_alert(alert)
                        return alert
        return None

    def clear_alerts(self, device_id: Optional[str] = None):
        """Clear active alerts cache (useful for test resets)."""
        with self._lock:
            if device_id:
                self._active_alerts.pop(device_id, None)
            else:
                self._active_alerts.clear()
                self._alert_history.clear()


# Global Singleton Instance
embedded_alert_generator = EmbeddedAlertGenerator()


def get_embedded_alert_generator() -> EmbeddedAlertGenerator:
    """Helper to access global Embedded Alert Generator instance."""
    return embedded_alert_generator
