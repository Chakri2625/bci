"""
test_state_machine.py
Comprehensive verification test suite for Python BCI State Machine:
- Temporal Window Framing Control (Deferred execution after window finishes)
- Framing cancellation via PUSH + PULL / API
- Persistent Control Mode (No automatic menu timeout)
- Single-fire latching within customizable time windows
- Combination command detection: PUSH + PULL -> BACK (Return to Menu / Cancel Framing)
- Appliance selection & actuator toggling
- Dynamic config updates
"""

import sys
import time
import asyncio

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from state_machine import BCIStateMachine

print("=== RUNNING PYTHON BCI STATE MACHINE TESTS ===")

sm = BCIStateMachine(
    power_threshold=0.3,
    debounce_ms=30,
    single_fire_window_ms=250,
    combo_window_ms=500,
    framing_window_ms=200,  # Fast 200ms for testing
    framing_enabled=True,
    auto_return_timeout_ms=0,
)

test_passed = 0
test_failed = 0


def assert_test(condition: bool, message: str):
    global test_passed, test_failed
    if condition:
        print(f"[PASS] {message}")
        test_passed += 1
    else:
        print(f"[FAIL] {message}")
        test_failed += 1


dispatched_commands = []
combo_events = []
suppressed_events = []
framing_started_events = []
framing_executed_events = []
framing_cancelled_events = []

sm.on("actuator_command", lambda cmd: dispatched_commands.append(cmd))
sm.on("combo_triggered", lambda evt: combo_events.append(evt))
sm.on("single_fire_suppressed", lambda evt: suppressed_events.append(evt))
sm.on("framing_window_started", lambda evt: framing_started_events.append(evt))
sm.on("framing_executed", lambda evt: framing_executed_events.append(evt))
sm.on("framing_cancelled", lambda evt: framing_cancelled_events.append(evt))


