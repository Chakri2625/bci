from fastapi import APIRouter
from core.navigation.models import NavigationRequest, NavigationResponse, NavigationStateResponse
from core.navigation.controller import navigation_controller
from core.navigation.manager import navigation_manager

navigation_router = APIRouter(prefix="/api/navigation", tags=["Navigation"])

@navigation_router.post("/command", response_model=NavigationResponse)
async def process_navigation_command(request: NavigationRequest, session: str = "default"):
    """
    Process a navigation command (PUSH, PULL, LEFT, RIGHT).
    """
    response = await navigation_controller.handle_command(request, session)
    return response

@navigation_router.get("/state", response_model=NavigationStateResponse)
def get_navigation_state(session: str = "default"):
    """
    Get current navigation state.
    """
    state = navigation_manager.get_state(session)
    return NavigationStateResponse(
        current_domain=state.get("active_domain"),
        active_app=state.get("active_app"),
        active_mode=state.get("active_mode"),
        last_command=state.get("last_command"),
        current_level=state.get("current_level", 1),
        command_history=state.get("command_history", [])
    )

@navigation_router.post("/reset", response_model=NavigationStateResponse)
def reset_navigation_state(session: str = "default"):
    """
    Reset navigation back to the starting point (Domain Selection).
    """
    state = navigation_manager.reset_navigation(session)
    return NavigationStateResponse(
        current_domain=state.get("active_domain"),
        active_app=state.get("active_app"),
        active_mode=state.get("active_mode"),
        last_command=state.get("last_command"),
        current_level=state.get("current_level", 1),
        command_history=state.get("command_history", [])
    )
