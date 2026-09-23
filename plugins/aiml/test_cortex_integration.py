"""Test script to verify Cortex integration with command window and updated mappings.

This script tests the updated Cortex integration flow:
1. Cortex bridge receives command
2. Command window collects commands
3. FSM processes command sequences with new mappings
4. Result callback emits to UI
"""

import sys
import logging
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from command_system.fsm_controller import FSMController
from command_system.command_mapper import CommandMapper
from command_system.command_window import CommandWindow
from backend.command_router import command_router

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def test_cortex_window_integration():
    """Test the Cortex integration flow with command window."""
    logger.info("=== Testing Cortex Integration with Command Window ===")
    
    # Create command window
    mock_window_results = []
    
    def window_callback(commands, confidences):
        """Mock callback to capture window results."""
        logger.info(f"[MOCK WINDOW CALLBACK] Window closed with: {commands}")
        mock_window_results.append((commands, confidences))
    
    command_window = CommandWindow(
        window_duration=2.0,  # 2s for test speed; live 8.0
        confidence_threshold=0.35,  # updated per config change
        command_callback=window_callback,
        logger=logger,
    )
    
    # Create FSM controller with callback
    mock_fsm_results = []
    
    def fsm_callback(result):
        """Mock callback to capture FSM results."""
        logger.info(f"[MOCK FSM CALLBACK] Received result: {result.get('command')} -> {result.get('action')}")
        mock_fsm_results.append(result)
    
    fsm = FSMController(mapper=CommandMapper(command_router=command_router, dry_run=True), dry_run=True)
    fsm.set_result_callback(fsm_callback)
    
    # Set to Level 3 for media control testing
    fsm.current_state = "MOBILE_DASHBOARD_ACTIVE"
    fsm.target_device = "mobile"
    
    # Test 1: Single command through window
    logger.info("\n--- Test 1: Single command (PUSH, 0.85) through window ---")
    command_window.add_command("push", 0.85)
    time.sleep(2.5)  # Wait for window to close
    
    assert len(mock_window_results) == 1, "Should have one window result"
    assert mock_window_results[0][0] == ["push"], "Should have single PUSH"
    
    # Process through FSM
    result = fsm.process_command_sequence(mock_window_results[0][0], mock_window_results[0][1])
    assert result["action"] == "next_track", "PUSH should be NEXT_TRACK at Level 3"
    logger.info("✓ Test 1 passed: Single command through window → NEXT_TRACK")
    
    # Test 2: Double command through window (true 8s grouping: wait for expiry, not immediate)
    logger.info("\n--- Test 2: Double command (RIGHT, PUSH) through window (wait for 8s expiry) ---")
    mock_window_results.clear()
    mock_fsm_results.clear()
    
    fsm.current_state = "MOBILE_DASHBOARD_ACTIVE"
    fsm.target_device = "mobile"
    
    command_window.add_command("right", 0.90)
    command_window.add_command("push", 0.85)
    time.sleep(0.5)
    assert len(mock_window_results) == 0, "Should not flush immediately; must wait for window expiry per spec"
    time.sleep(2.0)  # Wait for window expiry (2s test window, live 8s)
    
    assert len(mock_window_results) == 1, "Should have one window result after expiry"
    assert mock_window_results[0][0] == ["right", "push"], "Should have ordered RIGHT + PUSH"
    
    # Process through FSM
    result = fsm.process_command_sequence(mock_window_results[0][0], mock_window_results[0][1])
    assert result["action"] == "volume_up", "RIGHT + PUSH should be VOLUME_UP"
    logger.info("✓ Test 2 passed: Double command through window → VOLUME_UP")
    
    # Test 3: Low confidence rejected by window
    logger.info("\n--- Test 3: Low confidence (PUSH, 0.25) rejected by window ---")
    mock_window_results.clear()
    
    command_window.add_command("push", 0.25)
    time.sleep(2.5)  # Wait for window to close
    
    assert len(mock_window_results) == 0, "Low confidence should not trigger window"
    logger.info("✓ Test 3 passed: Low confidence rejected by window")
    
    # Test 4: RIGHT is now SEARCH (single-line at Level 3)
    logger.info("\n--- Test 4: RIGHT → SEARCH (single-line at Level 3) ---")
    mock_window_results.clear()
    mock_fsm_results.clear()
    
    fsm.current_state = "MOBILE_DASHBOARD_ACTIVE"
    fsm.target_device = "mobile"
    
    command_window.add_command("right", 0.90)
    time.sleep(2.5)  # Wait for window to close
    
    assert len(mock_window_results) == 1, "Should have one window result"
    assert mock_window_results[0][0] == ["right"], "Should have single RIGHT"
    
    # Process through FSM
    result = fsm.process_command_sequence(mock_window_results[0][0], mock_window_results[0][1])
    assert result["action"] == "search", "RIGHT should be SEARCH at Level 3"
    logger.info("✓ Test 4 passed: RIGHT → SEARCH (updated mapping)")
    
    # Test 5: PUSH + LEFT → Back to AI/ML (per SynaptiMesh spec's 4th double, ordered)
    logger.info("\n--- Test 5: PUSH + LEFT → Back to AI/ML (spec double, ordered) ---")
    mock_window_results.clear()
    mock_fsm_results.clear()
    
    fsm.current_state = "MOBILE_DASHBOARD_ACTIVE"
    fsm.target_device = "mobile"
    
    command_window.add_command("push", 0.87)
    command_window.add_command("left", 0.83)
    time.sleep(0.5)
    assert len(mock_window_results) == 0, "Should not flush immediately; wait for expiry"
    time.sleep(2.0)
    
    assert len(mock_window_results) == 1, "Should have one window result after expiry"
    assert mock_window_results[0][0] == ["push", "left"], "Should have ordered PUSH + LEFT"
    
    # Process through FSM
    result = fsm.process_command_sequence(mock_window_results[0][0], mock_window_results[0][1])
    assert result["action"] == "back_to_main_dashboard", "PUSH + LEFT should be back_to_main_dashboard"
    logger.info("✓ Test 5 passed: PUSH + LEFT → back_to_main_dashboard (spec)")
    
    logger.info("\n=== Cortex Integration with Command Window Tests Passed ===")
    logger.info(f"Total window callbacks: {len(mock_window_results)}")
    logger.info(f"Total FSM callbacks: {len(mock_fsm_results)}")
    logger.info("Integration flow verified successfully")

if __name__ == "__main__":
    try:
        test_cortex_window_integration()
    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)