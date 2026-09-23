import pytest
import asyncio
import threading
import time
from core.state.state_manager import StateManager, state_manager
from core.orchestration.ecosystem_orchestrator import ecosystem_orchestrator
from core.managers.command_lock_manager import command_lock_manager


@pytest.fixture(autouse=True)
def reset_system_state():
    """Reset state before and after each test."""
    state_manager.reset_state()
    command_lock_manager.reset()
    yield
    state_manager.reset_state()
    command_lock_manager.reset()


def test_1_initial_state_creation():
    """Test 1: Initial state creation and structure validation."""
    mgr = StateManager()
    state = mgr.get_state("default")
    assert state is not None
    assert state["current_level"] == 1
    assert state["active_domain"] is None
    assert state["active_app"] is None
    assert state["command_history"] == []
    assert state["sequence_validation"]["status"] == "READY"

    sys_state = mgr.get_system_state()
    assert sys_state["system_status"] == "IDLE"
    assert sys_state["execution_state"] == "IDLE"
    assert sys_state["active_tasks_count"] == 0
    assert "metrics" in sys_state
    assert sys_state["metrics"]["total_commands"] == 0


def test_2_system_state_update():
    """Test 2: System-level state updates and metric synchronization."""
    mgr = StateManager()
    mgr.update_system_state({
        "status": "RUNNING",
        "execution_state": "EXECUTING",
        "metrics": {"total_commands": 5, "successful": 4}
    })
    sys_state = mgr.get_system_state()
    assert sys_state["system_status"] == "RUNNING"
    assert sys_state["execution_state"] == "EXECUTING"
    assert sys_state["metrics"]["total_commands"] == 5
    assert sys_state["metrics"]["successful"] == 4


def test_3_domain_state_update():
    """Test 3: Domain state updates across all domains."""
    mgr = StateManager()
    for dom in ["BCI", "IOT", "ROBOTICS", "DESKTOP", "MEDIA", "AIML"]:
        dom_state = mgr.get_domain_state(dom)
        assert dom_state is not None
        assert dom_state["status"] == "READY"

    mgr.update_domain_state("DESKTOP", {"status": "BUSY", "active_app": "NOTEPAD", "last_action": "OPEN_NOTEPAD"})
    desktop_state = mgr.get_domain_state("DESKTOP")
    assert desktop_state["status"] == "BUSY"
    assert desktop_state["active_app"] == "NOTEPAD"
    assert desktop_state["last_action"] == "OPEN_NOTEPAD"


def test_4_active_command_registration():
    """Test 4: Registering active in-flight commands."""
    mgr = StateManager()
    cmd_info = mgr.register_active_command(
        command_id="cmd_test_01",
        command="PLAY",
        domain="MEDIA",
        app="YOUTUBE",
        session="default"
    )
    assert cmd_info["command_id"] == "cmd_test_01"
    assert cmd_info["status"] == "RUNNING"
    assert cmd_info["domain"] == "MEDIA"

    active_cmds = mgr.get_active_commands("default")
    assert len(active_cmds) == 1
    assert active_cmds[0]["command_id"] == "cmd_test_01"

    sys_state = mgr.get_system_state()
    assert sys_state["active_tasks_count"] == 1
    assert sys_state["execution_state"] == "EXECUTING"


def test_5_command_state_update():
    """Test 5: Updating active command state through its lifecycle."""
    mgr = StateManager()
    mgr.register_active_command("cmd_test_02", "VOLUME_UP", domain="MEDIA", app="YOUTUBE")
    
    updated = mgr.update_command_state("cmd_test_02", status="EXECUTING", result={"vol": 80})
    assert updated["status"] == "EXECUTING"
    assert updated["result"] == {"vol": 80}


def test_6_command_completion():
    """Test 6: Completing and removing an active command."""
    mgr = StateManager()
    mgr.register_active_command("cmd_test_03", "TOGGLE_PLAY_PAUSE", domain="MEDIA", app="YOUTUBE")
    mgr.update_command_state("cmd_test_03", status="SUCCESS", result={"status": "success"})
    
    sys_state = mgr.get_system_state()
    assert sys_state["metrics"]["successful"] == 1

    removed = mgr.remove_active_command("cmd_test_03")
    assert removed is True
    assert len(mgr.get_active_commands()) == 0
    assert mgr.get_system_state()["active_tasks_count"] == 0


def test_7_command_failure():
    """Test 7: Recording command failure state and error tracking."""
    mgr = StateManager()
    mgr.register_active_command("cmd_test_04", "INVALID_ACTION", domain="DESKTOP", app="CHROME")
    mgr.update_command_state("cmd_test_04", status="FAILED", error="Application not running")
    
    sys_state = mgr.get_system_state()
    assert sys_state["metrics"]["failed"] == 1
    assert sys_state["execution_state"] == "FAILED"

    mgr.remove_active_command("cmd_test_04")
    assert len(mgr.get_active_commands()) == 0


