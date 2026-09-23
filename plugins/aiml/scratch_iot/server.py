"""
server.py
Master IoT Hub Server for Emotiv EPOC BCI + ESP32 Actuator Controller in Python.
Built with FastAPI, Uvicorn, and WebSockets.
"""

import sys
import os
import json
import time
import asyncio
from typing import Dict, Any, Set
from contextlib import asynccontextmanager
import websockets

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from state_machine import BCIStateMachine
from cortex_bridge import CortexBridge
from esp32_connector import ESP32Connector

load_dotenv()

PORT = int(os.getenv("PORT", 3000))
HOST = os.getenv("HOST", "0.0.0.0")

# Instantiate Core Engines
state_machine = BCIStateMachine(
    power_threshold=float(os.getenv("POWER_THRESHOLD", 0.35)),
    debounce_ms=int(os.getenv("DEBOUNCE_MS", 900)),
    single_fire_window_ms=int(os.getenv("SINGLE_FIRE_WINDOW_MS", 1500)),
    combo_window_ms=int(os.getenv("COMBO_WINDOW_MS", 2000)),
    framing_window_ms=int(os.getenv("FRAMING_WINDOW_MS", 4000)),
    framing_enabled=os.getenv("FRAMING_ENABLED", "true").lower() in ("true", "1", "yes"),
    auto_return_timeout_ms=int(os.getenv("AUTO_RETURN_TIMEOUT_MS", 0)),
)

cortex_bridge = CortexBridge(
    url=os.getenv("CORTEX_URL", "wss://localhost:6868"),
    client_id=os.getenv("CORTEX_CLIENT_ID", ""),
    client_secret=os.getenv("CORTEX_CLIENT_SECRET", ""),
    license_key=os.getenv("CORTEX_LICENSE", ""),
    debit=1,
)

esp32_connector = ESP32Connector(
    mode=os.getenv("ESP32_MODE", "serial"),
    esp32_ip=os.getenv("ESP32_IP", "192.168.1.100"),
    esp32_port=int(os.getenv("ESP32_PORT", 80)),
    serial_port_path=os.getenv("ESP32_SERIAL_PORT", "COM5"),
    baud_rate=int(os.getenv("ESP32_BAUD_RATE", 115200)),
)

# Connected Dashboard WebSockets
dashboard_clients: Set[WebSocket] = set()


async def broadcast(event_type: str, payload: Any):
    if not dashboard_clients:
        return
    message = json.dumps({
        "type": event_type,
        "payload": payload,
        "timestamp": int(time.time() * 1000),
    })

    disconnected = set()
    for ws in list(dashboard_clients):
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.add(ws)

    for dead_ws in disconnected:
        dashboard_clients.discard(dead_ws)


# ----------------------------------------------------
# Event Wiring & Pipeline Hookup
# ----------------------------------------------------

# 1. Cortex Bridge Events
async def on_cortex_com(data):
    state_machine.process_mental_command(data.get("action"), data.get("power", 0.0), False)
    await broadcast("cortex_com", data)

async def on_cortex_pow(data):
    await broadcast("cortex_pow", data)

async def on_cortex_sys(data):
    await broadcast("cortex_sys", data)

async def on_cortex_dev(data):
    await broadcast("cortex_dev", data)

async def on_cortex_status_change(status):
    await broadcast("cortex_status", cortex_bridge.get_status())

async def on_cortex_log(log_entry):
    await broadcast("log", {"source": "CORTEX", **log_entry})

cortex_bridge.on("com", on_cortex_com)
cortex_bridge.on("pow", on_cortex_pow)
cortex_bridge.on("sys", on_cortex_sys)
cortex_bridge.on("dev", on_cortex_dev)
cortex_bridge.on("status_change", on_cortex_status_change)
cortex_bridge.on("log", on_cortex_log)


# 2. State Machine Events
async def on_sm_telemetry(telemetry):
    await broadcast("telemetry", telemetry)

async def on_sm_transition(transition):
    await broadcast("state_transition", transition)
    await broadcast("log", {
        "source": "STATE_MACHINE",
        "level": "info",
        "message": f"State Transition: [{transition.get('type')}] State: {transition.get('currentState')}, Target: {transition.get('selectedDevice') or 'None'}",
    })

async def on_sm_device_selected(selection):
    await broadcast("device_selected", selection)
    await broadcast("log", {
        "source": "STATE_MACHINE",
        "level": "success",
        "message": selection.get("message", "Device Selected"),
    })

async def on_sm_state_reset(reset_info):
    await broadcast("state_reset", reset_info)
    await broadcast("log", {
        "source": "STATE_MACHINE",
        "level": "warn",
        "message": reset_info.get("message", "State reset"),
    })

