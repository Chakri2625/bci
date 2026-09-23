"""
telemetry_models.py
===================
Standard Telemetry Models for SynaptiMesh across BCI, AI/ML, IoT, and Embedded Domains.
Built with Pydantic V2 for high-performance validation, serialization, and schema generation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union
import uuid

from pydantic import BaseModel, ConfigDict, Field


class TelemetryDomain(str, Enum):
    BCI = "BCI"
    AI_ML = "AI_ML"
    IOT = "IOT"
    EMBEDDED = "EMBEDDED"


# ---------------------------------------------------------------------------
# 1. BCI Telemetry Models
# ---------------------------------------------------------------------------

class MentalCommandTelemetry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    action: str = Field(..., description="Mental command action (e.g. PUSH, PULL, LEFT, RIGHT, NEUTRAL, STOP)")
    power: float = Field(0.0, ge=0.0, le=1.0, description="Confidence power score between 0.0 and 1.0")
    is_debounced: bool = Field(True, description="Whether the command passed debounce filtering")
    duration_ms: Optional[float] = Field(None, ge=0.0, description="Active command duration in milliseconds")


class FrequencyBandsTelemetry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    delta_uv2: Optional[float] = Field(None, description="Delta band power (0.5 - 4 Hz) in uV^2")
    theta_uv2: Optional[float] = Field(None, description="Theta band power (4 - 8 Hz) in uV^2")
    alpha_uv2: Optional[float] = Field(None, description="Alpha band power (8 - 12 Hz) in uV^2")
    beta_low_uv2: Optional[float] = Field(None, description="Low Beta band power (12 - 18 Hz) in uV^2")
    beta_high_uv2: Optional[float] = Field(None, description="High Beta band power (18 - 30 Hz) in uV^2")
    gamma_uv2: Optional[float] = Field(None, description="Gamma band power (30 - 45 Hz) in uV^2")


class BciTelemetry(BaseModel):
    """
    Standard Brain-Computer Interface (BCI) Telemetry.
    """
    model_config = ConfigDict(extra="ignore")

    headset_model: str = Field("Emotiv EPOC X", description="Headset model / manufacturer identifier")
    headset_id: Optional[str] = Field(None, description="Headset hardware identifier or serial number")
    sampling_rate_hz: int = Field(128, description="Signal sampling frequency in Hz")
    battery_pct: int = Field(100, ge=0, le=100, description="Headset battery level percentage")
    packet_loss_rate: Optional[float] = Field(0.0, ge=0.0, le=1.0, description="Wireless packet loss ratio")
    signal_quality: Dict[str, float] = Field(
        default_factory=dict,
        description="Contact quality score (0.0 to 1.0) indexed by EEG channel name (AF3, F7, F3, etc.)"
    )
    mental_command: MentalCommandTelemetry = Field(..., description="Current classified mental intent")
    frequency_bands: Optional[FrequencyBandsTelemetry] = Field(None, description="Power spectral density values")
    raw_channels_uv: Optional[Dict[str, List[float]]] = Field(
        None,
        description="Optional raw microvolt time-series arrays per channel"
    )


# ---------------------------------------------------------------------------
# 2. AI / ML Telemetry Models
# ---------------------------------------------------------------------------

class PredictionMetrics(BaseModel):
    model_config = ConfigDict(extra="ignore")

    predicted_intent: str = Field(..., description="Top classified class label or intent")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Prediction confidence score")
    probabilities: Dict[str, float] = Field(
        default_factory=dict,
        description="Probability distribution across all target classes"
    )
    window_samples: Optional[int] = Field(None, description="Number of samples in the inference window")


class HardwareMetrics(BaseModel):
    model_config = ConfigDict(extra="ignore")

    execution_device: str = Field("CPU", description="Inference device (CPU, CUDA_GPU, TENSORRT, EDGE_TPU)")
    cpu_utilization_pct: Optional[float] = Field(None, ge=0.0, le=100.0, description="CPU usage %")
    gpu_utilization_pct: Optional[float] = Field(None, ge=0.0, le=100.0, description="GPU usage %")
    ram_memory_used_mb: Optional[float] = Field(None, ge=0.0, description="RAM memory allocated in MB")
    gpu_vram_used_mb: Optional[float] = Field(None, ge=0.0, description="GPU VRAM allocated in MB")


class AiMlTelemetry(BaseModel):
    """
    Standard AI/ML Pipeline & Inference Telemetry.
    """
    model_config = ConfigDict(extra="ignore")

    model_name: str = Field(..., description="Model identifier or architecture name")
    model_version: str = Field("1.0.0", description="Model semantic version")
    pipeline_stage: str = Field("INFERENCE", description="Active pipeline stage (PREPROCESSING, INFERENCE, POSTPROCESSING)")
    inference_latency_ms: float = Field(..., ge=0.0, description="Execution time for forward pass in milliseconds")
    preprocess_latency_ms: Optional[float] = Field(None, ge=0.0, description="Data preprocessing duration in milliseconds")
    postprocess_latency_ms: Optional[float] = Field(None, ge=0.0, description="Thresholding and smoothing duration in milliseconds")
    prediction: PredictionMetrics = Field(..., description="Model classification results")
    hardware_metrics: Optional[HardwareMetrics] = Field(None, description="Hardware resource utilization during inference")


# ---------------------------------------------------------------------------
# 3. IoT Telemetry Models
# ---------------------------------------------------------------------------

class RelayStates(BaseModel):
    model_config = ConfigDict(extra="ignore")

    light: Literal["ON", "OFF", "TOGGLE"] = Field("OFF", description="Smart light relay state")
    fan: Literal["ON", "OFF", "TOGGLE"] = Field("OFF", description="Smart fan relay state")
    pump: Literal["ON", "OFF", "TOGGLE"] = Field("OFF", description="Smart pump relay state")


class EnvironmentalSensors(BaseModel):
    model_config = ConfigDict(extra="ignore")

    temperature_celsius: Optional[float] = Field(None, description="Ambient temperature in degrees Celsius")
    humidity_pct: Optional[float] = Field(None, ge=0.0, le=100.0, description="Relative humidity percentage")
    ambient_light_lux: Optional[float] = Field(None, ge=0.0, description="Ambient illuminance in Lux")
    motion_detected: Optional[bool] = Field(None, description="PIR / Radar motion detection flag")


class EnergyMetrics(BaseModel):
    model_config = ConfigDict(extra="ignore")

    voltage_v: Optional[float] = Field(None, ge=0.0, description="AC/DC supply voltage in Volts")
    current_a: Optional[float] = Field(None, ge=0.0, description="Current consumption in Amperes")
    power_watts: Optional[float] = Field(None, ge=0.0, description="Active power consumption in Watts")
    energy_kwh: Optional[float] = Field(None, ge=0.0, description="Cumulative energy consumption in kWh")


class ConnectivityMetrics(BaseModel):
    model_config = ConfigDict(extra="ignore")

    protocol: str = Field("MQTT", description="Active communication protocol (MQTT, HTTP, WEBSOCKET, COAP)")
    wifi_rssi_dbm: Optional[int] = Field(None, le=0, description="WiFi Signal Strength in dBm")
    ip_address: Optional[str] = Field(None, description="Local or assigned IPv4 address")
    uptime_seconds: Optional[int] = Field(None, ge=0, description="Device uptime since last boot in seconds")


class IotTelemetry(BaseModel):
    """
    Standard IoT Relay & Sensor Node Telemetry.
    """
    model_config = ConfigDict(extra="ignore")

    device_type: str = Field("SMART_RELAY", description="Device category (SMART_RELAY, SENSOR_NODE, SMART_HUB)")
    firmware_version: str = Field("2.0.0-unified", description="Firmware version running on MCU")
    status: Literal["ONLINE", "OFFLINE", "DEGRADED", "ERROR"] = Field("ONLINE", description="Operational device status")
    relays: RelayStates = Field(default_factory=RelayStates, description="Actuator / relay channel states")
    environmental_sensors: Optional[EnvironmentalSensors] = Field(None, description="Ambient environmental sensor readings")
    energy_metrics: Optional[EnergyMetrics] = Field(None, description="Power and energy telemetry")
    connectivity: Optional[ConnectivityMetrics] = Field(None, description="Network and connectivity diagnostics")


# ---------------------------------------------------------------------------
# 4. Embedded Telemetry Models
# ---------------------------------------------------------------------------

class SystemHealthTelemetry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    free_heap_bytes: int = Field(0, ge=0, description="Available RAM heap in bytes")
    cpu_core_temp_c: Optional[float] = Field(None, description="Microcontroller core temperature in Celsius")
    supply_voltage_v: Optional[float] = Field(None, ge=0.0, description="Main supply / battery voltage")
    battery_soc_pct: Optional[int] = Field(None, ge=0, le=100, description="Battery state of charge percentage")
    loop_frequency_hz: Optional[float] = Field(None, ge=0.0, description="Firmware main loop execution frequency in Hz")


class KinematicsTelemetry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    movement: str = Field("STOP", description="Active movement direction/command (FORWARD, BACKWARD, LEFT, RIGHT, STOP, LEFT360, RIGHT360, IDLE)")
    state: str = Field("IDLE", description="Kinematic state (e.g. IDLE, MOVING_FORWARD, MOVING_BACKWARD, TURNING_LEFT, TURNING_RIGHT, STOP, STOPPED)")
    speed: Optional[float] = Field(0.0, description="Normalized or current speed scalar/velocity")
    speed_pwm: Optional[int] = Field(None, ge=0, le=255, description="Motor PWM speed value (0 to 255)")
    speed_mode: str = Field("NORMAL", description="Active drive speed mode (SLOW, NORMAL, MEDIUM, FAST, TURBO)")
    motor_left_pwm: int = Field(0, ge=-255, le=255, description="Left motor PWM duty cycle (-255 to 255)")
    motor_right_pwm: int = Field(0, ge=-255, le=255, description="Right motor PWM duty cycle (-255 to 255)")
    steering_angle_deg: Optional[float] = Field(0.0, ge=-90.0, le=90.0, description="Front steering angle in degrees")
    linear_velocity_mps: Optional[float] = Field(None, description="Estimated linear velocity in meters/second")
    wheel_encoder_left_ticks: Optional[int] = Field(None, description="Left wheel encoder cumulative ticks")
    wheel_encoder_right_ticks: Optional[int] = Field(None, description="Right wheel encoder cumulative ticks")


class ImuTelemetry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    accel_x_g: Optional[float] = Field(None, description="Acceleration X axis in Gs")
    accel_y_g: Optional[float] = Field(None, description="Acceleration Y axis in Gs")
    accel_z_g: Optional[float] = Field(None, description="Acceleration Z axis in Gs")
    gyro_roll_deg_s: Optional[float] = Field(None, description="Angular roll rate in deg/s")
    gyro_pitch_deg_s: Optional[float] = Field(None, description="Angular pitch rate in deg/s")
    gyro_yaw_deg_s: Optional[float] = Field(None, description="Angular yaw rate in deg/s")


class SafetyRangingTelemetry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ultrasonic_front_distance_cm: Optional[float] = Field(None, ge=0.0, description="Front ultrasonic sensor distance in cm")
    ultrasonic_rear_distance_cm: Optional[float] = Field(None, ge=0.0, description="Rear ultrasonic sensor distance in cm")
    collision_detected: bool = Field(False, description="Collision or proximity trigger flag")
    emergency_stop_triggered: bool = Field(False, description="Emergency stop hardware or software flag")


class BusTelemetry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    protocol: str = Field("MQTT", description="Bus communication protocol (UART, CAN, SPI, I2C, MQTT, TCP_SOCKET)")
    baud_rate: Optional[int] = Field(None, description="Serial baud rate if using UART")
    rx_buffer_overflows: Optional[int] = Field(0, ge=0, description="Serial/CAN RX buffer overflow count")
    packet_crc_errors: Optional[int] = Field(0, ge=0, description="Corrupt packet / CRC error count")
    round_trip_latency_ms: Optional[float] = Field(None, ge=0.0, description="Command to ACK round-trip latency in ms")


class EmbeddedTelemetry(BaseModel):
    """
    Standard Embedded Microcontroller & Robotics Telemetry (RC Car, Wheelchair).
    """
    model_config = ConfigDict(extra="ignore")

    device_id: Optional[str] = Field(None, description="Microcontroller or robotics hardware identifier")
    device_mode: str = Field("RC_CAR", description="Device operational mode (RC_CAR, WHEELCHAIR, ROBOTIC_ARM)")
    mcu_architecture: str = Field("ESP32-WROOM-32", description="Microcontroller architecture (ESP32, STM32, RP2040)")
    firmware_version: str = Field("2.0.0-unified", description="Firmware version running on MCU")
    status: Literal["ONLINE", "OFFLINE", "DEGRADED", "ERROR", "MOVING", "STOPPED", "TIMEOUT", "ACTIVE", "IDLE"] = Field(
        "ONLINE",
        description="Operational device status"
    )
    system_health: SystemHealthTelemetry = Field(..., description="MCU system health, memory, and voltage metrics")
    kinematics: KinematicsTelemetry = Field(default_factory=KinematicsTelemetry, description="Motor drive and steering kinematics")
    imu_sensors: Optional[ImuTelemetry] = Field(None, description="6-DOF / 9-DOF IMU motion sensor readings")
    safety_and_ranging: Optional[SafetyRangingTelemetry] = Field(None, description="Obstacle proximity and safety flags")
    bus_telemetry: Optional[BusTelemetry] = Field(None, description="Bus performance and error counters")


# ---------------------------------------------------------------------------
# 5. Unified Telemetry Envelope
# ---------------------------------------------------------------------------

DomainTelemetryPayload = Union[BciTelemetry, AiMlTelemetry, IotTelemetry, EmbeddedTelemetry, Dict[str, Any]]


class UnifiedTelemetryPacket(BaseModel):
    """
    Unified standard telemetry envelope wrapping domain-specific payloads.
    """
    model_config = ConfigDict(extra="ignore")

    telemetry_id: str = Field(
        default_factory=lambda: f"TEL-{uuid.uuid4()}",
        description="Unique telemetry packet identifier"
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        description="ISO-8601 UTC timestamp of packet emission"
    )
    source_domain: TelemetryDomain = Field(..., description="Origin domain (BCI, AI_ML, IOT, EMBEDDED)")
    source_id: str = Field(..., description="Device MAC, headset ID, microcontroller ID, or inference node ID")
    session_id: Optional[str] = Field("default", description="Active user session identifier")
    trace_id: Optional[str] = Field(None, description="Distributed trace identifier linking commands to telemetry")
    sequence_number: int = Field(0, ge=0, description="Monotonically increasing sequence index")
    payload: DomainTelemetryPayload = Field(..., description="Domain-specific structured telemetry payload")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to clean JSON-serializable dictionary."""
        return self.model_dump(exclude_none=True)


