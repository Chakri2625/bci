# SynaptiMesh — Unified Dashboard (Experimental 05-09-26)

Experimental separate folder. Original project `03-09-26/sub_master` untouched.

## Unified Route
- `/` -> redirects to `/dashboard`
- `/dashboard` single common UI controls both Mobile (MQTT) and Desktop (Selenium)

## Architecture
```
BCI / POST /api/bci/command -> receive_cortex_command -> 4s window (0.35 threshold) -> FSM -> CommandMapper -> CommandRouter -> target
```
FSM is single source of truth for hierarchy. No second FSM.

## UART transmitter

The dashboard optionally transmits each canonical action to a second desktop
using USB-to-TTL UART. UART is an asynchronous, best-effort side effect: serial
errors and ACK timeouts are logged without interrupting the dashboard.

Install dependencies and start the existing application:

```powershell
pip install -r requirements.txt
python app.py
```

Configuration is provided with environment variables (defaults shown):

```text
UART_ENABLED=true
UART_PORT=COM3
UART_BAUDRATE=9600
UART_TIMEOUT=1.0
UART_ACK_ENABLED=false
UART_TERMINATOR=\\n
```

Set `UART_PORT=COM1` when that is the available receiver port. Set
`UART_ENABLED=false` to run the dashboard exactly without UART transmission.
The command payload is `action cmd|<canonical_action>`; the terminator remains
configurable because the receiver framing is not available for inspection.
Raw receiver responses are logged as `[UART RX]`; no ACK syntax is assumed.
`UART_ACK_ENABLED` defaults to `false` (fire-and-forget writes). Set it to
`true` only if the receiver echoes a reply line, to get delivery feedback.

Hardware wiring is TX -> RX, RX -> TX, and GND -> GND. Confirm the cable's
labels and receiver UART pinout before powering the link.

Run the independent diagnostic utility with a deliberately chosen command:

```powershell
python test_uart.py --port COM3 --command "action cmd|TEST"
```

The utility prompts for a command when `--command` is omitted. Use only a
receiver-supported safe command; `TEST` is not assumed to be supported.
Troubleshoot COM1 versus COM3, port-in-use errors, disconnected cables,
crossed TX/RX, missing GND, baud mismatch, receiver availability, ACK timeout,
and Windows access permissions.

## FSM Hierarchy
- Level1 DOMAIN_SELECTION: RIGHT -> Level2
- Level2 SUB_MASTER_DASHBOARD: PUSH->Mobile, PULL->Desktop, RIGHT->Back L1, LEFT undefined
- Level3 MOBILE/DESKTOP_ACTIVE: LEFT Play/Pause, PUSH Next, PULL Previous, RIGHT Search
- Doubles (ordered, via 4s window): RIGHT+PUSH Vol+, RIGHT+PULL Vol-, PUSH+RIGHT Back L2, PUSH+LEFT Back L1

Config: COMMAND_WINDOW_SECONDS=4.0, CONFIDENCE_THRESHOLD=0.35, DEBOUNCE 2s — unchanged.

NEUTRAL ignored completely. Deduplication: repeated same primitive within window suppressed; ordered doubles preserved.

## BCI Input
Single path: `POST /api/bci/command {"command":"LEFT","confidence":0.95}` -> `receive_cortex_command`. For doubles, frontend does two sequential POSTs (e.g. RIGHT then PUSH). No duplicate socket+fetch.

## Mobile/Desktop Execution
- Mobile: `command_router.route("Right_Play_Pause", target="mobile")` -> `MQTT publish`
- Desktop: `controller.execute_action("Play / Pause")` via existing desktop_modules (Selenium/OS keys)
- Target determined by FSM `target_device`.

## Run
```bash
pip install -r requirements.txt
python app.py  # http://localhost:8000/dashboard
```

## Testing
Use dashboard BCI buttons (BCI Play/Pause etc.) — they send primitives through window. History shows accepted logical commands only.

## Cortex
Set `CORTEX_CLIENT_ID`/`CORTEX_CLIENT_SECRET` env to enable live bridge (wss://localhost:6868 handshake with token/headset/session polling).
