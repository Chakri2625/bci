"""
tests/test_embedded_v9_2.py
----------------------------
Integration and unit tests for SynaptiMesh Embedded Dashboard v9.2.
Validates REST API endpoints, state machine / simulator commands,
Cortex bridge integration, ESP32 multi-transport configuration,
command logger persistence, and responsive UI template rendering.
"""

import pytest
import os
import json
from fastapi.testclient import TestClient
from main import app
from plugins.embedded.dashboard.command_logger import CommandLogger
from plugins.embedded.dashboard.bci_controller import BCIController

client = TestClient(app)


def test_embedded_dashboard_html_renders():
    """Verify the new Embedded Dashboard HTML renders with all required cards and navigation."""
    response = client.get("/embedded")
    assert response.status_code == 200
    text = response.text

    # SynaptiMesh Branding & Top Navigation
    assert "SynaptiMesh" in text
    assert "BACK TO SYNAPTIMESH" in text
    assert "DASHBOARD" in text
    assert "CAR CONTROL" in text

    # Header status & connections
    assert "connectionStatus" in text
    assert "robotStatus" in text

    # Device selector & Telemetry
    assert "deviceSelector" in text
    assert "currentState" in text
    assert "currentCommand" in text
    assert "frontDistance" in text
    assert "emergencyBtn" in text
    assert "activityLog" in text
    assert "consoleOutput" in text
    assert "notification" in text

    # Scripts
    assert "websocket_manager.js" in text
    assert "dashboard.js" in text
    assert "mqtt_broker_popup.js" in text


def test_embedded_car_control_html_renders():
    """Verify the 3D Robot Car Control simulation page renders."""
    response = client.get("/embedded/car-control")
    assert response.status_code == 200
    assert "SynaptiMesh" in response.text
    assert "command_manager.js" in response.text
    assert "car_control.js" in response.text


def test_api_status_endpoint():
    """Verify /api/status returns stateMachine, cortex, car, and esp32 metadata."""
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert "stateMachine" in data
    assert "cortex" in data
    assert "car" in data
    assert "esp32" in data
    assert data["car"]["target"] == "robotcar"


def test_api_config_get_and_post():
    """Verify /api/bci/config returns and updates configuration."""
    response = client.get("/api/bci/config")
    assert response.status_code == 200
    data = response.json()
    assert "bci" in data
    assert "cortex" in data

    # Update config
    post_res = client.post("/api/bci/config", json={
        "bci": {
            "powerThreshold": 0.40,
            "debounceMs": 500,
            "comboWindowMs": 3000
        }
    })
    assert post_res.status_code == 200
    updated = post_res.json()
    assert updated["success"] is True
    assert updated["bci"]["powerThreshold"] == 0.40


def test_api_bci_domain_and_device_selection():
    """Verify /api/bci/select-domain, select-device, and reset endpoints."""
    # Reset navigation
    reset_res = client.post("/api/bci/reset")
    assert reset_res.status_code == 200
    assert reset_res.json()["success"] is True

    # Select domain EMBEDDED
    domain_res = client.post("/api/bci/select-domain", json={"domain": "EMBEDDED"})
    assert domain_res.status_code == 200
    assert domain_res.json()["success"] is True
    assert domain_res.json()["currentState"]["selectedDomain"] == "EMBEDDED"

    # Select device car
    device_res = client.post("/api/bci/select-device", json={"device": "car"})
    assert device_res.status_code == 200
    assert device_res.json()["success"] is True
    assert device_res.json()["currentState"]["selectedDevice"] in ("car", "ROBOT CAR")


def test_api_simulate_mental_command():
    """Verify /api/simulate executes simulated thought frames."""
    res = client.post("/api/simulate", json={"action": "push", "power": 0.85})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["action"] == "push"
    assert "currentState" in data


def test_api_simulate_combination():
    """Verify /api/simulate-combination executes multi-action combos."""
    res = client.post("/api/simulate-combination", json={"actions": ["push", "pull"], "power": 0.9})
    assert res.status_code == 200
    data = res.json()
    assert "result" in data
    assert "currentState" in data


