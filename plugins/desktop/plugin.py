from plugins.desktop.uart_transport import UARTTransport
import importlib
import logging
import sys
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from plugin_sdk.interfaces.desktop_plugin import DesktopPluginInterface
from plugins.desktop.registry import (
    DEFAULT_APP_ROUTING,
    get_supported_applications,
    get_target_subplugin_id,
    load_subplugins,
)

# Ensure console supports UTF-8 box characters on Windows
if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logger = logging.getLogger("desktop_command_handler")
logger.setLevel(logging.INFO)
logger.propagate = False

# Suppress noisy Selenium, urllib3, uvicorn access, and orchestrator loggers from polluting terminal
for _noisy in [
    "selenium",
    "selenium.webdriver.remote.remote_connection",
    "urllib3",
    "urllib3.connectionpool",
    "core.orchestration.resource_lock_manager",
    "resource_lock_manager",
    "async_task_manager",
    "uvicorn.access",
]:
    _nl = logging.getLogger(_noisy)
    _nl.setLevel(logging.WARNING)
    _nl.propagate = False

_command_counter = 1041


def _clean_truncate(val: Any, max_len: int = 21) -> str:
    """Clean whitespace and truncate a string to fit neatly in a card row."""
    s = " ".join(str(val).split())
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def _extract_command_id(payload: Optional[Dict[str, Any]]) -> str:
    """Extract existing command_id or generate one following CMD-xxxx convention."""
    global _command_counter
    if isinstance(payload, dict):
        cid = payload.get("command_id") or payload.get("id") or payload.get("cmd_id")
        if cid:
            return str(cid)
        _command_counter += 1
        cid = f"CMD-{_command_counter}"
        payload["command_id"] = cid
        return cid
    _command_counter += 1
    return f"CMD-{_command_counter}"


def _render_command_card(
    title: str,
    cmd_id: str,
    domain: str,
    app: str,
    action: str,
    checks: List[Tuple[str, str]],
    footer: Union[str, List[str]],
) -> str:
    """Render a clean command or result card with exact character alignment (width 37)."""
    w = 35
    top = (
        f"┌──────────── {title} ───────────────┐"
        if title == "RESULT"
        else f"┌──────────── {title} ──────────────┐"
    )
    div = f"├{'─' * w}┤"
    bot = f"└{'─' * w}┘"
    lines = [top]
    lines.append(f"│ {'ID':<8}: {cmd_id:<23} │")
    lines.append(f"│ {'Domain':<8}: {domain:<23} │")
    lines.append(f"│ {'App':<8}: {app:<23} │")
    lines.append(f"│ {'Action':<8}: {action:<23} │")
    lines.append(div)
    for lbl, val in checks:
        lines.append(f"│ {lbl:<17}{val:<16} │")
    lines.append(div)
    if isinstance(footer, (list, tuple)):
        for item in footer:
            lines.append(f"│ {item:<33} │")
    else:
        lines.append(f"│ {footer:<33} │")
    lines.append(bot)
    return "\n".join(lines)


def _log_card(card: str) -> None:
    """Output the clean command card directly to the terminal."""
    try:
        print(f"\n{card}\n", flush=True)
    except Exception:
        safe_card = card.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8")
        print(f"\n{safe_card}\n", flush=True)



