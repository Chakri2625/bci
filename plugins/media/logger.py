import json
import os
import datetime
import threading

class MediaActivityLogger:
    def __init__(self, log_path="data/media_log.json"):
        self.log_path = log_path
        self.lock = threading.Lock()
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        if not os.path.exists(self.log_path):
            with open(self.log_path, "w") as f:
                json.dump({"current_media": {}, "history": []}, f)

    def _read_log(self):
        try:
            with open(self.log_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"current_media": {}, "history": []}

    def _write_log(self, data):
        with open(self.log_path, "w") as f:
            json.dump(data, f, indent=4)

    def log_activity(self, activity: dict):
        with self.lock:
            data = self._read_log()
            
            # Enrich activity with timestamp if missing
            if "timestamp" not in activity:
                activity["timestamp"] = datetime.datetime.now().isoformat()
                
            # Update history
            data["history"].append(activity)
            if len(data["history"]) > 100:  # Keep last 100 entries
                data["history"] = data["history"][-100:]
                
            # Update current media state if status is success
            if activity.get("status") == "SUCCESS":
                data["current_media"] = {
                    "domain": activity.get("domain"),
                    "platform": activity.get("application"),
                    "media_type": activity.get("media_type"),
                    "title": activity.get("title"),
                    "artist": activity.get("artist"),
                    "state": activity.get("current_state"),
                    "position_seconds": activity.get("position"),
                    "duration_seconds": activity.get("duration"),
                    "volume": activity.get("volume"),
                    "current_command": activity.get("command"),
                    "current_action": activity.get("action"),
                    "last_updated": activity["timestamp"]
                }
                
            self._write_log(data)

media_logger = MediaActivityLogger()
