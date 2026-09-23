# core/managers/domain_handler.py

"""
DomainHandler – a unified domain execution handler and failure isolation boundary
for all domain plugin executions.
It delegates execution to the existing RetryManager, isolates domain-specific
failures (DomainError and unexpected exceptions), logs them, and returns
controlled failure responses without crashing the application.
"""

import logging
from typing import Any, Callable, Dict, Optional

from core.managers.retry_manager import retry_manager
from core.exceptions import DomainError
from core.plugin_manager.manager import execute

logger = logging.getLogger("domain_handler")
logger.setLevel(logging.INFO)


class DomainHandler:
    """Execute a domain plugin command with centralized error handling and failure isolation.

    Parameters
    ----------
    plugin_id: str – the id of the plugin (e.g., "iot", "embedded", "desktop", etc.)
    command: str – the command/action name to invoke on the plugin.
    payload: dict – payload passed to the plugin execute method.
    session: str – session identifier for retry manager state updates.
    device_id: Optional[str] – passed through for IoT-type domains.
    state_updater_cb: Optional[Callable] – UI/orchestrator state callback for retries.
    func: Optional[Callable] – execution function (defaults to core.plugin_manager.manager.execute).
    """

    async def handle(
        self,
        plugin_id: str,
        command: str,
        payload: Dict[str, Any],
        session: str,
        device_id: Optional[str] = None,
        state_updater_cb: Optional[Callable[[int, str, Optional[str]], None]] = None,
        func: Optional[Callable] = None,
        retry_mgr: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Executes a domain command through RetryManager while providing domain-level
        failure isolation, logging, and controlled error responses.
        """
        target_func = func if func is not None else execute
        target_retry = retry_mgr if retry_mgr is not None else retry_manager
        cb = state_updater_cb if state_updater_cb is not None else (lambda attempt, status, reason: None)

        try:
            result = await target_retry.execute_with_retry(
                command_name=command,
                session=session,
                state_updater_cb=cb,
                func=target_func,
                plugin_id=plugin_id,
                command=command,
                payload=payload,
            )
            if isinstance(result, dict) and result.get("status") == "FAILED":
                if "error" not in result:
                    result["error"] = result.get("reason")
                if "result" not in result:
                    result["result"] = {"status": "failed", "error": result.get("reason")}
            return result
        except DomainError as de:
            error_msg = str(de)
            logger.error(
                f"[DomainHandler] DomainError caught during execution of {plugin_id}:{command}: {error_msg}",
                exc_info=True,
            )
            if state_updater_cb:
                try:
                    state_updater_cb(1, "FAILED", error_msg)
                except Exception:
                    pass
            return {
                "status": "FAILED",
                "reason": error_msg,
                "error": error_msg,
                "attempt": 1,
                "result": {"status": "failed", "error": error_msg},
            }
        except Exception as ex:
            error_msg = str(ex)
            logger.error(
                f"[DomainHandler] Unexpected exception caught during execution of {plugin_id}:{command}: {error_msg}",
                exc_info=True,
            )
            if state_updater_cb:
                try:
                    state_updater_cb(1, "FAILED", error_msg)
                except Exception:
                    pass
            return {
                "status": "FAILED",
                "reason": error_msg,
                "error": error_msg,
                "attempt": 1,
                "result": {"status": "failed", "error": error_msg},
            }


domain_handler = DomainHandler()
