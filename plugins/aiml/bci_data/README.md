# BCI Data — Recording & Replay

Recorded BCI sessions are **raw, unmodified** classified command streams from the BCI team / Cortex. Replay converges at the same entry point as live data: `receive_cortex_command()`.

## Format

Each session is a JSON file containing an ordered list of events (or object with `events` key). Each event:

```json
{
  "timestamp": "2026-09-05T13:10:01.120",
  "command": "PUSH",
  "confidence": 0.91
}
```

Additional fields are preserved (e.g. `source`, `level`, `power`). Required fields for replay: `command`, `confidence` (numeric 0-1), `timestamp` (optional; if missing current time is used). Tolerant parser accepts:
- `confidence` or `power`
- timestamp as ISO8601 string (`2026-09-05T13:10:01.120` or `2026-09-05 13:10:01.120`), epoch float, or any string (passed through, timing derived if parseable)
- `command` case-insensitive (`PUSH`, `push`, `Push`)

**Do NOT manually deduplicate** raw files. If source sent `PUSH,PUSH,PUSH`, save all three. Deduplication is done by the FSM 4-second window during replay/live.

Supported primitives: `LEFT` `RIGHT` `PUSH` `PULL` (plus `NEUTRAL` which is preserved and filtered by FSM). Invalid commands are reported and skipped during replay, not silently rewritten.

## Directory Layout

```
bci_data/
├── raw/            # put BCI team JSON here (immutable). Examples: session_001.json
├── replay/         # optional: normalized/copied files for replay (or just reuse raw)
└── README.md
```

You may add new datasets simply by dropping a new JSON file into `bci_data/raw/`. Example minimal session (`bci_data/raw/session_001.json`):

```json
[
  {"timestamp": "2026-09-05T13:10:01.120", "command": "PUSH", "confidence": 0.91},
  {"timestamp": "2026-09-05T13:10:02.030", "command": "PUSH", "confidence": 0.88},
  {"timestamp": "2026-09-05T13:10:03.440", "command": "PUSH", "confidence": 0.92},
  {"timestamp": "2026-09-05T13:10:05.100", "command": "RIGHT", "confidence": 0.93},
  {"timestamp": "2026-09-05T13:10:05.260", "command": "PUSH", "confidence": 0.89}
]
```

Also supports object form: `{"session": "001", "events": [ ... ]}`.

## Recording

Recorder is **optional** and additive. It observes Cortex commands WITHOUT modifying them, without FSM logic, without deduplication.

- When OFF (default): `Cortex → receive_cortex_command() → window → FSM → mapper → router`
- When ON:
  ```
  Cortex ─┬─→ recorder → bci_data/raw/session_<timestamp>.json
          └─→ receive_cortex_command() → existing pipeline
  ```

**Enable via API (or env):**

```bash
# Start a new recording session
curl -X POST http://localhost:8000/api/bci/recording/start

# Status
curl http://localhost:8000/api/bci/recording/status

# Stop (flushes file)
curl -X POST http://localhost:8000/api/bci/recording/stop
```

Or set `BCI_RECORDING=1` env to auto-start on boot (file `bci_data/raw/session_<timestamp>.json`).

Dashboard → BCI Data Replay panel → `● Recording` indicator when active.

Incoming events come from TWO places, both recorded: `POST /api/bci/command` (dashboard BCI buttons + future BCI team bridge) and `cortex_bridge` (`_cortex_cb`). Both call the same recorder.

## Replay

Replay reads a saved raw JSON and feeds events **one-by-one into `fsm_controller.receive_cortex_command(command, confidence, timestamp)`** — the same path live Cortex uses — exercising: confidence filtering (0.35), NEUTRAL filtering, duplicate suppression, 4s window, ordered doubles, FSM, mapper, router, mobile/desktop execution.

**CLI (no headset needed):**

```bash
# realtime with original timing (1.0x)
python3 replay_bci.py bci_data/raw/session_001.json

# faster
python3 replay_bci.py bci_data/raw/session_001.json --speed 2.0

# half speed
python3 replay_bci.py bci_data/raw/session_001.json --speed 0.5

# fast (no timing, sequential)
python3 replay_bci.py bci_data/raw/session_001.json --fast

# dry-run (FSM only, no MQTT/Selenium dispatch)
python3 replay_bci.py bci_data/raw/session_001.json --dry-run

# custom window / threshold
python3 replay_bci.py bci_data/raw/session_001.json --window 4.0 --threshold 0.35
```

**API (from dashboard or curl):**

```bash
# list sessions
curl http://localhost:8000/api/bci/replay/list

# start replay (realtime, 1.0x)
curl -X POST http://localhost:8000/api/bci/replay/start -H "Content-Type: application/json" \
  -d '{"file":"session_001.json","speed":1.0,"realtime":true}'

# also accepts bci_data/raw/session_001.json or absolute path

# stop
curl -X POST http://localhost:8000/api/bci/replay/stop

# status
curl http://localhost:8000/api/bci/replay/status
```

Dashboard → BCI Data Replay panel: Dataset dropdown, Speed input, Mode Real-time/Fast, Replay/Stop, status badge.

**Timing:** Replay computes `delay = (curr_ts - prev_ts) / speed` from recorded timestamps (ISO or epoch). If timestamps unparseable or realtime=false, sends sequentially with `0.05s` gap. Absolute wall-clock is NOT used.

## Adding New Datasets

1. Drop JSON file into `bci_data/raw/` (e.g. `session_003.json`).
2. Replay immediately: `python3 replay_bci.py bci_data/raw/session_003.json` or via dashboard dropdown (auto-discovers files).

No code changes required.

## Important Notes

- Raw data must NOT be deduplicated before saving — FSM window decides.
- Do NOT convert `RIGHT` + `PUSH` into `RIGHT+PUSH` before FSM — send as two sequential primitives.
- Recording never bypasses FSM; replay never calls `process_command()` directly — both converge at `receive_cortex_command()`.
- Invalid/unknown commands are skipped with warning; NEUTRAL passes through to existing FSM filter.
