"""
Terminal Execution Display & Timestamp Tracker (SynaptiMesh Core - Day 6 Member 5).
-------------------------------------------------------------------------------------
Displays a clean, human-readable terminal execution box whenever a command reaches
a terminal lifecycle state (COMPLETED, FAILED, CANCELLED, TIMEOUT), while continuing
to append structured execution logs to logs/execution.log.

Thread-safe, async-compatible, with duplicate output suppression.
"""

from __future__ import annotations

import datetime
import logging
import os
from pathlib import Path
import re
import sys
import textwrap
import threading
import time
from typing import Any, Dict, List, Optional, Union

# Configure logger for terminal display / execution logging
logger = logging.getLogger("execution_display")

# Ensure UTF-8 output encoding for Windows terminals
try:
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# De-duplication registry to prevent duplicate prints from multiple callbacks
_displayed_command_ids: set[str] = set()
_display_lock = threading.RLock()

# Log file paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PRIMARY_LOG_DIR = PROJECT_ROOT / "logs"
SECONDARY_LOG_DIR = PROJECT_ROOT / "data" / "logs"
EXECUTION_LOG_FILE = PRIMARY_LOG_DIR / "execution.log"


def format_time_hms_mmm(val: Union[float, int, str, datetime.datetime, None]) -> str:
    """
    Format a timestamp into HH:MM:SS.mmm format.
    Handles float timestamps, datetime objects, ISO-8601 strings, and pre-formatted strings.
    """
    if val is None:
        val = time.time()

    if isinstance(val, (int, float)):
        dt = datetime.datetime.fromtimestamp(val)
        millis = int((val % 1) * 1000)
        return dt.strftime("%H:%M:%S") + f".{millis:03d}"

    if isinstance(val, datetime.datetime):
        millis = int(val.microsecond / 1000)
        return val.strftime("%H:%M:%S") + f".{millis:03d}"

    if isinstance(val, str):
        val = val.strip()
        # Already formatted as HH:MM:SS.mmm
        if re.match(r"^\d{2}:\d{2}:\d{2}\.\d{3}$", val):
            return val

        # Try parsing ISO-8601 format
        try:
            # Handle trailing 'Z'
            iso_str = val.replace("Z", "+00:00") if val.endswith("Z") else val
            dt = datetime.datetime.fromisoformat(iso_str)
            millis = int(dt.microsecond / 1000)
            return dt.strftime("%H:%M:%S") + f".{millis:03d}"
        except Exception:
            pass

        # Try float conversion
        try:
            f = float(val)
            dt = datetime.datetime.fromtimestamp(f)
            millis = int((f % 1) * 1000)
            return dt.strftime("%H:%M:%S") + f".{millis:03d}"
        except Exception:
            return val

    return str(val)


