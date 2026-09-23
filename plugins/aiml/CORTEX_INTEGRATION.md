# Cortex Integration for Emotiv EPOC X Headset

## Overview

This integration adds Emotiv Cortex mental command support to the existing sub_master system. Cortex commands flow through the existing FSM command system, preserving all existing functionality while adding brain-computer interface control.

## Architecture

```
EPOC X Headset
    ↓
Cortex (wss://localhost:6868)
    ↓
cortex_bridge.py (NEW)
    ↓
FSMController.process_cortex_command()
    ↓
Existing FSM logic (threshold, state, RIGHT combinations)
    ↓
CommandRouter
    ↓
Mobile (MQTT) / Desktop (Selenium)
```

## Files Changed

### New Files

- **`command_system/cortex_bridge.py`**: Cortex WebSocket connection and command extraction
- **`test_cortex_integration.py`**: Integration tests for Cortex flow

### Modified Files

- **`command_system/fsm_controller.py`**: Added `process_cortex_command()` method and result callback support
- **`app.py`**: Integrated Cortex bridge initialization and startup
- **`requirements.txt`**: Added `websocket-client>=1.0.0`

## Key Features

### 1. Threshold Checking

- Uses `0.35` threshold for Cortex commands (lower for easier detection/testing)
- Applied in `process_cortex_command()` before FSM processing
- Commands below threshold are rejected with logging

### 2. Existing FSM Logic Preserved

- RIGHT double-line logic unchanged
- All existing state transitions maintained
- Command mappings unchanged
- Existing manual commands work exactly as before

### 3. UI Integration

- Cortex commands trigger same `fsm_command_result` event as manual commands
- Master dashboard updates automatically for both manual and Cortex commands
- No UI changes required

### 4. Error Handling

- Cortex connection failures don't crash the application
- Automatic reconnection with exponential backoff
- Self-signed SSL certificate handling for localhost
- Graceful degradation if Cortex unavailable

## Configuration

### Environment Variables

Set these environment variables before running the application:

```bash
export CORTEX_CLIENT_ID="your_client_id"
export CORTEX_CLIENT_SECRET="your_client_secret"
```

If these are not set, the Cortex bridge is disabled and the system runs normally without Cortex support.

### Getting Cortex Credentials

