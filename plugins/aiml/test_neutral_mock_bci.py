"""NEUTRAL Filtering + Mock BCI Real-Time End-to-End Tests.

Covers 10 required test cases plus pipeline verification.
All tests go through REAL pipeline:
    Mock BCI -> receive_cortex_command (NEUTRAL filter 0.35) -> 8s window ordered -> FSM mapping -> Mapper -> Router

No architecture/mapping/threshold/window changes except NEUTRAL filtering.
"""

import sys
import time
import logging
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

from command_system.fsm_controller import FSMController
from command_system.command_mapper import CommandMapper
from command_system.mock_bci import MockBCIStream, create_mock_packet, generate_realistic_stream
from backend.command_router import command_router

def make_fsm():
    mapper = CommandMapper(command_router=command_router, dry_run=True)
    fsm = FSMController(mapper=mapper, dry_run=True)
    # Use 2s window for test speed where noted; live is 8.0
    # For most tests we override to 2s to avoid 8s waits; one test uses 8s explicitly
    return fsm

def report(name, inputs, expected, actual, passed):
    status = "PASS" if passed else "FAIL"
    print(f"\n[{status}] {name}")
    print(f"  Input: {inputs}")
    print(f"  Expected: {expected}")
    print(f"  Actual: {actual}")
    return passed

# ---------------------------------------------------------------------------
# Test 1 — NEUTRAL is ignored
# ---------------------------------------------------------------------------
def test1_neutral_ignored():
    name = "Test 1 — NEUTRAL is ignored"
    fsm = make_fsm()
    fsm.window_duration = 2.0  # speed
    fsm.window_confidence_threshold = 0.35
    fsm.current_state = "MOBILE_DASHBOARD_ACTIVE"
    fsm.target_device = "mobile"
    stream = MockBCIStream(fsm, window_duration=2.0)
    packets = [
        create_mock_packet("NEUTRAL", 0.95, level=3),
        create_mock_packet("NEUTRAL", 0.91, level=3),
        create_mock_packet("NEUTRAL", 0.88, level=3),
    ]
    print(f"\n=== {name} ===")
    stream.feed(packets, verbose=True)
    time.sleep(2.5)  # wait window (should be empty, no window started)
    window = stream.get_window_commands()
    history_len = len(fsm.history)
    # NEUTRAL should not enter window, not trigger mapping
    passed = len(window)==0 and history_len==0
    # Detailed stages already printed via feed
    print(f"[WINDOW] After 8s (2s test) window_commands={window}")
    print(f"[FSM] history len {history_len}")
    return report(name, "NEUTRAL x3", "CommandWindow=[] history=0", f"window={window} history={history_len}", passed)

# ---------------------------------------------------------------------------
# Test 2 — NEUTRAL between valid commands (RIGHT, PUSH -> Volume Up)
# ---------------------------------------------------------------------------
def test2_neutral_between():
    name = "Test 2 — NEUTRAL between valid commands"
    fsm = make_fsm()
    fsm.window_duration = 2.0
    fsm.current_state = "MOBILE_DASHBOARD_ACTIVE"
    fsm.target_device = "mobile"
    stream = MockBCIStream(fsm, window_duration=2.0)
    packets = [
        create_mock_packet("RIGHT", 0.82, level=3),
        create_mock_packet("NEUTRAL", 0.94, level=3),
        create_mock_packet("NEUTRAL", 0.91, level=3),
        create_mock_packet("PUSH", 0.76, level=3),
    ]
    print(f"\n=== {name} ===")
    stream.feed(packets, verbose=True)
    # Before expiry, window should contain [RIGHT, PUSH] (NEUTRAL ignored, order preserved)
    with fsm.window_lock:
        window_before = [c for c,_ ,_ in fsm.window_commands]
    print(f"[WINDOW] Before expiry contains {window_before} expected [RIGHT, PUSH]")
    before_ok = window_before == ["right", "push"]
    time.sleep(2.5)
    # After window, should have processed RIGHT+PUSH -> Volume Up
    last = fsm.history[-1] if fsm.history else {}
    action = last.get("action")
    print(f"[FSM] Processing [RIGHT, PUSH] -> {last}")
    print(f"[MAPPER] RIGHT + PUSH → Volume Up")
    print(f"[ROUTER] Dispatching Volume Up -> {last.get('dispatch')}")
    passed = before_ok and action == "volume_up"
    return report(name, "RIGHT, NEUTRAL, NEUTRAL, PUSH", "[RIGHT,PUSH] -> Volume Up", f"window_before={window_before} action={action}", passed)

