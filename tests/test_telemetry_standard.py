"""
test_telemetry_standard.py
==========================
Comprehensive tests for Standard Telemetry Schemas, Models, Cortex Processing,
IoT Sensor tracking, and Telemetry API routes across BCI, AI/ML, IoT, and Embedded.
"""

import json
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from models.telemetry_models import (
    AiMlTelemetry,
    BciTelemetry,
    ConnectivityMetrics,
    EmbeddedTelemetry,
    EnergyMetrics,
    EnvironmentalSensors,
    FrequencyBandsTelemetry,
    HardwareMetrics,
    ImuTelemetry,
    IotTelemetry,
    KinematicsTelemetry,
    MentalCommandTelemetry,
    PredictionMetrics,
    RelayStates,
    SafetyRangingTelemetry,
    SystemHealthTelemetry,
    TelemetryDomain,
    UnifiedTelemetryPacket,
)
from plugins.iot.device_manager import Device, DeviceManager
from services.cortex_service import CortexService
from api.telemetry_routes import telemetry_router
from fastapi import FastAPI


# ===========================================================================
# 1. BCI Telemetry Model Tests
# ===========================================================================

def test_bci_telemetry_valid():
    cmd = MentalCommandTelemetry(action="PUSH", power=0.95, is_debounced=True, duration_ms=450.0)
    bands = FrequencyBandsTelemetry(alpha_uv2=24.5, beta_low_uv2=12.3, theta_uv2=8.1)
    bci = BciTelemetry(
        headset_model="Emotiv EPOC X",
        headset_id="EPOCX-98214",
        sampling_rate_hz=128,
        battery_pct=85,
        signal_quality={"AF3": 0.95, "F7": 0.90, "O1": 0.98},
        mental_command=cmd,
        frequency_bands=bands
    )
    
    packet = UnifiedTelemetryPacket(
        source_domain=TelemetryDomain.BCI,
        source_id="EPOCX-98214",
        session_id="SES-001",
        payload=bci
    )
    
    data = packet.to_dict()
    assert data["source_domain"] == "BCI"
    assert data["payload"]["mental_command"]["action"] == "PUSH"
    assert data["payload"]["signal_quality"]["AF3"] == 0.95
    assert data["payload"]["battery_pct"] == 85


def test_bci_telemetry_invalid_battery():
    with pytest.raises(ValidationError):
        BciTelemetry(
            headset_model="Emotiv EPOC X",
            battery_pct=150,  # Invalid: > 100
            mental_command=MentalCommandTelemetry(action="PUSH", power=0.5)
        )


# ===========================================================================
# 2. AI / ML Telemetry Model Tests
# ===========================================================================

def test_aiml_telemetry_valid():
    pred = PredictionMetrics(
        predicted_intent="LEFT_LIGHT_ON",
        confidence=0.925,
        probabilities={"LEFT_LIGHT_ON": 0.925, "LEFT_LIGHT_OFF": 0.05, "NEUTRAL": 0.025},
        window_samples=640
    )
    hw = HardwareMetrics(
        execution_device="CUDA_GPU",
        cpu_utilization_pct=32.0,
        gpu_utilization_pct=45.5,
        ram_memory_used_mb=1280.0
    )
    aiml = AiMlTelemetry(
        model_name="EEGNet_v4_IntentClassifier",
        model_version="2.1.0",
        pipeline_stage="INFERENCE",
        inference_latency_ms=8.4,
        preprocess_latency_ms=2.1,
        prediction=pred,
        hardware_metrics=hw
    )

    packet = UnifiedTelemetryPacket(
        source_domain=TelemetryDomain.AI_ML,
        source_id="INFERENCE-NODE-01",
        payload=aiml
    )

    data = packet.to_dict()
    assert data["source_domain"] == "AI_ML"
    assert data["payload"]["model_name"] == "EEGNet_v4_IntentClassifier"
    assert data["payload"]["prediction"]["confidence"] == 0.925
    assert data["payload"]["hardware_metrics"]["execution_device"] == "CUDA_GPU"


