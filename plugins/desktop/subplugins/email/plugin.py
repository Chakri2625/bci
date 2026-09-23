from plugin_sdk.interfaces.desktop_plugin import DesktopPluginInterface
from .commands import COMMANDS
from .handlers import compose_email, send_email, close_app
from .widget import get_widget

class EmailPlugin(DesktopPluginInterface):
    plugin_id = "email"
    
    def get_widget(self):
        return get_widget()
        
    async def execute(self, command, payload=None):
        if command not in COMMANDS: return {"status": "error", "message": "Unknown command"}
        if command == "compose_email": return compose_email(payload)
        if command == "send_email": return send_email(payload)
        if command == "close_app": return close_app(payload)
