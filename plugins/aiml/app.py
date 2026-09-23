"""
SynaptiMesh — Unified Dashboard (Experimental)
===============================================
Single route /dashboard that controls both Mobile (MQTT) and Desktop (Selenium)
through one FSM pipeline. Execution stays platform-specific, UI is common.

Architecture:
  BCI / Test -> receive_cortex_command -> 4s window -> FSM (single source) -> Mapper -> Router -> Mobile/Desktop

Do NOT modify legacy mappings. Use 4s window, 0.35 threshold, 2s debounce as-is.
BCI buttons use ONE path: POST /api/bci/command -> receive_cortex_command
"""
import atexit
import os, sys, threading, logging, warnings, time, subprocess
from pathlib import Path
from dotenv import load_dotenv
warnings.filterwarnings("ignore", category=DeprecationWarning)
load_dotenv()

_WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, _WORKSPACE_ROOT)

BASE_DIR = Path(__file__).resolve().parent
MOBILE_PLUGIN_DIR = BASE_DIR / "mobile_dashboard" / "mobile_plugin"
DESKTOP_MODULES_DIR = BASE_DIR / "desktop_dashboard" / "desktop_modules"
DASHBOARD_TEMPLATE_DIR = BASE_DIR / "dashboard" / "templates"
MASTER_TEMPLATE_DIR = BASE_DIR / "master_dashboard" / "templates"

for p in [str(BASE_DIR), str(DESKTOP_MODULES_DIR), str(MOBILE_PLUGIN_DIR)]:
    if p not in sys.path:
        sys.path.append(p)

from flask import Flask, render_template, send_from_directory, request, jsonify, redirect
from flask_socketio import SocketIO
from jinja2 import ChoiceLoader, FileSystemLoader
try:
    from uart_transmitter import uart_transmitter
    from command_system.command_mapper import canonical_action_for
except ImportError:
    from plugins.aiml.uart_transmitter import uart_transmitter
    from plugins.aiml.command_system.command_mapper import canonical_action_for


def _observe_uart_action(command, device=None):
    """Observe existing direct-device commands without changing their dispatch."""
    action = canonical_action_for(command, device) if device else command
    if action:
        uart_transmitter.send_action(action)


atexit.register(uart_transmitter.shutdown)

MOBILE_NAMESPACE = "/mobile"
DESKTOP_NAMESPACE = "/desktop"
DASHBOARD_NAMESPACE = "/dashboard"

class NamespacedSocketIO:
    def __init__(self, socketio, namespace):
        self._socketio=socketio; self._namespace=namespace
    def emit(self, event, *args, **kwargs):
        kwargs["namespace"]=self._namespace
        return self._socketio.emit(event,*args,**kwargs)
    def on(self, event, **kwargs):
        kwargs.setdefault("namespace", self._namespace)
        return self._socketio.on(event,**kwargs)

app = Flask(__name__,
    template_folder=str(DASHBOARD_TEMPLATE_DIR),
    static_folder=str(BASE_DIR / "dashboard" / "static"))
app.config["SECRET_KEY"]="unified_dashboard_secret"
app.config["TEMPLATES_AUTO_RELOAD"]=True
app.config["SEND_FILE_MAX_AGE_DEFAULT"]=0

@app.after_request
def _no_cache(r):
    r.headers["Cache-Control"]="no-store, no-cache, must-revalidate, max-age=0"
    r.headers["Pragma"]="no-cache"
    return r

# Jinja loader includes dashboard + master + mobile/desktop for legacy templates if needed
app.jinja_loader = ChoiceLoader([
    FileSystemLoader(str(DASHBOARD_TEMPLATE_DIR)),
    FileSystemLoader(str(MASTER_TEMPLATE_DIR)),
    FileSystemLoader(str(BASE_DIR / "mobile_dashboard" / "templates")),
    FileSystemLoader(str(BASE_DIR / "desktop_dashboard" / "templates")),
])

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# --- Mobile backend ---
try:
    from plugins.aiml.mobile_dashboard.mobile_plugin.config.config import DEBUG_MODE
except Exception:
    try:
        from config.config import DEBUG_MODE
    except Exception:
        DEBUG_MODE = False

