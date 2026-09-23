"""
Wheelchair Network Sender (MQTT + Mock fallback)
==================================================
Handles command dispatch to the smart wheelchair controller over MQTT, with a
safe MOCK fallback when no broker connection is available. Mirrors the public
contract of plugins/embedded/subplugins/rc_car/esp32_sender.py (protocol,
is_connected(), send_command(), close(), on_ack_received / on_status_received
callbacks) so both Robotics devices behave identically from the plugin layer.

Unlike the RC car, no wheelchair hardware protocol (TCP/WebSocket/HTTP) has
been specified in this project yet, so only MQTT + MOCK are implemented here.
Extending to another transport should follow the same pattern used in
esp32_sender.py.
"""

import logging
import threading
import time
from typing import Optional, Callable, Tuple

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

from . import config

logger = logging.getLogger("WheelchairSender")


class WheelchairSender:
    """Manages the communication bridge with the wheelchair controller."""

    def __init__(self,
                 device_ip: str = config.DEVICE_IP,
                 protocol: str = config.COMMUNICATION_PROTOCOL):

        self.device_ip = device_ip
        self.protocol = protocol.upper()

        self.mqtt_client = None
        self._mqtt_connected = False
        self.mqtt_broker_host = getattr(config, "MQTT_BROKER_HOST", "52.21.249.6")
        self.mqtt_broker_port = int(getattr(config, "MQTT_BROKER_PORT", 1883))
        self.mqtt_control_topic = getattr(config, "MQTT_CONTROL_TOPIC", "wheelchair/wheelchair-01/control")
        self.mqtt_status_topic = getattr(config, "MQTT_STATUS_TOPIC", "wheelchair/wheelchair-01/status")
        self.mqtt_ack_topic = getattr(config, "MQTT_ACK_TOPIC", "wheelchair/wheelchair-01/ack")

        self.last_ack: Optional[str] = None
        self.last_device_status: Optional[str] = None
        self.last_payload_sent: Optional[str] = None

        self._ack_event = threading.Event()

        self.on_ack_received: Optional[Callable[[str], None]] = None
        self.on_status_received: Optional[Callable[[str], None]] = None

        if self.protocol == "MQTT":
            self._init_mqtt()

        logger.info(f"WheelchairSender initialized (Protocol: {self.protocol}, Broker: {self.mqtt_broker_host}:{self.mqtt_broker_port})")

    def _init_mqtt(self) -> bool:
        if mqtt is None:
            logger.error("Paho-MQTT library not installed! Cannot initialize MQTT.")
            self._mqtt_connected = False
            return False

        if self.mqtt_client and self._mqtt_connected:
            return True

        try:
            client_id = f"SynaptiMesh_Wheelchair_{int(time.time() * 1000) % 1000000}"
            if hasattr(mqtt, "CallbackAPIVersion"):
                self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
            else:
                self.mqtt_client = mqtt.Client(client_id=client_id)

            def on_connect(client, userdata, flags, rc, properties=None):
                is_success = (rc == 0) or (hasattr(rc, "is_failure") and not rc.is_failure)
                if is_success:
                    self._mqtt_connected = True
                    logger.info(f"Connected to MQTT Broker ({self.mqtt_broker_host}:{self.mqtt_broker_port}) successfully.")
                    client.subscribe(self.mqtt_ack_topic)
                    client.subscribe(self.mqtt_status_topic)
                else:
                    self._mqtt_connected = False
                    logger.error(f"MQTT Connection failed with code: {rc}")

            def on_disconnect(client, userdata, *args):
                self._mqtt_connected = False
                logger.warning("Disconnected from MQTT Broker.")

            def on_message(client, userdata, msg):
                try:
                    payload_str = msg.payload.decode("utf-8", errors="ignore").strip()
                    topic = msg.topic
                    if topic == self.mqtt_ack_topic:
                        self.last_ack = payload_str
                        self._ack_event.set()
                        if self.on_ack_received:
                            self.on_ack_received(payload_str)
                    elif topic == self.mqtt_status_topic:
                        self.last_device_status = payload_str
                        if self.on_status_received:
                            self.on_status_received(payload_str)
                except Exception as e:
                    logger.error(f"Error processing MQTT message: {e}")

            self.mqtt_client.on_connect = on_connect
            self.mqtt_client.on_disconnect = on_disconnect
            self.mqtt_client.on_message = on_message

            self.mqtt_client.connect(self.mqtt_broker_host, self.mqtt_broker_port, keepalive=60)
            self.mqtt_client.loop_start()

            start_wait = time.time()
            while not self._mqtt_connected and (time.time() - start_wait) < 2.0:
                time.sleep(0.05)

            return self._mqtt_connected
        except Exception as e:
            logger.error(f"Failed to set up MQTT client: {e}")
            self._mqtt_connected = False
            return False

    def is_connected(self) -> bool:
        if self.protocol == "MQTT":
            return self._mqtt_connected
        return False

    def send_command(self, payload: str) -> Tuple[bool, float, str]:
        """
        Dispatches a command payload to the wheelchair controller. Falls back to
        a MOCK acknowledgement when no broker connection is available so the
        rest of the pipeline (and tests) can run without real hardware.
        """
        start_time = time.perf_counter()
        self.last_payload_sent = payload

        if self.protocol == "MQTT" and self.mqtt_client and self._mqtt_connected:
            try:
                self.mqtt_client.publish(self.mqtt_control_topic, payload, qos=1)
                latency_ms = (time.perf_counter() - start_time) * 1000.0
                logger.debug(f"MQTT Command '{payload}' published in {latency_ms:.2f}ms")
                return True, latency_ms, "MQTT Publish OK"
            except Exception as e:
                logger.warning(f"MQTT publish failed: {e}. Falling back to MOCK.")

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        logger.info(f"Wheelchair controller unreachable. MOCK execution for payload: {payload}")
        return True, latency_ms, "MOCK Delivery OK"

    def close(self):
        if self.mqtt_client:
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except Exception:
                pass
            self._mqtt_connected = False
            self.mqtt_client = None
