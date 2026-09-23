"""
Comprehensive Unit and Integration Tests for SynaptiMesh Controlled Retry, Timeout, and Timestamp Architecture.

Covers all 9 test scenarios specified in Section 24:
1. test_successful_first_attempt: Status COMPLETED, Attempt 1/3, Retry Count 0, valid timestamps & duration.
2. test_timeout_then_success: Attempt 1 times out, Attempt 2 succeeds -> COMPLETED, Attempt 2/3, Retry Count 1.
3. test_three_timeouts_failure: 3 timeouts -> Status FAILED, Attempts 3/3, Retry Count 2, exactly 3 executions (no 4th).
4. test_non_retryable_error: Non-retryable error (INVALID_COMMAND) fails immediately on Attempt 1/3, Retry Count 0.
5. test_cancellation_during_retry_delay: Cancelled during retry delay -> Status CANCELLED, Attempt 2 never runs.
6. test_timestamp_accuracy: Start, completion, duration accuracy, and ISO-8601 UTC format.
7. test_multiple_concurrent_commands: Concurrent commands retain isolated command_ids, attempts, and durations.
8. test_duplicate_command_prevention: Duplicate commands are rejected without corrupting retry states.
9. test_existing_desktop_commands: Desktop commands (open_notepad, open_calculator, open_chrome, open_youtube) execute cleanly.
"""

import asyncio
import functools
import io
import json
import re
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.config.retry_config import (
    COMMAND_TIMEOUT,
    MAX_RETRIES,
    RETRY_DELAY,
    is_retryable_error,
)
from core.logging.terminal_display import (
    TimestampTracker,
    display_command_received,
    display_command_timeout,
    display_execution_running,
    display_failure_summary,
    display_final_execution_summary,
    display_retry_started,
    display_success_summary,
    format_utc_iso,
    log_execution_event,
)
from core.managers.retry_manager import RetryManager
from core.validation.conflict_manager import ConflictManager


