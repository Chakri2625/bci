# ESP32 IoT Master Hub - Hardware Wiring & Troubleshooting Guide

This firmware controls 3 actuators / LEDs corresponding to mental commands processed from the **Emotiv EPOC BCI Headset**.

---

## 📌 GPIO Pin Mapping

| Actuator | Hardware Representation | ESP32 GPIO Pin | Mental Command (Select) | Mental Command (Action) |
| :--- | :--- | :--- | :--- | :--- |
| **💡 Light** | Relay 1 / LED 1 | **GPIO 21** (or GPIO 23) | `push` | `right` (ON) / `left` (OFF) |
| **🌀 Fan** | Relay 2 / LED 2 | **GPIO 32** (or GPIO 22) | `pull` | `right` (ON) / `left` (OFF) |
| **🚰 Pump** | Relay 3 / LED 3 | **GPIO 25** (or GPIO 21) | `left` | `right` (ON) / `left` (OFF) |
| **⚡ Status** | Built-in Blue LED | **GPIO 2** | N/A (Heartbeat) | Heartbeat Blink |

---

## 🔌 Hardware Circuit Options

### Option 1: LEDs (Active-HIGH)
```
             +-------------------+
             |    ESP32 Board    |
             |                   |
             |           GPIO 21 |----[ 220Ω Resistor ]----( + ) [ 💡 Light LED ]----( - ) GND
             |           GPIO 32 |----[ 220Ω Resistor ]----( + ) [ 🌀 Fan LED ]  ----( - ) GND
             |           GPIO 25 |----[ 220Ω Resistor ]----( + ) [ 🚰 Pump LED ] ----( - ) GND
             |               GND |------------------------------------------------- Common GND
             |                   |
             |        Micro-USB  |======> To PC (Serial 115200 baud or 5V Power)
             +-------------------+
```

### Option 2: 3/4-Channel 5V Relay Module (Active-LOW Optocoupler)
- Connect ESP32 **GPIO 21, 32, 25** to Relay **IN1, IN2, IN3**.
- Connect ESP32 **GND** to Relay **GND**.
- Power Relay **VCC** with **5V (VIN)** or **3.3V**.

---

## 🛠️ Troubleshooting Common Hardware Issues

### Issue 1: "Appliances turn ON immediately at power-on and won't turn off"

**Root Cause**: Inverted Relay Logic Polarity.
- If your circuit is **Active-HIGH** (LEDs, MOSFETs, or Active-High relays) and the firmware was set to Active-LOW, writing `HIGH` (which the firmware thought was OFF) turns everything ON on boot!
- If your relay module is **Active-LOW 5V Optocoupler** powered by 5V VCC, the ESP32's 3.3V HIGH output creates a `5V - 3.3V = 1.7V` forward voltage drop across the optocoupler diode, keeping the relay permanently energized!

**Solution**:
1. In `esp32_iot_hub.ino`, set:
   ```cpp
   bool activeLowRelays = false; // Set to false for LEDs & Active-HIGH circuits
   ```
2. Or switch polarity on the fly without re-flashing:
   - In Arduino Serial Monitor (115200 baud), type:
     ```
     POLARITY:HIGH
     ```
     or
     ```
     POLARITY:LOW
     ```
   - Type `TEST` to run a 1-second sequential self-test.
3. For 5V Optocoupler relay modules that don't turn off with 3.3V logic:
   - In `esp32_iot_hub.ino`, set `const bool USE_OPEN_DRAIN = true;` or power the relay module VCC from the ESP32's 3.3V output pin instead of 5V VIN.

---

### Issue 2: "ESP32 HTTP Ping Failed / Connection timed out (172.20.221.14 / ConnectTimeoutError)"

**Root Cause**:
1. The ESP32 is not connected to the exact same WiFi network as your PC (or WiFi credentials in `esp32_iot_hub.ino` were not set).
2. The ESP32 received a different IP address from DHCP after rebooting.
3. Your PC is on a different subnet (e.g. PC is `172.18.17.x` while ESP32 was `172.20.221.x`).
4. Router or Mobile Hotspot "AP Isolation / Client Isolation" is blocking port 80 traffic between devices.

**Solution**:
1. **Recommended Easiest Fix - Use USB Serial Mode**:
   - Plug the ESP32 into your PC via USB cable.
   - In the Web Dashboard (`http://localhost:3000`), under **ESP32 Settings**, choose **USB Serial (COM Port)**.
   - Select your COM port (e.g. `COM5` or click **Scan**) and click **Connect ESP32**.
   - USB Serial works with **0% latency**, **100% reliability**, and requires **no WiFi setup**.
2. **If using WiFi HTTP Mode**:
   - In `esp32_iot_hub.ino`, configure your 2.4GHz WiFi credentials:
     ```cpp
     const char* WIFI_SSID = "Your_WiFi_Name";
     const char* WIFI_PASS = "Your_WiFi_Password";
     ```
   - Open Arduino Serial Monitor at **115200 baud** to see the actual IP assigned:
     ```
     [WiFi IP Address] http://172.18.17.xx
     ```
   - Enter that exact IP address in the Master Hub Web Dashboard or use `http://esp32-hub.local/api/status`.

---

## 🚀 Flashing via Arduino IDE

