from core.state.state_manager import state_manager

class NavigationManager:
    def validate_and_dispatch_back(self, session: str = "default") -> dict:
        state = state_manager.get_state(session)
        level = state.get("current_level", 1)
        
        if level <= 1:
            return {"status": "ignored", "message": "Already at root level (Level 1)"}
        
        if level == 3:
            updates = {
                "current_level": 2,
                "active_app": None,
                "last_resolved_action": "Previous Stage"
            }
        elif level == 2:
            updates = {
                "current_level": 1,
                "active_domain": None,
                "active_app": None,
                "last_resolved_action": "Previous Stage"
            }
            
        state_manager.update_state(session, updates)
        return {"status": "success", "updates": updates}

    def validate_and_dispatch_home(self, session: str = "default") -> dict:
        state = state_manager.get_state(session)
        level = state.get("current_level", 1)
        active_domain = state.get("active_domain")
        active_app = state.get("active_app")
        
        if level == 1 and active_domain is None and active_app is None:
            return {"status": "ignored", "message": "Already at Home (Level 1)"}
            
        updates = {
            "current_level": 1,
            "active_domain": None,
            "active_app": None,
            "last_resolved_action": "Domain Selection"
        }
        
        state_manager.update_state(session, updates)
        return {"status": "success", "updates": updates}

navigation_manager = NavigationManager()
