import time
import pytest
from core.managers.command_lock_manager import CommandLockManager, command_lock_manager
from core.orchestration.ecosystem_orchestrator import EcosystemOrchestrator
from core.state.state_manager import StateManager, state_manager
from core.managers.event_history import EventHistoryManager, event_history, EventType, EventStatus
from core.routing.rule_router import resolve_command, navigate_home, navigate_back


@pytest.fixture
def lock_manager():
    mgr = CommandLockManager(default_duration=4.0)
    mgr.reset_lock("default")
    return mgr


@pytest.fixture
def orchestrator():
    orch = EcosystemOrchestrator()
    state_manager.reset_state()
    command_lock_manager.reset_lock("default")
    return orch


# ============================================================================
# 1. BASE COMMAND LOCK MANAGER UNIT TESTS (9 REQUIREMENT TESTS)
# ============================================================================

def test_initial_command_lock_state(lock_manager):
    """Initial state must be unlocked, idle, and have no combinations."""
    state = lock_manager.get_lock_state("default")
    assert state["is_locked"] is False
    assert state["active_command"] is None
    assert state["combination"] is None
    assert state["has_second_command"] is False
    assert state["status"] == "IDLE"
    assert state["duration"] == 4.0


def test_command_1_accepted_starts_single_timer(lock_manager):
    """TEST 1: 1st accepted command (e.g., PUSH) starts single timer T0 and sets deadline T0 + duration."""
    t_start = time.time()
    res = lock_manager.acquire_or_combine("default", "PUSH")

    assert res["status"] == "accepted"
    assert res["action"] == "locked"
    assert res["command"] == "PUSH"
    assert res["is_combination"] is False
    assert res["timer_deadline"] is not None
    assert abs(res["timer_deadline"] - (t_start + 4.0)) < 0.2
    assert res["time_remaining"] > 3.8

    state = lock_manager.get_lock_state("default")
    assert state["is_locked"] is True
    assert state["active_command"] == "PUSH"
    assert state["has_second_command"] is False
    assert state["status"] == "LOCKED"


def test_command_2_forms_push_right_combination(lock_manager):
    """TEST 2: Command 1 PUSH -> Command 2 RIGHT -> forms PUSH_RIGHT. Timer deadline remains unchanged."""
    res1 = lock_manager.acquire_or_combine("default", "PUSH")
    d1 = res1["timer_deadline"]
    t0 = res1["timer_started"]

    time.sleep(0.05)
    res2 = lock_manager.acquire_or_combine("default", "RIGHT")

    assert res2["status"] == "accepted"
    assert res2["action"] == "combined"
    assert res2["command"] == "PUSH_RIGHT"
    assert res2["is_combination"] is True
    assert res2["has_second_command"] is True
    # Invariant: Timer is NOT reset, deadline is exactly d1
    assert res2["timer_deadline"] == d1
    assert res2["timer_started"] == t0

    state = lock_manager.get_lock_state("default")
    assert state["is_locked"] is True
    assert state["active_command"] == "PUSH_RIGHT"
    assert state["combination"] == "PUSH_RIGHT"
    assert state["has_second_command"] is True
    assert state["status"] == "COMBINATION"


def test_command_2_forms_push_left_combination(lock_manager):
    """TEST 3: Command 1 PUSH -> Command 2 LEFT -> forms PUSH_LEFT. Timer deadline remains unchanged."""
    res1 = lock_manager.acquire_or_combine("default", "PUSH")
    d1 = res1["timer_deadline"]

    time.sleep(0.05)
    res2 = lock_manager.acquire_or_combine("default", "LEFT")

    assert res2["status"] == "accepted"
    assert res2["action"] == "combined"
    assert res2["command"] == "PUSH_LEFT"
    assert res2["is_combination"] is True
    assert res2["has_second_command"] is True
    assert res2["timer_deadline"] == d1


def test_command_3_ignored_left_after_push_right(lock_manager):
    """TEST 4: PUSH -> RIGHT -> LEFT: 3rd command LEFT is ignored during lock."""
    lock_manager.acquire_or_combine("default", "PUSH")
    res2 = lock_manager.acquire_or_combine("default", "RIGHT")
    d_initial = res2["timer_deadline"]

    res3 = lock_manager.acquire_or_combine("default", "LEFT")
    assert res3["status"] == "ignored"
    assert res3["active_command"] == "PUSH_RIGHT"
    assert res3["has_second_command"] is True
    assert res3["timer_deadline"] == d_initial  # Deadline unchanged


