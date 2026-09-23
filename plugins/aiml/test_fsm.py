import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from command_system.fsm_controller import FSMController

# Mock execute_action
import command_system.command_mapper as mapper

def mock_execute_action(target, action):
    print(f"MOCK_EXECUTE -> TARGET: {target} | ACTION: {action}")

mapper.execute_action = mock_execute_action

def run_tests():
    print("--- Running FSM Tests ---\n")
    
    def reset_fsm():
        return FSMController()

    fsm = reset_fsm()
    print("TEST 1: Input 'right' -> AI/ML domain selected")
    fsm.process_command("right")
    assert fsm.get_state() == "SUB_MASTER_DASHBOARD"
    print("PASS\n")

    fsm = reset_fsm()
    print("TEST 2: Input 'right', 'push' -> Mobile Dashboard selected")
    fsm.process_command("right")
    fsm.process_command("push")
    assert fsm.selected_dashboard == "mobile"
    print("PASS\n")
    
    print("TEST 3: Input 'right', 'push', Start Automation -> Mobile Dashboard opens")
    fsm.ui_start_automation("mobile")
    assert fsm.get_state() == "MOBILE_DASHBOARD_ACTIVE"
    print("PASS\n")
    
    fsm = reset_fsm()
    print("TEST 4: Input 'right', 'pull', Start Automation -> Desktop Dashboard opens")
    fsm.process_command("right")
    fsm.process_command("pull")
    fsm.ui_start_automation("desktop")
    assert fsm.get_state() == "DESKTOP_DASHBOARD_ACTIVE"
    print("PASS\n")
    
    print("TEST 5: Input 'right' (wait), 'push' -> Volume Up")
    # We are already in DESKTOP_DASHBOARD_ACTIVE
    fsm.process_command("right")
    assert fsm.get_state() == "RIGHT_COMBINATION_WAIT"
    fsm.process_command("push") # Volume Up
    assert fsm.get_state() == "DESKTOP_DASHBOARD_ACTIVE"
    print("PASS\n")
    
    print("TEST 6: Input 'right' (wait), 'pull' -> Volume Down")
    fsm.process_command("right")
    fsm.process_command("pull")
    print("PASS\n")
    
    print("TEST 7: Input 'right' (wait), 'left' -> Return to Level 2")
    fsm.process_command("right")
    fsm.process_command("left")
    assert fsm.get_state() == "SUB_MASTER_DASHBOARD"
    print("PASS\n")
    
    print("TEST 8: Input 'left' -> Return to Level 1 from Level 2")
    fsm.process_command("left")
    assert fsm.get_state() == "DOMAIN_SELECTION"
    print("PASS\n")
    
    print("ALL TESTS PASSED!")

if __name__ == "__main__":
    run_tests()
