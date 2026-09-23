/*
====================================================
      SYNAPTIMESH ESP32-C6 ROBOT CAR SLAVE
      Master Hub + Mosquitto MQTT
====================================================
*/

#include <WiFi.h>
#include <WiFiClient.h>
#include <WebServer.h>
#include <PubSubClient.h>
#include <Preferences.h>
#include <NimBLEDevice.h>

// ====================================================
// WIFI
// ====================================================
Preferences prefs;

String wifiSSID = "";
String wifiPASS = "";

// ====================================================
// MQTT - MATCHES MASTER HUB
// ====================================================

const char* MQTT_SERVER = "52.21.249.6";
const uint16_t MQTT_PORT = 1883;

const char* DEVICE_ID = "98:A3:16:BF:2C:C0";

const char* CONTROL_TOPIC =
    "robotcar/98:A3:16:BF:2C:C0/control";

const char* ACK_TOPIC =
    "robotcar/98:A3:16:BF:2C:C0/ack";

const char* STATUS_TOPIC =
    "robotcar/98:A3:16:BF:2C:C0/status";

#define SERVICE_UUID "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
#define RX_UUID      "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
#define TX_UUID      "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

#define DEVICE_NAME "SynaptiMesh_C6_Setup"

// ====================================================
// MOTOR PINS
// ====================================================

#define IN1 10
#define IN2 11
#define IN3 4
#define IN4 5

// ====================================================
// ULTRASONIC
// ====================================================

#define FRONT_TRIG 18
#define FRONT_ECHO 19

#define REAR_TRIG 21
#define REAR_ECHO 22

const float OBSTACLE_LIMIT = 30.0;

// ====================================================
// TIMING
// ====================================================

const unsigned long WIFI_RETRY = 5000;
const unsigned long MQTT_RETRY = 3000;
const unsigned long SENSOR_INTERVAL = 300;

const unsigned long TURN_TIME = 500;
const unsigned long TURN360_TIME = 2000;

// ====================================================
// OBJECT
// ====================================================

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);
WebServer httpServer(80);

NimBLEServer* server = nullptr;
NimBLECharacteristic* txChar = nullptr;
NimBLECharacteristic* rxChar = nullptr;

bool bleConnected = false;
bool wifiConnectRequest = false;

// ====================================================
// STATE
// ====================================================

String currentCommand = "";

bool frontBlocked = false;
bool rearBlocked = false;
bool motionActive = false;

unsigned long motionStart = 0;
unsigned long motionTime = 0;

unsigned long lastWiFiAttempt = 0;
unsigned long lastMQTTAttempt = 0;
unsigned long lastSensorRead = 0;
const unsigned long BLE_WIFI_RETRY = 5000;

// ====================================================
// COMMAND EXECUTION BRIDGE
// ====================================================
void executeCarCommand(String command);
void publishCommandFeedback(const String& message);

// ====================================================
// HTTP API (same command vocabulary as MQTT)
// ====================================================
void handleHttpStatus()
{
    String json = "{\"device\":\"" + String(DEVICE_ID) + "\",\"wifi\":" +
                  String(WiFi.status() == WL_CONNECTED ? "true" : "false") +
                  ",\"mqtt\":" + String(mqtt.connected() ? "true" : "false") +
                  ",\"ip\":\"" + WiFi.localIP().toString() +
                  "\",\"command\":\"" + currentCommand + "\"}";
    httpServer.send(200, "application/json", json);
}

void handleHttpCarCommand()
{
    String command = httpServer.hasArg("command") ? httpServer.arg("command") : "";
    command.trim();
    if (command == "") {
        httpServer.send(400, "application/json", "{\"success\":false,\"error\":\"command required\"}");
        return;
    }
    executeCarCommand(command);
    httpServer.send(200, "application/json", "{\"success\":true,\"command\":\"" + command + "\"}");
}

void setupHttpServer()
{
    httpServer.on("/api/status", HTTP_GET, handleHttpStatus);
    httpServer.on("/api/car/command", HTTP_POST, handleHttpCarCommand);
    httpServer.on("/api/car/command", HTTP_GET, handleHttpCarCommand);
    httpServer.begin();
    Serial.println("[HTTP] ESP32-C6 Robot Car API listening on port 80");
}