try:
    from plugins.aiml.mobile_dashboard.mobile_plugin.services.logger_service import setup_logger
    from plugins.aiml.mobile_dashboard.mobile_plugin.services.mqtt_service import MQTTService
    from plugins.aiml.mobile_dashboard.mobile_plugin.scheduler.pipeline import PipelineScheduler
    from plugins.aiml.mobile_dashboard.mobile_plugin.events.socket_events import register_socket_events
    mobile_sio = NamespacedSocketIO(socketio, MOBILE_NAMESPACE)
    setup_logger(mobile_sio)
    mqtt_service = MQTTService(mobile_sio, pipeline_scheduler=None)
    pipeline_scheduler = PipelineScheduler(mqtt_service, mobile_sio)
    mqtt_service.pipeline_scheduler = pipeline_scheduler
    register_socket_events(mobile_sio, mqtt_service, pipeline_scheduler, action_observer=_observe_uart_action)
    MOBILE_AVAILABLE=True
except Exception as e:
    logging.getLogger().warning(f"[UNIFIED] Mobile backend not available: {e}")
    mqtt_service=None; pipeline_scheduler=None; MOBILE_AVAILABLE=False

# --- Desktop backend ---
try:
    try:
        from plugins.aiml.desktop_controller import register_desktop_backend
    except ImportError:
        from desktop_controller import register_desktop_backend
    desktop_controller, desktop_status_poller = register_desktop_backend(
        app, socketio, namespace=DESKTOP_NAMESPACE, action_observer=_observe_uart_action
    )
    DESKTOP_AVAILABLE=True
except Exception as e:
    logging.getLogger().warning(f"[UNIFIED] Desktop backend not available: {e}")
    desktop_controller=None; desktop_status_poller=lambda: None; DESKTOP_AVAILABLE=False

# --- Backend registry ---
from backend.device_manager import device_manager
from backend.state_manager import state_manager
from backend.command_router import command_router
if MOBILE_AVAILABLE and mqtt_service:
    device_manager.register_mobile(mqtt_service, pipeline_scheduler)
    state_manager.register_device("mobile")
if DESKTOP_AVAILABLE and desktop_controller:
    device_manager.register_desktop(desktop_controller)
    state_manager.register_device("desktop")

# --- FSM layer (single source of truth) ---
from command_system.command_mapper import CommandMapper
from command_system.fsm_controller import FSMController
from command_system.cortex_bridge import create_cortex_bridge

dashboard_sio = NamespacedSocketIO(socketio, DASHBOARD_NAMESPACE)
fsm_mapper = CommandMapper(command_router=command_router, dry_run=False)
fsm_controller = FSMController(mapper=fsm_mapper, dry_run=False, combo_timeout=4.0)

# --- BCI Recording & Replay (additive, optional) ---
from command_system.bci_recorder import BCIRecorder
from command_system.bci_replay import BCIReplayEngine
BCI_DATA_RAW_DIR = BASE_DIR / "bci_data" / "raw"
BCI_DATA_REPLAY_DIR = BASE_DIR / "bci_data" / "replay"
BCI_DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
BCI_DATA_REPLAY_DIR.mkdir(parents=True, exist_ok=True)
_auto_record = os.environ.get("BCI_RECORDING", "").lower() in ("1", "true", "on", "yes")
bci_recorder = BCIRecorder(base_dir=BCI_DATA_RAW_DIR, auto_start=_auto_record)
bci_replay_engine = BCIReplayEngine(fsm_controller=fsm_controller, base_dir=BCI_DATA_RAW_DIR)
if _auto_record:
    logging.getLogger().info(f"[RECORDER] auto-started via BCI_RECORDING env -> {bci_recorder.get_status()}")

# --- JioSaavn auto-launch state (secondary, not dominant) ---
from command_system.states import OPEN_MOBILE_DASHBOARD, OPEN_DESKTOP_DASHBOARD
jiosaavn_status = {
    "mobile": {"status": "idle", "message": "Idle"},
    "desktop": {"status": "idle", "message": "Idle"},
    "overall": "idle"
}
_last_jiosaavn_launch = {"device": None, "ts": 0.0}
_jiosaavn_lock = threading.Lock()

def _set_jiosaavn_status(device, status, message):
    with _jiosaavn_lock:
        jiosaavn_status[device]["status"] = status
        jiosaavn_status[device]["message"] = message
        jiosaavn_status["overall"] = status
    socketio.emit("jiosaavn_status", {"device": device, "status": status, "message": message, "jiosaavn": dict(jiosaavn_status)}, namespace=DASHBOARD_NAMESPACE)
    logging.getLogger().info(f"[JIOSAAVN] {device} -> {status}: {message}")

