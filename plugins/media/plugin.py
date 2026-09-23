import logging
import asyncio
import uuid
from plugin_sdk.interfaces.base_plugin import BasePlugin
from core.state.state_manager import state_manager
from plugins.media.logger import media_logger
from plugins.media.providers.youtube_provider import YouTubeProvider
from plugins.media.providers.jiosaavn_provider import JioSaavnProvider
try:
    from services.media_execution_service import get_media_execution_service
except ImportError:
    import sys
    import os
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
    from services.media_execution_service import get_media_execution_service

from plugin_sdk.interfaces.media_plugin import MediaPluginInterface

logger = logging.getLogger("media_manager")

class MediaManagerPlugin(MediaPluginInterface, BasePlugin):
    plugin_id = "media"
    
    def __init__(self):
        self.providers = {
            "YOUTUBE": YouTubeProvider(),
            "JIOSAAVN": JioSaavnProvider()
        }
        self.execution_service = get_media_execution_service()
        
    def initialize(self, context):
        logger.info("[MediaManager] Initialized")
        
    def _resolve_action(self, command: str, domain: str, app: str, level: int) -> str:
        """
        Resolves a BCI command (PUSH, PULL, LEFT, RIGHT) to a Media Operation
        (PREVIOUS, NEXT, TOGGLE_PLAY_PAUSE, SEARCH, etc.)
        """
        if app == "YOUTUBE":
            mapping = {
                "PUSH": "PREVIOUS",
                "PULL": "NEXT",
                "LEFT": "TOGGLE_PLAY_PAUSE",
                "RIGHT": "SEARCH"
            }
            return mapping.get(command, command)
            
        if app == "JIOSAAVN":
            mapping = {
                "PUSH": "PREVIOUS",
                "PULL": "NEXT",
                "LEFT": "TOGGLE_PLAY_PAUSE",
                "RIGHT": "SEARCH"
            }
            return mapping.get(command, command)
            
        return command

    async def execute(self, command: str, payload: dict = None) -> dict:
        """
        command: The BCI command (e.g. 'LEFT') or an already resolved action
        payload: { "domain": "PYTHON", "app": "YOUTUBE", "session": "default", ... }
        """
        if payload is None:
            payload = {}
            
        session_id = payload.get("session", "default")
        state = state_manager.get_state(session_id)
        
        # Get context
        current_domain = payload.get("domain", state.get("active_domain"))
        current_app = payload.get("app", state.get("active_app"))
        current_level = state.get("current_level", 3)
        
        # TASK 1/3: Timeout boundary for every media execution path
        try:
            from core.config.retry_config import COMMAND_TIMEOUT
            timeout = COMMAND_TIMEOUT
        except ImportError:
            timeout = 10.0
        
        # 1. Resolve BCI command to Media Action
        action = self._resolve_action(command, current_domain, current_app, current_level)
        logger.info(f"[MediaManager] Resolved command {command} -> {action} for app {current_app}")
        
        # 2. Select Provider or delegate to execution service (original routing preserved)
        provider = self.providers.get(current_app)
        if provider:
            # Provider path (e.g. desktop browser automation via YouTube/JioSaavn providers).
            # TASK 1/3: wrap with a real-time timeout boundary so a hung provider
            # cannot block the pipeline indefinitely.
            try:
                result = await asyncio.wait_for(provider.execute(action, payload), timeout=timeout)
            except asyncio.TimeoutError:
                err_msg = f"Media provider execution timed out after {timeout}s"
                logger.error(f"[MediaManager] TIMEOUT: {err_msg} (app={current_app}, action={action})")
                result = {
                    "success": False,
                    "status": "failed",
                    "error": err_msg,
                    "message": "Command execution timed out",
                    "timed_out": True,
                    "execution_time_ms": round(timeout * 1000.0, 2),
                }
        else:
            # Fallback to the unified media execution service (async, timeout-protected,
            # with lifecycle/event/logging/metrics integration built in).
            cmd_payload = dict(payload)
            if current_app:
                cmd_payload["app"] = current_app
            cmd_payload["domain"] = current_domain or "MEDIA"
            cmd_payload["session"] = session_id
            cmd_payload["command_id"] = payload.get("command_id")
            
            try:
                result = await self.execution_service.execute_command_async(
                    action=action,
                    payload=cmd_payload,
                    command_id=payload.get("command_id"),
                    timeout=timeout,
                )
            except Exception as e:
                logger.error(f"[MediaManager] Execution error: {e}", exc_info=True)
                result = {
                    "success": False,
                    "status": "failed",
                    "error": str(e),
                    "message": "Media execution failed"
                }
        
        # 3. Log Activity (legacy - keep for backwards compatibility)
        media_type_map = {
            "YOUTUBE": "VIDEO",
            "JIOSAAVN": "AUDIO"
        }
        activity = {
            "session_id": session_id,
            "level": current_level,
            "domain": current_domain,
            "application": current_app,
            "command": command,
            "action": action,
            "media_type": media_type_map.get(current_app, "UNKNOWN"),
            "source": current_app or "MEDIA_SERVICE",
            "status": result.get("status"),
            "execution_time_ms": result.get("execution_time_ms", 0),
            "error": result.get("error")
        }
        media_logger.log_activity(activity)
        
        # 4. Return standard response
        status_val = str(result.get("status", "")).upper()
        success = result.get("success", status_val == "SUCCESS")
        response = {
            "success": success,
            "status": "success" if success else result.get("status", "failed").lower(),  
            "domain": "MEDIA",
            "application": current_app,
            "command": command,
            "action": action,
            "message": result.get("message", "Media operation completed") if success else result.get("message", "Media operation failed"),
            "details": result.get("details", {})
        }
        if not success:
            response["error"] = result.get("error")
            
        return response


MediaHandler = MediaManagerPlugin

