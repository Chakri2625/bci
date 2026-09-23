import asyncio
import logging
from typing import List, Dict, Any, Optional
from core.navigation.controller import navigation_controller
from core.navigation.models import NavigationRequest
from core.plugin_manager.manager import execute
from core.state.state_manager import state_manager
from core.orchestration.timing_controller import timing_controller, DependentAction

logger = logging.getLogger("AutomationEngine")

class AutomationEngine:
    def __init__(self):
        self.is_running = False
        self._cancel_flag = False

    async def execute_sequence(self, domain: str, plugin: str, commands: List[Dict[str, Any]], session: str = "default"):
        """
        Executes a sequence of commands with timing controls (delay_before, delay_after, timeout).
        """
        self.is_running = True
        self._cancel_flag = False
        results = []

        try:
            # Force transition to the right domain if we are not there
            current_state = state_manager.get_state(session)
            if current_state.get("active_domain") != domain.upper():
                logger.info(f"Automation shifting domain to {domain.upper()}")
                state_manager.update_state(session, {
                    "current_level": 2,
                    "active_domain": domain.upper(),
                    "active_app": plugin.upper()
                })

            for i, cmd_obj in enumerate(commands):
                if self._cancel_flag:
                    logger.warning("Automation sequence cancelled by user/emergency STOP.")
                    if plugin.upper() == "RC_CAR":
                        await execute(domain.lower(), "STOP", {"app": plugin.upper()})
                    break

                # Pre-execution delay
                delay_before = cmd_obj.get("delay_before", 0.0)
                if delay_before > 0:
                    await asyncio.sleep(delay_before)

                command = cmd_obj.get("command", "").upper()
                logger.info(f"Automation executing step {i+1}/{len(commands)}: {command}")

                timeout = cmd_obj.get("timeout")
                action_res = None

                if command in ["PUSH", "PULL", "LEFT", "RIGHT", "STOP"]:
                    exec_coro = execute(domain.lower(), command, {"app": plugin.upper(), "confidence": 1.0})
                    if timeout is not None:
                        action_res = await asyncio.wait_for(exec_coro, timeout=timeout)
                    else:
                        action_res = await exec_coro
                    results.append(action_res)
                
                # Post-execution delay (backward compatible with 'delay')
                delay_after = cmd_obj.get("delay_after", cmd_obj.get("delay", 1.0))
                if delay_after > 0:
                    await asyncio.sleep(delay_after)

        except Exception as e:
            logger.error(f"Automation execution failed: {e}")
            if plugin.upper() == "RC_CAR":
                await execute(domain.lower(), "STOP", {"app": plugin.upper()})
        finally:
            self.is_running = False
            self._cancel_flag = False
            
        return results

    async def execute_workflow(
        self,
        domain: str,
        plugin: str,
        actions: List[Dict[str, Any]],
        session: str = "default",
        global_timeout: Optional[float] = None
    ) -> List[DependentAction]:
        """
        Executes a workflow of dependent actions with synchronized timing controls.
        """
        self.is_running = True
        self._cancel_flag = False

        try:
            current_state = state_manager.get_state(session)
            if current_state.get("active_domain") != domain.upper():
                state_manager.update_state(session, {
                    "current_level": 2,
                    "active_domain": domain.upper(),
                    "active_app": plugin.upper()
                })

            async def _workflow_executor(action: DependentAction):
                cmd_name = str(action.command).upper()
                payload = dict(action.payload or {})
                payload.setdefault("app", plugin.upper())
                payload.setdefault("confidence", 1.0)
                return await execute(domain.lower(), cmd_name, payload)

            results = await timing_controller.execute_dependent_actions(
                actions=actions,
                session=session,
                global_timeout=global_timeout,
                execute_fn=_workflow_executor
            )
            return results
        finally:
            self.is_running = False
            self._cancel_flag = False

    def stop(self):
        self._cancel_flag = True
        timing_controller.cancel_all()

automation_engine = AutomationEngine()
