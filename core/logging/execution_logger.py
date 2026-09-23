import logging
import os
import time
from typing import Optional, Dict, Any

log_dir = os.path.join("data", "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "execution_events.log")

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

file_handler = logging.FileHandler(log_file)
file_handler.setFormatter(formatter)

logger = logging.getLogger("execution_events")
logger.setLevel(logging.INFO)

# Only add the handler if it hasn't been added already to prevent duplicates
if not logger.handlers:
    logger.addHandler(file_handler)

class ExecutionLogger:
    def _log_event(
        self,
        event_type: str,
        execution_id: str,
        command: str,
        priority: Optional[str] = None,
        domain: Optional[str] = "N/A",
        app: Optional[str] = "N/A",
        status: Optional[str] = None,
        message: Optional[str] = None,
        error_code: Optional[str] = None,
        duration: Optional[float] = None
    ):
        """Internal method to format and write the event."""
        try:
            log_parts = [
                f"[EVENT={event_type}]",
                f"[EXEC_ID={execution_id}]",
                f"[CMD={command}]"
            ]
            
            if priority:
                log_parts.append(f"[PRIORITY={priority}]")
            if domain and domain != "N/A":
                log_parts.append(f"[DOMAIN={domain}]")
            if app and app != "N/A":
                log_parts.append(f"[APP={app}]")
            if status:
                log_parts.append(f"[STATUS={status}]")
            if error_code:
                log_parts.append(f"[ERROR_CODE={error_code}]")
            if duration is not None:
                log_parts.append(f"[DURATION={duration:.2f}ms]")
            if message:
                log_parts.append(f"[MSG={message}]")

            logger.info(" ".join(log_parts))
        except Exception as e:
            # Prevent logging failures from breaking execution
            fallback_logger = logging.getLogger("execution_logger_fallback")
            fallback_logger.error(f"Failed to log execution event: {e}")

    def log_command_received(self, execution_id: str, command: str):
        self._log_event("COMMAND_RECEIVED", execution_id, command)

    def log_priority_assigned(self, execution_id: str, command: str, priority: str):
        self._log_event("PRIORITY_ASSIGNED", execution_id, command, priority=priority)

    def log_execution_started(self, execution_id: str, command: str, priority: str, domain: str, app: str):
        self._log_event("EXECUTION_STARTED", execution_id, command, priority=priority, domain=domain, app=app)

    def log_execution_completed(self, execution_id: str, command: str, priority: str, duration: float):
        self._log_event("EXECUTION_COMPLETED", execution_id, command, priority=priority, status="SUCCESS", duration=duration)

    def log_execution_failed(self, execution_id: str, command: str, priority: str, duration: float, error_code: str, message: str):
        self._log_event("EXECUTION_FAILED", execution_id, command, priority=priority, status="FAILED", duration=duration, error_code=error_code, message=message)

    def log_execution_cancelled(self, execution_id: str, command: str, priority: str, duration: float):
        self._log_event("EXECUTION_CANCELLED", execution_id, command, priority=priority, status="CANCELLED", duration=duration)

execution_logger = ExecutionLogger()
