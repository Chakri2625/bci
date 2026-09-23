"""
Event History Storage and Manager (Sprint 10 Day 8 - Member 7: Mubeena)
========================================================================
Maintains structured, chronological history of all backend events generated
during command processing, state transitions, domain routing, and execution.

Provides:
- Fast O(1) lookups and indexed request queries.
- Flexible filtering, time-window constraints, sorting, and pagination.
- Advanced performance metrics (P50, P90, P95, P99 latency, failure rates per domain).
- Live real-time event streaming via async subscriber queues (SSE & WebSocket).
- Thread-safe in-memory event storage with optional capacity constraints.
- Seamless hooks for EcosystemOrchestrator, LifecycleTracker, and EventBus.
"""

from __future__ import annotations

import asyncio
import datetime
from enum import Enum
import itertools
import logging
import math
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Set, Union

logger = logging.getLogger("event_history")


class EventType(str, Enum):
    """Standardized event types across the SynaptiMesh ecosystem."""
    COMMAND_RECEIVED = "COMMAND_RECEIVED"
    COMMAND_NORMALIZED = "COMMAND_NORMALIZED"
    COMMAND_VALIDATED = "COMMAND_VALIDATED"
    COMMAND_VALIDATION_FAILED = "COMMAND_VALIDATION_FAILED"
    COMMAND_ROUTED = "COMMAND_ROUTED"
    COMMAND_QUEUED = "COMMAND_QUEUED"
    COMMAND_ACCEPTED = "COMMAND_ACCEPTED"
    COMMAND_LOCKED = "COMMAND_LOCKED"
    COMBINATION_CREATED = "COMBINATION_CREATED"
    COMMAND_IGNORED_DURING_LOCK = "COMMAND_IGNORED_DURING_LOCK"
    TIMER_STARTED = "TIMER_STARTED"
    TIMER_CONTINUED = "TIMER_CONTINUED"
    TIMER_EXPIRED = "TIMER_EXPIRED"
    COMMAND_UNLOCKED = "COMMAND_UNLOCKED"
    HOME_NAVIGATION = "HOME_NAVIGATION"
    BACK_NAVIGATION = "BACK_NAVIGATION"
    EXECUTION_STARTED = "EXECUTION_STARTED"
    EXECUTION_COMPLETED = "EXECUTION_COMPLETED"
    EXECUTION_PROGRESS = "EXECUTION_PROGRESS"
    COMMAND_SUCCESS = "COMMAND_SUCCESS"
    COMMAND_FAILED = "COMMAND_FAILED"
    COMMAND_CANCELLED = "COMMAND_CANCELLED"
    COMMAND_TIMEOUT = "COMMAND_TIMEOUT"
    STATE_TRANSITION = "STATE_TRANSITION"
    PRIORITY_ADJUSTED = "PRIORITY_ADJUSTED"
    RESOURCE_LOCKED = "RESOURCE_LOCKED"
    RESOURCE_RELEASED = "RESOURCE_RELEASED"
    HARDWARE_IO = "HARDWARE_IO"
    SYSTEM_DIAGNOSTIC = "SYSTEM_DIAGNOSTIC"
    DEVICE_STATE_CHANGED = "DEVICE_STATE_CHANGED"
    DEVICE_CONNECTED = "DEVICE_CONNECTED"
    DEVICE_DISCONNECTED = "DEVICE_DISCONNECTED"
    CUSTOM = "CUSTOM"


class EventStatus(str, Enum):
    """Status outcomes for stored events."""
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"


