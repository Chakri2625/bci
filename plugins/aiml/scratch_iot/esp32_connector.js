/**
 * esp32_connector.js
 * Hardware Connector for ESP32 IoT Master Hub.
 * Supports:
 *  1. WiFi (HTTP REST API / Direct WebSockets)
 *  2. Serial USB UART (COM port)
 */

const http = require('http');
const EventEmitter = require('events');

class ESP32Connector extends EventEmitter {
  constructor(options = {}) {
    super();
    this.mode = options.mode || 'wifi'; // 'wifi' | 'serial' | 'mock'
    this.esp32Ip = options.esp32Ip || process.env.ESP32_IP || '192.168.1.100';
    this.esp32Port = options.esp32Port || 80;
    this.serialPortPath = options.serialPortPath || process.env.ESP32_SERIAL_PORT || 'COM3';
    this.baudRate = options.baudRate || 115200;

    this.serialPort = null;
    this.isConnected = false;
    this.lastPingTime = 0;
    this.lastLatency = null;
    this.activeWsClient = null; // Connected ESP32 WebSocket client

    this.deviceStates = {
      light: 'OFF',
      fan: 'OFF',
      pump: 'OFF'
    };
  }

  updateConfig(config = {}) {
    if (config.mode) this.mode = config.mode;
    if (config.esp32Ip) this.esp32Ip = config.esp32Ip.trim();
    if (config.esp32Port) this.esp32Port = parseInt(config.esp32Port, 10);
    if (config.serialPortPath) this.serialPortPath = config.serialPortPath.trim();
    if (config.baudRate) this.baudRate = parseInt(config.baudRate, 10);

    this.emit('config_updated', this.getConfig());
  }

  getConfig() {
    return {
      mode: this.mode,
      esp32Ip: this.esp32Ip,
      esp32Port: this.esp32Port,
      serialPortPath: this.serialPortPath,
      baudRate: this.baudRate,
      isConnected: this.isConnected,
      lastLatency: this.lastLatency
    };
  }

  /**
   * Register a directly connected ESP32 WebSocket client
   */
  registerWebSocketClient(ws) {
    this.activeWsClient = ws;
    this.isConnected = true;
    this.mode = 'wifi_ws';

    this.emit('log', { level: 'success', message: 'ESP32 connected directly via WebSocket!' });
    this.emit('status_change', { connected: true, mode: 'wifi_ws' });

    ws.on('message', (message) => {
      try {
        const data = JSON.parse(message.toString());
        if (data.type === 'status_sync' && data.states) {
          this.deviceStates = { ...this.deviceStates, ...data.states };
          this.emit('states_sync', this.deviceStates);
        }
      } catch (e) {
        // Raw text line
        this.emit('log', { level: 'info', message: `ESP32 WS: ${message}` });
      }
    });

    ws.on('close', () => {
      this.activeWsClient = null;
      this.isConnected = false;
      this.emit('log', { level: 'warn', message: 'ESP32 WebSocket connection closed.' });
      this.emit('status_change', { connected: false });
    });
  }

  /**
   * Initialize Serial connection if mode is 'serial'
   */
  async initSerial() {
    let SerialPortPackage;
    try {
      SerialPortPackage = require('serialport');
    } catch (e) {
      this.emit('log', {
        level: 'warn',
        message: 'SerialPort module not installed. Run `npm install serialport` for USB COM port mode.'
      });
      return false;
    }

    try {
      const { SerialPort } = SerialPortPackage;
      const { ReadlineParser } = require('@serialport/parser-readline');

      if (this.serialPort && this.serialPort.isOpen) {
        await new Promise((res) => this.serialPort.close(res));
      }

      this.serialPort = new SerialPort({
        path: this.serialPortPath,
        baudRate: this.baudRate
      });

      const parser = this.serialPort.pipe(new ReadlineParser({ delimiter: '\r\n' }));

      this.serialPort.on('open', () => {
        this.isConnected = true;
        this.emit('log', {
          level: 'success',
          message: `Opened ESP32 Serial Port ${this.serialPortPath} @ ${this.baudRate} baud`
        });
        this.emit('status_change', { connected: true, mode: 'serial' });
      });

      parser.on('data', (line) => {
        this.emit('log', { level: 'info', message: `[ESP32 Serial] ${line}` });
        this._parseSerialLine(line);
      });

      this.serialPort.on('error', (err) => {
        this.isConnected = false;
        this.emit('log', { level: 'error', message: `ESP32 Serial Error: ${err.message}` });
        this.emit('status_change', { connected: false });
      });

      this.serialPort.on('close', () => {
        this.isConnected = false;
        this.emit('log', { level: 'warn', message: 'ESP32 Serial Port closed.' });
        this.emit('status_change', { connected: false });
      });

      return true;
    } catch (err) {
      this.emit('log', { level: 'error', message: `Failed to initialize Serial: ${err.message}` });
      return false;
    }
  }