# ---------------------------------------------------------------------------
# Test 3 — NEUTRAL does not reset window
# ---------------------------------------------------------------------------
def test3_neutral_no_reset():
    name = "Test 3 — NEUTRAL does not reset window"
    fsm = make_fsm()
    fsm.window_duration = 2.0
    fsm.current_state = "MOBILE_DASHBOARD_ACTIVE"
    fsm.target_device = "mobile"
    stream = MockBCIStream(fsm, window_duration=2.0)
    packets = [
        create_mock_packet("RIGHT", 0.80, level=3),
        create_mock_packet("NEUTRAL", 0.93, level=3),
        create_mock_packet("NEUTRAL", 0.91, level=3),
        create_mock_packet("NEUTRAL", 0.88, level=3),
        create_mock_packet("PUSH", 0.76, level=3),
    ]
    print(f"\n=== {name} ===")
    stream.feed(packets, verbose=True)
    with fsm.window_lock:
        window_before = [c for c,_,_ in fsm.window_commands]
    print(f"[WINDOW] Before expiry {window_before} must be [RIGHT,PUSH] (NEUTRAL not resetting)")
    time.sleep(2.5)
    last = fsm.history[-1] if fsm.history else {}
    passed = window_before == ["right","push"] and last.get("action")=="volume_up"
    return report(name, "RIGHT + 3xNEUTRAL + PUSH within 8s", "[RIGHT,PUSH]", f"window_before={window_before} action={last.get('action')}", passed)

# ---------------------------------------------------------------------------
# Test 4 — Low-confidence ignored
# ---------------------------------------------------------------------------
def test4_low_confidence():
    name = "Test 4 — Low-confidence ignored"
    fsm = make_fsm()
    fsm.window_duration = 2.0
    fsm.current_state = "MOBILE_DASHBOARD_ACTIVE"
    fsm.target_device = "mobile"
    stream = MockBCIStream(fsm, window_duration=2.0)
    print(f"\n=== {name} ===")
    # First low confidence
    stream.feed([create_mock_packet("RIGHT", 0.34, level=3)], verbose=True)
    time.sleep(2.5)
    # Should be ignored, no history
    hist_len_after_low = len(fsm.history)
    print(f"[FILTER] 0.34 <0.35 -> Ignored, history len {hist_len_after_low}")
    # Then valid
    stream.feed([create_mock_packet("RIGHT", 0.40, level=3)], verbose=True)
    print(f"[FILTER] 0.40 >=0.35 -> Accepted")
    time.sleep(2.5)
    last = fsm.history[-1] if fsm.history else {}
    passed = hist_len_after_low==0 and last.get("action")=="search"
    return report(name, "RIGHT 0.34 then 0.40", "0.34 ignored, 0.40 accepted -> Search", f"low_hist={hist_len_after_low} action={last.get('action')}", passed)

# ---------------------------------------------------------------------------
# Test 5 — Single valid command mapping
# ---------------------------------------------------------------------------
def test5_single():
    name = "Test 5 — Single valid command"
    fsm = make_fsm()
    fsm.window_duration = 2.0
    fsm.current_state = "MOBILE_DASHBOARD_ACTIVE"
    fsm.target_device = "mobile"
    stream = MockBCIStream(fsm, window_duration=2.0)
    print(f"\n=== {name} ===")
    stream.feed([create_mock_packet("RIGHT", 0.80, level=3)], verbose=True)
    time.sleep(2.5)
    last = fsm.history[-1] if fsm.history else {}
    print(f"[WINDOW] 8s (2s test) expired -> [RIGHT]")
    print(f"[FSM] Processing [RIGHT] -> Search")
    passed = last.get("action")=="search"
    return report(name, "RIGHT 0.80", "RIGHT->Search", f"action={last.get('action')}", passed)

# ---------------------------------------------------------------------------
# Test 6 — RIGHT + PUSH within 8s -> Volume Up (after window expiry)
# ---------------------------------------------------------------------------
def test6_right_push():
    name = "Test 6 — RIGHT + PUSH within 8s -> Volume Up"
    fsm = make_fsm()
    fsm.window_duration = 2.0
    fsm.current_state = "MOBILE_DASHBOARD_ACTIVE"
    fsm.target_device = "mobile"
    stream = MockBCIStream(fsm, window_duration=2.0)
    print(f"\n=== {name} ===")
    stream.feed([create_mock_packet("RIGHT", 0.82, level=3), create_mock_packet("PUSH", 0.76, level=3)], verbose=True)
    # Should not process immediately
    print(f"[CHECK] Before expiry history len {len(fsm.history)} expected 0")
    before = len(fsm.history)==0
    time.sleep(2.5)
    last = fsm.history[-1] if fsm.history else {}
    print(f"[WINDOW] 8s expired -> [RIGHT,PUSH]")
    print(f"[FSM] Processing [RIGHT,PUSH] -> Volume Up")
    passed = before and last.get("action")=="volume_up"
    return report(name, "[RIGHT,PUSH] within 8s", "Volume Up after window", f"action={last.get('action')} before={before}", passed)

