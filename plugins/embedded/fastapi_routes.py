"""
plugins/embedded/fastapi_routes.py
-----------------------------------
FastAPI routes for the Embedded Robotics Domain (SynaptiMesh Master Hub & Car Control).
Integrates the updated Embedded Dashboard v9.2 functionality, WebSocket & REST APIs,
multi-transport ESP32 connector, BCI controller, command logger, and centralized Cortex bridge.
"""

import asyncio
import json
import logging
import os
import re
import ssl
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import websockets
from fastapi import APIRouter, FastAPI, File, Form, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from models.api_models import EmbeddedCommandRequest
from services.cortex_service import CortexService
from plugins.embedded.dashboard.bci_controller import BCIController
from plugins.embedded.dashboard.command_logger import CommandLogger
from plugins.embedded.dashboard.esp32_connection_manager import SynaptiMeshESP32Connector
import plugins.embedded.dashboard.embedded_config as config

BASE_DIR = Path(__file__).resolve().parent
DASHBOARD_DIR = BASE_DIR / "dashboard"
TEMPLATES_DIR = DASHBOARD_DIR / "templates"
STATIC_DIR = DASHBOARD_DIR / "static"

router = APIRouter()
logger = logging.getLogger("embedded_routes")

# ---------------------------------------------------------------------------
# Core Embedded Singletons
# ---------------------------------------------------------------------------
_bci_config = dict(
    power_threshold=config.POWER_THRESHOLD,
    debounce_ms=config.DEBOUNCE_MS,
    single_fire_window_ms=config.SINGLE_FIRE_WINDOW_MS,
    neutral_stop=config.NEUTRAL_STOPS_CAR,
    combo_window_ms=config.COMBO_WINDOW_MS,
)

bci = BCIController(**_bci_config)
simulator_bci = BCIController(**_bci_config)
command_logger = CommandLogger(log_dir=str(DASHBOARD_DIR / "logs"))

esp32 = SynaptiMeshESP32Connector(
    mode=os.getenv("ESP32_MODE", "mqtt"),
    esp32_ip=os.getenv("ESP32_IP", "172.28.27.14"),
    esp32_port=int(os.getenv("ESP32_PORT", 80)),
    serial_port_path=os.getenv("SERIAL_PORT", "COM5"),
    baud_rate=int(os.getenv("BAUD_RATE", 115200)),
    mqtt_broker=config.MQTT_BROKER,
    mqtt_port=config.MQTT_PORT,
    mqtt_base_topic=config.MQTT_BASE_TOPIC,
    mqtt_device_id=config.MQTT_DEVICE_ID,
)

# Connected WebSocket clients for real-time dashboard events
_ws_clients: Set[WebSocket] = set()
_ws_lock = threading.Lock()

# Lazy hub reference
_hub_instance = None
_hub_thread_started = False


def get_embedded_hub():
    global _hub_instance
    if _hub_instance is None:
        try:
            from plugins.embedded.dashboard.embedded_backend.hub import Hub
            _hub_instance = Hub()
            _hub_instance.initialize()
            logger.info("[EMBEDDED] SynaptiMesh Hub initialized successfully")
        except Exception as e:
            logger.error(f"[EMBEDDED] Failed to initialize Embedded Hub: {e}")
    return _hub_instance


def _run_embedded_flask_server():
    try:
        logging.getLogger("werkzeug").setLevel(logging.CRITICAL)
        from plugins.embedded.dashboard.app import app as flask_app, hub as app_hub
        app_hub.initialize()
        logger.info(f"[EMBEDDED] Running Embedded Hub Socket.IO server on {config.HOST}:{config.PORT}")
        app_hub.socket.socket.run(
            flask_app,
            host=config.HOST,
            port=config.PORT,
            debug=False,
            use_reloader=False,
            allow_unsafe_werkzeug=True
        )
    except Exception as e:
        logger.error(f"[EMBEDDED] Error running Embedded Flask Socket.IO server: {e}")


