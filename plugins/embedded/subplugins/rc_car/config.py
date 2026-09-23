"""
Configuration Settings for BCI-Controlled RC Car
=================================================
This file contains all configuration parameters for the EMOTIV EPOC X Cortex API
integration, ESP32 TCP Socket communication, safety thresholds, and logging.
"""

import os
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
CSV_LOG_PATH = LOGS_DIR / "commands.csv"

# ==============================================================================
# EMOTIV Cortex API Configuration
# ==============================================================================
CORTEX_CLIENT_ID = os.getenv("CORTEX_CLIENT_ID", "LeIpR00oXMhYpKNsnH5I26capksi3LV4hA3QjCLR")
CORTEX_CLIENT_SECRET = os.getenv("CORTEX_CLIENT_SECRET", "1yjXoxkw4aPujipgvVxtLGYN1hu6ZgctD9YI7zptmlLUynkzNdZoux3oipQyTV1Nnu65284semeJ4UT02po3ikzPDrxaYewrM9AyUzmwfhJJDR7UEgNIHQurIvWE2jj3")
CORTEX_URL = os.getenv("CORTEX_URL", "wss://localhost:6868")
HEADSET_ID = os.getenv("HEADSET_ID", "")
CORTEX_LICENSE = os.getenv("CORTEX_LICENSE", "")
CORTEX_STREAMS = ["com"]

# ==============================================================================
# ESP32 Wireless Communication Configuration
# ==============================================================================
# IP address assigned to the ESP32 on your local Wi-Fi network
# ⚠️  Discovered active ESP32 at: 172.29.116.136
ESP32_IP = os.getenv("ESP32_IP", "172.29.116.136")

ESP32_PORT = int(os.getenv("ESP32_PORT", "5000"))
ESP32_WS_PORT = int(os.getenv("ESP32_WS_PORT", "81"))

# Protocol Selection: 'WEBSOCKET', 'TCP_SOCKET', 'HTTP', or 'MQTT'
COMMUNICATION_PROTOCOL = os.getenv("COMMUNICATION_PROTOCOL", "MQTT").upper()

# Network Timeout and Retry Parameters
NETWORK_TIMEOUT_SECONDS = float(os.getenv("NETWORK_TIMEOUT_SECONDS", "2.0"))
MAX_NETWORK_RETRIES = 2

# ==============================================================================
# MQTT Communication Configuration (Verified Embedded Team Settings)
# ==============================================================================
MQTT_BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "52.21.249.6")
MQTT_BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", "1883"))
ESP32_DEVICE_ID = os.getenv("ESP32_DEVICE_ID", "98:A3:16:BF:2C:C0")
MQTT_CONTROL_TOPIC = os.getenv("MQTT_CONTROL_TOPIC", f"robotcar/{ESP32_DEVICE_ID}/control")
MQTT_STATUS_TOPIC = os.getenv("MQTT_STATUS_TOPIC", f"robotcar/{ESP32_DEVICE_ID}/status")
MQTT_ACK_TOPIC = os.getenv("MQTT_ACK_TOPIC", f"robotcar/{ESP32_DEVICE_ID}/ack")

# ==============================================================================
# Command Mapping for Current Embedded Firmware (External MQTT Payloads)
# ==============================================================================
# Maps internal BCI commands and motor actions to the external firmware payloads.
# When firmware updates to new command names, only update this mapping.
COMMAND_MAP = {
    "FORWARD": "LIFTCARFORWARD",
    "BACKWARD": "LIFTCARBACKWARD",
    "LEFT": "LIFTCARLEFT",
    "RIGHT": "LIFTCARRIGHT",
    "STOP": "LIFTCARSTOP",
}

# ==============================================================================
# Safety & Command Processing Parameters
# ==============================================================================
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.60"))
DEBOUNCE_INTERVAL_SECONDS = 0.10
SAFETY_AUTO_STOP_TIMEOUT = 5.0

# Speed Settings (PWM values 0 - 255)
SPEED_MODES = {
    "SLOW": 150,
    "MEDIUM": 200,
    "FAST": 255
}
DEFAULT_SPEED_MODE = "MEDIUM"

# ==============================================================================
# Web Telemetry Dashboard Configuration
# ==============================================================================
DASHBOARD_HOST = "0.0.0.0"
DASHBOARD_PORT = 5000
ENABLE_DASHBOARD = True

# Debugging Settings
DEBUG_MODE = True
PRINT_RAW_CORTEX_FRAMES = False
