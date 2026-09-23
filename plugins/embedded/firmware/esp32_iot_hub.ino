/*
 * ==============================================================================
 * Project: ESP32 IoT Actuator Hub (Emotiv EPOC BCI Integration)
 * Target Board: ESP32 Dev Module / NodeMCU-32S / ESP32-WROOM-32
 * 
 * Actuators / Relays:
 *   - 💡 Light (Relay 1) -> GPIO 21 (or GPIO 23)
 *   - 🌀 Fan   (Relay 2) -> GPIO 32 (or GPIO 22)
 *   - 🚰 Pump  (Relay 3) -> GPIO 25 (or GPIO 21)
 *   - ⚡ Status LED      -> GPIO 2  (Built-in Blue LED)
 * 
 * Communication Modes:
 *   1. Serial UART (115200 baud) - Fast, 100% reliable USB Cable Mode
 *   2. WiFi HTTP REST Server     - Wireless Mode (http://<ESP32_IP>/api/control)
 *   3. mDNS Local Domain         - http://esp32-hub.local/api/status
 *   4. MQTT Broker Mode          - Real-time PubSub over MQTT Broker (iot/esp32/cmd & iot/esp32/status)
 * ==============================================================================
 */

#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include <PubSubClient.h>

// ==============================================================================
// 1. USER WIFI CONFIGURATION
// ==============================================================================
// Set your 2.4GHz WiFi credentials (ESP32 supports 2.4GHz WiFi only, not 5GHz)
const char* WIFI_SSID = "YOUR_WIFI_SSID";         // Replace with your WiFi SSID
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";     // Replace with your WiFi Password

// ==============================================================================
// 1B. USER MQTT BROKER & TOPIC CONFIGURATION
// ==============================================================================
// Set your MQTT Broker host or IP (e.g. "52.21.249.6" or your server IP or "broker.emqx.io")
const char* MQTT_BROKER       = "52.21.249.6";         // Replace with your MQTT server IP or hostname
const int   MQTT_PORT         = 1883;                  // Default MQTT port (1883)
const char* MQTT_USER         = "";                    // Optional: Broker username (leave empty if none)
const char* MQTT_PASS         = "";                    // Optional: Broker password (leave empty if none)
const char* MQTT_CLIENT_ID    = "ESP32_Actuator_Node"; // Unique Client ID

// Topic Schema: {BASE_TOPIC}/{DEVICE_ID}/<type>
const char* BASE_TOPIC        = "iot";                 // Base topic namespace
const char* DEVICE_ID         = "esp32";               // Device identifier

// STATUS_TOPIC = "{BASE_TOPIC}/{DEVICE_ID}/status"
// ACTION_TOPIC = "{BASE_TOPIC}/{DEVICE_ID}/action"
// ACK_TOPIC    = "{BASE_TOPIC}/{DEVICE_ID}/ack"
const char* STATUS_TOPIC      = "iot/esp32/status";    // Published full state telemetry
const char* ACTION_TOPIC      = "iot/esp32/action";    // Subscribed action/command topic
const char* ACK_TOPIC         = "iot/esp32/ack";       // Published command acknowledgment
const char* LWT_TOPIC         = "iot/esp32/availability";// Published LWT / online topic

