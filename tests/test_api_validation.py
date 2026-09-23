import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from core.communication.api_server import setup_routes
from plugins.iot.fastapi_routes import setup_iot_routes
from plugins.embedded.fastapi_routes import setup_embedded_routes
from plugins.aiml.fastapi_routes import setup_aiml_routes
import core.plugin_manager.manager as plugin_manager

from models.api_models import (
    SystemHealthResponse,
    SessionStateResponse,
    SystemStateResponse,
    DiagnosticsResponse,
    LifecycleSummaryResponse,
    DomainStateResponse,
    IoTStatusResponse,
    IoTDeviceListResponse,
    EmbeddedCommandRequest,
    BCIUnifiedCommandRequest,
    FSMCommandRequest,
    ActionRequest,
    VolumeRequest,
    SearchRequest,
)
from models.command_models import NavigationCommand, CommandErrorResponse
from models.device_models import (
    DeviceState,
    DeviceDomain,
    DeviceType,
    DeviceProtocol,
    ConnectionStatus,
    OperationalStatus,
)
from models.telemetry_models import (
    UnifiedTelemetryPacket,
    TelemetryDomain,
    BciTelemetry,
    MentalCommandTelemetry,
    IotTelemetry,
    RelayStates,
)

# Initialize test app with all registered route modules
app = FastAPI()
setup_routes(app)
setup_iot_routes(app)
setup_embedded_routes(app)
setup_aiml_routes(app)
client = TestClient(app)


# ===========================================================================
# 1. Basic BCI Command Validation Tests (Sprint 10 baseline)
# ===========================================================================

def test_valid_command():
    response = client.post("/api/v1/bci/command", json={"command": "PUSH"})
    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_unsupported_command_returns_400():
    response = client.post("/api/v1/bci/command", json={"command": "INVALID_COMMAND"})
    assert response.status_code == 400
    data = response.json()
    assert data["status"] == "error"
    assert data["error_code"] == "INVALID_COMMAND"
    assert data["message"] == "Invalid command"
    assert "reason" in data


def test_missing_command_returns_400():
    response = client.post("/api/v1/bci/command", json={})
    assert response.status_code == 400
    data = response.json()
    assert data["status"] == "error"
    assert data["error_code"] == "MISSING_COMMAND"
    assert data["message"] == "Missing command or commands field"
    assert "details" in data


def test_empty_command_returns_400():
    response = client.post("/api/v1/bci/command", json={"command": ""})
    assert response.status_code == 400
    data = response.json()
    assert data["status"] == "error"
    assert data["error_code"] == "MISSING_COMMAND"
    assert data["message"] == "Missing command or commands field"