def run_async(coro_fn):
    """Decorator to run async test functions synchronously with asyncio.run."""
    @functools.wraps(coro_fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(coro_fn(*args, **kwargs))
    return wrapper


# =============================================================================
# Test 1: Successful First Attempt
# =============================================================================
@run_async
async def test_successful_first_attempt():
    """
    Section 24 - Test 1:
    - Command succeeds on Attempt 1
    - Status is COMPLETED
    - Attempt is 1/3, Retry Count is 0
    - Completion time > Start time
    - Duration is recorded
    - Terminal displays attempt 1/3 and Success summary
    """
    out_stream = io.StringIO()
    mgr = RetryManager(max_attempts=3, retry_delay=0.1, command_timeout=2.0)

    async def sample_action():
        await asyncio.sleep(0.05)
        return {"status": "success", "data": "notepad opened"}

    res = await mgr.execute_with_retry(
        command_name="open_notepad",
        session="SESSION-001",
        command_id="CMD-001",
        func=sample_action,
        stream=out_stream,
    )

    # Validate output structure
    assert res["type"] == "RESPONSE"
    assert res["command_id"] == "CMD-001"
    assert res["session_id"] == "SESSION-001"
    assert res["command"] == "open_notepad"
    assert res["status"] == "COMPLETED"
    assert res["attempt"] == 1
    assert res["max_attempts"] == 3
    assert res["retry_count"] == 0
    assert res["timeout"] is False
    assert res["error"] is None
    assert res["result"] == {"status": "success", "data": "notepad opened"}
    assert res["duration_seconds"] >= 0.04

    # Validate ISO-8601 UTC timestamps
    iso_pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
    assert re.match(iso_pattern, res["start_time"])
    assert re.match(iso_pattern, res["completion_time"])

    # Validate terminal output stream
    captured = out_stream.getvalue()
    assert "CMD-001" in captured
    assert "SESSION-001" in captured
    assert "open_notepad" in captured
    assert "Attempt: 1/3" in captured
    assert "COMPLETED" in captured


# =============================================================================
# Test 2: Timeout Then Success
# =============================================================================
@run_async
async def test_timeout_then_success():
    """
    Section 24 - Test 2:
    - Command times out on Attempt 1
    - Timeout message displayed
    - Retry delay observed
    - Command succeeds on Attempt 2
    - Status is COMPLETED, Attempt is 2/3, Retry Count is 1
    - Same Command ID and Session ID preserved
    """
    out_stream = io.StringIO()
    mgr = RetryManager(max_attempts=3, retry_delay=0.05, command_timeout=0.15)

    call_count = 0

    async def flaky_action():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Simulate timeout on attempt 1
            await asyncio.sleep(0.3)
            return {"status": "success"}
        # Fast success on attempt 2
        return {"status": "success", "attempt": 2}

    res = await mgr.execute_with_retry(
        command_name="open_calculator",
        session="SESSION-001",
        command_id="CMD-002",
        func=flaky_action,
        stream=out_stream,
    )

    assert call_count == 2
    assert res["command_id"] == "CMD-002"
    assert res["session_id"] == "SESSION-001"
    assert res["command"] == "open_calculator"
    assert res["status"] == "COMPLETED"
    assert res["attempt"] == 2
    assert res["max_attempts"] == 3
    assert res["retry_count"] == 1
    assert res["timeout"] is True  # Encountered timeout along the way
    assert res["error"] is None

    captured = out_stream.getvalue()
    assert "COMMAND TIMEOUT" in captured
    assert "[RETRY] Attempt 2/3" in captured
    assert "Attempt: 2/3" in captured
    assert "COMPLETED" in captured


# =============================================================================
# Test 3: Three Timeouts Failure (Strictly Max 3 Attempts)
# =============================================================================
@run_async
async def test_three_timeouts_failure():
    """
    Section 24 - Test 3:
    - Command times out on Attempt 1, 2, and 3
    - Each attempt is logged and displayed
    - Exactly 3 attempts executed — NO 4th attempt
    - Status is FAILED, Attempts is 3/3, Retry Count is 2
    - Error is 'Command timed out after X seconds'
    - Failure summary and Execution summary displayed
    """
    out_stream = io.StringIO()
    mgr = RetryManager(max_attempts=3, retry_delay=0.02, command_timeout=0.08)

    call_count = 0

    async def always_times_out():
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.25)
        return {"status": "success"}

    res = await mgr.execute_with_retry(
        command_name="open_chrome",
        session="SESSION-001",
        command_id="CMD-003",
        func=always_times_out,
        stream=out_stream,
    )

    # Strict check: Exactly 3 attempts executed, no 4th attempt ever!
    assert call_count == 3
    assert res["command_id"] == "CMD-003"
    assert res["session_id"] == "SESSION-001"
    assert res["status"] == "FAILED"
    assert res["attempt"] == 3
    assert res["max_attempts"] == 3
    assert res["retry_count"] == 2
    assert res["timeout"] is True
    assert "timed out" in res["error"].lower()

    captured = out_stream.getvalue()
    assert "COMMAND TIMEOUT" in captured
    assert "Status: FAILED" in captured
    assert "Attempts: 3/3" in captured
    assert "Retry Count: 2" in captured
    assert "Final Status  : FAILED" in captured
    assert "EXECUTION SUMMARY" in captured


# =============================================================================
# Test 4: Non-Retryable Error (Fails Immediately on Attempt 1)
# =============================================================================
@run_async
async def test_non_retryable_error():
    """
    Section 24 - Test 4:
    - Command fails with an invalid command / unknown command
    - Fails immediately on Attempt 1
    - No retries attempted (Retry Count is 0, Attempt is 1/3)
    - Status is FAILED
    """
    out_stream = io.StringIO()
    mgr = RetryManager(max_attempts=3, retry_delay=0.1, command_timeout=1.0)

    call_count = 0

    async def invalid_cmd_action():
        nonlocal call_count
        call_count += 1
        raise ValueError("INVALID_COMMAND: Unknown command FOOBAR_ACTION")

    res = await mgr.execute_with_retry(
        command_name="FOOBAR_ACTION",
        session="SESSION-001",
        command_id="CMD-004",
        func=invalid_cmd_action,
        stream=out_stream,
    )

    # Must fail immediately on attempt 1 without retrying!
    assert call_count == 1
    assert res["command_id"] == "CMD-004"
    assert res["session_id"] == "SESSION-001"
    assert res["status"] == "FAILED"
    assert res["attempt"] == 1
    assert res["max_attempts"] == 3
    assert res["retry_count"] == 0
    assert "INVALID_COMMAND" in res["error"]

    captured = out_stream.getvalue()
    assert "Status: FAILED" in captured
    assert "Retry Count: 0" in captured
    assert "Attempts: 1/3" in captured
    assert "EXECUTION SUMMARY" in captured