// ==============================================================================
// 2. RELAY / ACTUATOR TRIGGER LOGIC (ACTIVE-HIGH vs ACTIVE-LOW)
// ==============================================================================
// ⚠️ IMPORTANT: Why do appliances turn ON at power-up and not turn off?
//
// Scenario A: LEDs or Active-HIGH Relays / MOSFETs / Transistors (VCC on pin -> GND)
//   -> Set 'activeLowRelays = false'
//   -> HIGH (3.3V) = Turn ON, LOW (0V) = Turn OFF.
//
// Scenario B: Active-LOW Relay Modules (standard 1/2/4/8 channel optocoupler boards)
//   -> Set 'activeLowRelays = true'
//   -> LOW (0V) = Turn ON, HIGH (3.3V) = Turn OFF.
//
// Scenario C: 5V Active-LOW Relay Module powered by 5V VCC
//   -> If ESP32 3.3V HIGH is not high enough to turn OFF a 5V relay (1.7V drop across optocoupler),
//      set 'USE_OPEN_DRAIN = true' or power the relay module VCC from 3.3V.
//
// NOTE: You can also switch polarity dynamically by sending serial command "POLARITY:HIGH" or "POLARITY:LOW"
bool activeLowRelays = false;        // Default to Active-High (LEDs / standard high-trigger)
const bool USE_OPEN_DRAIN = false;  // Set true for 5V optocoupler relay boards needing open-drain Hi-Z

// ==============================================================================
// 3. PIN DEFINITIONS
// ==============================================================================
const int PIN_LIGHT      = 21; // Light Actuator / Relay 1 (Change to 23 if using alternate pinout)
const int PIN_FAN        = 32; // Fan Actuator / Relay 2   (Change to 22 if using alternate pinout)
const int PIN_PUMP       = 25; // Pump Actuator / Relay 3  (Change to 21 if using alternate pinout)
const int PIN_STATUS_LED = 2;  // Built-in Heartbeat / WiFi Status LED

// ==============================================================================
// 4. DEVICE STATES & TIMERS
// ==============================================================================
bool stateLight = false;
bool stateFan   = false;
bool statePump  = false;

WebServer server(80);
WiFiClient espWiFiClient;
PubSubClient mqttClient(espWiFiClient);

unsigned long lastHeartbeat = 0;
unsigned long lastWiFiCheck = 0;
unsigned long lastMqttCheck = 0;
bool heartbeatState = false;
bool isWiFiConfigured = false;
bool isMqttConfigured = false;

// ---------------- FUNCTION DECLARATIONS ----------------
void setupHardware();
void setupWiFi();
void checkWiFiConnection();
void setupMQTT();
void checkMQTTConnection();
bool reconnectMQTT();
void mqttCallback(char* topic, byte* payload, unsigned int length);
void publishMqttStatus();
void setupWebServer();
void processSerialCommands();
void setActuatorState(String device, String state);
void setRelayPolarity(bool isLow);
int getPinLevel(bool isOn);
void runSelfTest();
String getStatusJson();
void handleControl();
void handleStatus();
void handleRoot();
void handleTest();

// ==============================================================================
// SETUP
// ==============================================================================
void setup() {
  Serial.begin(115200);
  Serial.setTimeout(20); // Fast non-blocking serial read timeout (20ms)
  delay(300);

  Serial.println("\n=======================================================");
  Serial.println("  🧠 ESP32 IoT Master Hub for Emotiv EPOC BCI");
  Serial.printf("  Pins: Light(GPIO %d), Fan(GPIO %d), Pump(GPIO %d), Status(GPIO %d)\n", 
                PIN_LIGHT, PIN_FAN, PIN_PUMP, PIN_STATUS_LED);
  Serial.printf("  Default Relay Mode: %s\n", activeLowRelays ? "ACTIVE-LOW" : "ACTIVE-HIGH");
  Serial.println("=======================================================");

  // 1. Initialize hardware outputs strictly in OFF state
  setupHardware();

  // 2. Quick 3-blink startup indicator on status LED
  for (int i = 0; i < 3; i++) {
    digitalWrite(PIN_STATUS_LED, HIGH);
    delay(80);
    digitalWrite(PIN_STATUS_LED, LOW);
    delay(80);
  }

  // 3. Connect WiFi
  setupWiFi();

  // 4. Start MQTT Client (if configured)
  setupMQTT();

  // 5. Start HTTP Web Server
  setupWebServer();

  Serial.println("[ESP32 READY] Listening for commands via USB Serial, WiFi REST, and MQTT.");
  Serial.println("Tip: Send 'TEST' in Serial Monitor to test all actuators.");
  Serial.println("Tip: Send 'POLARITY:HIGH' or 'POLARITY:LOW' to flip relay logic.");
}

