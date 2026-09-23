from core.state.state_manager import state_manager
from core.routing.rule_router import resolve_command, navigate_back, navigate_home
from core.plugin_manager.manager import execute
from core.navigation.models import NavigationResponse

class NavigationManager:
    @staticmethod
    async def process_navigation(command: str, session: str = "default") -> NavigationResponse:
        try:
            from core.validation.command_normalizer import normalize_command
            cmd = normalize_command(command)
        except Exception:
            cmd = command.upper()
        state = state_manager.get_state(session)
        current_domain = state.get("active_domain", "domain_selection")
        
        # Determine the action using existing routing
        resolution = resolve_command(cmd, state)
        
        status = "success"
        error = None
        target_domain = current_domain
        action_result = None
        
        try:
            if resolution["type"] == "transition":
                target_domain = resolution["domain"]
                state_manager.update_state(session, {
                    "current_level": resolution["level"],
                    "active_domain": resolution["domain"],
                    "active_app": resolution["app"],
                    "last_resolved_action": None
                })
            elif resolution["type"] == "action":
                target_domain = resolution["domain"]
                exec_domain = (resolution.get("domain") or "desktop").lower()
                action_result = await execute(exec_domain, resolution["action"], {"domain": resolution["domain"], "app": resolution["app"]})
                state_manager.update_state(session, {
                    "last_resolved_action": resolution["action"]
                })
            elif resolution["type"] == "navigate_back":
                active_app = state.get("active_app")
                if active_app:
                    await execute("desktop", "close_app", {"domain": state.get("active_domain"), "app": active_app})
                updates = navigate_back(state)
                if updates:
                    state_manager.update_state(session, updates)
                # Update target domain after state update
                target_domain = state_manager.get_state(session).get("active_domain", "domain_selection")
            elif resolution["type"] == "navigate_home":
                active_app = state.get("active_app")
                if active_app:
                    await execute("desktop", "close_app", {"domain": state.get("active_domain"), "app": active_app})
                updates = navigate_home(state)
                if updates:
                    state_manager.update_state(session, updates)
                target_domain = state_manager.get_state(session).get("active_domain", "domain_selection")
            else:
                status = "failed"
                error = "invalid transition"
        except Exception as e:
            status = "failed"
            error = str(e)
            
        new_state = state_manager.get_state(session)
        
        return NavigationResponse(
            command=cmd,
            current_domain=current_domain,
            target_domain=target_domain,
            status=status,
            error=error,
            action_result=action_result,
            state=new_state
        )

    @staticmethod
    def get_state(session: str = "default"):
        return state_manager.get_state(session)

    @staticmethod
    def reset_navigation(session: str = "default"):
        # We simulate a reset by navigating home
        state = state_manager.get_state(session)
        updates = navigate_home(state)
        if updates:
            state_manager.update_state(session, updates)
        return state_manager.get_state(session)

navigation_manager = NavigationManager()
