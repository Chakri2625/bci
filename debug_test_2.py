import asyncio
from fastapi.testclient import TestClient
from main import app
from core.state.state_manager import state_manager
from core.plugin_manager.manager import load_plugins

load_plugins()

client = TestClient(app)

state_manager.states.clear()
r1 = client.post("/api/navigation/command", json={"command": "push"})
print("R1:", r1.json())
r2 = client.post("/api/navigation/command", json={"command": "push"})
print("R2:", r2.json())
r3 = client.post("/api/navigation/command", json={"command": "reset"})
print("R3:", r3.json())
r4 = client.get("/api/navigation/state")
print("R4:", r4.json())