// ==============================================================================
// MAIN LOOP
// ==============================================================================
void loop() {
  // Handle HTTP REST API client requests
  server.handleClient();

  // Handle Serial USB Commands (Instant non-blocking)
  processSerialCommands();

  // Handle MQTT Broker Messages & Keepalive (non-blocking)
  if (WiFi.status() == WL_CONNECTED && isMqttConfigured) {
    if (mqttClient.connected()) {
      mqttClient.loop();
    } else {
      checkMQTTConnection();
    }
  }

  // Periodic non-blocking WiFi reconnect check (every 5 seconds)
  if (millis() - lastWiFiCheck >= 5000) {
    lastWiFiCheck = millis();
    checkWiFiConnection();
  }

  // Non-blocking Heartbeat Blink (Blinks fast if WiFi disconnected, slow if connected)
  unsigned long interval = (WiFi.status() == WL_CONNECTED) ? 1000 : 250;
  if (millis() - lastHeartbeat >= interval) {
    lastHeartbeat = millis();
    heartbeatState = !heartbeatState;
    digitalWrite(PIN_STATUS_LED, heartbeatState ? HIGH : LOW);
  }
}

// ==============================================================================
// HARDWARE INITIALIZATION
// ==============================================================================
int getPinLevel(bool isOn) {
  if (activeLowRelays) {
    return isOn ? LOW : HIGH;
  } else {
    return isOn ? HIGH : LOW;
  }
}

void applyPinModes() {
  int outMode = USE_OPEN_DRAIN ? OUTPUT_OPEN_DRAIN : OUTPUT;
  pinMode(PIN_LIGHT, outMode);
  pinMode(PIN_FAN, outMode);
  pinMode(PIN_PUMP, outMode);
  pinMode(PIN_STATUS_LED, OUTPUT);
}

void applyCurrentStates() {
  digitalWrite(PIN_LIGHT, getPinLevel(stateLight));
  digitalWrite(PIN_FAN,   getPinLevel(stateFan));
  digitalWrite(PIN_PUMP,  getPinLevel(statePump));
}

void setupHardware() {
  // All devices start OFF
  stateLight = false;
  stateFan   = false;
  statePump  = false;

  // Set OFF output levels before enabling pinMode to prevent power-on glitches
  digitalWrite(PIN_LIGHT, getPinLevel(false));
  digitalWrite(PIN_FAN,   getPinLevel(false));
  digitalWrite(PIN_PUMP,  getPinLevel(false));
  digitalWrite(PIN_STATUS_LED, LOW);

  applyPinModes();
  applyCurrentStates();

  Serial.println("[HARDWARE] Actuators initialized in OFF state.");
}

void setRelayPolarity(bool isLow) {
  activeLowRelays = isLow;
  Serial.printf("[CONFIG] Relay polarity changed to: %s\n", activeLowRelays ? "ACTIVE-LOW (LOW=ON, HIGH=OFF)" : "ACTIVE-HIGH (HIGH=ON, LOW=OFF)");
  applyCurrentStates();
}

