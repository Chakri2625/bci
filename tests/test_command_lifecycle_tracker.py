"""
Test Suite for Command Lifecycle Tracker.
-----------------------------------------
Validates:
1. Command lifecycle stages and terminal state checks.
2. Command creation with auto-generated and custom Command IDs.
3. Validation status tracking (VALIDATING, VALIDATED, VALIDATION_FAILED).
4. Queue status tracking (QUEUED, priority, queue_position).
5. Execution start tracking (EXECUTION_STARTED, target subsystem).
6. Execution completion tracking (EXECUTION_COMPLETED, duration calculation).
7. Success/failure tracking (SUCCESS, FAILED, error codes, results).
8. Cancellation and Timeout tracking.
9. Session ID & Command ID multi-tenant indexing and querying.
10. Active vs completed command querying and audit trail export.
11. Summary statistics and metrics aggregation.
12. Thread-safety under concurrent lifecycle updates.
"""

import threading
import time
import pytest

from core.managers.lifecycle_tracker import (
    CommandLifecycleStage,
    CommandLifecycleRecord,
    CommandLifecycleTracker,
    LifecycleTransition,
    lifecycle_tracker,
    TERMINAL_STAGES,
)
from core.state.state_manager import StateManager
from models.command_models import CommandLifecycleModel, LifecycleTransitionModel


@pytest.fixture
def tracker():
    """Create a fresh isolated tracker instance for each test."""
    return CommandLifecycleTracker()


# =========================================================================
# 1. LIFECYCLE STAGES DEFINITION & PROPERTIES
# =========================================================================

def test_lifecycle_stages_definition():
    """Verify all required lifecycle stages exist."""
    stages = [
        CommandLifecycleStage.CREATED,
        CommandLifecycleStage.VALIDATING,
        CommandLifecycleStage.VALIDATED,
        CommandLifecycleStage.VALIDATION_FAILED,
        CommandLifecycleStage.QUEUED,
        CommandLifecycleStage.EXECUTION_STARTED,
        CommandLifecycleStage.EXECUTION_COMPLETED,
        CommandLifecycleStage.SUCCESS,
        CommandLifecycleStage.FAILED,
        CommandLifecycleStage.CANCELLED,
        CommandLifecycleStage.TIMEOUT,
    ]
    for stage in stages:
        assert isinstance(stage.value, str)
        assert len(stage.value) > 0


def test_terminal_stages_classification(tracker):
    """Verify terminal vs non-terminal states."""
    rec = tracker.create_command("PUSH", session_id="s1")
    assert not rec.is_terminal

    tracker.track_validating(rec.command_id)
    assert not rec.is_terminal

    tracker.track_validation(rec.command_id, is_valid=True)
    assert not rec.is_terminal

    tracker.track_queued(rec.command_id)
    assert not rec.is_terminal

    tracker.track_execution_started(rec.command_id)
    assert not rec.is_terminal

    tracker.track_success(rec.command_id)
    assert rec.is_terminal


# =========================================================================
# 2. COMMAND CREATION TRACKING
# =========================================================================

def test_command_creation_default_and_custom_id(tracker):
    """Test command creation with auto-generated and explicit Command IDs."""
    rec1 = tracker.create_command("FORWARD", session_id="user_1")
    assert rec1.command_id.startswith("CMD-")
    assert rec1.session_id == "user_1"
    assert rec1.command == "FORWARD"
    assert rec1.current_stage == CommandLifecycleStage.CREATED
    assert len(rec1.history) == 1
    assert rec1.history[0].to_stage == CommandLifecycleStage.CREATED
    assert rec1.created_at > 0
    assert rec1.created_at_iso is not None

    rec2 = tracker.create_command(
        "STOP",
        session_id="user_2",
        command_id="CUSTOM-9999",
        domain="ROBOTICS",
        metadata={"source": "EMOTIV_BCI", "confidence": 0.98},
    )
    assert rec2.command_id == "CUSTOM-9999"
    assert rec2.session_id == "user_2"
    assert rec2.domain == "ROBOTICS"
    assert rec2.metadata["source"] == "EMOTIV_BCI"
    assert rec2.metadata["confidence"] == 0.98


# =========================================================================
# 3. VALIDATION STATUS TRACKING
# =========================================================================

def test_validation_success_and_failure_tracking(tracker):
    """Test tracking validation progression and failures."""
    rec = tracker.create_command("NAVIGATE", session_id="session_val")

    # In progress validation
    tracker.track_validating(rec.command_id, metadata={"validator": "SequenceValidator"})
    assert rec.current_stage == CommandLifecycleStage.VALIDATING

    # Passed validation
    tracker.track_validation(rec.command_id, is_valid=True, reason="Syntax and sequence valid")
    assert rec.current_stage == CommandLifecycleStage.VALIDATED
    assert rec.metadata["is_valid"] is True
    assert rec.metadata["validation_reason"] == "Syntax and sequence valid"

    # Failed validation command
    rec_fail = tracker.create_command("INVALID_COMBO", session_id="session_val")
    tracker.track_validation(
        rec_fail.command_id,
        is_valid=False,
        reason="Conflicting rule in Level 2",
        metadata={"rule_id": "RULE_CONFLICT_01"},
    )
    assert rec_fail.current_stage == CommandLifecycleStage.VALIDATION_FAILED
    assert rec_fail.metadata["is_valid"] is False
    assert rec_fail.metadata["rule_id"] == "RULE_CONFLICT_01"


