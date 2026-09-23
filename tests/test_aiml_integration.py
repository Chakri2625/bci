import pytest
from fastapi.testclient import TestClient
from main import app
from core.state.state_manager import state_manager
from core.plugin_manager.manager import get_plugin, load_plugins, PLUGINS

client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_state():
    state_manager.states.clear()
    PLUGINS.clear()
    load_plugins()

def test_aiml_plugin_discovery():
    aiml_plugin = get_plugin("aiml")
    assert aiml_plugin is not None
    assert aiml_plugin.name == "aiml"
    result = aiml_plugin.get_widgets()
    widget_ids = [w["id"] for w in result.get("widgets", [])]
    assert "mobile" in widget_ids
    assert "desktop" in widget_ids
    assert "jiosaavn" in widget_ids

def test_aiml_dashboard_html():
    response = client.get("/aiml")
    assert response.status_code == 200
    assert "Unified BCI Dashboard" in response.text or "BrainFlow BCI System" in response.text

def test_aiml_fsm_state_endpoint():
    response = client.get("/api/fsm/state")
    assert response.status_code == 200
    data = response.json()
    assert "fsm" in data
    assert "current_state" in data["fsm"]
    assert "jiosaavn" in data
    assert "overall" in data["jiosaavn"]

def test_aiml_bci_command_push():
    response = client.post("/api/bci/command", json={"command": "PUSH"})
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "success"
    assert "fsm" in data

def test_aiml_phase2_routing():
    from core.state.state_manager import state_manager
    # Set to Level 2 and select AIML
    state_manager.update_state("default", {"current_level": 2, "active_domain": "AIML"})
    
    # In Level 2, command "push" selects MOBILE
    response = client.post("/api/v1/bci/command", json={"command": "push"})
    assert response.status_code == 200
    data = response.json()
    assert data["resolved"]["app"] == "MOBILE"

def test_jiosaavn_play_action_normalization():
    try:
        from plugins.aiml.desktop_dashboard.desktop_modules.operate_jiosavaan import JioSaavnController
    except ImportError:
        from plugins.aiml.desktop_dashboard.operate_jiosavaan import JioSaavnController
    from unittest.mock import MagicMock
    
    ctrl = JioSaavnController()
    ctrl.player_engine = MagicMock()
    ctrl.player_engine.play_pause.return_value = True

    # Test exact user input: 'paly'
    res_paly = ctrl.execute_action("paly")
    assert "Play / Pause" in res_paly and "Success" in res_paly
    assert ctrl.player_engine.play_pause.call_count == 1

    # Test canonical: 'play'
    res_play = ctrl.execute_action("play")
    assert "Play / Pause" in res_play and "Success" in res_play
    assert ctrl.player_engine.play_pause.call_count == 2

    # Test 'toggle_play_pause'
    res_toggle = ctrl.execute_action("toggle_play_pause")
    assert "Play / Pause" in res_toggle and "Success" in res_toggle
    assert ctrl.player_engine.play_pause.call_count == 3

def test_jiosaavn_provider_execution():
    from plugins.media.providers.jiosaavn_provider import JioSaavnProvider
    from unittest.mock import MagicMock, patch
    import asyncio

    provider = JioSaavnProvider()
    mock_ctrl = MagicMock()
    mock_ctrl.execute_action.return_value = "Executed Play / Pause (Success)"
    provider._controller = mock_ctrl

    res = asyncio.run(provider.execute("PLAY", {}))
    assert res["status"] == "SUCCESS"
    assert res["action"] == "PLAY"
    mock_ctrl.execute_action.assert_called_with("PLAY", query=None)
