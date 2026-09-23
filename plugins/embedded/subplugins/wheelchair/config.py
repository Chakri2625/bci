"""
Configuration Settings for BCI-Controlled Smart Wheelchair
============================================================
Mirrors plugins/embedded/subplugins/rc_car/config.py conventions so both
Embedded/Robotics devices (CAR, WHEELCHAIR) share the same safety, logging,
and command-mapping shape. When wheelchair firmware/device details change,
only this file should need updating.
"""

import os
from pathlib import Path

# Base Paths (shared "logs" folder with rc_car, distinct CSV file)
BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
CSV_LOG_PATH = LOGS_DIR / "wheelchair_commands.csv"

# ==============================================================================
# Wheelchair Controller Network Configuration
# ==============================================================================
DEVICE_IP = os.getenv("WHEELCHAIR_IP", "0.0.0.0")
DEVICE_ID = os.getenv("WHEELCHAIR_DEVICE_ID", "wheelchair-01")

# Protocol Selection: 'MQTT' (default) or 'MOCK' (no hardware attached)
COMMUNICATION_PROTOCOL = os.getenv("WHEELCHAIR_COMMUNICATION_PROTOCOL", "MQTT").upper()

NETWORK_TIMEOUT_SECONDS = float(os.getenv("WHEELCHAIR_NETWORK_TIMEOUT_SECONDS", "2.0"))

# ==============================================================================
# MQTT Communication Configuration
# ==============================================================================
MQTT_BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "52.21.249.6")
MQTT_BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", "1883"))
MQTT_CONTROL_TOPIC = os.getenv("WHEELCHAIR_MQTT_CONTROL_TOPIC", f"wheelchair/{DEVICE_ID}/control")
MQTT_STATUS_TOPIC = os.getenv("WHEELCHAIR_MQTT_STATUS_TOPIC", f"wheelchair/{DEVICE_ID}/status")
MQTT_ACK_TOPIC = os.getenv("WHEELCHAIR_MQTT_ACK_TOPIC", f"wheelchair/{DEVICE_ID}/ack")

# ==============================================================================
# Command Mapping for Current Wheelchair Firmware (External MQTT Payloads)
# ==============================================================================
# Maps internal BCI commands to external firmware payloads. Keep the external
# BCI command names (PUSH/PULL/LEFT/RIGHT/STOP) untouched; only this map should
# change if the firmware's expected payload strings change.
COMMAND_MAP = {
    "PUSH": "WHEELCHAIRFORWARD",
    "PULL": "WHEELCHAIRBACKWARD",
    "LEFT": "WHEELCHAIRLEFT",
    "RIGHT": "WHEELCHAIRRIGHT",
    "STOP": "WHEELCHAIRSTOP",
}

# ==============================================================================
# Safety & Command Processing Parameters
# ==============================================================================
# A wheelchair is an assistive mobility device, so safety filtering is at least
# as strict as the RC car: require a slightly higher confidence and a slower
# auto-stop timeout so a lost command stream halts the chair quickly.
CONFIDENCE_THRESHOLD = float(os.getenv("WHEELCHAIR_CONFIDENCE_THRESHOLD", "0.65"))
DEBOUNCE_INTERVAL_SECONDS = 0.10
SAFETY_AUTO_STOP_TIMEOUT = 3.0

# Speed Settings (abstract 0-100 "comfort speed" levels, no PWM specifics known)
SPEED_MODES = {
    "SLOW": 30,
    "MEDIUM": 55,
    "FAST": 80,
}
DEFAULT_SPEED_MODE = "SLOW"

DEBUG_MODE = True
