/**
 * server.js
 * Master IoT Hub Server for Emotiv EPOC BCI + ESP32 Actuator Controller.
 */

require('dotenv').config();
const http = require('http');
const path = require('path');
const express = require('express');
const cors = require('cors');
const WebSocket = require('ws');

const BCIStateMachine = require('./state_machine');
const CortexBridge = require('./cortex_bridge');
const ESP32Connector = require('./esp32_connector');

const PORT = process.env.PORT || 3000;
const app = express();

app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const server = http.createServer(app);
const wss = new WebSocket.Server({ server });

// Instantiate Core Engines
const stateMachine = new BCIStateMachine({
  powerThreshold: parseFloat(process.env.POWER_THRESHOLD) || 0.35,
  debounceMs: parseInt(process.env.DEBOUNCE_MS, 10) || 900,
  autoReturnTimeoutMs: parseInt(process.env.AUTO_RETURN_TIMEOUT_MS, 10) || 12000
});

const cortexBridge = new CortexBridge({
  url: process.env.CORTEX_URL || 'wss://localhost:6868',
  clientId: process.env.CORTEX_CLIENT_ID || '',
  clientSecret: process.env.CORTEX_CLIENT_SECRET || '',
  license: process.env.CORTEX_LICENSE || '',
  debit: 1
});

const esp32Connector = new ESP32Connector({
  mode: process.env.ESP32_MODE || 'wifi',
  esp32Ip: process.env.ESP32_IP || '192.168.1.100',
  esp32Port: parseInt(process.env.ESP32_PORT, 10) || 80,
  serialPortPath: process.env.ESP32_SERIAL_PORT || 'COM3',
  baudRate: parseInt(process.env.ESP32_BAUD_RATE, 10) || 115200
});

// Broadcast Helper to all connected Web Dashboard clients
function broadcast(type, payload) {
  const message = JSON.stringify({ type, payload, timestamp: Date.now() });
  wss.clients.forEach((client) => {
    if (client.readyState === WebSocket.OPEN && client.isDashboard) {
      client.send(message);
    }
  });
}

// ----------------------------------------------------
// Event Wiring & Core Pipeline
// ----------------------------------------------------

// 1. Emotiv Cortex Stream -> BCI State Machine
cortexBridge.on('com', (data) => {
  // data: { action: 'push', power: 0.82, time, sid }
  stateMachine.processMentalCommand(data.action, data.power, false);
});

cortexBridge.on('status_change', (status) => {
  broadcast('cortex_status', cortexBridge.getStatus());
});

cortexBridge.on('log', (logEntry) => {
  broadcast('log', { source: 'CORTEX', ...logEntry });
});

// 2. State Machine -> ESP32 Hardware + Web Dashboard
stateMachine.on('telemetry', (telemetry) => {
  broadcast('telemetry', telemetry);
});

stateMachine.on('transition', (transition) => {
  broadcast('state_transition', transition);
  broadcast('log', {
    source: 'STATE_MACHINE',
    level: 'info',
    message: `State Transition: [${transition.type}] State: ${transition.currentState}, Target: ${transition.selectedDevice || 'None'}`
  });
});

stateMachine.on('device_selected', (selection) => {
  broadcast('device_selected', selection);
  broadcast('log', {
    source: 'STATE_MACHINE',
    level: 'success',
    message: selection.message
  });
});

stateMachine.on('state_reset', (resetInfo) => {
  broadcast('state_reset', resetInfo);
  broadcast('log', {
    source: 'STATE_MACHINE',
    level: 'warn',
    message: resetInfo.message
  });
});

stateMachine.on('actuator_command', async (cmd) => {
  broadcast('actuator_updated', cmd);
  broadcast('log', {
    source: 'ACTUATOR',
    level: 'success',
    message: `Actuator Action: ${cmd.device.toUpperCase()} is now ${cmd.state} (Triggered by '${cmd.triggerAction}')`
  });

  // Dispatch to ESP32 hardware
  await esp32Connector.sendCommand(cmd.device, cmd.state);
});

stateMachine.on('command_filtered', (filterInfo) => {
  broadcast('command_filtered', filterInfo);
});

stateMachine.on('info', (info) => {
  broadcast('log', { source: 'STATE_MACHINE', level: 'info', message: info.message });
});

// 3. ESP32 Connector Events
esp32Connector.on('log', (logEntry) => {
  broadcast('log', { source: 'ESP32', ...logEntry });
});

esp32Connector.on('status_change', (status) => {
  broadcast('esp32_status', esp32Connector.getConfig());
});

