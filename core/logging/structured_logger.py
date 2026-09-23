import logging
import json
import os
import threading
from typing import Optional, Dict, Any
from core.logging.log_schema import StructuredLogEvent, LogLevel, EventType

class JSONFormatter(logging.Formatter):
    def format(self, record):
        if hasattr(record, 'json_data'):
            return json.dumps(record.json_data)
        
        # Fallback for standard log messages
        fallback_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "log_level": record.levelname,
            "message": record.getMessage()
        }
        return json.dumps(fallback_data)

class StructuredLogger:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(StructuredLogger, cls).__new__(cls)
                cls._instance._initialize()
            return cls._instance

    def _initialize(self):
        self.logger = logging.getLogger("synaptimesh_structured")
        self.logger.setLevel(logging.DEBUG)

        if not self.logger.handlers:
            # Ensure the logs directory exists
            log_dir = os.path.join("data", "logs")
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, "structured.log")

            # File handler
            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(JSONFormatter())
            self.logger.addHandler(file_handler)

            # Console handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(JSONFormatter())
            self.logger.addHandler(console_handler)

    def log_event(self, event_type: str, level: str = LogLevel.INFO.value, **kwargs):
        event = StructuredLogEvent(
            event_type=event_type,
            log_level=level,
            **kwargs
        )
        
        log_level_map = {
            LogLevel.DEBUG.value: logging.DEBUG,
            LogLevel.INFO.value: logging.INFO,
            LogLevel.WARNING.value: logging.WARNING,
            LogLevel.ERROR.value: logging.ERROR,
            LogLevel.CRITICAL.value: logging.CRITICAL,
        }
        
        log_method_level = log_level_map.get(level.upper(), logging.INFO)
        
        # Add json_data to the record so the formatter can pick it up
        extra = {"json_data": event.to_dict()}
        self.logger.log(log_method_level, event.message or f"Event: {event.event_type}", extra=extra)

    # Helper methods
    def log_command_received(self, **kwargs):
        self.log_event(EventType.COMMAND_RECEIVED.value, **kwargs)
        
    def log_command_routed(self, **kwargs):
        self.log_event(EventType.COMMAND_ROUTED.value, **kwargs)
        
    def log_execution_started(self, **kwargs):
        self.log_event(EventType.EXECUTION_STARTED.value, **kwargs)
        
    def log_execution_completed(self, **kwargs):
        self.log_event(EventType.EXECUTION_COMPLETED.value, **kwargs)
        
    def log_execution_failed(self, **kwargs):
        self.log_event(EventType.EXECUTION_FAILED.value, level=LogLevel.ERROR.value, **kwargs)
        
    def log_response_sent(self, **kwargs):
        self.log_event(EventType.RESPONSE_SENT.value, **kwargs)

structured_logger = StructuredLogger()