async def on_sm_actuator_command(cmd):
    await broadcast("actuator_updated", cmd)
    await broadcast("log", {
        "source": "ACTUATOR",
        "level": "success",
        "message": f"Actuator Action: {cmd.get('device', '').upper()} is now {cmd.get('state')} (Triggered by '{cmd.get('triggerAction')}')",
    })
    # Forward to ESP32 Hardware
    await esp32_connector.send_command(cmd.get("device"), cmd.get("state"))

async def on_sm_command_filtered(filter_info):
    await broadcast("command_filtered", filter_info)

async def on_sm_single_fire_suppressed(suppress_info):
    await broadcast("single_fire_suppressed", suppress_info)

async def on_sm_combo_window_started(combo_info):
    await broadcast("combo_window_started", combo_info)
    await broadcast("log", {
        "source": "COMBO_ENGINE",
        "level": "info",
        "message": f"Combo Window Started: First Action [{combo_info.get('firstAction', '').upper()}]. Waiting for PULL (Back / Cancel).",
    })

async def on_sm_combo_triggered(combo_event):
    await broadcast("combo_triggered", combo_event)
    await broadcast("log", {
        "source": "COMBO_ENGINE",
        "level": "success",
        "message": combo_event.get("message", "Combination Executed!"),
    })

async def on_sm_combo_window_expired(expiry_info):
    await broadcast("combo_window_expired", expiry_info)

async def on_sm_framing_window_started(framing_info):
    await broadcast("framing_window_started", framing_info)
    await broadcast("log", {
        "source": "TEMPORAL_FRAMING",
        "level": "info",
        "message": f"Temporal Framing: Holding command for {framing_info.get('windowMs', 4000)/1000:.1f}s. Executes once window finishes.",
    })

async def on_sm_framing_executed(executed_info):
    await broadcast("framing_executed", executed_info)
    await broadcast("log", {
        "source": "TEMPORAL_FRAMING",
        "level": "success",
        "message": f"Temporal Framing Completed: Executed action [{executed_info.get('kind')}] on [{executed_info.get('device', '').upper()}].",
    })

async def on_sm_framing_cancelled(cancelled_info):
    await broadcast("framing_cancelled", cancelled_info)
    await broadcast("log", {
        "source": "TEMPORAL_FRAMING",
        "level": "warn",
        "message": cancelled_info.get("message", "Framing Window Cancelled."),
    })

async def on_sm_info(info):
    await broadcast("log", {
        "source": "STATE_MACHINE",
        "level": "info",
        "message": info.get("message", ""),
    })

state_machine.on("telemetry", on_sm_telemetry)
state_machine.on("transition", on_sm_transition)
state_machine.on("device_selected", on_sm_device_selected)
state_machine.on("state_reset", on_sm_state_reset)
state_machine.on("actuator_command", on_sm_actuator_command)
state_machine.on("command_filtered", on_sm_command_filtered)
state_machine.on("single_fire_suppressed", on_sm_single_fire_suppressed)
state_machine.on("combo_window_started", on_sm_combo_window_started)
state_machine.on("combo_triggered", on_sm_combo_triggered)
state_machine.on("combo_window_expired", on_sm_combo_window_expired)
state_machine.on("framing_window_started", on_sm_framing_window_started)
state_machine.on("framing_executed", on_sm_framing_executed)
state_machine.on("framing_cancelled", on_sm_framing_cancelled)
state_machine.on("info", on_sm_info)


# 3. ESP32 Connector Events
async def on_esp32_log(log_entry):
    await broadcast("log", {"source": "ESP32", **log_entry})

async def on_esp32_status_change(status):
    await broadcast("esp32_status", esp32_connector.get_config())

async def on_esp32_states_sync(states):
    for k, v in states.items():
        if k in state_machine.device_states:
            state_machine.device_states[k] = v
    await broadcast("state_transition", state_machine.get_full_state())

esp32_connector.on("log", on_esp32_log)
esp32_connector.on("status_change", on_esp32_status_change)
esp32_connector.on("states_sync", on_esp32_states_sync)


# ----------------------------------------------------
# Lifespan Management
# ----------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    if esp32_connector.mode == "serial":
        esp32_connector.init_serial()
    # Auto-connect to Emotiv Cortex if credentials or service are available
    asyncio.create_task(cortex_bridge.connect())
    yield
    esp32_connector.disconnect_serial()
    await cortex_bridge.disconnect()