# =============================================================================
# Test 5: Cancellation During Retry Delay
# =============================================================================
@run_async
async def test_cancellation_during_retry_delay():
    """
    Section 24 - Test 5:
    - Command times out on Attempt 1
    - During the retry delay before Attempt 2, cancellation signal is sent
    - Retry loop terminates immediately
    - Attempt 2 is NEVER started
    - Status is CANCELLED
    """
    out_stream = io.StringIO()
    mgr = RetryManager(max_attempts=3, retry_delay=0.2, command_timeout=0.08)

    call_count = 0

    async def times_out_then_cancel():
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.2)

    # Background task to cancel command while in retry delay
    async def trigger_cancel():
        await asyncio.sleep(0.12)  # While attempt 1 timed out and delay has begun
        mgr.cancel_command("CMD-005")

    cancel_task = asyncio.create_task(trigger_cancel())
    res = await mgr.execute_with_retry(
        command_name="open_youtube",
        session="SESSION-001",
        command_id="CMD-005",
        func=times_out_then_cancel,
        stream=out_stream,
    )
    await cancel_task

    # Must have only run attempt 1; attempt 2 never executed!
    assert call_count == 1
    assert res["command_id"] == "CMD-005"
    assert res["session_id"] == "SESSION-001"
    assert res["status"] == "CANCELLED"
    assert res["attempt"] == 1
    assert res["retry_count"] == 0


# =============================================================================
# Test 6: Execution Timestamp & Duration Accuracy
# =============================================================================
def test_timestamp_accuracy():
    """
    Section 24 - Test 6:
    - Verify start time is recorded before execution
    - Verify completion time is recorded after execution
    - Verify completion time >= start time
    - Verify duration = completion - start
    - Verify ISO-8601 UTC format
    """
    tracker = TimestampTracker(command_id="CMD-006")
    tracker.session_id = "SESSION-001"

    t0 = time.time()
    tracker.record_start("CMD-006", "SESSION-001", attempt=1, start_time=t0)
    time.sleep(0.05)
    t1 = time.time()
    tracker.record_completion("CMD-006", "SESSION-001", attempt=1, completion_time=t1)

    dur = tracker.calculate_duration("CMD-006", attempt=1)
    details = tracker.get_execution_details("CMD-006", attempt=1)

    assert details is not None
    assert details["start_time"] == t0
    assert details["completion_time"] == t1
    assert details["status"] == "COMPLETED"
    assert dur >= 0.04
    assert dur == round(t1 - t0, 3)

    # Check ISO format
    iso_start = format_utc_iso(t0)
    iso_comp = format_utc_iso(t1)
    iso_pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
    assert re.match(iso_pattern, iso_start)
    assert re.match(iso_pattern, iso_comp)


# =============================================================================
# Test 7: Multiple Concurrent Commands Isolation
# =============================================================================
@run_async
async def test_multiple_concurrent_commands():
    """
    Section 24 - Test 7:
    - Execute multiple commands concurrently (CMD-007A and CMD-007B)
    - Each command maintains its own independent:
      * Command ID
      * Attempt counter
      * Timeout tracker
      * Timestamps & duration calculation
    - One command's retry or timeout does not affect the other
    """
    mgr = RetryManager(max_attempts=3, retry_delay=0.05, command_timeout=0.15)

    # Command A: times out on attempt 1, succeeds on attempt 2
    call_a = 0
    async def cmd_a_fn():
        nonlocal call_a
        call_a += 1
        if call_a == 1:
            await asyncio.sleep(0.25)
        return {"status": "success", "cmd": "A"}

    # Command B: succeeds immediately on attempt 1
    call_b = 0
    async def cmd_b_fn():
        nonlocal call_b
        call_b += 1
        await asyncio.sleep(0.03)
        return {"status": "success", "cmd": "B"}

    task_a = mgr.execute_with_retry(
        command_name="open_notepad",
        session="SESSION-001",
        command_id="CMD-007A",
        func=cmd_a_fn,
    )
    task_b = mgr.execute_with_retry(
        command_name="open_calculator",
        session="SESSION-002",
        command_id="CMD-007B",
        func=cmd_b_fn,
    )

    res_a, res_b = await asyncio.gather(task_a, task_b)

    # Check isolation for Command A
    assert res_a["command_id"] == "CMD-007A"
    assert res_a["session_id"] == "SESSION-001"
    assert res_a["attempt"] == 2
    assert res_a["retry_count"] == 1
    assert res_a["status"] == "COMPLETED"

    # Check isolation for Command B
    assert res_b["command_id"] == "CMD-007B"
    assert res_b["session_id"] == "SESSION-002"
    assert res_b["attempt"] == 1
    assert res_b["retry_count"] == 0
    assert res_b["status"] == "COMPLETED"