def test_8_command_cancellation():
    """Test 8: Recording command cancellation state."""
    mgr = StateManager()
    mgr.register_active_command("cmd_test_05", "LONG_TASK", domain="DESKTOP", app="NOTEPAD")
    mgr.update_command_state("cmd_test_05", status="CANCELLED", error="Task cancelled by user")
    
    sys_state = mgr.get_system_state()
    assert sys_state["metrics"]["cancelled"] == 1
    assert sys_state["execution_state"] == "CANCELLED"

    mgr.remove_active_command("cmd_test_05")
    assert len(mgr.get_active_commands()) == 0


def test_9_timeout_state_handling():
    """Test 9: Recording timeout state and cleanup."""
    mgr = StateManager()
    mgr.register_active_command("cmd_test_06", "IOT_ACTION", domain="IOT", app="RELAY_1")
    mgr.update_command_state("cmd_test_06", status="TIMED_OUT", error="Device ACK timeout exceeded")
    
    sys_state = mgr.get_system_state()
    assert sys_state["metrics"]["timed_out"] == 1
    assert sys_state["execution_state"] == "TIMED_OUT"

    mgr.remove_active_command("cmd_test_06")
    assert len(mgr.get_active_commands()) == 0


def test_10_state_reset():
    """Test 10: Full and session-specific state reset restores clean state."""
    mgr = StateManager()
    mgr.register_active_command("cmd_test_07", "PUSH", session="sess_1")
    mgr.update_state("sess_1", {"current_level": 3, "active_domain": "MEDIA", "active_app": "YOUTUBE"})
    
    # Session reset
    res = mgr.reset_state("sess_1")
    assert res["current_level"] == 1
    assert res["active_domain"] is None
    assert len(mgr.get_active_commands("sess_1")) == 0

    # Global reset
    mgr.register_active_command("cmd_test_08", "PULL", session="default")
    mgr.reset_state()
    assert mgr.get_system_state()["active_tasks_count"] == 0
    assert mgr.get_system_state()["execution_state"] == "RESET"


def test_11_multiple_simultaneous_commands():
    """Test 11: Tracking multiple simultaneous in-flight commands."""
    mgr = StateManager()
    mgr.register_active_command("cmd_multi_1", "OPEN_NOTEPAD", domain="PYTHON", app="NOTEPAD")
    mgr.register_active_command("cmd_multi_2", "PLAY", domain="MEDIA", app="YOUTUBE")
    mgr.register_active_command("cmd_multi_3", "FORWARD", domain="EMBEDDED", app="RC_CAR")

    active = mgr.get_active_commands()
    assert len(active) == 3
    assert mgr.get_system_state()["active_tasks_count"] == 3

    mgr.remove_active_command("cmd_multi_1")
    assert len(mgr.get_active_commands()) == 2
    mgr.remove_active_command("cmd_multi_2")
    mgr.remove_active_command("cmd_multi_3")
    assert len(mgr.get_active_commands()) == 0


def test_12_concurrent_state_updates():
    """Test 12: Thread-safe concurrent state updates under multi-threaded load."""
    mgr = StateManager()
    num_threads = 10
    updates_per_thread = 20

    def worker(tid):
        session = f"session_{tid}"
        for i in range(updates_per_thread):
            cmd_id = f"cmd_{tid}_{i}"
            mgr.add_command(session, f"CMD_{i}")
            mgr.register_active_command(cmd_id, f"CMD_{i}", session=session)
            mgr.update_state(session, {"current_level": (i % 3) + 1})
            mgr.update_command_state(cmd_id, status="SUCCESS")
            mgr.remove_active_command(cmd_id, session=session)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    sys_state = mgr.get_system_state()
    assert sys_state["metrics"]["total_commands"] == num_threads * updates_per_thread
    assert sys_state["metrics"]["successful"] == num_threads * updates_per_thread
    assert sys_state["active_tasks_count"] == 0


def test_13_state_consistency_after_execution():
    """Test 13: State consistency across command history and sequence validation."""
    mgr = StateManager()
    for cmd in ["PUSH", "PULL", "LEFT", "RIGHT"]:
        mgr.add_command("default", cmd)

    state = mgr.get_state("default")
    assert state["last_command"] == "RIGHT"
    assert state["command_history"] == ["PUSH", "PULL", "LEFT", "RIGHT"]
    assert mgr.get_system_state()["metrics"]["total_commands"] == 4


