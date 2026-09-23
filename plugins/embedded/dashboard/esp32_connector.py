import sys
import os
import time
import json
import asyncio
import threading
from typing import Dict, Any, Optional, Callable, List
import requests

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class ESP32Connector:
    def __init__(
        self,
        mode: str = "mqtt",
        esp32_ip: str = "172.28.27.14",
        esp32_port: int = 80,
        serial_port_path: str = "COM5",
        baud_rate: int = 115200,
        mqtt_broker: str = "52.21.249.6",
        mqtt_port: int = 1883,
        mqtt_user: str = "",
        mqtt_password: str = "",
        mqtt_base_topic: str = "iot",
        mqtt_device_id: str = "esp32",
        mqtt_topic_action: str = "",
        mqtt_topic_status: str = "",
        mqtt_topic_ack: str = "",
        mqtt_client_id: str = "",
        # Backward compatibility alias
        mqtt_topic_cmd: str = "",
    ):
        self.mode = mode or os.getenv("ESP32_MODE", "mqtt")
        self.esp32_ip = (esp32_ip or os.getenv("ESP32_IP", "172.28.27.14")).strip()
        self.esp32_port = int(esp32_port or os.getenv("ESP32_PORT", 80))
        self.serial_port_path = (serial_port_path or os.getenv("ESP32_SERIAL_PORT", "COM5")).strip()
        self.baud_rate = int(baud_rate or os.getenv("ESP32_BAUD_RATE", 115200))

        # MQTT Broker & Topic Schema Configuration
        self.mqtt_broker = (mqtt_broker or os.getenv("MQTT_BROKER", "52.21.249.6")).strip()
        self.mqtt_port = int(mqtt_port or os.getenv("MQTT_PORT", 1883))
        self.mqtt_user = (mqtt_user or os.getenv("MQTT_USER", "")).strip()
        self.mqtt_password = (mqtt_password or os.getenv("MQTT_PASSWORD", "")).strip()
        configured_client_id = (mqtt_client_id or os.getenv("MQTT_CLIENT_ID", "")).strip()
        if not configured_client_id or configured_client_id == "synaptimesh_master_hub":
            configured_client_id = f"synaptimesh_master_hub_{os.getpid()}"
        self.mqtt_client_id = configured_client_id

        # FIXED Robot Car MQTT contract. The ESP32 firmware listens on /control
        # and publishes /ack + /status. Legacy /action configuration is ignored.
        self.mqtt_base_topic = (mqtt_base_topic or os.getenv("MQTT_BASE_TOPIC", "robotcar")).strip().rstrip("/")
        self.mqtt_device_id = (mqtt_device_id or os.getenv("MQTT_DEVICE_ID", "98:A3:16:BF:2C:C0")).strip().strip("/")
        self._set_robot_car_topics()

        self.mqtt_client = None
        self.mqtt_connected = False
        self.robot_car_online: Optional[bool] = None
        self._mqtt_manual_disconnect = False
        self._mqtt_disconnect_logged = False
        self._ack_lock = threading.Lock()
        self._pending_acks = []
        self._mqtt_connecting = False
        self.mqtt_last_seen: Optional[float] = None

        self.serial_conn = None
        self._serial_thread = None
        self._stop_serial = False

        self.is_connected = False
        self.last_latency: Optional[int] = None
        self.last_error: Optional[str] = None
        self.active_ws_client = None  # WebSocket object
        self._async_loop = None
        self._mqtt_manual_disconnect = False

        self.device_states: Dict[str, str] = {
            "light": "OFF",
            "fan": "OFF",
            "pump": "OFF",
        }

        self._listeners: Dict[str, List[Callable]] = {}

    def bind_async_loop(self, loop):
        """Bind the FastAPI event loop for callbacks originating from MQTT/serial threads."""
        self._async_loop = loop

    def _set_robot_car_topics(self):
        """Derive the exact Robot Car topics from base topic and device ID."""
        prefix = f"{self.mqtt_base_topic.rstrip('/')}/{self.mqtt_device_id.strip('/')}"
        self.mqtt_topic_action = f"{prefix}/control"
        self.mqtt_topic_cmd = self.mqtt_topic_action
        self.mqtt_topic_status = f"{prefix}/status"
        self.mqtt_topic_ack = f"{prefix}/ack"

    def on(self, event_name: str, callback: Callable):
        if event_name not in self._listeners:
            self._listeners[event_name] = []
        self._listeners[event_name].append(callback)

    def emit(self, event_name: str, data: Any = None):
        if event_name not in self._listeners:
            return
        for callback in list(self._listeners[event_name]):
            try:
                if asyncio.iscoroutinefunction(callback):
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        loop = self._async_loop
                    if loop and loop.is_running():
                        loop.call_soon_threadsafe(loop.create_task, callback(data))
                else:
                    callback(data)
            except Exception as e:
                print(f"[ERROR in ESP32 listener '{event_name}']: {e}")

    @staticmethod
    def get_available_ports() -> List[Dict[str, str]]:
        """Scans and lists all system COM / Serial ports with hardware descriptions."""
        ports_list = []
        try:
            import serial.tools.list_ports
            for p in serial.tools.list_ports.comports():
                ports_list.append({
                    "port": p.device,
                    "description": p.description,
                    "hwid": p.hwid or "",
                    "isEsp32": "cp210" in (p.description or "").lower() or "ch340" in (p.description or "").lower() or "usb" in (p.description or "").lower()
                })
        except Exception as err:
            print(f"[COM Ports scan error]: {err}")
        return ports_list

    def _rebuild_robot_topics(self):
        """Keep control/status/ack topics derived from the active base topic + device ID."""
        self.mqtt_topic_action = f"{self.mqtt_base_topic}/{self.mqtt_device_id}/control"
        self.mqtt_topic_cmd = self.mqtt_topic_action
        self.mqtt_topic_status = f"{self.mqtt_base_topic}/{self.mqtt_device_id}/status"
        self.mqtt_topic_ack = f"{self.mqtt_base_topic}/{self.mqtt_device_id}/ack"

    def update_config(self, config: Dict[str, Any]):
        old_mode = self.mode
        old_port = self.serial_port_path
        old_baud = self.baud_rate
        old_mqtt_broker = self.mqtt_broker
        old_mqtt_port = self.mqtt_port
        old_mqtt_user = self.mqtt_user
        old_mqtt_password = self.mqtt_password
        old_mqtt_topic_cmd = self.mqtt_topic_cmd
        old_mqtt_topic_status = self.mqtt_topic_status
        old_mqtt_topic_ack = self.mqtt_topic_ack
        old_mqtt_base_topic = self.mqtt_base_topic
        old_mqtt_device_id = self.mqtt_device_id

        if "mode" in config:
            self.mode = str(config["mode"]).strip()
        if "esp32Ip" in config:
            self.esp32_ip = str(config["esp32Ip"]).strip()
        elif "esp32_ip" in config:
            self.esp32_ip = str(config["esp32_ip"]).strip()

        if "esp32Port" in config:
            self.esp32_port = int(config["esp32Port"])
        elif "esp32_port" in config:
            self.esp32_port = int(config["esp32_port"])

        if "serialPortPath" in config:
            self.serial_port_path = str(config["serialPortPath"]).strip()
        elif "serial_port_path" in config:
            self.serial_port_path = str(config["serial_port_path"]).strip()

        if "baudRate" in config:
            self.baud_rate = int(config["baudRate"])
        elif "baud_rate" in config:
            self.baud_rate = int(config["baud_rate"])

        # MQTT Config Properties
        if "mqttBroker" in config:
            self.mqtt_broker = str(config["mqttBroker"]).strip()
        elif "mqtt_broker" in config:
            self.mqtt_broker = str(config["mqtt_broker"]).strip()

        if "mqttPort" in config:
            self.mqtt_port = int(config["mqttPort"])
        elif "mqtt_port" in config:
            self.mqtt_port = int(config["mqtt_port"])

        if "mqttUser" in config:
            self.mqtt_user = str(config["mqttUser"]).strip()
        elif "mqtt_user" in config:
            self.mqtt_user = str(config["mqtt_user"]).strip()

        if "mqttPassword" in config:
            self.mqtt_password = str(config["mqttPassword"]).strip()
        elif "mqtt_password" in config:
            self.mqtt_password = str(config["mqtt_password"]).strip()

        if "mqttBaseTopic" in config:
            self.mqtt_base_topic = str(config["mqttBaseTopic"]).strip()
        elif "mqtt_base_topic" in config:
            self.mqtt_base_topic = str(config["mqtt_base_topic"]).strip()

        if "mqttDeviceId" in config:
            self.mqtt_device_id = str(config["mqttDeviceId"]).strip()
        elif "mqtt_device_id" in config:
            self.mqtt_device_id = str(config["mqtt_device_id"]).strip()

        # Individual Robot Car topics are intentionally NOT configurable.
        # This prevents stale /action values from overriding the firmware contract.
        self._set_robot_car_topics()

        if "mqttClientId" in config:
            self.mqtt_client_id = str(config["mqttClientId"]).strip()
        elif "mqtt_client_id" in config:
            self.mqtt_client_id = str(config["mqtt_client_id"]).strip()

        # Re-derive after every config update so topic fields can never drift.
        self._set_robot_car_topics()

        # Auto-reconnect if serial settings changed while in serial mode
        if self.mode == "serial":
            if old_mode != "serial" or old_port != self.serial_port_path or old_baud != self.baud_rate or not self.is_connected:
                self.init_serial()
        elif old_mode == "serial" and self.mode != "serial":
            self.disconnect_serial()

        # MQTT is lifecycle-managed here. A transient disconnected state must
        # NEVER cause update_config() to create a new Paho client.
        # Only actual MQTT configuration changes trigger an intentional rebuild.
        if self.mode == "mqtt":
            mqtt_changed = (
                old_mode != "mqtt"
                or old_mqtt_broker != self.mqtt_broker
                or old_mqtt_port != self.mqtt_port
                or old_mqtt_user != self.mqtt_user
                or old_mqtt_password != self.mqtt_password
                or old_mqtt_topic_cmd != self.mqtt_topic_action
                or old_mqtt_topic_status != self.mqtt_topic_status
                or old_mqtt_topic_ack != self.mqtt_topic_ack
                or old_mqtt_base_topic != self.mqtt_base_topic
                or old_mqtt_device_id != self.mqtt_device_id
            )
            if mqtt_changed:
                self.init_mqtt(force=True)
        elif old_mode == "mqtt" and self.mode != "mqtt":
            self.disconnect_mqtt()

        self.emit("config_updated", self.get_config())
        self.emit("status_change", self.get_config())

    def get_config(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "esp32Ip": self.esp32_ip,
            "esp32Port": self.esp32_port,
            "serialPortPath": self.serial_port_path,
            "baudRate": self.baud_rate,
            "mqttBroker": self.mqtt_broker,
            "mqttPort": self.mqtt_port,
            "mqttUser": self.mqtt_user,
            "mqttBaseTopic": self.mqtt_base_topic,
            "mqttDeviceId": self.mqtt_device_id,
            "mqttTopicAction": self.mqtt_topic_action,
            "mqttTopicCmd": self.mqtt_topic_action,
            "mqttTopicStatus": self.mqtt_topic_status,
            "mqttTopicAck": self.mqtt_topic_ack,
            "mqttClientId": self.mqtt_client_id,
            "mqttConnected": self.mqtt_connected,
            "robotCarOnline": self.robot_car_online,
            "mqttLastSeen": self.mqtt_last_seen,
            "isConnected": self.is_connected,
            "lastLatency": self.last_latency,
            "lastError": self.last_error,
            "pendingAckCount": len(self._pending_acks),
            "availablePorts": self.get_available_ports(),
        }

    # -------------------------------------------------------------------------
    # WebSocket Direct Client Handling
    # -------------------------------------------------------------------------
    def register_websocket_client(self, ws):
        self.active_ws_client = ws
        self.is_connected = True
        self.last_error = None
        self.mode = "wifi_ws"
        self.emit("log", {"level": "success", "message": "ESP32 connected directly via WebSocket!"})
        self.emit("status_change", self.get_config())

    def unregister_websocket_client(self):
        self.active_ws_client = None
        self.is_connected = False
        self.emit("log", {"level": "warn", "message": "ESP32 WebSocket connection closed."})
        self.emit("status_change", self.get_config())

    def handle_ws_message(self, text: str):
        try:
            data = json.loads(text)
            if data.get("type") == "status_sync" and "states" in data:
                self.device_states.update(data["states"])
                self.emit("states_sync", self.device_states)
            elif "states" in data:
                self.device_states.update(data["states"])
                self.emit("states_sync", self.device_states)
        except Exception:
            self.emit("log", {"level": "info", "message": f"ESP32 WS: {text}"})

    # -------------------------------------------------------------------------
    # MQTT Client (paho-mqtt)
    # -------------------------------------------------------------------------
    def init_mqtt(self, force: bool = False) -> bool:
        """Start exactly one Paho MQTT client.

        Normal calls are idempotent. A new client is created only for an
        explicit/intentional reconnect or an MQTT configuration change.
        Paho owns automatic reconnects after an unexpected broker disconnect.
        """
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            self.last_error = "paho-mqtt not installed"
            self.emit("log", {
                "level": "warn",
                "message": "paho-mqtt not installed. Run `pip install paho-mqtt` for MQTT mode.",
            })
            return False

        # Already connected: never replace the live client.
        if not force and self.mqtt_client is not None and self.mqtt_connected:
            return True

        # A client already exists and is handling an automatic reconnect.
        # Do not create a second client while that one is alive.
        if not force and self.mqtt_client is not None and self._mqtt_connecting:
            return True

        try:
            self._mqtt_manual_disconnect = False

            if force and self.mqtt_client is not None:
                self.disconnect_mqtt(emit_status=False)

            self._mqtt_connecting = True

            try:
                self.mqtt_client = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION2,
                    client_id=self.mqtt_client_id or None,
                )
            except (AttributeError, TypeError):
                self.mqtt_client = mqtt.Client(client_id=self.mqtt_client_id or None)

            if self.mqtt_user:
                self.mqtt_client.username_pw_set(
                    self.mqtt_user, self.mqtt_password or None
                )

            self.mqtt_client.on_connect = self._on_mqtt_connect
            self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
            self.mqtt_client.on_message = self._on_mqtt_message

            try:
                self.mqtt_client.reconnect_delay_set(min_delay=1, max_delay=10)
            except Exception:
                pass

            self.emit("log", {
                "level": "info",
                "message": (
                    f"Connecting to MQTT Broker {self.mqtt_broker}:{self.mqtt_port} "
                    f"(Client: {self.mqtt_client_id})..."
                ),
            })

            self.mqtt_client.connect_async(
                self.mqtt_broker, self.mqtt_port, keepalive=60
            )
            self.mqtt_client.loop_start()
            return True

        except Exception as err:
            self._mqtt_connecting = False
            self.mqtt_connected = False
            if self.mode == "mqtt":
                self.is_connected = False
            self.last_error = f"MQTT connect failed: {err}"
            self.emit("log", {
                "level": "error",
                "message": (
                    f"Failed to initialize MQTT broker connection "
                    f"({self.mqtt_broker}:{self.mqtt_port}): {err}"
                ),
            })
            self.emit("status_change", self.get_config())
            return False

    def disconnect_mqtt(self, emit_status: bool = True):
        """Intentionally disconnect MQTT and stop automatic reconnects."""
        self._mqtt_manual_disconnect = True
        self._mqtt_connecting = False

        client = self.mqtt_client
        self.mqtt_client = None
        self.mqtt_connected = False

        if client:
            try:
                client.loop_stop()
            except Exception:
                pass
            try:
                client.disconnect()
            except Exception:
                pass

        if self.mode == "mqtt":
            self.is_connected = False

        if emit_status:
            self.emit("status_change", self.get_config())

    def _on_mqtt_connect(self, client, userdata, flags, rc_or_reason, *args, **kwargs):
        is_failure = getattr(rc_or_reason, "is_failure", False) if hasattr(rc_or_reason, "is_failure") else (rc_or_reason != 0)
        if not is_failure:
            self._mqtt_connecting = False
            self.mqtt_connected = True
            self.robot_car_online = self.robot_car_online
            if self.mode == "mqtt":
                self.is_connected = True
                self.last_error = None
            self.emit("log", {
                "level": "success",
                "message": f"Connected to MQTT Broker [{self.mqtt_broker}:{self.mqtt_port}]. Subscribed to topics.",
            })
            try:
                # Subscribe ONLY to ESP32-originated topics. Never subscribe to
                # /control because that is the Master Hub TX topic and would make
                # the broker echo our own command back into the dashboard.
                client.subscribe([
                    (self.mqtt_topic_ack, 1),
                    (self.mqtt_topic_status, 1),
                    (f"{self.mqtt_base_topic}/{self.mqtt_device_id}/availability", 0),
                    (f"{self.mqtt_base_topic}/{self.mqtt_device_id}/pong", 0),
                ])
            except Exception as sub_err:
                self.emit("log", {"level": "warn", "message": f"MQTT subscribe notice: {sub_err}"})
            self.emit("status_change", self.get_config())
        else:
            self._mqtt_connecting = False
            self.mqtt_connected = False
            if self.mode == "mqtt":
                self.is_connected = False
            self.last_error = f"MQTT connection rejected by broker: {rc_or_reason}"
            self.emit("log", {"level": "error", "message": self.last_error})
            self.emit("status_change", self.get_config())

    def _on_mqtt_disconnect(self, client, userdata, *args, **kwargs):
        self.mqtt_connected = False
        self._mqtt_connecting = False
        if self.mode == "mqtt":
            self.is_connected = False

        if not self._mqtt_manual_disconnect:
            reason = args[0] if args else kwargs.get("reason_code", "unknown")
            self.last_error = f"MQTT disconnected (reason: {reason})"
            self.emit("log", {
                "level": "warn",
                "message": f"{self.last_error}. Paho will retry automatically.",
            })

        self.emit("status_change", self.get_config())

    async def _watch_ack(self, pending):
        """Wait briefly for the ESP32's application-level ACK and report a timeout."""
        event = pending.get("event")
        if not event:
            return
        try:
            await asyncio.wait_for(event.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            removed = False
            with self._ack_lock:
                if pending in self._pending_acks:
                    self._pending_acks.remove(pending)
                    removed = True
            if removed:
                self.emit("esp32_ack_timeout", {
                    "command": pending.get("command"),
                    "topic": self.mqtt_topic_action,
                    "sentAt": int(pending.get("sent_at", time.time()) * 1000),
                    "timeoutMs": 2000,
                })
                self.emit("log", {
                    "level": "error",
                    "message": (
                        f"ACK TIMEOUT [{pending.get('command')}] — broker accepted the publish, "
                        "but no ESP32 ACK arrived on the configured ACK topic. "
                        "The control-topic loopback does not prove ESP32 reception."
                    ),
                })

    def _on_mqtt_message(self, client, userdata, msg):
        try:
            raw = msg.payload.decode("utf-8", errors="replace").strip()
            topic = msg.topic
            self.mqtt_last_seen = time.time()

            # A command topic is included in the wildcard subscription only so the
            # Master Hub can prove that its own MQTT client loop is alive. This is NOT
            # proof that the ESP32 received the command. Label it explicitly.
            if topic == self.mqtt_topic_action:
                self.emit("log", {
                    "level": "info",
                    "message": f"MQTT LOOPBACK [MASTER TX ECHO] [{topic}] {raw} — ESP32 RX not proven",
                })
                self.emit("mqtt_loopback", {"topic": topic, "payload": raw})
                self.emit("status_change", self.get_config())
                return

            if topic == self.mqtt_topic_ack:
                ack_received_at = time.time()
                pending = None
                with self._ack_lock:
                    if self._pending_acks:
                        pending = self._pending_acks.pop(0)
                latency = None
                if pending:
                    latency = int((ack_received_at - pending["sent_at"]) * 1000)
                    pending["ack"] = raw
                    pending["ack_received"] = True
                    event = pending.get("event")
                    if event and self._async_loop and self._async_loop.is_running():
                        self._async_loop.call_soon_threadsafe(event.set)
                self.emit("esp32_ack", {
                    "topic": topic, "ack": raw, "latency": latency,
                    "command": pending.get("command") if pending else None,
                    "receivedAt": int(ack_received_at * 1000),
                })
                self.emit("log", {
                    "level": "success",
                    "message": f"ESP32 ACK RX [{topic}] {raw}" + (f" • {latency} ms" if latency is not None else ""),
                })
                self.emit("status_change", self.get_config())
                return

            # Robot Car LWT/status is DEVICE state, not broker state.
            if topic == self.mqtt_topic_status:
                self.robot_car_online = raw.lower() in (
                    "online", "ready", "connected", "1", "true"
                )
                self.emit("log", {
                    "level": "info" if self.robot_car_online else "warn",
                    "message": f"ESP32 MQTT: [{topic}] {raw}",
                })
                self.emit("status_change", self.get_config())
                return

            if topic.endswith("/availability") or topic.endswith("/lwt"):
                self.robot_car_online = raw.lower() in (
                    "online", "ready", "connected", "1", "true"
                )
                self.emit("log", {
                    "level": "info" if self.robot_car_online else "warn",
                    "message": f"ESP32 Node status via MQTT: {raw.upper()}",
                })
                self.emit("status_change", self.get_config())
                return

            if topic.endswith("/pong") or raw == "PONG":
                self.emit("log", {
                    "level": "info",
                    "message": f"ESP32 MQTT Ping reply from {topic}",
                })
                self.emit("status_change", self.get_config())
                return

            # JSON payload state sync retained for reference/other ESP32 nodes.
            parsed_json = None
            if raw.startswith("{") and raw.endswith("}"):
                try:
                    parsed_json = json.loads(raw)
                except Exception:
                    pass

            if parsed_json:
                if "states" in parsed_json:
                    self.device_states.update(parsed_json["states"])
                    self.emit("states_sync", self.device_states)
                elif "device" in parsed_json and "state" in parsed_json:
                    dev = str(parsed_json["device"]).lower()
                    st = str(parsed_json["state"]).upper()
                    self.device_states[dev] = st
                    self.emit("states_sync", self.device_states)
                else:
                    for k in ("light", "fan", "pump"):
                        if k in parsed_json:
                            self.device_states[k] = str(parsed_json[k]).upper()
                    self.emit("states_sync", self.device_states)
                self.emit("log", {
                    "level": "info",
                    "message": f"ESP32 MQTT State Sync: {raw}",
                })
            else:
                self.emit("log", {
                    "level": "info",
                    "message": f"ESP32 MQTT: [{topic}] {raw}",
                })

            self.emit("status_change", self.get_config())

        except Exception as e:
            self.emit("log", {
                "level": "error",
                "message": f"Error handling MQTT message: {e}",
            })

    # -------------------------------------------------------------------------
    # Serial UART (PySerial)
    # -------------------------------------------------------------------------
    def init_serial(self) -> bool:
        try:
            import serial
        except ImportError:
            self.last_error = "pyserial not installed"
            self.emit("log", {
                "level": "warn",
                "message": "pyserial not installed. Run `pip install pyserial` for USB COM port mode.",
            })
            return False

        try:
            self.disconnect_serial()
            time.sleep(0.15)  # Allow Windows kernel to release COM port handle

            self.serial_conn = serial.Serial(self.serial_port_path, self.baud_rate, timeout=1)
            self.is_connected = True
            self._stop_serial = False
            self.last_error = None
            self.emit("log", {
                "level": "success",
                "message": f"Opened ESP32 Serial Port {self.serial_port_path} @ {self.baud_rate} baud",
            })
            self.emit("status_change", self.get_config())

            self._serial_thread = threading.Thread(target=self._serial_reader_loop, daemon=True)
            self._serial_thread.start()

            # Request initial status
            try:
                self.serial_conn.write(b"STATUS\n")
            except Exception:
                pass

            return True
        except PermissionError:
            self.is_connected = False
            self.last_error = f"Port {self.serial_port_path} is busy (Access Denied). Close Arduino Serial Monitor / PuTTY."
            self.emit("log", {
                "level": "error",
                "message": f"Serial port {self.serial_port_path} is locked by another app (e.g. Arduino Serial Monitor). Please close it and click Connect.",
            })
            self.emit("status_change", self.get_config())
            return False
        except Exception as err:
            self.is_connected = False
            self.last_error = str(err)
            self.emit("log", {"level": "error", "message": f"Failed to open Serial Port {self.serial_port_path}: {err}"})
            self.emit("status_change", self.get_config())
            return False

    def disconnect_serial(self):
        self._stop_serial = True
        if self.serial_conn:
            try:
                if self.serial_conn.is_open:
                    self.serial_conn.close()
            except Exception:
                pass
            self.serial_conn = None
        self.is_connected = False
        self.emit("status_change", self.get_config())

    def _serial_reader_loop(self):
        while not self._stop_serial and self.serial_conn and self.serial_conn.is_open:
            try:
                line = self.serial_conn.readline().decode("utf-8", errors="replace").strip()
                if line:
                    self.emit("log", {"level": "info", "message": f"[ESP32 Serial] {line}"})
                    # Parse JSON ACK or status
                    if line.startswith("{") and line.endswith("}"):
                        try:
                            json_data = json.loads(line)
                            if "states" in json_data:
                                self.device_states.update(json_data["states"])
                                self.emit("states_sync", self.device_states)
                        except Exception:
                            pass
            except Exception:
                break
        self.is_connected = False
        self.emit("status_change", self.get_config())

    # -------------------------------------------------------------------------
    # Command Dispatch
    # -------------------------------------------------------------------------
    async def send_command(self, device: str, state: str) -> Dict[str, Any]:
        device = (device or "").lower().strip()
        state = (state or "").upper().strip()
        self.device_states[device] = state

        command_payload = {
            "device": device,
            "state": state,
            "timestamp": int(time.time() * 1000),
        }

        self.emit("log", {
            "level": "info",
            "message": f"Dispatching to ESP32: [{device.upper()} -> {state}] via Mode: {self.mode.upper()}",
        })

        # 1. Direct WebSocket client
        if self.active_ws_client:
            try:
                await self.active_ws_client.send_text(json.dumps({"type": "control", **command_payload}))
                return {"success": True, "mode": "websocket"}
            except Exception as err:
                self.emit("log", {"level": "error", "message": f"WS Dispatch error: {err}"})

        # 2. Serial Mode
        if self.mode == "serial":
            if not self.serial_conn or not self.serial_conn.is_open:
                # Attempt auto-connect
                self.init_serial()

            if self.serial_conn and self.serial_conn.is_open:
                try:
                    cmd = f"{device.upper()}:{state}\n"
                    self.serial_conn.write(cmd.encode("utf-8"))
                    return {"success": True, "mode": "serial", "command": cmd.strip()}
                except Exception as err:
                    self.emit("log", {"level": "error", "message": f"Serial write error: {err}"})
                    return {"success": False, "error": str(err)}
            else:
                return {"success": False, "error": self.last_error or "Serial port not connected"}

        # 3. WiFi HTTP REST Mode
        if self.mode in ("wifi", "http"):
            return await self._send_http_request(device, state)

        # 4. MQTT Mode
        if self.mode == "mqtt":
            if not self.mqtt_client or not self.mqtt_connected:
                self.init_mqtt()

            if self.mqtt_client and self.mqtt_connected:
                try:
                    payload_str = json.dumps(command_payload)
                    # Generic transport fallback uses the same canonical /control
                    # topic schema as the Robot Car path.
                    self.mqtt_client.publish(self.mqtt_topic_action, payload_str, qos=1)
                    self.mqtt_client.publish(f"{self.mqtt_topic_action}/raw", f"{device.upper()}:{state}", qos=1)
                    return {
                        "success": True,
                        "mode": "mqtt",
                        "topic": self.mqtt_topic_action,
                        "command": f"{device.upper()}:{state}",
                    }
                except Exception as err:
                    self.emit("log", {"level": "error", "message": f"MQTT publish error: {err}"})
                    return {"success": False, "error": str(err)}
            else:
                return {"success": False, "error": self.last_error or "MQTT Broker not connected"}

        # Virtual / Simulation Fallback
        return {"success": True, "mode": "virtual"}

    async def _send_http_request(self, device: str, state: str) -> Dict[str, Any]:
        url = f"http://{self.esp32_ip}:{self.esp32_port}/api/control?device={device}&state={state}"
        start_time = time.time()
        loop = asyncio.get_running_loop()

        def _do_get():
            try:
                return requests.get(url, timeout=2.5)
            except Exception as e:
                return e

        res = await loop.run_in_executor(None, _do_get)
        latency_ms = int((time.time() - start_time) * 1000)

        if isinstance(res, requests.Response):
            self.last_latency = latency_ms
            self.is_connected = True
            self.last_error = None
            self.emit("log", {
                "level": "success",
                "message": f"ESP32 HTTP Response ({latency_ms}ms): {res.text.strip() or res.status_code}",
            })
            self.emit("status_change", self.get_config())
            return {"success": True, "latency": latency_ms, "response": res.text}
        else:
            self.last_latency = None
            self.is_connected = False
            self.last_error = str(res)
            err_msg = f"ESP32 HTTP Request failed ({self.esp32_ip}:{self.esp32_port}): {res}"
            if "ConnectTimeout" in str(res) or "Max retries exceeded" in str(res):
                err_msg += f". (Hint: Verify ESP32 IP in Arduino Serial Monitor, ensure PC & ESP32 are on same 2.4GHz WiFi, or switch to 'USB Serial' mode.)"
            self.emit("log", {
                "level": "warn",
                "message": err_msg,
            })
            self.emit("status_change", self.get_config())
            return {"success": False, "error": str(res)}

    async def ping(self) -> Dict[str, Any]:
        """Pings the ESP32 hardware according to the current active communication mode."""
        start_time = time.time()

        # Serial Mode Ping
        if self.mode == "serial":
            if not self.serial_conn or not self.serial_conn.is_open:
                if not self.init_serial():
                    return {"success": False, "error": self.last_error or "Serial port not connected"}

            try:
                self.serial_conn.write(b"STATUS\n")
                latency_ms = int((time.time() - start_time) * 1000)
                self.is_connected = True
                self.last_latency = latency_ms
                self.last_error = None
                self.emit("log", {"level": "success", "message": f"ESP32 Serial Ping OK ({self.serial_port_path} @ {self.baud_rate})"})
                self.emit("status_change", self.get_config())
                return {"success": True, "mode": "serial", "latency": latency_ms, "port": self.serial_port_path}
            except Exception as e:
                self.is_connected = False
                self.last_error = str(e)
                self.emit("status_change", self.get_config())
                return {"success": False, "error": str(e)}

        # WebSocket Mode Ping
        if self.mode == "wifi_ws":
            if self.active_ws_client:
                try:
                    await self.active_ws_client.send_text(json.dumps({"type": "ping"}))
                    return {"success": True, "mode": "websocket", "connected": True}
                except Exception as e:
                    return {"success": False, "error": str(e)}
            return {"success": False, "error": "No ESP32 WebSocket client connected"}

        # MQTT Mode Ping
        if self.mode == "mqtt":
            if not self.mqtt_client or not self.mqtt_connected:
                if not self.init_mqtt():
                    return {"success": False, "error": self.last_error or "MQTT Broker not connected"}
                await asyncio.sleep(0.3)

            try:
                ping_payload = json.dumps({"type": "ping", "timestamp": int(time.time() * 1000)})
                self.mqtt_client.publish("iot/esp32/ping", ping_payload, qos=0)
                latency_ms = int((time.time() - start_time) * 1000)
                self.last_latency = latency_ms
                self.is_connected = self.mqtt_connected
                self.emit("log", {
                    "level": "success",
                    "message": f"MQTT Broker Link OK ({self.mqtt_broker}:{self.mqtt_port})",
                })
                self.emit("status_change", self.get_config())
                return {
                    "success": True,
                    "mode": "mqtt",
                    "broker": self.mqtt_broker,
                    "port": self.mqtt_port,
                    "topic": self.mqtt_topic_cmd,
                    "connected": self.mqtt_connected,
                    "lastSeen": self.mqtt_last_seen,
                }
            except Exception as e:
                self.is_connected = False
                self.last_error = str(e)
                self.emit("status_change", self.get_config())
                return {"success": False, "error": str(e)}

        # HTTP REST Ping
        url = f"http://{self.esp32_ip}:{self.esp32_port}/api/status"
        loop = asyncio.get_running_loop()

        def _do_ping():
            try:
                return requests.get(url, timeout=2.0)
            except Exception as e:
                return e

        res = await loop.run_in_executor(None, _do_ping)
        latency_ms = int((time.time() - start_time) * 1000)

        if isinstance(res, requests.Response):
            self.is_connected = True
            self.last_latency = latency_ms
            self.last_error = None
            self.emit("log", {"level": "success", "message": f"ESP32 HTTP Ping OK ({latency_ms}ms)"})
            self.emit("status_change", self.get_config())
            return {"success": True, "latency": latency_ms, "body": res.text}
        else:
            self.is_connected = False
            self.last_latency = None
            self.last_error = str(res)
            err_msg = f"ESP32 HTTP Ping Failed: {res}"
            if "ConnectTimeout" in str(res) or "Max retries exceeded" in str(res):
                err_msg += f" -> Hint: Check if ESP32 IP changed in Serial Monitor, verify WiFi 2.4GHz network, or use USB Serial mode."
            self.emit("log", {"level": "warn", "message": err_msg})
            self.emit("status_change", self.get_config())
            return {"success": False, "error": str(res)}
