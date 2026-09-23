"""
telemetry_routes.py
===================
FastAPI routes and WebSocket streaming for standardized multi-domain telemetry
(BCI, AI/ML, IoT, Embedded).
"""

from collections import deque
from datetime import datetime, timezone
import asyncio
import json
import logging
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from models.telemetry_models import (
    AiMlTelemetry,
    BciTelemetry,
    EmbeddedTelemetry,
    IotTelemetry,
    TelemetryDomain,
    UnifiedTelemetryPacket,
)
from services.bci_aiml_normalizer import bci_aiml_normalizer

logger = logging.getLogger("api.telemetry")

telemetry_router = APIRouter(prefix="/api/v1/telemetry", tags=["Telemetry"])

# In-memory circular telemetry buffer & latest cache
_TELEMETRY_HISTORY: deque = deque(maxlen=500)
_LATEST_TELEMETRY: Dict[str, Dict[str, Any]] = {
    "BCI": {},
    "AI_ML": {},
    "IOT": {},
    "EMBEDDED": {},
    "COMBINED": {}
}

# Connected WebSocket clients
_CONNECTED_WS_CLIENTS: set[WebSocket] = set()


async def broadcast_telemetry_packet(packet: Dict[str, Any]):
    """Broadcast validated telemetry to all connected WebSocket subscribers with error isolation."""
    # 1. Primary broadcast via centralized, high-performance WebSocketServer
    try:
        from core.communication.websocket_server import websocket_server
        domain = packet.get("source_domain") or "CORE"
        source_id = packet.get("source_id") or "master_hub"
        payload = packet.get("payload") or packet
        await websocket_server.broadcast_telemetry(
            domain=str(domain),
            source_id=str(source_id),
            payload=payload,
            telemetry_id=packet.get("telemetry_id"),
            session_id=packet.get("session_id", "default"),
            trace_id=packet.get("trace_id")
        )
    except Exception as ws_err:
        logger.debug(f"Broadcast to websocket_server: {ws_err}")

    # 2. Forward to any legacy sockets in _CONNECTED_WS_CLIENTS not managed by WebSocketServer
    try:
        from core.communication.websocket_server import websocket_server
        with websocket_server._clients_lock:
            active_ws_set = set(websocket_server._clients.keys())
    except Exception:
        active_ws_set = set()

    dead_clients = set()
    for ws in list(_CONNECTED_WS_CLIENTS):
        if ws in active_ws_set:
            continue
        try:
            await ws.send_json(packet)
        except Exception:
            dead_clients.add(ws)

    for dead in dead_clients:
        _CONNECTED_WS_CLIENTS.discard(dead)



# ---------------------------------------------------------------------------
# REST Endpoints
# ---------------------------------------------------------------------------

