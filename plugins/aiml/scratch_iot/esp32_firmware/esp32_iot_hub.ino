/*
 * ==============================================================================
 * Project: ESP32 IoT Actuator Hub (Emotiv EPOC BCI Integration)
 * Target Board: ESP32 Dev Module / NodeMCU-32S
 * Actuators:
 *   - 💡 Light (Relay 1) -> GPIO 21
 *   - 🌀 Fan   (Relay 2) -> GPIO 32
 *   - 🚰 Pump  (Relay 3) -> GPIO 25
 *   - ⚡ Status LED      -> GPIO 2 (Built-in)
 * 
 * Communication Modes:
 *   1. Serial UART (115200 baud) - USB Cable Mode
 *   2. WiFi HTTP REST Server - Wireless Mode (http://<ESP32_IP>/api/control)
 *   3. Direct WebSocket Client - Real-time push connection to Master Hub
 * ==============================================================================
 */

#include <WiFi.h>
#include <WebServer.h>

// ---------------- USER CONFIGURATION ----------------
const char* WIFI_SSID = "YOUR_WIFI_SSID";         // Replace with your WiFi SSID
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";     // Replace with your WiFi Password

// Master Hub Server IP for reverse reporting (optional)
const char* MASTER_HUB_IP = "192.168.1.100";
const int MASTER_HUB_PORT = 3000;

// ---------------- RELAY TRIGGER LOGIC CONFIGURATION ----------------
// Most relay breakout boards (1/2/4/8 channel) are ACTIVE-LOW:
//   - LOW  (0V)        -> Relay ON (Energized)
//   - HIGH (3.3V/5V)   -> Relay OFF (De-energized)
// Set to 'true' for standard active-low relay modules.
// Set to 'false' if using active-high relays or simple LEDs wired to GND.
const bool ACTIVE_LOW_RELAYS = true;

#define RELAY_ON  (ACTIVE_LOW_RELAYS ? LOW : HIGH)
#define RELAY_OFF (ACTIVE_LOW_RELAYS ? HIGH : LOW)

// ---------------- PIN DEFINITIONS -------------------
const int PIN_LIGHT      = 21; // Light Actuator / Relay 1
const int PIN_FAN        = 32; // Fan Actuator / Relay 2
const int PIN_PUMP       = 25; // Pump Actuator / Relay 3
const int PIN_STATUS_LED = 2;  // Built-in Heartbeat Status LED

// ---------------- DEVICE STATES ---------------------
bool stateLight = false;
bool stateFan   = false;
bool statePump  = false;

WebServer server(80);
unsigned long lastHeartbeat = 0;
bool heartbeatState = false;

// ---------------- FUNCTION DECLARATIONS -------------
void setupHardware();
void setupWiFi();
void setupWebServer();
void processSerialCommands();
void setActuatorState(String device, String state);
String getStatusJson();
void handleControl();
void handleStatus();
void handleRoot();

void setup() {
  Serial.begin(115200);
  delay(500);

  Serial.println("\n=======================================================");
  Serial.println("  🧠 ESP32 IoT Master Hub for Emotiv EPOC BCI");
  Serial.printf("  Pins: Light(%d), Fan(%d), Pump(%d), Status(%d)\n", PIN_LIGHT, PIN_FAN, PIN_PUMP, PIN_STATUS_LED);
  Serial.printf("  Relay Mode: %s\n", ACTIVE_LOW_RELAYS ? "ACTIVE-LOW (LOW=ON, HIGH=OFF)" : "ACTIVE-HIGH (HIGH=ON, LOW=OFF)");
  Serial.println("=======================================================");

  setupHardware();
  setupWiFi();
  setupWebServer();

  Serial.println("[ESP32 READY] Listening on Serial and WiFi HTTP REST.");
}

void loop() {
  // Handle HTTP REST API requests
  server.handleClient();

  // Handle Serial USB Commands
  processSerialCommands();

  // Non-blocking Heartbeat Blink
  if (millis() - lastHeartbeat >= 1000) {
    lastHeartbeat = millis();
    heartbeatState = !heartbeatState;
    digitalWrite(PIN_STATUS_LED, heartbeatState ? HIGH : LOW);
  }
}

