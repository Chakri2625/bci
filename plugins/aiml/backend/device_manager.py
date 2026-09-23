"""Device registry: holds references to the mobile and desktop backends.

Mobile  -> MQTTService + PipelineScheduler (communicates with Android)
Desktop -> JioSaavnController (communicates with Chrome/Selenium)
"""


class DeviceManager:
    def __init__(self):
        self._mobile = {"mqtt_service": None, "pipeline_scheduler": None}
        self._desktop = {"controller": None}

    def register_mobile(self, mqtt_service, pipeline_scheduler):
        self._mobile["mqtt_service"] = mqtt_service
        self._mobile["pipeline_scheduler"] = pipeline_scheduler

    def register_desktop(self, controller):
        self._desktop["controller"] = controller

    def get_device(self, target):
        if target == "mobile":
            return self._mobile
        if target == "desktop":
            return self._desktop
        raise ValueError(f"Unknown target device: {target}")

    def get_mobile(self):
        return self._mobile

    def get_desktop(self):
        return self._desktop

    def is_ready(self, target):
        device = self.get_device(target)
        if target == "mobile":
            return device["mqtt_service"] is not None and device["mqtt_service"].client is not None
        if target == "desktop":
            return device["controller"] is not None
        return False


device_manager = DeviceManager()