app = FastAPI(title="Emotiv BCI + ESP32 Master IoT Hub", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------------------------------
# WebSocket Endpoints
# ----------------------------------------------------
@app.websocket("/ws")
async def websocket_dashboard_endpoint(websocket: WebSocket):
    await websocket.accept()
    dashboard_clients.add(websocket)

    # Send Initial Snapshot
    initial_snapshot = {
        "stateMachine": state_machine.get_full_state(),
        "cortex": cortex_bridge.get_status(),
        "esp32": esp32_connector.get_config(),
    }
    await websocket.send_text(json.dumps({"type": "init_snapshot", "payload": initial_snapshot}))

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
                msg_type = data.get("type")

                if msg_type == "simulate_command":
                    action = data.get("action")
                    power = float(data.get("power", 1.0))
                    state_machine.process_mental_command(action, power, True)

                elif msg_type == "cancel_framing":
                    state_machine.cancel_framing_window("manual_user_cancel")

                elif msg_type == "manual_override":
                    device = data.get("device")
                    state = data.get("state")
                    state_machine.manual_override(device, state)

                elif msg_type == "return_selection":
                    state_machine.return_to_selection_mode("manual_request")

                elif msg_type == "update_config":
                    cfg = data.get("config") or data.get("stateMachineConfig") or data
                    if cfg and isinstance(cfg, dict):
                        state_machine.update_config(cfg)

            except Exception as e:
                print(f"[WS Error]: {e}")
    except WebSocketDisconnect:
        dashboard_clients.discard(websocket)


@app.websocket("/esp32")
async def websocket_esp32_endpoint(websocket: WebSocket):
    await websocket.accept()
    esp32_connector.register_websocket_client(websocket)

    try:
        while True:
            raw = await websocket.receive_text()
            esp32_connector.handle_ws_message(raw)
    except WebSocketDisconnect:
        esp32_connector.unregister_websocket_client()


# ----------------------------------------------------
# REST API Endpoints
# ----------------------------------------------------
@app.get("/api/status")
async def get_status():
    return {
        "stateMachine": state_machine.get_full_state(),
        "cortex": cortex_bridge.get_status(),
        "esp32": esp32_connector.get_config(),
    }


@app.get("/api/esp32/ports")
async def get_esp32_ports():
    ports = esp32_connector.get_available_ports()
    return {"success": True, "ports": ports}


@app.post("/api/esp32/connect")
async def connect_esp32(request: Request):
    try:
        body = await request.json()
        if body:
            esp32_connector.update_config(body)
    except Exception:
        pass

    if esp32_connector.mode == "serial":
        ok = esp32_connector.init_serial()
        return {"success": ok, "config": esp32_connector.get_config()}
    else:
        res = await esp32_connector.ping()
        return {"success": esp32_connector.is_connected, "ping": res, "config": esp32_connector.get_config()}


@app.post("/api/esp32/disconnect")
async def disconnect_esp32():
    esp32_connector.disconnect_serial()
    return {"success": True, "config": esp32_connector.get_config()}


@app.post("/api/esp32/ping")
async def ping_esp32():
    result = await esp32_connector.ping()
    return result


@app.post("/api/simulate")
async def simulate_command(request: Request):
    body = await request.json()
    action = body.get("action")
    if not action:
        return JSONResponse(status_code=400, content={"error": "Action parameter is required."})

    power = float(body.get("power", 1.0))
    result = state_machine.process_mental_command(action, power, True)
    return {
        "success": True,
        "result": result,
        "currentState": state_machine.get_full_state(),
    }


@app.post("/api/framing/cancel")
async def cancel_framing():
    state_machine.cancel_framing_window("api_cancel")
    return {"success": True, "message": "Framing window cancelled."}


@app.post("/api/override")
async def override_device(request: Request):
    body = await request.json()
    device = body.get("device")
    state = body.get("state")
    if not device or not state:
        return JSONResponse(status_code=400, content={"error": "Device and state are required."})

    result = state_machine.manual_override(device, state)
    return {
        "success": True,
        "result": result,
        "deviceStates": state_machine.device_states,
    }


@app.post("/api/selection-mode")
async def return_selection_mode():
    state_machine.return_to_selection_mode("api_request")
    return {"success": True, "state": state_machine.get_full_state()}


@app.post("/api/config")
async def update_config(request: Request):
    body = await request.json()
    cortex_cfg = body.get("cortex")
    sm_cfg = body.get("stateMachineConfig")
    esp32_cfg = body.get("esp32")

    if cortex_cfg:
        cortex_bridge.set_credentials(cortex_cfg)
    if sm_cfg:
        state_machine.update_config(sm_cfg)
    elif any(k in body for k in ("framingWindowMs", "framing_window_ms", "powerThreshold", "debounceMs", "comboWindowMs")):
        state_machine.update_config(body)
    if esp32_cfg:
        esp32_connector.update_config(esp32_cfg)

    await broadcast("cortex_status", cortex_bridge.get_status())
    await broadcast("esp32_status", esp32_connector.get_config())

    return {
        "success": True,
        "cortex": cortex_bridge.get_status(),
        "stateMachine": state_machine.get_full_state(),
        "esp32": esp32_connector.get_config(),
    }


@app.post("/api/cortex/connect")
async def connect_cortex(request: Request):
    try:
        body = await request.json()
        if body:
            if body.get("clientId") or body.get("clientSecret"):
                cortex_bridge.set_credentials(body)
                # Persist credentials to .env so they survive restarts
                _persist_env_credentials(
                    body.get("clientId", ""),
                    body.get("clientSecret", ""),
                )
    except Exception:
        pass

    asyncio.create_task(cortex_bridge.connect())
    return {"success": True, "message": "Initiated connection to Emotiv Cortex on wss://localhost:6868."}


def _persist_env_credentials(client_id: str, client_secret: str):
    """Write CORTEX_CLIENT_ID and CORTEX_CLIENT_SECRET back to .env file."""
    try:
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        if not os.path.exists(env_path):
            return
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        new_lines = []
        updated = {"CORTEX_CLIENT_ID": False, "CORTEX_CLIENT_SECRET": False}
        for line in lines:
            if line.startswith("CORTEX_CLIENT_ID=") and client_id:
                new_lines.append(f"CORTEX_CLIENT_ID={client_id}\n")
                updated["CORTEX_CLIENT_ID"] = True
            elif line.startswith("CORTEX_CLIENT_SECRET=") and client_secret:
                new_lines.append(f"CORTEX_CLIENT_SECRET={client_secret}\n")
                updated["CORTEX_CLIENT_SECRET"] = True
            else:
                new_lines.append(line)
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception as e:
        print(f"[WARN] Could not persist credentials to .env: {e}")


@app.post("/api/cortex/disconnect")
async def disconnect_cortex():
    await cortex_bridge.disconnect()
    return {"success": True, "message": "Disconnected from Emotiv Cortex."}


@app.get("/api/cortex/profiles")
async def get_cortex_profiles():
    profiles = await cortex_bridge.query_and_load_profiles()
    return {"success": True, "profiles": profiles, "activeProfile": cortex_bridge.active_profile}


@app.post("/api/cortex/load-profile")
async def load_cortex_profile(request: Request):
    body = await request.json()
    profile_name = body.get("profile")
    if not profile_name:
        return JSONResponse(status_code=400, content={"error": "Profile name is required."})

    ok = await cortex_bridge.load_profile(profile_name)
    return {"success": ok, "activeProfile": cortex_bridge.active_profile}


@app.post("/api/cortex/diagnose")
async def diagnose_cortex():
    """Send a raw getCortexInfo + queryHeadsets to Cortex and return the result."""
    import ssl as _ssl
    import json as _json
    result = {"cortex_url": "wss://localhost:6868", "steps": []}
    try:
        ssl_ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = _ssl.CERT_NONE
        async with websockets.connect("wss://localhost:6868", ssl=ssl_ctx) as ws:
            async def _req(method, params=None):
                payload = {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": 1}
                await ws.send(_json.dumps(payload))
                raw = await asyncio.wait_for(ws.recv(), timeout=8.0)
                return _json.loads(raw)

            info = await _req("getCortexInfo")
            result["steps"].append({"method": "getCortexInfo", "response": info})

            headsets = await _req("queryHeadsets")
            result["steps"].append({"method": "queryHeadsets", "response": headsets})

            if cortex_bridge.client_id and cortex_bridge.client_secret:
                access = await _req("requestAccess", {
                    "clientId": cortex_bridge.client_id,
                    "clientSecret": cortex_bridge.client_secret,
                })
                result["steps"].append({"method": "requestAccess", "response": access})

        result["success"] = True
    except Exception as e:
        result["success"] = False
        result["error"] = str(e)
    return result


# ----------------------------------------------------
# Static Files / Frontend UI
# ----------------------------------------------------
public_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public")
if os.path.exists(public_dir):
    app.mount("/", StaticFiles(directory=public_dir, html=True), name="public")


if __name__ == "__main__":
    print("=" * 60)
    print("🧠 Emotiv Cortex BCI Engine & Neural Suite (Python FastAPI)")
    print(f"🌐 Emotiv Web Dashboard: http://localhost:{PORT}")
    print(f"⚡ BCI WebSocket Stream: ws://localhost:{PORT}/ws")
    print("🔗 SynaptiMesh Master:   http://127.0.0.1:8000")
    print("=" * 60)
    uvicorn.run("server:app", host=HOST, port=PORT, reload=False)
