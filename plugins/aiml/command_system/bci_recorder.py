"""BCI Recorder — saves raw BCI events without modification.

Additive observer that captures Cortex/mapped commands to JSON. Must NOT:
- deduplicate
- apply FSM logic
- modify command based on state
- interfere with live pipeline

Usage in app.py:
    recorder = BCIRecorder(base_dir=BASE_DIR/"bci_data"/"raw")
    # on cortex or /api/bci/command:
    if recorder.is_recording: recorder.record(command, confidence, timestamp, extra={})

Optional: auto-start via BCI_RECORDING env.
"""

import json
import time
import threading
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class BCIRecorder:
    def __init__(self, base_dir: Optional[Path] = None, auto_start: bool = False):
        self.base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent / "bci_data" / "raw"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._is_recording = False
        self._current_file: Optional[Path] = None
        self._events: list = []
        self._session_start_ts: Optional[str] = None
        if auto_start:
            try:
                self.start()
            except Exception as e:
                logger.warning(f"[RECORDER] auto_start failed: {e}")

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._is_recording

    def start(self, filename: Optional[str] = None) -> Path:
        """Start a new recording session. Returns Path of session file."""
        with self._lock:
            if self._is_recording:
                logger.info("[RECORDER] already recording, returning current file")
                return self._current_file
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            # also deterministic local timestamp for session id
            if filename:
                fname = filename if filename.endswith(".json") else filename + ".json"
                p = self.base_dir / fname
            else:
                p = self.base_dir / f"session_{ts}.json"
            # ensure not overwriting: add suffix if exists
            counter = 1
            orig = p
            while p.exists():
                p = orig.with_name(orig.stem + f"_{counter}" + orig.suffix)
                counter += 1
            self._current_file = p
            self._events = []
            self._session_start_ts = datetime.now(timezone.utc).isoformat()
            self._is_recording = True
            # create file immediately with empty list so UI sees it
            with open(p, "w") as f:
                json.dump([], f)
            logger.info(f"[RECORDER] Started session: {p}")
            return p

    def stop(self) -> Optional[Path]:
        """Stop recording, flush to file, return Path or None if not recording."""
        with self._lock:
            if not self._is_recording:
                return None
            p = self._current_file
            events = list(self._events)
            self._is_recording = False
        # write outside lock
        if p is not None:
            try:
                with open(p, "w") as f:
                    json.dump(events, f, indent=2)
                logger.info(f"[RECORDER] Stopped session: {p} ({len(events)} events)")
            except Exception as e:
                logger.error(f"[RECORDER] flush failed {p}: {e}")
        with self._lock:
            self._current_file = None
            self._events = []
            self._session_start_ts = None
        return p

    def record(self, command: str, confidence: float = 1.0, timestamp: Optional[Any] = None, extra: Optional[Dict[str, Any]] = None):
        """Append one raw event. Never deduplicates. Preserves exactly what arrived."""
        with self._lock:
            if not self._is_recording or self._current_file is None:
                return False
            # Normalize timestamp to ISO string preserving original if string, else generate
            if timestamp is None:
                ts_str = datetime.now(timezone.utc).isoformat()
            elif isinstance(timestamp, (int, float)):
                ts_str = datetime.fromtimestamp(float(timestamp), tz=timezone.utc).isoformat()
            elif isinstance(timestamp, str):
                ts_str = timestamp
            else:
                ts_str = str(timestamp)
            event: Dict[str, Any] = {
                "timestamp": ts_str,
                "command": str(command),
                "confidence": float(confidence),
            }
            # preserve extra fields where practical but do not overwrite core
            if extra:
                for k, v in extra.items():
                    if k not in event:
                        event[k] = v
            self._events.append(event)
            # incremental flush every event (simple, safe; small files)
            try:
                with open(self._current_file, "w") as f:
                    json.dump(self._events, f, indent=2)
            except Exception as e:
                logger.error(f"[RECORDER] write failed: {e}")
            logger.info(f"[RECORDER] captured {command} conf={confidence:.3f} ts={ts_str} -> {self._current_file.name} ({len(self._events)} events)")
            return True

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "is_recording": self._is_recording,
                "current_file": str(self._current_file) if self._current_file else None,
                "current_file_name": self._current_file.name if self._current_file else None,
                "event_count": len(self._events),
                "session_start": self._session_start_ts,
                "base_dir": str(self.base_dir),
            }

    def list_sessions(self):
        """List raw json files in base_dir."""
        try:
            files = sorted(self.base_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            return [p.name for p in files]
        except Exception:
            return []


# default instance for app.py to import quickly (lazy dir creation)
_default_recorder: Optional[BCIRecorder] = None

def get_recorder(base_dir: Optional[Path] = None, auto_start: bool = False) -> BCIRecorder:
    global _default_recorder
    if _default_recorder is None:
        _default_recorder = BCIRecorder(base_dir=base_dir, auto_start=auto_start)
    return _default_recorder
