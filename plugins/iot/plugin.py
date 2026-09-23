import json
import logging
import time
import uuid
import asyncio
import paho.mqtt.client as mqtt
from typing import Dict, Any, Optional, List
from dataclasses import asdict

from .device_manager import DeviceManager, Device
from models.device_models import DeviceState
from services.iot_telemetry_normalizer import normalize_iot_telemetry, device_to_telemetry_packet
from core.state.state_manager import state_manager
from core.communication.websocket_server import websocket_server

logger = logging.getLogger("iot_plugin")

# ESP32 2.0.0-unified Firmware Command Mappings
COMMAND_MAPPINGS = {
    "left_light_on": {"device": "light", "state": "ON"},
    "left_light_off": {"device": "light", "state": "OFF"},
    "left_fan_on": {"device": "fan", "state": "ON"},
    "left_fan_off": {"device": "fan", "state": "OFF"},
    "left_pump_on": {"device": "pump", "state": "ON"},
    "left_pump_off": {"device": "pump", "state": "OFF"},
    "right_light_on": {"device": "light", "state": "ON"},
    "right_light_off": {"device": "light", "state": "OFF"},
    "right_fan_on": {"device": "fan", "state": "ON"},
    "right_fan_off": {"device": "fan", "state": "OFF"},
    "toggle_light": {"device": "light", "state": "TOGGLE"},
    "toggle_fan": {"device": "fan", "state": "TOGGLE"},
    "toggle_pump": {"device": "pump", "state": "TOGGLE"},
    "turn on": {"device": "light", "state": "ON"},
    "turn off": {"device": "light", "state": "OFF"},
}

SUPPORTED_ACTIONS = {
    "LIGHT": ["Left_light_on", "Left_light_off", "Right_light_on", "Right_light_off", "toggle_light", "turn on", "turn off"],
    "FAN": ["Left_fan_on", "Left_fan_off", "Right_fan_on", "Right_fan_off", "toggle_fan"],
    "PUMP": ["Left_pump_on", "Left_pump_off", "toggle_pump"]
}


