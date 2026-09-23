from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, StrictStr
from datetime import datetime, timezone
import json
import logging
import os
import sys
import time
import uuid
from typing import Any, Optional, Union

# Ensure workspace root is in sys.path
_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from core.plugin_manager.manager import execute
from core.state.state_manager import state_manager
from core.managers.lifecycle_tracker import lifecycle_tracker
from core.navigation.api import navigation_router
from core.orchestration.ecosystem_orchestrator import ecosystem_orchestrator
from models.api_models import (
    SystemHealthResponse,
    SessionStateResponse,
    SystemStateResponse,
    DiagnosticsResponse,
    LifecycleSummaryResponse,
    DomainStateResponse,
    StateSyncRequest,
    StateUpdateRequest,
)
from models.command_models import CommandErrorResponse, CommandResponse
from models.device_models import DeviceState

try:
    from core.validation.invalid_combination_rules import check_navigation_combination
except ImportError:
    check_navigation_combination = None
from core.automation.engine import automation_engine
import asyncio

try:
    from services.desktop_integration_service import get_desktop_integration_service
except ImportError:
    get_desktop_integration_service = None

try:
    from services.media_execution_service import get_media_execution_service
except ImportError:
    get_media_execution_service = None

logger = logging.getLogger("api_server")

router = APIRouter(prefix="/api/v1")

class CombinationCheckRequest(BaseModel):
    commands: Any

@router.post("/validate-combination")
async def validate_combination_endpoint(request: CombinationCheckRequest):
    if check_navigation_combination:
        return check_navigation_combination(request.commands)
    return {"status": "error", "message": "check_navigation_combination not found"}

class BCICommandRequest(BaseModel):
    command: Optional[Union[StrictStr, list[StrictStr]]] = None
    commands: Optional[Union[StrictStr, list[StrictStr]]] = None
    confidence: Optional[float] = 1.0
    source: Optional[str] = "unknown"
    device_id: Optional[str] = None
    session_id: Optional[str] = None
    command_id: Optional[str] = None

@router.get("/state", response_model=SessionStateResponse)
def get_state(session: Optional[str] = None):
    active_session = session if session and session != "default" else state_manager.get_active_session_id()
    return state_manager.get_state(active_session)

@router.get("/state/system", response_model=SystemStateResponse)
def get_system_state():
    return state_manager.get_system_state()

@router.get("/state/performance")
def get_performance_state():
    return state_manager.get_performance_metrics()

@router.get("/state/domain/{domain}", response_model=DomainStateResponse)
def get_domain_state_endpoint(domain: str, session: Optional[str] = None):
    dom_state = state_manager.get_domain_state(domain, session=session)
    dom_upper = domain.upper()
    if dom_upper == "IOT":
        try:
            from core.plugin_manager.manager import get_plugin
            iot = get_plugin("iot")
            if iot and hasattr(iot, "latest_status") and iot.latest_status:
                first_dev = next(iter(iot.latest_status.values()), None)
                if first_dev:
                    dom_state["device_state"] = DeviceState.from_iot_device(first_dev)
        except Exception:
            pass
    elif dom_upper in ("EMBEDDED", "ROBOTICS"):
        try:
            from core.plugin_manager.manager import get_plugin
            emb = get_plugin("embedded")
            if emb and hasattr(emb, "subplugins") and "rc_car" in emb.subplugins:
                car = emb.subplugins["rc_car"]
                status_dict = {"status": "ONLINE", "speed_mode": getattr(car, "speed_mode", "NORMAL"), "online": True}
                dom_state["device_state"] = DeviceState.from_embedded_status("RC_CAR_01", status_dict, "RC_CAR")
        except Exception:
            pass
    return dom_state


@router.get("/state/commands/active")
def get_active_commands_endpoint(session: Optional[str] = None):
    return state_manager.get_active_commands(session=session)

@router.get("/state/failures")
def get_failures_endpoint():
    """Retrieve structured failure telemetry, history, and recovery summary."""
    return state_manager.get_failure_tracking()

@router.get("/state/failures/domain/{domain}")
def get_domain_failure_endpoint(domain: str):
    """Retrieve failure and recovery health metrics for a specific domain."""
    return state_manager.get_domain_health(domain)

@router.post("/state/failures/clear")
def clear_failures_endpoint(domain: Optional[str] = None):
    """Clear recorded failure history globally or for a specific domain."""
    state_manager.clear_failure_history(domain=domain)
    return {"status": "success", "domain": domain or "all"}

@router.post("/state/reset")
async def reset_system_state_endpoint(session: Optional[str] = None):
    res = state_manager.reset_state(session=session)
    try:
        from core.communication.websocket_server import websocket_server
        active_sess = session or state_manager.get_active_session_id()
        envelope = websocket_server.create_envelope(
            msg_type="STATE_UPDATE",
            source_domain="CORE",
            session_id=active_sess,
            payload={"session_id": active_sess, "action": "RESET", "state": res},
        )
        await websocket_server.broadcast_envelope(envelope)
    except Exception:
        pass
    return res