def _launch_jiosaavn_async(device):
    """Reuse existing launch mechanisms. Never crashes FSM."""
    try:
        _set_jiosaavn_status(device, "opening", "Opening..." if device=="desktop" else "Launching...")
        if device == "mobile":
            logging.getLogger().info("[FSM] Entered MOBILE_DASHBOARD_ACTIVE")
            logging.getLogger().info("[JIOSAAVN] Launching Mobile JioSaavn")
            # Existing Android mechanism: publish Right_jiosaavn via MQTT router
            result = command_router.route("Right_jiosaavn", target="mobile")
            dispatched = result.get("dispatched", False)
            if dispatched:
                _set_jiosaavn_status(device, "ready", "Launch requested")
                logging.getLogger().info("[JIOSAAVN] Mobile JioSaavn launch requested")
            else:
                _set_jiosaavn_status(device, "failed", result.get("reason") or "Launch failed")
                logging.getLogger().warning(f"[JIOSAAVN] Failed to launch Mobile JioSaavn: {result}")
        else:
            logging.getLogger().info("[FSM] Entered DESKTOP_DASHBOARD_ACTIVE")
            logging.getLogger().info("[JIOSAAVN] Desktop JioSaavn open forwarded to secondary device (UART); local launch skipped")
            if uart_transmitter and uart_transmitter.enabled:
                uart_transmitter.send_action("OPEN_DESKTOP_DASHBOARD")
            _set_jiosaavn_status(device, "ready", "Forwarded")
    except Exception as e:
        logging.getLogger().error(f"[JIOSAAVN] Failed to launch {device} JioSaavn: {e}")
        _set_jiosaavn_status(device, "failed", str(e))

def _maybe_auto_launch(result):
    """Trigger only on actual dashboard activation, with duplicate guard."""
    action = result.get("action")
    if action not in (OPEN_MOBILE_DASHBOARD, OPEN_DESKTOP_DASHBOARD):
        return
    device = "mobile" if action == OPEN_MOBILE_DASHBOARD else "desktop"
    now = time.time()
    # Duplicate guard: dedup already suppresses repeated pushes, but add 3s cooldown per device
    with _jiosaavn_lock:
        if _last_jiosaavn_launch["device"] == device and (now - _last_jiosaavn_launch["ts"]) < 3.0:
            logging.getLogger().info(f"[JIOSAAVN] Duplicate launch suppressed for {device}")
            return
        _last_jiosaavn_launch["device"] = device
        _last_jiosaavn_launch["ts"] = now
    threading.Thread(target=_launch_jiosaavn_async, args=(device,), daemon=True).start()

def _get_current_volume():
    """Return actual known volume. Desktop system volume is source of truth; fallback 50. Mobile volume via MQTT media_update not reliably absolute, so desktop is used."""
    try:
        if DESKTOP_AVAILABLE and desktop_controller is not None:
            st = desktop_controller.get_status()
            v = st.get("volume")
            if v is not None:
                return int(max(0, min(100, int(float(v)))))
    except Exception:
        pass
    return 50

_volume_state = {"volume": _get_current_volume(), "source": "desktop" if DESKTOP_AVAILABLE else "fallback"}

def _emit_volume(force=False):
    vol = _get_current_volume()
    if force or vol != _volume_state["volume"]:
        _volume_state["volume"] = vol
        socketio.emit("volume_update", {"volume": vol, "source": _volume_state["source"]}, namespace=DASHBOARD_NAMESPACE)
        logging.getLogger().info(f"[VOLUME] {vol}% (source={_volume_state['source']})")

def _volume_poller():
    """Poll desktop volume every 1s and emit to dashboard if changed."""
    last = None
    while True:
        try:
            vol = _get_current_volume()
            if vol != last:
                last = vol
                _volume_state["volume"] = vol
                socketio.emit("volume_update", {"volume": vol, "source": "desktop"}, namespace=DASHBOARD_NAMESPACE)
        except Exception:
            pass
        socketio.sleep(1.0)

