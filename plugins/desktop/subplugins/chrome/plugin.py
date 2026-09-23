from plugin_sdk.interfaces.desktop_plugin import DesktopPluginInterface
from .commands import COMMANDS
from .handlers import open_predefined_article, scroll_up, scroll_down, open_search_bar, close_app
from .widget import get_widget

class ChromePlugin(DesktopPluginInterface):
    plugin_id = "chrome"
    
    def get_widget(self):
        return get_widget()
        
    async def execute(self, command, payload=None):
        if command not in COMMANDS: return {"status": "error", "message": "Unknown command"}
        if command == "open_predefined_article": return open_predefined_article()
        if command == "scroll_up": return scroll_up()
        if command == "scroll_down": return scroll_down()
        if command == "open_search_bar": return open_search_bar()
        if command == "close_app": return close_app()
