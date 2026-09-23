"""Persistent SynaptiMesh Robot Car command logger: JSON + CSV + TXT."""
from __future__ import annotations
import csv, json, os, tempfile, threading, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

class CommandLogger:
    CSV_FIELDS = [
        "id", "timestamp_utc", "timestamp_unix_ms", "source", "category",
        "command", "transport", "success", "latency_ms", "topic", "endpoint",
        "error", "details"
    ]

    def __init__(self, log_dir: Optional[str] = None):
        self.log_dir = Path(log_dir or os.getenv(
            "COMMAND_LOG_DIR",
            str(Path(__file__).resolve().parent / "logs")
        ))
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.json_path = self.log_dir / "command_log.json"
        self.csv_path = self.log_dir / "command_log.csv"
        self.txt_path = self.log_dir / "command_log.txt"
        self._lock = threading.Lock()
        self._ensure_files()

    def _ensure_files(self):
        with self._lock:
            if not self.json_path.exists():
                self.json_path.write_text("[]\n", encoding="utf-8")
            if not self.csv_path.exists():
                with self.csv_path.open("w", newline="", encoding="utf-8") as f:
                    csv.DictWriter(f, fieldnames=self.CSV_FIELDS).writeheader()
            if not self.txt_path.exists():
                self.txt_path.write_text(
                    "SynaptiMesh Robot Car Command Log\n"
                    "================================\n", encoding="utf-8"
                )

    @staticmethod
    def _json_safe(value: Any):
        try:
            json.dumps(value)
            return value
        except TypeError:
            return str(value)

    def log(
        self,
        command: str,
        source: str,
        result: Optional[Dict[str, Any]] = None,
        category: str = "ROBOT_CAR",
        **metadata
    ) -> Dict[str, Any]:
        result = result or {}
        now = datetime.now(timezone.utc)
        timestamp_ms = int(now.timestamp() * 1000)
        success = bool(result.get("success", False))
        latency = result.get("latency")
        event = {
            "id": str(uuid.uuid4()),
            "timestamp_utc": now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "timestamp_unix_ms": timestamp_ms,
            "source": str(source),
            "category": str(category),
            "command": str(command).strip().upper(),
            "transport": str(result.get("mode") or metadata.get("transport") or ""),
            "success": success,
            "latency_ms": latency,
            "topic": str(result.get("topic") or metadata.get("topic") or ""),
            "endpoint": str(result.get("url") or metadata.get("endpoint") or ""),
            "error": str(result.get("error") or ""),
            "details": {
                "result": self._json_safe(result),
                "metadata": self._json_safe(metadata),
            },
        }

        route = event["topic"] or event["endpoint"] or "-"
        latency_text = f'{latency} ms' if latency is not None else "-"
        status = "SUCCESS" if success else "FAILED"
        line = (
            f'[{event["timestamp_utc"]}] [{status}] '
            f'SOURCE={event["source"]} COMMAND={event["command"]} '
            f'TRANSPORT={event["transport"] or "-"} ROUTE={route} '
            f'LATENCY={latency_text}'
        )
        if event["error"]:
            line += f' ERROR={event["error"]}'
        line += "\n"

        with self._lock:
            try:
                data = json.loads(self.json_path.read_text(encoding="utf-8") or "[]")
                if not isinstance(data, list):
                    data = []
            except (OSError, json.JSONDecodeError):
                data = []
            data.append(event)

            fd, tmp = tempfile.mkstemp(
                prefix="command_log_", suffix=".tmp", dir=str(self.log_dir)
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    f.write("\n")
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self.json_path)
            finally:
                try: os.remove(tmp)
                except FileNotFoundError: pass

            with self.csv_path.open("a", newline="", encoding="utf-8") as f:
                row = dict(event)
                row["details"] = json.dumps(event["details"], ensure_ascii=False)
                csv.DictWriter(f, fieldnames=self.CSV_FIELDS).writerow(row)

            with self.txt_path.open("a", encoding="utf-8") as f:
                f.write(line)

        return event

    def log_dashboard_action(self, command: str, source: str, **metadata):
        return self.log(command, source, {"success": True}, "DASHBOARD", **metadata)
