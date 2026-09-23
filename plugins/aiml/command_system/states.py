"""Finite State Machine state and action definitions for the Master Hub.

The Master Hub receives only four BCI primitives (``push``, ``pull``,
``left``, ``right``). Their meaning is interpreted hierarchically based on the
current FSM state, exactly as described in the project spec.

States
------
- DOMAIN_SELECTION        (Level 1) initial state, wait for ``right``
- SUB_MASTER_DASHBOARD    (Level 2) dashboard selection layer
- MOBILE_DASHBOARD_ACTIVE (Level 3) mobile dashboard is open
- DESKTOP_DASHBOARD_ACTIVE(Level 3) desktop dashboard is open
- LEVEL_3_COMMAND_MODE    (Level 3) media control mode entry
- RIGHT_COMBINATION_WAIT  prefix state waiting for the second command
"""

# ---------------------------------------------------------------------------
# BCI primitive commands (the only things the BCI headset provides)
# ---------------------------------------------------------------------------
PUSH = "push"
PULL = "pull"
LEFT = "left"
RIGHT = "right"

PRIMITIVE_COMMANDS = {PUSH, PULL, LEFT, RIGHT}

# ---------------------------------------------------------------------------
# FSM states
# ---------------------------------------------------------------------------
DOMAIN_SELECTION = "DOMAIN_SELECTION"
SUB_MASTER_DASHBOARD = "SUB_MASTER_DASHBOARD"
MOBILE_DASHBOARD_ACTIVE = "MOBILE_DASHBOARD_ACTIVE"
DESKTOP_DASHBOARD_ACTIVE = "DESKTOP_DASHBOARD_ACTIVE"
LEVEL_3_COMMAND_MODE = "LEVEL_3_COMMAND_MODE"
RIGHT_COMBINATION_WAIT = "RIGHT_COMBINATION_WAIT"

INITIAL_STATE = SUB_MASTER_DASHBOARD  # Changed per task: Application starts at Level 2 (Sub-Master) synchronized with UI

# States in which the FSM is at "Level 3" (media control is active).
LEVEL_3_STATES = {
    MOBILE_DASHBOARD_ACTIVE,
    DESKTOP_DASHBOARD_ACTIVE,
    LEVEL_3_COMMAND_MODE,
}

# ---------------------------------------------------------------------------
# High-level actions the FSM can produce
# ---------------------------------------------------------------------------
# Level 1 / navigation
SELECT_AI_ML_DOMAIN = "select_ai_ml_domain"
RETURN_TO_LEVEL_1 = "return_to_level_1"
RETURN_TO_LEVEL_2 = "return_to_level_2"
WAIT_FOR_COMBINATION = "wait_for_combination"
NONE = "none"

# Level 2 (dashboard selection)
SELECT_MOBILE_DASHBOARD = "select_mobile_dashboard"
SELECT_DESKTOP_DASHBOARD = "select_desktop_dashboard"

# Level 1 -> direct open (auto domain selection + open the dashboard)
OPEN_MOBILE_DASHBOARD = "open_mobile_dashboard"
OPEN_DESKTOP_DASHBOARD = "open_desktop_dashboard"

# Level 3 (media control)
NEXT_TRACK = "next_track"
PREVIOUS_TRACK = "previous_track"
PLAY_PAUSE = "play_pause"
VOLUME_UP = "volume_up"
VOLUME_DOWN = "volume_down"
SEARCH = "search"
BACK_TO_LEVEL_2 = "back_to_level_2"
BACK_TO_MAIN_DASHBOARD = "back_to_main_dashboard"

# Display labels for logs / UI
ACTION_LABELS = {
    SELECT_AI_ML_DOMAIN: "Select AI/ML Domain",
    RETURN_TO_LEVEL_1: "Return to Level 1",
    RETURN_TO_LEVEL_2: "Return to Level 2",
    WAIT_FOR_COMBINATION: "Wait for combination command",
    NONE: "No action",
    SELECT_MOBILE_DASHBOARD: "Select Mobile Dashboard",
    SELECT_DESKTOP_DASHBOARD: "Select Desktop Dashboard",
    OPEN_MOBILE_DASHBOARD: "Open Mobile Dashboard",
    OPEN_DESKTOP_DASHBOARD: "Open Desktop Dashboard",
    NEXT_TRACK: "Next Track",
    PREVIOUS_TRACK: "Previous Track",
    PLAY_PAUSE: "Play / Pause",
    VOLUME_UP: "Volume Up",
    VOLUME_DOWN: "Volume Down",
    SEARCH: "Search",
    BACK_TO_LEVEL_2: "Back to Level 2",
    BACK_TO_MAIN_DASHBOARD: "Back to Main Dashboard",
}

STATE_LABELS = {
    DOMAIN_SELECTION: "DOMAIN_SELECTION (Level 1)",
    SUB_MASTER_DASHBOARD: "SUB_MASTER_DASHBOARD (Level 2)",
    MOBILE_DASHBOARD_ACTIVE: "MOBILE_DASHBOARD_ACTIVE (Level 3)",
    DESKTOP_DASHBOARD_ACTIVE: "DESKTOP_DASHBOARD_ACTIVE (Level 3)",
    LEVEL_3_COMMAND_MODE: "LEVEL_3_COMMAND_MODE (Level 3)",
    RIGHT_COMBINATION_WAIT: "RIGHT_COMBINATION_WAIT (Level 3 prefix)",
}