def ensure_embedded_server_started():
    global _hub_thread_started
    if not _hub_thread_started:
        _hub_thread_started = True
        t = threading.Thread(target=_run_embedded_flask_server, daemon=True)
        t.start()
        logger.info("[EMBEDDED] Embedded Hub background server thread started")


async def broadcast_embedded_event(event_type: str, payload: Any):
    """Broadcast an event payload to all connected Embedded dashboard WebSockets."""
    message = json.dumps({"type": event_type, "payload": payload}, default=str)
    with _ws_lock:
        clients = list(_ws_clients)

    dead_clients = []
    for ws in clients:
        try:
            await ws.send_text(message)
        except Exception:
            dead_clients.append(ws)

    if dead_clients:
        with _ws_lock:
            for ws in dead_clients:
                _ws_clients.discard(ws)


def _safe_async_broadcast(event_type: str, payload: Any):
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(broadcast_embedded_event(event_type, payload))
    except RuntimeError:
        pass


# ---------------------------------------------------------------------------
# Wire Event Callbacks from BCIController & ESP32 Connector
# ---------------------------------------------------------------------------
def _wire_event_handlers():
    cortex_service = CortexService.get_instance()

    # Forward Cortex events to connected clients
    cortex_service.on("cortex_status", lambda s: _safe_async_broadcast("cortex_status", s))
    cortex_service.on("cortex_com", lambda d: _safe_async_broadcast("cortex_com", d))
    cortex_service.on("cortex_pow", lambda d: _safe_async_broadcast("cortex_pow", d))
    cortex_service.on("cortex_sys", lambda d: _safe_async_broadcast("cortex_sys", d))
    cortex_service.on("cortex_dev", lambda d: _safe_async_broadcast("cortex_dev", d))
    cortex_service.on("telemetry", lambda d: _safe_async_broadcast("telemetry", d))
    cortex_service.on("log", lambda d: _safe_async_broadcast("log", {"source": "CORTEX", **d}))

    # Forward BCI events
    bci.on("actuator_command", lambda cmd: _safe_async_broadcast("actuator_command", cmd))
    bci.on("combo_triggered", lambda d: (_safe_async_broadcast("combo_triggered", d), _safe_async_broadcast("log", {"source": "BCI COMBO", "level": "success", "message": d.get("message", d.get("combo", "Combination detected"))})))
    bci.on("combo_window_started", lambda d: _safe_async_broadcast("combo_window_started", d))
    bci.on("combo_window_expired", lambda d: _safe_async_broadcast("combo_window_expired", d))
    bci.on("combo_window_rejected", lambda d: _safe_async_broadcast("combo_window_rejected", d))
    bci.on("command_filtered", lambda d: _safe_async_broadcast("command_filtered", d))
    bci.on("single_fire_suppressed", lambda d: _safe_async_broadcast("single_fire_suppressed", d))
    bci.on("telemetry", lambda d: _safe_async_broadcast("telemetry", d))
    bci.on("log", lambda d: _safe_async_broadcast("log", {"source": "BCI", "level": "info", "message": d.get("message", "")}))

    # Forward ESP32 events
    esp32.on("log", lambda d: _safe_async_broadcast("log", {"source": "ESP32", **d}))
    esp32.on("esp32_monitor", lambda msg, level="info": _safe_async_broadcast("esp32_monitor", {"message": msg, "level": level}))
    esp32.on("esp32_config", lambda cfg: _safe_async_broadcast("esp32_config", cfg))
    esp32.on("esp32_ack", lambda ack: _safe_async_broadcast("ack", ack))
    esp32.on("esp32_rx", lambda d: _safe_async_broadcast("esp32_rx", d))
    esp32.on("esp32_tx_result", lambda res: _safe_async_broadcast("esp32_tx_result", res))


_wire_event_handlers()


async def send_logged_car_command(command: str, source: str, **metadata) -> Dict[str, Any]:
    """Execute car command via ESP32 multi-transport connector and record to CommandLogger."""
    result = await esp32.send_car_command(command)
    event = command_logger.log(command, source, result=result, **metadata)
    await broadcast_embedded_event("command_logged", event)
    await broadcast_embedded_event("car_command_dispatched", {
        "command": command,
        "source": source,
        "result": result,
        "timestamp": event["timestamp_unix_ms"]
    })
    return result


