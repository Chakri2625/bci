import pytest
import asyncio
from unittest.mock import AsyncMock, patch

from core.managers.domain_handler import DomainHandler, domain_handler
from core.exceptions import (
    DomainError,
    DomainExecutionError,
    DomainTimeoutError,
    DomainCommunicationError,
)
from core.orchestration.ecosystem_orchestrator import ecosystem_orchestrator
from core.state.state_manager import state_manager
from core.managers.lifecycle_tracker import lifecycle_tracker


@pytest.mark.asyncio
async def test_domain_handler_success():
    """Verify DomainHandler executes a domain command and returns successful result."""
    handler = DomainHandler()

    async def mock_func(plugin_id, command, payload):
        return {"status": "ok", "plugin": plugin_id, "action": command}

    updates = []

    def updater(attempt, status, reason):
        updates.append((attempt, status, reason))

    res = await handler.handle(
        plugin_id="iot",
        command="turn_on",
        payload={"power": 1},
        session="test_sess_1",
        state_updater_cb=updater,
        func=mock_func,
    )

    assert res["status"] == "SUCCESS"
    assert res["result"]["action"] == "turn_on"
    assert res["attempt"] == 1
    # Check that the orchestrator's state_updater_cb was called
    assert len(updates) >= 2
    assert updates[0] == (1, "READY", None)
    assert updates[1] == (1, "SUCCESS", None)


@pytest.mark.asyncio
async def test_domain_handler_retry_with_state_updater():
    """Verify DomainHandler forwards state_updater_cb on temporary failure retries."""
    handler = DomainHandler()
    call_count = 0

    async def mock_func(plugin_id, command, payload):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("connection loss")
        return {"status": "ok", "recovered": True}

    updates = []

    def updater(attempt, status, reason):
        updates.append((attempt, status, reason))

    res = await handler.handle(
        plugin_id="iot",
        command="read_sensor",
        payload={},
        session="test_sess_retry",
        state_updater_cb=updater,
        func=mock_func,
    )

    assert res["status"] == "SUCCESS"
    assert res["attempt"] == 2
    assert call_count == 2
    # Verify retry updates occurred in state_updater_cb
    statuses = [u[1] for u in updates]
    assert "READY" in statuses
    assert "RETRYING" in statuses
    assert "SUCCESS" in statuses


@pytest.mark.asyncio
async def test_domain_handler_domain_error_isolation():
    """Verify DomainHandler catches DomainError, isolates failure, and returns controlled response."""
    handler = DomainHandler()

    async def mock_func(plugin_id, command, payload):
        raise DomainExecutionError("Hardware register write fault")

    updates = []

    def updater(attempt, status, reason):
        updates.append((attempt, status, reason))

    res = await handler.handle(
        plugin_id="embedded",
        command="set_pwm",
        payload={"pin": 4},
        session="test_sess_domain_err",
        state_updater_cb=updater,
        func=mock_func,
    )

    assert res["status"] == "FAILED"
    assert "Hardware register write fault" in res["reason"]
    assert res["result"]["status"] == "failed"
    # Ensure application did not crash and failure state was reported
    statuses = [u[1] for u in updates]
    assert "FAILED" in statuses


@pytest.mark.asyncio
async def test_domain_handler_unexpected_exception_isolation():
    """Verify DomainHandler catches unexpected arbitrary exceptions and returns controlled failure."""
    handler = DomainHandler()

    async def mock_func(plugin_id, command, payload):
        raise RuntimeError("Fatal memory segmentation or null pointer")

    updates = []

    def updater(attempt, status, reason):
        updates.append((attempt, status, reason))

    res = await handler.handle(
        plugin_id="python",
        command="calculate",
        payload={},
        session="test_sess_unexpected",
        state_updater_cb=updater,
        func=mock_func,
    )

    assert res["status"] == "FAILED"
    assert "Fatal memory segmentation" in res["reason"]
    assert res["result"]["status"] == "failed"


