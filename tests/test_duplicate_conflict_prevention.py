import time
import pytest
from core.validation.conflict_manager import ConflictManager, DecisionStatus, DecisionResult, conflict_manager
from core.state.state_manager import state_manager
from core.orchestration.ecosystem_orchestrator import ecosystem_orchestrator


@pytest.fixture(autouse=True)
def reset_conflict_state():
    conflict_manager.clear_cycle()
    state_manager.states.pop("default", None)
    yield
    conflict_manager.clear_cycle()
    state_manager.states.pop("default", None)


def test_normal_command_allowed():
    cm = ConflictManager()
    res = cm.evaluate(command="FORWARD", domain="EMBEDDED", app="RC_CAR")
    assert res.is_allowed is True
    assert res.status == DecisionStatus.ALLOWED
    assert res.reason is None


def test_exact_duplicate_in_active_cycle():
    cm = ConflictManager()
    # First command registered as active
    fp = cm.register_active(command="FORWARD", domain="EMBEDDED", app="RC_CAR")
    
    # Second identical command during active execution
    res = cm.evaluate(command="FORWARD", domain="EMBEDDED", app="RC_CAR")
    assert res.is_allowed is False
    assert res.status == DecisionStatus.DUPLICATE
    assert "currently executing" in res.reason or "Duplicate" in res.reason

    # Once released, evaluate is allowed
    cm.release_active(fp)
    # Wait out debounce window
    time.sleep(cm.debounce_interval + 0.05)
    res_after = cm.evaluate(command="FORWARD", domain="EMBEDDED", app="RC_CAR")
    assert res_after.is_allowed is True


def test_same_command_different_device_allowed():
    cm = ConflictManager()
    cm.register_active(command="TURN_ON", domain="IOT", device_id="light_living_room")

    # Same command on a different device should be allowed
    res = cm.evaluate(command="TURN_ON", domain="IOT", device_id="light_bedroom")
    assert res.is_allowed is True
    assert res.status == DecisionStatus.ALLOWED


def test_same_command_different_target_app_allowed():
    cm = ConflictManager()
    cm.register_active(command="search", domain="PYTHON", app="YOUTUBE")

    # Same command name in different app is allowed
    res = cm.evaluate(command="search", domain="PYTHON", app="CHROME")
    assert res.is_allowed is True
    assert res.status == DecisionStatus.ALLOWED


def test_same_command_different_parameters_allowed():
    cm = ConflictManager()
    cm.register_active(command="SET_BRIGHTNESS", domain="IOT", device_id="lamp", payload={"level": 50})

    # Different parameter is not a duplicate
    res = cm.evaluate(command="SET_BRIGHTNESS", domain="IOT", device_id="lamp", payload={"level": 100})
    assert res.is_allowed is True
    assert res.status == DecisionStatus.ALLOWED


def test_conflicting_opposing_directional_commands():
    cm = ConflictManager()
    cm.register_active(command="LEFT", domain="EMBEDDED", app="RC_CAR")

    # Contradictory opposing command RIGHT on the same target
    res = cm.evaluate(command="RIGHT", domain="EMBEDDED", app="RC_CAR")
    assert res.is_allowed is False
    assert res.status == DecisionStatus.CONFLICT
    assert "LEFT" in res.conflicts and "RIGHT" in res.conflicts


def test_stop_vs_movement_priority():
    cm = ConflictManager()
    # 1. When movement is active, STOP command overrides/allowed
    cm.register_active(command="FORWARD", domain="EMBEDDED", app="RC_CAR", priority=1)
    res_stop = cm.evaluate(command="STOP", domain="EMBEDDED", app="RC_CAR")
    assert res_stop.is_allowed is True

    # 2. When STOP is active, a movement command is rejected due to STOP priority
    cm.clear_cycle()
    cm.register_active(command="STOP", domain="EMBEDDED", app="RC_CAR", priority=10)
    res_move = cm.evaluate(command="FORWARD", domain="EMBEDDED", app="RC_CAR", priority=1)
    assert res_move.is_allowed is False
    assert res_move.status == DecisionStatus.CONFLICT
    assert "STOP" in res_move.conflicts


def test_priority_resolution_allows_higher_priority():
    cm = ConflictManager()
    # Active command with priority 1
    cm.register_active(command="PUSH", domain="PYTHON", app="YOUTUBE", priority=1)

    # Conflicting PULL command with higher priority (e.g. 5) is allowed to override
    res = cm.evaluate(command="PULL", domain="PYTHON", app="YOUTUBE", priority=5)
    assert res.is_allowed is True

    # Conflicting command with lower/equal priority is rejected
    res_low = cm.evaluate(command="PULL", domain="PYTHON", app="YOUTUBE", priority=1)
    assert res_low.is_allowed is False
    assert res_low.status == DecisionStatus.CONFLICT


def test_new_execution_cycle_allows_repeated_command():
    cm = ConflictManager(debounce_interval=0.1)
    fp = cm.register_active(command="toggle_play_pause", domain="PYTHON", app="YOUTUBE")
    cm.release_active(fp)

    # Wait for execution cycle / debounce window to complete
    time.sleep(0.12)

    res = cm.evaluate(command="toggle_play_pause", domain="PYTHON", app="YOUTUBE")
    assert res.is_allowed is True
    assert res.status == DecisionStatus.ALLOWED


@pytest.mark.asyncio
async def test_orchestrator_duplicate_prevention_integration():
    # Setup state to level 3 YouTube
    state_manager.update_state("default", {
        "current_level": 3,
        "active_domain": "PYTHON",
        "active_app": "YOUTUBE"
    })

    # Simulate active execution of previous_video
    fp = conflict_manager.register_active(command="previous_video", domain="PYTHON", app="YOUTUBE")

    # Send duplicate PUSH command (which maps to previous_video)
    res = await ecosystem_orchestrator.process_command("PUSH", session="default")
    assert res["status"] == "duplicate"
    assert res["executed"] is False
    assert "Duplicate" in res["reason"] or "executing" in res["reason"]

    # Release active command
    conflict_manager.release_active(fp)
    time.sleep(0.6)

    # Now sending PUSH succeeds
    res_allowed = await ecosystem_orchestrator.process_command("PUSH", session="default")
    assert res_allowed["status"] == "success"
    assert res_allowed["executed"] is True