// ---------------- HARDWARE SETUP --------------------
void setupHardware() {
  // Set default output level to OFF BEFORE enabling output mode to prevent startup flicker/glitches
  digitalWrite(PIN_LIGHT, RELAY_OFF);
  digitalWrite(PIN_FAN, RELAY_OFF);
  digitalWrite(PIN_PUMP, RELAY_OFF);
  digitalWrite(PIN_STATUS_LED, LOW);

  pinMode(PIN_LIGHT, OUTPUT);
  pinMode(PIN_FAN, OUTPUT);
  pinMode(PIN_PUMP, OUTPUT);
  pinMode(PIN_STATUS_LED, OUTPUT);

  // Guarantee all relays remain firmly OFF upon boot
  digitalWrite(PIN_LIGHT, RELAY_OFF);
  digitalWrite(PIN_FAN, RELAY_OFF);
  digitalWrite(PIN_PUMP, RELAY_OFF);
  digitalWrite(PIN_STATUS_LED, LOW);

  stateLight = false;
  stateFan   = false;
  statePump  = false;
}

// ---------------- WIFI SETUP ------------------------
void setupWiFi() {
  if (String(WIFI_SSID) == "YOUR_WIFI_SSID") {
    Serial.println("[WiFi] Default WiFi credentials detected. Running in SERIAL-ONLY mode.");
    Serial.println("[WiFi] To enable WiFi, update WIFI_SSID and WIFI_PASS in esp32_iot_hub.ino");
    return;
  }

  Serial.printf("[WiFi] Connecting to %s", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n[WiFi] Connected!");
    Serial.print("[WiFi] ESP32 IP Address: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\n[WiFi] Connection timed out. Running in Serial mode.");
  }
}

// ---------------- WEB SERVER & REST API -------------
void setupWebServer() {
  // CORS Headers for all REST responses
  server.enableCORS(true);

  server.on("/", HTTP_GET, handleRoot);
  server.on("/api/status", HTTP_GET, handleStatus);
  server.on("/api/control", HTTP_GET, handleControl);
  server.on("/api/control", HTTP_POST, handleControl);

  server.begin();
  Serial.println("[HTTP] REST API Server started on port 80");
}

void handleRoot() {
  String html = "<!DOCTYPE html><html><head><title>ESP32 IoT Hub</title>";
  html += "<meta name='viewport' content='width=device-width, initial-scale=1'>";
  html += "<style>body{font-family:sans-serif;background:#0d1117;color:#c9d1d9;padding:20px;text-align:center;}";
  html += ".card{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:15px;margin:10px auto;max-width:400px;}";
  html += "h1{color:#58a6ff;} .btn{display:inline-block;padding:8px 16px;margin:5px;border-radius:6px;text-decoration:none;font-weight:bold;}";
  html += ".on{background:#238636;color:white;} .off{background:#da3633;color:white;}</style></head><body>";
  html += "<h1>🧠 ESP32 IoT Master Hub</h1><p>Emotiv EPOC BCI Receiver</p>";

  html += "<div class='card'><h3>💡 Light (GPIO " + String(PIN_LIGHT) + "): " + String(stateLight ? "ON" : "OFF") + "</h3>";
  html += "<a class='btn on' href='/api/control?device=light&state=ON'>Turn ON</a>";
  html += "<a class='btn off' href='/api/control?device=light&state=OFF'>Turn OFF</a></div>";

  html += "<div class='card'><h3>🌀 Fan (GPIO " + String(PIN_FAN) + "): " + String(stateFan ? "ON" : "OFF") + "</h3>";
  html += "<a class='btn on' href='/api/control?device=fan&state=ON'>Turn ON</a>";
  html += "<a class='btn off' href='/api/control?device=fan&state=OFF'>Turn OFF</a></div>";

  html += "<div class='card'><h3>🚰 Pump (GPIO " + String(PIN_PUMP) + "): " + String(statePump ? "ON" : "OFF") + "</h3>";
  html += "<a class='btn on' href='/api/control?device=pump&state=ON'>Turn ON</a>";
  html += "<a class='btn off' href='/api/control?device=pump&state=OFF'>Turn OFF</a></div>";

  html += "</body></html>";
  server.send(200, "text/html", html);
}

