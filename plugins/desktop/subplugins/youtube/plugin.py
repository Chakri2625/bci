from plugin_sdk.interfaces.desktop_plugin import DesktopPluginInterface
from .commands import COMMANDS
from .handlers import previous_video, next_video, toggle_play_pause, search, close_app, volume_up, volume_down
from .widget import get_widget

class YoutubePlugin(DesktopPluginInterface):
    plugin_id = "youtube"
    
    def get_widget(self):
        return get_widget()
        
    async def execute(self, command, payload=None):
        if command not in COMMANDS: return {"status": "error", "message": "Unknown command"}
        if command == "previous_video": return previous_video()
        if command == "next_video": return next_video()
        if command == "toggle_play_pause": return toggle_play_pause()
        if command == "search": return search(payload)
        if command == "close_app": return close_app()
        if command == "volume_up": return volume_up()
        if command == "volume_down": return volume_down()
