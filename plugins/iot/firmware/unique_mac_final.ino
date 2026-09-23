#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <Preferences.h>
#include <HTTPClient.h>
#include <HTTPUpdate.h>
#define FIRMWARE_VERSION "1.0.0"
Preferences preferences;
// final working esp32 code 16-06-26 4pm

// ================= WIFI =================

String wifiSSID = "";
String wifiPassword = "";

bool wifiConfigured = false;
bool wifiConnectedOnce = false;
bool bleModeStarted = false;

const char* mqtt_server = "broker.hivemq.com";
String OTA_URL =
"http://172.18.1.102:5000/firmware.bin";  //host server ip 

#define SERVICE_UUID        "12345678-1234-1234-1234-123456789abc"

#define CHARACTERISTIC_UUID "87654321-4321-4321-4321-cba987654321"

String receivedData = "";



// ================= MQTT =================

WiFiClient espClient;

PubSubClient client(espClient);
//new 13/07
String DEVICE_ID = "";

String ACTION_TOPIC = "";
String STATUS_TOPIC = "";
String ACK_TOPIC = "";




// String ACTION_TOPIC =
// "iot/smarttank/actions";

// String STATUS_TOPIC =
// "iot/smarttank/status";

// String ACK_TOPIC =
// "iot/smarttank/system_ack";


// NEW 15 NYT===================================================NEW-NYT=======================================================
#define LIGHT_LED 13
#define FAN_LED   12
#define PUMP_LED  14
#define WIFI_RESET_BUTTON 27  // wifi reset
// ================= VARIABLES =================

String currentCommand =
"Neutral";

unsigned long lastPublish = 0;


 // new 10/06
String lastCommandId = "";
// modified 13/07
void executeCommand(
    String cmd,
    String commandId
){
   
//=================================================================NEW-15-NYT==========================================================================

if(cmd == "Push")          // Light ON
{
    digitalWrite(LIGHT_LED, HIGH);
}

else if(cmd == "Pull")     // Light OFF
{
    digitalWrite(LIGHT_LED, LOW);
}

else if(cmd == "Rotate")   // Fan ON
{
    digitalWrite(FAN_LED, HIGH);
}

else if(cmd == "Lift")     // Fan OFF
{
    digitalWrite(FAN_LED, LOW);
}

else if(cmd == "Left")     // Pump ON
{
    digitalWrite(PUMP_LED, HIGH);
}

else if(cmd == "Right")    // Pump OFF
{
    digitalWrite(PUMP_LED, LOW);
}

//change   new 17



StaticJsonDocument<300> ackDoc;


// Device information 13/07
ackDoc["device_id"] = DEVICE_ID;
ackDoc["mac"] = WiFi.macAddress();

// Command details
ackDoc["command_id"] = commandId;
ackDoc["command"] = cmd;


// Result
ackDoc["result"] = "SUCCESS";


// Current device state
ackDoc["light"] =
digitalRead(LIGHT_LED) ? "ON" : "OFF";


ackDoc["fan"] =
digitalRead(FAN_LED) ? "ON" : "OFF";


ackDoc["pump"] =
digitalRead(PUMP_LED) ? "ON" : "OFF";


// Device time (uptime)
unsigned long seconds =
millis()/1000;

String deviceTime =
String(seconds/3600) + ":" +
String((seconds%3600)/60) + ":" +
String(seconds%60);


ackDoc["device_time"] = deviceTime;

ackDoc["firmware"] =
FIRMWARE_VERSION;

char ackBuffer[300];


serializeJson(
    ackDoc,
    ackBuffer
);


client.publish(
    ACK_TOPIC.c_str(),
    ackBuffer
);
}
// NEW 

class WiFiCallback : public BLECharacteristicCallbacks {

