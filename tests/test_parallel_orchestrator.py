import pytest
import asyncio
import time
from fastapi.testclient import TestClient
from main import app
from core.state.state_manager import state_manager
from core.navigation.sequence_validator import sequence_validator
from unittest.mock import patch, AsyncMock

client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_state():
    state_manager.states.clear()
    if hasattr(sequence_validator, 'history'):
        sequence_validator.history.clear()

def test_1_single_command_execution():
    state_manager.update_state("default", {"current_level": 3, "active_domain": "IOT", "active_app": "LIGHT"})
    with patch("core.orchestration.ecosystem_orchestrator.retry_manager.execute_with_retry", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = {"status": "success", "result": "light_on"}
        
        response = client.post("/api/v1/bci/command", json={"command": "RIGHT", "device_id": "dev1"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["executed"] is True
        assert mock_exec.call_count == 1

def test_2_and_3_parallel_execution_and_overlap():
    async def run():
        state_manager.update_state("default", {"current_level": 3, "active_domain": "IOT", "active_app": "LIGHT"})
        
        async def slow_execute(*args, **kwargs):
            await asyncio.sleep(0.1)
            return {"status": "success", "result": "done"}
            
        with patch("core.orchestration.ecosystem_orchestrator.retry_manager.execute_with_retry", side_effect=slow_execute) as mock_exec:
            from core.orchestration.ecosystem_orchestrator import ecosystem_orchestrator
            start = time.time()
            
            results = await ecosystem_orchestrator.process_command(["RIGHT", "RIGHT"], device_id="dev1")
            
            duration = time.time() - start
            
            assert len(results) == 2
            assert results[0]["status"] == "success"
            assert results[1]["status"] == "success"
            assert duration < 0.15
            assert mock_exec.call_count == 2
    asyncio.run(run())

def test_4_one_fails_others_continue():
    async def run():
        state_manager.update_state("default", {"current_level": 3, "active_domain": "IOT", "active_app": "LIGHT"})
        
        call_count = 0
        async def selective_fail(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Simulated failure")
            return {"status": "success"}
            
        with patch("core.orchestration.ecosystem_orchestrator.retry_manager.execute_with_retry", side_effect=selective_fail) as mock_exec:
            from core.orchestration.ecosystem_orchestrator import ecosystem_orchestrator
            results = await ecosystem_orchestrator.process_command(["RIGHT", "RIGHT"], device_id="dev1")
            
            assert len(results) == 2
            assert results[0]["status"] == "failed"
            assert "Simulated failure" in results[0]["error"]
            
            assert results[1]["status"] == "success"
            assert mock_exec.call_count == 2
    asyncio.run(run())

def test_5_invalid_commands_rejected():
    async def run():
        state_manager.update_state("default", {"current_level": 1, "active_domain": None, "active_app": None})
        from core.orchestration.ecosystem_orchestrator import ecosystem_orchestrator
        
        with patch("core.orchestration.ecosystem_orchestrator.retry_manager.execute_with_retry", new_callable=AsyncMock) as mock_exec:
            results = await ecosystem_orchestrator.process_command(["JUMP", "PUSH"])
            
            assert len(results) == 2
            assert results[0]["status"] == "invalid"
            assert results[0]["executed"] is False
            
            assert results[1]["status"] == "success"
            assert results[1]["resolved"]["type"] == "transition"
            assert mock_exec.call_count == 0
    asyncio.run(run())

def test_6_conflicting_commands_handled_safely():
    async def run():
        state_manager.update_state("default", {"current_level": 3, "active_domain": "IOT", "active_app": "LIGHT"})
        from core.orchestration.ecosystem_orchestrator import ecosystem_orchestrator
        
        with patch("core.orchestration.ecosystem_orchestrator.retry_manager.execute_with_retry", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {"status": "success"}
            results = await ecosystem_orchestrator.process_command(["RIGHT", "LEFT"], device_id="dev1")
            
            assert len(results) == 2
            assert results[0]["status"] == "success"
            assert results[1]["status"] == "failed"
            assert "Conflict" in results[1]["error"]
            assert mock_exec.call_count == 1
    asyncio.run(run())

def test_7_exception_handling():
    async def run():
        state_manager.update_state("default", {"current_level": 3, "active_domain": "IOT", "active_app": "LIGHT"})
        from core.orchestration.ecosystem_orchestrator import ecosystem_orchestrator
        
        with patch("core.orchestration.ecosystem_orchestrator.retry_manager.execute_with_retry", side_effect=Exception("Critical error")):
            results = await ecosystem_orchestrator.process_command(["RIGHT"], device_id="dev1")
            
            assert len(results) == 1
            assert results[0]["status"] == "failed"
            assert "Critical error" in results[0]["error"]
    asyncio.run(run())
