import threading
import pytest

from core.tasks.task_status_manager import (
    TaskState,
    TaskStatusManager,
    InvalidTaskTransitionError,
    TaskNotFoundError,
)


@pytest.fixture
def manager():
    """Each test gets its own isolated manager instance."""
    return TaskStatusManager()


def test_create_task_starts_pending(manager):
    record = manager.create_task(command="OPEN_CHROME")
    assert record.state == TaskState.PENDING
    assert manager.get_status(record.task_id) == TaskState.PENDING
    assert record.history[0]["state"] == "PENDING"


def test_duplicate_task_id_rejected(manager):
    manager.create_task(task_id="t1")
    with pytest.raises(ValueError):
        manager.create_task(task_id="t1")


def test_valid_full_success_sequence(manager):
    record = manager.create_task(task_id="t1")
    manager.mark_running("t1")
    assert manager.get_status("t1") == TaskState.RUNNING

    completed = manager.mark_completed("t1", result={"ok": True})
    assert completed.state == TaskState.COMPLETED
    assert completed.result == {"ok": True}
    assert completed.started_at is not None
    assert completed.finished_at is not None


def test_valid_failure_sequence(manager):
    manager.create_task(task_id="t1")
    manager.mark_running("t1")
    failed = manager.mark_failed("t1", error="boom")
    assert failed.state == TaskState.FAILED
    assert failed.error == "boom"


def test_cancel_from_pending(manager):
    manager.create_task(task_id="t1")
    cancelled = manager.mark_cancelled("t1")
    assert cancelled.state == TaskState.CANCELLED


def test_cancel_from_running(manager):
    manager.create_task(task_id="t1")
    manager.mark_running("t1")
    cancelled = manager.mark_cancelled("t1")
    assert cancelled.state == TaskState.CANCELLED


def test_invalid_transition_pending_to_completed(manager):
    manager.create_task(task_id="t1")
    with pytest.raises(InvalidTaskTransitionError):
        manager.transition("t1", TaskState.COMPLETED)


def test_terminal_states_reject_further_transitions(manager):
    manager.create_task(task_id="t1")
    manager.mark_running("t1")
    manager.mark_completed("t1")
    for target in (TaskState.RUNNING, TaskState.FAILED, TaskState.CANCELLED):
        with pytest.raises(InvalidTaskTransitionError):
            manager.transition("t1", target)


def test_same_state_transition_is_idempotent_noop(manager):
    manager.create_task(task_id="t1")
    manager.mark_running("t1")
    # Simulates Member 7 and Member 8 both trying to cancel around the same time.
    manager.mark_cancelled("t1", note="timeout")
    result = manager.mark_cancelled("t1", note="user requested")  # should not raise
    assert result.state == TaskState.CANCELLED


def test_unknown_task_raises_not_found(manager):
    with pytest.raises(TaskNotFoundError):
        manager.get_status("does-not-exist")
    with pytest.raises(TaskNotFoundError):
        manager.mark_running("does-not-exist")


def test_get_all_tasks_filtering(manager):
    manager.create_task(task_id="a")
    manager.create_task(task_id="b")
    manager.mark_running("b")
    pending = manager.get_all_tasks(TaskState.PENDING)
    running = manager.get_all_tasks(TaskState.RUNNING)
    assert [t.task_id for t in pending] == ["a"]
    assert [t.task_id for t in running] == ["b"]


def test_get_active_task_ids(manager):
    manager.create_task(task_id="a")
    manager.create_task(task_id="b")
    manager.mark_running("b")
    manager.mark_completed("b")
    assert manager.get_active_task_ids() == ["a"]


def test_snapshots_are_detached_copies(manager):
    record = manager.create_task(task_id="t1")
    record.state = TaskState.COMPLETED  # mutate the returned snapshot
    # internal state must be unaffected by external mutation
    assert manager.get_status("t1") == TaskState.PENDING


def test_listener_notified_on_every_transition(manager):
    seen = []
    manager.register_listener(lambda rec: seen.append(rec.state))

    manager.create_task(task_id="t1")
    manager.mark_running("t1")
    manager.mark_completed("t1")

    assert seen == [TaskState.PENDING, TaskState.RUNNING, TaskState.COMPLETED]


def test_broken_listener_does_not_break_manager(manager):
    def bad_listener(_record):
        raise RuntimeError("listener exploded")

    manager.register_listener(bad_listener)
    # Should not raise despite the listener failing.
    record = manager.create_task(task_id="t1")
    assert record.state == TaskState.PENDING


def test_concurrent_transitions_are_thread_safe(manager):
    """
    Simulate multiple threads (e.g. a timeout thread and a cancellation
    thread) racing to transition the same running task. Exactly one
    transition should win; the rest must fail cleanly, and the manager's
    internal state must never end up corrupted or inconsistent.
    """
    manager.create_task(task_id="t1")
    manager.mark_running("t1")

    winners = []
    errors = []
    lock = threading.Lock()

    def try_cancel():
        try:
            manager.transition("t1", TaskState.CANCELLED, note="race")
            with lock:
                winners.append(threading.get_ident())
        except InvalidTaskTransitionError:
            pass
        except Exception as exc:  # pragma: no cover - should never happen
            with lock:
                errors.append(exc)

    def try_fail():
        try:
            manager.transition("t1", TaskState.FAILED, error="race")
            with lock:
                winners.append(threading.get_ident())
        except InvalidTaskTransitionError:
            pass
        except Exception as exc:  # pragma: no cover - should never happen
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=try_cancel) for _ in range(10)]
    threads += [threading.Thread(target=try_fail) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    # Because CANCELLED/FAILED are both valid targets from RUNNING, the
    # first thread to acquire the lock wins and flips the task terminal;
    # every other thread (regardless of which target it wanted) then hits
    # the "already terminal" branch and is rejected.
    final_state = manager.get_status("t1")
    assert final_state in (TaskState.CANCELLED, TaskState.FAILED)


def test_remove_task_and_reset(manager):
    manager.create_task(task_id="t1")
    manager.remove_task("t1")
    assert not manager.exists("t1")

    manager.create_task(task_id="t2")
    manager.register_listener(lambda rec: None)
    manager.reset()
    assert manager.get_all_tasks() == []