# ===========================================================================
# 3. IoT Telemetry Model Tests
# ===========================================================================

def test_iot_telemetry_valid():
    relays = RelayStates(light="ON", fan="OFF", pump="OFF")
    env = EnvironmentalSensors(
        temperature_celsius=25.4,
        humidity_pct=60.5,
        ambient_light_lux=350.0,
        motion_detected=False
    )
    energy = EnergyMetrics(voltage_v=230.1, current_a=0.5, power_watts=115.0)
    conn = ConnectivityMetrics(protocol="MQTT", wifi_rssi_dbm=-62, ip_address="192.168.1.50")
    
    iot = IotTelemetry(
        device_type="SMART_RELAY",
        firmware_version="2.0.0-unified",
        status="ONLINE",
        relays=relays,
        environmental_sensors=env,
        energy_metrics=energy,
        connectivity=conn
    )

    packet = UnifiedTelemetryPacket(
        source_domain=TelemetryDomain.IOT,
        source_id="ESP32_48:E7:29:AA:1B:02",
        payload=iot
    )

    data = packet.to_dict()
    assert data["source_domain"] == "IOT"
    assert data["payload"]["relays"]["light"] == "ON"
    assert data["payload"]["environmental_sensors"]["temperature_celsius"] == 25.4
    assert data["payload"]["connectivity"]["wifi_rssi_dbm"] == -62


# ===========================================================================
# 4. Embedded Telemetry Model Tests
# ===========================================================================

def test_embedded_telemetry_valid():
    health = SystemHealthTelemetry(
        free_heap_bytes=195400,
        cpu_core_temp_c=41.2,
        supply_voltage_v=11.9,
        battery_soc_pct=85
    )
    kin = KinematicsTelemetry(
        movement="FORWARD",
        state="MOVING_FORWARD",
        speed=0.6,
        motor_left_pwm=180,
        motor_right_pwm=180,
        speed_mode="NORMAL",
        steering_angle_deg=0.0
    )
    imu = ImuTelemetry(accel_x_g=0.01, accel_y_g=0.0, accel_z_g=0.99)
    safety = SafetyRangingTelemetry(
        ultrasonic_front_distance_cm=52.0,
        collision_detected=False,
        emergency_stop_triggered=False
    )

    embedded = EmbeddedTelemetry(
        device_id="ROBOTCAR_98:A3:16:BF:2C:C0",
        mcu_architecture="ESP32-WROOM-32",
        device_mode="RC_CAR",
        status="ONLINE",
        system_health=health,
        kinematics=kin,
        imu_sensors=imu,
        safety_and_ranging=safety
    )

    packet = UnifiedTelemetryPacket(
        source_domain=TelemetryDomain.EMBEDDED,
        source_id="ROBOTCAR_98:A3:16:BF:2C:C0",
        payload=embedded
    )

    data = packet.to_dict()
    assert data["source_domain"] == "EMBEDDED"
    assert data["payload"]["device_id"] == "ROBOTCAR_98:A3:16:BF:2C:C0"
    assert data["payload"]["device_mode"] == "RC_CAR"
    assert data["payload"]["status"] == "ONLINE"
    assert data["payload"]["system_health"]["free_heap_bytes"] == 195400
    assert data["payload"]["system_health"]["battery_soc_pct"] == 85
    assert data["payload"]["kinematics"]["movement"] == "FORWARD"
    assert data["payload"]["kinematics"]["speed"] == 0.6
    assert data["payload"]["kinematics"]["motor_left_pwm"] == 180


# ===========================================================================
# 5. Static JSON Schema Export Verification
# ===========================================================================

def test_schema_export_structure():
    schema = UnifiedTelemetryPacket.model_json_schema()
    assert "$defs" in schema
    assert "BciTelemetry" in schema["$defs"]
    assert "AiMlTelemetry" in schema["$defs"]
    assert "IotTelemetry" in schema["$defs"]
    assert "EmbeddedTelemetry" in schema["$defs"]
    assert "source_domain" in schema["properties"]
    assert "payload" in schema["properties"]