# =========================================================================
# 4. QUEUE STATUS TRACKING
# =========================================================================

def test_queue_status_tracking(tracker):
    """Test tracking enqueued status with priority and position."""
    rec = tracker.create_command("PUSH", session_id="queue_test")
    tracker.track_validation(rec.command_id, is_valid=True)
    tracker.track_queued(rec.command_id, priority="CRITICAL", queue_position=0)

    assert rec.current_stage == CommandLifecycleStage.QUEUED
    assert rec.metadata["priority"] == "CRITICAL"
    assert rec.metadata["queue_position"] == 0
    assert any(t.to_stage == CommandLifecycleStage.QUEUED for t in rec.history)


# =========================================================================
# 5. EXECUTION START AND COMPLETION TRACKING
# =========================================================================

def test_execution_start_and_completion_timing(tracker):
    """Test start tracking, completion tracking, and accurate duration recording."""
    rec = tracker.create_command("PLAY_MEDIA", session_id="exec_test")
    tracker.track_validation(rec.command_id, is_valid=True)
    tracker.track_queued(rec.command_id, priority="NORMAL")

    tracker.track_execution_started(rec.command_id, target="MEDIA_PLUGIN")
    assert rec.current_stage == CommandLifecycleStage.EXECUTION_STARTED
    assert rec.started_at is not None
    assert rec.domain == "MEDIA_PLUGIN"

    time.sleep(0.02)  # Tiny delay for measurable duration

    tracker.track_execution_completed(
        rec.command_id,
        success=True,
        result={"status": "playing", "track_id": "123"},
        metadata={"bytes_streamed": 1024},
    )

    assert rec.current_stage == CommandLifecycleStage.SUCCESS
    assert rec.completed_at is not None
    assert rec.duration_ms is not None
    assert rec.duration_ms >= 15.0  # At least ~20ms
    assert rec.result == {"status": "playing", "track_id": "123"}
    assert rec.metadata["bytes_streamed"] == 1024


# =========================================================================
# 6. SUCCESS AND FAILURE TRACKING
# =========================================================================

def test_success_and_failure_terminal_transitions(tracker):
    """Test success and failure terminal pathways."""
    # Direct success
    rec_succ = tracker.create_command("VOLUME_UP")
    tracker.track_success(rec_succ.command_id, result={"volume": 80})
    assert rec_succ.current_stage == CommandLifecycleStage.SUCCESS
    assert rec_succ.result == {"volume": 80}
    assert rec_succ.is_terminal

    # Direct failure
    rec_fail = tracker.create_command("DRIVE_FORWARD")
    tracker.track_execution_started(rec_fail.command_id, target="RC_CAR")
    tracker.track_failure(
        rec_fail.command_id,
        error="Motor stall detected",
        error_code="ERR_MOTOR_STALL",
        metadata={"current_draw": 3.2},
    )
    assert rec_fail.current_stage == CommandLifecycleStage.FAILED
    assert rec_fail.error == "Motor stall detected"
    assert rec_fail.error_code == "ERR_MOTOR_STALL"
    assert rec_fail.metadata["current_draw"] == 3.2
    assert rec_fail.is_terminal


def test_cancelled_and_timeout_tracking(tracker):
    """Test cancellation and timeout tracking."""
    rec_cancel = tracker.create_command("UNSAFE_ACTION")
    tracker.track_cancelled(rec_cancel.command_id, reason="User aborted via framing window")
    assert rec_cancel.current_stage == CommandLifecycleStage.CANCELLED
    assert rec_cancel.error == "User aborted via framing window"
    assert rec_cancel.is_terminal

    rec_timeout = tracker.create_command("LONG_HTTP_POLL")
    tracker.track_execution_started(rec_timeout.command_id)
    tracker.track_timeout(rec_timeout.command_id, reason="Deadline exceeded (5000ms)")
    assert rec_timeout.current_stage == CommandLifecycleStage.TIMEOUT
    assert rec_timeout.error == "Deadline exceeded (5000ms)"
    assert rec_timeout.is_terminal


# =========================================================================
# 7. SESSION ID & COMMAND ID INTEGRATION & QUERYING
# =========================================================================

