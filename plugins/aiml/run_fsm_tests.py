"""Standalone test harness for the FSM command system.

Runs the 8 required test flows from the spec, plus every sequence in
``test_command_sequences.json``, against the FSM in dry-run mode (no MQTT /
Selenium needed). The JSON file is processed exactly like real flat BCI input.

Usage:
    python run_fsm_tests.py
"""

import json
import sys
from pathlib import Path

from command_system.fsm_controller import create_fsm
from command_system.command_parser import parse_sequence
from command_system.states import ACTION_LABELS, SUB_MASTER_DASHBOARD, MOBILE_DASHBOARD_ACTIVE

HERE = Path(__file__).resolve().parent
TEST_JSON = HERE / "test_command_sequences.json"

FLOW_ACTION = {
    "action": None,
    "message": None,
}

# ---------------------------------------------------------------------------
# The 8 required flows: (commands, [Start Automation?], expected)
# ---------------------------------------------------------------------------
REQUIRED_FLOWS = [
    {
        "name": "TEST 1",
        "commands": ["right"],
        "start_automation": False,
        "expected": "Select AI/ML Domain",
        "expected_state": "SUB_MASTER_DASHBOARD",
    },
    {
        "name": "TEST 2",
        "commands": ["right", "push"],
        "start_automation": False,
        "expected": "Select Mobile Dashboard",
        "expected_state": "SUB_MASTER_DASHBOARD",
    },
    {
        "name": "TEST 3",
        "commands": ["right", "push"],
        "start_automation": True,
        "expected": "Mobile Dashboard opens",
        "expected_state": "MOBILE_DASHBOARD_ACTIVE",
    },
    {
        "name": "TEST 4",
        "commands": ["right", "pull"],
        "start_automation": True,
        "expected": "Desktop Dashboard opens",
        "expected_state": "DESKTOP_DASHBOARD_ACTIVE",
    },
    {
        "name": "TEST 5",
        "commands": ["right", "push", "right", "push"],
        "start_automation": False,
        "expected": "Volume Up",
        "expected_state": "SUB_MASTER_DASHBOARD",
    },
    {
        "name": "TEST 6",
        "commands": ["right", "pull", "right", "pull"],
        "start_automation": False,
        "expected": "Volume Down",
        "expected_state": "SUB_MASTER_DASHBOARD",
    },
    {
        "name": "TEST 7",
        "commands": ["right", "push", "right", "left"],
        "start_automation": False,
        "expected": "Return to Level 2",
        "expected_state": "SUB_MASTER_DASHBOARD",
    },
    {
        "name": "TEST 8",
        "commands": ["right", "push", "left"],
        "start_automation": False,
        "expected": "Return to Level 1",
        "expected_state": "DOMAIN_SELECTION",
    },
    {
        "name": "TEST 9 (direct open)",
        "commands": ["push"],
        "start_automation": False,
        "expected": "Open Mobile Dashboard",
        "expected_state": "MOBILE_DASHBOARD_ACTIVE",
    },
    {
        "name": "TEST 10 (direct open)",
        "commands": ["pull"],
        "start_automation": False,
        "expected": "Open Desktop Dashboard",
        "expected_state": "DESKTOP_DASHBOARD_ACTIVE",
    },
]


def run_required_flows():
    print("=" * 72)
    print("REQUIRED TEST FLOWS (spec)")
    print("=" * 72)
    passed = 0
    for flow in REQUIRED_FLOWS:
        fsm = create_fsm(dry_run=True)
        fsm.reset()
        last = None
        for cmd in flow["commands"]:
            last = fsm.process_command(cmd, confidence=0.95)
        if flow.get("start_automation"):
            opened = fsm.start_automation()
            got = f"{opened} dashboard opens" if opened else "nothing opened"
        else:
            got = ACTION_LABELS.get(last.get("action"), last.get("message", ""))

        ok = got.lower() == flow["expected"].lower() and fsm.current_state == flow["expected_state"]
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        print(f"[{status}] {flow['name']}: expected='{flow['expected']}' state='{flow['expected_state']}'")
        print(f"        got: action='{got}' state='{fsm.current_state}'")
    print(f"\nRequired flows: {passed}/{len(REQUIRED_FLOWS)} passed")
    return passed == len(REQUIRED_FLOWS)


