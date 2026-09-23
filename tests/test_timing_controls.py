"""
Unit tests for Timing Controls and Synchronized Execution for Dependent Actions (Member 7).
"""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, patch

from core.orchestration.timing_controller import (
    ActionLifecycleState,
    ActionTimeoutError,
    CircularDependencyError,
    DependencyCondition,
    DependencyGraph,
    DependentAction,
    MissingDependencyError,
    TimingController,
    WorkflowTimeoutError,
    timing_controller,
)
from core.state.state_manager import state_manager
from core.automation.engine import automation_engine
from core.orchestration.ecosystem_orchestrator import ecosystem_orchestrator


@pytest.fixture(autouse=True)
def reset_state():
    state_manager.states.clear()


def test_1_dependency_graph_validation_missing_dependency():
    """Missing dependency raises MissingDependencyError."""
    actions = [
        DependentAction(id="act1", command="PUSH"),
        DependentAction(id="act2", command="PULL", depends_on=["non_existent_id"]),
    ]
    with pytest.raises(MissingDependencyError) as exc_info:
        DependencyGraph.validate(actions)
    assert "non_existent_id" in str(exc_info.value)


def test_2_dependency_graph_validation_circular_dependency():
    """Circular dependency raises CircularDependencyError."""
    actions = [
        DependentAction(id="act1", command="PUSH", depends_on=["act3"]),
        DependentAction(id="act2", command="LEFT", depends_on=["act1"]),
        DependentAction(id="act3", command="RIGHT", depends_on=["act2"]),
    ]
    with pytest.raises(CircularDependencyError) as exc_info:
        DependencyGraph.validate(actions)
    assert "Circular dependency detected" in str(exc_info.value)


def test_3_dependency_graph_validation_duplicate_id():
    """Duplicate action ID raises ValueError."""
    actions = [
        DependentAction(id="dup_id", command="PUSH"),
        DependentAction(id="dup_id", command="PULL"),
    ]
    with pytest.raises(ValueError) as exc_info:
        DependencyGraph.validate(actions)
    assert "Duplicate action ID" in str(exc_info.value)


def test_4_strict_dependency_sequence():
    """Dependent action B starts strictly after action A completes."""
    async def run():
        controller = TimingController()
        order = []

        async def exec_fn(action: DependentAction):
            if action.id == "A":
                order.append("A_start")
                await asyncio.sleep(0.06)
                order.append("A_end")
                return "result_A"
            elif action.id == "B":
                order.append("B_start")
                await asyncio.sleep(0.03)
                order.append("B_end")
                return "result_B"

        actions = [
            {"id": "A", "command": "cmd_A"},
            {"id": "B", "command": "cmd_B", "depends_on": ["A"]},
        ]

        results = await controller.execute_dependent_actions(actions, execute_fn=exec_fn)

        assert order == ["A_start", "A_end", "B_start", "B_end"]
        assert len(results) == 2
        assert results[0].status == ActionLifecycleState.SUCCESS
        assert results[0].result == "result_A"
        assert results[1].status == ActionLifecycleState.SUCCESS
        assert results[1].result == "result_B"
        assert results[0].completed_at <= results[1].started_at

    asyncio.run(run())


def test_5_parallel_branches_synchronized_join():
    """Parallel actions A and B execute concurrently, and join action C waits for both."""
    async def run():
        controller = TimingController()
        timeline = {}

        async def exec_fn(action: DependentAction):
            start = time.time()
            if action.id == "A":
                await asyncio.sleep(0.08)
            elif action.id == "B":
                await asyncio.sleep(0.08)
            elif action.id == "C":
                await asyncio.sleep(0.03)
            end = time.time()
            timeline[action.id] = (start, end)
            return f"done_{action.id}"

        actions = [
            {"id": "A", "command": "branch_A"},
            {"id": "B", "command": "branch_B"},
            {"id": "C", "command": "join_C", "depends_on": ["A", "B"]},
        ]

        start_time = time.time()
        results = await controller.execute_dependent_actions(actions, execute_fn=exec_fn)
        total_time = time.time() - start_time

        # A and B ran concurrently (total time around 0.08s + 0.03s = ~0.11s, strictly < 0.17s)
        assert total_time < 0.17
        assert len(results) == 3
        for r in results:
            assert r.status == ActionLifecycleState.SUCCESS

        # C started after both A and B finished
        assert timeline["C"][0] >= timeline["A"][1] - 0.01
        assert timeline["C"][0] >= timeline["B"][1] - 0.01

    asyncio.run(run())


