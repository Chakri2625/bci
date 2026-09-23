"""
device_manager.py
-----------------
Maintains discovered ESP32 devices, relay states, sensor telemetry,
connectivity monitoring, offline/online transitions, and activity log ingestion.
Sprint 11 — IoT Pipeline Implementation (Tasks 1, 2, 4, 5).
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Dict, List, Optional, Tuple

from models.device_models import (
    ConnectionStatus,
    DeviceDomain,
    DeviceProtocol,
    DeviceState,
    DeviceType,
    IoTActivityRecord,
    NetworkInfo,
    OperationalStatus,
)

logger = logging.getLogger("plugins.iot.device_manager")


@dataclass
class Device:
    device_id: str
    mac: str
    system: str
    light: str
    fan: str
    pump: str
    firmware: str = "Unknown"
    last_seen: str = ""
    last_seen_timestamp: float = 0.0
    last_seen_iso: str = ""
    online: bool = True
    connection_status: str = "ONLINE"
    offline_reason: Optional[str] = None
    state_version: int = 1
    
    # Environmental & Sensor Telemetry
    temperature_celsius: Optional[float] = None
    humidity_pct: Optional[float] = None
    ambient_light_lux: Optional[float] = None
    motion_detected: Optional[bool] = None
    
    # Energy Telemetry
    voltage_v: Optional[float] = None
    current_a: Optional[float] = None
    power_watts: Optional[float] = None
    energy_kwh: Optional[float] = None
    
    # Connectivity
    wifi_rssi_dbm: Optional[int] = None
    ip_address: Optional[str] = None
    uptime_seconds: Optional[int] = None
    
    # Raw extra sensor bag
    sensors: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize dataclass to clean dictionary."""
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}

    def get_relay_snapshot(self) -> Dict[str, str]:
        return {
            "light": self.light,
            "fan": self.fan,
            "pump": self.pump,
        }

    def to_device_state(self) -> DeviceState:
        """Convert into authoritative Pydantic DeviceState schema."""
        return DeviceState.from_iot_device(self)


