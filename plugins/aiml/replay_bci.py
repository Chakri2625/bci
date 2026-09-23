#!/usr/bin/env python3
"""
CLI replay for BCI recorded sessions.

Usage:
    python3 replay_bci.py bci_data/raw/session_001.json
    python3 replay_bci.py bci_data/raw/session_001.json --speed 2.0
    python3 replay_bci.py bci_data/raw/session_001.json --fast
    python3 replay_bci.py bci_data/raw/session_001.json --dry-run

Replays through the SAME path as live Cortex: fsm_controller.receive_cortex_command()
without requiring EPOC X headset or Flask server.

For live server replay, prefer: curl POST /api/bci/replay/start
"""
import argparse
import sys
import time
from pathlib import Path

# Ensure desktop modules and mobile plugin resolvable if needed
BASE_DIR = Path(__file__).resolve().parent
import sys as _sys
for p in [str(BASE_DIR / "desktop_dashboard" / "desktop_modules"), str(BASE_DIR / "mobile_dashboard" / "mobile_plugin")]:
    if p not in _sys.path:
        _sys.path.insert(0, p)

from command_system.fsm_controller import FSMController
from command_system.command_mapper import CommandMapper
from command_system.bci_replay import BCIReplayEngine


def build_fsm(dry_run=True, window=4.0, threshold=0.35):
    # dry_run True avoids needing MQTT/desktop controller
    mapper = CommandMapper(command_router=None, dry_run=dry_run)
    fsm = FSMController(mapper=mapper, dry_run=dry_run, combo_timeout=window)
    fsm.window_confidence_threshold = threshold
    fsm.window_duration = window
    return fsm


def main():
    parser = argparse.ArgumentParser(description="Replay BCI raw JSON through FSM pipeline")
    parser.add_argument("file", help="Path to BCI raw JSON (bci_data/raw/session_*.json)")
    parser.add_argument("--speed", type=float, default=1.0, help="Replay speed multiplier (default 1.0)")
    parser.add_argument("--fast", action="store_true", help="Ignore timestamps, send sequentially")
    parser.add_argument("--realtime", action="store_true", help="Use timestamp-based realtime (default)")
    parser.add_argument("--window", type=float, default=4.0, help="FSM window seconds (default 4.0)")
    parser.add_argument("--threshold", type=float, default=0.35, help="Confidence threshold (default 0.35)")
    parser.add_argument("--dry-run", action="store_true", default=True, help="FSM dry-run (no hardware dispatch) - default")
    parser.add_argument("--live", action="store_true", help="Attempt live dispatch (needs device backends) - overrides dry-run")
    parser.add_argument("--inter-delay", type=float, default=0.02, help="Gap in fast mode (seconds, default 0.02)")
    args = parser.parse_args()

    realtime = not args.fast
    if args.realtime:
        realtime = True
    if args.fast:
        realtime = False

    dry_run = not args.live
    if args.live:
        dry_run = False

    fsm = build_fsm(dry_run=dry_run, window=args.window, threshold=args.threshold)
    # Start at L3 for standalone media tests? No - start at default L2 unless user navigates via data.
    # Provide readable FSM state logger via prints
    print(f"[REPLAY CLI] file={args.file} speed={args.speed} realtime={realtime} dry_run={dry_run} window={args.window} threshold={args.threshold}")
    print(f"[REPLAY CLI] initial FSM {fsm.get_state()}")

    # collect dispatch logs
    replay = BCIReplayEngine(fsm_controller=fsm, base_dir=BASE_DIR/"bci_data"/"raw")

    result = replay.replay_sync(file=args.file, speed=args.speed, realtime=realtime, inter_event_delay=args.inter_delay)
    # Wait for window to flush (single command waits full window; double flushes immediately)
    wait = fsm.window_duration + 0.5 if len(fsm.history)==0 or fsm.window_commands else 0.3
    # If history still empty but window has pending, wait full window
    if fsm.window_commands:
        wait = fsm.window_duration + 0.5
        print(f"[REPLAY CLI] waiting {wait:.1f}s for {fsm.window_duration}s window flush...")
        time.sleep(wait)
    elif len(fsm.history)==0:
        # may be single pending flushed after timer
        time.sleep(fsm.window_duration + 0.5)
    print(f"[REPLAY CLI] done status={result}")

    # show FSM history summary
    print(f"[REPLAY CLI] FSM final state {fsm.get_state()}")
    print(f"[REPLAY CLI] history ({len(fsm.history)} logical actions):")
    for i, h in enumerate(fsm.history[-20:], 1):
        print(f"  {i}. {h.get('command')} -> {h.get('action')} msg={h.get('message')} dispatch={h.get('dispatch')}")

    # if dry-run, also print mapper dispatch_log
    if fsm.mapper and fsm.mapper.dispatch_log:
        print(f"[REPLAY CLI] mapper dispatches ({len(fsm.mapper.dispatch_log)}):")
        for d in fsm.mapper.dispatch_log[-20:]:
            print(f"    {d}")

if __name__ == "__main__":
    main()