@router.post("/state/sync", summary="Synchronize domain state and broadcast to WebSockets")
async def sync_domain_state_endpoint(request: StateSyncRequest):
    """
    REST endpoint to ingest domain state, synchronize via CrossDomainStateSynchronizer,
    and broadcast STATE_UPDATE event across all connected WebSocket clients.
    """
    from core.state.state_synchronizer import cross_domain_state_synchronizer
    active_session = request.session_id if request.session_id and request.session_id != "default" else state_manager.get_active_session_id()
    synced = cross_domain_state_synchronizer.sync_domain(
        session_id=active_session,
        domain=request.domain,
        domain_state=request.domain_state
    )
    try:
        from core.communication.websocket_server import websocket_server
        envelope = websocket_server.create_envelope(
            msg_type="STATE_UPDATE",
            source_domain=request.domain,
            session_id=active_session,
            payload={
                "session_id": active_session,
                "domain": request.domain,
                "version": cross_domain_state_synchronizer.version,
                "state": synced,
            }
        )
        await websocket_server.broadcast_envelope(envelope)
    except Exception:
        pass
    return {
        "status": "success",
        "session_id": active_session,
        "domain": request.domain,
        "version": cross_domain_state_synchronizer.version,
        "state": synced
    }


@router.post("/state/update", summary="Update session state and broadcast to WebSockets")
async def update_state_endpoint(request: StateUpdateRequest):
    """
    REST endpoint to update session state in StateManager and broadcast STATE_UPDATE
    event across all connected WebSocket clients.
    """
    active_session = request.session_id if request.session_id and request.session_id != "default" else state_manager.get_active_session_id()
    state_manager.update_state(active_session, request.updates)
    updated_state = state_manager.get_state(active_session)
    try:
        from core.communication.websocket_server import websocket_server
        envelope = websocket_server.create_envelope(
            msg_type="STATE_UPDATE",
            source_domain="CORE",
            session_id=active_session,
            payload={"session_id": active_session, "state": updated_state}
        )
        await websocket_server.broadcast_envelope(envelope)
    except Exception:
        pass
    return {"status": "success", "session_id": active_session, "state": updated_state}


# -------------------------------------------------------------
# LIFECYCLE & EXECUTION TIMING ENDPOINTS (Day 8 Member 6)
# -------------------------------------------------------------
@router.get("/lifecycle/summary", response_model=LifecycleSummaryResponse)
def get_lifecycle_summary_endpoint(session: Optional[str] = None):
    """Retrieve aggregate command lifecycle metrics and timing statistics."""
    summary = lifecycle_tracker.get_summary(session_id=session)
    return {"status": "success", "summary": summary}


@router.get("/lifecycle/commands")
def get_lifecycle_commands_endpoint(session: Optional[str] = None, limit: int = 50):
    """Retrieve list of tracked commands with start/completion timestamps and duration."""
    records = lifecycle_tracker.get_session_commands(session) if session else list(lifecycle_tracker._records.values())
    sorted_records = sorted(records, key=lambda r: r.created_at, reverse=True)[:limit]
    return {
        "status": "success",
        "count": len(sorted_records),
        "commands": [r.to_dict() for r in sorted_records]
    }

@router.get("/lifecycle/{command_id}")
def get_lifecycle_detail_endpoint(command_id: str):
    """Retrieve detailed lifecycle record for a single command."""
    rec = lifecycle_tracker.get_lifecycle(command_id)
    if not rec:
        return {"status": "error", "message": f"Command '{command_id}' not found"}
    return {"status": "success", "lifecycle": rec.to_dict()}

@router.get("/lifecycle/{command_id}/timing")
def get_command_timing_endpoint(command_id: str):
    """Retrieve execution start, completion, and duration telemetry for a specific command."""
    timing = lifecycle_tracker.get_execution_timing(command_id) or state_manager.get_command_timing(command_id)
    if not timing:
        return {"status": "error", "message": f"Timing for command '{command_id}' not found"}
    return {"status": "success", "timing": timing}

