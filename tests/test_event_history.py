"""
Test Suite for Event History Storage & API Structure (Member 7 - Mubeena)
==========================================================================
Validates:
1. Event Model initialization, serialization (to_dict/from_dict), aliases.
2. Storing events (single, multiple, custom fields, timestamps, durations).
3. Preservation of multiple events without overwriting.
4. Chronological order maintenance (asc & desc).
5. History retrieval and filtering (request_id, event_type, command, domain, status, time range).
6. Searching by Event ID (existing vs non-existent).
7. Searching/filtering by Request ID / Command ID.
8. Empty history handling and behavior.
9. Clearing event history.
10. Statistical metrics & summary generation.
11. Thread safety & concurrency under multi-threaded writes.
12. FastAPI REST API endpoints:
    - GET /api/v1/events/history
    - GET /api/v1/events/history/{event_id}
    - GET /api/v1/events/{event_id}
    - GET /api/v1/events/summary
    - POST /api/v1/events
    - DELETE /api/v1/events/history
    - POST /api/v1/events/clear
"""

import threading
import time
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.managers.event_history import (
    Event,
    EventType,
    EventStatus,
    EventHistoryManager,
    event_history_manager,
)
from api.event_history_routes import router as event_history_router


@pytest.fixture
def manager():
    """Create a fresh isolated EventHistoryManager instance for each test."""
    return EventHistoryManager()


@pytest.fixture
def api_client():
    """Create a test client configured with event history router."""
    app = FastAPI()
    app.include_router(event_history_router)
    # Clear singleton state before test
    event_history_manager.clear_event_history()
    client = TestClient(app)
    return client


# =========================================================================
# 1. EVENT MODEL TESTS
# =========================================================================

def test_event_model_initialization():
    """Verify Event object properly populates all structured fields."""
    event = Event(
        event_type=EventType.COMMAND_RECEIVED,
        command="SELECT_DESKTOP",
        domain="PYTHON",
        status=EventStatus.SUCCESS,
        request_id="REQ-1001",
        execution_duration=15.4,
        metadata={"source": "bci", "confidence": 0.98},
    )

    assert event.event_id.startswith("EVT-")
    assert event.request_id == "REQ-1001"
    assert event.command_id == "REQ-1001"
    assert event.event_type == "COMMAND_RECEIVED"
    assert event.command == "SELECT_DESKTOP"
    assert event.domain == "PYTHON"
    assert event.status == "SUCCESS"
    assert event.execution_duration == 15.4
    assert event.timestamp > 0
    assert "T" in event.timestamp_iso
    assert event.metadata["source"] == "bci"
    assert event.error is None


def test_event_model_to_dict_and_from_dict():
    """Verify Event serialization to and from dictionary."""
    orig = Event(
        event_type=EventType.COMMAND_FAILED,
        command="START_RC_CAR",
        domain="EMBEDDED",
        status=EventStatus.FAILED,
        request_id="REQ-8888",
        execution_duration=42.1,
        error="Connection timeout to broker",
        metadata={"retry_count": 3},
    )

    d = orig.to_dict()
    assert d["event_id"] == orig.event_id
    assert d["event_type"] == "COMMAND_FAILED"
    assert d["status"] == "FAILED"
    assert d["error"] == "Connection timeout to broker"

    rebuilt = Event.from_dict(d)
    assert rebuilt.event_id == orig.event_id
    assert rebuilt.request_id == orig.request_id
    assert rebuilt.command_id == orig.command_id
    assert rebuilt.event_type == orig.event_type
    assert rebuilt.domain == orig.domain
    assert rebuilt.status == orig.status
    assert rebuilt.execution_duration == orig.execution_duration
    assert rebuilt.error == orig.error
    assert rebuilt.metadata == orig.metadata


# =========================================================================
# 2. EVENT STORAGE & PRESERVATION TESTS
# =========================================================================

def test_store_single_event(manager):
    """Verify storing a single event generates correct record and updates count."""
    assert manager.count() == 0

    ev = manager.store_event(
        event_type=EventType.COMMAND_RECEIVED,
        command="NAVIGATE_HOME",
        domain="DESKTOP",
        request_id="REQ-001",
    )

    assert manager.count() == 1
    assert ev.event_id is not None
    assert ev.command == "NAVIGATE_HOME"
    assert ev.request_id == "REQ-001"