  _parseSerialLine(line) {
    // Check if line contains JSON or state updates e.g. "ACK: LIGHT=ON" or {"light":"ON"}
    try {
      if (line.startsWith('{') && line.endsWith('}')) {
        const json = JSON.parse(line);
        if (json.states) {
          this.deviceStates = { ...this.deviceStates, ...json.states };
          this.emit('states_sync', this.deviceStates);
        }
      }
    } catch (e) {}
  }

  /**
   * Dispatch Actuator Command (e.g. device: 'light', state: 'ON')
   */
  async sendCommand(device, state) {
    device = (device || '').toLowerCase();
    state = (state || '').toUpperCase();

    this.deviceStates[device] = state;
    const commandPayload = {
      device,
      state,
      timestamp: Date.now()
    };

    this.emit('log', {
      level: 'info',
      message: `Dispatching to ESP32: [${device.toUpperCase()} -> ${state}] via Mode: ${this.mode}`
    });

    // 1. Direct WebSocket client
    if (this.activeWsClient && this.activeWsClient.readyState === 1) {
      try {
        this.activeWsClient.send(JSON.stringify({ type: 'control', ...commandPayload }));
        return { success: true, mode: 'websocket' };
      } catch (err) {
        this.emit('log', { level: 'error', message: `WS Dispatch error: ${err.message}` });
      }
    }

    // 2. Serial Mode
    if (this.mode === 'serial' && this.serialPort && this.serialPort.isOpen) {
      const serialCmd = `${device.toUpperCase()}:${state}\n`;
      return new Promise((resolve) => {
        this.serialPort.write(serialCmd, (err) => {
          if (err) {
            this.emit('log', { level: 'error', message: `Serial write error: ${err.message}` });
            resolve({ success: false, error: err.message });
          } else {
            resolve({ success: true, mode: 'serial' });
          }
        });
      });
    }

    // 3. WiFi HTTP REST Mode
    if (this.mode === 'wifi' || this.mode === 'http') {
      return this._sendHttpRequest(device, state);
    }

    // Fallback Mock/Virtual Mode
    return { success: true, mode: 'virtual' };
  }

  _sendHttpRequest(device, state) {
    return new Promise((resolve) => {
      const startTime = Date.now();
      const path = `/api/control?device=${encodeURIComponent(device)}&state=${encodeURIComponent(state)}`;
      const options = {
        hostname: this.esp32Ip,
        port: this.esp32Port,
        path,
        method: 'GET',
        timeout: 2500
      };

      const req = http.request(options, (res) => {
        let rawData = '';
        res.on('data', (chunk) => { rawData += chunk; });
        res.on('end', () => {
          this.lastLatency = Date.now() - startTime;
          this.isConnected = true;
          this.emit('log', {
            level: 'success',
            message: `ESP32 HTTP Response (${this.lastLatency}ms): ${rawData || res.statusCode}`
          });
          resolve({ success: true, latency: this.lastLatency, response: rawData });
        });
      });

      req.on('error', (e) => {
        this.lastLatency = null;
        // Don't spam errors if ESP32 is offline during local dashboard testing
        this.emit('log', {
          level: 'warn',
          message: `ESP32 HTTP Request failed (${this.esp32Ip}:${this.esp32Port}): ${e.message}`
        });
        resolve({ success: false, error: e.message });
      });

      req.on('timeout', () => {
        req.destroy();
        this.emit('log', { level: 'warn', message: `ESP32 HTTP Request timeout (${this.esp32Ip})` });
        resolve({ success: false, error: 'Timeout' });
      });

      req.end();
    });
  }

  /**
   * Ping ESP32 to test connectivity
   */
  async ping() {
    const startTime = Date.now();
    return new Promise((resolve) => {
      const req = http.get(`http://${this.esp32Ip}:${this.esp32Port}/api/status`, { timeout: 2000 }, (res) => {
        let body = '';
        res.on('data', (c) => body += c);
        res.on('end', () => {
          const latency = Date.now() - startTime;
          this.isConnected = true;
          this.lastLatency = latency;
          resolve({ success: true, latency, body });
        });
      });

      req.on('error', (err) => {
        this.isConnected = false;
        resolve({ success: false, error: err.message });
      });

      req.on('timeout', () => {
        req.destroy();
        this.isConnected = false;
        resolve({ success: false, error: 'Timeout' });
      });
    });
  }
}

module.exports = ESP32Connector;
