import re
from typing import List, Union, Dict, Any, Optional

# Movement commands set
MOVEMENT_COMMANDS = {"LEFT", "RIGHT", "PUSH", "PULL", "FORWARD", "BACKWARD", "MOVE"}

# Opposing directional pairs (order independent)
OPPOSING_PAIRS = [
    ({"LEFT", "RIGHT"}, "Conflicting movement commands"),
    ({"PUSH", "PULL"}, "Conflicting movement commands"),
    ({"FORWARD", "BACKWARD"}, "Conflicting movement commands"),
]


class InvalidCombinationRules:
    """
    Module containing rules and logic to detect unsafe, conflicting,
    or redundant navigation command combinations before execution.
    """

    @staticmethod
    def parse_commands(input_data: Union[str, List[str]]) -> List[str]:
        """
        Parse and normalize input commands from a string (e.g. 'LEFT + RIGHT')
        or a list of strings (e.g. ['LEFT', 'RIGHT']).
        """
        if isinstance(input_data, str):
            # Split on +, commas, or whitespace
            raw_tokens = re.split(r'[\+,\s]+', input_data.strip())
            tokens = [t.strip().upper() for t in raw_tokens if t.strip()]
            return tokens
        elif isinstance(input_data, list):
            return [str(cmd).strip().upper() for cmd in input_data if str(cmd).strip()]
        return []

    @classmethod
    def check_combination(cls, input_data: Union[str, List[str]]) -> Dict[str, Any]:
        """
        Check whether navigation commands conflict or contain unsafe combinations.

        Returns:
            dict: {
                "result": "VALID" | "REJECTED",
                "reason": Optional[str],
                "conflicts": List[str]
            }
        """
        commands = cls.parse_commands(input_data)

        if not commands:
            return {
                "result": "REJECTED",
                "reason": "No valid commands provided",
                "conflicts": []
            }

        cmd_set = set(commands)

        # Rule 1: STOP combined with any movement command
        if "STOP" in cmd_set:
            movement_found = cmd_set.intersection(MOVEMENT_COMMANDS)
            if movement_found:
                conflict_cmds = sorted(list({"STOP"}.union(movement_found)))
                return {
                    "result": "REJECTED",
                    "reason": "Conflicting commands: STOP takes priority over movement commands",
                    "conflicts": conflict_cmds
                }

        # Rule 2: Opposing directional movement pairs
        for pair_set, reason_msg in OPPOSING_PAIRS:
            if pair_set.issubset(cmd_set):
                conflict_cmds = sorted(list(pair_set))
                return {
                    "result": "REJECTED",
                    "reason": reason_msg,
                    "conflicts": conflict_cmds
                }

        # Rule 3: Unnecessary / redundant repeated movement commands in sequence
        for i in range(len(commands) - 1):
            if commands[i] in MOVEMENT_COMMANDS and commands[i] == commands[i + 1]:
                return {
                    "result": "REJECTED",
                    "reason": f"Redundant movement command repeated unnecessarily: {commands[i]}",
                    "conflicts": [commands[i]]
                }

        return {
            "result": "VALID",
            "reason": None,
            "conflicts": []
        }


def check_navigation_combination(input_data: Union[str, List[str]]) -> Dict[str, Any]:
    """
    Helper function to check navigation command combinations.
    """
    return InvalidCombinationRules.check_combination(input_data)
