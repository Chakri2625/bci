import sys
import os

# Ensure workspace root is always in sys.path
_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

import asyncio
import threading
import time
import webbrowser
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from core.plugin_manager.manager import discover_plugins, load_plugins
from core.communication.api_server import setup_routes
from plugins.desktop.ui.app import setup_ui
from plugins.aiml.fastapi_routes import setup_aiml_routes
from plugins.iot.fastapi_routes import setup_iot_routes
from plugins.embedded.fastapi_routes import setup_embedded_routes
from api.telemetry_routes import setup_telemetry_routes

def _auto_open_browser(url="http://127.0.0.1:8000", delay=1.2):
    if "pytest" in sys.modules or os.getenv("TESTING") == "1":
        return
    time.sleep(delay)
    try:
        webbrowser.open(url)
    except Exception as e:
        print(f"Auto-launch browser notification: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Bootstrapping SynaptiMesh...")
    discover_plugins()
    load_plugins()
    print("\n" + "=" * 60)
    print("🌐 SynaptiMesh Master Control: http://127.0.0.1:8000")
    print("🧠 Emotiv BCI Neural Suite:    http://127.0.0.1:8000/bci")
    print("🤖 AIML Master Hub:            http://127.0.0.1:8000/aiml")
    print("💡 IoT Dashboard:              http://127.0.0.1:8000/iot")
    print("🚗 Embedded Dashboard:         http://127.0.0.1:8000/embedded")
    print("=" * 60 + "\n")
    
    # Automatically open default browser on startup
    threading.Thread(target=_auto_open_browser, args=("http://127.0.0.1:8000", 1.0), daemon=True).start()
    yield
    try:
        from core.communication.websocket_server import websocket_server
        websocket_server.close_all()
    except Exception:
        pass

from fastapi.responses import Response

app = FastAPI(title="SynaptiMesh", lifespan=lifespan)

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)

setup_routes(app)
setup_ui(app)
setup_aiml_routes(app)
setup_iot_routes(app)
setup_embedded_routes(app)
setup_telemetry_routes(app)


if __name__ == "__main__":
    import logging
    for _noisy in [
        "selenium",
        "selenium.webdriver.remote.remote_connection",
        "urllib3",
        "urllib3.connectionpool",
        "uvicorn.access",
        "core.orchestration.resource_lock_manager",
        "resource_lock_manager",
    ]:
        _l = logging.getLogger(_noisy)
        _l.setLevel(logging.WARNING)
        _l.propagate = False
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False, access_log=False)


