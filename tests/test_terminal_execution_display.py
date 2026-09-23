"""
Tests for Day 6 — Member 5: Terminal Execution Display

Tests the full terminal execution display pipeline:
- Test 1: open_notepad → COMPLETED
- Test 2: open_calculator → FAILED (with Error line)
- Test 3: run_automation → CANCELLED
- Test 4: Multiple commands — each produces exactly one summary (no duplicates)
- Test 5: Long text wrapping without breaking box borders
- Test 6: Thread safety under concurrent access
- Test 7: logs/execution.log receives entries
- Test 8: TimestampTracker integration in CommandLifecycleRecord
- Test 9: display_execution_summary called from lifecycle tracker transitions
"""

from __future__ import annotations

import io
import os
import sys
import threading
import time
from pathlib import Path

import pytest

# Ensure project root on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.logging.terminal_display import (
    TimestampTracker,
    display_execution_summary,
    format_execution_box,
    format_time_hms_mmm,
    is_command_displayed,
    reset_displayed_commands,
    write_execution_log,
)
from core.managers.lifecycle_tracker import (
    CommandLifecycleRecord,
    CommandLifecycleStage,
    CommandLifecycleTracker,
    TERMINAL_STAGES,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _capture_summary(execution_data=None, **kwargs) -> str:
    """Capture display_execution_summary output to a string buffer."""
    buf = io.StringIO()
    display_execution_summary(execution_data=execution_data, stream=buf, force=True, **kwargs)
    return buf.getvalue()


def _make_record(
    command: str = "test_command",
    command_id: str = "CMD-TEST",
    session_id: str = "SESSION-TEST",
    domain: str = "python",
) -> CommandLifecycleRecord:
    """Create a fresh CommandLifecycleRecord for test isolation."""
    record = CommandLifecycleRecord(
        command_id=command_id,
        session_id=session_id,
        command=command,
        domain=domain,
    )
    return record


# ── Test 1: COMPLETED summary ──────────────────────────────────────────────────

class TestCompletedSummary:
    """Test 1: open_notepad → COMPLETED"""

    def test_completed_box_contains_command_name(self):
        reset_displayed_commands()
        out = _capture_summary(
            command="open_notepad",
            command_id="CMD-001",
            session_id="SESSION-001",
            status="COMPLETED",
            started_at=time.time() - 2.305,
            completed_at=time.time(),
        )
        assert "open_notepad" in out

    def test_completed_box_contains_command_id(self):
        reset_displayed_commands()
        out = _capture_summary(
            command="open_notepad",
            command_id="CMD-001",
            session_id="SESSION-001",
            status="COMPLETED",
            started_at=time.time() - 2.0,
            completed_at=time.time(),
        )
        assert "CMD-001" in out

    def test_completed_box_contains_session_id(self):
        reset_displayed_commands()
        out = _capture_summary(
            command="open_notepad",
            command_id="CMD-001",
            session_id="SESSION-001",
            status="COMPLETED",
            started_at=time.time() - 2.0,
            completed_at=time.time(),
        )
        assert "SESSION-001" in out

    def test_completed_box_status_is_completed(self):
        reset_displayed_commands()
        out = _capture_summary(
            command="open_notepad",
            command_id="CMD-001",
            session_id="SESSION-001",
            status="COMPLETED",
            started_at=time.time() - 2.0,
            completed_at=time.time(),
        )
        assert "COMPLETED" in out

    def test_completed_box_no_error_line(self):
        reset_displayed_commands()
        out = _capture_summary(
            command="open_notepad",
            command_id="CMD-001",
            session_id="SESSION-001",
            status="COMPLETED",
            started_at=time.time() - 2.0,
            completed_at=time.time(),
        )
        assert "Error:" not in out

    def test_completed_box_duration_line_present(self):
        reset_displayed_commands()
        out = _capture_summary(
            command="open_notepad",
            command_id="CMD-001",
            session_id="SESSION-001",
            status="COMPLETED",
            started_at=time.time() - 2.305,
            completed_at=time.time(),
        )
        assert "Duration:" in out
        assert "seconds" in out

    def test_completed_box_borders(self):
        reset_displayed_commands()
        out = _capture_summary(
            command="open_notepad",
            command_id="CMD-001",
            session_id="SESSION-001",
            status="COMPLETED",
            started_at=time.time() - 2.0,
            completed_at=time.time(),
        )
        assert "┌" in out
        assert "┐" in out
        assert "└" in out
        assert "┘" in out
        assert "│" in out

    def test_completed_via_lifecycle_tracker(self):
        """Test 1 via the real lifecycle tracker pipeline."""
        reset_displayed_commands()
        buf = io.StringIO()
        tracker = CommandLifecycleTracker()
        rec = tracker.create_command(
            "open_notepad", session_id="SESSION-001", command_id="CMD-001"
        )
        tracker.track_execution_started("CMD-001", target="python")
        time.sleep(0.05)

        # Capture output during completion
        import core.logging.terminal_display as td
        original_stdout = sys.stdout
        try:
            sys.stdout = buf
            tracker.track_execution_completed("CMD-001", success=True)
        finally:
            sys.stdout = original_stdout

        output = buf.getvalue()
        assert "open_notepad" in output or is_command_displayed("CMD-001")

    def test_completed_timestamp_format(self):
        """Timestamps must be in HH:MM:SS.mmm format."""
        reset_displayed_commands()
        ts = time.time()
        out = _capture_summary(
            command="open_notepad",
            command_id="CMD-T01",
            session_id="SESSION-001",
            status="COMPLETED",
            started_at=ts - 1.5,
            completed_at=ts,
        )
        import re
        # Should contain at least one time in HH:MM:SS.mmm format
        assert re.search(r"\d{2}:\d{2}:\d{2}\.\d{3}", out), f"No HH:MM:SS.mmm timestamp found in:\n{out}"


# ── Test 2: FAILED summary ─────────────────────────────────────────────────────

class TestFailedSummary:
    """Test 2: open_calculator → FAILED"""

    def test_failed_box_status(self):
        reset_displayed_commands()
        out = _capture_summary(
            command="open_calculator",
            command_id="CMD-002",
            session_id="SESSION-001",
            status="FAILED",
            started_at=time.time() - 2.0,
            completed_at=time.time(),
            error="Application could not be opened",
        )
        assert "FAILED" in out

    def test_failed_box_error_line_present(self):
        reset_displayed_commands()
        out = _capture_summary(
            command="open_calculator",
            command_id="CMD-002",
            session_id="SESSION-001",
            status="FAILED",
            started_at=time.time() - 2.0,
            completed_at=time.time(),
            error="Application could not be opened",
        )
        assert "Error:" in out
        assert "Application could not be opened" in out

    def test_failed_box_command_id(self):
        reset_displayed_commands()
        out = _capture_summary(
            command="open_calculator",
            command_id="CMD-002",
            session_id="SESSION-001",
            status="FAILED",
            started_at=time.time() - 2.0,
            completed_at=time.time(),
            error="Application could not be opened",
        )
        assert "CMD-002" in out

    def test_failed_via_lifecycle_tracker(self):
        """Test 2 via real lifecycle tracker."""
        reset_displayed_commands()
        buf = io.StringIO()
        tracker = CommandLifecycleTracker()
        tracker.create_command("open_calculator", session_id="SESSION-001", command_id="CMD-002")
        tracker.track_execution_started("CMD-002", target="python")
        time.sleep(0.05)

        original_stdout = sys.stdout
        try:
            sys.stdout = buf
            tracker.track_execution_completed(
                "CMD-002",
                success=False,
                error="Application could not be opened",
            )
        finally:
            sys.stdout = original_stdout

        output = buf.getvalue()
        assert "open_calculator" in output or is_command_displayed("CMD-002")

    def test_failed_duration_positive(self):
        reset_displayed_commands()
        start = time.time() - 2.080
        end = time.time()
        out = _capture_summary(
            command="open_calculator",
            command_id="CMD-002D",
            session_id="SESSION-001",
            status="FAILED",
            started_at=start,
            completed_at=end,
            error="Failed",
        )
        assert "Duration:" in out


# ── Test 3: CANCELLED summary ──────────────────────────────────────────────────

class TestCancelledSummary:
    """Test 3: run_automation → CANCELLED"""

    def test_cancelled_box_status(self):
        reset_displayed_commands()
        out = _capture_summary(
            command="run_automation",
            command_id="CMD-003",
            session_id="SESSION-002",
            status="CANCELLED",
            started_at=time.time() - 4.2,
            completed_at=time.time(),
        )
        assert "CANCELLED" in out

    def test_cancelled_box_command(self):
        reset_displayed_commands()
        out = _capture_summary(
            command="run_automation",
            command_id="CMD-003",
            session_id="SESSION-002",
            status="CANCELLED",
            started_at=time.time() - 4.2,
            completed_at=time.time(),
        )
        assert "run_automation" in out

    def test_cancelled_no_error_line(self):
        reset_displayed_commands()
        out = _capture_summary(
            command="run_automation",
            command_id="CMD-003",
            session_id="SESSION-002",
            status="CANCELLED",
            started_at=time.time() - 4.2,
            completed_at=time.time(),
        )
        # No error line for cancelled (no error message)
        assert "Error:" not in out

    def test_cancelled_via_lifecycle_tracker(self):
        """Test 3 via real lifecycle tracker."""
        reset_displayed_commands()
        buf = io.StringIO()
        tracker = CommandLifecycleTracker()
        tracker.create_command("run_automation", session_id="SESSION-002", command_id="CMD-003")
        tracker.track_execution_started("CMD-003", target="python")
        time.sleep(0.05)

        original_stdout = sys.stdout
        try:
            sys.stdout = buf
            tracker.track_cancelled("CMD-003", reason="User cancelled")
        finally:
            sys.stdout = original_stdout

        output = buf.getvalue()
        assert "run_automation" in output or is_command_displayed("CMD-003")


# ── Test 4: No duplicate output ────────────────────────────────────────────────

class TestNoDuplicateOutput:
    """Test 4: Each command produces exactly one summary."""

    def test_single_command_no_duplicate(self):
        reset_displayed_commands()
        buf = io.StringIO()
        cid = "CMD-NO-DUPE-001"
        # First call — should print
        display_execution_summary(
            stream=buf,
            command="test_cmd",
            command_id=cid,
            session_id="SESSION-001",
            status="COMPLETED",
        )
        # Second call — should be suppressed
        display_execution_summary(
            stream=buf,
            command="test_cmd",
            command_id=cid,
            session_id="SESSION-001",
            status="COMPLETED",
        )
        output = buf.getvalue()
        # Box should appear exactly once (only one ┌ top border per call)
        count = output.count("┌")
        assert count == 1, f"Expected 1 box, got {count}"

    def test_multiple_commands_produce_individual_summaries(self):
        reset_displayed_commands()
        buf = io.StringIO()
        for i in range(1, 5):
            display_execution_summary(
                stream=buf,
                command=f"cmd_{i}",
                command_id=f"CMD-MULTI-{i:03d}",
                session_id="SESSION-001",
                status="COMPLETED",
            )
        output = buf.getvalue()
        box_count = output.count("┌")
        assert box_count == 4, f"Expected 4 boxes for 4 commands, got {box_count}"

    def test_is_command_displayed_flag(self):
        reset_displayed_commands()
        buf = io.StringIO()
        cid = "CMD-FLAG-TEST"
        assert not is_command_displayed(cid)
        display_execution_summary(
            stream=buf,
            command="flag_cmd",
            command_id=cid,
            session_id="SESSION-001",
            status="COMPLETED",
        )
        assert is_command_displayed(cid)

    def test_force_flag_bypasses_dedup(self):
        reset_displayed_commands()
        buf = io.StringIO()
        cid = "CMD-FORCE-001"
        display_execution_summary(
            stream=buf, command="f_cmd", command_id=cid,
            session_id="SESSION-001", status="COMPLETED",
        )
        display_execution_summary(
            stream=buf, force=True, command="f_cmd", command_id=cid,
            session_id="SESSION-001", status="COMPLETED",
        )
        count = buf.getvalue().count("┌")
        assert count == 2, f"Expected 2 boxes with force=True, got {count}"

    def test_lifecycle_tracker_no_duplicate_on_multiple_terminal_calls(self):
        """Via lifecycle tracker: calling track_success twice should not double-print."""
        reset_displayed_commands()
        buf = io.StringIO()
        tracker = CommandLifecycleTracker()
        tracker.create_command("nodupe_cmd", session_id="SESSION-001", command_id="CMD-DUPE-LT")
        tracker.track_execution_started("CMD-DUPE-LT", target="python")

        original_stdout = sys.stdout
        try:
            sys.stdout = buf
            tracker.track_success("CMD-DUPE-LT")
            # Attempt second terminal transition — should not produce a second box
            try:
                tracker.track_failure("CMD-DUPE-LT", error="should not re-fire")
            except Exception:
                pass
        finally:
            sys.stdout = original_stdout

        output = buf.getvalue()
        count = output.count("┌")
        # The first SUCCESS should have printed; FAILED should be suppressed by dedup
        assert count == 1, f"Expected 1 box, got {count}"


# ── Test 5: Long text wrapping ─────────────────────────────────────────────────

class TestLongTextWrapping:

    def test_long_command_name_does_not_break_box(self):
        reset_displayed_commands()
        long_cmd = "a" * 80
        out = _capture_summary(
            command=long_cmd,
            command_id="CMD-LONG-001",
            session_id="SESSION-001",
            status="COMPLETED",
        )
        # Box borders must still be present
        assert "┌" in out
        assert "┘" in out

    def test_long_error_message_does_not_break_box(self):
        reset_displayed_commands()
        long_err = "Error detail: " + "x" * 200
        out = _capture_summary(
            command="err_cmd",
            command_id="CMD-LONG-002",
            session_id="SESSION-001",
            status="FAILED",
            error=long_err,
        )
        assert "┌" in out
        assert "┘" in out

    def test_box_lines_have_consistent_width(self):
        """All lines in the box must have the same printed width."""
        reset_displayed_commands()
        out = _capture_summary(
            command="check_width_cmd",
            command_id="CMD-WIDTH",
            session_id="SESSION-001",
            status="COMPLETED",
        )
        lines = [l for l in out.strip().split("\n") if l.strip()]
        # All box lines should have the same length (59 chars)
        widths = set(len(l) for l in lines)
        assert len(widths) == 1, f"Box lines have inconsistent widths: {widths}\n{out}"


# ── Test 6: Thread safety ──────────────────────────────────────────────────────

class TestThreadSafety:

    def test_concurrent_display_no_interleaving(self):
        reset_displayed_commands()
        errors = []
        results = []
        lock = threading.Lock()

        def worker(n):
            try:
                buf = io.StringIO()
                display_execution_summary(
                    stream=buf,
                    command=f"cmd_thread_{n}",
                    command_id=f"CMD-TH-{n:03d}",
                    session_id="SESSION-001",
                    status="COMPLETED",
                )
                with lock:
                    results.append(buf.getvalue())
            except Exception as e:
                with lock:
                    errors.append(str(e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
        assert len(results) == 10


# ── Test 7: execution.log file ──────────────────────────────────────────────────

class TestExecutionLogFile:

    def test_execution_log_written(self, tmp_path, monkeypatch):
        """write_execution_log appends to execution.log."""
        import core.logging.terminal_display as td
        log_file = tmp_path / "execution.log"
        monkeypatch.setattr(td, "PRIMARY_LOG_DIR", tmp_path)
        monkeypatch.setattr(td, "EXECUTION_LOG_FILE", log_file)

        reset_displayed_commands()
        write_execution_log({
            "command": "open_notepad",
            "command_id": "CMD-LOG-001",
            "session_id": "SESSION-001",
            "status": "COMPLETED",
            "start": "11:30:10.125",
            "completion": "11:30:12.430",
            "duration": "2.305 seconds",
            "error": None,
        })

        assert log_file.exists(), "execution.log was not created"
        content = log_file.read_text(encoding="utf-8")
        assert "open_notepad" in content
        assert "CMD-LOG-001" in content
        assert "SESSION-001" in content

    def test_execution_log_appends_multiple_entries(self, tmp_path, monkeypatch):
        import core.logging.terminal_display as td
        log_file = tmp_path / "execution.log"
        monkeypatch.setattr(td, "PRIMARY_LOG_DIR", tmp_path)
        monkeypatch.setattr(td, "EXECUTION_LOG_FILE", log_file)

        for i in range(3):
            write_execution_log({
                "command": f"cmd_{i}",
                "command_id": f"CMD-LOG-{i:03d}",
                "session_id": "SESSION-001",
                "status": "COMPLETED",
                "start": "11:00:00.000",
                "completion": "11:00:01.000",
                "duration": "1.000 seconds",
                "error": None,
            })

        content = log_file.read_text(encoding="utf-8")
        assert content.count("CMD-LOG-") == 3

    def test_real_execution_log_written_via_display(self):
        """display_execution_summary must also write to execution.log."""
        reset_displayed_commands()
        buf = io.StringIO()
        cid = f"CMD-REAL-LOG-{int(time.time())}"
        display_execution_summary(
            stream=buf,
            command="log_test_cmd",
            command_id=cid,
            session_id="SESSION-LOG",
            status="COMPLETED",
        )
        # Check if the project-level logs/execution.log received the entry
        log_path = PROJECT_ROOT / "logs" / "execution.log"
        alt_log_path = PROJECT_ROOT / "data" / "logs" / "execution.log"
        found = False
        for lp in [log_path, alt_log_path]:
            if lp.exists():
                content = lp.read_text(encoding="utf-8", errors="replace")
                if cid in content:
                    found = True
                    break
        assert found, f"Command ID {cid} not found in execution.log files"


# ── Test 8: TimestampTracker ───────────────────────────────────────────────────

class TestTimestampTracker:

    def test_record_start_and_completion(self):
        tracker = TimestampTracker(command_id="CMD-TS-001")
        t0 = time.time()
        tracker.record_start(t0)
        time.sleep(0.1)
        t1 = time.time()
        tracker.record_completion(t1)
        assert tracker.duration_seconds is not None
        assert tracker.duration_seconds >= 0.09

    def test_start_str_format(self):
        tracker = TimestampTracker(command_id="CMD-TS-002")
        tracker.record_start(time.time())
        import re
        assert re.match(r"^\d{2}:\d{2}:\d{2}\.\d{3}$", tracker.start_str)

    def test_completion_str_format(self):
        tracker = TimestampTracker(command_id="CMD-TS-003")
        tracker.record_start(time.time())
        tracker.record_completion(time.time())
        import re
        assert re.match(r"^\d{2}:\d{2}:\d{2}\.\d{3}$", tracker.completion_str)

    def test_duration_str_format(self):
        tracker = TimestampTracker(command_id="CMD-TS-004")
        tracker.record_start(time.time() - 2.305)
        tracker.record_completion(time.time())
        assert "seconds" in tracker.duration_str
        # Should look like "2.305 seconds"
        import re
        assert re.match(r"^\d+\.\d{3} seconds$", tracker.duration_str)

    def test_lifecycle_record_has_timestamp_tracker(self):
        rec = _make_record(command_id="CMD-TS-RECORD")
        assert hasattr(rec, "timestamp_tracker")
        assert isinstance(rec.timestamp_tracker, TimestampTracker)

    def test_lifecycle_record_tracker_records_start(self):
        rec = _make_record(command_id="CMD-TS-START")
        rec.add_transition(CommandLifecycleStage.EXECUTION_STARTED, reason="test")
        assert rec.timestamp_tracker.start_time is not None

    def test_lifecycle_record_tracker_records_completion(self):
        rec = _make_record(command_id="CMD-TS-COMPLETE")
        rec.add_transition(CommandLifecycleStage.EXECUTION_STARTED, reason="test")
        time.sleep(0.05)
        rec.add_transition(CommandLifecycleStage.SUCCESS, reason="test")
        assert rec.timestamp_tracker.completion_time is not None
        assert rec.timestamp_tracker.duration_seconds is not None
        assert rec.timestamp_tracker.duration_seconds >= 0.04


# ── Test 9: Integration flow ──────────────────────────────────────────────────

class TestLifecyclePipelineIntegration:
    """Full pipeline integration tests using real lifecycle tracker."""

    def _run_lifecycle(self, command: str, cid: str, sid: str, success: bool = True,
                       error: str = None, cancel: bool = False) -> tuple[str, CommandLifecycleRecord]:
        reset_displayed_commands()
        buf = io.StringIO()
        tracker = CommandLifecycleTracker()
        tracker.create_command(command, session_id=sid, command_id=cid)
        tracker.track_execution_started(cid, target="python")
        time.sleep(0.05)

        original_stdout = sys.stdout
        try:
            sys.stdout = buf
            if cancel:
                rec = tracker.track_cancelled(cid, reason="User cancelled")
            elif success:
                rec = tracker.track_execution_completed(cid, success=True)
            else:
                rec = tracker.track_execution_completed(cid, success=False, error=error)
        finally:
            sys.stdout = original_stdout

        return buf.getvalue(), rec

    def test_pipeline_completed_values(self):
        output, rec = self._run_lifecycle("open_notepad", "CMD-P01", "SESSION-001")
        assert "open_notepad" in output or is_command_displayed("CMD-P01")
        assert rec.current_stage.value == "SUCCESS"
        assert rec.started_at is not None
        assert rec.completed_at is not None
        assert rec.duration_ms is not None

    def test_pipeline_failed_values(self):
        output, rec = self._run_lifecycle(
            "open_calculator", "CMD-P02", "SESSION-001",
            success=False, error="Application could not be opened",
        )
        assert is_command_displayed("CMD-P02") or "open_calculator" in output
        assert rec.current_stage.value == "FAILED"

    def test_pipeline_cancelled_values(self):
        output, rec = self._run_lifecycle(
            "run_automation", "CMD-P03", "SESSION-002", cancel=True
        )
        assert is_command_displayed("CMD-P03") or "run_automation" in output
        assert rec.current_stage.value == "CANCELLED"

    def test_pipeline_each_command_one_summary_only(self):
        """Multiple commands each produce exactly one summary."""
        reset_displayed_commands()
        buf = io.StringIO()
        tracker = CommandLifecycleTracker()
        cmds = [
            ("open_notepad", "CMD-PIPE-1", "SESSION-001"),
            ("open_calculator", "CMD-PIPE-2", "SESSION-001"),
            ("run_automation", "CMD-PIPE-3", "SESSION-002"),
        ]
        original_stdout = sys.stdout
        try:
            sys.stdout = buf
            for cmd, cid, sid in cmds:
                tracker.create_command(cmd, session_id=sid, command_id=cid)
                tracker.track_execution_started(cid, target="python")
                time.sleep(0.02)
                tracker.track_success(cid)
        finally:
            sys.stdout = original_stdout

        output = buf.getvalue()
        count = output.count("┌")
        assert count == 3, f"Expected 3 boxes for 3 commands, got {count}\n{output}"


# ── Test format_time_hms_mmm ──────────────────────────────────────────────────

class TestFormatTimeHmsMmm:

    def test_float_timestamp(self):
        import re
        result = format_time_hms_mmm(time.time())
        assert re.match(r"^\d{2}:\d{2}:\d{2}\.\d{3}$", result)

    def test_iso_string(self):
        import re
        result = format_time_hms_mmm("2026-09-08T11:30:10.125000+00:00")
        assert re.match(r"^\d{2}:\d{2}:\d{2}\.\d{3}$", result)

    def test_already_formatted(self):
        result = format_time_hms_mmm("11:30:10.125")
        assert result == "11:30:10.125"

    def test_none_returns_current_time(self):
        import re
        result = format_time_hms_mmm(None)
        assert re.match(r"^\d{2}:\d{2}:\d{2}\.\d{3}$", result)
