import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import time
import pytest
from core.validation.conflict_manager import ConflictManager, DecisionStatus, DecisionResult, conflict_manager
from core.state.state_manager import state_manager
from core.orchestration.ecosystem_orchestrator import ecosystem_orchestrator
from core.orchestration.parallel_engine import parallel_engine
from core.orchestration.timing_controller import timing_controller, DependentAction, ActionLifecycleState
from core.managers.resource_lock_manager import resource_lock_manager
from core.managers.priority_manager import PriorityLevel, PriorityManager, get_command_priority


@pytest.fixture(autouse=True)
def reset_system_state():
    conflict_manager.clear_cycle()
    resource_lock_manager.clear()
    state_manager.states.pop("default", None)
    yield
    conflict_manager.clear_cycle()
    resource_lock_manager.clear()
    state_manager.states.pop("default", None)


# ---------------------------------------------------------------------------
# Test 1 — Independent Desktop Commands
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_1_independent_desktop_commands():
    """
    Independent Desktop commands (e.g., Notepad and Chrome) target different resources.
    They must NOT conflict and must be allowed to execute concurrently in parallel.
    """
    executed = []

    async def run_notepad():
        await asyncio.sleep(0.02)
        executed.append("notepad")
        return {"status": "success", "app": "NOTEPAD"}

    async def run_chrome():
        await asyncio.sleep(0.02)
        executed.append("chrome")
        return {"status": "success", "app": "CHROME"}

    executables = [
        {
            "cmd": "PUSH",
            "resolution": {"type": "action", "domain": "PYTHON", "app": "NOTEPAD", "action": "open_notepad"},
            "payload": {"domain": "PYTHON", "app": "NOTEPAD"},
            "execute_func": run_notepad,
            "base_result": {"status": "success"}
        },
        {
            "cmd": "PULL",
            "resolution": {"type": "action", "domain": "PYTHON", "app": "CHROME", "action": "open_predefined_article"},
            "payload": {"domain": "PYTHON", "app": "CHROME"},
            "execute_func": run_chrome,
            "base_result": {"status": "success"}
        }
    ]

    results = await parallel_engine.execute_concurrently(executables)
    assert len(results) == 2
    assert all(r["status"] == "SUCCESS" for r in results)
    assert "notepad" in executed and "chrome" in executed


# ---------------------------------------------------------------------------
# Test 2 — Independent Media Commands
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_2_independent_media_commands():
    """
    Independent Media commands (e.g., YouTube video search and JioSaavn audio search)
    operate on independent media providers and execute without cross-domain conflict.
    """
    executed = []

    async def run_yt_search():
        await asyncio.sleep(0.02)
        executed.append("yt_search")
        return {"status": "success", "app": "YOUTUBE"}

    async def run_js_search():
        await asyncio.sleep(0.02)
        executed.append("js_search")
        return {"status": "success", "app": "JIOSAAVN"}

    executables = [
        {
            "cmd": "RIGHT",
            "resolution": {"type": "action", "domain": "MEDIA", "app": "YOUTUBE", "action": "SEARCH"},
            "payload": {"domain": "MEDIA", "app": "YOUTUBE"},
            "execute_func": run_yt_search,
            "base_result": {"status": "success"}
        },
        {
            "cmd": "RIGHT",
            "resolution": {"type": "action", "domain": "MEDIA", "app": "JIOSAAVN", "action": "SEARCH"},
            "payload": {"domain": "MEDIA", "app": "JIOSAAVN"},
            "execute_func": run_js_search,
            "base_result": {"status": "success"}
        }
    ]

    results = await parallel_engine.execute_concurrently(executables)
    assert len(results) == 2
    assert all(r["status"] == "SUCCESS" for r in results)
    assert "yt_search" in executed and "js_search" in executed


# ---------------------------------------------------------------------------
# Test 3 — Desktop/Media Conflict Prevention
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_3_desktop_media_conflict_detected():
    """
    When a Desktop action targets YouTube (e.g. previous_video) and a Media action
    targets YouTube (e.g. NEXT / next_video), a conflict is detected on the shared
    YouTube resource, preventing unsafe simultaneous execution.
    """
    # 1. Direct ConflictManager evaluation
    cm = ConflictManager()
    fp = cm.register_active(command="PREVIOUS", domain="MEDIA", app="YOUTUBE")

    # Conflicting NEXT command on YouTube
    res = cm.evaluate(command="NEXT", domain="PYTHON", app="YOUTUBE")
    assert res.is_allowed is False
    assert res.status == DecisionStatus.CONFLICT
    assert "PREVIOUS" in res.conflicts and "NEXT" in res.conflicts

    # 2. Parallel engine conflict check
    executables = [
        {
            "cmd": "PUSH",
            "resolution": {"type": "action", "domain": "PYTHON", "app": "YOUTUBE", "action": "previous_video"},
            "payload": {"domain": "PYTHON", "app": "YOUTUBE"},
            "base_result": {"status": "success"}
        },
        {
            "cmd": "PULL",
            "resolution": {"type": "action", "domain": "MEDIA", "app": "YOUTUBE", "action": "NEXT"},
            "payload": {"domain": "MEDIA", "app": "YOUTUBE"},
            "base_result": {"status": "success"}
        }
    ]

    parallel_res = await parallel_engine.execute_concurrently(executables)
    assert any(r["status"] == "FAILED" and "Conflict" in r.get("error", "") for r in parallel_res)

    # 3. Orchestrator live conflict response
    state_manager.update_state("default", {
        "current_level": 3,
        "active_domain": "PYTHON",
        "active_app": "YOUTUBE"
    })
    # Active YouTube execution already registered above with `fp`
    conflict_manager.register_active(command="PREVIOUS", domain="MEDIA", app="YOUTUBE")
    orch_res = await ecosystem_orchestrator.process_command("PULL", session="default")
    assert orch_res["status"] == "conflict"
    assert orch_res["executed"] is False
    assert "Conflict" in orch_res["conflict"]


