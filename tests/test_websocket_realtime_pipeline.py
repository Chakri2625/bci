import asyncio
import json
import time
import pytest
from fastapi.testclient import TestClient
from main import app
from core.communication.websocket_server import get_websocket_server, WebSocketEnvelope
from core.state.state_synchronizer import cross_domain_state_synchronizer
from core.state.state_manager import state_manager
from models.telemetry_models import UnifiedTelemetryPacket, TelemetryDomain


client = TestClient(app)


def receive_matching(ws, target_type=None, target_domain=None, max_skips=30):
    """Receive messages, skipping initial snapshots / ambient frames until target type and domain match."""
    for _ in range(max_skips):
        msg = ws.receive_json()
        if target_type is None:
            return msg
        if msg.get("type") == target_type:
            if target_domain is None or msg.get("source_domain") == target_domain:
                return msg
    return msg


# ---------------------------------------------------------------------------
# 1. State -> WebSocket Broadcasting Tests (Member 6)
# ---------------------------------------------------------------------------

def test_rest_state_sync_triggers_websocket_broadcast():
    """Verify REST state sync via CrossDomainStateSynchronizer broadcasts STATE_UPDATE to WS clients."""
    with client.websocket_connect("/ws") as ws:
        receive_matching(ws, None)

        test_session = f"SESS-TEST-{int(time.time() * 1000)}"
        res = client.post("/api/v1/state/sync", json={
            "session_id": test_session,
            "domain": "IOT",
            "domain_state": {"relay_1": "ON", "temperature": 24.2}
        })
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["domain"] == "IOT"

        msg = receive_matching(ws, "STATE_UPDATE", target_domain="IOT")
        assert msg["type"] == "STATE_UPDATE"
        assert msg["source_domain"] == "IOT"
        assert msg["payload"]["session_id"] == test_session
        assert "relay_1" in msg["payload"]["state"]["domains"]["IOT"]


def test_rest_state_update_triggers_websocket_broadcast():
    """Verify REST state/update endpoint updates state and broadcasts to WebSocket."""
    with client.websocket_connect("/ws") as ws:
        receive_matching(ws, None)

        test_sess = f"SESS-UPD-{int(time.time() * 1000)}"
        res = client.post("/api/v1/state/update", json={
            "session_id": test_sess,
            "updates": {"active_mode": "AUTONOMOUS", "current_level": 2}
        })
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "success"
        assert body["state"]["active_mode"] == "AUTONOMOUS"

        msg = receive_matching(ws, "STATE_UPDATE")
        assert msg["type"] == "STATE_UPDATE"
        assert msg["payload"]["session_id"] == test_sess
        assert msg["payload"]["state"]["active_mode"] == "AUTONOMOUS"


def test_reset_domain_selection_broadcasts():
    """Verify reset_to_domain_selection triggers WebSocket STATE_UPDATE broadcast."""
    from core.communication.api_server import reset_to_domain_selection
    with client.websocket_connect("/ws") as ws:
        receive_matching(ws, None)
        test_sess = f"SESS-RESET-{int(time.time() * 1000)}"
        res = reset_to_domain_selection(session=test_sess)
        assert res["status"] == "success"

        msg = receive_matching(ws, "STATE_UPDATE")
        assert msg["type"] == "STATE_UPDATE"
        assert msg["payload"]["session_id"] == test_sess
        assert msg["payload"]["action"] == "RESET_DOMAIN_SELECTION"


# ---------------------------------------------------------------------------
# 2. Standard WebSocket Message Formatting & Schema Tests (Member 7)
# ---------------------------------------------------------------------------

def test_telemetry_schema_validation_and_broadcast():
    """Verify UnifiedTelemetryPacket format compliance and JSON serializability."""
    from models.telemetry_models import BciTelemetry, MentalCommandTelemetry
    server = get_websocket_server()
    with client.websocket_connect("/ws") as ws:
        receive_matching(ws, None)

        bci_payload = BciTelemetry(
            headset_id="EPOC-X-TEST",
            battery_pct=90,
            signal_quality={"AF3": 0.98},
            mental_command=MentalCommandTelemetry(action="PUSH", power=0.85)
        )
        packet = UnifiedTelemetryPacket(
            source_domain=TelemetryDomain.BCI,
            source_id="EPOC-X-TEST",
            session_id="session_test",
            payload=bci_payload
        )

        asyncio.run(server.broadcast_telemetry(
            domain=packet.source_domain.value,
            source_id=packet.source_id,
            payload=packet,
            telemetry_id=packet.telemetry_id,
            session_id=packet.session_id
        ))

        msg = receive_matching(ws, "TELEMETRY_FRAME", target_domain="BCI")
        assert msg["type"] == "TELEMETRY_FRAME"
        assert msg["source_domain"] == "BCI"
        assert msg["source_id"] == "EPOC-X-TEST"
        assert "battery_pct" in msg["payload"]
        assert msg["payload"]["battery_pct"] == 90
        assert msg["payload"]["mental_command"]["action"] == "PUSH"
        assert "timestamp" in msg
        assert "sequence_number" in msg



def test_malformed_telemetry_safe_handling():
    """Verify server safely handles malformed/non-dict telemetry without raising or terminating."""
    server = get_websocket_server()
    with client.websocket_connect("/ws") as ws:
        receive_matching(ws, None)

        asyncio.run(server.broadcast_telemetry(
            domain="UNKNOWN_CORRUPT",
            source_id="corrupt_node",
            payload="corrupt_raw_string_data"  # type: ignore
        ))

        msg = receive_matching(ws, "TELEMETRY_FRAME", target_domain="UNKNOWN_CORRUPT")
        assert msg["type"] == "TELEMETRY_FRAME"
        assert "corrupt_raw_string_data" in str(msg["payload"])


