import logging
import time
from .esp32_sender import ESP32Sender
from .command_processor import CommandProcessor
from . import config

logger = logging.getLogger("RcCarPlugin")

class RcCarPlugin:
    def __init__(self):
        self.sender = ESP32Sender()
        self.processor = CommandProcessor(on_action_ready=self._on_action_ready)
        self.last_status = "initialized"
        self.last_motor_action = "STOP"
        self.last_ack = None
        self.last_device_status = None
        self.last_source = "DASHBOARD"
        self.last_confidence = 1.0

        # Register callbacks from sender
        self.sender.on_ack_received = self._on_ack_received
        self.sender.on_status_received = self._on_status_received

    def _parse_motor_action(self, msg: str) -> str:
        if not msg or not isinstance(msg, str):
            return None
        upper = msg.upper()
        if "LEFT360" in upper:
            return "LEFT360"
        if "RIGHT360" in upper:
            return "RIGHT360"
        if "FORWARD" in upper:
            return "FORWARD"
        if "BACKWARD" in upper or "REVERSE" in upper:
            return "BACKWARD"
        if "LEFT" in upper:
            return "LEFT"
        if "RIGHT" in upper:
            return "RIGHT"
        if "STOP" in upper or "OBSTACLE" in upper or "BLOCKED" in upper or "COMPLETE" in upper or "OFFLINE" in upper:
            return "STOP"
        return None

    def _on_ack_received(self, ack_msg: str):
        self.last_ack = ack_msg
        logger.info(f"RcCarPlugin recorded ACK: {ack_msg}")
        action = self._parse_motor_action(ack_msg)
        if action:
            self.last_motor_action = action
            if action != "STOP":
                self.processor.active_state = action
                self.processor.last_command_time = time.time()
            else:
                self.processor.active_state = "STOP"

    def _on_status_received(self, status_msg: str):
        self.last_device_status = status_msg
        logger.info(f"RcCarPlugin recorded Device Status: {status_msg}")
        action = self._parse_motor_action(status_msg)
        if action:
            self.last_motor_action = action
            if action != "STOP":
                self.processor.active_state = action
                self.processor.last_command_time = time.time()
            else:
                self.processor.active_state = "STOP"

    def _on_action_ready(self, payload: str, bci_command: str, confidence: float):
        logger.info(f"RcCarPlugin dispatching payload: {payload}")
        self.sender.send_command(payload)
        self.last_motor_action = bci_command
        self.last_ack = getattr(self.sender, "last_ack", None)
        self.last_device_status = getattr(self.sender, "last_device_status", None)

    async def execute(self, command: str, payload: dict = None):
        if command == "get_widget":
            return {
                "id": "rc_car",
                "name": "RC Car Control",
                "type": "rc_car", 
                "actions": ["forward", "backward", "left", "right", "stop"],
                "status": self.status()
            }
            
        if command == "STOP":
            self.stop()
            return {"status": "success", "action": "STOP", "payload_sent": config.COMMAND_MAP.get("STOP", "LIFTCARSTOP")}

        # Normalize incoming command
        cmd_upper = command.strip().upper()
        legacy_map = {"PUSH": "FORWARD", "PULL": "BACKWARD"}
        bci_cmd = legacy_map.get(cmd_upper, cmd_upper)
        
        confidence = payload.get("confidence", 1.0) if payload else 1.0
        source = payload.get("source", "DASHBOARD") if payload else "DASHBOARD"

        executed, status_msg, payload_sent = self.processor.process_command(bci_cmd, confidence)
        self.last_status = "SUCCESS" if executed else "FAILED"
        if executed:
            self.last_source = source
            self.last_confidence = confidence
            
        logger.info(f"[DEBUG 7] RC CAR RESULT: {self.last_status}")
        logger.info(f"[DEBUG 8] RC CAR PAYLOAD: {payload_sent}")
        logger.info(f"[DEBUG 9] DASHBOARD UPDATE")
        
        return {
            "status": "success" if executed else "failed",
            "message": status_msg,
            "action": command,
            "payload_sent": payload_sent,
            "ack": getattr(self.sender, "last_ack", None),
            "device_status": getattr(self.sender, "last_device_status", None)
        }
            
    def stop(self):
        logger.warning("RC CAR EMERGENCY STOP TRIGGERED")
        self.processor.process_command("STOP", 1.0)
        self.last_motor_action = "STOP"
        self.last_status = "SUCCESS"
        self.last_source = "DASHBOARD"
        self.last_confidence = 1.0

    def is_connected(self) -> bool:
        if hasattr(self, "sender") and hasattr(self.sender, "is_connected"):
            return self.sender.is_connected()
        return False

    def status(self):
        was_timeout = self.processor.check_watchdog_timeout()
        
        mqtt_connected = getattr(self.sender, "_mqtt_connected", False)
        connected = self.is_connected()
        
        command = self.last_motor_action
        
        device_state = "STOPPED"
        if command == "FORWARD": device_state = "MOVING_FORWARD"
        elif command == "BACKWARD": device_state = "MOVING_BACKWARD"
        elif command == "LEFT": device_state = "TURNING_LEFT"
        elif command == "RIGHT": device_state = "TURNING_RIGHT"
        
        exec_status = "EXECUTING"
        if command == "STOP":
            exec_status = "STOPPED"
            
        if was_timeout or (command == "STOP" and self.last_status == "FAILED" and "TIMEOUT" in getattr(self, 'last_status_msg', '')):
            exec_status = "TIMEOUT"
            
        if self.processor.active_state == "STOP" and was_timeout:
             exec_status = "TIMEOUT"

        # Check offline
        if not connected and self.sender.protocol != "MOCK":
            exec_status = "OFFLINE"
            device_state = "STOPPED"
            command = "NOT EXECUTED"
            
        return {
            "device": "CAR",
            "command": command,
            "source": getattr(self, "last_source", "DASHBOARD").upper(),
            "status": exec_status,
            "device_state": device_state,
            
            # Keys needed for backward compatibility with older UI
            "movement": command,
            "confidence": getattr(self, "last_confidence", 1.0),
            "safety": "TIMEOUT" if exec_status == "TIMEOUT" else "SAFE",
            "mode": "HARDWARE" if connected else ("DISCONNECTED" if self.sender.protocol == "MQTT" else "MOCK"),
            "protocol": self.sender.protocol,
            "connected": connected,
            "mqtt_status": "CONNECTED" if mqtt_connected else "DISCONNECTED",
            "esp_ack": getattr(self.sender, "last_ack", None) or "--",
            "esp_status": getattr(self.sender, "last_device_status", None) or "--",
            "speed": 0.12 if command in ["FORWARD", "LEFT", "RIGHT"] else (-0.12 if command == "BACKWARD" else 0.0),
            "steering": -1 if command == "LEFT" else (1 if command == "RIGHT" else 0),
            "speed_mode": getattr(self, "speed_mode", "MEDIUM"),
            "speed_pwm": getattr(self, "speed_pwm", 180),
            "front_distance": getattr(self, "front_distance", 50.0),
            "rear_distance": getattr(self, "rear_distance", 50.0),
        }