def _emit_state():
    socketio.emit("fsm_state_update", fsm_controller.get_state(), namespace=DASHBOARD_NAMESPACE)
    # also push jiosaavn status so header stays in sync
    socketio.emit("jiosaavn_status", {"jiosaavn": dict(jiosaavn_status)}, namespace=DASHBOARD_NAMESPACE)
    # also push window duration + volume so config UI stays in sync
    try:
        socketio.emit("config_update", {"command_window_seconds": fsm_controller.get_window_duration(), "volume": _volume_state["volume"]}, namespace=DASHBOARD_NAMESPACE)
    except Exception:
        pass

def _fsm_result_callback(result):
    # enrich with target_device for UI, ensure level present
    result["target_device"]=fsm_controller.target_device
    socketio.emit("fsm_command_result", result, namespace=DASHBOARD_NAMESPACE)
    _emit_state()
    _maybe_auto_launch(result)
    # After volume command, push updated volume (system volume changed via PlayerEngine)
    if result.get("action") in ("volume_up", "volume_down"):
        # give OS a moment to settle (especially macOS osascript)
        def _delayed_vol():
            socketio.sleep(0.3)
            _emit_volume(force=True)
        socketio.start_background_task(_delayed_vol)

fsm_controller.set_result_callback(_fsm_result_callback)

# wrap for window flush path: ensure state also emitted (fsm_controller already calls callback after flush for doubles)
_orig_cb = _fsm_result_callback
def _fsm_result_with_state(result):
    _orig_cb(result)
    # Device actions are already forwarded through command_mapper / command_router via UART
fsm_controller.set_result_callback(_fsm_result_with_state)

# --- Cortex bridge (optional, uses FSM's internal 4s window) ---
CORTEX_CLIENT_ID=os.environ.get("CORTEX_CLIENT_ID","")
CORTEX_CLIENT_SECRET=os.environ.get("CORTEX_CLIENT_SECRET","")
CORTEX_ENABLED=bool(CORTEX_CLIENT_ID and CORTEX_CLIENT_SECRET)
cortex_bridge=None
if CORTEX_ENABLED:
    def _cortex_cb(command, power, timestamp=None):
        logging.getLogger().info(f"[CORTEX] -> FSM: {command} power={power:.3f} ts={timestamp}")
        # Additive recording: observe raw Cortex event before FSM processing (never deduplicates)
        try:
            if bci_recorder.is_recording:
                bci_recorder.record(command, power, timestamp=timestamp, extra={"source": "cortex"})
        except Exception as e:
            logging.getLogger().warning(f"[RECORDER] cortex record failed: {e}")
        fsm_controller.receive_cortex_command(command, power, timestamp=timestamp)
    cortex_bridge=create_cortex_bridge(CORTEX_CLIENT_ID, CORTEX_CLIENT_SECRET, _cortex_cb, logging.getLogger())
    logging.getLogger().info("[UNIFIED] Cortex bridge initialized (FSM owns 4s window)")
else:
    logging.getLogger().warning("[UNIFIED] Cortex disabled (no credentials) - using test buttons")

# --- Socket handlers for unified dashboard (server->client only; no bci_command emit to avoid duplicate) ---
@socketio.on("connect", namespace=DASHBOARD_NAMESPACE)
def handle_dashboard_connect():
    # push current state on connect
    socketio.emit("fsm_state_update", fsm_controller.get_state(), namespace=DASHBOARD_NAMESPACE)
    socketio.emit("jiosaavn_status", {"jiosaavn": dict(jiosaavn_status)}, namespace=DASHBOARD_NAMESPACE)
    try:
        socketio.emit("bci_recording_status", bci_recorder.get_status(), namespace=DASHBOARD_NAMESPACE)
        socketio.emit("bci_replay_status", bci_replay_engine.get_status(), namespace=DASHBOARD_NAMESPACE)
        socketio.emit("volume_update", {"volume": _get_current_volume(), "source": _volume_state.get("source","desktop")}, namespace=DASHBOARD_NAMESPACE)
        socketio.emit("config_update", {"command_window_seconds": fsm_controller.get_window_duration()}, namespace=DASHBOARD_NAMESPACE)
    except Exception:
        pass

# --- REST API ---

@app.route("/")
def root():
    return redirect("/dashboard")