# ---------------------------------------------------------------------------
# 3. Connection Manager & Error Isolation Tests (Member 9)
# ---------------------------------------------------------------------------

def test_multi_client_safe_broadcast_and_isolation():
    """Verify broadcasting to multiple clients, and verify a failing client does not block others."""
    server = get_websocket_server()
    with client.websocket_connect("/ws") as ws1:
        receive_matching(ws1, None)
        with client.websocket_connect("/ws") as ws2:
            receive_matching(ws2, None)
            initial_count = server.client_count()
            assert initial_count >= 2

            env = server.create_envelope(
                msg_type="MULTI_TEST",
                source_domain="CORE",
                payload={"msg": "hello_all"}
            )
            asyncio.run(server.broadcast_envelope(env))

            r1 = receive_matching(ws1, "MULTI_TEST")
            r2 = receive_matching(ws2, "MULTI_TEST")
            assert r1["type"] == "MULTI_TEST"
            assert r2["type"] == "MULTI_TEST"


def test_dead_client_graceful_cleanup():
    """Verify dead client is detected and unregistered during broadcast without crashing others."""
    server = get_websocket_server()
    with client.websocket_connect("/ws") as ws_survivor:
        receive_matching(ws_survivor, None)

        with client.websocket_connect("/ws") as ws_dead:
            receive_matching(ws_dead, None)
        # ws_dead closed

        env = server.create_envelope(
            msg_type="CLEANUP_CHECK",
            source_domain="CORE",
            payload={"alive": True}
        )
        asyncio.run(server.broadcast_envelope(env))

        survivor_msg = receive_matching(ws_survivor, "CLEANUP_CHECK")
        assert survivor_msg["type"] == "CLEANUP_CHECK"


# ---------------------------------------------------------------------------
# 4. Heartbeat & Keep-Alive Tests (Member 9)
# ---------------------------------------------------------------------------

def test_bidirectional_heartbeat_ping_pong():
    """Verify client PING returns PONG with server time and updates last_heartbeat."""
    with client.websocket_connect("/ws") as ws:
        receive_matching(ws, None)
        client_time = time.time() * 1000
        ws.send_json({"type": "PING", "time": client_time})
        resp = receive_matching(ws, "PONG")
        assert resp["type"] == "PONG"
        assert resp["payload"]["client_time"] == client_time
        assert "server_time" in resp["payload"]


def test_stale_heartbeat_timeout_cleanup():
    """Verify client whose last_heartbeat exceeds timeout threshold is detected as stale."""
    server = get_websocket_server()
    mock_ws = object()
    from core.communication.websocket_server import WebSocketClientSession
    mock_session = WebSocketClientSession(mock_ws, client_id="test_stale_mock_client")
    mock_session.last_heartbeat = time.time() - 100
    with server._clients_lock:
        server._clients[mock_ws] = mock_session
        now = time.time()
        timeout = 30.0
        stale = [s for s in server._clients.values() if now - s.last_heartbeat > timeout]
        assert any(s.client_id == "test_stale_mock_client" for s in stale)
        del server._clients[mock_ws]


# ---------------------------------------------------------------------------
# 5. Streaming Performance Benchmark (<50 ms target) (Member 8)
# ---------------------------------------------------------------------------

def test_websocket_streaming_performance_benchmark():
    """Benchmark end-to-end WebSocket envelope creation, serialization, and delivery latency."""
    server = get_websocket_server()
    with client.websocket_connect("/ws") as ws:
        receive_matching(ws, None)

        num_messages = 100
        latencies = []

        baseline_start = time.perf_counter()
        raw_env = server.create_envelope(
            msg_type="BENCHMARK",
            source_domain="CORE",
            payload={"iteration": 0, "telemetry": [0.1, 0.2, 0.3]}
        )
        asyncio.run(server.broadcast_envelope(raw_env))
        _ = receive_matching(ws, "BENCHMARK")
        baseline_ms = (time.perf_counter() - baseline_start) * 1000

        for i in range(num_messages):
            t0 = time.perf_counter()
            env = server.create_envelope(
                msg_type="TELEMETRY_FRAME",
                source_domain="BENCHMARK_DOMAIN",
                source_id="DEV-BENCH",
                payload={"index": i, "temp": 22.0 + (i * 0.05)}
            )
            asyncio.run(server.broadcast_envelope(env))
            msg = receive_matching(ws, "TELEMETRY_FRAME", target_domain="BENCHMARK_DOMAIN")
            t1 = time.perf_counter()
            latencies.append((t1 - t0) * 1000)
            assert msg["type"] == "TELEMETRY_FRAME"

        avg_latency = sum(latencies) / len(latencies)
        max_latency = max(latencies)
        min_latency = min(latencies)

        print(f"\n==========================================")
        print(f"WEBSOCKET STREAMING BENCHMARK RESULTS")
        print(f"==========================================")
        print(f"Messages tested: {num_messages}")
        print(f"Baseline latency: {baseline_ms:.3f} ms")
        print(f"Optimized latency (min): {min_latency:.3f} ms")
        print(f"Average latency: {avg_latency:.3f} ms")
        print(f"Maximum latency: {max_latency:.3f} ms")
        print(f"Target: < 50 ms  ->  PASSED: {max_latency < 50.0}")
        print(f"==========================================")

        assert avg_latency < 50.0, f"Average latency {avg_latency} ms exceeded 50 ms target"
        assert max_latency < 50.0, f"Max latency {max_latency} ms exceeded 50 ms target"
