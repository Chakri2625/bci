import asyncio
import json
import time
import pytest
from fastapi.testclient import TestClient

from main import app
from core.communication.websocket_server import get_websocket_server
from services.cortex_service import CortexService
from plugins.embedded.fastapi_routes import _ws_clients as embedded_ws_clients
from api.telemetry_routes import _CONNECTED_WS_CLIENTS as telemetry_ws_clients

client = TestClient(app)

def test_single_client_connection_and_registration():
    server = get_websocket_server()
    cortex = CortexService.get_instance()
    initial_server_count = server.client_count()
    initial_cortex_count = len(cortex._ws_clients)

    with client.websocket_connect("/ws") as ws:
        # Handshake / Initial snapshot
        data = ws.receive_json()
        assert data["type"] in ("init_snapshot", "SNAPSHOT", "CONNECTED")

        # Verify Registration
        assert server.client_count() == initial_server_count + 1
        assert len(cortex._ws_clients) == initial_cortex_count + 1

    # Verify Disconnect Cleanup
    time.sleep(0.1) # allow cleanup to run
    assert server.client_count() == initial_server_count
    assert len(cortex._ws_clients) == initial_cortex_count

def test_client_message():
    with client.websocket_connect("/ws") as ws:
        ws.receive_json() # Consume snapshot
        ws.send_json({"type": "PING", "time": time.time()})
        resp = ws.receive_json()
        assert resp["type"] == "PONG"

def test_guaranteed_cleanup():
    server = get_websocket_server()
    initial_server_count = server.client_count()

    # We force a disconnect and verify cleanup runs
    try:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
            assert server.client_count() == initial_server_count + 1
            raise RuntimeError("Unexpected exception simulating client crash")
    except RuntimeError:
        pass

    time.sleep(0.1)
    assert server.client_count() == initial_server_count

def test_multiple_clients_and_isolation():
    server = get_websocket_server()
    initial_server_count = server.client_count()

    with client.websocket_connect("/ws") as ws1:
        ws1.receive_json()
        with client.websocket_connect("/ws") as ws2:
            ws2.receive_json()
            assert server.client_count() == initial_server_count + 2

        # ws2 disconnected, ws1 should remain active
        time.sleep(0.1)
        assert server.client_count() == initial_server_count + 1
        
        # Test ws1 is still alive
        ws1.send_json({"type": "PING", "time": time.time()})
        resp = ws1.receive_json()
        assert resp["type"] == "PONG"

    time.sleep(0.1)
    assert server.client_count() == initial_server_count

def test_reconnection():
    server = get_websocket_server()
    initial_server_count = server.client_count()

    # Connect, Disconnect
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        assert server.client_count() == initial_server_count + 1

    time.sleep(0.1)
    assert server.client_count() == initial_server_count

    # Reconnect
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        assert server.client_count() == initial_server_count + 1
        
        ws.send_json({"type": "PING", "time": time.time()})
        resp = ws.receive_json()
        assert resp["type"] == "PONG"

    time.sleep(0.1)
    assert server.client_count() == initial_server_count

def test_event_history_disconnect_detection():
    # Verify that event history doesn't block and properly handles ping
    with client.websocket_connect("/api/v1/events/ws") as ws:
        data = ws.receive_json()
        assert data["type"] == "WS_CONNECTED"

        ws.send_json({"type": "PING", "time": time.time()})
        resp = ws.receive_json()
        assert resp["type"] == "PONG"

def test_telemetry_client_cleanup():
    initial_count = len(telemetry_ws_clients)
    with client.websocket_connect("/api/v1/telemetry/ws") as ws:
        ws.receive_json()
        assert len(telemetry_ws_clients) == initial_count + 1

    time.sleep(0.1)
    assert len(telemetry_ws_clients) == initial_count

def test_embedded_client_cleanup():
    initial_count = len(embedded_ws_clients)
    with client.websocket_connect("/embedded/ws") as ws:
        # embedded endpoint sends 5 snapshots initially
        for _ in range(5):
            ws.receive_json()
        assert len(embedded_ws_clients) == initial_count + 1

    time.sleep(0.1)
    assert len(embedded_ws_clients) == initial_count

def test_stale_client_detection():
    server = get_websocket_server()
    # We will mock the last_heartbeat to simulate a stale client
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        
        # Manually set last_heartbeat to 1 hour ago
        for session in server._clients.values():
            session.last_heartbeat = time.time() - 3600
        
        # The monitor loop runs every 15s. We'll manually trigger the logic for testing
        now = time.time()
        timeout = 30.0
        stale_clients = []
        for s_ws, session in list(server._clients.items()):
            if now - session.last_heartbeat > timeout:
                stale_clients.append((s_ws, session))
                
        assert len(stale_clients) >= 1
        
        for s_ws, session in stale_clients:
            server.unregister_client(s_ws)

        assert server.client_count() == 0