def test_command_3_ignored_right_after_push_left(lock_manager):
    """TEST 5: PUSH -> LEFT -> RIGHT: 3rd command RIGHT is ignored during lock."""
    lock_manager.acquire_or_combine("default", "PUSH")
    res2 = lock_manager.acquire_or_combine("default", "LEFT")
    d_initial = res2["timer_deadline"]

    res3 = lock_manager.acquire_or_combine("default", "RIGHT")
    assert res3["status"] == "ignored"
    assert res3["active_command"] == "PUSH_LEFT"
    assert res3["has_second_command"] is True
    assert res3["timer_deadline"] == d_initial


def test_command_3_ignored_push_after_push_right(lock_manager):
    """TEST 6: PUSH -> RIGHT -> PUSH: 3rd command PUSH is ignored during lock."""
    lock_manager.acquire_or_combine("default", "PUSH")
    lock_manager.acquire_or_combine("default", "RIGHT")

    res3 = lock_manager.acquire_or_combine("default", "PUSH")
    assert res3["status"] == "ignored"
    assert res3["active_command"] == "PUSH_RIGHT"


def test_command_3_ignored_push_after_push_left(lock_manager):
    """TEST 7: PUSH -> LEFT -> PUSH: 3rd command PUSH is ignored during lock."""
    lock_manager.acquire_or_combine("default", "PUSH")
    lock_manager.acquire_or_combine("default", "LEFT")

    res3 = lock_manager.acquire_or_combine("default", "PUSH")
    assert res3["status"] == "ignored"
    assert res3["active_command"] == "PUSH_LEFT"


def test_command_3_ignored_pull_after_push_right(lock_manager):
    """TEST 8: PUSH -> RIGHT -> PULL: 3rd command PULL is ignored during lock."""
    lock_manager.acquire_or_combine("default", "PUSH")
    lock_manager.acquire_or_combine("default", "RIGHT")

    res3 = lock_manager.acquire_or_combine("default", "PULL")
    assert res3["status"] == "ignored"
    assert res3["active_command"] == "PUSH_RIGHT"


def test_command_3_ignored_pull_after_push_left(lock_manager):
    """TEST 9: PUSH -> LEFT -> PULL: 3rd command PULL is ignored during lock."""
    lock_manager.acquire_or_combine("default", "PUSH")
    lock_manager.acquire_or_combine("default", "LEFT")

    res3 = lock_manager.acquire_or_combine("default", "PULL")
    assert res3["status"] == "ignored"
    assert res3["active_command"] == "PUSH_LEFT"


def test_timer_strictly_non_resetting(lock_manager):
    """Verify timer deadline is never restarted across combinations or ignored commands."""
    res1 = lock_manager.acquire_or_combine("default", "PUSH")
    t0 = res1["timer_started"]
    d0 = res1["timer_deadline"]

    time.sleep(0.1)
    res2 = lock_manager.acquire_or_combine("default", "LEFT")
    assert res2["timer_started"] == t0
    assert res2["timer_deadline"] == d0
    assert res2["time_remaining"] < 4.0

    time.sleep(0.1)
    res3 = lock_manager.acquire_or_combine("default", "RIGHT")
    assert res3["timer_deadline"] == d0
    assert res3["time_remaining"] < res2["time_remaining"]


def test_timer_expiry_and_auto_unlock():
    """Verify timer unlocks automatically after duration expires."""
    short_lock = CommandLockManager(default_duration=0.15)
    short_lock.acquire_or_combine("default", "PUSH")
    state1 = short_lock.get_lock_state("default")
    assert state1["is_locked"] is True

    time.sleep(0.20)
    state2 = short_lock.get_lock_state("default")
    assert state2["is_locked"] is False
    assert state2["active_command"] is None
    assert state2["status"] == "IDLE"


def test_stop_command_bypasses_and_clears_lock(lock_manager):
    """Explicit reset immediately clears lock regardless of timer."""
    lock_manager.acquire_or_combine("default", "PUSH")
    lock_manager.acquire_or_combine("default", "LEFT")
    assert lock_manager.get_lock_state("default")["is_locked"] is True

    lock_manager.reset_lock("default")
    assert lock_manager.get_lock_state("default")["is_locked"] is False