esp32Connector.on('states_sync', (states) => {
  // Synchronize state machine if ESP32 reported external change
  Object.keys(states).forEach((k) => {
    if (stateMachine.deviceStates[k]) {
      stateMachine.deviceStates[k] = states[k];
    }
  });
  broadcast('state_transition', stateMachine.getFullState());
});

// ----------------------------------------------------
// WebSocket Server Connection Handler
// ----------------------------------------------------
wss.on('connection', (ws, req) => {
  const url = req.url;

  // Check if it's an ESP32 hardware direct WebSocket connection
  if (url === '/esp32') {
    ws.isDashboard = false;
    esp32Connector.registerWebSocketClient(ws);
    return;
  }

  // Otherwise, it's a Web Dashboard UI client
  ws.isDashboard = true;

  // Send Initial Snapshot
  const initialSnapshot = {
    stateMachine: stateMachine.getFullState(),
    cortex: cortexBridge.getStatus(),
    esp32: esp32Connector.getConfig()
  };
  ws.send(JSON.stringify({ type: 'init_snapshot', payload: initialSnapshot }));

  ws.on('message', (message) => {
    try {
      const data = JSON.parse(message.toString());
      if (data.type === 'simulate_command') {
        stateMachine.processMentalCommand(data.action, data.power, true);
      } else if (data.type === 'manual_override') {
        stateMachine.manualOverride(data.device, data.state);
      } else if (data.type === 'return_selection') {
        stateMachine.returnToSelectionMode('manual_request');
      }
    } catch (e) {}
  });
});

// ----------------------------------------------------
// REST API Endpoints
// ----------------------------------------------------

// Get full system status
app.get('/api/status', (req, res) => {
  res.json({
    stateMachine: stateMachine.getFullState(),
    cortex: cortexBridge.getStatus(),
    esp32: esp32Connector.getConfig()
  });
});

// Simulate Mental Command (e.g. { action: "push", power: 0.85 })
app.post('/api/simulate', (req, res) => {
  const { action, power } = req.body;
  if (!action) {
    return res.status(400).json({ error: 'Action parameter is required.' });
  }

  const result = stateMachine.processMentalCommand(action, power !== undefined ? power : 1.0, true);
  res.json({ success: true, result, currentState: stateMachine.getFullState() });
});

// Manual Device Override
app.post('/api/override', (req, res) => {
  const { device, state } = req.body;
  if (!device || !state) {
    return res.status(400).json({ error: 'Device and state are required.' });
  }

  const result = stateMachine.manualOverride(device, state);
  res.json({ success: true, result, deviceStates: stateMachine.deviceStates });
});

// Return to Selection Mode
app.post('/api/selection-mode', (req, res) => {
  stateMachine.returnToSelectionMode('api_request');
  res.json({ success: true, state: stateMachine.getFullState() });
});

// Update Configuration (Cortex credentials, Thresholds, ESP32)
app.post('/api/config', (req, res) => {
  const { cortex, stateMachineConfig, esp32 } = req.body;

  if (cortex) {
    cortexBridge.setCredentials(cortex);
  }
  if (stateMachineConfig) {
    stateMachine.updateConfig(stateMachineConfig);
  }
  if (esp32) {
    esp32Connector.updateConfig(esp32);
  }

  broadcast('cortex_status', cortexBridge.getStatus());
  broadcast('esp32_status', esp32Connector.getConfig());

  res.json({
    success: true,
    cortex: cortexBridge.getStatus(),
    stateMachine: stateMachine.getFullState(),
    esp32: esp32Connector.getConfig()
  });
});

// Connect to Emotiv Cortex
app.post('/api/cortex/connect', (req, res) => {
  if (req.body && (req.body.clientId || req.body.clientSecret)) {
    cortexBridge.setCredentials(req.body);
  }
  cortexBridge.connect();
  res.json({ success: true, message: 'Initiated connection to Emotiv Cortex.' });
});

// Disconnect from Emotiv Cortex
app.post('/api/cortex/disconnect', (req, res) => {
  cortexBridge.disconnect();
  res.json({ success: true, message: 'Disconnected from Emotiv Cortex.' });
});

// Ping ESP32
app.post('/api/esp32/ping', async (req, res) => {
  const pingResult = await esp32Connector.ping();
  res.json(pingResult);
});

// Start Master Server
server.listen(PORT, () => {
  console.log(`=======================================================`);
  console.log(`🧠 Emotiv BCI + ESP32 Master IoT Hub Server Running!`);
  console.log(`🌐 Web Dashboard: http://localhost:${PORT}`);
  console.log(`⚡ WebSocket Hub: ws://localhost:${PORT}`);
  console.log(`=======================================================`);
});
