# JioSaavn Master Hub — opencode project context

This file is the reference for any opencode session working in this repo.
Read this first before making changes.

## What this project is

A **single Flask + Flask-SocketIO application** that unifies two existing,
already-working JioSaavn dashboards behind one Master Hub landing page.

| Dashboard | Target | Original source (do not edit) | Controls JioSaavn via |
|-----------|--------|-------------------------------|------------------------|
| 📱 Mobile  | Android device | `Documents/BCI_CODE/sprint6/sprint8/final_web_page/Plugin` | **MQTT** (`broker.emqx.io:1883`) |
| 🖥 Desktop | Browser (Chrome) | `Documents/BCI_CODE/sprint6/sprint10/web_dash_board` | **Selenium** (Chrome remote debugging :9222) |

The original dashboards were **not rebuilt** — their control logic is copied
into this repo **unchanged**. Only the thin web-server wiring was adapted.

## Quick start

```bash
cd sub_master   # or absolute path to this folder
# macOS / Linux:
source .venv/bin/activate
# Windows (PowerShell): .venv\Scripts\Activate.ps1
# Windows (cmd):        .venv\Scripts\activate.bat
python app.py                    # serves on port 8000
```

- Open `http://localhost:8000` (or `/master`) → Master Hub landing page.
- Port override: `MASTER_HUB_PORT=8080 python app.py`.
- Desktop JioSaavn control needs Chrome running with remote debugging:
  `desktop_dashboard/desktop_modules/start_chrome.py` (cross-platform; legacy `start_chrome.sh` kept for compat).

### Dependencies

`requirements.txt`: Flask, Flask-SocketIO, paho-mqtt, selenium, requests,
PyAutoGUI. Installed in `.venv` (Python 3.13, macOS).

## Directory structure

```
dummy-advanced/
├── app.py                       ← entry point: single Flask-SocketIO server
├── desktop_controller.py        ← refactored wiring of desktop dashboard
├── requirements.txt / README.md
├── Python_pipeline/
│   └── integrated_eeg.json      ← MOBILE pipeline dataset (MUST live here —
│                                   the unchanged mobile config computes this path)
├── master_dashboard/
│   ├── templates/index.html     ← Master Hub landing page
│   └── static/                  ← css/style.css, js/main.js, liquid_bg.png
├── mobile_dashboard/
│   ├── templates/mobile.html    ← mobile UI copy (io('/mobile') + back button)
│   └── mobile_plugin/           ← UNCHANGED mobile modules
│       ├── config/config.py     ← MQTT broker/topics, command map, data path
│       ├── services/mqtt_service.py
│       ├── services/logger_service.py
│       ├── scheduler/pipeline.py
│       └── events/socket_events.py
├── desktop_dashboard/
│   ├── templates/dashboard.html ← desktop UI copy (io('/desktop') + back button)
│   ├── static/liquid_bg.png
│   └── desktop_modules/         ← UNCHANGED desktop modules
│       ├── operate_jiosavaan.py (JioSaavnController facade)
│       ├── browser_manager.py   (Selenium attach :9222)
│       ├── player_engine.py
│       ├── bci_pipeline.py
│       ├── logger.py
│       ├── os_operations.py
│       ├── start_chrome.py (cross-platform) + start_chrome.sh (legacy)
│       └── data/integrated_eeg.json  ← DESKTOP pipeline dataset
└── backend/                     ← future unified control layer
    ├── device_manager.py        ← registry of mobile + desktop backends
    ├── state_manager.py         ← active dashboard + connection state
    └── command_router.py        ← single-target dispatch only
```

## Architecture (the important part)

### One server, one SocketIO, two namespaces

Both original dashboards used the SAME socket event names (`manual_command`,
`log_update`, `status_update`, `command_dispatched`, …) — that would collide.
This app runs a single server and isolates the two dashboards with
**Socket.IO namespaces**:

- Mobile clients connect with `io('/mobile')` (mobile template line ~500)
- Desktop clients connect with `io('/desktop')` (desktop template line ~950)

`app.py` defines `NamespacedSocketIO` — a thin wrapper around the shared
SocketIO that pins `namespace=` on every `emit()`/`on()`. It is passed into
the (unchanged) dashboard services so all their broadcasts stay isolated.

### Backend wiring

- **Mobile** (`app.py`): `setup_logger(mobile_sio)` →
  `MQTTService(mobile_sio)` → `PipelineScheduler(...)` →
  `register_socket_events(...)`. The BCI pipeline thread starts **paused**
  (must click **▶ RESUME** on the mobile dashboard) and is guarded with
  `WERKZEUG_RUN_MAIN` to avoid double-start under the debug reloader.
- **Desktop** (`desktop_controller.py`): `register_desktop_backend(app,
  socketio, namespace)` returns `(controller, status_poller)`. Instantiates
  `JioSaavnController` once, wires logger + BCI emitter to `/desktop`,
  registers the `/api/*` routes and socket handlers. `status_poller` runs as
  a SocketIO background task.

### Connections survive navigation

Both backends initialise once at startup (MQTT connect + pipeline thread;
desktop controller + status poller + lazy Chrome attach). Switching between
Master → Mobile → Desktop → Master is pure page navigation; MQTT and Chrome
connections are never torn down.

