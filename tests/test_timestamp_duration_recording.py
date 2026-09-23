"""
Test Suite for Day 8 Member 6: Timestamp and Execution Duration Recording.
-------------------------------------------------------------------------
Verifies:
1. Normal execution start and completion timestamp recording.
2. Accurate duration calculation (completion - start).
3. Failed execution timing and duration recording.
4. Cancelled execution timing and duration recording.
5. Timeout execution timing and duration recording.
6. Missing start timestamp safe fallback without crashing.
7. Repeated lifecycle updates idempotency and protection against corruption.
8. Concurrent execution timing independence across multiple simultaneous commands.
9. Pydantic model serialization/deserialization compatibility.
10. Central StateManager and REST API integration.
"""

import asyncio
import time
import pytest
from fastapi.testclient import TestClient

from core.managers.lifecycle_tracker import (
    CommandLifecycleStage,
    CommandLifecycleRecord,
    CommandLifecycleTracker,
    lifecycle_tracker,
)
from core.state.state_manager import state_manager
from models.command_models import CommandLifecycleModel, LifecycleTransitionModel
from main import app


@pytest.fixture(autouse=True)
def cleanup_trackers():
    """Reset lifecycle tracker and state manager between test cases."""
    lifecycle_tracker.clear()
    state_manager.reset_state()
    yield
    lifecycle_tracker.clear()
    state_manager.reset_state()


def test_normal_start_completion_and_duration():
    """1. Verify start timestamp, completion timestamp, and duration for normal execution."""
    tracker = CommandLifecycleTracker()
    rec = tracker.create_command("PUSH", session_id="sess-1", command_id="CMD-1001", domain="DESKTOP")

    assert rec.created_at is not None
    assert rec.started_at is None
    assert rec.completed_at is None
    assert rec.duration_ms is None

    # Track validation and queued
    tracker.track_validation("CMD-1001", is_valid=True)
    tracker.track_queued("CMD-1001", priority="HIGH")

    # Track start
    t_start = time.time()
    rec_start = tracker.track_execution_started("CMD-1001", target="DESKTOP:YOUTUBE")
    assert rec_start.started_at is not None
    assert rec_start.started_at_iso is not None
    assert abs(rec_start.started_at - t_start) < 0.5
    assert rec_start.current_stage == CommandLifecycleStage.EXECUTION_STARTED

    time.sleep(0.05)  # 50 ms execution simulation

    # Track completion
    t_complete = time.time()
    rec_done = tracker.track_execution_completed("CMD-1001", success=True, result={"playback": "PLAY"})

    assert rec_done.completed_at is not None
    assert rec_done.completed_at_iso is not None
    assert rec_done.completed_at >= rec_done.started_at
    assert rec_done.duration_ms is not None
    assert rec_done.duration_ms >= 40.0  # at least ~50ms
    assert rec_done.duration_s is not None
    assert rec_done.current_stage == CommandLifecycleStage.SUCCESS

    # Verify dictionary export
    d = rec_done.to_dict()
    assert d["command_id"] == "CMD-1001"
    assert d["started_at"] == rec_done.started_at
    assert d["started_at_iso"] == rec_done.started_at_iso
    assert d["completed_at"] == rec_done.completed_at
    assert d["completed_at_iso"] == rec_done.completed_at_iso
    assert d["duration_ms"] == rec_done.duration_ms
    assert d["duration_s"] == rec_done.duration_s


def test_failed_execution_timing():
    """2. Verify start and completion timestamps and duration for failed execution."""
    tracker = CommandLifecycleTracker()
    rec = tracker.create_command("PULL", session_id="sess-2", command_id="CMD-1002")

    tracker.track_execution_started("CMD-1002", target="IOT:LIGHT")
    time.sleep(0.02)
    rec_fail = tracker.track_failure("CMD-1002", error="Network unreachable", error_code="NET_ERR")

    assert rec_fail.current_stage == CommandLifecycleStage.FAILED
    assert rec_fail.started_at is not None
    assert rec_fail.completed_at is not None
    assert rec_fail.duration_ms is not None
    assert rec_fail.duration_ms >= 15.0
    assert rec_fail.error == "Network unreachable"
    assert rec_fail.error_code == "NET_ERR"