@app.route("/dashboard")
def dashboard():
    state_manager.set_active_dashboard("dashboard")
    # Start at the Sub-Master Hub (Level 2): reset FSM + JioSaavn status on open
    # so a leftover state (e.g. DESKTOP_DASHBOARD_ACTIVE) is not shown to the user.
    fsm_controller.reset()
    with _jiosaavn_lock:
        jiosaavn_status["mobile"] = {"status": "idle", "message": "Idle"}
        jiosaavn_status["desktop"] = {"status": "idle", "message": "Idle"}
        jiosaavn_status["overall"] = "idle"
        _last_jiosaavn_launch["device"] = None
        _last_jiosaavn_launch["ts"] = 0.0
    return render_template("dashboard.html")

@app.route("/api/fsm/state", methods=["GET"])
def fsm_state():
    return jsonify({"status":"success","fsm":fsm_controller.get_state(), "jiosaavn": jiosaavn_status})

@app.route("/api/jiosaavn/status", methods=["GET"])
def jiosaavn_status_api():
    return jsonify({"status":"success","jiosaavn": jiosaavn_status})

@app.route("/api/fsm/reset", methods=["POST"])
def fsm_reset():
    fsm_controller.reset()
    with _jiosaavn_lock:
        jiosaavn_status["mobile"] = {"status": "idle", "message": "Idle"}
        jiosaavn_status["desktop"] = {"status": "idle", "message": "Idle"}
        jiosaavn_status["overall"] = "idle"
        _last_jiosaavn_launch["device"] = None
        _last_jiosaavn_launch["ts"] = 0.0
    socketio.emit("jiosaavn_status", {"jiosaavn": dict(jiosaavn_status)}, namespace=DASHBOARD_NAMESPACE)
    _emit_state()
    return jsonify({"status":"success","fsm":fsm_controller.get_state(), "jiosaavn": jiosaavn_status})

@app.route("/api/fsm/command", methods=["POST"])
def fsm_direct():
    """Direct process_command (no window) - for debugging only. BCI path uses /api/bci/command."""
    data=request.json or {}
    raw=data.get("command") or data.get("raw_command")
    conf=float(data.get("confidence",1.0))
    if not raw: return jsonify({"status":"error","message":"Missing command"}),400
    result=fsm_controller.process_command(raw, confidence=conf)
    _emit_state()
    socketio.emit("fsm_command_result", result, namespace=DASHBOARD_NAMESPACE)
    return jsonify({"status":"success","result":result,"fsm":fsm_controller.get_state()})

@app.route("/api/bci/command", methods=["POST"])
def bci_command():
    """Single BCI input path: receive_cortex_command -> 4s window -> FSM -> mapper -> router.
    For ordered doubles, frontend does two sequential POSTs (RIGHT then PUSH etc.)
    """
    data=request.json or {}
    raw=data.get("command") or data.get("raw_command")
    conf=float(data.get("confidence",0.95))
    if not raw: return jsonify({"status":"error","message":"Missing command"}),400
    # Additive recording: capture raw event exactly as received (no dedup, no FSM logic) before processing
    try:
        if bci_recorder.is_recording:
            # preserve original timestamp if provided, else generate ISO now
            ts_in = data.get("timestamp")
            bci_recorder.record(raw, conf, timestamp=ts_in if ts_in else time.time(), extra={"source": "api_bci_command"})
    except Exception as e:
        logging.getLogger().warning(f"[RECORDER] api record failed: {e}")
    accepted=fsm_controller.receive_cortex_command(raw, conf)
    # result will be emitted via callback after window (single=after 4s, double=immediate if different)
    return jsonify({"status":"success","accepted":accepted,"command":raw,"confidence":conf,"fsm":fsm_controller.get_state()})

@app.route("/api/fsm/back", methods=["POST"])
def fsm_back():
    data=request.json or {}
    lvl=data.get("level")
    # Map unified back buttons: back L2 or L1
    # Use FSM navigate logic
    result=fsm_controller.navigate_back()
    # If specific level requested and not matching, adjust
    if lvl==2 and fsm_controller.current_state!="SUB_MASTER_DASHBOARD":
        # PUSH+RIGHT path would be via window normally; here direct back to Level 2
        from command_system.states import SUB_MASTER_DASHBOARD
        fsm_controller.target_device=None; fsm_controller.dashboard_open=False
        fsm_controller.current_state=SUB_MASTER_DASHBOARD
        result={"action":"back_to_level_2","new_state":SUB_MASTER_DASHBOARD,"message":"Returned to Level 2 (Unified back)"}
    _emit_state()
    return jsonify({"status":"success","result":result,"fsm":fsm_controller.get_state()})

