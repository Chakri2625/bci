"""In-memory command performance metrics."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Deque, Dict, Optional


class MetricsService:
    """Collect terminal command measurements in a bounded 60-second window."""

    def __init__(self, window_seconds: float = 60.0, max_samples: int = 10_000):
        self.window_seconds = window_seconds
        self.max_samples = max_samples
        self._events: Deque[Dict[str, Any]] = deque()
        self._recorded_command_ids = set()
        self._lock = threading.RLock()

    def record_completion(self, record: Any) -> bool:
        """Record one terminal lifecycle record, returning whether it was new."""
        with self._lock:
            if record.command_id in self._recorded_command_ids:
                return False

            queued_at = self._transition_time(record, "QUEUED")
            started_at = record.started_at or self._transition_time(record, "EXECUTION_STARTED")
            completed_at = record.completed_at or time.time()
            route = (
                record.metadata.get("route")
                or record.metadata.get("target")
                or record.domain
                or "unknown"
            )
            event = {
                "command_id": record.command_id,
                "command_type": record.command or "UNKNOWN",
                "route": str(route),
                "status": record.current_stage.value,
                "completed_at": completed_at,
                "duration_ms": round(record.duration_ms or 0.0, 2),
                "queue_wait_ms": (
                    round(max(0.0, (started_at - queued_at) * 1000.0), 2)
                    if queued_at is not None and started_at is not None
                    else None
                ),
            }
            if len(self._events) >= self.max_samples:
                evicted = self._events.popleft()
                self._recorded_command_ids.discard(evicted["command_id"])
            self._events.append(event)
            self._recorded_command_ids.add(record.command_id)
            self._prune(completed_at)
            return True

    def get_stats(self, command_type: Optional[str] = None, route: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            self._prune(time.time())
            events = [
                event for event in self._events
                if (command_type is None or event["command_type"] == command_type)
                and (route is None or event["route"] == route)
            ]
            return self._summarize(events, command_type=command_type, route=route)

    def getStats(self, command_type: Optional[str] = None, route: Optional[str] = None) -> Dict[str, Any]:
        """Compatibility-friendly camelCase interface for API consumers."""
        return self.get_stats(command_type=command_type, route=route)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._recorded_command_ids.clear()

    def _summarize(
        self,
        events: list[Dict[str, Any]],
        command_type: Optional[str],
        route: Optional[str],
    ) -> Dict[str, Any]:
        completed = len(events)
        successes = sum(event["status"] == "SUCCESS" for event in events)
        failures = completed - successes
        durations = [event["duration_ms"] for event in events]
        queue_waits = [event["queue_wait_ms"] for event in events if event["queue_wait_ms"] is not None]
        success_rate = successes / completed if completed else 0.0
        failure_rate = failures / completed if completed else 0.0
        return {
            "window_seconds": self.window_seconds,
            "command_type": command_type,
            "route": route,
            "completed_commands": completed,
            "throughput": {
                "commands_per_second": round(completed / self.window_seconds, 4),
                "commands_per_minute": round(completed * 60.0 / self.window_seconds, 4),
            },
            "success_count": successes,
            "failure_count": failures,
            "success_rate": round(success_rate, 4),
            "failure_rate": round(failure_rate, 4),
            "error_rate_percent": round(failure_rate * 100.0, 2),
            "latency_ms": self._distribution(durations),
            "queue_wait_ms": self._distribution(queue_waits),
            "by_command_type": self._group(events, "command_type"),
            "by_route": self._group(events, "route"),
        }

    def _group(self, events: list[Dict[str, Any]], field: str) -> Dict[str, Any]:
        grouped: Dict[str, list[Dict[str, Any]]] = {}
        for event in events:
            grouped.setdefault(event[field], []).append(event)
        return {key: self._summarize_group(group) for key, group in grouped.items()}

    @staticmethod
    def _summarize_group(events: list[Dict[str, Any]]) -> Dict[str, Any]:
        durations = sorted(event["duration_ms"] for event in events)
        queue_waits = sorted(event["queue_wait_ms"] for event in events if event["queue_wait_ms"] is not None)
        successes = sum(event["status"] == "SUCCESS" for event in events)
        return {
            "completed_commands": len(events),
            "success_count": successes,
            "failure_count": len(events) - successes,
            "success_rate": round(successes / len(events), 4),
            "failure_rate": round((len(events) - successes) / len(events), 4),
            "error_rate_percent": round((len(events) - successes) / len(events) * 100.0, 2),
            "latency_ms": MetricsService._distribution(durations),
            "queue_wait_ms": MetricsService._distribution(queue_waits),
        }

    @staticmethod
    def _distribution(values: list[float]) -> Dict[str, float]:
        if not values:
            return {"average": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0}
        ordered = sorted(values)
        return {
            "average": round(sum(ordered) / len(ordered), 2),
            "p50": round(MetricsService._percentile(ordered, 0.50), 2),
            "p95": round(MetricsService._percentile(ordered, 0.95), 2),
            "p99": round(MetricsService._percentile(ordered, 0.99), 2),
        }

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float:
        index = (len(values) - 1) * percentile
        lower = int(index)
        upper = min(lower + 1, len(values) - 1)
        return values[lower] + (values[upper] - values[lower]) * (index - lower)

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._events and self._events[0]["completed_at"] < cutoff:
            evicted = self._events.popleft()
            self._recorded_command_ids.discard(evicted["command_id"])

    @staticmethod
    def _transition_time(record: Any, stage: str) -> Optional[float]:
        for transition in record.history:
            if transition.to_stage.value == stage:
                return transition.timestamp
        return None


metrics_service = MetricsService()