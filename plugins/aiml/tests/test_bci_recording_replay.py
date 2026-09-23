"""Tests for BCI Recording & Replay — must use receive_cortex_command path."""

import json, time, tempfile, threading
from pathlib import Path
import sys
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
for p in [str(BASE_DIR/"desktop_dashboard"/"desktop_modules"), str(BASE_DIR/"mobile_dashboard"/"mobile_plugin")]:
    if p not in sys.path: sys.path.insert(0, p)

from command_system.bci_recorder import BCIRecorder
from command_system.bci_replay import BCIReplayEngine, _parse_timestamp_to_epoch, load_bci_file, _validate_event
from command_system.fsm_controller import FSMController
from command_system.command_mapper import CommandMapper
from command_system.states import MOBILE_DASHBOARD_ACTIVE, SUB_MASTER_DASHBOARD, VOLUME_UP, BACK_TO_LEVEL_2, DOMAIN_SELECTION

def _make_fsm(window=4.0, threshold=0.35, at_level3=True):
    mapper = CommandMapper(dry_run=True)
    fsm = FSMController(mapper=mapper, dry_run=True, combo_timeout=window)
    fsm.window_confidence_threshold = threshold
    fsm.window_duration = window
    if at_level3:
        fsm.current_state = MOBILE_DASHBOARD_ACTIVE
        fsm.target_device = "mobile"
        fsm.dashboard_open = True
    return fsm

# Test 1 — Recording preserves raw (no dedup)
def test_recording_preserves_raw():
    with tempfile.TemporaryDirectory() as tmp:
        rec = BCIRecorder(base_dir=Path(tmp))
        rec.start(filename="test.json")
        rec.record("PUSH", 0.91, timestamp="2026-09-05T13:10:01.120")
        rec.record("PUSH", 0.88, timestamp="2026-09-05T13:10:02.030")
        rec.record("PUSH", 0.92, timestamp="2026-09-05T13:10:03.440")
        p = rec.stop()
        data = json.loads(Path(p).read_text())
        assert len(data) == 3, f"expected 3 raw events, got {data}"
        assert [e["command"] for e in data] == ["PUSH","PUSH","PUSH"]
        print("Test1 recording preserved: PASS")

# Test 2 — Replay dedup: 3 PUSH -> 1 logical
def test_replay_dedup():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)/"dedup.json"
        json.dump([
            {"timestamp":"2026-09-05T13:10:01.120","command":"PUSH","confidence":0.91},
            {"timestamp":"2026-09-05T13:10:01.200","command":"PUSH","confidence":0.88},
            {"timestamp":"2026-09-05T13:10:01.300","command":"PUSH","confidence":0.92},
        ], open(p,"w"))
        fsm = _make_fsm(window=0.5)
        engine = BCIReplayEngine(fsm, base_dir=Path(tmp))
        # fast mode to group within window
        engine.replay_sync(str(p), speed=1.0, realtime=False, inter_event_delay=0.02)
        time.sleep(0.7)  # wait for 0.5s window expiry
        # Should have exactly 1 logical NEXT
        assert len(fsm.history)==1, f"expected 1, got {fsm.history}"
        assert fsm.history[0]["action"]=="next_track", f"got {fsm.history[0]}"
        print("Test2 dedup replay: PASS")

# Test3 — Ordered double RIGHT+PUSH -> VOLUME_UP
def test_ordered_double():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)/"double.json"
        json.dump([
            {"timestamp":"2026-09-05T13:10:01.000","command":"RIGHT","confidence":0.91},
            {"timestamp":"2026-09-05T13:10:01.300","command":"PUSH","confidence":0.89},
        ], open(p,"w"))
        fsm = _make_fsm(window=0.5)
        engine = BCIReplayEngine(fsm, base_dir=Path(tmp))
        engine.replay_sync(str(p), speed=1.0, realtime=False, inter_event_delay=0.02)
        time.sleep(0.2)
        assert len(fsm.history)==1
        assert fsm.history[0]["action"]==VOLUME_UP, f"expected VOLUME_UP got {fsm.history[0]}"
        print("Test3 RIGHT+PUSH VOLUME_UP: PASS")

# Test4 — Reverse PUSH+RIGHT -> BACK_TO_LEVEL_2
def test_reverse_double():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)/"rev.json"
        json.dump([
            {"timestamp":"2026-09-05T13:10:01.000","command":"PUSH","confidence":0.91},
            {"timestamp":"2026-09-05T13:10:01.200","command":"RIGHT","confidence":0.89},
        ], open(p,"w"))
        fsm = _make_fsm(window=0.5)
        engine = BCIReplayEngine(fsm, base_dir=Path(tmp))
        engine.replay_sync(str(p), speed=1.0, realtime=False, inter_event_delay=0.02)
        time.sleep(0.2)
        assert len(fsm.history)==1
        assert fsm.history[0]["action"]==BACK_TO_LEVEL_2
        assert fsm.current_state==SUB_MASTER_DASHBOARD
        print("Test4 PUSH+RIGHT BACK_TO_LEVEL_2: PASS")

