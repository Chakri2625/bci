"""
Command Lifecycle Tracker (SynaptiMesh Core).
---------------------------------------------
Tracks commands across explicit lifecycle stages:
- CREATED: Initial command registration.
- VALIDATING / VALIDATED / VALIDATION_FAILED: Validation pipeline stages.
- QUEUED: Priority queue / execution buffer staging.
- EXECUTION_STARTED: Subsystem / actuator execution started.
- EXECUTION_COMPLETED: Subsystem execution completed.
- SUCCESS / FAILED / CANCELLED / TIMEOUT: Terminal states.

Integrates Session IDs, Command IDs, timestamped transitions, and audit traceability.
"""

from __future__ import annotations

import datetime
from enum import Enum
import itertools
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger("lifecycle_tracker")


class CommandLifecycleStage(str, Enum):
    """Explicit lifecycle stages for a command in SynaptiMesh."""
    CREATED = "CREATED"
    VALIDATING = "VALIDATING"
    VALIDATED = "VALIDATED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    QUEUED = "QUEUED"
    EXECUTION_STARTED = "EXECUTION_STARTED"
    EXECUTION_COMPLETED = "EXECUTION_COMPLETED"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"


TERMINAL_STAGES = {
    CommandLifecycleStage.SUCCESS,
    CommandLifecycleStage.FAILED,
    CommandLifecycleStage.CANCELLED,
    CommandLifecycleStage.TIMEOUT,
}


class LifecycleTransition:
    """Represents a single state transition in the command lifecycle."""

    def __init__(
        self,
        from_stage: Optional[CommandLifecycleStage],
        to_stage: CommandLifecycleStage,
        timestamp: float,
        reason: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.from_stage = from_stage
        self.to_stage = to_stage
        self.timestamp = timestamp
        self.timestamp_iso = datetime.datetime.fromtimestamp(
            timestamp, tz=datetime.timezone.utc
        ).isoformat()
        self.reason = reason
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from_stage": self.from_stage.value if self.from_stage else None,
            "to_stage": self.to_stage.value,
            "timestamp": self.timestamp,
            "timestamp_iso": self.timestamp_iso,
            "reason": self.reason,
            "metadata": self.metadata,
        }

    def __repr__(self) -> str:
        return f"<LifecycleTransition {self.from_stage} -> {self.to_stage} at {self.timestamp_iso}>"


