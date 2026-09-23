"""BCI Replay Engine — reads raw BCI JSON and replays through receive_cortex_command().

Converges with live pipeline at receive_cortex_command(), so replay exercises:
 confidence filtering, NEUTRAL filtering, deduplication, 4s window, ordered doubles, FSM, mapper, router.

Never calls process_command() directly. Never deduplicates before FSM. Never converts RIGHT+PUSH.
"""

import json
import time
import threading
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable, Tuple
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Allowed primitives; NEUTRAL allowed but preserved (FSM will filter). Others rejected.
_VALID_MIN_CONF = 0.0
_VALID_MAX_CONF = 1.05  # allow slight over 1.0 for robustness, but flag >1.0
PRIMITIVE_SET = {"push", "pull", "left", "right", "neutral"}


def _parse_timestamp_to_epoch(ts: Any) -> Optional[float]:
    """Try to parse timestamp to epoch float for delay calc. Returns None if unparseable."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        s = ts.strip()
        if not s:
            return None
        # try ISO8601
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                # handle Z
                ss = s.replace("Z", "+00:00") if s.endswith("Z") else s
                # fromisoformat handles +00:00
                try:
                    dt = datetime.fromisoformat(ss)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt.timestamp()
                except Exception:
                    pass
                dt = datetime.strptime(s.split("+")[0].split("Z")[0][:26], fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.timestamp()
            except Exception:
                continue
        # numeric string
        try:
            return float(s)
        except Exception:
            return None
    return None


def _normalize_events(data: Any) -> List[Dict[str, Any]]:
    """Normalize raw file data to list of events. Adapter: tolerates multiple shapes."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # object forms: {"events": [...]}, {"commands": [...]}, {"data": [...]}, {"session":..., "events":...}
        for key in ("events", "commands", "data", "packets", "raw"):
            if key in data and isinstance(data[key], list):
                return data[key]
        # single event object
        if "command" in data:
            return [data]
        # test_sequences hierarchical (unlikely for raw, but support)
        if "test_sequences" in data:
            events = []
            for seq in data.get("test_sequences", []):
                for pkt in seq.get("commands", []):
                    events.append(pkt)
            return events
    return []


