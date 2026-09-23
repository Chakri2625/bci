"""
Unit and Integration Tests for BCI / Cortex Connection Reconnection Handling.
Tests robust exponential backoff, state recovery tracking, terminal visual outputs,
and clean cancellation without requiring a physical Emotiv headset or network access.
"""

import asyncio
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from services.cortex_service import CortexConfig, CortexService
from core.state.state_manager import state_manager


@pytest.fixture
def cortex_service_instance():
    """Create an isolated CortexService instance for test execution."""
    config = CortexConfig(
        reconnect_base_delay=2.0,
        reconnect_max_delay=16.0,
        max_reconnect_attempts=4,
        backoff_multiplier=2.0,
        client_id="test_client_id",
        client_secret="test_client_secret"
    )
    svc = CortexService(config=config)
    yield svc
    # Cleanup tasks if any still running
    if svc._reconnect_task and not svc._reconnect_task.done():
        svc._reconnect_task.cancel()
    if svc._listen_task and not svc._listen_task.done():
        svc._listen_task.cancel()


@pytest.mark.asyncio
async def test_connection_loss_triggers_reconnect_loop(cortex_service_instance, capsys):
    """Test 1: Connection loss in listener loop triggers reconnect loop and visual banner."""
    svc = cortex_service_instance
    svc._should_reconnect = True
    svc.is_connected = True

    # Fake a websocket that raises an exception on read
    mock_ws = MagicMock()
    mock_ws.__aiter__.side_effect = ConnectionResetError("Remote server closed connection")
    svc.ws = mock_ws

    with patch.object(svc, "_reconnect_loop", new_callable=AsyncMock) as mock_loop:
        await svc._listener_loop()

        # Verify state reset and reconnect task triggered
        assert svc.is_connected is False
        assert mock_loop.called or svc._reconnect_task is not None

    captured = capsys.readouterr().out
    assert "========== BCI CONNECTION ==========" in captured
    assert "Status      : DISCONNECTED" in captured
    assert "Remote server closed connection" in captured


@pytest.mark.asyncio
async def test_exponential_backoff_and_failed_attempts(cortex_service_instance, capsys):
    """Tests 2, 3, 4: First attempt fails, backoff increases (2s -> 4s -> 8s), and second attempt occurs."""
    svc = cortex_service_instance
    svc._should_reconnect = True

    sleep_delays: List[float] = []

    async def fake_sleep(seconds):
        sleep_delays.append(seconds)

    # Attempt 1 fails, Attempt 2 fails, Attempt 3 succeeds
    connect_calls = 0

    async def fake_connect():
        nonlocal connect_calls
        connect_calls += 1
        if connect_calls < 3:
            return {"status": "error", "message": f"Simulated failure {connect_calls}"}
        svc.is_connected = True
        return {"status": "connected"}

    with patch("asyncio.sleep", side_effect=fake_sleep), \
         patch.object(svc, "connect", side_effect=fake_connect):
        
        await svc._reconnect_loop(reason="Socket drop")

    # Assert correct exponential backoff progression
    # Attempt 1 sleeps 2.0s, Attempt 2 sleeps 4.0s, Attempt 3 sleeps 8.0s
    assert len(sleep_delays) == 3
    assert sleep_delays[0] == 2.0
    assert sleep_delays[1] == 4.0
    assert sleep_delays[2] == 8.0
    assert connect_calls == 3
    assert svc.reconnect_attempts == 0  # Resets on success

    captured = capsys.readouterr().out
    # Check attempt 1 output
    assert "Attempt     : 1" in captured
    assert "Next Retry  : 2.0 seconds" in captured
    assert "[RECONNECT] Attempt 1 FAILED" in captured
    assert "Retrying with backoff: 4.0 seconds" in captured

    # Check attempt 2 output
    assert "Attempt     : 2" in captured
    assert "Next Retry  : 4.0 seconds" in captured
    assert "[RECONNECT] Attempt 2 FAILED" in captured
    assert "Retrying with backoff: 8.0 seconds" in captured

    # Check successful recovery output
    assert "Status      : CONNECTED" in captured
    assert "Result      : Reconnected Successfully" in captured
    assert "Attempts    : 3" in captured


@pytest.mark.asyncio
async def test_successful_reconnect_stops_further_retries(cortex_service_instance):
    """Test 5: Successful reconnect stops further retries immediately."""
    svc = cortex_service_instance
    svc._should_reconnect = True
    connect_count = 0

    async def mock_connect():
        nonlocal connect_count
        connect_count += 1
        svc.is_connected = True
        return {"status": "connected"}

    with patch("asyncio.sleep", new_callable=AsyncMock), \
         patch.object(svc, "connect", side_effect=mock_connect):
        
        await svc._reconnect_loop(reason="Transient blip")

    assert connect_count == 1
    assert svc.reconnect_attempts == 0
    assert svc.is_connected is True