def test_store_multiple_events_preserved(manager):
    """Verify multiple events are preserved without overwriting previous events."""
    commands = ["MOVE_FORWARD", "MOVE_BACKWARD", "TURN_LEFT", "TURN_RIGHT", "STOP"]
    stored_ids = []

    for idx, cmd in enumerate(commands):
        ev = manager.store_event(
            event_type=EventType.EXECUTION_STARTED,
            command=cmd,
            domain="EMBEDDED",
            request_id=f"REQ-{idx}",
        )
        stored_ids.append(ev.event_id)

    assert manager.count() == 5
    # Ensure all stored IDs are distinct
    assert len(set(stored_ids)) == 5

    history = manager.get_event_history(as_dict=False)
    assert len(history) == 5
    for idx, ev in enumerate(history):
        assert ev.command == commands[idx]
        assert ev.event_id == stored_ids[idx]


def test_store_event_with_object(manager):
    """Verify manager can store pre-instantiated Event object directly."""
    custom_ev = Event(
        event_type="CUSTOM_PROBE",
        command="PING",
        domain="IOT",
        status=EventStatus.SUCCESS,
        request_id="REQ-CUSTOM",
    )

    stored = manager.store_event(custom_ev)
    assert stored is custom_ev
    assert manager.count() == 1
    assert manager.get_event_by_id(custom_ev.event_id, as_dict=False) is custom_ev


# =========================================================================
# 3. CHRONOLOGICAL ORDER TESTS
# =========================================================================

def test_chronological_order_preserved(manager):
    """Verify events are stored and retrieved in strict chronological order."""
    t0 = 1000.0
    manager.store_event(event_type="FIRST", timestamp=t0 + 1)
    manager.store_event(event_type="SECOND", timestamp=t0 + 2)
    manager.store_event(event_type="THIRD", timestamp=t0 + 3)

    history_asc = manager.get_event_history(order="asc")
    assert [e["event_type"] for e in history_asc] == ["FIRST", "SECOND", "THIRD"]

    history_desc = manager.get_event_history(order="desc")
    assert [e["event_type"] for e in history_desc] == ["THIRD", "SECOND", "FIRST"]


# =========================================================================
# 4. QUERYING, FILTERING & LOOKUP TESTS
# =========================================================================

def test_get_event_by_id(manager):
    """Verify O(1) lookup by event_id."""
    ev1 = manager.store_event(event_type="TYPE_A", request_id="R1")
    ev2 = manager.store_event(event_type="TYPE_B", request_id="R2")

    found1 = manager.get_event_by_id(ev1.event_id)
    assert found1 is not None
    assert found1["event_id"] == ev1.event_id
    assert found1["request_id"] == "R1"

    found2 = manager.get_event_by_id(ev2.event_id)
    assert found2 is not None
    assert found2["event_id"] == ev2.event_id

    # Non-existent ID returns None
    assert manager.get_event_by_id("NON_EXISTENT_ID") is None


def test_get_events_by_request_id(manager):
    """Verify grouping and retrieval by request_id."""
    manager.store_event(event_type="RECEIVED", request_id="REQ-55", command="PLAY")
    manager.store_event(event_type="ROUTED", request_id="REQ-55", domain="MEDIA")
    manager.store_event(event_type="COMPLETED", request_id="REQ-55", status="SUCCESS")
    # Unrelated event
    manager.store_event(event_type="RECEIVED", request_id="REQ-99", command="OTHER")

    req55_events = manager.get_events_by_request_id("REQ-55")
    assert len(req55_events) == 3
    assert [e["event_type"] for e in req55_events] == ["RECEIVED", "ROUTED", "COMPLETED"]

    req99_events = manager.get_events_by_request_id("REQ-99")
    assert len(req99_events) == 1

    empty_events = manager.get_events_by_request_id("UNKNOWN_REQ")
    assert empty_events == []


def test_filter_by_event_type(manager):
    """Verify filtering by event_type."""
    manager.store_event(event_type="COMMAND_SUCCESS")
    manager.store_event(event_type="COMMAND_FAILED")
    manager.store_event(event_type="COMMAND_SUCCESS")

    successes = manager.get_event_history(event_type="COMMAND_SUCCESS")
    assert len(successes) == 2

    failures = manager.get_event_history(event_type="COMMAND_FAILED")
    assert len(failures) == 1


