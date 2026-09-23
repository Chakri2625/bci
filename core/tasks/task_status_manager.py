"""
Task Status Manager
====================

Owner: Member 4 (Day 3 - Concurrent Command Execution)

Responsibility
--------------
Track the lifecycle of every task moving through the concurrent execution
pipeline across five explicit states:

    PENDING -> RUNNING -> COMPLETED
                       \\-> FAILED
    PENDING -> CANCELLED
    RUNNING -> CANCELLED

All reads/writes are guarded by a single re-entrant lock, so this manager is
safe to call from:
  - the asyncio event loop thread (Member 3's Parallel Command Execution
    Engine, driving tasks created by Member 2's Async Task Manager), and
  - worker threads used for blocking calls (e.g. the pyautogui-based desktop
    automation / Chrome subplugin commands, which are typically dispatched
    via `loop.run_in_executor`).

Upstream contract (Member 2 - Async Task Manager)
--------------------------------------------------
This module does not assume a concrete `Task` class from Member 2 - at the
time of writing, `core/queue/task_queue.py` only exposes a minimal
`asyncio.Queue` wrapper and no Task/TaskManager type has landed yet. To stay
compatible regardless of the final shape of that module, this manager only
requires a `task_id: str`. Member 2's Task Manager should call
`task_status_manager.create_task(task_id, command=..., metadata=...)` at the
moment a task is accepted, and this manager owns all status transitions from
that point on. If Member 2's Task object already carries its own id, pass
that same id in here so every downstream component refers to the same task
by the same identifier.

Downstream contract (Member 7/8 - Timeout & Cancellation)
-----------------------------------------------------------
Two ways to observe status changes:
  1. `task_status_manager.register_listener(callback)` - `callback` is a
     plain, synchronous `Callable[[TaskStatusRecord], None]` invoked on every
     create/transition, from whatever thread triggered it. Cheap, ordered,
     and thread-safe. Good fit for a Timeout Manager arming/disarming a
     timer, or a Cancellation Manager checking whether a cancel request is
     still valid.
  2. `core.events.event_bus` - every transition also publishes a
     `"task_status_changed"` event with a JSON-serialisable payload, for
     components that are already wired into the async event bus.

Integration (Member 9)
-----------------------
`task_status_manager.get_status(task_id)` / `get_task(task_id)` /
`get_all_tasks(state)` give a consistent, thread-safe view of the world for
the final integration + `/status`-style endpoints.
"""

import asyncio
import logging
import threading
import time
import uuid
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from pydantic import BaseModel, Field

from core.logging.logger import logger as base_logger
from core.events.event_bus import event_bus

logger = logging.getLogger("synaptimesh.task_status_manager")


class TaskState(str, Enum):
    """The five explicit lifecycle states a task can be in."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# States from which no further transition is allowed.
TERMINAL_STATES: Set[TaskState] = {
    TaskState.COMPLETED,
    TaskState.FAILED,
    TaskState.CANCELLED,
}

# Explicit state machine. Anything not listed here is rejected.
VALID_TRANSITIONS: Dict[TaskState, Set[TaskState]] = {
    TaskState.PENDING: {TaskState.RUNNING, TaskState.CANCELLED},
    TaskState.RUNNING: {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.COMPLETED: set(),
    TaskState.FAILED: set(),
    TaskState.CANCELLED: set(),
}


class TaskNotFoundError(KeyError):
    """Raised when querying/transitioning a task_id that isn't registered."""

    def __init__(self, task_id: str):
        self.task_id = task_id
        super().__init__(f"Unknown task_id: '{task_id}'")


class InvalidTaskTransitionError(Exception):
    """Raised when a transition would violate the task state machine."""

    def __init__(self, task_id: str, current: TaskState, target: TaskState):
        self.task_id = task_id
        self.current = current
        self.target = target
        super().__init__(
            f"Task '{task_id}': invalid transition {current.value} -> {target.value}"
        )