class DeviceManager:
    """
    Thread-safe IoT Device Manager coordinating device states, sensor readings,
    connection health tracking, offline detection, and activity log ingestion.
    """

    def __init__(self):
        self.devices: Dict[str, Device] = {}
        self.selected_device: Optional[str] = None
        self.activity_logs: List[IoTActivityRecord] = []
        self.lock = RLock()
        self.max_activity_logs = 500

    # ----------------------------------------------------
    # Activity Log Ingestion (Task 2)
    # ----------------------------------------------------
    def log_activity(
        self,
        device_id: str,
        action: str,
        previous_state: Optional[Dict[str, Any]] = None,
        new_state: Optional[Dict[str, Any]] = None,
        source: str = "MQTT",
        status: str = "SUCCESS",
        reason: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> IoTActivityRecord:
        """
        Record a structured activity log record, store in memory and backend event history.
        """
        now = time.time()
        iso_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        record = IoTActivityRecord(
            activity_id=f"ACT-IOT-{uuid.uuid4().hex[:10]}",
            device_id=device_id,
            action=action,
            previous_state=previous_state,
            new_state=new_state,
            timestamp=now,
            timestamp_iso=iso_ts,
            source=source,
            status=status,
            reason=reason,
            metadata=metadata or {},
        )

        with self.lock:
            self.activity_logs.insert(0, record)
            if len(self.activity_logs) > self.max_activity_logs:
                self.activity_logs.pop()

        # Integrate with backend event history manager
        try:
            from core.managers.event_history import event_history_manager, EventType, EventStatus
            
            evt_type = EventType.DEVICE_STATE_CHANGED
            if "CONNECT" in action.upper() or "ONLINE" in action.upper():
                evt_type = EventType.DEVICE_CONNECTED
            elif "OFFLINE" in action.upper() or "TIMEOUT" in action.upper() or "DISCONNECT" in action.upper():
                evt_type = EventType.DEVICE_DISCONNECTED

            event_history_manager.record_event(
                event_type=evt_type,
                command=action,
                command_id=record.activity_id,
                domain="IOT",
                status=EventStatus.SUCCESS if status.upper() in ("SUCCESS", "ONLINE", "RECONNECTED") else EventStatus.FAILED,
                metadata={
                    "device_id": device_id,
                    "action": action,
                    "previous_state": previous_state,
                    "new_state": new_state,
                    "source": source,
                    "reason": reason,
                    **(metadata or {}),
                }
            )
        except Exception as e:
            logger.debug(f"Event history recording skipped: {e}")

        logger.info(f"[ACTIVITY_LOG] Device={device_id} Action={action} Status={status} Reason={reason}")
        return record

    def get_activity_logs(
        self,
        device_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Retrieve stored activity logs with optional device_id filter."""
        with self.lock:
            if device_id:
                filtered = [r.to_dict() for r in self.activity_logs if r.device_id == device_id]
            else:
                filtered = [r.to_dict() for r in self.activity_logs]
            return filtered[:limit]

    # ----------------------------------------------------
    # Add or Update Device Status (Tasks 1, 4, 5)
    # ----------------------------------------------------
    def update_device(self, payload: dict) -> Tuple[Optional[Device], Optional[IoTActivityRecord]]:
        """
        Ingest incoming device state, parse payload, validate, and update state.
        Detects transitions from offline -> online and changes in relay states.
        """
        device_id = payload.get("device_id") or payload.get("deviceId") or payload.get("mac")
        if not device_id:
            return None, None

        states = payload.get("states", {})
        if not isinstance(states, dict):
            states = {}

        now_sec = time.time()
        now_str = datetime.now().strftime("%H:%M:%S")
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        activity_record = None

        with self.lock:
            if device_id not in self.devices:
                dev = Device(
                    device_id=device_id,
                    mac=payload.get("mac") or payload.get("deviceId", device_id),
                    system=payload.get("system", "ESP32"),
                    light=str(states.get("light", payload.get("light", "OFF"))).upper(),
                    fan=str(states.get("fan", payload.get("fan", "OFF"))).upper(),
                    pump=str(states.get("pump", payload.get("pump", "OFF"))).upper(),
                    firmware=payload.get("firmware", "2.0.0-unified"),
                    last_seen=now_str,
                    last_seen_timestamp=now_sec,
                    last_seen_iso=now_iso,
                    online=True,
                    connection_status="ONLINE",
                    offline_reason=None,
                    state_version=1,
                    wifi_rssi_dbm=payload.get("rssi") or payload.get("wifi_rssi_dbm"),
                    ip_address=payload.get("ip") or payload.get("ip_address"),
                    uptime_seconds=payload.get("uptime") or payload.get("uptime_seconds"),
                )
                self.devices[device_id] = dev
                
                # Log initial registration / connection
                activity_record = self.log_activity(
                    device_id=device_id,
                    action="DEVICE_REGISTERED",
                    previous_state=None,
                    new_state=dev.get_relay_snapshot(),
                    source=payload.get("source", "MQTT"),
                    status="SUCCESS",
                    reason="Initial device discovery",
                )
                return dev, activity_record

            device = self.devices[device_id]
            prev_relays = device.get_relay_snapshot()
            was_offline = not device.online

            # Update core metadata
            device.mac = payload.get("mac") or payload.get("deviceId", device.mac)
            device.system = payload.get("system", device.system)
            device.firmware = payload.get("firmware", device.firmware)
            device.last_seen = now_str
            device.last_seen_timestamp = now_sec
            device.last_seen_iso = now_iso

            # Update relay states if present
            new_light = str(states.get("light", payload.get("light", device.light))).upper()
            new_fan = str(states.get("fan", payload.get("fan", device.fan))).upper()
            new_pump = str(states.get("pump", payload.get("pump", device.pump))).upper()

            relays_changed = (
                new_light != device.light
                or new_fan != device.fan
                or new_pump != device.pump
            )

            device.light = new_light
            device.fan = new_fan
            device.pump = new_pump

            # Reconnection detection (Task 5)
            if was_offline:
                device.online = True
                device.connection_status = "ONLINE"
                device.offline_reason = None
                device.state_version += 1
                activity_record = self.log_activity(
                    device_id=device_id,
                    action="DEVICE_RECONNECTED",
                    previous_state={"connection_status": "OFFLINE", **prev_relays},
                    new_state={"connection_status": "ONLINE", **device.get_relay_snapshot()},
                    source=payload.get("source", "MQTT"),
                    status="ONLINE",
                    reason="Device heartbeat / payload received",
                )
            elif relays_changed:
                device.state_version += 1
                activity_record = self.log_activity(
                    device_id=device_id,
                    action="RELAY_STATE_CHANGED",
                    previous_state=prev_relays,
                    new_state=device.get_relay_snapshot(),
                    source=payload.get("source", "MQTT"),
                    status="SUCCESS",
                    reason=payload.get("reason", "Relay state update"),
                )

            # Network info
            if "rssi" in payload or "wifi_rssi_dbm" in payload:
                device.wifi_rssi_dbm = payload.get("rssi") or payload.get("wifi_rssi_dbm")
            if "ip" in payload or "ip_address" in payload:
                device.ip_address = payload.get("ip") or payload.get("ip_address")
            if "uptime" in payload or "uptime_seconds" in payload:
                device.uptime_seconds = payload.get("uptime") or payload.get("uptime_seconds")

            return device, activity_record

    # ----------------------------------------------------
    # Update Environmental & Energy Sensor Telemetry (Task 1)
    # ----------------------------------------------------
    def update_sensors(self, device_id: str, sensor_payload: dict) -> Tuple[Optional[Device], Optional[IoTActivityRecord]]:
        """Update environmental, energy, and telemetry readings for a device."""
        if not device_id or not isinstance(sensor_payload, dict):
            return None, None

        activity_record = None

        with self.lock:
            if device_id not in self.devices:
                self.update_device({"device_id": device_id})

            device = self.devices.get(device_id)
            if not device:
                return None, None

            now_sec = time.time()
            device.last_seen = datetime.now().strftime("%H:%M:%S")
            device.last_seen_timestamp = now_sec
            device.last_seen_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

            was_offline = not device.online
            if was_offline:
                device.online = True
                device.connection_status = "ONLINE"
                device.offline_reason = None
                device.state_version += 1
                activity_record = self.log_activity(
                    device_id=device_id,
                    action="DEVICE_RECONNECTED",
                    previous_state={"connection_status": "OFFLINE"},
                    new_state={"connection_status": "ONLINE"},
                    source="SENSOR_MQTT",
                    status="ONLINE",
                    reason="Sensor telemetry stream resumed",
                )

            # Temperature
            for key in ("temp", "temperature", "temperature_celsius"):
                if key in sensor_payload and sensor_payload[key] is not None:
                    try:
                        device.temperature_celsius = float(sensor_payload[key])
                        break
                    except (ValueError, TypeError):
                        pass

            # Humidity
            for key in ("humidity", "humidity_pct"):
                if key in sensor_payload and sensor_payload[key] is not None:
                    try:
                        device.humidity_pct = float(sensor_payload[key])
                        break
                    except (ValueError, TypeError):
                        pass

            # Lux
            for key in ("lux", "ambient_light_lux", "light_level"):
                if key in sensor_payload and sensor_payload[key] is not None:
                    try:
                        device.ambient_light_lux = float(sensor_payload[key])
                        break
                    except (ValueError, TypeError):
                        pass

            # Motion
            for key in ("motion", "motion_detected"):
                if key in sensor_payload and sensor_payload[key] is not None:
                    val = sensor_payload[key]
                    device.motion_detected = bool(val)
                    break

            # Voltage, Current, Power, Energy
            for key in ("voltage", "voltage_v"):
                if key in sensor_payload and sensor_payload[key] is not None:
                    try:
                        device.voltage_v = float(sensor_payload[key])
                        break
                    except (ValueError, TypeError):
                        pass

            for key in ("current", "current_a"):
                if key in sensor_payload and sensor_payload[key] is not None:
                    try:
                        device.current_a = float(sensor_payload[key])
                        break
                    except (ValueError, TypeError):
                        pass

            for key in ("power", "power_watts"):
                if key in sensor_payload and sensor_payload[key] is not None:
                    try:
                        device.power_watts = float(sensor_payload[key])
                        break
                    except (ValueError, TypeError):
                        pass

            for key in ("energy", "energy_kwh"):
                if key in sensor_payload and sensor_payload[key] is not None:
                    try:
                        device.energy_kwh = float(sensor_payload[key])
                        break
                    except (ValueError, TypeError):
                        pass

            # RSSI
            for key in ("rssi", "wifi_rssi_dbm"):
                if key in sensor_payload and sensor_payload[key] is not None:
                    try:
                        device.wifi_rssi_dbm = int(sensor_payload[key])
                        break
                    except (ValueError, TypeError):
                        pass

            device.sensors.update(sensor_payload)
            return device, activity_record

    # ----------------------------------------------------
    # Connection Monitoring & Offline State Updates (Tasks 4 & 5)
    # ----------------------------------------------------
    def set_device_offline(
        self,
        device_id: str,
        reason: str = "Heartbeat timeout (>15s)",
    ) -> Optional[IoTActivityRecord]:
        """
        Explicitly mark a device as OFFLINE / DISCONNECTED, capture state, and log activity.
        """
        with self.lock:
            device = self.devices.get(device_id)
            if not device:
                return None

            if not device.online and device.connection_status == "OFFLINE":
                return None  # Already offline

            prev_state = {
                "connection_status": device.connection_status,
                "online": device.online,
                **device.get_relay_snapshot(),
            }

            device.online = False
            device.connection_status = "OFFLINE"
            device.offline_reason = reason
            device.state_version += 1

            new_state = {
                "connection_status": "OFFLINE",
                "online": False,
                "reason": reason,
                **device.get_relay_snapshot(),
            }

            activity_record = self.log_activity(
                device_id=device_id,
                action="DEVICE_OFFLINE",
                previous_state=prev_state,
                new_state=new_state,
                source="CONNECTION_MONITOR",
                status="OFFLINE",
                reason=reason,
            )
            return activity_record

    def set_device_online(
        self,
        device_id: str,
        reason: str = "Device heartbeat received",
    ) -> Optional[IoTActivityRecord]:
        """Explicitly mark a device as ONLINE / CONNECTED."""
        with self.lock:
            device = self.devices.get(device_id)
            if not device:
                return None

            if device.online and device.connection_status == "ONLINE":
                return None

            prev_state = {
                "connection_status": device.connection_status,
                "online": device.online,
                **device.get_relay_snapshot(),
            }

            device.online = True
            device.connection_status = "ONLINE"
            device.offline_reason = None
            device.last_seen = datetime.now().strftime("%H:%M:%S")
            device.last_seen_timestamp = time.time()
            device.last_seen_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            device.state_version += 1

            new_state = {
                "connection_status": "ONLINE",
                "online": True,
                **device.get_relay_snapshot(),
            }

            activity_record = self.log_activity(
                device_id=device_id,
                action="DEVICE_ONLINE",
                previous_state=prev_state,
                new_state=new_state,
                source="CONNECTION_MONITOR",
                status="ONLINE",
                reason=reason,
            )
            return activity_record

    def check_timeouts(self, timeout_seconds: float = 15.0) -> List[IoTActivityRecord]:
        """
        Scan all tracked devices and transition timed-out devices to OFFLINE.
        Returns list of newly generated activity records.
        """
        now = time.time()
        timeout_records: List[IoTActivityRecord] = []

        with self.lock:
            for device_id, device in self.devices.items():
                if device.online:
                    age = now - device.last_seen_timestamp
                    if age > timeout_seconds:
                        rec = self.set_device_offline(
                            device_id=device_id,
                            reason=f"Heartbeat timeout (elapsed {age:.1f}s > {timeout_seconds}s)",
                        )
                        if rec:
                            timeout_records.append(rec)

        return timeout_records

    # ----------------------------------------------------
    # Queries & State Export (Task 1 & 6)
    # ----------------------------------------------------
    def get_device(self, device_id: str) -> Optional[Device]:
        with self.lock:
            return self.devices.get(device_id)

    def get_all_devices(self) -> List[Device]:
        with self.lock:
            return list(self.devices.values())

    def get_all_device_states(self) -> List[DeviceState]:
        with self.lock:
            return [d.to_device_state() for d in self.devices.values()]

    def to_device_state(self, device_id: str) -> Optional[DeviceState]:
        with self.lock:
            dev = self.devices.get(device_id)
            return dev.to_device_state() if dev else None

    def remove_device(self, device_id: str):
        with self.lock:
            if device_id in self.devices:
                del self.devices[device_id]

    def total_devices(self) -> int:
        with self.lock:
            return len(self.devices)

    def online_devices_count(self) -> int:
        with self.lock:
            return sum(1 for d in self.devices.values() if d.online)