class CommandLifecycleRecord:
    """Complete lifecycle tracking record for a command."""

    def __init__(
        self,
        command_id: str,
        session_id: str,
        command: str,
        domain: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.command_id = command_id
        self.session_id = session_id
        self.command = command
        self.domain = domain
        self.current_stage: CommandLifecycleStage = CommandLifecycleStage.CREATED
        self.created_at: float = time.time()
        self.created_at_iso: str = datetime.datetime.fromtimestamp(
            self.created_at, tz=datetime.timezone.utc
        ).isoformat()
        self.started_at: Optional[float] = None
        self.started_at_iso: Optional[str] = None
        self.completed_at: Optional[float] = None
        self.completed_at_iso: Optional[str] = None
        self.duration_ms: Optional[float] = None
        self.duration_s: Optional[float] = None
        self.result: Optional[Any] = None
        self.error: Optional[str] = None
        self.error_code: Optional[str] = None
        self.metadata: Dict[str, Any] = metadata or {}
        self.history: List[LifecycleTransition] = [
            LifecycleTransition(
                from_stage=None,
                to_stage=CommandLifecycleStage.CREATED,
                timestamp=self.created_at,
                reason="Command created",
                metadata=self.metadata.copy(),
            )
        ]

    @property
    def is_terminal(self) -> bool:
        return self.current_stage in TERMINAL_STAGES

    def add_transition(
        self,
        new_stage: CommandLifecycleStage,
        reason: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None,
    ) -> LifecycleTransition:
        """Add a lifecycle transition with atomic terminal state guard.
        
        Only ONE terminal state is allowed: SUCCESS, FAILED, TIMEOUT, or CANCELLED.
        Once a terminal state is set, it cannot be changed.
        """
        now = timestamp if timestamp is not None else time.time()
        
        # Atomic terminal state guard: prevent state regression
        if self.is_terminal and new_stage not in TERMINAL_STAGES:
            # Already in terminal state, ignore non-terminal transitions
            logger.warning(
                f"[LIFECYCLE] Command {self.command_id} already in terminal state "
                f"{self.current_stage.value}, ignoring transition to {new_stage.value}"
            )
            return self.history[-1]  # Return last transition
        
        # If already terminal and trying to set another terminal state, only allow if not yet set
        if self.is_terminal and new_stage in TERMINAL_STAGES:
            if self.current_stage in TERMINAL_STAGES:
                logger.warning(
                    f"[LIFECYCLE] Command {self.command_id} already in terminal state "
                    f"{self.current_stage.value}, ignoring duplicate terminal state {new_stage.value}"
                )
                return self.history[-1]
        
        transition = LifecycleTransition(
            from_stage=self.current_stage,
            to_stage=new_stage,
            timestamp=now,
            reason=reason,
            metadata=metadata or {},
        )
        self.current_stage = new_stage
        self.history.append(transition)

        if metadata:
            self.metadata.update(metadata)

        if new_stage == CommandLifecycleStage.EXECUTION_STARTED and self.started_at is None:
            self.started_at = now
            self.started_at_iso = datetime.datetime.fromtimestamp(
                now, tz=datetime.timezone.utc
            ).isoformat()

        if new_stage in (
            CommandLifecycleStage.EXECUTION_COMPLETED,
            CommandLifecycleStage.SUCCESS,
            CommandLifecycleStage.FAILED,
            CommandLifecycleStage.CANCELLED,
            CommandLifecycleStage.TIMEOUT,
        ):
            if self.completed_at is None:
                self.completed_at = now
                self.completed_at_iso = datetime.datetime.fromtimestamp(
                    now, tz=datetime.timezone.utc
                ).isoformat()
                if self.started_at is not None:
                    self.duration_ms = round((self.completed_at - self.started_at) * 1000.0, 2)
                else:
                    self.duration_ms = round((self.completed_at - self.created_at) * 1000.0, 2)
                self.duration_s = round(self.duration_ms / 1000.0, 4) if self.duration_ms is not None else None

        return transition

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command_id": self.command_id,
            "session_id": self.session_id,
            "command": self.command,
            "domain": self.domain,
            "current_stage": self.current_stage.value,
            "is_terminal": self.is_terminal,
            "created_at": self.created_at,
            "created_at_iso": self.created_at_iso,
            "started_at": self.started_at,
            "started_at_iso": self.started_at_iso,
            "completed_at": self.completed_at,
            "completed_at_iso": self.completed_at_iso,
            "duration_ms": self.duration_ms,
            "duration_s": self.duration_s,
            "result": self.result,
            "error": self.error,
            "error_code": self.error_code,
            "metadata": self.metadata,
            "transitions_count": len(self.history),
            "history": [t.to_dict() for t in self.history],
        }

    def __repr__(self) -> str:
        return f"<CommandLifecycleRecord {self.command_id} [{self.current_stage.value}] session={self.session_id}>"