@pytest.mark.asyncio
async def test_14_orchestrator_integration():
    """Test 14: Real end-to-end integration with EcosystemOrchestrator."""
    state_manager.reset_state("default")
    
    # Transition to Desktop domain (Level 1 -> Level 2)
    res1 = await ecosystem_orchestrator.process_command("PUSH", session="default")
    assert res1["status"] == "success"
    assert res1["resolved"]["type"] == "transition"
    
    curr_state = state_manager.get_state("default")
    assert curr_state["current_level"] == 2
    assert curr_state["active_domain"] == "PYTHON"

    # Verify domain state synchronized
    dom_state = state_manager.get_domain_state("DESKTOP", session="default")
    assert dom_state["session_active"] is True
    assert dom_state["current_level"] == 2


@pytest.mark.asyncio
async def test_15_end_to_end_pipeline_flow():
    """Test 15: Full command flow through validation, routing, execution, and state recording."""
    state_manager.reset_state("test_sess")
    
    # 1. Level 1 -> 2: Select Desktop (PUSH)
    await ecosystem_orchestrator.process_command("PUSH", session="test_sess")
    command_lock_manager.reset("test_sess")
    # 2. Level 2 -> 3: Select Notepad (LEFT)
    await ecosystem_orchestrator.process_command("LEFT", session="test_sess")

    st = state_manager.get_state("test_sess")
    assert st["current_level"] == 3
    assert st["active_domain"] == "PYTHON"
    assert st["active_app"] == "NOTEPAD"
    assert st["last_command"] == "LEFT"
    assert len(st["command_history"]) == 2

    # Verify system state reflects completed transitions
    sys_state = state_manager.get_system_state()
    assert sys_state["metrics"]["total_commands"] >= 2
    assert sys_state["active_tasks_count"] == 0


# -------------------------------------------------------------
# Tests for WebSocket STATE_UPDATE broadcast wiring (Sprint 11 Day 2)
# -------------------------------------------------------------

def test_16_update_system_state_sync_no_loop_safe():
    """Test 16: update_system_state() works correctly in a sync context (no event loop).

    Verifies the safe no-op path when no asyncio event loop is running:
    - Return value reflects updated state.
    - No exception is raised.
    - State changes are durable (readable via get_system_state).
    """
    mgr = StateManager()
    result = mgr.update_system_state({
        "status": "RUNNING",
        "execution_state": "EXECUTING",
        "metrics": {"total_commands": 3},
    })
    # Return value is updated snapshot
    assert result["system_status"] == "RUNNING"
    assert result["execution_state"] == "EXECUTING"
    assert result["metrics"]["total_commands"] == 3

    # Durable in internal state
    sys_state = mgr.get_system_state()
    assert sys_state["system_status"] == "RUNNING"
    assert sys_state["execution_state"] == "EXECUTING"


@pytest.mark.asyncio
async def test_17_update_system_state_schedules_ws_broadcast():
    """Test 17: update_system_state() schedules broadcast_state_update() on a running event loop.

    Uses unittest.mock to patch websocket_server.broadcast_state_update and
    verifies loop.create_task() was invoked with it — without needing real WebSocket clients.
    """
    from unittest.mock import AsyncMock, patch, MagicMock
    import asyncio

    mgr = StateManager()

    # Create a coroutine the mock will return so create_task has a real awaitable
    broadcast_mock = AsyncMock(return_value=None)

    with patch(
        "core.communication.websocket_server.websocket_server.broadcast_state_update",
        new=broadcast_mock,
    ):
        mgr.update_system_state({
            "status": "RUNNING",
            "execution_state": "EXECUTING",
        })

        # Yield control so the scheduled task can execute
        await asyncio.sleep(0)

    # broadcast_state_update should have been called once with the correct args
    broadcast_mock.assert_called_once()
    call_kwargs = broadcast_mock.call_args.kwargs
    assert call_kwargs["domain"] == "CORE"
    assert call_kwargs["session_id"] == mgr.active_session_id
    assert call_kwargs["state_payload"]["system_status"] == "RUNNING"
    assert call_kwargs["state_payload"]["execution_state"] == "EXECUTING"


@pytest.mark.asyncio
async def test_18_broadcast_payload_reflects_updated_values():
    """Test 18: The snapshot passed to broadcast_state_update contains the values
    that were just written — not stale pre-update state.

    Guards against a potential race where the snapshot is captured before
    mutations are applied.
    """
    from unittest.mock import AsyncMock, patch
    import asyncio

    mgr = StateManager()

    captured_payloads = []

    async def capture_broadcast(state_payload, session_id, domain):
        captured_payloads.append(dict(state_payload))

    with patch(
        "core.communication.websocket_server.websocket_server.broadcast_state_update",
        new=capture_broadcast,
    ):
        mgr.update_system_state({
            "system_status": "DEGRADED",
            "execution_state": "FAILED",
            "metrics": {"failed": 7},
        })
        await asyncio.sleep(0)

    assert len(captured_payloads) == 1
    payload = captured_payloads[0]
    assert payload["system_status"] == "DEGRADED"
    assert payload["execution_state"] == "FAILED"
    assert payload["metrics"]["failed"] == 7

