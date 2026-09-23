# 🧠 Emotiv EPOC BCI to ESP32 IoT Master Hub (Python Server)

A Brain-Computer Interface (BCI) IoT Master Hub that connects an **Emotiv EPOC Headset** (via **Emotiv Cortex API v2 WebSockets**) to an **ESP32 Microcontroller** controlling 3 appliances/actuators represented by LEDs or relays:
1. 💡 **Light** (Push)
2. 🌀 **Fan** (Pull)
3. 🚰 **Pump** (Left)

---

## 🎮 Mental Command Mapping Architecture

The hub implements a hierarchical state machine designed for brainwave navigation:

```
                          ┌───────────────────────────┐
                          │   ROOT: SELECTION MODE    │
                          └─────────────┬─────────────┘
                                        │
           ┌────────────────────────────┼────────────────────────────┐
           │ "push"                     │ "pull"                     │ "left"
           ▼                            ▼                            ▼
   ┌───────────────┐            ┌───────────────┐            ┌───────────────┐
   │  LIGHT (💡)   │            │   FAN (🌀)    │            │   PUMP (🚰)   │
   │  GPIO 23      │            │   GPIO 22     │            │   GPIO 21     │
   └───────┬───────┘            └───────┬───────┘            └───────┬───────┘
           │                            │                            │
           └────────────────────────────┼────────────────────────────┘
                                        │
                          ┌──────────────┴──────────────┐
                          │   DEVICE CONTROL SUB-MODE   │
                          └──────────────┬──────────────┘
                          │
                          ┌──────────────┴──────────────────────────┐
                          │ "right"     -->  ⚡ Turn ON (Framed)     │
                          │ "left"      -->  ⭕ Turn OFF (Framed)    │
                          │ "push+pull" -->  ↩️ Exit Domain / Cancel │
                          └─────────────────────────────────────────┘
```

---

## ⚡ Quick Start (Python Server)

### 1. Install Dependencies & Start Python Master Hub

```bash
# Install Python packages
pip install -r requirements.txt

# Start the Python Master Server
python server.py
```

Open your browser and navigate to:
👉 **`http://localhost:3000`**

---

### 2. Running State Machine Automated Tests

```bash
python test_state_machine.py
```

---

### 3. Flashing the ESP32 Firmware

1. Open `esp32_firmware/esp32_iot_hub.ino` in Arduino IDE.
2. Select your ESP32 board (`ESP32 Dev Module`) and COM Port.
3. (Optional) Set your WiFi credentials in `esp32_iot_hub.ino`:
   ```cpp
   const char* WIFI_SSID = "Your_WiFi_Name";
   const char* WIFI_PASS = "Your_WiFi_Password";
   ```
4. Click **Upload**.
5. Connect LEDs / Relays:
   - **Light**: GPIO 23
   - **Fan**: GPIO 22
   - **Pump**: GPIO 21

---

### 4. Emotiv Cortex API Setup

1. Make sure **Emotiv App** (or Cortex Service) is running on your machine.
2. Ensure your **Emotiv EPOC** headset is turned on and paired.
3. Generate your `Cortex Client ID` and `Client Secret` from [Emotiv Developer Portal](https://account.emotiv.com/my-account/cortex-apps/).
4. In the Web Dashboard at `http://localhost:3000`, click the ⚙️ **Settings** button and enter your credentials, then click **Connect to Cortex**.

---

### 5. Interactive Testing (Without Headset)

You can test the entire pipeline using the built-in **BCI Mental Command Simulator** on the web dashboard:
- Click **PUSH** or press key **`1`** $\rightarrow$ Selects Light
- Click **PULL** or press key **`2`** $\rightarrow$ Selects Fan
- Click **LEFT** or press key **`3`** $\rightarrow$ Selects Pump
- Click **RIGHT** or press key **`4`** $\rightarrow$ Turns Selected Device ON
- Click **LEFT** or press key **`3`** $\rightarrow$ Turns Selected Device OFF
- Press **`Escape`** or click **Reset** $\rightarrow$ Returns to Selection Mode

---

## 📁 Repository Structure

```
├── server.py                      # FastAPI + Uvicorn Master Hub Server in Python
├── state_machine.py               # Hierarchical BCI State Machine Engine (Python)
├── cortex_bridge.py               # Emotiv Cortex API v2 JSON-RPC WebSocket Bridge (Python)
├── esp32_connector.py             # Hardware driver for WiFi REST / Serial UART (Python)
├── test_state_machine.py          # State Machine Automated Test Suite (Python)
├── requirements.txt               # Python package dependencies
├── public/                        # Glassmorphic Real-Time Web Dashboard UI
│   ├── index.html                 # Main Dashboard HTML with Oscilloscope & Simulator
│   ├── style.css                  # Cyberpunk dark theme stylesheet
│   └── app.js                     # Frontend WebSocket controller
└── esp32_firmware/                # Arduino C++ Firmware for ESP32
    └── esp32_iot_hub.ino          # WiFi REST + Serial UART + WebSocket Actuator Controller
```