# ---------------------------------------------------------------------------
# Test 4 — Dependency-Based Conflict / Timing Controls
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_4_dependency_based_workflow():
    """
    Desktop and Media actions chained in a dependent workflow must respect
    dependency ordering and satisfy conditions before executing downstream actions.
    """
    execution_order = []

    async def desktop_open(action):
        await asyncio.sleep(0.01)
        execution_order.append("open_notepad")
        return {"status": "success"}

    async def media_play(action):
        await asyncio.sleep(0.01)
        execution_order.append("play_music")
        return {"status": "success"}

    actions = [
        DependentAction(
            id="step_1",
            command="open_notepad",
            domain="PYTHON",
            app="NOTEPAD"
        ),
        DependentAction(
            id="step_2",
            command="PLAY",
            domain="MEDIA",
            app="YOUTUBE",
            depends_on=["step_1"]
        )
    ]

    async def custom_executor(act):
        if act.id == "step_1":
            return await desktop_open(act)
        return await media_play(act)

    results = await timing_controller.execute_dependent_actions(
        actions=actions,
        execute_fn=custom_executor
    )

    assert len(results) == 2
    assert results[0].status == ActionLifecycleState.SUCCESS
    assert results[1].status == ActionLifecycleState.SUCCESS
    assert execution_order == ["open_notepad", "play_music"]


# ---------------------------------------------------------------------------
# Test 5 — Priority Handling Between Conflicting Actions
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_5_priority_handling():
    """
    When conflicting commands are evaluated, emergency/higher priority commands
    take precedence over lower priority operations.
    """
    cm = ConflictManager()

    # Active playback command on YouTube with normal priority (1)
    cm.register_active(command="PLAY", domain="MEDIA", app="YOUTUBE", priority=1)

    # Emergency STOP command overrides active playback
    res_stop = cm.evaluate(command="STOP", domain="MEDIA", app="YOUTUBE")
    assert res_stop.is_allowed is True

    # When STOP is active, a conflicting lower-priority PLAY command is rejected
    cm.clear_cycle()
    cm.register_active(command="STOP", domain="MEDIA", app="YOUTUBE", priority=10)
    res_play = cm.evaluate(command="PLAY", domain="MEDIA", app="YOUTUBE", priority=1)
    assert res_play.is_allowed is False
    assert res_play.status == DecisionStatus.CONFLICT
    assert "STOP" in res_play.conflicts


# ---------------------------------------------------------------------------
# Test 6 — Recovery After Conflict Resolution
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_6_conflict_recovery():
    """
    Once an active operation completes or releases its active registration,
    subsequent operations on that resource proceed normally.
    """
    cm = ConflictManager(debounce_interval=0.1)

    # 1. Operation starts
    fp = cm.register_active(command="previous_video", domain="PYTHON", app="YOUTUBE")

    # Conflicting attempt is rejected
    res_rejected = cm.evaluate(command="next_video", domain="PYTHON", app="YOUTUBE")
    assert res_rejected.is_allowed is False

    # 2. First operation completes and releases
    cm.release_active(fp)
    time.sleep(0.12)  # Wait past debounce window

    # 3. Second operation is now allowed
    res_allowed = cm.evaluate(command="next_video", domain="PYTHON", app="YOUTUBE")
    assert res_allowed.is_allowed is True
    assert res_allowed.status == DecisionStatus.ALLOWED


# ---------------------------------------------------------------------------
# Test 7 — Existing Functionality Remains Intact
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_7_existing_functionality_normal_execution():
    """
    Verify that standard Desktop, Media, and navigation flows continue to work
    normally through EcosystemOrchestrator when no conflicts exist.
    """
    # Level 1 -> Transition to PYTHON
    res_l1 = await ecosystem_orchestrator.process_command("PUSH", session="default")
    assert res_l1["status"] == "success"
    assert res_l1["resolved"]["type"] == "transition"
    assert res_l1["resolved"]["domain"] == "PYTHON"

    # Level 2 -> Transition to CHROME
    res_l2 = await ecosystem_orchestrator.process_command("PULL", session="default")
    assert res_l2["status"] == "success"
    assert res_l2["resolved"]["type"] == "transition"
    assert res_l2["resolved"]["app"] == "CHROME"

    # Level 3 -> Action execution on CHROME
    res_l3 = await ecosystem_orchestrator.process_command("PUSH", session="default")
    assert res_l3["status"] == "success"
    assert res_l3["resolved"]["type"] == "action"
    assert res_l3["resolved"]["action"] == "open_predefined_article"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

