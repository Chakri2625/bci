"""Hierarchical FSM command interpretation layer for the Master Hub.

Replaces the direct command mapping with a hierarchical Finite State Machine
that interprets the four BCI primitives (``push`` / ``pull`` / ``left`` /
``right``) based on the current state:

- Level 1: DOMAIN_SELECTION
- Level 2: SUB_MASTER_DASHBOARD
- Level 3: MOBILE/DESKTOP_DASHBOARD_ACTIVE + RIGHT_COMBINATION_WAIT

Only the interpretation layer is new; the existing MQTT and Selenium control
paths are reused unchanged via ``command_mapper`` / ``backend.command_router``.
"""

from .states import (
    PUSH,
    PULL,
    LEFT,
    RIGHT,
    DOMAIN_SELECTION,
    SUB_MASTER_DASHBOARD,
    MOBILE_DASHBOARD_ACTIVE,
    DESKTOP_DASHBOARD_ACTIVE,
    LEVEL_3_COMMAND_MODE,
    RIGHT_COMBINATION_WAIT,
)
from .command_parser import Command, parse_sequence, parse_flat_packet
from .command_mapper import CommandMapper, command_mapper
from .fsm_controller import FSMController, create_fsm

__all__ = [
    "PUSH",
    "PULL",
    "LEFT",
    "RIGHT",
    "DOMAIN_SELECTION",
    "SUB_MASTER_DASHBOARD",
    "MOBILE_DASHBOARD_ACTIVE",
    "DESKTOP_DASHBOARD_ACTIVE",
    "LEVEL_3_COMMAND_MODE",
    "RIGHT_COMBINATION_WAIT",
    "Command",
    "parse_sequence",
    "parse_flat_packet",
    "CommandMapper",
    "command_mapper",
    "FSMController",
    "create_fsm",
]