  void onWrite(BLECharacteristic *pCharacteristic) {

    String chunk = pCharacteristic->getValue();

    if (chunk.length() > 0) {

      receivedData += chunk;

      int commaIndex =
      receivedData.indexOf(',');

      if (commaIndex > 0) {

        wifiSSID =
        receivedData.substring(
          0,
          commaIndex
        );

        wifiPassword =
        receivedData.substring(
          commaIndex + 1
        );

        wifiSSID.trim();
        wifiPassword.trim();

        Serial.println();
        Serial.println("WiFi Data Received");

        Serial.print("SSID: ");
        Serial.println(wifiSSID);

        Serial.print("PASSWORD: ");
        Serial.println(wifiPassword);

        wifiConfigured = true;
        wifiConnectedOnce = false;
        bleModeStarted = false;
        preferences.begin("wifi", false);

        preferences.putString("ssid", wifiSSID);
        preferences.putString("pass", wifiPassword);

        preferences.end();

        Serial.println("WiFi Credentials Saved");
        
        WiFi.disconnect(true);
        receivedData = "";
      }
    }
  }
};


// ================= WIFI new preference funtion=================
void loadWiFiCredentials()
{
    preferences.begin("wifi", true);

    wifiSSID = preferences.getString("ssid", "");
    wifiPassword = preferences.getString("pass", "");

    preferences.end();

    if(wifiSSID.length() > 0)
    {
        wifiConfigured = true;

        Serial.println("Saved WiFi Credentials Found");
        Serial.print("SSID: ");
        Serial.println(wifiSSID);
    }
}
// modified 13/07
void setup_wifi()
{
    Serial.println("Connecting WiFi...");

    WiFi.begin(
        wifiSSID.c_str(),
        wifiPassword.c_str()
    );

    int attempts = 0;

    while(
        WiFi.status() != WL_CONNECTED &&
        attempts < 20
    )
    {
        delay(500);
        Serial.print(".");
        attempts++;
    }

    if(WiFi.status() == WL_CONNECTED)
{
    Serial.println();
    Serial.println("Connected");
    Serial.println(WiFi.localIP());

    DEVICE_ID = WiFi.macAddress();
    DEVICE_ID.replace(":", "_");

    Serial.print("Device ID : ");
    Serial.println(DEVICE_ID);

    ACTION_TOPIC = "iot/device/" + DEVICE_ID + "/action";
    STATUS_TOPIC = "iot/device/" + DEVICE_ID + "/status";
    ACK_TOPIC = "iot/device/" + DEVICE_ID + "/ack";
    // Print Topics (Paste here)
    Serial.println("===== MQTT Topics =====");
    Serial.print("ACTION : ");
    Serial.println(ACTION_TOPIC);

    Serial.print("STATUS : ");
    Serial.println(STATUS_TOPIC);

    Serial.print("ACK    : ");
    Serial.println(ACK_TOPIC);
    Serial.println("=======================");
}
    
}
 // ota function
 void performOTA()
{
    if(WiFi.status() != WL_CONNECTED)
    {
        Serial.println("WiFi Not Connected");
        return;
    }

    Serial.println("Starting OTA Update...");

    WiFiClient otaClient;

    t_httpUpdate_return ret =
    httpUpdate.update(
        otaClient,
        OTA_URL
    );

    switch(ret)
    {
        case HTTP_UPDATE_FAILED:

            Serial.printf(
                "Update Failed (%d): %\n",
                httpUpdate.getLastError(),
                httpUpdate.getLastErrorString().c_str()
            );

            break;

        case HTTP_UPDATE_NO_UPDATES:

            Serial.println(
                "No Updates Available"
            );

            break;

        case HTTP_UPDATE_OK:

            Serial.println(
                "Update Successful"
            );

            break;
    }
}

// ================= CALLBACK =================

void callback(

char* topic,

byte* payload,

unsigned int length

){

String msg="";

for(

int i=0;

i<length;

i++

){

msg +=

(char)

payload[i];

}
// modified 13/07

Serial.print("Received Topic: ");
Serial.println(topic);

Serial.print("Payload: ");
Serial.println(msg);



Serial.println(
msg
);

StaticJsonDocument<200> doc;

DeserializationError error =

deserializeJson(

doc,

msg

);

if(error){

Serial.println(
"JSON Error"
);

return;

}

String command =
doc["command"] | "";
// OTA commad detection
if(command == "OTA_UPDATE")
{
    performOTA();
    return;
}

String commandId =
doc["command_id"] | "";

if(commandId == lastCommandId)
{
    Serial.println(
        "Duplicate Command Ignored"
    );

    return;
}

lastCommandId = commandId;

executeCommand(
    command,
    commandId
);

}