// ==============================================================================
// WIFI & NETWORKING
// ==============================================================================
void setupWiFi() {
  if (String(WIFI_SSID) == "YOUR_WIFI_SSID" || String(WIFI_SSID).length() == 0) {
    isWiFiConfigured = false;
    Serial.println("[WiFi] No WiFi credentials configured. Running in USB SERIAL-ONLY mode.");
    Serial.println("[WiFi] To enable WiFi REST API, edit WIFI_SSID & WIFI_PASS in esp32_iot_hub.ino");
    return;
  }

  isWiFiConfigured = true;
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.persistent(true);

  Serial.printf("[WiFi] Connecting to 2.4GHz SSID: '%s'", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 25) {
    delay(300);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n[WiFi] Connected successfully!");
    Serial.print("[WiFi IP Address] http://");
    Serial.println(WiFi.localIP());
    Serial.printf("[WiFi Signal] RSSI: %d dBm\n", WiFi.RSSI());

    if (MDNS.begin("esp32-hub")) {
      Serial.println("[mDNS] Responder started: http://esp32-hub.local");
    }
  } else {
    Serial.println("\n[WiFi] Initial connection timeout. Background auto-reconnect will keep trying.");
    Serial.println("[WiFi] USB Serial control is active and ready immediately.");
  }
}

void checkWiFiConnection() {
  if (!isWiFiConfigured) return;

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[WiFi] Disconnected. Reconnecting...");
    WiFi.disconnect();
    WiFi.reconnect();
  }
}

// ==============================================================================
// WEB SERVER & REST API
// ==============================================================================
void setupWebServer() {
  server.enableCORS(true);

  server.on("/", HTTP_GET, handleRoot);
  server.on("/api/status", HTTP_GET, handleStatus);
  server.on("/api/control", HTTP_GET, handleControl);
  server.on("/api/control", HTTP_POST, handleControl);
  server.on("/api/test", HTTP_GET, handleTest);
  server.on("/api/test", HTTP_POST, handleTest);

  server.begin();
  Serial.println("[HTTP Server] REST API listening on port 80");
}

void handleRoot() {
  String html = "<!DOCTYPE html><html><head><title>ESP32 IoT Hub</title>";
  html += "<meta name='viewport' content='width=device-width, initial-scale=1'>";
  html += "<style>body{font-family:sans-serif;background:#0d1117;color:#c9d1d9;padding:20px;text-align:center;}";
  html += ".card{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:15px;margin:10px auto;max-width:420px;}";
  html += "h1{color:#58a6ff;} .btn{display:inline-block;padding:8px 16px;margin:5px;border-radius:6px;text-decoration:none;font-weight:bold;}";
  html += ".on{background:#238636;color:white;} .off{background:#da3633;color:white;} .util{background:#1f6feb;color:white;}";
  html += ".status{font-size:14px;color:#8b949e;margin-top:10px;}</style></head><body>";
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

  html += "<div class='card'><h3>⚙️ Relay Polarity: " + String(activeLowRelays ? "Active-LOW" : "Active-HIGH") + "</h3>";
  html += "<a class='btn util' href='/api/control?polarity=active_high'>Set Active-HIGH (LEDs)</a>";
  html += "<a class='btn util' href='/api/control?polarity=active_low'>Set Active-LOW (Relays)</a>";
  html += "<br><a class='btn on' href='/api/control?device=all&state=OFF'>Turn ALL OFF</a>";
  html += "<a class='btn util' href='/api/test'>Run Hardware Test</a></div>";

  html += "<div class='status'>IP: " + WiFi.localIP().toString() + " | Uptime: " + String(millis() / 1000) + "s</div>";
  html += "</body></html>";
  server.send(200, "text/html", html);
}

void handleStatus() {
  server.send(200, "application/json", getStatusJson());
}

void handleControl() {
  // Check for polarity configuration
  if (server.hasArg("polarity")) {
    String pol = server.arg("polarity");
    pol.toLowerCase();
    if (pol == "active_low" || pol == "low" || pol == "true" || pol == "1") {
      setRelayPolarity(true);
    } else {
      setRelayPolarity(false);
    }
    server.send(200, "application/json", getStatusJson());
    return;
  }

  if (!server.hasArg("device") || !server.hasArg("state")) {
    server.send(400, "application/json", "{\"error\":\"Missing 'device' or 'state' parameter\"}");
    return;
  }

  String device = server.arg("device");
  String state  = server.arg("state");

  setActuatorState(device, state);
  server.send(200, "application/json", getStatusJson());
}

