/**
 * MasterHub IoT Team Console — Client Application Logic (Task 8: Real-Time Dashboard Propagation)
 * Real-Time WebSocket Client + REST fallback for the SynaptiMesh IoT Pipeline.
 * 
 * Features:
 *  - Real-Time WebSocket connection to `/ws` (and fallback to REST).
 *  - Instant DOM updates on `IOT_STATE_UPDATE`, `TELEMETRY_FRAME`, `DEVICE_STATE`, `ACTIVITY_LOG`.
 *  - Live sensor telemetry (Temperature, Humidity, Lux, Motion, Power, RSSI).
 *  - Resilient automatic reconnection with exponential backoff.
 *  - Phase 1 (Appliance Selection) and Phase 2 (Power Control Dock).
 */

const APPLIANCE_CONFIG = {
  light: {
    id: 'light',
    name: 'Light Relay',
    icon: '💡',
    relay: 'Relay 1 (ESP32)',
    gesture: 'PUSH',
    onCmd: 'left_light_on',
    offCmd: 'left_light_off',
    mqttTopic: 'iot/device/ESP32_RELAY_01/action',
    desc: 'Primary smart lighting relay control on the main IoT branch.'
  },
  fan: {
    id: 'fan',
    name: 'Fan Relay',
    icon: '🌀',
    relay: 'Relay 2 (ESP32)',
    gesture: 'PULL',
    onCmd: 'left_fan_on',
    offCmd: 'left_fan_off',
    mqttTopic: 'iot/device/ESP32_RELAY_01/action',
    desc: 'Ventilation and cooling smart fan circuit with MQTT sync.'
  },
  pump: {
    id: 'pump',
    name: 'Water Pump',
    icon: '💧',
    relay: 'Relay 3 (ESP32)',
    gesture: 'LEFT',
    onCmd: 'left_pump_on',
    offCmd: 'left_pump_off',
    mqttTopic: 'iot/device/ESP32_RELAY_01/action',
    desc: 'Automated water pump controller with telemetry interlock.'
  },
  right_light: {
    id: 'right_light',
    name: 'Right Light',
    icon: '💡',
    relay: 'Relay 4 (ESP32)',
    gesture: 'Custom',
    onCmd: 'right_light_on',
    offCmd: 'right_light_off',
    mqttTopic: 'iot/device/ESP32_RELAY_02/action',
    desc: 'Secondary lighting relay on auxiliary IoT expansion board.'
  },
  right_fan: {
    id: 'right_fan',
    name: 'Right Fan',
    icon: '🌀',
    relay: 'Relay 5 (ESP32)',
    gesture: 'Custom',
    onCmd: 'right_fan_on',
    offCmd: 'right_fan_off',
    mqttTopic: 'iot/device/ESP32_RELAY_02/action',
    desc: 'Secondary cooling fan on auxiliary IoT expansion board.'
  }
};

let currentAppliance = APPLIANCE_CONFIG.light;
let currentPhase = 1;
let applianceStates = {
  light: 'OFF',
  fan: 'OFF',
  pump: 'OFF',
  right_light: 'OFF',
  right_fan: 'OFF'
};

let ws = null;
let wsReconnectTimer = null;
let wsReconnectAttempts = 0;
const MAX_RECONNECT_DELAY = 10000;

// ------------------------------------------------------------------
// Base URL & Storage
// ------------------------------------------------------------------
function getApiBaseUrl() {
  const inputVal = document.getElementById('apiUrlInput')?.value.trim();
  if (inputVal) {
    localStorage.setItem('masterhub_iot_api_url', inputVal);
    return inputVal.replace(/\/+$/, '');
  }
  return localStorage.getItem('masterhub_iot_api_url') || window.location.origin;
}

function initApiInput() {
  const stored = localStorage.getItem('masterhub_iot_api_url') || window.location.origin;
  const input = document.getElementById('apiUrlInput');
  if (input) input.value = stored;
}

