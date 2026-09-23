from datetime import datetime
import os
import json
import asyncio
import time
import uuid
from datetime import datetime, timezone
import logging
from typing import Optional, Any, Callable, Dict

try:
    from core.config.retry_config import is_retryable_error, MAX_RETRIES, RETRY_DELAY, COMMAND_TIMEOUT
except ImportError:
    is_retryable_error = None
    MAX_RETRIES = 3
    RETRY_DELAY = 1.0
    COMMAND_TIMEOUT = 10.0

try:
    from core.logging.terminal_display import format_execution_box, display_execution_summary, format_utc_iso
except ImportError:
    format_execution_box = None
    display_execution_summary = None
    def format_utc_iso(ts=None):
        t = ts if ts is not None else time.time()
        dt = datetime.fromtimestamp(t, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

try:
    from core.managers.lifecycle_tracker import lifecycle_tracker, CommandLifecycleStage
except ImportError:
    lifecycle_tracker = None
    CommandLifecycleStage = None

try:
    from core.state.state_manager import state_manager
except ImportError:
    state_manager = None

try:
    from core.events.event_bus import event_bus
except ImportError:
    event_bus = None

try:
    from core.logging.structured_logger import structured_logger
except ImportError:
    structured_logger = None

logger = logging.getLogger("retry_manager")
LOGS_FILE = "data/logs.json"


class RetryManager:
    def __init__(
        self,
        max_attempts: int = 3,
        retry_delay: float = 1.0,
        command_timeout: float = 10.0,
        max_retries: Optional[int] = None
    ):
        self.max_attempts = max_retries if max_retries is not None else max_attempts
        self.retry_delay = retry_delay
        self.command_timeout = command_timeout
        self._cancelled_commands = set()
        os.makedirs("data", exist_ok=True)
        if not os.path.exists(LOGS_FILE):
            with open(LOGS_FILE, "w", encoding="utf-8") as f:
                json.dump([], f)

    def cancel_command(self, command_id: str) -> None:
        """Cancel a command by ID to stop its retry loop."""
        self._cancelled_commands.add(command_id)

    def is_cancelled(self, command_id: str) -> bool:
        """Check if command was cancelled."""
        return command_id in self._cancelled_commands

    def log_retry(self, command: str, attempt: int, status: str, reason: str = None):
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "command": command,
            "attempt": attempt,
            "status": status,
            "reason": reason
        }
        try:
            with open(LOGS_FILE, "r", encoding="utf-8") as f:
                logs = json.load(f)
        except Exception:
            logs = []
            
        logs.append(log_entry)
        
        try:
            with open(LOGS_FILE, "w", encoding="utf-8") as f:
                json.dump(logs, f, indent=4)
        except Exception:
            pass

    def is_temporary_failure(self, error_msg: str) -> bool:
        """
        Returns True if the error is considered temporary and should be retried.
        """
        if is_retryable_error:
            return is_retryable_error(error_msg)

        error_msg = str(error_msg).lower()
        temporary_keywords = [
            "timeout", "timed out", "not responding", "busy", "connection loss", "temporary",
            "error", "disconnected", "unavailable", "unreachable", "refused",
            "broken pipe", "connection reset"
        ]
        if "missing device_id" in error_msg or "invalid command" in error_msg or "validation" in error_msg:
            return False
            
        for kw in temporary_keywords:
            if kw in error_msg:
                return True
        return False

    async def execute_with_retry(
        self,
        command_name: str,
        session: str = "default",
        state_updater_cb: Optional[Callable] = None,
        func: Optional[Callable] = None,
        *args,
        command_id: Optional[str] = None,
        stream: Optional[Any] = None,
        cancel_token: Optional[Any] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Executes a function with up to max_attempts for temporary failures.
        Updates state dynamically and supports stream output and standardized responses.
        """
        cid = command_id or f"CMD-{uuid.uuid4().hex[:6].upper()}"
        sid = session or "SESSION-001"
        effective_func = func or kwargs.pop("fn", None)
        
        # If func was passed as positional arg or keyword
        if effective_func is None and state_updater_cb and callable(state_updater_cb) and not inspect_is_cb(state_updater_cb):
            # Signature was (command_name, session, func, ...)
            effective_func = state_updater_cb
            state_updater_cb = None

        start_ts = time.time()
        start_iso = format_utc_iso(start_ts)
        last_exception = None
        last_result = None
        encountered_timeout = False

        if stream:
            stream.write(f"[{format_utc_iso()}] Command Received: {command_name} (ID: {cid}, Session: {sid})\n")
            stream.flush()

        for attempt in range(1, self.max_attempts + 1):
            if stream:
                stream.write(f"Attempt: {attempt}/{self.max_attempts}\n")
                stream.flush()

            if attempt > 1:
                if state_updater_cb:
                    try:
                        state_updater_cb(attempt, "RETRYING", last_exception)
                    except Exception:
                        pass
                if stream:
                    stream.write(f"[RETRY] Attempt {attempt}/{self.max_attempts} after {self.retry_delay}s delay\n")
                    stream.flush()

                # Sleep with cancellation polling
                slept = 0.0
                step = 0.02
                cancelled = False
                while slept < self.retry_delay:
                    if (cancel_token and getattr(cancel_token, "is_cancelled", False)) or cid in self._cancelled_commands:
                        cancelled = True
                        break
                    to_sleep = min(step, self.retry_delay - slept)
                    await asyncio.sleep(to_sleep)
                    slept += to_sleep

                if cancelled or (cancel_token and getattr(cancel_token, "is_cancelled", False)) or cid in self._cancelled_commands:
                    comp_ts = time.time()
                    if stream:
                        stream.write("Status: CANCELLED\n")
                        stream.flush()
                    return {
                        "type": "RESPONSE",
                        "command_id": cid,
                        "session_id": sid,
                        "command": command_name,
                        "status": "CANCELLED",
                        "attempt": attempt - 1,
                        "max_attempts": self.max_attempts,
                        "retry_count": attempt - 2,
                        "timeout": encountered_timeout,
                        "error": "Cancelled during retry delay",
                        "result": None,
                        "duration_seconds": round(comp_ts - start_ts, 3),
                        "start_time": start_iso,
                        "completion_time": format_utc_iso(comp_ts),
                    }
            else:
                if state_updater_cb:
                    try:
                        state_updater_cb(attempt, "READY", None)
                    except Exception:
                        pass

            try:
                if effective_func is None:
                    res = {"status": "success"}
                else:
                    if self.command_timeout and self.command_timeout > 0:
                        res = await asyncio.wait_for(
                            effective_func(*args, **kwargs),
                            timeout=self.command_timeout
                        )
                    else:
                        res = await effective_func(*args, **kwargs)

                # Check if dictionary returned error
                if isinstance(res, dict) and res.get("status") in ("error", "failed"):
                    msg = res.get("message") or res.get("error") or "Execution failed"
                    if self.is_temporary_failure(msg):
                        raise Exception(msg)
                    else:
                        # Non-retryable failure
                        self.log_retry(command_name, attempt, "FAILED", msg)
                        if state_updater_cb:
                            try:
                                state_updater_cb(attempt, "FAILED", msg)
                            except Exception:
                                pass
                        comp_ts = time.time()
                        comp_iso = format_utc_iso(comp_ts)
                        dur_sec = max(0.0, round(comp_ts - start_ts, 3))
                        if stream:
                            stream.write(f"Status: FAILED\nAttempts: {attempt}/{self.max_attempts}\nRetry Count: {attempt - 1}\nFinal Status  : FAILED\nEXECUTION SUMMARY\n")
                            stream.flush()
                        return {
                            "type": "RESPONSE",
                            "command_id": cid,
                            "session_id": sid,
                            "command": command_name,
                            "status": "FAILED",
                            "attempt": attempt,
                            "max_attempts": self.max_attempts,
                            "retry_count": attempt - 1,
                            "timeout": encountered_timeout,
                            "error": msg,
                            "result": res,
                            "duration_seconds": dur_sec,
                            "start_time": start_iso,
                            "completion_time": comp_iso,
                            "reason": msg,
                        }

                # Success
                self.log_retry(command_name, attempt, "SUCCESS")
                if state_updater_cb:
                    try:
                        state_updater_cb(attempt, "SUCCESS", None)
                    except Exception:
                        pass
                comp_ts = time.time()
                comp_iso = format_utc_iso(comp_ts)
                dur_sec = max(0.0, round(comp_ts - start_ts, 3))
                if stream:
                    stream.write(f"Status: COMPLETED\nAttempts: {attempt}/{self.max_attempts}\nRetry Count: {attempt - 1}\nFinal Status  : COMPLETED\nEXECUTION SUMMARY\n")
                    stream.flush()
                return {
                    "type": "RESPONSE",
                    "command_id": cid,
                    "session_id": sid,
                    "command": command_name,
                    "status": "COMPLETED",
                    "attempt": attempt,
                    "max_attempts": self.max_attempts,
                    "retry_count": attempt - 1,
                    "timeout": encountered_timeout,
                    "error": None,
                    "result": res,
                    "duration_seconds": dur_sec,
                    "start_time": start_iso,
                    "completion_time": comp_iso,
                }

            except (asyncio.TimeoutError, TimeoutError):
                encountered_timeout = True
                err_msg = f"Command timed out after {self.command_timeout} seconds"
                last_exception = err_msg
                self.log_retry(command_name, attempt, "TIMEOUT", err_msg)
                
                # TASK 1: Integrate timeout with lifecycle tracker
                if lifecycle_tracker:
                    try:
                        timeout_duration_ms = round((time.time() - start_ts) * 1000.0, 2)
                        lifecycle_tracker.track_timeout(
                            cid,
                            reason=err_msg,
                            timeout_duration_ms=timeout_duration_ms,
                            metadata={"domain": kwargs.get("plugin_id"), "attempt": attempt}
                        )
                    except Exception as e:
                        logger.debug(f"Lifecycle tracker timeout integration failed: {e}")
                
                # TASK 2: Update state manager with timeout
                if state_manager:
                    try:
                        state_manager.record_failure(
                            command_id=cid,
                            domain=kwargs.get("plugin_id", "SYSTEM"),
                            affected_component=f"{kwargs.get('plugin_id', 'System')} Execution",
                            failure_type="TIMEOUT",
                            failure_reason=err_msg,
                            error_source="RetryManager",
                            recovery_status="RECOVERY_FAILED",
                            session=sid
                        )
                        # Update timeout counter in metrics
                        with state_manager._lock:
                            state_manager.system_state["metrics"]["timed_out"] = \
                                state_manager.system_state["metrics"].get("timed_out", 0) + 1
                    except Exception as e:
                        logger.debug(f"State manager timeout integration failed: {e}")
                
                # TASK 2: Publish timeout event to event bus
                if event_bus:
                    try:
                        timeout_payload = {
                            "command": command_name,
                            "command_id": cid,
                            "session_id": sid,
                            "domain": kwargs.get("plugin_id"),
                            "status": "TIMEOUT",
                            "error": err_msg,
                            "timeout_duration_ms": round((time.time() - start_ts) * 1000.0, 2),
                            "attempt": attempt,
                            "execution_duration": round((time.time() - start_ts) * 1000.0, 2)
                        }
                        # asyncio is imported at module level - do NOT re-import here
                        # (a local import would shadow the module-level name and break
                        # the `except (asyncio.TimeoutError, ...)` clause evaluation)
                        asyncio.create_task(event_bus.publish("COMMAND_TIMEOUT", timeout_payload))
                    except Exception as e:
                        logger.debug(f"Event bus timeout publishing failed: {e}")
                
                # TASK 2: Log timeout via structured logger
                if structured_logger:
                    try:
                        structured_logger.log_execution_failed(
                            execution_id=cid,
                            command=command_name,
                            priority="NORMAL",
                            domain=kwargs.get("plugin_id", "SYSTEM"),
                            duration=round((time.time() - start_ts) * 1000.0, 2),
                            error_code="TIMEOUT",
                            message=err_msg
                        )
                    except Exception as e:
                        logger.debug(f"Structured logger timeout integration failed: {e}")
                
                if stream:
                    stream.write(f"COMMAND TIMEOUT: Command {cid} timed out after {self.command_timeout}s\n")
                    stream.flush()
                if state_updater_cb:
                    try:
                        state_updater_cb(attempt, "TIMEOUT", err_msg)
                    except Exception:
                        pass

            except Exception as e:
                err_msg = str(e)
                if self.is_temporary_failure(err_msg):
                    last_exception = err_msg
                    self.log_retry(command_name, attempt, "RETRYING", err_msg)
                else:
                    self.log_retry(command_name, attempt, "FAILED", err_msg)
                    if state_updater_cb:
                        try:
                            state_updater_cb(attempt, "FAILED", err_msg)
                        except Exception:
                            pass
                    comp_ts = time.time()
                    comp_iso = format_utc_iso(comp_ts)
                    dur_sec = max(0.0, round(comp_ts - start_ts, 3))
                    if stream:
                        stream.write(f"Status: FAILED\nAttempts: {attempt}/{self.max_attempts}\nRetry Count: {attempt - 1}\nFinal Status  : FAILED\nEXECUTION SUMMARY\n")
                        stream.flush()
                    return {
                        "type": "RESPONSE",
                        "command_id": cid,
                        "session_id": sid,
                        "command": command_name,
                        "status": "FAILED",
                        "attempt": attempt,
                        "max_attempts": self.max_attempts,
                        "retry_count": attempt - 1,
                        "timeout": encountered_timeout,
                        "error": err_msg,
                        "result": None,
                        "duration_seconds": dur_sec,
                        "start_time": start_iso,
                        "completion_time": comp_iso,
                        "reason": err_msg,
                    }

        # All retries exhausted
        self.log_retry(command_name, self.max_attempts, "FAILED", last_exception)
        if state_updater_cb:
            try:
                state_updater_cb(self.max_attempts, "FAILED", last_exception)
            except Exception:
                pass
        comp_ts = time.time()
        comp_iso = format_utc_iso(comp_ts)
        dur_sec = max(0.0, round(comp_ts - start_ts, 3))
        if stream:
            stream.write(f"Status: FAILED\nAttempts: {self.max_attempts}/{self.max_attempts}\nRetry Count: {self.max_attempts - 1}\nFinal Status  : FAILED\nEXECUTION SUMMARY\n")
            stream.flush()
        return {
            "type": "RESPONSE",
            "command_id": cid,
            "session_id": sid,
            "command": command_name,
            "status": "FAILED",
            "attempt": self.max_attempts,
            "max_attempts": self.max_attempts,
            "retry_count": self.max_attempts - 1,
            "timeout": encountered_timeout,
            "error": last_exception or "Retries exhausted",
            "result": None,
            "duration_seconds": dur_sec,
            "start_time": start_iso,
            "completion_time": comp_iso,
            "reason": last_exception,
        }


def inspect_is_cb(fn) -> bool:
    try:
        import inspect
        params = list(inspect.signature(fn).parameters.keys())
        return len(params) >= 3 and params[0] in ("attempt", "att")
    except Exception:
        return False


retry_manager = RetryManager()
