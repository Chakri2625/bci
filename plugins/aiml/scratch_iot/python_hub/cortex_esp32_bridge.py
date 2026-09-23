"""
cortex_esp32_bridge.py
Standalone Python 3 Bridge for Emotiv EPOC Headset (Cortex WebSocket API) -> ESP32 IoT Hub.

Logic:
  Selection Mode:
    'push' -> Select Light
    'pull' -> Select Fan
    'left' -> Select Pump
  Control Mode:
    'right' -> Turn ON
    'left'  -> Turn OFF
"""

import asyncio
import json
import ssl
import time
import os
import sys
import requests
import websockets
from dotenv import load_dotenv

load_dotenv()

# Cortex Credentials (Set in .env or hardcode here)
CORTEX_URL = os.getenv("CORTEX_URL", "wss://localhost:6868")
CLIENT_ID = os.getenv("CORTEX_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("CORTEX_CLIENT_SECRET", "")
LICENSE = os.getenv("CORTEX_LICENSE", "")

# ESP32 Settings
ESP32_MODE = os.getenv("ESP32_MODE", "wifi")  # 'wifi' or 'serial'
ESP32_IP = os.getenv("ESP32_IP", "192.168.1.100")
ESP32_PORT = int(os.getenv("ESP32_PORT", 80))
ESP32_SERIAL_PORT = os.getenv("ESP32_SERIAL_PORT", "COM3")
BAUD_RATE = int(os.getenv("ESP32_BAUD_RATE", 115200))

POWER_THRESHOLD = float(os.getenv("POWER_THRESHOLD", 0.35))
DEBOUNCE_SECONDS = float(os.getenv("DEBOUNCE_SECONDS", 0.9))

# Global State
current_state = "SELECT_APPLIANCE"  # "SELECT_APPLIANCE" or "CONTROL_DEVICE"
selected_device = None              # "light", "fan", "pump"
device_states = {"light": "OFF", "fan": "OFF", "pump": "OFF"}
last_trigger_time = 0
serial_conn = None


def init_serial():
    global serial_conn
    try:
        import serial
        serial_conn = serial.Serial(ESP32_SERIAL_PORT, BAUD_RATE, timeout=1)
        print(f"[ESP32 SERIAL] Connected to {ESP32_SERIAL_PORT} @ {BAUD_RATE} baud")
    except Exception as e:
        print(f"[ESP32 SERIAL WARN] Could not open serial port: {e}")
        serial_conn = None


def dispatch_to_esp32(device, state):
    device = device.lower()
    state = state.upper()
    device_states[device] = state
    print(f"\n[DISPATCH] Setting {device.upper()} -> {state}")

    # 1. Serial Mode
    if ESP32_MODE == "serial" and serial_conn and serial_conn.is_open:
        try:
            cmd = f"{device.upper()}:{state}\n"
            serial_conn.write(cmd.encode("utf-8"))
            print(f"[SERIAL TX] Sent: {cmd.strip()}")
            return
        except Exception as e:
            print(f"[SERIAL ERR] {e}")

    # 2. WiFi HTTP REST Mode
    try:
        url = f"http://{ESP32_IP}:{ESP32_PORT}/api/control?device={device}&state={state}"
        res = requests.get(url, timeout=2.0)
        print(f"[WIFI REST] Response ({res.status_code}): {res.text.strip()}")
    except Exception as e:
        print(f"[WIFI REST WARN] Failed to reach ESP32 at {ESP32_IP}: {e}")


combo_first_action = None
combo_start_time = 0.0

def handle_mental_command(action, power):
    global current_state, selected_device, last_trigger_time, combo_first_action, combo_start_time

    action = (action or "").lower().strip()
    now = time.time()

    if action == "neutral" or power < POWER_THRESHOLD:
        return

    if (now - last_trigger_time) < DEBOUNCE_SECONDS:
        return

    last_trigger_time = now

    # Combo check (PUSH + PULL -> Exit Domain)
    if combo_first_action == "push" and (now - combo_start_time) <= 2.0:
        if action == "pull":
            combo_first_action = None
            print("⚡ [COMBO] PUSH + PULL detected! Exiting domain back to Selection Mode.")
            current_state = "SELECT_APPLIANCE"
            selected_device = None
            return

    if current_state == "SELECT_APPLIANCE":
        if action == "push":
            selected_device = "light"
            current_state = "CONTROL_DEVICE"
            print(f"👉 [SELECTION] Selected: LIGHT 💡 (Domain Locked). Think 'RIGHT' for ON, 'LEFT' for OFF, 'PUSH+PULL' to exit.")
        elif action == "pull":
            selected_device = "fan"
            current_state = "CONTROL_DEVICE"
            print(f"👉 [SELECTION] Selected: FAN 🌀 (Domain Locked). Think 'RIGHT' for ON, 'LEFT' for OFF, 'PUSH+PULL' to exit.")
        elif action == "left":
            selected_device = "pump"
            current_state = "CONTROL_DEVICE"
            print(f"👉 [SELECTION] Selected: PUMP 🚰 (Domain Locked). Think 'RIGHT' for ON, 'LEFT' for OFF, 'PUSH+PULL' to exit.")
        elif action == "right":
            print(f"ℹ️ [INFO] Think 'push' (Light), 'pull' (Fan), or 'left' (Pump) to choose an appliance first.")

    elif current_state == "CONTROL_DEVICE":
        # Domain is LOCKED to selected_device
        if action == "right":
            dispatch_to_esp32(selected_device, "ON")
            print(f"✅ [ACTION] Turned {selected_device.upper()} ON! (Domain remains locked on {selected_device.upper()})")
        elif action == "left":
            dispatch_to_esp32(selected_device, "OFF")
            print(f"❌ [ACTION] Turned {selected_device.upper()} OFF! (Domain remains locked on {selected_device.upper()})")
        elif action == "push":
            combo_first_action = "push"
            combo_start_time = now
            print(f"⚡ [COMBO WINDOW] PUSH registered on locked {selected_device.upper()}. Think PULL within 2.0s to exit domain.")
        elif action == "pull":
            combo_first_action = None
            print(f"ℹ️ [INFO] Domain is locked on {selected_device.upper()}. Think RIGHT (ON), LEFT (OFF), or PUSH+PULL to exit.")


class CortexClient:
    def __init__(self):
        self.req_id = 1
        self.ws = None
        self.token = None
        self.session_id = None
        self.headset_id = None

    async def send_request(self, method, params=None):
        params = params or {}
        msg_id = self.req_id
        self.req_id += 1
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": msg_id
        }
        await self.ws.send(json.dumps(payload))
        while True:
            raw = await self.ws.recv()
            data = json.loads(raw)
            if data.get("id") == msg_id:
                if "error" in data:
                    raise Exception(data["error"].get("message", "Cortex Error"))
                return data.get("result")
            elif "com" in data:
                action, power = data["com"]
                handle_mental_command(action, power)

    async def run(self):
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        print(f"Connecting to Cortex at {CORTEX_URL}...")
        async with websockets.connect(CORTEX_URL, ssl=ssl_ctx) as ws:
            self.ws = ws
            print("Connected to Cortex WebSocket!")

            if not CLIENT_ID or not CLIENT_SECRET:
                print("\n[ERROR] Missing CORTEX_CLIENT_ID and CORTEX_CLIENT_SECRET!")
                print("Please set them in your .env file or python script.")
                return

            print("Requesting Cortex Access...")
            await self.send_request("requestAccess", {"clientId": CLIENT_ID, "clientSecret": CLIENT_SECRET})

            print("Authorizing...")
            auth = await self.send_request("authorize", {
                "clientId": CLIENT_ID,
                "clientSecret": CLIENT_SECRET,
                "license": LICENSE,
                "debit": 1
            })
            self.token = auth["cortexToken"]
            print(f"Authorized! Cortex Token acquired.")

            print("Querying Headsets...")
            headsets = await self.send_request("queryHeadsets")
            if not headsets:
                print("[WARN] No Emotiv headset detected. Ensure your EPOC headset is connected.")
                return

            self.headset_id = headsets[0]["id"]
            print(f"Found Headset: {self.headset_id}")

            print(f"Creating Session...")
            session = await self.send_request("createSession", {
                "cortexToken": self.token,
                "headset": self.headset_id,
                "status": "active"
            })
            self.session_id = session["id"]
            print(f"Session Created: {self.session_id}")

            print("Subscribing to 'com' stream...")
            await self.send_request("subscribe", {
                "cortexToken": self.token,
                "session": self.session_id,
                "streams": ["com"]
            })
            print("Subscribed! Listening for Mental Commands (Push, Pull, Left, Right)...")

            # Main event loop
            while True:
                raw = await self.ws.recv()
                data = json.loads(raw)
                if "com" in data:
                    action, power = data["com"]
                    handle_mental_command(action, power)


if __name__ == "__main__":
    print("=" * 60)
    print("🧠 Emotiv EPOC to ESP32 Python IoT Bridge")
    print(f"Mappings:")
    print("  SELECTION: push -> Light | pull -> Fan | left -> Pump")
    print("  CONTROL:   right -> ON   | left -> OFF")
    print("=" * 60)

    if ESP32_MODE == "serial":
        init_serial()

    client = CortexClient()
    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        print("\nExiting...")