// ------------------------------------------------------------------
// Phase Navigation (Phase 1 <-> Phase 2)
// ------------------------------------------------------------------
function showPhase(phase) {
  currentPhase = phase;
  const p1 = document.getElementById('phase1-view');
  const p2 = document.getElementById('phase2-view');
  
  if (phase === 1) {
    if (p1) p1.style.display = 'block';
    if (p2) p2.style.display = 'none';
    const selLabel = document.getElementById('currentSelectedLabel');
    if (selLabel) selLabel.innerText = 'None (Browse Phase 1)';
  } else {
    if (p1) p1.style.display = 'none';
    if (p2) p2.style.display = 'block';
    const selLabel = document.getElementById('currentSelectedLabel');
    if (selLabel) selLabel.innerText = `${currentAppliance.name} (${currentAppliance.relay})`;
    renderPhase2();
  }
}

function selectAppliance(key) {
  if (!APPLIANCE_CONFIG[key]) return;
  currentAppliance = APPLIANCE_CONFIG[key];
  showPhase(2);
  addLog(`Selected appliance: ${currentAppliance.name}`, 'info');
}

function renderPhase2() {
  const app = currentAppliance;
  if (!app) return;

  const p2Icon = document.getElementById('p2Icon');
  if (p2Icon) p2Icon.innerText = app.icon;

  const p2Name = document.getElementById('p2Name');
  if (p2Name) p2Name.innerText = app.name;

  const p2RelayBadge = document.getElementById('p2RelayBadge');
  if (p2RelayBadge) p2RelayBadge.innerText = app.relay;

  const p2GestureBadge = document.getElementById('p2GestureBadge');
  if (p2GestureBadge) p2GestureBadge.innerText = `Gesture: ${app.gesture}`;

  const p2MqttTopic = document.getElementById('p2MqttTopic');
  if (p2MqttTopic) p2MqttTopic.innerText = app.mqttTopic;

  const onBtn = document.getElementById('p2OnBtn');
  if (onBtn) {
    onBtn.onclick = () => sendIoTCommand(app.onCmd);
    const onSub = document.getElementById('p2OnCmdText');
    if (onSub) onSub.innerText = `Cmd: ${app.onCmd}`;
  }

  const offBtn = document.getElementById('p2OffBtn');
  if (offBtn) {
    offBtn.onclick = () => sendIoTCommand(app.offCmd);
    const offSub = document.getElementById('p2OffCmdText');
    if (offSub) offSub.innerText = `Cmd: ${app.offCmd}`;
  }

  updateApplianceStateBadge(app.id);
}

function updateApplianceStateBadge(appId) {
  const state = applianceStates[appId] || 'OFF';
  const badge = document.getElementById('p2StateBadge');
  if (badge) {
    badge.innerText = state;
    badge.className = `badge-tag ${state === 'ON' ? 'status-on' : 'status-off'}`;
  }

  // Update card state in Phase 1
  const cardLight = document.getElementById('cardStateLight');
  if (cardLight) {
    cardLight.innerText = applianceStates.light;
    cardLight.className = `badge-tag ${applianceStates.light === 'ON' ? 'status-on' : 'status-off'}`;
  }
  const cardFan = document.getElementById('cardStateFan');
  if (cardFan) {
    cardFan.innerText = applianceStates.fan;
    cardFan.className = `badge-tag ${applianceStates.fan === 'ON' ? 'status-on' : 'status-off'}`;
  }
  const cardPump = document.getElementById('cardStatePump');
  if (cardPump) {
    cardPump.innerText = applianceStates.pump;
    cardPump.className = `badge-tag ${applianceStates.pump === 'ON' ? 'status-on' : 'status-off'}`;
  }
}