class IoTPlugin:
    plugin_id = "iot"
    SUPPORTED_ACTIONS = SUPPORTED_ACTIONS
    
    def __init__(self, broker="broker.hivemq.com", port=1883, topic_root="iot/device"):
        self.broker = broker
        self.port = port
        self.topic_root = topic_root
        self.client = mqtt.Client()
        self.connected = False
        
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message

        # Lightweight state storage for incoming messages
        self.latest_status = {}
        self.latest_sensor = {}
        self.latest_ack = {}
        self.command_acks: Dict[str, Any] = {}
        
        # Enhanced Device Manager integration (Tasks 1, 2, 4, 5)
        self.device_manager = DeviceManager()
        
        # Pending ACKs map: command_id -> asyncio.Future
        self.pending_acks: Dict[str, asyncio.Future] = {}

    @classmethod
    def is_action_supported(cls, device_type: str, action: str) -> bool:
        actions = cls.SUPPORTED_ACTIONS.get(device_type.upper(), [])
        return any(a.lower() == action.lower() for a in actions)

    @classmethod
    def get_supported_actions(cls) -> Dict[str, List[str]]:
        return cls.SUPPORTED_ACTIONS

    def get_command_ack(self, command_id: str) -> Optional[Dict[str, Any]]:
        return self.command_acks.get(command_id)

    def initialize(self, context=None):
        """Start the MQTT client and connect to the broker."""
        try:
            self.client.connect(self.broker, self.port, 60)
            self.client.loop_start()
            logger.info(f"MQTT Listener Started on {self.broker}:{self.port}")
        except Exception as e:
            logger.error(f"Failed to connect to MQTT Broker: {e}")
            self.connected = False

    def shutdown(self):
        """Cleanly disconnect and stop the loop."""
        self.client.loop_stop()
        self.client.disconnect()
        self.connected = False
        
        # Clean up pending ACKs
        for command_id, future in self.pending_acks.items():
            if not future.done():
                future.cancel()
        self.pending_acks.clear()
        
        logger.info("MQTT Listener Stopped")

    def on_connect(self, client, userdata, flags, rc):
        self.connected = (rc == 0)
        if self.connected:
            logger.info(f"MQTT Connected : {rc}")
            # Primary device topics
            client.subscribe(f"{self.topic_root}/+/status")
            client.subscribe(f"{self.topic_root}/+/ack")
            client.subscribe(f"{self.topic_root}/+/sensor")
            client.subscribe("iot/+/status")
            client.subscribe("iot/+/ack")
            client.subscribe("iot/+/sensor")
            client.subscribe("iot/esp32/action")
            # Legacy & firmware specific topics
            client.subscribe("shaik/home/system_ack")
            client.subscribe("shaik/home/status")

            try:
                state_manager.update_domain_state("IOT", {
                    "status": "READY",
                    "connected": True,
                    "broker": f"{self.broker}:{self.port}"
                })
            except Exception:
                pass
        else:
            logger.error(f"MQTT Connection failed with code {rc}")

    def on_disconnect(self, client, userdata, rc):
        self.connected = False
        logger.info(f"MQTT Disconnected : {rc}")
        if hasattr(self, "pending_acks"):
            for cmd_id, fut in list(self.pending_acks.items()):
                if not fut.done():
                    fut.set_result({"status": "error", "message": "Device disconnected during communication"})
            self.pending_acks.clear()

        try:
            state_manager.update_domain_state("IOT", {
                "status": "DEGRADED",
                "connected": False
            })
        except Exception:
            pass

    def is_connected(self) -> bool:
        """
        Returns True if connected to MQTT broker AND at least one IoT relay device
        has reported an active status/heartbeat within the last 15 seconds.
        """
        if not self.connected:
            return False
        if hasattr(self, "device_manager"):
            devices = self.device_manager.get_all_devices()
            if not devices:
                return False
            now = time.time()
            return any((now - getattr(d, 'last_seen_timestamp', 0)) < 15.0 for d in devices)
        return False

    def check_timeouts(self, timeout_seconds: float = 15.0) -> List[Any]:
        """
        Check for timed-out devices, transition to OFFLINE, sync central StateManager,
        and broadcast events via WebSocket. (Tasks 4 & 5)
        """
        timeout_records = self.device_manager.check_timeouts(timeout_seconds=timeout_seconds)
        for rec in timeout_records:
            dev = self.device_manager.get_device(rec.device_id)
            if dev:
                dev_state = dev.to_device_state()
                state_manager.sync_device_state(dev_state)

                # Broadcast WebSocket OFFLINE notification
                try:
                    env = websocket_server.create_envelope(
                        msg_type="DEVICE_OFFLINE",
                        source_domain="IOT",
                        source_id=rec.device_id,
                        payload={
                            "device_id": rec.device_id,
                            "status": "OFFLINE",
                            "reason": rec.reason,
                            "timestamp": rec.timestamp,
                            "state": dev.to_dict(),
                            "device_state": dev_state.to_dict()
                        }
                    )
                    websocket_server.broadcast_envelope_sync(env)
                except Exception as ws_err:
                    logger.debug(f"Timeout WebSocket broadcast failed: {ws_err}")

        return timeout_records

    def on_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode()
            data = json.loads(payload)
            topic = msg.topic
            
            # Handle shaik/home/system_ack format
            if "shaik/home" in topic:
                device_id = "shaik_home"
                if "ack" in topic:
                    self.handle_ack(device_id, data)
                elif "status" in topic:
                    self.handle_status(device_id, data)
                return

            parts = topic.split("/")
            if len(parts) >= 2:
                device_id = parts[-2]
                
                if topic.endswith("/status"):
                    self.handle_status(device_id, data)
                elif topic.endswith("/ack"):
                    self.handle_ack(device_id, data)
                elif topic.endswith("/sensor"):
                    self.handle_sensor(device_id, data)
                else:
                    logger.debug(f"Unknown topic format: {topic}")
                
        except json.JSONDecodeError:
            logger.error(f"Malformed JSON payload on topic {msg.topic}")
        except Exception as e:
            logger.error(f"MQTT MESSAGE ERROR : {e}")

    def handle_status(self, device_id: str, data: Dict[str, Any]):
        """
        Task 1, 4, 5, 6, 7: Ingest status, update device state, sync with central StateManager,
        and broadcast state update over WebSocket.
        """
        if not isinstance(data, dict):
            logger.error(f"Invalid status payload format: expected dict, got {type(data)}")
            return
        
        self.connected = True
        self.latest_status[device_id] = dict(data)
        merged_data = dict(data)
        merged_data["device_id"] = device_id
        dev, activity_record = self.device_manager.update_device(merged_data)
        logger.info(f"Status update from esp32 ({device_id}): {data}")

        if dev:
            # Sync with Central StateManager (Task 6)
            dev_state = dev.to_device_state()
            state_manager.sync_device_state(dev_state)

            # Broadcast over WebSocket (Task 7)
            try:
                env = websocket_server.create_envelope(
                    msg_type="IOT_STATE_UPDATE",
                    source_domain="IOT",
                    source_id=device_id,
                    payload={
                        "device_id": device_id,
                        "status": "ONLINE",
                        "online": dev.online,
                        "relays": dev.get_relay_snapshot(),
                        "state": dev.to_dict(),
                        "device_state": dev_state.to_dict(),
                        "activity": activity_record.to_dict() if activity_record else None
                    }
                )
                websocket_server.broadcast_envelope_sync(env)
            except Exception as e:
                logger.debug(f"WebSocket state broadcast failed: {e}")

    def handle_sensor(self, device_id: str, data: Dict[str, Any]):
        """
        Task 1, 3, 6, 7: Ingest sensor readings, normalize telemetry, sync StateManager,
        and broadcast TELEMETRY_FRAME over WebSocket.
        """
        if not isinstance(data, dict):
            return
        
        self.connected = True
        self.latest_sensor[device_id] = dict(data)
        merged_data = dict(data)
        merged_data["device_id"] = device_id
        dev, activity_record = self.device_manager.update_sensors(device_id, merged_data)
        logger.info(f"Sensor telemetry from esp32 ({device_id}): {data}")

        if dev:
            # Normalize to standard telemetry format (Task 3)
            telemetry_packet = normalize_iot_telemetry(dev.to_dict(), device_id=device_id)
            dev_state = dev.to_device_state()

            # Sync with Central StateManager (Task 6)
            state_manager.sync_device_state(dev_state)

            # Broadcast standardized telemetry packet over WebSocket (Task 7)
            try:
                env = websocket_server.create_envelope(
                    msg_type="TELEMETRY_FRAME",
                    source_domain="IOT",
                    source_id=device_id,
                    telemetry_id=telemetry_packet.telemetry_id,
                    payload=telemetry_packet.payload.model_dump(exclude_none=True)
                )
                websocket_server.broadcast_envelope_sync(env)
            except Exception as e:
                logger.debug(f"WebSocket telemetry broadcast failed: {e}")

    def handle_ack(self, device_id: str, data: Dict[str, Any]):
        """
        Task 1, 2, 6, 7: Acknowledgement Handler & activity log recording.
        """
        self.latest_ack[device_id] = dict(data)
        merged_data = dict(data)
        merged_data["device_id"] = device_id
        dev, activity_record = self.device_manager.update_device(merged_data)
        
        command_id = data.get("command_id", "UNKNOWN")
        command = data.get("command", "UNKNOWN")
        status = data.get("status", "UNKNOWN")
        
        logger.info(f"[ACK] Device: {device_id} | Command: {command} | Command ID: {command_id} | Status: {status}")

        if not activity_record and dev:
            activity_record = self.device_manager.log_activity(
                device_id=device_id,
                action=f"ACK:{command}",
                new_state=dev.get_relay_snapshot(),
                source="MQTT_ACK",
                status="SUCCESS" if str(status).lower() not in ("error", "failed", "false") else "FAILED",
                metadata=data
            )

        if dev:
            dev_state = dev.to_device_state()
            state_manager.sync_device_state(dev_state)

            try:
                env = websocket_server.create_envelope(
                    msg_type="IOT_COMMAND_ACK",
                    source_domain="IOT",
                    source_id=device_id,
                    payload={
                        "device_id": device_id,
                        "command_id": command_id,
                        "command": command,
                        "status": status,
                        "state": dev.to_dict(),
                        "device_state": dev_state.to_dict(),
                        "ack_data": data
                    }
                )
                websocket_server.broadcast_envelope_sync(env)
            except Exception as e:
                logger.debug(f"WebSocket ACK broadcast failed: {e}")
        
        if command_id == "UNKNOWN":
            logger.warning(f"ACK payload missing command_id from {device_id}")
            return
            
        self.command_acks[command_id] = {
            "device_id": device_id,
            "data": data
        }

        future = self.pending_acks.pop(command_id, None)
        if future:
            if not future.done():
                try:
                    loop = future.get_loop()
                    loop.call_soon_threadsafe(future.set_result, data)
                except Exception as e:
                    logger.error(f"Failed to set future result safely: {e}")
            else:
                logger.warning(f"ACK received for command {command_id}, but future was already done.")
        else:
            logger.debug(f"Received ACK for unknown/resolved command_id: {command_id}")

    async def execute_with_ack(self, command: str, payload: Optional[Dict[str, Any]] = None, timeout: float = 5.0) -> Dict[str, Any]:
        """Execute a command and wait for its ACK."""
        payload = payload or {}
        command_id = payload.get("command_id", str(uuid.uuid4()))
        payload["command_id"] = command_id
        
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self.pending_acks[command_id] = future
        
        # Execute standard publish
        result = await self.execute(command, payload)
        
        if result.get("status") != "success":
            self.pending_acks.pop(command_id, None)
            return result
            
        try:
            ack_data = await asyncio.wait_for(future, timeout=timeout)
            
            ack_status = ack_data.get("status", "success")
            if str(ack_status).lower() in ["error", "failed", "false"]:
                result["status"] = "error"
                result["message"] = ack_data.get("message", "Device reported error")
            else:
                result["status"] = "success"
                result["message"] = "ACK received"
            result["ack_data"] = ack_data
            return result
        except asyncio.TimeoutError:
            self.pending_acks.pop(command_id, None)
            result["status"] = "error"
            result["message"] = "ACK timeout"
            return result
        except asyncio.CancelledError:
            self.pending_acks.pop(command_id, None)
            raise

    async def execute(self, command: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Executes IoT domain actions by publishing to MQTT in the exact JSON shape
        the ESP32 firmware expects:
            {"command": "Left_light_on", "command_id": "<uuid>"}
        """
        payload = payload or {}
        command_id = payload.get("command_id") or str(uuid.uuid4())

        if "device_id" not in payload and command != "GET_STATUS":
            return {
                "status": "error",
                "message": "device_id missing: Validation Error: device_id is required for IoT actions",
                "command_id": command_id
            }

        device_id = payload.get("device_id") or "ESP32_RELAY_01"
        
        # Auto-resolve hardcoded device_id to the actual connected device's MAC
        if device_id == "ESP32_RELAY_01":
            all_devices = self.device_manager.get_all_devices()
            if all_devices:
                device_id = all_devices[0].device_id
            else:
                device_id = "00_4B_12_30_81_00"
        
        if command == "GET_STATUS":
            # Check timeouts on status query
            self.check_timeouts(timeout_seconds=15.0)
            device = self.device_manager.get_device(device_id)
            device_data = asdict(device) if device else {}
            res = {
                "status": "success",
                "device_id": device_id,
                "latest_status": self.latest_status.get(device_id, {}),
                "latest_ack": self.latest_ack.get(device_id, {}),
                "latest_sensor": self.latest_sensor.get(device_id, {}),
                "device_info": device_data,
                "activity_logs": self.device_manager.get_activity_logs(device_id, limit=20)
            }
            if "command_id" in payload:
                res["command_ack"] = self.get_command_ack(payload["command_id"])
            return res
        
        if not self.connected:
            return {
                "status": "error",
                "message": "MQTT client disconnected",
                "command_id": command_id
            }

        # Map to 2.0.0-unified dictionary
        mapped_cmd = COMMAND_MAPPINGS.get(command.lower())
        
        if not mapped_cmd and not command.startswith("TURN_"):
            return {
                "status": "error",
                "message": f"Unknown command: {command}",
                "command_id": command_id
            }
            
        outbound_payload = {
            "command": command,
            "command_id": command_id,
            "timestamp": int(time.time() * 1000)
        }
        if mapped_cmd:
            outbound_payload["device"] = mapped_cmd["device"]
            outbound_payload["state"] = mapped_cmd["state"]
        
        raw_json = json.dumps(outbound_payload)
        topic = f"{self.topic_root}/{device_id}/action"
        
        try:
            # Publish to primary device topic
            msg_info = self.client.publish(topic, raw_json)
            
            if msg_info.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.info(f"[IOT PUBLISH] Topic: {topic} | Payload: {raw_json}")
                
                # Log execution in activity log (Task 2)
                self.device_manager.log_activity(
                    device_id=device_id,
                    action=f"DISPATCH:{command}",
                    source="REST_API",
                    status="SUCCESS",
                    reason="Command published to MQTT",
                    metadata={"topic": topic, "command_id": command_id, "outbound": outbound_payload}
                )

                return {
                    "status": "success",
                    "command_id": command_id,
                    "topic": topic,
                    "message": "Command published successfully",
                    "command": mapped_cmd,
                    "raw_payload": outbound_payload
                }
            else:
                return {
                    "status": "error",
                    "message": f"Publish failed with code {msg_info.rc}",
                    "command_id": command_id
                }
        except Exception as e:
            self.connected = False
            logger.error(f"Failed to publish command: {e}")
            return {
                "status": "error",
                "message": f"Exception during publish: {str(e)}",
                "command_id": command_id
            }
