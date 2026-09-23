"""
Test suite for verifying placeholder dashboard removal, fast domain routing,
minimal transition locking, and real team dashboard preservation in SynaptiMesh.
"""
import os
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_index_html_has_no_placeholder_dashboards():
    """Verify that index.html does not contain legacy placeholder dashboard HTML/JS."""
    template_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "plugins",
        "desktop",
        "ui",
        "templates",
        "index.html"
    )
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Legacy placeholder DOM IDs must not exist
    assert "iot-connect-stage" not in content, "Found legacy #iot-connect-stage in index.html"
    assert 'id="rc-car-ui"' not in content, "Found legacy #rc-car-ui in index.html"
    assert 'id="rc-car-canvas"' not in content, "Found legacy #rc-car-canvas in index.html"

    # Legacy placeholder JS arrays must not exist
    assert "iotLevelTwoMap" not in content, "Found legacy iotLevelTwoMap in index.html"
    assert "embeddedLevelTwoMap" not in content, "Found legacy embeddedLevelTwoMap in index.html"
    assert "aimlLevelTwoMap" not in content, "Found legacy aimlLevelTwoMap in index.html"
    assert "iotDeviceActions" not in content, "Found legacy iotDeviceActions in index.html"

    # Legacy 3D RC car simulation functions/intervals must not exist
    assert "init3DScene" not in content, "Found legacy init3DScene in index.html"
    assert "fetchRcCarStatus" not in content, "Found legacy fetchRcCarStatus in index.html"


def test_index_html_has_fast_router_and_transition_overlay():
    """Verify index.html contains the instant router and minimal transition overlay."""
    template_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "plugins",
        "desktop",
        "ui",
        "templates",
        "index.html"
    )
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Transition overlay elements must exist
    assert 'id="domainTransitionOverlay"' in content
    assert "setDomainTransitionLock" in content
    assert "resolveAndOpenDomainDashboard" in content

    # All 4 domain routes must be registered in router
    assert "'PYTHON': '/'" in content or '"PYTHON": "/"' in content
    assert "'IOT': '/iot'" in content or '"IOT": "/iot"' in content
    assert "'EMBEDDED': '/embedded'" in content or '"EMBEDDED": "/embedded"' in content
    assert "'AIML': '/aiml'" in content or '"AIML": "/aiml"' in content


def test_all_domain_endpoints_return_real_dashboards():
    """Verify that all domain endpoints serve their respective authentic dashboards."""
    # 1. Desktop / Python Main Dashboard
    res_py = client.get("/")
    assert res_py.status_code == 200
    assert b"SYNAPTIMESH" in res_py.content or b"SynaptiMesh" in res_py.content

    # 2. Standalone IoT Team Dashboard
    res_iot = client.get("/iot")
    assert res_iot.status_code in (200, 302, 307)
    if res_iot.status_code == 200:
        assert b"IoT" in res_iot.content or b"device" in res_iot.content.lower()

    # 3. Standalone Embedded Team Dashboard
    res_emb = client.get("/embedded")
    assert res_emb.status_code == 200
    assert b"EMBEDDED" in res_emb.content or b"Embedded" in res_emb.content

    # 4. Standalone AI/ML Team Dashboard
    res_aiml = client.get("/aiml")
    assert res_aiml.status_code == 200
    assert b"Unified BCI Dashboard" in res_aiml.content or b"AIML" in res_aiml.content or b"JioSaavn" in res_aiml.content


def test_level_1_domain_matrix_selection():
    """Verify Level 1 domain command navigation correctly transitions domain state."""
    # Check navigation state endpoint
    res = client.get("/api/navigation/state")
    assert res.status_code == 200
    data = res.json()
    assert data["current_level"] == 1

    # Verify PULL selects EMBEDDED
    res_pull = client.post("/api/navigation/command", json={"command": "pull"})
    assert res_pull.status_code == 200
    data_pull = res_pull.json()
    assert data_pull["status"] == "success"
    assert data_pull["target_domain"] == "EMBEDDED"
