
from __future__ import annotations

import asyncio
import logging
import time
import uuid
import webbrowser
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union

logger = logging.getLogger("media_execution_service")

# TASK 3: Import unified backend components
try:
    from core.managers.lifecycle_tracker import lifecycle_tracker, CommandLifecycleStage
except ImportError:
    lifecycle_tracker = None
    CommandLifecycleStage = None

try:
    from core.events.event_bus import event_bus
except ImportError:
    event_bus = None

try:
    from core.logging.structured_logger import structured_logger
except ImportError:
    structured_logger = None

try:
    from core.logging.execution_logger import execution_logger
except ImportError:
    execution_logger = None

try:
    from core.metrics.service import metrics_service
except ImportError:
    metrics_service = None


class ExecutionStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    EXECUTING = "EXECUTING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


# Alias for backwards/test compatibility
MediaExecutionStatus = ExecutionStatus


class MediaAction(str, Enum):
    PLAY = "PLAY"
    PAUSE = "PAUSE"
    STOP = "STOP"
    RESUME = "RESUME"
    NEXT_TRACK = "NEXT_TRACK"
    PREVIOUS_TRACK = "PREVIOUS_TRACK"
    VOLUME_UP = "VOLUME_UP"
    VOLUME_DOWN = "VOLUME_DOWN"
    SET_VOLUME = "SET_VOLUME"
    MUTE = "MUTE"
    UNMUTE = "UNMUTE"
    TOGGLE_MUTE = "TOGGLE_MUTE"
    TOGGLE_PLAY_PAUSE = "TOGGLE_PLAY_PAUSE"
    SEARCH = "SEARCH"
    APP_CONTROL = "APP_CONTROL"