def test_filter_by_domain(manager):
    """Verify filtering by domain."""
    manager.store_event(event_type="EVT1", domain="DESKTOP")
    manager.store_event(event_type="EVT2", domain="IOT")
    manager.store_event(event_type="EVT3", domain="DESKTOP")
    manager.store_event(event_type="EVT4", domain="AIML")

    desktop_evs = manager.get_event_history(domain="desktop")
    assert len(desktop_evs) == 2
    assert all(e["domain"] == "DESKTOP" for e in desktop_evs)

    iot_evs = manager.get_event_history(domain="IOT")
    assert len(iot_evs) == 1


def test_filter_by_status(manager):
    """Verify filtering by status."""
    manager.store_event(event_type="A", status="SUCCESS")
    manager.store_event(event_type="B", status="FAILED")
    manager.store_event(event_type="C", status="SUCCESS")

    failed = manager.get_event_history(status="FAILED")
    assert len(failed) == 1
    assert failed[0]["status"] == "FAILED"


def test_filter_by_command_substring(manager):
    """Verify filtering by command name or substring."""
    manager.store_event(event_type="E1", command="VOLUME_UP")
    manager.store_event(event_type="E2", command="VOLUME_DOWN")
    manager.store_event(event_type="E3", command="MUTE")

    vol_events = manager.get_event_history(command="VOLUME")
    assert len(vol_events) == 2

    mute_events = manager.get_event_history(command="MUTE")
    assert len(mute_events) == 1


def test_filter_by_timestamp_range(manager):
    """Verify filtering by start_time and end_time timestamps."""
    t0 = 2000.0
    manager.store_event(event_type="E1", timestamp=t0 + 10)
    manager.store_event(event_type="E2", timestamp=t0 + 20)
    manager.store_event(event_type="E3", timestamp=t0 + 30)
    manager.store_event(event_type="E4", timestamp=t0 + 40)

    res = manager.get_event_history(start_time=t0 + 15, end_time=t0 + 35)
    assert len(res) == 2
    assert [e["event_type"] for e in res] == ["E2", "E3"]


def test_pagination_limit_and_offset(manager):
    """Verify pagination with limit and offset."""
    for i in range(10):
        manager.store_event(event_type=f"EVT_{i}")

    page1 = manager.get_event_history(limit=3, offset=0)
    assert len(page1) == 3
    assert [e["event_type"] for e in page1] == ["EVT_0", "EVT_1", "EVT_2"]

    page2 = manager.get_event_history(limit=3, offset=3)
    assert len(page2) == 3
    assert [e["event_type"] for e in page2] == ["EVT_3", "EVT_4", "EVT_5"]


# =========================================================================
# 5. EMPTY HISTORY & CLEAR HISTORY TESTS
# =========================================================================

def test_empty_history_returns_proper_response(manager):
    """Verify query on empty manager returns empty list without error."""
    assert manager.count() == 0
    assert manager.get_event_history() == []
    assert manager.get_event_by_id("ANY") is None
    assert manager.get_events_by_request_id("ANY") == []

    summary = manager.get_summary()
    assert summary["total_events"] == 0
    assert summary["events_by_type"] == {}
    assert summary["events_by_status"] == {}


def test_clear_event_history(manager):
    """Verify clearing history resets all memory and indices."""
    manager.store_event(event_type="E1", request_id="R1")
    manager.store_event(event_type="E2", request_id="R2")
    assert manager.count() == 2

    cleared = manager.clear_event_history()
    assert cleared == 2
    assert manager.count() == 0
    assert manager.get_event_history() == []
    assert manager.get_events_by_request_id("R1") == []


# =========================================================================
# 6. SUMMARY & STATISTICAL METRICS TESTS
# =========================================================================

def test_get_summary_metrics(manager):
    """Verify statistical aggregation by type, domain, status, and duration."""
    manager.store_event(event_type="CMD", domain="DESKTOP", status="SUCCESS", execution_duration=10.0)
    manager.store_event(event_type="CMD", domain="DESKTOP", status="SUCCESS", execution_duration=20.0)
    manager.store_event(event_type="TRANSITION", domain="IOT", status="FAILED", execution_duration=30.0)

    summary = manager.get_summary()
    assert summary["total_events"] == 3
    assert summary["events_by_type"]["CMD"] == 2
    assert summary["events_by_type"]["TRANSITION"] == 1
    assert summary["events_by_status"]["SUCCESS"] == 2
    assert summary["events_by_status"]["FAILED"] == 1
    assert summary["events_by_domain"]["DESKTOP"] == 2
    assert summary["events_by_domain"]["IOT"] == 1
    assert summary["average_execution_duration_ms"] == 20.0


