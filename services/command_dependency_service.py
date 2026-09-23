"""
services/command_dependency_service.py
---------------------------------------
Member 7 — Command Dependency Management Service

Coordinates complex, multi-action workflows with fine-grained dependencies,
topological validation, lifecycle tracking, cross-domain dispatching, and
structured workflow telemetry.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Union

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

logger = logging.getLogger("CommandDependencyService")


class CommandDependencyService:
    """
    Dedicated service for validating, scheduling, executing, and tracking
    dependent multi-action command workflows across domains.
    """

    def __init__(self, controller: Optional[TimingController] = None):
        self.controller = controller or timing_controller
        self._history: List[Dict[str, Any]] = []
        self._max_history = 100

    def validate_workflow(
        self, actions: List[Union[DependentAction, Dict[str, Any]]]
    ) -> List[DependentAction]:
        """
        Validates the dependency graph structure of the given actions.
        
        Checks:
        - Duplicate action IDs
        - Missing prerequisite dependencies
        - Circular dependency cycles (Kahn's topological sort)
        
        Returns:
            List of parsed DependentAction objects.
            
        Raises:
            ValueError: If duplicate action IDs are detected.
            MissingDependencyError: If a depends_on ID does not exist.
            CircularDependencyError: If a dependency cycle is detected.
        """
        parsed_actions: List[DependentAction] = []
        for item in actions:
            if isinstance(item, DependentAction):
                parsed_actions.append(item)
            elif isinstance(item, dict):
                parsed_actions.append(DependentAction(**item))
            else:
                raise TypeError(f"Expected DependentAction or dict, got {type(item)}")

        DependencyGraph.validate(parsed_actions)
        return parsed_actions

    async def execute_workflow(
        self,
        actions: List[Union[DependentAction, Dict[str, Any]]],
        session_id: str = "default",
        global_timeout: Optional[float] = None,
        stop_on_first_error: bool = False,
        execute_fn: Optional[Callable] = None,
        workflow_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executes a workflow of dependent actions with synchronized DAG progression.

        Args:
            actions: List of DependentAction objects or configuration dicts.
            session_id: Session identifier for context and state tracking.
            global_timeout: Overall workflow timeout limit in seconds.
            stop_on_first_error: Whether to halt remaining actions when one fails.
            execute_fn: Optional custom executor `async def(action) -> result`.
            workflow_id: Optional tracking identifier.

        Returns:
            Standardized workflow summary dictionary including action details and metrics.
        """
        start_time = time.perf_counter()
        wid = workflow_id or f"wf_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"

        logger.info(
            f"[CommandDependencyService] Starting workflow '{wid}' with {len(actions)} actions (session='{session_id}')"
        )

        # 1. Pre-execution Graph Validation
        parsed_actions = self.validate_workflow(actions)

        # 2. Build Default Cross-Domain Dispatcher if no custom execute_fn is provided
        async def _cross_domain_executor(act: DependentAction) -> Any:
            """Dispatches action via core plugin manager or CommandServiceMapper."""
            if callable(act.command):
                if asyncio.iscoroutinefunction(act.command):
                    return await act.command(**(act.payload or {}))
                return act.command(**(act.payload or {}))

            domain_str = (act.domain or "").strip().lower()
            cmd_str = str(act.command)
            payload = dict(act.payload or {})

            if act.app:
                payload["app"] = act.app.upper()
            if act.device_id:
                payload["device_id"] = act.device_id
            payload.setdefault("session", session_id)
            payload.setdefault("confidence", 1.0)

            # Route through core plugin manager
            from core.plugin_manager.manager import execute
            target_plugin = domain_str if domain_str else "desktop"
            logger.debug(
                f"[CommandDependencyService] Dispatching action '{act.id}' -> plugin '{target_plugin}', command '{cmd_str}'"
            )
            return await execute(target_plugin, cmd_str, payload)

        actual_executor = execute_fn or _cross_domain_executor

        # 3. Synchronized DAG Execution via TimingController
        try:
            executed_actions = await self.controller.execute_dependent_actions(
                actions=parsed_actions,
                session=session_id,
                global_timeout=global_timeout,
                stop_on_first_error=stop_on_first_error,
                execute_fn=actual_executor,
            )
        except WorkflowTimeoutError as wte:
            logger.warning(f"[CommandDependencyService] Workflow '{wid}' timed out: {wte}")
            executed_actions = parsed_actions

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # 4. Summarize Action States & Metrics
        succeeded = 0
        failed = 0
        skipped = 0
        timed_out = 0
        action_summaries = []

        for act in executed_actions:
            if act.status == ActionLifecycleState.SUCCESS:
                succeeded += 1
            elif act.status == ActionLifecycleState.FAILED:
                failed += 1
            elif act.status == ActionLifecycleState.SKIPPED:
                skipped += 1
            elif act.status == ActionLifecycleState.TIMEOUT:
                timed_out += 1

            action_summaries.append(
                {
                    "id": act.id,
                    "command": str(act.command) if not callable(act.command) else getattr(act.command, "__name__", "callable"),
                    "domain": act.domain,
                    "app": act.app,
                    "status": act.status.value,
                    "result": act.result,
                    "error": act.error,
                    "duration": act.duration,
                    "started_at": act.started_at,
                    "completed_at": act.completed_at,
                }
            )

        total = len(executed_actions)
        is_overall_success = succeeded == total and total > 0

        if is_overall_success:
            overall_status = "SUCCESS"
        elif succeeded > 0 and (failed > 0 or skipped > 0):
            overall_status = "PARTIAL"
        elif timed_out > 0:
            overall_status = "TIMEOUT"
        else:
            overall_status = "FAILED"

        # 5. Build Standardized Workflow Response
        timeline = self.controller.get_timeline(executed_actions)
        response = {
            "workflow_id": wid,
            "status": overall_status,
            "success": is_overall_success,
            "total_actions": total,
            "succeeded_count": succeeded,
            "failed_count": failed,
            "skipped_count": skipped,
            "timed_out_count": timed_out,
            "execution_time_ms": elapsed_ms,
            "actions": action_summaries,
            "timeline": timeline,
            "metadata": {
                "session_id": session_id,
                "timestamp": time.time(),
                "stop_on_first_error": stop_on_first_error,
                "global_timeout": global_timeout,
            },
        }

        # 6. Telemetry History Recording
        self._record_history(response)
        logger.info(
            f"[CommandDependencyService] Completed workflow '{wid}' | Status: {overall_status} | "
            f"Succeeded: {succeeded}/{total}, Failed: {failed}, Skipped: {skipped} ({elapsed_ms}ms)"
        )
        return response

    async def execute_sequence(
        self,
        steps: List[Dict[str, Any]],
        session_id: str = "default",
        execute_fn: Optional[Callable] = None,
        global_timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Convenience method to execute sequential steps with auto-chained dependencies.
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

        return await self.execute_workflow(
            actions=actions,
            session_id=session_id,
            global_timeout=global_timeout,
            execute_fn=execute_fn,
        )

    def cancel_active(self) -> None:
        """Cancel all running workflows managed by the timing controller."""
        self.controller.cancel_all()

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve recent workflow execution telemetry records."""
        return self._history[-limit:]

    def _record_history(self, record: Dict[str, Any]) -> None:
        """Appends a workflow response to in-memory history."""
        self._history.append(record)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]


# Global singleton instance
_dependency_service_instance: Optional[CommandDependencyService] = None


def get_command_dependency_service() -> CommandDependencyService:
    """Retrieve or initialize the global CommandDependencyService singleton."""
    global _dependency_service_instance
    if _dependency_service_instance is None:
        _dependency_service_instance = CommandDependencyService()
    return _dependency_service_instance
