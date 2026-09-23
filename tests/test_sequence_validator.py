from core.navigation.sequence_validator import sequence_validator


def test_level_one_commands_are_valid_and_exposed():
    state = {"current_level": 1, "active_domain": None, "active_app": None}
    result = sequence_validator.validate("PUSH", state)

    assert result["is_valid"] is True
    assert result["status"] == "VALID"
    assert "PUSH" in result["allowed_next_commands"]


def test_invalid_command_has_a_clear_rejection_reason():
    state = {"current_level": 1, "active_domain": None, "active_app": None}
    result = sequence_validator.validate("JUMP", state)

    assert result["is_valid"] is False
    assert result["status"] == "INVALID"
    assert "Unsupported command" in result["rejection_reason"]


def test_unmapped_command_is_rejected_for_current_state():
    state = {"current_level": 2, "active_domain": "EMBEDDED", "active_app": None}
    result = sequence_validator.validate("RIGHT", state)

    assert result["is_valid"] is False
    assert "not available" in result["rejection_reason"]