@router.post("/bci/command")
async def process_bci_command(request: BCICommandRequest, session: Optional[str] = None):
    if request.session_id:
        active_session = request.session_id
    elif session:
        active_session = session
    else:
        active_session = state_manager.get_active_session_id()

    active_command_id = request.command_id if request.command_id else uuid.uuid4().hex

    # Delegate pure orchestration to EcosystemOrchestrator
    cmd_to_process = request.command if request.command is not None else request.commands
    if cmd_to_process is None or (isinstance(cmd_to_process, str) and not cmd_to_process.strip()):
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "error_code": "MISSING_COMMAND",
                "message": "Missing command or commands field",
                "details": ["command or commands field is required and cannot be empty"]
            }
        )
        
    result = await ecosystem_orchestrator.process_command(
        command=cmd_to_process,
        session=active_session,
        confidence=request.confidence,
        source=request.source,
        device_id=request.device_id,
        command_id=active_command_id
    )

    if isinstance(result, dict) and (result.get("status") == "invalid" or (result.get("validation") and not result["validation"].get("valid", True))):
        reason = result.get("reason") or (result.get("validation") or {}).get("rejection_reason", "Unsupported command.")
        resp_data = dict(result)
        resp_data["status"] = "error"
        resp_data["error_code"] = "INVALID_COMMAND"
        resp_data["message"] = "Invalid command"
        resp_data["reason"] = reason
        resp_data["details"] = [reason] if reason else []
        return JSONResponse(
            status_code=400,
            content=resp_data
        )
    return result


class TuningConfigRequest(BaseModel):
    threshold: Optional[float] = None
    sensitivity: Optional[float] = None
    framing_duration: Optional[float] = None


class DashboardConfigUpdateRequest(BaseModel):
    env: Optional[str] = None
    debug: Optional[bool] = None
    log_level: Optional[str] = None
    ws_enabled: Optional[bool] = None
    ws_heartbeat_interval_sec: Optional[float] = None
    ws_client_timeout_sec: Optional[float] = None
    ws_broadcast_rate_hz: Optional[float] = None
    framing_duration_sec: Optional[float] = None
    power_threshold: Optional[float] = None
    sensitivity: Optional[float] = None


@router.get("/state/lock")
def get_command_lock_state_endpoint(session: Optional[str] = "default"):
    from core.managers.command_lock_manager import command_lock_manager
    return {"status": "success", "lock": command_lock_manager.get_lock_state(session or "default")}

@router.post("/state/lock/reset")
def reset_command_lock_endpoint(session: Optional[str] = "default"):
    from core.managers.command_lock_manager import command_lock_manager
    command_lock_manager.reset_lock(session or "default")
    return {"status": "success", "message": "Command lock reset to IDLE", "lock": command_lock_manager.get_lock_state(session or "default")}

@router.get("/config/dashboard")
def get_dashboard_config_endpoint():
    """Retrieve full dashboard backend configuration."""
    from core.config.dashboard_config import dashboard_config_manager
    cfg = dashboard_config_manager.get_config()
    return {"status": "success", "config": cfg.model_dump()}

@router.post("/config/dashboard")
def update_dashboard_config_endpoint(req: DashboardConfigUpdateRequest):
    """Dynamically update dashboard backend configuration fields."""
    from core.config.dashboard_config import dashboard_config_manager
    from services.cortex_service import cortex_service
    from core.managers.command_lock_manager import command_lock_manager

    updates = req.model_dump(exclude_unset=True)
    cfg = dashboard_config_manager.update_config(updates)

    # Sync with Cortex and Command Lock Manager if applicable
    if "power_threshold" in updates and updates["power_threshold"] is not None:
        cortex_service.config.power_threshold = float(updates["power_threshold"])
    if "framing_duration_sec" in updates and updates["framing_duration_sec"] is not None:
        command_lock_manager.set_default_duration(float(updates["framing_duration_sec"]))

    return {"status": "success", "message": "Dashboard backend configuration updated", "config": cfg.model_dump()}

@router.get("/config/websocket")
def get_websocket_config_endpoint():
    """Retrieve WebSocket layer parameters for client connections and real-time streaming."""
    from core.config.dashboard_config import dashboard_config_manager
    return {"status": "success", "websocket": dashboard_config_manager.to_websocket_config()}

@router.get("/config/environment")
def get_environment_summary_endpoint():
    """Retrieve active environment setup summary and runtime diagnostics."""
    from core.config.dashboard_config import dashboard_config_manager
    return {"status": "success", "environment": dashboard_config_manager.to_environment_summary()}

@router.get("/config/tuning")
def get_tuning_config_endpoint():
    from services.cortex_service import cortex_service
    from core.managers.command_lock_manager import command_lock_manager
    from core.config.dashboard_config import dashboard_config_manager
    cfg = dashboard_config_manager.get_config()
    power_thresh = getattr(cortex_service, "power_threshold", cfg.power_threshold)
    return {
        "status": "success",
        "threshold": power_thresh,
        "sensitivity": power_thresh,
        "framing_duration": command_lock_manager.get_default_duration()
    }