def test_session_isolation_and_lookup(tracker):
    """Test grouping and querying by session_id and command_id."""
    tracker.create_command("CMD_A1", session_id="session_A")
    tracker.create_command("CMD_A2", session_id="session_A")
    tracker.create_command("CMD_B1", session_id="session_B")

    cmds_a = tracker.get_session_commands("session_A")
    cmds_b = tracker.get_session_commands("session_B")

    assert len(cmds_a) == 2
    assert len(cmds_b) == 1
    assert cmds_a[0].command == "CMD_A1"
    assert cmds_a[1].command == "CMD_A2"
    assert cmds_b[0].command == "CMD_B1"


def test_active_commands_filtering(tracker):
    """Test filtering of active (in-flight) vs completed commands."""
    c1 = tracker.create_command("ACTIVE_1", session_id="s1")
    c2 = tracker.create_command("ACTIVE_2", session_id="s1")
    c3 = tracker.create_command("FINISHED_1", session_id="s1")

    tracker.track_execution_started(c1.command_id)
    tracker.track_queued(c2.command_id)
    tracker.track_success(c3.command_id)

    active_all = tracker.get_active_commands()
    active_s1 = tracker.get_active_commands(session_id="s1")

    assert len(active_all) == 2
    assert len(active_s1) == 2
    assert c1.command_id in [c.command_id for c in active_s1]
    assert c2.command_id in [c.command_id for c in active_s1]
    assert c3.command_id not in [c.command_id for c in active_s1]


# =========================================================================
# 8. AUDIT TRAIL EXPORT & SUMMARY METRICS
# =========================================================================

def test_summary_and_audit_trail_export(tracker):
    """Test metrics summary aggregation and audit log export."""
    c1 = tracker.create_command("ACTION_1", session_id="test_stats")
    tracker.track_execution_started(c1.command_id)
    time.sleep(0.01)
    tracker.track_success(c1.command_id)

    c2 = tracker.create_command("ACTION_2", session_id="test_stats")
    tracker.track_failure(c2.command_id, error="Network error")

    c3 = tracker.create_command("ACTION_3", session_id="test_stats")
    tracker.track_queued(c3.command_id)

    summary = tracker.get_summary("test_stats")
    assert summary["total_commands"] == 3
    assert summary["active_commands"] == 1
    assert summary["stage_counts"]["SUCCESS"] == 1
    assert summary["stage_counts"]["FAILED"] == 1
    assert summary["stage_counts"]["QUEUED"] == 1

    audit = tracker.export_audit_trail("test_stats")
    assert len(audit) == 3
    assert all("history" in item for item in audit)
    assert all("transitions_count" in item for item in audit)


# =========================================================================
# 9. PYDANTIC MODEL SERIALIZATION
# =========================================================================

def test_pydantic_model_compatibility(tracker):
    """Verify CommandLifecycleModel can validate and serialize tracker records."""
    rec = tracker.create_command(
        "CHROME_NAV", session_id="user_pydantic", domain="BROWSER"
    )
    tracker.track_validation(rec.command_id, is_valid=True)
    tracker.track_execution_started(rec.command_id, target="CHROME")
    tracker.track_success(rec.command_id, result={"url": "https://example.com"})

    data = rec.to_dict()
    model = CommandLifecycleModel(**data)

    assert model.command_id == rec.command_id
    assert model.current_stage == "SUCCESS"
    assert model.is_terminal is True
    assert model.domain == "BROWSER"
    assert len(model.history) == len(rec.history)
    assert model.history[-1].to_stage == "SUCCESS"


# =========================================================================
# 10. STATE MANAGER INTEGRATION
# =========================================================================

def test_state_manager_lifecycle_integration():
    """Test StateManager integration with lifecycle commands."""
    sm = StateManager()
    sm.add_command("session_sm", "PUSH", command_id="CMD-SM-001")
    state = sm.get_state("session_sm")

    assert state["last_command"] == "PUSH"
    assert state["last_command_id"] == "CMD-SM-001"
    assert "PUSH" in state["command_history"]


# =========================================================================
# 11. THREAD SAFETY & CONCURRENCY
# =========================================================================

def test_concurrent_lifecycle_tracking(tracker):
    """Test that concurrent lifecycle creations and transitions are thread-safe."""
    threads = []
    num_threads = 20
    commands_per_thread = 10

    def worker(worker_id: int):
        for i in range(commands_per_thread):
            session = f"session_worker_{worker_id}"
            rec = tracker.create_command(f"CMD_W_{worker_id}_{i}", session_id=session)
            tracker.track_validation(rec.command_id, is_valid=True)
            tracker.track_queued(rec.command_id, priority="HIGH")
            tracker.track_execution_started(rec.command_id, target="WORKER_TARGET")
            tracker.track_execution_completed(
                rec.command_id, success=True, result={"val": i}
            )

    for w in range(num_threads):
        t = threading.Thread(target=worker, args=(w,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    summary = tracker.get_summary()
    expected_total = num_threads * commands_per_thread
    assert summary["total_commands"] == expected_total
    assert summary["stage_counts"]["SUCCESS"] == expected_total
    assert summary["active_commands"] == 0