def test_cancelled_execution_timing():
    """3. Verify cancelled execution timing recording."""
    tracker = CommandLifecycleTracker()
    rec = tracker.create_command("LEFT", session_id="sess-3", command_id="CMD-1003")

    tracker.track_execution_started("CMD-1003")
    time.sleep(0.02)
    rec_cancel = tracker.track_cancelled("CMD-1003", reason="User aborted")

    assert rec_cancel.current_stage == CommandLifecycleStage.CANCELLED
    assert rec_cancel.started_at is not None
    assert rec_cancel.completed_at is not None
    assert rec_cancel.duration_ms is not None
    assert rec_cancel.duration_ms >= 15.0


def test_timeout_execution_timing():
    """4. Verify timeout execution timing recording."""
    tracker = CommandLifecycleTracker()
    rec = tracker.create_command("RIGHT", session_id="sess-4", command_id="CMD-1004")

    tracker.track_execution_started("CMD-1004")
    time.sleep(0.02)
    rec_timeout = tracker.track_timeout("CMD-1004", reason="Subsystem timed out after 2000ms")

    assert rec_timeout.current_stage == CommandLifecycleStage.TIMEOUT
    assert rec_timeout.started_at is not None
    assert rec_timeout.completed_at is not None
    assert rec_timeout.duration_ms is not None
    assert rec_timeout.duration_ms >= 15.0


def test_missing_start_timestamp_safe_fallback():
    """5. Verify safe fallback calculation when completion occurs without an explicit start timestamp."""
    tracker = CommandLifecycleTracker()
    rec = tracker.create_command("PUSH_LEFT", session_id="sess-5", command_id="CMD-1005")

    # Directly complete without track_execution_started
    time.sleep(0.02)
    rec_done = tracker.track_success("CMD-1005", result={"status": "ok"})

    assert rec_done.started_at is None
    assert rec_done.completed_at is not None
    # Falls back to created_at
    assert rec_done.duration_ms is not None
    assert rec_done.duration_ms >= 15.0
    assert rec_done.is_terminal is True


def test_repeated_terminal_updates_do_not_corrupt_timing():
    """6. Verify repeated terminal state updates do not overwrite original completion timestamp or duration."""
    tracker = CommandLifecycleTracker()
    rec = tracker.create_command("PUSH", command_id="CMD-1006")

    tracker.track_execution_started("CMD-1006")
    time.sleep(0.02)
    rec_done = tracker.track_execution_completed("CMD-1006", success=True)

    initial_completed_at = rec_done.completed_at
    initial_duration = rec_done.duration_ms

    time.sleep(0.02)
    # Subsequent terminal call
    rec_repeated = tracker.track_success("CMD-1006", result={"extra": 1})

    assert rec_repeated.completed_at == initial_completed_at
    assert rec_repeated.duration_ms == initial_duration


def test_explicit_helper_methods():
    """7. Verify record_start_timestamp, record_completion_timestamp, calculate_duration, get_execution_timing."""
    tracker = CommandLifecycleTracker()
    tracker.create_command("PUSH", command_id="CMD-1007")

    rec1 = tracker.record_start_timestamp("CMD-1007", target="DESKTOP:MEDIA")
    assert rec1.current_stage == CommandLifecycleStage.EXECUTION_STARTED
    assert rec1.started_at is not None

    time.sleep(0.02)
    rec2 = tracker.record_completion_timestamp("CMD-1007", status="SUCCESS", result={"ok": True})
    assert rec2.current_stage == CommandLifecycleStage.SUCCESS
    assert rec2.completed_at is not None

    duration = tracker.calculate_duration("CMD-1007")
    assert duration is not None
    assert duration >= 15.0

    timing = tracker.get_execution_timing("CMD-1007")
    assert timing is not None
    assert timing["command_id"] == "CMD-1007"
    assert timing["duration_ms"] == duration
    assert timing["status"] == "SUCCESS"


