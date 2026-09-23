import pytest
import asyncio
from core.orchestration.ecosystem_orchestrator import ecosystem_orchestrator
from core.state.state_manager import state_manager
from core.managers.lifecycle_tracker import lifecycle_tracker

@pytest.mark.asyncio
async def test_invalid_transition_no_action_bug():
    """
    Tests the exact production scenario where a corrupt state causes a validation failure 
    and triggers recovery_handler.handle_invalid_transition (the no_action / invalid-transition path).
    Ensures that no AttributeError is thrown due to variable shadowing (rec vs recovery_res).
    """
    session = "test_no_action_session"
    
    # 1. Force a corrupt state to trigger the handle_invalid_transition path natively
    state_manager.update_state(session, {
        "current_level": 5,  # Invalid level
        "active_domain": "UNKNOWN", # Invalid domain
        "active_app": None
    })
    
    # 2. Send any standard command that would normally be validated
    command = "PUSH"
    
    # 3. Process the command (Before the fix, this threw AttributeError: 'RecoveryResult' object has no attribute 'current_stage')
    try:
        result = await ecosystem_orchestrator.process_command(command, session=session)
    except Exception as e:
        pytest.fail(f"process_command raised an exception: {e}")
        
    # 4. Verify structured failure result and no unhandled exceptions
    assert isinstance(result, dict), "Result must be a structured dictionary."
    assert result.get("status") == "no_action", f"Expected 'no_action' status, got {result.get('status')}"
    assert result.get("executed") is False, "Command should not have executed."
    
    # 5. Verify RecoveryResult was handled correctly
    assert result.get("recovery_attempted") is not None, "Recovery should have been attempted or evaluated."
    
    # 6. Verify command IDs and lifecycle are preserved
    command_id = result.get("command_id")
    assert command_id is not None, "command_id must be preserved."
    
    lifecycle_stage = result.get("lifecycle_stage")
    assert lifecycle_stage is not None, "lifecycle_stage must be present and correctly pulled from CommandLifecycleRecord."
    assert lifecycle_stage == "VALIDATION_FAILED", "Should be the raw enum value, which is VALIDATION_FAILED."
    
    lifecycle_dict = result.get("lifecycle")
    assert isinstance(lifecycle_dict, dict), "lifecycle must be a dictionary."
    assert "command_id" in lifecycle_dict, "lifecycle dict must be a true CommandLifecycleRecord dict, not a RecoveryResult dict."
    
    # Verify the underlying lifecycle tracker actually recorded the validation failure
    l_rec = lifecycle_tracker.get_lifecycle(command_id)
    assert l_rec is not None
    assert l_rec.current_stage.value in ("VALIDATION_FAILED", "FAILED")