class TimestampTracker:
    """
    Tracks execution timestamps and durations for a command.
    Generates exact HH:MM:SS.mmm formatted strings and calculated duration.
    """

    def __init__(self, command_id: Optional[str] = None, session_id: Optional[str] = None):
        self.command_id = command_id
        self.session_id = session_id or "default"
        self.start_time: Optional[float] = None
        self.completion_time: Optional[float] = None
        self.duration_seconds: Optional[float] = None
        self.status: str = "QUEUED"
        self.error: Optional[str] = None
        self._attempts: Dict[int, Dict[str, Any]] = {}

    def record_start(self, *args, **kwargs) -> float:
        """Record the start timestamp for execution."""
        attempt = kwargs.get("attempt", 1)
        st = kwargs.get("start_time")
        cid = kwargs.get("command_id")
        sid = kwargs.get("session_id")

        for arg in args:
            if isinstance(arg, (int, float)):
                st = float(arg)
            elif isinstance(arg, str):
                if not self.command_id or self.command_id.startswith("CMD-"):
                    self.command_id = arg
                elif not self.session_id or self.session_id == "default":
                    self.session_id = arg

        if cid:
            self.command_id = cid
        if sid:
            self.session_id = sid

        actual_st = float(st) if st is not None else time.time()
        if self.start_time is None:
            self.start_time = actual_st

        if attempt not in self._attempts:
            self._attempts[attempt] = {}
        self._attempts[attempt]["start_time"] = actual_st
        self._attempts[attempt]["status"] = "RUNNING"
        return actual_st

    def record_completion(self, *args, **kwargs) -> float:
        """Record completion timestamp and calculate duration."""
        attempt = kwargs.get("attempt", 1)
        ct = kwargs.get("completion_time")
        status = kwargs.get("status", "COMPLETED")
        err = kwargs.get("error")

        for arg in args:
            if isinstance(arg, (int, float)):
                ct = float(arg)
            elif isinstance(arg, str):
                if arg.upper() in ("COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"):
                    status = arg.upper()

        actual_ct = float(ct) if ct is not None else time.time()
        self.completion_time = actual_ct
        self.status = status
        self.error = err

        if self.start_time is not None:
            self.duration_seconds = max(0.0, round(self.completion_time - self.start_time, 3))
        else:
            self.duration_seconds = 0.0

        if attempt not in self._attempts:
            self._attempts[attempt] = {"start_time": self.start_time or actual_ct}
        self._attempts[attempt]["completion_time"] = actual_ct
        self._attempts[attempt]["status"] = status
        self._attempts[attempt]["error"] = err
        st_att = self._attempts[attempt].get("start_time", self.start_time or actual_ct)
        self._attempts[attempt]["duration"] = max(0.0, round(actual_ct - st_att, 3))

        return actual_ct

    def calculate_duration(self, *args, **kwargs) -> float:
        """Calculate and return duration in seconds."""
        attempt = kwargs.get("attempt", 1)
        for arg in args:
            if isinstance(arg, int):
                attempt = arg

        if attempt in self._attempts:
            att = self._attempts[attempt]
            if "completion_time" in att and "start_time" in att:
                return max(0.0, round(att["completion_time"] - att["start_time"], 3))

        if self.start_time is not None and self.completion_time is not None:
            self.duration_seconds = max(0.0, round(self.completion_time - self.start_time, 3))
            return self.duration_seconds
        return self.duration_seconds or 0.0

    def get_execution_details(self, *args, **kwargs) -> Optional[Dict[str, Any]]:
        """Retrieve execution details for a command or specific attempt."""
        attempt = kwargs.get("attempt", 1)
        for arg in args:
            if isinstance(arg, int):
                attempt = arg

        if attempt in self._attempts:
            att = self._attempts[attempt]
            return {
                "command_id": self.command_id,
                "session_id": self.session_id,
                "start_time": att.get("start_time", self.start_time),
                "completion_time": att.get("completion_time", self.completion_time),
                "duration_seconds": att.get("duration", self.duration_seconds),
                "status": att.get("status", self.status),
                "error": att.get("error", self.error),
            }

        return {
            "command_id": self.command_id,
            "session_id": self.session_id,
            "start_time": self.start_time,
            "completion_time": self.completion_time,
            "duration_seconds": self.duration_seconds,
            "status": self.status,
            "error": self.error,
        }

    @property
    def start_str(self) -> str:
        return format_time_hms_mmm(self.start_time)

    @property
    def completion_str(self) -> str:
        return format_time_hms_mmm(self.completion_time)

    @property
    def duration_str(self) -> str:
        sec = self.duration_seconds if self.duration_seconds is not None else 0.0
        return f"{sec:.3f} seconds"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command_id": self.command_id,
            "start_time": self.start_time,
            "completion_time": self.completion_time,
            "duration_seconds": self.duration_seconds,
            "start_str": self.start_str,
            "completion_str": self.completion_str,
            "duration_str": self.duration_str,
        }