# ---------------------------------------------------------------------------
# HTML Template Endpoints
# ---------------------------------------------------------------------------

def _render_template(template_name: str) -> HTMLResponse:
    ensure_embedded_server_started()
    template_path = TEMPLATES_DIR / template_name
    if not template_path.exists():
        return HTMLResponse(content=f"<h1>Embedded template {template_name} not found</h1>", status_code=404)
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    v = int(time.time())
    content = re.sub(
        r"\{\{\s*url_for\('static',\s*filename='([^']+)'\)\s*(\?[^\"']*)?\}\}",
        rf"/embedded/static/\1?v={v}",
        content
    )
    content = content.replace("{{ url_for('index') }}", "/embedded")
    content = content.replace("{{ url_for('car_control') }}", "/embedded/car-control")
    return HTMLResponse(content=content, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@router.get("/embedded", response_class=HTMLResponse)
@router.get("/embedded/dashboard", response_class=HTMLResponse)
async def get_embedded_dashboard():
    """Serve the SynaptiMesh Embedded Master Hub Dashboard v9.2."""
    return _render_template("index.html")


@router.get("/embedded/car-control", response_class=HTMLResponse)
@router.get("/car-control", response_class=HTMLResponse)
async def get_embedded_car_control():
    """Serve the SynaptiMesh 3D Robot Car Control simulation page."""
    return _render_template("car_control.html")


@router.get("/embedded/desktop-car-control", response_class=HTMLResponse)
@router.get("/desktop-car-control", response_class=HTMLResponse)
async def get_embedded_desktop_car_control():
    """Serve desktop car control."""
    return _render_template("desktop_car_control.html")


@router.get("/embedded/mobile-car-control", response_class=HTMLResponse)
@router.get("/mobile-car-control", response_class=HTMLResponse)
async def get_embedded_mobile_car_control():
    """Serve mobile car control."""
    return _render_template("mobile_car_control.html")

# ---------------------------------------------------------------------------
# WebSocket Real-Time Communication Endpoint
# ---------------------------------------------------------------------------

@router.websocket("/ws")
@router.websocket("/embedded/ws")
async def embedded_ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("[WS SERVER] WS_CONNECTED: New client connection to Embedded Hub")
    with _ws_lock:
        _ws_clients.add(websocket)

    from core.communication.websocket_server import websocket_server
    session = websocket_server.register_client(websocket)

    cortex_service = CortexService.get_instance()
    cortex_service.register_client(websocket)

    # Initial state sync
    try:
        await websocket.send_text(json.dumps({
            "type": "cortex_status",
            "payload": cortex_service.get_status()
        }))
        await websocket.send_text(json.dumps({
            "type": "esp32_config",
            "payload": esp32.get_config()
        }))
        await websocket.send_text(json.dumps({
            "type": "bci_config",
            "payload": bci.get_config()
        }))
        await websocket.send_text(json.dumps({
            "type": "state_machine",
            "payload": bci.get_full_state()
        }))
        await websocket.send_text(json.dumps({
            "type": "log",
            "payload": {
                "source": "SYSTEM",
                "level": "success",
                "message": "Connected to SynaptiMesh Embedded Master Hub."
            }
        }))
    except Exception as err:
        logger.warning(f"[EMBEDDED WS] Error sending initial handshake: {err}")

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                msg_type = msg.get("type", "")

                if msg_type == "ping":
                    await websocket.send_text(json.dumps({"type": "pong", "payload": {"time": time.time()}}))

                elif msg_type == "car_command":
                    cmd = msg.get("command", "")
                    if cmd:
                        await send_logged_car_command(cmd, "WS_CLIENT")

                elif msg_type == "simulate":
                    action = msg.get("action", "")
                    power = float(msg.get("power", 1.0))
                    if action:
                        bci.process_mental_command(action, power)

            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        logger.info(f"[WS SERVER] WS_DISCONNECTED: Client {session.client_id} disconnected normally.")
    except Exception as e:
        logger.error(f"[WS SERVER] WS_ERROR: Embedded WebSocket closed with error: {e}")
    finally:
        logger.info(f"[WS SERVER] WS_CLEANUP: Cleaning up resources for client {session.client_id}")
        with _ws_lock:
            _ws_clients.discard(websocket)
        from core.communication.websocket_server import websocket_server
        websocket_server.unregister_client(websocket)
        cortex_service.unregister_client(websocket)


# ---------------------------------------------------------------------------
# REST API Endpoints for Dashboard v9.2
# ---------------------------------------------------------------------------

@router.get("/api/status")
async def get_api_status():
    """Return comprehensive system status for Embedded Dashboard v9.2."""
    cortex_service = CortexService.get_instance()
    return {
        "stateMachine": bci.get_full_state(),
        "cortex": cortex_service.get_status(),
        "car": {
            "target": "robotcar",
            "mqttConnected": getattr(esp32, "mqtt_connected", False),
            "robotCarOnline": getattr(esp32, "robot_car_online", False),
        },
        "esp32": esp32.get_config()
    }


@router.get("/api/bci/config")
@router.get("/api/embedded/config")
@router.get("/api/config")
async def get_api_config():
    cortex_service = CortexService.get_instance()
    return {
        "cortex": cortex_service.get_status(),
        "bci": bci.get_config(),
        "esp32": esp32.get_config()
    }


@router.post("/api/bci/config")
@router.post("/api/embedded/config")
@router.post("/api/config")
async def set_api_config(request: Request):
    body = await request.json()
    bci_cfg = body.get("bci") or body.get("stateMachineConfig") or body
    bci.update_config(bci_cfg)
    return {"success": True, "bci": bci.get_config()}


@router.post("/api/car/command")
async def api_car_command(request: Request):
    """Handle car control commands from dashboard v9.2 buttons and controls."""
    body = await request.json()
    cmd = str(body.get("command", "")).strip().upper()
    source = str(body.get("source", "MANUAL_CONTROLLER")).strip()

    if not cmd:
        return JSONResponse(status_code=400, content={"success": False, "error": "Command is required"})

    result = await send_logged_car_command(cmd, source)
    status_code = 200 if result.get("success") else 500
    return JSONResponse(status_code=status_code, content=result)


@router.post("/api/simulate")
async def api_simulate(request: Request):
    """Simulate low-latency BCI mental command."""
    body = await request.json()
    action = str(body.get("action", "")).strip().lower()
    power = float(body.get("power", 0.85))

    if not action:
        return JSONResponse(status_code=400, content={"success": False, "error": "Action is required"})

    # Process simulator action
    res = simulator_bci.process_simulator_selection([action], power=power)
    # Also forward to live bci for live state mirroring
    bci.process_mental_command(action, power)

    return {
        "success": True,
        "action": action,
        "power": power,
        "result": res,
        "currentState": bci.get_full_state()
    }


@router.post("/api/simulate-combination")
async def api_simulate_combination(request: Request):
    """Simulate BCI combination command (e.g. push + pull)."""
    body = await request.json()
    actions = body.get("actions", ["push", "pull"])
    power = float(body.get("power", 0.85))

    res = simulator_bci.process_simulator_selection(actions, power=power)
    return {
        "success": res.get("type") != "SIMULATION_REJECTED",
        "actions": actions,
        "result": res,
        "currentState": simulator_bci.get_full_state(),
        "liveState": bci.get_full_state(),
    }


@router.post("/api/bci/select-domain")
async def api_bci_select_domain(request: Request):
    body = await request.json()
    domain = body.get("domain", "EMBEDDED")
    try:
        res = bci.select_domain(domain)
        return {"success": True, "result": res, "currentState": bci.get_full_state()}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"success": False, "error": str(e)})


