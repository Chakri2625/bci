import json
import threading
from queue import Queue, Full, Empty

from flask_sock import Sock


class _Client:
    """One native WebSocket connection with a bounded outbound queue."""

    def __init__(self, ws):
        self.ws = ws
        self.queue = Queue(maxsize=100)
        self.send_lock = threading.Lock()
        self.closed = threading.Event()

    def send_loop(self):
        while not self.closed.is_set():
            try:
                message = self.queue.get(timeout=0.5)
            except Empty:
                continue

            if message is None:
                break

            try:
                with self.send_lock:
                    self.ws.send(message)
            except Exception:
                self.closed.set()
                break

    def enqueue(self, message):
        if self.closed.is_set():
            return False

        try:
            self.queue.put_nowait(message)
            return True
        except Full:
            # Drop the oldest queued message so a slow browser cannot
            # grow memory without bound.
            try:
                self.queue.get_nowait()
                self.queue.put_nowait(message)
                return True
            except (Empty, Full):
                return False

    def close(self):
        self.closed.set()
        try:
            self.queue.put_nowait(None)
        except Full:
            pass


class WebSocketManager:
    """Native WebSocket transport for browser <-> Master Hub communication."""

    def __init__(self):
        self.sock = Sock()
        self.clients = set()
        self.lock = threading.RLock()
        self.device_status = {}

        # Cached MQTT connection state.
        # These values must survive WebSocket client reconnects so a
        # dashboard opened after MQTT startup immediately reflects the
        # real Master Hub / broker / slave state.
        self.mqtt_connected = False
        self.mqtt_ever_connected = False
        self.device_mqtt_status = {}

        self.command_handler = None
        self.initialized = False
        self.socket = self  # Compatibility alias for legacy socket.socket callers

    def run(self, app, **kwargs):
        """Compatibility method for legacy Flask-SocketIO callers."""
        pass

    def initialize(self, app):
        if self.initialized:
            return

        self.sock.init_app(app)

        @self.sock.route("/ws")
        def websocket(ws):
            client = _Client(ws)
            self.register(client)

            try:
                self.send_to(client, {
                    "type": "connected",
                    "transport": "websocket",
                })

                self.send_to(client, {
                    "type": "device_status_snapshot",
                    "devices": self.get_device_status_snapshot(),
                })

                # MQTT may have connected before the browser opened its
                # WebSocket. Send the cached broker state immediately.
                self.send_to(client, {
                    "type": "mqtt_status",
                    "connected": self.mqtt_connected,
                    "ever_connected": self.mqtt_ever_connected,
                })

                # Restore cached slave MQTT states for this new client.
                self.send_to(client, {
                    "type": "mqtt_device_snapshot",
                    "devices": self.get_device_mqtt_status_snapshot(),
                })

                while True:
                    raw = ws.receive()

                    if raw is None:
                        break

                    self.handle_client_message(client, raw)

            except Exception as exc:
                print(f"[WebSocket] Client error: {exc}")

            finally:
                self.unregister(client)

        self.initialized = True
        print("[WebSocket] Native WebSocket endpoint ready -> /ws")

    def register(self, client):
        with self.lock:
            self.clients.add(client)

        threading.Thread(
            target=client.send_loop,
            name="SynaptiMesh-WebSocket-Sender",
            daemon=True,
        ).start()

        print(f"[WebSocket] Client connected | clients={self.client_count()}")

    def unregister(self, client):
        removed = False

        with self.lock:
            if client in self.clients:
                self.clients.remove(client)
                removed = True

        client.close()

        if removed:
            print(f"[WebSocket] Client disconnected | clients={self.client_count()}")

    def client_count(self):
        with self.lock:
            return len(self.clients)

    def send_to(self, client, data):
        try:
            message = json.dumps(data, separators=(",", ":"))
        except (TypeError, ValueError):
            return False

        return client.enqueue(message)

    def broadcast(self, data):
        try:
            message = json.dumps(data, separators=(",", ":"))
        except (TypeError, ValueError):
            return

        with self.lock:
            clients = list(self.clients)

        dead = []

        for client in clients:
            if not client.enqueue(message):
                dead.append(client)

        for client in dead:
            self.unregister(client)

    # ----------------------------------------------------------
    # Browser -> Hub
    # ----------------------------------------------------------

    def set_command_handler(self, callback):
        self.command_handler = callback

    def handle_client_message(self, client, raw):
        try:
            data = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            self.send_to(client, {
                "type": "error",
                "message": "Invalid WebSocket JSON message",
            })
            return

        if not isinstance(data, dict):
            self.send_to(client, {
                "type": "error",
                "message": "WebSocket message must be an object",
            })
            return

        message_type = str(data.get("type", "")).strip().lower()

        if message_type == "ping":
            self.send_to(client, {"type": "pong"})
            return

        if message_type == "hello":
            self.send_to(client, {
                "type": "hello",
                "transport": "websocket",
            })
            return

        if message_type == "command":
            if not self.command_handler:
                self.send_to(client, {
                    "type": "command_result",
                    "ok": False,
                    "message": "Command handler is not ready",
                })
                return

            command = str(data.get("command", "")).strip().upper()
            device = str(data.get("device", "")).strip()

            result = self.command_handler(
                command=command,
                device=device,
            )

            if result is None:
                result = {
                    "ok": True,
                    "command": command,
                    "device": device,
                }

            result = dict(result)
            result["type"] = "command_result"
            self.send_to(client, result)
            return

        self.send_to(client, {
            "type": "error",
            "message": f"Unknown WebSocket message type: {message_type or 'empty'}",
        })

    # ----------------------------------------------------------
    # Hub -> Browser event compatibility API
    # ----------------------------------------------------------

    def telemetry(self, data):
        payload = dict(data or {})
        self.broadcast({"type": "telemetry", **payload})

    def ack(self, data):
        self.broadcast({"type": "ack", **dict(data or {})})

    def activity(self, message_or_data):
        if isinstance(message_or_data, dict):
            payload = dict(message_or_data)
        else:
            payload = {"message": str(message_or_data)}

        self.broadcast({"type": "activity", **payload})

    def mqtt_status(self, connected):
        connected = bool(connected)

        with self.lock:
            self.mqtt_connected = connected
            if connected:
                self.mqtt_ever_connected = True

        self.broadcast({
            "type": "mqtt_status",
            "connected": connected,
            "ever_connected": self.mqtt_ever_connected,
        })

    def mqtt_device_status(self, device, status):
        device = str(device or "UNKNOWN").strip()
        status = str(status or "OFFLINE").strip().upper()

        with self.lock:
            self.device_mqtt_status[device] = status

        self.broadcast({
            "type": "mqtt_device_status",
            "device": device,
            "status": status,
        })

    def get_device_mqtt_status_snapshot(self):
        with self.lock:
            return dict(self.device_mqtt_status)

    def handle_message(self, topic, payload):
        """Broadcast raw MQTT traffic once, without interpreting it."""
        device = self.extract_device(topic)

        self.broadcast({
            "type": "mqtt_message",
            "topic": topic,
            "payload": payload,
            "device": device,
        })

    def update_device_status(self, device, status):
        device = str(device or "UNKNOWN")
        status = str(status or "UNKNOWN")

        with self.lock:
            self.device_status[device] = status

        self.broadcast({
            "type": "device_status",
            "device": device,
            "status": status,
        })

    def get_device_status_snapshot(self):
        with self.lock:
            return dict(self.device_status)

    @staticmethod
    def extract_device(topic):
        parts = str(topic or "").split("/")

        if len(parts) >= 3:
            return parts[1]

        return "UNKNOWN"
