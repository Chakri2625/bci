"""
tests/test_timestamp_tracker.py
--------------------------------
Comprehensive test suite for Day 6 — Member 5:
Execution Timestamp Tracking + Audit Logging in SynaptiMesh.

Covers:
A. Successful command (QUEUED -> RUNNING -> COMPLETED)
B. Failed command (QUEUED -> RUNNING -> FAILED)
C. Cancelled command (QUEUED -> RUNNING -> CANCELLED)
D. Multiple concurrent commands (independent isolated timestamps)
E. Duration validation (completion_time >= start_time, duration_seconds >= 0)
F. Audit logging format and persistence in logs/execution.log
G. Deduplication (repeated start/completion events do not duplicate logs)
H. Error shielding (timestamp tracking never crashes execution)
I. Integration with CommandServiceMapper, SequentialProcessor, and AsyncTaskManager
"""

import asyncio
import os
import re
import threading
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from core.logging.timestamp_tracker import (
    DEFAULT_LOG_FILE,
    ExecutionRecord,
    TimestampTracker,
    get_timestamp_tracker,
    get_utc_now,
    parse_iso_utc,
    display_execution_summary,
    format_terminal_time,
)
from services.command_service_mapper import CommandServiceMapper, get_command_service_mapper
from core.navigation.sequential_processor import SequentialProcessor
from core.managers.async_task_manager import AsyncTaskManager


@pytest.fixture
def clean_tracker(tmp_path):
    """Provide an isolated TimestampTracker instance with a dedicated temp log file."""
    log_file = str(tmp_path / "test_execution.log")
    tracker = TimestampTracker(log_file_path=log_file)
    tracker.clear()
    return tracker, log_file


# ---------------------------------------------------------------------------
# Unit Tests for TimestampTracker
# ---------------------------------------------------------------------------

def test_utc_now_iso_format():
    """Verify get_utc_now produces a valid timezone-aware UTC datetime and ISO 8601 string."""
    dt, iso_str = get_utc_now()
    assert dt.tzinfo is not None
    assert dt.tzinfo == timezone.utc
    assert iso_str.endswith("Z")
    # Verify standard ISO regex: YYYY-MM-DDTHH:MM:SS.mmmZ
    pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
    assert re.match(pattern, iso_str), f"ISO string '{iso_str}' does not match expected format"


def test_successful_command_lifecycle(clean_tracker):
    """
    Test Requirement A: Successful command
    Flow: QUEUED -> RUNNING -> COMPLETED
    """
    tracker, log_file = clean_tracker
    cid = "CMD-001"
    sid = "SESSION-001"
    cmd_name = "open_notepad"

    # 1. QUEUED
    q_rec = tracker.record_queued(command_id=cid, session_id=sid, command=cmd_name)
    assert q_rec["status"] == "QUEUED"
    assert q_rec["command_id"] == cid
    assert q_rec["session_id"] == sid
    assert q_rec["command"] == cmd_name

    # 2. RUNNING
    s_rec = tracker.record_start(command_id=cid, session_id=sid, command=cmd_name)
    assert s_rec["status"] == "RUNNING"
    assert s_rec["start_time"] is not None
    assert s_rec["completion_time"] is None

    # Small delay to ensure duration > 0
    time.sleep(0.01)

    # 3. COMPLETED
    c_rec = tracker.record_completion(command_id=cid, session_id=sid, command=cmd_name, status="COMPLETED")
    assert c_rec["status"] == "COMPLETED"
    assert c_rec["start_time"] is not None
    assert c_rec["completion_time"] is not None
    assert c_rec["duration_seconds"] >= 0.01
    assert c_rec["error"] is None

    # Verify get_execution_details matches
    details = tracker.get_execution_details(cid)
    assert details == c_rec

    # Verify log output in execution.log
    with open(log_file, "r", encoding="utf-8") as f:
        content = f.read()

    assert "COMMAND_STARTED | command_id=CMD-001 | session_id=SESSION-001 | command=open_notepad" in content
    assert "COMMAND_COMPLETED | command_id=CMD-001 | session_id=SESSION-001 | command=open_notepad" in content
    assert "status=COMPLETED" in content