void handleTest() {
  runSelfTest();
  server.send(200, "application/json", getStatusJson());
}

// ==============================================================================
// ACTUATOR CONTROLLER
// ==============================================================================
void setActuatorState(String device, String state) {
  device.toLowerCase();
  state.toUpperCase();
  bool isOn = (state == "ON" || state == "1" || state == "TRUE");

  if (device == "light" || device == "push") {
    stateLight = isOn;
    digitalWrite(PIN_LIGHT, getPinLevel(stateLight));
    Serial.printf("[ACTION] Light set to %s (Pin %d -> %s)\n", 
                  stateLight ? "ON" : "OFF", PIN_LIGHT, getPinLevel(stateLight) ? "HIGH" : "LOW");
  } else if (device == "fan" || device == "pull") {
    stateFan = isOn;
    digitalWrite(PIN_FAN, getPinLevel(stateFan));
    Serial.printf("[ACTION] Fan set to %s (Pin %d -> %s)\n", 
                  stateFan ? "ON" : "OFF", PIN_FAN, getPinLevel(stateFan) ? "HIGH" : "LOW");
  } else if (device == "pump" || device == "left") {
    statePump = isOn;
    digitalWrite(PIN_PUMP, getPinLevel(statePump));
    Serial.printf("[ACTION] Pump set to %s (Pin %d -> %s)\n", 
                  statePump ? "ON" : "OFF", PIN_PUMP, getPinLevel(statePump) ? "HIGH" : "LOW");
  } else if (device == "all") {
    stateLight = isOn;
    stateFan   = isOn;
    statePump  = isOn;
    digitalWrite(PIN_LIGHT, getPinLevel(stateLight));
    digitalWrite(PIN_FAN,   getPinLevel(stateFan));
    digitalWrite(PIN_PUMP,  getPinLevel(statePump));
    Serial.printf("[ACTION] All actuators set to %s\n", isOn ? "ON" : "OFF");
  }

  // Output status JSON ACK
  Serial.println(getStatusJson());

  // Publish updated status to MQTT
  publishMqttStatus();
}

void runSelfTest() {
  Serial.println("\n[TEST] --- Starting Hardware Self-Test ---");
  
  // All OFF first
  digitalWrite(PIN_LIGHT, getPinLevel(false));
  digitalWrite(PIN_FAN,   getPinLevel(false));
  digitalWrite(PIN_PUMP,  getPinLevel(false));
  delay(300);

  // Test Light
  Serial.println("[TEST] Testing Light (GPIO " + String(PIN_LIGHT) + ") -> ON");
  digitalWrite(PIN_LIGHT, getPinLevel(true));
  delay(600);
  digitalWrite(PIN_LIGHT, getPinLevel(false));

  // Test Fan
  Serial.println("[TEST] Testing Fan (GPIO " + String(PIN_FAN) + ") -> ON");
  digitalWrite(PIN_FAN, getPinLevel(true));
  delay(600);
  digitalWrite(PIN_FAN, getPinLevel(false));

  // Test Pump
  Serial.println("[TEST] Testing Pump (GPIO " + String(PIN_PUMP) + ") -> ON");
  digitalWrite(PIN_PUMP, getPinLevel(true));
  delay(600);
  digitalWrite(PIN_PUMP, getPinLevel(false));

  // Restore current states
  applyCurrentStates();
  Serial.println("[TEST] --- Hardware Self-Test Finished ---\n");
}