# ---------------------------------------------------------------------------
# 6. Standard Telemetry Alert Models (Member 6)
# ---------------------------------------------------------------------------

class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class AlertStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class TelemetryAlert(BaseModel):
    """
    Standard normalized alert model for movement, speed, battery, safety, and hardware status.
    """
    model_config = ConfigDict(extra="ignore")

    alert_id: str = Field(
        default_factory=lambda: f"ALT-{uuid.uuid4().hex[:10].upper()}",
        description="Unique alert identifier"
    )
    alert_type: str = Field(..., description="Alert category classification (e.g. OBSTACLE_PROXIMITY, CRITICAL_BATTERY, LOW_BATTERY, EMERGENCY_STOP, HARDWARE_FAULT, WATCHDOG_TIMEOUT, OVERHEATING, ABNORMAL_SPEED, UNSAFE_MOVEMENT, OFFLINE)")
    severity: AlertSeverity = Field(AlertSeverity.WARNING, description="Severity level (INFO, WARNING, ERROR, CRITICAL)")
    device_id: str = Field(..., description="Target hardware or logical device identifier")
    device_mode: str = Field("RC_CAR", description="Operational device mode (RC_CAR, WHEELCHAIR, ROBOTIC_ARM, GENERIC)")
    domain: TelemetryDomain = Field(TelemetryDomain.EMBEDDED, description="Origin telemetry domain")
    message: str = Field(..., description="Human-readable alert summary message")
    condition: str = Field(..., description="Underlying trigger condition key")
    status: AlertStatus = Field(AlertStatus.ACTIVE, description="Alert lifecycle state (ACTIVE, RESOLVED, ACKNOWLEDGED)")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        description="ISO-8601 UTC timestamp of alert emission"
    )
    timestamp_unix_ms: int = Field(
        default_factory=lambda: int(datetime.now(timezone.utc).timestamp() * 1000),
        description="Unix timestamp in milliseconds"
    )
    resolved_at: Optional[str] = Field(None, description="ISO-8601 UTC timestamp when condition resolved")
    source: str = Field("SERVER_ALERT_GENERATOR", description="Component that generated the alert")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Contextual values and metrics at trigger time")

    def to_dict(self) -> Dict[str, Any]:
        """Convert alert to clean JSON-serializable dictionary."""
        return self.model_dump(exclude_none=True)

