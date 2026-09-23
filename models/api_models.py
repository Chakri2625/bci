"""
api_models.py
=============
Standard Pydantic V2 Request & Response Models for SynaptiMesh REST APIs.
Used for route validation, serialization, and openapi schema generation.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field

from models.command_models import CommandErrorResponse, CommandResponse
from models.device_models import DeviceState
from models.telemetry_models import (
    AiMlTelemetry,
    BciTelemetry,
    EmbeddedTelemetry,
    IotTelemetry,
    UnifiedTelemetryPacket,
)


# ===========================================================================
# 1. Health & Diagnostics Response Models
# ===========================================================================

class DomainHealthInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    online: bool = Field(..., description="Whether the domain service is reachable")
    label: str = Field(..., description="Human-readable domain label")
    transport: str = Field(..., description="Communication transport description")


class SystemHealthResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str = Field("online", description="Overall system health status")
    server: bool = Field(True, description="HTTP API server running status")
    online_count: int = Field(..., description="Count of online operational domains")
    total_domains: int = Field(4, description="Total registered ecosystem domains")
    broker_connected: bool = Field(..., description="MQTT broker connectivity status")
    domains: Dict[str, DomainHealthInfo] = Field(..., description="Health status per domain")


class PlatformDiagnostics(BaseModel):
    model_config = ConfigDict(extra="ignore")

    system: str = Field(..., description="Host OS platform name")
    release: str = Field(..., description="OS release version")
    python_version: str = Field(..., description="Active Python runtime version")
    pid: int = Field(..., description="Process ID of the API server")


class ResourceDiagnostics(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cpu_percent: float = Field(..., description="Current host CPU utilization percentage")
    ram_percent: float = Field(..., description="Current host RAM utilization percentage")
    active_threads: int = Field(..., description="Number of active daemon execution threads")


class TransportDiagnostics(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mqtt_broker: str = Field(..., description="Configured MQTT broker endpoint")
    ipc_status: str = Field(..., description="Local IPC channel state")
    latency_ms: float = Field(..., description="Estimated transport latency in milliseconds")
    throughput_msg_per_sec: float = Field(..., description="Average throughput messages per second")


class DiagnosticsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str = Field("success", description="Diagnostics status outcome")
    timestamp: float = Field(default_factory=time.time, description="Unix timestamp of diagnostic sample")
    platform: PlatformDiagnostics = Field(..., description="Host platform and runtime information")
    resources: ResourceDiagnostics = Field(..., description="Host system resource utilization")
    transport_metrics: TransportDiagnostics = Field(..., description="Transport network health metrics")


# ===========================================================================
# 2. State & Session Response Models
# ===========================================================================

class SequenceValidationState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    previous_command: Optional[str] = None
    current_command: Optional[str] = None
    status: str = "READY"
    is_valid: Optional[bool] = None
    allowed_next_commands: List[str] = Field(default_factory=list)
    rejection_reason: Optional[str] = None
    current_state: Dict[str, Any] = Field(default_factory=dict)


class SessionStateResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    session_id: str = Field(..., description="Active session identifier")
    active_domain: Optional[str] = Field(None, description="Currently selected domain")
    active_app: Optional[str] = Field(None, description="Active application under domain")
    active_mode: Optional[str] = Field(None, description="Active sub-operational mode")
    last_command: Optional[str] = Field(None, description="Last processed command")
    previous_command: Optional[str] = Field(None, description="Preceding command in sequence")
    current_level: int = Field(1, description="FSM navigation hierarchy level (1, 2, 3)")
    command_history: List[Any] = Field(default_factory=list, description="Historical commands in session")
    commands: Dict[str, Any] = Field(default_factory=dict, description="Session command state dict")
    retry_status: Optional[str] = Field("READY", description="Command retry manager status")
    retry_attempt: Optional[int] = Field(1, description="Current retry attempt index")
    retry_reason: Optional[str] = None
    action_status: Optional[str] = None
    action_logs: List[Any] = Field(default_factory=list)
    last_command_id: Optional[str] = None
    lifecycle_stage: Optional[str] = Field("CREATED", description="Last lifecycle stage")
    sequence_validation: Optional[Union[SequenceValidationState, Dict[str, Any]]] = None
    command_lock: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None


class SystemMetrics(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total_commands: int = 0
    successful: int = 0
    failed: int = 0
    cancelled: int = 0
    timed_out: int = 0


class SystemPerformance(BaseModel):
    model_config = ConfigDict(extra="ignore")

    avg_execution_latency_ms: float = 0.0
    recent_execution_latency_ms: float = 0.0
    avg_processing_latency_ms: float = 0.0
    recent_processing_latency_ms: float = 0.0
    total_measured_commands: int = 0
    bottleneck_status: str = "OPTIMAL"
    bottleneck_indicators: List[str] = Field(default_factory=list)
    stage_breakdown_ms: Dict[str, float] = Field(default_factory=dict)


class FailureTracking(BaseModel):
    model_config = ConfigDict(extra="ignore")

    last_failure: Optional[Any] = None
    active_failures_count: int = 0
    total_failures_recorded: int = 0
    recovery_summary: Dict[str, int] = Field(default_factory=dict)
    failure_history: List[Any] = Field(default_factory=list)


class SystemStateResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    system_status: str = Field("IDLE", description="Overall system operational status")
    execution_state: str = Field("IDLE", description="Active execution state machine state")
    active_tasks_count: int = Field(0, description="Number of currently running tasks")
    last_activity_timestamp: float = Field(default_factory=time.time, description="Timestamp of last activity")
    metrics: SystemMetrics = Field(default_factory=SystemMetrics, description="Aggregated command execution metrics")
    performance: SystemPerformance = Field(default_factory=SystemPerformance, description="System performance & latency telemetry")
    failure_tracking: FailureTracking = Field(default_factory=FailureTracking, description="Failure and recovery metrics")


class DomainStateResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    domain: str = Field(..., description="Domain name (DESKTOP, EMBEDDED, IOT, AIML, BCI, etc.)")
    status: str = Field("READY", description="Domain operational status (READY, BUSY, ERROR, DEGRADED)")
    session_active: bool = Field(False, description="Whether an active session is routed to this domain")
    current_level: int = Field(1, description="FSM navigation level within domain")
    active_app: Optional[str] = Field(None, description="Active application in domain")
    last_action: Optional[str] = Field(None, description="Last action executed on domain")
    last_action_timestamp: Optional[float] = None
    failure_reason: Optional[str] = None
    failure_type: Optional[str] = None
    affected_component: Optional[str] = None
    recovery_status: Optional[str] = "NONE"
    recovery_attempt: int = 0
    last_failure_timestamp: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    device_state: Optional[Union[DeviceState, Dict[str, Any]]] = Field(None, description="Device-state payload (Member 4)")
    telemetry: Optional[Union[UnifiedTelemetryPacket, Dict[str, Any]]] = Field(None, description="Domain telemetry (Member 3)")


# ===========================================================================
# 3. Lifecycle Summary Response Models
# ===========================================================================

class LifecycleSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total_commands: int = Field(..., description="Total commands recorded in lifecycle")
    active_commands: int = Field(..., description="Currently active / non-terminal commands")
    stage_counts: Dict[str, int] = Field(..., description="Command counts grouped by lifecycle stage")
    avg_duration_ms: float = Field(..., description="Average execution duration in milliseconds")
    session_id: str = Field("all", description="Session identifier filter")


class LifecycleSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str = Field("success", description="Status outcome")
    summary: LifecycleSummary = Field(..., description="Command lifecycle summary telemetry")


# ===========================================================================
# 4. IoT Response Models
# ===========================================================================

class IoTStatusResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    connected: bool = Field(..., description="MQTT connection status for IoT plugin")
    broker: Optional[str] = Field(None, description="Connected MQTT broker host")
    port: Optional[int] = Field(None, description="Connected MQTT broker port")
    devices_online: Optional[int] = Field(None, description="Number of currently online IoT devices")
    error: Optional[str] = Field(None, description="Error message if plugin is not connected/loaded")


class IoTDeviceItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    device_id: str = Field(..., description="Unique device identifier (e.g. ESP32_RELAY_01)")
    status: Dict[str, Any] = Field(default_factory=dict, description="Live status dictionary (states, online flag, uptime)")
    device_state: Optional[DeviceState] = Field(None, description="Standardized DeviceState envelope (Member 4)")


class IoTDeviceListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    devices: List[IoTDeviceItem] = Field(default_factory=list, description="List of detected IoT devices")
    count: int = Field(0, description="Total count of IoT devices")


# ===========================================================================
# 5. Typed Request Models for Subplugin Endpoints
# ===========================================================================

class EmbeddedCommandRequest(BaseModel):
    """Schema for embedded robot car & wheelchair commands."""
    model_config = ConfigDict(extra="ignore")

    command: str = Field(..., min_length=1, description="Embedded text command (e.g. LIFTCARFORWARD, LIFTCARSTOP, CARFORWARD)")
    target: Optional[str] = Field(None, description="Target device (CAR, CHAIR)")
    domain: Optional[str] = Field(None, description="Domain prefix (LIFT, DESKTOP, IOT)")


class BCIUnifiedCommandRequest(BaseModel):
    """Schema for BCI input commands routed to FSM."""
    model_config = ConfigDict(extra="ignore")

    command: Optional[str] = Field(None, description="Mental command action (PUSH, PULL, LEFT, RIGHT, NEUTRAL)")
    raw_command: Optional[str] = Field(None, description="Alias for command")
    confidence: Optional[float] = Field(0.95, ge=0.0, le=1.0, description="Mental command confidence power (0.0 to 1.0)")


class FSMCommandRequest(BaseModel):
    """Schema for direct FSM commands."""
    model_config = ConfigDict(extra="ignore")

    command: Optional[str] = Field(None, description="Command string to execute directly on FSM")
    raw_command: Optional[str] = Field(None, description="Alias for command")
    confidence: Optional[float] = Field(1.0, ge=0.0, le=1.0, description="Confidence score")


class FSMBackRequest(BaseModel):
    """Schema for navigating backward in FSM hierarchy."""
    model_config = ConfigDict(extra="ignore")

    level: Optional[int] = Field(None, ge=1, le=3, description="Target navigation level to return to")


class ActionRequest(BaseModel):
    """Schema for manual media or desktop action dispatch."""
    model_config = ConfigDict(extra="ignore")

    action: str = Field(..., min_length=1, description="Action name (e.g. 'Volume Up', 'Play / Pause', 'Search Album/Playlist')")
    query: Optional[str] = Field(None, description="Search query if action requires parameter")


class VolumeRequest(BaseModel):
    """Schema for setting system master volume."""
    model_config = ConfigDict(extra="ignore")

    volume: int = Field(..., ge=0, le=100, description="Master volume level (0 to 100)")


class SearchRequest(BaseModel):
    """Schema for searching media or playlist tracks."""
    model_config = ConfigDict(extra="ignore")

    query: str = Field(..., min_length=1, description="Search query string")


class AimlAutomationRequest(BaseModel):
    """Schema for toggling AIML automated background polling."""
    model_config = ConfigDict(extra="ignore")

    action: Optional[Literal["start", "stop", "toggle"]] = Field("toggle", description="Automation trigger action")


class AimlConfigRequest(BaseModel):
    """Schema for dynamically updating AIML parameters."""
    model_config = ConfigDict(extra="ignore")

    confidence_threshold: Optional[float] = Field(None, ge=0.0, le=1.0, description="Classification confidence threshold")
    volume_cooldown: Optional[float] = Field(None, ge=0.0, description="Volume step rate limit cooldown in seconds")
    headless: Optional[bool] = Field(None, description="Selenium headless browser mode toggle")


class StateSyncRequest(BaseModel):
    """Schema for synchronizing domain state across sessions."""
    model_config = ConfigDict(extra="ignore")

    session_id: Optional[str] = Field("default", description="Session identifier")
    domain: str = Field(..., description="Target domain key")
    domain_state: Dict[str, Any] = Field(default_factory=dict, description="Domain snapshot data")


class StateUpdateRequest(BaseModel):
    """Schema for updating session state in StateManager."""
    model_config = ConfigDict(extra="ignore")

    session_id: Optional[str] = Field("default", description="Session identifier")
    updates: Dict[str, Any] = Field(default_factory=dict, description="State key-value updates")