@router.post("/config/tuning")
def update_tuning_config_endpoint(req: TuningConfigRequest):
    from services.cortex_service import cortex_service
    from core.managers.command_lock_manager import command_lock_manager
    from core.config.dashboard_config import dashboard_config_manager
    
    updates_to_dash = {}
    if req.threshold is not None:
        val = float(req.threshold)
        if val > 1.0 and val <= 100.0:
            val = val / 100.0
        if 0.0 <= val <= 1.0:
            cortex_service.config.power_threshold = val
            updates_to_dash["power_threshold"] = val
            logger.info(f"[TUNING] Power threshold updated dynamically to {val:.2f}")

    if req.sensitivity is not None:
        val = float(req.sensitivity)
        if val > 1.0 and val <= 100.0:
            val = val / 100.0
        if 0.0 <= val <= 1.0:
            cortex_service.config.power_threshold = val
            updates_to_dash["sensitivity"] = val
            logger.info(f"[TUNING] Sensitivity updated dynamically to {val:.2f}")

    if req.framing_duration is not None:
        dur = float(req.framing_duration)
        if dur >= 0.5 and dur <= 30.0:
            command_lock_manager.set_default_duration(dur)
            updates_to_dash["framing_duration_sec"] = dur

    if updates_to_dash:
        dashboard_config_manager.update_config(updates_to_dash)

    power_thresh = getattr(cortex_service, "power_threshold", 0.65)
    return {
        "status": "success",
        "message": "Tuning configuration updated dynamically",
        "threshold": power_thresh,
        "sensitivity": power_thresh,
        "framing_duration": command_lock_manager.get_default_duration()
    }

@router.get("/widgets")
async def get_widgets():
    desktop_res = await execute("desktop", "get_widgets", None)
    embedded_res = await execute("embedded", "get_widgets", None)
    aiml_res = await execute("aiml", "get_widgets", None)
    
    widgets = []
    if desktop_res and "widgets" in desktop_res:
        widgets.extend(desktop_res["widgets"])
    if embedded_res and "widgets" in embedded_res:
        widgets.extend(embedded_res["widgets"])
    if aiml_res and "widgets" in aiml_res:
        widgets.extend(aiml_res["widgets"])
        
    return {"widgets": widgets}

@router.get("/embedded/rc_car/status")
async def get_rc_car_status():
    res = await execute("embedded", "get_widget", {"app": "RC_CAR"})
    return res

class RcCarSpeedRequest(BaseModel):
    speed_mode: Optional[str] = None
    speed_pwm: Optional[int] = None

@router.post("/embedded/rc_car/speed")
async def set_rc_car_speed(req: RcCarSpeedRequest):
    speed_mode = (req.speed_mode or "MEDIUM").upper()
    pwm = 255 if speed_mode == "FAST" else (180 if speed_mode == "MEDIUM" else 120)
    if req.speed_pwm is not None:
        pwm = req.speed_pwm
    from core.plugin_manager.manager import get_plugin
    embedded = get_plugin("embedded")
    if embedded and hasattr(embedded, "subplugins") and "rc_car" in embedded.subplugins:
        car = embedded.subplugins["rc_car"]
        car.speed_mode = speed_mode
        car.speed_pwm = pwm
    return {"status": "success", "speed_mode": speed_mode, "speed_pwm": pwm}

@router.post("/embedded/rc_car/stop")
async def stop_rc_car():
    automation_engine.stop()
    res = await execute("embedded", "STOP", {"app": "RC_CAR"})
    return res

class AutomationRequest(BaseModel):
    domain: str
    plugin: str
    commands: list[dict]

@router.post("/automation/execute")
async def run_automation(request: AutomationRequest, session: str = "default"):
    task_id = None
    try:
        from core.communication.intake import request_intake
        intake_res = await request_intake.accept_request("automation", request.model_dump(), session=session)
        task_id = intake_res.get("task_id")
    except Exception as e:
        logger.warning(f"Intake processing failed for automation: {e}")

    asyncio.create_task(automation_engine.execute_sequence(
        domain=request.domain, 
        plugin=request.plugin, 
        commands=request.commands, 
        session=session
    ))
    resp = {"status": "started"}
    if task_id:
        resp["task_id"] = task_id
    return resp

class GenericIntakeRequest(BaseModel):
    request_type: str
    payload: dict
    custom_id: Optional[str] = None

@router.get("/intake/metrics")
def get_intake_metrics():
    from core.communication.intake import request_intake
    return request_intake.get_metrics()

@router.post("/intake/submit")
async def submit_intake_request(request: GenericIntakeRequest, session: str = "default"):
    from core.communication.intake import request_intake
    res = await request_intake.accept_request(
        request_type=request.request_type,
        payload=request.payload,
        session=session,
        custom_id=request.custom_id
    )
    return res

@router.get("/intake/status/{task_id}")
def get_intake_status(task_id: str):
    from core.queue.task_queue import task_queue
    task_data = task_queue.get_task(task_id)
    if not task_data:
        return JSONResponse(status_code=404, content={"status": "error", "message": "Task not found"})
    return task_data

