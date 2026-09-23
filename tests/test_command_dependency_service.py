import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.command_dependency_service import (
    CommandDependencyService,
    get_command_dependency_service,
    ActionLifecycleState,
    DependencyCondition,
    CircularDependencyError,
    MissingDependencyError,
    DependentAction,
)


@pytest.fixture
def dep_service():
    """Create a fresh CommandDependencyService instance for testing."""
    return CommandDependencyService()


# ---------------------------------------------------------------------------
# 1. Validation & Graph Tests
# ---------------------------------------------------------------------------

def test_singleton_getter():
    """Verify singleton getter returns consistent service instance."""
    svc1 = get_command_dependency_service()
    svc2 = get_command_dependency_service()
    assert svc1 is svc2
    assert isinstance(svc1, CommandDependencyService)


def test_validation_valid_graph(dep_service):
    """Verify valid dependency graph parses without error."""
    actions = [
        {"id": "step1", "command": "CMD_A"},
        {"id": "step2", "command": "CMD_B", "depends_on": ["step1"]},
        {"id": "step3", "command": "CMD_C", "depends_on": ["step1", "step2"]},
    ]
    parsed = dep_service.validate_workflow(actions)
    assert len(parsed) == 3
    assert parsed[0].id == "step1"
    assert parsed[1].depends_on == ["step1"]


def test_validation_missing_dependency(dep_service):
    """Verify missing dependency raises MissingDependencyError."""
    actions = [
        {"id": "step1", "command": "CMD_A"},
        {"id": "step2", "command": "CMD_B", "depends_on": ["non_existent_step"]},
    ]
    with pytest.raises(MissingDependencyError) as exc_info:
        dep_service.validate_workflow(actions)
    assert "non_existent_step" in str(exc_info.value)


def test_validation_circular_dependency(dep_service):
    """Verify circular dependency cycle raises CircularDependencyError."""
    actions = [
        {"id": "A", "command": "CMD_A", "depends_on": ["C"]},
        {"id": "B", "command": "CMD_B", "depends_on": ["A"]},
        {"id": "C", "command": "CMD_C", "depends_on": ["B"]},
    ]
    with pytest.raises(CircularDependencyError) as exc_info:
        dep_service.validate_workflow(actions)
    assert "Circular dependency detected" in str(exc_info.value)


def test_validation_duplicate_id(dep_service):
    """Verify duplicate action IDs raise ValueError."""
    actions = [
        {"id": "dup", "command": "CMD_1"},
        {"id": "dup", "command": "CMD_2"},
    ]
    with pytest.raises(ValueError) as exc_info:
        dep_service.validate_workflow(actions)
    assert "Duplicate action ID" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 2. Sequential & Branching DAG Execution
# ---------------------------------------------------------------------------

def test_strict_sequential_execution(dep_service):
    """Verify dependent action B strictly starts after action A finishes."""
    timestamps = {}

    async def mock_exec(act: DependentAction):
        timestamps[f"{act.id}_start"] = time.time()
        await asyncio.sleep(0.04)
        timestamps[f"{act.id}_end"] = time.time()
        return f"Result {act.id}"

    actions = [
        {"id": "A", "command": "CMD_A"},
        {"id": "B", "command": "CMD_B", "depends_on": ["A"]},
    ]

    res = asyncio.run(dep_service.execute_workflow(actions, execute_fn=mock_exec))

    assert res["status"] == "SUCCESS"
    assert res["success"] is True
    assert res["total_actions"] == 2
    assert res["succeeded_count"] == 2
    assert timestamps["B_start"] >= timestamps["A_end"]


def test_diamond_branching_dag(dep_service):
    r"""
    Verify diamond workflow:
          A
        /   \
       B     C
        \   /
          D
    D must wait for both B and C to complete.
    """
    timestamps = {}

    async def mock_exec(act: DependentAction):
        timestamps[f"{act.id}_start"] = time.time()
        await asyncio.sleep(0.03)
        timestamps[f"{act.id}_end"] = time.time()
        return f"OK_{act.id}"

    actions = [
        {"id": "A", "command": "START"},
        {"id": "B", "command": "BRANCH_1", "depends_on": ["A"]},
        {"id": "C", "command": "BRANCH_2", "depends_on": ["A"]},
        {"id": "D", "command": "JOIN", "depends_on": ["B", "C"]},
    ]

    res = asyncio.run(dep_service.execute_workflow(actions, execute_fn=mock_exec))

    assert res["status"] == "SUCCESS"
    assert res["succeeded_count"] == 4
    # D starts only after both B and C end
    assert timestamps["D_start"] >= timestamps["B_end"]
    assert timestamps["D_start"] >= timestamps["C_end"]


# ---------------------------------------------------------------------------
# 3. Dependency Condition & Failure Handling
# ---------------------------------------------------------------------------

def test_condition_all_success_skips_on_failure(dep_service):
    """Verify downstream action is SKIPPED when upstream dependency fails under all_success."""
    async def mock_exec(act: DependentAction):
        if act.id == "A":
            raise RuntimeError("Database connection lost")
        return "OK"

    actions = [
        {"id": "A", "command": "FAILING_ACTION"},
        {"id": "B", "command": "DEPENDENT_ACTION", "depends_on": ["A"], "condition": "all_success"},
        {"id": "C", "command": "CHAINED_ACTION", "depends_on": ["B"], "condition": "all_success"},
    ]

    res = asyncio.run(dep_service.execute_workflow(actions, execute_fn=mock_exec))

    assert res["status"] in ["FAILED", "PARTIAL"]
    assert res["success"] is False
    assert res["failed_count"] == 1
    assert res["skipped_count"] == 2

    # Check action states
    action_dict = {a["id"]: a for a in res["actions"]}
    assert action_dict["A"]["status"] == "FAILED"
    assert action_dict["B"]["status"] == "SKIPPED"
    assert action_dict["C"]["status"] == "SKIPPED"


