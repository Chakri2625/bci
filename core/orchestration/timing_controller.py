"""
Timing Controls and Synchronized Execution for Dependent Actions (Member 7).

This module provides fine-grained timing controls (pre-execution delays, execution timeouts,
post-execution delays, retry delays, and global workflow deadlines) combined with dependency graph
resolution and synchronized execution for multi-action workflows.
"""

import asyncio
import logging
import time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Union
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("timing_controller")


class ActionLifecycleState(str, Enum):
    """Lifecycle states for a dependent action during synchronized execution."""
    PENDING = "PENDING"
    WAITING_DEPENDENCY = "WAITING_DEPENDENCY"
    DELAYING_BEFORE = "DELAYING_BEFORE"
    EXECUTING = "EXECUTING"
    DELAYING_AFTER = "DELAYING_AFTER"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class DependencyCondition(str, Enum):
    """Condition on prerequisite dependencies to permit action execution."""
    ALL_SUCCESS = "all_success"
    ANY_SUCCESS = "any_success"
    ALL_COMPLETED = "all_completed"


class CircularDependencyError(Exception):
    """Raised when a dependency cycle is detected in the action graph."""
    pass


class MissingDependencyError(Exception):
    """Raised when an action references a non-existent prerequisite dependency ID."""
    pass


class ActionTimeoutError(Exception):
    """Raised when an individual action exceeds its specified timeout."""
    pass


class WorkflowTimeoutError(Exception):
    """Raised when the overall workflow execution exceeds its global timeout."""
    pass