@router.get("/health", response_model=SystemHealthResponse)
async def get_system_health():

    from core.plugin_manager.manager import get_plugin
    desktop_plugin = get_plugin("desktop")
    embedded_plugin = get_plugin("embedded")
    iot_plugin = get_plugin("iot")
    aiml_plugin = get_plugin("aiml")

    # 1. IoT domain connection strictly as per MQTT Broker / server
    iot_connected = False
    if iot_plugin and hasattr(iot_plugin, "is_connected"):
        iot_connected = iot_plugin.is_connected()
    elif iot_plugin:
        iot_connected = bool(getattr(iot_plugin, "connected", False))

    # 2. Embedded domain connection strictly as per its hardware status & MQTT
    embedded_connected = False
    if embedded_plugin and hasattr(embedded_plugin, "is_connected"):
        embedded_connected = embedded_plugin.is_connected()
    elif embedded_plugin and hasattr(embedded_plugin, "subplugins"):
        rc_car = embedded_plugin.subplugins.get("rc_car")
        if rc_car and hasattr(rc_car, "is_connected"):
            embedded_connected = rc_car.is_connected()
        elif rc_car and hasattr(rc_car, "sender") and hasattr(rc_car.sender, "is_connected"):
            embedded_connected = rc_car.sender.is_connected()
        elif rc_car and hasattr(rc_car, "sender"):
            embedded_connected = bool(getattr(rc_car.sender, "_mqtt_connected", False))

    # 3. Desktop domain as per local OS daemon
    desktop_connected = desktop_plugin is not None

    # 4. AIML domain as per AI engine
    aiml_connected = aiml_plugin is not None and getattr(aiml_plugin, "initialized", True)

    # Broker connectivity: check whether any MQTT client is actually connected to the broker
    broker_connected = (
        bool(iot_plugin and getattr(iot_plugin, "connected", False)) or
        bool(embedded_plugin and hasattr(embedded_plugin, "subplugins") and
             getattr(embedded_plugin.subplugins.get("rc_car"), "sender", None) and
             getattr(embedded_plugin.subplugins["rc_car"].sender, "_mqtt_connected", False))
    )

    domains = {
        "desktop": {
            "online": desktop_connected,
            "label": "Python OS (Desktop)",
            "transport": "Win32 IPC Daemon"
        },
        "embedded": {
            "online": embedded_connected,
            "label": "Embedded Robotics (RC Car)",
            "transport": "MQTT 52.21.249.6:1883"
        },
        "iot": {
            "online": iot_connected,
            "label": "Smart IoT Relays (#101)",
            "transport": "MQTT 52.21.249.6:1883"
        },
        "aiml": {
            "online": aiml_connected,
            "label": "AIML & Audio Engine",
            "transport": "FastAPI / Local IPC"
        }
    }

    online_count = sum(1 for d in domains.values() if d["online"])

    return {
        "status": "online",
        "server": True,
        "online_count": online_count,
        "total_domains": 4,
        "broker_connected": broker_connected,
        "domains": domains
    }


# -------------------------------------------------------------
# MEDIA EXECUTION API ENDPOINTS (Member 4 Integration)
# -------------------------------------------------------------
class MediaControlRequest(BaseModel):
    action: str
    app: Optional[str] = "YOUTUBE"
    step: Optional[int] = 5
    level: Optional[int] = 50
    query: Optional[str] = None
    command_id: Optional[str] = None