void processSerialCommands()
{
    if (!Serial.available()) return;
    String command = Serial.readStringUntil('\n');
    command.trim();
    if (command.length() == 0) return;
    Serial.print("[SERIAL RX] ");
    Serial.println(command);
    if (command.equalsIgnoreCase("STATUS")) {
        Serial.println("[SERIAL STATUS] DEVICE=" + String(DEVICE_ID) +
                       " WIFI=" + String(WiFi.status() == WL_CONNECTED ? "ONLINE" : "OFFLINE") +
                       " MQTT=" + String(mqtt.connected() ? "ONLINE" : "OFFLINE") +
                       " CMD=" + currentCommand);
        return;
    }
    executeCarCommand(command);
}

// ====================================================
// MOTOR CONTROL
// ====================================================

void stopRobot()
{
    digitalWrite(IN1, LOW);
    digitalWrite(IN2, LOW);
    digitalWrite(IN3, LOW);
    digitalWrite(IN4, LOW);

    motionActive = false;
}

void forward()
{
    digitalWrite(IN1, HIGH);
    digitalWrite(IN2, LOW);
    digitalWrite(IN3, HIGH);
    digitalWrite(IN4, LOW);
}

void backward()
{
    digitalWrite(IN1, LOW);
    digitalWrite(IN2, HIGH);
    digitalWrite(IN3, LOW);
    digitalWrite(IN4, HIGH);
}

void leftTurn()
{
    digitalWrite(IN1, LOW);
    digitalWrite(IN2, HIGH);
    digitalWrite(IN3, HIGH);
    digitalWrite(IN4, LOW);
}

void rightTurn()
{
    digitalWrite(IN1, HIGH);
    digitalWrite(IN2, LOW);
    digitalWrite(IN3, LOW);
    digitalWrite(IN4, HIGH);
}


// ====================================================
// MQTT PUBLISH
// ====================================================

void publishACK(const char* msg)
{
    Serial.print("[ACK] ");
    Serial.println(msg);
    if (!mqtt.connected()) return;
    mqtt.publish(ACK_TOPIC, msg);

    Serial.print("[ACK] ");
    Serial.println(msg);
}

void publishStatus(const char* msg)
{
    Serial.print("[STATUS] ");
    Serial.println(msg);
    if (!mqtt.connected()) return;
    mqtt.publish(STATUS_TOPIC, msg);

    Serial.print("[STATUS] ");
    Serial.println(msg);
}

// ====================================================
// WIFI
// ====================================================
void sendBLE(String msg)
{
    if(!bleConnected)
        return;

    txChar->setValue(msg);

    txChar->notify();
}
void printWiFiDetails()
{
    Serial.println();

    Serial.print("SSID : ");

    Serial.println(wifiSSID);

    Serial.print("PASS : ");

    Serial.println(wifiPASS);

    Serial.print("SSID Length : ");

    Serial.println(wifiSSID.length());

    Serial.print("PASS Length : ");

    Serial.println(wifiPASS.length());

    Serial.println();
}
void saveCredentials()
{
    prefs.begin("wifi", false);

    prefs.putString("ssid", wifiSSID);

    prefs.putString("pass", wifiPASS);

    prefs.end();

    Serial.println("Credentials Saved");

    sendBLE("Credentials Saved");
}
bool loadCredentials()
{
    prefs.begin("wifi", true);

    wifiSSID = prefs.getString("ssid", "");

    wifiPASS = prefs.getString("pass", "");

    prefs.end();

    if(wifiSSID=="")
        return false;

    Serial.println("Stored Credentials Found");

    printWiFiDetails();

    return true;
}
class ServerCallbacks : public NimBLEServerCallbacks
{
    void onConnect(NimBLEServer* pServer, NimBLEConnInfo& connInfo) override
    {
        bleConnected = true;

        Serial.println();
        Serial.println("================================");
        Serial.println("BLE CLIENT CONNECTED");
        Serial.println("================================");

        sendBLE("Connected");
    }