class TaskStatusRecord(BaseModel):
    """Snapshot of a single task's lifecycle state and metadata."""

    task_id: str
    command: Optional[str] = None
    session: str = "default"
    state: TaskState = TaskState.PENDING
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    history: List[Dict[str, Any]] = Field(default_factory=list)

    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES


TaskListener = Callable[[TaskStatusRecord], None]


def _snapshot(record: TaskStatusRecord) -> TaskStatusRecord:
    """Return a detached copy so callers can't mutate internal state."""
    if hasattr(record, "model_copy"):  # pydantic v2
        return record.model_copy(deep=True)
    return record.copy(deep=True)  # pydantic v1 fallback


def _as_dict(record: TaskStatusRecord) -> Dict[str, Any]:
    if hasattr(record, "model_dump"):  # pydantic v2
        return record.model_dump(mode="json")
    return record.dict()  # pydantic v1 fallback


class TaskStatusManager:
    """
    Thread-safe registry for concurrent task lifecycle state.

    Usage
    -----
        task_status_manager.create_task(task_id, command="OPEN_CHROME")
        task_status_manager.mark_running(task_id)
        ...
        task_status_manager.mark_completed(task_id, result={"status": "ok"})
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tasks: Dict[str, TaskStatusRecord] = {}
        self._listeners: List[TaskListener] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ------------------------------------------------------------------
    # Setup / wiring
    # ------------------------------------------------------------------
    def bind_event_loop(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """
        Remember the main asyncio event loop so status changes triggered
        from worker threads (e.g. pyautogui automation running in an
        executor) can still publish to the async event_bus.

        Call this once during app startup, from inside the running loop:
            task_status_manager.bind_event_loop()
        """
        with self._lock:
            self._loop = loop or asyncio.get_running_loop()

    def register_listener(self, callback: TaskListener) -> None:
        """Register a synchronous callback invoked on every create/transition."""
        with self._lock:
            self._listeners.append(callback)

    def unregister_listener(self, callback: TaskListener) -> None:
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    # ------------------------------------------------------------------
    # Task creation
    # ------------------------------------------------------------------
    def create_task(
        self,
        task_id: Optional[str] = None,
        command: Optional[str] = None,
        session: str = "default",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TaskStatusRecord:
        """
        Register a new task in the PENDING state. If `task_id` is omitted,
        a uuid4 string is generated (matching the id convention already
        used for QueuedCommand elsewhere in this codebase).
        """
        task_id = task_id or str(uuid.uuid4())
        with self._lock:
            if task_id in self._tasks:
                raise ValueError(f"Task '{task_id}' is already registered")

            record = TaskStatusRecord(
                task_id=task_id,
                command=command,
                session=session,
                metadata=metadata or {},
                state=TaskState.PENDING,
            )
            record.history.append(
                {"state": TaskState.PENDING.value, "timestamp": record.created_at, "note": "task created"}
            )
            self._tasks[task_id] = record
            snapshot = _snapshot(record)

        base_logger.info(f"[TaskStatusManager] Task created: id={task_id}, command={command}")
        self._notify(snapshot)
        return snapshot

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def get_status(self, task_id: str) -> TaskState:
        """Return just the current TaskState for `task_id`."""
        with self._lock:
            return self._get(task_id).state

    def get_task(self, task_id: str) -> TaskStatusRecord:
        """Return a full, detached snapshot of a task's record."""
        with self._lock:
            return _snapshot(self._get(task_id))

    def get_all_tasks(self, state: Optional[TaskState] = None) -> List[TaskStatusRecord]:
        """Return snapshots of all tasks, optionally filtered by state."""
        with self._lock:
            records = self._tasks.values()
            if state is not None:
                records = [r for r in records if r.state == state]
            return [_snapshot(r) for r in records]

    def get_active_task_ids(self) -> List[str]:
        """Task ids currently in PENDING or RUNNING (non-terminal) state."""
        with self._lock:
            return [tid for tid, r in self._tasks.items() if not r.is_terminal()]

    def exists(self, task_id: str) -> bool:
        with self._lock:
            return task_id in self._tasks

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------
    def transition(
        self,
        task_id: str,
        new_state: TaskState,
        *,
        error: Optional[str] = None,
        result: Optional[Any] = None,
        note: Optional[str] = None,
    ) -> TaskStatusRecord:
        """
        Move `task_id` to `new_state`, enforcing VALID_TRANSITIONS.

        Idempotent no-op if the task is already in `new_state` (guards
        against double-cancellation races between Member 7 and Member 8).
        Raises InvalidTaskTransitionError for any other disallowed move,
        e.g. COMPLETED -> RUNNING or PENDING -> COMPLETED.
        """
        with self._lock:
            record = self._get(task_id)
            current = record.state

            if current == new_state:
                logger.debug(f"[TaskStatusManager] No-op transition for '{task_id}': already {current.value}")
                return _snapshot(record)

            allowed = VALID_TRANSITIONS.get(current, set())
            if new_state not in allowed:
                logger.warning(
                    f"[TaskStatusManager] Rejected invalid transition for '{task_id}': "
                    f"{current.value} -> {new_state.value}"
                )
                raise InvalidTaskTransitionError(task_id, current, new_state)

            now = time.time()
            record.state = new_state
            record.updated_at = now

            if new_state == TaskState.RUNNING and record.started_at is None:
                record.started_at = now
            if new_state in TERMINAL_STATES:
                record.finished_at = now
            if error is not None:
                record.error = str(error)
            if result is not None:
                record.result = result

            record.history.append({"state": new_state.value, "timestamp": now, "note": note})
            snapshot = _snapshot(record)

        base_logger.info(f"[TaskStatusManager] Task {task_id}: {current.value} -> {new_state.value}")
        self._notify(snapshot)
        return snapshot

    # Convenience wrappers -------------------------------------------------
    def mark_running(self, task_id: str) -> TaskStatusRecord:
        return self.transition(task_id, TaskState.RUNNING)

    def mark_completed(self, task_id: str, result: Optional[Any] = None) -> TaskStatusRecord:
        return self.transition(task_id, TaskState.COMPLETED, result=result)

    def mark_failed(self, task_id: str, error: Optional[str] = None) -> TaskStatusRecord:
        return self.transition(task_id, TaskState.FAILED, error=error)

    def mark_cancelled(self, task_id: str, note: Optional[str] = None) -> TaskStatusRecord:
        return self.transition(task_id, TaskState.CANCELLED, note=note or "cancelled")

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def remove_task(self, task_id: str) -> None:
        """Drop a terminal task's record once downstream consumers are done with it."""
        with self._lock:
            self._tasks.pop(task_id, None)

    def reset(self) -> None:
        """Clear all tracked tasks and listeners. Intended for test fixtures."""
        with self._lock:
            self._tasks.clear()
            self._listeners.clear()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _get(self, task_id: str) -> TaskStatusRecord:
        record = self._tasks.get(task_id)
        if record is None:
            raise TaskNotFoundError(task_id)
        return record

    def _notify(self, record: TaskStatusRecord) -> None:
        """Fan out a status change to sync listeners and the async event bus."""
        for callback in list(self._listeners):
            try:
                callback(record)
            except Exception as exc:  # a bad listener must never break the manager
                logger.error(f"[TaskStatusManager] Listener error for task '{record.task_id}': {exc}")

        coro = event_bus.publish("task_status_changed", _as_dict(record))
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            # Not called from within the event loop thread (e.g. a worker
            # thread running a blocking pyautogui command). If the loop was
            # registered via bind_event_loop(), hop back onto it safely.
            if self._loop is not None and not self._loop.is_closed():
                asyncio.run_coroutine_threadsafe(coro, self._loop)
            else:
                logger.debug(
                    f"[TaskStatusManager] No event loop bound; skipping event_bus publish for task '{record.task_id}'"
                )
                coro.close()


# Module-level singleton, matching the convention used by task_queue,
# event_bus, state_manager and retry_manager elsewhere in core/.
task_status_manager = TaskStatusManager()
