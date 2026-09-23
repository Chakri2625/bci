import json
import math
import re
from typing import Any, Dict, Optional, Union

try:
    from models.telemetry_models import (
        EmbeddedTelemetry,
        SystemHealthTelemetry,
        KinematicsTelemetry,
        UnifiedTelemetryPacket,
        TelemetryDomain
    )
except ImportError:
    try:
        import sys
        import os
        _repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
        if _repo_root not in sys.path:
            sys.path.insert(0, _repo_root)
        from models.telemetry_models import (
            EmbeddedTelemetry,
            SystemHealthTelemetry,
            KinematicsTelemetry,
            UnifiedTelemetryPacket,
            TelemetryDomain
        )
    except Exception:
        EmbeddedTelemetry = None
        SystemHealthTelemetry = None
        KinematicsTelemetry = None
        UnifiedTelemetryPacket = None
        TelemetryDomain = None


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
    if value is None:
        return None

    if isinstance(value, bool):
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


# ==========================================================
# TELEMETRY MANAGER
# ==========================================================

class TelemetryManager:

    def __init__(self, socket):

        print("[Telemetry] Ready")

        self.socket = socket

        # --------------------------------------------------
        # Latest device information (backward compatible)
        # --------------------------------------------------

        self.latest = {

            "device": "UNKNOWN",

            "state": "STOP",

            "status": "OFFLINE",

            "ack": "",

            "last_command": "",

            "front_distance": 0.0,

            "rear_distance": 0.0,

            "front_obstacle": False,

            "rear_obstacle": False,

            "wifi": "DISCONNECTED",

            "mqtt": "DISCONNECTED",

            "battery_soc_pct": None,

            "supply_voltage_v": None,

            "normalized_telemetry": None
        }

        # --------------------------------------------------
        # Per-device state store (Robot + Wheelchair isolation)
        # --------------------------------------------------
        self.devices_latest: Dict[str, Dict[str, Any]] = {}

    def _get_or_init_device_state(self, device: str) -> Dict[str, Any]:
        """Retrieve or initialize isolated state store for a specific device."""
        dev_id = str(device or "UNKNOWN").strip()
        if dev_id not in self.devices_latest:
            self.devices_latest[dev_id] = {
                "device": dev_id,
                "device_id": dev_id,
                "state": "STOP",
                "status": "OFFLINE",
                "ack": "",
                "last_command": "",
                "front_distance": 0.0,
                "rear_distance": 0.0,
                "front_obstacle": False,
                "rear_obstacle": False,
                "wifi": "DISCONNECTED",
                "mqtt": "DISCONNECTED",
                "battery_soc_pct": None,
                "supply_voltage_v": None,
                "speed": 0.0,
                "speed_mode": "NORMAL",
                "normalized_telemetry": None
            }
        return self.devices_latest[dev_id]


    # ======================================================
    # MQTT MESSAGE HANDLER
    # ======================================================

    def handle_telemetry(
        self,
        topic,
        payload
    ):

        # One transport path: every MQTT message enters TelemetryManager
        # once, then is forwarded to browser clients through WebSocket.
        self.socket.handle_message(topic, payload)

        # ==================================================
        # ACK TOPIC
        # ==================================================

        if topic.endswith("/ack"):

            self.handle_ack(
                topic,
                payload
            )

            return


        # ==================================================
        # STATUS / TELEMETRY TOPIC
        # ==================================================

        if topic.endswith("/status") or topic.endswith("/telemetry"):

            self.handle_status(
                topic,
                payload
            )

            return


        # ==================================================
        # UNKNOWN TOPIC
        # ==================================================

        print(
            f"[Telemetry] Ignoring unknown topic: {topic}"
        )


    # ======================================================
    # ACK HANDLER
    # ======================================================

    def handle_ack(
        self,
        topic,
        payload
    ):

        device = self.extract_device(
            topic
        )

        ack = payload.strip()

        # ACK proves the slave is reachable through MQTT.
        self.socket.mqtt_device_status(
            device,
            "ONLINE"
        )

        # --------------------------------------------------
        # Store per-device and legacy latest
        # --------------------------------------------------
        dev_state = self._get_or_init_device_state(device)
        dev_state["device"] = device
        dev_state["device_id"] = device
        dev_state["ack"] = ack
        dev_state["last_command"] = ack
        dev_state["status"] = "ONLINE"
        dev_state["mqtt"] = "CONNECTED"

        self.latest["device"] = device
        self.latest["ack"] = ack
        self.latest["last_command"] = ack

        # Synchronize with Central State Manager
        try:
            from core.state.state_manager import state_manager
            sm_data = dict(dev_state)
            sm_data["device_id"] = device
            sm_data["domain"] = "EMBEDDED"
            state_manager.sync_device_state(sm_data, force=True)
        except Exception:
            pass

        # --------------------------------------------------
        # SINGLE ACK CONSOLE LOG
        # --------------------------------------------------

        print(
            f"[ESP32 ACK] Device: {device} | ACK: {ack}"
        )

        # --------------------------------------------------
        # Send ACK to website
        # --------------------------------------------------

        self.socket.ack({
            "device": device,
            "ack": ack,
            "topic": topic
        })

        # --------------------------------------------------
        # Also send activity log
        # --------------------------------------------------

        self.socket.activity(
            f"[ACK] {device}: {ack}"
        )

        # --------------------------------------------------
        # Update telemetry display
        # --------------------------------------------------

        self.socket.telemetry({
            "device": device,
            "device_id": device,
            "ack": ack
        })


    # ======================================================
    # ======================================================
    # STATUS HANDLER
    # ======================================================

    def handle_status(
        self,
        topic,
        payload
    ):

        device = self.extract_device(
            topic
        )

        dev_state = self._get_or_init_device_state(device)

        # --------------------------------------------------
        # Parse payload (JSON vs String)
        # --------------------------------------------------
        parsed_json = None
        raw_battery = None
        raw_voltage = None
        state_text = None

        if isinstance(payload, dict):
            parsed_json = payload
            status_text = str(payload.get("status") or payload.get("state") or "ONLINE").strip()
        else:
            raw_str = str(payload or "").strip()
            if raw_str.startswith("{") and raw_str.endswith("}"):
                try:
                    parsed_json = json.loads(raw_str)
                    status_text = str(parsed_json.get("status") or parsed_json.get("state") or "ONLINE").strip()
                except Exception:
                    parsed_json = None
                    status_text = raw_str
            else:
                status_text = raw_str

        if isinstance(parsed_json, dict):
            # 1. Search for battery field aliases
            for key in ("battery_soc_pct", "battery", "battery_pct", "battery_level", "soc"):
                if key in parsed_json:
                    raw_battery = parsed_json[key]
                    break
            if raw_battery is None and isinstance(parsed_json.get("system_health"), dict):
                sh = parsed_json["system_health"]
                for key in ("battery_soc_pct", "battery", "battery_pct", "battery_level", "soc"):
                    if key in sh:
                        raw_battery = sh[key]
                        break

            # 2. Search for supply voltage
            for key in ("supply_voltage_v", "supply_voltage", "voltage", "voltage_v"):
                if key in parsed_json:
                    raw_voltage = parsed_json[key]
                    break
            if raw_voltage is None and isinstance(parsed_json.get("system_health"), dict):
                sh = parsed_json["system_health"]
                for key in ("supply_voltage_v", "supply_voltage", "voltage", "voltage_v"):
                    if key in sh:
                        raw_voltage = sh[key]
                        break

            # 3. Explicit state
            if "state" in parsed_json:
                state_text = str(parsed_json["state"]).strip().upper()

            # 4. Ranging & obstacle telemetry
            if "front_distance" in parsed_json:
                try:
                    dev_state["front_distance"] = float(parsed_json["front_distance"])
                    self.latest["front_distance"] = dev_state["front_distance"]
                except (ValueError, TypeError):
                    pass
            if "rear_distance" in parsed_json:
                try:
                    dev_state["rear_distance"] = float(parsed_json["rear_distance"])
                    self.latest["rear_distance"] = dev_state["rear_distance"]
                except (ValueError, TypeError):
                    pass
            if "front_obstacle" in parsed_json:
                dev_state["front_obstacle"] = bool(parsed_json["front_obstacle"])
                self.latest["front_obstacle"] = dev_state["front_obstacle"]
            if "rear_obstacle" in parsed_json:
                dev_state["rear_obstacle"] = bool(parsed_json["rear_obstacle"])
                self.latest["rear_obstacle"] = dev_state["rear_obstacle"]
        else:
            # Check plain text status for battery substring, e.g. "BATTERY: 75%" or "BAT: 75"
            match_bat = re.search(r'battery[_\s]*(?:soc)?[_\s]*(?:pct|level)?[:=]?\s*(\d+)%?', status_text, re.IGNORECASE)
            if match_bat:
                raw_battery = match_bat.group(1)
            match_volt = re.search(r'(?:voltage|supply_voltage)[:=]?\s*([0-9]+(?:\.[0-9]+)?)v?', status_text, re.IGNORECASE)
            if match_volt:
                raw_voltage = match_volt.group(1)

        # --------------------------------------------------
        # Validate battery & supply voltage
        # --------------------------------------------------
        validated_battery = validate_battery_soc(raw_battery)
        validated_voltage = validate_supply_voltage(raw_voltage)

        # Normal slave status proves the MQTT path is active.
        # OFFLINE/DISCONNECTED is treated as a broken slave link.
        mqtt_device_state = (
            "DISCONNECTED"
            if status_text.upper() in ("OFFLINE", "DISCONNECTED")
            else "ONLINE"
        )

        self.socket.mqtt_device_status(
            device,
            mqtt_device_state
        )

        # --------------------------------------------------
        # Store latest device & status info (isolated per device)
        # --------------------------------------------------
        dev_state["device"] = device
        dev_state["device_id"] = device
        dev_state["status"] = status_text
        dev_state["mqtt"] = "CONNECTED" if mqtt_device_state == "ONLINE" else "DISCONNECTED"
        if validated_battery is not None:
            dev_state["battery_soc_pct"] = validated_battery
        if validated_voltage is not None:
            dev_state["supply_voltage_v"] = validated_voltage

        self.latest["device"] = device
        self.latest["status"] = status_text
        if validated_battery is not None:
            self.latest["battery_soc_pct"] = validated_battery
        if validated_voltage is not None:
            self.latest["supply_voltage_v"] = validated_voltage

        self.socket.update_device_status(
            device,
            status_text
        )

        # --------------------------------------------------
        # Determine basic state (movement)
        # --------------------------------------------------

        VALID_STATES = ("FORWARD", "BACKWARD", "LEFT", "RIGHT", "LEFT360", "RIGHT360", "STOP", "IDLE")
        if state_text in VALID_STATES:
            dev_state["state"] = state_text
            self.latest["state"] = state_text
        else:
            upper_status = status_text.upper()

            if "OBSTACLE" in upper_status:
                dev_state["state"] = "STOP"
            elif "FORWARD" in upper_status:
                dev_state["state"] = "FORWARD"
            elif "BACKWARD" in upper_status:
                dev_state["state"] = "BACKWARD"
            elif "LEFT360" in upper_status:
                dev_state["state"] = "LEFT360"
            elif "RIGHT360" in upper_status:
                dev_state["state"] = "RIGHT360"
            elif "LEFT" in upper_status:
                dev_state["state"] = "LEFT"
            elif "RIGHT" in upper_status:
                dev_state["state"] = "RIGHT"
            elif "STOP" in upper_status:
                dev_state["state"] = "STOP"
            
            self.latest["state"] = dev_state["state"]

        # --------------------------------------------------
        # Normalize into Standardized Telemetry Model
        # --------------------------------------------------
        dev_topic_lower = f"{device} {topic}".lower()
        if "chair" in dev_topic_lower or "wheelchair" in dev_topic_lower:
            device_mode = "WHEELCHAIR"
        elif "arm" in dev_topic_lower or "robotic_arm" in dev_topic_lower:
            device_mode = "ROBOTIC_ARM"
        else:
            device_mode = "RC_CAR"

        dev_state["device_mode"] = device_mode

        if SystemHealthTelemetry is not None and EmbeddedTelemetry is not None:
            try:
                free_heap = 0
                cpu_temp = None
                loop_hz = None
                if isinstance(parsed_json, dict):
                    sh = parsed_json.get("system_health") if isinstance(parsed_json.get("system_health"), dict) else parsed_json
                    try:
                        free_heap = int(sh.get("free_heap_bytes", 0))
                    except (ValueError, TypeError):
                        free_heap = 0
                    try:
                        cpu_temp = float(sh["cpu_core_temp_c"]) if sh.get("cpu_core_temp_c") is not None else None
                    except (ValueError, TypeError):
                        pass
                    try:
                        loop_hz = float(sh["loop_frequency_hz"]) if sh.get("loop_frequency_hz") is not None else None
                    except (ValueError, TypeError):
                        pass

                health_model = SystemHealthTelemetry(
                    free_heap_bytes=free_heap,
                    cpu_core_temp_c=cpu_temp,
                    supply_voltage_v=validated_voltage,
                    battery_soc_pct=validated_battery,
                    loop_frequency_hz=loop_hz
                )

                mov_state = dev_state["state"]
                kin_state = "MOVING_FORWARD" if mov_state == "FORWARD" else (
                    "MOVING_BACKWARD" if mov_state == "BACKWARD" else (
                        "TURNING_LEFT" if mov_state == "LEFT" else (
                            "TURNING_RIGHT" if mov_state == "RIGHT" else (
                                "ROTATING_360" if mov_state in ("LEFT360", "RIGHT360") else (
                                    "IDLE" if mov_state == "IDLE" else "STOPPED"
                                )
                            )
                        )
                    )
                )

                speed_val = 0.6 if mov_state in ("FORWARD", "BACKWARD", "LEFT", "RIGHT", "LEFT360", "RIGHT360") else 0.0
                if isinstance(parsed_json, dict) and "speed" in parsed_json:
                    try:
                        speed_val = float(parsed_json["speed"])
                    except (ValueError, TypeError):
                        pass

                kinematics_model = (
                    KinematicsTelemetry(
                        movement=mov_state,
                        state=kin_state,
                        speed=speed_val,
                        speed_mode="NORMAL"
                    )
                    if KinematicsTelemetry is not None
                    else None
                )

                embedded_telemetry = EmbeddedTelemetry(
                    device_id=device,
                    device_mode=device_mode,
                    status=mqtt_device_state if mqtt_device_state in ("ONLINE", "OFFLINE", "DEGRADED", "ERROR") else "ONLINE",
                    system_health=health_model,
                    kinematics=kinematics_model or KinematicsTelemetry()
                )

                dev_state["normalized_telemetry"] = embedded_telemetry.model_dump(exclude_none=True)
                self.latest["normalized_telemetry"] = dev_state["normalized_telemetry"]
            except Exception as e:
                print(f"[Telemetry Normalization Warning] {e}")

        # Synchronize with Central State Manager (Member 8 & 9)
        try:
            from core.state.state_manager import state_manager
            sm_data = dict(dev_state)
            sm_data["device_id"] = device
            sm_data["domain"] = "EMBEDDED"
            state_manager.sync_device_state(sm_data, force=True)
        except Exception:
            pass

        # --------------------------------------------------
        # SINGLE STATUS CONSOLE LOG
        # --------------------------------------------------

        battery_log = f" | Battery: {validated_battery}%" if validated_battery is not None else ""
        voltage_log = f" | Voltage: {validated_voltage}V" if validated_voltage is not None else ""

        print(
            f"[ESP32 STATUS] Device: {device} | "
            f"Mode: {device_mode} | "
            f"Status: {status_text} | "
            f"State: {dev_state['state']}"
            f"{battery_log}{voltage_log}"
        )

        # --------------------------------------------------
        # Send status and battery to website via WebSocket
        # --------------------------------------------------

        telemetry_payload = {
            "device": device,
            "device_id": device,
            "device_mode": device_mode,
            "status": status_text,
            "state": dev_state["state"]
        }

        if validated_battery is not None:
            telemetry_payload["battery_soc_pct"] = validated_battery
        elif dev_state.get("battery_soc_pct") is not None:
            telemetry_payload["battery_soc_pct"] = dev_state["battery_soc_pct"]

        if validated_voltage is not None:
            telemetry_payload["supply_voltage_v"] = validated_voltage
        elif dev_state.get("supply_voltage_v") is not None:
            telemetry_payload["supply_voltage_v"] = dev_state["supply_voltage_v"]

        for dist_key in ("front_distance", "rear_distance", "front_obstacle", "rear_obstacle"):
            if dist_key in dev_state and dev_state[dist_key] is not None:
                telemetry_payload[dist_key] = dev_state[dist_key]

        self.socket.telemetry(telemetry_payload)

        # --------------------------------------------------
        # Activity log
        # --------------------------------------------------

        self.socket.activity(
            f"[STATUS] {device} ({device_mode}): {status_text}{battery_log}"
        )

        # --------------------------------------------------
        # Server-Side Alert Evaluation (Sprint 11 Day 5 Members 6 & 9)
        # --------------------------------------------------
        try:
            from services.embedded_alert_generator import embedded_alert_generator
            eval_payload = dict(dev_state)
            eval_payload["device_id"] = device
            eval_payload["device_mode"] = device_mode
            eval_payload["status"] = status_text
            alerts = embedded_alert_generator.evaluate_telemetry(eval_payload)
            if alerts:
                for a in alerts:
                    if hasattr(self.socket, "alert"):
                        self.socket.alert(a.to_dict())
                    if hasattr(self.socket, "activity"):
                        prefix = "[CRITICAL ALERT]" if a.severity.value == "CRITICAL" else f"[{a.severity.value} ALERT]"
                        self.socket.activity(f"{prefix} {device}: {a.message}")
        except Exception as alert_err:
            print(f"[Telemetry Alert Warning] {alert_err}")



    # ======================================================
    # DEVICE EXTRACTION
    # ======================================================

    def extract_device(
        self,
        topic
    ):

        parts = str(topic or "").split("/")

        # Expected:
        # robotcar/<DEVICE_ID>/ack
        # robotcar/<DEVICE_ID>/status
        # wheelchair/<DEVICE_ID>/status
        # mesh/<DEVICE_ID>/telemetry

        if len(parts) >= 3:
            return parts[1]
        elif len(parts) == 2:
            return parts[0]

        return "UNKNOWN"


    # ======================================================
    # GET LATEST (PER-DEVICE & GLOBAL)
    # ======================================================

    def get_latest(self):
        """Backward compatible getter returning the latest global telemetry snapshot."""
        return self.latest

    def get_device_latest(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve isolated latest telemetry state for a specific device (Robot or Wheelchair)."""
        dev_id = str(device_id or "").strip()
        if dev_id in self.devices_latest:
            return dict(self.devices_latest[dev_id])
        return None

    def get_all_devices_latest(self) -> Dict[str, Dict[str, Any]]:
        """Retrieve dictionary of all registered device telemetry states."""
        return {k: dict(v) for k, v in self.devices_latest.items()}