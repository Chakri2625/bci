from flask_socketio import SocketIO


# ==========================================================
# SOCKET MANAGER
# ==========================================================

class SocketManager:

    def __init__(self):

        self.socket = SocketIO(
            cors_allowed_origins="*",
            async_mode="threading",
            ping_timeout=20,
            ping_interval=25,
            logger=False,
            engineio_logger=False
        )

        # --------------------------------------------------
        # LATEST DEVICE STATUS
        # --------------------------------------------------
        self.device_status = {}
        self.device_mqtt_status = {}


    # ======================================================
    # INITIALIZE
    # ======================================================

    def initialize(
        self,
        app
    ):

        self.socket.init_app(
            app
        )

        # --------------------------------------------------
        # SEND CURRENT STATE TO NEW DASHBOARD CLIENT
        # --------------------------------------------------

        @self.socket.on("connect")
        def handle_connect():

            print(
                "[SOCKET.IO] Dashboard connected"
            )

            self.socket.emit(
                "device_status_snapshot",
                self.device_status
            )


    def _safe_emit(self, event, data):
        try:
            if self.socket:
                self.socket.emit(event, data)
        except Exception:
            pass

    # ======================================================
    # TELEMETRY
    # ======================================================

    def telemetry(
        self,
        data
    ):
        self._safe_emit("telemetry", data)


    # ======================================================
    # ACK
    # ======================================================

    def ack(
        self,
        data
    ):
        self._safe_emit("ack", data)


    # ======================================================
    # ACTIVITY
    # ======================================================

    def activity(
        self,
        data
    ):
        self._safe_emit("activity", data)


    # ======================================================
    # MQTT STATUS
    # ======================================================

    def mqtt_status(
        self,
        connected
    ):
        self._safe_emit("mqtt_status", {"connected": connected})


    # ======================================================
    # RAW MQTT MESSAGE
    # ======================================================

    def mqtt_message(
        self,
        topic,
        payload
    ):
        self._safe_emit("mqtt_message", {"topic": topic, "payload": payload})


    # Backward-compatible alias for any future caller.
    def handle_message(
        self,
        topic,
        payload
    ):

        self.mqtt_message(
            topic,
            payload
        )


    # ======================================================
    # DEVICE STATUS
    # ======================================================

    def update_device_status(
        self,
        device,
        status
    ):

        device = str(device).strip()
        status = str(status).strip()

        if not device:
            return

        self.device_status[device] = status
        self._safe_emit("device_status", {"device": device, "status": status})

    def mqtt_device_status(
        self,
        device,
        status
    ):
        device_str = str(device or "UNKNOWN").strip()
        status_str = str(status or "OFFLINE").strip().upper()
        self.device_mqtt_status[device_str] = status_str
        self._safe_emit("mqtt_device_status", {"device": device_str, "status": status_str})

    def alert(
        self,
        data
    ):
        self._safe_emit("alert", data)

    def get_device_status_snapshot(self):
        return dict(self.device_status)

    def get_device_mqtt_status_snapshot(self):
        return dict(self.device_mqtt_status)