@pytest.mark.asyncio
async def test_concurrent_execution_timing_isolation():
    """8. Verify multiple simultaneous commands have independent timestamps and duration without cross-talk."""
    tracker = CommandLifecycleTracker()

    c1 = tracker.create_command("CMD_A", command_id="CMD-A")
    c2 = tracker.create_command("CMD_B", command_id="CMD-B")

    # Command A starts at t0
    t0 = time.time()
    tracker.track_execution_started("CMD-A", timestamp=t0)

    # Command B starts at t0 + 10ms
    t1 = t0 + 0.010
    tracker.track_execution_started("CMD-B", timestamp=t1)

    # Command A completes at t0 + 50ms (Duration = 50ms)
    t2 = t0 + 0.050
    rec_a = tracker.track_execution_completed("CMD-A", success=True, timestamp=t2)

    # Command B completes at t0 + 90ms (Duration = 80ms)
    t3 = t0 + 0.090
    rec_b = tracker.track_execution_completed("CMD-B", success=True, timestamp=t3)

    assert rec_a.started_at == t0
    assert rec_a.completed_at == t2
    assert rec_a.duration_ms == 50.0

    assert rec_b.started_at == t1
    assert rec_b.completed_at == t3
    assert rec_b.duration_ms == 80.0

    # Verify no timing cross-talk
    assert rec_a.duration_ms != rec_b.duration_ms


def test_pydantic_model_compatibility():
    """9. Verify CommandLifecycleModel validates and serializes timing fields."""
    tracker = CommandLifecycleTracker()
    rec = tracker.create_command("PUSH", command_id="CMD-1008")
    tracker.track_execution_started("CMD-1008")
    time.sleep(0.01)
    tracker.track_success("CMD-1008")

    d = rec.to_dict()
    model = CommandLifecycleModel.model_validate(d)

    assert model.command_id == "CMD-1008"
    assert model.current_stage == "SUCCESS"
    assert model.started_at is not None
    assert model.started_at_iso is not None
    assert model.completed_at is not None
    assert model.completed_at_iso is not None
    assert model.duration_ms is not None
    assert model.duration_s is not None


def test_state_manager_timing_integration():
    """10. Verify StateManager records active command timestamps and duration."""
    cmd = state_manager.register_active_command(
        command_id="CMD-1009",
        command="PUSH",
        domain="DESKTOP",
        app="YOUTUBE"
    )

    assert cmd["started_at"] is not None
    assert cmd["started_at_iso"] is not None
    assert cmd["completed_at"] is None
    assert cmd["duration_ms"] is None

    time.sleep(0.02)
    updated = state_manager.update_command_state("CMD-1009", status="SUCCESS")

    assert updated["completed_at"] is not None
    assert updated["completed_at_iso"] is not None
    assert updated["duration_ms"] is not None
    assert updated["duration_ms"] >= 15.0

    timing = state_manager.get_command_timing("CMD-1009")
    assert timing is not None
    assert timing["duration_ms"] == updated["duration_ms"]


def test_api_lifecycle_endpoints():
    """11. Verify REST API endpoints expose execution timing and duration."""
    client = TestClient(app)

    # 1. Dispatch command via API
    res = client.post("/api/v1/bci/command", json={"command": "PUSH", "session_id": "test_sess"})
    assert res.status_code == 200
    data = res.json()
    cid = data.get("command_id")
    assert cid is not None

    # 2. Check summary endpoint
    res_sum = client.get("/api/v1/lifecycle/summary")
    assert res_sum.status_code == 200
    sum_data = res_sum.json()
    assert sum_data["status"] == "success"
    assert "summary" in sum_data
    assert "avg_duration_ms" in sum_data["summary"]

    # 3. Check commands endpoint
    res_cmds = client.get("/api/v1/lifecycle/commands?limit=10")
    assert res_cmds.status_code == 200
    cmds_data = res_cmds.json()
    assert cmds_data["status"] == "success"
    assert len(cmds_data["commands"]) > 0

    # 4. Check specific command timing endpoint
    res_timing = client.get(f"/api/v1/lifecycle/{cid}/timing")
    assert res_timing.status_code == 200
    timing_data = res_timing.json()
    assert timing_data["status"] == "success"
    t = timing_data["timing"]
    assert t["command_id"] == cid
    assert t["started_at"] is not None or t["created_at"] is not None
