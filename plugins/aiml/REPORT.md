# SynaptiMesh — Project Report (05-09-26)

Generated: 2026-09-15

## 1. Overview

**SynaptiMesh** is an experimental unified dashboard that turns BCI headset
commands (and dashboard buttons) into actions on three targets:

| Target | Transport | Where |
|---|---|---|
| Mobile dashboard | MQTT (`paho-mqtt`, broker.emqx.io) | phone / `mobile_dashboard` |
| Desktop JioSaavn | Selenium + Chrome CDP (port 9222) | this PC / `desktop_dashboard` |
| Second desktop / device | USB-to-TTL UART (COM3) | best-effort / `uart_transmitter.py` |

Single Flask app: `app.py` (unified UI at `http://localhost:8000/dashboard`).
The FSM in `command_system/fsm_controller.py` is the single source of truth for
command hierarchy — there is no second FSM.

## 2. Command pipeline

```
BCI headset / dashboard buttons
   -> POST /api/bci/command {"command":"LEFT","confidence":0.95}
   -> command_system/command_window.py     (4.0 s window, dedup, doubles)
   -> command_system/fsm_controller.py     (state machine, target_device)
   -> command_system/command_mapper.py     (logical action -> canonical action)
   -> backend/command_router.py            (route: mobile / desktop / uart)
       -> Mobile   : MQTT publish on bci/rohan/commands
       -> Desktop  : desktop_dashboard/desktop_modules (Selenium / OS keys)
       -> UART     : uart_transmitter.send_action()   (async, best-effort)
```

Live BCI (optional): `command_system/cortex_bridge.py` connects to
`wss://localhost:6868` (Emotiv Cortex) when `CORTEX_CLIENT_ID` /
`CORTEX_CLIENT_SECRET` are set. Without them the app falls back to
`mock_bci.py` + dashboard test buttons.

## 3. Directory structure

```
05-09-26/
  app.py                          Flask unified server (manual + API)
  desktop_controller.py           Desktop action REST controller
  uart_transmitter.py             Best-effort UART transport (worker thread)
  test_uart.py                    Independent UART diagnostic utility
  replay_bci.py                   Replay recorded BCI sessions
  requirements.txt                Dependencies (incl. win32-only)
  README.md                       Project documentation
  REPORT.md                       This report

  command_system/                 BCI -> FSM -> command pipeline
    fsm_controller.py, states.py, command_mapper.py, command_parser.py
    command_window.py, cortex_bridge.py, mock_bci.py
    bci_recorder.py, bci_replay.py

  backend/
    command_router.py             Final routing per target
    device_manager.py, state_manager.py

  desktop_dashboard/desktop_modules/
    operate_jiosavaan.py          JioSaavn controller
    browser_manager.py            Chrome CDP attach / click helpers
    player_engine.py              Media action execution
    os_operations.py              Windows volume/media (+ winrt fallback)
    bci_pipeline.py               Simulated BCI feed (data/integrated_eeg.json)
    start_chrome.py + .sh         Chrome remote-debugging launcher
    logger.py                     Logging config

  mobile_dashboard/mobile_plugin/
    services/mqtt_service.py      MQTT publish/subscribe
    services/logger_service.py
    events/socket_events.py       SocketIO events
    scheduler/pipeline.py
    config/config.py

  dashboard/  master_dashboard/  desktop_dashboard/templates+static...
                                  Web UIs (unified / mobile / desktop style)

  tests/test_bci_recording_replay.py   Unit tests (recording & replay)
  bci_data/                        Recorded sessions (raw/ + replay/)
```

## 4. FSM hierarchy (command_system/states.py)

- Level 1 `DOMAIN_SELECTION`: wait for `right`
- Level 2 `SUB_MASTER_DASHBOARD` (initial): `push` -> Mobile, `pull` -> Desktop,
  `right` -> back to L1
- Level 3 `MOBILE/DESKTOP_DASHBOARD_ACTIVE`: `left` = Play/Pause, `push` = Next,
  `pull` = Previous, `right` = Search
