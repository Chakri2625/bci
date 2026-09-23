/**
 * test_state_machine.js
 * Verification test for BCI State Machine and Command Pipeline.
 */

const BCIStateMachine = require('./state_machine');

console.log("=== RUNNING BCI STATE MACHINE TESTS ===");

const sm = new BCIStateMachine({
  powerThreshold: 0.3,
  debounceMs: 50, // fast for testing
  autoReturnTimeoutMs: 500
});

let testPassed = 0;
let testFailed = 0;

function assert(condition, message) {
  if (condition) {
    console.log(`✅ PASS: ${message}`);
    testPassed++;
  } else {
    console.error(`❌ FAIL: ${message}`);
    testFailed++;
  }
}

// Track dispatches
const dispatchedCommands = [];
sm.on('actuator_command', (cmd) => {
  dispatchedCommands.push(cmd);
});

async function runTests() {
  // Test 1: Initial state
  assert(sm.currentState === 'SELECT_APPLIANCE', 'Initial state is SELECT_APPLIANCE');
  assert(sm.selectedDevice === null, 'Initial selected device is null');

  // Test 2: Threshold rejection
  sm.processMentalCommand('push', 0.1);
  assert(sm.selectedDevice === null, 'Command below threshold (0.1) is rejected');

  // Test 3: Select Light (push)
  await new Promise(r => setTimeout(r, 60));
  sm.processMentalCommand('push', 0.8);
  assert(sm.currentState === 'CONTROL_DEVICE', 'State transitioned to CONTROL_DEVICE');
  assert(sm.selectedDevice === 'light', 'Selected device is LIGHT');

  // Test 4: Turn Light ON (right)
  await new Promise(r => setTimeout(r, 60));
  sm.processMentalCommand('right', 0.85);
  assert(sm.deviceStates.light === 'ON', 'Light state is ON');
  assert(dispatchedCommands.length === 1 && dispatchedCommands[0].device === 'light' && dispatchedCommands[0].state === 'ON', 'Dispatched LIGHT:ON');

  // Test 5: Turn Light OFF (left)
  await new Promise(r => setTimeout(r, 60));
  sm.processMentalCommand('left', 0.85);
  assert(sm.deviceStates.light === 'OFF', 'Light state is OFF');
  assert(dispatchedCommands.length === 2 && dispatchedCommands[1].device === 'light' && dispatchedCommands[1].state === 'OFF', 'Dispatched LIGHT:OFF');

  // Test 6: Verify Domain is LOCKED (pull does NOT switch away from light)
  await new Promise(r => setTimeout(r, 60));
  sm.processMentalCommand('pull', 0.75);
  assert(sm.selectedDevice === 'light', 'Domain remains locked on LIGHT (pull does not switch device)');

  // Test 7: Combo PUSH + PULL -> Return to Selection Mode
  await new Promise(r => setTimeout(r, 60));
  sm.processMentalCommand('push', 0.85);
  await new Promise(r => setTimeout(r, 60));
  sm.processMentalCommand('pull', 0.85);
  assert(sm.currentState === 'SELECT_APPLIANCE', 'Combo PUSH+PULL returned to SELECT_APPLIANCE');
  assert(sm.selectedDevice === null, 'Selected device is null after domain exit');

  // Test 8: Select Pump (left)
  await new Promise(r => setTimeout(r, 60));
  sm.processMentalCommand('left', 0.8);
  assert(sm.currentState === 'CONTROL_DEVICE', 'State transitioned to CONTROL_DEVICE for Pump');
  assert(sm.selectedDevice === 'pump', 'Selected device is PUMP');

  // Test 9: Turn Pump ON (right)
  await new Promise(r => setTimeout(r, 60));
  sm.processMentalCommand('right', 0.8);
  assert(sm.deviceStates.pump === 'ON', 'Pump state is ON');

  // Test 10: Turn Pump OFF (left)
  await new Promise(r => setTimeout(r, 60));
  sm.processMentalCommand('left', 0.8);
  assert(sm.deviceStates.pump === 'OFF', 'Pump state is OFF');

  console.log("\n=======================================");
  console.log(`TEST SUMMARY: ${testPassed} Passed, ${testFailed} Failed`);
  console.log("=======================================");

  if (testFailed > 0) {
    process.exit(1);
  }
}

runTests();