@app.route("/api/action", methods=["POST"])
def handle_manual_action():
    """Manual fallback (mirrors desktop /api/action) - direct dispatch without FSM window."""
    data=request.json or {}
    action=data.get("action")
    query=data.get("query")
    # Route to current target or desktop fallback
    target=fsm_controller.target_device or "desktop"
    result=None
    if target=="mobile" and MOBILE_AVAILABLE:
        from backend.command_router import command_router as cr
        # Map action to mobile command
        mobile_map={"Play / Pause":"Right_Play_Pause","Next Track":"Right_Next_Song","Previous Track":"Right_Previous_Song","Volume Up":"Right_Volume_Up","Volume Down":"Right_Volume_Down","Search Album/Playlist":"Right_Search_Playlist","Search":"Right_Search_Playlist"}
        cmd=mobile_map.get(action, action)
        result=cr.route(cmd, target="mobile")
    elif desktop_controller:
        result=desktop_controller.execute_action(action, query=query)
        _observe_uart_action(action, "desktop")
        status=desktop_controller.get_status()
        socketio.emit("status_update", status, namespace=DESKTOP_NAMESPACE)
    else:
        result="No backend available"
    return jsonify({"status":"success","message":str(result),"target":target})

@app.route("/api/config", methods=["GET", "POST"])
def handle_unified_config():
    # GET: return desktop config + unified command_window_seconds + volume
    if request.method == "GET":
        base = {}
        if desktop_controller:
            try:
                base = desktop_controller.get_config() or {}
            except Exception:
                base = {}
        base["command_window_seconds"] = fsm_controller.get_window_duration()
        base["volume"] = _get_current_volume()
        return jsonify({"status":"success","config": base})
    # POST: update desktop config and/or window
    data = request.json or {}
    # handle window config if present
    win = data.get("command_window_seconds")
    if win is None:
        win = data.get("window_duration")
    if win is None:
        win = data.get("window")
    updated = {}
    if win is not None:
        try:
            new_val = fsm_controller.set_window_duration(float(win))
            updated["command_window_seconds"] = new_val
            # emit to dashboard
            socketio.emit("config_update", {"command_window_seconds": new_val}, namespace=DASHBOARD_NAMESPACE)
            socketio.emit("volume_update", {"volume": _volume_state["volume"]}, namespace=DASHBOARD_NAMESPACE)
            logging.getLogger().info(f"[CONFIG] command_window_seconds set to {new_val}s via /api/config")
        except Exception as e:
            return jsonify({"status":"error","message":str(e)}), 400
    if desktop_controller:
        confidence = data.get("confidence_threshold")
        cooldown = data.get("volume_cooldown")
        headless = data.get("headless")
        if any(v is not None for v in (confidence, cooldown, headless)):
            try:
                cfg = desktop_controller.update_config(
                    confidence_threshold=confidence,
                    volume_cooldown=cooldown,
                    headless=headless,
                )
                # merge
                base = cfg
                base["command_window_seconds"] = fsm_controller.get_window_duration()
                base["volume"] = _get_current_volume()
                socketio.emit("config_update", base, namespace=DASHBOARD_NAMESPACE)
                return jsonify({"status":"success","config": base})
            except Exception as e:
                return jsonify({"status":"error","message":str(e)}),400
        # if only window was updated, return merged
        if updated:
            base = desktop_controller.get_config() or {}
            base.update(updated)
            base["volume"] = _get_current_volume()
            return jsonify({"status":"success","config": base})
    # no desktop controller but window updated
    if updated:
        return jsonify({"status":"success","config": {"command_window_seconds": updated["command_window_seconds"], "volume": _get_current_volume()}})
    return jsonify({"status":"success","config": {"command_window_seconds": fsm_controller.get_window_duration(), "volume": _get_current_volume()}})

