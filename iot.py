# Compatibility wrapper for the IoT plugin
import warnings
from plugins.iot.plugin import IoTPlugin

warnings.warn("iot.py is deprecated. Please interact with the IoT layer via the plugin manager and core adapters.", DeprecationWarning)

# Expose a placeholder or instance if legacy code expects mqtt_manager
class _LegacyMQTTManagerWrapper:
    def __init__(self):
        self._plugin = IoTPlugin()
        
    def start(self):
        self._plugin.initialize()
        
    def get_status(self):
        return {
            "connected": self._plugin.connected,
            "broker_host": self._plugin.broker,
            "broker_port": self._plugin.port,
            "client_id": "legacy-wrapper",
            "tls_enabled": False,
            "topic_root": self._plugin.topic_root,
        }
        
mqtt_manager = _LegacyMQTTManagerWrapper()