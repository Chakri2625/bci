"""
Command Priority and Ordering Manager (Member 7)

Handles priority assignment, prioritized heap queue, and strict FIFO ordering
for commands in SynaptiMesh.
"""

from enum import IntEnum
import heapq
import itertools
from typing import Any, Dict, List, Optional, Union


class PriorityLevel(IntEnum):
    CRITICAL = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4


COMMAND_PRIORITY_MAP: Dict[str, PriorityLevel] = {
    # CRITICAL (1)
    "STOP": PriorityLevel.CRITICAL,
    "EMERGENCY_STOP": PriorityLevel.CRITICAL,
    "HALT": PriorityLevel.CRITICAL,
    "ABORT": PriorityLevel.CRITICAL,
    "SHUTDOWN": PriorityLevel.CRITICAL,
    "CANCEL": PriorityLevel.CRITICAL,
    "KILL": PriorityLevel.CRITICAL,
    "BRAKE": PriorityLevel.CRITICAL,
    # HIGH (2)
    "MOVE": PriorityLevel.HIGH,
    "PUSH": PriorityLevel.HIGH,
    "PULL": PriorityLevel.HIGH,
    "FORWARD": PriorityLevel.HIGH,
    "BACKWARD": PriorityLevel.HIGH,
    "LEFT": PriorityLevel.HIGH,
    "RIGHT": PriorityLevel.HIGH,
    "PUSH_LEFT": PriorityLevel.HIGH,
    "PUSH_RIGHT": PriorityLevel.HIGH,
    "NAVIGATE": PriorityLevel.HIGH,
    # NORMAL (3)
    "OPEN": PriorityLevel.NORMAL,
    "CLOSE": PriorityLevel.NORMAL,
    "SELECT": PriorityLevel.NORMAL,
    "CLICK": PriorityLevel.NORMAL,
    "ENTER": PriorityLevel.NORMAL,
    "SWITCH": PriorityLevel.NORMAL,
    "START": PriorityLevel.NORMAL,
    "PAUSE": PriorityLevel.NORMAL,
    # LOW (4)
    "INFO": PriorityLevel.LOW,
    "STATUS": PriorityLevel.LOW,
    "LOG": PriorityLevel.LOW,
    "PING": PriorityLevel.LOW,
    "SEARCH": PriorityLevel.LOW,
    "QUERY": PriorityLevel.LOW,
    "METRICS": PriorityLevel.LOW,
    "HELP": PriorityLevel.LOW,
}


def parse_priority(priority_input: Any) -> Optional[PriorityLevel]:
    """
    Parse priority from integer, enum, or string.
    Returns None if the input cannot be parsed as a valid PriorityLevel.
    """
    if isinstance(priority_input, PriorityLevel):
        return priority_input

    if isinstance(priority_input, int):
        try:
            return PriorityLevel(priority_input)
        except ValueError:
            return None

    if isinstance(priority_input, str):
        cleaned = priority_input.strip().upper()
        # Check by name (e.g. "CRITICAL")
        if hasattr(PriorityLevel, cleaned):
            return PriorityLevel[cleaned]
        # Check by integer string (e.g. "1")
        if cleaned.isdigit():
            try:
                return PriorityLevel(int(cleaned))
            except ValueError:
                return None

    return None


def get_command_priority(command_item: Any, explicit_priority: Any = None) -> PriorityLevel:
    """
    Determine the PriorityLevel for a command item.
    """
    # 1. Check explicit priority passed directly
    if explicit_priority is not None:
        parsed = parse_priority(explicit_priority)
        if parsed is not None:
            return parsed

    # 2. Check if command_item has an embedded priority
    if isinstance(command_item, dict) and "priority" in command_item:
        parsed = parse_priority(command_item["priority"])
        if parsed is not None:
            return parsed
    elif hasattr(command_item, "priority") and getattr(command_item, "priority") is not None:
        parsed = parse_priority(getattr(command_item, "priority"))
        if parsed is not None:
            return parsed

    # 3. Resolve command name
    cmd_name = ""
    if isinstance(command_item, str):
        cmd_name = command_item
    elif isinstance(command_item, dict):
        cmd_name = command_item.get("command") or command_item.get("action") or command_item.get("type") or ""
    elif hasattr(command_item, "command"):
        cmd_name = str(getattr(command_item, "command"))
    elif hasattr(command_item, "action"):
        cmd_name = str(getattr(command_item, "action"))

    cmd_upper = str(cmd_name).strip().upper()
    return COMMAND_PRIORITY_MAP.get(cmd_upper, PriorityLevel.NORMAL)


class PriorityManager:
    """
    Manages prioritized command queue with atomic monotonic counter
    to guarantee strict FIFO order among commands with identical priority.
    """

    def __init__(self):
        self._heap: List[tuple] = []
        self._counter = itertools.count()

    def enqueue(self, command: Any, priority: Optional[Any] = None) -> PriorityLevel:
        """
        Assigns priority and enqueues command with strict FIFO sequence counter.
        Returns the assigned PriorityLevel.
        """
        assigned_priority = get_command_priority(command, explicit_priority=priority)
        seq = next(self._counter)
        heapq.heappush(self._heap, (int(assigned_priority), seq, command))
        return assigned_priority

    def enqueue_batch(self, commands: List[Any]) -> List[PriorityLevel]:
        """
        Enqueues a list of commands in batch.
        """
        return [self.enqueue(cmd) for cmd in commands]

    def dequeue(self) -> Optional[Any]:
        """
        Removes and returns the highest-priority (lowest priority value),
        earliest-arrived command. Returns None if the queue is empty.
        """
        if not self._heap:
            return None
        _prio, _seq, item = heapq.heappop(self._heap)
        return item

    def peek(self) -> Optional[Any]:
        """
        Returns the next command without removing it from the queue.
        Returns None if queue is empty.
        """
        if not self._heap:
            return None
        return self._heap[0][2]

    def is_empty(self) -> bool:
        """Returns True if queue is empty."""
        return len(self._heap) == 0

    def size(self) -> int:
        """Returns the number of elements in the queue."""
        return len(self._heap)

    def __len__(self) -> int:
        return len(self._heap)

    def clear(self) -> None:
        """Resets the queue and sequence counter."""
        self._heap.clear()
        self._counter = itertools.count()