# Legacy helper for direct volume endpoint (desktop path uses /api/volume)
@app.route("/api/volume", methods=["GET", "POST"])
def handle_volume():
    if request.method == "GET":
        return jsonify({"status":"success","volume": _get_current_volume(), "source": _volume_state.get("source","desktop")})
    data = request.json or {}
    vol = data.get("volume")
    if vol is None:
        vol = data.get("value")
    if vol is None:
        return jsonify({"status":"error","message":"Missing volume (0-100)"}),400
    try:
        vol_int = int(max(0, min(100, int(float(vol)))))
        # Use set_system_master_volume via desktop modules if available
        actual = vol_int
        try:
            if DESKTOP_AVAILABLE:
                from os_operations import set_system_master_volume as _set_vol
                actual = int(_set_vol(vol_int))
                # also update controller cached
                try:
                    desktop_controller.current_volume = float(actual)
                except Exception:
                    pass
            else:
                # fallback: just store
                _volume_state["volume"] = vol_int
                actual = vol_int
        except Exception as e:
            logging.getLogger().warning(f"[VOLUME] set failed: {e}")
            actual = vol_int
            _volume_state["volume"] = actual
        _volume_state["volume"] = actual
        socketio.emit("volume_update", {"volume": actual, "source": "manual"}, namespace=DASHBOARD_NAMESPACE)
        return jsonify({"status":"success","volume": actual})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}),400

# Ensure unified handlers override legacy desktop handlers for same paths
try:
    # desktop_controller registers handle_config and handle_direct_volume; unify them
    if 'handle_config' in app.view_functions and 'handle_unified_config' in app.view_functions:
        app.view_functions['handle_config'] = app.view_functions['handle_unified_config']
    if 'handle_direct_volume' in app.view_functions and 'handle_volume' in app.view_functions:
        # keep both endpoints pointing to unified volume handler
        app.view_functions['handle_direct_volume'] = app.view_functions['handle_volume']
except Exception:
    pass

# --- BCI Recording APIs (additive, optional) ---
@app.route("/api/bci/recording/status", methods=["GET"])
def bci_recording_status():
    return jsonify({"status": "success", "recording": bci_recorder.get_status()})

@app.route("/api/bci/recording/start", methods=["POST"])
def bci_recording_start():
    data = request.json or {}
    fname = data.get("filename") or data.get("file")
    p = bci_recorder.start(filename=fname)
    st = bci_recorder.get_status()
    socketio.emit("bci_recording_status", st, namespace=DASHBOARD_NAMESPACE)
    return jsonify({"status": "success", "recording": st, "file": str(p)})

@app.route("/api/bci/recording/stop", methods=["POST"])
def bci_recording_stop():
    p = bci_recorder.stop()
    st = bci_recorder.get_status()
    socketio.emit("bci_recording_status", st, namespace=DASHBOARD_NAMESPACE)
    return jsonify({"status": "success", "recording": st, "file": str(p) if p else None})

@app.route("/api/bci/recording/list", methods=["GET"])
def bci_recording_list():
    return jsonify({"status": "success", "sessions": bci_recorder.list_sessions(), "recording": bci_recorder.get_status()})

# --- BCI Replay APIs (additive) ---
@app.route("/api/bci/replay/list", methods=["GET"])
def bci_replay_list():
    sessions = bci_replay_engine.list_sessions()
    return jsonify({"status": "success", "sessions": sessions, "replay": bci_replay_engine.get_status()})

@app.route("/api/bci/replay/status", methods=["GET"])
def bci_replay_status():
    return jsonify({"status": "success", "replay": bci_replay_engine.get_status()})

@app.route("/api/bci/replay/start", methods=["POST"])
def bci_replay_start():
    data = request.json or {}
    file = data.get("file") or data.get("filename") or data.get("session")
    if not file:
        return jsonify({"status": "error", "message": "missing 'file' field"}), 400
    speed = float(data.get("speed", 1.0))
    # realtime flag: supports realtime / fast
    realtime = data.get("realtime", True)
    # also accept mode string
    mode = data.get("mode", "")
    if isinstance(mode, str) and mode.lower() == "fast":
        realtime = False
    if "fast" in data and bool(data.get("fast")):
        realtime = False
    res = bci_replay_engine.start(file=file, speed=speed, realtime=bool(realtime))
    # emit via socket for dashboard
    socketio.emit("bci_replay_status", bci_replay_engine.get_status(), namespace=DASHBOARD_NAMESPACE)
    # polling thread to emit progress until done
    def _poll():
        while bci_replay_engine.is_playing():
            socketio.sleep(0.5)
            socketio.emit("bci_replay_status", bci_replay_engine.get_status(), namespace=DASHBOARD_NAMESPACE)
        socketio.emit("bci_replay_status", bci_replay_engine.get_status(), namespace=DASHBOARD_NAMESPACE)
        socketio.emit("fsm_state_update", fsm_controller.get_state(), namespace=DASHBOARD_NAMESPACE)
    socketio.start_background_task(_poll)
    if res.get("status") == "error":
        return jsonify(res), 400
    return jsonify({"status": "success", "replay": bci_replay_engine.get_status(), "result": res})