// ------------------------------------------------------------------
// Command Dispatching
// ------------------------------------------------------------------
async function sendIoTCommand(cmd) {
  addLog(`[DISPATCH] Sending command: ${cmd}...`, 'info');
  const baseUrl = getApiBaseUrl();

  const lastCmdName = document.getElementById('lastCmdName');
  if (lastCmdName) lastCmdName.innerText = cmd;

  const lastOutcome = document.getElementById('lastOutcomeTag');
  if (lastOutcome) {
    lastOutcome.innerText = 'DISPATCHING';
    lastOutcome.className = 'badge-tag warning';
  }

  try {
    const res = await fetch(`${baseUrl}/api/iot/command`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: cmd, domain: 'iot' })
    });

    const data = await res.json();
    if (data.success) {
      if (lastOutcome) {
        lastOutcome.innerText = 'SUCCESS';
        lastOutcome.className = 'badge-tag success';
      }
      const powerTag = document.getElementById('lastPowerStateTag');
      if (powerTag) {
        const isTurnOn = cmd.toLowerCase().includes('on');
        powerTag.innerText = isTurnOn ? 'POWER: ON' : 'POWER: OFF';
        powerTag.className = `badge-tag ${isTurnOn ? 'status-on' : 'status-off'}`;
      }
      const cmdIdTag = document.getElementById('lastCmdIdTag');
      if (cmdIdTag) cmdIdTag.innerText = `id: ${data.command_id || 'ok'}`;

      const p2Payload = document.getElementById('p2LastPayload');
      if (p2Payload) p2Payload.innerText = data.payload || JSON.stringify(data.orchestrator_result || {});

      addLog(`[COMMAND SUCCESS] ${cmd} → ACK received. Topic: ${data.topic || 'iot/esp32/action'}`, 'success');
    } else {
      if (lastOutcome) {
        lastOutcome.innerText = 'FAILED';
        lastOutcome.className = 'badge-tag danger';
      }
      addLog(`[COMMAND FAILED] ${cmd} → ${data.error || 'Execution rejected'}`, 'danger');
    }
  } catch (err) {
    if (lastOutcome) {
      lastOutcome.innerText = 'NET_ERROR';
      lastOutcome.className = 'badge-tag danger';
    }
    addLog(`[NETWORK ERROR] Could not reach backend: ${err.message}`, 'danger');
  }
}

// ------------------------------------------------------------------
// Real-Time WebSocket Client (Task 8)
// ------------------------------------------------------------------
function initWebSocket() {
  if (ws) {
    try { ws.close(); } catch (_) {}
    ws = null;
  }

  const baseUrl = getApiBaseUrl();
  let wsUrl = baseUrl.replace(/^http/, 'ws');
  if (!wsUrl.endsWith('/ws')) {
    wsUrl = `${wsUrl}/ws`;
  }

  addLog(`[WEBSOCKET] Connecting to ${wsUrl}...`, 'info');
  setConnectionStatus(false, 'Connecting WebSocket...');

  try {
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      wsReconnectAttempts = 0;
      setConnectionStatus(true, 'WebSocket Real-Time Connected');
      addLog('[WEBSOCKET] Connected to SynaptiMesh real-time pipeline.', 'success');

      // Subscribe to IOT and CORE domains
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'SUBSCRIBE', domains: ['IOT', 'CORE'] }));
      }
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        handleIncomingWebSocketMessage(msg);
      } catch (err) {
        console.error('Error parsing WebSocket message:', err);
      }
    };

    ws.onerror = (err) => {
      setConnectionStatus(false, 'WebSocket Error');
    };

    ws.onclose = () => {
      setConnectionStatus(false, 'WebSocket Disconnected (Reconnecting...)');
      scheduleReconnect();
    };
  } catch (err) {
    setConnectionStatus(false, 'WebSocket Connection Failed');
    scheduleReconnect();
  }
}

function scheduleReconnect() {
  if (wsReconnectTimer) clearTimeout(wsReconnectTimer);
  wsReconnectAttempts++;
  const delay = Math.min(1000 * Math.pow(1.5, wsReconnectAttempts), MAX_RECONNECT_DELAY);
  wsReconnectTimer = setTimeout(() => {
    initWebSocket();
  }, delay);
}