1. **Install ESP32 Board Support**:
   - In Arduino IDE, go to `File > Preferences`.
   - Add to *Additional Board Manager URLs*:
     ```
     https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
     ```
   - Go to `Tools > Board > Boards Manager...`, search for `esp32` and click **Install**.

3. **Install PubSubClient Library (for MQTT)**:
   - In Arduino IDE, go to `Sketch > Include Library > Manage Libraries...` (or Ctrl + Shift + I).
   - Search for **PubSubClient** by *Nick O'Leary*.
   - Click **Install**.

4. **Select Board & Port**:
   - `Tools > Board > ESP32 Arduino > ESP32 Dev Module`
   - `Tools > Port > COMx` (select the COM port where ESP32 is plugged in)
   - `Tools > Upload Speed > 115200` (or 921600)

5. **Click Upload (Ctrl + U)**.
6. Open Serial Monitor at **115200 baud** to view logs and send diagnostic commands:
   - `TEST` -> Run sequential hardware test
   - `STATUS` -> Print current states JSON
   - `IP` -> Print WiFi IP address
   - `POLARITY:HIGH` / `POLARITY:LOW` -> Toggle relay polarity

---

## 📡 MQTT Broker Setup & Topics

When using MQTT Mode, the ESP32 and Master IoT Hub communicate through your MQTT broker (e.g. Mosquitto, EMQX, HiveMQ, AWS IoT, or a self-hosted server).

### Topic Hierarchy Schema:
```python
STATUS_TOPIC = f"{BASE_TOPIC}/{DEVICE_ID}/status"  # Default: iot/esp32/status
ACTION_TOPIC = f"{BASE_TOPIC}/{DEVICE_ID}/action"  # Default: iot/esp32/action
ACK_TOPIC    = f"{BASE_TOPIC}/{DEVICE_ID}/ack"     # Default: iot/esp32/ack
```

### Configuration in `esp32_iot_hub.ino`:
```cpp
const char* MQTT_BROKER       = "52.21.249.6";         // Replace with your broker IP or hostname
const int   MQTT_PORT         = 1883;                  // Broker port (default 1883)
const char* MQTT_USER         = "";                    // Optional username
const char* MQTT_PASS         = "";                    // Optional password
const char* MQTT_CLIENT_ID    = "ESP32_Actuator_Node"; // Unique Client ID

const char* BASE_TOPIC        = "iot";                 // Base topic namespace
const char* DEVICE_ID         = "esp32";               // Device identifier

const char* STATUS_TOPIC      = "iot/esp32/status";    // Published full state telemetry
const char* ACTION_TOPIC      = "iot/esp32/action";    // Subscribed incoming action commands
const char* ACK_TOPIC         = "iot/esp32/ack";       // Published command acknowledgment
const char* LWT_TOPIC         = "iot/esp32/availability";// Published availability / LWT topic
```

### Topic Reference:
- **Action / Command Topic** (`ACTION_TOPIC`, e.g. `iot/esp32/action`):
  - Send JSON: `{"device":"light","state":"ON"}`
  - Or plain text: `LIGHT:ON`, `FAN:OFF`, `PUMP:ON`, `ALL:OFF`
- **Status / Telemetry Topic** (`STATUS_TOPIC`, e.g. `iot/esp32/status`):
  - ESP32 publishes full JSON states on connect and on every change:
    ```json
    {"uptime":12340,"wifiConnected":true,"mqttConnected":true,"ip":"192.168.1.105","relayMode":"active_high","states":{"light":"ON","fan":"OFF","pump":"OFF"}}
    ```
- **Acknowledgment Topic** (`ACK_TOPIC`, e.g. `iot/esp32/ack`):
  - ESP32 publishes execution confirmation for each received command:
    ```json
    {"device":"light","state":"ON","status":"OK","timestamp":12345}
    ```
- **Availability / LWT** (`LWT_TOPIC`, e.g. `iot/esp32/availability`):
  - ESP32 publishes `"online"` when connected, and broker publishes `"offline"` via LWT if connection drops.

### Test with `mosquitto_pub` / `mosquitto_sub`:
```bash
# Listen to ESP32 telemetry, acks & availability:
mosquitto_sub -h 52.21.249.6 -t "iot/esp32/#" -v

# Turn Light ON via ACTION_TOPIC:
mosquitto_pub -h 52.21.249.6 -t "iot/esp32/action" -m '{"device":"light","state":"ON"}'

# Turn Fan OFF via plain text:
mosquitto_pub -h 52.21.249.6 -t "iot/esp32/action" -m 'FAN:OFF'
```


## Primary SynaptiMesh transport interfaces

The Robot Car firmware exposes the same `LIFTCAR...` command vocabulary through:

- USB Serial at 115200 baud
- MQTT using the configured Robot Car control topic
- Wi-Fi HTTP using `/api/car/command`
- `/api/status` for HTTP status checks

These interfaces are transport mechanisms for the same Robot Car command layer; the Master Hub selects one active transport at a time. Firmware flashing is a separate maintenance operation performed over USB Serial.
\n\n### Firmware flashing\nUse `SynaptiMesh_C6_RobotCar.ino.merged.bin` for a complete flash. The Master Hub detects `.merged.bin` automatically and flashes it at `0x0`. Application-only `.bin` files continue to use the configured application offset (normally `0x10000`).\n