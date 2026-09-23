import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from core.orchestration.ecosystem_orchestrator import ecosystem_orchestrator
from core.managers.lifecycle_tracker import lifecycle_tracker
from core.exceptions import ValidationError, RoutingError, ExecutionError, SynaptiMeshError

@pytest.fixture(autouse=True)
def reset_lifecycle():
    lifecycle_tracker._executions.clear()

def test_validation_error_structured_result():
    with patch("core.orchestration.ecosystem_orchestrator.sequence_validator") as mock_validator:
        mock_validator.validate.return_value = {"is_valid": False, "reason": "Test validation failure"}
        
        result = asyncio.run(ecosystem_orchestrator.process_command("INVALID_CMD", session="test_sess"))
        
        assert result["success"] is False
        assert result["status"] == "invalid"
        assert result["error_code"] == "VALIDATION_FAILED"
        assert result["error"] == "Invalid command sequence"
        
        # Verify LifecycleTracker
        executions = list(lifecycle_tracker._executions.values())
        assert len(executions) == 1
        assert executions[0]["status"] == "FAILED"
        assert executions[0]["error"] == "Invalid command sequence"

def test_execution_error_structured_result():
    with patch("core.orchestration.ecosystem_orchestrator.sequence_validator") as mock_validator, \
         patch("core.orchestration.ecosystem_orchestrator.resolve_command") as mock_resolver, \
         patch("core.orchestration.ecosystem_orchestrator.retry_manager") as mock_retry:
         
        mock_validator.validate.return_value = {"is_valid": True}
        mock_validator.refresh.return_value = {"is_valid": True}
        mock_resolver.return_value = {"type": "action", "domain": "IOT", "app": "LIGHT", "action": "Left_light_on"}
        
        mock_retry.execute_with_retry = AsyncMock(return_value={"status": "FAILED", "reason": "App not responding"})
        
        result = asyncio.run(ecosystem_orchestrator.process_command("PUSH", session="test_sess", device_id="dev1"))
        
        assert result["success"] is False
        assert result["status"] == "failed"
        assert result["error_code"] == "EXECUTION_FAILED"
        assert "App not responding" in result["error"]
        
        executions = list(lifecycle_tracker._executions.values())
        assert len(executions) == 1
        assert executions[0]["status"] == "FAILED"
        assert "App not responding" in executions[0]["error"]

def test_unexpected_exception_structured_result():
    with patch("core.orchestration.ecosystem_orchestrator.sequence_validator") as mock_validator:
        mock_validator.validate.side_effect = Exception("Database disconnected")
        
        result = asyncio.run(ecosystem_orchestrator.process_command("PUSH", session="test_sess"))
        
        assert result["success"] is False
        assert result["status"] == "failed"
        assert result["error_code"] == "EXECUTION_FAILED"
        assert "Database disconnected" in result["error"]

def test_parallel_execution_failure_isolation():
    with patch("core.orchestration.ecosystem_orchestrator.sequence_validator") as mock_validator, \
         patch("core.orchestration.ecosystem_orchestrator.resolve_command") as mock_resolver, \
         patch("core.orchestration.ecosystem_orchestrator.retry_manager") as mock_retry:
         
        def mock_validate(cmd, state):
            if cmd == "BAD_CMD":
                return {"is_valid": False, "reason": "invalid"}
            return {"is_valid": True}
            
        mock_validator.validate.side_effect = mock_validate
        mock_validator.refresh.return_value = {"is_valid": True}
        
        def mock_resolve(cmd, state):
            return {"type": "action", "domain": "IOT", "app": "LIGHT", "action": "Left_light_on"}
        mock_resolver.side_effect = mock_resolve
        
        mock_retry.execute_with_retry = AsyncMock(return_value={"status": "SUCCESS", "result": "ok"})
        
        results = asyncio.run(ecosystem_orchestrator.process_command(["GOOD_CMD", "BAD_CMD"], session="test_sess", device_id="dev1"))
        
        assert len(results) == 2
        
        good = next(r for r in results if r["command"] == "GOOD_CMD")
        bad = next(r for r in results if r["command"] == "BAD_CMD")
        
        assert good["success"] is True
        assert good["status"] == "success"
        
        assert bad["success"] is False
        assert bad["status"] == "invalid"
        assert bad["error_code"] == "VALIDATION_FAILED"

def test_success_result_generation():
    with patch("core.orchestration.ecosystem_orchestrator.sequence_validator") as mock_validator, \
         patch("core.orchestration.ecosystem_orchestrator.resolve_command") as mock_resolver:
         
        mock_validator.validate.return_value = {"is_valid": True}
        mock_validator.refresh.return_value = {"is_valid": True}
        mock_resolver.return_value = {"type": "transition", "level": 2, "domain": "PYTHON", "app": None}
        
        result = asyncio.run(ecosystem_orchestrator.process_command("PUSH", session="test_sess"))
        
        assert result["success"] is True
        assert result["status"] == "success"
        assert "execution_time_ms" in result
        
        executions = list(lifecycle_tracker._executions.values())
        assert len(executions) == 1
        assert executions[0]["status"] == "SUCCESS"