def _normalize_execution_data(execution_data: Any, **kwargs) -> Dict[str, Any]:
    """
    Extract normalized dictionary from CommandLifecycleRecord, dict, or kwargs.
    """
    data: Dict[str, Any] = {}

    if execution_data is not None:
        if hasattr(execution_data, "to_dict"):
            data = execution_data.to_dict()
            # Also attach internal attributes if available
            if hasattr(execution_data, "command_id"):
                data["command_id"] = execution_data.command_id
            if hasattr(execution_data, "session_id"):
                data["session_id"] = execution_data.session_id
            if hasattr(execution_data, "command"):
                data["command"] = execution_data.command
            if hasattr(execution_data, "current_stage"):
                stage_val = getattr(execution_data.current_stage, "value", str(execution_data.current_stage))
                data["status"] = stage_val
            if hasattr(execution_data, "started_at"):
                data["started_at"] = execution_data.started_at
            if hasattr(execution_data, "completed_at"):
                data["completed_at"] = execution_data.completed_at
            if hasattr(execution_data, "duration_ms"):
                data["duration_ms"] = execution_data.duration_ms
            if hasattr(execution_data, "error"):
                data["error"] = execution_data.error
            if hasattr(execution_data, "timestamp_tracker"):
                data["timestamp_tracker"] = execution_data.timestamp_tracker
        elif isinstance(execution_data, dict):
            data = dict(execution_data)
        else:
            data = {"command": str(execution_data)}

    # Apply kwargs overrides
    data.update(kwargs)

    # Normalize fields
    command = data.get("command") or data.get("command_name") or data.get("action") or "UNKNOWN"
    command_id = data.get("command_id") or data.get("cid") or "CMD-000"
    session_id = data.get("session_id") or data.get("session") or "SESSION-001"

    raw_status = str(data.get("status") or data.get("current_stage") or "COMPLETED").upper()
    if raw_status in ("SUCCESS", "COMPLETED", "EXECUTION_COMPLETED", "OK"):
        status = "COMPLETED"
    elif raw_status in ("FAILED", "FAILURE", "ERROR", "VALIDATION_FAILED"):
        status = "FAILED"
    elif raw_status in ("CANCELLED", "CANCELED"):
        status = "CANCELLED"
    elif raw_status == "TIMEOUT":
        status = "TIMEOUT"
    else:
        status = raw_status

    tracker = data.get("timestamp_tracker")
    start_val = data.get("start") or data.get("start_time") or data.get("started_at")
    comp_val = data.get("completion") or data.get("completion_time") or data.get("completed_at")

    if tracker and isinstance(tracker, TimestampTracker):
        start_str = tracker.start_str
        comp_str = tracker.completion_str
        duration_str = tracker.duration_str
        duration_sec = tracker.duration_seconds or 0.0
    else:
        # Fallback to created_at if start is missing
        if start_val is None:
            start_val = data.get("created_at") or time.time()
        if comp_val is None:
            comp_val = time.time()

        start_str = format_time_hms_mmm(start_val)
        comp_str = format_time_hms_mmm(comp_val)

        # Duration
        if "duration" in data and isinstance(data["duration"], (int, float)):
            duration_sec = float(data["duration"])
        elif "duration_seconds" in data and isinstance(data["duration_seconds"], (int, float)):
            duration_sec = float(data["duration_seconds"])
        elif "duration_ms" in data and data["duration_ms"] is not None:
            duration_sec = float(data["duration_ms"]) / 1000.0
        elif isinstance(start_val, (int, float)) and isinstance(comp_val, (int, float)):
            duration_sec = max(0.0, comp_val - start_val)
        else:
            duration_sec = 0.0

        duration_str = f"{duration_sec:.3f} seconds"

    error = data.get("error") or data.get("error_message") or data.get("rejection_reason")

    return {
        "command": command,
        "command_id": command_id,
        "session_id": session_id,
        "status": status,
        "start": start_str,
        "completion": comp_str,
        "duration": duration_str,
        "duration_seconds": duration_sec,
        "error": error,
        "raw": data,
    }


def _format_box_row(label: str, value: str, max_inner_width: int = 55) -> List[str]:
    """
    Format a labeled row within the fixed 55-character content width.
    If value overflows, wrap cleanly with indent without breaking the box borders.
    """
    full_text = f"{label}: {value}"
    if len(full_text) <= max_inner_width:
        return [f"│ {full_text.ljust(max_inner_width)} │"]

    # Wrap overflowing content cleanly
    indent = " " * (len(label) + 2)
    subsequent = indent if len(indent) <= 15 else "  "
    wrapped = textwrap.wrap(full_text, width=max_inner_width, subsequent_indent=subsequent)
    return [f"│ {line.ljust(max_inner_width)} │" for line in wrapped]


def format_execution_box(execution_data: Any = None, **kwargs) -> str:
    """
    Generate the formatted terminal execution summary box.

    Style:
    ┌─────────────────────────────────────────────────────────┐
    │ Command: open_notepad                                   │
    │ Command ID: CMD-001                                     │
    │ Session ID: SESSION-001                                 │
    │ Status: COMPLETED                                       │
    │ Start: 11:30:10.125                                     │
    │ Completion: 11:30:12.430                                │
    │ Duration: 2.305 seconds                                 │
    └─────────────────────────────────────────────────────────┘
    """
    norm = _normalize_execution_data(execution_data, **kwargs)

    top_border = "┌" + "─" * 57 + "┐"
    bot_border = "└" + "─" * 57 + "┘"

    rows: List[str] = [top_border]
    rows.extend(_format_box_row("Command", str(norm["command"])))
    rows.extend(_format_box_row("Command ID", str(norm["command_id"])))
    rows.extend(_format_box_row("Session ID", str(norm["session_id"])))
    rows.extend(_format_box_row("Status", str(norm["status"])))
    rows.extend(_format_box_row("Start", str(norm["start"])))
    rows.extend(_format_box_row("Completion", str(norm["completion"])))
    rows.extend(_format_box_row("Duration", str(norm["duration"])))

    # Display error line for failures or if error is explicitly present
    if norm["status"] == "FAILED" or norm["error"]:
        err_msg = str(norm["error"]) if norm["error"] else "Execution failed"
        rows.extend(_format_box_row("Error", err_msg))

    rows.append(bot_border)
    return "\n".join(rows)