- Ordered doubles (4 s window): `right+push` Vol+, `right+pull` Vol-,
  `push+right` Back L2, `push+left` Back L1

Config: `COMMAND_WINDOW_SECONDS=4.0`, `CONFIDENCE_THRESHOLD=0.35`, debounce 2 s.
Canonical actions include `play_pause`, `next_track`, `previous_track`,
`volume_up`, `volume_down`, `search`, `open_mobile_dashboard`,
`open_desktop_dashboard`.

## 5. UART subsystem (uart_transmitter.py)

- Asynchronous: actions are queued on a 1-worker thread pool; the dashboard
  never waits on the receiver.
- Transport config (env vars, defaults shown):
  `UART_ENABLED=true`, `UART_PORT=COM3`, `UART_BAUDRATE=9600`,
  `UART_TIMEOUT=1.0`, `UART_ACK_ENABLED=false`, `UART_TERMINATOR=\n`.
- Wire payload: `action cmd|<canonical_action>\n` (e.g. `action cmd|play_pause\n`).
- `UART_ACK_ENABLED=false` (default) = fire-and-forget writes; set `true` only
  if the receiver echoes a line, to obtain delivery feedback.
- Received bytes (when ACK enabled) are logged as `[UART RX]`; no ACK syntax is
  assumed.
- Hardware: two-laptop link via USB-to-TTL adapters. Wiring is TX->RX,
  RX->TX, GND->GND (crossed between the two adapters). Both sides must use the
  same baud rate.

## 6. Diagnostics & testing status (2026-09-15)

Verified working:
- `python -m py_compile` passes for all edited modules (`app.py`,
  `uart_transmitter.py`, `test_uart.py`, `start_chrome.py`, `os_operations.py`).
- Full pipeline end-to-end: BCI button `pull` -> FSM L2->L3 -> desktop open;
  `left` -> Chrome attached to port 9222, JioSaavn tab opened and
  `#player_play_pause` clicked (`UART TX action cmd|play_pause` fired).
- UART: COM3 opens, `[UART] Connected @ 115200`, payload written, zero serial
  errors in log. Loopback/echo reply from the receiver laptop is **still
  pending** — the physical link to the second laptop is the current open item.
- winrt media-status fallback logs **once per process** instead of every second.
- `start_chrome.py` no longer crashes on Windows cp1252 consoles (UTF-8
  stdout/stderr reconfigure at startup).

Pending (hardware/firmware — not code):
- Receiver laptop not yet confirming receipt of `action cmd|<action>`.
  Suspects: baud mismatch on the receiving side, crossed/missing TX-RX wiring,
  phantom COM3 port, or receiver-side parser expecting a different payload.
  Suggested: TX->RX loopback on the sending adapter, and a serial monitor on
  the receiver laptop at the same baud to observe the payload.

## 7. Recent changes (this session)

| File | Change |
|---|---|
| `start_chrome.py` | UTF-8 stdout/stderr reconfigure (fixes emoji print crash) |
| `app.py` | `subprocess.run` decode with `encoding="utf-8", errors="replace"` |
| `os_operations.py` | winrt `ImportError` logged only once per process |
| `requirements.txt` | `winsdk>=1.0.0; sys_platform == "win32"` uncommented |
| `uart_transmitter.py` | ACK-timeout warning clarifies TX succeeded; defaults 9600; ACK disabled by default |
| `test_uart.py` | default baud 9600; ACK read on unless `--no-ack` |
| `README.md` | baud 9600, ACK default false, wiring notes |

## 8. Recommended next steps

1. Loopback test on sending adapter (TX jumped to RX) to prove adapter health.
2. Run a serial monitor on the receiver laptop at **9600** and resend a test
   command; confirm `action cmd|LOOP` arrives.
3. If the receiver's firmware expects a different payload, adjust
   `uart_transmitter.send_command()` (`action cmd|` prefix) to match.
4. To run: `pip install -r requirements.txt` then `python app.py`
   (http://localhost:8000/dashboard).