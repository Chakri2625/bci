def resolve_command(command, state):
    cmd_upper = str(command).upper().replace("+", "_").replace(" ", "_")
    if cmd_upper in ("PUSH_RIGHT", "BACK", "W_D"):
        return {"type": "navigate_back", "level": max(1, state.get("current_level", 1) - 1), "domain": state.get("active_domain"), "app": None}
    if cmd_upper in ("PUSH_LEFT", "HOME", "W_A"):
        return {"type": "navigate_home", "level": 1, "domain": None, "app": None}

    # Use fallback keys to support both state structures
    level = state.get("level", state.get("current_level", 1))
    domain = state.get("domain", state.get("active_domain"))
    app = state.get("application", state.get("active_app"))

    # Check direct IoT commands regardless of navigation state
    cmd_upper = command.upper()
    direct_iot_map = {
        "LEFT_LIGHT_ON": ("LIGHT", "Left_light_on"),
        "LEFT_LIGHT_OFF": ("LIGHT", "Left_light_off"),
        "LEFT_FAN_ON": ("FAN", "Left_fan_on"),
        "LEFT_FAN_OFF": ("FAN", "Left_fan_off"),
        "LEFT_PUMP_ON": ("PUMP", "Left_pump_on"),
        "LEFT_PUMP_OFF": ("PUMP", "Left_pump_off"),
        "RIGHT_LIGHT_ON": ("LIGHT", "right_light_on"),
        "RIGHT_LIGHT_OFF": ("LIGHT", "right_light_off"),
        "RIGHT_FAN_ON": ("FAN", "right_fan_on"),
        "RIGHT_FAN_OFF": ("FAN", "right_fan_off"),
        "TOGGLE_LIGHT": ("LIGHT", "toggle_light"),
        "TOGGLE_FAN": ("FAN", "toggle_fan"),
        "TOGGLE_PUMP": ("PUMP", "toggle_pump"),
        "TURN ON": ("LIGHT", "turn on"),
        "TURN OFF": ("LIGHT", "turn off"),
        "GET_STATUS": (app or "LIGHT", "GET_STATUS"),
    }
    if cmd_upper in direct_iot_map:
        target_app, act_name = direct_iot_map[cmd_upper]
        return {"type": "action", "level": 3, "domain": "IOT", "app": app or target_app, "action": act_name}

    if level == 1:
        domain_map = {"PUSH": "PYTHON", "PULL": "EMBEDDED", "LEFT": "IOT", "RIGHT": "AIML"}
        if command in domain_map:
            return {"type": "transition", "level": 2, "domain": domain_map[command], "app": None}
            
    elif level == 2 and domain == "PYTHON":
        app_map = {"PUSH": "YOUTUBE", "PULL": "CHROME", "LEFT": "NOTEPAD", "RIGHT": "GMAIL"}
        if command in app_map:
            return {"type": "transition", "level": 3, "domain": domain, "app": app_map[command]}

    elif level == 2 and domain == "AIML":
        app_map = {
            "PUSH": "MOBILE",
            "PULL": "DESKTOP",
            "JIOSAAVN": "MOBILE",
            "MOBILE": "MOBILE",
            "DESKTOP": "DESKTOP"
        }
        if command in app_map:
            return {"type": "transition", "level": 3, "domain": domain, "app": app_map[command]}

    elif level == 2 and domain == "EMBEDDED":
        app_map = {"PUSH": "RC_CAR"}
        if command in app_map:
            return {"type": "transition", "level": 3, "domain": domain, "app": app_map[command]}

    elif level == 2 and domain == "IOT":
        app_map = {"PUSH": "LIGHT", "PULL": "FAN", "LEFT": "PUMP"}
        if command in app_map:
            return {"type": "transition", "level": 3, "domain": domain, "app": app_map[command]}

    elif level == 3 and domain == "PYTHON" and app is not None:
        media_apps = ["YOUTUBE"]
        if app in media_apps:
            valid_commands = ["PUSH", "PULL", "LEFT", "RIGHT"]
            if command in valid_commands:
                return {"type": "action", "level": 3, "domain": "MEDIA", "app": app, "action": command}
        else:
            action_map = {
                "CHROME": {"PUSH": "open_predefined_article", "PULL": "scroll_up", "LEFT": "scroll_down", "RIGHT": "open_search_bar"},
                "NOTEPAD": {"PUSH": "open_notepad", "PULL": "save_file"},
                "GMAIL": {"PUSH": "compose_email", "PULL": "send_email"}
            }
            app_actions = action_map.get(app, {})
            if command in app_actions:
                return {"type": "action", "level": 3, "domain": domain, "app": app, "action": app_actions[command]}
    elif level == 3 and domain == "AIML" and app in ["JIOSAAVN", "MOBILE", "DESKTOP"]:
        valid_commands = ["PUSH", "PULL", "LEFT", "RIGHT"]
        if command in valid_commands:
            return {"type": "action", "level": 3, "domain": "AIML", "app": app, "action": command}
    elif level == 3 and domain == "EMBEDDED" and app == "RC_CAR":
        action_map = {"PUSH": "FORWARD", "PULL": "BACKWARD", "LEFT": "LEFT", "RIGHT": "RIGHT", "STOP": "STOP"}
        if command in action_map:
            return {"type": "action", "level": 3, "domain": domain, "app": app, "action": action_map[command]}
    elif level == 3 and domain == "IOT" and app is not None:
        iot_action_map = {
            "LIGHT": {"RIGHT": "Left_light_on", "LEFT": "Left_light_off"},
            "FAN": {"RIGHT": "Left_fan_on", "LEFT": "Left_fan_off"},
            "PUMP": {"RIGHT": "Left_pump_on", "LEFT": "Left_pump_off"}
        }
        app_actions = iot_action_map.get(app, {})
        if command in app_actions:
            return {"type": "action", "level": 3, "domain": domain, "app": app, "action": app_actions[command]}
        cmd_upper = command.upper()
        for act in app_actions.values():
            if cmd_upper == act.upper():
                return {"type": "action", "level": 3, "domain": domain, "app": app, "action": act}

    elif domain == "IOT":
        cmd_upper = command.upper()
        direct_map = {
            "LEFT_LIGHT_ON": ("LIGHT", "Left_light_on"),
            "LEFT_LIGHT_OFF": ("LIGHT", "Left_light_off"),
            "LEFT_FAN_ON": ("FAN", "Left_fan_on"),
            "LEFT_FAN_OFF": ("FAN", "Left_fan_off"),
            "LEFT_PUMP_ON": ("PUMP", "Left_pump_on"),
            "LEFT_PUMP_OFF": ("PUMP", "Left_pump_off"),
            "RIGHT_LIGHT_ON": ("LIGHT", "right_light_on"),
            "RIGHT_LIGHT_OFF": ("LIGHT", "right_light_off"),
            "RIGHT_FAN_ON": ("FAN", "right_fan_on"),
            "RIGHT_FAN_OFF": ("FAN", "right_fan_off"),
            "TOGGLE_LIGHT": ("LIGHT", "toggle_light"),
            "TOGGLE_FAN": ("FAN", "toggle_fan"),
            "TOGGLE_PUMP": ("PUMP", "toggle_pump"),
            "TURN ON": ("LIGHT", "turn on"),
            "TURN OFF": ("LIGHT", "turn off"),
            "GET_STATUS": (app or "LIGHT", "GET_STATUS"),
        }
        if cmd_upper in direct_map:
            target_app, act_name = direct_map[cmd_upper]
            return {"type": "action", "level": 3, "domain": "IOT", "app": app or target_app, "action": act_name}

    return {"type": "no_action"}

def navigate_back(state):
    level = state.get("current_level", 1)
    if level == 3:
        return {"current_level": 2, "active_app": None, "last_resolved_action": "Previous Stage"}
    elif level == 2:
        return {"current_level": 1, "active_domain": None, "active_app": None, "last_resolved_action": "Previous Stage"}
    return {"last_resolved_action": "Previous Stage"}

def navigate_home(state):
    return {"current_level": 1, "active_domain": None, "active_app": None, "last_resolved_action": "Domain Selection"}