# ===========================================================================
# 6. IoT DeviceManager Sensor Tracking Tests
# ===========================================================================

def test_device_manager_sensors():
    dm = DeviceManager()
    dm.update_device({
        "device_id": "esp32_living_room",
        "mac": "24:6F:28:B1:C2:A0",
        "system": "ESP32",
        "light": "ON",
        "fan": "OFF",
        "pump": "OFF"
    })

    dm.update_sensors("esp32_living_room", {
        "temperature": 27.5,
        "humidity": 55.0,
        "lux": 420,
        "voltage": 230.5,
        "rssi": -55
    })

    dev = dm.get_device("esp32_living_room")
    assert dev is not None
    assert dev.light == "ON"
    assert dev.temperature_celsius == 27.5
    assert dev.humidity_pct == 55.0
    assert dev.ambient_light_lux == 420.0
    assert dev.voltage_v == 230.5
    assert dev.wifi_rssi_dbm == -55

    d_dict = dev.to_dict()
    assert d_dict["temperature_celsius"] == 27.5
    assert d_dict["wifi_rssi_dbm"] == -55


# ===========================================================================
# 7. Cortex Contact Quality & Band Power Parsing Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_cortex_cq_and_band_power_handlers():
    cortex = CortexService()
    
    # Test Contact Quality frame parsing
    dev_frame = {
        "dev": [90, 4, 4, [4, 4, 3, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4]],
        "time": 1726550000.0
    }
    await cortex._handle_contact_quality_data(dev_frame)
    assert len(cortex.contact_quality) == 14
    assert cortex.contact_quality["AF3"] == 1.0
    assert cortex.contact_quality["F3"] == 0.75
    assert cortex.signal_quality in ["EXCELLENT", "GOOD"]

    # Test Band Power frame parsing
    pow_frame = {
        "pow": [12.5, 24.2, 18.0, 9.5, 4.2],
        "time": 1726550000.0
    }
    await cortex._handle_band_power_data(pow_frame)
    assert cortex.band_powers["theta_uv2"] == 12.5
    assert cortex.band_powers["alpha_uv2"] == 24.2
    assert cortex.band_powers["gamma_uv2"] == 4.2


# ===========================================================================
# 8. Telemetry API Route Tests
# ===========================================================================

def test_telemetry_api_endpoints():
    app = FastAPI()
    app.include_router(telemetry_router)
    client = TestClient(app)

    # 1. Ingest valid telemetry
    payload = {
        "source_domain": "IOT",
        "source_id": "ESP32_01",
        "session_id": "SES-99",
        "payload": {
            "device_type": "SMART_RELAY",
            "firmware_version": "2.0.0-unified",
            "status": "ONLINE",
            "relays": {"light": "ON", "fan": "OFF", "pump": "OFF"}
        }
    }
    res = client.post("/api/v1/telemetry", json=payload)
    assert res.status_code == 200
    res_data = res.json()
    assert res_data["status"] == "success"
    assert res_data["domain"] == "IOT"

    # 2. Get latest per domain
    latest_res = client.get("/api/v1/telemetry/latest?domain=IOT")
    assert latest_res.status_code == 200
    latest_data = latest_res.json()
    assert latest_data["status"] == "success"
    assert latest_data["domain"] == "IOT"
    assert latest_data["telemetry"]["source_id"] == "ESP32_01"

    # 3. Get history
    hist_res = client.get("/api/v1/telemetry/history?limit=10")
    assert hist_res.status_code == 200
    hist_data = hist_res.json()
    assert hist_data["count"] >= 1

    # 4. Get schema
    schema_res = client.get("/api/v1/telemetry/schema")
    assert schema_res.status_code == 200
    assert "$defs" in schema_res.json()