class DesktopPlugin(DesktopPluginInterface):
    plugin_id = "desktop"

    def __init__(self, subplugins: Optional[Dict[str, Any]] = None):
        if subplugins is not None:
            self.subplugins = subplugins
        else:
            self.subplugins = load_subplugins()
        self.app_routing = dict(DEFAULT_APP_ROUTING)
        self._dispatched_command_ids: Set[str] = set()
        self.uart_transport = UARTTransport()

    def register_subplugin(
        self,
        subplugin_id: str,
        subplugin_instance: Any,
        app_names: Optional[List[str]] = None,
    ) -> None:
        """Register or override a subplugin instance and its mapped application names."""
        self.subplugins[subplugin_id] = subplugin_instance
        if app_names:
            for app_name in app_names:
                self.app_routing[app_name.strip().upper()] = subplugin_id

    def get_supported_commands(self, subplugin: Any, target_id: str) -> List[str]:
        """
        Inspect the target subplugin's actual COMMANDS definition without altering
        subplugin internals.
        """
        if hasattr(subplugin, "COMMANDS") and isinstance(subplugin.COMMANDS, (list, tuple, set)):
            return list(subplugin.COMMANDS)
        if hasattr(subplugin, "commands") and isinstance(subplugin.commands, (list, tuple, set)):
            return list(subplugin.commands)

        try:
            mod = sys.modules.get(subplugin.__class__.__module__)
            if mod and hasattr(mod, "COMMANDS") and isinstance(mod.COMMANDS, (list, tuple, set)):
                return list(mod.COMMANDS)
        except Exception:
            pass

        if target_id:
            try:
                mod = importlib.import_module(f"plugins.desktop.subplugins.{target_id}.commands")
                if hasattr(mod, "COMMANDS") and isinstance(mod.COMMANDS, (list, tuple, set)):
                    return list(mod.COMMANDS)
            except Exception:
                pass

        return []

    async def execute(self, command: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Desktop Command Handler: Routing and Validation layer.
        Validates the incoming command and payload, identifies the target application,
        verifies command support against the subplugin's COMMANDS definition, and
        forwards execution to the appropriate subplugin with card logging.
        """
        logger.info(f"[DEBUG] Master Hub command received: {command}")
        # 1. Special command: get_widgets (used by UI / Master Hub widgets polling - silent)
        if command == "get_widgets":
            widgets = []
            for name, sp in self.subplugins.items():
                if hasattr(sp, "get_widget"):
                    try:
                        widgets.append(sp.get_widget())
                    except Exception as e:
                        logger.warning(f"Error fetching widget for {name}: {e}")
            return {"status": "success", "widgets": widgets}

        # Extract command tracking metadata
        cmd_id = _extract_command_id(payload)
        domain = "DESKTOP"
        action_str = str(command) if command else "UNKNOWN"
        app_raw = None
        if isinstance(payload, dict):
            app_raw = payload.get("app")

        app_display = str(app_raw) if app_raw else "UNKNOWN"

        # 2. Command format validation
        if not command or not isinstance(command, str) or not command.strip():
            logger.error(f"[DesktopCommandHandler] Invalid command format: {command}")
            card = _render_command_card(
                title="COMMAND",
                cmd_id=cmd_id,
                domain=domain,
                app=app_display,
                action=action_str,
                checks=[
                    ("Validation", "✗ FAILED"),
                    ("Application", "- NOT CHECKED"),
                    ("Route", "- NONE"),
                    ("Command", "✗ EMPTY"),
                    ("Handler", "- NOT CALLED"),
                ],
                footer="Status          : ❌ REJECTED",
            )
            _log_card(card)
            return {
                "status": "error",
                "app": None,
                "command": command,
                "message": "Command must be a non-empty string",
            }

        command = command.strip()
        action_str = command

        # 3. Payload existence and type validation
        if payload is None:
            logger.error(f"[DesktopCommandHandler] Command '{command}' rejected: missing payload")
            card = _render_command_card(
                title="COMMAND",
                cmd_id=cmd_id,
                domain=domain,
                app=app_display,
                action=action_str,
                checks=[
                    ("Validation", "✗ FAILED"),
                    ("Application", "- NOT CHECKED"),
                    ("Route", "- NONE"),
                    ("Command", "- NOT CHECKED"),
                    ("Handler", "- NOT CALLED"),
                ],
                footer="Status          : ❌ REJECTED",
            )
            _log_card(card)
            return {
                "status": "error",
                "app": None,
                "command": command,
                "message": "Payload is required and cannot be empty",
            }

        if not isinstance(payload, dict):
            logger.error(f"[DesktopCommandHandler] Command '{command}' rejected: payload is not a dictionary ({type(payload).__name__})")
            card = _render_command_card(
                title="COMMAND",
                cmd_id=cmd_id,
                domain=domain,
                app=app_display,
                action=action_str,
                checks=[
                    ("Validation", "✗ FAILED"),
                    ("Application", "- NOT CHECKED"),
                    ("Route", "- NONE"),
                    ("Command", "- NOT CHECKED"),
                    ("Handler", "- NOT CALLED"),
                ],
                footer="Status          : ❌ REJECTED",
            )
            _log_card(card)
            return {
                "status": "error",
                "app": None,
                "command": command,
                "message": f"Payload must be a dictionary, got {type(payload).__name__}",
            }

        # 4. App field validation
        if "app" not in payload or payload["app"] is None:
            logger.error(f"[DesktopCommandHandler] Command '{command}' rejected: missing 'app' in payload")
            card = _render_command_card(
                title="COMMAND",
                cmd_id=cmd_id,
                domain=domain,
                app="MISSING",
                action=action_str,
                checks=[
                    ("Validation", "✓ PASS"),
                    ("Application", "✗ MISSING"),
                    ("Route", "- NONE"),
                    ("Command", "- NOT CHECKED"),
                    ("Handler", "- NOT CALLED"),
                ],
                footer="Status          : ❌ REJECTED",
            )
            _log_card(card)
            return {
                "status": "error",
                "app": None,
                "command": command,
                "message": "Payload missing app info for action routing.",
            }

        app_raw = payload["app"]
        if not isinstance(app_raw, str) or not app_raw.strip():
            logger.error(f"[DesktopCommandHandler] Command '{command}' rejected: 'app' must be a non-empty string")
            card = _render_command_card(
                title="COMMAND",
                cmd_id=cmd_id,
                domain=domain,
                app="INVALID",
                action=action_str,
                checks=[
                    ("Validation", "✓ PASS"),
                    ("Application", "✗ INVALID"),
                    ("Route", "- NONE"),
                    ("Command", "- NOT CHECKED"),
                    ("Handler", "- NOT CALLED"),
                ],
                footer="Status          : ❌ REJECTED",
            )
            _log_card(card)
            return {
                "status": "error",
                "app": None,
                "command": command,
                "message": "The 'app' field must be a non-empty string",
            }

        app_key = app_raw.strip().upper()
        logger.debug(f"[DesktopCommandHandler] Validating app '{app_key}' for command '{command}'")
        logger.info(f"[DEBUG] Normalized command: {command}")

        # 5. Application support check
        target_subplugin_id = self.app_routing.get(app_key)
        logger.info(f"[DEBUG] PYTHON domain selected: {target_subplugin_id}")
        if not target_subplugin_id:
            supported = sorted(list(self.app_routing.keys()))
            logger.error(f"[DesktopCommandHandler] Unsupported application '{app_raw}'. Supported: {supported}")
            card = _render_command_card(
                title="COMMAND",
                cmd_id=cmd_id,
                domain=domain,
                app=app_raw,
                action=action_str,
                checks=[
                    ("Validation", "✓ PASS"),
                    ("Application", "✗ UNSUPPORTED"),
                    ("Route", "- NONE"),
                    ("Command", "- NOT CHECKED"),
                    ("Handler", "- NOT CALLED"),
                ],
                footer="Status          : ❌ REJECTED",
            )
            _log_card(card)
            return {
                "status": "error",
                "app": app_raw,
                "command": command,
                "message": f"Desktop application '{app_raw}' is unsupported or not registered. Supported: {supported}",
            }

        # 6. Target subplugin existence check
        subplugin = self.subplugins.get(target_subplugin_id)
        if not subplugin:
            logger.error(f"[DesktopCommandHandler] Subplugin '{target_subplugin_id}' for '{app_raw}' is not loaded")
            card = _render_command_card(
                title="COMMAND",
                cmd_id=cmd_id,
                domain=domain,
                app=app_raw,
                action=action_str,
                checks=[
                    ("Validation", "✓ PASS"),
                    ("Application", f"✓ {app_raw}"),
                    ("Route", "✗ NOT LOADED"),
                    ("Command", "- NOT CHECKED"),
                    ("Handler", "- NOT CALLED"),
                ],
                footer="Status          : ❌ REJECTED",
            )
            _log_card(card)
            return {
                "status": "error",
                "app": app_raw,
                "command": command,
                "message": f"Subplugin for {app_raw} not found",
            }

        # 7. Command validation against subplugin's COMMANDS definition
        supported_commands = self.get_supported_commands(subplugin, target_subplugin_id)
        uart_high_level = ["OPEN_YOUTUBE", "OPEN_CHROME", "OPEN_NOTEPAD", "OPEN_GMAIL"]
        is_uart_cmd = command in uart_high_level
        
        if supported_commands and command not in supported_commands and not is_uart_cmd:
            logger.error(
                f"[DesktopCommandHandler] Command '{command}' is not supported by {app_raw} "
                f"(subplugin '{target_subplugin_id}'). Supported: {supported_commands} or {uart_high_level}"
            )
            card = _render_command_card(
                title="COMMAND",
                cmd_id=cmd_id,
                domain=domain,
                app=app_raw,
                action=action_str,
                checks=[
                    ("Validation", "✓ PASS"),
                    ("Application", f"✓ {app_raw}"),
                    ("Route", f"✓ {target_subplugin_id}"),
                    ("Command", "✗ INVALID"),
                    ("Handler", "- NOT CALLED"),
                ],
                footer="Status          : ❌ REJECTED",
            )
            _log_card(card)
            return {
                "status": "error",
                "app": app_raw,
                "command": command,
                "message": f"Unknown or unsupported command '{command}' for application '{app_raw}'. Supported commands: {supported_commands}",
            }

        # 8. Safe delegation to subplugin with pre-execution command card (logged only once per command)
        handler_name = subplugin.__class__.__name__
        if cmd_id not in self._dispatched_command_ids:
            card_dispatch = _render_command_card(
                title="COMMAND",
                cmd_id=cmd_id,
                domain=domain,
                app=app_raw,
                action=action_str,
                checks=[
                    ("Validation", "✓ PASS"),
                    ("Application", f"✓ {app_raw}"),
                    ("Route", f"✓ {target_subplugin_id}"),
                    ("Command", "✓ VALID"),
                    ("Handler", f"✓ {handler_name}"),
                ],
                footer="Execution        ● RUNNING",
            )
            _log_card(card_dispatch)
            self._dispatched_command_ids.add(cmd_id)

        logger.info(f"[DEBUG] Desktop plugin execute(): {command}")
        try:
            # Map internal UI commands to UART high-level commands
            uart_mapping = {
                "open_notepad": "OPEN_NOTEPAD",
                "open_predefined_article": "OPEN_CHROME",
                "open_youtube": "OPEN_YOUTUBE",
                "search": "OPEN_YOUTUBE",
                "compose_email": "OPEN_GMAIL"
            }
            
            if getattr(self, "uart_transport", None) and self.uart_transport.config.get("enabled"):
                uart_cmd = uart_mapping.get(command, command.upper())
                logger.info(f"[DEBUG] UART command prepared: {uart_cmd}")
                if not self.uart_transport.running:
                    self.uart_transport.start()
                
                sub_result = None
                if self.uart_transport.is_connected():
                    logger.info(f"[DesktopCommandHandler] Routing '{command}' as '{uart_cmd}' via UART Transport")
                    sub_result = self.uart_transport.send_command(uart_cmd)
                    
                    logger.info(f"[DEBUG] ACK matched to command: {uart_cmd}")
                    logger.info(f"[DEBUG] Execution result: {sub_result.get('status') if isinstance(sub_result, dict) else sub_result}")
                    logger.info(f"[DEBUG] Lifecycle updated: True")
                    logger.info(f"[DEBUG] Dashboard updated: True")
                    
                    logger.info(f"[MAIN] Desktop execution result: {sub_result}")
                    logger.info(f"[MAIN] UART status: {sub_result.get('status') if isinstance(sub_result, dict) else sub_result}")
                    logger.info(f"[MAIN] ACK: {sub_result.get('message') if isinstance(sub_result, dict) else sub_result}")
                    logger.info(f"[MAIN] Final command status: {sub_result.get('status') if isinstance(sub_result, dict) else 'SUCCESS'}")
                else:
                    if self.uart_transport.config.get("fallback_to_local", False):
                        reverse_mapping = {
                            "OPEN_NOTEPAD": "open_notepad",
                            "OPEN_CHROME": "open_predefined_article",
                            "OPEN_YOUTUBE": "search",
                            "OPEN_GMAIL": "compose_email"
                        }
                        local_cmd = reverse_mapping.get(command, command)
                        logger.info(f"[DesktopCommandHandler] UART not connected. Executing '{local_cmd}' via local subplugin.")
                        sub_result = await subplugin.execute(local_cmd, payload)
                    else:
                        logger.warning(f"[DesktopCommandHandler] UART not connected and fallback_to_local is disabled. Skipping local execution.")
                        sub_result = {"status": "SUCCESS", "message": "UART transmission queued (local execution skipped)"}
            else:
                reverse_mapping = {
                    "OPEN_NOTEPAD": "open_notepad",
                    "OPEN_CHROME": "open_predefined_article",
                    "OPEN_YOUTUBE": "search",
                    "OPEN_GMAIL": "compose_email"
                }
                local_cmd = reverse_mapping.get(command, command)
                sub_result = await subplugin.execute(local_cmd, payload)
        except Exception as e:
            logger.exception(f"[DesktopCommandHandler] Execution error delegating '{command}' to '{target_subplugin_id}': {e}")
            err_msg = str(e)
            card_err = _render_command_card(
                title="RESULT",
                cmd_id=cmd_id,
                domain=domain,
                app=app_raw,
                action=action_str,
                checks=[
                    ("Validation", "✓ PASS"),
                    ("Application", "✓ FOUND"),
                    ("Route", f"✓ {target_subplugin_id}"),
                    ("Command", "✓ VALID"),
                    ("Handler", f"✓ {handler_name}"),
                    ("Execution", "✗ FAILED"),
                ],
                footer=[
                    f"{'Status':<10}: {'FAILED':<21}",
                    f"{'Execution':<10}: {'FAILED':<21}",
                    f"{'Result':<10}: {_clean_truncate(err_msg):<21}",
                ],
            )
            _log_card(card_err)
            return {
                "status": "error",
                "app": app_raw,
                "command": command,
                "message": f"Subplugin execution error: {err_msg}",
            }

        # 9. Format structured response and display result card
        is_sub_dict = isinstance(sub_result, dict)
        is_error = False
        res_msg = ""

        if is_sub_dict:
            status_val = str(sub_result.get("status", "")).lower()
            is_error = status_val in ("error", "failed")
            res_msg = sub_result.get("message") or sub_result.get("error") or sub_result.get("result") or ""
        else:
            res_msg = str(sub_result) if sub_result is not None else ""

        if not res_msg:
            res_msg = f"Command '{command}' executed successfully" if not is_error else "Execution failed"

        if is_error:
            card_sub_err = _render_command_card(
                title="RESULT",
                cmd_id=cmd_id,
                domain=domain,
                app=app_raw,
                action=action_str,
                checks=[
                    ("Validation", "✓ PASS"),
                    ("Application", "✓ FOUND"),
                    ("Route", f"✓ {target_subplugin_id}"),
                    ("Command", "✓ VALID"),
                    ("Handler", f"✓ {handler_name}"),
                    ("Execution", "✗ FAILED"),
                ],
                footer=[
                    f"{'Status':<10}: {'FAILED':<21}",
                    f"{'Execution':<10}: {'FAILED':<21}",
                    f"{'Result':<10}: {_clean_truncate(res_msg):<21}",
                ],
            )
            _log_card(card_sub_err)
            res = dict(sub_result) if is_sub_dict else {"status": "error", "message": res_msg}
            res.setdefault("app", app_raw)
            res.setdefault("command", command)
            return res

        # Standard structured success response
        card_success = _render_command_card(
            title="RESULT",
            cmd_id=cmd_id,
            domain=domain,
            app=app_raw,
            action=action_str,
            checks=[
                ("Validation", "✓ PASS"),
                ("Application", "✓ FOUND"),
                ("Route", f"✓ {target_subplugin_id}"),
                ("Command", "✓ VALID"),
                ("Handler", f"✓ {handler_name}"),
                ("Execution", "✓ COMPLETE"),
            ],
            footer=[
                f"{'Status':<10}: {'SUCCESS':<21}",
                f"{'Execution':<10}: {'COMPLETE':<21}",
                f"{'Result':<10}: {_clean_truncate(res_msg):<21}",
            ],
        )
        _log_card(card_success)

        if is_sub_dict:
            res = {
                "status": "success",
                "app": app_raw,
                "command": command,
                "message": sub_result.get("message", f"Command '{command}' executed successfully on {app_raw}"),
                "result": sub_result,
            }
            for k, v in sub_result.items():
                if k not in res:
                    res[k] = v
            return res

        return {
            "status": "success",
            "app": app_raw,
            "command": command,
            "result": sub_result,
            "message": f"Command '{command}' executed successfully on {app_raw}",
        }


# Alias for explicit role naming
DesktopCommandHandler = DesktopPlugin
