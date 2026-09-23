"""Tracks which dashboard the user is viewing and per-device connection state."""


class StateManager:
    def __init__(self):
        self._active_dashboard = "master"
        self._devices = {
            "mobile": {"registered": False, "connected": False},
            "desktop": {"registered": False, "connected": False},
        }

    def set_active_dashboard(self, name):
        self._active_dashboard = name

    def get_active_dashboard(self):
        return self._active_dashboard

    def register_device(self, name, registered=True):
        if name in self._devices:
            self._devices[name]["registered"] = registered

    def set_connected(self, name, connected):
        if name in self._devices:
            self._devices[name]["connected"] = connected

    def get_state(self):
        return {
            "active_dashboard": self._active_dashboard,
            "devices": {k: dict(v) for k, v in self._devices.items()},
        }


state_manager = StateManager()