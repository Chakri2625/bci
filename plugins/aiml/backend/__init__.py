"""Master Hub backend package.

Seeds the future unified command routing / device management layer.
Only single-target dispatch (mobile | desktop) is wired; broadcasting to
"both" is intentionally left unimplemented for now.
"""

from .device_manager import device_manager
from .state_manager import state_manager
from .command_router import command_router

__all__ = ["device_manager", "state_manager", "command_router"]