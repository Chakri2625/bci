import asyncio
import concurrent.futures
import pytest
from fastapi.testclient import TestClient
from main import app
from core.communication.intake import RequestIntake, request_intake
from core.queue.task_queue import TaskQueue, task_queue
from core.plugin_manager.manager import load_plugins, PLUGINS
from core.state.state_manager import state_manager

client = TestClient(app)

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.fixture(autouse=True)
def reset_environment():
    state_manager.states.clear()
    PLUGINS.clear()
    load_plugins()
    task_queue.clear()
    request_intake.total_received = 0
    request_intake.total_accepted = 0
    request_intake.total_rejected = 0

@pytest.mark.anyio
async def test_concurrent_request_intake_async_tasks():
    custom_queue = TaskQueue()
    intake = RequestIntake(queue=custom_queue)
    num_requests = 50

    async def submit_single(index):
        payload = {
            "domain": "embedded",
            "plugin": "rc_car",
            "commands": [{"command": "push", "delay": 0.1}]
        }
        return await intake.accept_request("automation", payload, session=f"session_{index}")

    results = await asyncio.gather(*(submit_single(i) for i in range(num_requests)))

    # 1. Verify all received a unique task ID and status started
    task_ids = [r["task_id"] for r in results]
    assert len(task_ids) == num_requests
    assert len(set(task_ids)) == num_requests, "All task IDs must be unique"
    for r in results:
        assert r["status"] == "started"

    # 2. Verify metrics and queue state
    metrics = intake.get_metrics()
    assert metrics["total_received"] == num_requests
    assert metrics["total_accepted"] == num_requests
    assert metrics["total_rejected"] == 0
    assert custom_queue.qsize() == num_requests

    # 3. Verify no lost requests
    queued_tasks = custom_queue.list_tasks(limit=100)
    assert len(queued_tasks) == num_requests

@pytest.mark.anyio
async def test_intake_validation_and_rejection():
    custom_queue = TaskQueue()
    intake = RequestIntake(queue=custom_queue)

    # Missing domain
    res1 = await intake.accept_request("automation", {"plugin": "rc_car", "commands": [{"command": "push"}]})
    assert res1["status"] == "rejected"
    assert "domain" in res1["error"]
    assert res1["task_id"] is None

    # Empty commands
    res2 = await intake.accept_request("automation", {"domain": "embedded", "plugin": "rc_car", "commands": []})
    assert res2["status"] == "rejected"
    assert "empty" in res2["error"]

    # Invalid payload type
    res3 = await intake.accept_request("automation", "invalid_payload")
    assert res3["status"] == "rejected"

    # Rejected tasks must not enter the execution queue
    assert custom_queue.qsize() == 0
    metrics = intake.get_metrics()
    assert metrics["total_rejected"] == 3
    assert metrics["total_accepted"] == 0

def test_concurrent_api_intake_multithreaded():
    num_threads = 20

    def call_api(index):
        payload = {
            "domain": "embedded",
            "plugin": "rc_car",
            "commands": [{"command": "push", "delay": 0.05}]
        }
        resp = client.post(f"/api/v1/automation/execute?session=thread_{index}", json=payload)
        return resp.status_code, resp.json()

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(call_api, range(num_threads)))

    for status_code, data in results:
        assert status_code == 200
        assert data["status"] == "started"
        assert "task_id" in data

    metrics_resp = client.get("/api/v1/intake/metrics")
    assert metrics_resp.status_code == 200
    metrics = metrics_resp.json()
    assert metrics["total_accepted"] >= num_threads

def test_generic_intake_endpoint_and_status():
    payload = {
        "request_type": "telemetry_batch",
        "payload": {"sensor": "gyro", "value": [1.0, 2.0, 3.0]},
        "custom_id": "custom_task_999"
    }
    resp = client.post("/api/v1/intake/submit", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "started"
    assert data["task_id"] == "custom_task_999"

    # Check status endpoint
    status_resp = client.get("/api/v1/intake/status/custom_task_999")
    assert status_resp.status_code == 200
    task_data = status_resp.json()
    assert task_data["task_id"] == "custom_task_999"
    assert task_data["request_type"] == "telemetry_batch"
    assert task_data["status"] in ["QUEUED", "PROCESSING", "COMPLETED"]