    void onDisconnect(NimBLEServer* pServer,
                      NimBLEConnInfo& connInfo,
                      int reason) override
    {
        bleConnected = false;

        Serial.println();
        Serial.println("BLE CLIENT DISCONNECTED");

        NimBLEDevice::startAdvertising();

        Serial.println("Advertising Restarted");
    }
};
class RXCallbacks : public NimBLECharacteristicCallbacks
{
    void onWrite(NimBLECharacteristic *pCharacteristic,
                 NimBLEConnInfo& connInfo) override
    {
        std::string value = pCharacteristic->getValue();

        if(value.empty())
            return;

        String data = String(value.c_str());

        data.trim();

        Serial.println();
        Serial.println("Received:");

        Serial.println(data);

        int comma = data.indexOf(',');

        if(comma==-1)
        {
            sendBLE("Invalid Format");

            return;
        }

        wifiSSID = data.substring(0,comma);

        wifiPASS = data.substring(comma+1);

        wifiSSID.trim();

        wifiPASS.trim();

        printWiFiDetails();

        wifiConnectRequest = true;

        sendBLE("Credentials Received");
    }
};
void setupBLE()
{
    NimBLEDevice::init(DEVICE_NAME);

    server = NimBLEDevice::createServer();

    server->setCallbacks(new ServerCallbacks());

    NimBLEService *service =
        server->createService(SERVICE_UUID);

      txChar = service->createCharacteristic(
          TX_UUID,
          NIMBLE_PROPERTY::NOTIFY
        );

      rxChar = service->createCharacteristic(
          RX_UUID,
          NIMBLE_PROPERTY::WRITE |
          NIMBLE_PROPERTY::WRITE_NR
        );


    rxChar->setCallbacks(new RXCallbacks());

    service->start();

    NimBLEAdvertising *advertising =
        NimBLEDevice::getAdvertising();

    advertising->addServiceUUID(SERVICE_UUID);

    NimBLEDevice::startAdvertising();

    Serial.println();

    Serial.println("BLE READY");

    Serial.print("Device Name : ");

    Serial.println(DEVICE_NAME);
}
void startWiFi()
{
    Serial.println();
    Serial.println("[WIFI] Connecting...");
    Serial.print("[WIFI] SSID: ");
    if (wifiSSID == "")
      return;

    Serial.println(wifiSSID);

    WiFi.mode(WIFI_STA);

    WiFi.begin(
      wifiSSID.c_str(),
      wifiPASS.c_str()
    );

    lastWiFiAttempt = millis();
}

void updateWiFi()
{
    if (WiFi.status() == WL_CONNECTED)
        return;

    if (millis() - lastWiFiAttempt < WIFI_RETRY)
        return;

    Serial.println("[WIFI] Reconnecting...");

    WiFi.disconnect();
    if (wifiSSID == "")
    return;

    WiFi.disconnect();

    WiFi.begin(
    wifiSSID.c_str(),
    wifiPASS.c_str()
    );

lastWiFiAttempt = millis();

    lastWiFiAttempt = millis();
}

// ====================================================
// MQTT CONNECTION
// ====================================================

void connectMQTT()
{
    if (WiFi.status() != WL_CONNECTED)
        return;

    if (mqtt.connected())
        return;

    if (millis() - lastMQTTAttempt < MQTT_RETRY)
        return;

    lastMQTTAttempt = millis();

    Serial.println();
    Serial.println("[MQTT] Connecting...");
    Serial.print("[MQTT] Broker: ");
    Serial.print(MQTT_SERVER);
    Serial.print(":");
    Serial.println(MQTT_PORT);

    String clientID = "ESP32_";
    clientID += DEVICE_ID;

    if (mqtt.connect(
            clientID.c_str(),
            nullptr,
            nullptr,
            STATUS_TOPIC,
            1,
            true,
            "OFFLINE"))
    {
        Serial.println("[MQTT] Connected");

        mqtt.subscribe(CONTROL_TOPIC);

        Serial.print("[MQTT] Subscribed: ");
        Serial.println(CONTROL_TOPIC);

        mqtt.publish(
            STATUS_TOPIC,
            "ONLINE",
            true
        );

        Serial.println("[MQTT] ONLINE");
    }
    else
    {
        Serial.print("[MQTT] Failed. State: ");
        Serial.println(mqtt.state());
    }
}

