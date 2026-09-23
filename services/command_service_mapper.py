"""
Command Service Mapper (Member 5 - Day 5 Implementation)
Routes incoming validated commands to their respective domain execution services
while preserving metadata, maintaining lifecycle status, and providing error isolation.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union

logger = logging.getLogger("CommandServiceMapper")


class Domain(str, Enum):
    DESKTOP = "DESKTOP"
    MEDIA = "MEDIA"
    IOT = "IOT"
    EMBEDDED = "EMBEDDED"
    AIML = "AIML"
    PYTHON = "PYTHON"


class MappingStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ROUTED = "ROUTED"
    EXECUTING = "EXECUTING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass
class RoutedCommandContext:
    command_id: str
    domain: str
    action: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    priority: int = 1
    timestamp: float = field(default_factory=time.time)
    session_id: Optional[str] = None
    device_id: Optional[str] = None
    status: MappingStatus = MappingStatus.RECEIVED
    start_time: Optional[str] = None
    completion_time: Optional[str] = None
    duration_seconds: Optional[float] = None
    execution_time_ms: float = 0.0
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class CommandServiceMapper:
    """
    Central routing layer that maps incoming validated commands to the target
    execution service (Desktop, Media, IoT, Embedded) based on domain and action.
    """

    def __init__(self):
        self.logger = logging.getLogger("CommandServiceMapper")
        self._services: Dict[str, Any] = {}
        self._action_handlers: Dict[str, Dict[str, Callable]] = {}
        self._command_history: List[RoutedCommandContext] = []
        self._max_history = 100
        
        # Initialize default domain services registry
        self._init_default_services()

    def _init_default_services(self) -> None:
        """Attempt to register known domain services lazily."""
        try:
            from services.media_execution_service import get_media_execution_service
            self.register_service(Domain.MEDIA.value, get_media_execution_service())
        except Exception as e:
            self.logger.debug(f"MediaExecutionService default init notice: {e}")

        try:
            from services.desktop_integration_service import get_desktop_integration_service
            self.register_service(Domain.DESKTOP.value, get_desktop_integration_service())
        except Exception as e:
            self.logger.debug(f"DesktopIntegrationService default init notice: {e}")

    def register_service(self, domain: Union[Domain, str], service_instance: Any) -> None:
        """Register an execution service for a specific domain."""
        dom_key = domain.value.upper() if isinstance(domain, Domain) else str(domain).upper()
        self._services[dom_key] = service_instance
        self.logger.info(f"[CommandServiceMapper] Registered service for domain: {dom_key}")

    def unregister_service(self, domain: Union[Domain, str]) -> None:
        """Unregister an execution service for a domain."""
        dom_key = domain.value.upper() if isinstance(domain, Domain) else str(domain).upper()
        if dom_key in self._services:
            del self._services[dom_key]
            self.logger.info(f"[CommandServiceMapper] Unregistered service for domain: {dom_key}")

    def register_action_handler(self, domain: Union[Domain, str], action: str, handler: Callable) -> None:
        """Register a specific action handler override for a domain."""
        dom_key = domain.value.upper() if isinstance(domain, Domain) else str(domain).upper()
        act_key = action.strip().lower()
        if dom_key not in self._action_handlers:
            self._action_handlers[dom_key] = {}
        self._action_handlers[dom_key][act_key] = handler
        self.logger.info(f"[CommandServiceMapper] Registered action handler for {dom_key} -> {act_key}")

    def map_and_execute(
        self,
        command_id: Optional[str] = None,
        domain: Union[Domain, str] = "",
        action: str = "",
        parameters: Optional[Dict[str, Any]] = None,
        priority: int = 1,
        timestamp: Optional[float] = None,
        session_id: Optional[str] = None,
        device_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Main entry point for routing and executing a command.
        Preserves metadata, tracks execution time, isolates errors, and returns a standardized response.
        """
        start_time = time.time()
        cid = command_id or f"cmd_{uuid.uuid4().hex[:8]}"
        dom_str = domain.value.upper() if isinstance(domain, Domain) else str(domain).upper()
        act_str = action.strip().lower()
        params = parameters if parameters is not None else {}
        ts = timestamp or time.time()

        ctx = RoutedCommandContext(
            command_id=cid,
            domain=dom_str,
            action=act_str,
            parameters=params,
            priority=priority,
            timestamp=ts,
            session_id=session_id,
            device_id=device_id,
            status=MappingStatus.RECEIVED,
        )

        self.logger.info(f"[CommandServiceMapper] Routing command {cid} -> domain: '{dom_str}', action: '{act_str}'")

        from core.logging.timestamp_tracker import get_timestamp_tracker
        tracker = get_timestamp_tracker()
        rec = tracker.record_start(cid, session_id or "default", act_str)
        ctx.start_time = rec.get("start_time") if isinstance(rec, dict) else time.strftime("%Y-%m-%dT%H:%M:%S")

        # Step 1: Validate domain target
        if not dom_str:
            return self._build_error_response(
                ctx=ctx,
                start_time=start_time,
                error="Empty or missing domain in command payload",
                status=MappingStatus.FAILED,
            )

        # Step 2: Route to specific action handler if registered
        if dom_str in self._action_handlers and act_str in self._action_handlers[dom_str]:
            ctx.status = MappingStatus.ROUTED
            handler = self._action_handlers[dom_str][act_str]
            return self._execute_handler(ctx, handler, start_time)

        # Step 3: Route to registered domain service
        if dom_str in self._services:
            ctx.status = MappingStatus.ROUTED
            service = self._services[dom_str]
            return self._execute_service(ctx, service, start_time)

        # Step 4: Check fallback domain mappings
        return self._handle_fallback_or_unsupported(ctx, start_time)

    def _execute_handler(self, ctx: RoutedCommandContext, handler: Callable, start_time: float) -> Dict[str, Any]:
        """Execute a registered callable action handler safely."""
        ctx.status = MappingStatus.EXECUTING
        from core.logging.timestamp_tracker import get_timestamp_tracker
        tracker = get_timestamp_tracker()
        try:
            res = handler(ctx.action, ctx.parameters, ctx)
            elapsed_ms = round((time.time() - start_time) * 1000, 2)
            ctx.execution_time_ms = elapsed_ms
            ctx.status = MappingStatus.SUCCESS
            ctx.result = res if isinstance(res, dict) else {"data": res}
            ctx.error = None
            comp_rec = tracker.record_completion(ctx.command_id)
            if isinstance(comp_rec, dict):
                ctx.completion_time = comp_rec.get("completion_time")
                ctx.duration_seconds = comp_rec.get("duration_seconds")
            else:
                ctx.completion_time = time.strftime("%Y-%m-%dT%H:%M:%S")
                ctx.duration_seconds = round(time.time() - start_time, 4)
            self._record_history(ctx)

            # Ensure response adheres to standardized schema
            return {
                "command_id": ctx.command_id,
                "domain": ctx.domain,
                "action": ctx.action,
                "session_id": ctx.session_id,
                "status": "SUCCESS",
                "success": True,
                "start_time": ctx.start_time,
                "completion_time": ctx.completion_time,
                "duration_seconds": ctx.duration_seconds,
                "error": None,
                "execution_time_ms": elapsed_ms,
                "result": ctx.result,
                "metadata": {
                    "priority": ctx.priority,
                    "timestamp": ctx.timestamp,
                    "session_id": ctx.session_id,
                    "device_id": ctx.device_id,
                },
            }
        except Exception as e:
            self.logger.error(f"[CommandServiceMapper] Handler execution error for {ctx.command_id}: {e}", exc_info=True)
            return self._build_error_response(ctx, start_time, str(e), MappingStatus.FAILED)

    def _execute_service(self, ctx: RoutedCommandContext, service: Any, start_time: float) -> Dict[str, Any]:
        """Execute against a registered service instance."""
        ctx.status = MappingStatus.EXECUTING
        from core.logging.timestamp_tracker import get_timestamp_tracker
        tracker = get_timestamp_tracker()
        try:
            # Check standard service methods
            if hasattr(service, "execute_command"):
                res = service.execute_command(
                    action=ctx.action,
                    payload=ctx.parameters,
                    command_id=ctx.command_id,
                )
            elif hasattr(service, "execute"):
                res = service.execute(
                    action=ctx.action,
                    parameters=ctx.parameters,
                )
            elif hasattr(service, "execute_action"):
                res = service.execute_action(
                    action=ctx.action,
                    query=ctx.parameters.get("query") if ctx.parameters else None,
                )
            elif hasattr(service, "handle_command"):
                res = service.handle_command(ctx.action, ctx.parameters)
            elif callable(service):
                res = service(ctx.action, ctx.parameters)
            else:
                return self._build_error_response(
                    ctx,
                    start_time,
                    f"Service for domain '{ctx.domain}' does not implement execute_command, execute, or handle_command",
                    MappingStatus.UNSUPPORTED,
                )

            elapsed_ms = round((time.time() - start_time) * 1000, 2)
            ctx.execution_time_ms = elapsed_ms
            
            # Unpack response if already formatted
            if isinstance(res, dict):
                success = res.get("success", True)
                status = "SUCCESS" if success else "FAILED"
                ctx.status = MappingStatus.SUCCESS if success else MappingStatus.FAILED
                ctx.result = res
                if success:
                    ctx.error = None
                    comp_rec = tracker.record_completion(ctx.command_id)
                else:
                    ctx.error = res.get("error", "Execution failed")
                    comp_rec = tracker.record_failure(
                        command_id=ctx.command_id,
                        session_id=ctx.session_id,
                        command=f"{ctx.domain}:{ctx.action}",
                        error=ctx.error,
                    )

                if isinstance(comp_rec, dict):
                    ctx.completion_time = comp_rec.get("completion_time")
                    ctx.duration_seconds = comp_rec.get("duration_seconds")
                else:
                    ctx.completion_time = time.strftime("%Y-%m-%dT%H:%M:%S")
                    ctx.duration_seconds = round(time.time() - start_time, 4)

                self._record_history(ctx)

                return {
                    "command_id": ctx.command_id,
                    "domain": ctx.domain,
                    "action": ctx.action,
                    "session_id": ctx.session_id,
                    "status": status,
                    "success": success,
                    "start_time": ctx.start_time,
                    "completion_time": ctx.completion_time,
                    "duration_seconds": ctx.duration_seconds,
                    "error": ctx.error,
                    "execution_time_ms": elapsed_ms,
                    "result": res,
                    "metadata": {
                        "priority": ctx.priority,
                        "timestamp": ctx.timestamp,
                        "session_id": ctx.session_id,
                        "device_id": ctx.device_id,
                    },
                }
            else:
                ctx.status = MappingStatus.SUCCESS
                ctx.result = {"data": res}
                ctx.error = None
                comp_rec = tracker.record_completion(ctx.command_id)
                if isinstance(comp_rec, dict):
                    ctx.completion_time = comp_rec.get("completion_time")
                    ctx.duration_seconds = comp_rec.get("duration_seconds")
                else:
                    ctx.completion_time = time.strftime("%Y-%m-%dT%H:%M:%S")
                    ctx.duration_seconds = round(time.time() - start_time, 4)

                self._record_history(ctx)

                return {
                    "command_id": ctx.command_id,
                    "domain": ctx.domain,
                    "action": ctx.action,
                    "session_id": ctx.session_id,
                    "status": "SUCCESS",
                    "success": True,
                    "start_time": ctx.start_time,
                    "completion_time": ctx.completion_time,
                    "duration_seconds": ctx.duration_seconds,
                    "error": None,
                    "execution_time_ms": elapsed_ms,
                    "result": ctx.result,
                    "metadata": {
                        "priority": ctx.priority,
                        "timestamp": ctx.timestamp,
                        "session_id": ctx.session_id,
                        "device_id": ctx.device_id,
                    },
                }

        except Exception as e:
            self.logger.error(f"[CommandServiceMapper] Service execution error for {ctx.command_id}: {e}", exc_info=True)
            return self._build_error_response(ctx, start_time, str(e), MappingStatus.FAILED)

    def _handle_fallback_or_unsupported(self, ctx: RoutedCommandContext, start_time: float) -> Dict[str, Any]:
        """Attempt to resolve unmapped domains through dynamic module lookups or return unsupported error."""
        # Check if domain matches standard plugin names
        try:
            if ctx.domain == "DESKTOP":
                from plugins.desktop.plugin import DesktopPlugin
                plugin = DesktopPlugin()
                self.register_service("DESKTOP", plugin)
                return self._execute_service(ctx, plugin, start_time)
            elif ctx.domain == "IOT":
                from plugins.iot.plugin import IoTPlugin
                plugin = IoTPlugin()
                self.register_service("IOT", plugin)
                return self._execute_service(ctx, plugin, start_time)
            elif ctx.domain == "EMBEDDED":
                from plugins.embedded.plugin import EmbeddedPlugin
                plugin = EmbeddedPlugin()
                self.register_service("EMBEDDED", plugin)
                return self._execute_service(ctx, plugin, start_time)
            elif ctx.domain == "MEDIA":
                from services.media_execution_service import get_media_execution_service
                service = get_media_execution_service()
                self.register_service("MEDIA", service)
                return self._execute_service(ctx, service, start_time)
            elif ctx.domain in ("AIML", "AI_ML", "JIOSAAVN"):
                try:
                    from plugins.aiml import app as aiml_app
                    service = aiml_app.desktop_controller
                except Exception:
                    service = None
                if not service:
                    from plugins.aiml.desktop_dashboard.operate_jiosavaan import JioSaavnController
                    service = JioSaavnController()
                self.register_service(ctx.domain, service)
                return self._execute_service(ctx, service, start_time)
        except Exception as e:
            self.logger.warning(f"[CommandServiceMapper] Fallback import failed for {ctx.domain}: {e}")

        # Domain truly unsupported
        error_msg = f"Unsupported or unregistered domain: '{ctx.domain}'. No execution service available."
        self.logger.warning(f"[CommandServiceMapper] {error_msg} (command_id: {ctx.command_id})")
        return self._build_error_response(ctx, start_time, error_msg, MappingStatus.UNSUPPORTED)

    def _build_error_response(
        self,
        ctx: RoutedCommandContext,
        start_time: float,
        error: str,
        status: MappingStatus = MappingStatus.FAILED,
    ) -> Dict[str, Any]:
        """Build standardized error response preserving all metadata."""
        from core.logging.timestamp_tracker import get_timestamp_tracker
        tracker = get_timestamp_tracker()
        cmd_name = f"{ctx.domain}:{ctx.action}" if ctx.domain and ctx.action else (ctx.domain or "unknown")
        comp_rec = tracker.record_failure(
            command_id=ctx.command_id,
            session_id=ctx.session_id,
            command=cmd_name,
            error=error,
        )
        if isinstance(comp_rec, dict):
            ctx.completion_time = comp_rec.get("completion_time")
            ctx.duration_seconds = comp_rec.get("duration_seconds")
        else:
            ctx.completion_time = time.strftime("%Y-%m-%dT%H:%M:%S")
            ctx.duration_seconds = round(time.time() - start_time, 4)

        elapsed_ms = round((time.time() - start_time) * 1000, 2)
        ctx.status = status
        ctx.execution_time_ms = elapsed_ms
        ctx.error = error
        self._record_history(ctx)

        return {
            "command_id": ctx.command_id,
            "domain": ctx.domain,
            "action": ctx.action,
            "session_id": ctx.session_id,
            "status": status.value,
            "success": False,
            "start_time": ctx.start_time,
            "completion_time": ctx.completion_time,
            "duration_seconds": ctx.duration_seconds,
            "execution_time_ms": elapsed_ms,
            "error": error,
            "message": f"Command execution failed: {error}",
            "metadata": {
                "priority": ctx.priority,
                "timestamp": ctx.timestamp,
                "session_id": ctx.session_id,
                "device_id": ctx.device_id,
            },
        }

    def _record_history(self, ctx: RoutedCommandContext) -> None:
        """Keep last N execution records for observability and telemetry."""
        self._command_history.append(ctx)
        if len(self._command_history) > self._max_history:
            self._command_history.pop(0)

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return execution history records."""
        return [
            {
                "command_id": c.command_id,
                "domain": c.domain,
                "action": c.action,
                "session_id": c.session_id,
                "status": c.status.value,
                "start_time": c.start_time,
                "completion_time": c.completion_time,
                "duration_seconds": c.duration_seconds,
                "execution_time_ms": c.execution_time_ms,
                "error": c.error,
                "timestamp": c.timestamp,
            }
            for c in self._command_history[-limit:]
        ]

    def get_registered_domains(self) -> List[str]:
        """Return list of currently registered domain services."""
        return list(self._services.keys())


# Global Singleton Instance
_mapper_instance: Optional[CommandServiceMapper] = None


def get_command_service_mapper() -> CommandServiceMapper:
    """Singleton getter for CommandServiceMapper."""
    global _mapper_instance
    if _mapper_instance is None:
        _mapper_instance = CommandServiceMapper()
    return _mapper_instance
