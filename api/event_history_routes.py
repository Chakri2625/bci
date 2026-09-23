"""
Event History REST API & Real-Time Streaming Endpoints (Sprint 10 Day 8 - Member 7: Mubeena)
=============================================================================================
Exposes endpoints for querying, filtering, streaming, analyzing, and visualizing
the backend event history.

Endpoints:
- GET       /api/v1/events/history       : Retrieve event history with filtering, pagination, and sorting
- GET       /api/v1/events/history/{id}  : Retrieve a specific event by ID
- GET       /api/v1/events/summary       : Get statistical breakdown of stored events
- GET       /api/v1/events/analytics     : Deep latency percentiles (P50/P90/P99), domain failure rates, top commands
- GET       /api/v1/events/stream        : Server-Sent Events (SSE) live real-time event streaming
- WebSocket /api/v1/events/ws            : WebSocket live bidirectional event streaming
- POST      /api/v1/events               : Store/ingest a new event
- DELETE    /api/v1/events/history       : Clear all events from history
- POST      /api/v1/events/clear         : Alternative POST endpoint to clear history
- GET       /events                      : Visual Event History & Telemetry Dashboard (HTML UI)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Union
from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from core.managers.event_history import (
    Event,
    EventType,
    EventStatus,
    event_history_manager,
)
from models.device_models import DeviceState
from models.telemetry_models import (
    AiMlTelemetry,
    BciTelemetry,
    EmbeddedTelemetry,
    IotTelemetry,
    UnifiedTelemetryPacket,
)

logger = logging.getLogger("event_history_api")

router = APIRouter(tags=["Event History"])


class EventCreateRequest(BaseModel):
    """Schema for creating/storing a new event via API."""
    event_type: str = Field(..., description="Event type identifier (e.g. COMMAND_RECEIVED, EXECUTION_COMPLETED)")
    command: Optional[Union[str, Dict[str, Any], List[Any]]] = Field(None, description="Command string or payload")
    domain: Optional[str] = Field(None, description="Domain identifier (e.g. PYTHON, DESKTOP, EMBEDDED, IOT, AIML)")
    status: Optional[str] = Field("SUCCESS", description="Event status outcome")
    request_id: Optional[str] = Field(None, description="Correlating request or command ID")
    command_id: Optional[str] = Field(None, description="Alias for request_id")
    event_id: Optional[str] = Field(None, description="Custom event ID if predefined")
    timestamp: Optional[float] = Field(None, description="Unix timestamp (defaults to current time)")
    execution_duration: Optional[float] = Field(None, description="Execution duration (ms or seconds)")
    error: Optional[Union[str, Dict[str, Any]]] = Field(None, description="Error details if status is FAILED/ERROR")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Arbitrary extra metadata")
    telemetry: Optional[Union[UnifiedTelemetryPacket, BciTelemetry, AiMlTelemetry, IotTelemetry, EmbeddedTelemetry, Dict[str, Any]]] = Field(None, description="Structured telemetry payload (Member 3)")
    device_state: Optional[Union[DeviceState, Dict[str, Any]]] = Field(None, description="Structured device-state snapshot (Member 4)")



@router.get("/api/v1/events/history", summary="Get stored event history with optional filters")
def get_event_history(
    request_id: Optional[str] = Query(None, description="Filter by Request ID / Command ID"),
    command_id: Optional[str] = Query(None, description="Alias for request_id"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    command: Optional[str] = Query(None, description="Filter by command substring/name"),
    domain: Optional[str] = Query(None, description="Filter by domain"),
    status: Optional[str] = Query(None, description="Filter by event status"),
    start_time: Optional[Union[float, str]] = Query(None, description="Filter events on or after timestamp / ISO string"),
    end_time: Optional[Union[float, str]] = Query(None, description="Filter events on or before timestamp / ISO string"),
    since_seconds: Optional[float] = Query(None, description="Filter events within last N seconds"),
    since_minutes: Optional[float] = Query(None, description="Filter events within last N minutes"),
    limit: Optional[int] = Query(None, ge=1, le=5000, description="Max events to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    order: str = Query("asc", description="Sort order: 'asc' (chronological) or 'desc' (reverse chronological)"),
):
    """
    Retrieve stored backend events in JSON format with rich filtering, sorting, and pagination.
    """
    events = event_history_manager.get_event_history(
        request_id=request_id or command_id,
        event_type=event_type,
        command=command,
        domain=domain,
        status=status,
        start_time=start_time,
        end_time=end_time,
        since_seconds=since_seconds,
        since_minutes=since_minutes,
        limit=limit,
        offset=offset,
        order=order,
        as_dict=True,
    )
    
    total = event_history_manager.count()
    return {
        "status": "success",
        "total_stored": total,
        "count": len(events),
        "offset": offset,
        "limit": limit,
        "order": order.lower(),
        "events": events,
    }


@router.get("/api/v1/events/summary", summary="Get aggregated event history summary and metrics")
@router.get("/api/v1/events/stats", summary="Get aggregated event history stats (alias)")
def get_events_summary():
    """
    Retrieve statistical breakdown of all events stored in memory.
    """
    summary = event_history_manager.get_summary()
    return {
        "status": "success",
        "summary": summary,
    }


@router.get("/api/v1/events/analytics", summary="Get deep latency percentiles and reliability analytics")
def get_events_analytics():
    """
    Compute P50/P90/P95/P99 latency percentiles, domain failure rates, and top executed commands.
    """
    analytics = event_history_manager.get_analytics()
    return {
        "status": "success",
        "analytics": analytics,
    }


@router.get("/api/v1/events/stream", summary="Server-Sent Events (SSE) live real-time event stream")
async def stream_events():
    """
    Stream new backend events live in real time using Server-Sent Events (SSE).
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    event_history_manager.add_async_listener(queue)

    async def event_generator():
        try:
            # Yield connection acknowledged message
            init_payload = json.dumps({"type": "STREAM_CONNECTED", "timestamp": time.time()})
            yield f"data: {init_payload}\n\n"

            while True:
                try:
                    event: Event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    data_str = json.dumps({"type": "EVENT", "data": event.to_dict()})
                    yield f"data: {data_str}\n\n"
                except asyncio.TimeoutError:
                    # Send keep-alive heartbeat comment
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            event_history_manager.remove_async_listener(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.websocket("/api/v1/events/ws")
async def websocket_event_feed(websocket: WebSocket):
    """
    WebSocket endpoint for bidirectional real-time live event streaming.
    """
    await websocket.accept()
    logger.info("[WS SERVER] WS_CONNECTED: New client connection to Event History")
    from core.communication.websocket_server import websocket_server
    session = websocket_server.register_client(websocket)

    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    event_history_manager.add_async_listener(queue)
    try:
        await websocket.send_json({"type": "WS_CONNECTED", "timestamp": time.time()})
        
        async def receive_loop():
            while True:
                msg = await websocket.receive_text()
                session.last_heartbeat = time.time()
                try:
                    data = json.loads(msg)
                    if data.get("type", "").upper() == "PING":
                        await websocket.send_json({"type": "PONG", "timestamp": time.time()})
                except json.JSONDecodeError:
                    pass

        async def send_loop():
            while True:
                event: Event = await queue.get()
                await websocket.send_json({"type": "EVENT", "data": event.to_dict()})

        receive_task = asyncio.create_task(receive_loop())
        send_task = asyncio.create_task(send_loop())
        
        done, pending = await asyncio.wait(
            [receive_task, send_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        for task in pending:
            task.cancel()

    except (WebSocketDisconnect, asyncio.CancelledError):
        logger.info(f"[WS SERVER] WS_DISCONNECTED: Client {session.client_id} disconnected from Event History.")
    except Exception as e:
        logger.warning(f"[WS SERVER] WS_ERROR: Event History WebSocket error: {e}")
    finally:
        logger.info(f"[WS SERVER] WS_CLEANUP: Cleaning up Event History for client {session.client_id}")
        event_history_manager.remove_async_listener(queue)
        websocket_server.unregister_client(websocket)


@router.get("/api/v1/events/history/{event_id}", summary="Get a specific event by Event ID")
@router.get("/api/v1/events/{event_id}", summary="Get a specific event by Event ID (alias)")
def get_event_by_id(event_id: str):
    """
    Retrieve details of a single event using its unique Event ID.
    """
    event = event_history_manager.get_event_by_id(event_id, as_dict=True)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event with ID '{event_id}' was not found in history.",
        )
    return {
        "status": "success",
        "event": event,
    }


@router.post("/api/v1/events", status_code=status.HTTP_201_CREATED, summary="Store a new event")
@router.post("/api/v1/events/store", status_code=status.HTTP_201_CREATED, summary="Store a new event (alias)")
def create_event(req: EventCreateRequest):
    """
    Ingest and store an event into the structured event history.
    """
    meta = dict(req.metadata or {})
    if req.telemetry:
        meta["telemetry"] = req.telemetry.model_dump(exclude_none=True) if hasattr(req.telemetry, "model_dump") else req.telemetry
    if req.device_state:
        meta["device_state"] = req.device_state.model_dump(exclude_none=True) if hasattr(req.device_state, "model_dump") else req.device_state

    event = event_history_manager.store_event(
        event_type=req.event_type,
        command=req.command,
        domain=req.domain,
        status=req.status or "SUCCESS",
        request_id=req.request_id or req.command_id,
        event_id=req.event_id,
        timestamp=req.timestamp,
        execution_duration=req.execution_duration,
        error=req.error,
        metadata=meta,
    )
    return {
        "status": "success",
        "message": "Event stored successfully",
        "event_id": event.event_id,
        "event": event.to_dict(),
    }



@router.delete("/api/v1/events/history", summary="Clear all stored event history")
@router.post("/api/v1/events/clear", summary="Clear all stored event history (POST alias)")
def clear_event_history():
    """
    Clear all events from the event history memory.
    """
    cleared_count = event_history_manager.clear_event_history()
    return {
        "status": "success",
        "message": f"Successfully cleared {cleared_count} events from history.",
        "cleared_count": cleared_count,
    }


# =========================================================================
# INTERACTIVE VISUAL EVENT AUDIT DASHBOARD (UI)
# =========================================================================

@router.get("/events", response_class=HTMLResponse, summary="Interactive Event History Visual Dashboard")
@router.get("/events/dashboard", response_class=HTMLResponse, summary="Interactive Event History Visual Dashboard (alias)")
async def get_event_dashboard():
    """
    Renders an interactive real-time cyber-themed Event History dashboard.
    """
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SynaptiMesh — Event History & Audit Control</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600;700&family=Outfit:wght@600;800;900&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-base: #0a0f1d;
            --bg-card: rgba(15, 23, 42, 0.85);
            --bg-card-hover: rgba(30, 41, 59, 0.9);
            --border-color: rgba(56, 189, 248, 0.2);
            --border-bright: rgba(56, 189, 248, 0.6);
            --primary: #38bdf8;
            --purple: #a855f7;
            --emerald: #10b981;
            --rose: #f43f5e;
            --amber: #f59e0b;
            --text: #f8fafc;
            --text-muted: #94a3b8;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background-color: var(--bg-base);
            background-image: radial-gradient(circle at 50% 0%, #1e1b4b 0%, #0a0f1d 70%);
            color: var(--text);
            font-family: 'Inter', sans-serif;
            min-height: 100vh;
            padding: 24px;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        
        /* Header */
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--border-color);
            margin-bottom: 24px;
        }
        .brand { display: flex; align-items: center; gap: 14px; }
        .logo-badge {
            background: linear-gradient(135deg, #0284c7, #9333ea);
            width: 44px; height: 44px; border-radius: 12px;
            display: grid; place-items: center; font-size: 22px;
            box-shadow: 0 0 20px rgba(56, 189, 248, 0.35);
        }
        h1 { font-family: 'Outfit', sans-serif; font-size: 26px; font-weight: 800; letter-spacing: -0.5px; }
        .live-tag {
            background: rgba(16, 185, 129, 0.15);
            color: var(--emerald);
            border: 1px solid rgba(16, 185, 129, 0.4);
            padding: 4px 12px; border-radius: 9999px;
            font-size: 12px; font-weight: 600;
            display: flex; align-items: center; gap: 6px;
        }
        .pulse-dot {
            width: 8px; height: 8px; border-radius: 50%;
            background-color: var(--emerald);
            box-shadow: 0 0 8px var(--emerald);
            animation: pulse 1.5s infinite;
        }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }

        /* Metrics Row */
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }
        .metric-card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 18px 20px;
            backdrop-filter: blur(12px);
            transition: transform 0.2s, border-color 0.2s;
        }
        .metric-card:hover { transform: translateY(-2px); border-color: var(--border-bright); }
        .metric-label { font-size: 13px; color: var(--text-muted); font-weight: 500; margin-bottom: 6px; }
        .metric-value { font-family: 'JetBrains Mono', monospace; font-size: 26px; font-weight: 700; color: var(--text); }
        .metric-sub { font-size: 12px; color: var(--text-muted); margin-top: 4px; }

        /* Controls Panel */
        .controls-panel {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 16px 20px;
            margin-bottom: 24px;
            display: flex;
            flex-wrap: wrap;
            gap: 12px;
            align-items: center;
            justify-content: space-between;
        }
        .filter-group { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
        input, select, button {
            background: rgba(3, 7, 18, 0.6);
            border: 1px solid var(--border-color);
            color: var(--text);
            padding: 8px 14px;
            border-radius: 10px;
            font-size: 13px;
            font-family: inherit;
            outline: none;
            transition: border-color 0.2s;
        }
        input:focus, select:focus { border-color: var(--primary); }
        button {
            cursor: pointer;
            font-weight: 600;
            display: inline-flex; align-items: center; gap: 6px;
            transition: all 0.2s;
        }
        .btn-primary { background: linear-gradient(135deg, #0284c7, #0369a1); border: none; }
        .btn-primary:hover { background: #0284c7; box-shadow: 0 0 12px rgba(56, 189, 248, 0.4); }
        .btn-danger { background: rgba(244, 63, 94, 0.15); border-color: rgba(244, 63, 94, 0.4); color: var(--rose); }
        .btn-danger:hover { background: rgba(244, 63, 94, 0.25); }

        /* Table View */
        .table-container {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 12px 35px rgba(0, 0, 0, 0.4);
        }
        table { width: 100%; border-collapse: collapse; text-align: left; }
        th {
            background: rgba(3, 7, 18, 0.8);
            padding: 14px 18px;
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-muted);
            border-bottom: 1px solid var(--border-color);
        }
        td {
            padding: 12px 18px;
            font-size: 13px;
            border-bottom: 1px solid rgba(148, 163, 184, 0.08);
        }
        tr:hover td { background: var(--bg-card-hover); }
        .mono { font-family: 'JetBrains Mono', monospace; font-size: 12px; }
        
        /* Badges */
        .badge {
            display: inline-block; padding: 3px 8px;
            border-radius: 6px; font-size: 11px; font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
        }
        .badge-success { background: rgba(16, 185, 129, 0.15); color: var(--emerald); border: 1px solid rgba(16, 185, 129, 0.3); }
        .badge-failed { background: rgba(244, 63, 94, 0.15); color: var(--rose); border: 1px solid rgba(244, 63, 94, 0.3); }
        .badge-pending { background: rgba(245, 158, 11, 0.15); color: var(--amber); border: 1px solid rgba(245, 158, 11, 0.3); }
        .badge-domain { background: rgba(168, 85, 247, 0.15); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.3); }

        /* Modal */
        .modal-overlay {
            position: fixed; inset: 0; background: rgba(0,0,0,0.7);
            backdrop-filter: blur(6px); display: none; place-items: center; z-index: 1000;
        }
        .modal-content {
            background: #0f172a; border: 1px solid var(--border-bright);
            border-radius: 16px; width: 90%; max-width: 650px; padding: 24px;
            box-shadow: 0 20px 50px rgba(0,0,0,0.8);
        }
        pre {
            background: #030712; padding: 14px; border-radius: 10px;
            font-family: 'JetBrains Mono', monospace; font-size: 12px;
            overflow-x: auto; color: #38bdf8; max-height: 400px;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="brand">
                <div class="logo-badge">⚡</div>
                <div>
                    <h1>SynaptiMesh Event History & Audit</h1>
                    <div style="font-size: 12px; color: var(--text-muted);">Member 7 (Mubeena) — Backend Event Store & Telemetry Stream</div>
                </div>
            </div>
            <div class="live-tag">
                <div class="pulse-dot"></div>
                <span id="stream-status">SSE LIVE CONNECTED</span>
            </div>
        </header>

        <!-- Metric Cards -->
        <div class="metrics-grid">
            <div class="metric-card">
                <div class="metric-label">Total Stored Events</div>
                <div class="metric-value" id="val-total">0</div>
                <div class="metric-sub" id="sub-total">In-Memory Audit Trail</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Avg Execution Latency</div>
                <div class="metric-value" style="color: var(--primary);" id="val-avg-lat">0.0 ms</div>
                <div class="metric-sub" id="val-percentiles">P50: 0ms | P90: 0ms</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Overall Reliability</div>
                <div class="metric-value" style="color: var(--emerald);" id="val-success-rate">100%</div>
                <div class="metric-sub" id="val-fail-count">0 Failures Detected</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Active Domains</div>
                <div class="metric-value" style="color: var(--purple);" id="val-domains">4</div>
                <div class="metric-sub">Desktop, Embedded, IoT, AIML</div>
            </div>
        </div>

        <!-- Filter & Search Controls -->
        <div class="controls-panel">
            <div class="filter-group">
                <input type="text" id="search-input" placeholder="🔍 Search Command / Request ID..." oninput="applyFilters()">
                <select id="domain-filter" onchange="applyFilters()">
                    <option value="">All Domains</option>
                    <option value="DESKTOP">Desktop</option>
                    <option value="EMBEDDED">Embedded</option>
                    <option value="IOT">IoT</option>
                    <option value="AIML">AIML</option>
                    <option value="MEDIA">Media</option>
                </select>
                <select id="status-filter" onchange="applyFilters()">
                    <option value="">All Statuses</option>
                    <option value="SUCCESS">Success</option>
                    <option value="FAILED">Failed</option>
                    <option value="IN_PROGRESS">In Progress</option>
                </select>
            </div>
            <div class="filter-group">
                <button class="btn-primary" onclick="fetchHistory()">↻ Refresh</button>
                <button class="btn-danger" onclick="clearHistory()">🗑 Clear History</button>
            </div>
        </div>

        <!-- Event Table -->
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Event ID</th>
                        <th>Request ID</th>
                        <th>Event Type</th>
                        <th>Domain</th>
                        <th>Command</th>
                        <th>Status</th>
                        <th>Duration</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody id="events-tbody">
                    <tr>
                        <td colspan="9" style="text-align:center; color: var(--text-muted); padding: 40px;">
                            Waiting for events to arrive...
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>

    <!-- JSON Inspector Modal -->
    <div class="modal-overlay" id="json-modal" onclick="closeModal(event)">
        <div class="modal-content" onclick="event.stopPropagation()">
            <h3 style="margin-bottom: 12px; font-family: Outfit;">Inspect Event Payload</h3>
            <pre id="modal-json"></pre>
            <div style="text-align: right; margin-top: 14px;">
                <button class="btn-primary" onclick="document.getElementById('json-modal').style.display='none'">Close</button>
            </div>
        </div>
    </div>

    <script>
        let allEvents = [];

        async function fetchHistory() {
            try {
                const res = await fetch('/api/v1/events/history?limit=100&order=desc');
                const data = await res.json();
                if (data.status === 'success') {
                    allEvents = data.events;
                    renderTable(allEvents);
                }
                updateAnalytics();
            } catch (err) {
                console.error('Failed to fetch events:', err);
            }
        }

        async function updateAnalytics() {
            try {
                const res = await fetch('/api/v1/events/analytics');
                const json = await res.json();
                if (json.status === 'success') {
                    const a = json.analytics;
                    document.getElementById('val-total').textContent = a.total_events;
                    document.getElementById('val-avg-lat').textContent = `${a.latency_metrics.avg_ms} ms`;
                    document.getElementById('val-percentiles').textContent = `P50: ${a.latency_metrics.p50_ms}ms | P90: ${a.latency_metrics.p90_ms}ms | P99: ${a.latency_metrics.p99_ms}ms`;
                    
                    const rel = a.reliability_metrics;
                    const successPct = (100 - rel.overall_failure_rate_percent).toFixed(1);
                    document.getElementById('val-success-rate').textContent = `${successPct}%`;
                    document.getElementById('val-fail-count').textContent = `${rel.total_failures} Failures Detected`;
                }
            } catch (err) {
                console.error('Failed to fetch analytics:', err);
            }
        }

        function renderTable(events) {
            const tbody = document.getElementById('events-tbody');
            if (!events || events.length === 0) {
                tbody.innerHTML = '<tr><td colspan="9" style="text-align:center; color: var(--text-muted); padding: 40px;">No events recorded in history yet.</td></tr>';
                return;
            }

            tbody.innerHTML = events.map(ev => {
                const statusBadge = ev.status === 'SUCCESS' ? 'badge-success' : (ev.status === 'FAILED' ? 'badge-failed' : 'badge-pending');
                const timeStr = new Date(ev.timestamp * 1000).toLocaleTimeString();
                const durStr = ev.execution_duration != null ? `${ev.execution_duration.toFixed(1)} ms` : '-';
                const domainBadge = ev.domain ? `<span class="badge badge-domain">${ev.domain}</span>` : '-';
                
                return `
                    <tr>
                        <td class="mono" style="color: var(--text-muted);">${timeStr}</td>
                        <td class="mono" style="color: var(--primary);">${ev.event_id}</td>
                        <td class="mono">${ev.request_id || '-'}</td>
                        <td><strong>${ev.event_type}</strong></td>
                        <td>${domainBadge}</td>
                        <td class="mono" style="color: #cbd5e1;">${typeof ev.command === 'object' ? JSON.stringify(ev.command) : (ev.command || '-')}</td>
                        <td><span class="badge ${statusBadge}">${ev.status}</span></td>
                        <td class="mono">${durStr}</td>
                        <td>
                            <button style="padding: 4px 10px; font-size: 11px;" onclick="inspectEvent('${ev.event_id}')">Inspect</button>
                        </td>
                    </tr>
                `;
            }).join('');
        }

        function applyFilters() {
            const query = document.getElementById('search-input').value.toUpperCase();
            const domain = document.getElementById('domain-filter').value;
            const status = document.getElementById('status-filter').value;

            const filtered = allEvents.filter(ev => {
                if (domain && ev.domain !== domain) return false;
                if (status && ev.status !== status) return false;
                if (query) {
                    const text = `${ev.event_id} ${ev.request_id || ''} ${ev.command || ''} ${ev.event_type}`.toUpperCase();
                    if (!text.includes(query)) return false;
                }
                return true;
            });
            renderTable(filtered);
        }

        function inspectEvent(eventId) {
            const ev = allEvents.find(e => e.event_id === eventId);
            if (ev) {
                document.getElementById('modal-json').textContent = JSON.stringify(ev, null, 2);
                document.getElementById('json-modal').style.display = 'grid';
            }
        }

        function closeModal(e) {
            if (e.target.id === 'json-modal') {
                document.getElementById('json-modal').style.display = 'none';
            }
        }

        async function clearHistory() {
            if (confirm('Clear all stored event history memory?')) {
                await fetch('/api/v1/events/history', { method: 'DELETE' });
                fetchHistory();
            }
        }

        // Live SSE Streaming Connection
        function setupEventStream() {
            const source = new EventSource('/api/v1/events/stream');
            source.onmessage = (e) => {
                try {
                    const payload = JSON.parse(e.data);
                    if (payload.type === 'EVENT' && payload.data) {
                        allEvents.unshift(payload.data);
                        if (allEvents.length > 200) allEvents.pop();
                        applyFilters();
                        updateAnalytics();
                    }
                } catch (err) {}
            };
            source.onerror = () => {
                document.getElementById('stream-status').textContent = 'RECONNECTING...';
            };
            source.onopen = () => {
                document.getElementById('stream-status').textContent = 'SSE LIVE CONNECTED';
            };
        }

        // Initialize
        fetchHistory();
        setupEventStream();
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)