@telemetry_router.post("", summary="Ingest Standard Telemetry Packet")
async def ingest_telemetry(payload: Dict[str, Any]):
    """
    Ingest, validate, and broadcast a standard telemetry packet across BCI, AI/ML, IoT, or Embedded.
    """
    try:
        # Check if already enveloped
        if "source_domain" in payload and "payload" in payload:
            packet = UnifiedTelemetryPacket(**payload)
        else:
            # Auto-infer domain envelope if domain-specific payload was provided
            domain = payload.get("domain") or payload.get("source_domain") or "IOT"
            source_id = payload.get("source_id") or payload.get("device_id") or payload.get("headsetId") or "node_auto"
            packet = UnifiedTelemetryPacket(
                source_domain=domain,
                source_id=str(source_id),
                session_id=payload.get("session_id", "default"),
                trace_id=payload.get("trace_id"),
                payload=payload
            )

        data = packet.to_dict()

        # Update cache & history
        domain_key = packet.source_domain.value if hasattr(packet.source_domain, "value") else str(packet.source_domain)
        _LATEST_TELEMETRY[domain_key] = data
        _TELEMETRY_HISTORY.append(data)

        # Process through BCI + AI/ML normalizer & correlation engine
        try:
            combined = bci_aiml_normalizer.process_telemetry_packet(packet)
            if combined:
                _LATEST_TELEMETRY["COMBINED"] = combined.to_dict()
                combined_pkt = bci_aiml_normalizer.create_unified_transport_packet(combined)
                await broadcast_telemetry_packet(combined_pkt.to_dict())
        except Exception as norm_err:
            logger.warning(f"Error processing telemetry for combined analytics: {norm_err}")

        # Process Embedded / Robotics movement, speed, battery, safety & status alerts (Member 6)
        if domain_key in ("EMBEDDED", "ROBOTICS"):
            try:
                from services.embedded_alert_generator import embedded_alert_generator
                alerts = embedded_alert_generator.evaluate_telemetry(packet)
                if alerts:
                    for a in alerts:
                        await broadcast_telemetry_packet({
                            "source_domain": "EMBEDDED",
                            "source_id": a.device_id,
                            "type": "ALERT",
                            "payload": a.to_dict()
                        })
            except Exception as alert_err:
                logger.warning(f"Error evaluating embedded alerts during ingestion: {alert_err}")

        # Broadcast live over WebSockets
        await broadcast_telemetry_packet(data)

        return {
            "status": "success",
            "telemetry_id": packet.telemetry_id,
            "domain": domain_key,
            "timestamp": packet.timestamp
        }

    except ValidationError as val_err:
        logger.warning(f"Telemetry validation failed: {val_err}")
        raise HTTPException(status_code=422, detail=val_err.errors())
    except Exception as exc:
        logger.error(f"Telemetry ingestion error: {exc}")
        raise HTTPException(status_code=400, detail=str(exc))


@telemetry_router.post("/aiml/accuracy", summary="Ingest AI/ML Accuracy Telemetry")
async def ingest_aiml_accuracy_telemetry(payload: Dict[str, Any]):
    """Ingest command classification evaluation directly via Telemetry API."""
    try:
        from plugins.aiml.accuracy_engine import accuracy_engine
        if "evaluations" in payload and isinstance(payload["evaluations"], list):
            res = accuracy_engine.ingest_batch(payload["evaluations"])
        else:
            res = accuracy_engine.ingest(payload)
        return res
    except Exception as exc:
        logger.error(f"AI/ML accuracy telemetry ingestion error: {exc}")
        raise HTTPException(status_code=400, detail=str(exc))


