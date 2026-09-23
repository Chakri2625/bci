from datetime import datetime, timezone
import json
from pathlib import Path


LOG_FILE = Path("data/logs.json")


class RoutingEventLogger:
    def __init__(self):
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    def _write(self, event):
        logs = []

        if LOG_FILE.exists():
            try:
                logs = json.loads(LOG_FILE.read_text())
            except (json.JSONDecodeError, OSError):
                logs = []

        logs.append(event)
        LOG_FILE.write_text(json.dumps(logs, indent=2))

    def command_received(self, session_id, command):
        self._write({
            "event": "command_received",
            "session_id": session_id,
            "command": command,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    def command_routed(self, session_id, command, domain, plugin):
        self._write({
            "event": "command_routed",
            "session_id": session_id,
            "command": command,
            "domain": domain,
            "plugin": plugin,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })


logger = RoutingEventLogger()