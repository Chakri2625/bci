from fastapi import APIRouter
from pydantic import BaseModel
from typing import Any, Optional
from core.plugin_manager.manager import get_all_plugins, execute
from core.state.state_manager import state_manager
from core.routing.rule_router import resolve_command, navigate_back, navigate_home

router = APIRouter(prefix="/api/v1")

class BCICommandRequest(BaseModel):
    command: str

@router.get("/state")
def get_state(session: str = "default"):
    return state_manager.get_state(session)

@router.post("/bci/command")
async def process_bci_command(request: BCICommandRequest, session: str = "default"):
    cmd = request.command.upper()
    state_manager.add_command(session, cmd)
    state = state_manager.get_state(session)
    
    resolution = resolve_command(cmd, state)
    result = {"status": "success", "resolved": resolution, "executed": False}
    
    if resolution["type"] == "transition":
        state_manager.update_state(session, {
            "current_level": resolution["level"],
            "active_domain": resolution["domain"],
            "active_app": resolution["app"],
            "last_resolved_action": None
        })
    elif resolution["type"] == "action":
        action_res = await execute("desktop", resolution["action"], {"domain": resolution["domain"], "app": resolution["app"]})
        result["action_result"] = action_res
        result["executed"] = True
        state_manager.update_state(session, {
            "last_resolved_action": resolution["action"]
        })
    elif resolution["type"] == "navigate_back":
        updates = navigate_back(state)
        if updates:
            state_manager.update_state(session, updates)
    elif resolution["type"] == "navigate_home":
        updates = navigate_home(state)
        if updates:
            state_manager.update_state(session, updates)
    else:
        result["status"] = "no_action"
        
    result["state"] = state_manager.get_state(session)
    return result

@router.get("/widgets")
async def get_widgets():
    res = await execute("desktop", "get_widgets", None)
    return res

def setup_routes(app):
    app.include_router(router)