@pytest.mark.asyncio
async def test_failed_reconnect_reaches_configured_limit(cortex_service_instance, capsys):
    """Test 6: Failed reconnect exhausts max_reconnect_attempts and updates state manager."""
    svc = cortex_service_instance
    svc._should_reconnect = True
    svc.max_reconnect_attempts = 3

    async def always_fail_connect():
        return {"status": "error", "message": "Connection refused"}

    with patch("asyncio.sleep", new_callable=AsyncMock), \
         patch.object(svc, "connect", side_effect=always_fail_connect):
        
        await svc._reconnect_loop(reason="Cortex offline")

    assert svc.reconnect_attempts == 3
    assert svc.is_connected is False

    captured = capsys.readouterr().out
    assert "========== BCI CONNECTION ==========" in captured
    assert "Status      : FAILED" in captured
    assert "Attempts    : 3" in captured
    assert "Reason      : Cortex offline" in captured

    # Verify StateManager recorded recovery failure
    bci_health = state_manager.get_domain_health("BCI")
    assert bci_health["recovery_status"] == "RECOVERY_FAILED"


@pytest.mark.asyncio
async def test_manual_disconnect_stops_reconnect_task(cortex_service_instance):
    """Test 7: Manual disconnect stops any active reconnect task cleanly."""
    svc = cortex_service_instance
    svc._should_reconnect = True

    # Start a running reconnect loop with a pause event
    reconnect_started = asyncio.Event()
    reconnect_blocker = asyncio.Event()

    async def blocking_sleep(delay):
        reconnect_started.set()
        await reconnect_blocker.wait()

    with patch("asyncio.sleep", side_effect=blocking_sleep):
        task = asyncio.create_task(svc._reconnect_loop(reason="Manual test"))
        svc._reconnect_task = task
        await reconnect_started.wait()

        assert not task.done()
        assert svc._should_reconnect is True

        # User calls disconnect()
        await svc.disconnect()

        assert svc._should_reconnect is False
        assert svc._reconnect_task is None
        assert task.done() or task.cancelled()


@pytest.mark.asyncio
async def test_successful_reconnect_restores_authentication_flow(cortex_service_instance):
    """Test 8: Successful reconnect initiates authentication, session creation, and profile reloading."""
    svc = cortex_service_instance
    svc._should_reconnect = True
    svc.active_profile = "trained_alpha_profile"
    svc.client_id = "CID-1234"
    svc.client_secret = "SEC-5678"

    # Reset state to simulate drop
    svc._reset_state()
    # Confirm active_profile saved for re-handshake
    assert svc._saved_profile == "trained_alpha_profile"

    auth_subscribed = False

    async def mock_auth_subscribe():
        nonlocal auth_subscribed
        auth_subscribed = True
        svc.is_authorized = True
        svc.is_session_active = True
        svc.is_subscribed = True
        # If saved profile exists, reload it
        if svc._saved_profile:
            svc.active_profile = svc._saved_profile

    async def mock_connect():
        svc.is_connected = True
        svc._auth_task = asyncio.create_task(mock_auth_subscribe())
        return {"status": "connected"}

    with patch("asyncio.sleep", new_callable=AsyncMock), \
         patch.object(svc, "connect", side_effect=mock_connect):
        
        await svc._reconnect_loop(reason="Recovery test")

    assert auth_subscribed is True
    assert svc.is_authorized is True
    assert svc.is_session_active is True
    assert svc.is_subscribed is True
    assert svc.active_profile == "trained_alpha_profile"


@pytest.mark.asyncio
async def test_terminal_visual_output_exact_format(cortex_service_instance, capsys):
    """Test 9: Verify terminal outputs conform strictly to the required reviewer specification."""
    svc = cortex_service_instance
    svc._should_reconnect = True

    async def mock_connect_fail_then_ok():
        if svc.reconnect_attempts == 1:
            return {"status": "error", "message": "First try failure"}
        svc.is_connected = True
        return {"status": "connected"}

    with patch("asyncio.sleep", new_callable=AsyncMock), \
         patch.object(svc, "connect", side_effect=mock_connect_fail_then_ok):
        
        await svc._reconnect_loop(reason="Simulated dropout")

    out = capsys.readouterr().out
    
    # 1. Reconnecting attempt 1
    assert "========== RECONNECT HANDLER ==========" in out
    assert "Status      : RECONNECTING" in out
    assert "Attempt     : 1" in out
    assert "Next Retry  : 2.0 seconds" in out

    # 2. Attempt 1 failed
    assert "[RECONNECT] Attempt 1 FAILED" in out
    assert "[RECONNECT] Retrying with backoff: 4.0 seconds" in out

    # 3. Reconnecting attempt 2
    assert "Attempt     : 2" in out
    assert "Next Retry  : 4.0 seconds" in out

    # 4. Successful recovery banner
    assert "========== BCI CONNECTION ==========" in out
    assert "Status      : CONNECTED" in out
    assert "Result      : Reconnected Successfully" in out
    assert "Attempts    : 2" in out
