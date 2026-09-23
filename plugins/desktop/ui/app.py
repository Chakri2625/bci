from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import os
import logging

logger = logging.getLogger("desktop_ui")

def setup_ui(app: FastAPI):
    dir_path = os.path.dirname(os.path.realpath(__file__))
    index_path = os.path.join(dir_path, "templates", "index.html")

    @app.get("/", response_class=HTMLResponse)
    @app.get("/bci", response_class=HTMLResponse)
    async def get_dashboard(request: Request):
        if request.query_params.get("reset") or request.query_params.get("back"):
            try:
                from core.state.state_manager import state_manager
                active_sess = state_manager.get_active_session_id()
                state_manager.update_state(active_sess, {
                    "current_level": 1,
                    "active_domain": None,
                    "active_app": None,
                    "last_resolved_action": "Domain Selection"
                })
                print("[NAVIGATION] AIML → MASTER\n[NAVIGATION] AIML state cleared\n[NAVIGATION] Master Dashboard active")
                logger.info("[NAVIGATION] AIML → MASTER | State cleared | Master Dashboard active")
            except Exception as e:
                logger.warning(f"Error resetting state on master load: {e}")

        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()
        return HTMLResponse(content=content)
