import time
from typing import Optional, Any
from pydantic import BaseModel, Field
from datetime import datetime

class ExecutionResult(BaseModel):
    """
    Standard execution result representation.
    Designed to be compatible with existing dictionary-based consumers via .model_dump().
    """
    success: bool
    status: str
    command: Optional[str] = None
    message: Optional[str] = None
    error_code: Optional[str] = None
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)
    data: Optional[Any] = None
    execution_time_ms: Optional[float] = None
    
    # Extra fields for backward compatibility
    resolved: Optional[Any] = None
    executed: Optional[bool] = None
    validation: Optional[Any] = None
    state: Optional[Any] = None
    action_result: Optional[Any] = None

    def to_dict(self) -> dict:
        """
        Converts to a dictionary, dropping None values to keep responses clean
        while ensuring required fields are present.
        """
        base_dict = self.model_dump(exclude_none=True)
        # Ensure 'status' is always there even if it wasn't strictly success
        if not self.success and "status" not in base_dict:
            base_dict["status"] = "failed"
        elif self.success and "status" not in base_dict:
            base_dict["status"] = "success"
        
        # Serialize datetime if present
        if "timestamp" in base_dict and isinstance(base_dict["timestamp"], datetime):
            base_dict["timestamp"] = base_dict["timestamp"].isoformat()
            
        return base_dict