@app.route("/api/bci/replay/stop", methods=["POST"])
def bci_replay_stop():
    bci_replay_engine.stop()
    st = bci_replay_engine.get_status()
    socketio.emit("bci_replay_status", st, namespace=DASHBOARD_NAMESPACE)
    return jsonify({"status": "success", "replay": st})

@app.route("/favicon.ico")
def favicon():
    return send_from_directory(app.static_folder, "favicon.svg", mimetype="image/svg+xml")

def _run_start_chrome_blocking():
    """Deterministic startup: run start_chrome.py synchronously and wait.
    Reuses existing DESKTOP_MODULES_DIR/start_chrome.py. Logs clearly on failure
    but does not abort Flask startup (graceful per existing conventions)."""
    logger = logging.getLogger()
    start_chrome_path = DESKTOP_MODULES_DIR / "start_chrome.py"
    if not start_chrome_path.is_file():
        logger.error(f"[STARTUP] start_chrome.py not found at {start_chrome_path} — skipping Chrome pre-launch")
        return False
    logger.info("[STARTUP] Running start_chrome.py before Flask server...")
    try:
        # Use same interpreter, inherit env, block until completion (~20s max + margin)
        result = subprocess.run(
            [sys.executable, str(start_chrome_path)],
            capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace"
        )
        # Log combined output for diagnostics (truncated)
        if result.stdout:
            for line in result.stdout.strip().splitlines()[-20:]:
                logger.info(f"[start_chrome] {line}")
        if result.returncode == 0:
            logger.info("[STARTUP] start_chrome.py completed successfully — Chrome ready, starting Flask server")
            return True
        else:
            if result.stderr:
                for line in result.stderr.strip().splitlines()[-20:]:
                    logger.error(f"[start_chrome][stderr] {line}")
            logger.error(f"[STARTUP] start_chrome.py failed with exit code {result.returncode} — continuing Flask startup anyway (desktop automation may be limited)")
            return False
    except subprocess.TimeoutExpired:
        logger.error("[STARTUP] start_chrome.py timed out after 60s — continuing Flask startup anyway")
        return False
    except Exception as e:
        logger.error(f"[STARTUP] Failed to invoke start_chrome.py: {e} — continuing Flask startup anyway")
        return False

def main():
    logger=logging.getLogger()
    # --- Deterministic startup order: Chrome first, then Flask ---
    # Run synchronously before ANY Flask/server init; start_chrome.py is
    # idempotent (returns 0 immediately if port 9222 already open), so
    # double-run with reloader is harmless but ensures parent also shows
    # chrome-before-server ordering per spec.
    _run_start_chrome_blocking()
    if not DEBUG_MODE or os.environ.get("WERKZEUG_RUN_MAIN")=="true":
        if MOBILE_AVAILABLE and pipeline_scheduler:
            logger.info("[UNIFIED] Starting Mobile pipeline (paused)...")
            threading.Thread(target=pipeline_scheduler.bci_pipeline_loop, daemon=True).start()
        logger.info("[UNIFIED] Starting Desktop poller...")
        socketio.start_background_task(desktop_status_poller)
        logger.info("[UNIFIED] Starting Unified volume poller...")
        socketio.start_background_task(_volume_poller)
        if CORTEX_ENABLED and cortex_bridge:
            logger.info("[UNIFIED] Starting Cortex bridge...")
            threading.Thread(target=lambda: cortex_bridge.connect(), daemon=True).start()
    port=int(os.environ.get("UNIFIED_PORT", os.environ.get("MASTER_HUB_PORT","8000")))
    logger.info(f"[UNIFIED] SynaptiMesh Unified Dashboard -> http://localhost:{port}/dashboard")
    socketio.run(app, host="0.0.0.0", port=port, debug=DEBUG_MODE, allow_unsafe_werkzeug=True)

if __name__=="__main__":
    main()