// ====================================================
// MQTT COMMAND CALLBACK
// ====================================================

void mqttCallback(
    char* topic,
    byte* payload,
    unsigned int length)
{
    if (strcmp(topic, CONTROL_TOPIC) != 0) return;
    String command; command.reserve(length);
    for (unsigned int i = 0; i < length; i++) command += (char)payload[i];
    command.trim();
    executeCarCommand(command);
}

void executeCarCommand(String command)
{
    command.trim();

    Serial.println();
    Serial.println("================================");
    Serial.println("[COMMAND] RECEIVED");
    Serial.print("[COMMAND] ");
    Serial.println(command);
    Serial.println("================================");

    // Ignore repeated timed command
    if (motionActive && command == currentCommand)
    {
        Serial.println("[MQTT] Duplicate ignored");
        return;
    }

    currentCommand = command;

    // ==================================================
    // STOP
    // ==================================================

    if (command == "LIFTCARSTOP")
    {
        stopRobot();

        currentCommand = "";

        publishACK("CAR STOP EXECUTED");
        publishStatus("CAR STOP EXECUTED");

        return;
    }

    // ==================================================
    // FORWARD
    // ==================================================

    if (command == "LIFTCARFORWARD")
    {
        if (frontBlocked)
        {
            stopRobot();

            publishACK("FRONT BLOCKED");
            publishStatus("FRONT BLOCKED");

            return;
        }

        forward();

        publishACK("CAR FORWARD EXECUTED");
        publishStatus("CAR FORWARD EXECUTED");

        return;
    }

    // ==================================================
    // BACKWARD
    // ==================================================

    if (command == "LIFTCARBACKWARD")
    {
        if (rearBlocked)
        {
            stopRobot();

            publishACK("REAR BLOCKED");
            publishStatus("REAR BLOCKED");

            return;
        }

        backward();

        publishACK("CAR BACKWARD EXECUTED");
        publishStatus("CAR BACKWARD EXECUTED");

        return;
    }

    // ==================================================
    // LEFT / LEFT 360
    // ==================================================

    if (command == "LIFTCARLEFT" ||
        command == "LIFTCARLEFT360")
    {
        // LEFT is independently controllable.
        // A FRONT obstacle must not block a LEFT turn.
        leftTurn();

        motionActive = true;
        motionStart = millis();

        motionTime =
            command == "LIFTCARLEFT360"
            ? TURN360_TIME
            : TURN_TIME;

        publishACK(
            command == "LIFTCARLEFT360"
            ? "CAR LEFT360 EXECUTED"
            : "CAR LEFT EXECUTED"
        );

        publishStatus(
            command == "LIFTCARLEFT360"
            ? "CAR LEFT360 EXECUTED"
            : "CAR LEFT EXECUTED"
        );

        return;
    }

    // ==================================================
    // RIGHT / RIGHT 360
    // ==================================================

    if (command == "LIFTCARRIGHT" ||
        command == "LIFTCARRIGHT360")
    {
        // RIGHT is independently controllable.
        // A FRONT obstacle must not block a RIGHT turn.
        rightTurn();

        motionActive = true;
        motionStart = millis();

        motionTime =
            command == "LIFTCARRIGHT360"
            ? TURN360_TIME
            : TURN_TIME;

        publishACK(
            command == "LIFTCARRIGHT360"
            ? "CAR RIGHT360 EXECUTED"
            : "CAR RIGHT EXECUTED"
        );

        publishStatus(
            command == "LIFTCARRIGHT360"
            ? "CAR RIGHT360 EXECUTED"
            : "CAR RIGHT EXECUTED"
        );

        return;
    }

    // ==================================================
    // INVALID COMMAND
    // ==================================================

    stopRobot();

    currentCommand = "";

    publishACK("INVALID COMMAND");
    publishStatus("INVALID COMMAND");
}

