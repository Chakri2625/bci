"""
main
mqtt_service.py
----------------
Reusable MQTT client wrapping paho-mqtt.

Features
--------
✓ Persistent MQTT connection
✓ Thread-safe
✓ Automatic reconnect
✓ Publish messages
✓ Subscribe to MQTT topics
✓ Receive MQTT messages
✓ Custom callback support
"""

import json
import threading
import time

import paho.mqtt.client as mqtt

from services.logger_service import get_logger

log = get_logger("services.mqtt")

#BROKER_HOST = "broker.hivemq.com"
BROKER_HOST = "52.21.249.6"
BROKER_PORT = 1883
KEEPALIVE = 60

# Default Publish Topic
DEFAULT_TOPIC = None
#DEFAULT_TOPIC = "iot/device/{device_id}/action"

# Subscribe Topics
STATUS_TOPIC = "iot/device/+/status"
ACK_TOPIC = "iot/device/+/ack"
SENSOR_TOPIC = "iot/device/+/sensor"

# new topics
ONLINE_DEVICES = {}
# embedded devices
ROBOT_ACK_TOPIC = "robotcar/+/ack"
ROBOT_STATUS_TOPIC = "robotcar/+/status"

WHEELCHAIR_ACK_TOPIC = "wheelchair/+/ack"
WHEELCHAIR_STATUS_TOPIC = "wheelchair/+/status"


