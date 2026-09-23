"""
websocket_server.py
===================
SynaptiMesh Core WebSocket Server Architecture & Message Flow Engine.
Sprint 11 — Day 2 Member 1 Implementation.

Provides:
- Thread-safe, non-blocking WebSocket connection manager and client registry.
- Standardized message envelope serialization compatible with Day 1 schemas.
- Low-latency multi-client state and telemetry broadcasting layer.
- Comprehensive connection lifecycle management (CONNECT -> ACCEPT -> REGISTER -> ACTIVE -> RECEIVE/SEND -> DISCONNECT -> UNREGISTER).
- Error isolation and stale connection garbage collection.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set
import uuid

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from core.config.dashboard_config import get_dashboard_config, dashboard_config_manager

logger = logging.getLogger("core.websocket_server")


class WebSocketEnvelope(BaseModel):
    """Standardized WebSocket Message Envelope for SynaptiMesh real-time pipeline."""
    type: str = Field(..., description="Message/event type identifier")
    version: str = Field("2.0.0", description="Message schema protocol version")
    source_domain: str = Field("CORE", description="Origin domain (BCI, AI_ML, IOT, EMBEDDED, CORE)")
    source_id: str = Field("master_hub", description="Origin source identifier")
    session_id: Optional[str] = Field("default", description="Active session identifier")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        description="ISO-8601 UTC timestamp"
    )
    timestamp_unix_ms: int = Field(
        default_factory=lambda: int(time.time() * 1000),
        description="Unix epoch timestamp in milliseconds"
    )
    telemetry_id: Optional[str] = Field(None, description="Unique telemetry identifier")
    trace_id: Optional[str] = Field(None, description="Distributed trace identifier")
    sequence_number: int = Field(0, ge=0, description="Monotonically increasing sequence number")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Structured message payload")

    def to_json(self) -> str:
        return json.dumps(self.model_dump(exclude_none=True), default=str)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True)


class WebSocketClientSession:
    """Represents a connected WebSocket client session with metadata and state."""

    def __init__(self, websocket: WebSocket, client_id: Optional[str] = None):
        self.websocket = websocket
        self.client_id = client_id or f"ws_client_{uuid.uuid4().hex[:8]}"
        self.connected_at = time.time()
        self.last_heartbeat = time.time()
        self.subscriptions: Set[str] = {"*"}  # Default to all domains
        self.is_active = True
        self.client_ip = getattr(getattr(websocket, "client", None), "host", "unknown")

    def to_summary(self) -> Dict[str, Any]:
        return {
            "client_id": self.client_id,
            "connected_at": self.connected_at,
            "uptime_seconds": round(time.time() - self.connected_at, 1),
            "client_ip": self.client_ip,
            "subscriptions": list(self.subscriptions),
            "is_active": self.is_active,
        }


class WebSocketServer:
    """
    Centralized, thread-safe WebSocket Server and Broadcast Coordinator.
    Manages active client lifecycles, structured serialization, and async distribution.
    """

    _instance: Optional[WebSocketServer] = None
    _lock = threading.RLock()

    def __new__(cls) -> WebSocketServer:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(WebSocketServer, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return

        self._clients: Dict[WebSocket, WebSocketClientSession] = {}
        self._clients_lock = threading.RLock()
        self._sequence_counter = 0
        self._counter_lock = threading.Lock()
        self._event_handlers: Dict[str, List[Callable]] = {}
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._initialized = True
        logger.info("[WS SERVER] Centralized WebSocket Server architecture initialized")

    def _next_sequence(self) -> int:
        with self._counter_lock:
            self._sequence_counter += 1
            return self._sequence_counter

    # ---------------------------------------------------------------------------
    # Client Connection Lifecycle
    # ---------------------------------------------------------------------------

    def _start_heartbeat_monitor(self):
        """Lazily start the background heartbeat monitor task if not already running."""
        try:
            loop = asyncio.get_running_loop()
            if self._heartbeat_task is None or self._heartbeat_task.done():
                self._heartbeat_task = loop.create_task(self._heartbeat_monitor_loop())
                logger.info("[WS SERVER] Heartbeat monitor task started")
        except RuntimeError:
            pass

    async def _heartbeat_monitor_loop(self):
        """Periodically scans for and disconnects stale WebSocket clients."""
        logger.info("[WS SERVER] Heartbeat monitor loop running...")
        try:
            while True:
                cfg = dashboard_config_manager.get_config()
                interval = cfg.ws_heartbeat_interval_sec or 15.0
                timeout = cfg.ws_client_timeout_sec or 30.0
                await asyncio.sleep(interval)
                
                now = time.time()
                stale_clients = []
                with self._clients_lock:
                    for ws, session in list(self._clients.items()):
                        if not session.is_active:
                            continue
                        if now - session.last_heartbeat > timeout:
                            stale_clients.append((ws, session))

                for ws, session in stale_clients:
                    logger.warning(f"[WS SERVER] Client {session.client_id} is stale (timeout > {timeout}s). Cleaning up.")
                    self.unregister_client(ws)
                    try:
                        await ws.close()
                    except Exception:
                        pass
        except asyncio.CancelledError:
            logger.info("[WS SERVER] Heartbeat monitor task cancelled")
        except Exception as e:
            logger.error(f"[WS SERVER] Heartbeat monitor error: {e}")

    async def handle_connection(
        self,
        websocket: WebSocket,
        channel: str = "default",
        initial_snapshot_provider: Optional[Callable[[], Dict[str, Any]]] = None,
        custom_message_handler: Optional[Callable[[WebSocketClientSession, Dict[str, Any]], Any]] = None
    ):
        """
        Complete connection lifecycle loop for an incoming WebSocket connection:
        CONNECT -> ACCEPT -> REGISTER -> ACTIVE -> RECEIVE/SEND -> DISCONNECT -> UNREGISTER
        """
        await websocket.accept()
        session = self.register_client(websocket)
        logger.info(f"[WS SERVER] Client connected on channel '{channel}' [id={session.client_id}, total={self.client_count()}]")

        try:
            # Send standard connection confirmation
            welcome_envelope = self.create_envelope(
                msg_type="CONNECTED",
                source_domain="CORE",
                source_id="master_hub",
                payload={
                    "client_id": session.client_id,
                    "channel": channel,
                    "status": "ACTIVE",
                    "server_time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "config": dashboard_config_manager.to_websocket_config()
                }
            )
            await websocket.send_text(welcome_envelope.to_json())

            # Send initial snapshot if provider supplied
            if initial_snapshot_provider:
                try:
                    snapshot_data = initial_snapshot_provider()
                    if asyncio.iscoroutine(snapshot_data):
                        snapshot_data = await snapshot_data
                    snapshot_envelope = self.create_envelope(
                        msg_type="SNAPSHOT",
                        source_domain="CORE",
                        payload=snapshot_data
                    )
                    await websocket.send_text(snapshot_envelope.to_json())
                except Exception as snap_err:
                    logger.warning(f"[WS SERVER] Initial snapshot generation error: {snap_err}")

            # Message receive loop
            while True:
                raw_text = await websocket.receive_text()
                session.last_heartbeat = time.time()
                try:
                    data = json.loads(raw_text)
                    if isinstance(data, dict):
                        await self._process_incoming_message(session, data, custom_message_handler)
                except json.JSONDecodeError:
                    logger.debug(f"[WS SERVER] Received malformed JSON from client {session.client_id}")
                    err_env = self.create_envelope(
                        msg_type="ERROR",
                        source_domain="CORE",
                        payload={"message": "Malformed JSON payload"}
                    )
                    await websocket.send_text(err_env.to_json())

        except WebSocketDisconnect:
            logger.info(f"[WS SERVER] Client {session.client_id} disconnected normally.")
        except Exception as exc:
            logger.warning(f"[WS SERVER] Connection exception on client {session.client_id}: {exc}")
        finally:
            self.unregister_client(websocket)
            logger.info(f"[WS SERVER] Client unregistered. Total active: {self.client_count()}")

    def register_client(self, websocket: WebSocket) -> WebSocketClientSession:
        """Register a new active WebSocket client session."""
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
        with self._clients_lock:
            session = WebSocketClientSession(websocket)
            self._clients[websocket] = session
            self._start_heartbeat_monitor()
            return session

    def unregister_client(self, websocket: WebSocket):
        """Cleanly unregister and drop a disconnected WebSocket client session."""
        with self._clients_lock:
            session = self._clients.pop(websocket, None)
            if session:
                session.is_active = False

    def client_count(self) -> int:
        """Return count of active WebSocket client connections."""
        with self._clients_lock:
            return len(self._clients)

    def get_active_sessions(self) -> List[WebSocketClientSession]:
        """Return list of active client sessions."""
        with self._clients_lock:
            return list(self._clients.values())

    # ---------------------------------------------------------------------------
    # Message Envelope Creation & Normalization
    # ---------------------------------------------------------------------------

    def create_envelope(
        self,
        msg_type: str,
        source_domain: str = "CORE",
        source_id: str = "master_hub",
        session_id: str = "default",
        payload: Optional[Dict[str, Any]] = None,
        telemetry_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> WebSocketEnvelope:
        """Construct a standardized, schema-compliant WebSocket message envelope."""
        return WebSocketEnvelope(
            type=msg_type.upper(),
            version="2.0.0",
            source_domain=source_domain.upper(),
            source_id=str(source_id),
            session_id=session_id,
            telemetry_id=telemetry_id or f"TEL-{uuid.uuid4().hex[:12]}",
            trace_id=trace_id,
            sequence_number=self._next_sequence(),
            payload=payload or {}
        )

    # ---------------------------------------------------------------------------
    # Broadcasting & Distribution Layer
    # ---------------------------------------------------------------------------

    async def broadcast_envelope(self, envelope: WebSocketEnvelope):
        """
        Asynchronously broadcast a standardized envelope to all connected clients.
        Drops failed/disconnected clients gracefully without blocking or raising.
        """
        with self._clients_lock:
            clients = list(self._clients.items())

        if not clients:
            return

        json_str = envelope.to_json()
        dead_sockets: List[WebSocket] = []

        # Broadcast concurrently
        tasks = []
        sockets = []
        for ws, session in clients:
            if not session.is_active:
                dead_sockets.append(ws)
                continue
            sockets.append(ws)
            tasks.append(ws.send_text(json_str))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for ws, res in zip(sockets, results):
                if isinstance(res, Exception):
                    logger.debug(f"[WS SERVER] Send failed for client: {res}")
                    dead_sockets.append(ws)

        if dead_sockets:
            for dead_ws in dead_sockets:
                self.unregister_client(dead_ws)

    def broadcast_envelope_sync(self, envelope: WebSocketEnvelope):
        """Thread-safe synchronous helper to schedule envelope broadcast on active event loop."""
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                self._loop = loop
                loop.create_task(self.broadcast_envelope(envelope))
                return
        except RuntimeError:
            pass

        loop = getattr(self, "_loop", None)
        if loop and loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(self.broadcast_envelope(envelope), loop)
            except Exception:
                pass

    async def broadcast_telemetry(
        self,
        domain: str,
        source_id: str,
        payload: Dict[str, Any],
        telemetry_id: Optional[str] = None,
        session_id: str = "default",
        trace_id: Optional[str] = None
    ):
        """Publish a live domain telemetry frame across all WebSocket subscribers with schema validation."""
        clean_payload = payload
        try:
            from models.telemetry_models import UnifiedTelemetryPacket
            if isinstance(payload, UnifiedTelemetryPacket):
                clean_payload = payload.payload if isinstance(payload.payload, dict) else (
                    payload.payload.model_dump(exclude_none=True) if hasattr(payload.payload, "model_dump") else payload.payload
                )
                domain = payload.source_domain.value if hasattr(payload.source_domain, "value") else str(payload.source_domain)
                source_id = payload.source_id or source_id
                telemetry_id = telemetry_id or payload.telemetry_id
                trace_id = trace_id or payload.trace_id
                session_id = payload.session_id or session_id
            elif hasattr(payload, "model_dump"):
                clean_payload = payload.model_dump(exclude_none=True)
            elif not isinstance(payload, dict):
                clean_payload = {"raw_value": str(payload)}
        except Exception as norm_err:
            logger.debug(f"[WS SERVER] Telemetry normalization fallback: {norm_err}")
            clean_payload = {"raw": str(payload)}

        envelope = self.create_envelope(
            msg_type="TELEMETRY_FRAME",
            source_domain=str(domain).upper(),
            source_id=str(source_id),
            session_id=session_id,
            payload=clean_payload,
            telemetry_id=telemetry_id,
            trace_id=trace_id
        )
        await self.broadcast_envelope(envelope)

    async def broadcast_state_update(
        self,
        state_payload: Dict[str, Any],
        session_id: str = "default",
        domain: str = "CORE"
    ):
        """Publish a centralized system state or session state mutation."""
        envelope = self.create_envelope(
            msg_type="STATE_UPDATE",
            source_domain=domain,
            session_id=session_id,
            payload=state_payload
        )
        await self.broadcast_envelope(envelope)

    async def broadcast_event(
        self,
        event_type: str,
        payload: Dict[str, Any],
        domain: str = "CORE",
        source_id: str = "master_hub"
    ):
        """Publish a generic system/BCI/robotics event to all connected dashboards."""
        envelope = self.create_envelope(
            msg_type=event_type,
            source_domain=domain,
            source_id=source_id,
            payload=payload
        )
        await self.broadcast_envelope(envelope)

    # ---------------------------------------------------------------------------
    # Client Inbound Message Handling
    # ---------------------------------------------------------------------------

    async def _process_incoming_message(
        self,
        session: WebSocketClientSession,
        data: Dict[str, Any],
        custom_handler: Optional[Callable[[WebSocketClientSession, Dict[str, Any]], Any]] = None
    ):
        """Process messages received from frontend clients."""
        msg_type = str(data.get("type", "")).upper()

        if msg_type == "PING":
            pong_env = self.create_envelope(
                msg_type="PONG",
                source_domain="CORE",
                payload={"client_time": data.get("time"), "server_time": time.time()}
            )
            await session.websocket.send_text(pong_env.to_json())
            return

        if msg_type == "SUBSCRIBE":
            domains = data.get("domains") or data.get("payload", {}).get("domains")
            if isinstance(domains, list):
                session.subscriptions = set(d.upper() for d in domains)
                ack_env = self.create_envelope(
                    msg_type="SUBSCRIBE_ACK",
                    source_domain="CORE",
                    payload={"subscriptions": list(session.subscriptions)}
                )
                await session.websocket.send_text(ack_env.to_json())
            return

        if custom_handler:
            try:
                res = custom_handler(session, data)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as h_err:
                logger.warning(f"[WS SERVER] Custom handler error: {h_err}")

    # ---------------------------------------------------------------------------
    # Diagnostics & Lifecycle Hooks
    # ---------------------------------------------------------------------------

    def get_diagnostics(self) -> Dict[str, Any]:
        """Return runtime health and connection metrics."""
        with self._clients_lock:
            clients_summary = [s.to_summary() for s in self._clients.values()]
        return {
            "status": "ONLINE",
            "active_clients_count": len(clients_summary),
            "total_messages_sequenced": self._sequence_counter,
            "clients": clients_summary,
            "config": dashboard_config_manager.to_websocket_config(),
        }

    def close_all(self):
        """Gracefully disconnect all clients on server shutdown."""
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()

        with self._clients_lock:
            for ws, session in list(self._clients.items()):
                session.is_active = False
            self._clients.clear()
        logger.info("[WS SERVER] All active WebSocket connections closed cleanly.")


# Global Singleton Instance
websocket_server = WebSocketServer()


def get_websocket_server() -> WebSocketServer:
    """Helper to access global WebSocket Server instance."""
    return websocket_server