def test_malformed_request_payload_returns_422():
    response = client.post("/api/v1/bci/command", content="not a json", headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    data = response.json()
    assert data["status"] == "error"
    assert data["error_code"] == "VALIDATION_ERROR"
    assert data["message"] == "Malformed request payload"
    assert "details" in data


def test_wrong_field_type_returns_422():
    response = client.post("/api/v1/bci/command", json={"command": 123})
    assert response.status_code == 422
    data = response.json()
    assert data["status"] == "error"
    assert data["error_code"] == "VALIDATION_ERROR"
    assert data["message"] == "Malformed request payload"
    assert "details" in data


def test_invalid_input_does_not_reach_execution(monkeypatch):
    execution_reached = False

    async def mock_execute(*args, **kwargs):
        nonlocal execution_reached
        execution_reached = True
        return {"status": "success"}

    monkeypatch.setattr(plugin_manager, "execute", mock_execute)

    response = client.post("/api/v1/bci/command", json={"command": "INVALID_COMMAND"})
    assert response.status_code == 400
    assert execution_reached is False


# ===========================================================================
# 2. Response Model Schema Conformance Tests (Task 1)
# ===========================================================================

def test_system_health_response_schema():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    # Validate conforming to SystemHealthResponse model
    validated = SystemHealthResponse.model_validate(data)
    assert validated.status == "online"
    assert validated.server is True
    assert validated.total_domains == 4
    assert isinstance(validated.domains, dict)
    assert "desktop" in validated.domains


def test_session_state_response_schema():
    response = client.get("/api/v1/state")
    assert response.status_code == 200
    data = response.json()
    validated = SessionStateResponse.model_validate(data)
    assert validated.session_id is not None
    assert validated.current_level in (1, 2, 3)
    assert isinstance(validated.command_history, list)


def test_system_state_response_schema():
    response = client.get("/api/v1/state/system")
    assert response.status_code == 200
    data = response.json()
    validated = SystemStateResponse.model_validate(data)
    assert validated.system_status in ("IDLE", "RUNNING", "ERROR", "ACTIVE")
    assert validated.metrics.total_commands >= 0
    assert validated.performance.bottleneck_status is not None


def test_diagnostics_response_schema():
    response = client.get("/api/v1/diagnostics")
    assert response.status_code == 200
    data = response.json()
    validated = DiagnosticsResponse.model_validate(data)
    assert validated.status == "success"
    assert validated.platform.system is not None
    assert validated.resources.cpu_percent >= 0.0
    assert validated.transport_metrics.mqtt_broker is not None


def test_lifecycle_summary_response_schema():
    response = client.get("/api/v1/lifecycle/summary")
    assert response.status_code == 200
    data = response.json()
    validated = LifecycleSummaryResponse.model_validate(data)
    assert validated.status == "success"
    assert validated.summary.total_commands >= 0
    assert isinstance(validated.summary.stage_counts, dict)


def test_domain_state_response_schema():
    response = client.get("/api/v1/state/domain/IOT")
    assert response.status_code == 200
    data = response.json()
    validated = DomainStateResponse.model_validate(data)
    assert validated.domain == "IOT"
    assert validated.status is not None


def test_iot_status_response_schema():
    response = client.get("/api/iot/status")
    assert response.status_code == 200
    data = response.json()
    validated = IoTStatusResponse.model_validate(data)
    assert isinstance(validated.connected, bool)


def test_iot_devices_response_schema():
    response = client.get("/api/iot/devices")
    assert response.status_code == 200
    data = response.json()
    validated = IoTDeviceListResponse.model_validate(data)
    assert isinstance(validated.devices, list)
    assert validated.count >= 0


# ===========================================================================
# 3. Subplugin Typed Request Model Parsing & Validation (Task 2)
# ===========================================================================

def test_embedded_command_valid():
    response = client.post("/embedded/command", json={"command": "LIFTCARFORWARD"})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_embedded_command_missing_command_422():
    response = client.post("/embedded/command", json={})
    assert response.status_code == 422
    data = response.json()
    assert data["status"] == "error"
    assert data["error_code"] == "VALIDATION_ERROR"


def test_embedded_command_invalid_domain_400():
    response = client.post("/embedded/command", json={"command": "INVALIDDOMAINCARFORWARD"})
    assert response.status_code == 400
    data = response.json()
    assert data["status"] == "error"
    assert data["error_code"] == "INVALID_DOMAIN"


def test_embedded_command_invalid_action_400():
    response = client.post("/embedded/command", json={"command": "LIFTCARFLY"})
    assert response.status_code == 400
    data = response.json()
    assert data["status"] == "error"
    assert data["error_code"] == "INVALID_COMMAND"


def test_aiml_bci_command_valid():
    response = client.post("/api/bci/command", json={"command": "PUSH", "confidence": 0.92})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["command"] == "PUSH"
    assert data["confidence"] == 0.92


def test_aiml_bci_command_missing_command_400():
    response = client.post("/api/bci/command", json={})
    assert response.status_code == 400
    data = response.json()
    assert data["status"] == "error"
    assert data["error_code"] == "MISSING_COMMAND"


def test_aiml_bci_command_invalid_confidence_boundary_422():
    response = client.post("/api/bci/command", json={"command": "PUSH", "confidence": 2.5})
    assert response.status_code == 422
    data = response.json()
    assert data["status"] == "error"
    assert data["error_code"] == "VALIDATION_ERROR"


def test_aiml_fsm_command_valid():
    response = client.post("/api/fsm/command", json={"command": "PUSH"})
    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_aiml_action_valid():
    response = client.post("/api/action", json={"action": "Volume Up"})
    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_aiml_action_missing_action_422():
    response = client.post("/api/action", json={})
    assert response.status_code == 422
    data = response.json()
    assert data["status"] == "error"
    assert data["error_code"] == "VALIDATION_ERROR"


def test_aiml_volume_valid():
    response = client.post("/api/volume", json={"volume": 65})
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["volume"] == 65


def test_aiml_volume_boundary_out_of_range_422():
    # Volume > 100
    response = client.post("/api/volume", json={"volume": 150})
    assert response.status_code == 422
    assert response.json()["status"] == "error"

    # Volume < 0
    response2 = client.post("/api/volume", json={"volume": -10})
    assert response2.status_code == 422
    assert response2.json()["status"] == "error"


def test_aiml_volume_invalid_type_422():
    response = client.post("/api/volume", json={"volume": "invalid_volume"})
    assert response.status_code == 422
    assert response.json()["status"] == "error"


def test_aiml_search_valid():
    response = client.post("/api/search", json={"query": "Arijit Singh"})
    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_aiml_search_missing_query_422():
    response = client.post("/api/search", json={})
    assert response.status_code == 422
    assert response.json()["status"] == "error"


# ===========================================================================
# 4. Standardized Error Response Envelope Validation (Task 3)
# ===========================================================================

def test_standardized_error_envelope_400():
    response = client.post("/api/v1/bci/command", json={"command": "INVALID_CMD"})
    assert response.status_code == 400
    data = response.json()
    # Validate against CommandErrorResponse
    err = CommandErrorResponse.model_validate(data)
    assert err.status == "error"
    assert err.error_code is not None
    assert err.message is not None


def test_standardized_error_envelope_422():
    response = client.post("/api/v1/bci/command", json={"command": 9999})
    assert response.status_code == 422
    data = response.json()
    err = CommandErrorResponse.model_validate(data)
    assert err.status == "error"
    assert err.error_code == "VALIDATION_ERROR"
    assert isinstance(err.details, list)


# ===========================================================================
# 5. Telemetry & Device-State Integration Validation (Task 4)
# ===========================================================================

def test_events_ingest_with_telemetry():
    telemetry_payload = {
        "headset_model": "Emotiv EPOC X",
        "sampling_rate_hz": 128,
        "battery_pct": 95,
        "mental_command": {
            "action": "PUSH",
            "power": 0.88,
            "is_debounced": True
        }
    }
    event_req = {
        "event_type": "BCI_TELEMETRY_RECORDED",
        "domain": "BCI",
        "command": "PUSH",
        "status": "SUCCESS",
        "telemetry": telemetry_payload
    }
    response = client.post("/api/v1/events", json=event_req)
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "success"
    assert "telemetry" in data["event"]["metadata"]
    assert data["event"]["metadata"]["telemetry"]["mental_command"]["action"] == "PUSH"


def test_events_ingest_with_device_state():
    device_state_payload = {
        "device_id": "ESP32_RELAY_01",
        "device_name": "Living Room Relay",
        "domain": "IOT",
        "device_type": "SMART_RELAY",
        "protocol": "MQTT",
        "connection_status": "ONLINE",
        "operational_status": "IDLE",
        "capabilities": ["toggle_light", "toggle_fan"],
        "state": {"light": "ON", "fan": "OFF"}
    }
    event_req = {
        "event_type": "DEVICE_STATE_SNAPSHOT",
        "domain": "IOT",
        "status": "SUCCESS",
        "device_state": device_state_payload
    }
    response = client.post("/api/v1/events", json=event_req)
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "success"
    assert "device_state" in data["event"]["metadata"]
    assert data["event"]["metadata"]["device_state"]["device_id"] == "ESP32_RELAY_01"


# ===========================================================================
# 6. Strict Extra Forbidden Model Validation
# ===========================================================================

def test_navigation_command_extra_forbid():
    from datetime import datetime
    # Valid navigation command
    valid_cmd = {
        "command_id": "CMD-1001",
        "command": "PUSH",
        "timestamp": datetime.now().isoformat()
    }
    model = NavigationCommand.model_validate(valid_cmd)
    assert model.command == "PUSH"

    # With extra unexpected fields -> should raise ValidationError
    invalid_cmd = dict(valid_cmd)
    invalid_cmd["unauthorized_injected_field"] = "hacked"
    with pytest.raises(ValidationError):
        NavigationCommand.model_validate(invalid_cmd)