def test_6_pre_execution_delay():
    """delay_before introduces a delay before execution starts."""
    async def run():
        controller = TimingController()
        exec_called_at = 0.0

        async def exec_fn(action: DependentAction):
            nonlocal exec_called_at
            exec_called_at = time.time()
            return "ok"

        action = DependentAction(id="act1", command="TEST", delay_before=0.08)
        start = time.time()
        results = await controller.execute_dependent_actions([action], execute_fn=exec_fn)
        
        assert results[0].status == ActionLifecycleState.SUCCESS
        assert exec_called_at - start >= 0.075

    asyncio.run(run())


def test_7_post_execution_delay_blocks_dependents():
    """delay_after holds dependent action from starting until post-delay passes."""
    async def run():
        controller = TimingController()
        b_started_at = 0.0
        a_finished_exec_at = 0.0

        async def exec_fn(action: DependentAction):
            nonlocal a_finished_exec_at, b_started_at
            if action.id == "A":
                await asyncio.sleep(0.02)
                a_finished_exec_at = time.time()
                return "ok_A"
            elif action.id == "B":
                b_started_at = time.time()
                return "ok_B"

        actions = [
            {"id": "A", "command": "cmd_A", "delay_after": 0.08},
            {"id": "B", "command": "cmd_B", "depends_on": ["A"]},
        ]

        results = await controller.execute_dependent_actions(actions, execute_fn=exec_fn)

        assert results[0].status == ActionLifecycleState.SUCCESS
        assert results[1].status == ActionLifecycleState.SUCCESS
        assert b_started_at - a_finished_exec_at >= 0.075

    asyncio.run(run())


def test_8_action_execution_timeout():
    """An action exceeding its timeout gets marked as TIMEOUT and cancels execution."""
    async def run():
        controller = TimingController()

        async def slow_fn(action: DependentAction):
            await asyncio.sleep(0.5)
            return "never_returned"

        action = DependentAction(id="timeout_act", command="SLOW", timeout=0.05)
        results = await controller.execute_dependent_actions([action], execute_fn=slow_fn)

        assert results[0].status == ActionLifecycleState.TIMEOUT
        assert "timed out after 0.05s" in results[0].error

    asyncio.run(run())


def test_9_dependency_condition_all_success_skips_on_upstream_failure():
    """Downstream action with all_success is SKIPPED when upstream dependency fails."""
    async def run():
        controller = TimingController()

        async def exec_fn(action: DependentAction):
            if action.id == "A":
                raise RuntimeError("Simulated failure in A")
            return "ok"

        actions = [
            {"id": "A", "command": "fail_cmd"},
            {"id": "B", "command": "dep_cmd", "depends_on": ["A"], "condition": "all_success"},
            {"id": "C", "command": "chain_dep_cmd", "depends_on": ["B"], "condition": "all_success"},
        ]

        results = await controller.execute_dependent_actions(actions, execute_fn=exec_fn)

        action_map = {r.id: r for r in results}
        assert action_map["A"].status == ActionLifecycleState.FAILED
        assert action_map["B"].status == ActionLifecycleState.SKIPPED
        assert "not satisfied" in action_map["B"].error
        assert action_map["C"].status == ActionLifecycleState.SKIPPED

    asyncio.run(run())


def test_10_dependency_condition_any_success_and_all_completed():
    """Test any_success condition runs if at least one dependency succeeded."""
    async def run():
        controller = TimingController()

        async def exec_fn(action: DependentAction):
            if action.id == "A":
                raise RuntimeError("Failed A")
            if action.id == "B":
                return "Success B"
            if action.id == "C":
                return "Success C"
            if action.id == "D":
                return "Success D"

        actions = [
            {"id": "A", "command": "fail_A"},
            {"id": "B", "command": "success_B"},
            {"id": "C", "command": "run_C", "depends_on": ["A", "B"], "condition": "any_success"},
            {"id": "D", "command": "run_D", "depends_on": ["A"], "condition": "all_completed"},
        ]

        results = await controller.execute_dependent_actions(actions, execute_fn=exec_fn)
        action_map = {r.id: r for r in results}

        assert action_map["A"].status == ActionLifecycleState.FAILED
        assert action_map["B"].status == ActionLifecycleState.SUCCESS
        assert action_map["C"].status == ActionLifecycleState.SUCCESS
        assert action_map["D"].status == ActionLifecycleState.SUCCESS

    asyncio.run(run())


