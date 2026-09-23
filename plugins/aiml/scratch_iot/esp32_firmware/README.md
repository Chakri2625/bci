# ESP32 IoT Master Hub - Hardware Wiring & Flashing Guide

This firmware controls 3 actuators / LEDs corresponding to the mental commands from the **Emotiv EPOC Headset**.

---

## 📌 GPIO Pin Mapping

| Actuator | Representation | ESP32 GPIO Pin | Mental Command (Select) | Mental Command (Action) |
| :--- | :--- | :--- | :--- | :--- |
| **💡 Light** | LED 1 (Yellow / White) | **GPIO 23** | `push` | `right` (ON) / `left` (OFF) |
| **🌀 Fan** | LED 2 (Blue / Green) | **GPIO 22** | `pull` | `right` (ON) / `left` (OFF) |
| **🚰 Pump** | LED 3 (Cyan / Red) | **GPIO 21** | `left` | `right` (ON) / `left` (OFF) |
| **⚡ Status** | Built-in Blue LED | **GPIO 2** | N/A (Heartbeat) | Heartbeat Blink |

---

## 🔌 Hardware Circuit Diagram

```
                 +-------------------+
                 |    ESP32 Board    |
                 |                   |
                 |           GPIO 23 |----[ 220Ω Resistor ]----( + ) [ 💡 Light LED ]----( - ) GND
                 |           GPIO 22 |----[ 220Ω Resistor ]----( + ) [ 🌀 Fan LED ]  ----( - ) GND
                 |           GPIO 21 |----[ 220Ω Resistor ]----( + ) [ 🚰 Pump LED ] ----( - ) GND
                 |               GND |------------------------------------------------- Common GND
                 |                   |
                 |        Micro-USB  |======> To PC (Serial 115200 baud or Power)
                 +-------------------+
```

> **Note for Real Relays / Motors / DC Pumps**:
> If driving 5V/12V real fans or water pumps instead of LEDs, connect GPIO 23, 22, 21 to the input pins (`IN1`, `IN2`, `IN3`) of a **3-Channel or 4-Channel 5V Relay Module** or MOSFET driver module, and connect VCC to 5V (VIN) and GND to ESP32 GND.

---

## 🚀 Flashing via Arduino IDE

1. **Install ESP32 Board Support**:
   - In Arduino IDE, go to `File > Preferences`.
   - Add to *Additional Board Manager URLs*:
     ```
     https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
     ```
   - Go to `Tools > Board > Boards Manager...`, search for `esp32` and click **Install**.

2. **Select Board & Port**:
   - `Tools > Board > ESP32 Arduino > ESP32 Dev Module`
   - `Tools > Port > COMx` (select the COM port where ESP32 is plugged in)
   - `Tools > Upload Speed > 115200` (or 921600)

3. **Configure WiFi (Optional)**:
   - In `esp32_iot_hub.ino`, set:
     ```cpp
     const char* WIFI_SSID = "Your_WiFi_Name";
     const char* WIFI_PASS = "Your_WiFi_Password";
     ```
   - *If using Serial USB cable only, you don't even need WiFi!*

4. **Click Upload (Ctrl + U)**.
5. Open Serial Monitor at **115200 baud** to verify startup.