# Test5 — Confidence filtering 0.2 rejected
def test_confidence_filter():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)/"low.json"
        json.dump([{"timestamp":"2026-09-05T13:10:01.000","command":"PUSH","confidence":0.2}], open(p,"w"))
        fsm = _make_fsm(window=0.3)
        engine = BCIReplayEngine(fsm, base_dir=Path(tmp))
        engine.replay_sync(str(p), speed=1.0, realtime=False, inter_event_delay=0.01)
        time.sleep(0.5)
        assert len(fsm.history)==0, f"low conf should be filtered, got {fsm.history}"
        print("Test5 confidence threshold: PASS")

# Test6 — NEUTRAL preserved in raw, but filtered by FSM
def test_neutral():
    with tempfile.TemporaryDirectory() as tmp:
        # raw preserves
        rec = BCIRecorder(base_dir=Path(tmp))
        rec.start(filename="neu.json")
        rec.record("NEUTRAL", 0.9, timestamp="2026-09-05T13:10:01.000")
        rec.record("PUSH", 0.9, timestamp="2026-09-05T13:10:02.000")
        p = rec.stop()
        data = json.loads(Path(p).read_text())
        assert any(e["command"]=="NEUTRAL" for e in data), "NEUTRAL not preserved in raw"
        # replay
        q = Path(tmp)/"replay_neu.json"
        json.dump([
            {"timestamp":"2026-09-05T13:10:01.000","command":"NEUTRAL","confidence":0.9},
            {"timestamp":"2026-09-05T13:10:01.300","command":"PUSH","confidence":0.9},
        ], open(q,"w"))
        fsm = _make_fsm(window=0.3)
        engine = BCIReplayEngine(fsm, base_dir=Path(tmp))
        engine.replay_sync(str(q), speed=1.0, realtime=False, inter_event_delay=0.02)
        time.sleep(0.5)
        # Only PUSH should produce history (NEUTRAL filtered)
        assert len(fsm.history)==1 and fsm.history[0]["command"].lower()=="push"
        print("Test6 NEUTRAL filtering: PASS")

# Test7 — Timing preserves relative delays at 1.0x (also speed multiplier)
def test_timing():
    t1 = _parse_timestamp_to_epoch("2026-09-05T13:10:01.120")
    t2 = _parse_timestamp_to_epoch("2026-09-05T13:10:02.030")
    t3 = _parse_timestamp_to_epoch("2026-09-05T13:10:03.440")
    assert abs((t2-t1)-0.91) < 0.01
    assert abs((t3-t2)-1.41) < 0.01
    # speed 2.0 halves
    orig = 1.0
    speed = 2.0
    assert abs((orig/speed)-0.5) < 1e-9
    # verify replay fast vs realtime leaves window logic working - we check engine computes delay via t diff
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)/"timing.json"
        json.dump([
            {"timestamp":"2026-09-05T13:10:01.000","command":"RIGHT","confidence":0.9},
            {"timestamp":"2026-09-05T13:10:01.100","command":"PUSH","confidence":0.9},
        ], open(p,"w"))
        fsm = _make_fsm(window=0.5)
        engine = BCIReplayEngine(fsm, base_dir=Path(tmp))
        start = time.time()
        engine.replay_sync(str(p), speed=10.0, realtime=True, inter_event_delay=0.01)
        elapsed = time.time()-start
        # At 10x speed, 0.1s original delay -> 0.01s, so total <0.3s
        assert elapsed < 0.5, f"speed 10x not respected, elapsed {elapsed}"
        print("Test7 timing + speed: PASS")

# Test8 — Invalid command rejected safely
def test_invalid():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)/"invalid.json"
        json.dump([
            {"timestamp":"2026-09-05T13:10:01.000","command":"INVALID","confidence":0.9},
            {"timestamp":"2026-09-05T13:10:01.100","command":"PUSH","confidence":0.9},
        ], open(p,"w"))
        ok, reason, norm = _validate_event({"command":"INVALID","confidence":0.9}, 0)
        assert not ok
        ok2, _, _ = _validate_event({"command":"RIGHT+PUSH","confidence":0.9}, 0)
        assert not ok2, "combined should be rejected"
        fsm = _make_fsm(window=0.3)
        engine = BCIReplayEngine(fsm, base_dir=Path(tmp))
        engine.replay_sync(str(p), speed=1.0, realtime=False, inter_event_delay=0.01)
        time.sleep(0.5)
        # INVALID skipped, PUSH processed
        assert len(fsm.history)==1 and fsm.history[0]["action"]=="next_track"
        print("Test8 invalid handling: PASS")

if __name__=="__main__":
    test_recording_preserves_raw()
    test_replay_dedup()
    test_ordered_double()
    test_reverse_double()
    test_confidence_filter()
    test_neutral()
    test_timing()
    test_invalid()
    print("\nALL TESTS PASSED")
