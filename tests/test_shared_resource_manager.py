"""
Unit tests for Shared Resource Management Layer (Day 3 - Member 5).
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time
import pytest

from core.managers.shared_resource_manager import (
    Resource,
    ResourceState,
    SharedResourceManager,
)


def test_test1_register_resource():
    """Test 1 — Register resource: browser is registered and recognized."""
    manager = SharedResourceManager()
    registered = manager.register_resource("browser")

    assert registered is True
    assert manager.is_registered("browser") is True
    assert len(manager) == 1
    assert "browser" in manager


def test_test2_resource_initially_available():
    """Test 2 — Resource initially available: after registration, status is available."""
    manager = SharedResourceManager()
    manager.register_resource("browser")

    assert manager.is_available("browser") is True
    status = manager.get_resource_status("browser")
    assert status is not None
    assert status["status"] == "available"
    assert status["task_id"] is None


def test_test3_assign_resource():
    """Test 3 — Assign resource: Task 001 acquires browser."""
    manager = SharedResourceManager()
    manager.register_resource("browser")

    assigned = manager.assign_resource("browser", "task_001")
    assert assigned is True

    status = manager.get_resource_status("browser")
    assert status["status"] == "in_use"
    assert status["task_id"] == "task_001"
    assert status["acquired_at"] is not None


def test_test4_resource_becomes_unavailable():
    """Test 4 — Resource becomes unavailable when assigned to a task."""
    manager = SharedResourceManager()
    manager.register_resource("browser")
    manager.assign_resource("browser", "task_001")

    assert manager.is_available("browser") is False

    # Another task attempting to acquire it should be rejected
    rejected = manager.assign_resource("browser", "task_002")
    assert rejected is False


def test_test5_release_resource():
    """Test 5 — Release resource: Task 001 releases browser -> available again."""
    manager = SharedResourceManager()
    manager.register_resource("browser")
    manager.assign_resource("browser", "task_001")

    released = manager.release_resource("browser", "task_001")
    assert released is True
    assert manager.is_available("browser") is True

    status = manager.get_resource_status("browser")
    assert status["status"] == "available"
    assert status["task_id"] is None
    assert status["released_at"] is not None


def test_test6_duplicate_registration():
    """Test 6 — Duplicate registration: registering twice avoids duplication and preserves state."""
    manager = SharedResourceManager()
    assert manager.register_resource("browser") is True

    # Assign to task_001
    manager.assign_resource("browser", "task_001")

    # Second registration should return False and NOT overwrite current state
    assert manager.register_resource("browser") is False
    assert len(manager) == 1

    status = manager.get_resource_status("browser")
    assert status["status"] == "in_use"
    assert status["task_id"] == "task_001"


def test_test7_wrong_task_releases_resource():
    """Test 7 — Wrong task releases resource: Task 002 release attempt is rejected."""
    manager = SharedResourceManager()
    manager.register_resource("browser")
    manager.assign_resource("browser", "task_001")

    # Task 002 tries to release Task 001's resource
    rejected = manager.release_resource("browser", "task_002")
    assert rejected is False

    # Resource must remain assigned to Task 001
    assert manager.is_available("browser") is False
    status = manager.get_resource_status("browser")
    assert status["task_id"] == "task_001"
    assert status["status"] == "in_use"


def test_test8_multiple_independent_resources():
    """Test 8 — Multiple independent resources assigned to different tasks."""
    manager = SharedResourceManager()
    manager.register_resources(["browser", "notepad", "mqtt"])

    assert manager.assign_resource("browser", "task_001") is True
    assert manager.assign_resource("notepad", "task_002") is True
    assert manager.assign_resource("mqtt", "task_003") is True

    assert manager.is_available("browser") is False
    assert manager.is_available("notepad") is False
    assert manager.is_available("mqtt") is False

    all_res = manager.get_all_resources()
    assert all_res["browser"]["task_id"] == "task_001"
    assert all_res["notepad"]["task_id"] == "task_002"
    assert all_res["mqtt"]["task_id"] == "task_003"


def test_test9_concurrent_access_race_condition_protection():
    """Test 9 — Concurrent access: 20 threads simultaneously attempt to acquire the SAME resource.
    Guarantees exactly ONE thread succeeds and the rest are safely rejected."""
    manager = SharedResourceManager()
    manager.register_resource("browser")

    num_threads = 20
    results = []
    barrier = threading.Barrier(num_threads)

    def try_acquire(task_idx: int):
        barrier.wait()  # Synchronize all threads to start at the exact same moment
        task_id = f"task_{task_idx:03d}"
        success = manager.assign_resource("browser", task_id)
        return (task_id, success)

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(try_acquire, i) for i in range(num_threads)]
        for f in as_completed(futures):
            results.append(f.result())

    successes = [r for r in results if r[1] is True]
    failures = [r for r in results if r[1] is False]

    assert len(successes) == 1, f"Expected exactly 1 winner, got {len(successes)}"
    assert len(failures) == num_threads - 1

    winner_task_id = successes[0][0]
    status = manager.get_resource_status("browser")
    assert status["status"] == "in_use"
    assert status["task_id"] == winner_task_id


def test_concurrent_multi_resource_allocations():
    """Stress test: 50 threads allocating and releasing 5 different resources randomly."""
    manager = SharedResourceManager(default_resources=["res_1", "res_2", "res_3", "res_4", "res_5"])

    def worker(worker_id: int):
        task_id = f"worker_{worker_id}"
        for step in range(10):
            res_id = f"res_{step % 5 + 1}"
            acquired = manager.assign_resource(res_id, task_id)
            if acquired:
                time.sleep(0.001)
                manager.release_resource(res_id, task_id)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(25)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All resources should be released and available
    available = manager.get_available_resources()
    assert len(available) == 5


def test_task_resource_tracking_and_bulk_release():
    """Test tracking all resources held by a task and releasing them in bulk."""
    manager = SharedResourceManager(default_resources=["browser", "mqtt", "display", "serial"])
    
    manager.assign_resource("browser", "task_alpha")
    manager.assign_resource("mqtt", "task_alpha")
    manager.assign_resource("display", "task_beta")

    alpha_resources = manager.get_task_resources("task_alpha")
    assert sorted(alpha_resources) == ["browser", "mqtt"]

    beta_resources = manager.get_task_resources("task_beta")
    assert beta_resources == ["display"]

    # Release all for task_alpha
    released = manager.release_all_for_task("task_alpha")
    assert sorted(released) == ["browser", "mqtt"]
    assert manager.is_available("browser") is True
    assert manager.is_available("mqtt") is True
    assert manager.is_available("display") is False  # beta still holds display


def test_batch_atomic_resource_assignment():
    """Test atomic multi-resource assignment (all-or-nothing)."""
    manager = SharedResourceManager(default_resources=["browser", "notepad", "calculator"])
    
    # Pre-occupy calculator with task_001
    manager.assign_resource("calculator", "task_001")

    # task_002 requests browser, notepad, calculator atomically
    assigned = manager.assign_resources(["browser", "notepad", "calculator"], "task_002", atomic=True)
    assert assigned is False

    # Since it was atomic, neither browser nor notepad should have been assigned to task_002
    assert manager.is_available("browser") is True
    assert manager.is_available("notepad") is True
    assert manager.get_task_resources("task_002") == []


def test_idempotent_reassignment():
    """Test that assigning an already owned resource to the same task succeeds."""
    manager = SharedResourceManager(default_resources=["browser"])
    assert manager.assign_resource("browser", "task_001") is True
    # Same task re-assigns
    assert manager.assign_resource("browser", "task_001") is True
    assert manager.get_resource_status("browser")["task_id"] == "task_001"


def test_force_release_and_reset_all():
    """Test force release and reset all operations."""
    manager = SharedResourceManager(default_resources=["browser", "notepad"])
    manager.assign_resource("browser", "task_001")
    manager.assign_resource("notepad", "task_002")

    assert len(manager.get_occupied_resources()) == 2

    # Force release browser
    assert manager.force_release_resource("browser") is True
    assert manager.is_available("browser") is True
    assert manager.is_available("notepad") is False

    # Reset all
    manager.reset_all_states()
    assert len(manager.get_available_resources()) == 2
    assert len(manager.get_occupied_resources()) == 0


def test_resource_summary_and_model():
    """Test high-level summary metrics and Pydantic model serialization."""
    manager = SharedResourceManager(default_resources=["browser", "notepad", "calculator"])
    manager.assign_resource("browser", "task_001")

    summary = manager.get_resource_summary()
    assert summary["total_count"] == 3
    assert summary["available_count"] == 2
    assert summary["occupied_count"] == 1
    assert "browser" in summary["occupied_resources"]
    assert "notepad" in summary["available_resources"]

    res_model = manager.get_resource("browser")
    assert isinstance(res_model, Resource)
    assert res_model.resource_id == "browser"
    assert res_model.status == ResourceState.IN_USE.value
    assert res_model.task_id == "task_001"
    assert res_model.is_available() is False
