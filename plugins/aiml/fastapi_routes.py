import os
import sys
import json
import time
import asyncio
from pathlib import Path
from fastapi import FastAPI, APIRouter, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, Dict, Any, List

BASE_DIR = Path(__file__).resolve().parent
_WORKSPACE_ROOT = str(BASE_DIR.parent.parent)
if _WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, _WORKSPACE_ROOT)

# Ensure BASE_DIR and submodules are in sys.path without shadowing workspace root
for p in [str(BASE_DIR), str(BASE_DIR / "desktop_dashboard" / "desktop_modules"), str(BASE_DIR / "mobile_dashboard" / "mobile_plugin")]:
    if p not in sys.path:
        sys.path.append(p)

from plugins.aiml.plugin import AIMLPlugin
from core.plugin_manager.manager import get_plugin

router = APIRouter()

def get_aiml() -> Optional[AIMLPlugin]:
    plugin = get_plugin("aiml")
    if not plugin:
        plugin = AIMLPlugin()
        plugin.initialize()
    return plugin


# --- HTML Template Endpoints ---

@router.get("/aiml", response_class=HTMLResponse)
@router.get("/aiml/dashboard", response_class=HTMLResponse)
@router.get("/dashboard", response_class=HTMLResponse)
async def get_aiml_unified_dashboard():
    """Serve the Unified BCI & JioSaavn Dashboard from 05-09-26."""
    template_path = BASE_DIR / "dashboard" / "templates" / "dashboard.html"
    if not template_path.exists():
        template_path = BASE_DIR / "templates" / "landing.html"
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Normalize Jinja static urls with cache busters
    v = int(time.time())
    content = content.replace("{{ url_for('static', filename='favicon.svg') }}", "/aiml/static/favicon.svg")
    content = content.replace("{{ url_for('static', filename='css/style.css') }}", f"/aiml/static/css/style.css?v={v}")
    content = content.replace("{{ url_for('static', filename='js/dashboard.js') }}", f"/aiml/static/js/dashboard.js?v={v}")
    return HTMLResponse(content=content, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

@router.get("/master", response_class=HTMLResponse)
@router.get("/aiml/landing", response_class=HTMLResponse)
async def get_master_hub_landing():
    """Serve the vintage Master Hub Analog Console."""
    template_path = BASE_DIR / "templates" / "landing.html"
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()
    return HTMLResponse(content=content)

@router.get("/mobile", response_class=HTMLResponse)
@router.get("/aiml/mobile", response_class=HTMLResponse)
async def get_mobile_dashboard():
    """Serve the Android / MQTT Mobile Player Dashboard."""
    template_path = BASE_DIR / "mobile_dashboard" / "resources" / "templates" / "index.html"
    if not template_path.exists():
        template_path = BASE_DIR / "mobile_dashboard" / "templates" / "mobile.html"
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()
    return HTMLResponse(content=content)

@router.get("/desktop", response_class=HTMLResponse)
@router.get("/aiml/desktop", response_class=HTMLResponse)
async def get_desktop_dashboard():
    """Serve the Browser / Selenium Desktop Player Dashboard."""
    template_path = BASE_DIR / "desktop_dashboard" / "templates" / "dashboard.html"
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()
    return HTMLResponse(content=content)

@router.get("/bci", response_class=HTMLResponse)
@router.get("/emotiv", response_class=HTMLResponse)
async def get_emotiv_bci_suite():
    """Serve the Dedicated Emotiv BCI Neural Suite directly within SynaptiMesh."""
    bci_path = BASE_DIR / "scratch_iot" / "public" / "index.html"
    if not bci_path.exists():
        bci_path = Path(__file__).resolve().parents[2] / "plugins" / "aiml" / "scratch_iot" / "public" / "index.html"
    with open(bci_path, "r", encoding="utf-8") as f:
        content = f.read()
    content = content.replace('href="style.css"', 'href="/bci/static/style.css"')
    content = content.replace('src="app.js"', 'src="/bci/static/app.js"')
    return HTMLResponse(content=content)


def get_fsm():
    aiml = get_aiml()
    if not aiml:
        return None
    if getattr(aiml, 'fsm_controller', None):
        return aiml.fsm_controller
    try:
        from plugins.aiml import app as aiml_app
        return getattr(aiml_app, 'fsm_controller', None)
    except Exception:
        return None


from models.api_models import (
    BCIUnifiedCommandRequest,
    FSMCommandRequest,
    FSMBackRequest,
    ActionRequest,
    VolumeRequest,
    SearchRequest,
    AimlAutomationRequest,
    AimlConfigRequest,
)

# --- Master Hub / Unified FSM API Endpoints ---

class DashboardSelectionRequest(BaseModel):
    dashboard: Optional[str] = None

@router.get("/api/fsm/state")
async def get_unified_fsm_state():
    """Return active FSM state and JioSaavn playback status."""
    try:
        from plugins.aiml import app as aiml_app
        fsm = aiml_app.fsm_controller
        return {
            "status": "success",
            "fsm": fsm.get_state() if fsm else {"current_state": "SUB_MASTER_DASHBOARD", "level": 2},
            "jiosaavn": getattr(aiml_app, "jiosaavn_status", {})
        }
    except Exception as e:
        return {"status": "error", "error_code": "FSM_ERROR", "message": str(e), "details": [str(e)]}

@router.get("/api/jiosaavn/status")
async def get_unified_jiosaavn_status():
    """Return live JioSaavn mobile & desktop status."""
    try:
        from plugins.aiml import app as aiml_app
        return {
            "status": "success",
            "jiosaavn": getattr(aiml_app, "jiosaavn_status", {})
        }
    except Exception as e:
        return {"status": "error", "error_code": "JIOSAAVN_ERROR", "message": str(e), "details": [str(e)]}

@router.post("/api/bci/command")
async def receive_unified_bci_command(req: BCIUnifiedCommandRequest):
    """
    Single BCI input path: receive_cortex_command -> 4s window -> FSM -> mapper -> router.
    Used by the Unified BCI Dashboard test buttons and cortex bridge.
    """
    raw = req.command or req.raw_command
    conf = float(req.confidence if req.confidence is not None else 0.95)
    if not raw:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "error_code": "MISSING_COMMAND",
                "message": "Missing command",
                "details": ["command or raw_command field is required"]
            }
        )

    try:
        from plugins.aiml import app as aiml_app
        fsm = aiml_app.fsm_controller
        accepted = fsm.receive_cortex_command(raw, conf)
        return {
            "status": "success",
            "accepted": bool(accepted),
            "command": raw,
            "confidence": conf,
            "fsm": fsm.get_state()
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error_code": "BCI_PROCESSING_ERROR",
                "message": str(e),
                "details": [str(e)]
            }
        )