# ============================================================================
# 2. FULL ORCHESTRATOR INTEGRATION & NAVIGATION TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_orchestrator_home_navigation_push_left(orchestrator):
    """Verify PUSH+LEFT navigates to HOME (Level 1 / Domain Selection) from Level 2."""
    # Step 1: Navigate to Level 2 (e.g. Python Domain)
    r1 = await orchestrator.process_command("PUSH")
    assert r1["state"]["current_level"] == 2
    assert r1["state"]["active_domain"] == "PYTHON"

    # Reset lock between discrete phase tests
    command_lock_manager.reset_lock("default")

    # Step 2: Send combination PUSH_LEFT
    r_home = await orchestrator.process_command("PUSH_LEFT")
    assert r_home["status"] == "success"
    assert r_home["state"]["current_level"] == 1
    assert r_home["state"]["active_domain"] is None
    assert r_home["state"]["active_app"] is None


@pytest.mark.asyncio
async def test_orchestrator_back_navigation_push_right(orchestrator):
    """Verify PUSH+RIGHT navigates BACK / PREVIOUS DOMAIN from Level 3 to Level 2."""
    # Navigate: Level 1 -> Level 2 (PYTHON)
    await orchestrator.process_command("PUSH")
    command_lock_manager.reset_lock("default")

    # Level 2 -> Level 3 (YOUTUBE)
    await orchestrator.process_command("PUSH")
    st = state_manager.get_state("default")
    assert st["current_level"] == 3
    assert st["active_app"] == "YOUTUBE"
    command_lock_manager.reset_lock("default")

    # Send PUSH_RIGHT
    r_back = await orchestrator.process_command("PUSH_RIGHT")
    assert r_back["status"] == "success"
    assert r_back["state"]["current_level"] == 2
    assert r_back["state"]["active_domain"] == "PYTHON"
    assert r_back["state"]["active_app"] is None


@pytest.mark.asyncio
async def test_orchestrator_sequential_lock_combination(orchestrator):
    """Test full sequential workflow: PUSH -> LEFT forms combination and executes HOME."""
    # Navigate to Level 2
    await orchestrator.process_command("PUSH")
    command_lock_manager.reset_lock("default")
    assert state_manager.get_state("default")["current_level"] == 2

    # Step A: 1st command PUSH locks
    res_a = await orchestrator.process_command("PUSH")
    assert res_a["lock"]["is_locked"] is True
    assert res_a["lock"]["active_command"] == "PUSH"

    # Step B: 2nd command LEFT forms combination PUSH_LEFT -> triggers HOME
    res_b = await orchestrator.process_command("LEFT")
    assert res_b["status"] == "success"
    assert res_b["lock"]["combination"] == "PUSH_LEFT"
    assert res_b["state"]["current_level"] == 1


@pytest.mark.asyncio
async def test_orchestrator_3rd_command_ignored_prevents_actuator_dispatch(orchestrator):
    """Test that a 3rd command during active lock returns ignored and never reaches actuators."""
    command_lock_manager.reset_lock("default")

    # Command 1
    await orchestrator.process_command("PUSH")
    # Command 2
    await orchestrator.process_command("RIGHT")

    # Command 3 (Ignored)
    res_3 = await orchestrator.process_command("LEFT")
    assert res_3["status"] == "ignored"
    assert "ignored" in res_3["reason"].lower()
    assert res_3["resolved"] is None or res_3["resolved"].get("type") == "no_action"


# ============================================================================
# 3. THRESHOLD & SENSITIVITY DYNAMIC TUNING TESTS
# ============================================================================

def test_tuning_config_dynamic_update(lock_manager):
    """Verify updating default duration changes config live without altering active running lock."""
    res1 = lock_manager.acquire_or_combine("default", "PUSH", duration=4.0)
    d0 = res1["timer_deadline"]

    # Update default duration for future locks
    lock_manager.set_default_duration(6.0)
    assert lock_manager.get_default_duration() == 6.0

    # Active running lock deadline must NOT change
    state = lock_manager.get_lock_state("default")
    assert state["timer_deadline"] == d0
