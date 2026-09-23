import json
import logging
import uuid
import sys
import time
import threading
from pathlib import Path
from datetime import datetime
import paho.mqtt.client as mqtt

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.config import (
    MQTT_BROKER, MQTT_PORT, MQTT_QOS, MQTT_KEEPALIVE, CLIENT_ID_PREFIX,
    TOPIC_COMMAND, TOPIC_ACK, TOPIC_STATUS, TOPIC_HEARTBEAT, TOPIC_MEDIA,
    ONLINE_PAYLOAD, LAST_WILL_PAYLOAD, DEBUG_MODE,
    COMMAND_MAP, DISPLAY_LABELS
)


class MQTTService:
    """MQTT service for handling communication with the BCI system."""
    
    def __init__(self, socketio, pipeline_scheduler=None):
        self.socketio = socketio
        self.client = None
        self.logger = logging.getLogger()
        self.pipeline_scheduler = pipeline_scheduler
        self.manual_command_active = False
        self.manual_command_timeout = None
        self.media_subscribed = True  # Track media subscription state
    
    def on_message(self, client, userdata, msg):
        """Callback for handling incoming MQTT messages."""
        try:
            raw_payload = msg.payload.decode('utf-8')
            payload = json.loads(raw_payload)
            topic = msg.topic

            if topic == TOPIC_ACK and payload.get("status") == "EXECUTED":
                self.logger.info(f"[APK] ACK RECEIVED :: {payload.get('command')}")
                self.socketio.emit('execution_feedback', payload)
                return

            msg_type = payload.get("type")

            if msg_type == "execution_feedback":
                self.logger.info(f"[APK] ACK RECEIVED :: {payload.get('command')}")
                self.socketio.emit('execution_feedback', payload)

            elif topic == TOPIC_STATUS:
                # Suppress status logging to avoid spam
                pass

            elif topic == TOPIC_HEARTBEAT:
                if DEBUG_MODE:
                    self.logger.debug(f"[MQTT] Heartbeat :: {payload.get('status')}")

            elif topic == TOPIC_MEDIA or msg_type == "media_update" or any(k in payload for k in ["title", "song", "track", "song_name", "track_name"]):
                song_title = payload.get("title") or payload.get("song") or payload.get("track") or payload.get("song_name") or "Playing Track"
                artist_name = payload.get("artist") or payload.get("singers") or payload.get("subtitle") or payload.get("artist_name") or "JioSaavn Artist"
                
                self.logger.info(f"[JIOSAAVN REALTIME] {song_title} — {artist_name}")
                
                # Broadcast normalized payload to Web Socket
                self.socketio.emit('media_update', {
                    "title": song_title,
                    "artist": artist_name,
                    "album_art": payload.get("album_art") or payload.get("art") or payload.get("artwork") or payload.get("imageUrl") or "",
                    "status": payload.get("status") or payload.get("state") or "Playing",
                    "current_time": payload.get("current_time", "1:15"),
                    "total_time": payload.get("total_time", "3:40"),
                    "progress_percent": payload.get("progress_percent", 35),
                    "volume": payload.get("volume", 70)
                })

            elif msg_type == "command":
                if DEBUG_MODE:
                    self.logger.debug(f"[CMD] Broadcasted command payload: {payload.get('command')}")

        except Exception as e:
            self.logger.error(f"[MQTT ERROR] {e}")
    
    def connect(self) -> mqtt.Client:
        """Connect to MQTT broker and return the client instance."""
        self.client = mqtt.Client(
            client_id=f"{CLIENT_ID_PREFIX}-{uuid.uuid4()}",
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        self.client.on_message = self.on_message
        self.status_thread_running = True
        self.client.will_set(
            topic=TOPIC_STATUS,
            payload=LAST_WILL_PAYLOAD,
            qos=MQTT_QOS,
            retain=False,
        )

        try:
            logging.info(f"[MQTT] Connecting to {MQTT_BROKER}:{MQTT_PORT}...")
            self.client.connect(MQTT_BROKER, MQTT_PORT, keepalive=MQTT_KEEPALIVE)

            for topic in (TOPIC_ACK, TOPIC_STATUS, TOPIC_HEARTBEAT, TOPIC_MEDIA):
                self.client.subscribe(topic, qos=MQTT_QOS)
                logging.info(f"[MQTT] Subscribed to {topic}")

            self.client.loop_start()

            result = self.client.publish(
                topic=TOPIC_STATUS,
                payload=ONLINE_PAYLOAD,
                qos=MQTT_QOS,
                retain=True,
            )
            if result.rc == 0:
                logging.info(f"[MQTT] ONLINE status published to {TOPIC_STATUS}: {ONLINE_PAYLOAD}")
            else:
                logging.error(f"[MQTT] Failed to publish ONLINE status, code: {result.rc}")

            logging.info(f"[MQTT] Publishing commands on {TOPIC_COMMAND}")
            
            # Notify frontend that MQTT is connected
            self.socketio.emit('mqtt_connection_status', {'status': 'CONNECTED'})
            
            # Start lightweight periodic status publisher (every 30 seconds)
            self.start_status_publisher()
            
            return self.client
        except Exception as e:
            logging.error(f"[MQTT ERROR] Failed: {e}")
            raise
    
    def publish_command(self, raw_command: str, confidence: float, timestamp: float = None):
        """Publish a command to the MQTT broker."""
        import time
        
        command = (COMMAND_MAP.get(raw_command) or raw_command).strip()
        label = DISPLAY_LABELS.get(command, command)

        payload = {
            "command": command,
            "normalized_command": command.upper(),
            "label": label,
            "confidence": round(float(confidence), 3),
            "timestamp": datetime.now().isoformat(),
        }
        serialized_payload = json.dumps(payload)
        if self.client:
            result = self.client.publish(TOPIC_COMMAND, serialized_payload, qos=MQTT_QOS)
            if result.rc == 0:
                logging.info(f"[MQTT] publish {TOPIC_COMMAND} :: {command}")
            else:
                logging.error(f"[MQTT] Publish failed code {result.rc}")

        self.socketio.emit('command_dispatched', {
            "command": command,
            "display_label": label,
            "confidence": confidence,
            "timestamp": timestamp or time.time(),
        })
    
    def publish_search_query(self, query: str):
        """Publish a search query to the MQTT broker."""
        payload = {
            "command": "type_query",
            "normalized_command": "TYPE_QUERY",
            "label": "Search Query",
            "query": query,
            "confidence": 1.0,
            "timestamp": datetime.now().isoformat(),
        }
        serialized_payload = json.dumps(payload)
        if self.client:
            result = self.client.publish(TOPIC_COMMAND, serialized_payload, qos=MQTT_QOS)
            if result.rc == 0:
                logging.info(f"[MQTT SEARCH] {TOPIC_COMMAND} :: query='{query}'")
            else:
                logging.error(f"[MQTT] Search publish failed code {result.rc}")
    
    def activate_manual_command_mode(self, duration_seconds=10):
        """
        Activate manual command mode to allow media updates for a specified duration.
        
        Args:
            duration_seconds: How long to allow media updates after manual command (default 10 seconds)
        """
        self.manual_command_active = True
        self.manual_command_timeout = time.time() + duration_seconds
        self.logger.info(f"[MQTT] Manual command mode activated for {duration_seconds} seconds")
        
        # Ensure media topic is subscribed for manual commands
        if not self.media_subscribed and self.client:
            try:
                self.client.subscribe(TOPIC_MEDIA, qos=MQTT_QOS)
                self.media_subscribed = True
                self.logger.info("[MQTT] Subscribed to media topic for manual command")
            except Exception as e:
                self.logger.error(f"[MQTT ERROR] Failed to subscribe to media topic: {e}")
        
        # Schedule automatic unsubscription after timeout
        def unsubscribe_after_timeout():
            time.sleep(duration_seconds)
            if self.manual_command_active and time.time() >= self.manual_command_timeout:
                self.manual_command_active = False
                self.manual_command_timeout = None
                # Only unsubscribe if pipeline is still paused
                if self.pipeline_scheduler and self.pipeline_scheduler.is_paused():
                    self.toggle_media_subscription(False)
        
        thread = threading.Thread(target=unsubscribe_after_timeout, daemon=True)
        thread.start()
    
    def toggle_media_subscription(self, should_subscribe):
        """
        Toggle media topic subscription based on pipeline state.
        
        Args:
            should_subscribe: True to subscribe, False to unsubscribe
        """
        if not self.client:
            return
            
        try:
            if should_subscribe and not self.media_subscribed:
                self.client.subscribe(TOPIC_MEDIA, qos=MQTT_QOS)
                self.media_subscribed = True
                self.logger.info("[MQTT] Subscribed to media topic")
            elif not should_subscribe and self.media_subscribed:
                self.client.unsubscribe(TOPIC_MEDIA)
                self.media_subscribed = False
                self.logger.info("[MQTT] Unsubscribed from media topic")
        except Exception as e:
            self.logger.error(f"[MQTT ERROR] Failed to toggle media subscription: {e}")
    
    def start_status_publisher(self):
        """
        Start a lightweight background thread to periodically republish the ONLINE status.
        This ensures that late-joining Android clients receive the web plugin status
        even if the MQTT broker's retained message mechanism isn't working properly.
        """
        def publish_status_periodically():
            while self.status_thread_running:
                try:
                    if self.client and self.client.is_connected():
                        result = self.client.publish(
                            topic=TOPIC_STATUS,
                            payload=ONLINE_PAYLOAD,
                            qos=MQTT_QOS,
                            retain=True,
                        )
                        # Don't log successful republishes to avoid spam
                except Exception as e:
                    logging.error(f"[MQTT ERROR] Failed to republish status: {e}")
                
                # Republish every 30 seconds (much less frequent than before)
                time.sleep(30)
        
        status_thread = threading.Thread(target=publish_status_periodically, daemon=True)
        status_thread.start()
        logging.info("[MQTT] Started lightweight status publisher (30s interval)")
    
    def stop_status_publisher(self):
        """Stop the periodic status publisher."""
        self.status_thread_running = False