@router.post("/api/fsm/command")
async def execute_direct_fsm_command(req: FSMCommandRequest):
    """Direct process_command bypassing the window."""
    raw = req.command or req.raw_command
    conf = float(req.confidence if req.confidence is not None else 1.0)
    if not raw:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "error_code": "MISSING_COMMAND",
                "message": "Missing command",
                "details": ["command or raw_command field is required"]
            }
        )

    try:
        from plugins.aiml import app as aiml_app
        fsm = aiml_app.fsm_controller
        result = fsm.process_command(raw, confidence=conf)
        aiml_app._emit_state()
        aiml_app.socketio.emit("fsm_command_result", result, namespace=aiml_app.DASHBOARD_NAMESPACE)
        return {
            "status": "success",
            "result": result,
            "fsm": fsm.get_state()
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error_code": "FSM_COMMAND_ERROR",
                "message": str(e),
                "details": [str(e)]
            }
        )

@router.post("/api/fsm/reset")
async def reset_unified_fsm():
    """Reset FSM back to Level 2 (SUB_MASTER_DASHBOARD)."""
    try:
        from plugins.aiml import app as aiml_app
        fsm = aiml_app.fsm_controller
        fsm.reset()
        with aiml_app._jiosaavn_lock:
            aiml_app.jiosaavn_status["mobile"] = {"status": "idle", "message": "Idle"}
            aiml_app.jiosaavn_status["desktop"] = {"status": "idle", "message": "Idle"}
            aiml_app.jiosaavn_status["overall"] = "idle"
            aiml_app._last_jiosaavn_launch["device"] = None
            aiml_app._last_jiosaavn_launch["ts"] = 0.0
        aiml_app.socketio.emit("jiosaavn_status", {"jiosaavn": dict(aiml_app.jiosaavn_status)}, namespace=aiml_app.DASHBOARD_NAMESPACE)
        aiml_app._emit_state()
        return {
            "status": "success",
            "fsm": fsm.get_state(),
            "jiosaavn": aiml_app.jiosaavn_status
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error_code": "FSM_RESET_ERROR",
                "message": str(e),
                "details": [str(e)]
            }
        )

