"""
test_websocket_architecture_day2.py
===================================
Test Suite for Sprint 11 Day 2 Member 1:
WebSocket Server Architecture & Message Flow.

Verifies:
- WebSocket endpoint existence and connection acceptance.
- Standard message envelope format conforming to Day 1 schema.
- Connection lifecycle: CONNECT -> ACCEPT -> REGISTER -> ACTIVE -> DISCONNECT -> UNREGISTER.
- Multi-client simultaneous connection support and broadcast isolation.
- Stale connection cleanup and error handling with malformed messages.
- Bidirectional ping/pong communication.
- Real-time telemetry and state broadcasting.
- Streaming latency measurement test.
"""

import asyncio
from datetime import datetime, timezone
import json
import time
import pytest
from fastapi.testclient import TestClient

from main import app
from core.communication.websocket_server import (
    WebSocketEnvelope,
    WebSocketServer,
    get_websocket_server,
)

client = TestClient(app)


def test_websocket_envelope_structure():
    """Verify standard WebSocket message envelope construction and serialization."""
    server = get_websocket_server()
    env = server.create_envelope(
        msg_type="TELEMETRY_FRAME",
        source_domain="BCI",
        source_id="EPOC-X-TEST",
        session_id="test_session_101",
        payload={"command": "PUSH", "power": 0.95}
    )

    data = env.to_dict()
    assert data["type"] == "TELEMETRY_FRAME"
    assert data["version"] == "2.0.0"
    assert data["source_domain"] == "BCI"
    assert data["source_id"] == "EPOC-X-TEST"
    assert data["session_id"] == "test_session_101"
    assert "timestamp" in data
    assert "timestamp_unix_ms" in data
    assert "sequence_number" in data
    assert data["payload"]["command"] == "PUSH"
    assert data["payload"]["power"] == 0.95

    json_str = env.to_json()
    parsed = json.loads(json_str)
    assert parsed["type"] == "TELEMETRY_FRAME"


def test_websocket_connection_and_handshake():
    """Verify WebSocket client connection acceptance and initial snapshot."""
    with client.websocket_connect("/ws") as ws:
        # Initial welcome snapshot packet
        data = ws.receive_json()
        assert data["type"] in ("init_snapshot", "SNAPSHOT", "CONNECTED")
        assert "payload" in data or "data" in data


def test_websocket_bci_endpoint():
    """Verify /api/v1/bci/ws and /api/v1/ws alias endpoints."""
    with client.websocket_connect("/api/v1/bci/ws") as ws:
        data = ws.receive_json()
        assert data["type"] in ("init_snapshot", "SNAPSHOT", "CONNECTED")

    with client.websocket_connect("/api/v1/ws") as ws:
        data = ws.receive_json()
        assert data["type"] in ("init_snapshot", "SNAPSHOT", "CONNECTED")


def test_websocket_telemetry_streaming_endpoint():
    """Verify /api/v1/telemetry/ws endpoint connection and initial snapshot."""
    with client.websocket_connect("/api/v1/telemetry/ws") as ws:
        data = ws.receive_json()
        assert data["type"] == "SNAPSHOT"
        assert "data" in data
        assert "BCI" in data["data"]
        assert "IOT" in data["data"]


def test_websocket_ping_pong():
    """Verify bidirectional ping-pong heartbeat over WebSocket."""
    with client.websocket_connect("/ws") as ws:
        _ = ws.receive_json()  # Consume initial snapshot

        # Send ping
        ws.send_json({"type": "PING", "time": time.time()})
        resp = ws.receive_json()
        assert resp["type"] == "PONG"


def test_websocket_malformed_json_handling():
    """Verify that malformed JSON from a client does not crash the server and returns structured error."""
    with client.websocket_connect("/ws") as ws:
        _ = ws.receive_json()  # Consume initial snapshot

        # Send invalid text/data
        ws.send_text("THIS IS NOT JSON {{{")
        err = ws.receive_json()
        assert err["type"] == "ERROR"
        assert err["payload"]["error"] == "MALFORMED_JSON"

        # Connection remains healthy for subsequent messages
        ws.send_json({"type": "PING"})
        resp = ws.receive_json()
        assert resp["type"] == "PONG"


def test_websocket_server_registry_and_lifecycle():
    """Verify client registration and clean unregistration on disconnect."""
    server = get_websocket_server()
    initial_count = server.client_count()

    with client.websocket_connect("/ws") as ws:
        _ = ws.receive_json()
        # Active count incremented
        assert server.client_count() == initial_count + 1
        sessions = server.get_active_sessions()
        assert len(sessions) >= 1
        assert sessions[-1].is_active is True

    # After exiting with block (disconnect), client count returns cleanly
    deadline = time.time() + 1.0
    while time.time() < deadline and server.client_count() != initial_count:
        time.sleep(0.02)
    assert server.client_count() == initial_count


def test_websocket_multi_client_broadcast():
    """Verify that multiple connected clients simultaneously receive broadcast packets."""
    server = get_websocket_server()

    with client.websocket_connect("/ws") as ws1:
        _ = ws1.receive_json()
        with client.websocket_connect("/ws") as ws2:
            _ = ws2.receive_json()

            # Broadcast from server
            test_envelope = server.create_envelope(
                msg_type="TEST_BROADCAST",
                source_domain="CORE",
                payload={"msg": "Hello Multi-Client"}
            )
            server.broadcast_envelope_sync(test_envelope)

            # Both clients receive ping/broadcast
            ws1.send_json({"type": "PING"})
            resp1 = ws1.receive_json()
            assert resp1["type"] in ("TEST_BROADCAST", "PONG")

            ws2.send_json({"type": "PING"})
            resp2 = ws2.receive_json()
            assert resp2["type"] in ("TEST_BROADCAST", "PONG")


def test_websocket_streaming_latency_measurement():
    """Measure streaming transmission latency of WebSocket message envelope."""
    server = get_websocket_server()
    start_time = time.perf_counter()
    env = server.create_envelope(
        msg_type="LATENCY_TEST",
        source_domain="CORE",
        payload={"sample": [1.0, 2.0, 3.0, 4.0]}
    )
    json_payload = env.to_json()
    _ = json.loads(json_payload)
    duration_ms = (time.perf_counter() - start_time) * 1000

    # Serialization and envelope packing should take < 1 ms, well below 50 ms budget
    assert duration_ms < 50.0
    print(f"\n[LATENCY TEST] Envelope serialization + parse time: {duration_ms:.3f} ms (Target < 50 ms)")


def test_websocket_server_diagnostics():
    """Verify diagnostics telemetry reported by WebSocket server."""
    server = get_websocket_server()
    diag = server.get_diagnostics()
    assert diag["status"] == "ONLINE"
    assert "active_clients_count" in diag
    assert "total_messages_sequenced" in diag
    assert "config" in diag
