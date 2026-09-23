import os
import sys
import importlib

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

PLUGINS = {}

def register_plugin(plugin_id, plugin_instance):
    PLUGINS[plugin_id] = plugin_instance
    print(f"Registered plugin: {plugin_id}")

def get_plugin(plugin_id):
    if plugin_id not in PLUGINS:
        if plugin_id == "iot":
            try:
                from plugins.iot.plugin import IoTPlugin
                p = IoTPlugin()
                register_plugin("iot", p)
            except Exception as e:
                print(f"Error lazy-loading iot plugin: {e}")
        elif plugin_id == "desktop":
            try:
                from plugins.desktop.plugin import DesktopPlugin
                register_plugin("desktop", DesktopPlugin())
            except Exception:
                pass
        elif plugin_id == "embedded":
            try:
                from plugins.embedded.plugin import EmbeddedPlugin
                register_plugin("embedded", EmbeddedPlugin())
            except Exception:
                pass
        elif plugin_id == "media":
            try:
                from plugins.media.plugin import MediaManagerPlugin
                register_plugin("media", MediaManagerPlugin())
            except Exception:
                pass
        elif plugin_id == "aiml":
            try:
                from plugins.aiml.plugin import AIMLPlugin
                register_plugin("aiml", AIMLPlugin())
            except Exception:
                pass
    return PLUGINS.get(plugin_id)

def get_all_plugins():
    return list(PLUGINS.keys())

def discover_plugins():
    print("Discovering plugins...")
    
def load_plugins():
    print("Loading plugins...")
    try:
        from plugins.desktop.plugin import DesktopPlugin
        register_plugin("desktop", DesktopPlugin())
    except Exception as e:
        print(f"Error loading desktop plugin: {e}")
        
    try:
        from plugins.embedded.plugin import EmbeddedPlugin
        register_plugin("embedded", EmbeddedPlugin())
    except Exception as e:
        print(f"Error loading embedded plugin: {e}")
        
    try:
        from plugins.iot.plugin import IoTPlugin
        iot_plugin = IoTPlugin()
        iot_plugin.initialize(None)
        register_plugin("iot", iot_plugin)
    except ModuleNotFoundError:
        pass
    except Exception as e:
        print(f"Error loading iot plugin: {e}")

    try:
        from plugins.media.plugin import MediaManagerPlugin
        media_plugin = MediaManagerPlugin()
        media_plugin.initialize(None)
        register_plugin("media", media_plugin)
    except Exception as e:
        print(f"Error loading media plugin: {e}")

    try:
        from plugins.aiml.plugin import AIMLPlugin
        aiml_plugin = AIMLPlugin()
        aiml_plugin.initialize(None)
        register_plugin("aiml", aiml_plugin)
    except Exception as e:
        print(f"Error loading aiml plugin: {e}")


import asyncio
import inspect
import logging

logger = logging.getLogger("plugin_manager")

async def execute(plugin_id, command, payload=None):
    plugin = get_plugin(plugin_id)
    if not plugin:
        return {"status": "error", "message": "Plugin not found"}
        
    if not hasattr(plugin, "execute"):
        return {"status": "error", "message": f"Plugin {plugin_id} does not implement execute"}

    try:
        if inspect.iscoroutinefunction(plugin.execute) or asyncio.iscoroutinefunction(plugin.execute):
            return await plugin.execute(command, payload)
        elif callable(plugin.execute):
            result = plugin.execute(command, payload)
            if inspect.isawaitable(result):
                return await result
            return result
        else:
            return {"status": "error", "message": f"Plugin {plugin_id} execute is not callable"}
    except Exception as e:
        logger.error(f"[PluginManager] Error executing command '{command}' on plugin '{plugin_id}': {e}", exc_info=True)
        return {"status": "error", "message": str(e)}

