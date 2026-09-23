import json
import logging
import threading
import time
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.config import DATA_FILE_PATH, CONFIDENCE_THRESHOLD, TARGET_DOMAIN, COMMAND_MAP


class PipelineScheduler:
    """Manages the BCI pipeline background task with pause/resume functionality."""
    
    def __init__(self, mqtt_service, socketio):
        self.mqtt_service = mqtt_service
        self.socketio = socketio
        self.pause_event = threading.Event()
        self.pause_event.set()  # Pipeline starts in HALTED/PAUSED state initially
        self.logger = logging.getLogger()
    
    def interruptible_sleep(self, seconds: float):
        """Sleep that can be interrupted by pause_event."""
        steps = int(seconds * 10)
        for _ in range(steps):
            if self.pause_event.is_set():
                return True
            time.sleep(0.1)
        return False
    
    def toggle_pause(self, should_pause: bool):
        """Toggle the pause state of the pipeline."""
        if should_pause:
            self.pause_event.set()
            self.logger.info("[PIPELINE] Automatic pipeline HALTED.")
        else:
            self.pause_event.clear()
            self.logger.info("[PIPELINE] Automatic pipeline RESUMED.")
    
    def is_paused(self):
        """Check if the pipeline is currently paused."""
        return self.pause_event.is_set()
    
    def bci_pipeline_loop(self):
        """Main BCI pipeline loop that processes EEG data and publishes commands."""
        file_path = DATA_FILE_PATH

        # Track processed packets to prevent duplicate triggers within a single pass
        last_processed_timestamp = 0.0

        # Connect to MQTT with retry/backoff so a transient broker or network
        # failure does not permanently kill the pipeline thread. The thread
        # stays alive and keeps attempting until the broker is reachable.
        mqtt_client = None
        while mqtt_client is None:
            try:
                mqtt_client = self.mqtt_service.connect()
            except Exception as e:
                logging.error(f"[MQTT ERROR] Connection failed: {e}. Retrying in 5s...")
                time.sleep(5)

        try:
            while True:
                # 1. If halted via UI, wait here until RESUME is clicked
                if self.pause_event.is_set():
                    time.sleep(0.5)
                    continue

                try:
                    with open(file_path, 'r', encoding="utf-8") as file:
                        data = json.load(file)
                except Exception as e:
                    logging.error(f"[FILE READ ERROR] Could not read JSON: {e}")
                    time.sleep(3)
                    continue

                readings = data.get("data", [])

                # 2. Iterate through all packets in the JSON file
                for packet in readings:
                    if self.pause_event.is_set():
                        break

                    domain = packet.get("domain")
                    confidence = packet.get("confidence", 0.0)
                    raw_command = packet.get("command")
                    timestamp = packet.get("timestamp", 0.0)

                    # Skip packets already processed in the current loop iteration
                    if timestamp <= last_processed_timestamp:
                        continue

                    if domain != TARGET_DOMAIN or raw_command == "Right" or confidence < CONFIDENCE_THRESHOLD:
                        if timestamp > last_processed_timestamp:
                            last_processed_timestamp = timestamp
                        continue

                    target_command = COMMAND_MAP.get(raw_command)
                    if not target_command:
                        if timestamp > last_processed_timestamp:
                            last_processed_timestamp = timestamp
                        continue

                    self.mqtt_service.publish_command(raw_command, confidence, timestamp)
                    last_processed_timestamp = timestamp

                    # 3-second delay between commands
                    if self.interruptible_sleep(3):
                        break

                # 3. CRITICAL FIX: Reset timestamp tracking so the loop can replay the JSON file indefinitely
                last_processed_timestamp = 0.0

                if not self.pause_event.is_set():
                    self.interruptible_sleep(2)

        except Exception as e:
            logging.critical(f"[PIPELINE CRASH] {e}")



