import pytest
from core.validation.invalid_combination_rules import (
    InvalidCombinationRules,
    check_navigation_combination
)

def test_left_right_conflict():
    res = check_navigation_combination("LEFT + RIGHT")
    assert res["result"] == "REJECTED"
    assert "Conflicting movement commands" in res["reason"]
    assert set(res["conflicts"]) == {"LEFT", "RIGHT"}

def test_push_pull_conflict():
    res = check_navigation_combination("PUSH + PULL")
    assert res["result"] == "REJECTED"
    assert "Conflicting movement commands" in res["reason"]
    assert set(res["conflicts"]) == {"PUSH", "PULL"}

def test_forward_backward_conflict():
    res = check_navigation_combination(["FORWARD", "BACKWARD"])
    assert res["result"] == "REJECTED"
    assert "Conflicting movement commands" in res["reason"]
    assert set(res["conflicts"]) == {"FORWARD", "BACKWARD"}

def test_stop_move_conflict():
    res = check_navigation_combination("STOP + MOVE")
    assert res["result"] == "REJECTED"
    assert "STOP takes priority over movement" in res["reason"]
    assert "STOP" in res["conflicts"]
    assert "MOVE" in res["conflicts"]

def test_left_stop_conflict():
    res = check_navigation_combination("LEFT + STOP")
    assert res["result"] == "REJECTED"
    assert "STOP takes priority over movement" in res["reason"]
    assert "STOP" in res["conflicts"]
    assert "LEFT" in res["conflicts"]

def test_redundant_repeated_command():
    res = check_navigation_combination("LEFT + LEFT")
    assert res["result"] == "REJECTED"
    assert "Redundant movement command repeated unnecessarily" in res["reason"]
    assert "LEFT" in res["conflicts"]

def test_valid_single_command():
    res = check_navigation_combination("LEFT")
    assert res["result"] == "VALID"
    assert res["reason"] is None
    assert res["conflicts"] == []

def test_valid_combination():
    res = check_navigation_combination("PUSH + LEFT")
    assert res["result"] == "VALID"
    assert res["reason"] is None
    assert res["conflicts"] == []

def test_class_direct_usage():
    res = InvalidCombinationRules.check_combination(["PUSH", "RIGHT"])
    assert res["result"] == "VALID"

def test_validate_combination_api():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    response = client.post("/api/v1/validate-combination", json={"commands": "LEFT + RIGHT"})
    assert response.status_code == 200
    data = response.json()
    assert data["result"] == "REJECTED"
    assert "Conflicting movement commands" in data["reason"]

