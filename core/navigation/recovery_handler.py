"""
Navigation Recovery Handler
===========================
Handles recovery actions for rejected, timed-out, and failed navigation commands,
ensuring safe continuation, graceful degradation, or controlled termination.
"""

import copy
import logging
from typing import Dict, Any, Optional

from core.state.state_manager import state_manager
from core.routing.rule_router import navigate_back, navigate_home

logger = logging.getLogger("synaptimesh.recovery")


class RecoveryResult:
    """
    Structured outcome of a navigation recovery operation.
    """
    def __init__(self,
                 attempted: bool,
                 status: str,
                 action: str,
                 error: Optional[str] = None,
                 state: Optional[dict] = None):
        self.attempted = attempted
        self.status = status          # "not_required", "recovered", "terminated", "failed"
        self.action = action          # "none", "restore_previous_state", "navigate_back", "navigate_home", "terminate"
        self.error = error
        self.state = state

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recovery_attempted": self.attempted,
            "recovery_status": self.status,
            "recovery_action": self.action,
            "recovery_error": self.error
        }


class RecoveryHandler:
    """
    Manages navigation-level recovery across both NavigationController and BCI API paths.
    Does NOT contain hardware/RC-car safety logic (which is isolated in subplugins).
    """

    @staticmethod
    def log_recovery(command: str, reason: str, action: str, status: str):
        """
        Standardized recovery log format:
        [Recovery] command=<COMMAND> reason=<REASON> action=<ACTION> status=<STATUS>
        """
        logger.warning(f"[Recovery] command={command} reason={reason} action={action} status={status}")

    def handle_rejected_command(self,
                                command: str,
                                reason: str = "invalid command",
                                session: str = "default") -> RecoveryResult:
        """
        Handles rejected / invalid command input.
        Preserves current valid state without unnecessary mutation or corruption.
        """
        current_state = state_manager.get_state(session)
        action = "none"
        status = "not_required"
        self.log_recovery(command, reason, action, status)
        return RecoveryResult(attempted=True, status=status, action=action, error=reason, state=current_state)

    def handle_invalid_transition(self,
                                  command: str,
                                  reason: str = "invalid transition",
                                  previous_state: Optional[dict] = None,
                                  session: str = "default") -> RecoveryResult:
        """
        Handles invalid transition (e.g. rule router returns no_action).
        Restores previous valid state snapshot if provided, or retains safe state.
        """
        if previous_state:
            state_manager.update_state(session, copy.deepcopy(previous_state))
            action = "restore_previous_state"
            status = "recovered"
        else:
            action = "none"
            status = "not_required"
            
        current_state = state_manager.get_state(session)
        self.log_recovery(command, reason, action, status)
        return RecoveryResult(attempted=True, status=status, action=action, error=reason, state=current_state)

    def handle_execution_failure(self,
                                 command: str,
                                 reason: str,
                                 previous_state: Optional[dict] = None,
                                 session: str = "default") -> RecoveryResult:
        """
        Handles failed execution of a navigation action or plugin.
        Recovery Strategy:
        1. Restore previous valid state snapshot.
        2. If previous state is unavailable or invalid, use navigate_back().
        3. If navigate_back() fails, use navigate_home().
        4. If home fails, report controlled termination.
        """
        try:
            if previous_state:
                state_manager.update_state(session, copy.deepcopy(previous_state))
                current_state = state_manager.get_state(session)
                action = "restore_previous_state"
                status = "recovered"
                self.log_recovery(command, reason, action, status)
                return RecoveryResult(attempted=True, status=status, action=action, error=reason, state=current_state)

            current_state = state_manager.get_state(session)
            back_updates = navigate_back(current_state)
            if back_updates:
                state_manager.update_state(session, back_updates)
                current_state = state_manager.get_state(session)
                action = "navigate_back"
                status = "recovered"
                self.log_recovery(command, reason, action, status)
                return RecoveryResult(attempted=True, status=status, action=action, error=reason, state=current_state)

            home_updates = navigate_home(current_state)
            if home_updates:
                state_manager.update_state(session, home_updates)
                current_state = state_manager.get_state(session)
                action = "navigate_home"
                status = "recovered"
                self.log_recovery(command, reason, action, status)
                return RecoveryResult(attempted=True, status=status, action=action, error=reason, state=current_state)

        except Exception as rec_err:
            self.log_recovery(command, f"{reason} | recovery_error: {rec_err}", "terminate", "failed")
            return RecoveryResult(attempted=True, status="failed", action="terminate", error=str(rec_err), state=state_manager.get_state(session))

        self.log_recovery(command, reason, "terminate", "terminated")
        return RecoveryResult(attempted=True, status="terminated", action="terminate", error=reason, state=state_manager.get_state(session))

    def handle_exception(self,
                         command: str,
                         exception: Exception,
                         previous_state: Optional[dict] = None,
                         session: str = "default") -> RecoveryResult:
        """
        Handles unexpected Python exceptions during navigation execution.
        """
        reason = f"exception: {str(exception)}"
        return self.handle_execution_failure(command, reason, previous_state, session)

    def handle_timeout(self,
                       command: str,
                       timeout_seconds: float,
                       previous_state: Optional[dict] = None,
                       session: str = "default") -> RecoveryResult:
        """
        Handles navigation execution timeout.
        """
        reason = f"timeout after {timeout_seconds}s"
        return self.handle_execution_failure(command, reason, previous_state, session)

    def recover_to_safe_state(self, session: str = "default") -> RecoveryResult:
        """
        Explicitly recovers session navigation state to the root safe state (Level 1 Domain Selection).
        """
        try:
            current_state = state_manager.get_state(session)
            updates = navigate_home(current_state)
            state_manager.update_state(session, updates)
            new_state = state_manager.get_state(session)
            self.log_recovery("RECOVER", "forced safe state", "navigate_home", "recovered")
            return RecoveryResult(attempted=True, status="recovered", action="navigate_home", state=new_state)
        except Exception as e:
            self.log_recovery("RECOVER", f"safe state error: {e}", "terminate", "failed")
            return RecoveryResult(attempted=True, status="failed", action="terminate", error=str(e), state=state_manager.get_state(session))


recovery_handler = RecoveryHandler()