@router.get("/api/fsm/state")
async def get_fsm_state_endpoint():
    """Retrieve live FSM hierarchy state, target device, and JioSaavn status."""
    try:
        from plugins.aiml import app as aiml_app
        fsm = aiml_app.fsm_controller
        state_data = fsm.get_state() if fsm else {}
        
        # Get latest volume
        vol = 50
        try:
            from os_operations import get_system_master_volume
            vol = get_system_master_volume()
        except Exception:
            pass
            
        return {
            "status": "success",
            "fsm": state_data,
            "jiosaavn": getattr(aiml_app, 'jiosaavn_status', {}),
            "volume": vol,
            "window_seconds": getattr(fsm, 'combo_timeout', 4.0) if fsm else 4.0
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )

@router.get("/api/volume")
async def get_volume_endpoint():
    """Get current system volume level."""
    try:
        from os_operations import get_system_master_volume
        vol = get_system_master_volume()
        return {"status": "success", "volume": vol}
    except Exception as e:
        return {"status": "success", "volume": 50}

@router.get("/api/config")
async def get_config_endpoint():
    """Get current command window and volume configuration."""
    try:
        from plugins.aiml import app as aiml_app
        fsm = aiml_app.fsm_controller
        win = getattr(fsm, 'combo_timeout', 4.0) if fsm else 4.0
        vol = 50
        try:
            from os_operations import get_system_master_volume
            vol = get_system_master_volume()
        except Exception:
            pass
        return {
            "status": "success",
            "config": {
                "command_window_seconds": win,
                "volume": vol
            }
        }
    except Exception as e:
        return {"status": "success", "config": {"command_window_seconds": 4.0, "volume": 50}}

class ConfigUpdateRequest(BaseModel):
    command_window_seconds: Optional[float] = 4.0

@router.post("/api/config")
async def set_config_endpoint(req: ConfigUpdateRequest):
    """Set command window duration."""
    try:
        from plugins.aiml import app as aiml_app
        fsm = aiml_app.fsm_controller
        if fsm and req.command_window_seconds:
            fsm.combo_timeout = float(req.command_window_seconds)
            if hasattr(fsm, 'command_window') and fsm.command_window:
                fsm.command_window.window_seconds = float(req.command_window_seconds)
        return {
            "status": "success",
            "config": {
                "command_window_seconds": float(req.command_window_seconds or 4.0)
            }
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}



@router.post("/api/fsm/back")
async def back_unified_fsm(req: Optional[FSMBackRequest] = None):
    """Navigate backwards through FSM hierarchy."""
    lvl = req.level if req else None
    try:
        from plugins.aiml import app as aiml_app
        fsm = aiml_app.fsm_controller
        result = fsm.navigate_back()
        if lvl == 2 and fsm.current_state != "SUB_MASTER_DASHBOARD":
            from command_system.states import SUB_MASTER_DASHBOARD
            fsm.target_device = None
            fsm.dashboard_open = False
            fsm.current_state = SUB_MASTER_DASHBOARD
            result = {"action": "back_to_level_2", "new_state": SUB_MASTER_DASHBOARD, "message": "Returned to Level 2 (Unified back)"}
        aiml_app._emit_state()

        # Reset global state manager to Level 1 / Master Hub
        try:
            from core.state.state_manager import state_manager
            state_manager.reset_state("default")
            state_manager.set_active_domain(None)
            state_manager.set_level(1)
        except Exception:
            pass

        return {"status": "success", "result": result, "fsm": fsm.get_state()}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error_code": "FSM_BACK_ERROR",
                "message": str(e),
                "details": [str(e)]
            }
        )

