import os

APP_NAME = "SynaptiMesh Master Hub"
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", 5000))
DEBUG = False

# ---------------------------------------
# MQTT Configuration
# ---------------------------------------
MQTT_BROKER = os.environ.get("CAR_MQTT_BROKER", os.environ.get("MQTT_BROKER", "52.21.249.6"))
MQTT_PORT = int(os.environ.get("CAR_MQTT_PORT", os.environ.get("MQTT_PORT", 1883)))
MQTT_DEVICE_ID = os.environ.get("MQTT_DEVICE_ID", "98:A3:16:BF:2C:C0")
MQTT_BASE_TOPIC = os.environ.get("MQTT_BASE_TOPIC", "robotcar")

# ---------------------------------------
# BCI & Timing Parameters
# ---------------------------------------
POWER_THRESHOLD = float(os.environ.get("POWER_THRESHOLD", 0.35))
DEBOUNCE_MS = int(os.environ.get("DEBOUNCE_MS", 300))
SINGLE_FIRE_WINDOW_MS = int(os.environ.get("SINGLE_FIRE_WINDOW_MS", 500))
COMBO_WINDOW_MS = int(os.environ.get("COMBO_WINDOW_MS", 2500))
NEUTRAL_STOPS_CAR = os.environ.get("NEUTRAL_STOPS_CAR", "true").lower() in ("true", "1", "yes")