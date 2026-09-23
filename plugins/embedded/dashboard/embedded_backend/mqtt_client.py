from enum import Enum
import socket
import time

import paho.mqtt.client as mqtt
try:
    from .. import embedded_config as config
except ImportError:
    import config


class MQTTState(Enum):
    OFFLINE = 0
    CONNECTING = 1
    CONNECTED = 2
    RECONNECTING = 3
    ERROR = 4


class MQTTClient:

    def __init__(self):

        # Explicit unique client ID.
        self.client_id = (
            f"synaptimesh-master-hub-"
            f"{int(time.time() * 1000)}"
        )

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.client_id,
            protocol=mqtt.MQTTv311,
            clean_session=True,
        )

        self.state = MQTTState.OFFLINE
        self.connected = False

        self.message_listeners = []
        self.connection_listeners = []

        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self.client.on_log = self.on_log
        self.client.on_connect_fail = self.on_connect_fail

    # ============================================================
    # RAW MQTT 3.1.1 DIAGNOSTIC
    # ============================================================

    def _mqtt_protocol_diagnostic(self):
        """
        Performs a real MQTT 3.1.1 CONNECT/CONNACK test.

        This is separate from Paho and is only diagnostic.

        It distinguishes:
            1. TCP port reachable
            2. MQTT broker responding
            3. MQTT broker rejecting the CONNECT
        """

        host = config.MQTT_BROKER
        port = config.MQTT_PORT

        print(
            f"[MQTT DIAGNOSTIC] Raw MQTT test -> "
            f"{host}:{port}",
            flush=True
        )

        sock = None

        try:
            sock = socket.create_connection(
                (host, port),
                timeout=10
            )

            print(
                f"[MQTT DIAGNOSTIC] Raw TCP CONNECTED -> "
                f"{host}:{port}",
                flush=True
            )

            # MQTT 3.1.1 CONNECT packet.
            #
            # Variable header = 10 bytes:
            #   00 04       Protocol name length
            #   MQTT        Protocol name
            #   04          MQTT 3.1.1
            #   02          Clean Session = 1
            #   00 3C       Keep Alive = 60 seconds
            #
            # Payload = 2 bytes:
            #   00 00       Zero-length Client ID
            #
            # Total Remaining Length = 10 + 2 = 12 = 0x0C.
            connect_packet = bytes([
                0x10, 0x0C,
                0x00, 0x04,
                0x4D, 0x51, 0x54, 0x54,
                0x04,
                0x02,
                0x00, 0x3C,
                0x00, 0x00,
            ])

            print(
                "[MQTT DIAGNOSTIC] Sending valid MQTT 3.1.1 CONNECT",
                flush=True
            )

            print(
                "[MQTT DIAGNOSTIC] CONNECT bytes -> "
                f"{connect_packet.hex(' ')}",
                flush=True
            )

            sock.sendall(connect_packet)

            print(
                "[MQTT DIAGNOSTIC] Waiting for CONNACK...",
                flush=True
            )

            response = sock.recv(16)

            if not response:
                print(
                    "[MQTT DIAGNOSTIC] MQTT FAILED -> "
                    "broker closed TCP connection without CONNACK",
                    flush=True
                )
                return False

            print(
                f"[MQTT DIAGNOSTIC] MQTT RESPONSE <- "
                f"{response.hex(' ')}",
                flush=True
            )

            # MQTT CONNACK:
            #   Byte 0 = 0x20
            #   Byte 1 = 0x02
            #   Byte 2 = ACK flags
            #   Byte 3 = reason/return code
            if len(response) >= 4 and response[0] == 0x20:

                reason_code = response[3]

                if reason_code == 0:
                    print(
                        "[MQTT DIAGNOSTIC] CONNACK SUCCESS -> "
                        "broker accepted MQTT CONNECT",
                        flush=True
                    )
                    return True

                reason_names = {
                    1: "Unacceptable protocol version",
                    2: "Identifier rejected",
                    3: "Server unavailable",
                    4: "Bad username/password",
                    5: "Not authorized",
                }

                description = reason_names.get(
                    reason_code,
                    "Unknown MQTT CONNACK reason"
                )

                print(
                    f"[MQTT DIAGNOSTIC] CONNACK REJECTED -> "
                    f"code={reason_code} | {description}",
                    flush=True
                )
                return False

            print(
                "[MQTT DIAGNOSTIC] MQTT FAILED -> "
                "received data was not a valid CONNACK",
                flush=True
            )
            return False

        except socket.timeout:
            print(
                "[MQTT DIAGNOSTIC] MQTT TIMEOUT -> "
                "TCP connection succeeded, but no CONNACK arrived "
                "within 10 seconds",
                flush=True
            )
            return False

        except Exception as e:
            print(
                f"[MQTT DIAGNOSTIC] Raw MQTT ERROR -> "
                f"{type(e).__name__}: {e}",
                flush=True
            )
            return False

        finally:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass

    # ============================================================
    # CONNECT
    # ============================================================

    def connect(self):

        self.state = MQTTState.CONNECTING

        print("[MQTT] Connecting...", flush=True)
        print(
            f"[MQTT] Broker -> "
            f"{config.MQTT_BROKER}:{config.MQTT_PORT}",
            flush=True
        )
        print(
            f"[MQTT] Client ID -> {self.client_id}",
            flush=True
        )

        # Diagnostic only. Paho connection below remains the real
        # application connection.
        diagnostic_ok = self._mqtt_protocol_diagnostic()

        print(
            f"[MQTT DIAGNOSTIC] Result -> "
            f"{'MQTT broker responded' if diagnostic_ok else 'No successful MQTT CONNACK'}",
            flush=True
        )

        # Actual Paho MQTT connection.
        try:
            result = self.client.connect(
                config.MQTT_BROKER,
                config.MQTT_PORT,
                keepalive=60
            )

            print(
                f"[MQTT] connect() returned -> {result}",
                flush=True
            )

            self.client.loop_start()

            print(
                "[MQTT] Network loop started",
                flush=True
            )

            # Give the background network loop time to receive CONNACK.
            # This does not block the web server indefinitely.
            for _ in range(15):
                if self.connected:
                    break
                time.sleep(1)

            if self.connected:
                print(
                    "[MQTT] Connection confirmed by broker",
                    flush=True
                )
            else:
                print(
                    "[MQTT] WARNING -> Paho is still waiting for broker CONNACK",
                    flush=True
                )

        except Exception as e:
            self.state = MQTTState.ERROR
            self.connected = False

            print(
                "[MQTT] Connection Failed",
                flush=True
            )
            print(
                f"[MQTT] Error -> {type(e).__name__}: {e}",
                flush=True
            )

            self._notify_connection_listeners(False)

    # ============================================================
    # DISCONNECT
    # ============================================================

    def disconnect(self):

        try:
            self.client.loop_stop()
        except Exception:
            pass

        try:
            self.client.disconnect()
        except Exception:
            pass

        self.state = MQTTState.OFFLINE
        self.connected = False

        print("[MQTT] Disconnected", flush=True)

        self._notify_connection_listeners(False)

    # ============================================================
    # PUBLISH
    # ============================================================

    def publish(self, topic, payload):

        if not self.connected:
            print("[MQTT] Publish Failed (Offline)", flush=True)
            return False

        result = self.client.publish(topic, payload)

        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            print(
                f"[MQTT TX] {topic} <- {payload}",
                flush=True
            )
            return True

        print(
            f"[MQTT ERROR] Failed -> {topic} "
            f"(rc={result.rc})",
            flush=True
        )

        return False

    # ============================================================
    # STATE
    # ============================================================

    def is_connected(self):
        return self.connected

    def get_state(self):
        return self.state

    # ============================================================
    # MESSAGE LISTENERS
    # ============================================================

    def add_message_listener(self, callback):

        if callback not in self.message_listeners:
            self.message_listeners.append(callback)

    def remove_message_listener(self, callback):

        if callback in self.message_listeners:
            self.message_listeners.remove(callback)

    # ============================================================
    # CONNECTION LISTENERS
    # ============================================================

    def add_connection_listener(self, callback):

        if callback not in self.connection_listeners:
            self.connection_listeners.append(callback)

    def remove_connection_listener(self, callback):

        if callback in self.connection_listeners:
            self.connection_listeners.remove(callback)

    # ============================================================
    # SUBSCRIBE
    # ============================================================

    def subscribe(self, topic):

        if not self.connected:
            print(
                f"[MQTT] Cannot subscribe while offline -> {topic}",
                flush=True
            )
            return False

        try:
            result, mid = self.client.subscribe(topic)

            if result == mqtt.MQTT_ERR_SUCCESS:
                print(
                    f"[MQTT] Subscribed -> {topic} "
                    f"(mid={mid})",
                    flush=True
                )
                return True

            print(
                f"[MQTT] Failed to subscribe -> {topic} "
                f"(rc={result})",
                flush=True
            )

        except Exception as e:
            print(
                f"[MQTT] Subscribe Error -> {topic}: "
                f"{type(e).__name__}: {e}",
                flush=True
            )

        return False

    # ============================================================
    # MQTT CALLBACKS
    # ============================================================

    def on_connect(
        self,
        client,
        userdata,
        flags,
        reason_code,
        properties
    ):

        print(
            f"[MQTT] on_connect called | "
            f"reason_code={reason_code} | flags={flags}",
            flush=True
        )

        if reason_code == 0:

            self.connected = True
            self.state = MQTTState.CONNECTED

            print("[MQTT] Connected", flush=True)

            self.subscribe("robotcar/+/status")
            self.subscribe("robotcar/+/ack")
            self.subscribe("wheelchair/+/status")
            self.subscribe("wheelchair/+/ack")
            self.subscribe("mesh/+/telemetry")
            self.subscribe("mesh/+/status")
            self.subscribe("mesh/+/ack")

            self._notify_connection_listeners(True)

        else:

            self.connected = False
            self.state = MQTTState.ERROR

            print(
                f"[MQTT] Failed -> reason_code={reason_code}",
                flush=True
            )

            self._notify_connection_listeners(False)

    def on_disconnect(
        self,
        client,
        userdata,
        disconnect_flags,
        reason_code,
        properties
    ):

        self.connected = False

        if reason_code == 0:
            self.state = MQTTState.OFFLINE
            print(
                "[MQTT] Disconnected cleanly",
                flush=True
            )
        else:
            self.state = MQTTState.RECONNECTING
            print(
                f"[MQTT] Disconnected unexpectedly -> "
                f"reason_code={reason_code}",
                flush=True
            )

        self._notify_connection_listeners(False)

    def on_connect_fail(self, client, userdata):

        self.connected = False
        self.state = MQTTState.ERROR

        print("[MQTT] CONNECT FAILED", flush=True)
        print(
            "[MQTT] Paho could not establish the MQTT connection.",
            flush=True
        )

        self._notify_connection_listeners(False)

    def on_log(self, client, userdata, level, buf):

        print(
            f"[MQTT LOG] {buf}",
            flush=True
        )

    def on_message(self, client, userdata, msg):

        payload = msg.payload.decode(
            "utf-8",
            errors="replace"
        )

        print(
            f"[MQTT RX] {msg.topic} -> {payload}",
            flush=True
        )

        for callback in list(self.message_listeners):

            try:
                callback(msg.topic, payload)

            except Exception as e:
                print(
                    "[MQTT] Listener Error:",
                    flush=True
                )
                print(e, flush=True)

    # ============================================================
    # CONNECTION LISTENER NOTIFICATION
    # ============================================================

    def _notify_connection_listeners(self, connected):

        for callback in list(self.connection_listeners):

            try:
                callback(connected)

            except Exception as e:
                print(
                    "[MQTT] Connection Listener Error:",
                    flush=True
                )
                print(e, flush=True)
