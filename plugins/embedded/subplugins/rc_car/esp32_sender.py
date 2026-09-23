"""
ESP32 Network Sender (MQTT, TCP Sockets, WebSockets & HTTP)
============================================================
Handles low-latency wireless command dispatch to ESP32 RC Car over MQTT topics,
TCP Sockets (Port 5000), WebSockets (Port 81), or HTTP POST with latency timing,
ACK/status subscription, and execution verification.
"""

import json
import logging
import socket
import threading
import time
from typing import Dict, Any, Tuple, Optional, Callable

import requests

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

try:
    from websockets.sync.client import connect as ws_sync_connect
except ImportError:
    ws_sync_connect = None

try:
    import websocket as ws_client_lib
except ImportError:
    ws_client_lib = None

from . import config

logger = logging.getLogger("ESP32Sender")


class ESP32Sender:
    """
    Manages communication bridge with ESP32 microcontroller over MQTT, WebSockets, TCP Sockets, or HTTP.
    """

    def __init__(self,
                 esp32_ip: str = config.ESP32_IP,
                 esp32_port: int = config.ESP32_PORT,
                 protocol: str = config.COMMUNICATION_PROTOCOL):

        self.esp32_ip = esp32_ip
        self.esp32_port = esp32_port
        self.esp32_ws_port = getattr(config, 'ESP32_WS_PORT', 81)
        self.endpoint_url = f"http://{self.esp32_ip}:{config.ESP32_HTTP_PORT}/api/command" if hasattr(config, 'ESP32_HTTP_PORT') else f"http://{self.esp32_ip}/api/command"
        self.protocol = protocol.upper()
        self.current_speed_mode = config.DEFAULT_SPEED_MODE

        self.socket_client: Optional[socket.socket] = None
        self.ws_client = None

        # MQTT Communication State
        self.mqtt_client = None
        self._mqtt_connected = False
        self.mqtt_broker_host = getattr(config, 'MQTT_BROKER_HOST', '52.21.249.6')
        self.mqtt_broker_port = int(getattr(config, 'MQTT_BROKER_PORT', 1883))
        self.mqtt_control_topic = getattr(config, 'MQTT_CONTROL_TOPIC', 'robotcar/98:A3:16:BF:2C:C0/control')
        self.mqtt_status_topic = getattr(config, 'MQTT_STATUS_TOPIC', 'robotcar/98:A3:16:BF:2C:C0/status')
        self.mqtt_ack_topic = getattr(config, 'MQTT_ACK_TOPIC', 'robotcar/98:A3:16:BF:2C:C0/ack')

        # Telemetry & Status Cache
        self.last_ack: Optional[str] = None
        self.last_ack_time: float = 0.0
        self.last_device_status: Optional[str] = None
        self.last_status_time: float = 0.0
        self.last_payload_sent: Optional[str] = None

        # ACK Synchronization
        self._ack_event = threading.Event()
        self._last_received_ack: Optional[str] = None

        # Callbacks
        self.on_ack_received: Optional[Callable[[str], None]] = None
        self.on_status_received: Optional[Callable[[str], None]] = None

        # Initialize MQTT immediately if configured as protocol
        if self.protocol == "MQTT":
            self._init_mqtt()

        logger.info(f"ESP32Sender initialized (Protocol: {self.protocol}, Broker: {self.mqtt_broker_host}:{self.mqtt_broker_port})")

    def _init_mqtt(self) -> bool:
        """
        Establishes connection to MQTT broker and subscribes to ACK and status topics.
        """
        if mqtt is None:
            logger.error("Paho-MQTT library not installed! Cannot initialize MQTT.")
            self._mqtt_connected = False
            return False

        if self.mqtt_client and self._mqtt_connected:
            return True

        try:
            client_id = f"SynaptiMesh_BCI_{int(time.time() * 1000) % 1000000}"
            if hasattr(mqtt, "CallbackAPIVersion"):
                self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
            else:
                self.mqtt_client = mqtt.Client(client_id=client_id)

            if getattr(config, 'MQTT_USER', None) and getattr(config, 'MQTT_PASSWORD', None):
                self.mqtt_client.username_pw_set(config.MQTT_USER, config.MQTT_PASSWORD)

            def on_connect(client, userdata, flags, rc, properties=None):
                is_success = (rc == 0) or (hasattr(rc, "is_failure") and not rc.is_failure)
                if is_success:
                    self._mqtt_connected = True
                    logger.info(f"Connected to MQTT Broker ({self.mqtt_broker_host}:{self.mqtt_broker_port}) successfully.")
                    client.subscribe(self.mqtt_ack_topic)
                    client.subscribe(self.mqtt_status_topic)
                    logger.info(f"Subscribed to topics: {self.mqtt_ack_topic}, {self.mqtt_status_topic}")
                else:
                    self._mqtt_connected = False
                    logger.error(f"MQTT Connection failed with code: {rc}")

            def on_disconnect(client, userdata, *args):
                self._mqtt_connected = False
                logger.warning("Disconnected from MQTT Broker.")

            def on_message(client, userdata, msg):
                try:
                    payload_str = msg.payload.decode('utf-8', errors='ignore').strip()
                    topic = msg.topic
                    logger.info(f"MQTT message received on [{topic}]: '{payload_str}'")

                    if topic == self.mqtt_ack_topic:
                        self.last_ack = payload_str
                        self.last_ack_time = time.time()
                        self._last_received_ack = payload_str
                        self._ack_event.set()
                        logger.info(f"Execution ACK captured: '{payload_str}'")
                        if self.on_ack_received:
                            try:
                                self.on_ack_received(payload_str)
                            except Exception as e:
                                logger.error(f"Error in on_ack_received callback: {e}")

                    elif topic == self.mqtt_status_topic:
                        self.last_device_status = payload_str
                        self.last_status_time = time.time()
                        logger.info(f"Device Status captured: '{payload_str}'")
                        if self.on_status_received:
                            try:
                                self.on_status_received(payload_str)
                            except Exception as e:
                                logger.error(f"Error in on_status_received callback: {e}")
                except Exception as e:
                    logger.error(f"Error processing MQTT message: {e}")

            self.mqtt_client.on_connect = on_connect
            self.mqtt_client.on_disconnect = on_disconnect
            self.mqtt_client.on_message = on_message

            self.mqtt_client.connect(self.mqtt_broker_host, self.mqtt_broker_port, keepalive=60)
            self.mqtt_client.loop_start()

            # Wait briefly for connection handshake
            start_wait = time.time()
            while not self._mqtt_connected and (time.time() - start_wait) < 2.0:
                time.sleep(0.05)

            return self._mqtt_connected
        except Exception as e:
            logger.error(f"Failed to setup MQTT Client: {e}")
            self._mqtt_connected = False
            return False

    def is_connected(self) -> bool:
        """
        Returns connection state for the active protocol.
        For MQTT, requires active broker connection AND positive device online status
        (explicitly rejecting 'OFFLINE' messages).
        """
        if self.protocol == "MQTT":
            if not self._mqtt_connected:
                return False
            status = getattr(self, "last_device_status", None)
            if status:
                status_str = str(status).strip().upper()
                if "OFFLINE" in status_str:
                    return False
                if "ONLINE" in status_str:
                    return True
            # Check if recent ACK was received within 15 seconds
            if getattr(self, "last_ack_time", 0) and (time.time() - self.last_ack_time < 15.0):
                return True
            return False
        elif self.protocol == "WEBSOCKET":
            return self.ws_client is not None
        elif self.protocol == "TCP_SOCKET":
            return self.socket_client is not None
        elif self.protocol == "HTTP":
            return True
        return False

    def send_payload_mqtt(self, payload: str, wait_ack_timeout: float = None) -> Tuple[bool, float, str]:
        """
        Publishes raw string payload to MQTT control topic.
        Does NOT treat publish success as execution success.
        Waits for ACK from the ESP32 on the ACK topic to confirm execution.
        """
        if wait_ack_timeout is None:
            wait_ack_timeout = getattr(config, 'NETWORK_TIMEOUT_SECONDS', 2.0)

        if not self._mqtt_connected or not self.mqtt_client:
            if not self._init_mqtt():
                logger.error(f"Cannot send MQTT command: Not connected to broker at {self.mqtt_broker_host}:{self.mqtt_broker_port}")
                return False, 0.0, "Device unavailable - MQTT broker unreachable / disconnected"

        self._ack_event.clear()
        self._last_received_ack = None
        self.last_payload_sent = payload
        start_time = time.perf_counter()

        logger.info(f"Publishing MQTT payload '{payload}' to topic '{self.mqtt_control_topic}'")
        try:
            msg_info = self.mqtt_client.publish(self.mqtt_control_topic, payload, qos=0)
            msg_info.wait_for_publish(timeout=1.0)
            if msg_info.rc != mqtt.MQTT_ERR_SUCCESS and not msg_info.is_published():
                latency_ms = (time.perf_counter() - start_time) * 1000.0
                err_msg = f"MQTT Publish failed with return code {msg_info.rc}"
                logger.error(err_msg)
                return False, latency_ms, err_msg
        except (socket.error, OSError, Exception) as pub_err:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            self._mqtt_connected = False
            err_msg = f"Device communication error during publish: {pub_err}"
            logger.error(err_msg)
            return False, latency_ms, err_msg

        # Wait for actual ACK from the ESP32
        ack_received = self._ack_event.wait(timeout=wait_ack_timeout)
        latency_ms = (time.perf_counter() - start_time) * 1000.0

        if ack_received:
            ack_text = self._last_received_ack or self.last_ack
            if not ack_text or not str(ack_text).strip():
                err_msg = "Invalid response: empty ACK received from ESP32"
                logger.warning(err_msg)
                return False, latency_ms, err_msg

            ack_str = str(ack_text).strip()
            # Check for error strings or error JSON
            if ack_str.upper().startswith(("ERR", "ERROR", "FAIL")):
                err_msg = f"Device error response: {ack_str}"
                logger.warning(err_msg)
                return False, latency_ms, err_msg

            try:
                ack_json = json.loads(ack_str)
                if isinstance(ack_json, dict):
                    status = str(ack_json.get("status", "")).lower()
                    if status in ("error", "failed", "false") or "error" in ack_json:
                        err_msg = ack_json.get("message") or ack_json.get("error") or f"Device error status: {status}"
                        logger.warning(f"ESP32 reported execution failure: {err_msg}")
                        return False, latency_ms, err_msg
            except (json.JSONDecodeError, ValueError):
                pass  # Plain text ACK like LIFTCARFORWARD_ACK

            logger.info(f"ESP32 Execution Confirmed in {latency_ms:.2f}ms: '{ack_str}'")
            return True, latency_ms, ack_str
        else:
            warning_msg = f"Communication timeout: Published '{payload}' to {self.mqtt_control_topic}, but no ACK received within {wait_ack_timeout}s"
            logger.warning(warning_msg)
            return False, latency_ms, warning_msg

    def _connect_websocket(self) -> bool:
        """
        Establishes or reconnects WebSocket client connection to ESP32 (Port 81).
        """
        if self.ws_client:
            try:
                self.ws_client.close()
            except Exception:
                pass
            self.ws_client = None

        ws_url = f"ws://{self.esp32_ip}:{self.esp32_ws_port}"

        if ws_sync_connect is not None:
            try:
                self.ws_client = ws_sync_connect(ws_url, open_timeout=config.NETWORK_TIMEOUT_SECONDS)
                logger.info(f"Connected WebSocket client (via websockets.sync) to ESP32 at {ws_url}")
                return True
            except Exception as e:
                logger.warning(f"WebSocket connection to {ws_url} failed: {e}")
                self.ws_client = None
                return False
        elif ws_client_lib is not None:
            try:
                self.ws_client = ws_client_lib.create_connection(ws_url, timeout=config.NETWORK_TIMEOUT_SECONDS)
                logger.info(f"Connected WebSocket client (via websocket-client) to ESP32 at {ws_url}")
                return True
            except Exception as e:
                logger.warning(f"WebSocket connection to {ws_url} failed: {e}")
                self.ws_client = None
                return False
        else:
            logger.warning("No WebSocket module installed! Falling back to TCP Socket.")
            self.protocol = "TCP_SOCKET"
            return self._connect_socket()

    def send_command_websocket(self, action: str) -> Tuple[bool, float, str]:
        """
        Sends command line over persistent WebSocket (Port 81).
        """
        payload = f"{action.upper()}\n"
        start_time = time.perf_counter()

        for attempt in range(1, config.MAX_NETWORK_RETRIES + 1):
            if not self.ws_client:
                if not self._connect_websocket():
                    time.sleep(0.02)
                    continue

            try:
                self.ws_client.send(payload)
                latency_ms = (time.perf_counter() - start_time) * 1000.0
                logger.debug(f"WebSocket Command '{action}' delivered in {latency_ms:.2f}ms")
                return True, latency_ms, f"WebSocket Delivery OK ({action})"
            except Exception as ws_err:
                logger.warning(f"WebSocket attempt {attempt} failed: {ws_err}. Reconnecting...")
                self._connect_websocket()

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        return False, latency_ms, "WebSocket send failed after retries"

    def _connect_socket(self) -> bool:
        """
        Establishes or reconnects TCP socket connection to ESP32 on port 5000.
        """
        if self.socket_client:
            try:
                self.socket_client.close()
            except Exception:
                pass
            self.socket_client = None

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(config.NETWORK_TIMEOUT_SECONDS)
            sock.connect((self.esp32_ip, self.esp32_port))
            self.socket_client = sock
            logger.info(f"Connected TCP Socket to ESP32 at {self.esp32_ip}:{self.esp32_port}")
            return True
        except Exception as e:
            logger.warning(f"TCP Socket connection to {self.esp32_ip}:{self.esp32_port} failed: {e}")
            self.socket_client = None
            return False

    def send_command_socket(self, action: str) -> Tuple[bool, float, str]:
        """
        Sends command line over persistent TCP Socket (Port 5000).
        """
        payload_bytes = f"{action.upper()}\n".encode('utf-8')
        start_time = time.perf_counter()

        for attempt in range(1, config.MAX_NETWORK_RETRIES + 1):
            if not self.socket_client:
                if not self._connect_socket():
                    time.sleep(0.05)
                    continue

            try:
                self.socket_client.sendall(payload_bytes)
                latency_ms = (time.perf_counter() - start_time) * 1000.0
                logger.debug(f"TCP Socket Command '{action}' delivered in {latency_ms:.2f}ms")
                return True, latency_ms, f"TCP Socket Delivery OK ({action})"
            except (socket.error, socket.timeout, BrokenPipeError, OSError) as sock_err:
                logger.warning(f"TCP Socket attempt {attempt} failed: {sock_err}. Reconnecting...")
                self._connect_socket()

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        return False, latency_ms, "TCP Socket send failed after retries"

    def set_speed_mode(self, speed_mode: str) -> bool:
        if speed_mode.upper() in config.SPEED_MODES:
            self.current_speed_mode = speed_mode.upper()
            logger.info(f"Speed mode set to: {self.current_speed_mode}")
            return True
        return False

    def send_command_http(self, action: str, speed_pwm: int) -> Tuple[bool, float, str]:
        payload = {
            "command": action,
            "speed": speed_pwm,
            "timestamp": time.time()
        }

        start_time = time.perf_counter()
        headers = {"Content-Type": "application/json"}

        for attempt in range(1, config.MAX_NETWORK_RETRIES + 1):
            try:
                resp = requests.post(
                    self.endpoint_url,
                    json=payload,
                    headers=headers,
                    timeout=config.NETWORK_TIMEOUT_SECONDS
                )
                latency_ms = (time.perf_counter() - start_time) * 1000.0

                if resp.status_code == 200:
                    logger.debug(f"HTTP Command '{action}' delivered in {latency_ms:.2f}ms")
                    return True, latency_ms, resp.text
                else:
                    logger.warning(f"HTTP Attempt {attempt}: Status code {resp.status_code}")

            except requests.exceptions.RequestException as req_err:
                logger.warning(f"HTTP Attempt {attempt} failed: {req_err}")
                if attempt < config.MAX_NETWORK_RETRIES:
                    time.sleep(0.05)

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        return False, latency_ms, "Network connection to ESP32 failed after retries"

    def send_command(self, payload_or_action: str, speed_mode: Optional[str] = None) -> Tuple[bool, float, str]:
        """
        Main entry method to dispatch motor command / payload.
        """
        if self.protocol == "MQTT":
            return self.send_payload_mqtt(payload_or_action)

        mode = speed_mode.upper() if speed_mode else self.current_speed_mode
        pwm_val = config.SPEED_MODES.get(mode, config.SPEED_MODES[config.DEFAULT_SPEED_MODE])

        # Mock mode fallback only for non-MQTT legacy testing
        is_connected = self.ws_client is not None or self.socket_client is not None or self.protocol == "HTTP"
        if not is_connected:
            logger.info(f"ESP32 disconnected. MOCK execution for action: {payload_or_action}")
            return True, 0.0, "MOCK Delivery OK"

        if self.protocol == "WEBSOCKET":
            success, latency, msg = self.send_command_websocket(payload_or_action)
            if success:
                return success, latency, msg
            logger.warning(f"WebSocket to {self.esp32_ip}:{self.esp32_ws_port} failed ({msg}). Falling back to TCP Socket on port {self.esp32_port}...")
            return self.send_command_socket(payload_or_action)
        elif self.protocol == "TCP_SOCKET":
            return self.send_command_socket(payload_or_action)
        else:
            return self.send_command_http(payload_or_action, pwm_val)

    def close(self):
        """
        Closes network connections cleanly.
        """
        if self.ws_client:
            try:
                self.ws_client.close()
            except Exception:
                pass
            self.ws_client = None

        if self.socket_client:
            try:
                self.socket_client.close()
            except Exception:
                pass
            self.socket_client = None

        if self.mqtt_client:
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except Exception:
                pass
            self._mqtt_connected = False
            self.mqtt_client = None


