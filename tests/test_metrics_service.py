import pytest

from core.managers.lifecycle_tracker import CommandLifecycleTracker
from core.metrics import MetricsService, metrics_service


def test_metrics_collect_terminal_command_performance():
    metrics_service.reset()
    tracker = CommandLifecycleTracker()
    record = tracker.create_command("COMMAND_A", domain="ROUTE_A")
    tracker.track_queued(record.command_id)
    tracker.track_execution_started(record.command_id)
    tracker.track_success(record.command_id)

    stats = metrics_service.get_stats()

    assert stats["completed_commands"] == 1
    assert stats["success_count"] == 1
    assert stats["failure_count"] == 0
    assert stats["latency_ms"]["p50"] >= 0
    assert stats["queue_wait_ms"]["p50"] >= 0
    assert stats["by_command_type"]["COMMAND_A"]["completed_commands"] == 1
    assert stats["by_route"]["ROUTE_A"]["completed_commands"] == 1


def test_metrics_deduplicate_and_classify_failures():
    metrics = MetricsService()
    tracker = CommandLifecycleTracker()
    record = tracker.create_command("COMMAND_B", metadata={"route": "ROUTE_B"})
    tracker.track_timeout(record.command_id, reason="deadline")

    assert metrics.record_completion(record) is True
    assert metrics.record_completion(record) is False
    stats = metrics.getStats(command_type="COMMAND_B", route="ROUTE_B")
    assert stats["completed_commands"] == 1
    assert stats["success_rate"] == 0.0
    assert stats["failure_rate"] == 1.0


def test_metrics_use_fixed_window_throughput_and_error_percentage():
    metrics = MetricsService(window_seconds=60)
    tracker = CommandLifecycleTracker()

    success = tracker.create_command("COMMAND_OK")
    tracker.track_success(success.command_id)
    failure = tracker.create_command("COMMAND_FAIL")
    tracker.track_failure(failure.command_id, error="failed")
    metrics.record_completion(success)
    metrics.record_completion(failure)

    stats = metrics.get_stats()

    assert stats["window_seconds"] == 60
    assert stats["throughput"]["commands_per_second"] == pytest.approx(2 / 60, abs=0.00005)
    assert stats["throughput"]["commands_per_minute"] == 2.0
    assert stats["error_rate_percent"] == 50.0