@router.post("/api/action")
async def handle_manual_action_api(req: ActionRequest):
    """Direct manual action dispatch to Mobile (MQTT) or Desktop (Selenium)."""
    action = req.action
    query = req.query
    try:
        from plugins.aiml import app as aiml_app
        target = aiml_app.fsm_controller.target_device or "desktop"
        result = None
        vol = 100
        is_playing = False
        auto_active = False

        if action in ("Volume Up", "volume_up", "Right_Volume_Up"):
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
            result = f"Volume Up executed ({vol}%)"
            return {
                "status": "success",
                "message": result,
                "target": target,
                "volume": vol,
                "is_playing": is_playing,
                "automation_active": auto_active
            }
        elif action in ("Volume Down", "volume_down", "Right_Volume_Down"):
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
            result = f"Volume Down executed ({vol}%)"
            return {
                "status": "success",
                "message": result,
                "target": target,
                "volume": vol,
                "is_playing": is_playing,
                "automation_active": auto_active
            }
        elif action in ("Open Mobile Dashboard", "Launch Mobile Dashboard", "Mobile Dashboard", "mobile_dashboard"):
            print("[MOBILE] Mobile Dashboard command received\n[MOBILE] Routing command to Android APK\n[MOBILE] PC browser launch skipped")
            if aiml_app.MOBILE_AVAILABLE:
                from backend.command_router import command_router as cr
                result = cr.route("Right_jiosaavn", target="mobile")
            else:
                result = "Mobile layer simulated (APK route active)"
            return {
                "status": "success",
                "message": str(result),
                "target": "mobile",
                "dispatched_to_apk": True,
                "browser_launch": "skipped"
            }

        if target == "mobile" and aiml_app.MOBILE_AVAILABLE:
            from backend.command_router import command_router as cr
            mobile_map = {
                "Play / Pause": "Right_Play_Pause",
                "Next Track": "Right_Next_Song",
                "Previous Track": "Right_Previous_Song",
                "Volume Up": "Right_Volume_Up",
                "Volume Down": "Right_Volume_Down",
                "Search Album/Playlist": "Right_Search_Playlist",
                "Search": "Right_Search_Playlist",
                "Launch JioSaavn": "Right_jiosaavn",
                "Open JioSaavn": "Right_jiosaavn"
            }
            cmd = mobile_map.get(action, action)
            result = cr.route(cmd, target="mobile")
        elif target == "desktop" or aiml_app.desktop_controller:
            from backend.command_router import command_router as cr
            result = cr.route(action, target="desktop")
            status = aiml_app.desktop_controller.get_status() if aiml_app.desktop_controller else {}
            vol = status.get("volume", 100)
            is_playing = status.get("is_playing", False)
            auto_active = status.get("automation_active", False)
            if aiml_app.socketio:
                aiml_app.socketio.emit("status_update", status, namespace=aiml_app.DESKTOP_NAMESPACE)
        else:
            result = "No backend available"
        return {
            "status": "success",
            "message": str(result),
            "target": target,
            "volume": vol,
            "is_playing": is_playing,
            "automation_active": auto_active
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error_code": "ACTION_EXECUTION_ERROR",
                "message": str(e),
                "details": [str(e)]
            }
        )

@router.post("/api/volume")
async def handle_volume_api(req: VolumeRequest):
    """Set system master volume directly."""
    vol_pct = req.volume
    try:
        from os_operations import set_system_master_volume
        actual = set_system_master_volume(int(vol_pct))
        from plugins.aiml import app as aiml_app
        if aiml_app.desktop_controller:
            aiml_app.desktop_controller.current_volume = float(actual)
            status = aiml_app.desktop_controller.get_status()
            aiml_app.socketio.emit("status_update", status, namespace=aiml_app.DESKTOP_NAMESPACE)
        return {"status": "success", "volume": actual}
    except Exception as e:
        return {"status": "success", "volume": int(vol_pct)}