# =========================================================================
# 7. THREAD SAFETY & CONCURRENCY TESTS
# =========================================================================

def test_thread_safety_concurrent_writes(manager):
    """Verify concurrent event writes across multiple threads without data race."""
    num_threads = 10
    events_per_thread = 50

    def worker(thread_idx):
        for i in range(events_per_thread):
            manager.store_event(
                event_type="CONCURRENT_EVENT",
                command=f"CMD_{thread_idx}_{i}",
                request_id=f"REQ_T{thread_idx}",
                metadata={"thread": thread_idx, "iter": i},
            )

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert manager.count() == num_threads * events_per_thread

    # Verify per-thread request indexing
    for t in range(num_threads):
        req_events = manager.get_events_by_request_id(f"REQ_T{t}")
        assert len(req_events) == events_per_thread


# =========================================================================
# 8. REST API ENDPOINT TESTS (FastAPI TestClient)
# =========================================================================

def test_api_get_empty_history(api_client):
    """GET /api/v1/events/history on empty state."""
    res = api_client.get("/api/v1/events/history")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["count"] == 0
    assert data["total_stored"] == 0
    assert data["events"] == []


def test_api_post_create_event(api_client):
    """POST /api/v1/events storing a new event."""
    payload = {
        "event_type": "COMMAND_RECEIVED",
        "command": "LIGHTS_ON",
        "domain": "IOT",
        "status": "SUCCESS",
        "request_id": "REQ-API-101",
        "execution_duration": 8.5,
        "metadata": {"room": "living_room"},
    }
    res = api_client.post("/api/v1/events", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["status"] == "success"
    assert "event_id" in data
    assert data["event"]["command"] == "LIGHTS_ON"
    assert data["event"]["request_id"] == "REQ-API-101"
    assert data["event"]["domain"] == "IOT"


def test_api_get_history_with_filtering(api_client):
    """GET /api/v1/events/history with query parameters."""
    # Seed events
    api_client.post("/api/v1/events", json={"event_type": "TYPE_A", "domain": "DESKTOP", "request_id": "R1", "status": "SUCCESS"})
    api_client.post("/api/v1/events", json={"event_type": "TYPE_B", "domain": "EMBEDDED", "request_id": "R2", "status": "FAILED"})
    api_client.post("/api/v1/events", json={"event_type": "TYPE_A", "domain": "IOT", "request_id": "R3", "status": "SUCCESS"})

    # Filter by event_type
    res = api_client.get("/api/v1/events/history?event_type=TYPE_A")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 2

    # Filter by domain
    res = api_client.get("/api/v1/events/history?domain=embedded")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 1
    assert data["events"][0]["request_id"] == "R2"

    # Filter by request_id
    res = api_client.get("/api/v1/events/history?request_id=R3")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 1
    assert data["events"][0]["domain"] == "IOT"


def test_api_get_event_by_id(api_client):
    """GET /api/v1/events/history/{event_id} success and 404."""
    post_res = api_client.post("/api/v1/events", json={"event_type": "TEST_ID_LOOKUP", "command": "TEST_CMD"})
    event_id = post_res.json()["event_id"]

    # Valid ID lookup
    res = api_client.get(f"/api/v1/events/history/{event_id}")
    assert res.status_code == 200
    assert res.json()["event"]["event_id"] == event_id

    # Alias route GET /api/v1/events/{event_id}
    res_alias = api_client.get(f"/api/v1/events/{event_id}")
    assert res_alias.status_code == 200
    assert res_alias.json()["event"]["event_id"] == event_id

    # Non-existent ID lookup -> 404
    bad_res = api_client.get("/api/v1/events/history/EVT-NONEXISTENT")
    assert bad_res.status_code == 404


def test_api_get_summary(api_client):
    """GET /api/v1/events/summary endpoint."""
    api_client.post("/api/v1/events", json={"event_type": "START", "domain": "AIML"})
    api_client.post("/api/v1/events", json={"event_type": "STOP", "domain": "AIML"})

    res = api_client.get("/api/v1/events/summary")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["summary"]["total_events"] == 2
    assert data["summary"]["events_by_domain"]["AIML"] == 2


def test_api_clear_history(api_client):
    """DELETE /api/v1/events/history and POST /api/v1/events/clear endpoints."""
    api_client.post("/api/v1/events", json={"event_type": "E1"})
    api_client.post("/api/v1/events", json={"event_type": "E2"})

    # Check populated
    check1 = api_client.get("/api/v1/events/history")
    assert check1.json()["count"] == 2

    # Clear via DELETE
    del_res = api_client.delete("/api/v1/events/history")
    assert del_res.status_code == 200
    assert del_res.json()["cleared_count"] == 2

    # Check empty
    check2 = api_client.get("/api/v1/events/history")
    assert check2.json()["count"] == 0


def test_api_get_analytics(api_client):
    """GET /api/v1/events/analytics endpoint with P50/P90/P99 latency & reliability metrics."""
    # Seed events with duration and status
    durations = [10.0, 20.0, 30.0, 40.0, 50.0, 100.0]
    for d in durations:
        api_client.post("/api/v1/events", json={
            "event_type": "CMD_EXEC",
            "command": "FORWARD",
            "domain": "EMBEDDED",
            "status": "SUCCESS",
            "execution_duration": d,
        })
    # Add a failure event
    api_client.post("/api/v1/events", json={
        "event_type": "CMD_EXEC",
        "command": "CONNECT_MQTT",
        "domain": "IOT",
        "status": "FAILED",
        "error": "Connection timed out",
    })

    res = api_client.get("/api/v1/events/analytics")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    a = data["analytics"]
    assert a["total_events"] == 7
    assert a["latency_metrics"]["count"] == 6
    assert a["latency_metrics"]["p50_ms"] >= 20.0
    assert a["latency_metrics"]["p90_ms"] >= 50.0
    assert a["reliability_metrics"]["total_failures"] == 1
    assert "EMBEDDED" in a["domain_analytics"]
    assert "IOT" in a["domain_analytics"]
    assert a["domain_analytics"]["IOT"]["failed_count"] == 1


def test_time_window_since_filters(manager):
    """Verify relative time window filters (since_seconds and since_minutes)."""
    now = time.time()
    manager.store_event(event_type="OLD", timestamp=now - 500)
    manager.store_event(event_type="RECENT_1", timestamp=now - 20)
    manager.store_event(event_type="RECENT_2", timestamp=now - 5)

    recent_events = manager.get_event_history(since_seconds=30)
    assert len(recent_events) == 2
    assert [e["event_type"] for e in recent_events] == ["RECENT_1", "RECENT_2"]

    all_window = manager.get_event_history(since_minutes=10)
    assert len(all_window) == 3


def test_event_bus_auto_mirroring():
    """Verify EventBus publishes automatically mirror into EventHistoryManager."""
    import asyncio
    from core.events.event_bus import EventBus
    from core.managers.event_history import EventHistoryManager

    eb = EventBus()
    # Publish an event through the EventBus
    asyncio.run(eb.publish("TELEMETRY_PULSE", {
        "command": "BATTERY_LEVEL",
        "domain": "IOT",
        "status": "SUCCESS",
        "request_id": "REQ-BUS-99",
        "execution_duration": 4.2
    }))

    # Verify event landed in global event_history_manager
    events = event_history_manager.get_events_by_request_id("REQ-BUS-99")
    assert len(events) >= 1
    assert events[0]["command"] == "BATTERY_LEVEL"
    assert events[0]["domain"] == "IOT"


def test_real_time_streaming_listeners(manager):
    """Verify sync and async listener queues receive dispatched events."""
    import asyncio

    received_sync = []
    def sync_listener(ev):
        received_sync.append(ev.event_id)

    manager.add_sync_listener(sync_listener)

    async_q = asyncio.Queue()
    manager.add_async_listener(async_q)

    ev = manager.store_event(event_type="STREAM_TEST", command="PING")

    assert ev.event_id in received_sync
    assert async_q.qsize() == 1
    streamed_ev = async_q.get_nowait()
    assert streamed_ev.event_id == ev.event_id

    # Clean up
    manager.remove_sync_listener(sync_listener)
    manager.remove_async_listener(async_q)


def test_events_dashboard_ui_endpoint(api_client):
    """GET /events returns interactive HTML dashboard UI."""
    res = api_client.get("/events")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "SynaptiMesh Event History" in res.text
    assert "SSE LIVE CONNECTED" in res.text

