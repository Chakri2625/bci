import time
from collections import defaultdict
from contextlib import contextmanager
from typing import Dict, Any


class CommandProfiler:
    """
    Lightweight, production-safe latency profiler for command validation,
    routing, and end-to-end processing.
    """
    def __init__(self):
        self._metrics = defaultdict(lambda: {
            "count": 0,
            "total_time_us": 0.0,
            "min_time_us": float("inf"),
            "max_time_us": 0.0,
            "last_time_us": 0.0
        })

    def record(self, operation: str, elapsed_us: float):
        """Record an operation's latency in microseconds."""
        m = self._metrics[operation]
        m["count"] += 1
        m["total_time_us"] += elapsed_us
        m["last_time_us"] = elapsed_us
        if elapsed_us < m["min_time_us"]:
            m["min_time_us"] = elapsed_us
        if elapsed_us > m["max_time_us"]:
            m["max_time_us"] = elapsed_us

    @contextmanager
    def time_operation(self, operation: str):
        """Context manager for zero-overhead block timing."""
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_us = (time.perf_counter() - start) * 1_000_000.0
            self.record(operation, elapsed_us)

    def get_metrics(self) -> Dict[str, Any]:
        """Return aggregated profiling statistics."""
        summary = {}
        for op, data in self._metrics.items():
            count = data["count"]
            avg_us = (data["total_time_us"] / count) if count > 0 else 0.0
            summary[op] = {
                "count": count,
                "avg_latency_us": round(avg_us, 2),
                "avg_latency_ms": round(avg_us / 1000.0, 4),
                "min_latency_us": round(data["min_time_us"], 2) if count > 0 else 0.0,
                "max_latency_us": round(data["max_time_us"], 2),
                "last_latency_us": round(data["last_time_us"], 2)
            }
        return summary

    def reset(self):
        """Reset all profiling metrics."""
        self._metrics.clear()


profiler = CommandProfiler()