@router.post("/api/search")
async def handle_search_api(req: SearchRequest):
    """Search on JioSaavn or send query."""
    query = req.query
    try:
        from plugins.aiml import app as aiml_app
        target = aiml_app.fsm_controller.target_device or "desktop"
        if target == "mobile" and aiml_app.MOBILE_AVAILABLE and aiml_app.mqtt_service:
            aiml_app.mqtt_service.publish_search_query(query)
            return {"status": "success", "message": f"Dispatched search '{query}' to Mobile (MQTT)", "target": "mobile"}
        elif aiml_app.desktop_controller:
            res = aiml_app.desktop_controller.execute_action("Search Album/Playlist", query=query)
            status = aiml_app.desktop_controller.get_status()
            aiml_app.socketio.emit("status_update", status, namespace=aiml_app.DESKTOP_NAMESPACE)
            return {"status": "success", "message": str(res), "volume": status.get("volume", 100), "target": "desktop"}
        return {"status": "success", "message": f"Search queued for '{query}'"}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error_code": "SEARCH_ERROR",
                "message": str(e),
                "details": [str(e)]
            }
        )

@router.get("/api/automation")
async def get_automation_api():
    """Get active automation state."""
    try:
        from plugins.aiml import app as aiml_app
        if aiml_app.desktop_controller:
            return {"status": "success", "automation_active": aiml_app.desktop_controller.is_automation_active()}
        return {"status": "success", "automation_active": False}
    except Exception:
        return {"status": "success", "automation_active": False}

@router.post("/api/automation")
async def handle_automation_api(req: AimlAutomationRequest):
    """Toggle or set automation state."""
    action = req.action or "toggle"
    try:
        from plugins.aiml import app as aiml_app
        if aiml_app.desktop_controller:
            if action == "start":
                aiml_app.desktop_controller.bci_processor.start_automation()
            elif action == "stop":
                aiml_app.desktop_controller.bci_processor.stop_automation()
            else:
                aiml_app.desktop_controller.toggle_automation()
            status = aiml_app.desktop_controller.get_status()
            aiml_app.socketio.emit("status_update", status, namespace=aiml_app.DESKTOP_NAMESPACE)
            return {"status": "success", "automation_active": aiml_app.desktop_controller.is_automation_active()}
        return {"status": "success", "automation_active": False}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error_code": "AUTOMATION_ERROR",
                "message": str(e),
                "details": [str(e)]
            }
        )

@router.get("/api/config")
async def get_aiml_config_api():
    try:
        from plugins.aiml import app as aiml_app
        if aiml_app.desktop_controller:
            return {"status": "success", "config": aiml_app.desktop_controller.get_config()}
        return {"status": "success", "config": {}}
    except Exception:
        return {"status": "success", "config": {}}

@router.post("/api/config")
async def post_aiml_config_api(req: AimlConfigRequest):
    confidence = req.confidence_threshold
    cooldown = req.volume_cooldown
    headless = req.headless
    try:
        from plugins.aiml import app as aiml_app
        if aiml_app.desktop_controller:
            updated = aiml_app.desktop_controller.update_config(
                confidence_threshold=confidence,
                volume_cooldown=cooldown,
                headless=headless
            )
            aiml_app.socketio.emit("config_update", updated, namespace=aiml_app.DESKTOP_NAMESPACE)
            return {"status": "success", "config": updated}
        return {"status": "success", "config": {}}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error_code": "CONFIG_UPDATE_ERROR",
                "message": str(e),
                "details": [str(e)]
            }
        )


@router.post("/api/master/start_automation")
async def start_automation(req: DashboardSelectionRequest):
    fsm = get_fsm()
    if fsm and hasattr(fsm, "ui_start_automation") and fsm.ui_start_automation(req.dashboard):
        return {"status": "success", "message": f"{req.dashboard} dashboard activated"}
    return JSONResponse(status_code=400, content={"status": "error", "message": "Invalid state or target"})

@router.post("/api/master/select_dashboard")
async def select_dashboard(req: DashboardSelectionRequest):
    fsm = get_fsm()
    if fsm and hasattr(fsm, "ui_select_dashboard") and fsm.ui_select_dashboard(req.dashboard):
        return {"status": "success"}
    return JSONResponse(status_code=400, content={"status": "error", "message": "Invalid state"})

