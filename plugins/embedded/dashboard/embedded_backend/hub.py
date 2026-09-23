from .cli import CLI
from .mqtt_client import MQTTClient
from .dispatcher import Dispatcher, CommandSource
from .telemetry import TelemetryManager
from .websocket_manager import WebSocketManager
from .device_registry import CommandTarget
from .socket_manager import SocketManager


class Hub:

    def __init__(self):
        print()
        print("======================================")
        print("Creating SynaptiMesh Hub")
        print("======================================")

        self.websocket = WebSocketManager()
        self.socket = self.websocket  # Compatibility alias
        self.mqtt = MQTTClient()
        self.dispatcher = Dispatcher(self.mqtt)
        self.telemetry = TelemetryManager(self.websocket)
        self.cli = CLI(self.dispatcher)
        self.initialized = False

    def initialize(self):
        if self.initialized:
            return

        print("[HUB] Initializing Modules...")

        # Exactly one MQTT message listener.
        self.mqtt.add_message_listener(
            self.telemetry.handle_telemetry
        )

        # MQTT connection state -> browser WebSocket clients.
        self.mqtt.add_connection_listener(
            self.websocket.mqtt_status
        )

        # Browser WebSocket commands -> Hub dispatcher.
        self.websocket.set_command_handler(
            self.handle_websocket_command
        )

        self.mqtt.connect()
        self.initialized = True

        print("[HUB] Initialization Complete")

    def handle_websocket_command(self, command, device=""):
        command = str(command or "").strip().upper()
        device = str(device or "").strip()

        if not command:
            return {"ok": False, "message": "Empty command"}

        domains = ("LIFT", "DESKTOP", "IOT")
        domain = next(
            (item for item in domains if command.startswith(item)),
            None,
        )

        if domain is None:
            return {
                "ok": False,
                "message": f"Invalid domain: {command}",
            }

        remaining = command[len(domain):]

        if remaining.startswith("CAR"):
            target = CommandTarget.CAR
            action = remaining[3:]

        elif remaining.startswith("CHAIR"):
            target = CommandTarget.CHAIR
            action = remaining[5:]

        else:
            return {
                "ok": False,
                "message": f"Invalid target: {remaining}",
            }

        valid_commands = {
            "FORWARD",
            "BACKWARD",
            "LEFT",
            "RIGHT",
            "LEFT360",
            "RIGHT360",
            "STOP",
            "DROP",
        }

        if action not in valid_commands:
            return {
                "ok": False,
                "message": f"Invalid command: {action}",
            }

        print()
        print("================================")
        print("[WEB COMMAND]")
        print(f"RAW: {command}")
        print("================================")
        print(f"[DOMAIN]  {domain}")
        print(f"[TARGET]  {target}")
        print(f"[COMMAND] {action}")

        self.dispatcher.dispatch(
            source=CommandSource.DASHBOARD,
            target=target,
            domain=domain,
            command=action,
        )

        print("[WEB COMMAND] ACCEPTED")

        return {
            "ok": True,
            "command": command,
            "device": device,
        }

    def start_cli(self):
        print("[HUB] Starting CLI...")
        self.cli.start()
