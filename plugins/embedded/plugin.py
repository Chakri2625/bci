from plugins.embedded.registry import load_subplugins
from plugin_sdk.interfaces.embedded_plugin import EmbeddedPluginInterface

class EmbeddedPlugin(EmbeddedPluginInterface):
    plugin_id = "embedded"
    
    def __init__(self):
        self.subplugins = load_subplugins()
        
    async def execute(self, command, payload=None):
        if command == "get_widgets":
            widgets = []
            for name, sp in self.subplugins.items():
                if hasattr(sp, "get_widget"):
                    widgets.append(sp.get_widget())
            return {"widgets": widgets}
            
        if not payload or "app" not in payload:
            return {"status": "error", "message": "Payload missing app info for action routing."}
            
        app = payload["app"]
        registry_map = {
            "RC_CAR": "rc_car"
        }
        
        target = registry_map.get(app)
        if not target or target not in self.subplugins:
            return {"status": "error", "message": f"Subplugin for {app} not found"}
            
        return await self.subplugins[target].execute(command, payload)

    def is_connected(self) -> bool:
        rc_car = self.subplugins.get("rc_car")
        if rc_car:
            if hasattr(rc_car, "is_connected"):
                return rc_car.is_connected()
            if hasattr(rc_car, "sender") and hasattr(rc_car.sender, "is_connected"):
                return rc_car.sender.is_connected()
            if hasattr(rc_car, "sender"):
                return bool(getattr(rc_car.sender, "_mqtt_connected", False))
        return False