class Event:
    """
    Structured data model representing a single backend event.
    
    Attributes:
        event_id: Unique identifier for the event (e.g. EVT-xxxxxxxx)
        request_id / command_id: Correlation ID linking to the parent command/request
        event_type: Type of event (EventType or string)
        command: Command string, payload, or action name
        domain: Target/source domain (e.g. PYTHON, DESKTOP, EMBEDDED, IOT, AIML, SYSTEM)
        status: Execution/event status (EventStatus or string)
        timestamp: Unix timestamp (seconds since epoch)
        timestamp_iso: UTC ISO-8601 formatted timestamp string
        execution_duration: Elapsed execution time (in milliseconds or seconds), if available
        error: Error message, details, or error object if failed
        metadata: Arbitrary additional structured data/context
    """

    def __init__(
        self,
        event_type: Union[EventType, str],
        command: Optional[Union[str, Dict[str, Any], List[Any]]] = None,
        domain: Optional[str] = None,
        status: Union[EventStatus, str] = EventStatus.SUCCESS,
        request_id: Optional[str] = None,
        command_id: Optional[str] = None,
        event_id: Optional[str] = None,
        timestamp: Optional[float] = None,
        execution_duration: Optional[float] = None,
        error: Optional[Union[str, Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.event_id = event_id or f"EVT-{uuid.uuid4().hex[:12].upper()}"
        self.request_id = request_id or command_id
        self.command_id = self.request_id  # Ensure command_id and request_id are aliases
        
        self.event_type = event_type.value if isinstance(event_type, EventType) else str(event_type)
        self.command = command
        self.domain = domain.upper() if domain else None
        self.status = status.value if isinstance(status, EventStatus) else str(status).upper()
        
        self.timestamp = timestamp if timestamp is not None else time.time()
        self.timestamp_iso = datetime.datetime.fromtimestamp(
            self.timestamp, tz=datetime.timezone.utc
        ).isoformat()
        
        self.execution_duration = execution_duration
        self.error = error
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert the event object to a JSON-serializable dictionary."""
        return {
            "event_id": self.event_id,
            "request_id": self.request_id,
            "command_id": self.command_id,
            "event_type": self.event_type,
            "command": self.command,
            "domain": self.domain,
            "status": self.status,
            "timestamp": self.timestamp,
            "timestamp_iso": self.timestamp_iso,
            "execution_duration": self.execution_duration,
            "error": self.error,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Event:
        """Construct an Event object from a dictionary."""
        return cls(
            event_id=data.get("event_id"),
            request_id=data.get("request_id") or data.get("command_id"),
            command_id=data.get("command_id") or data.get("request_id"),
            event_type=data.get("event_type", EventType.CUSTOM),
            command=data.get("command"),
            domain=data.get("domain"),
            status=data.get("status", EventStatus.SUCCESS),
            timestamp=data.get("timestamp"),
            execution_duration=data.get("execution_duration"),
            error=data.get("error"),
            metadata=data.get("metadata") or {},
        )

    def __repr__(self) -> str:
        return (
            f"<Event id={self.event_id} type={self.event_type} "
            f"cmd={self.command} domain={self.domain} status={self.status}>"
        )


class EventHistoryManager:
    """
    Thread-safe manager for storing, querying, and managing backend event history.
    
    Guarantees:
    - Events are stored strictly in chronological sequence.
    - O(1) retrieval by event_id and fast indexing by request_id.
    - Rich filtering by request ID, event type, command, status, domain, and timestamp ranges.
    - Advanced analytics (P50, P90, P99 latency percentiles, failure rates).
    - Real-time subscriber dispatching for SSE / WebSocket feeds.
    - Concurrent-safe operations via reentrant locking.
    """

    def __init__(self, max_capacity: Optional[int] = 10000):
        self._lock = threading.RLock()
        self._events: List[Event] = []
        self._events_by_id: Dict[str, Event] = {}
        self._events_by_request_id: Dict[str, List[Event]] = {}
        self._max_capacity = max_capacity
        self._total_stored_count = 0
        
        # Real-time streaming listeners
        self._async_listeners: Set[asyncio.Queue] = set()
        self._sync_listeners: List[Callable[[Event], None]] = []

    def add_async_listener(self, queue: asyncio.Queue) -> None:
        """Register an asyncio.Queue for live event streaming (SSE/WebSocket)."""
        with self._lock:
            self._async_listeners.add(queue)

    def remove_async_listener(self, queue: asyncio.Queue) -> None:
        """Unregister an asyncio.Queue from live streaming."""
        with self._lock:
            self._async_listeners.discard(queue)

    def add_sync_listener(self, callback: Callable[[Event], None]) -> None:
        """Register a synchronous callback to be notified on new events."""
        with self._lock:
            if callback not in self._sync_listeners:
                self._sync_listeners.append(callback)

    def remove_sync_listener(self, callback: Callable[[Event], None]) -> None:
        """Unregister a synchronous callback."""
        with self._lock:
            if callback in self._sync_listeners:
                self._sync_listeners.remove(callback)

    def store_event(
        self,
        event_or_type: Optional[Union[Event, EventType, str]] = None,
        command: Optional[Union[str, Dict[str, Any], List[Any]]] = None,
        domain: Optional[str] = None,
        status: Union[EventStatus, str] = EventStatus.SUCCESS,
        request_id: Optional[str] = None,
        command_id: Optional[str] = None,
        event_id: Optional[str] = None,
        timestamp: Optional[float] = None,
        execution_duration: Optional[float] = None,
        error: Optional[Union[str, Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Event:
        """
        Store a new event into history in strict chronological order.
        
        Can accept either an existing `Event` instance or individual field keyword arguments.
        """
        if isinstance(event_or_type, Event):
            event = event_or_type
        else:
            event_type = event_or_type or kwargs.get("event_type", EventType.CUSTOM)
            merged_meta = dict(metadata or {})
            if kwargs:
                for k, v in kwargs.items():
                    if k not in (
                        "event_type", "command", "domain", "status",
                        "request_id", "command_id", "event_id", "timestamp",
                        "execution_duration", "error", "metadata"
                    ):
                        merged_meta[k] = v

            event = Event(
                event_type=event_type,
                command=command,
                domain=domain,
                status=status,
                request_id=request_id or command_id,
                command_id=command_id or request_id,
                event_id=event_id,
                timestamp=timestamp,
                execution_duration=execution_duration,
                error=error,
                metadata=merged_meta,
            )

        with self._lock:
            # Enforce capacity constraints if specified
            if self._max_capacity and len(self._events) >= self._max_capacity:
                evicted = self._events.pop(0)
                self._events_by_id.pop(evicted.event_id, None)
                if evicted.request_id and evicted.request_id in self._events_by_request_id:
                    req_list = self._events_by_request_id[evicted.request_id]
                    if evicted in req_list:
                        req_list.remove(evicted)
                    if not req_list:
                        self._events_by_request_id.pop(evicted.request_id, None)

            # Append to chronological store
            self._events.append(event)
            self._events_by_id[event.event_id] = event
            
            if event.request_id:
                if event.request_id not in self._events_by_request_id:
                    self._events_by_request_id[event.request_id] = []
                self._events_by_request_id[event.request_id].append(event)

            self._total_stored_count += 1
            logger.debug(f"[EVENT_HISTORY] Stored event {event.event_id} ({event.event_type})")

            # Dispatch to sync listeners
            for cb in self._sync_listeners:
                try:
                    cb(event)
                except Exception as e:
                    logger.warning(f"Error in sync listener callback: {e}")

            # Dispatch to async streaming queues
            dead_queues = []
            for q in list(self._async_listeners):
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    pass
                except Exception:
                    dead_queues.append(q)
            for dq in dead_queues:
                self._async_listeners.discard(dq)

            return event

    def record_event(self, *args, **kwargs) -> Event:
        """Alias for store_event for backward-compatibility."""
        return self.store_event(*args, **kwargs)

    def get_event_history(
        self,
        request_id: Optional[str] = None,
        command_id: Optional[str] = None,
        event_type: Optional[Union[EventType, str]] = None,
        command: Optional[str] = None,
        domain: Optional[str] = None,
        status: Optional[Union[EventStatus, str]] = None,
        start_time: Optional[Union[float, str]] = None,
        end_time: Optional[Union[float, str]] = None,
        since_seconds: Optional[float] = None,
        since_minutes: Optional[float] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        order: str = "asc",
        as_dict: bool = True,
    ) -> List[Union[Dict[str, Any], Event]]:
        """
        Retrieve stored event history with flexible multi-parameter filtering.
        """
        target_req_id = request_id or command_id
        target_type = event_type.value if isinstance(event_type, EventType) else event_type
        target_status = status.value if isinstance(status, EventStatus) else status

        # Support relative time-window helpers
        now_ts = time.time()
        start_ts: Optional[float] = None
        if since_minutes is not None:
            start_ts = now_ts - (since_minutes * 60.0)
        elif since_seconds is not None:
            start_ts = now_ts - since_seconds
        elif start_time is not None:
            if isinstance(start_time, (int, float)):
                start_ts = float(start_time)
            elif isinstance(start_time, str):
                try:
                    start_ts = float(start_time)
                except ValueError:
                    try:
                        start_ts = datetime.datetime.fromisoformat(
                            start_time.replace("Z", "+00:00")
                        ).timestamp()
                    except Exception:
                        start_ts = None

        end_ts: Optional[float] = None
        if end_time is not None:
            if isinstance(end_time, (int, float)):
                end_ts = float(end_time)
            elif isinstance(end_time, str):
                try:
                    end_ts = float(end_time)
                except ValueError:
                    try:
                        end_ts = datetime.datetime.fromisoformat(
                            end_time.replace("Z", "+00:00")
                        ).timestamp()
                    except Exception:
                        end_ts = None

        with self._lock:
            if target_req_id and target_req_id in self._events_by_request_id:
                candidates = list(self._events_by_request_id[target_req_id])
            else:
                candidates = list(self._events)

            filtered: List[Event] = []
            for ev in candidates:
                if target_req_id and ev.request_id != target_req_id:
                    continue
                if target_type and ev.event_type.upper() != target_type.upper():
                    continue
                if domain and (not ev.domain or ev.domain.upper() != domain.upper()):
                    continue
                if target_status and ev.status.upper() != target_status.upper():
                    continue
                if command:
                    cmd_str = str(ev.command or "")
                    if command.upper() not in cmd_str.upper():
                        continue
                if start_ts is not None and ev.timestamp < start_ts:
                    continue
                if end_ts is not None and ev.timestamp > end_ts:
                    continue
                filtered.append(ev)

            if order.lower() == "desc":
                filtered.reverse()

            if offset > 0:
                filtered = filtered[offset:]
            if limit is not None and limit >= 0:
                filtered = filtered[:limit]

            if as_dict:
                return [e.to_dict() for e in filtered]
            return filtered

    def get_event_by_id(
        self, event_id: str, as_dict: bool = True
    ) -> Optional[Union[Dict[str, Any], Event]]:
        """O(1) lookup of a specific event by its event_id."""
        with self._lock:
            event = self._events_by_id.get(event_id)
            if event is None:
                return None
            return event.to_dict() if as_dict else event

    def get_events_by_request_id(
        self, request_id: str, as_dict: bool = True
    ) -> List[Union[Dict[str, Any], Event]]:
        """Retrieve all events associated with a specific request/command ID."""
        with self._lock:
            events = self._events_by_request_id.get(request_id, [])
            if as_dict:
                return [e.to_dict() for e in events]
            return list(events)

    def clear_event_history(self) -> int:
        """Clear all stored events from history and return the number of cleared events."""
        with self._lock:
            count = len(self._events)
            self._events.clear()
            self._events_by_id.clear()
            self._events_by_request_id.clear()
            logger.info(f"[EVENT_HISTORY] Cleared {count} events from history.")
            return count

    def count(self) -> int:
        """Return the current number of stored events."""
        with self._lock:
            return len(self._events)

    def get_summary(self) -> Dict[str, Any]:
        """Generate statistical summary of stored events."""
        with self._lock:
            by_type: Dict[str, int] = {}
            by_status: Dict[str, int] = {}
            by_domain: Dict[str, int] = {}
            
            total_duration = 0.0
            duration_count = 0

            for ev in self._events:
                by_type[ev.event_type] = by_type.get(ev.event_type, 0) + 1
                by_status[ev.status] = by_status.get(ev.status, 0) + 1
                dom = ev.domain or "UNSPECIFIED"
                by_domain[dom] = by_domain.get(dom, 0) + 1
                
                if ev.execution_duration is not None:
                    total_duration += ev.execution_duration
                    duration_count += 1

            first_event_time = self._events[0].timestamp_iso if self._events else None
            last_event_time = self._events[-1].timestamp_iso if self._events else None
            avg_duration = (total_duration / duration_count) if duration_count > 0 else 0.0

            return {
                "total_events": len(self._events),
                "lifetime_stored_count": self._total_stored_count,
                "first_event_at": first_event_time,
                "last_event_at": last_event_time,
                "events_by_type": by_type,
                "events_by_status": by_status,
                "events_by_domain": by_domain,
                "average_execution_duration_ms": round(avg_duration, 2),
            }

    def get_analytics(self) -> Dict[str, Any]:
        """
        Compute deep performance metrics, percentiles (P50, P90, P95, P99),
        per-domain failure rates, and command execution frequency breakdown.
        """
        with self._lock:
            durations: List[float] = []
            domain_metrics: Dict[str, Dict[str, Any]] = {}
            command_counts: Dict[str, int] = {}
            error_counts: Dict[str, int] = {}
            status_counts: Dict[str, int] = {}

            for ev in self._events:
                status_counts[ev.status] = status_counts.get(ev.status, 0) + 1
                
                # Command frequency
                if ev.command:
                    cmd_key = str(ev.command)
                    command_counts[cmd_key] = command_counts.get(cmd_key, 0) + 1

                # Error frequency
                if ev.error:
                    err_str = str(ev.error)
                    error_counts[err_str] = error_counts.get(err_str, 0) + 1

                # Domain breakdown
                dom = ev.domain or "UNSPECIFIED"
                if dom not in domain_metrics:
                    domain_metrics[dom] = {
                        "total": 0,
                        "success": 0,
                        "failed": 0,
                        "durations": [],
                    }
                d_entry = domain_metrics[dom]
                d_entry["total"] += 1
                if ev.status in ("SUCCESS", "COMPLETED", "OK"):
                    d_entry["success"] += 1
                elif ev.status in ("FAILED", "ERROR", "REJECTED", "CANCELLED", "TIMEOUT"):
                    d_entry["failed"] += 1

                if ev.execution_duration is not None and ev.execution_duration >= 0:
                    durations.append(ev.execution_duration)
                    d_entry["durations"].append(ev.execution_duration)

            # Compute percentiles
            durations.sort()
            n = len(durations)
            
            def percentile(p: float) -> float:
                if not durations:
                    return 0.0
                k = (n - 1) * p
                f = math.floor(k)
                c = math.ceil(k)
                if f == c:
                    return round(durations[int(k)], 2)
                d0 = durations[int(f)] * (c - k)
                d1 = durations[int(c)] * (k - f)
                return round(d0 + d1, 2)

            p50 = percentile(0.50)
            p90 = percentile(0.90)
            p95 = percentile(0.95)
            p99 = percentile(0.99)
            avg_lat = round(sum(durations) / n, 2) if n > 0 else 0.0
            min_lat = round(durations[0], 2) if n > 0 else 0.0
            max_lat = round(durations[-1], 2) if n > 0 else 0.0

            # Process domain metrics
            domain_summary = {}
            for dom, data in domain_metrics.items():
                t = data["total"]
                f = data["failed"]
                fail_pct = round((f / t) * 100.0, 2) if t > 0 else 0.0
                d_durs = data["durations"]
                d_avg = round(sum(d_durs) / len(d_durs), 2) if d_durs else 0.0
                domain_summary[dom] = {
                    "total_events": t,
                    "success_count": data["success"],
                    "failed_count": f,
                    "failure_rate_percent": fail_pct,
                    "average_duration_ms": d_avg,
                }

            # Top 10 commands
            top_commands = [
                {"command": k, "count": v}
                for k, v in sorted(command_counts.items(), key=lambda x: x[1], reverse=True)[:10]
            ]

            total_events = len(self._events)
            total_failed = sum(v for k, v in status_counts.items() if k in ("FAILED", "ERROR", "REJECTED", "CANCELLED", "TIMEOUT"))
            overall_failure_rate = round((total_failed / total_events) * 100.0, 2) if total_events > 0 else 0.0

            return {
                "total_events": total_events,
                "latency_metrics": {
                    "count": n,
                    "min_ms": min_lat,
                    "max_ms": max_lat,
                    "avg_ms": avg_lat,
                    "p50_ms": p50,
                    "p90_ms": p90,
                    "p95_ms": p95,
                    "p99_ms": p99,
                },
                "reliability_metrics": {
                    "total_failures": total_failed,
                    "overall_failure_rate_percent": overall_failure_rate,
                    "status_breakdown": status_counts,
                },
                "domain_analytics": domain_summary,
                "top_commands": top_commands,
                "top_errors": [
                    {"error": k, "count": v}
                    for k, v in sorted(error_counts.items(), key=lambda x: x[1], reverse=True)[:10]
                ],
            }

    def attach_to_event_bus(self, bus=None) -> None:
        """Subscribe to the global event bus to mirror events into history."""
        try:
            if bus is None:
                from core.events.event_bus import event_bus
                bus = event_bus

            def bus_subscriber(payload):
                try:
                    if isinstance(payload, dict):
                        self.store_event(
                            event_type=payload.get("event_type", EventType.CUSTOM),
                            command=payload.get("command"),
                            domain=payload.get("domain"),
                            status=payload.get("status", EventStatus.SUCCESS),
                            request_id=payload.get("request_id") or payload.get("command_id"),
                            metadata=payload,
                        )
                except Exception as ex:
                    logger.warning(f"Error mirroring event bus payload: {ex}")

            bus.subscribe("*", bus_subscriber)
            logger.info("[EVENT_HISTORY] Successfully attached to EventBus.")
        except Exception as e:
            logger.warning(f"Failed to attach to EventBus: {e}")

    def export_history(self) -> List[Dict[str, Any]]:
        """Export full history as a list of dicts."""
        return self.get_event_history(as_dict=True)

    # Compatibility alias
    record_event = store_event



# Global singleton instance for easy import across SynaptiMesh
event_history_manager = EventHistoryManager()
event_history = event_history_manager