// ====================================================
// ULTRASONIC
// ====================================================

float readDistance(uint8_t trig, uint8_t echo)
{
    digitalWrite(trig, LOW);
    delayMicroseconds(2);

    digitalWrite(trig, HIGH);
    delayMicroseconds(10);

    digitalWrite(trig, LOW);

    unsigned long duration =
        pulseIn(echo, HIGH, 12000);

    if (duration == 0)
        return 400.0;

    return duration * 0.0343f / 2.0f;
}

// ====================================================
// OBSTACLE MONITOR
// ====================================================

void checkObstacles()
{
    if (millis() - lastSensorRead < SENSOR_INTERVAL)
        return;

    lastSensorRead = millis();

    float front =
        readDistance(FRONT_TRIG, FRONT_ECHO);

    float rear =
        readDistance(REAR_TRIG, REAR_ECHO);

    bool newFront =
        front <= OBSTACLE_LIMIT;

    bool newRear =
        rear <= OBSTACLE_LIMIT;

    // Front obstacle: only block/stop FORWARD movement.
    // LEFT, RIGHT and BACKWARD remain available so the operator
    // can steer around the obstacle.
    if (newFront &&
        !frontBlocked &&
        currentCommand == "LIFTCARFORWARD")
    {
        stopRobot();

        publishACK("FRONT OBSTACLE");
        publishStatus("FRONT OBSTACLE");

        Serial.print("[OBSTACLE] FRONT: ");
        Serial.print(front);
        Serial.println(" cm");
    }

    // Rear obstacle: only block/stop BACKWARD movement.
    // LEFT, RIGHT and FORWARD remain available.
    if (newRear &&
        !rearBlocked &&
        currentCommand == "LIFTCARBACKWARD")
    {
        stopRobot();

        publishACK("REAR OBSTACLE");
        publishStatus("REAR OBSTACLE");

        Serial.print("[OBSTACLE] REAR: ");
        Serial.print(rear);
        Serial.println(" cm");
    }

    frontBlocked = newFront;
    rearBlocked = newRear;
}

// ====================================================
// TIMED MOVEMENT
// ====================================================

void updateMotion()
{
    if (!motionActive)
        return;

    if (millis() - motionStart >= motionTime)
    {
        stopRobot();

        currentCommand = "";

        Serial.println("[MOTION] Complete");

        publishStatus("MOTION COMPLETE");
    }
}

// ====================================================
// SETUP
// ====================================================

void setup()
{
    Serial.begin(115200);

    delay(1000);

    Serial.println();
    Serial.println("======================================");
    Serial.println("   SYNAPTIMESH ESP32-C6 SLAVE");
    Serial.println("======================================");

    // Motor pins
    pinMode(IN1, OUTPUT);
    pinMode(IN2, OUTPUT);
    pinMode(IN3, OUTPUT);
    pinMode(IN4, OUTPUT);

    stopRobot();

    // Ultrasonic pins
    pinMode(FRONT_TRIG, OUTPUT);
    pinMode(FRONT_ECHO, INPUT);

    pinMode(REAR_TRIG, OUTPUT);
    pinMode(REAR_ECHO, INPUT);

    Serial.println("[SYSTEM] GPIO Ready");

    // MQTT
    setupBLE();

    if(loadCredentials())
    {
      startWiFi();
    }
    else
    {
      Serial.println("Waiting for BLE Credentials...");
    }

    mqtt.setServer(MQTT_SERVER, MQTT_PORT);
    mqtt.setCallback(mqttCallback);
    mqtt.setBufferSize(256);
    setupHttpServer();

    Serial.println("[SYSTEM] READY");
}

// ====================================================
// LOOP
// ====================================================

void loop()
{
    if(wifiConnectRequest)
    {
      wifiConnectRequest = false;

      startWiFi();
    }

    if (WiFi.status() == WL_CONNECTED)
    {
        if (!mqtt.connected())
            connectMQTT();

        if (mqtt.connected())
            mqtt.loop();
    }

    checkObstacles();

    updateMotion();
    processSerialCommands();
    httpServer.handleClient();

    delay(2);
}