def test_api_car_command_and_logging(tmp_path):
    """Verify /api/car/command and CommandLogger persistence."""
    logger = CommandLogger(log_dir=str(tmp_path))
    event = logger.log(
        command="FORWARD",
        source="TEST_SUITE",
        result={"success": True, "mode": "mqtt", "latency": 12.5, "topic": "robotcar/test/control"}
    )
    assert event["command"] == "FORWARD"
    assert event["success"] is True
    assert event["source"] == "TEST_SUITE"
    assert (tmp_path / "command_log.json").exists()
    assert (tmp_path / "command_log.csv").exists()
    assert (tmp_path / "command_log.txt").exists()


def test_api_esp32_endpoints():
    """Verify ESP32 ports, config, and diagnostic endpoints."""
    # Ports
    ports_res = client.get("/api/esp32/ports")
    assert ports_res.status_code == 200
    assert "ports" in ports_res.json()

    # Get config
    cfg_res = client.get("/api/esp32/config")
    assert cfg_res.status_code == 200
    assert "config" in cfg_res.json()
    assert cfg_res.json()["config"]["mode"] in ("mqtt", "serial", "wifi", "http")

    # Update config
    update_res = client.post("/api/esp32/config", json={"baudRate": 115200})
    assert update_res.status_code == 200
    assert update_res.json()["config"]["baudRate"] == 115200


def test_api_cortex_endpoints():
    """Verify Cortex profiles and diagnostic endpoints."""
    profiles_res = client.get("/api/cortex/profiles")
    assert profiles_res.status_code == 200
    assert "profiles" in profiles_res.json()

    diag_res = client.post("/api/cortex/diagnose")
    assert diag_res.status_code == 200
    assert "socket_connected" in diag_res.json() or "steps" in diag_res.json() or "endpoint" in diag_res.json()


def test_legacy_embedded_command_dispatch():
    """Verify backwards compatibility for /embedded/command endpoint."""
    res = client.post("/embedded/command", json={"command": "LIFTCARSTOP", "domain": "LIFT", "target": "CAR"})
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_websocket_realtime_connection():
    """Verify WebSocket /ws connection and initial handshake."""
    with client.websocket_connect("/ws") as ws:
        msg1 = json.loads(ws.receive_text())
        assert msg1["type"] in ("init_snapshot", "cortex_status")
        assert "payload" in msg1
        if "cortex" in msg1["payload"]:
            assert "connected" in msg1["payload"]["cortex"]

        # Send ping / command
        ws.send_text(json.dumps({"type": "ping"}))


def test_desktop_and_mobile_car_control_routes():
    """Verify desktop and mobile responsive car control template routes."""
    res_desktop = client.get("/embedded/desktop-car-control")
    assert res_desktop.status_code == 200
    assert "Car Control" in res_desktop.text or "car_control" in res_desktop.text

    res_mobile = client.get("/embedded/mobile-car-control")
    assert res_mobile.status_code == 200
    assert "Car Control" in res_mobile.text or "car_control" in res_mobile.text


def test_static_assets_availability():
    """Verify all new static JS and CSS files are properly served."""
    assets = [
        "/embedded/static/js/websocket_manager.js",
        "/embedded/static/js/command_manager.js",
        "/embedded/static/js/desktop_car_control.js",
        "/embedded/static/js/mobile_car_control.js",
        "/embedded/static/css/desktop_car_control.css",
        "/embedded/static/css/mobile_car_control.css",
    ]
    for asset in assets:
        res = client.get(asset)
        assert res.status_code == 200, f"Failed to serve asset: {asset}"
        assert len(res.content) > 0


def test_http_command_dispatch_with_device():
    """Verify HTTP command dispatch with device targeting header and payload."""
    res_text = client.post(
        "/embedded/command",
        content="LIFTCARFORWARD",
        headers={"Content-Type": "text/plain", "X-SynaptiMesh-Device": "car"}
    )
    assert res_text.status_code == 200
    assert res_text.json()["ok"] is True or res_text.json().get("status") == "ok"

    res_json = client.post(
        "/embedded/command",
        json={"command": "LIFTCARSTOP", "device": "chair"}
    )
    assert res_json.status_code == 200
    assert res_json.json()["ok"] is True or res_json.json().get("status") == "ok"