@pytest.mark.asyncio
async def test_orchestrator_integration_preserves_lifecycle_and_state():
    """Verify EcosystemOrchestrator uses DomainHandler while preserving locking, lifecycle, and state updates."""
    session = "test_orch_dh_session"
    state_manager.update_state(session, {
        "current_level": 3,
        "active_domain": "IOT",
        "active_app": "LIGHT"
    })

    with patch("core.managers.domain_handler.domain_handler.handle") as mock_handle:
        mock_handle.return_value = {
            "status": "SUCCESS",
            "attempt": 1,
            "result": {"status": "success", "action": "Left_light_on"}
        }

        # Execute a command that resolves to an action
        res = await ecosystem_orchestrator.process_command("RIGHT", session=session, device_id="dev_100")

        # Validate response structure is fully preserved
        assert "status" in res
        assert "executed" in res
        assert "lifecycle" in res
        assert "lifecycle_stage" in res
        assert "state" in res
        assert "validation" in res

        # Validate mock_handle received parameters including state_updater_cb
        assert mock_handle.called
        kwargs = mock_handle.call_args.kwargs
        assert kwargs.get("plugin_id") == "iot"
        assert kwargs.get("command") == "Left_light_on"
        assert kwargs.get("state_updater_cb") is not None
        assert kwargs.get("session") == session

        # Validate state updates were applied
        st = state_manager.get_state(session)
        assert st.get("last_resolved_action") == "Left_light_on"
        assert st.get("action_status") == "SUCCESS"


@pytest.mark.asyncio
async def test_orchestrator_failure_isolation_with_domain_handler():
    """Verify orchestrator failure isolation when DomainHandler encounters a failure."""
    session = "test_orch_fail_session"
    state_manager.update_state(session, {
        "current_level": 3,
        "active_domain": "IOT",
        "active_app": "LIGHT"
    })

    with patch("core.managers.domain_handler.domain_handler.handle") as mock_handle:
        mock_handle.return_value = {
            "status": "FAILED",
            "reason": "Zigbee coordinator unreachable",
            "error": "Zigbee coordinator unreachable",
            "attempt": 1,
            "result": {"status": "failed", "error": "Zigbee coordinator unreachable"}
        }

        res = await ecosystem_orchestrator.process_command("RIGHT", session=session, device_id="dev_100")

        assert res["executed"] is True
        assert res["action_result"]["status"] == "failed"
        assert "Zigbee coordinator unreachable" in res["action_result"]["error"]

        # Ensure state manager updated last_resolved_action and action_status
        st = state_manager.get_state(session)
        assert st.get("action_status") == "FAILED"
        assert st.get("last_resolved_action") == "Left_light_on"


@pytest.mark.asyncio
async def test_parallel_orchestrator_integration_with_domain_handler():
    """Verify parallel command execution delegates to DomainHandler and preserves state/lifecycle."""
    session = "test_orch_parallel_dh"
    state_manager.update_state(session, {
        "current_level": 3,
        "active_domain": "IOT",
        "active_app": "LIGHT"
    })

    with patch("core.managers.domain_handler.domain_handler.handle") as mock_handle:
        mock_handle.return_value = {
            "status": "SUCCESS",
            "attempt": 1,
            "result": {"status": "success", "action": "Left_light_on"}
        }

        # Send command list
        results = await ecosystem_orchestrator.process_command(["RIGHT"], session=session, device_id="dev_100")
        assert isinstance(results, list)
        assert len(results) == 1
        assert results[0]["executed"] is True
        assert results[0]["action_result"]["status"] == "success"
        assert mock_handle.called
        kwargs = mock_handle.call_args.kwargs
        assert kwargs.get("plugin_id") == "iot"
        assert kwargs.get("command") == "Left_light_on"
        assert kwargs.get("state_updater_cb") is not None