@router.post("/api/bci/select-device")
async def api_bci_select_device(request: Request):
    body = await request.json()
    device = body.get("device", "car")
    res = bci.select_device(device)
    status_code = 200 if res.get("success") else 400
    return JSONResponse(status_code=status_code, content={**res, "currentState": bci.get_full_state()})


@router.post("/api/bci/reset")
async def api_bci_reset():
    res = bci.reset_navigation("dashboard_reset")
    return {"success": True, "result": res, "currentState": bci.get_full_state()}


# ---------------------------------------------------------------------------
# Cortex API Bridge Endpoints (Consumes Centralized CortexService)
# ---------------------------------------------------------------------------

@router.post("/api/cortex/connect")
async def api_cortex_connect(request: Request):
    cortex_service = CortexService.get_instance()
    body = await request.json()
    if body:
        cortex_service.set_credentials(
            client_id=body.get("clientId") or body.get("client_id", ""),
            client_secret=body.get("clientSecret") or body.get("client_secret", ""),
            license_key=body.get("license") or body.get("license_key", ""),
            profile_name=body.get("profile") or body.get("profile_name", "")
        )
    res = await cortex_service.connect()
    return {"success": True, "status": cortex_service.get_status(), "result": res}


@router.post("/api/cortex/disconnect")
async def api_cortex_disconnect():
    cortex_service = CortexService.get_instance()
    await cortex_service.disconnect()
    return {"success": True, "message": "Disconnected from Emotiv Cortex."}