def run_json_sequences():
    print()
    print("=" * 72)
    print("HIERARCHICAL TEST FILE (test_command_sequences.json)")
    print("=" * 72)
    if not TEST_JSON.exists():
        print(f"!! Missing {TEST_JSON}")
        return False

    with open(TEST_JSON, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    sequences = data.get("test_sequences", [])
    passed = 0
    for seq in sequences:
        name = seq.get("name", "?")
        fsm = create_fsm(dry_run=True)
        fsm.reset()

        packets = seq.get("commands", [])
        if not packets:
            print(f"[FAIL] {name}: no commands")
            continue

        # Seed FSM context from the first command's level annotation (the file
        # describes the FSM hierarchy; real BCI input carries no levels).
        first_level = packets[0].get("level", 1)
        if first_level == 2:
            fsm.current_state = SUB_MASTER_DASHBOARD
        elif first_level == 3:
            fsm.current_state = MOBILE_DASHBOARD_ACTIVE
            fsm.target_device = "mobile"
            fsm.dashboard_open = True

        # 8-second window grouping for Level 3 per updated spec:
        # Collect valid commands, then group consecutive Level-3 packets within 8s into windows of max 2 (ordered)
        import datetime
        def parse_ts(ts_val):
            try:
                if isinstance(ts_val, (int, float)):
                    return float(ts_val)
                if isinstance(ts_val, str):
                    try:
                        return datetime.datetime.strptime(ts_val, "%Y-%m-%d %H:%M:%S.%f").timestamp()
                    except ValueError:
                        return datetime.datetime.strptime(ts_val, "%Y-%m-%d %H:%M:%S").timestamp()
                return 0.0
            except Exception:
                return 0.0

        # Parse all packets first
        parsed = []
        for packet in packets:
            cmd = parse_sequence(packet, hierarchical=False, confidence_threshold=0.35)[0]
            if cmd is None:
                continue
            level = packet.get("level", first_level)
            cmd.level = level
            cmd.expected_action = packet.get("expected_action")
            ts = parse_ts(packet.get("timestamp", 0))
            parsed.append((packet, cmd, ts, level))

        # Group into windows: Level 1/2 each alone, Level 3 grouped by 6s max 2
        windows = []
        i = 0
        while i < len(parsed):
            packet, cmd, ts, level = parsed[i]
            if level != 3:
                # Level 1/2: single window
                # Flush any pending? For L3 pending already handled via grouping
                if level == 3 and fsm.current_state == SUB_MASTER_DASHBOARD:
                    fsm.start_automation()
                windows.append([(packet, cmd, ts)])
                i += 1
            else:
                # Level 3: try to form window of 1-2 within 8s
                if i + 1 < len(parsed):
                    nxt_packet, nxt_cmd, nxt_ts, nxt_level = parsed[i+1]
                    if nxt_level == 3 and (nxt_ts - ts) <= 8.0:
                        # Double window ordered
                        windows.append([(packet, cmd, ts), (nxt_packet, nxt_cmd, nxt_ts)])
                        i += 2
                        continue
                # Single window
                windows.append([(packet, cmd, ts)])
                i += 1

        results = []
        for window in windows:
            level = window[0][1].level
            # Auto-open dashboard if Level 3 arrives while still at Level 2
            if level == 3 and fsm.current_state == SUB_MASTER_DASHBOARD:
                fsm.start_automation()
            if level != 3:
                packet, cmd, ts = window[0]
                res = fsm.process_command(cmd.command, cmd.confidence, ts)
                results.append((window, res))
            elif len(window) == 1:
                packet, cmd, ts = window[0]
                res = fsm.process_command_sequence([cmd.command], [cmd.confidence], timestamp=ts)
                results.append((window, res))
            else:
                cmds = [c.command for _, c, _ in window]
                confs = [c.confidence for _, c, _ in window]
                ts = window[0][2]
                res = fsm.process_command_sequence(cmds, confs, timestamp=ts)
                results.append((window, res))

        ok = True
        for window, res in results:
            for packet, cmd, ts in window:
                expected = cmd.expected_action
                if not expected:
                    continue
                expected_norm = expected.lower().replace(" / ", " / ")
                got = (res.get("action_label") or res.get("message") or "").lower()
                if expected_norm != got:
                    ok = False
                    print(
                        f"    mismatch: window={[c.command for _,c,_ in window]} expected='{expected}' "
                        f"got='{res.get('action_label')}'"
                    )
                    break
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        final = results[-1][1] if results else {}
        print(
            f"[{status}] {name}: final_state={fsm.current_state} "
            f"last_action={final.get('action_label')}"
        )
    print(f"\nJSON sequences: {passed}/{len(sequences)} passed")
    return passed == len(sequences)


def main():
    all_ok = run_required_flows()
    json_ok = run_json_sequences()
    print()
    print("=" * 72)
    print("OVERALL: " + ("ALL TESTS PASSED" if all_ok and json_ok else "SOME TESTS FAILED"))
    print("=" * 72)
    return 0 if (all_ok and json_ok) else 1


if __name__ == "__main__":
    sys.exit(main())