// ================= RECONNECT =================

void reconnect(){

while(!client.connected()){

Serial.println("Trying MQTT Connection...");

String id =
"ESP32-" +
String(random(9999));

if(
client.connect(id.c_str())
){

Serial.println("MQTT Connected");

client.subscribe(
ACTION_TOPIC.c_str()
);
// modified 13/07
Serial.print("Subscribed to: ");
Serial.println(ACTION_TOPIC);

}
else{

Serial.print("MQTT Failed, rc=");
Serial.println(client.state());

delay(2000);

}

}

}

// ================= SETUP =================
void setupBLE(){

BLEDevice::init(
"IMTIYAZ_ESP32"
);

BLEServer *pServer =
BLEDevice::createServer();

BLEService *pService =
pServer->createService(
SERVICE_UUID
);

BLECharacteristic *pCharacteristic =
pService->createCharacteristic(
CHARACTERISTIC_UUID,
BLECharacteristic::PROPERTY_WRITE
);

pCharacteristic->setCallbacks(
new WiFiCallback()
);

pService->start();

BLEAdvertising *pAdvertising =
BLEDevice::getAdvertising();

pAdvertising->addServiceUUID(
SERVICE_UUID
);

pAdvertising->start();

Serial.println("BLE Ready");
Serial.println("Device Name: IMTIYAZ_ESP32");
Serial.println("Waiting for WiFi Credentials...");
}

//----------------------------------------------------up new--

void setup(){

Serial.begin(
115200
);

pinMode(
LIGHT_LED,
OUTPUT
);

pinMode(
FAN_LED,
OUTPUT
);

pinMode(
PUMP_LED,
OUTPUT
);

pinMode(
    WIFI_RESET_BUTTON,
    INPUT_PULLUP
);


loadWiFiCredentials();

if(wifiConfigured)
{
    setup_wifi();
    wifiConnectedOnce = true;
}
//new
else
{
    setupBLE();
}


client.setServer(

mqtt_server,

1883

);

client.setCallback(

callback

);

}

// ================= LOOP =================

void loop(){
//new reset=====================
if(
    digitalRead(WIFI_RESET_BUTTON) == LOW &&
    !bleModeStarted
)
{
    Serial.println(
        "WiFi Change Mode Activated"
    );

    //WiFi.disconnect(true);

    //delay(1000);

    setupBLE();

    bleModeStarted = true;
}


static bool mqttConfigured = false;


if(
wifiConfigured &&
!wifiConnectedOnce
){

WiFi.disconnect(true);

delay(1000);

WiFi.mode(WIFI_STA);

setup_wifi();
wifiConnectedOnce = true;

if(!mqttConfigured){

client.setServer(
mqtt_server,
1883
);

client.setCallback(
callback
);

mqttConfigured = true;
}

}


if(
WiFi.status()==WL_CONNECTED
){

if(
!client.connected()
){
reconnect();
}
// modified 13/07
client.loop();

}

if(millis() - lastPublish > 2000)
{
    lastPublish = millis();

    StaticJsonDocument<300> doc;
    
    doc["device_id"] = DEVICE_ID;
    doc["mac"] = WiFi.macAddress();
    doc["system"] = "ONLINE";

    doc["light"] =
        digitalRead(LIGHT_LED) ? "ON" : "OFF";

    doc["fan"] =
        digitalRead(FAN_LED) ? "ON" : "OFF";

    doc["pump"] =
        digitalRead(PUMP_LED) ? "ON" : "OFF";

    char buffer[300];

    serializeJson(doc, buffer);

    if(client.connected())
    {
        client.publish(
            STATUS_TOPIC.c_str(),
            buffer
        );
    }
}
}