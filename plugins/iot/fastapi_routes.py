"""
plugins/iot/fastapi_routes.py
------------------------------
FastAPI routes for the IoT domain plugin.
Serves the IoT dashboard at /iot and provides REST API endpoints
for IoT command dispatch, state ingestion, activity logging, telemetry standardization,
and connection health monitoring.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core.orchestration.ecosystem_orchestrator import ecosystem_orchestrator
from core.plugin_manager.manager import get_plugin
from core.state.state_manager import state_manager
from models.api_models import IoTDeviceItem, IoTDeviceListResponse, IoTStatusResponse
from models.device_models import DeviceState, IoTActivityRecord
from services.iot_telemetry_normalizer import normalize_iot_telemetry

BASE_DIR = Path(__file__).resolve().parent
DASHBOARD_DIR = BASE_DIR / "dashboard"

router = APIRouter()
logger = logging.getLogger("iot_routes")


# --- Pydantic Request Models ---

class IoTCommandRequest(BaseModel):
    command: str
    domain: str = "iot"
    device_id: Optional[str] = None


class IoTActivityLogRequest(BaseModel):
    device_id: str
    action: str
    previous_state: Optional[Dict[str, Any]] = None
    new_state: Optional[Dict[str, Any]] = None
    source: str = "REST_API"
    status: str = "SUCCESS"
    reason: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class IoTStatusIngestRequest(BaseModel):
    device_id: str
    light: Optional[str] = None
    fan: Optional[str] = None
    pump: Optional[str] = None
    states: Optional[Dict[str, Any]] = None
    mac: Optional[str] = None
    system: Optional[str] = "ESP32"
    firmware: Optional[str] = "2.0.0-unified"
    rssi: Optional[int] = None
    ip: Optional[str] = None
    uptime: Optional[int] = None


class IoTSensorIngestRequest(BaseModel):
    device_id: str
    temperature_celsius: Optional[float] = None
    humidity_pct: Optional[float] = None
    ambient_light_lux: Optional[float] = None
    motion_detected: Optional[bool] = None
    voltage_v: Optional[float] = None
    current_a: Optional[float] = None
    power_watts: Optional[float] = None
    energy_kwh: Optional[float] = None
    rssi: Optional[int] = None


# --- Dashboard HTML Endpoint ---

@router.get("/iot", response_class=HTMLResponse)
async def get_iot_dashboard():
    """Serve the IoT Team Console dashboard."""
    template_path = DASHBOARD_DIR / "index.html"
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()
    return HTMLResponse(content=content)


# --- IoT REST API Endpoints ---

@router.post("/api/iot/command")
async def dispatch_iot_command(request: IoTCommandRequest):
    """
    Dispatch an IoT command through the final backend orchestration flow.
    Integrates with EcosystemOrchestrator, SequenceValidator, RuleRouter,
    LifecycleTracker, StateManager, RetryManager, and the IoT Integration Layer.
    """
    device_id = request.device_id or "ESP32_RELAY_01"
    session_id = "default"

    try:
        # Route through the unified central orchestrator
        orch_res = await ecosystem_orchestrator.process_command(
            command=request.command,
            session=session_id,
            confidence=1.0,
            source="iot_dashboard",
            device_id=device_id
        )

        orch_status = orch_res.get("status", "unknown")
        action_result = orch_res.get("action_result") or {}
        
        is_action_dict = isinstance(action_result, dict)
        action_status = (action_result.get("status") if is_action_dict else None) or ""
        success = (orch_status == "success") and (action_status.lower() in ("success", "ok") if action_status else (orch_status == "success" and not orch_res.get("error")))

        cmd_id = orch_res.get("command_id") or (action_result.get("command_id") if is_action_dict else None) or f"cmd_{int(time.time()*1000)}"
        cmd_name = (action_result.get("command") if is_action_dict else None) or request.command
        topic = (action_result.get("topic") if is_action_dict else None) or f"iot/esp32/action"
        
        raw_payload = action_result.get("raw_payload") if is_action_dict else None
        if raw_payload:
            payload_str = json.dumps(raw_payload)
        else:
            payload_str = json.dumps({"command": cmd_name, "command_id": cmd_id})

        error_msg = None
        if not success:
            error_msg = (action_result.get("message") or action_result.get("error")) if is_action_dict else None
            if not error_msg and orch_res.get("validation", {}).get("rejection_reason"):
                error_msg = orch_res["validation"]["rejection_reason"]
            if not error_msg:
                error_msg = orch_res.get("error") or "Execution failed"

        lc_stage = orch_res.get("lifecycle_stage")
        if hasattr(lc_stage, "value"):
            lc_stage = lc_stage.value
        elif not lc_stage:
            lc_stage = "SUCCESS" if success else "FAILED"

        return {
            "success": success,
            "status": "success" if success else "failed",
            "action": request.command,
            "command": cmd_name,
            "domain": "iot",
            "device_id": device_id,
            "command_id": cmd_id,
            "topic": topic,
            "payload": payload_str,
            "error": error_msg,
            "lifecycle_stage": lc_stage,
            "lifecycle": orch_res.get("lifecycle"),
            "state": orch_res.get("state") or state_manager.get_state(session_id),
            "orchestrator_result": orch_res
        }
    except Exception as e:
        logger.error(f"IoT command dispatch error: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "status": "error",
                "error_code": "IOT_DISPATCH_ERROR",
                "message": str(e),
                "error": str(e),
                "details": [str(e)]
            }
        )


@router.get("/api/iot/devices")
async def get_online_devices():
    """Return list of online IoT devices with standardized DeviceState and connectivity."""
    plugin = get_plugin("iot")
    if not plugin:
        return {"devices": [], "count": 0}

    # Run background timeout check on device list retrieval (Task 4)
    plugin.check_timeouts(timeout_seconds=15.0)

    devices = []
    mqtt_connected = getattr(plugin, "connected", False)
    all_devs = plugin.device_manager.get_all_devices()
    
    for dev_obj in all_devs:
        dev_dict = dev_obj.to_dict()
        device_state = dev_obj.to_device_state()

        devices.append({
            "device_id": dev_obj.device_id,
            "status": dev_dict,
            "device_state": device_state.to_dict()
        })

    # If device manager was empty but latest_status had entries, include them
    if not devices and plugin.latest_status:
        for device_id, status_data in plugin.latest_status.items():
            st_copy = dict(status_data)
            dev_state = DeviceState.from_iot_device(st_copy)
            devices.append({
                "device_id": device_id,
                "status": st_copy,
                "device_state": dev_state.to_dict()
            })

    return {"devices": devices, "count": len(devices)}


@router.get("/api/iot/status", response_model=IoTStatusResponse)
async def get_iot_plugin_status():
    """Return IoT plugin connection status and online device count."""
    plugin = get_plugin("iot")
    if not plugin:
        return {"connected": False, "error": "IoT plugin not loaded"}

    plugin.check_timeouts(timeout_seconds=15.0)

    online_count = plugin.device_manager.online_devices_count() if hasattr(plugin, "device_manager") else len(plugin.latest_status)

    return {
        "connected": plugin.connected,
        "broker": plugin.broker,
        "port": plugin.port,
        "devices_online": online_count,
    }


# --- Activity Log Endpoints (Task 2) ---

@router.get("/api/iot/activity-logs")
async def get_iot_activity_logs(
    device_id: Optional[str] = Query(None, description="Filter by device ID"),
    limit: int = Query(50, ge=1, le=500, description="Max records to return")
):
    """Retrieve structured IoT activity logs."""
    plugin = get_plugin("iot")
    if not plugin or not hasattr(plugin, "device_manager"):
        return {"activity_logs": [], "count": 0}

    logs = plugin.device_manager.get_activity_logs(device_id=device_id, limit=limit)
    return {"activity_logs": logs, "count": len(logs)}


@router.post("/api/iot/activity-log")
async def ingest_iot_activity_log(request: IoTActivityLogRequest):
    """Ingest an activity log record directly via REST."""
    plugin = get_plugin("iot")
    if not plugin or not hasattr(plugin, "device_manager"):
        raise HTTPException(status_code=503, detail="IoT plugin not initialized")

    record = plugin.device_manager.log_activity(
        device_id=request.device_id,
        action=request.action,
        previous_state=request.previous_state,
        new_state=request.new_state,
        source=request.source,
        status=request.status,
        reason=request.reason,
        metadata=request.metadata,
    )
    return {"status": "success", "activity_id": record.activity_id, "record": record.to_dict()}


# --- Device State & Sensor Ingestion Endpoints (Task 1 & 3) ---

@router.post("/api/iot/ingest/status")
async def ingest_device_status(payload: IoTStatusIngestRequest):
    """Ingest IoT device status via REST API (mirrors MQTT /status topic)."""
    plugin = get_plugin("iot")
    if not plugin:
        raise HTTPException(status_code=503, detail="IoT plugin not loaded")

    data = payload.model_dump(exclude_none=True)
    device_id = payload.device_id
    plugin.handle_status(device_id, data)

    dev = plugin.device_manager.get_device(device_id)
    return {
        "status": "success",
        "device_id": device_id,
        "device_state": dev.to_device_state().to_dict() if dev else {}
    }


@router.post("/api/iot/ingest/sensor")
async def ingest_sensor_telemetry(payload: IoTSensorIngestRequest):
    """Ingest IoT sensor telemetry via REST API (mirrors MQTT /sensor topic)."""
    plugin = get_plugin("iot")
    if not plugin:
        raise HTTPException(status_code=503, detail="IoT plugin not loaded")

    data = payload.model_dump(exclude_none=True)
    device_id = payload.device_id
    plugin.handle_sensor(device_id, data)

    dev = plugin.device_manager.get_device(device_id)
    telemetry_packet = normalize_iot_telemetry(dev.to_dict() if dev else data, device_id=device_id)
    return {
        "status": "success",
        "device_id": device_id,
        "telemetry": telemetry_packet.to_dict()
    }


@router.get("/api/iot/telemetry/latest")
async def get_latest_telemetry(device_id: Optional[str] = Query(None)):
    """Return latest standardized telemetry packet for an IoT device."""
    plugin = get_plugin("iot")
    if not plugin:
        raise HTTPException(status_code=503, detail="IoT plugin not loaded")

    target_id = device_id
    if not target_id:
        all_devs = plugin.device_manager.get_all_devices()
        if all_devs:
            target_id = all_devs[0].device_id
        else:
            target_id = "ESP32_RELAY_01"

    dev = plugin.device_manager.get_device(target_id)
    raw_data = dev.to_dict() if dev else plugin.latest_sensor.get(target_id, {})
    packet = normalize_iot_telemetry(raw_data, device_id=target_id)
    return packet.to_dict()


# --- Setup Function ---

def setup_iot_routes(app: FastAPI):
    """Register IoT routes and mount static assets."""
    app.include_router(router)

    # Mount static files for the IoT dashboard
    if DASHBOARD_DIR.exists():
        app.mount("/iot/static", StaticFiles(directory=str(DASHBOARD_DIR)), name="iot_dashboard_static")
        logger.info(f"Mounted IoT dashboard static files from {DASHBOARD_DIR}")
