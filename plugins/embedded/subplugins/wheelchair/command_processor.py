"""
BCI Command Processor (Wheelchair)
===================================
Filters, debounces, logs, and maps BCI mental-command streams into safe,
actionable motor commands for the Smart Wheelchair. Structurally identical
to plugins/embedded/subplugins/rc_car/command_processor.py so both Embedded
devices share the same safety guarantees (confidence threshold, debounce,
watchdog auto-stop, CSV telemetry).
"""

import csv
import logging
import time
from datetime import datetime
from typing import Callable, Optional, Tuple

from . import config

logger = logging.getLogger("WheelchairCommandProcessor")


class WheelchairCommandProcessor:
    """
    Processes raw BCI stream inputs with safety thresholds, debouncing, duplicate
    filtering, auto-stop timeouts, and CSV telemetry logging for the wheelchair.
    """

    def __init__(self,
                 on_action_ready: Optional[Callable[[str, str, float], None]] = None,
                 confidence_threshold: float = config.CONFIDENCE_THRESHOLD,
                 debounce_interval: float = config.DEBOUNCE_INTERVAL_SECONDS,
                 csv_path: str = str(config.CSV_LOG_PATH)):

        self.on_action_ready = on_action_ready
        self.confidence_threshold = confidence_threshold
        self.debounce_interval = debounce_interval
        self.csv_path = csv_path

        self.last_command: Optional[str] = None
        self.last_external_command: Optional[str] = None
        self.last_command_time: float = 0.0
        self.last_executed_time: float = 0.0
        self.active_state: str = "STOP"

        self._init_csv_log()

    def _init_csv_log(self):
        try:
            with open(self.csv_path, mode="a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if f.tell() == 0:
                    writer.writerow([
                        "Timestamp",
                        "Mental_Command",
                        "Confidence",
                        "Execution_Status",
                        "Network_Latency_ms",
                        "Motor_Command",
                        "Error"
                    ])
        except Exception as e:
            logger.error(f"Failed to initialize CSV log file: {e}")

    def log_telemetry(self,
                      mental_command: str,
                      confidence: float,
                      status: str,
                      latency_ms: float = 0.0,
                      motor_command: str = "STOP",
                      error_msg: str = "None"):
        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        try:
            with open(self.csv_path, mode="a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    timestamp_str,
                    mental_command,
                    f"{confidence:.4f}",
                    status,
                    f"{latency_ms:.2f}",
                    motor_command,
                    error_msg
                ])
        except Exception as e:
            logger.error(f"Error writing to CSV log: {e}")

    def process_command(self, raw_command: str, confidence: float) -> Tuple[bool, str, str]:
        """
        Evaluates an incoming BCI command frame against safety rules and maps to
        the external payload.

        Returns:
            (executed: bool, status_msg: str, external_command: str)
        """
        current_time = time.time()
        command = raw_command.strip().upper()

        if command not in config.COMMAND_MAP:
            status = f"REJECTED_UNKNOWN_COMMAND ({command})"
            logger.warning(f"Safety Rejection: Unknown command '{command}'")
            self.log_telemetry(command, confidence, status, motor_command="STOP", error_msg="Unknown command string")
            return False, status, "STOP"

        external_command = config.COMMAND_MAP[command]

        if confidence < self.confidence_threshold:
            status = f"REJECTED_LOW_CONFIDENCE ({confidence:.2f} < {self.confidence_threshold})"
            logger.info(f"Filtered BCI command '{command}': Low confidence ({confidence:.2f} < {self.confidence_threshold})")
            self.log_telemetry(command, confidence, status, motor_command=self.active_state, error_msg="Low confidence")
            return False, status, self.active_state

        time_since_last = current_time - self.last_executed_time
        if command == self.last_command and time_since_last < self.debounce_interval:
            status = f"IGNORED_DEBOUNCED ({time_since_last:.3f}s < {self.debounce_interval}s)"
            logger.debug(f"Debounced duplicate command '{command}' within {self.debounce_interval}s window.")
            self.log_telemetry(command, confidence, status, motor_command=self.active_state)
            return False, status, self.active_state

        self.last_command = command
        self.last_external_command = external_command
        self.last_command_time = current_time
        self.last_executed_time = current_time
        self.active_state = command

        status = "EXECUTED_SUCCESS"
        logger.info(f"ACCEPTED BCI COMMAND: '{command}' (conf={confidence:.2f}) -> Payload: '{external_command}'")

        if self.on_action_ready:
            try:
                self.on_action_ready(external_command, command, confidence)
            except Exception as e:
                logger.error(f"Error in on_action_ready handler: {e}")
                self.log_telemetry(command, confidence, "EXECUTION_ERROR", motor_command=external_command, error_msg=str(e))
                return False, "EXECUTION_ERROR", external_command

        self.log_telemetry(command, confidence, status, motor_command=external_command)
        return True, status, external_command

    def check_watchdog_timeout(self) -> bool:
        """
        Checks if the safety timeout has elapsed since the last valid command.
        If timed out while moving, forces a STOP action.
        """
        current_time = time.time()
        if self.active_state != "STOP":
            if (current_time - self.last_command_time) > config.SAFETY_AUTO_STOP_TIMEOUT:
                logger.warning(f"SAFETY WATCHDOG EXPIRED (> {config.SAFETY_AUTO_STOP_TIMEOUT}s without command)! Forcing STOP.")
                self.active_state = "STOP"
                stop_payload = config.COMMAND_MAP.get("STOP", "WHEELCHAIRSTOP")
                if self.on_action_ready:
                    self.on_action_ready(stop_payload, "STOP", 1.0)
                self.log_telemetry("STOP", 1.0, "SAFETY_TIMEOUT_AUTO_STOP", motor_command=stop_payload, error_msg="Command stream timeout")
                return True
        return False
