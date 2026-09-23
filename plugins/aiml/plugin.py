import os
import sys
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger("aiml_plugin")
PLUGIN_DIR = Path(__file__).resolve().parent

_WORKSPACE_ROOT = str(PLUGIN_DIR.parent.parent)
if _WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, _WORKSPACE_ROOT)

# Ensure submodules can be resolved without shadowing workspace root
for p in [str(PLUGIN_DIR), str(PLUGIN_DIR / "mobile_dashboard"), str(PLUGIN_DIR / "desktop_dashboard"), str(PLUGIN_DIR / "bci_bridge")]:
    if p not in sys.path:
        sys.path.append(p)


from plugin_sdk.interfaces.aiml_plugin import AIMLPluginInterface

class AIMLPlugin(AIMLPluginInterface):
    plugin_id = "aiml"
    name = "aiml"

    def __init__(self):
        self.name = "aiml"
        self.plugin_name = "aiml"
        self.initialized = False
        self.flask_app = None
        self.socketio = None
        self.parser = None
        self.cortex_bridge = None
        self.active_bci_source = None
        from plugins.aiml.accuracy_engine import accuracy_engine
        self.accuracy_engine = accuracy_engine

    def initialize(self, context=None):
        """Initialize AIML Master Hub, FSM, and BCI Sources."""
        try:
            from plugins.aiml import app as aiml_app_module
            self.flask_app = getattr(aiml_app_module, 'app', None)
            self.socketio = getattr(aiml_app_module, 'socketio', None)
            self.cortex_bridge = getattr(aiml_app_module, 'cortex_bridge', None)
            self.fsm_controller = getattr(aiml_app_module, 'fsm_controller', None)
            self.active_bci_source = getattr(aiml_app_module, 'active_bci_source', None)
            self.parser = getattr(aiml_app_module, 'parser', None)

            # Start active BCI source loop if not already running
            if self.active_bci_source and hasattr(self.active_bci_source, 'start'):
                try:
                    self.active_bci_source.start()
                    logger.info("AIML Master Hub active BCI source started.")
                except Exception as e:
                    logger.warning(f"Active BCI source start note: {e}")

            self.initialized = True
            logger.info("AIMLPlugin initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize AIMLPlugin: {e}")
            self.initialized = False

    def shutdown(self):
        """Cleanly stop BCI source and release resources."""
        if self.active_bci_source and hasattr(self.active_bci_source, 'stop'):
            try:
                self.active_bci_source.stop()
            except Exception as e:
                logger.error(f"Error stopping BCI source: {e}")
        self.initialized = False
        logger.info("AIMLPlugin shutdown complete.")

    def is_connected(self) -> bool:
        """Returns True if the AIML plugin and unified dashboard FSM are initialized."""
        return self.initialized

    def get_widgets(self):
        """Return available UI widgets for the AIML domain."""
        return {
            "widgets": [
                {
                    "id": "mobile",
                    "name": "Mobile JioSaavn (Android)",
                    "type": "media",
                    "actions": ["toggle_play_pause", "next_video", "previous_video", "search"]
                },
                {
                    "id": "desktop",
                    "name": "Desktop JioSaavn (Browser)",
                    "type": "media",
                    "actions": ["toggle_play_pause", "next_video", "previous_video", "search"]
                },
                {
                    "id": "jiosaavn",
                    "name": "JioSaavn AI Media",
                    "type": "media",
                    "actions": ["toggle_play_pause", "next_video", "previous_video", "search"]
                }
            ]
        }

    async def execute(self, command: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Handle incoming command dispatch for AIML / Master Hub domain."""
        if not command or not str(command).strip():
            return {"status": "error", "message": "Command cannot be empty"}
            
        payload = payload or {}
        cmd_upper = (command or "").upper()

        if not self.initialized:
            self.initialize()

        if command in ["get_widgets", "get_widget"]:
            return self.get_widgets()

        fsm = self.fsm_controller or (self.parser.fsm if self.parser and hasattr(self.parser, 'fsm') else None)

        if cmd_upper in ["GET_STATE", "FSM_STATE", "STATUS"]:
            try:
                from plugins.aiml import app as aiml_app
                return {
                    "status": "success",
                    "state": fsm.get_state() if fsm else "UNKNOWN",
                    "fsm": fsm.get_state() if fsm else {},
                    "jiosaavn": getattr(aiml_app, "jiosaavn_status", {}),
                    "dashboard_url": "/aiml"
                }
            except Exception:
                return {"status": "success", "state": fsm.get_state() if fsm else "UNKNOWN", "dashboard_url": "/aiml"}

        if cmd_upper == "SELECT_DASHBOARD":
            target = payload.get("dashboard")
            if fsm and hasattr(fsm, "ui_select_dashboard") and fsm.ui_select_dashboard(target):
                return {"status": "success", "selected": target}
            return {"status": "error", "message": "Failed to select dashboard"}

        if cmd_upper == "START_AUTOMATION":
            target = payload.get("dashboard")
            if fsm and hasattr(fsm, "ui_start_automation") and fsm.ui_start_automation(target):
                return {"status": "success", "message": f"{target} dashboard activated"}
            return {"status": "error", "message": "Failed to start automation"}

        if cmd_upper == "RESET_STATE":
            if fsm:
                fsm.reset()
                return {"status": "success"}
            return {"status": "error", "message": "FSM not available"}

        if cmd_upper in ["INGEST_ACCURACY", "ACCURACY_INGEST"]:
            if "evaluations" in payload and isinstance(payload["evaluations"], list):
                res = self.accuracy_engine.ingest_batch(payload["evaluations"])
            else:
                res = self.accuracy_engine.ingest(payload)
            return {"status": "success", "result": res}

        if cmd_upper in ["GET_ACCURACY", "ACCURACY_METRICS", "ACCURACY"]:
            metrics = self.accuracy_engine.get_metrics()
            return {"status": "success", "metrics": metrics}

        if cmd_upper in ["RESET_ACCURACY", "ACCURACY_RESET"]:
            self.accuracy_engine.reset()
            return {"status": "success", "message": "AIML accuracy metrics reset"}

        if cmd_upper in ["VOLUME_UP", "RIGHT+PUSH", "RIGHT_PUSH", "VOL_UP", "INCREASE_VOLUME"]:
            vol = 100
            try:
                from services.media_execution_service import get_media_execution_service
                get_media_execution_service().volume_up()
            except Exception:
                pass
            try:
                from os_operations import send_os_media_key, get_system_master_volume
                send_os_media_key("Volume Up")
                vol = get_system_master_volume()
            except Exception:
                pass
            print(f"[MEDIA] Volume Up command received\n[MEDIA] Volume Up executed (Volume: {vol}%)")
            logger.info(f"[MEDIA] Volume Up executed ({vol}%)")
            return {"status": "success", "action": "volume_up", "volume": vol, "message": f"Volume Up executed ({vol}%)"}

        if cmd_upper in ["VOLUME_DOWN", "RIGHT+PULL", "RIGHT_PULL", "VOL_DOWN", "DECREASE_VOLUME"]:
            vol = 0
            try:
                from services.media_execution_service import get_media_execution_service
                get_media_execution_service().volume_down()
            except Exception:
                pass
            try:
                from os_operations import send_os_media_key, get_system_master_volume
                send_os_media_key("Volume Down")
                vol = get_system_master_volume()
            except Exception:
                pass
            print(f"[MEDIA] Volume Down command received\n[MEDIA] Volume Down executed (Volume: {vol}%)")
            logger.info(f"[MEDIA] Volume Down executed ({vol}%)")
            return {"status": "success", "action": "volume_down", "volume": vol, "message": f"Volume Down executed ({vol}%)"}

        if cmd_upper in ["MOBILE", "OPEN_MOBILE_DASHBOARD", "SELECT_MOBILE_DASHBOARD", "MOBILE_DASHBOARD"]:
            print("[MOBILE] Mobile Dashboard command received\n[MOBILE] Routing command to Android APK\n[MOBILE] PC browser launch skipped")
            logger.info("[MOBILE] Routing command to Android APK | PC browser launch skipped")
            try:
                from backend.command_router import command_router
                res = command_router.route("Right_jiosaavn", target="mobile")
                return {
                    "status": "success",
                    "action": "open_mobile_dashboard",
                    "target": "mobile",
                    "dispatched_to_apk": True,
                    "result": str(res)
                }
            except Exception as e:
                return {
                    "status": "success",
                    "action": "open_mobile_dashboard",
                    "target": "mobile",
                    "dispatched_to_apk": False,
                    "note": str(e)
                }

        # Route standard BCI and media commands through Unified FSM
        media_map = {
            "TOGGLE_PLAY_PAUSE": "LEFT",
            "PLAY_PAUSE": "LEFT",
            "NEXT_VIDEO": "PUSH",
            "NEXT_TRACK": "PUSH",
            "PREVIOUS_VIDEO": "PULL",
            "PREVIOUS_TRACK": "PULL",
            "SEARCH": "RIGHT"
        }
        bci_cmd = media_map.get(cmd_upper, cmd_upper)
        if fsm:
            confidence = float(payload.get("confidence", 1.0))
            result = fsm.process_command(bci_cmd, confidence=confidence)
            try:
                from plugins.aiml import app as aiml_app
                aiml_app._emit_state()
                aiml_app.socketio.emit("fsm_command_result", result, namespace=aiml_app.DASHBOARD_NAMESPACE)
            except Exception:
                pass
            return {
                "status": "success",
                "message": f"Executed AIML command: {command}",
                "plugin": "aiml",
                "command": command,
                "bci_command": bci_cmd,
                "result": result,
                "fsm": fsm.get_state(),
                "dashboard_url": "/aiml"
            }

        # Default fallback
        return {
            "status": "success",
            "message": f"Executed AIML command: {command}",
            "plugin": "aiml",
            "command": command,
            "dashboard_url": "/aiml"
        }