@router.get("/api/cortex/profiles")
async def api_cortex_profiles():
    cortex_service = CortexService.get_instance()
    profiles = await cortex_service.query_profiles()
    return {"success": True, "profiles": profiles, "activeProfile": cortex_service.active_profile}


@router.post("/api/cortex/load-profile")
async def api_cortex_load_profile(request: Request):
    cortex_service = CortexService.get_instance()
    body = await request.json()
    name = body.get("profile")
    if not name:
        return JSONResponse(status_code=400, content={"error": "Profile name is required."})
    res = await cortex_service.load_profile(name)
    ok = res.get("status") == "success"
    return {"success": ok, "activeProfile": cortex_service.active_profile, "result": res}


@router.post("/api/cortex/diagnose")
async def api_cortex_diagnose():
    cortex_service = CortexService.get_instance()
    res = await cortex_service.run_diagnostic()
    return res


# ---------------------------------------------------------------------------
# ESP32 Multi-Transport & Firmware Flashing Endpoints
# ---------------------------------------------------------------------------

@router.get("/api/esp32/ports")
async def api_esp32_ports():
    ports = esp32.get_available_ports()
    return {"success": True, "ports": ports}


@router.post("/api/esp32/connect")
async def api_esp32_connect():
    try:
        if esp32.mode == "serial":
            ok = esp32.init_serial()
        elif esp32.mode == "mqtt":
            ok = esp32.init_mqtt(force=True)
        elif esp32.mode in ("wifi", "http"):
            result = await esp32.ping()
            return result
        else:
            return JSONResponse(status_code=400, content={"success": False, "error": f"Unsupported ESP32 mode: {esp32.mode}"})
        return {"success": bool(ok), "config": esp32.get_config(), "error": None if ok else esp32.last_error}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e), "config": esp32.get_config()})


@router.post("/api/esp32/disconnect")
async def api_esp32_disconnect():
    try:
        esp32.disconnect_serial()
        esp32.disconnect_mqtt()
        return {"success": True, "config": esp32.get_config()}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@router.post("/api/esp32/serial/write")
async def api_esp32_serial_write(request: Request):
    body = await request.json()
    text = str(body.get("text", "")).strip()
    if not text:
        return JSONResponse(status_code=400, content={"success": False, "error": "Serial text is required."})
    if esp32.mode != "serial":
        return JSONResponse(status_code=400, content={"success": False, "error": "ESP32 connector is not in serial mode."})

    try:
        if not esp32.serial_conn or not esp32.serial_conn.is_open:
            if not esp32.init_serial():
                return JSONResponse(status_code=503, content={"success": False, "error": esp32.last_error or "Serial port unavailable"})
        wire = text.rstrip("\r\n") + "\n"
        esp32.serial_conn.write(wire.encode("utf-8"))
        esp32.serial_conn.flush()
        esp32.emit("log", {"level": "info", "message": f"[ESP32 Serial TX] {text}"})
        return {"success": True, "port": esp32.serial_port_path, "text": text}
    except Exception as e:
        esp32.last_error = str(e)
        esp32.emit("log", {"level": "error", "message": f"[ESP32 Serial TX ERROR] {e}"})
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@router.get("/api/esp32/config")
async def api_esp32_get_config():
    return {"success": True, "config": esp32.get_config()}