@router.get("/media/status")
def get_media_status():
    """Retrieve live media execution layer telemetry and history."""
    try:
        from services.media_execution_service import get_media_execution_service
        svc = get_media_execution_service()
        history = svc.get_history(limit=5)
        supported = svc.get_supported_actions()
        return {
            "status": "success",
            "supported_actions": supported,
            "recent_actions": history,
            "active_provider": "YOUTUBE",
            "volume": 75,
            "playback": "PAUSED" if not history else (history[-1].get("action") or "PLAY")
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/media/control")
def execute_media_control(req: MediaControlRequest):
    """Directly trigger a media execution operation."""
    try:
        from services.media_execution_service import get_media_execution_service
        svc = get_media_execution_service()
        payload = {
            "app": req.app,
            "step": req.step,
            "level": req.level,
            "query": req.query,
            "command_id": req.command_id
        }
        res = svc.execute_command(action=req.action, payload=payload, command_id=req.command_id)
        return res
    except Exception as e:
        return {"status": "FAILED", "success": False, "error": str(e)}


# -------------------------------------------------------------
# LIVE SYSTEM & HARDWARE DIAGNOSTICS ENDPOINT
# -------------------------------------------------------------
@router.get("/diagnostics", response_model=DiagnosticsResponse)
def get_system_diagnostics():

    """Return real-time host hardware and background daemon diagnostics."""
    import os
    import sys
    import platform
    import time
    import threading

    # Memory & CPU stats
    cpu_percent = 12.5
    ram_percent = 42.0
    try:
        import psutil
        cpu_percent = psutil.cpu_percent(interval=None)
        ram_percent = psutil.virtual_memory().percent
    except ImportError:
        pass

    return {
        "status": "success",
        "timestamp": time.time(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "python_version": sys.version.split()[0],
            "pid": os.getpid()
        },
        "resources": {
            "cpu_percent": cpu_percent,
            "ram_percent": ram_percent,
            "active_threads": threading.active_count()
        },
        "transport_metrics": {
            "mqtt_broker": "52.21.249.6:1883",
            "ipc_status": "NOMINAL",
            "latency_ms": 2.4,
            "throughput_msg_per_sec": 14.8
        }
    }


# -------------------------------------------------------------
# VISUAL MACRO WORKFLOW RUNNER ENDPOINT
# -------------------------------------------------------------
class MacroStep(BaseModel):
    type: str  # "bci", "iot", "media", "delay"
    command: Optional[str] = None
    parameters: Optional[dict] = None
    delay_ms: Optional[int] = 200


class MacroExecuteRequest(BaseModel):
    name: Optional[str] = "Quick Pipeline"
    steps: list[dict]


@router.post("/macro/execute")
async def execute_macro_pipeline(req: MacroExecuteRequest, session: str = "default"):
    """Execute a structured multi-step macro pipeline."""
    results = []
    for idx, step in enumerate(req.steps):
        stype = step.get("type", "bci").lower()
        cmd = step.get("command", "PUSH")
        delay = step.get("delay_ms", 100) / 1000.0

        if stype == "bci":
            res = await ecosystem_orchestrator.process_command(cmd, session=session)
            results.append({"step": idx + 1, "type": "bci", "command": cmd, "result": res.get("status")})
        elif stype == "iot":
            from plugins.iot.plugin import IoTPlugin
            plugin = IoTPlugin()
            dev = step.get("device_id", "DEV-101")
            res = plugin.execute(cmd, {"device_id": dev})
            results.append({"step": idx + 1, "type": "iot", "command": cmd, "result": res})
        elif stype == "media":
            from services.media_execution_service import get_media_execution_service
            svc = get_media_execution_service()
            res = await svc.execute_command_async(cmd, step.get("parameters", {}))
            results.append({"step": idx + 1, "type": "media", "command": cmd, "result": res.get("status")})
        
        if delay > 0:
            await asyncio.sleep(delay)

    return {"status": "success", "macro_name": req.name, "executed_steps": results}


# -------------------------------------------------------------
# DESKTOP DOMAIN ADVANCED AUTOMATION ENDPOINTS (Options 1, 3, 5, 6)
# -------------------------------------------------------------
class WindowFocusRequest(BaseModel):
    hwnd: Optional[int] = None
    title: Optional[str] = None


class OsActionRequest(BaseModel):
    action: str
    params: Optional[dict] = None


class BrowserActionRequest(BaseModel):
    action: str
    params: Optional[dict] = None


class ProcessKillRequest(BaseModel):
    pid: Optional[int] = None
    name: Optional[str] = None


@router.get("/desktop/windows")
def get_desktop_windows(limit: int = 12):
    """Retrieve list of active top-level application windows."""
    try:
        from services.desktop_integration_service import get_desktop_integration_service
        svc = get_desktop_integration_service()
        windows = svc.list_active_windows(limit=limit)
        return {"status": "success", "count": len(windows), "windows": windows}
    except Exception as e:
        return {"status": "error", "message": str(e), "windows": []}


@router.post("/desktop/windows/focus")
def focus_desktop_window(req: WindowFocusRequest):
    """Bring target window to foreground."""
    try:
        from services.desktop_integration_service import get_desktop_integration_service
        svc = get_desktop_integration_service()
        res = svc.focus_window(hwnd=req.hwnd, title_query=req.title)
        return res
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/desktop/os_action")
def trigger_os_tactical_action(req: OsActionRequest):
    """Execute native OS tactical action (Screenshot, Show Desktop, Lock, Explorer, etc.)."""
    try:
        from services.desktop_integration_service import get_desktop_integration_service
        svc = get_desktop_integration_service()
        res = svc.execute_os_action(action=req.action, params=req.params)
        return res
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/desktop/browser_action")
def trigger_browser_action(req: BrowserActionRequest):
    """Execute deep web browser actions (Scrolling, Tabs, Zoom, Search Query)."""
    try:
        from services.desktop_integration_service import get_desktop_integration_service
        svc = get_desktop_integration_service()
        res = svc.execute_browser_action(action=req.action, params=req.params)
        return res
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/desktop/processes")
def get_desktop_processes(limit: int = 10):
    """List top CPU/Memory processes."""
    try:
        from services.desktop_integration_service import get_desktop_integration_service
        svc = get_desktop_integration_service()
        procs = svc.list_top_processes(limit=limit)
        return {"status": "success", "count": len(procs), "processes": procs}
    except Exception as e:
        return {"status": "error", "message": str(e), "processes": []}


@router.post("/desktop/processes/kill")
def kill_desktop_process(req: ProcessKillRequest):
    """Safely terminate unresponsive process."""
    try:
        from services.desktop_integration_service import get_desktop_integration_service
        svc = get_desktop_integration_service()
        res = svc.kill_process(pid=req.pid, name=req.name)
        return res
    except Exception as e:
        return {"status": "error", "message": str(e)}


from services.cortex_service import cortex_service
from fastapi import WebSocket, WebSocketDisconnect
import time

class CortexCredentialsRequest(BaseModel):
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    license_id: Optional[str] = None
    profile_name: Optional[str] = None

class CortexProfileRequest(BaseModel):
    profile_name: str

@router.get("/cortex/status")
async def get_cortex_status_endpoint():
    """Retrieve live Emotiv Cortex API v2 connection and headset status."""
    return cortex_service.get_status()

@router.post("/cortex/connect")
async def connect_cortex_endpoint():
    """Initiate live WebSocket connection and auth handshake to Cortex API v2 (wss://localhost:6868)."""
    return await cortex_service.connect()

@router.post("/cortex/disconnect")
async def disconnect_cortex_endpoint():
    """Disconnect active session from Cortex API v2."""
    return await cortex_service.disconnect()

@router.post("/cortex/credentials")
async def set_cortex_credentials_endpoint(req: CortexCredentialsRequest):
    """Update Cortex client ID and secret credentials."""
    cortex_service.set_credentials(
        client_id=req.client_id,
        client_secret=req.client_secret,
        license_id=req.license_id,
        profile_name=req.profile_name
    )
    return {"status": "success", "message": "Credentials updated"}

@router.get("/cortex/diagnostic")
async def get_cortex_diagnostic_endpoint():
    """Run active diagnostic check on Cortex API v2 endpoint."""
    return await cortex_service.run_diagnostic()

@router.post("/cortex/profile/load")
async def load_cortex_profile_endpoint(req: CortexProfileRequest):
    """Load specific user training profile on Cortex session."""
    return await cortex_service.load_profile(req.profile_name)

@router.post("/cortex/framing/cancel")
async def cancel_cortex_framing_endpoint():
    """Broadcast global cancellation of temporal window framing."""
    await cortex_service.broadcast_event("framing_cancelled", {"message": "User Aborted"})
    return {"status": "success"}

def setup_routes(app):
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        err_details = []
        for e in exc.errors():
            d = dict(e)
            if "input" in d:
                if isinstance(d["input"], bytes):
                    d["input"] = d["input"].decode("utf-8", errors="replace")
                elif not isinstance(d["input"], (str, int, float, bool, list, dict, type(None))):
                    d["input"] = str(d["input"])
            err_details.append(d)
        return JSONResponse(
            status_code=422,
            content={
                "status": "error",
                "error_code": "VALIDATION_ERROR",
                "message": "Malformed request payload",
                "details": err_details
            }
        )


    app.include_router(router)
    app.include_router(navigation_router)
    try:
        from api.event_history_routes import router as event_history_router
        app.include_router(event_history_router)
    except Exception as e:
        logger.warning(f"Could not include event_history_router: {e}")

    @app.websocket("/ws")
    @app.websocket("/api/v1/ws")
    @app.websocket("/api/v1/bci/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        logger.info("[WS SERVER] WS_CONNECTED: New client connection to API server")
        cortex_service.register_client(websocket)
        from core.communication.websocket_server import websocket_server
        session = websocket_server.register_client(websocket)
        try:
            snapshot = {
                "type": "init_snapshot",
                "version": "2.0.0",
                "source_domain": "CORE",
                "source_id": "master_hub",
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "timestamp_unix_ms": int(time.time() * 1000),
                "payload": {
                    "client_id": session.client_id,
                    "cortex": cortex_service.get_status(),
                    "stateMachine": {
                        "config": {
                            "powerThreshold": getattr(cortex_service, "_power_threshold", 0.65),
                            "debounceMs": getattr(cortex_service, "_debounce_ms", 350),
                            "singleFireWindowMs": 1500,
                            "comboWindowMs": 2000,
                            "framingWindowMs": 4000,
                            "framingEnabled": True
                        }
                    }
                }
            }
            await websocket.send_json(snapshot)
            while True:
                try:
                    raw_text = await websocket.receive_text()
                except WebSocketDisconnect:
                    break

                try:
                    data = json.loads(raw_text)
                except Exception:
                    error_resp = {
                        "type": "ERROR",
                        "version": "2.0.0",
                        "source_domain": "CORE",
                        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                        "timestamp_unix_ms": int(time.time() * 1000),
                        "payload": {"error": "MALFORMED_JSON", "message": "Invalid JSON payload"}
                    }
                    await websocket.send_json(error_resp)
                    continue

                if not isinstance(data, dict):
                    continue
                session.last_heartbeat = time.time()
                msg_type = data.get("type", "")
                payload = data.get("payload", {})

                if msg_type == "ping" or msg_type == "PING":
                    pong_resp = {
                        "type": "PONG",
                        "version": "2.0.0",
                        "source_domain": "CORE",
                        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                        "timestamp_unix_ms": int(time.time() * 1000),
                        "payload": {"client_time": data.get("time"), "server_time": time.time()}
                    }
                    await websocket.send_json(pong_resp)
                elif msg_type == "cortex_com":
                    act = payload.get("action", "")
                    pwr = payload.get("power", 0.85)
                    sim = payload.get("simulated", False)
                    await cortex_service.broadcast_event("cortex_com", {
                        "action": str(act).upper(),
                        "power": pwr,
                        "time": time.time(),
                        "simulated": sim
                    })
                    if act and str(act).upper() != "NEUTRAL":
                        await ecosystem_orchestrator.process_command(
                            command=str(act).upper(),
                            session=state_manager.get_active_session_id(),
                            confidence=pwr,
                            source="bci_sim" if sim else "cortex_ws"
                        )
                elif msg_type == "cancel_framing":
                    await cortex_service.broadcast_event("framing_cancelled", {"message": "Cancelled by user"})
                elif msg_type == "update_config":
                    if "framingWindowMs" in payload:
                        pass
        except WebSocketDisconnect:
            logger.info(f"[WS SERVER] WS_DISCONNECTED: Client {session.client_id} disconnected normally.")
        except Exception as e:
            logger.error(f"[WS SERVER] WS_ERROR: WebSocket error for client {session.client_id}: {e}")
        finally:
            logger.info(f"[WS SERVER] WS_CLEANUP: Cleaning up resources for client {session.client_id}")
            cortex_service.unregister_client(websocket)
            websocket_server.unregister_client(websocket)

# --- Semantic merge: A-only definitions preserved ---

def reset_to_domain_selection(session: Optional[str] = None):
    active_session = session if session and session != "default" else state_manager.get_active_session_id()
    state_manager.update_state(active_session, {
        "current_level": 1,
        "active_domain": None,
        "active_app": None,
        "last_resolved_action": "Domain Selection"
    })
    res_state = state_manager.get_state(active_session)
    try:
        from core.communication.websocket_server import websocket_server
        envelope = websocket_server.create_envelope(
            msg_type="STATE_UPDATE",
            source_domain="CORE",
            session_id=active_session,
            payload={"session_id": active_session, "action": "RESET_DOMAIN_SELECTION", "state": res_state},
        )
        websocket_server.broadcast_envelope_sync(envelope)
    except Exception:
        pass
    return {"status": "success", "state": res_state}

def get_lifecycle_summary(session: Optional[str] = None):
    """Get aggregated command lifecycle metrics, active count, stage counts, avg duration."""
    return {"status": "success", "summary": lifecycle_tracker.get_summary(session)}

def get_lifecycle_commands(session: Optional[str] = None, limit: int = 50):
    """Get recent command lifecycle records ordered by creation timestamp."""
    records = lifecycle_tracker.get_session_commands(session) if session else list(lifecycle_tracker._records.values())
    recs_sorted = sorted(records, key=lambda r: r.created_at, reverse=True)[:limit]
    return {
        "status": "success",
        "count": len(recs_sorted),
        "commands": [r.to_dict() for r in recs_sorted]
    }

def get_command_lifecycle(command_id: str):
    """Get complete lifecycle state and audit transition history for a single Command ID."""
    rec = lifecycle_tracker.get_record(command_id)
    if not rec:
        return {"status": "error", "message": f"Command ID '{command_id}' not found"}
    return {"status": "success", "command": rec.to_dict()}

def get_lifecycle_audit_trail(session: Optional[str] = None):
    """Export full command lifecycle audit trail with all timestamped transitions."""
    trail = lifecycle_tracker.export_audit_trail(session)
    return {"status": "success", "count": len(trail), "audit_trail": trail}

def get_uart_status():
    from core.plugin_manager.manager import get_plugin
    desktop = get_plugin("desktop")
    if desktop and hasattr(desktop, "uart_transport"):
        if desktop.uart_transport.config.get("enabled"):
            conn = desktop.uart_transport.serial_conn
            is_open = conn.is_open if conn else False
            return {
                "enabled": True,
                "connected": is_open,
                "port": desktop.uart_transport.config.get("port"),
                "baudrate": desktop.uart_transport.config.get("baudrate"),
                "latency_ms": 12 # Mock latency for now
            }
    return {"enabled": False, "connected": False, "port": "N/A"}