def write_execution_log(norm_data: Dict[str, Any], log_path: Optional[Path] = None) -> None:
    """
    Write structured execution summary to the execution log file.
    Does NOT replace existing logging; writes concurrently to execution.log.
    """
    target_files = [EXECUTION_LOG_FILE, SECONDARY_LOG_DIR / "execution.log"]
    if log_path:
        target_files.insert(0, Path(log_path))

    timestamp_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
    err_part = f' | Error="{norm_data["error"]}"' if norm_data.get("error") else ""
    log_line = (
        f"{timestamp_iso} - EXECUTION - INFO - "
        f"Command={norm_data['command']} | "
        f"CommandID={norm_data['command_id']} | "
        f"SessionID={norm_data['session_id']} | "
        f"Status={norm_data['status']} | "
        f"Start={norm_data['start']} | "
        f"Completion={norm_data['completion']} | "
        f"Duration={norm_data['duration']}{err_part}\n"
    )

    for target in target_files:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "a", encoding="utf-8") as f:
                f.write(log_line)
        except Exception as e:
            logger.warning(f"Could not append to execution log at {target}: {e}")


def display_execution_summary(
    execution_data: Any = None,
    force: bool = False,
    stream: Optional[Any] = None,
    **kwargs,
) -> str:
    """
    Display the formatted execution summary box directly in the terminal/console
    and append to execution.log.

    Guarantees no duplicate output per command_id unless force=True.
    Thread-safe and async-compatible.
    """
    norm = _normalize_execution_data(execution_data, **kwargs)
    cid = norm.get("command_id")

    with _display_lock:
        # Check de-duplication registry
        if cid and not force:
            if cid in _displayed_command_ids:
                return ""  # Suppress duplicate display
            _displayed_command_ids.add(cid)

        # If execution_data is a CommandLifecycleRecord, mark it as displayed
        if execution_data is not None and hasattr(execution_data, "_terminal_summary_displayed"):
            if not force and getattr(execution_data, "_terminal_summary_displayed", False):
                return ""
            execution_data._terminal_summary_displayed = True

        box_str = format_execution_box(execution_data=norm)

        # Write to execution.log
        write_execution_log(norm)

        # Print to terminal / stream
        out_stream = stream or sys.stdout
        try:
            out_stream.write(box_str + "\n")
            out_stream.flush()
        except UnicodeEncodeError:
            try:
                # Windows terminal fallback for legacy code pages
                if hasattr(out_stream, "buffer"):
                    out_stream.buffer.write((box_str + "\n").encode("utf-8", errors="replace"))
                    out_stream.buffer.flush()
                else:
                    ascii_box = box_str.translate(str.maketrans("┌┐└┘─│", "++++-|"))
                    out_stream.write(ascii_box + "\n")
                    out_stream.flush()
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"Terminal display output warning: {e}")

        return box_str


def reset_displayed_commands() -> None:
    """Clear displayed command IDs cache (useful for test isolation)."""
    with _display_lock:
        _displayed_command_ids.clear()


def is_command_displayed(command_id: str) -> bool:
    """Check whether a command has already had its terminal summary displayed."""
    with _display_lock:
        return command_id in _displayed_command_ids


def format_utc_iso(timestamp: Optional[float] = None) -> str:
    """Format timestamp as ISO-8601 UTC string."""
    ts = timestamp if timestamp is not None else time.time()
    dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def log_execution_event(event_type: str, details: Optional[Dict[str, Any]] = None, **kwargs) -> None:
    """Log an execution event."""
    data = dict(details or {})
    data.update(kwargs)
    logger.info(f"[{event_type}] {data}")


def display_command_received(command_id: str, command: str, **kwargs) -> None:
    """Display command received banner."""
    logger.info(f"Received command: {command} (ID: {command_id})")


def display_execution_running(command_id: str, command: str, **kwargs) -> None:
    """Display command execution running banner."""
    logger.info(f"Executing command: {command} (ID: {command_id})")


def display_retry_started(command_id: str, attempt: int, max_retries: int, delay: float, **kwargs) -> None:
    """Display retry started notification."""
    logger.info(f"Retrying command {command_id} (Attempt {attempt}/{max_retries}) after {delay}s delay")


def display_command_timeout(command_id: str, timeout: float, **kwargs) -> None:
    """Display command timeout alert."""
    logger.warning(f"Command {command_id} timed out after {timeout}s")


def display_success_summary(execution_data: Any = None, **kwargs) -> str:
    """Display success execution box."""
    return display_execution_summary(execution_data, **kwargs)


def display_failure_summary(execution_data: Any = None, **kwargs) -> str:
    """Display failure execution box."""
    return display_execution_summary(execution_data, **kwargs)


def display_final_execution_summary(execution_data: Any = None, **kwargs) -> str:
    """Display final execution summary box."""
    return display_execution_summary(execution_data, **kwargs)