@router.post("/api/esp32/config")
async def api_esp32_set_config(request: Request):
    body = await request.json()
    esp32.update_config(body or {})
    return {"success": True, "config": esp32.get_config()}


@router.post("/api/esp32/test")
async def api_esp32_test():
    return await esp32.test_transport()


@router.post("/api/esp32/flash")
async def api_esp32_flash(
    firmware: UploadFile = File(...),
    port: str = Form(""),
    offset: str = Form("0x10000"),
    baud: int = Form(460800)
):
    if not port:
        port = esp32.serial_port_path
    filename = os.path.basename(firmware.filename or "firmware.bin")
    suffix = Path(filename).suffix.lower()
    if suffix != ".bin":
        return JSONResponse(status_code=400, content={"success": False, "error": "Upload a compiled .bin firmware file."})

    temp_dir = tempfile.mkdtemp(prefix="synaptimesh_fw_")
    target = os.path.join(temp_dir, filename)
    try:
        with open(target, "wb") as f:
            f.write(await firmware.read())
        await send_logged_car_command("STOP", "FIRMWARE_FLASH_SAFETY_STOP")
        was_serial = esp32.mode == "serial"
        if was_serial:
            esp32.disconnect_serial()

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: esp32.flash_firmware(port, target, offset, baud))
        if was_serial:
            esp32.init_serial()
        return result
    finally:
        try:
            if os.path.exists(target):
                os.remove(target)
            os.rmdir(temp_dir)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Legacy Command Dispatch API (Backwards Compatibility)
# ---------------------------------------------------------------------------

@router.post("/command")
@router.post("/embedded/command")
async def dispatch_embedded_command(request: Request):
    """
    Handle embedded web commands (e.g. LIFTCARFORWARD, LIFTCARSTOP, etc.).
    Dispatches via Hub's dispatcher and SynaptiMesh ESP32 connector.
    Supports both JSON and text/plain bodies.
    """
    content_type = request.headers.get("content-type", "")
    device_header = request.headers.get("x-synaptimesh-device", "").strip()
    text_command = ""
    domain = None
    target_param = None

    if "json" in content_type:
        try:
            body = await request.json()
            if isinstance(body, dict):
                text_command = str(body.get("command", "")).strip().upper()
                domain = body.get("domain")
                target_param = body.get("target") or body.get("device")
            else:
                text_command = str(body).strip().upper()
        except Exception:
            pass
    else:
        raw_body = await request.body()
        text_command = raw_body.decode("utf-8", errors="ignore").strip().upper()

    if not text_command:
        return JSONResponse(
            status_code=422,
            content={
                "status": "error",
                "ok": False,
                "error_code": "VALIDATION_ERROR",
                "message": "Missing command or commands field",
                "details": ["command cannot be empty"]
            }
        )

    domains = ("LIFT", "DESKTOP", "IOT")
    matched_domain = None
    if domain:
        if domain.upper() in domains:
            matched_domain = domain.upper()
        else:
            return JSONResponse(
                status_code=400,
                content={
                    "status": "error",
                    "ok": False,
                    "error_code": "INVALID_DOMAIN",
                    "message": f"Invalid domain: {domain}",
                    "details": [f"Domain '{domain}' is not in valid domains: {domains}"]
                }
            )
    else:
        for d in domains:
            if text_command.startswith(d):
                matched_domain = d
                break
        if not matched_domain and ("CAR" in text_command or "CHAIR" in text_command):
            return JSONResponse(
                status_code=400,
                content={
                    "status": "error",
                    "ok": False,
                    "error_code": "INVALID_DOMAIN",
                    "message": "Invalid domain prefix in command",
                    "details": [f"Command '{text_command}' does not begin with a valid domain: {domains}"]
                }
            )
    domain = matched_domain or "LIFT"

    remaining = text_command[len(domain):] if text_command.startswith(domain) else text_command
    from plugins.embedded.dashboard.embedded_backend.device_registry import CommandTarget
    from plugins.embedded.dashboard.embedded_backend.dispatcher import CommandSource

    target_candidate = target_param or device_header
    if target_candidate:
        tgt_str = str(target_candidate).upper()
        target = CommandTarget.CAR if "CAR" in tgt_str else CommandTarget.CHAIR
        command = remaining.replace("CAR", "").replace("CHAIR", "") if ("CAR" in remaining or "CHAIR" in remaining) else remaining
    elif remaining.startswith("CAR"):
        target = CommandTarget.CAR
        command = remaining[3:]
    elif remaining.startswith("CHAIR"):
        target = CommandTarget.CHAIR
        command = remaining[5:]
    else:
        target = CommandTarget.CAR
        command = remaining

    VALID_COMMANDS = {
        "FORWARD", "BACKWARD", "LEFT", "RIGHT",
        "LEFT360", "RIGHT360", "STOP", "DROP", "PING"
    }

    if command not in VALID_COMMANDS:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "ok": False,
                "error_code": "INVALID_COMMAND",
                "message": f"Invalid command: {command}",
                "details": [f"Command '{command}' is not in valid commands list: {sorted(list(VALID_COMMANDS))}"]
            }
        )

    # Dispatch via both Hub dispatcher & ESP32 connection manager
    hub = get_embedded_hub()
    if hub and hasattr(hub, "dispatcher"):
        hub.dispatcher.dispatch(
            source=CommandSource.DASHBOARD,
            target=target,
            domain=domain,
            command=command
        )

    result = await send_logged_car_command(command, "DASHBOARD_API", domain=domain, target=str(target))
    logger.info(f"[EMBEDDED COMMAND] Dispatched {text_command} -> target={target}, command={command}")
    return {"status": "ok", "ok": True, "command": text_command, "device": str(target), "result": result}