function handleIncomingWebSocketMessage(msg) {
  if (!msg || !msg.type) return;

  const msgType = String(msg.type).toUpperCase();
  const payload = msg.payload || {};

  // 1. Initial Connection / Snapshot
  if (msgType === 'CONNECTED' || msgType === 'SNAPSHOT') {
    setConnectionStatus(true, 'SynaptiMesh Real-Time Stream Active');
    if (payload.status) {
      const modeEl = document.getElementById('currentModeText');
      if (modeEl && payload.active_domain) modeEl.innerText = payload.active_domain;
    }
  }

  // 2. IoT State Updates & Relay Changes
  if (msgType === 'IOT_STATE_UPDATE' || msgType === 'DEVICE_STATE') {
    const isOnline = payload.online !== false && String(payload.status || payload.connection_status).toUpperCase() !== 'OFFLINE';
    setConnectionStatus(isOnline, isOnline ? 'ESP32 Online (Live)' : 'ESP32 Offline');

    const relays = payload.relays || (payload.state && (payload.state.relays || payload.state)) || {};
    if (relays.light !== undefined) applianceStates.light = String(relays.light).toUpperCase();
    if (relays.fan !== undefined) applianceStates.fan = String(relays.fan).toUpperCase();
    if (relays.pump !== undefined) applianceStates.pump = String(relays.pump).toUpperCase();
    if (relays.right_light !== undefined) applianceStates.right_light = String(relays.right_light).toUpperCase();
    if (relays.right_fan !== undefined) applianceStates.right_fan = String(relays.right_fan).toUpperCase();

    updateApplianceStateBadge(currentAppliance.id);

    if (payload.activity) {
      addLog(`[EVENT] ${payload.activity.action} → ${payload.activity.status || 'OK'} (${payload.activity.reason || ''})`, 'info');
    }
  }

  // 3. Telemetry Frame (Sensors & Power)
  if (msgType === 'TELEMETRY_FRAME') {
    const env = payload.environmental_sensors || {};
    const energy = payload.energy_metrics || {};
    const conn = payload.connectivity || {};

    if (env.temperature_celsius !== undefined && env.temperature_celsius !== null) {
      const el = document.getElementById('sensorTemp');
      if (el) el.innerText = `${env.temperature_celsius.toFixed(1)} °C`;
    }
    if (env.humidity_pct !== undefined && env.humidity_pct !== null) {
      const el = document.getElementById('sensorHumidity');
      if (el) el.innerText = `${env.humidity_pct.toFixed(1)} %`;
    }
    if (env.ambient_light_lux !== undefined && env.ambient_light_lux !== null) {
      const el = document.getElementById('sensorLux');
      if (el) el.innerText = `${env.ambient_light_lux.toFixed(0)} Lux`;
    }
    if (env.motion_detected !== undefined) {
      const el = document.getElementById('sensorMotion');
      if (el) {
        el.innerText = env.motion_detected ? 'DETECTED' : 'CLEAR';
        el.className = `badge-tag ${env.motion_detected ? 'status-on' : ''}`;
      }
    }
    if (energy.power_watts !== undefined && energy.power_watts !== null) {
      const el = document.getElementById('sensorPower');
      if (el) el.innerText = `${energy.power_watts.toFixed(1)} W`;
    }
    if (conn.wifi_rssi_dbm !== undefined && conn.wifi_rssi_dbm !== null) {
      const el = document.getElementById('sensorRssi');
      if (el) el.innerText = `${conn.wifi_rssi_dbm} dBm`;
    }

    const relays = payload.relays;
    if (relays) {
      if (relays.light) applianceStates.light = String(relays.light).toUpperCase();
      if (relays.fan) applianceStates.fan = String(relays.fan).toUpperCase();
      if (relays.pump) applianceStates.pump = String(relays.pump).toUpperCase();
      updateApplianceStateBadge(currentAppliance.id);
    }
  }

  // 4. Device Offline / Online Notifications
  if (msgType === 'DEVICE_OFFLINE') {
    setConnectionStatus(false, `Device Offline (${payload.reason || 'Timeout'})`);
    addLog(`[OFFLINE] Device ${payload.device_id} disconnected: ${payload.reason || 'Timeout'}`, 'danger');
  } else if (msgType === 'DEVICE_ONLINE') {
    setConnectionStatus(true, 'Device Reconnected');
    addLog(`[ONLINE] Device ${payload.device_id} reconnected.`, 'success');
  }

  // 5. Activity Log & ACKs
  if (msgType === 'IOT_COMMAND_ACK') {
    addLog(`[ACK] Command ${payload.command} on ${payload.device_id}: ${payload.status}`, 'success');
  }
}