def test_failed_command_lifecycle(clean_tracker):
    """
    Test Requirement B: Failed command
    Flow: QUEUED -> RUNNING -> FAILED
    """
    tracker, log_file = clean_tracker
    cid = "CMD-002"
    sid = "SESSION-001"
    cmd_name = "open_calculator"
    err_msg = "Application could not be opened"

    tracker.record_queued(command_id=cid, session_id=sid, command=cmd_name)
    tracker.record_start(command_id=cid, session_id=sid, command=cmd_name)
    time.sleep(0.01)
    f_rec = tracker.record_failure(command_id=cid, session_id=sid, command=cmd_name, error=err_msg)

    assert f_rec["status"] == "FAILED"
    assert f_rec["error"] == err_msg
    assert f_rec["start_time"] is not None
    assert f_rec["completion_time"] is not None
    assert f_rec["duration_seconds"] >= 0.01

    with open(log_file, "r", encoding="utf-8") as f:
        content = f.read()

    assert "COMMAND_STARTED | command_id=CMD-002 | session_id=SESSION-001 | command=open_calculator" in content
    assert "COMMAND_FAILED | command_id=CMD-002 | session_id=SESSION-001 | command=open_calculator" in content
    assert f"error={err_msg}" in content


def test_cancelled_command_lifecycle(clean_tracker):
    """
    Test Requirement C: Cancelled command
    Flow: QUEUED -> RUNNING -> CANCELLED
    """
    tracker, log_file = clean_tracker
    cid = "CMD-003"
    sid = "SESSION-002"
    cmd_name = "long_computation"
    reason = "User aborted task"

    tracker.record_queued(command_id=cid, session_id=sid, command=cmd_name)
    tracker.record_start(command_id=cid, session_id=sid, command=cmd_name)
    time.sleep(0.01)
    c_rec = tracker.record_cancel(command_id=cid, session_id=sid, command=cmd_name, reason=reason)

    assert c_rec["status"] == "CANCELLED"
    assert c_rec["error"] == reason
    assert c_rec["start_time"] is not None
    assert c_rec["completion_time"] is not None
    assert c_rec["duration_seconds"] >= 0.01

    with open(log_file, "r", encoding="utf-8") as f:
        content = f.read()

    assert "COMMAND_STARTED | command_id=CMD-003 | session_id=SESSION-002 | command=long_computation" in content
    assert "COMMAND_CANCELLED | command_id=CMD-003 | session_id=SESSION-002 | command=long_computation" in content
    assert "status=CANCELLED" in content


def test_multiple_concurrent_commands(clean_tracker):
    """
    Test Requirement D & 11: Multiple commands executed concurrently.
    Verify each command maintains its own independent timestamps and records safely.
    """
    tracker, _ = clean_tracker
    num_commands = 20
    results = {}

    def worker(idx):
        cid = f"CMD-MULTI-{idx:03d}"
        sid = f"SESSION-{idx % 3}"
        cmd_name = f"action_{idx}"
        
        tracker.record_queued(cid, session_id=sid, command=cmd_name)
        tracker.record_start(cid, session_id=sid, command=cmd_name)
        time.sleep(0.005 * (idx % 4 + 1))
        
        if idx % 3 == 0:
            rec = tracker.record_failure(cid, session_id=sid, command=cmd_name, error=f"Failure {idx}")
        elif idx % 3 == 1:
            rec = tracker.record_cancel(cid, session_id=sid, command=cmd_name, reason="Cancelled")
        else:
            rec = tracker.record_completion(cid, session_id=sid, command=cmd_name, status="COMPLETED")
            
        results[cid] = rec

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_commands)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == num_commands
    for cid, rec in results.items():
        assert rec["command_id"] == cid
        assert rec["start_time"] is not None
        assert rec["completion_time"] is not None
        assert rec["duration_seconds"] >= 0.0
        # Check that individual query returns identical data
        queried = tracker.get_execution_details(cid)
        assert queried == rec