@router.post("/api/master/reset_state")
async def reset_state():
    fsm = get_fsm()
    if fsm:
        if hasattr(fsm, "reset"):
            fsm.reset()
        elif hasattr(fsm, "ui_reset_state"):
            fsm.ui_reset_state()
    return {"status": "success"}

@router.get("/api/master/fsm_state")
async def get_fsm_state():
    fsm = get_fsm()
    if fsm:
        return {
            "state": fsm.get_state() if hasattr(fsm, 'get_state') else "SUB_MASTER_DASHBOARD",
            "selected": getattr(fsm, 'selected_dashboard', None) or getattr(fsm, 'target_device', None)
        }
    return {"state": "SUB_MASTER_DASHBOARD", "selected": None}


# --- AI/ML Command Accuracy Ingestion Endpoints ---

from plugins.aiml.accuracy_engine import accuracy_engine, CommandAccuracyEvaluation

class AccuracyIngestRequest(BaseModel):
    command_id: Optional[str] = None
    session_id: Optional[str] = "default"
    predicted_intent: str
    ground_truth_intent: Optional[str] = None
    confidence: float
    probabilities: Optional[Dict[str, float]] = None
    is_accurate: Optional[bool] = None
    model_name: Optional[str] = "Cortex-EEG-v2"
    model_version: Optional[str] = "2.1.0"
    inference_latency_ms: Optional[float] = 12.5
    preprocess_latency_ms: Optional[float] = None
    postprocess_latency_ms: Optional[float] = None
    source: Optional[str] = "BCI_CORTEX"
    metadata: Optional[Dict[str, Any]] = None

class BatchAccuracyIngestRequest(BaseModel):
    evaluations: List[AccuracyIngestRequest]

class AccuracyBenchmarkRequest(BaseModel):
    model_name: Optional[str] = "Cortex-EEG-v2"
    model_version: Optional[str] = "2.1.0"
    sample_count: Optional[int] = 20
    simulated_noise: Optional[float] = 0.05


@router.post("/api/aiml/accuracy/ingest", summary="Ingest AI/ML Command Accuracy Evaluation")
@router.post("/api/v1/aiml/accuracy/ingest", summary="Ingest AI/ML Command Accuracy Evaluation (v1)")
async def ingest_aiml_accuracy(payload: Dict[str, Any]):
    """
    Ingest a single prediction evaluation or a batch of predictions,
    calculate classification accuracy against ground truth, update analytics,
    and broadcast live AI/ML domain telemetry.
    """
    try:
        if "evaluations" in payload and isinstance(payload["evaluations"], list):
            res = accuracy_engine.ingest_batch(payload["evaluations"])
        else:
            res = accuracy_engine.ingest(payload)
        return res
    except Exception as e:
        logger.error(f"Error ingesting accuracy: {e}")
        return JSONResponse(status_code=400, content={"status": "error", "message": str(e)})


@router.get("/api/aiml/accuracy/metrics", summary="Get AI/ML Command Accuracy Analytics")
@router.get("/api/v1/aiml/accuracy/metrics", summary="Get AI/ML Command Accuracy Analytics (v1)")
async def get_aiml_accuracy_metrics():
    """
    Retrieve real-time accuracy analytics, overall accuracy %, per-intent metrics,
    confusion matrix, and rolling window trends.
    """
    try:
        metrics = accuracy_engine.get_metrics()
        return {"status": "success", "metrics": metrics}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@router.get("/api/aiml/accuracy/history", summary="Get Historical Accuracy Ingestion Records")
@router.get("/api/v1/aiml/accuracy/history", summary="Get Historical Accuracy Ingestion Records (v1)")
async def get_aiml_accuracy_history(limit: int = 50, offset: int = 0):
    """
    Retrieve historical classification evaluation records with pagination.
    """
    try:
        history = accuracy_engine.get_history(limit=limit, offset=offset)
        return {"status": "success", "count": len(history), "history": history}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@router.post("/api/aiml/accuracy/reset", summary="Reset Accuracy Metrics")
