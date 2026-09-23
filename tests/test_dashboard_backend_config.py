"""
Test Suite for Dashboard Backend Configuration & Environment Setup (Member 8).
"""

import os
import pytest
from fastapi.testclient import TestClient
from main import app
from core.config.dashboard_config import (
    DashboardBackendConfig,
    DashboardConfigManager,
    dashboard_config_manager,
    get_dashboard_config,
)

client = TestClient(app)


def test_dashboard_backend_config_defaults():
    """Verify default initialization of DashboardBackendConfig model."""
    cfg = DashboardBackendConfig()
    assert cfg.app_name == "SynaptiMesh Dashboard"
    assert cfg.env == "development"
    assert cfg.port == 8000
    assert cfg.ws_enabled is True
    assert cfg.ws_heartbeat_interval_sec == 15.0
    assert cfg.ws_client_timeout_sec == 30.0
    assert cfg.cortex_ws_url == "wss://localhost:6868"
    assert "PYTHON" in cfg.authoritative_dashboards
    assert cfg.authoritative_dashboards["PYTHON"] == "/"
    assert cfg.authoritative_dashboards["IOT"] == "/iot"


def test_dashboard_config_manager_env_overrides(monkeypatch):
    """Verify that environment variables take precedence in configuration manager."""
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("PORT", "9090")
    monkeypatch.setenv("WS_HEARTBEAT_INTERVAL_SEC", "20.5")
    monkeypatch.setenv("POWER_THRESHOLD", "0.75")
    monkeypatch.setenv("CORTEX_WS_URL", "wss://cortex.example.com:6868")

    mgr = DashboardConfigManager()
    cfg = mgr.get_config()

    assert cfg.env == "production"
    assert cfg.port == 9090
    assert cfg.ws_heartbeat_interval_sec == 20.5
    assert cfg.power_threshold == 0.75
    assert cfg.cortex_ws_url == "wss://cortex.example.com:6868"


def test_dashboard_config_dynamic_update():
    """Verify thread-safe dynamic configuration updates at runtime."""
    mgr = DashboardConfigManager()
    updated = mgr.update_config({
        "debug": False,
        "log_level": "DEBUG",
        "ws_broadcast_rate_hz": 60.0,
        "framing_duration_sec": 5.5
    })

    assert updated.debug is False
    assert updated.log_level == "DEBUG"
    assert updated.ws_broadcast_rate_hz == 60.0
    assert updated.framing_duration_sec == 5.5


def test_to_websocket_config_export():
    """Verify WebSocket layer parameter export helper."""
    mgr = DashboardConfigManager()
    ws_cfg = mgr.to_websocket_config()

    assert ws_cfg["enabled"] is True
    assert ws_cfg["port"] == 8000
    assert ws_cfg["path"] == "/ws"
    assert ws_cfg["bci_path"] == "/api/v1/bci/ws"
    assert ws_cfg["heartbeat_interval_sec"] == 15.0
    assert "cortex_ws_url" in ws_cfg


def test_to_environment_summary_export():
    """Verify environment setup summary telemetry output."""
    mgr = DashboardConfigManager()
    env_sum = mgr.to_environment_summary()

    assert env_sum["app_name"] == "SynaptiMesh Dashboard"
    assert "environment" in env_sum
    assert "python_version" in env_sum
    assert env_sum["server"]["port"] == 8000
    assert env_sum["websocket"]["enabled"] is True


def test_api_get_dashboard_config():
    """Verify GET /api/v1/config/dashboard returns full configuration."""
    response = client.get("/api/v1/config/dashboard")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "config" in data
    assert data["config"]["app_name"] == "SynaptiMesh Dashboard"


def test_api_post_dashboard_config_update():
    """Verify POST /api/v1/config/dashboard updates configuration dynamically."""
    payload = {
        "log_level": "WARNING",
        "ws_heartbeat_interval_sec": 12.0,
        "power_threshold": 0.80
    }
    response = client.post("/api/v1/config/dashboard", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["config"]["log_level"] == "WARNING"
    assert data["config"]["ws_heartbeat_interval_sec"] == 12.0
    assert data["config"]["power_threshold"] == 0.80

    # Verify global manager updated
    current_cfg = get_dashboard_config()
    assert current_cfg.power_threshold == 0.80


def test_api_get_websocket_config():
    """Verify GET /api/v1/config/websocket returns WebSocket layer parameters."""
    response = client.get("/api/v1/config/websocket")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "websocket" in data
    assert data["websocket"]["enabled"] is True
    assert data["websocket"]["path"] == "/ws"


def test_api_get_environment_summary():
    """Verify GET /api/v1/config/environment returns environment summary."""
    response = client.get("/api/v1/config/environment")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "environment" in data
    assert data["environment"]["server"]["port"] == 8000
