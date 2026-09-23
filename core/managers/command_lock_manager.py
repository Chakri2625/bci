"""
Command Lock & Combination Manager (SynaptiMesh Core).
=====================================================
Enforces exact command lock and combination rules across SynaptiMesh:
1. The FIRST accepted command acquires the lock and starts ONE timer (T0).
2. While locked, allows ONLY ONE valid second command to form a supported combination (PUSH+LEFT, PUSH+RIGHT).
3. The original timer MUST NOT reset or restart upon combination creation.
4. Third commands and invalid commands during lock are strictly IGNORED and blocked from reaching executors.
5. Upon timer expiration, the command unlocks and the system returns to IDLE.
6. Integrates with EventHistory and LifecycleTracker for audit traceability.
7. Thread-safe using threading.RLock.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, Optional, Tuple

from core.validation.command_normalizer import normalize_command
from core.managers.event_history import event_history, EventType, EventStatus

logger = logging.getLogger("command_lock_manager")


class CommandLockManager:
    """
    Thread-safe authoritative command lock and combination manager.
    """

    def __init__(self, default_duration: float = 4.0):
        self._lock = threading.RLock()
        self._default_duration: float = default_duration
        self._locks: Dict[str, Dict[str, Any]] = {}

    def get_default_duration(self) -> float:
        with self._lock:
            return self._default_duration

    def set_default_duration(self, duration: float) -> None:
        """Update default lock duration without altering active running locks."""
        with self._lock:
            if duration > 0:
                self._default_duration = float(duration)
                logger.info(f"[LOCK_MANAGER] Default timer duration updated to {self._default_duration:.1f}s")

    def _cleanup_expired(self, session: str, now: Optional[float] = None) -> None:
        """Internal helper to unlock expired locks. Must be called while holding self._lock."""
        if now is None:
            now = time.time()
        if session in self._locks:
            lock = self._locks[session]
            if now >= lock.get("deadline", 0.0):
                cmd = lock.get("active_command")
                cid = lock.get("command_id")
                start_t = lock.get("start_time")
                deadline = lock.get("deadline")
                
                logger.info(f"[LOCK_MANAGER] Lock expired for session '{session}' (cmd: {cmd}). Unlocking -> IDLE")
                print(f"[TEMPORAL] Window expired (Session: {session}, Command: {cmd})")
                
                # Log audit events
                try:
                    event_history.record_event(
                        event_type=EventType.TIMER_EXPIRED,
                        command=cmd,
                        command_id=cid,
                        status=EventStatus.SUCCESS,
                        metadata={
                            "session_id": session,
                            "timer_started": start_t,
                            "timer_deadline": deadline,
                            "reason": "Timer deadline reached"
                        }
                    )
                    event_history.record_event(
                        event_type=EventType.COMMAND_UNLOCKED,
                        command=cmd,
                        command_id=cid,
                        status=EventStatus.SUCCESS,
                        metadata={
                            "session_id": session,
                            "state": "IDLE"
                        }
                    )
                except Exception as e:
                    logger.debug(f"[LOCK_MANAGER] Event recording error during expiry: {e}")

                del self._locks[session]

    def get_lock_state(self, session: str = "default") -> Dict[str, Any]:
        """Return the current lock and timer state for a session."""
        with self._lock:
            now = time.time()
            self._cleanup_expired(session, now)

            if session in self._locks:
                lock = self._locks[session]
                remaining = max(0.0, lock["deadline"] - now)
                status = "COMBINATION" if lock.get("has_second_command") else "LOCKED"
                return {
                    "is_locked": True,
                    "active_command": lock["active_command"],
                    "original_command": lock["original_command"],
                    "combination": lock["combination"],
                    "timer_started": lock["start_time"],
                    "timer_deadline": lock["deadline"],
                    "time_remaining": round(remaining, 3),
                    "duration": lock["duration"],
                    "has_second_command": lock["has_second_command"],
                    "status": status,
                    "session_id": session,
                }
            else:
                return {
                    "is_locked": False,
                    "active_command": None,
                    "original_command": None,
                    "combination": None,
                    "timer_started": None,
                    "timer_deadline": None,
                    "time_remaining": 0.0,
                    "duration": self._default_duration,
                    "has_second_command": False,
                    "status": "IDLE",
                    "session_id": session,
                }

    def can_accept_command(self, session: str, command: str) -> Tuple[bool, bool, Optional[str], Optional[str]]:
        """
        Check if a command can be accepted.
        Returns: (accepted, is_combination, normalized_resulting_command, rejection_reason)
        """
        with self._lock:
            now = time.time()
            self._cleanup_expired(session, now)
            norm = normalize_command(command)

            if session not in self._locks:
                return (True, False, norm, None)

            lock = self._locks[session]
            if lock.get("has_second_command"):
                return (False, False, None, "Third command ignored while lock is active")

            # Check supported combinations
            active_cmd = lock.get("active_command")
            if active_cmd == "PUSH":
                if norm in ("LEFT", "PUSH_LEFT", "HOME"):
                    return (True, True, "PUSH_LEFT", None)
                elif norm in ("RIGHT", "PUSH_RIGHT", "BACK"):
                    return (True, True, "PUSH_RIGHT", None)
            elif active_cmd == "RIGHT":
                if norm in ("PUSH", "RIGHT_PUSH"):
                    return (True, True, "RIGHT_PUSH", None)
                elif norm in ("PULL", "RIGHT_PULL"):
                    return (True, True, "RIGHT_PULL", None)
            elif active_cmd == "PULL":
                if norm in ("LEFT", "PULL_LEFT"):
                    return (True, True, "PULL_LEFT", None)
                elif norm in ("RIGHT", "PULL_RIGHT"):
                    return (True, True, "PULL_RIGHT", None)
            elif active_cmd == "LEFT":
                if norm in ("PUSH", "LEFT_PUSH"):
                    return (True, True, "LEFT_PUSH", None)
                elif norm in ("PULL", "LEFT_PULL"):
                    return (True, True, "LEFT_PULL", None)

            return (False, False, None, f"Command '{norm}' ignored during active '{active_cmd}' lock")

    def acquire_or_combine(
        self,
        session: str,
        command: str,
        command_id: Optional[str] = None,
        duration: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Attempt to acquire initial lock or form a combination.
        Guarantees that timer is never reset upon combination creation or ignored commands.
        """
        with self._lock:
            now = time.time()
            self._cleanup_expired(session, now)

            if not command_id:
                command_id = uuid.uuid4().hex

            norm_cmd = normalize_command(command)
            # Handle incoming compound strings directly if in IDLE
            COMPOUND_COMMANDS = (
                "PUSH_LEFT", "PUSH_RIGHT", "RIGHT_PUSH", "RIGHT_PULL",
                "PULL_LEFT", "PULL_RIGHT", "LEFT_PUSH", "LEFT_PULL"
            )
            if session not in self._locks and norm_cmd in COMPOUND_COMMANDS:
                dur = float(duration if duration is not None else self._default_duration)
                deadline = now + dur
                self._locks[session] = {
                    "session": session,
                    "active_command": norm_cmd,
                    "original_command": "PUSH",
                    "combination": norm_cmd,
                    "start_time": now,
                    "deadline": deadline,
                    "duration": dur,
                    "has_second_command": True,
                    "command_id": command_id,
                    "is_locked": True,
                }
                
                # Log events
                try:
                    event_history.record_event(
                        event_type=EventType.COMMAND_ACCEPTED,
                        command=norm_cmd,
                        command_id=command_id,
                        status=EventStatus.SUCCESS,
                        metadata={"session_id": session, "timer_started": now, "timer_deadline": deadline}
                    )
                    event_history.record_event(
                        event_type=EventType.COMMAND_LOCKED,
                        command=norm_cmd,
                        command_id=command_id,
                        status=EventStatus.SUCCESS,
                        metadata={"session_id": session, "timer_deadline": deadline}
                    )
                    event_history.record_event(
                        event_type=EventType.TIMER_STARTED,
                        command=norm_cmd,
                        command_id=command_id,
                        status=EventStatus.SUCCESS,
                        metadata={"session_id": session, "start_time": now, "deadline": deadline, "duration": dur}
                    )
                    if norm_cmd == "PUSH_LEFT":
                        event_history.record_event(
                            event_type=EventType.HOME_NAVIGATION,
                            command=norm_cmd,
                            command_id=command_id,
                            status=EventStatus.SUCCESS,
                            metadata={"session_id": session}
                        )
                    elif norm_cmd == "PUSH_RIGHT":
                        event_history.record_event(
                            event_type=EventType.BACK_NAVIGATION,
                            command=norm_cmd,
                            command_id=command_id,
                            status=EventStatus.SUCCESS,
                            metadata={"session_id": session}
                        )
                except Exception as e:
                    logger.debug(f"[LOCK_MANAGER] Event log error: {e}")

                return {
                    "status": "accepted",
                    "action": "locked",
                    "command": norm_cmd,
                    "timer_started": now,
                    "timer_deadline": deadline,
                    "time_remaining": dur,
                    "is_combination": True,
                    "has_second_command": True,
                }

            # 1. FIRST COMMAND - Acquire Initial Lock
            if session not in self._locks:
                dur = float(duration if duration is not None else self._default_duration)
                deadline = now + dur
                self._locks[session] = {
                    "session": session,
                    "active_command": norm_cmd,
                    "original_command": norm_cmd,
                    "combination": None,
                    "start_time": now,
                    "deadline": deadline,
                    "duration": dur,
                    "has_second_command": False,
                    "command_id": command_id,
                    "is_locked": True,
                }

                logger.info(f"[LOCK_MANAGER] Session '{session}' locked with command '{norm_cmd}' for {dur:.1f}s (deadline: {deadline:.3f})")
                print(f"[TEMPORAL] Window started\n[TEMPORAL] Start time: {now:.3f}\n[TEMPORAL] Command received: {norm_cmd}\n[TEMPORAL] Command logged")

                try:
                    event_history.record_event(
                        event_type=EventType.COMMAND_ACCEPTED,
                        command=norm_cmd,
                        command_id=command_id,
                        status=EventStatus.SUCCESS,
                        metadata={"session_id": session, "timer_started": now, "timer_deadline": deadline}
                    )
                    event_history.record_event(
                        event_type=EventType.COMMAND_LOCKED,
                        command=norm_cmd,
                        command_id=command_id,
                        status=EventStatus.SUCCESS,
                        metadata={"session_id": session, "timer_deadline": deadline}
                    )
                    event_history.record_event(
                        event_type=EventType.TIMER_STARTED,
                        command=norm_cmd,
                        command_id=command_id,
                        status=EventStatus.SUCCESS,
                        metadata={"session_id": session, "start_time": now, "deadline": deadline, "duration": dur}
                    )
                except Exception as e:
                    logger.debug(f"[LOCK_MANAGER] Event log error: {e}")

                return {
                    "status": "accepted",
                    "action": "locked",
                    "command": norm_cmd,
                    "timer_started": now,
                    "timer_deadline": deadline,
                    "time_remaining": dur,
                    "is_combination": False,
                    "has_second_command": False,
                }

            # 2. LOCK IS ACTIVE - Handle 2nd / 3rd commands
            lock = self._locks[session]
            remaining = max(0.0, lock["deadline"] - now)
            print(f"[TEMPORAL] Command received: {norm_cmd}\n[TEMPORAL] Existing temporal window active — timer NOT reset\n[TEMPORAL] Command logged")

            # If a combination is already locked (or 3rd command arrives): ALWAYS IGNORE
            if lock.get("has_second_command"):
                logger.info(f"[LOCK_MANAGER] 3rd command '{norm_cmd}' IGNORED during active combination lock '{lock['active_command']}'")
                try:
                    event_history.record_event(
                        event_type=EventType.COMMAND_IGNORED_DURING_LOCK,
                        command=norm_cmd,
                        command_id=command_id,
                        status=EventStatus.REJECTED,
                        metadata={
                            "session_id": session,
                            "active_command": lock["active_command"],
                            "reason": "Third command ignored while lock is active",
                            "timer_started": lock["start_time"],
                            "timer_deadline": lock["deadline"],
                            "time_remaining": remaining
                        }
                    )
                except Exception as e:
                    logger.debug(f"[LOCK_MANAGER] Event log error: {e}")

                return {
                    "status": "ignored",
                    "reason": "Third command ignored while lock is active",
                    "command": norm_cmd,
                    "active_command": lock["active_command"],
                    "timer_started": lock["start_time"],
                    "timer_deadline": lock["deadline"],
                    "time_remaining": remaining,
                    "is_combination": False,
                    "has_second_command": True,
                }

            # Check if this 2nd command forms a supported combination
            active_cmd = lock.get("active_command")
            combined_cmd = None
            nav_event = None

            if active_cmd == "PUSH":
                if norm_cmd in ("LEFT", "PUSH_LEFT", "HOME"):
                    combined_cmd = "PUSH_LEFT"
                    nav_event = EventType.HOME_NAVIGATION
                elif norm_cmd in ("RIGHT", "PUSH_RIGHT", "BACK"):
                    combined_cmd = "PUSH_RIGHT"
                    nav_event = EventType.BACK_NAVIGATION
            elif active_cmd == "RIGHT":
                if norm_cmd in ("PUSH", "RIGHT_PUSH"):
                    combined_cmd = "RIGHT_PUSH"
                elif norm_cmd in ("PULL", "RIGHT_PULL"):
                    combined_cmd = "RIGHT_PULL"
            elif active_cmd == "PULL":
                if norm_cmd in ("LEFT", "PULL_LEFT"):
                    combined_cmd = "PULL_LEFT"
                elif norm_cmd in ("RIGHT", "PULL_RIGHT"):
                    combined_cmd = "PULL_RIGHT"
            elif active_cmd == "LEFT":
                if norm_cmd in ("PUSH", "LEFT_PUSH"):
                    combined_cmd = "LEFT_PUSH"
                elif norm_cmd in ("PULL", "LEFT_PULL"):
                    combined_cmd = "LEFT_PULL"

            if combined_cmd:
                # Combination ACCEPTED & LOCKED
                lock["has_second_command"] = True
                lock["active_command"] = combined_cmd
                lock["combination"] = combined_cmd
                # CRITICAL: Timer MUST NOT reset or restart!
                logger.info(
                    f"[LOCK_MANAGER] Combination formed: '{combined_cmd}' in session '{session}'. "
                    f"Original timer continues unchanged (remaining: {remaining:.2f}s)"
                )

                try:
                    event_history.record_event(
                        event_type=EventType.COMBINATION_CREATED,
                        command=combined_cmd,
                        command_id=command_id,
                        status=EventStatus.SUCCESS,
                        metadata={
                            "session_id": session,
                            "original_command": active_cmd,
                            "second_command": norm_cmd,
                            "combination": combined_cmd,
                            "timer_started": lock["start_time"],
                            "timer_deadline": lock["deadline"],
                            "time_remaining": remaining
                        }
                    )
                    event_history.record_event(
                        event_type=EventType.TIMER_CONTINUED,
                        command=combined_cmd,
                        command_id=command_id,
                        status=EventStatus.SUCCESS,
                        metadata={
                            "session_id": session,
                            "timer_started": lock["start_time"],
                            "timer_deadline": lock["deadline"],
                            "time_remaining": remaining
                        }
                    )
                    if nav_event:
                        event_history.record_event(
                            event_type=nav_event,
                            command=combined_cmd,
                            command_id=command_id,
                            status=EventStatus.SUCCESS,
                            metadata={"session_id": session}
                        )
                except Exception as e:
                    logger.debug(f"[LOCK_MANAGER] Event log error: {e}")

                return {
                    "status": "accepted",
                    "action": "combined",
                    "command": combined_cmd,
                    "timer_started": lock["start_time"],
                    "timer_deadline": lock["deadline"],
                    "time_remaining": remaining,
                    "is_combination": True,
                    "has_second_command": True,
                }
            else:
                # Non-combinable 2nd command -> IGNORE
                logger.info(f"[LOCK_MANAGER] Command '{norm_cmd}' IGNORED during active lock '{active_cmd}'")
                try:
                    event_history.record_event(
                        event_type=EventType.COMMAND_IGNORED_DURING_LOCK,
                        command=norm_cmd,
                        command_id=command_id,
                        status=EventStatus.REJECTED,
                        metadata={
                            "session_id": session,
                            "active_command": active_cmd,
                            "reason": f"Command '{norm_cmd}' ignored during active '{active_cmd}' lock",
                            "timer_started": lock["start_time"],
                            "timer_deadline": lock["deadline"],
                            "time_remaining": remaining
                        }
                    )
                except Exception as e:
                    logger.debug(f"[LOCK_MANAGER] Event log error: {e}")

                return {
                    "status": "ignored",
                    "reason": f"Command '{norm_cmd}' ignored during active lock",
                    "command": norm_cmd,
                    "active_command": active_cmd,
                    "timer_started": lock["start_time"],
                    "timer_deadline": lock["deadline"],
                    "time_remaining": remaining,
                    "is_combination": False,
                    "has_second_command": False,
                }

    def reset(self, session: Optional[str] = None) -> None:
        """Explicitly release lock(s) and reset session(s) to IDLE."""
        with self._lock:
            if session is None:
                self._locks.clear()
            else:
                self.reset_lock(session)

    def reset_lock(self, session: str = "default") -> None:
        """Explicitly release lock and reset session to IDLE."""
        with self._lock:
            if session in self._locks:
                cmd = self._locks[session].get("active_command")
                cid = self._locks[session].get("command_id")
                del self._locks[session]
                try:
                    event_history.record_event(
                        event_type=EventType.COMMAND_UNLOCKED,
                        command=cmd,
                        command_id=cid,
                        status=EventStatus.SUCCESS,
                        metadata={"session_id": session, "reason": "Explicit reset"}
                    )
                except Exception:
                    pass


command_lock_manager = CommandLockManager(default_duration=4.0)