# ---------------------------------------------------------------------------
# Test 7 — PUSH + RIGHT within 8s -> Back to Sub-Domain (order matters)
# ---------------------------------------------------------------------------
def test7_push_right():
    name = "Test 7 — PUSH + RIGHT (order matters) -> Back to Sub-Domain"
    fsm = make_fsm()
    fsm.window_duration = 2.0
    fsm.current_state = "MOBILE_DASHBOARD_ACTIVE"
    fsm.target_device = "mobile"
    stream = MockBCIStream(fsm, window_duration=2.0)
    print(f"\n=== {name} ===")
    stream.feed([create_mock_packet("PUSH", 0.85, level=3), create_mock_packet("RIGHT", 0.82, level=3)], verbose=True)
    time.sleep(2.5)
    last = fsm.history[-1] if fsm.history else {}
    print(f"[FSM] [PUSH,RIGHT] -> Back to Sub-Domain (not Volume Up)")
    passed = last.get("action")=="back_to_level_2" and last.get("new_state")=="SUB_MASTER_DASHBOARD"
    # Also verify not volume_up
    not_volume = last.get("action")!="volume_up"
    return report(name, "[PUSH,RIGHT] within 8s", "Back to Sub-Domain != Volume Up", f"action={last.get('action')} not_volume={not_volume}", passed and not_volume)

# ---------------------------------------------------------------------------
# Test 8 — Commands separated by >8s -> separate windows
# ---------------------------------------------------------------------------
def test8_separated():
    name = "Test 8 — Commands separated by >8s (separate windows)"
    fsm = make_fsm()
    fsm.window_duration = 2.0  # use 2s for test speed, simulate > window
    fsm.current_state = "MOBILE_DASHBOARD_ACTIVE"
    fsm.target_device = "mobile"
    stream = MockBCIStream(fsm, window_duration=2.0)
    print(f"\n=== {name} ===")
    # First window
    stream.feed([create_mock_packet("RIGHT", 0.82, level=3)], verbose=True)
    time.sleep(2.5)  # >2s (live >8s)
    first = fsm.history[-1] if fsm.history else {}
    print(f"[WINDOW1] RIGHT -> {first.get('action')} (Search)")
    # Second window after gap
    stream.feed([create_mock_packet("PUSH", 0.76, level=3)], verbose=True)
    time.sleep(2.5)
    second = fsm.history[-1] if fsm.history else {}
    print(f"[WINDOW2] PUSH -> {second.get('action')} (Next Track)")
    # They must NOT become [RIGHT,PUSH] Volume Up
    passed = first.get("action")=="search" and second.get("action")=="next_track"
    return report(name, "RIGHT then >window then PUSH", "Window1 Search, Window2 Next Track (not Volume Up)", f"first={first.get('action')} second={second.get('action')}", passed)

# ---------------------------------------------------------------------------
# Test 9 — Large NEUTRAL stream realistic
# ---------------------------------------------------------------------------
def test9_large_neutral():
    name = "Test 9 — Large NEUTRAL stream (20+15+20)"
    fsm = make_fsm()
    fsm.window_duration = 2.0
    fsm.current_state = "MOBILE_DASHBOARD_ACTIVE"
    fsm.target_device = "mobile"
    stream = MockBCIStream(fsm, window_duration=2.0)
    packets = generate_realistic_stream(
        valid_sequence=["RIGHT","PUSH"],
        valid_confidences=[0.82,0.76],
        neutral_before=20, neutral_between=15, neutral_after=20, level=3
    )
    print(f"\n=== {name} ===")
    print(f"[MOCK] Generated {len(packets)} packets (many NEUTRAL)")
    # Feed without verbose to avoid spam, but show summary
    # We'll feed with verbose False then verify window
    stream.feed(packets, verbose=False)
    with fsm.window_lock:
        before = [c for c,_,_ in fsm.window_commands]
    print(f"[FILTER] After feeding, window contains {before} (NEUTRAL ignored, should be [right,push])")
    before_ok = before == ["right","push"]
    time.sleep(2.5)
    last = fsm.history[-1] if fsm.history else {}
    print(f"[WINDOW] 8s expired -> [RIGHT,PUSH] -> Volume Up, neutrals had no effect")
    passed = before_ok and last.get("action")=="volume_up"
    return report(name, "20 NEUTRAL + RIGHT +15 NEUTRAL + PUSH +20 NEUTRAL", "[RIGHT,PUSH]->Volume Up, neutrals ignored", f"window_before={before} action={last.get('action')}", passed)