1. Log in to [Emotiv Developer Portal](https://www.emotiv.com/my-account/cortex-apps/)
2. Create a new Cortex app
3. Note the Client ID and Client Secret
4. Approve the app in EMOTIV Launcher (one-time setup)

## Usage

### Starting the Application with Cortex

```bash
# Set environment variables
export CORTEX_CLIENT_ID="your_client_id"
export CORTEX_CLIENT_SECRET="your_client_secret"

# Run the application
python3 app.py
```

### Starting without Cortex

```bash
# Don't set the environment variables, or set them to empty
python3 app.py
```

The application will log:

```
[MASTER HUB] Cortex bridge initialized (will connect on startup)
```

or

```
[MASTER HUB] Cortex bridge disabled (missing CORTEX_CLIENT_ID or CORTEX_CLIENT_SECRET)
```

## Mental Command Mapping

Cortex mental commands map directly to FSM primitives:

| Cortex Command | FSM Primitive | Level 3 Action (when mobile/desktop active) |
| -------------- | ------------- | ------------------------------------------- |
| push           | push          | Next Track                                  |
| pull           | pull          | Previous Track                              |
| left           | left          | Play / Pause                                |
| right          | right         | Prefix for combinations                     |
| neutral        | (ignored)     | N/A                                         |

### RIGHT Combinations (Preserved Logic)

- RIGHT + push → Volume Up
- RIGHT + pull → Volume Down
- RIGHT + right → Search
- RIGHT + left → Return to Level 2
- **6-second timeout window** for second command (FSM combination timeout only)
- If second command arrives after 6 seconds, combination times out and RIGHT is cleared
- **Cortex continues listening continuously** - the 6-second timeout applies only to the FSM combination window, not to Cortex connection

## Testing

Run the integration tests:

```bash
python3 test_cortex_integration.py
```

This tests:

- Threshold checking (0.35)
- Callback mechanism for UI updates
- RIGHT double-line logic preservation
- Combination commands (RIGHT + PUSH = VOLUME_UP)
- Unknown command handling

## Data Flow Example

### Successful Combination (within 6-second window)

```
Cortex: {"com":["right",0.85]}
    ↓
cortex_bridge.py: RIGHT, 0.85
    ↓
process_cortex_command("right", 0.85, threshold=0.35)
    ↓
[LOG] Command accepted: right (power=0.850 >= threshold=0.350)
    ↓
FSM: RIGHT → RIGHT_COMBINATION_WAIT (6-second timer starts)
    ↓
[LOG] Waiting for second command
    ↓
callback: fsm_command_result emitted to UI
    ↓
Cortex: {"com":["push",0.78]} (4 seconds later)
    ↓
cortex_bridge.py: PUSH, 0.78
    ↓
process_cortex_command("push", 0.78, threshold=0.35)
    ↓
FSM: RIGHT + PUSH → VOLUME_UP (within 6-second window)
    ↓
CommandRouter: route("Right_Volume_Up", "mobile")
    ↓
MQTT: publish to Android
    ↓
Android: Volume Up executed
```

### Timeout Example (after 6-second window)

```
Cortex: {"com":["right",0.85]}
    ↓
FSM: RIGHT → RIGHT_COMBINATION_WAIT (6-second timer starts)
    ↓
... 7 seconds pass ...
    ↓
Cortex: {"com":["push",0.78]}
    ↓
FSM: Combination timeout after 6.0s - pending 'right' dropped
    ↓
FSM: PUSH → NEXT_TRACK (treated as normal single command)
    ↓
CommandRouter: route("Right_Next_Song", "mobile")
    ↓
Android: Next Track executed
```

## Logging

Cortex integration adds these log markers:

- `[CORTEX]`: Cortex bridge events
- `[CORTEX BRIDGE]`: Command forwarding to FSM
- `[CORTEX] Command accepted/rejected`: Threshold checking
- `[STATE]`, `[COMMAND]`, `[ACTION]`: Existing FSM logging

## Troubleshooting

### Cortex Connection Fails

1. Ensure EMOTIV Launcher is running
2. Check that headset is connected and status is "connected"
3. Verify Client ID and Client Secret are correct
4. Check that you approved the app in EMOTIV Launcher
5. Check logs for SSL certificate errors

### Commands Not Being Processed

1. Check threshold (commands below 0.35 are rejected)
2. Verify FSM state (must be in appropriate state for command)
3. Check logs for `[CORTEX] Command accepted/rejected` messages
4. Ensure target device is selected for Level 3 commands

### UI Not Updating

1. Check that `fsm_command_result` events are being received
2. Verify SocketIO connection to `/master` namespace
3. Check browser console for SocketIO errors
4. Ensure result callback is properly set in FSM

## Safety Features

- **Non-blocking**: Cortex connection runs in background thread
- **Graceful degradation**: System works without Cortex
- **Reconnection**: Automatic reconnection on disconnect
- **Threshold protection**: Low-confidence commands rejected
- **Error isolation**: Cortex errors don't crash the application
- **Existing functionality preserved**: Manual commands unchanged

## Future Enhancements

Potential improvements for production use:

- Add Cortex session management (create/destroy sessions on demand)
- Add profile loading for custom mental command training
- Add Cortex status API endpoint for dashboard monitoring
- Add configuration file for Cortex settings
- Add configurable threshold tuning (currently set to 0.35)
- Add command cooldown/rate limiting

## Implementation Notes

- **Threshold**: Uses 0.35 threshold for Cortex commands (lower for easier detection)
- **RIGHT logic**: Existing double-line command logic preserved with 6-second timeout
- **No UI changes**: Dashboard automatically receives Cortex commands
- **SSL handling**: Self-signed certificate handling for localhost
- **Reconnection**: Exponential backoff with max attempts
- **Threading**: Background thread for WebSocket connection
- **Callback pattern**: Result callback for UI updates
- **Combination timeout**: 6-second window for RIGHT second command (configurable via combo_timeout parameter)

## Verification

The integration has been tested and verified to:

- ✅ Use 0.35 threshold for Cortex commands
- ✅ Preserve RIGHT double-line logic with 6-second timeout
- ✅ Trigger same UI events as manual commands
- ✅ Handle connection failures gracefully
- ✅ Not affect existing manual command functionality
- ✅ Support reconnection on disconnect
- ✅ Log all Cortex events for debugging
- ✅ Timeout RIGHT combinations after 6 seconds correctly
