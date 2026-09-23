"""Parse raw BCI JSON into normalized primitive commands for the FSM.

The BCI layer emits a flat list of packets:

    [
        {"timestamp": "...", "command": "right", "confidence": 0.9850},
        {"timestamp": "...", "command": "push",  "confidence": 0.9520}
    ]

Only the four primitives (``push``/``pull``/``left``/``right``) are
interpreted here. Unknown commands, low-confidence samples and the debug
``expected_action`` annotations present in the hierarchical test file are all
handled gracefully (ignored / surfaced) without changing the real BCI format.
"""

from .states import (
    PRIMITIVE_COMMANDS,
    PUSH,
    PULL,
    LEFT,
    RIGHT,
)


class Command:
    """A single normalized BCI primitive with metadata."""

    __slots__ = ("command", "confidence", "timestamp", "level", "expected_action")

    def __init__(self, command, confidence=1.0, timestamp=None, level=None, expected_action=None):
        self.command = command
        self.confidence = float(confidence)
        self.timestamp = timestamp
        self.level = level
        self.expected_action = expected_action

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"Command({self.command!r}, conf={self.confidence:.3f}, ts={self.timestamp!r})"


def normalize_primitive(raw):
    """Map any BCI token to a canonical primitive, or ``None`` if unknown."""
    if raw is None:
        return None
    token = str(raw).strip().lower()
    if token in PRIMITIVE_COMMANDS:
        return token
    # Tolerate a few human-friendly aliases for manual testing.
    aliases = {
        "push": PUSH,
        "pull": PULL,
        "left": LEFT,
        "right": RIGHT,
    }
    return aliases.get(token)


def parse_flat_packet(packet, confidence_threshold=0.0):
    """Parse a single flat BCI packet (the real BCI output format).

    Returns a :class:`Command` or ``None`` if the packet is not a valid
    primitive or is below the confidence threshold.
    """
    if not isinstance(packet, dict):
        return None

    raw = packet.get("command")
    command = normalize_primitive(raw)
    if command is None:
        return None

    confidence = float(packet.get("confidence", 1.0))
    if confidence < confidence_threshold:
        return None

    return Command(
        command=command,
        confidence=confidence,
        timestamp=packet.get("timestamp"),
    )


def parse_sequence(data, confidence_threshold=0.0, hierarchical=False):
    """Parse BCI input into an ordered list of :class:`Command`.

    Supports two input shapes:

    - ``hierarchical=False`` (default): the real flat BCI list
      ``[{"timestamp", "command", "confidence"}, ...]``.
    - ``hierarchical=True``: the test file shape
      ``{"test_sequences": [{"name", "commands": [{"level", ...}]}]}`` where
      each sequence carries its own commands plus ``expected_action`` for
      verification.

    Returns a list of :class:`Command`.
    """
    commands = []

    if hierarchical:
        sequences = data.get("test_sequences", []) if isinstance(data, dict) else []
        for seq in sequences:
            for packet in seq.get("commands", []):
                cmd = parse_flat_packet(packet, confidence_threshold)
                if cmd is not None:
                    cmd.level = packet.get("level")
                    cmd.expected_action = packet.get("expected_action")
                    commands.append(cmd)
        return commands

    if isinstance(data, list):
        for packet in data:
            cmd = parse_flat_packet(packet, confidence_threshold)
            if cmd is not None:
                commands.append(cmd)
    elif isinstance(data, dict):
        # Single flat packet.
        cmd = parse_flat_packet(data, confidence_threshold)
        if cmd is not None:
            commands.append(cmd)

    return commands