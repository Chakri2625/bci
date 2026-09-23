from enum import Enum
from typing import Dict, Any, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

class EventType(str, Enum):
    COMMAND_RECEIVED = "COMMAND_RECEIVED"
    COMMAND_ROUTED = "COMMAND_ROUTED"
    PRIORITY_ASSIGNED = "PRIORITY_ASSIGNED"
    EXECUTION_STARTED = "EXECUTION_STARTED"
    EXECUTION_COMPLETED = "EXECUTION_COMPLETED"
    RESPONSE_SENT = "RESPONSE_SENT"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    RETRY_STARTED = "RETRY_STARTED"
    SESSION_STARTED = "SESSION_STARTED"
    SESSION_ENDED = "SESSION_ENDED"
    
@dataclass
class StructuredLogEvent:
    event_type: str
    log_level: str
    request_id: Optional[str] = None
    execution_id: Optional[str] = None
    command_id: Optional[str] = None
    session_id: Optional[str] = None
    domain: Optional[str] = None
    command: Optional[str] = None
    status: Optional[str] = None
    message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))

    def to_dict(self):
        return asdict(self)