async def run_tests():
    global test_passed, test_failed

    # -------------------------------------------------------------
    # Test Group 1: Temporal Framing Window (Deferred Execution)
    # -------------------------------------------------------------
    assert_test(sm.current_state == "SELECT_APPLIANCE", "Initial state is SELECT_APPLIANCE")
    assert_test(sm.selected_device is None, "Initial selected device is None")

    # Send 'push' (Select Light) -> Enters Temporal Framing Window
    await asyncio.sleep(0.04)
    sm.process_mental_command("push", 0.85)

    assert_test(sm._pending_framed_command is not None, "Command entered Temporal Framing Window (pending)")
    assert_test(sm.selected_device is None, "Device is NOT selected yet (held during time frame)")
    assert_test(len(framing_started_events) == 1, "Emitted framing_window_started event")

    # Wait for the framing window (200ms) to complete
    print("Waiting for temporal framing window (0.25s)...")
    await asyncio.sleep(0.25)

    assert_test(sm.selected_device == "light", "Command EXECUTED after time frame completed (Light selected)")
    assert_test(sm.current_state == "CONTROL_DEVICE", "State transitioned to CONTROL_DEVICE after time frame")
    assert_test(len(framing_executed_events) == 1, "Emitted framing_executed event")

    # -------------------------------------------------------------
    # Test Group 2: Temporal Framing Cancellation
    # -------------------------------------------------------------
    sm.process_mental_command("neutral", 0.0)
    await asyncio.sleep(0.04)
    sm.process_mental_command("right", 0.85)  # Turn Light ON (starts framing)

    assert_test(sm._pending_framed_command is not None, "Actuator ON command entered Temporal Framing Window")
    assert_test(sm.device_states["light"] == "OFF", "Actuator state NOT applied yet during time frame")

    # Cancel before window finishes
    sm.cancel_framing_window("test_cancel")
    assert_test(sm._pending_framed_command is None, "Framing window successfully cancelled")
    assert_test(len(framing_cancelled_events) == 1, "Emitted framing_cancelled event")

    # Wait past window duration and ensure command was NOT executed
    await asyncio.sleep(0.25)
    assert_test(sm.device_states["light"] == "OFF", "Command was NOT executed after cancellation")

    # -------------------------------------------------------------
    # Test Group 3: Direct Actuator Execution when Framing Completes
    # -------------------------------------------------------------
    sm.process_mental_command("neutral", 0.0)
    await asyncio.sleep(0.04)
    sm.process_mental_command("right", 0.85)
    await asyncio.sleep(0.25)
    assert_test(sm.device_states["light"] == "ON", "Actuator state turned ON after framing window finished")

    # -------------------------------------------------------------
    # Test Group 4: Single-Fire Latch Window (Takes only 1 time)
    # -------------------------------------------------------------
    sm.process_mental_command("neutral", 0.0)
    await asyncio.sleep(0.04)
    sm.process_mental_command("left", 0.85)  # Turn Light OFF (framed)
    # Immediately send consecutive 'left' frames in same window
    sm.process_mental_command("left", 0.85)
    assert_test(
        len(suppressed_events) >= 1,
        "Sustained continuous 'left' stream suppressed by single-fire latch window",
    )

    # Relax to neutral -> resets latch
    sm.process_mental_command("neutral", 0.0)
    assert_test(sm._last_latched_action is None, "Relaxing to neutral resets single-fire latch")
    await asyncio.sleep(0.25)  # Wait for left to finish executing

    # -------------------------------------------------------------
    # Test Group 5: Combination Command (PUSH + PULL -> BACK)
    # -------------------------------------------------------------
    await asyncio.sleep(0.04)
    sm.process_mental_command("push", 0.85)
    assert_test(sm._combo_first_action == "push", "Combo window opened on PUSH")

    sm.process_mental_command("neutral", 0.0)
    await asyncio.sleep(0.04)
    res = sm.process_mental_command("pull", 0.85)

    assert_test(
        len(combo_events) == 1 and combo_events[0]["combo"] == "PUSH+PULL",
        "Combo event PUSH+PULL detected and triggered",
    )
    assert_test(
        sm.current_state == "SELECT_APPLIANCE" and sm.selected_device is None,
        "Combo PUSH+PULL executed BACK (returned to SELECT_APPLIANCE and reset selection)",
    )

    # -------------------------------------------------------------
    # Test Group 6: Domain Locking & Window Framing Cancellation via PUSH + PULL
    # -------------------------------------------------------------
    sm.process_mental_command("neutral", 0.0)
    await asyncio.sleep(0.04)
    # Select Pump (left)
    sm.process_mental_command("left", 0.8)
    await asyncio.sleep(0.25)  # Wait for framing to finish
    assert_test(sm.selected_device == "pump", "Selected device is PUMP")
    assert_test(sm.current_state == "CONTROL_DEVICE", "Current state is CONTROL_DEVICE")

    # In locked Pump domain, send 'pull' directly (without push) -> must NOT switch to fan!
    sm.process_mental_command("neutral", 0.0)
    await asyncio.sleep(0.04)
    sm.process_mental_command("pull", 0.85)
    assert_test(
        sm.selected_device == "pump" and sm.current_state == "CONTROL_DEVICE",
        "Domain is locked: 'pull' alone did not switch device away from PUMP",
    )

    # Start an Actuator command inside framing window (right -> Turn Pump ON)
    sm.process_mental_command("neutral", 0.0)
    await asyncio.sleep(0.04)
    sm.process_mental_command("right", 0.85)
    assert_test(sm._pending_framed_command is not None, "Actuator command entered Temporal Framing Window")

    # Cancel the active window framing and exit domain using PUSH + PULL
    sm.process_mental_command("neutral", 0.0)
    await asyncio.sleep(0.04)
    sm.process_mental_command("push", 0.85)
    assert_test(sm._combo_first_action == "push", "PUSH opened combo window during framing")

    sm.process_mental_command("neutral", 0.0)
    await asyncio.sleep(0.04)
    sm.process_mental_command("pull", 0.85)

    assert_test(
        sm._pending_framed_command is None,
        "Framing window was cancelled by PUSH + PULL combo",
    )
    assert_test(
        sm.current_state == "SELECT_APPLIANCE" and sm.selected_device is None,
        "PUSH + PULL successfully exited the locked PUMP domain back to SELECT_APPLIANCE",
    )
    # Wait past framing duration to verify Pump was NOT turned ON
    await asyncio.sleep(0.25)
    assert_test(sm.device_states["pump"] == "OFF", "Pump remained OFF after framing cancellation")

    # -------------------------------------------------------------
    # Test Group 7: Configuration Customization (Customized Seconds)
    # -------------------------------------------------------------
    sm.update_config({
        "framingWindowMs": 4500,
        "framingEnabled": True,
        "singleFireWindowMs": 2000,
        "comboWindowMs": 3500,
        "powerThreshold": 0.45,
    })
    cfg = sm.get_config()
    assert_test(cfg["framingWindowMs"] == 4500, "Updated framingWindowMs to 4500ms (4.5s)")
    assert_test(cfg["framingEnabled"] is True, "Framing enabled is True")
    assert_test(cfg["singleFireWindowMs"] == 2000, "Updated singleFireWindowMs to 2000ms")
    assert_test(cfg["comboWindowMs"] == 3500, "Updated comboWindowMs to 3500ms")
    assert_test(cfg["powerThreshold"] == 0.45, "Updated powerThreshold to 0.45")

    # Test Custom Duration: Set to 300ms (0.3s) and verify execution timing
    sm.update_config({"framingWindowMs": 300})
    assert_test(sm.framing_window_ms == 300, "Dynamically customized window frame duration to 300ms")

    # Test Custom Duration: Set to 6000ms (6.0s)
    sm.update_config({"framingWindowMs": 6000})
    assert_test(sm.framing_window_ms == 6000, "Dynamically customized window frame duration to 6000ms (6.0s)")

    print("\n=======================================")
    print(f"TEST SUMMARY: {test_passed} Passed, {test_failed} Failed")
    print("=======================================")

    if test_failed > 0:
        exit(1)


if __name__ == "__main__":
    asyncio.run(run_tests())