def load_bci_file(path: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Load file, return (events, warnings). Events are raw dicts with timestamp/command/confidence."""
    warnings: List[str] = []
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except Exception as e:
        return [], [f"failed to read {path}: {e}"]
    events = _normalize_events(data)
    if not isinstance(events, list):
        return [], [f"unexpected top-level type {type(events)}"]
    # warn if empty
    if len(events) == 0:
        warnings.append(f"{path.name}: no events found")
    return events, warnings


def _validate_event(ev: Dict[str, Any], index: int) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Validate one event, return (ok, reason, normalized). Never auto-fix command."""
    if not isinstance(ev, dict):
        return False, f"event {index}: not an object", None
    raw_cmd = ev.get("command", ev.get("cmd", ev.get("action")))
    if raw_cmd is None:
        return False, f"event {index}: missing 'command' field", None
    cmd_str = str(raw_cmd).strip()
    cmd_lower = cmd_str.lower()
    # reject combined like RIGHT+PUSH entering receive_cortex_command
    if "+" in cmd_str:
        return False, f"event {index}: combined command '{cmd_str}' must not be sent to receive_cortex_command (send as two primitives)", None
    if cmd_lower not in PRIMITIVE_SET:
        return False, f"event {index}: unknown command '{cmd_str}' (allowed: LEFT/PUSH/PULL/RIGHT/NEUTRAL)", None
    # confidence numeric check
    raw_conf = ev.get("confidence", ev.get("power", ev.get("conf", None)))
    if raw_conf is None:
        return False, f"event {index}: missing 'confidence'/'power'", None
    try:
        conf = float(raw_conf)
    except Exception:
        return False, f"event {index}: confidence not numeric: {raw_conf!r}", None
    if conf < 0.0 or conf > 1.05:
        return False, f"event {index}: confidence {conf} out of [0,1] range", None
    # timestamp presence (optional but warn)
    ts = ev.get("timestamp", ev.get("time", ev.get("ts", None)))
    if ts is None:
        # will use current time during replay; not a hard error
        pass
    # normalized: preserve original timestamp repr for recorder compat, but provide parsed
    norm = {"command": cmd_str, "confidence": conf, "timestamp": ts, "_raw": ev}
    return True, "ok", norm


class BCIReplayEngine:
    """Replay raw BCI JSON through fsm_controller.receive_cortex_command().

    Supports realtime (relative delays) and fast modes, speed multiplier, stop.
    Single path: every event -> receive_cortex_command(command, confidence, timestamp)
    """

    def __init__(self, fsm_controller, base_dir: Optional[Path] = None):
        self.fsm = fsm_controller
        self.base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent / "bci_data" / "raw"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()
        self._status = "idle"  # idle | playing | stopped | completed | error
        self._current_file: Optional[str] = None
        self._progress = {"total": 0, "sent": 0, "skipped": 0}
        self._last_error: Optional[str] = None
        self._replay_lock = threading.Lock()

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "status": self._status,
                "current_file": self._current_file,
                "progress": dict(self._progress),
                "error": self._last_error,
            }

    def list_sessions(self) -> List[str]:
        try:
            raws = sorted(self.base_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            # also check replay dir for convenience
            replay_dir = self.base_dir.parent / "replay"
            if replay_dir.is_dir():
                raws2 = list(replay_dir.glob("*.json"))
                raws = [*raws, *raws2]
            return [p.name for p in raws]
        except Exception:
            return []

    def _resolve_file(self, file: str) -> Path:
        p = Path(file)
        if p.is_file():
            return p
        # try base_dir / file
        cand = self.base_dir / file
        if cand.is_file():
            return cand
        # try replay dir
        cand2 = self.base_dir.parent / "replay" / file
        if cand2.is_file():
            return cand2
        # basename only
        cand3 = self.base_dir / Path(file).name
        if cand3.is_file():
            return cand3
        raise FileNotFoundError(f"replay file not found: {file} (searched {self.base_dir}, {self.base_dir.parent/'replay'})")

    def stop(self):
        self._stop_flag.set()
        th = None
        with self._lock:
            th = self._thread
        if th and th.is_alive():
            th.join(timeout=2.0)
        with self._lock:
            if self._status == "playing":
                self._status = "stopped"
        logger.info("[REPLAY] stopped")

    def is_playing(self) -> bool:
        with self._lock:
            return self._status == "playing"

    def start(self, file: str, speed: float = 1.0, realtime: bool = True, inter_event_delay: float = 0.05) -> Dict[str, Any]:
        """Start replay in background thread. Returns status dict."""
        with self._replay_lock:
            with self._lock:
                if self._status == "playing":
                    return {"status": "error", "message": "already playing", **self.get_status()}
            try:
                path = self._resolve_file(file)
            except FileNotFoundError as e:
                with self._lock:
                    self._status = "error"; self._last_error = str(e)
                return {"status": "error", "message": str(e)}
            # reset state
            self._stop_flag.clear()
            with self._lock:
                self._current_file = str(path)
                self._progress = {"total": 0, "sent": 0, "skipped": 0}
                self._last_error = None
                self._status = "playing"

            def _run():
                try:
                    events, warns = load_bci_file(path)
                    for w in warns:
                        logger.warning(f"[REPLAY] {w}")
                    # validate but do not filter raw count for total: count raw events, but progress uses validated send
                    valid_norms: List[Dict[str, Any]] = []
                    for idx, ev in enumerate(events):
                        ok, reason, norm = _validate_event(ev, idx)
                        if not ok:
                            logger.warning(f"[REPLAY] skip {reason}")
                            with self._lock:
                                self._progress["skipped"] += 1
                            continue
                        valid_norms.append(norm)
                    with self._lock:
                        self._progress["total"] = len(events)
                    # calculate delays
                    prev_epoch: Optional[float] = None
                    for i, norm in enumerate(valid_norms):
                        if self._stop_flag.is_set():
                            break
                        cmd = norm["command"]
                        conf = norm["confidence"]
                        ts_raw = norm["timestamp"]
                        epoch = _parse_timestamp_to_epoch(ts_raw)
                        if realtime and speed > 0:
                            if i == 0:
                                # no delay for first
                                prev_epoch = epoch
                            else:
                                if epoch is not None and prev_epoch is not None:
                                    orig_delay = epoch - prev_epoch
                                    # clamp negative or huge delays (out-of-order or gaps > 30s cap)
                                    if orig_delay < 0:
                                        orig_delay = 0.0
                                    if orig_delay > 30.0:
                                        orig_delay = min(orig_delay, 5.0)
                                    actual = orig_delay / float(speed) if speed else 0.0
                                    # also cap actual to avoid too long test waits; but preserve original semantics
                                    if actual > 10.0:
                                        actual = 10.0
                                    if actual > 0.001:
                                        # interruptible sleep
                                        end = time.time() + actual
                                        while time.time() < end:
                                            if self._stop_flag.is_set():
                                                break
                                            time.sleep(min(0.05, end - time.time()))
                                else:
                                    # fallback tiny gap
                                    time.sleep(inter_event_delay / float(speed) if speed else inter_event_delay)
                                prev_epoch = epoch if epoch is not None else prev_epoch
                        else:
                            # fast mode: tiny gap to avoid collapsing timer edge cases, but not wall timing
                            if inter_event_delay > 0:
                                time.sleep(inter_event_delay)
                            prev_epoch = epoch if epoch is not None else prev_epoch
                        if self._stop_flag.is_set():
                            break
                        # single path convergence: NEUTRAL is sent, FSM filters it; duplicates sent as-is
                        # preserve timestamp as epoch float for FSM window
                        fsm_ts = epoch if epoch is not None else time.time()
                        try:
                            accepted = self.fsm.receive_cortex_command(cmd, conf, timestamp=fsm_ts)
                            logger.info(f"[REPLAY] {i+1}/{len(valid_norms)} {cmd} conf={conf:.2f} accepted={accepted} ts={ts_raw}")
                        except Exception as e:
                            logger.error(f"[REPLAY] receive_cortex_command failed for {cmd}: {e}")
                        with self._lock:
                            self._progress["sent"] += 1
                    with self._lock:
                        if self._stop_flag.is_set():
                            self._status = "stopped"
                        else:
                            self._status = "completed"
                        logger.info(f"[REPLAY] {self._status}: {self._progress} file={path.name}")
                except Exception as e:
                    logger.error(f"[REPLAY] error: {e}")
                    with self._lock:
                        self._status = "error"
                        self._last_error = str(e)

            self._thread = threading.Thread(target=_run, daemon=True)
            self._thread.start()
            return {"status": "success", "message": f"replay started: {path.name}", **self.get_status()}

    # helper for CLI sync replay (blocking)
    def replay_sync(self, file: str, speed: float = 1.0, realtime: bool = True, inter_event_delay: float = 0.05) -> Dict[str, Any]:
        res = self.start(file, speed=speed, realtime=realtime, inter_event_delay=inter_event_delay)
        if res.get("status") == "error":
            return res
        # wait for completion
        while True:
            st = self.get_status()
            if st["status"] in ("completed", "stopped", "error", "idle"):
                return st
            time.sleep(0.05)
