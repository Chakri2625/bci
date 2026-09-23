from plugin_sdk.interfaces.desktop_plugin import DesktopPluginInterface
from .handlers import open_notepad, save_file, close_app
from .commands import COMMANDS
from .widget import get_widget

class NotepadPlugin(DesktopPluginInterface):
    plugin_id = "notepad"
    
    def get_widget(self):
        return get_widget()
        
    async def execute(self, command, payload=None):
        if command not in COMMANDS:
            return {"status": "error", "message": "Unknown command"}
            
        if command == "open_notepad":
            return open_notepad()
        elif command == "save_file":
            return save_file()
        elif command == "close_app":
            return close_app()