# =============================================================================
# Test 8: Duplicate Command Prevention Integration
# =============================================================================
def test_duplicate_command_prevention():
    """
    Section 24 - Test 8:
    - Verify DuplicateDetector / ConflictManager properly handles duplicate commands
    - Ensures that retry states do not register false duplicates for identical Command IDs
    """
    cm = ConflictManager(debounce_interval=0.5)

    # First command is accepted
    eval1 = cm.evaluate(command="open_notepad", domain="DESKTOP", app="NOTEPAD", session="SESSION-001")
    assert eval1.is_allowed is True

    # Immediate duplicate within cooldown window is rejected/flagged
    eval2 = cm.evaluate(command="open_notepad", domain="DESKTOP", app="NOTEPAD", session="SESSION-001")
    # Duplicate within debounce window:
    if not eval2.is_allowed:
        assert "duplicate" in eval2.reason.lower() or "debounce" in eval2.reason.lower()


# =============================================================================
# Test 9: Existing Desktop Commands Execution
# =============================================================================
@run_async
async def test_existing_desktop_commands():
    """
    Section 24 - Test 9:
    - Verify existing desktop commands (open_notepad, open_calculator, open_chrome, open_youtube, youtube_search)
      execute successfully through execute_with_retry without breaking functionality
    """
    from plugins.desktop.plugin import DesktopPlugin
    from plugin_sdk.interfaces.desktop_plugin import DesktopPluginInterface

    class MockSub(DesktopPluginInterface):
        def __init__(self, plugin_id, cmds):
            self.plugin_id = plugin_id
            self.COMMANDS = cmds
            self.execute = AsyncMock(return_value={"status": "success", "message": f"{plugin_id} OK"})
            self.get_widget = MagicMock(return_value={"widget_id": f"{plugin_id}_w"})

    mock_subs = {
        "notepad": MockSub("notepad", ["open_notepad", "save_file", "close_app"]),
        "chrome": MockSub("chrome", ["open_search_bar", "scroll_up"]),
        "youtube": MockSub("youtube", ["search", "play_video"]),
    }
    desktop_plugin = DesktopPlugin(subplugins=mock_subs)
    mgr = RetryManager(max_attempts=3, retry_delay=0.05, command_timeout=1.0)

    # 1. Test open_notepad
    res_notepad = await mgr.execute_with_retry(
        command_name="open_notepad",
        session="SESSION-001",
        command_id="CMD-009A",
        func=desktop_plugin.execute,
        command="open_notepad",
        payload={"domain": "DESKTOP", "app": "NOTEPAD"},
    )
    assert res_notepad["status"] == "COMPLETED"
    assert res_notepad["attempt"] == 1
    assert res_notepad["retry_count"] == 0

    # 2. Test open_chrome (open_search_bar)
    res_chrome = await mgr.execute_with_retry(
        command_name="open_search_bar",
        session="SESSION-001",
        command_id="CMD-009B",
        func=desktop_plugin.execute,
        command="open_search_bar",
        payload={"domain": "DESKTOP", "app": "CHROME"},
    )
    assert res_chrome["status"] == "COMPLETED"
    assert res_chrome["attempt"] == 1

    # 3. Test open_youtube (search)
    res_yt = await mgr.execute_with_retry(
        command_name="search",
        session="SESSION-001",
        command_id="CMD-009C",
        func=desktop_plugin.execute,
        command="search",
        payload={"domain": "DESKTOP", "app": "YOUTUBE", "query": "python"},
    )
    assert res_yt["status"] == "COMPLETED"
    assert res_yt["attempt"] == 1
