import pytest
import asyncio
import time
from core.managers.resource_lock_manager import (
    ResourceLockManager,
    ResourceConflictError,
    resource_lock_manager,
)
from core.orchestration.ecosystem_orchestrator import EcosystemOrchestrator
from core.state.state_manager import state_manager


@pytest.fixture(autouse=True)
def clean_locks_and_state():
    """Reset locks and state before and after each test."""
    resource_lock_manager.clear()
    state_manager.states.clear()
    yield
    resource_lock_manager.clear()
    state_manager.states.clear()


def test_same_resource_prevents_simultaneous_execution():
    """
    Ensure that multiple operations targeting the SAME resource cannot execute
    simultaneously and are serialized safely.
    """
    async def run():
        mgr = ResourceLockManager()
        resource = "device:LIGHT_01"
        execution_timeline = []

        async def task(task_id: str, duration: float):
            async with mgr.lock(resource, owner=task_id):
                execution_timeline.append(f"start_{task_id}")
                await asyncio.sleep(duration)
                execution_timeline.append(f"end_{task_id}")

        # Launch task_1 and task_2 concurrently for the exact same resource
        await asyncio.gather(
            task("t1", 0.05),
            task("t2", 0.02)
        )

        # Verify strict non-overlapping execution: t1 starts & finishes before t2 starts
        assert execution_timeline == ["start_t1", "end_t1", "start_t2", "end_t2"]

    asyncio.run(run())


def test_different_resources_execute_concurrently():
    """
    Ensure that operations targeting DIFFERENT resources do NOT block each other
    and execute concurrently in parallel.
    """
    async def run():
        mgr = ResourceLockManager()
        res_a = "device:LIGHT_01"
        res_b = "device:FAN_02"
        execution_timeline = []

        async def task_a():
            async with mgr.lock(res_a, owner="task_a"):
                execution_timeline.append("start_a")
                await asyncio.sleep(0.06)
                execution_timeline.append("end_a")

        async def task_b():
            await asyncio.sleep(0.01)  # start shortly after task_a starts
            async with mgr.lock(res_b, owner="task_b"):
                execution_timeline.append("start_b")
                await asyncio.sleep(0.02)
                execution_timeline.append("end_b")

        await asyncio.gather(task_a(), task_b())

        # Task B should start and finish while Task A is still running
        assert execution_timeline == ["start_a", "start_b", "end_b", "end_a"]

    asyncio.run(run())


def test_lock_released_after_successful_execution():
    """
    Verify that the resource lock is immediately and cleanly released
    following successful execution, allowing subsequent operations to acquire it.
    """
    async def run():
        mgr = ResourceLockManager()
        resource = "app:PYTHON:YOUTUBE"

        assert not mgr.is_locked(resource)
        assert mgr.get_holder(resource) is None

        async with mgr.lock(resource, owner="op_1"):
            assert mgr.is_locked(resource)
            assert mgr.get_holder(resource) == "op_1"

        # Must be released after exiting context
        assert not mgr.is_locked(resource)
        assert mgr.get_holder(resource) is None

        # Next operation can acquire without delay
        acquired = await mgr.acquire(resource, owner="op_2", blocking=False)
        assert acquired is True
        assert mgr.is_locked(resource)
        assert mgr.get_holder(resource) == "op_2"
        await mgr.release(resource, owner="op_2")
        assert not mgr.is_locked(resource)

    asyncio.run(run())


def test_lock_released_after_execution_failure():
    """
    Verify that the resource lock is guaranteed to be released even if
    an exception/failure occurs inside the critical section.
    """
    async def run():
        mgr = ResourceLockManager()
        resource = "device:PUMP_01"

        with pytest.raises(RuntimeError, match="Simulated crash"):
            async with mgr.lock(resource, owner="failing_task"):
                assert mgr.is_locked(resource)
                assert mgr.get_holder(resource) == "failing_task"
                raise RuntimeError("Simulated crash")

        # Lock MUST be released despite exception
        assert not mgr.is_locked(resource)
        assert mgr.get_holder(resource) is None

        # Subsequent task must be able to acquire cleanly
        async with mgr.lock(resource, owner="recovery_task"):
            assert mgr.is_locked(resource)
            assert mgr.get_holder(resource) == "recovery_task"

        assert not mgr.is_locked(resource)

    asyncio.run(run())


def test_non_blocking_conflict_rejection():
    """
    Verify non-blocking acquisition raises ResourceConflictError or returns False
    when a resource is already locked.
    """
    async def run():
        mgr = ResourceLockManager()
        resource = "device:LIGHT_01"

        acquired = await mgr.acquire(resource, owner="primary_owner", blocking=True)
        assert acquired is True

        # Non-blocking acquire should fail immediately
        second_acquire = await mgr.acquire(resource, owner="secondary_owner", blocking=False)
        assert second_acquire is False

        # Context manager non-blocking should raise ResourceConflictError
        with pytest.raises(ResourceConflictError, match="currently locked"):
            async with mgr.lock(resource, owner="secondary_owner", blocking=False):
                pass

        await mgr.release(resource, owner="primary_owner")
        assert not mgr.is_locked(resource)

    asyncio.run(run())


def test_orchestrator_resource_locking_integration(monkeypatch):
    """
    Verify EcosystemOrchestrator applies resource locking during action execution.
    """
    async def run():
        orchestrator = EcosystemOrchestrator()
        session_1 = "session_test_1"
        session_2 = "session_test_2"

        # Set state to Level 3 IOT LIGHT
        state_manager.update_state(session_1, {
            "current_level": 3,
            "active_domain": "IOT",
            "active_app": "LIGHT"
        })
        state_manager.update_state(session_2, {
            "current_level": 3,
            "active_domain": "IOT",
            "active_app": "LIGHT"
        })

        execution_order = []

        # Mock execute to simulate real execution delay and record order
        async def mock_execute(plugin_id, command, payload):
            device_id = payload.get("device_id")
            execution_order.append(f"start_{device_id}")
            await asyncio.sleep(0.04)
            execution_order.append(f"end_{device_id}")
            return {"status": "success", "result": {"status": "success", "device_id": device_id}}

        monkeypatch.setattr("core.orchestration.ecosystem_orchestrator.execute", mock_execute)

        # 1. Test SAME device simultaneously -> serialized
        await asyncio.gather(
            orchestrator.process_command("RIGHT", session=session_1, device_id="LIGHT_99"),
            orchestrator.process_command("RIGHT", session=session_2, device_id="LIGHT_99")
        )
        assert execution_order == ["start_LIGHT_99", "end_LIGHT_99", "start_LIGHT_99", "end_LIGHT_99"]

        # Clear order
        execution_order.clear()

        # 2. Test DIFFERENT devices simultaneously -> concurrent
        await asyncio.gather(
            orchestrator.process_command("RIGHT", session=session_1, device_id="LIGHT_A"),
            orchestrator.process_command("RIGHT", session=session_2, device_id="LIGHT_B")
        )
        # Both start before either finishes
        assert execution_order[0].startswith("start_")
        assert execution_order[1].startswith("start_")

    asyncio.run(run())
