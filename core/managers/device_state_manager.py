import time
from typing import Dict, Optional

class DeviceStatus:
    OFFLINE = "OFFLINE"
    IDLE = "IDLE"
    BUSY = "BUSY"
    ERROR = "ERROR"

class DeviceState:
    def __init__(self, device_id: str):
        self.device_id: str = device_id
        self.status: str = DeviceStatus.OFFLINE
        self.last_heartbeat: float = 0.0
        self.current_command_id: Optional[str] = None
        self.telemetry: dict = {}

class DeviceStateManager:
    def __init__(self, on_state_change=None):
        self.devices: Dict[str, DeviceState] = {}
        self.on_state_change = on_state_change

    def _set_status(self, device: DeviceState, new_status: str):
        if device.status != new_status:
            device.status = new_status
            if self.on_state_change:
                self.on_state_change(device.device_id, new_status)

    def _get_or_create_device(self, device_id: str) -> DeviceState:
        if device_id not in self.devices:
            self.devices[device_id] = DeviceState(device_id)
            # Notify creation
            if self.on_state_change:
                self.on_state_change(device_id, self.devices[device_id].status)
        return self.devices[device_id]

    def update_heartbeat(self, device_id: str, telemetry: dict):
        """
        Updates last_heartbeat timestamp.
        If status was OFFLINE, transitions it to IDLE.
        """
        device = self._get_or_create_device(device_id)
        device.last_heartbeat = time.time()
        device.telemetry = telemetry
        
        if device.status == DeviceStatus.OFFLINE:
            self._set_status(device, DeviceStatus.IDLE)

    def assign_command(self, device_id: str, command_id: str) -> bool:
        """
        Checks if the device is IDLE.
        Transitions status to BUSY and links the current_command_id.
        """
        device = self._get_or_create_device(device_id)
        if device.status == DeviceStatus.IDLE:
            self._set_status(device, DeviceStatus.BUSY)
            device.current_command_id = command_id
            return True
        return False

    def release_device(self, device_id: str, success: bool):
        """
        Clears current_command_id.
        Transitions status back to IDLE (or ERROR if execution crashed the device).
        """
        if device_id in self.devices:
            device = self.devices[device_id]
            device.current_command_id = None
            if success:
                self._set_status(device, DeviceStatus.IDLE)
            else:
                self._set_status(device, DeviceStatus.ERROR)

    def check_timeouts(self, timeout_threshold_seconds: float):
        """
        A background worker or periodic check that marks devices as OFFLINE 
        if time.time() - last_heartbeat > threshold.
        """
        current_time = time.time()
        for device in self.devices.values():
            if current_time - device.last_heartbeat > timeout_threshold_seconds:
                if device.status != DeviceStatus.OFFLINE:
                    self._set_status(device, DeviceStatus.OFFLINE)
                    device.current_command_id = None # Optional: clear command if offline