class CommandLifecycleTracker:
    """
    Centralized thread-safe Command Lifecycle Tracking Manager.
    Maintains active and historical command lifecycle states by Command ID and Session ID.
    """

    def __init__(self, max_history_per_session: int = 500):
        self._records: Dict[str, CommandLifecycleRecord] = {}  # command_id -> record
        self._session_map: Dict[str, List[str]] = {}  # session_id -> list of command_ids
        self._executions: Dict[str, Dict[str, Any]] = {}  # execution_id -> legacy execution dict
        self._lock = threading.RLock()
        self._id_counter = itertools.count(1000)
        self.max_history_per_session = max_history_per_session

    def generate_command_id(self, prefix: str = "CMD") -> str:
        """Generate standard compliant monotonic command ID."""
        return f"{prefix}-{next(self._id_counter)}"

    def create_command(
        self,
        command: str,
        session_id: str = "default",
        command_id: Optional[str] = None,
        domain: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CommandLifecycleRecord:
        """
        Register a newly created command in the lifecycle tracker.
        """
        with self._lock:
            cid = command_id or self.generate_command_id()
            record = CommandLifecycleRecord(
                command_id=cid,
                session_id=session_id,
                command=command,
                domain=domain,
                metadata=metadata,
            )
            self._records[cid] = record
            session_list = self._session_map.setdefault(session_id, [])
            session_list.append(cid)

            if len(session_list) > self.max_history_per_session:
                old_cid = session_list.pop(0)

            logger.info(
                f"[LIFECYCLE] Created command {cid} (cmd={command}, session={session_id})"
            )
            return record

    def track_validation(
        self,
        command_id: str,
        is_valid: bool,
        reason: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CommandLifecycleRecord:
        """
        Record validation outcome for a command.
        """
        with self._lock:
            record = self._get_or_create(command_id)
            target_stage = (
                CommandLifecycleStage.VALIDATED
                if is_valid
                else CommandLifecycleStage.VALIDATION_FAILED
            )
            meta = metadata or {}
            meta["is_valid"] = is_valid
            if reason:
                meta["validation_reason"] = reason

            record.add_transition(target_stage, reason=reason, metadata=meta)
            logger.info(
                f"[LIFECYCLE] Command {command_id} validation -> {target_stage.value} (valid={is_valid}, reason={reason})"
            )
            return record

    def track_validating(
        self,
        command_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CommandLifecycleRecord:
        """
        Record that command is currently undergoing validation.
        """
        with self._lock:
            record = self._get_or_create(command_id)
            record.add_transition(
                CommandLifecycleStage.VALIDATING,
                reason="Validation in progress",
                metadata=metadata,
            )
            return record

    def track_queued(
        self,
        command_id: str,
        priority: Optional[Any] = None,
        queue_position: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CommandLifecycleRecord:
        """
        Record that command has been queued.
        """
        with self._lock:
            record = self._get_or_create(command_id)
            meta = metadata or {}
            if priority is not None:
                meta["priority"] = str(priority)
            if queue_position is not None:
                meta["queue_position"] = queue_position

            record.add_transition(
                CommandLifecycleStage.QUEUED,
                reason=f"Enqueued in priority queue (priority={priority})",
                metadata=meta,
            )
            logger.info(
                f"[LIFECYCLE] Command {command_id} -> QUEUED (priority={priority}, pos={queue_position})"
            )
            return record

    def track_execution_started(
        self,
        command_id: str,
        target: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None,
    ) -> CommandLifecycleRecord:
        """
        Record that execution has started.
        """
        with self._lock:
            record = self._get_or_create(command_id)
            meta = metadata or {}
            if target:
                meta["target"] = target
                if not record.domain:
                    record.domain = target

            record.add_transition(
                CommandLifecycleStage.EXECUTION_STARTED,
                reason=f"Execution started on target '{target or 'default'}'",
                metadata=meta,
                timestamp=timestamp,
            )
            logger.info(
                f"[EXECUTION_START] Command {command_id} ({record.command}) -> EXECUTION_STARTED at {record.started_at_iso} (target={target})"
            )
            return record

    def track_execution_completed(
        self,
        command_id: str,
        success: bool,
        result: Optional[Any] = None,
        error: Optional[str] = None,
        error_code: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None,
    ) -> CommandLifecycleRecord:
        """
        Record that execution completed and immediately transition to terminal SUCCESS or FAILED.
        """
        with self._lock:
            record = self._get_or_create(command_id)
            meta = metadata or {}
            record.result = result
            record.error = error
            record.error_code = error_code

            # Record intermediate completion
            record.add_transition(
                CommandLifecycleStage.EXECUTION_COMPLETED,
                reason="Subsystem execution routine completed",
                metadata=meta,
                timestamp=timestamp,
            )

            # Advance to terminal state
            if success:
                record.add_transition(
                    CommandLifecycleStage.SUCCESS,
                    reason="Command completed successfully",
                    metadata=meta,
                    timestamp=timestamp,
                )
            else:
                record.add_transition(
                    CommandLifecycleStage.FAILED,
                    reason=error or "Command execution failed",
                    metadata=meta,
                    timestamp=timestamp,
                )

            logger.info(
                f"[EXECUTION_COMPLETE] Command {command_id} ({record.command}) -> {record.current_stage.value} at {record.completed_at_iso} (duration={record.duration_ms}ms)"
            )
            # TASK 2: Forward terminal record into MetricsService
            self._notify_metrics(record)
            return record

    def _notify_metrics(self, record: CommandLifecycleRecord) -> None:
        """
        TASK 2 (Metrics Integration): Forward terminal command records into the
        global MetricsService so performance data covers the entire backend.

        Uses a lazy import to avoid any circular dependency concerns.
        record_completion() deduplicates by command_id, so repeated calls
        for the same record are safe no-ops.
        """
        if not record.is_terminal:
            return
        try:
            from core.metrics.service import metrics_service
            metrics_service.record_completion(record)
        except Exception as e:
            logger.debug(f"[LIFECYCLE] Metrics recording notice for {record.command_id}: {e}")

    def track_success(
        self,
        command_id: str,
        result: Optional[Any] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None,
    ) -> CommandLifecycleRecord:
        """
        Transition command directly to SUCCESS terminal stage.
        """
        with self._lock:
            record = self._get_or_create(command_id)
            record.result = result
            record.add_transition(
                CommandLifecycleStage.SUCCESS,
                reason="Command execution succeeded",
                metadata=metadata,
                timestamp=timestamp,
            )
            logger.info(
                f"[EXECUTION_COMPLETE] Command {command_id} ({record.command}) -> SUCCESS at {record.completed_at_iso} (duration={record.duration_ms}ms)"
            )
            # TASK 2: Forward terminal record into MetricsService
            self._notify_metrics(record)
            return record

    def track_failure(
        self,
        command_id: str,
        error: Optional[str] = None,
        error_code: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None,
    ) -> CommandLifecycleRecord:
        """
        Transition command directly to FAILED terminal stage.
        """
        with self._lock:
            record = self._get_or_create(command_id)
            record.error = error or "Execution failed"
            record.error_code = error_code
            meta = metadata or {}
            if error_code:
                meta["error_code"] = error_code
            record.add_transition(
                CommandLifecycleStage.FAILED,
                reason=record.error,
                metadata=meta,
                timestamp=timestamp,
            )
            logger.warning(
                f"[EXECUTION_COMPLETE] Command {command_id} ({record.command}) -> FAILED at {record.completed_at_iso} (error={record.error}, duration={record.duration_ms}ms)"
            )
            # TASK 2: Forward terminal record into MetricsService
            self._notify_metrics(record)
            return record

    def track_failed(
        self,
        command_id: str,
        error: Optional[str] = None,
        error_code: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None,
    ) -> CommandLifecycleRecord:
        """Alias for track_failure."""
        return self.track_failure(command_id, error=error, error_code=error_code, metadata=metadata, timestamp=timestamp)

    def track_cancelled(
        self,
        command_id: str,
        reason: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None,
    ) -> CommandLifecycleRecord:
        """
        Record cancellation of a command.
        """
        with self._lock:
            record = self._get_or_create(command_id)
            record.error = reason or "Cancelled"
            record.add_transition(
                CommandLifecycleStage.CANCELLED,
                reason=reason or "Command was cancelled",
                metadata=metadata,
                timestamp=timestamp,
            )
            logger.info(
                f"[EXECUTION_COMPLETE] Command {command_id} ({record.command}) -> CANCELLED at {record.completed_at_iso} (reason={reason}, duration={record.duration_ms}ms)"
            )
            # TASK 2: Forward terminal record into MetricsService
            self._notify_metrics(record)
            return record

    def track_timeout(
        self,
        command_id: str,
        reason: Optional[str] = None,
        timeout_duration_ms: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None,
    ) -> CommandLifecycleRecord:
        """
        Record timeout of a command with duration and error details.
        """
        with self._lock:
            record = self._get_or_create(command_id)
            meta = metadata or {}
            if timeout_duration_ms is not None:
                meta["timeout_duration_ms"] = timeout_duration_ms
            record.error = reason or "Execution timeout"
            record.error_code = "TIMEOUT"
            record.add_transition(
                CommandLifecycleStage.TIMEOUT,
                reason=reason or "Command execution timed out",
                metadata=meta,
                timestamp=timestamp,
            )
            logger.warning(
                f"[EXECUTION_COMPLETE] Command {command_id} ({record.command}) -> TIMEOUT "
                f"at {record.completed_at_iso} (reason={reason}, duration={record.duration_ms}ms)"
            )
            # TASK 2: Forward terminal record into MetricsService
            self._notify_metrics(record)
            return record

    def record_start_timestamp(
        self,
        command_id: str,
        target: Optional[str] = None,
        timestamp: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CommandLifecycleRecord:
        """
        Explicitly record the execution start timestamp for a command.
        """
        return self.track_execution_started(
            command_id=command_id,
            target=target,
            metadata=metadata,
            timestamp=timestamp,
        )

    def record_completion_timestamp(
        self,
        command_id: str,
        status: Union[str, CommandLifecycleStage] = CommandLifecycleStage.SUCCESS,
        timestamp: Optional[float] = None,
        result: Optional[Any] = None,
        error: Optional[str] = None,
        error_code: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CommandLifecycleRecord:
        """
        Explicitly record the execution completion timestamp and calculate duration.
        """
        st = status.value if isinstance(status, CommandLifecycleStage) else str(status).upper()
        if st in ("SUCCESS", "COMPLETED"):
            return self.track_success(command_id, result=result, metadata=metadata, timestamp=timestamp)
        elif st in ("FAILED", "ERROR"):
            return self.track_failure(command_id, error=error, error_code=error_code, metadata=metadata, timestamp=timestamp)
        elif st == "CANCELLED":
            return self.track_cancelled(command_id, reason=error or "Cancelled", metadata=metadata, timestamp=timestamp)
        elif st in ("TIMEOUT", "TIMED_OUT"):
            return self.track_timeout(command_id, reason=error or "Timed out", metadata=metadata, timestamp=timestamp)
        else:
            return self.track_execution_completed(
                command_id=command_id,
                success=True,
                result=result,
                error=error,
                error_code=error_code,
                metadata=metadata,
                timestamp=timestamp,
            )

    def calculate_duration(self, command_id: str) -> Optional[float]:
        """
        Return the execution duration in milliseconds for a command if completed.
        """
        with self._lock:
            rec = self.get_lifecycle(command_id)
            return rec.duration_ms if rec else None

    def get_execution_timing(self, command_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve structured execution timing telemetry for a specific command.
        """
        with self._lock:
            rec = self.get_lifecycle(command_id)
            if not rec:
                return None
            return {
                "command_id": rec.command_id,
                "session_id": rec.session_id,
                "command": rec.command,
                "domain": rec.domain,
                "status": rec.current_stage.value,
                "is_terminal": rec.is_terminal,
                "created_at": rec.created_at,
                "created_at_iso": rec.created_at_iso,
                "started_at": rec.started_at,
                "started_at_iso": rec.started_at_iso,
                "completed_at": rec.completed_at,
                "completed_at_iso": rec.completed_at_iso,
                "duration_ms": rec.duration_ms,
                "duration_s": rec.duration_s,
            }

    def get_lifecycle(self, command_id: str) -> Optional[CommandLifecycleRecord]:
        """
        Retrieve the lifecycle record for a given command_id.
        """
        with self._lock:
            return self._records.get(command_id)

    def get_record(self, command_id: str) -> Optional[CommandLifecycleRecord]:
        """Alias for get_lifecycle."""
        return self.get_lifecycle(command_id)

    def get_session_commands(
        self, session_id: str = "default"
    ) -> List[CommandLifecycleRecord]:
        """
        Retrieve all lifecycle records for a session in chronological order.
        """
        with self._lock:
            cids = self._session_map.get(session_id, [])
            return [self._records[cid] for cid in cids if cid in self._records]

    def get_active_commands(
        self, session_id: Optional[str] = None
    ) -> List[CommandLifecycleRecord]:
        """
        Retrieve currently non-terminal (in-flight) commands.
        """
        with self._lock:
            if session_id:
                cids = self._session_map.get(session_id, [])
                return [
                    self._records[cid]
                    for cid in cids
                    if cid in self._records and not self._records[cid].is_terminal
                ]
            return [rec for rec in self._records.values() if not rec.is_terminal]

    def get_summary(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get aggregated lifecycle counts and statistics.
        """
        with self._lock:
            records = (
                self.get_session_commands(session_id)
                if session_id
                else list(self._records.values())
            )
            stage_counts = {stage.value: 0 for stage in CommandLifecycleStage}
            total_duration = 0.0
            completed_count = 0

            for rec in records:
                stage_counts[rec.current_stage.value] = (
                    stage_counts.get(rec.current_stage.value, 0) + 1
                )
                if rec.duration_ms is not None:
                    total_duration += rec.duration_ms
                    completed_count += 1

            avg_duration = (
                round(total_duration / completed_count, 2)
                if completed_count > 0
                else 0.0
            )

            return {
                "total_commands": len(records),
                "active_commands": len([r for r in records if not r.is_terminal]),
                "stage_counts": stage_counts,
                "avg_duration_ms": avg_duration,
                "session_id": session_id or "all",
            }

    def export_audit_trail(
        self, session_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Export detailed audit log for traceability.
        """
        with self._lock:
            records = (
                self.get_session_commands(session_id)
                if session_id
                else list(self._records.values())
            )
            return [rec.to_dict() for rec in records]

    def start_execution(
        self,
        command: str,
        domain: Optional[str] = None,
        app: Optional[str] = None,
        priority: str = "NORMAL",
        execution_id: Optional[str] = None,
    ) -> str:
        """Legacy and task manager compatible execution start."""
        with self._lock:
            import uuid
            eid = execution_id or uuid.uuid4().hex
            now = time.time()
            self._executions[eid] = {
                "execution_id": eid,
                "command": command,
                "domain": domain,
                "app": app,
                "priority": priority,
                "status": "PENDING",
                "start_time": now,
                "end_time": None,
                "result": None,
                "error": None,
            }
            # Also register in modern records
            self.create_command(command=command, command_id=eid, domain=domain)
            return eid

    def update_status(
        self,
        execution_id: str,
        status: str,
        result: Optional[Any] = None,
        error: Optional[str] = None,
    ) -> bool:
        """Update status for an execution with state-machine validity checks."""
        with self._lock:
            if execution_id not in self._executions:
                return False

            st_upper = status.upper()
            allowed = {"PENDING", "RUNNING", "SUCCESS", "FAILED", "CANCELLED", "TIMEOUT"}
            if st_upper not in allowed:
                return False

            curr = self._executions[execution_id]
            curr_st = curr["status"]
            terminal = {"SUCCESS", "FAILED", "CANCELLED", "TIMEOUT"}
            if curr_st in terminal:
                return False

            curr["status"] = st_upper
            if result is not None:
                curr["result"] = result
            if error is not None:
                curr["error"] = error
            if st_upper in terminal:
                curr["end_time"] = time.time()

            # Sync with modern records if present
            if execution_id in self._records:
                if st_upper == "RUNNING":
                    self.track_execution_started(execution_id)
                elif st_upper == "SUCCESS":
                    self.track_success(execution_id, result=result)
                elif st_upper == "FAILED":
                    self.track_failure(execution_id, error=error)
                elif st_upper == "CANCELLED":
                    self.track_cancelled(execution_id, reason=error)
                elif st_upper == "TIMEOUT":
                    self.track_timeout(execution_id, reason=error)

            return True

    def get_execution(self, execution_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._executions.get(execution_id)

    def get_all_executions(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return dict(self._executions)

    def cleanup_completed(self, keep_latest: int = 10) -> int:
        with self._lock:
            terminal = {"SUCCESS", "FAILED", "CANCELLED", "TIMEOUT"}
            completed_keys = [k for k, v in self._executions.items() if v.get("status") in terminal]
            to_remove = len(completed_keys) - keep_latest
            if to_remove > 0:
                for k in completed_keys[:to_remove]:
                    self._executions.pop(k, None)
                return to_remove
            return 0

    def clear(self, session_id: Optional[str] = None) -> None:
        """
        Reset records for a session or globally.
        """
        with self._lock:
            if session_id:
                cids = self._session_map.pop(session_id, [])
                for cid in cids:
                    self._records.pop(cid, None)
                    self._executions.pop(cid, None)
            else:
                self._records.clear()
                self._session_map.clear()
                self._executions.clear()

    def _get_or_create(self, command_id: str) -> CommandLifecycleRecord:
        """Helper to get existing or auto-create a placeholder if not present."""
        if command_id not in self._records:
            record = CommandLifecycleRecord(
                command_id=command_id,
                session_id="default",
                command="UNKNOWN",
            )
            self._records[command_id] = record
            self._session_map.setdefault("default", []).append(command_id)
            return record
        return self._records[command_id]


# Global singleton instance
CommandLifecycleTracker = CommandLifecycleTracker
LifecycleTracker = CommandLifecycleTracker
lifecycle_tracker = CommandLifecycleTracker()
