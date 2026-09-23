import asyncio
import time
import pytest
from core.queue.task_queue import TaskQueue, AsyncTask, TaskStatus
from core.plugin_manager.manager import register_plugin, get_plugin, execute
from core.events.event_bus import EventBus


@pytest.mark.asyncio
async def test_async_task_lifecycle_success():
    async def sample_async_func(x, y):
        await asyncio.sleep(0.01)
        return x + y

    task = AsyncTask(target=sample_async_func, args=(3, 7), name="add_task")
    assert task.status == TaskStatus.QUEUED
    assert task.created_at is not None

    res = await task.execute()
    assert res == 10
    assert task.result == 10
    assert task.status == TaskStatus.COMPLETED
    assert task.started_at is not None
    assert task.completed_at is not None
    assert task.completed_at >= task.started_at
    assert task.error is None


@pytest.mark.asyncio
async def test_sync_task_execution_in_thread():
    def sample_sync_func(a, b):
        time.sleep(0.01)
        return a * b

    task = AsyncTask(target=sample_sync_func, args=(4, 5), name="mult_task")
    res = await task.execute()
    assert res == 20
    assert task.result == 20
    assert task.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_async_task_error_handling():
    async def failing_coro():
        await asyncio.sleep(0.01)
        raise ValueError("Simulated async failure")

    task = AsyncTask(target=failing_coro, name="fail_task")
    res = await task.execute()
    assert task.status == TaskStatus.FAILED
    assert "Simulated async failure" in task.error
    assert res == {"status": "error", "message": "Simulated async failure"}


@pytest.mark.asyncio
async def test_task_cancellation_before_execution():
    task = AsyncTask(target=lambda: "done", name="cancel_me")
    cancelled = task.cancel()
    assert cancelled is True
    assert task.status == TaskStatus.CANCELLED

    res = await task.execute()
    assert res is None
    assert task.status == TaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_task_queue_submit_background():
    tq = TaskQueue()
    completed_event = asyncio.Event()

    async def background_worker(value):
        await asyncio.sleep(0.02)
        completed_event.set()
        return f"result_{value}"

    task = tq.submit_background(background_worker, 42, name="bg_task")
    assert task.id in tq.tasks
    assert task.status in (TaskStatus.QUEUED, TaskStatus.RUNNING)

    await asyncio.wait_for(completed_event.wait(), timeout=1.0)
    # Give the runner a tiny moment to record history
    await asyncio.sleep(0.01)

    task_info = tq.get_task(task.id)
    assert task_info is not None
    assert task_info["status"] == TaskStatus.COMPLETED
    assert task_info["result"] == "result_42"


@pytest.mark.asyncio
async def test_task_queue_enqueue_dequeue():
    tq = TaskQueue()
    task = await tq.enqueue(lambda: "hello_queue")
    assert isinstance(task, AsyncTask)

    dequeued = await tq.dequeue()
    assert dequeued.id == task.id

    res = await dequeued.execute()
    assert res == "hello_queue"
    assert dequeued.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_plugin_execute_async_and_sync():
    class DummyAsyncPlugin:
        async def execute(self, command, payload=None):
            await asyncio.sleep(0.01)
            return {"status": "success", "echo": command, "type": "async"}

    class DummySyncPlugin:
        def execute(self, command, payload=None):
            return {"status": "success", "echo": command, "type": "sync"}

    register_plugin("dummy_async", DummyAsyncPlugin())
    register_plugin("dummy_sync", DummySyncPlugin())

    res_async = await execute("dummy_async", "PING", {"test": 1})
    assert res_async["status"] == "success"
    assert res_async["type"] == "async"

    res_sync = await execute("dummy_sync", "PING", {"test": 2})
    assert res_sync["status"] == "success"
    assert res_sync["type"] == "sync"

    res_missing = await execute("non_existent_plugin", "TEST", {})
    assert res_missing["status"] == "error"
    assert "Plugin not found" in res_missing["message"]


@pytest.mark.asyncio
async def test_event_bus_async_and_sync_subscribers():
    eb = EventBus()
    received = []

    async def async_sub(payload):
        await asyncio.sleep(0.01)
        received.append(("async", payload))

    def sync_sub(payload):
        received.append(("sync", payload))

    def faulty_sub(payload):
        raise RuntimeError("Subscriber exception")

    eb.subscribe("TEST_EVENT", async_sub)
    eb.subscribe("TEST_EVENT", faulty_sub)
    eb.subscribe("TEST_EVENT", sync_sub)

    await eb.publish("TEST_EVENT", {"data": 123})

    assert ("async", {"data": 123}) in received
    assert ("sync", {"data": 123}) in received

    # Unsubscribe test
    eb.unsubscribe("TEST_EVENT", sync_sub)
    received.clear()
    await eb.publish("TEST_EVENT", {"data": 456})
    assert ("async", {"data": 456}) in received
    assert ("sync", {"data": 456}) not in received
