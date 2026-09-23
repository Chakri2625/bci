import pytest
from core.validation.command_normalizer import normalize_command

def test_normalize_command_case():
    assert normalize_command("push") == "PUSH"
    assert normalize_command("PULL") == "PULL"
    assert normalize_command("LeFt") == "LEFT"

def test_normalize_command_whitespace():
    assert normalize_command("  push  ") == "PUSH"
    assert normalize_command("push right") == "PUSH_RIGHT"
    assert normalize_command(" push  left ") == "PUSH_LEFT"

def test_normalize_command_separators():
    assert normalize_command("push-left") == "PUSH_LEFT"
    assert normalize_command("push_right") == "PUSH_RIGHT"
    assert normalize_command("push - left") == "PUSH_LEFT"

def test_normalize_command_aliases():
    assert normalize_command("w") == "PUSH"
    assert normalize_command("S") == "PULL"
    assert normalize_command(" a ") == "LEFT"
    assert normalize_command("D") == "RIGHT"
    assert normalize_command("space") == "STOP"
    assert normalize_command("home") == "PUSH_LEFT"
    assert normalize_command("back") == "PUSH_RIGHT"

def test_normalize_invalid_command():
    # Invalid commands should not be swallowed; they should pass through normalized
    assert normalize_command("jump") == "JUMP"
    assert normalize_command("jump-up") == "JUMP_UP"
    assert normalize_command("") == ""
    assert normalize_command(None) is None
