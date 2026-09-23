from core.navigation.models import NavigationRequest, NavigationResponse
from core.navigation.manager import navigation_manager
from core.logging.logger import log_navigation
from core.state.state_manager import state_manager

VALID_COMMANDS = {"PUSH", "PULL", "LEFT", "RIGHT", "PUSH_LEFT", "PUSH_RIGHT"}

class NavigationController:
    @staticmethod
    async def handle_command(request: NavigationRequest, session: str = "default") -> NavigationResponse:
        try:
            from core.validation.command_normalizer import normalize_command
            cmd = normalize_command(request.command)
        except ImportError:
            cmd = request.command.upper()

        state = state_manager.get_state(session)

        # Check command validity
        if cmd not in VALID_COMMANDS:
            current_domain = state.get("active_domain", "domain_selection")
            log_navigation(cmd, current_domain, current_domain, "failed", "invalid command")
            from core.navigation.recovery_handler import recovery_handler
            rec = recovery_handler.handle_rejected_command(cmd, "invalid command", session)
            return NavigationResponse(
                command=cmd,
                current_domain=current_domain,
                target_domain=current_domain,
                status="failed",
                error="invalid command",
                state=state,
                recovery_attempted=rec.attempted,
                recovery_status=rec.status,
                recovery_action=rec.action,
                recovery_error=rec.error
            )

        # Check duplicate navigation requests and ignore repeated commands safely.
        if state.get("last_command") == cmd:
            current_domain = state.get("active_domain", "domain_selection")
            log_navigation(cmd, current_domain, current_domain, "success", "ignored duplicate")
            return NavigationResponse(
                command=cmd,
                current_domain=current_domain,
                target_domain=current_domain,
                status="success",
                error="ignored duplicate",
                state=state
            )

        state_manager.add_command(session, cmd)

        # Process via Manager
        response = await navigation_manager.process_navigation(cmd, session)

        if response.status == "failed":
            from core.navigation.recovery_handler import recovery_handler
            rec = recovery_handler.handle_invalid_transition(cmd, response.error or "invalid transition", state, session)
            response.recovery_attempted = rec.attempted
            response.recovery_status = rec.status
            response.recovery_action = rec.action
            response.recovery_error = rec.error
            response.state = rec.state or state_manager.get_state(session)

        # Log navigation
        log_navigation(
            response.command,
            response.current_domain,
            response.target_domain,
            response.status,
            response.error
        )

        return response

    @staticmethod
    async def handle_raw_command(request, session: str = "default") -> NavigationResponse:
        if isinstance(request, str):
            request = NavigationRequest(command=request)
        return await NavigationController.handle_command(request, session=session)

navigation_controller = NavigationController()
