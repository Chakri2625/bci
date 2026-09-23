"""
Comprehensive Test Suite for SynaptiMesh Core Bug Fixes:
1. Dynamic Session ID generation on startup and reset
2. AIML -> Master navigation loop prevention
3. Mobile Dashboard APK routing (skipping PC browser launch)
4. AIML Volume Up / Volume Down controls
5. Temporal Window timer preservation without reset upon subsequent commands
"""

import pytest
import asyncio
import time
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.state.state_manager import StateManager, state_manager
from core.communication.api_server import router
from plugins.aiml.fastapi_routes import router as aiml_router
from core.orchestration.ecosystem_orchestrator import ecosystem_orchestrator
from core.managers.command_lock_manager import command_lock_manager
from plugins.aiml.plugin import AIMLPlugin

app = FastAPI()
app.include_router(router)
app.include_router(aiml_router)
client = TestClient(app)


# ============================================================
# 1. SESSION ID TESTS
# ============================================================
def test_dynamic_session_id_generation():
    """Verify that a unique session ID is generated on startup and reset."""
    sm = StateManager()
    session1 = sm.get_active_session_id()
    assert session1 is not None
    assert session1.startswith("SESSION-")
    assert session1 != "default"

    # Resetting state must produce a NEW distinct session ID
    new_state = sm.reset_state()
    session2 = sm.get_active_session_id()
    assert session2 is not None
    assert session2.startswith("SESSION-")
    assert session2 != session1
    assert new_state["session_id"] == session2

    # Third reset produces another unique ID
    sm.reset_state()
    session3 = sm.get_active_session_id()
    assert session3 != session2
    assert session3 != session1


def test_api_uses_active_dynamic_session():
    """Verify API endpoints use the active dynamic session rather than 'default'."""
    reset_resp = client.post("/api/v1/state/reset")
    assert reset_resp.status_code == 200
    reset_data = reset_resp.json()
    active_sid = reset_data["session_id"]
    assert active_sid != "default"
    assert active_sid.startswith("SESSION-")

    # GET /api/v1/state without query param should return active session
    state_resp = client.get("/api/v1/state")
    assert state_resp.status_code == 200
    state_data = state_resp.json()
    assert state_data["session_id"] == active_sid


# ============================================================
# 2. NAVIGATION LOOP PREVENTION TESTS
# ============================================================
def test_navigation_state_reset():
    """Verify that resetting navigation resets state to Level 1 and clears domain."""
    active_sid = state_manager.get_active_session_id()

    # Set state as if inside AIML domain (Level 2)
    state_manager.update_state(active_sid, {
        "current_level": 2,
        "active_domain": "AIML",
        "active_app": None
    })
    st = state_manager.get_state(active_sid)
    assert st["current_level"] == 2
    assert st["active_domain"] == "AIML"

    # Simulate navigating back to Master (/?reset=1)
    state_manager.update_state(active_sid, {
        "current_level": 1,
        "active_domain": None,
        "active_app": None,
        "last_resolved_action": "Domain Selection"
    })
    st_master = state_manager.get_state(active_sid)
    assert st_master["current_level"] == 1
    assert st_master["active_domain"] is None


# ============================================================
# 3. MOBILE DASHBOARD APK ROUTING TESTS
# ============================================================
@pytest.mark.asyncio
async def test_mobile_dashboard_command_routes_to_apk():
    """Verify Mobile Dashboard command dispatches to APK and does not launch browser."""
    plugin = AIMLPlugin()
    res = await plugin.execute("OPEN_MOBILE_DASHBOARD")
    assert res["status"] == "success"
    assert res["action"] == "open_mobile_dashboard"
    assert res["target"] == "mobile"


