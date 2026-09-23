import logging
import time

logger = logging.getLogger("media_jiosaavn_provider")

class JioSaavnProvider:
    def __init__(self):
        # We define a mapping from Media Manager actions to JioSaavn actions
        self.action_mapping = {
            "PREVIOUS": "PREVIOUS",
            "NEXT": "NEXT",
            "TOGGLE_PLAY_PAUSE": "TOGGLE_PLAY_PAUSE",
            "SEARCH": "SEARCH",
            "PLAY": "PLAY",
            "PAUSE": "PAUSE",
            "RESUME": "RESUME",
            "STOP": "STOP"
        }

    async def execute(self, action: str, payload: dict) -> dict:
        start_time = time.time()
        
        jiosaavn_action = self.action_mapping.get(action)
        if not jiosaavn_action:
            return {
                "status": "FAILED",
                "execution_time_ms": int((time.time() - start_time) * 1000),
                "error": f"Unsupported JioSaavn action: {action}"
            }
            
        try:
            logger.info(f"[JioSaavnProvider] Attempting to execute {jiosaavn_action}")
            try:
                from plugins.aiml.desktop_dashboard.desktop_modules.operate_jiosavaan import JioSaavnController
            except ImportError:
                from plugins.aiml.desktop_dashboard.operate_jiosavaan import JioSaavnController
            # Reusable singleton or new instance
            if not hasattr(self, "_controller") or self._controller is None:
                try:
                    from plugins.aiml import app as aiml_app
                    self._controller = aiml_app.desktop_controller or JioSaavnController()
                except Exception:
                    self._controller = JioSaavnController()

            query = payload.get("query") if payload else None
            res = self._controller.execute_action(jiosaavn_action, query=query)
            execution_time = int((time.time() - start_time) * 1000)

            return {
                "status": "SUCCESS",
                "success": True,
                "execution_time_ms": execution_time,
                "action": action,
                "result": str(res)
            }
                
        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            logger.error(f"[JioSaavnProvider] Error executing {action}: {e}")
            return {
                "status": "FAILED",
                "execution_time_ms": execution_time,
                "error": str(e)
            }