String getStatusJson() {
  String json = "{";
  json += "\"uptime\":" + String(millis()) + ",";
  json += "\"wifiConnected\":" + String(WiFi.status() == WL_CONNECTED ? "true" : "false") + ",";
  json += "\"mqttConnected\":" + String(mqttClient.connected() ? "true" : "false") + ",";
  json += "\"ip\":\"" + WiFi.localIP().toString() + "\",";
  json += "\"relayMode\":\"" + String(activeLowRelays ? "active_low" : "active_high") + "\",";
  json += "\"states\":{";
  json += "\"light\":\"" + String(stateLight ? "ON" : "OFF") + "\",";
  json += "\"fan\":\""   + String(stateFan   ? "ON" : "OFF") + "\",";
  json += "\"pump\":\""  + String(statePump  ? "ON" : "OFF") + "\"";
  json += "}}";
  return json;
}

// ==============================================================================
// SERIAL COMMAND PARSER
// ==============================================================================
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

  if (line.equalsIgnoreCase("IP") || line.equalsIgnoreCase("WIFI")) {
    if (WiFi.status() == WL_CONNECTED) {
      Serial.printf("[WiFi] Connected to '%s' | IP: http://%s | RSSI: %d dBm\n", 
                    WIFI_SSID, WiFi.localIP().toString().c_str(), WiFi.RSSI());
    } else {
      Serial.printf("[WiFi] Not connected (Status code: %d). WiFi Configured: %s\n", 
                    WiFi.status(), isWiFiConfigured ? "YES" : "NO");
    }
    return;
  }

  if (line.equalsIgnoreCase("TEST")) {
    runSelfTest();
    return;
  }

  if (line.equalsIgnoreCase("POLARITY:HIGH") || line.equalsIgnoreCase("RELAY:ACTIVE_HIGH") || line.equalsIgnoreCase("POLARITY HIGH")) {
    setRelayPolarity(false);
    return;
  }

  if (line.equalsIgnoreCase("POLARITY:LOW") || line.equalsIgnoreCase("RELAY:ACTIVE_LOW") || line.equalsIgnoreCase("POLARITY LOW")) {
    setRelayPolarity(true);
    return;
  }

  if (line.equalsIgnoreCase("INVERT")) {
    setRelayPolarity(!activeLowRelays);
    return;
  }

  // Protocol format: "LIGHT:ON", "FAN:OFF", "PUMP:ON", "ALL:OFF"
  int colonIndex = line.indexOf(':');
  if (colonIndex != -1) {
    String device = line.substring(0, colonIndex);
    String state  = line.substring(colonIndex + 1);
    setActuatorState(device, state);
    return;
  }

  // Space-separated format: "light on", "fan off", "all off"
  int spaceIndex = line.indexOf(' ');
  if (spaceIndex != -1) {
    String device = line.substring(0, spaceIndex);
    String state  = line.substring(spaceIndex + 1);
    setActuatorState(device, state);
    return;
  }
}

// ==============================================================================
// MQTT IMPLEMENTATION
// ==============================================================================
void setupMQTT() {
  if (String(MQTT_BROKER) == "192.168.1.100" && !isWiFiConfigured) {
    // WiFi not configured, leave MQTT idle
    isMqttConfigured = false;
    return;
  }
  if (String(MQTT_BROKER).length() == 0) {
    isMqttConfigured = false;
    Serial.println("[MQTT] No MQTT Broker configured.");
    return;
  }

  isMqttConfigured = true;
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setCallback(mqttCallback);
  mqttClient.setBufferSize(512); // Buffer size for JSON messages

  Serial.printf("[MQTT] Broker: %s:%d | Action: %s | Status: %s | Ack: %s\n", 
                MQTT_BROKER, MQTT_PORT, ACTION_TOPIC, STATUS_TOPIC, ACK_TOPIC);
  if (WiFi.status() == WL_CONNECTED) {
    reconnectMQTT();
  }
}

void checkMQTTConnection() {
  if (!isMqttConfigured || WiFi.status() != WL_CONNECTED) return;

  if (!mqttClient.connected()) {
    if (millis() - lastMqttCheck >= 5000) {
      lastMqttCheck = millis();
      reconnectMQTT();
    }
  }
}

