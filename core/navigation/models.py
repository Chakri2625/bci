from pydantic import BaseModel
from typing import Optional, Any

class NavigationRequest(BaseModel):
    command: str
    device_id: Optional[str] = None

class NavigationResponse(BaseModel):
    command: str
    current_domain: Optional[str] = None
    target_domain: Optional[str] = None
    status: str
    error: Optional[str] = None
    action_result: Optional[Any] = None
    state: Optional[dict] = None
    recovery_attempted: Optional[bool] = False
    recovery_status: Optional[str] = None
    recovery_action: Optional[str] = None
    recovery_error: Optional[str] = None

class NavigationStateResponse(BaseModel):
    current_domain: Optional[str] = None
    active_app: Optional[str] = None
    active_mode: Optional[str] = None
    last_command: Optional[str] = None
    current_level: int
    command_history: list[str]