@telemetry_router.get("/aiml/accuracy/metrics", summary="Get AI/ML Accuracy Telemetry Metrics")
def get_aiml_accuracy_telemetry_metrics():
    """Retrieve current AI/ML command classification accuracy metrics."""
    try:
        from plugins.aiml.accuracy_engine import accuracy_engine
        return {"status": "success", "metrics": accuracy_engine.get_metrics()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@telemetry_router.get("/combined", summary="Get Latest Combined BCI + AI/ML Analytics")
def get_combined_bci_aiml_analytics():
    """Retrieve the latest combined BCI + AI/ML analytics snapshot."""
    combined = bci_aiml_normalizer.get_latest_combined()
    if not combined:
        return {
            "status": "success",
            "combined": None,
            "message": "No combined analytics produced yet"
        }
    return {
        "status": "success",
        "combined": combined.to_dict()
    }


@telemetry_router.get("/latest", summary="Retrieve Latest Telemetry Snapshots")
def get_latest_telemetry(domain: Optional[str] = Query(None, description="Optional domain filter (BCI, AI_ML, IOT, EMBEDDED, COMBINED)")):
    """Retrieve the most recent telemetry packet per domain or for a specific domain."""
    if domain:
        dom_upper = domain.upper()
        if dom_upper not in _LATEST_TELEMETRY:
            raise HTTPException(status_code=404, detail=f"Domain '{domain}' not found. Valid domains: {list(_LATEST_TELEMETRY.keys())}")
        return {
            "status": "success",
            "domain": dom_upper,
            "telemetry": _LATEST_TELEMETRY.get(dom_upper) or None
        }

    return {
        "status": "success",
        "domains": _LATEST_TELEMETRY
    }


@telemetry_router.get("/history", summary="Retrieve Historical Telemetry Buffer")
def get_telemetry_history(
    limit: int = Query(50, ge=1, le=500, description="Max number of records to return"),
    domain: Optional[str] = Query(None, description="Filter history by domain")
):
    """Retrieve circular buffer history of telemetry packets."""
    records = list(_TELEMETRY_HISTORY)
    if domain:
        dom_upper = domain.upper()
        records = [r for r in records if r.get("source_domain") == dom_upper]

    records = records[-limit:]
    return {
        "status": "success",
        "count": len(records),
        "history": records
    }


@telemetry_router.get("/schema", summary="Retrieve Telemetry JSON Schema")
def get_telemetry_schema():
    """Retrieve the standard JSON Schema (Draft 2020-12) for Unified Telemetry."""
    return UnifiedTelemetryPacket.model_json_schema()



def record_telemetry_packet(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Synchronously record a telemetry packet into history, cache, and schedule WS broadcast.
    """
    try:
        if "source_domain" in payload and "payload" in payload:
            packet = UnifiedTelemetryPacket(**payload)
        else:
            domain = payload.get("domain") or payload.get("source_domain") or "IOT"
            source_id = payload.get("source_id") or payload.get("device_id") or payload.get("headsetId") or "node_auto"
            packet = UnifiedTelemetryPacket(
                source_domain=domain,
                source_id=str(source_id),
                session_id=payload.get("session_id", "default"),
                trace_id=payload.get("trace_id"),
                payload=payload
            )

        data = packet.to_dict()
        domain_key = packet.source_domain.value if hasattr(packet.source_domain, "value") else str(packet.source_domain)
        _LATEST_TELEMETRY[domain_key] = data
        _TELEMETRY_HISTORY.append(data)

        # Process through BCI + AI/ML normalizer & correlation engine
        try:
            combined = bci_aiml_normalizer.process_telemetry_packet(packet)
            if combined:
                _LATEST_TELEMETRY["COMBINED"] = combined.to_dict()
                combined_pkt = bci_aiml_normalizer.create_unified_transport_packet(combined)
                try:
                    loop = asyncio.get_running_loop()
                    if loop.is_running():
                        loop.create_task(broadcast_telemetry_packet(combined_pkt.to_dict()))
                except RuntimeError:
                    pass
        except Exception as norm_err:
            logger.warning(f"Error processing telemetry packet for combined analytics: {norm_err}")

        # Process Embedded / Robotics movement, speed, battery, safety & status alerts (Member 6)
        if domain_key in ("EMBEDDED", "ROBOTICS"):
            try:
                from services.embedded_alert_generator import embedded_alert_generator
                alerts = embedded_alert_generator.evaluate_telemetry(packet)
                if alerts:
                    try:
                        loop = asyncio.get_running_loop()
                        if loop.is_running():
                            for a in alerts:
                                loop.create_task(broadcast_telemetry_packet({
                                    "source_domain": "EMBEDDED",
                                    "source_id": a.device_id,
                                    "type": "ALERT",
                                    "payload": a.to_dict()
                                }))
                    except RuntimeError:
                        pass
            except Exception as alert_err:
                logger.warning(f"Error evaluating embedded alerts during sync record: {alert_err}")

        # Schedule async broadcast if an event loop is running
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(broadcast_telemetry_packet(data))
        except RuntimeError:
            pass

        return data
    except Exception as exc:
        logger.warning(f"Failed to record telemetry packet: {exc}")
        return {}


# ---------------------------------------------------------------------------
# Alert Management Endpoints (Sprint 11 Day 5 Member 6)
# ---------------------------------------------------------------------------

@telemetry_router.get("/alerts", summary="Retrieve Active Alerts and Alert History")
def get_telemetry_alerts(
    device_id: Optional[str] = Query(None, description="Optional device ID filter"),
    limit: int = Query(50, ge=1, le=200, description="Max history records to return")
):
    """Retrieve currently active alerts and recent alert history."""
    try:
        from services.embedded_alert_generator import embedded_alert_generator
        active_alerts = embedded_alert_generator.get_active_alerts(device_id=device_id)
        history = embedded_alert_generator.get_alert_history(limit=limit, device_id=device_id)
        return {
            "status": "success",
            "active_count": len(active_alerts),
            "active_alerts": active_alerts,
            "history_count": len(history),
            "history": history
        }
    except Exception as exc:
        logger.error(f"Error retrieving alerts: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@telemetry_router.post("/alerts/resolve", summary="Resolve Active Alert")
def resolve_telemetry_alert(payload: Dict[str, Any]):
    """Manually resolve an active alert by ID."""
    alert_id = payload.get("alert_id")
    reason = payload.get("reason", "MANUAL_RESOLVE")
    if not alert_id:
        raise HTTPException(status_code=422, detail="Missing required 'alert_id' field")

    try:
        from services.embedded_alert_generator import embedded_alert_generator
        resolved = embedded_alert_generator.resolve_alert(alert_id=alert_id, reason=reason)
        if resolved:
            return {
                "status": "success",
                "message": f"Alert '{alert_id}' resolved",
                "alert": resolved.to_dict()
            }
        return {
            "status": "not_found",
            "message": f"Active alert '{alert_id}' not found or already resolved"
        }
    except Exception as exc:
        logger.error(f"Error resolving alert: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@telemetry_router.post("/alerts/clear", summary="Clear Alerts Cache")
def clear_telemetry_alerts(device_id: Optional[str] = None):
    """Clear active alerts cache and history (useful for test resets)."""
    try:
        from services.embedded_alert_generator import embedded_alert_generator
        embedded_alert_generator.clear_alerts(device_id=device_id)
        return {"status": "success", "message": "Alerts cache cleared"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@telemetry_router.post("/alerts/evaluate", summary="Directly Evaluate Telemetry for Alerts")
def evaluate_telemetry_for_alerts(payload: Dict[str, Any]):
    """Directly evaluate an embedded telemetry payload and return generated / transition alerts."""
    try:
        from services.embedded_alert_generator import embedded_alert_generator
        alerts = embedded_alert_generator.evaluate_telemetry(payload)
        return {
            "status": "success",
            "alerts_count": len(alerts),
            "alerts": [a.to_dict() for a in alerts]
        }
    except Exception as exc:
        logger.error(f"Error evaluating telemetry alerts: {exc}")
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Background Ambient Telemetry Stream Generator
# ---------------------------------------------------------------------------
_AMBIENT_TELEMETRY_TASK: Optional[asyncio.Task] = None


async def _ambient_telemetry_loop():
    """
    Periodically emits ambient telemetry updates across BCI, IoT, Embedded, and AI/ML
    to keep the live telemetry stream actively pulsating.
    """
    import random
    domains_cycle = ["IOT", "BCI", "EMBEDDED", "AI_ML"]
    idx = 0
    while True:
        await asyncio.sleep(3.5)
        try:
            dom = domains_cycle[idx % len(domains_cycle)]
            idx += 1

            if dom == "IOT":
                sample = {
                    "source_domain": "IOT",
                    "source_id": "DEV-101",
                    "session_id": "system_ambient",
                    "payload": {
                        "device_id": "DEV-101",
                        "device_type": "smart_relay",
                        "temperature": round(23.5 + random.uniform(-0.6, 0.6), 1),
                        "humidity": round(48.0 + random.uniform(-1.5, 1.5), 1),
                        "rssi": random.randint(-60, -50),
                        "status": "ONLINE"
                    }
                }
            elif dom == "BCI":
                sample = {
                    "source_domain": "BCI",
                    "source_id": "EPOC-X-DEFAULT",
                    "session_id": "system_ambient",
                    "payload": {
                        "headset_id": "EPOC-X-PRO",
                        "contact_quality": "GOOD",
                        "battery": 94,
                        "signal_quality": round(96.0 + random.uniform(-2.0, 2.0), 1),
                        "command": "NEUTRAL",
                        "power": round(random.uniform(0.08, 0.22), 2)
                    }
                }
            elif dom == "EMBEDDED":
                sample = {
                    "source_domain": "EMBEDDED",
                    "source_id": "RC-CAR-01",
                    "session_id": "system_ambient",
                    "payload": {
                        "device_id": "RC-CAR-01",
                        "device_mode": "RC_CAR",
                        "mcu_architecture": "ESP32-WROOM-32",
                        "firmware_version": "2.0.0-unified",
                        "status": "ONLINE",
                        "system_health": {
                            "free_heap_bytes": 185000 + random.randint(-2000, 2000),
                            "cpu_core_temp_c": round(39.5 + random.uniform(-0.5, 0.5), 1),
                            "battery_soc_pct": random.randint(85, 95),
                            "supply_voltage_v": round(12.4 + random.uniform(-0.2, 0.2), 2),
                            "loop_frequency_hz": 50.0
                        },
                        "kinematics": {
                            "movement": "STOP",
                            "state": "IDLE",
                            "speed": 0.0,
                            "speed_mode": "NORMAL",
                            "motor_left_pwm": 0,
                            "motor_right_pwm": 0
                        }
                    }
                }
            else:  # AI_ML
                sample = {
                    "source_domain": "AI_ML",
                    "source_id": "AIML-ORCHESTRATOR",
                    "session_id": "system_ambient",
                    "payload": {
                        "model": "CognitiveActionRouter",
                        "confidence": round(0.95 + random.uniform(-0.03, 0.03), 2),
                        "latency_ms": round(4.2 + random.uniform(-0.4, 0.4), 1),
                        "status": "READY"
                    }
                }

            pkt = UnifiedTelemetryPacket(**sample)
            data = pkt.to_dict()
            _LATEST_TELEMETRY[dom] = data
            _TELEMETRY_HISTORY.append(data)
            await broadcast_telemetry_packet(data)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug(f"Ambient telemetry loop: {e}")


# ---------------------------------------------------------------------------
# WebSocket Endpoint for Real-time Streaming
# ---------------------------------------------------------------------------

@telemetry_router.websocket("/ws")
async def telemetry_websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint streaming live telemetry frames directly to dashboards and clients.
    """
    await websocket.accept()
    _CONNECTED_WS_CLIENTS.add(websocket)
    from core.communication.websocket_server import websocket_server
    session = websocket_server.register_client(websocket)
    logger.info(f"[WS SERVER] WS_CONNECTED: WebSocket client connected for telemetry streaming. Total clients: {len(_CONNECTED_WS_CLIENTS)}")

    try:
        # Send initial snapshot of latest states
        await websocket.send_json({
            "type": "SNAPSHOT",
            "version": "2.0.0",
            "source_domain": "CORE",
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "data": _LATEST_TELEMETRY
        })

        while True:
            # Keep-alive receive loop
            msg = await websocket.receive_text()
            session.last_heartbeat = time.time()
            try:
                data = json.loads(msg)
                # If client pushes telemetry over WS, ingest and broadcast
                if isinstance(data, dict):
                    if data.get("type") in ("ping", "PING"):
                        await websocket.send_json({
                            "type": "PONG",
                            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                        })
                    elif "type" not in data:
                        await ingest_telemetry(data)
            except Exception:
                pass

    except WebSocketDisconnect:
        logger.info(f"[WS SERVER] WS_DISCONNECTED: WebSocket client disconnected from telemetry stream. Remaining: {len(_CONNECTED_WS_CLIENTS) - 1}")
    except Exception as exc:
        logger.warning(f"[WS SERVER] WS_ERROR: WebSocket telemetry streaming error: {exc}")
    finally:
        logger.info(f"[WS SERVER] WS_CLEANUP: Cleaning up telemetry WS client")
        _CONNECTED_WS_CLIENTS.discard(websocket)
        websocket_server.unregister_client(websocket)


def setup_telemetry_routes(app: FastAPI):
    """Mount telemetry router on FastAPI application instance and start background stream."""
    app.include_router(telemetry_router)

    @app.on_event("startup")
    async def start_telemetry_background():
        global _AMBIENT_TELEMETRY_TASK
        if _AMBIENT_TELEMETRY_TASK is None or _AMBIENT_TELEMETRY_TASK.done():
            _AMBIENT_TELEMETRY_TASK = asyncio.create_task(_ambient_telemetry_loop())

    @app.on_event("shutdown")
    async def stop_telemetry_background():
        global _AMBIENT_TELEMETRY_TASK
        if _AMBIENT_TELEMETRY_TASK and not _AMBIENT_TELEMETRY_TASK.done():
            _AMBIENT_TELEMETRY_TASK.cancel()