class DependentAction(BaseModel):
    """
    Represents an action with explicit timing controls and prerequisite dependencies.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str = Field(..., description="Unique identifier for the action in the workflow graph")
    command: Union[str, Callable, Any] = Field(..., description="Command name, string code, or executable callable")
    domain: Optional[str] = Field(default=None, description="Optional target domain (e.g. 'IOT', 'EMBEDDED', 'PYTHON')")
    app: Optional[str] = Field(default=None, description="Optional target application (e.g. 'LIGHT', 'RC_CAR')")
    device_id: Optional[str] = Field(default=None, description="Optional target device ID for IoT actions")
    payload: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Execution parameters or payload")
    
    # Dependencies and conditions
    depends_on: List[str] = Field(default_factory=list, description="List of action IDs that must complete before this action")
    condition: Union[DependencyCondition, str] = Field(
        default=DependencyCondition.ALL_SUCCESS,
        description="Dependency requirement: 'all_success', 'any_success', or 'all_completed'"
    )
    
    # Timing Controls
    delay_before: float = Field(default=0.0, ge=0.0, description="Pre-execution delay in seconds")
    timeout: Optional[float] = Field(default=None, gt=0.0, description="Maximum execution timeout in seconds for this action")
    delay_after: float = Field(default=0.0, ge=0.0, description="Post-execution delay in seconds before unblocking dependents")
    retry_count: int = Field(default=0, ge=0, description="Number of retry attempts if execution fails")
    retry_delay: float = Field(default=0.0, ge=0.0, description="Delay between retry attempts in seconds")
    
    # Execution Tracking
    status: ActionLifecycleState = Field(default=ActionLifecycleState.PENDING, description="Current execution state")
    result: Optional[Any] = Field(default=None, description="Action execution result")
    error: Optional[str] = Field(default=None, description="Error message if execution failed, timed out, or skipped")
    scheduled_at: Optional[float] = Field(default=None, description="Timestamp when action was submitted to workflow")
    started_at: Optional[float] = Field(default=None, description="Timestamp when execution began (after delay_before)")
    completed_at: Optional[float] = Field(default=None, description="Timestamp when action completed (after delay_after)")
    duration: Optional[float] = Field(default=None, description="Total execution duration in seconds")


class DependencyGraph:
    """
    Validates, analyzes, and manages action dependency relationships and topological sorting.
    """

    @staticmethod
    def validate(actions: List[DependentAction]) -> None:
        """
        Validates action uniqueness, checks for missing dependencies, and ensures no cycles exist.
        """
        action_map: Dict[str, DependentAction] = {}
        for action in actions:
            if action.id in action_map:
                raise ValueError(f"Duplicate action ID found: '{action.id}'")
            action_map[action.id] = action

        # Check for missing dependencies
        for action in actions:
            for dep_id in action.depends_on:
                if dep_id not in action_map:
                    raise MissingDependencyError(
                        f"Action '{action.id}' depends on non-existent action ID '{dep_id}'"
                    )

        # Cycle detection using Kahn's algorithm (topological sorting)
        in_degree: Dict[str, int] = {action.id: 0 for action in actions}
        adj_list: Dict[str, List[str]] = {action.id: [] for action in actions}

        for action in actions:
            for dep_id in action.depends_on:
                adj_list[dep_id].append(action.id)
                in_degree[action.id] += 1

        queue = [aid for aid, deg in in_degree.items() if deg == 0]
        visited_count = 0

        while queue:
            node = queue.pop(0)
            visited_count += 1
            for neighbor in adj_list[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if visited_count != len(actions):
            # There is a cycle. Find participating nodes.
            cycle_nodes = [aid for aid, deg in in_degree.items() if deg > 0]
            raise CircularDependencyError(
                f"Circular dependency detected involving actions: {cycle_nodes}"
            )


class TimingController:
    """
    Orchestrates synchronized execution of dependent actions with precise timing controls.
    """

    def __init__(self):
        self._active_tasks: Set[asyncio.Task] = set()
        self._is_cancelled: bool = False

    def cancel_all(self):
        """Cancels all currently running actions managed by this controller."""
        self._is_cancelled = True
        for task in list(self._active_tasks):
            if not task.done():
                task.cancel()
        logger.info("[TimingController] Cancelled all active action tasks.")

    async def execute_dependent_actions(
        self,
        actions: List[Union[DependentAction, Dict[str, Any]]],
        session: str = "default",
        global_timeout: Optional[float] = None,
        stop_on_first_error: bool = False,
        execute_fn: Optional[Callable] = None,
    ) -> List[DependentAction]:
        """
        Executes a collection of actions respecting their dependency graph and timing constraints.

        Args:
            actions: List of DependentAction objects or dicts representing actions.
            session: Session identifier for context and logging.
            global_timeout: Optional maximum total execution time in seconds for the entire workflow.
            stop_on_first_error: If True, halts execution of remaining actions when any action fails.
            execute_fn: Optional custom executor function `async def(action) -> result`.

        Returns:
            List of DependentAction objects with their updated statuses, results, and timing metrics.
        """
        self._is_cancelled = False
        parsed_actions: List[DependentAction] = []
        for item in actions:
            if isinstance(item, DependentAction):
                parsed_actions.append(item)
            elif isinstance(item, dict):
                parsed_actions.append(DependentAction(**item))
            else:
                raise TypeError(f"Expected DependentAction or dict, got {type(item)}")

        # Validate graph
        DependencyGraph.validate(parsed_actions)

        # Setup lookup maps and completion synchronization events
        action_map: Dict[str, DependentAction] = {act.id: act for act in parsed_actions}
        completion_events: Dict[str, asyncio.Event] = {act.id: asyncio.Event() for act in parsed_actions}

        now = time.time()
        for act in parsed_actions:
            act.scheduled_at = now
            act.status = ActionLifecycleState.WAITING_DEPENDENCY if act.depends_on else ActionLifecycleState.PENDING

        halt_event = asyncio.Event()

        async def _default_executor(act: DependentAction) -> Any:
            """Default execution dispatcher for string commands or callables."""
            if callable(act.command):
                if asyncio.iscoroutinefunction(act.command):
                    return await act.command(**(act.payload or {}))
                return act.command(**(act.payload or {}))
            
            # String command: route through plugin manager or orchestrator
            from core.plugin_manager.manager import execute
            domain = (act.domain or "desktop").lower()
            plugin_payload = dict(act.payload or {})
            if act.app:
                plugin_payload["app"] = act.app.upper()
            if act.device_id:
                plugin_payload["device_id"] = act.device_id
            plugin_payload.setdefault("confidence", 1.0)
            plugin_payload.setdefault("session", session)

            return await execute(domain, act.command, plugin_payload)

        actual_executor = execute_fn or _default_executor

        async def _run_single_action(act: DependentAction):
            try:
                # 1. Wait for all prerequisite dependencies
                if act.depends_on:
                    for dep_id in act.depends_on:
                        await completion_events[dep_id].wait()

                # Check if workflow was cancelled or halted
                if self._is_cancelled or halt_event.is_set():
                    act.status = ActionLifecycleState.CANCELLED
                    act.error = "Workflow execution cancelled"
                    return

                # 2. Evaluate dependency condition
                if act.depends_on:
                    dep_actions = [action_map[dep_id] for dep_id in act.depends_on]
                    condition_met = self._evaluate_condition(act.condition, dep_actions)

                    if not condition_met:
                        act.status = ActionLifecycleState.SKIPPED
                        act.error = f"Prerequisite dependency condition '{act.condition}' not satisfied"
                        logger.info(f"[TimingController] Action '{act.id}' skipped: {act.error}")
                        return

                # 3. Pre-execution delay
                if act.delay_before > 0:
                    act.status = ActionLifecycleState.DELAYING_BEFORE
                    logger.debug(f"[TimingController] Action '{act.id}' delaying {act.delay_before}s before execution")
                    await asyncio.sleep(act.delay_before)

                if self._is_cancelled or halt_event.is_set():
                    act.status = ActionLifecycleState.CANCELLED
                    act.error = "Workflow execution cancelled"
                    return

                # 4. Action Execution with Timeout and Retries
                act.status = ActionLifecycleState.EXECUTING
                act.started_at = time.time()
                logger.info(f"[TimingController] Action '{act.id}' started execution (command: {act.command})")

                attempts = 0
                max_attempts = 1 + act.retry_count
                success = False
                last_error = None
                exec_result = None

                while attempts < max_attempts and not success:
                    attempts += 1
                    try:
                        if act.timeout is not None:
                            exec_result = await asyncio.wait_for(
                                actual_executor(act),
                                timeout=act.timeout
                            )
                        else:
                            exec_result = await actual_executor(act)

                        success = True
                        act.result = exec_result
                    except asyncio.TimeoutError:
                        last_error = f"Action timed out after {act.timeout}s"
                        logger.warning(f"[TimingController] Action '{act.id}' attempt {attempts}/{max_attempts} timed out")
                    except asyncio.CancelledError:
                        act.status = ActionLifecycleState.CANCELLED
                        act.error = "Action execution cancelled"
                        raise
                    except Exception as e:
                        last_error = str(e)
                        logger.warning(f"[TimingController] Action '{act.id}' attempt {attempts}/{max_attempts} failed: {e}")

                    if not success and attempts < max_attempts and act.retry_delay > 0:
                        await asyncio.sleep(act.retry_delay)

                if success:
                    act.status = ActionLifecycleState.SUCCESS
                else:
                    if "timed out" in (last_error or ""):
                        act.status = ActionLifecycleState.TIMEOUT
                    else:
                        act.status = ActionLifecycleState.FAILED
                    act.error = last_error

                    if stop_on_first_error:
                        halt_event.set()

                # 5. Post-execution delay (only if success)
                if act.status == ActionLifecycleState.SUCCESS and act.delay_after > 0:
                    act.status = ActionLifecycleState.DELAYING_AFTER
                    logger.debug(f"[TimingController] Action '{act.id}' delaying {act.delay_after}s after completion")
                    await asyncio.sleep(act.delay_after)
                    act.status = ActionLifecycleState.SUCCESS

                act.completed_at = time.time()
                if act.started_at is not None:
                    act.duration = round(act.completed_at - act.started_at, 4)

                logger.info(f"[TimingController] Action '{act.id}' finalized with status={act.status}")

            except asyncio.CancelledError:
                act.status = ActionLifecycleState.CANCELLED
                act.error = "Action execution cancelled"
                raise
            except Exception as e:
                act.status = ActionLifecycleState.FAILED
                act.error = str(e)
                logger.error(f"[TimingController] Unexpected error in action '{act.id}': {e}", exc_info=True)
                if stop_on_first_error:
                    halt_event.set()
            finally:
                completion_events[act.id].set()

        # Launch all action tasks concurrently; dependency waits synchronize their progression
        tasks = []
        for act in parsed_actions:
            task = asyncio.create_task(_run_single_action(act), name=f"timing_action_{act.id}")
            tasks.append(task)
            self._active_tasks.add(task)

        try:
            if global_timeout is not None:
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=global_timeout)
            else:
                await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.TimeoutError:
            logger.warning(f"[TimingController] Workflow exceeded global timeout of {global_timeout}s")
            self.cancel_all()
            for act in parsed_actions:
                if act.status in [
                    ActionLifecycleState.PENDING,
                    ActionLifecycleState.WAITING_DEPENDENCY,
                    ActionLifecycleState.DELAYING_BEFORE,
                    ActionLifecycleState.EXECUTING,
                    ActionLifecycleState.DELAYING_AFTER,
                ]:
                    act.status = ActionLifecycleState.TIMEOUT
                    act.error = f"Workflow global timeout exceeded ({global_timeout}s)"
            raise WorkflowTimeoutError(f"Workflow execution exceeded global timeout of {global_timeout}s")
        finally:
            for task in tasks:
                self._active_tasks.discard(task)

        return parsed_actions

    def _evaluate_condition(self, condition: Union[DependencyCondition, str], dep_actions: List[DependentAction]) -> bool:
        """Evaluates whether dependencies satisfy the execution condition."""
        if not dep_actions:
            return True

        cond_str = str(condition).lower()
        if "all_success" in cond_str:
            return all(dep.status == ActionLifecycleState.SUCCESS for dep in dep_actions)
        elif "any_success" in cond_str:
            return any(dep.status == ActionLifecycleState.SUCCESS for dep in dep_actions)
        elif "all_completed" in cond_str:
            return all(
                dep.status in [ActionLifecycleState.SUCCESS, ActionLifecycleState.FAILED, ActionLifecycleState.TIMEOUT, ActionLifecycleState.SKIPPED]
                for dep in dep_actions
            )
        return False

    async def execute_sequence_with_timing(
        self,
        steps: List[Dict[str, Any]],
        session: str = "default",
        execute_fn: Optional[Callable] = None,
        global_timeout: Optional[float] = None
    ) -> List[DependentAction]:
        """
        Convenience method to execute a list of sequential steps with timing controls,
        automatically chaining dependencies (step[i] depends on step[i-1]).
        """
        actions = []
        prev_id = None
        for i, step in enumerate(steps):
            act_id = step.get("id", f"step_{i+1}")
            depends = list(step.get("depends_on", []))
            if prev_id is not None and not depends:
                depends.append(prev_id)

            action_data = dict(step)
            action_data["id"] = act_id
            action_data["depends_on"] = depends
            actions.append(action_data)
            prev_id = act_id

        return await self.execute_dependent_actions(
            actions=actions,
            session=session,
            global_timeout=global_timeout,
            execute_fn=execute_fn
        )

    def get_timeline(self, actions: List[DependentAction]) -> List[Dict[str, Any]]:
        """Returns a chronological timeline of completed actions."""
        sorted_actions = sorted(
            [a for a in actions if a.started_at is not None],
            key=lambda x: x.started_at or 0
        )
        return [
            {
                "id": a.id,
                "command": str(a.command),
                "status": a.status.value,
                "started_at": a.started_at,
                "completed_at": a.completed_at,
                "duration": a.duration,
                "error": a.error
            }
            for a in sorted_actions
        ]


timing_controller = TimingController()