bool reconnectMQTT() {
  if (!isMqttConfigured || WiFi.status() != WL_CONNECTED) return false;
  if (mqttClient.connected()) return true;

  Serial.printf("[MQTT] Connecting to broker '%s:%d'...", MQTT_BROKER, MQTT_PORT);

  bool connected = false;
  if (strlen(MQTT_USER) > 0) {
    connected = mqttClient.connect(MQTT_CLIENT_ID, MQTT_USER, MQTT_PASS, LWT_TOPIC, 0, true, "offline");
  } else {
    connected = mqttClient.connect(MQTT_CLIENT_ID, LWT_TOPIC, 0, true, "offline");
  }

  if (connected) {
    Serial.println(" CONNECTED!");
    mqttClient.publish(LWT_TOPIC, "online", true);
    mqttClient.subscribe(ACTION_TOPIC);
    mqttClient.subscribe("iot/esp32/cmd"); // Backward-compatible alias
    mqttClient.subscribe("iot/esp32/ping");
    publishMqttStatus();
    return true;
  } else {
    Serial.printf(" FAILED (rc=%d). Will retry in 5s.\n", mqttClient.state());
    return false;
  }
}

void publishMqttStatus() {
  if (mqttClient.connected()) {
    String payload = getStatusJson();
    mqttClient.publish(STATUS_TOPIC, payload.c_str(), false);
  }
}

void publishMqttAck(String device, String state) {
  if (mqttClient.connected()) {
    String ackPayload = "{\"device\":\"" + device + "\",\"state\":\"" + state + "\",\"status\":\"OK\",\"timestamp\":" + String(millis()) + "}";
    mqttClient.publish(ACK_TOPIC, ackPayload.c_str(), false);
  }
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  char message[length + 1];
  for (unsigned int i = 0; i < length; i++) {
    message[i] = (char)payload[i];
  }
  message[length] = '\0';
  String msgStr = String(message);
  msgStr.trim();

  Serial.printf("[MQTT RX] %s -> %s\n", topic, msgStr.c_str());

  if (String(topic) == "iot/esp32/ping" || msgStr.equalsIgnoreCase("PING")) {
    mqttClient.publish("iot/esp32/pong", "PONG");
    return;
  }

  // Check JSON format: {"device":"light","state":"ON"}
  if (msgStr.startsWith("{") && msgStr.endsWith("}")) {
    int devIdx = msgStr.indexOf("\"device\"");
    int stateIdx = msgStr.indexOf("\"state\"");
    if (devIdx != -1 && stateIdx != -1) {
      int devColon = msgStr.indexOf(':', devIdx);
      int devQuote1 = msgStr.indexOf('"', devColon);
      int devQuote2 = msgStr.indexOf('"', devQuote1 + 1);
      String device = msgStr.substring(devQuote1 + 1, devQuote2);

      int stColon = msgStr.indexOf(':', stateIdx);
      int stQuote1 = msgStr.indexOf('"', stColon);
      int stQuote2 = msgStr.indexOf('"', stQuote1 + 1);
      String state = msgStr.substring(stQuote1 + 1, stQuote2);

      setActuatorState(device, state);
      publishMqttAck(device, state);
      return;
    }
  }

  // Format: "LIGHT:ON", "FAN:OFF", etc.
  int colonIndex = msgStr.indexOf(':');
  if (colonIndex != -1) {
    String device = msgStr.substring(0, colonIndex);
    String state  = msgStr.substring(colonIndex + 1);
    setActuatorState(device, state);
    publishMqttAck(device, state);
    return;
  }

  // Format: "light on", "fan off", etc.
  int spaceIndex = msgStr.indexOf(' ');
  if (spaceIndex != -1) {
    String device = msgStr.substring(0, spaceIndex);
    String state  = msgStr.substring(spaceIndex + 1);
    setActuatorState(device, state);
    publishMqttAck(device, state);
    return;
  }
}
