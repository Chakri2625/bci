"""Test script to verify command window functionality and updated mappings.

This script tests the new command windowing system and updated command mappings:
- 8-second command window (2s for test speed, live 8.0) true grouping per updated spec
- 0.35 confidence threshold (updated per config change)
- Single-line vs ordered double-line command detection (§7)
- Updated Level 3 mappings (RIGHT → Search) per spec §8
- New double-line combinations with order sensitivity
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

def test_command_window_basic():
    """Test basic command window functionality (8s grouping, 0.35 threshold, ordered)."""
    logger.info("=== Testing Command Window Basic Functionality (8s window, 0.35 threshold) ===")
    
    mock_results = []
    
    def mock_callback(commands, confidences):
        """Mock callback to capture window results."""
        logger.info(f"[MOCK CALLBACK] Window closed with commands: {commands}")
        mock_results.append((commands, confidences))
    
    window = CommandWindow(
        window_duration=2.0,  # 2s for test speed; live uses 8.0 per updated spec
        confidence_threshold=0.35,  # updated per config change
        command_callback=mock_callback,
        logger=logger,
    )
    
    # Test 1: Single command in window → processed after window expiry
    logger.info("\n--- Test 1: Single command (PUSH, 0.85) → single-line after 8s window ---")
    window.add_command("push", 0.85)
    time.sleep(2.5)  # Wait for window to close
    assert len(mock_results) == 1, "Should have one window result"
    assert mock_results[0][0] == ["push"], "Should have single PUSH command"
    logger.info("✓ Test 1 passed: Single command collected correctly (6s grouping)")
    
    # Test 2: Two commands in window → ordered double, processed after window expiry (not immediate)
    logger.info("\n--- Test 2: Two commands (RIGHT, PUSH) within window → ordered double after expiry ---")
    mock_results.clear()
    window.add_command("right", 0.90)
    window.add_command("push", 0.85)  # >=0.35 threshold
    time.sleep(0.5)  # Before window expiry, should NOT have flushed yet (true 8s grouping)
    assert len(mock_results) == 0, "Window should not flush immediately; must wait for 8s expiry per spec"
    time.sleep(2.0)  # Wait for window to expire
    assert len(mock_results) == 1, "Should have one window result after expiry"
    assert mock_results[0][0] == ["right", "push"], "Should have ordered RIGHT + PUSH (not sorted)"
    logger.info("✓ Test 2 passed: Ordered double collected correctly after 8s expiry")
    
    # Test 3: Low confidence command rejected (reuses 0.35 threshold)
    logger.info("\n--- Test 3: Low confidence command (PUSH, 0.25) rejected ---")
    mock_results.clear()
    window.add_command("push", 0.25)
    time.sleep(2.5)  # Wait for window to close
    assert len(mock_results) == 0, "Low confidence command should not trigger window (0.35 threshold)"
    logger.info("✓ Test 3 passed: Low confidence command rejected")
    
    logger.info("\n=== Command Window Basic Tests Passed ===")

def test_updated_mappings():
    """Test updated command mappings."""
    logger.info("\n=== Testing Updated Command Mappings ===")
    
    mock_results = []
    
    def mock_callback(result):
        """Mock callback to capture FSM results."""
        logger.info(f"[MOCK CALLBACK] Received result: {result.get('command')} -> {result.get('action')}")
        mock_results.append(result)
    
    fsm = FSMController(mapper=CommandMapper(command_router=command_router, dry_run=True), dry_run=True)
    fsm.set_result_callback(mock_callback)
    
    # Set to Level 3 for media control testing
    fsm.current_state = "MOBILE_DASHBOARD_ACTIVE"
    fsm.target_device = "mobile"
    
    # Test 1: RIGHT is now SEARCH (single-line)
    logger.info("\n--- Test 1: RIGHT → SEARCH (single-line) ---")
    result = fsm.process_command("right", confidence=0.90)
    assert result["action"] == "search", "RIGHT should be SEARCH"
    logger.info("✓ Test 1 passed: RIGHT → SEARCH")
    
    # Test 2: PUSH → NEXT_TRACK (unchanged)
    logger.info("\n--- Test 2: PUSH → NEXT_TRACK (unchanged) ---")
    result = fsm.process_command("push", confidence=0.85)
    assert result["action"] == "next_track", "PUSH should be NEXT_TRACK"
    logger.info("✓ Test 2 passed: PUSH → NEXT_TRACK")
    
    # Test 3: PULL → PREVIOUS_TRACK (unchanged)
    logger.info("\n--- Test 3: PULL → PREVIOUS_TRACK (unchanged) ---")
    result = fsm.process_command("pull", confidence=0.82)
    assert result["action"] == "previous_track", "PULL should be PREVIOUS_TRACK"
    logger.info("✓ Test 3 passed: PULL → PREVIOUS_TRACK")
    
    # Test 4: LEFT → PLAY_PAUSE (unchanged)
    logger.info("\n--- Test 4: LEFT → PLAY_PAUSE (unchanged) ---")
    result = fsm.process_command("left", confidence=0.88)
    assert result["action"] == "play_pause", "LEFT should be PLAY_PAUSE"
    logger.info("✓ Test 4 passed: LEFT → PLAY_PAUSE")
    
    logger.info("\n=== Updated Mapping Tests Passed ===")

def test_double_line_combinations():
    """Test new double-line command combinations."""
    logger.info("\n=== Testing Double-Line Combinations ===")
    
    mock_results = []
    
    def mock_callback(result):
        """Mock callback to capture FSM results."""
        logger.info(f"[MOCK CALLBACK] Received result: {result.get('command')} -> {result.get('action')}")
        mock_results.append(result)
    
    fsm = FSMController(mapper=CommandMapper(command_router=command_router, dry_run=True), dry_run=True)
    fsm.set_result_callback(mock_callback)
    
    # Set to Level 3 for media control testing
    fsm.current_state = "MOBILE_DASHBOARD_ACTIVE"
    fsm.target_device = "mobile"
    
    # Test 1: RIGHT + PUSH → VOLUME_UP
    logger.info("\n--- Test 1: RIGHT + PUSH → VOLUME_UP ---")
    result = fsm.process_command_sequence(["right", "push"], [0.90, 0.85])
    assert result["action"] == "volume_up", "RIGHT + PUSH should be VOLUME_UP"
    logger.info("✓ Test 1 passed: RIGHT + PUSH → VOLUME_UP")
    
    # Test 2: RIGHT + PULL → VOLUME_DOWN
    logger.info("\n--- Test 2: RIGHT + PULL → VOLUME_DOWN ---")
    result = fsm.process_command_sequence(["right", "pull"], [0.88, 0.82])
    assert result["action"] == "volume_down", "RIGHT + PULL should be VOLUME_DOWN"
    logger.info("✓ Test 2 passed: RIGHT + PULL → VOLUME_DOWN")
    
    # Test 3: PUSH + RIGHT → BACK_TO_LEVEL_2
    logger.info("\n--- Test 4: PUSH + RIGHT → BACK_TO_LEVEL_2 ---")
    result = fsm.process_command_sequence(["push", "right"], [0.85, 0.89])
    assert result["action"] == "back_to_level_2", "PUSH + RIGHT should be BACK_TO_LEVEL_2"
    assert result["new_state"] == "SUB_MASTER_DASHBOARD", "Should return to Level 2"
    logger.info("✓ Test 4 passed: PUSH + RIGHT → BACK_TO_LEVEL_2")
    
    # Test 5: PUSH + LEFT → BACK_TO_MAIN_DASHBOARD
    logger.info("\n--- Test 5: PUSH + LEFT → BACK_TO_MAIN_DASHBOARD ---")
    fsm.current_state = "MOBILE_DASHBOARD_ACTIVE"  # Reset to Level 3
    result = fsm.process_command_sequence(["push", "left"], [0.86, 0.84])
    assert result["action"] == "back_to_main_dashboard", "PUSH + LEFT should be BACK_TO_MAIN_DASHBOARD"
    assert result["new_state"] == "DOMAIN_SELECTION", "Should return to Level 1"
    logger.info("✓ Test 5 passed: PUSH + LEFT → BACK_TO_MAIN_DASHBOARD")
    
    # Test 6: Order sensitivity - PUSH + RIGHT ≠ RIGHT + PUSH
    logger.info("\n--- Test 6: Order sensitivity (PUSH + RIGHT ≠ RIGHT + PUSH) ---")
    fsm.current_state = "MOBILE_DASHBOARD_ACTIVE"  # Reset to Level 3 for first test
    fsm.target_device = "mobile"
    result1 = fsm.process_command_sequence(["push", "right"], [0.85, 0.89])
    fsm.current_state = "MOBILE_DASHBOARD_ACTIVE"  # Reset to Level 3 for second test
    fsm.target_device = "mobile"
    result2 = fsm.process_command_sequence(["right", "push"], [0.90, 0.85])
    assert result1["action"] == "back_to_level_2", "PUSH + RIGHT should be BACK_TO_LEVEL_2"
    assert result2["action"] == "volume_up", "RIGHT + PUSH should be VOLUME_UP"
    assert result1["action"] != result2["action"], "Order should matter"
    logger.info("✓ Test 6 passed: Order sensitivity preserved")
    
    logger.info("\n=== Double-Line Combination Tests Passed ===")

def test_level_2_mappings():
    """Test Level 2 dashboard selection mappings."""
    logger.info("\n=== Testing Level 2 Mappings ===")
    
    mock_results = []
    
    def mock_callback(result):
        """Mock callback to capture FSM results."""
        logger.info(f"[MOCK CALLBACK] Received result: {result.get('command')} -> {result.get('action')}")
        mock_results.append(result)
    
    fsm = FSMController(mapper=CommandMapper(command_router=command_router, dry_run=True), dry_run=True)
    fsm.set_result_callback(mock_callback)
    
    # Set to Level 2 for dashboard selection testing
    fsm.current_state = "SUB_MASTER_DASHBOARD"
    
    # Test 1: PUSH → SELECT_MOBILE_DASHBOARD
    logger.info("\n--- Test 1: PUSH → SELECT_MOBILE_DASHBOARD ---")
    result = fsm.process_command("push", confidence=0.90)
    assert result["action"] == "select_mobile_dashboard", "PUSH should select Mobile Dashboard"
    logger.info("✓ Test 1 passed: PUSH → SELECT_MOBILE_DASHBOARD")
    
    # Test 2: PULL → SELECT_DESKTOP_DASHBOARD
    logger.info("\n--- Test 2: PULL → SELECT_DESKTOP_DASHBOARD ---")
    result = fsm.process_command("pull", confidence=0.88)
    assert result["action"] == "select_desktop_dashboard", "PULL should select Desktop Dashboard"
    logger.info("✓ Test 2 passed: PULL → SELECT_DESKTOP_DASHBOARD")
    
    logger.info("\n=== Level 2 Mapping Tests Passed ===")

if __name__ == "__main__":
    try:
        test_command_window_basic()
        test_updated_mappings()
        test_double_line_combinations()
        test_level_2_mappings()
        
        logger.info("\n" + "="*60)
        logger.info("ALL COMMAND WINDOW TESTS PASSED")
        logger.info("="*60)
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)