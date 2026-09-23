"""
device_models.py
================
Standard Device-State Models for SynaptiMesh across IoT, Embedded, Robotics, and BCI Domains.
Built with Pydantic V2 for unified device registry, status tracking, capability negotiation,
and JSON Schema generation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import time
import uuid
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums for Standardized Device State Attributes
# ---------------------------------------------------------------------------

class DeviceDomain(str, Enum):
    """Supported ecosystem domains."""
    IOT = "IOT"
    EMBEDDED = "EMBEDDED"
    ROBOTICS = "ROBOTICS"
    BCI = "BCI"
    DESKTOP = "DESKTOP"
    MEDIA = "MEDIA"
    AIML = "AIML"


class DeviceType(str, Enum):
    """Device category classifications across all domains."""
    SMART_RELAY = "SMART_RELAY"
    SENSOR_NODE = "SENSOR_NODE"
    SMART_HUB = "SMART_HUB"
    RC_CAR = "RC_CAR"
    WHEELCHAIR = "WHEELCHAIR"
    ROBOTIC_ARM = "ROBOTIC_ARM"
    BCI_HEADSET = "BCI_HEADSET"
    DESKTOP_NODE = "DESKTOP_NODE"
    MEDIA_PLAYER = "MEDIA_PLAYER"
    INFERENCE_NODE = "INFERENCE_NODE"
    GENERIC = "GENERIC"


class DeviceProtocol(str, Enum):
    """Communication protocols used to interface with the device."""
    MQTT = "MQTT"
    WEBSOCKET = "WEBSOCKET"
    TCP_SOCKET = "TCP_SOCKET"
    HTTP = "HTTP"
    UART = "UART"
    CAN = "CAN"
    BLE = "BLE"
    SERIAL = "SERIAL"
    MOCK = "MOCK"


class ConnectionStatus(str, Enum):
    """Physical or network transport connectivity state."""
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    CONNECTING = "CONNECTING"
    DISCONNECTED = "DISCONNECTED"
    DEGRADED = "DEGRADED"
    ERROR = "ERROR"


class OperationalStatus(str, Enum):
    """Operational / execution availability state."""
    IDLE = "IDLE"
    BUSY = "BUSY"
    EXECUTING = "EXECUTING"
    STANDBY = "STANDBY"
    ERROR = "ERROR"
    MAINTENANCE = "MAINTENANCE"


# ---------------------------------------------------------------------------
# Network Diagnostics Sub-model
# ---------------------------------------------------------------------------

class NetworkInfo(BaseModel):
    """Network connection details and hardware identifiers."""
    model_config = ConfigDict(extra="ignore")

    ip_address: Optional[str] = Field(None, description="IPv4 or IPv6 network address")
    mac_address: Optional[str] = Field(None, description="Hardware MAC address")
    wifi_rssi_dbm: Optional[int] = Field(None, description="WiFi RSSI signal level in dBm")
    port: Optional[int] = Field(None, description="Active communication port")
    hostname: Optional[str] = Field(None, description="Device network hostname")
    uptime_seconds: Optional[int] = Field(None, ge=0, description="Device uptime since last boot in seconds")


# ---------------------------------------------------------------------------
# Domain-Specific State Payloads (Flexible dictionary wrappers / helpers)
# ---------------------------------------------------------------------------

class IotRelayState(BaseModel):
    """Operational actuator state for IoT smart switch / relay nodes."""
    model_config = ConfigDict(extra="ignore")

    light: str = Field("OFF", description="Light relay state (ON, OFF, TOGGLE)")
    fan: str = Field("OFF", description="Fan relay state (ON, OFF, TOGGLE)")
    pump: str = Field("OFF", description="Pump relay state (ON, OFF, TOGGLE)")
    power_state: str = Field("ACTIVE", description="Power supply mode (ACTIVE, STANDBY, LOW_POWER)")


class EmbeddedKinematicState(BaseModel):
    """Operational kinematic and motion state for robotics / vehicles."""
    model_config = ConfigDict(extra="ignore")

    motion_state: str = Field("STOP", description="Active motion state (STOP, FORWARD, BACKWARD, LEFT, RIGHT, etc.)")
    speed_mode: str = Field("NORMAL", description="Configured speed profile (SLOW, NORMAL, FAST, TURBO)")
    steering_angle_deg: Optional[float] = Field(0.0, description="Steering angle in degrees")
    emergency_stop: bool = Field(False, description="Emergency stop hardware or software trigger state")
    last_command: Optional[str] = Field(None, description="Last successfully executed command")


class BciDeviceState(BaseModel):
    """Operational hardware state for BCI headsets."""
    model_config = ConfigDict(extra="ignore")

    battery_pct: Optional[int] = Field(None, ge=0, le=100, description="Headset battery charge percentage")
    signal_quality_summary: Optional[str] = Field("GOOD", description="Aggregated contact quality status (EXCELLENT, GOOD, POOR, NO_SIGNAL)")
    active_profile: Optional[str] = Field(None, description="Active user calibration or mental profile")
    headset_model: str = Field("Emotiv EPOC X", description="Headset model identifier")


# ---------------------------------------------------------------------------
# Standard Device-State Envelope Model
# ---------------------------------------------------------------------------

def _current_timestamp() -> float:
    return time.time()


def _current_iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class DeviceState(BaseModel):
    """
    Unified Standard Device-State Model for SynaptiMesh.
    Provides authoritative representation of device identity, connectivity health,
    operational status, capabilities, firmware, and domain-specific state snapshots.
    """
    model_config = ConfigDict(extra="ignore", use_enum_values=True)

    device_id: str = Field(..., description="Unique hardware MAC, serial number, or logical ID")
    device_name: Optional[str] = Field(None, description="Human-friendly device name or label")
    domain: DeviceDomain = Field(..., description="Operational domain (IOT, EMBEDDED, ROBOTICS, BCI, etc.)")
    device_type: DeviceType = Field(..., description="Device classification (SMART_RELAY, RC_CAR, BCI_HEADSET, etc.)")
    protocol: DeviceProtocol = Field(DeviceProtocol.MQTT, description="Primary transport protocol")
    connection_status: ConnectionStatus = Field(ConnectionStatus.ONLINE, description="Physical/network connection state")
    operational_status: OperationalStatus = Field(OperationalStatus.IDLE, description="Operational readiness / execution state")
    capabilities: List[str] = Field(default_factory=list, description="Supported commands and operational features")
    last_seen_timestamp: float = Field(default_factory=_current_timestamp, description="Epoch timestamp of last contact")
    last_seen_iso: str = Field(default_factory=_current_iso_utc, description="ISO-8601 UTC timestamp of last contact")
    firmware_version: Optional[str] = Field(None, description="Firmware or software release version")
    network_info: Optional[NetworkInfo] = Field(None, description="Network connection parameters and metrics")
    state: Dict[str, Any] = Field(default_factory=dict, description="Domain-specific operational state snapshot")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Extensible device metadata or configuration properties")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize model to a clean JSON-serializable dictionary."""
        return self.model_dump(exclude_none=True)

    @classmethod
    def from_iot_device(cls, device_obj: Any) -> DeviceState:
        """
        Factory helper to map existing plugins.iot.device_manager.Device instances
        or status payloads into the standardized DeviceState model.
        """
        if hasattr(device_obj, "__dict__"):
            data = getattr(device_obj, "__dict__")
        elif isinstance(device_obj, dict):
            data = device_obj
        else:
            raise ValueError(f"Unsupported device object type: {type(device_obj)}")

        device_id = data.get("device_id") or data.get("deviceId") or "UNKNOWN_IOT"
        mac = data.get("mac") or data.get("deviceId")
        is_online = data.get("online", True)
        
        status_str = ConnectionStatus.ONLINE if is_online else ConnectionStatus.OFFLINE
        
        # Extract relay states & sensor values
        relay_state = {
            "light": data.get("light", "OFF"),
            "fan": data.get("fan", "OFF"),
            "pump": data.get("pump", "OFF"),
        }
        sensors = {}
        for k in ["temperature_celsius", "humidity_pct", "ambient_light_lux", "motion_detected", "voltage_v", "current_a", "power_watts", "energy_kwh"]:
            if data.get(k) is not None:
                sensors[k] = data.get(k)
        if hasattr(device_obj, "sensors") and getattr(device_obj, "sensors"):
            sensors.update(getattr(device_obj, "sensors"))
        elif isinstance(data.get("sensors"), dict):
            sensors.update(data.get("sensors"))

        state_dict = {**relay_state}
        if sensors:
            state_dict["sensors"] = sensors
        
        # Network Info
        net_info = NetworkInfo(
            ip_address=data.get("ip_address") or data.get("ip"),
            mac_address=mac,
            wifi_rssi_dbm=data.get("wifi_rssi_dbm") or data.get("rssi"),
            uptime_seconds=data.get("uptime_seconds") or data.get("uptime")
        )

        last_seen_ts = data.get("last_seen_timestamp") or time.time()
        try:
            last_seen_iso = datetime.fromtimestamp(last_seen_ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        except Exception:
            last_seen_iso = _current_iso_utc()

        capabilities = [
            "left_light_on", "left_light_off",
            "left_fan_on", "left_fan_off",
            "left_pump_on", "left_pump_off",
            "toggle_light", "toggle_fan", "toggle_pump"
        ]

        metadata = {"system": data.get("system", "ESP32")}
        if data.get("offline_reason"):
            metadata["offline_reason"] = data.get("offline_reason")
        if data.get("state_version"):
            metadata["state_version"] = data.get("state_version")

        return cls(
            device_id=device_id,
            device_name=f"IoT Relay ({device_id})",
            domain=DeviceDomain.IOT,
            device_type=DeviceType.SMART_RELAY,
            protocol=DeviceProtocol.MQTT,
            connection_status=status_str,
            operational_status=OperationalStatus.IDLE if is_online else OperationalStatus.ERROR,
            capabilities=capabilities,
            last_seen_timestamp=last_seen_ts,
            last_seen_iso=last_seen_iso,
            firmware_version=data.get("firmware", "2.0.0-unified"),
            network_info=net_info,
            state=state_dict,
            metadata=metadata
        )

    @classmethod
    def from_embedded_status(cls, device_id: str, status_data: Dict[str, Any], target_type: str = "RC_CAR") -> DeviceState:
        """
        Factory helper to map embedded status payloads (RC Car, Wheelchair)
        into the standardized DeviceState model.
        """
        is_car = "car" in target_type.lower()
        dev_type = DeviceType.RC_CAR if is_car else DeviceType.WHEELCHAIR
        domain = DeviceDomain.ROBOTICS if is_car else DeviceDomain.EMBEDDED

        raw_status = str(status_data.get("status", "ONLINE")).upper()
        is_offline = "OFFLINE" in raw_status or not status_data.get("online", True)
        conn_status = ConnectionStatus.OFFLINE if is_offline else ConnectionStatus.ONLINE

        capabilities = [
            "FORWARD", "BACKWARD", "LEFT", "RIGHT",
            "LEFT360", "RIGHT360", "STOP"
        ] if is_car else ["FORWARD", "BACKWARD", "LEFT", "RIGHT", "STOP"]

        motion_state = status_data.get("state") or status_data.get("motion_state") or "STOP"
        last_seen_ts = status_data.get("last_seen_timestamp") or time.time()
        
        try:
            last_seen_iso = datetime.fromtimestamp(last_seen_ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        except Exception:
            last_seen_iso = _current_iso_utc()

        state_payload = {
            "motion_state": motion_state,
            "speed_mode": status_data.get("speed_mode", "NORMAL"),
            "last_command": status_data.get("last_command") or status_data.get("ack")
        }

        net_info = NetworkInfo(
            ip_address=status_data.get("ip_address") or status_data.get("ip"),
            mac_address=status_data.get("mac_address") or status_data.get("mac"),
            wifi_rssi_dbm=status_data.get("wifi_rssi_dbm")
        )

        return cls(
            device_id=device_id,
            device_name=f"Robotics Vehicle ({device_id})",
            domain=domain,
            device_type=dev_type,
            protocol=DeviceProtocol.MQTT,
            connection_status=conn_status,
            operational_status=OperationalStatus.IDLE if not is_offline else OperationalStatus.ERROR,
            capabilities=capabilities,
            last_seen_timestamp=last_seen_ts,
            last_seen_iso=last_seen_iso,
            firmware_version=status_data.get("firmware_version", "1.0.0"),
            network_info=net_info,
            state=state_payload,
            metadata={"mcu": status_data.get("mcu", "ESP32")}
        )


# ---------------------------------------------------------------------------
# IoT Activity Record Model (Task 2)
# ---------------------------------------------------------------------------

class IoTActivityRecord(BaseModel):
    """
    Structured Activity Log Record for IoT device actions and state transitions.
    """
    model_config = ConfigDict(extra="ignore")

    activity_id: str = Field(default_factory=lambda: f"ACT-{uuid.uuid4().hex[:12]}", description="Unique activity log entry ID")
    device_id: str = Field(..., description="Unique hardware or logical device identifier")
    action: str = Field(..., description="Action, command, or lifecycle event name (e.g. TOGGLE_LIGHT, OFFLINE_TIMEOUT, CONNECTED)")
    previous_state: Optional[Dict[str, Any]] = Field(None, description="Device state prior to action")
    new_state: Optional[Dict[str, Any]] = Field(None, description="Device state after action execution")
    timestamp: float = Field(default_factory=_current_timestamp, description="Epoch timestamp of activity")
    timestamp_iso: str = Field(default_factory=_current_iso_utc, description="ISO-8601 UTC timestamp")
    source: str = Field("MQTT", description="Source of action (MQTT, BCI, REST_API, DASHBOARD, TIMEOUT_MONITOR)")
    status: str = Field("SUCCESS", description="Outcome status (SUCCESS, FAILED, OFFLINE, TIMEOUT, RECONNECTED)")
    reason: Optional[str] = Field(None, description="Optional explanation or trigger reason")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary additional context")

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True)