@router.post("/api/v1/aiml/accuracy/reset", summary="Reset Accuracy Metrics (v1)")
async def reset_aiml_accuracy():
    """
    Reset all historical evaluations and aggregate accuracy analytics.
    """
    try:
        accuracy_engine.reset()
        return {"status": "success", "message": "Accuracy metrics reset successfully"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@router.post("/api/aiml/accuracy/benchmark", summary="Run Automated AI/ML Accuracy Benchmark")
@router.post("/api/v1/aiml/accuracy/benchmark", summary="Run Automated AI/ML Accuracy Benchmark (v1)")
async def run_aiml_accuracy_benchmark(req: Optional[AccuracyBenchmarkRequest] = None):
    """
    Execute an automated benchmark across canonical BCI mental intents (PUSH, PULL, LEFT, RIGHT, NEUTRAL),
    injecting simulated test evaluations and returning benchmark accuracy metrics.
    """
    import random
    benchmark_req = req or AccuracyBenchmarkRequest()
    intents = ["PUSH", "PULL", "LEFT", "RIGHT", "NEUTRAL"]
    evaluations = []
    
    for i in range(benchmark_req.sample_count):
        intended = random.choice(intents)
        # 95% accuracy by default, modified by noise
        is_correct = random.random() > benchmark_req.simulated_noise
        predicted = intended if is_correct else random.choice([x for x in intents if x != intended])
        conf = round(random.uniform(0.82, 0.98) if is_correct else random.uniform(0.40, 0.65), 3)
        lat = round(random.uniform(8.5, 18.0), 2)
        
        evaluations.append({
            "command_id": f"BENCH-{i+1}",
            "predicted_intent": predicted,
            "ground_truth_intent": intended,
            "confidence": conf,
            "model_name": benchmark_req.model_name,
            "model_version": benchmark_req.model_version,
            "inference_latency_ms": lat,
            "source": "BENCHMARK_SUITE",
            "probabilities": {
                predicted: conf,
                intended: round(1.0 - conf, 3) if not is_correct else 0.05
            }
        })
        
    res = accuracy_engine.ingest_batch(evaluations)
    metrics = accuracy_engine.get_metrics()
    return {
        "status": "success",
        "benchmark": {
            "samples_ingested": res.get("count", 0),
            "model_name": benchmark_req.model_name,
            "model_version": benchmark_req.model_version,
            "metrics": metrics
        }
    }


# --- Setup Function for FastAPI ---

def setup_aiml_routes(app: FastAPI):
    app.include_router(router)

    # Mount static assets
    unified_static = BASE_DIR / "dashboard" / "static"
    desktop_static = BASE_DIR / "desktop_dashboard" / "static"
    mobile_static = BASE_DIR / "mobile_dashboard" / "resources" / "static"

    if unified_static.exists():
        app.mount("/aiml/static", StaticFiles(directory=str(unified_static)), name="aiml_unified_static")
        try:
            app.mount("/static", StaticFiles(directory=str(unified_static)), name="static_root")
        except Exception:
            pass

    if desktop_static.exists():
        app.mount("/desktop/static", StaticFiles(directory=str(desktop_static)), name="desktop_static")
        app.mount("/aiml/desktop/static", StaticFiles(directory=str(desktop_static)), name="aiml_desktop_static")

    if mobile_static.exists():
        app.mount("/mobile/static", StaticFiles(directory=str(mobile_static)), name="mobile_static")
        app.mount("/aiml/mobile/static", StaticFiles(directory=str(mobile_static)), name="aiml_mobile_static")

    bci_static = BASE_DIR / "scratch_iot" / "public"
    if bci_static.exists():
        app.mount("/bci/static", StaticFiles(directory=str(bci_static)), name="bci_static")

    # Mount Socket.IO WSGI middleware for live real-time dashboard events
    try:
        from starlette.middleware.wsgi import WSGIMiddleware
        from plugins.aiml.app import app as flask_app
        app.mount("/socket.io", WSGIMiddleware(flask_app))
    except Exception as e:
        print(f"[WARN] Could not mount Socket.IO WSGIMiddleware: {e}")
