"""
Unit tests for Command Priority and Ordering Manager (Member 7).
"""

from datetime import datetime
import pytest

from core.managers.priority_manager import (
    PriorityLevel,
    PriorityManager,
    get_command_priority,
    parse_priority,
)
from core.validation.command_validator import (
    validate_command,
    validate_and_prioritize,
)
from models.command_models import NavigationCommand


def test_priority_ordering_high_normal_low():
    """Normal (3) + High (2) + Low (4) orders as High -> Normal -> Low."""
    pm = PriorityManager()
    pm.enqueue("OPEN")    # Normal (3)
    pm.enqueue("MOVE")    # High (2)
    pm.enqueue("INFO")    # Low (4)

    assert pm.dequeue() == "MOVE"
    assert pm.dequeue() == "OPEN"
    assert pm.dequeue() == "INFO"
    assert pm.is_empty()


def test_same_priority_maintains_arrival_order():
    """STOP 1 -> STOP 2 -> STOP 3 (P1) maintains FIFO."""
    pm = PriorityManager()
    pm.enqueue({"command": "STOP", "id": 1})
    pm.enqueue({"command": "EMERGENCY_STOP", "id": 2})
    pm.enqueue({"command": "HALT", "id": 3})

    first = pm.dequeue()
    second = pm.dequeue()
    third = pm.dequeue()

    assert first["id"] == 1
    assert second["id"] == 2
    assert third["id"] == 3


def test_normal_priority_fifo():
    """A -> B -> C (P3) maintains FIFO."""
    pm = PriorityManager()
    pm.enqueue("OPEN")
    pm.enqueue("CLOSE")
    pm.enqueue("SELECT")

    assert pm.dequeue() == "OPEN"
    assert pm.dequeue() == "CLOSE"
    assert pm.dequeue() == "SELECT"


def test_dequeue_empty_queue_returns_none():
    """Empty queue safely returns None."""
    pm = PriorityManager()
    assert pm.dequeue() is None
    assert pm.peek() is None
    assert pm.is_empty()
    assert len(pm) == 0


def test_clear_empties_queue():
    """clear() safely resets the queue."""
    pm = PriorityManager()
    pm.enqueue("MOVE")
    pm.enqueue("STOP")
    assert len(pm) == 2

    pm.clear()
    assert len(pm) == 0
    assert pm.is_empty()
    assert pm.dequeue() is None


def test_mixed_priorities_ordering():
    """A(P3), B(P1), C(P4), D(P2) dequeues as B -> D -> A -> C."""
    pm = PriorityManager()
    pm.enqueue("OPEN")      # A - Normal (3)
    pm.enqueue("STOP")      # B - Critical (1)
    pm.enqueue("INFO")      # C - Low (4)
    pm.enqueue("PUSH")      # D - High (2)

    assert pm.dequeue() == "STOP"
    assert pm.dequeue() == "PUSH"
    assert pm.dequeue() == "OPEN"
    assert pm.dequeue() == "INFO"


def test_interleaved_enqueue_and_dequeue():
    """Streaming arrival with preemption by higher priority."""
    pm = PriorityManager()
    pm.enqueue("OPEN")      # Normal (3)
    pm.enqueue("STATUS")    # Low (4)

    # First dequeued should be OPEN
    assert pm.dequeue() == "OPEN"

    # Higher priority arrives while STATUS is waiting
    pm.enqueue("HALT")      # Critical (1)
    pm.enqueue("MOVE")      # High (2)

    assert pm.dequeue() == "HALT"
    assert pm.dequeue() == "MOVE"
    assert pm.dequeue() == "STATUS"
    assert pm.is_empty()


def test_unknown_command_gets_default_normal_priority():
    """Unrecognized command safely defaults to P3."""
    pm = PriorityManager()
    prio = pm.enqueue("CUSTOM_UNKNOWN_ACTION")
    assert prio == PriorityLevel.NORMAL
    assert pm.dequeue() == "CUSTOM_UNKNOWN_ACTION"