def test_duration_accuracy(clean_tracker):
    """
    Test Requirement E: Duration
    Verify: completion_time >= start_time and duration_seconds >= 0.
    """
    tracker, _ = clean_tracker
    cid = "CMD-DUR-01"
    
    tracker.record_start(cid, command="timed_task")
    sleep_time = 0.05
    time.sleep(sleep_time)
    rec = tracker.record_completion(cid, command="timed_task")

    s_dt = parse_iso_utc(rec["start_time"])
    c_dt = parse_iso_utc(rec["completion_time"])

    assert c_dt >= s_dt
    assert rec["duration_seconds"] >= sleep_time * 0.8  # Allow slight timing tolerance


def test_log_deduplication(clean_tracker):
    """
    Test Requirement 10: DO NOT DUPLICATE LOGS
    Ensure one command does not generate repeated STARTED or COMPLETED logs
    because of retries, callbacks, or duplicate lifecycle events.
    """
    tracker, log_file = clean_tracker
    cid = "CMD-DEDUP-01"
    sid = "SESSION-01"

    # Call record_start multiple times for same command_id
    tracker.record_start(cid, session_id=sid, command="repeat_action")
    tracker.record_start(cid, session_id=sid, command="repeat_action")
    tracker.record_start(cid, session_id=sid, command="repeat_action")

    # Call record_completion multiple times
    tracker.record_completion(cid, session_id=sid, command="repeat_action")
    tracker.record_completion(cid, session_id=sid, command="repeat_action")

    with open(log_file, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    started_lines = [l for l in lines if f"COMMAND_STARTED | command_id={cid}" in l]
    completed_lines = [l for l in lines if f"COMMAND_COMPLETED | command_id={cid}" in l]

    assert len(started_lines) == 1, f"Expected exactly 1 start log, got {len(started_lines)}"
    assert len(completed_lines) == 1, f"Expected exactly 1 completed log, got {len(completed_lines)}"


def test_error_handling_resilience(clean_tracker):
    """
    Test Requirement 15: ERROR HANDLING
    Timestamp tracking must NEVER cause command execution itself to fail.
    Invalid inputs or logger failure should be caught safely without throwing.
    """
    tracker, _ = clean_tracker
    # Pass None or invalid parameters
    rec = tracker.record_start(None, None, None)
    assert rec is not None
    assert rec["status"] == "RUNNING"

    comp_rec = tracker.record_completion(None)
    assert comp_rec is not None
    assert comp_rec["status"] == "COMPLETED"

    fail_rec = tracker.record_failure(None, error="Some error")
    assert fail_rec is not None
    assert fail_rec["status"] == "FAILED"


# ---------------------------------------------------------------------------
# Integration Tests with Existing Command Execution Pipeline
# ---------------------------------------------------------------------------

def test_command_service_mapper_timestamp_integration():
    """
    Verify CommandServiceMapper integrates with TimestampTracker:
    - Successful execution populates start_time, completion_time, duration_seconds.
    - Preserves metadata, session_id, and existing return fields.
    """
    mapper = CommandServiceMapper()
    mock_svc = MagicMock()
    mock_svc.execute_command.return_value = {"status": "SUCCESS", "success": True, "message": "OK"}
    mapper.register_service("MEDIA", mock_svc)

    res = mapper.map_and_execute(
        command_id="cmd_integ_001",
        domain="MEDIA",
        action="PLAY",
        parameters={"track": "Jazz"},
        priority=2,
        session_id="session_auditor",
        device_id="speaker_1",
    )

    assert res["command_id"] == "cmd_integ_001"
    assert res["session_id"] == "session_auditor"
    assert res["status"] == "SUCCESS"
    assert res["success"] is True
    assert res["start_time"] is not None
    assert res["completion_time"] is not None
    assert res["duration_seconds"] is not None
    assert res["duration_seconds"] >= 0.0
    assert res["error"] is None

    # Check history includes timestamps
    history = mapper.get_history(limit=5)
    matching = [h for h in history if h["command_id"] == "cmd_integ_001"]
    assert len(matching) == 1
    assert matching[0]["start_time"] == res["start_time"]
    assert matching[0]["completion_time"] == res["completion_time"]
    assert matching[0]["session_id"] == "session_auditor"


def test_command_service_mapper_failure_timestamp_integration():
    """
    Verify CommandServiceMapper logs failure and populates timestamps on error.
    """
    mapper = CommandServiceMapper()
    res = mapper.map_and_execute(
        command_id="cmd_integ_err_002",
        domain="UNREGISTERED_DOMAIN",
        action="FLY",
        session_id="session_err",
    )

    assert res["command_id"] == "cmd_integ_err_002"
    assert res["session_id"] == "session_err"
    assert res["success"] is False
    assert res["start_time"] is not None
    assert res["completion_time"] is not None
    assert res["duration_seconds"] is not None
    assert res["error"] is not None

    tracker = get_timestamp_tracker()
    details = tracker.get_execution_details("cmd_integ_err_002")
    assert details is not None
    assert details["status"] == "FAILED"
    assert details["session_id"] == "session_err"


def test_sequential_processor_timestamp_integration():
    """
    Verify SequentialProcessor executes command with timestamp tracking.
    """
    processor = SequentialProcessor()

    async def run_test():
        cmd_obj = await processor.enqueue(
            command="PUSH",
            session="seq_session_01",
        )
        assert cmd_obj.id is not None

        executed = await processor.execute_command(cmd_obj)
        assert executed.start_time is not None
        assert executed.completion_time is not None
        assert executed.duration_seconds is not None
        assert executed.duration_seconds >= 0.0

        # Verify record in tracker
        tracker = get_timestamp_tracker()
        details = tracker.get_execution_details(executed.id)
        assert details is not None
        assert details["command_id"] == executed.id
        assert details["session_id"] == "seq_session_01"

    asyncio.run(run_test())


def test_async_task_manager_timestamp_integration():
    """
    Verify AsyncTaskManager executes coroutine with timestamp tracking and exposes fields.
    """
    atm = AsyncTaskManager()

    async def run_test():
        async def dummy_coro():
            await asyncio.sleep(0.02)
            return "async_done"

        task_id = atm.submit(dummy_coro())
        statuses = await atm.wait_for_tasks([task_id])

        assert len(statuses) == 1
        status_info = statuses[0]
        assert status_info["status"] == "SUCCESS"
        assert status_info["result"] == "async_done"
        assert status_info["start_time"] is not None
        assert status_info["completion_time"] is not None
        assert status_info["duration_seconds"] >= 0.01

        # Test cancellation timestamp tracking
        async def long_coro():
            await asyncio.sleep(5.0)

        cancel_tid = atm.submit(long_coro())
        atm.cancel(cancel_tid)
        c_status = atm.get_status(cancel_tid)
        assert c_status["status"] == "CANCELLED"
        assert c_status["start_time"] is not None

    asyncio.run(run_test())


# ---------------------------------------------------------------------------
# Day 6 — Member 5: Terminal Execution Display Tests (Requirements 1-13)
# ---------------------------------------------------------------------------

def test_terminal_display_format_time():
    """
    Verify timestamp formatting strictly converts to HH:MM:SS.mmm.
    """
    # Full ISO format
    assert format_terminal_time("2026-09-07T11:30:10.125Z") == "11:30:10.125"
    assert format_terminal_time("2026-09-07T11:30:10.125") == "11:30:10.125"
    # Microseconds truncated to 3 digits
    assert format_terminal_time("2026-09-07T11:30:10.125789Z") == "11:30:10.125"
    # No milliseconds padded with .000
    assert format_terminal_time("11:30:10") == "11:30:10.000"
    # Datetime object
    dt = datetime(2026, 9, 7, 11, 30, 10, 125000, tzinfo=timezone.utc)
    assert format_terminal_time(dt) == "11:30:10.125"
    # Empty / None
    assert format_terminal_time(None) == "N/A"
    assert format_terminal_time("") == "N/A"


def test_terminal_display_test1_completed(clean_tracker):
    """
    Requirement 13 - Test 1:
    open_notepad -> COMPLETED
    Verify box structure:
    - Fixed 59 char width on every line
    - Command: open_notepad
    - Command ID: CMD-001
    - Session ID: SESSION-001
    - Status: COMPLETED
    - Start: 11:30:10.125
    - Completion: 11:30:12.430
    - Duration: 2.305 seconds
    - No Error line
    """
    record = {
        "command": "open_notepad",
        "command_id": "CMD-001",
        "session_id": "SESSION-001",
        "status": "COMPLETED",
        "start_time": "2026-09-07T11:30:10.125Z",
        "completion_time": "2026-09-07T11:30:12.430Z",
        "duration_seconds": 2.305,
        "error": None,
    }

    output = display_execution_summary(record)
    lines = output.splitlines()

    # All lines must be exactly 59 characters wide
    assert len(lines) == 9
    for line in lines:
        assert len(line) == 59, f"Line length {len(line)} != 59: '{line}'"

    assert lines[0] == f"┌{'─' * 57}┐"
    assert "│ Command: open_notepad" in lines[1]
    assert "│ Command ID: CMD-001" in lines[2]
    assert "│ Session ID: SESSION-001" in lines[3]
    assert "│ Status: COMPLETED" in lines[4]
    assert "│ Start: 11:30:10.125" in lines[5]
    assert "│ Completion: 11:30:12.430" in lines[6]
    assert "│ Duration: 2.305 seconds" in lines[7]
    assert lines[8] == f"└{'─' * 57}┘"
    assert "Error:" not in output


def test_terminal_display_test2_failed(clean_tracker):
    """
    Requirement 13 - Test 2:
    open_calculator -> FAILED
    Verify:
    - Status: FAILED
    - Error: Application could not be opened is displayed
    - All lines exactly 59 characters wide
    """
    record = {
        "command": "open_calculator",
        "command_id": "CMD-002",
        "session_id": "SESSION-001",
        "status": "FAILED",
        "start_time": "2026-09-07T11:31:03.100Z",
        "completion_time": "2026-09-07T11:31:05.180Z",
        "duration_seconds": 2.080,
        "error": "Application could not be opened",
    }

    output = display_execution_summary(record)
    lines = output.splitlines()

    assert len(lines) == 10  # includes Error line
    for line in lines:
        assert len(line) == 59, f"Line length {len(line)} != 59: '{line}'"

    assert "│ Command: open_calculator" in lines[1]
    assert "│ Command ID: CMD-002" in lines[2]
    assert "│ Session ID: SESSION-001" in lines[3]
    assert "│ Status: FAILED" in lines[4]
    assert "│ Start: 11:31:03.100" in lines[5]
    assert "│ Completion: 11:31:05.180" in lines[6]
    assert "│ Duration: 2.080 seconds" in lines[7]
    assert "│ Error: Application could not be opened" in lines[8]
    assert lines[9] == f"└{'─' * 57}┘"


def test_terminal_display_test3_cancelled(clean_tracker):
    """
    Requirement 13 - Test 3:
    run_automation -> CANCELLED
    Verify:
    - Status: CANCELLED
    - No Error line displayed for cancelled commands
    - All lines exactly 59 characters wide
    """
    record = {
        "command": "run_automation",
        "command_id": "CMD-003",
        "session_id": "SESSION-002",
        "status": "CANCELLED",
        "start_time": "2026-09-07T11:35:00.000Z",
        "completion_time": "2026-09-07T11:35:04.200Z",
        "duration_seconds": 4.200,
        "error": "User abort",
    }

    output = display_execution_summary(record)
    lines = output.splitlines()

    assert len(lines) == 9  # no Error line
    for line in lines:
        assert len(line) == 59, f"Line length {len(line)} != 59: '{line}'"

    assert "│ Command: run_automation" in lines[1]
    assert "│ Command ID: CMD-003" in lines[2]
    assert "│ Session ID: SESSION-002" in lines[3]
    assert "│ Status: CANCELLED" in lines[4]
    assert "│ Start: 11:35:00.000" in lines[5]
    assert "│ Completion: 11:35:04.200" in lines[6]
    assert "│ Duration: 4.200 seconds" in lines[7]
    assert "Error:" not in output
    assert lines[8] == f"└{'─' * 57}┘"


def test_terminal_display_test4_multiple_commands_dedup(clean_tracker, monkeypatch):
    """
    Requirement 13 - Test 4:
    Run multiple commands and confirm each command produces only one summary.
    Also verify execution.log still receives all events correctly.
    """
    tracker, log_file = clean_tracker
    displays = []

    # Intercept display_execution_summary to count calls
    import sys
    tt_module = sys.modules["core.logging.timestamp_tracker"]
    orig_display = tt_module.display_execution_summary

    def intercept_display(data):
        res = orig_display(data)
        displays.append(dict(data) if isinstance(data, dict) else data.to_dict())
        return res

    monkeypatch.setattr(tt_module, "display_execution_summary", intercept_display)

    commands = [
        ("CMD-M-01", "SESSION-A", "open_notepad", "COMPLETED", None),
        ("CMD-M-02", "SESSION-A", "open_calculator", "FAILED", "Application could not be opened"),
        ("CMD-M-03", "SESSION-B", "run_automation", "CANCELLED", "Aborted by operator"),
        ("CMD-M-04", "SESSION-B", "save_document", "COMPLETED", None),
    ]

    for cid, sid, cmd, status, err in commands:
        tracker.record_start(cid, session_id=sid, command=cmd)
        # Duplicate start calls should not trigger duplicate logs
        tracker.record_start(cid, session_id=sid, command=cmd)
        time.sleep(0.005)

        if status == "COMPLETED":
            tracker.record_completion(cid, session_id=sid, command=cmd)
            # Duplicate completion calls should not trigger duplicate logs or summaries
            tracker.record_completion(cid, session_id=sid, command=cmd)
        elif status == "FAILED":
            tracker.record_failure(cid, session_id=sid, command=cmd, error=err)
            tracker.record_failure(cid, session_id=sid, command=cmd, error=err)
        elif status == "CANCELLED":
            tracker.record_cancel(cid, session_id=sid, command=cmd, reason=err)
            tracker.record_cancel(cid, session_id=sid, command=cmd, reason=err)

    # Exactly 4 summaries should have been emitted (one per unique command)
    assert len(displays) == 4

    cmd_ids_emitted = [d["command_id"] for d in displays]
    assert cmd_ids_emitted == ["CMD-M-01", "CMD-M-02", "CMD-M-03", "CMD-M-04"]

    # Verify log file also received the events
    with open(log_file, "r", encoding="utf-8") as f:
        log_content = f.read()

    assert "CMD-M-01" in log_content
    assert "CMD-M-02" in log_content
    assert "CMD-M-03" in log_content
    assert "CMD-M-04" in log_content
    assert "COMMAND_COMPLETED | command_id=CMD-M-01" in log_content
    assert "COMMAND_FAILED | command_id=CMD-M-02" in log_content
    assert "COMMAND_CANCELLED | command_id=CMD-M-03" in log_content


def test_terminal_display_wrapping_long_text():
    """
    Requirement 9: If a command/error is longer than the available width,
    handle it safely with wrapping without breaking the 59-char box width.
    """
    long_error = "This is a very long error message that definitely exceeds fifty-five characters and must wrap onto subsequent lines neatly"
    long_cmd = "very_long_automation_script_name_exceeding_standard_display_limits"
    record = {
        "command": long_cmd,
        "command_id": "CMD-LONG-001",
        "session_id": "SESSION-LONG-001",
        "status": "FAILED",
        "start_time": "2026-09-07T12:00:00.000Z",
        "completion_time": "2026-09-07T12:00:05.123Z",
        "duration_seconds": 5.123,
        "error": long_error,
    }

    output = display_execution_summary(record)
    lines = output.splitlines()

    assert lines[0] == f"┌{'─' * 57}┐"
    assert lines[-1] == f"└{'─' * 57}┘"

    # Verify every single line maintains the exact 59 char width
    for idx, line in enumerate(lines):
        assert len(line) == 59, f"Line {idx} width {len(line)} != 59: '{line}'"
        assert line.startswith("│ ") or line.startswith("┌") or line.startswith("└")
        assert line.endswith(" │") or line.endswith("┐") or line.endswith("┘")
