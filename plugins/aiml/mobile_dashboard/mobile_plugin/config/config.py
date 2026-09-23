import os
from pathlib import Path

# ==========================================
# CONFIGURATION & CONSTANTS
# ==========================================
DEBUG_MODE = True

MQTT_BROKER = "broker.emqx.io"
MQTT_PORT = 1883
MQTT_QOS = 1
MQTT_KEEPALIVE = 60
CLIENT_ID_PREFIX = "BCI-WEB"

MQTT_NAMESPACE = "rohan"
TOPIC_COMMAND = f"bci/{MQTT_NAMESPACE}/commands"
TOPIC_CONTROL = f"bci/{MQTT_NAMESPACE}/control"
TOPIC_ACK = f"bci/{MQTT_NAMESPACE}/ack"
TOPIC_STATUS = f"bci/{MQTT_NAMESPACE}/status"
TOPIC_HEARTBEAT = f"bci/{MQTT_NAMESPACE}/heartbeat"
TOPIC_MEDIA = f"bci/{MQTT_NAMESPACE}/media"

ONLINE_PAYLOAD = '{"status":"ONLINE"}'
LAST_WILL_PAYLOAD = '{"status":"OFFLINE"}'

CONFIDENCE_THRESHOLD = 0.80
TARGET_DOMAIN = "AI_ML"

# Calculate DATA_FILE_PATH relative to the plugin directory
PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent
DATA_FILE_PATH = (
    PLUGIN_DIR.parent
    / "Python_pipeline"
    / "integrated_eeg.json"
)

# Command names must match Python_pipeline/config.py for Android compatibility
COMMAND_MAP = {
    "Right": "Right",
    "Right_jiosaavn": "Right_jiosaavn",
    "Right_Play_Pause": "Right_Play_Pause",
    "Right_Next_Song": "Right_Next_Song",
    "Right_Previous_Song": "Right_Previous_Song",
    "Right_Volume_Up": "Right_Volume_Up",
    "Right_Volume_Down": "Right_Volume_Down",
    "Right_Search_Playlist": "Right_Search_Playlist",
    "Drop": "Drop",
    "Right_Return_to_Home": "Right_Return_to_Home",
}

DISPLAY_LABELS = {
    "Right": "Right Gesture",
    "Right_jiosaavn": "Open JioSaavn",
    "Right_Play_Pause": "Play / Pause",
    "Right_Next_Song": "Next Track",
    "Right_Previous_Song": "Previous Track",
    "Right_Volume_Up": "Volume +",
    "Right_Volume_Down": "Volume -",
    "Right_Search_Playlist": "Search Playlist",
    "Drop": "Return to Home",
    "Right_Return_to_Home": "Return to Home",
}