def test_condition_any_success_executes_if_one_branch_succeeds(dep_service):
    """Verify action with any_success executes if at least one dependency succeeds."""
    async def mock_exec(act: DependentAction):
        if act.id == "FAIL_BRANCH":
            raise RuntimeError("Branch failed")
        return f"OK_{act.id}"

    actions = [
        {"id": "FAIL_BRANCH", "command": "CMD_FAIL"},
        {"id": "SUCCESS_BRANCH", "command": "CMD_SUCCESS"},
        {"id": "JOIN_NODE", "command": "CMD_JOIN", "depends_on": ["FAIL_BRANCH", "SUCCESS_BRANCH"], "condition": "any_success"},
    ]

    res = asyncio.run(dep_service.execute_workflow(actions, execute_fn=mock_exec))

    assert res["succeeded_count"] == 2
    assert res["failed_count"] == 1
    action_dict = {a["id"]: a for a in res["actions"]}
    assert action_dict["FAIL_BRANCH"]["status"] == "FAILED"
    assert action_dict["SUCCESS_BRANCH"]["status"] == "SUCCESS"
    assert action_dict["JOIN_NODE"]["status"] == "SUCCESS"


def test_condition_all_completed_executes_cleanup(dep_service):
    """Verify teardown/cleanup action executes under all_completed regardless of upstream failure."""
    cleanup_executed = False

    async def mock_exec(act: DependentAction):
        nonlocal cleanup_executed
        if act.id == "TASK_1":
            raise RuntimeError("Task 1 error")
        if act.id == "CLEANUP":
            cleanup_executed = True
            return "Cleanup done"
        return "OK"

    actions = [
        {"id": "TASK_1", "command": "DO_WORK"},
        {"id": "CLEANUP", "command": "CLEANUP_ENV", "depends_on": ["TASK_1"], "condition": "all_completed"},
    ]

    res = asyncio.run(dep_service.execute_workflow(actions, execute_fn=mock_exec))

    assert cleanup_executed is True
    action_dict = {a["id"]: a for a in res["actions"]}
    assert action_dict["TASK_1"]["status"] == "FAILED"
    assert action_dict["CLEANUP"]["status"] == "SUCCESS"


# ---------------------------------------------------------------------------
# 4. Timing Controls & Timeouts
# ---------------------------------------------------------------------------

def test_action_timeout_handling(dep_service):
    """Verify individual action timeout is trapped and marked TIMEOUT."""
    async def slow_exec(act: DependentAction):
        await asyncio.sleep(0.1)
        return "Slow OK"

    actions = [
        {"id": "fast", "command": "FAST_CMD"},
        {"id": "slow", "command": "SLOW_CMD", "timeout": 0.02},
    ]

    res = asyncio.run(dep_service.execute_workflow(actions, execute_fn=slow_exec))

    assert res["timed_out_count"] == 1
    action_dict = {a["id"]: a for a in res["actions"]}
    assert action_dict["slow"]["status"] == "TIMEOUT"


def test_pre_and_post_delays(dep_service):
    """Verify pre-delay and post-delay timing."""
    async def fast_exec(act: DependentAction):
        return "Done"

    actions = [
        {"id": "act1", "command": "CMD1", "delay_before": 0.03, "delay_after": 0.02},
        {"id": "act2", "command": "CMD2", "depends_on": ["act1"]},
    ]

    start_t = time.time()
    res = asyncio.run(dep_service.execute_workflow(actions, execute_fn=fast_exec))
    total_elapsed = time.time() - start_t

    assert res["status"] == "SUCCESS"
    assert total_elapsed >= 0.05


# ---------------------------------------------------------------------------
# 5. Cross-Domain Dispatch & History Tracking
# ---------------------------------------------------------------------------

def test_cross_domain_default_dispatch(dep_service):
    """Verify default dispatcher delegates to core plugin manager."""
    with patch("core.plugin_manager.manager.execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = {"status": "success", "message": "Dispatched"}

        actions = [
            {"id": "iot_light", "domain": "iot", "command": "LIGHT_ON", "device_id": "L1"},
            {"id": "media_play", "domain": "media", "command": "PLAY", "app": "YOUTUBE", "depends_on": ["iot_light"]},
        ]

        res = asyncio.run(dep_service.execute_workflow(actions, session_id="test_cross"))

        assert res["status"] == "SUCCESS"
        assert res["succeeded_count"] == 2
        assert mock_exec.call_count == 2


def test_execute_sequence_and_history(dep_service):
    """Verify execute_sequence auto-chains steps and stores history."""
    async def mock_exec(act: DependentAction):
        return f"Executed {act.id}"

    steps = [
        {"id": "s1", "command": "STEP_1"},
        {"id": "s2", "command": "STEP_2"},
        {"id": "s3", "command": "STEP_3"},
    ]

    res = asyncio.run(dep_service.execute_sequence(steps, session_id="seq_sess", execute_fn=mock_exec))

    assert res["status"] == "SUCCESS"
    assert res["total_actions"] == 3

    # Check history
    history = dep_service.get_history(limit=5)
    assert len(history) >= 1
    assert history[-1]["workflow_id"] == res["workflow_id"]
    assert history[-1]["metadata"]["session_id"] == "seq_sess"