@router.get("/api/embedded/telemetry")
async def get_embedded_telemetry_snapshot(device_id: Optional[str] = None):
    """Retrieve isolated telemetry snapshots for a specific device or all devices."""
    hub = get_embedded_hub()
    if hub and hasattr(hub, "telemetry"):
        if device_id:
            dev_data = hub.telemetry.get_device_latest(device_id)
            if dev_data:
                return {"status": "success", "device_id": device_id, "telemetry": dev_data}
            return JSONResponse(status_code=404, content={"status": "not_found", "message": f"Device {device_id} not found"})
        return {"status": "success", "devices": hub.telemetry.get_all_devices_latest(), "latest": hub.telemetry.get_latest()}
    return {"status": "success", "devices": {}, "latest": None}


@router.get("/api/embedded/devices")
async def get_embedded_devices_list():
    """Retrieve list of all active/registered embedded devices."""
    hub = get_embedded_hub()
    devices = []
    if hub and hasattr(hub, "telemetry"):
        all_devs = hub.telemetry.get_all_devices_latest()
        for dev_id, state in all_devs.items():
            devices.append({
                "device_id": dev_id,
                "device_mode": state.get("device_mode", "RC_CAR"),
                "status": state.get("status", "ONLINE"),
                "state": state.get("state", "STOP"),
                "battery_soc_pct": state.get("battery_soc_pct"),
                "supply_voltage_v": state.get("supply_voltage_v")
            })
    return {"status": "success", "count": len(devices), "devices": devices}


# ---------------------------------------------------------------------------
# Setup Function for FastAPI
# ---------------------------------------------------------------------------

def setup_embedded_routes(app: FastAPI):
    """Register embedded routes and mount static files."""
    app.include_router(router)

    if STATIC_DIR.exists():
        app.mount("/embedded/static", StaticFiles(directory=str(STATIC_DIR)), name="embedded_static")
        logger.info(f"Mounted Embedded static files from {STATIC_DIR}")

    ensure_embedded_server_started()
