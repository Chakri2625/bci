import re

_SEPARATOR_RE = re.compile(r'[\s\-\+]+')

ALIASES = {
    "W": "PUSH",
    "S": "PULL",
    "A": "LEFT",
    "D": "RIGHT",
    "SPACE": "STOP",
    "BACK": "PUSH_RIGHT",
    "HOME": "PUSH_LEFT",
    "EMBEDDED": "PULL",
    "ROBOTICS": "PULL",
    "IOT": "LEFT",
    "AIML": "RIGHT",
    "AI": "RIGHT",
    "DESKTOP": "PUSH",
    "PYTHON": "PUSH",
    "W_A": "PUSH_LEFT",
    "W+A": "PUSH_LEFT",
    "W_D": "PUSH_RIGHT",
    "W+D": "PUSH_RIGHT",
    "PUSH_LEFT": "PUSH_LEFT",
    "PUSH+LEFT": "PUSH_LEFT",
    "PUSH_RIGHT": "PUSH_RIGHT",
    "PUSH+RIGHT": "PUSH_RIGHT",
    "RIGHT_PUSH": "RIGHT_PUSH",
    "RIGHT+PUSH": "RIGHT_PUSH",
    "RIGHT_PULL": "RIGHT_PULL",
    "RIGHT+PULL": "RIGHT_PULL",
    "PULL_LEFT": "PULL_LEFT",
    "PULL+LEFT": "PULL_LEFT",
    "PULL_RIGHT": "PULL_RIGHT",
    "PULL+RIGHT": "PULL_RIGHT",
    "LEFT_PUSH": "LEFT_PUSH",
    "LEFT+PUSH": "LEFT_PUSH",
    "LEFT_PULL": "LEFT_PULL",
    "LEFT+PULL": "LEFT_PULL",
}

def normalize_command(command) -> str:
    """
    Normalizes a command string or list to a canonical representation.
    Handles case, whitespace, separators, compound combinations (+, -, space, list), and aliases.
    Invalid or unhandled commands are returned as-is (with case/whitespace normalized)
    so they can be caught by downstream validation.
    """
    if command is None:
        return None

    # Handle list input (e.g. ['PUSH', 'LEFT'] -> 'PUSH_LEFT')
    if isinstance(command, (list, tuple)):
        clean_tokens = [normalize_command(c) for c in command if c is not None and str(c).strip()]
        if not clean_tokens:
            return ""
        if len(clean_tokens) == 1:
            return clean_tokens[0]
        if len(clean_tokens) == 2:
            first, second = clean_tokens[0], clean_tokens[1]
            if first == "PUSH" and second == "LEFT":
                return "PUSH_LEFT"
            elif first == "PUSH" and second == "RIGHT":
                return "PUSH_RIGHT"
            else:
                return f"{first}_{second}"
        return "_".join(clean_tokens)

    if not isinstance(command, str):
        command = str(command)

    # 1. Strip whitespace and uppercase
    cmd = command.strip().upper()

    # Fast-path alias check before regex
    if cmd in ALIASES:
        return ALIASES[cmd]

    # 2. Normalize separators (+, -, spaces, tabs)
    if any(c in cmd for c in (' ', '-', '+', '\t')):
        cmd = _SEPARATOR_RE.sub('_', cmd)

    # 3. Handle shorthand aliases after separator replacement
    return ALIASES.get(cmd, cmd)

