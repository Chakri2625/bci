from core.plugin_manager.manager import execute
import logging
import time
from plugins.media.providers.base_provider import BaseMediaProvider

logger = logging.getLogger("media_youtube_provider")

class YouTubeProvider(BaseMediaProvider):
    provider_name: str = "YOUTUBE"

    def __init__(self):
        # We define a mapping from Media Manager actions to existing desktop youtube plugin actions
        self.action_mapping = {
            "PREVIOUS": "previous_video",
            "NEXT": "next_video",
            "TOGGLE_PLAY_PAUSE": "toggle_play_pause",
            "SEARCH": "search"
        }

    def get_supported_actions(self):
        return list(self.action_mapping.keys())

    async def execute(self, action: str, payload: dict = None) -> dict:
        start_time = time.time()
        
        desktop_action = self.action_mapping.get(action)
        if not desktop_action:
            return {
                "status": "FAILED",
                "success": False,
                "action": action,
                "error": f"Unsupported YouTube action: {action}"
            }
            
        try:
            # We call the existing desktop plugin with app="YOUTUBE"
            desktop_payload = {"app": "YOUTUBE"}
            if payload:
                desktop_payload.update(payload)
                
            logger.info(f"[YouTubeProvider] Executing {desktop_action}")
            result = await execute("desktop", desktop_action, desktop_payload)
            
            execution_time = int((time.time() - start_time) * 1000)
            
            # Normalize the result structure for MediaManager
            if isinstance(result, dict) and result.get("status") == "success":
                return {
                    "status": "SUCCESS",
                    "success": True,
                    "action": action,
                    "execution_time_ms": execution_time,
                    "message": result.get("message", f"YouTube {action} executed successfully"),
                    "details": result
                }
            else:
                return {
                    "status": "FAILED",
                    "success": False,
                    "action": action,
                    "execution_time_ms": execution_time,
                    "error": result.get("message") if isinstance(result, dict) else "Unknown error from desktop plugin",
                    "details": result
                }
                
        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            logger.error(f"[YouTubeProvider] Error executing {action}: {e}")
            return {
                "status": "FAILED",
                "success": False,
                "action": action,
                "execution_time_ms": execution_time,
                "error": str(e)
            }

