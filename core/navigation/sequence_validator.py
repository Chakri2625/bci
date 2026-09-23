"""State-aware validation for incoming BCI command sequences.

The validator intentionally asks the existing rule router whether a command can
be resolved.  This keeps navigation rules in one place while giving the API a
lightweight, structured validation step before a plugin can be invoked.
"""

from core.routing.rule_router import resolve_command


class SequenceValidator:
    """Validate a command against the current navigation state."""

    # Kept here rather than duplicated in callers so allowed-next-command
    # generation and validation always inspect the same command set.
    CANDIDATE_COMMANDS = (
        "PUSH", "PULL", "LEFT", "RIGHT", "STOP", "PUSH_LEFT", "PUSH_RIGHT"
    )

    def allowed_next_commands(self, state: dict) -> list[str]:
        """Return commands which the current router can resolve from *state*."""
        return [
            command
            for command in self.CANDIDATE_COMMANDS
            if resolve_command(command, state)["type"] != "no_action"
        ]

    def validate(self, command: str, state: dict) -> dict:
        """Return UI/API-friendly validation details without changing state."""
        try:
            from core.validation.command_normalizer import normalize_command
            command = normalize_command(command)
        except Exception:
            command = str(command).upper().replace("+", "_").replace(" ", "_")
        allowed_commands = self.allowed_next_commands(state)
        previous_command = state.get("previous_command")

        if command not in self.CANDIDATE_COMMANDS:
            reason = f"Invalid command: Unsupported command '{command}'."
        elif command not in allowed_commands:
            reason = (
                f"Invalid command sequence: {command} is not available at level {state.get('current_level', 1)} "
                f"for the current navigation state."
            )
        else:
            reason = None

        return {
            "previous_command": previous_command,
            "current_command": command,
            "status": "VALID" if reason is None else "INVALID",
            "is_valid": reason is None,
            "allowed_next_commands": allowed_commands,
            "rejection_reason": reason,
            "current_state": {
                "current_level": state.get("current_level", 1),
                "active_domain": state.get("active_domain"),
                "active_app": state.get("active_app"),
            },
        }

    def record(self, session: str, validation: dict, state_manager) -> None:
        """Persist the latest result and command history metadata in session memory."""
        state_manager.update_state(session, {
            "previous_command": validation["current_command"],
            "sequence_validation": validation,
        })

    def refresh(self, validation: dict, state: dict) -> dict:
        """Refresh display details after a valid command has changed navigation."""
        validation = validation.copy()
        validation["allowed_next_commands"] = self.allowed_next_commands(state)
        validation["current_state"] = {
            "current_level": state.get("current_level", 1),
            "active_domain": state.get("active_domain"),
            "active_app": state.get("active_app"),
        }
        return validation


sequence_validator = SequenceValidator()