void handleStatus() {
  server.send(200, "application/json", getStatusJson());
}

void handleControl() {
  if (!server.hasArg("device") || !server.hasArg("state")) {
    server.send(400, "application/json", "{\"error\":\"Missing device or state argument\"}");
    return;
  }

  String device = server.arg("device");
  String state  = server.arg("state");

  setActuatorState(device, state);
  server.send(200, "application/json", getStatusJson());
}

// ---------------- ACTUATOR CONTROLLER ---------------
void setActuatorState(String device, String state) {
  device.toLowerCase();
  state.toUpperCase();
  bool isOn = (state == "ON" || state == "1" || state == "TRUE");

  if (device == "light" || device == "push") {
    stateLight = isOn;
    digitalWrite(PIN_LIGHT, stateLight ? RELAY_ON : RELAY_OFF);
    Serial.printf("[ACTION] Light set to %s (Pin %d)\n", stateLight ? "ON" : "OFF", PIN_LIGHT);
  } else if (device == "fan" || device == "pull") {
    stateFan = isOn;
    digitalWrite(PIN_FAN, stateFan ? RELAY_ON : RELAY_OFF);
    Serial.printf("[ACTION] Fan set to %s (Pin %d)\n", stateFan ? "ON" : "OFF", PIN_FAN);
  } else if (device == "pump" || device == "left") {
    statePump = isOn;
    digitalWrite(PIN_PUMP, statePump ? RELAY_ON : RELAY_OFF);
    Serial.printf("[ACTION] Pump set to %s (Pin %d)\n", statePump ? "ON" : "OFF", PIN_PUMP);
  } else if (device == "all") {
    stateLight = isOn;
    stateFan   = isOn;
    statePump  = isOn;
    digitalWrite(PIN_LIGHT, stateLight ? RELAY_ON : RELAY_OFF);
    digitalWrite(PIN_FAN, stateFan ? RELAY_ON : RELAY_OFF);
    digitalWrite(PIN_PUMP, statePump ? RELAY_ON : RELAY_OFF);
    Serial.printf("[ACTION] All actuators set to %s\n", isOn ? "ON" : "OFF");
  }

  // Print ACK JSON to Serial
  Serial.println(getStatusJson());
}

String getStatusJson() {
  String json = "{";
  json += "\"uptime\":" + String(millis()) + ",";
  json += "\"states\":{";
  json += "\"light\":\"" + String(stateLight ? "ON" : "OFF") + "\",";
  json += "\"fan\":\""   + String(stateFan   ? "ON" : "OFF") + "\",";
  json += "\"pump\":\""  + String(statePump  ? "ON" : "OFF") + "\"";
  json += "}}";
  return json;
}

// ---------------- SERIAL COMMAND PARSER -------------
void processSerialCommands() {
  if (!Serial.available()) return;

  String line = Serial.readStringUntil('\n');
  line.trim();
  if (line.length() == 0) return;

  Serial.printf("[SERIAL RX] %s\n", line.c_str());

  if (line.equalsIgnoreCase("STATUS")) {
    Serial.println(getStatusJson());
    return;
  }

  // Protocol format 1: "LIGHT:ON", "FAN:OFF", "PUMP:ON"
  int colonIndex = line.indexOf(':');
  if (colonIndex != -1) {
    String device = line.substring(0, colonIndex);
    String state  = line.substring(colonIndex + 1);
    setActuatorState(device, state);
    return;
  }

  // Protocol format 2: simple space separated "light on", "fan off"
  int spaceIndex = line.indexOf(' ');
  if (spaceIndex != -1) {
    String device = line.substring(0, spaceIndex);
    String state  = line.substring(spaceIndex + 1);
    setActuatorState(device, state);
    return;
  }
}

