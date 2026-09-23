import pytest
from plugin_sdk.interfaces.base_plugin import BasePlugin
from plugin_sdk.interfaces.desktop_plugin import DesktopPluginInterface
from plugin_sdk.interfaces.iot_plugin import IoTPluginInterface
from plugin_sdk.interfaces.embedded_plugin import EmbeddedPluginInterface
from plugin_sdk.interfaces.aiml_plugin import AIMLPluginInterface

from plugins.desktop.plugin import DesktopPlugin
from plugins.embedded.plugin import EmbeddedPlugin
from plugins.iot.plugin import IoTPlugin
from plugins.aiml.plugin import AIMLPlugin

from core.plugin_manager.manager import load_plugins, get_plugin, execute


def test_interface_hierarchy():
    """Verify that all domain interfaces inherit from BasePlugin."""
    assert issubclass(DesktopPluginInterface, BasePlugin)
    assert issubclass(IoTPluginInterface, BasePlugin)
    assert issubclass(EmbeddedPluginInterface, BasePlugin)
    assert issubclass(AIMLPluginInterface, BasePlugin)


def test_plugin_conformance():
    """Verify that all concrete domain plugins inherit from their respective interfaces."""
    desktop = DesktopPlugin()
    embedded = EmbeddedPlugin()
    iot = IoTPlugin()
    aiml = AIMLPlugin()

    assert isinstance(desktop, DesktopPluginInterface)
    assert isinstance(embedded, EmbeddedPluginInterface)
    assert isinstance(iot, IoTPluginInterface)
    assert isinstance(aiml, AIMLPluginInterface)


def test_plugin_manager_loading():
    """Verify that load_plugins registers all 4 domain plugins."""
    load_plugins()
    assert get_plugin("desktop") is not None
    assert get_plugin("embedded") is not None
    assert get_plugin("iot") is not None
    assert get_plugin("aiml") is not None


@pytest.mark.asyncio
async def test_aiml_plugin_execution():
    """Verify AIML plugin execute contract and response format."""
    aiml = AIMLPlugin()
    res_success = await aiml.execute("INFER_INTENT", {"eeg_sample": [0.1, 0.2, 0.3]})
    assert res_success["status"] == "success"
    assert "INFER_INTENT" in res_success["message"]

    res_empty = await aiml.execute("", {})
    assert res_empty["status"] == "error"
    assert "empty" in res_empty["message"]


@pytest.mark.asyncio
async def test_iot_plugin_contract_error_handling():
    """Verify IoT plugin error handling for missing required device_id."""
    iot = IoTPlugin()
    res = await iot.execute("SET_TEMPERATURE", {})
    assert res["status"] == "error"
    assert "device_id" in res["message"]


@pytest.mark.asyncio
async def test_embedded_plugin_contract_error_handling():
    """Verify Embedded plugin error handling for missing app."""
    embedded = EmbeddedPlugin()
    res = await embedded.execute("FORWARD", {})
    assert res["status"] == "error"
    assert "app" in res["message"]


@pytest.mark.asyncio
async def test_manager_unified_dispatch_across_domains():
    """Verify core manager execution across all domain interfaces."""
    load_plugins()

    res_aiml = await execute("aiml", "PREDICT", {"data": 123})
    assert res_aiml["status"] == "success"

    res_iot_err = await execute("iot", "ACTION", {})
    assert res_iot_err["status"] == "error"