def test_invalid_explicit_priority_falls_back():
    """Handles invalid priorities without crashing."""
    pm = PriorityManager()
    # Invalid priority number or string should fallback to command default
    prio = pm.enqueue("MOVE", priority=999)
    assert prio == PriorityLevel.HIGH

    prio_invalid_str = pm.enqueue("UNKNOWN", priority="SUPER_HIGH_INVALID")
    assert prio_invalid_str == PriorityLevel.NORMAL


def test_string_priority_names():
    """Handles string priority names ('CRITICAL', etc.)."""
    pm = PriorityManager()
    pm.enqueue("TASK_A", priority="LOW")
    pm.enqueue("TASK_B", priority="CRITICAL")
    pm.enqueue("TASK_C", priority="HIGH")
    pm.enqueue("TASK_D", priority="NORMAL")

    assert pm.dequeue() == "TASK_B"  # CRITICAL
    assert pm.dequeue() == "TASK_C"  # HIGH
    assert pm.dequeue() == "TASK_D"  # NORMAL
    assert pm.dequeue() == "TASK_A"  # LOW


def test_enqueue_batch():
    """Ingests and orders batch commands."""
    pm = PriorityManager()
    batch = ["INFO", "BRAKE", "PUSH_LEFT", "START"]
    priorities = pm.enqueue_batch(batch)

    assert priorities == [
        PriorityLevel.LOW,
        PriorityLevel.CRITICAL,
        PriorityLevel.HIGH,
        PriorityLevel.NORMAL,
    ]
    assert pm.dequeue() == "BRAKE"
    assert pm.dequeue() == "PUSH_LEFT"
    assert pm.dequeue() == "START"
    assert pm.dequeue() == "INFO"


def test_peek_does_not_remove_command():
    """Inspects top command without modifying queue."""
    pm = PriorityManager()
    pm.enqueue("STOP")
    pm.enqueue("MOVE")

    assert pm.peek() == "STOP"
    assert len(pm) == 2
    assert pm.dequeue() == "STOP"
    assert pm.peek() == "MOVE"
    assert len(pm) == 1


def test_validation_to_priority_pipeline():
    """Member 6 validation -> Member 7 priority enqueue."""
    valid_data = {
        "command_id": "CMD-0001",
        "command": "PUSH",
        "timestamp": datetime.now().isoformat(),
    }
    is_valid, cmd_obj = validate_command(valid_data)
    assert is_valid is True

    pm = PriorityManager()
    prio = pm.enqueue(cmd_obj)
    assert prio == PriorityLevel.HIGH
    assert pm.peek().command == "PUSH"


def test_validate_and_prioritize_helper():
    """Unified validation and priority assignment."""
    pm = PriorityManager()
    valid_data = {
        "command_id": "CMD-0002",
        "command": "RIGHT",
        "timestamp": datetime.now().isoformat(),
    }

    is_valid, cmd_obj, prio = validate_and_prioritize(valid_data, priority_manager=pm)
    assert is_valid is True
    assert prio == PriorityLevel.HIGH
    assert len(pm) == 1

    invalid_data = {
        "command_id": "INVALID",
        "command": "NOT_ALLOWED",
    }
    is_valid_inv, err_resp, prio_inv = validate_and_prioritize(invalid_data, priority_manager=pm)
    assert is_valid_inv is False
    assert prio_inv is None
    assert len(pm) == 1


def test_pass_ordered_commands_to_conflict_prevention_mock():
    """Output delivery for Member 8 conflict prevention."""
    pm = PriorityManager()
    pm.enqueue({"command_id": "CMD-1001", "command": "PUSH_RIGHT"})
    pm.enqueue({"command_id": "CMD-1002", "command": "STOP"})
    pm.enqueue({"command_id": "CMD-1003", "command": "LOG"})

    # Member 8 consumer simulation
    processed_for_conflict_check = []
    while not pm.is_empty():
        next_cmd = pm.dequeue()
        processed_for_conflict_check.append(next_cmd["command_id"])

    assert processed_for_conflict_check == ["CMD-1002", "CMD-1001", "CMD-1003"]