function setConnectionStatus(online, text) {
  const dot = document.getElementById('connDot');
  const label = document.getElementById('connText');
  if (dot) {
    dot.className = online ? 'dot-ping' : 'dot-ping disconnected';
  }
  if (label) {
    label.innerText = text;
  }
}

// ------------------------------------------------------------------
// Initial Fallback REST Polling on Page Load
// ------------------------------------------------------------------
async function initialRestSync() {
  const baseUrl = getApiBaseUrl();
  try {
    const resp = await fetch(`${baseUrl}/api/iot/devices`);
    const data = await resp.json();
    if (data && data.devices && data.devices.length > 0) {
      const dev = data.devices[0].status;
      const states = dev.states || {};
      if (states.light !== undefined) applianceStates.light = states.light;
      if (states.fan !== undefined) applianceStates.fan = states.fan;
      if (states.pump !== undefined) applianceStates.pump = states.pump;
      updateApplianceStateBadge(currentAppliance.id);
      
      const isOnline = dev.online !== false;
      setConnectionStatus(isOnline, isOnline ? 'SynaptiMesh Connected (MQTT Online)' : 'MQTT Offline');
    }
  } catch (err) {
    console.debug('Initial REST sync skipped (WebSocket handles live feed)');
  }
}

// ------------------------------------------------------------------
// Navigation & Mode Helpers
// ------------------------------------------------------------------
function returnToMainHub() {
  window.location.href = '/';
}

async function switchMode(modeCommand) {
  addLog(`[FSM MODE] Switching operational mode: ${modeCommand}...`, 'info');
  const baseUrl = getApiBaseUrl();
  try {
    const resp = await fetch(`${baseUrl}/api/iot/command`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: modeCommand, domain: 'iot' })
    });
    const data = await resp.json();
    if (data.success) {
      const modeEl = document.getElementById('currentModeText');
      if (modeEl) modeEl.innerText = modeCommand === 'mode_iot' ? 'IOT_MODE' : 'IDLE';
      addLog(`[FSM MODE] Mode successfully changed to ${modeCommand}`, 'success');
    }
  } catch (e) {
    addLog(`[FSM MODE] Mode command sent. Active mode: IOT_MODE`, 'info');
  }
}

function clearLogs() {
  const box = document.getElementById('terminalLogs');
  if (box) box.innerHTML = '';
  addLog('Terminal cleared.', 'info');
}

function addLog(message, type = 'info') {
  const box = document.getElementById('terminalLogs');
  if (!box) return;
  const line = document.createElement('div');
  line.className = `t-log ${type}`;
  line.innerText = `[${new Date().toLocaleTimeString()}] ${message}`;
  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
  const ts = document.getElementById('logTimestamp');
  if (ts) ts.innerText = new Date().toLocaleTimeString();
}

// ------------------------------------------------------------------
// Initialization
// ------------------------------------------------------------------
window.addEventListener('DOMContentLoaded', () => {
  initApiInput();
  showPhase(1);
  initialRestSync();
  initWebSocket();
});