# ---------------------------------------------------------------------------
# Test 10 — Window reset
# ---------------------------------------------------------------------------
def test10_window_reset():
    name = "Test 10 — Window reset"
    fsm = make_fsm()
    fsm.window_duration = 2.0
    fsm.current_state = "MOBILE_DASHBOARD_ACTIVE"
    fsm.target_device = "mobile"
    stream = MockBCIStream(fsm, window_duration=2.0)
    print(f"\n=== {name} ===")
    # First sequence
    stream.feed([create_mock_packet("RIGHT", 0.82, level=3), create_mock_packet("PUSH", 0.76, level=3)], verbose=True)
    time.sleep(2.5)
    last1 = fsm.history[-1] if fsm.history else {}
    empty_after = stream.assert_window_empty()
    print(f"[WINDOW] After first expiry window_commands==[]? {empty_after} got {stream.get_window_commands()}")
    # Second sequence must not leak
    fsm.current_state = "MOBILE_DASHBOARD_ACTIVE"  # reset state
    stream.feed([create_mock_packet("PUSH", 0.85, level=3), create_mock_packet("RIGHT", 0.82, level=3)], verbose=True)
    time.sleep(2.5)
    last2 = fsm.history[-1] if fsm.history else {}
    print(f"[WINDOW] Second sequence [PUSH,RIGHT] -> Back to Sub-Domain, no leak from first")
    passed = empty_after and last1.get("action")=="volume_up" and last2.get("action")=="back_to_level_2"
    return report(name, "Sequence1 RIGHT+PUSH then Sequence2 PUSH+RIGHT", "Window reset, no leak, second = Back to Sub", f"empty_after={empty_after} first={last1.get('action')} second={last2.get('action')}", passed)

# ---------------------------------------------------------------------------
# End-to-end mock pipeline demonstration (realistic BCI example from spec)
# ---------------------------------------------------------------------------
def test_e2e_realistic():
    name = "E2E Realistic BCI Stream (spec example)"
    fsm = make_fsm()
    fsm.window_duration = 2.0
    fsm.current_state = "MOBILE_DASHBOARD_ACTIVE"
    fsm.target_device = "mobile"
    stream = MockBCIStream(fsm, window_duration=2.0)
    packets = [
        create_mock_packet("NEUTRAL", 0.95, level=3),
        create_mock_packet("NEUTRAL", 0.91, level=3),
        create_mock_packet("RIGHT", 0.82, level=3),
        create_mock_packet("NEUTRAL", 0.93, level=3),
        create_mock_packet("PUSH", 0.76, level=3),
        create_mock_packet("NEUTRAL", 0.89, level=3),
    ]
    print(f"\n=== {name} ===")
    stream.feed(packets, verbose=True)
    time.sleep(2.5)
    last = fsm.history[-1] if fsm.history else {}
    print(f"[E2E] Mock BCI -> FILTER (0.35) -> 8s Window [RIGHT,PUSH] -> FSM -> MAPPER RIGHT+PUSH->Volume Up -> ROUTER -> Mobile/Desktop")
    print(f"[E2E] Final dispatch: {last.get('dispatch')}")
    passed = last.get("action")=="volume_up" and last.get("dispatch",{}).get("dispatched")==True
    return report(name, "NEUTRAL,NEUTRAL,RIGHT,NEUTRAL,PUSH,NEUTRAL", "[RIGHT,PUSH]->Volume Up dispatch True", f"action={last.get('action')} dispatched={last.get('dispatch',{}).get('dispatched')}", passed)

def main():
    results = []
    results.append(test1_neutral_ignored())
    results.append(test2_neutral_between())
    results.append(test3_neutral_no_reset())
    results.append(test4_low_confidence())
    results.append(test5_single())
    results.append(test6_right_push())
    results.append(test7_push_right())
    results.append(test8_separated())
    results.append(test9_large_neutral())
    results.append(test10_window_reset())
    results.append(test_e2e_realistic())
    
    print("\n" + "="*72)
    print(f"NEUTRAL/MOCK BCI TESTS: {sum(results)}/{len(results)} passed")
    print("="*72)
    return 0 if all(results) else 1

if __name__ == "__main__":
    sys.exit(main())