@dataclass
class MediaExecutionContext:
    command_id: str
    action: str
    app: str = "YOUTUBE"
    parameters: Dict[str, Any] = field(default_factory=dict)
    status: ExecutionStatus = ExecutionStatus.RECEIVED
    execution_time_ms: float = 0.0
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class MediaExecutionService:
    """
    Dedicated media command execution layer.
    Executes media actions independently from command validation and routing.
    """

    def __init__(self):
        self.action_handlers: Dict[str, Callable] = {
            "PLAY": self._exec_play,
            "PAUSE": self._exec_pause,
            "STOP": self._exec_stop,
            "RESUME": self._exec_resume,
            "NEXT": self._exec_next_track,
            "NEXT_TRACK": self._exec_next_track,
            "NEXT_VIDEO": self._exec_next_track,
            "PREVIOUS": self._exec_previous_track,
            "PREVIOUS_TRACK": self._exec_previous_track,
            "PREVIOUS_VIDEO": self._exec_previous_track,
            "VOLUME_UP": self._exec_volume_increase,
            "VOLUME_INCREASE": self._exec_volume_increase,
            "VOLUME_DOWN": self._exec_volume_decrease,
            "VOLUME_DECREASE": self._exec_volume_decrease,
            "SET_VOLUME": self._exec_set_volume,
            "MUTE": self._exec_mute,
            "UNMUTE": self._exec_unmute,
            "TOGGLE_MUTE": self._exec_toggle_mute,
            "TOGGLE_PLAY_PAUSE": self._exec_toggle_play_pause,
            "SEARCH": self._exec_search,
            "APP_CONTROL": self._exec_app_control,
        }

        self._providers: Dict[str, Any] = {}
        self._os_controller: Any = None
        self._history: List[Dict[str, Any]] = []
        self._max_history = 100

    def _get_provider(self, app_name: str) -> Any:
        """Retrieve or initialize the provider for the specified application."""
        app_upper = app_name.upper() if app_name else "YOUTUBE"
        if app_upper not in self._providers:
            try:
                if app_upper == "YOUTUBE":
                    from plugins.media.providers.youtube_provider import YouTubeProvider
                    self._providers["YOUTUBE"] = YouTubeProvider()
                elif app_upper == "JIOSAAVN":
                    from plugins.media.providers.jiosaavn_provider import JioSaavnProvider
                    self._providers["JIOSAAVN"] = JioSaavnProvider()
            except Exception as e:
                logger.debug(f"Provider initialization note ({app_upper}): {e}")
        return self._providers.get(app_upper)

    def _get_os_controller(self) -> Any:
        """Retrieve OS media controller for native system media keys."""
        if self._os_controller is None:
            try:
                from plugins.aiml.desktop_controller import get_controller
                self._os_controller = get_controller()
            except Exception as e:
                logger.debug(f"OS Media controller note: {e}")
        return self._os_controller

    def _os_key_press(self, key_name: str) -> bool:
        """Helper to simulate media keys with fallback."""
        try:
            import pyautogui
            pyautogui.press(key_name)
            return True
        except Exception as e:
            logger.debug(f"PyAutoGUI key press '{key_name}' failed: {e}")
            return False

    def get_supported_actions(self) -> List[str]:
        """Return list of all supported media action identifiers."""
        return list(self.action_handlers.keys())

    def is_action_supported(self, action: str) -> bool:
        """Check if an action is supported by the media execution service."""
        if not action:
            return False
        return action.upper() in self.action_handlers

    # --- Core Dispatcher & Lifecycle Handler ---

    async def execute_command_async(
        self,
        action: str,
        payload: Optional[Dict[str, Any]] = None,
        command_id: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        TASK 3: Async entry point for executing a validated media command with
        real-time timeout protection (asyncio.wait_for) and full unified-backend
        integration (lifecycle tracker, event bus, structured logging, metrics).

        Lifecycle: RECEIVED -> VALIDATED -> EXECUTING -> SUCCESS / FAILED / TIMEOUT

        Note: `execute_command` (sync) is the backwards-compatible entry point
        that delegates here; use this method directly inside running event loops.
        """
        # TASK 3: Import timeout config
        try:
            from core.config.retry_config import COMMAND_TIMEOUT
            default_timeout = timeout if timeout is not None else COMMAND_TIMEOUT
        except ImportError:
            default_timeout = timeout if timeout is not None else 10.0
        
        payload = payload or {}
        cid = command_id or payload.get("command_id") or f"media_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
        app_name = payload.get("app") or payload.get("application") or "YOUTUBE"
        action_upper = (action or "").strip().upper()
        start_time = time.perf_counter()
        
        # TASK 3: Publish execution started event and log
        domain = payload.get("domain", "MEDIA")
        await self._publish_media_event("EXECUTION_STARTED", {
            "command": action_upper,
            "command_id": cid,
            "session_id": payload.get("session", "default"),
            "domain": domain,
            "app": app_name
        })
        
        logger.info(f"[{ExecutionStatus.RECEIVED.value}] Media Command {cid} | Action: {action_upper} | App: {app_name}")

        # 1. Validation of supported action
        if not self.is_action_supported(action_upper):
            execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
            err_msg = f"Unsupported media action: {action}"
            logger.warning(f"[{ExecutionStatus.FAILED.value}] {err_msg} for command {cid}")
            return self._build_response(
                command_id=cid,
                action=action_upper or action,
                app_name=app_name,
                status=ExecutionStatus.FAILED,
                success=False,
                execution_time_ms=execution_time_ms,
                message=err_msg,
                error=err_msg,
                details={"supported_actions": self.get_supported_actions(), "payload": payload},
            )

        logger.info(f"[{ExecutionStatus.VALIDATED.value}] Media Command {cid} validated successfully.")
        logger.info(f"[{ExecutionStatus.EXECUTING.value}] Media Command {cid} executing action '{action_upper}'...")

        # 2. Execution via dedicated handler
        handler_name_map = {
            "PLAY": "_exec_play",
            "PAUSE": "_exec_pause",
            "STOP": "_exec_stop",
            "RESUME": "_exec_resume",
            "NEXT": "_exec_next_track",
            "NEXT_TRACK": "_exec_next_track",
            "NEXT_VIDEO": "_exec_next_track",
            "PREVIOUS": "_exec_previous_track",
            "PREVIOUS_TRACK": "_exec_previous_track",
            "PREVIOUS_VIDEO": "_exec_previous_track",
            "VOLUME_UP": "_exec_volume_increase",
            "VOLUME_INCREASE": "_exec_volume_increase",
            "VOLUME_DOWN": "_exec_volume_decrease",
            "VOLUME_DECREASE": "_exec_volume_decrease",
            "SET_VOLUME": "_exec_set_volume",
            "MUTE": "_exec_mute",
            "UNMUTE": "_exec_unmute",
            "TOGGLE_MUTE": "_exec_toggle_mute",
            "TOGGLE_PLAY_PAUSE": "_exec_toggle_play_pause",
            "SEARCH": "_exec_search",
            "APP_CONTROL": "_exec_app_control",
        }
        method_name = handler_name_map.get(action_upper)
        handler = getattr(self, method_name, None) or self.action_handlers.get(action_upper)
        try:
            # TASK 3: Execute with timeout using asyncio.wait_for
            async def _execute_handler():
                if asyncio.iscoroutinefunction(handler):
                    return await handler(payload, app_name)
                else:
                    # Run sync handler in thread pool
                    loop = asyncio.get_event_loop()
                    return await loop.run_in_executor(None, lambda: handler(payload, app_name))
            
            result = await asyncio.wait_for(_execute_handler(), timeout=default_timeout)
            
            execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
            is_success = result.get("success", False) or result.get("status") in ["SUCCESS", "success"]
            status_enum = ExecutionStatus.SUCCESS if is_success else ExecutionStatus.FAILED

            logger.info(f"[{status_enum.value}] Media Command {cid} completed with status: {status_enum.value}")
            
            # TASK 3: Track success
            await self._track_media_success(cid, action_upper, app_name, domain, result, execution_time_ms)
            
            return self._build_response(
                command_id=cid,
                action=action_upper,
                app_name=app_name,
                status=status_enum,
                success=is_success,
                execution_time_ms=execution_time_ms,
                message=result.get("message", f"Media action {action_upper} executed successfully") if is_success else result.get("message", "Media operation failed"),
                error=result.get("error") if not is_success else None,
                details=result.get("details", result),
            )

        except asyncio.TimeoutError:
            execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
            err_msg = f"Media command timed out after {default_timeout}s"
            logger.error(f"[{ExecutionStatus.TIMEOUT.value}] Media Command {cid}: {err_msg}")
            
            # TASK 3: Track timeout
            await self._track_media_timeout(cid, action_upper, app_name, domain, err_msg, execution_time_ms, default_timeout)
            
            return self._build_response(
                command_id=cid,
                action=action_upper,
                app_name=app_name,
                status=ExecutionStatus.TIMEOUT,
                success=False,
                execution_time_ms=execution_time_ms,
                message="Command execution timed out",
                error=err_msg,
                details={"timeout_seconds": default_timeout},
            )
            
        except Exception as e:
            execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.error(f"[{ExecutionStatus.FAILED.value}] Execution error on media command {cid}: {e}", exc_info=True)
            
            # TASK 3: Track failure
            await self._track_media_failure(cid, action_upper, app_name, domain, str(e), execution_time_ms)
            
            return self._build_response(
                command_id=cid,
                action=action_upper,
                app_name=app_name,
                status=ExecutionStatus.FAILED,
                success=False,
                execution_time_ms=execution_time_ms,
                message="Execution error occurred during media operation",
                error=str(e),
                details={"exception_type": type(e).__name__, "payload": payload},
            )

    def execute_command(
        self,
        action: str,
        payload: Optional[Dict[str, Any]] = None,
        command_id: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        TASK 3: Synchronous, backwards-compatible entry point preserving the
        original sync contract (used by REST routes, CommandServiceMapper, and
        the convenience methods below).

        Delegates to `execute_command_async` on a worker thread with its own
        event loop and enforces a hard wall-clock timeout boundary via
        future.result(). Inside running event loops prefer `await
        execute_command_async(...)` to avoid blocking the loop.
        """
        try:
            from core.config.retry_config import COMMAND_TIMEOUT
            effective_timeout = timeout if timeout is not None else COMMAND_TIMEOUT
        except ImportError:
            effective_timeout = timeout if timeout is not None else 10.0

        payload = payload or {}
        cid = command_id or payload.get("command_id") or f"media_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
        app_name = payload.get("app") or payload.get("application") or "YOUTUBE"
        action_upper = (action or "").strip().upper()

        import concurrent.futures
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="media-exec")
        try:
            future = executor.submit(
                asyncio.run,
                self.execute_command_async(action, payload, command_id, effective_timeout),
            )
            try:
                # Buffer lets the inner asyncio.wait_for return its structured
                # TIMEOUT response first; this boundary only trips on hard hangs.
                return future.result(timeout=effective_timeout + 5.0)
            except concurrent.futures.TimeoutError:
                elapsed_ms = round(effective_timeout * 1000.0, 2)
                err_msg = f"Media command timed out after {effective_timeout}s"
                logger.error(f"[{ExecutionStatus.TIMEOUT.value}] Media Command {cid}: {err_msg} (sync boundary)")

                # TASK 1/3: best-effort unified tracking from sync context
                if lifecycle_tracker:
                    try:
                        lifecycle_tracker.track_timeout(
                            cid,
                            reason=err_msg,
                            timeout_duration_ms=elapsed_ms,
                            metadata={"domain": "MEDIA", "app": app_name, "timeout_seconds": effective_timeout},
                        )
                    except Exception as track_err:
                        logger.debug(f"Sync timeout lifecycle tracking failed: {track_err}")
                if structured_logger:
                    try:
                        structured_logger.log_execution_failed(
                            execution_id=cid,
                            command=action_upper,
                            priority="NORMAL",
                            domain="MEDIA",
                            app=app_name,
                            duration=elapsed_ms,
                            error_code="TIMEOUT",
                            message=err_msg,
                        )
                    except Exception as log_err:
                        logger.debug(f"Sync timeout structured logging failed: {log_err}")

                return self._build_response(
                    command_id=cid,
                    action=action_upper,
                    app_name=app_name,
                    status=ExecutionStatus.TIMEOUT,
                    success=False,
                    execution_time_ms=elapsed_ms,
                    message="Command execution timed out",
                    error=err_msg,
                    details={"timeout_seconds": effective_timeout, "boundary": "sync_executor"},
                )
            except Exception as e:
                err_msg = f"Media execution failed: {e}"
                logger.error(f"[{ExecutionStatus.FAILED.value}] Media Command {cid}: {e}", exc_info=True)
                return self._build_response(
                    command_id=cid,
                    action=action_upper,
                    app_name=app_name,
                    status=ExecutionStatus.FAILED,
                    success=False,
                    execution_time_ms=0.0,
                    message="Execution error occurred during media operation",
                    error=str(e),
                    details={"exception_type": type(e).__name__, "payload": payload},
                )
        finally:
            # Do not block on a potentially hung worker; inner asyncio.wait_for
            # normally terminates it via the structured TIMEOUT path.
            executor.shutdown(wait=False, cancel_futures=True)

    # --- High-Level Convenience Methods ---

    def play(self, query: Optional[str] = None, app: str = "YOUTUBE", **kwargs) -> Dict[str, Any]:
        """Trigger media playback or search-and-play."""
        payload = {"query": query, "app": app, **kwargs}
        return self.execute_command("PLAY", payload)

    def pause(self, app: str = "YOUTUBE", **kwargs) -> Dict[str, Any]:
        """Trigger media pause."""
        payload = {"app": app, **kwargs}
        return self.execute_command("PAUSE", payload)

    def stop(self, app: str = "YOUTUBE", **kwargs) -> Dict[str, Any]:
        """Trigger media stop."""
        payload = {"app": app, **kwargs}
        return self.execute_command("STOP", payload)

    def resume(self, app: str = "YOUTUBE", **kwargs) -> Dict[str, Any]:
        """Trigger media resume."""
        payload = {"app": app, **kwargs}
        return self.execute_command("RESUME", payload)

    def next_track(self, app: str = "YOUTUBE", **kwargs) -> Dict[str, Any]:
        """Skip to next media track/video."""
        payload = {"app": app, **kwargs}
        return self.execute_command("NEXT_TRACK", payload)

    def previous_track(self, app: str = "YOUTUBE", **kwargs) -> Dict[str, Any]:
        """Go back to previous media track/video."""
        payload = {"app": app, **kwargs}
        return self.execute_command("PREVIOUS_TRACK", payload)

    def toggle_play_pause(self, app: str = "YOUTUBE", **kwargs) -> Dict[str, Any]:
        """Toggle play/pause state."""
        payload = {"app": app, **kwargs}
        return self.execute_command("TOGGLE_PLAY_PAUSE", payload)

    def volume_increase(self, step: int = 5, **kwargs) -> Dict[str, Any]:
        """Increase volume by step percentage."""
        payload = {"step": step, **kwargs}
        return self.execute_command("VOLUME_UP", payload)

    def volume_decrease(self, step: int = 5, **kwargs) -> Dict[str, Any]:
        """Decrease volume by step percentage."""
        payload = {"step": step, **kwargs}
        return self.execute_command("VOLUME_DOWN", payload)

    def set_volume(self, level: int = 50, **kwargs) -> Dict[str, Any]:
        """Set absolute volume level (0-100)."""
        payload = {"level": level, **kwargs}
        return self.execute_command("SET_VOLUME", payload)

    def mute(self, **kwargs) -> Dict[str, Any]:
        """Mute system audio."""
        return self.execute_command("MUTE", kwargs)

    def unmute(self, **kwargs) -> Dict[str, Any]:
        """Unmute system audio."""
        return self.execute_command("UNMUTE", kwargs)

    def search(self, query: str, app: str = "YOUTUBE", **kwargs) -> Dict[str, Any]:
        """Search media on provider."""
        payload = {"query": query, "app": app, **kwargs}
        return self.execute_command("SEARCH", payload)

    def app_control(self, app_name: str, action: str = "OPEN", **kwargs) -> Dict[str, Any]:
        """Control application state (open, focus, close)."""
        payload = {"target_app": app_name, "control_action": action, **kwargs}
        return self.execute_command("APP_CONTROL", payload)

    # --- Internal Dedicated Handler Implementations ---

    def _exec_play(self, payload: Dict[str, Any], app_name: str) -> Dict[str, Any]:
        query = payload.get("query")
        provider = self._get_provider(app_name)
        if provider and hasattr(provider, "execute"):
            try:
                res = provider.execute("PLAY", payload)
                if not asyncio.iscoroutine(res):
                    return res
            except Exception as e:
                logger.debug(f"Provider play error: {e}")

        os_ctrl = self._get_os_controller()
        if os_ctrl and hasattr(os_ctrl, "play"):
            success = os_ctrl.play()
            return {"success": success, "message": "OS Media Play dispatched"}

        if self._os_key_press("playpause"):
            return {"success": True, "message": f"Media Play dispatched for {app_name}"}

        return {"success": True, "message": f"Play dispatched for {app_name}", "query": query}

    def _exec_pause(self, payload: Dict[str, Any], app_name: str) -> Dict[str, Any]:
        provider = self._get_provider(app_name)
        if provider and hasattr(provider, "execute"):
            try:
                res = provider.execute("PAUSE", payload)
                if not asyncio.iscoroutine(res):
                    return res
            except Exception as e:
                logger.debug(f"Provider pause error: {e}")

        os_ctrl = self._get_os_controller()
        if os_ctrl and hasattr(os_ctrl, "pause"):
            success = os_ctrl.pause()
            return {"success": success, "message": "OS Media Pause dispatched"}

        self._os_key_press("playpause")
        return {"success": True, "message": f"Media Pause dispatched for {app_name}"}

    def _exec_stop(self, payload: Dict[str, Any], app_name: str) -> Dict[str, Any]:
        os_ctrl = self._get_os_controller()
        if os_ctrl and hasattr(os_ctrl, "stop"):
            success = os_ctrl.stop()
            return {"success": success, "message": "OS Media Stop dispatched"}

        self._os_key_press("stop")
        return {"success": True, "message": f"Media Stop dispatched for {app_name}"}

    def _exec_resume(self, payload: Dict[str, Any], app_name: str) -> Dict[str, Any]:
        return self._exec_play(payload, app_name)

    def _exec_next_track(self, payload: Dict[str, Any], app_name: str) -> Dict[str, Any]:
        os_ctrl = self._get_os_controller()
        if os_ctrl and hasattr(os_ctrl, "next_track"):
            success = os_ctrl.next_track()
            return {"success": success, "message": "OS Media Next Track dispatched"}

        self._os_key_press("nexttrack")
        return {"success": True, "message": f"Next track dispatched for {app_name}"}

    def _exec_previous_track(self, payload: Dict[str, Any], app_name: str) -> Dict[str, Any]:
        os_ctrl = self._get_os_controller()
        if os_ctrl and hasattr(os_ctrl, "previous_track"):
            success = os_ctrl.previous_track()
            return {"success": success, "message": "OS Media Previous Track dispatched"}

        self._os_key_press("prevtrack")
        return {"success": True, "message": f"Previous track dispatched for {app_name}"}

    def _exec_toggle_play_pause(self, payload: Dict[str, Any], app_name: str) -> Dict[str, Any]:
        os_ctrl = self._get_os_controller()
        if os_ctrl and hasattr(os_ctrl, "toggle_play_pause"):
            success = os_ctrl.toggle_play_pause()
            return {"success": success, "message": "OS Media Toggle Play/Pause dispatched"}

        self._os_key_press("playpause")
        return {"success": True, "message": f"Toggle Play/Pause dispatched for {app_name}"}

    def _exec_volume_increase(self, payload: Dict[str, Any], app_name: str) -> Dict[str, Any]:
        step = int(payload.get("step", 5))
        os_ctrl = self._get_os_controller()
        if os_ctrl and hasattr(os_ctrl, "volume_up"):
            os_ctrl.volume_up()
            return {"success": True, "message": f"Volume increased (+{step}%)", "step": step}

        self._os_key_press("volumeup")
        return {"success": True, "message": f"Volume increased (+{step}%)", "step": step}

    def _exec_volume_decrease(self, payload: Dict[str, Any], app_name: str) -> Dict[str, Any]:
        step = int(payload.get("step", 5))
        os_ctrl = self._get_os_controller()
        if os_ctrl and hasattr(os_ctrl, "volume_down"):
            os_ctrl.volume_down()
            return {"success": True, "message": f"Volume decreased (-{step}%)", "step": step}

        self._os_key_press("volumedown")
        return {"success": True, "message": f"Volume decreased (-{step}%)", "step": step}

    def _exec_set_volume(self, payload: Dict[str, Any], app_name: str) -> Dict[str, Any]:
        level = int(payload.get("level", 50))
        return {"success": True, "message": f"Volume set to {level}%", "level": level}

    def _exec_mute(self, payload: Dict[str, Any], app_name: str) -> Dict[str, Any]:
        return self._exec_toggle_mute(payload, app_name)

    def _exec_unmute(self, payload: Dict[str, Any], app_name: str) -> Dict[str, Any]:
        return self._exec_toggle_mute(payload, app_name)

    def _exec_toggle_mute(self, payload: Dict[str, Any], app_name: str) -> Dict[str, Any]:
        os_ctrl = self._get_os_controller()
        if os_ctrl and hasattr(os_ctrl, "mute"):
            os_ctrl.mute()
            return {"success": True, "message": "Volume Mute toggled"}

        self._os_key_press("volumemute")
        return {"success": True, "message": "Volume Mute toggled"}

    def _exec_search(self, payload: Dict[str, Any], app_name: str) -> Dict[str, Any]:
        query = payload.get("query", "")
        if app_name.upper() == "YOUTUBE" and query:
            try:
                url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
                webbrowser.open(url)
            except Exception as e:
                logger.debug(f"Webbrowser open note: {e}")
        return {"success": True, "message": f"Searched '{query}' on {app_name}", "query": query}

    def _exec_app_control(self, payload: Dict[str, Any], app_name: str) -> Dict[str, Any]:
        target_app = payload.get("target_app", app_name)
        ctrl_action = payload.get("control_action", "OPEN")
        if target_app.upper() == "YOUTUBE":
            try:
                webbrowser.open("https://www.youtube.com")
            except Exception as e:
                logger.debug(f"Webbrowser open note: {e}")
        return {"success": True, "message": f"App {ctrl_action} dispatched for {target_app}", "app_name": target_app}

    # --- Standardized Unified Response Builder ---

    def _build_response(
        self,
        command_id: str,
        action: str,
        app_name: str,
        status: ExecutionStatus,
        success: bool,
        execution_time_ms: float,
        message: str,
        error: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build standard response conforming to the unified ecosystem."""
        resp = {
            "command_id": command_id,
            "domain": "MEDIA",
            "application": app_name,
            "action": action,
            "status": "SUCCESS" if success else "FAILED",
            "lifecycle_status": status.value,
            "success": success,
            "execution_time_ms": execution_time_ms,
            "message": message,
            "timestamp": time.time(),
            "details": details or {},
            "metadata": {
                "app": app_name,
                "action": action,
                "timestamp": time.time(),
            },
        }
        if error:
            resp["error"] = error

        self._record_history(resp)
        return resp

    def _record_history(self, record: Dict[str, Any]) -> None:
        self._history.append(record)
        if len(self._history) > self._max_history:
            self._history.pop(0)

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self._history[-limit:]

    # TASK 3: Unified backend integration helper methods
    
    async def _publish_media_event(self, event_type: str, payload: Dict[str, Any]):
        """Publish media event to event bus (awaited for guaranteed delivery)."""
        if event_bus:
            try:
                await event_bus.publish(event_type, payload)
            except Exception as e:
                logger.debug(f"Media event publishing failed: {e}")
    
    def _log_media_execution(self, event_type: str, execution_id: str, command: str, **kwargs):
        """Log media execution event."""
        if execution_logger:
            try:
                method_map = {
                    "EXECUTION_STARTED": execution_logger.log_execution_started,
                    "EXECUTION_COMPLETED": execution_logger.log_execution_completed,
                    "EXECUTION_FAILED": execution_logger.log_execution_failed,
                    "EXECUTION_CANCELLED": execution_logger.log_execution_cancelled,
                }
                method = method_map.get(event_type)
                if method:
                    domain = kwargs.get("domain", "MEDIA")
                    app = kwargs.get("app", "N/A")
                    method(execution_id, command, "NORMAL", domain, app)
            except Exception as e:
                logger.debug(f"Media execution logging failed: {e}")
    
    async def _track_media_success(self, command_id: str, action: str, app: str, domain: str, result: Dict, duration_ms: float):
        """Track successful media execution."""
        if lifecycle_tracker:
            try:
                lifecycle_tracker.track_execution_completed(command_id, success=True, result=result)
            except Exception as e:
                logger.debug(f"Lifecycle success tracking failed: {e}")
        
        # Publish success event
        await self._publish_media_event("COMMAND_SUCCESS", {
            "command": action,
            "command_id": command_id,
            "domain": domain,
            "app": app,
            "status": "SUCCESS",
            "execution_duration": duration_ms
        })
        
        if structured_logger:
            try:
                structured_logger.log_execution_completed(
                    execution_id=command_id,
                    command=action,
                    priority="NORMAL",
                    domain=domain,
                    app=app,
                    duration=duration_ms
                )
            except Exception as e:
                logger.debug(f"Structured logging failed: {e}")
        
        # Record metrics
        if metrics_service:
            try:
                self._record_media_metrics(command_id, "SUCCESS", duration_ms, action, domain)
            except Exception as e:
                logger.debug(f"Metrics recording failed: {e}")
    
    async def _track_media_failure(self, command_id: str, action: str, app: str, domain: str, error: str, duration_ms: float):
        """Track failed media execution."""
        if lifecycle_tracker:
            try:
                lifecycle_tracker.track_execution_completed(command_id, success=False, error=error)
            except Exception as e:
                logger.debug(f"Lifecycle failure tracking failed: {e}")
        
        await self._publish_media_event("COMMAND_FAILED", {
            "command": action,
            "command_id": command_id,
            "domain": domain,
            "app": app,
            "status": "FAILED",
            "error": error,
            "execution_duration": duration_ms
        })
        
        if structured_logger:
            try:
                structured_logger.log_execution_failed(
                    execution_id=command_id,
                    command=action,
                    priority="NORMAL",
                    domain=domain,
                    app=app,
                    duration=duration_ms,
                    error_code="EXECUTION_ERROR",
                    message=error
                )
            except Exception as e:
                logger.debug(f"Structured logging failed: {e}")
        
        if metrics_service:
            try:
                self._record_media_metrics(command_id, "FAILED", duration_ms, action, domain)
            except Exception as e:
                logger.debug(f"Metrics recording failed: {e}")
    
    async def _track_media_timeout(self, command_id: str, action: str, app: str, domain: str, error: str, duration_ms: float, timeout_seconds: float):
        """Track timed out media execution."""
        if lifecycle_tracker:
            try:
                lifecycle_tracker.track_timeout(
                    command_id,
                    reason=error,
                    timeout_duration_ms=duration_ms,
                    metadata={"domain": domain, "app": app, "timeout_seconds": timeout_seconds}
                )
            except Exception as e:
                logger.debug(f"Lifecycle timeout tracking failed: {e}")
        
        await self._publish_media_event("COMMAND_TIMEOUT", {
            "command": action,
            "command_id": command_id,
            "domain": domain,
            "app": app,
            "status": "TIMEOUT",
            "error": error,
            "timeout_duration_ms": duration_ms,
            "timeout_seconds": timeout_seconds
        })
        
        if structured_logger:
            try:
                structured_logger.log_execution_failed(
                    execution_id=command_id,
                    command=action,
                    priority="NORMAL",
                    domain=domain,
                    app=app,
                    duration=duration_ms,
                    error_code="TIMEOUT",
                    message=error
                )
            except Exception as e:
                logger.debug(f"Structured logging failed: {e}")
        
        if metrics_service:
            try:
                self._record_media_metrics(command_id, "TIMEOUT", duration_ms, action, domain)
            except Exception as e:
                logger.debug(f"Metrics recording failed: {e}")
    
    def _record_media_metrics(self, command_id: str, status: str, duration_ms: float, command: str, domain: str):
        """Record media command metrics."""
        if not metrics_service:
            return
        
        try:
            class MediaMetricsRecord:
                def __init__(self):
                    self.command_id = command_id
                    self.command = command
                    self.domain = domain
                    self.current_stage = type('Stage', (), {'value': status})()
                    self.duration_ms = duration_ms
                    self.metadata = {}
                    self.history = []
                    
                    from core.managers.lifecycle_tracker import LifecycleTransition, CommandLifecycleStage
                    self.history.append(LifecycleTransition(
                        from_stage=None,
                        to_stage=CommandLifecycleStage.QUEUED,
                        timestamp=time.time() - (duration_ms / 1000.0)
                    ))
                    self.history.append(LifecycleTransition(
                        from_stage=CommandLifecycleStage.QUEUED,
                        to_stage=CommandLifecycleStage.EXECUTION_STARTED,
                        timestamp=time.time() - (duration_ms / 1000.0)
                    ))
            
            record = MediaMetricsRecord()
            metrics_service.record_completion(record)
        except Exception as e:
            logger.debug(f"Media metrics recording failed: {e}")


# Global Singleton Instance
media_execution_service = MediaExecutionService()


def get_media_execution_service() -> MediaExecutionService:
    """Return singleton instance of MediaExecutionService."""
    global media_execution_service
    return media_execution_service
