# Command Window Integration - Architecture Summary

## Overview

This document describes the updated Cortex integration for `sub_master` with command windowing and updated command mappings.

## Architecture Changes

### Previous Architecture
```
Cortex → cortex_bridge.py → FSMController → CommandMapper → CommandRouter → Mobile/Desktop
```

### New Architecture
```
Cortex → cortex_bridge.py → command_window.py → FSMController → CommandMapper → CommandRouter → Mobile/Desktop
```

The command window is inserted between the Cortex bridge and FSM to determine single-line vs double-line commands.

## New Components

### command_window.py
**Location:** `command_system/command_window.py`

**Responsibilities:**
- Collect Cortex commands within a time window (2 seconds)
- Apply 0.35 confidence threshold
- Determine if 1 or 2 commands were received
- Preserve command order
- Output single-line or double-line command sequences

**Key Features:**
- 2-second window duration
- 0.35 confidence threshold
- Maximum 2 commands per window
- Window closes immediately when 2 commands received
- Automatic window closure after timeout
- Thread-safe command collection

## Updated Command Mappings

### Level 2 (Dashboard Selection)
- `PUSH` → Mobile Dashboard
- `PULL` → Desktop Dashboard

### Level 3 (Media Control) - Single Commands
- `PUSH` → Next Track
- `PULL` → Previous Track
- `RIGHT` → Search (NEW - was prefix)
- `LEFT` → Play/Pause

### Level 3 (Media Control) - Double Commands
- `RIGHT + PUSH` → Volume +
- `RIGHT + PULL` → Volume -
- `PULL + PUSH` → Search (NEW)
- `PUSH + RIGHT` → Back to Level 2 (NEW)
- `PUSH + LEFT` → Back to Main Dashboard (NEW)

**Important:** Command order is preserved. For example:
- `RIGHT + PUSH` → Volume +
- `PUSH + RIGHT` → Back to Level 2

These are different commands.

## FSM Controller Changes

### New Methods
- `process_command_sequence(commands, confidences, timestamp)` - Process command sequences from window
- `_process_single_command(command, confidence, timestamp)` - Handle single-line commands
- `_process_double_command(commands, confidence, timestamp)` - Handle double-line commands
- `_map_double_command(combination, cmd1, cmd2)` - Map combinations to actions
- `_execute_action(action, confidence, timestamp)` - Execute double-line actions

### Updated Methods
- `_handle_level3()` - Updated to treat RIGHT as SEARCH instead of prefix
- `_result()` - Added optional dispatch parameter

## States Changes

### New Actions
- `BACK_TO_LEVEL_2` - Navigate back to Level 2
- `BACK_TO_MAIN_DASHBOARD` - Navigate back to Level 1

## app.py Changes

### Initialization
- Added command window initialization with 2-second duration and 0.35 threshold
- Updated Cortex bridge callback to route commands to command window
- Command window callback processes sequences through FSM

### Data Flow
```
Cortex Bridge → Command Window → FSM Controller → Command Router → Mobile/Desktop
```

## Command Window Behavior

### Single Command Example
```
Time 0.0: PUSH (0.85)
Time 2.0: Window closes
Result: [PUSH] → Single-line → Next Track (at Level 3)
```

### Double Command Example
```
Time 0.0: RIGHT (0.90)
Time 0.5: PUSH (0.78)
Time 0.5: Window closes immediately
Result: [RIGHT, PUSH] → Double-line → Volume +
```

### Timeout Example
```
Time 0.0: PUSH (0.85)
Time 2.5: RIGHT (0.90)
Result: [PUSH] → Single-line → Next Track (first window)
        [RIGHT] → Single-line → Search (second window)
```

## Confidence Threshold

- **Cortex threshold:** 0.35 (for command window)
- **Mobile/Desktop threshold:** 0.80 (unchanged for existing systems)

Commands below 0.35 are rejected by the command window and never reach the FSM.

## Testing

### Test Files
- `test_command_window.py` - Tests command window functionality and updated mappings
- `test_cortex_integration.py` - Tests Cortex integration with command window

### Test Coverage
✅ Command window basic functionality
✅ Single command collection
✅ Double command collection
✅ Low confidence rejection
✅ Updated Level 3 mappings (RIGHT → SEARCH)
✅ Updated Level 2 mappings
✅ All 5 double-line combinations
✅ Order sensitivity preservation
✅ Hierarchy preservation

## Key Principles Preserved

1. **Hierarchy intact:** Existing 3-level hierarchy (DOMAIN_SELECTION → SUB_MASTER_DASHBOARD → LEVEL_3) unchanged
2. **No UI changes:** Existing dashboards work automatically
3. **Existing functionality:** Manual commands continue to work exactly as before
4. **Separation of concerns:** Window determines command count, FSM determines meaning
5. **CommandRouter reuse:** No changes to existing command routing

## Configuration

### Environment Variables
```bash
export CORTEX_CLIENT_ID="your_client_id"
export CORTEX_CLIENT_SECRET="your_client_secret"
```

### Window Settings
- Window duration: 2.0 seconds (configurable)
- Confidence threshold: 0.35 (configurable)
- Max commands per window: 2 (fixed)

## Running the System

```bash
cd /Users/rohansidharthsamala/Documents/BCI_CODE/sprint6/sprint9/18-08-26/sub_master
export CORTEX_CLIENT_ID="your_client_id"
export CORTEX_CLIENT_SECRET="your_client_secret"
python3 app.py
```

## Architecture Summary

```
                    EMOTIV HEADSET
                           ↓
                        CORTEX
                           ↓
                 cortex_bridge.py (EXISTING)
                           ↓
                 command_window.py (NEW)
                           ↓
                ┌──────────┴──────────┐
                │                     │
           1 command              2 commands
                │                     │
          SINGLE-LINE            DOUBLE-LINE
                │                     │
                └──────────┬──────────┘
                           ↓
                    FSMController (UPDATED)
                           ↓
                    Current Level
                           ↓
            NEW MAPPINGS + EXISTING MAPPINGS
                           ↓
                    CommandMapper (EXISTING)
                           ↓
                    CommandRouter (EXISTING)
                    ↙          ↘
                 MOBILE       DESKTOP
                   ↓             ↓
                 MQTT        Selenium
                   ↓             ↓
                Android       JioSaavn
```

## Success Criteria Met

✅ Command window determines command count (1 vs 2)
✅ FSM determines command meaning based on hierarchy level
✅ Hierarchy preserved (3 levels intact)
✅ Updated command mappings implemented
✅ 0.35 confidence threshold for Cortex
✅ 2-second command window duration
✅ 5 double-line combinations with order sensitivity
✅ RIGHT changed from prefix to SEARCH (single-line)
✅ Existing functionality preserved
✅ No UI changes required
✅ Existing manual commands work unchanged