def test_api_manual_action_mobile_dashboard():
    """Verify /api/action with Open Mobile Dashboard dispatches to APK."""
    resp = client.post("/api/action", json={"action": "Open Mobile Dashboard"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["target"] == "mobile"
    assert data["dispatched_to_apk"] is True
    assert data["browser_launch"] == "skipped"


# ============================================================
# 4. AIML VOLUME UP / VOLUME DOWN TESTS
# ============================================================
@pytest.mark.asyncio
async def test_volume_up_down_execution():
    """Verify Volume Up and Volume Down commands execute via plugin and API."""
    plugin = AIMLPlugin()

    # Volume Up
    res_up = await plugin.execute("VOLUME_UP")
    assert res_up["status"] == "success"
    assert res_up["action"] == "volume_up"
    assert "volume" in res_up

    # Volume Down
    res_down = await plugin.execute("VOLUME_DOWN")
    assert res_down["status"] == "success"
    assert res_down["action"] == "volume_down"
    assert "volume" in res_down


def test_api_manual_action_volume():
    """Verify /api/action executes Volume Up and Volume Down."""
    # Volume Up
    resp_up = client.post("/api/action", json={"action": "Volume Up"})
    assert resp_up.status_code == 200
    data_up = resp_up.json()
    assert data_up["status"] == "success"
    assert "Volume Up executed" in data_up["message"]

    # Volume Down
    resp_down = client.post("/api/action", json={"action": "Volume Down"})
    assert resp_down.status_code == 200
    data_down = resp_down.json()
    assert data_down["status"] == "success"
    assert "Volume Down executed" in data_down["message"]


# ============================================================
# 5. TEMPORAL WINDOW TIMER CONTINUITY TESTS
# ============================================================
def test_temporal_window_does_not_reset_on_subsequent_commands():
    """
    Verify that once a temporal window is active, receiving subsequent commands
    does NOT reset the start time or deadline back to the initial duration.
    """
    test_session = f"TEMPORAL-TEST-{time.time()}"
    command_lock_manager.reset_lock(test_session)

    # 1. First command acquires lock and starts timer
    res1 = command_lock_manager.acquire_or_combine(test_session, "PUSH", duration=5.0)
    assert res1["status"] == "accepted"
    start_t = res1["timer_started"]
    deadline = res1["timer_deadline"]
    assert deadline - start_t == pytest.approx(5.0, 0.01)

    time.sleep(0.1)

    # 2. Second command arrives during active window
    res2 = command_lock_manager.acquire_or_combine(test_session, "PUSH")
    # Must NOT create a new timer or reset start_time / deadline
    assert res2["timer_started"] == start_t
    assert res2["timer_deadline"] == deadline
    assert res2["time_remaining"] < 5.0

    time.sleep(0.1)

    # 3. Third command arrives
    res3 = command_lock_manager.acquire_or_combine(test_session, "PUSH")
    assert res3["timer_started"] == start_t
    assert res3["timer_deadline"] == deadline
    assert res3["time_remaining"] < res2["time_remaining"]


def test_temporal_window_combo_preserves_deadline():
    """Verify combination formation (PUSH + RIGHT) preserves original start time & deadline."""
    test_session = f"COMBO-TEST-{time.time()}"
    command_lock_manager.reset_lock(test_session)

    # PUSH starts 4.0s window
    res1 = command_lock_manager.acquire_or_combine(test_session, "PUSH", duration=4.0)
    orig_start = res1["timer_started"]
    orig_deadline = res1["timer_deadline"]

    time.sleep(0.08)

    # RIGHT forms PUSH_RIGHT combination
    res2 = command_lock_manager.acquire_or_combine(test_session, "RIGHT")
    assert res2["status"] == "accepted"
    assert res2["is_combination"] is True
    assert res2["command"] == "PUSH_RIGHT"
    # Original timer MUST continue unchanged
    assert res2["timer_started"] == orig_start
    assert res2["timer_deadline"] == orig_deadline
    assert res2["time_remaining"] < 4.0


def test_temporal_window_push_left_combo():
    """Verify combination formation (PUSH + LEFT) creates PUSH_LEFT and preserves original timer."""
    test_session = f"COMBO-LEFT-TEST-{time.time()}"
    command_lock_manager.reset_lock(test_session)

    # 1. PUSH starts window
    res1 = command_lock_manager.acquire_or_combine(test_session, "PUSH", duration=4.0)
    assert res1["status"] == "accepted"
    orig_start = res1["timer_started"]
    orig_deadline = res1["timer_deadline"]

    time.sleep(0.05)

    # 2. LEFT forms PUSH_LEFT combo
    res2 = command_lock_manager.acquire_or_combine(test_session, "LEFT")
    assert res2["status"] == "accepted"
    assert res2["is_combination"] is True
    assert res2["command"] == "PUSH_LEFT"
    assert res2["timer_started"] == orig_start
    assert res2["timer_deadline"] == orig_deadline


def test_direct_compound_commands_accepted():
    """Verify direct compound commands like 'PUSH+LEFT' and 'PUSH+RIGHT' are accepted."""
    test_session = f"DIRECT-COMBO-TEST-{time.time()}"
    command_lock_manager.reset_lock(test_session)

    # Direct PUSH+LEFT
    res = command_lock_manager.acquire_or_combine(test_session, "PUSH+LEFT", duration=4.0)
    assert res["status"] == "accepted"
    assert res["is_combination"] is True
    assert res["command"] == "PUSH_LEFT"

    command_lock_manager.reset_lock(test_session)

    # Direct PUSH+RIGHT
    res2 = command_lock_manager.acquire_or_combine(test_session, "PUSH+RIGHT", duration=4.0)
    assert res2["status"] == "accepted"
    assert res2["is_combination"] is True
    assert res2["command"] == "PUSH_RIGHT"


def test_right_push_volume_combo():
    """Verify RIGHT + PUSH forms RIGHT_PUSH combination for volume up."""
    test_session = f"VOL-COMBO-TEST-{time.time()}"
    command_lock_manager.reset_lock(test_session)

    res1 = command_lock_manager.acquire_or_combine(test_session, "RIGHT", duration=4.0)
    orig_start = res1["timer_started"]
    orig_deadline = res1["timer_deadline"]

    time.sleep(0.05)

    res2 = command_lock_manager.acquire_or_combine(test_session, "PUSH")
    assert res2["status"] == "accepted"
    assert res2["is_combination"] is True
    assert res2["command"] == "RIGHT_PUSH"
    assert res2["timer_started"] == orig_start
    assert res2["timer_deadline"] == orig_deadline