## Routes

| URL | Page / behaviour |
|-----|------------------|
| `/`, `/master` | Master Hub landing page |
| `/mobile` | Mobile Dashboard (render `mobile.html`) |
| `/desktop` | Desktop Dashboard (render `dashboard.html`) |
| `/static/<path>` | served from `master_dashboard/static/` |

Desktop API endpoints (all in `desktop_controller.py`, POST unless noted):
`/api/action`, `/api/automation` (GET+POST), `/api/volume`, `/api/search`,
`/api/config` (GET+POST).

## Socket.IO events

### Namespace `/mobile` (mobile dashboard)
- Server→client: `sync_state`, `log_message`, `mqtt_connection_status`,
  `command_dispatched`, `execution_feedback`, `media_update`
- Client→server: `connect`, `toggle_pause {paused}`, `manual_command
  {raw_command, confidence}`, `live_search_input {query}`

### Namespace `/desktop` (desktop dashboard)
- Server→client: `status_update`, `log_update`, `command_dispatched`,
  `automation_update`, `config_update`
- Client→server: `toggle_automation {action}`, `manual_command
  {raw_command, confidence}`

## Mobile backend details (MQTT)

- Broker `broker.emqx.io:1883`, QoS 1, topics `bci/rohan/{commands,ack,status,
  heartbeat,media,control}` (namespace `rohan`, see `mobile_dashboard/mobile_plugin/config/config.py`).
- Pipeline reads `integrated_eeg.json`, keeps only `domain == "AI_ML"`,
  `confidence >= 0.80`, skips neutral `Right`; replays forever with a 3 s gap.
- MQTT connect is **resilient**: if the broker is unreachable (e.g.
  `[Errno 61] Connection refused`), the pipeline thread does NOT crash — it
  retries every 5 s until the broker is reachable.

### ⚠️ CRITICAL gotcha: mobile dataset path

`mobile_dashboard/mobile_plugin/config/config.py` computes the dataset path
as `PLUGIN_DIR.parent / "Python_pipeline" / "integrated_eeg.json"`, which
resolves to the **repo root** `Python_pipeline/integrated_eeg.json` — NOT
inside `mobile_dashboard/`. If that file is missing, the mobile pipeline
logs `[FILE READ ERROR]`. Keep it exactly where it is.

## Desktop backend details (Selenium)

- `BrowserManager` attaches to an already-running Chrome on
  `127.0.0.1:9222` (`debuggerAddress`). It never spawns Chrome itself.
- Actions: DOM click first via `execute_js_click`, OS media-key fallback;
  volume is always OS-level (`os_operations.py`, macOS via `osascript`).
- Search uses JioSaavn's autocomplete API to resolve exact URLs then plays.
- Without Chrome running, controls degrade gracefully (return "failed",
  no crash) — expected during tests.

## Future: command router

`backend/command_router.py` supports single-target dispatch:
`route("NEXT_TRACK", target="mobile"|"desktop")`. **`target="both"` is NOT
implemented** — `route_multi(..., targets="both")` raises `NotImplementedError`
by design. Do not implement "both" unless asked.

## Conventions & guardrails

- **Never edit the original dashboards** at `sprint8/final_web_page/Plugin`
  or `sprint10/web_dash_board` — this repo is self-contained.
- **Do not rewrite working control logic** (`mqtt_service.py`, `bci_pipeline.py`,
  `operate_jiosavaan.py`, `browser_manager.py`, `os_operations.py`, etc.).
  Integrate/adapt only the wiring layer.
- The only allowed template edits are the namespace line (`io('/mobile')` /
  `io('/desktop')`) and the "← Back to Master Hub" button (both already done).
- Keep the single-server architecture; do not spin up separate servers.
- Match existing code style (no added comments in copied modules; simple,
  dependency-free approach).

## Verification workflow

```bash
cd sub_master   # or absolute path to this folder
# macOS/Linux: source .venv/bin/activate
# Windows:     .venv\Scripts\Activate.ps1  (PowerShell) or .venv\Scripts\activate.bat (cmd)
python app.py                     # start, watch log
# then:
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/master
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/mobile
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/desktop
curl -s http://localhost:8000/api/config
```

Expected startup log lines: `[MASTER HUB] ...` banner, `[MQTT] Subscribed to
bci/rohan/...`, `[OSOperations] Initialized for Darwin`, `[JioSaavnController]
Starting media status polling`.

A quick socket test (via `socketio.Client`) is: connect to `/mobile`, expect
`sync_state {is_paused: True}`; emit `toggle_pause {paused: False}` → pipeline
should publish `[MQTT] publish bci/rohan/commands :: ...`. No `[FILE READ
ERROR]` may appear.

## Useful facts

- Debug reloader is active (`DEBUG_MODE=True` from mobile config); background
  workers are guarded via `WERKZEUG_RUN_MAIN`.
- After editing `*.py`, the debug reloader restarts automatically.
- `desktop_dashboard/desktop_modules/system_execution.log` grows on every run
  (desktop logger behaviour; it is gitignored).