class MQTTService:

    def __init__(
        self,
        host=BROKER_HOST,
        port=BROKER_PORT,
        topic=DEFAULT_TOPIC,
        client_id="shaik_master_hub"
    ):

        self.host = host
        self.port = port
        self.topic = topic
        import uuid
        self.client_id = f"{client_id}_{uuid.uuid4().hex[:8]}"

        self._client = mqtt.Client(
            client_id=self.client_id,
            clean_session=True
        )

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        self._connected = False
        self._lock = threading.Lock()

        # User-defined callback
        self.message_callback = None

        # ACK synchronization
        self._ack_events = {}
        self._ack_payloads = {}

    # -------------------------------------------------
    # MQTT CALLBACKS
    # -------------------------------------------------

    def _on_connect(self, client, userdata, flags, rc):

        if rc == 0:

            self._connected = True

            log.info(
                f"Connected to MQTT Broker {self.host}:{self.port}"
            )

            # Subscribe to Topics

            client.subscribe(STATUS_TOPIC)
            log.info(f"Subscribed : {STATUS_TOPIC}")

            client.subscribe(ACK_TOPIC)
            log.info(f"Subscribed : {ACK_TOPIC}")

            client.subscribe(SENSOR_TOPIC)
            log.info(f"Subscribed : {SENSOR_TOPIC}")
             # EMBEDDED DEVICES
            client.subscribe(ROBOT_ACK_TOPIC)
            log.info(f"Subscribed : {ROBOT_ACK_TOPIC}")

            client.subscribe(ROBOT_STATUS_TOPIC)
            log.info(f"Subscribed : {ROBOT_STATUS_TOPIC}")

            client.subscribe(WHEELCHAIR_ACK_TOPIC)
            log.info(f"Subscribed : {WHEELCHAIR_ACK_TOPIC}")

            client.subscribe(WHEELCHAIR_STATUS_TOPIC)
            log.info(f"Subscribed : {WHEELCHAIR_STATUS_TOPIC}")
        else:

            self._connected = False
            log.error(f"MQTT Connection Failed : {rc}")

    def _on_disconnect(self, client, userdata, rc):

        self._connected = False
        log.warning(f"MQTT Disconnected : {rc}")

    def _on_message(self, client, userdata, msg):

        payload = msg.payload.decode()

        log.info("=================================")
        log.info(f"TOPIC   : {msg.topic}")
        log.info(f"PAYLOAD : {payload}")
        log.info("=================================")

        try:

            data = json.loads(payload)

        except Exception:

            data = payload

        # 30/07 Update online devices list
        if (
            isinstance(data, dict)
            and msg.topic.endswith("/status")
        ):
            device_id = data.get("device_id")
            if device_id:
                ONLINE_DEVICES[device_id] = data
                log.info(f"Device Registered : {device_id}")
                try:
                    # pyrefly: ignore [missing-import]
                    from services.dependency_guard import dependency_guard
                    dependency_guard.handle_status_update(msg.topic, data)
                except Exception as exc:
                    log.debug(f"Dependency guard status update ignored: {exc}")

        # Handle ACKs and wake waiting listeners
        if (
            isinstance(data, dict)
            and msg.topic.endswith("/ack")
        ):
            command_id = data.get("command_id")
            if command_id:
                with self._lock:
                    self._ack_payloads[command_id] = data
                    event = self._ack_events.get(command_id)
                    if event:
                        event.set()
                try:
                    # pyrefly: ignore [missing-import]
                    from services.dependency_guard import dependency_guard
                    dependency_guard.handle_ack(msg.topic, data)
                except Exception as exc:
                    log.debug(f"Dependency guard ack update ignored: {exc}")

        # Call custom callback if registered
        if self.message_callback:
            try:
                self.message_callback(msg.topic, data)
            except Exception as e:
                log.error(f"Message Callback Error : {e}")

    # -------------------------------------------------
    # ACK TRACKING
    # -------------------------------------------------

    def register_pending_ack(self, command_id: str):
        """Register a command_id to wait for an incoming ACK."""
        if not command_id:
            return
        with self._lock:
            self._ack_events[command_id] = threading.Event()
            self._ack_payloads.pop(command_id, None)

    def wait_for_ack(self, command_id: str, timeout: float = 2.0) -> tuple[bool, dict]:
        """
        Wait for an ACK payload from the device.
        Returns: (success: bool, ack_payload: dict)
        """
        if not command_id:
            return False, {}

        with self._lock:
            event = self._ack_events.get(command_id)
            if not event:
                event = threading.Event()
                self._ack_events[command_id] = event

        received = event.wait(timeout=timeout)
        with self._lock:
            payload = self._ack_payloads.pop(command_id, {})
            self._ack_events.pop(command_id, None)

        return received, payload

    # -------------------------------------------------
    # REGISTER CALLBACK
    # -------------------------------------------------

    def set_message_callback(self, callback):
        """
        callback(topic, payload)
        """
        self.message_callback = callback

    # -------------------------------------------------
    # CONNECTION
    # -------------------------------------------------

    def connect(self, timeout=5):

        with self._lock:

            if self._connected:
                return True

            try:

                self._client.connect(
                    self.host,
                    self.port,
                    KEEPALIVE
                )

                self._client.loop_start()

            except Exception as exc:

                log.error(exc)
                return False

        waited = 0

        while not self._connected and waited < timeout:

            time.sleep(0.1)
            waited += 0.1

        return self._connected

    def disconnect(self):

        with self._lock:

            self._client.loop_stop()
            self._client.disconnect()

            self._connected = False

            log.info("MQTT Client Disconnected")

    # -------------------------------------------------
    # PUBLISH
    # -------------------------------------------------

    def publish(
        self,
        payload,
        topic=None,
        qos=1,
        retry=1
    ):

        target_topic = topic or self.topic

        if not self._connected:

            if not self.connect():

                log.error("MQTT Not Connected")
                return False

        try:

            result = self._client.publish(
                target_topic,
                payload,
                qos=qos
            )

            result.wait_for_publish()

            if result.is_published():

                log.info(
                    f"Published -> {target_topic}"
                )

                return True

            if retry > 0:

                return self.publish(
                    payload,
                    topic,
                    qos,
                    retry - 1
                )

            return False

        except Exception as e:

            log.error(e)

            if retry > 0:

                return self.publish(
                    payload,
                    topic,
                    qos,
                    retry - 1
                )

            return False

    def publish_json(
        self,
        data,
        topic=None,
        qos=1
    ):

        return self.publish(
            json.dumps(data),
            topic,
            qos
        )


mqtt_service = MQTTService()

# new instance of MQTTService can be created with a different topic if needed
def get_first_online_device():

    if not ONLINE_DEVICES:
        return None

    return next(iter(ONLINE_DEVICES))
