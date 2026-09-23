"""
core/logging/timestamp_tracker.py
---------------------------------
Execution Timestamp Tracking and Audit Logging (Day 6 - Member 5).

Captures exact execution start time, completion time, duration, status, errors,
command_id, and session_id for every command executed across SynaptiMesh.
Provides thread-safe and async-safe tracking, deduplicated ISO 8601 UTC logging,
and fail-safe error isolation so execution is never disrupted.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("synaptimesh.timestamp_tracker")

# Standard execution log file path (relative to project root or workspace)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_LOG_FILE = os.path.join(_PROJECT_ROOT, "logs", "execution.log")


def get_utc_now() -> tuple[datetime, str]:
    """
    Return current timezone-aware UTC datetime and formatted ISO 8601 string.
    Example: (datetime_obj, '2026-09-07T11:30:10.125Z')
    """
    now = datetime.now(timezone.utc)
    iso_str = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return now, iso_str


def parse_iso_utc(iso_str: str) -> Optional[datetime]:
    """Parse ISO 8601 UTC string back into timezone-aware datetime."""
    if not iso_str:
        return None
    try:
        clean = iso_str.rstrip("Z")
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def format_terminal_time(time_val: Any) -> str:
    """
    Format timestamp to HH:MM:SS.mmm for terminal display.
    Example: '2026-09-07T11:30:10.125Z' -> '11:30:10.125'
    """
    if not time_val:
        return "N/A"
    try:
        if isinstance(time_val, datetime):
            return time_val.strftime("%H:%M:%S.%f")[:-3]
        if isinstance(time_val, str):
            clean = time_val.strip()
            if "T" in clean:
                clean = clean.split("T")[1]
            clean = clean.rstrip("Z")
            if "+" in clean:
                clean = clean.split("+")[0]
            if "." in clean:
                parts = clean.split(".")
                time_part = parts[0]
                ms_part = parts[1][:3].ljust(3, "0")
                return f"{time_part}.{ms_part}"
            elif ":" in clean:
                return f"{clean}.000"
    except Exception:
        pass
    return str(time_val)


def _safe_print(text: str) -> None:
    """Safely print unicode text to stdout across various terminal encodings."""
    try:
        print(text)
    except UnicodeEncodeError:
        if hasattr(sys.stdout, "buffer") and sys.stdout.buffer:
            sys.stdout.buffer.write((text + "\n").encode("utf-8", errors="replace"))
            sys.stdout.buffer.flush()
        else:
            ascii_fallback = (
                text.replace("┌", "+")
                .replace("┐", "+")
                .replace("└", "+")
                .replace("┘", "+")
                .replace("─", "-")
                .replace("│", "|")
            )
            print(ascii_fallback)


def display_execution_summary(execution_data: Any) -> str:
    """
    Display a formatted execution summary box directly in the console.
    Guarantees fixed box width (59 chars) and aligns all fields cleanly.
    """
    try:
        if hasattr(execution_data, "to_dict"):
            data = execution_data.to_dict()
        elif isinstance(execution_data, dict):
            data = dict(execution_data)
        else:
            data = {}

        cmd = str(data.get("command") or "unknown")
        cid = str(data.get("command_id") or "unknown")
        sid = str(data.get("session_id") or "default")
        status = str(data.get("status") or "COMPLETED").upper()
        start_time = format_terminal_time(data.get("start_time"))
        comp_time = format_terminal_time(data.get("completion_time"))

        dur = data.get("duration_seconds")
        if dur is not None and isinstance(dur, (int, float)):
            dur_str = f"{float(dur):.3f} seconds"
        elif dur is not None:
            dur_str = f"{dur} seconds"
        else:
            dur_str = "0.000 seconds"

        error = data.get("error")

        box_width = 57  # inner horizontal dashes
        content_width = 55  # characters inside borders: "│ " + 55 + " │"

        lines = [f"┌{'─' * box_width}┐"]

        fields = [
            ("Command", cmd),
            ("Command ID", cid),
            ("Session ID", sid),
            ("Status", status),
            ("Start", start_time),
            ("Completion", comp_time),
            ("Duration", dur_str),
        ]
        if status == "FAILED":
            fields.append(("Error", str(error) if error else "Execution failed"))
        elif error and status not in ("CANCELLED", "COMPLETED"):
            fields.append(("Error", str(error)))


        for label, val in fields:
            prefix = f"{label}: "
            val_str = str(val)
            available = content_width - len(prefix)

            if len(val_str) <= available:
                line_content = f"{prefix}{val_str}"
                lines.append(f"│ {line_content:<{content_width}} │")
            else:
                import textwrap
                wrapped = textwrap.wrap(val_str, width=available)
                for idx, chunk in enumerate(wrapped):
                    if idx == 0:
                        sub = f"{prefix}{chunk}"
                    else:
                        indent = " " * len(prefix)
                        sub = f"{indent}{chunk}"
                    lines.append(f"│ {sub:<{content_width}} │")

        lines.append(f"└{'─' * box_width}┘")
        box_str = "\n".join(lines)
        _safe_print(box_str)
        return box_str
    except Exception as e:
        logger.error(f"[TimestampTracker] Error displaying execution summary box: {e}")
        return ""




@dataclass
class ExecutionRecord:
    """
    Data model representing execution state and timing for a command.
    """
    command_id: str
    session_id: str = "default"
    command: str = "unknown"
    status: str = "QUEUED"  # QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED
    start_time: Optional[str] = None
    completion_time: Optional[str] = None
    duration_seconds: Optional[float] = None
    error: Optional[str] = None
    
    # Internal management fields (not exposed in simple dicts)
    _start_dt: Optional[datetime] = field(default=None, repr=False)
    _completion_dt: Optional[datetime] = field(default=None, repr=False)
    _started_logged: bool = field(default=False, repr=False)
    _finished_logged: bool = field(default=False, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        """Convert record to the standardized external dictionary format."""
        return {
            "command_id": self.command_id,
            "session_id": self.session_id,
            "command": self.command,
            "status": self.status,
            "start_time": self.start_time,
            "completion_time": self.completion_time,
            "duration_seconds": self.duration_seconds,
            "error": self.error,
        }


class TimestampTracker:
    """
    Thread-safe and async-safe execution timestamp tracker and audit logger.
    Tracks command lifecycle events, calculates durations, and writes structured audit logs.
    """

    def __init__(self, log_file_path: Optional[str] = None, enable_terminal_display: bool = True):
        self._lock = threading.RLock()
        self._records: Dict[str, ExecutionRecord] = {}
        self._history: List[ExecutionRecord] = []
        self._max_history: int = 500
        self._log_file = log_file_path or DEFAULT_LOG_FILE
        self._file_logger: Optional[logging.Logger] = None
        self._enable_terminal_display: bool = enable_terminal_display
        self._init_logger()


    def _init_logger(self) -> None:
        """Initialize dedicated file handler for audit logs."""
        try:
            log_dir = os.path.dirname(os.path.abspath(self._log_file))
            os.makedirs(log_dir, exist_ok=True)

            audit_logger = logging.getLogger("synaptimesh.audit.execution")
            audit_logger.setLevel(logging.INFO)
            audit_logger.propagate = False  # Avoid duplicate console noise unless configured

            # Check if handler already attached to avoid duplicates
            handler_exists = any(
                isinstance(h, logging.FileHandler) and os.path.abspath(h.baseFilename) == os.path.abspath(self._log_file)
                for h in audit_logger.handlers
            )

            if not handler_exists:
                file_handler = logging.FileHandler(self._log_file, encoding="utf-8")
                file_handler.setLevel(logging.INFO)
                file_handler.setFormatter(logging.Formatter("%(message)s"))
                audit_logger.addHandler(file_handler)

            self._file_logger = audit_logger
        except Exception as e:
            logger.error(f"[TimestampTracker] Failed to initialize audit file handler at {self._log_file}: {e}")

    def _write_log(self, message: str) -> None:
        """Safely write formatted line to audit log file and fallback logger."""
        try:
            if self._file_logger:
                self._file_logger.info(message)
            else:
                # Direct file append fallback if logger failed
                log_dir = os.path.dirname(os.path.abspath(self._log_file))
                os.makedirs(log_dir, exist_ok=True)
                with open(self._log_file, "a", encoding="utf-8") as f:
                    f.write(message + "\n")
        except Exception as e:
            logger.error(f"[TimestampTracker] Error writing to audit log: {e}")

    def record_queued(
        self,
        command_id: str,
        session_id: Optional[str] = None,
        command: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record when a command is queued before execution begins."""
        try:
            with self._lock:
                rec = self._records.get(command_id)
                if not rec:
                    rec = ExecutionRecord(
                        command_id=command_id,
                        session_id=session_id or "default",
                        command=command or "unknown",
                        status="QUEUED",
                    )
                    self._records[command_id] = rec
                else:
                    if session_id:
                        rec.session_id = session_id
                    if command:
                        rec.command = command
                    if rec.status == "QUEUED":
                        rec.status = "QUEUED"
                return rec.to_dict()
        except Exception as e:
            logger.error(f"[TimestampTracker] record_queued error for {command_id}: {e}")
            return {
                "command_id": command_id,
                "session_id": session_id or "default",
                "command": command or "unknown",
                "status": "QUEUED",
                "start_time": None,
                "completion_time": None,
                "duration_seconds": None,
                "error": None,
            }

    def record_start(
        self,
        command_id: str,
        session_id: Optional[str] = None,
        command: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Record when a command enters the RUNNING/EXECUTING state.
        Captures start timestamp, writes COMMAND_STARTED log entry (deduplicated).
        """
        try:
            with self._lock:
                start_dt, start_iso = get_utc_now()
                rec = self._records.get(command_id)

                if not rec:
                    rec = ExecutionRecord(
                        command_id=command_id,
                        session_id=session_id or "default",
                        command=command or "unknown",
                        status="RUNNING",
                        start_time=start_iso,
                        _start_dt=start_dt,
                    )
                    self._records[command_id] = rec
                else:
                    rec.status = "RUNNING"
                    if session_id:
                        rec.session_id = session_id
                    if command:
                        rec.command = command
                    if not rec.start_time:
                        rec.start_time = start_iso
                        rec._start_dt = start_dt

                # Deduplicated log emission
                if not rec._started_logged:
                    log_entry = (
                        f"[{rec.start_time}] COMMAND_STARTED | "
                        f"command_id={rec.command_id} | "
                        f"session_id={rec.session_id} | "
                        f"command={rec.command}"
                    )
                    self._write_log(log_entry)
                    rec._started_logged = True

                return rec.to_dict()
        except Exception as e:
            logger.error(f"[TimestampTracker] record_start error for {command_id}: {e}")
            return {
                "command_id": command_id,
                "session_id": session_id or "default",
                "command": command or "unknown",
                "status": "RUNNING",
                "start_time": None,
                "completion_time": None,
                "duration_seconds": None,
                "error": None,
            }

    def record_completion(
        self,
        command_id: str,
        session_id: Optional[str] = None,
        command: Optional[str] = None,
        status: str = "COMPLETED",
        result: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Record when a command finishes execution successfully.
        Captures completion timestamp, calculates duration, and writes COMMAND_COMPLETED log.
        """
        try:
            with self._lock:
                comp_dt, comp_iso = get_utc_now()
                rec = self._records.get(command_id)

                if not rec:
                    rec = ExecutionRecord(
                        command_id=command_id,
                        session_id=session_id or "default",
                        command=command or "unknown",
                        status=status,
                        start_time=comp_iso,
                        _start_dt=comp_dt,
                        completion_time=comp_iso,
                        _completion_dt=comp_dt,
                        duration_seconds=0.0,
                    )
                    self._records[command_id] = rec
                else:
                    rec.status = status
                    if session_id:
                        rec.session_id = session_id
                    if command:
                        rec.command = command
                    rec.completion_time = comp_iso
                    rec._completion_dt = comp_dt

                    # Calculate duration
                    if rec._start_dt:
                        diff = (comp_dt - rec._start_dt).total_seconds()
                        rec.duration_seconds = max(0.0, round(diff, 3))
                    elif rec.start_time:
                        sdt = parse_iso_utc(rec.start_time)
                        if sdt:
                            diff = (comp_dt - sdt).total_seconds()
                            rec.duration_seconds = max(0.0, round(diff, 3))
                        else:
                            rec.duration_seconds = 0.0
                    else:
                        rec.start_time = comp_iso
                        rec._start_dt = comp_dt
                        rec.duration_seconds = 0.0

                # Deduplicated final log emission
                if not rec._finished_logged:
                    duration_str = f"{rec.duration_seconds:.3f}s" if rec.duration_seconds is not None else "0.000s"
                    log_entry = (
                        f"[{rec.completion_time}] COMMAND_COMPLETED | "
                        f"command_id={rec.command_id} | "
                        f"session_id={rec.session_id} | "
                        f"command={rec.command} | "
                        f"duration={duration_str} | "
                        f"status={rec.status}"
                    )
                    self._write_log(log_entry)
                    if self._enable_terminal_display:
                        display_execution_summary(rec)
                    rec._finished_logged = True


                self._record_to_history(rec)
                return rec.to_dict()
        except Exception as e:
            logger.error(f"[TimestampTracker] record_completion error for {command_id}: {e}")
            return {
                "command_id": command_id,
                "session_id": session_id or "default",
                "command": command or "unknown",
                "status": status,
                "start_time": None,
                "completion_time": None,
                "duration_seconds": 0.0,
                "error": None,
            }

    def record_failure(
        self,
        command_id: str,
        session_id: Optional[str] = None,
        command: Optional[str] = None,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Record when command execution fails.
        Captures completion/end timestamp, calculates duration, records error message,
        and writes COMMAND_FAILED log.
        """
        try:
            with self._lock:
                comp_dt, comp_iso = get_utc_now()
                rec = self._records.get(command_id)
                err_msg = str(error) if error is not None else "Unknown error"

                if not rec:
                    rec = ExecutionRecord(
                        command_id=command_id,
                        session_id=session_id or "default",
                        command=command or "unknown",
                        status="FAILED",
                        start_time=comp_iso,
                        _start_dt=comp_dt,
                        completion_time=comp_iso,
                        _completion_dt=comp_dt,
                        duration_seconds=0.0,
                        error=err_msg,
                    )
                    self._records[command_id] = rec
                else:
                    rec.status = "FAILED"
                    rec.error = err_msg
                    if session_id:
                        rec.session_id = session_id
                    if command:
                        rec.command = command
                    rec.completion_time = comp_iso
                    rec._completion_dt = comp_dt

                    # Calculate duration
                    if rec._start_dt:
                        diff = (comp_dt - rec._start_dt).total_seconds()
                        rec.duration_seconds = max(0.0, round(diff, 3))
                    elif rec.start_time:
                        sdt = parse_iso_utc(rec.start_time)
                        if sdt:
                            diff = (comp_dt - sdt).total_seconds()
                            rec.duration_seconds = max(0.0, round(diff, 3))
                        else:
                            rec.duration_seconds = 0.0
                    else:
                        rec.start_time = comp_iso
                        rec._start_dt = comp_dt
                        rec.duration_seconds = 0.0

                # Deduplicated failure log emission
                if not rec._finished_logged:
                    duration_str = f"{rec.duration_seconds:.3f}s" if rec.duration_seconds is not None else "0.000s"
                    log_entry = (
                        f"[{rec.completion_time}] COMMAND_FAILED | "
                        f"command_id={rec.command_id} | "
                        f"session_id={rec.session_id} | "
                        f"command={rec.command} | "
                        f"duration={duration_str} | "
                        f"status=FAILED | "
                        f"error={rec.error}"
                    )
                    self._write_log(log_entry)
                    if self._enable_terminal_display:
                        display_execution_summary(rec)
                    rec._finished_logged = True

                self._record_to_history(rec)
                return rec.to_dict()
        except Exception as e:
            logger.error(f"[TimestampTracker] record_failure error for {command_id}: {e}")
            return {
                "command_id": command_id,
                "session_id": session_id or "default",
                "command": command or "unknown",
                "status": "FAILED",
                "start_time": None,
                "completion_time": None,
                "duration_seconds": 0.0,
                "error": str(error),
            }

    def record_cancel(
        self,
        command_id: str,
        session_id: Optional[str] = None,
        command: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Record when a command is cancelled.
        Captures cancellation timestamp, calculates duration, and writes COMMAND_CANCELLED log.
        """
        try:
            with self._lock:
                comp_dt, comp_iso = get_utc_now()
                rec = self._records.get(command_id)
                cancel_reason = reason or "Command was cancelled"

                if not rec:
                    rec = ExecutionRecord(
                        command_id=command_id,
                        session_id=session_id or "default",
                        command=command or "unknown",
                        status="CANCELLED",
                        start_time=comp_iso,
                        _start_dt=comp_dt,
                        completion_time=comp_iso,
                        _completion_dt=comp_dt,
                        duration_seconds=0.0,
                        error=cancel_reason,
                    )
                    self._records[command_id] = rec
                else:
                    rec.status = "CANCELLED"
                    rec.error = cancel_reason
                    if session_id:
                        rec.session_id = session_id
                    if command:
                        rec.command = command
                    rec.completion_time = comp_iso
                    rec._completion_dt = comp_dt

                    # Calculate duration
                    if rec._start_dt:
                        diff = (comp_dt - rec._start_dt).total_seconds()
                        rec.duration_seconds = max(0.0, round(diff, 3))
                    elif rec.start_time:
                        sdt = parse_iso_utc(rec.start_time)
                        if sdt:
                            diff = (comp_dt - sdt).total_seconds()
                            rec.duration_seconds = max(0.0, round(diff, 3))
                        else:
                            rec.duration_seconds = 0.0
                    else:
                        rec.start_time = comp_iso
                        rec._start_dt = comp_dt
                        rec.duration_seconds = 0.0

                # Deduplicated cancellation log emission
                if not rec._finished_logged:
                    duration_str = f"{rec.duration_seconds:.3f}s" if rec.duration_seconds is not None else "0.000s"
                    log_entry = (
                        f"[{rec.completion_time}] COMMAND_CANCELLED | "
                        f"command_id={rec.command_id} | "
                        f"session_id={rec.session_id} | "
                        f"command={rec.command} | "
                        f"duration={duration_str} | "
                        f"status=CANCELLED"
                    )
                    self._write_log(log_entry)
                    if self._enable_terminal_display:
                        display_execution_summary(rec)
                    rec._finished_logged = True


                self._record_to_history(rec)
                return rec.to_dict()
        except Exception as e:
            logger.error(f"[TimestampTracker] record_cancel error for {command_id}: {e}")
            return {
                "command_id": command_id,
                "session_id": session_id or "default",
                "command": command or "unknown",
                "status": "CANCELLED",
                "start_time": None,
                "completion_time": None,
                "duration_seconds": 0.0,
                "error": reason or "Cancelled",
            }

    def get_execution_details(self, command_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve execution details dictionary for a given command_id."""
        try:
            with self._lock:
                rec = self._records.get(command_id)
                if rec:
                    return rec.to_dict()
                return None
        except Exception as e:
            logger.error(f"[TimestampTracker] get_execution_details error for {command_id}: {e}")
            return None

    def _record_to_history(self, rec: ExecutionRecord) -> None:
        """Append completed record to history log with bound capacity."""
        self._history.append(rec)
        if len(self._history) > self._max_history:
            self._history.pop(0)

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return the most recent execution records."""
        with self._lock:
            return [r.to_dict() for r in self._history[-limit:]]

    def clear(self) -> None:
        """Clear memory cache of records and history (primarily for tests)."""
        with self._lock:
            self._records.clear()
            self._history.clear()


# Global Singleton Instance
_tracker_instance: Optional[TimestampTracker] = None
_tracker_lock = threading.Lock()


def get_timestamp_tracker(log_file_path: Optional[str] = None) -> TimestampTracker:
    """Return the global singleton TimestampTracker instance."""
    global _tracker_instance
    with _tracker_lock:
        if _tracker_instance is None:
            _tracker_instance = TimestampTracker(log_file_path)
        return _tracker_instance


# Export module-level instance for convenient import
timestamp_tracker = get_timestamp_tracker()
