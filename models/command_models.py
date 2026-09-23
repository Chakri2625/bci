from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LifecycleTransitionModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    from_stage: str | None = None
    to_stage: str
    timestamp: float | None = None
    reason: str | None = None
    metadata: dict = Field(default_factory=dict)


class CommandLifecycleModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    command_id: str
    command: str
    session_id: str | None = None
    current_stage: str
    created_at: float | None = None
    created_at_iso: str | None = None
    started_at: float | None = None
    started_at_iso: str | None = None
    completed_at: float | None = None
    completed_at_iso: str | None = None
    duration_ms: float | None = None
    duration_s: float | None = None
    updated_at: float | None = None
    is_terminal: bool = False
    priority: str | None = None
    domain: str | None = None
    target: str | None = None
    retry_count: int = 0
    max_retries: int = 3
    error: str | None = None
    result: dict | None = None
    history: list[LifecycleTransitionModel] = Field(default_factory=list)


CommandType = Literal[
    "PUSH",
    "PULL",
    "LEFT",
    "RIGHT",
    "PUSH_LEFT",
    "PUSH_RIGHT",
]


class NavigationCommand(BaseModel):
    """
    Validated SynaptiMesh command.

    This model represents the command received by the
    routing layer.
    """

    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(
        ...,
        pattern=r"^CMD-[0-9]{4,}$",
        description="Unique command identifier"
    )

    command: CommandType = Field(
        ...,
        description="SynaptiMesh command"
    )

    timestamp: datetime = Field(
        ...,
        description="Command timestamp"
    )


class CommandResponse(BaseModel):
    """
    Standard successful command response.
    """

    status: Literal["success", "error"]

    command_id: str | None = None

    message: str

    result: dict | None = None


class CommandErrorResponse(BaseModel):
    """
    Standard error response for invalid commands.
    """

    status: Literal["error"] = "error"

    error_code: str

    message: str

    details: list | None = None