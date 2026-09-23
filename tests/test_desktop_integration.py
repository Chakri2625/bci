"""
Tests for Desktop Integration Service & Command Mapping — SynaptiMesh Python OS
"""

import pytest
from services.desktop_integration_service import get_desktop_integration_service
from services.command_service_mapper import CommandServiceMapper, Domain


def test_desktop_integration_service_singleton():
    svc1 = get_desktop_integration_service()
    svc2 = get_desktop_integration_service()
    assert svc1 is svc2


def test_list_active_windows():
    svc = get_desktop_integration_service()
    windows = svc.list_active_windows(limit=5)
    assert isinstance(windows, list)
    assert len(windows) > 0
    assert "hwnd" in windows[0]
    assert "title" in windows[0]


def test_list_top_processes():
    svc = get_desktop_integration_service()
    procs = svc.list_top_processes(limit=5)
    assert isinstance(procs, list)
    assert len(procs) > 0
    assert "pid" in procs[0]
    assert "name" in procs[0]


def test_os_actions_execution():
    svc = get_desktop_integration_service()
    # Test safe OS action dispatch (SHOW_DESKTOP)
    res = svc.execute_os_action("SHOW_DESKTOP")
    assert res.get("status") == "success"
    assert res.get("action") == "SHOW_DESKTOP"


def test_browser_actions_execution():
    svc = get_desktop_integration_service()
    # Test scroll and zoom actions
    res1 = svc.execute_browser_action("SCROLL_DOWN", {"amount": 150})
    assert res1.get("status") == "success"
    assert res1.get("scrolled") == -150

    res2 = svc.execute_browser_action("SCROLL_UP", {"amount": 150})
    assert res2.get("status") == "success"
    assert res2.get("scrolled") == 150


def test_mapper_desktop_routing():
    mapper = CommandServiceMapper()
    res = mapper.map_and_execute(
        domain="DESKTOP",
        action="SHOW_DESKTOP",
        parameters={}
    )
    assert res.get("status") == "SUCCESS"
    assert res.get("success") is True
    assert res.get("domain") == "DESKTOP"