def test_11_retry_with_delay():
    """Action retries upon failure and succeeds after retry."""
    async def run():
        controller = TimingController()
        attempts = 0

        async def exec_fn(action: DependentAction):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("Temporary error")
            return "recovered"

        action = DependentAction(id="retry_act", command="RETRY", retry_count=2, retry_delay=0.03)
        results = await controller.execute_dependent_actions([action], execute_fn=exec_fn)

        assert results[0].status == ActionLifecycleState.SUCCESS
        assert results[0].result == "recovered"
        assert attempts == 2

    asyncio.run(run())


def test_12_workflow_global_timeout():
    """Workflow raises WorkflowTimeoutError if total duration exceeds global_timeout."""
    async def run():
        controller = TimingController()

        async def slow_fn(action: DependentAction):
            await asyncio.sleep(0.5)
            return "ok"

        actions = [
            {"id": "A", "command": "slow_A"},
            {"id": "B", "command": "slow_B", "depends_on": ["A"]},
        ]

        with pytest.raises(WorkflowTimeoutError):
            await controller.execute_dependent_actions(actions, global_timeout=0.08, execute_fn=slow_fn)

    asyncio.run(run())


def test_13_sequential_timing_convenience_method():
    """execute_sequence_with_timing chains dependencies automatically."""
    async def run():
        controller = TimingController()
        exec_seq = []

        async def exec_fn(action: DependentAction):
            exec_seq.append(action.id)
            return f"res_{action.id}"

        steps = [
            {"id": "step1", "command": "FIRST"},
            {"id": "step2", "command": "SECOND"},
            {"id": "step3", "command": "THIRD"},
        ]

        results = await controller.execute_sequence_with_timing(steps, execute_fn=exec_fn)

        assert exec_seq == ["step1", "step2", "step3"]
        assert len(results) == 3
        for r in results:
            assert r.status == ActionLifecycleState.SUCCESS

        timeline = controller.get_timeline(results)
        assert len(timeline) == 3
        assert timeline[0]["id"] == "step1"
        assert timeline[1]["id"] == "step2"
        assert timeline[2]["id"] == "step3"

    asyncio.run(run())


def test_14_automation_engine_integration():
    """AutomationEngine execute_workflow runs dependent actions with timing controls."""
    async def run():
        state_manager.update_state("default", {"current_level": 3, "active_domain": "EMBEDDED", "active_app": "RC_CAR"})

        with patch("core.automation.engine.execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {"status": "success", "action": "executed"}

            actions = [
                {"id": "init", "command": "STOP", "delay_before": 0.02},
                {"id": "move", "command": "FORWARD", "depends_on": ["init"], "delay_after": 0.02},
                {"id": "turn", "command": "RIGHT", "depends_on": ["move"]},
            ]

            results = await automation_engine.execute_workflow(
                domain="embedded",
                plugin="rc_car",
                actions=actions
            )

            assert len(results) == 3
            for r in results:
                assert r.status == ActionLifecycleState.SUCCESS
            assert mock_exec.call_count == 3

    asyncio.run(run())


def test_15_ecosystem_orchestrator_process_dependent_workflow():
    """EcosystemOrchestrator process_dependent_workflow coordinates synchronized actions."""
    async def run():
        state_manager.update_state("default", {"current_level": 3, "active_domain": "IOT", "active_app": "LIGHT"})

        with patch("core.orchestration.ecosystem_orchestrator.retry_manager.execute_with_retry", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {"status": "SUCCESS", "result": "light_state"}

            actions = [
                {"id": "turn_on", "command": "RIGHT", "device_id": "dev1"},
                {"id": "verify_state", "command": "RIGHT", "device_id": "dev1", "depends_on": ["turn_on"], "delay_before": 0.02},
            ]

            results = await ecosystem_orchestrator.process_dependent_workflow(actions)

            assert len(results) == 2
            assert results[0].status == ActionLifecycleState.SUCCESS
            assert results[1].status == ActionLifecycleState.SUCCESS
            assert results[0].completed_at <= results[1].started_at

    asyncio.run(run())
