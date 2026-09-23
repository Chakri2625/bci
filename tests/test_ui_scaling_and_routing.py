from pathlib import Path
from core.validation.command_normalizer import normalize_command
from core.routing.rule_router import resolve_command


def test_command_normalizer_domain_aliases():
    assert normalize_command("embedded") == "PULL"
    assert normalize_command("robotics") == "PULL"
    assert normalize_command("iot") == "LEFT"
    assert normalize_command("aiml") == "RIGHT"
    assert normalize_command("ai") == "RIGHT"
    assert normalize_command("desktop") == "PUSH"
    assert normalize_command("python") == "PUSH"
    assert normalize_command("w") == "PUSH"
    assert normalize_command("s") == "PULL"
    assert normalize_command("a") == "LEFT"
    assert normalize_command("d") == "RIGHT"


def test_rule_router_domain_routing():
    # Test level 1 domain resolution
    res_embedded = resolve_command("PULL", {"level": 1})
    assert res_embedded["domain"] == "EMBEDDED"
    assert res_embedded["level"] == 2
    
    res_iot = resolve_command("LEFT", {"level": 1})
    assert res_iot["domain"] == "IOT"
    assert res_iot["level"] == 2

    res_aiml = resolve_command("RIGHT", {"level": 1})
    assert res_aiml["domain"] == "AIML"
    assert res_aiml["level"] == 2

    res_desktop = resolve_command("PUSH", {"level": 1})
    assert res_desktop["domain"] == "PYTHON"
    assert res_desktop["level"] == 2


def test_index_html_ui_scaling_and_authoritative_routing():
    html_path = Path("plugins/desktop/ui/templates/index.html")
    assert html_path.exists(), "index.html template must exist"
    content = html_path.read_text(encoding="utf-8")

    # Issue 1: UI scaling and keyboard button visibility
    assert ".sys-state-compact" in content
    assert 'id="systemStateBadge"' in content
    assert 'id="shortcutsBtn"' in content

    # Responsive Grid & Media Breakpoints
    assert ".workspace-grid" in content
    assert "@media (max-width: 1480px)" in content
    assert "@media (max-width: 1200px)" in content
    assert "@media (max-width: 992px)" in content
    assert "@media (max-width: 860px)" in content
    assert "repeat(auto-fit, minmax(clamp(" in content

    # Issue 2: Authoritative domain dashboard mapping and resolver
    assert "AUTHORITATIVE_DOMAIN_DASHBOARDS" in content
    assert "resolveAndOpenDomainDashboard" in content
    assert "'/aiml'" in content or '"/aiml"' in content or "/aiml" in content
    assert "'/iot'" in content or '"/iot"' in content or "/iot" in content
    assert "'/embedded'" in content or '"/embedded"' in content or "/embedded" in content
    assert "handleDomainCardClick" in content
    assert "appFramingState" in content
    assert "startTemporalFraming" in content
    assert "completeTemporalFraming" in content


def test_authoritative_domain_dashboard_endpoints():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)

    # Verify Master Dashboard
    res_master = client.get("/")
    assert res_master.status_code == 200

    # Verify IoT Team Console Dashboard
    res_iot = client.get("/iot")
    assert res_iot.status_code == 200
    assert "IoT Team Console" in res_iot.text or "MasterHub" in res_iot.text

    # Verify Embedded Team Dashboard
    res_embedded = client.get("/embedded")
    assert res_embedded.status_code == 200
    assert "Master Hub" in res_embedded.text or "Embedded" in res_embedded.text

    # Verify AIML Hub
    res_aiml = client.get("/aiml")
    assert res_aiml.status_code == 200
