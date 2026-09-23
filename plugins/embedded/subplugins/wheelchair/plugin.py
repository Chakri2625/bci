import logging
from .wheelchair_sender import WheelchairSender
from .command_processor import WheelchairCommandProcessor
from . import config

logger = logging.getLogger("WheelchairPlugin")


class WheelchairPlugin:
    """
    Embedded/Robotics subplugin for the Smart Wheelchair. Structurally mirrors
    RcCarPlugin (plugins/embedded/subplugins/rc_car/plugin.py) so both devices
    share the same execute()/status()/get_widget() contract expected by
    EmbeddedPlugin and the Command Router.
    """

    def __init__(self):
        self.sender = WheelchairSender()
        self.processor = WheelchairCommandProcessor(on_action_ready=self._on_action_ready)
        self.last_status = "initialized"
        self.last_motor_action = "STOP"
        self.last_ack = None
        self.last_device_status = None
        self.last_source = "master_hub"
        self.last_confidence = 1.0

        self.sender.on_ack_received = self._on_ack_received
        self.sender.on_status_received = self._on_status_received

    def _on_ack_received(self, ack_msg: str):
        self.last_ack = ack_msg
        logger.info(f"WheelchairPlugin recorded ACK: {ack_msg}")

    def _on_status_received(self, status_msg: str):
        self.last_device_status = status_msg
        logger.info(f"WheelchairPlugin recorded Device Status: {status_msg}")

    def _on_action_ready(self, payload: str, bci_command: str, confidence: float):
        logger.info(f"WheelchairPlugin dispatching payload: {payload}")
        self.sender.send_command(payload)
        self.last_motor_action = bci_command
        self.last_ack = getattr(self.sender, "last_ack", None)
        self.last_device_status = getattr(self.sender, "last_device_status", None)

    async def execute(self, command: str, payload: dict = None):
        if command == "get_widget":
            return {
                "id": "wheelchair",
                "name": "Wheelchair Control",
                "type": "wheelchair",
                "actions": ["push", "pull", "left", "right"],
                "status": self.status()
            }

        if command == "STOP":
            self.stop()
            return {"status": "success", "action": "STOP", "payload_sent": config.COMMAND_MAP.get("STOP", "WHEELCHAIRSTOP")}

        # Normalize incoming command. Router sends the internal robotics
        # operation names (FORWARD/BACKWARD/LEFT/RIGHT) from rule_router.py;
        # translate those back to the external BCI command names before
        # safety processing, same convention as RcCarPlugin.
        cmd_upper = command.strip().upper()
        legacy_map = {"FORWARD": "PUSH", "BACKWARD": "PULL"}
        bci_cmd = legacy_map.get(cmd_upper, cmd_upper)

        confidence = payload.get("confidence", 1.0) if payload else 1.0
        source = payload.get("source", "master_hub") if payload else "master_hub"

        executed, status_msg, payload_sent = self.processor.process_command(bci_cmd, confidence)
        self.last_status = "SUCCESS" if executed else "FAILED"
        if executed:
            self.last_source = source
            self.last_confidence = confidence

        return {
            "status": "success" if executed else "failed",
            "message": status_msg,
            "action": command,
            "payload_sent": payload_sent,
            "ack": getattr(self.sender, "last_ack", None),
            "device_status": getattr(self.sender, "last_device_status", None)
        }

    def stop(self):
        logger.warning("WHEELCHAIR EMERGENCY STOP TRIGGERED")
        self.processor.process_command("STOP", 1.0)
        self.last_motor_action = "STOP"
        self.last_status = "SUCCESS"
        self.last_source = "master_hub"
        self.last_confidence = 1.0

    def status(self):
        connected = self.sender.is_connected()
        movement = self.last_motor_action
        steering = 0
        speed = 1.0 if movement != "STOP" else 0.0

        if movement == "LEFT":
            steering = -1
        elif movement == "RIGHT":
            steering = 1

        return {
            "command": movement.lower(),
            "movement": movement,
            "mapped_command": movement,
            "source": getattr(self, "last_source", "emotiv_simulator"),
            "confidence": getattr(self, "last_confidence", 0.0),
            "status": "MOVING" if movement != "STOP" else "STOPPED",
            "safety": "SAFE",
            "mode": "HARDWARE" if connected else "MOCK",
            "protocol": self.sender.protocol,
            "connected": connected,
            "last_ack": getattr(self.sender, "last_ack", None) or "--",
            "last_status": getattr(self.sender, "last_device_status", None) or "--",
            "speed": speed,
            "steering": steering,
            "moving": movement != "STOP"
        }
