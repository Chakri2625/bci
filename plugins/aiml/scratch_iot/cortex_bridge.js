/**
 * cortex_bridge.js
 * Emotiv Cortex API v2 WebSocket Bridge.
 * Connects to Emotiv Cortex Service (wss://localhost:6868), handles JSON-RPC 2.0 handshake,
 * authorization, session creation, and subscribes to mental command streams ('com').
 */

const WebSocket = require('ws');
const EventEmitter = require('events');

class CortexBridge extends EventEmitter {
  constructor(options = {}) {
    super();
    this.url = options.url || 'wss://localhost:6868';
    this.clientId = options.clientId || process.env.CORTEX_CLIENT_ID || '';
    this.clientSecret = options.clientSecret || process.env.CORTEX_CLIENT_SECRET || '';
    this.license = options.license || process.env.CORTEX_LICENSE || '';
    this.debit = options.debit !== undefined ? options.debit : 1;

    this.ws = null;
    this.requestId = 1;
    this.pendingRequests = new Map(); // id -> { resolve, reject, timeout }

    this.cortexToken = null;
    this.headsetId = null;
    this.headsets = [];
    this.sessionId = null;
    this.subscribedStreams = [];

    this.isConnected = false;
    this.isAuthorized = false;
    this.isSessionActive = false;
    this.isSubscribed = false;

    this.reconnectTimer = null;
    this.autoReconnect = false;
  }

  /**
   * Set or update Cortex credentials
   */
  setCredentials(credentials = {}) {
    if (credentials.clientId) this.clientId = credentials.clientId.trim();
    if (credentials.clientSecret) this.clientSecret = credentials.clientSecret.trim();
    if (credentials.license !== undefined) this.license = credentials.license.trim();
    if (credentials.debit !== undefined) this.debit = credentials.debit;
  }

  getStatus() {
    return {
      connected: this.isConnected,
      authorized: this.isAuthorized,
      sessionActive: this.isSessionActive,
      subscribed: this.isSubscribed,
      headsetId: this.headsetId,
      sessionId: this.sessionId,
      headsets: this.headsets,
      hasCredentials: Boolean(this.clientId && this.clientSecret)
    };
  }

  /**
   * Initiate connection to Cortex WebSocket
   */
  connect() {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      this.emit('log', { level: 'info', message: 'Cortex WebSocket is already connected or connecting.' });
      return;
    }

    this.emit('log', { level: 'info', message: `Connecting to Emotiv Cortex Service at ${this.url}...` });
    this.emit('status_change', { state: 'connecting' });

    try {
      this.ws = new WebSocket(this.url, {
        rejectUnauthorized: false // Cortex uses a local self-signed certificate
      });

      this.ws.on('open', () => this._onOpen());
      this.ws.on('message', (data) => this._onMessage(data));
      this.ws.on('error', (error) => this._onError(error));
      this.ws.on('close', (code, reason) => this._onClose(code, reason));
    } catch (err) {
      this._onError(err);
    }
  }

  /**
   * Disconnect and clear state
   */
  disconnect() {
    this.autoReconnect = false;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    if (this.ws) {
      try {
        this.ws.close();
      } catch (e) {}
      this.ws = null;
    }

    this._resetState();
    this.emit('status_change', { state: 'disconnected' });
    this.emit('log', { level: 'info', message: 'Disconnected from Cortex.' });
  }

  _resetState() {
    this.isConnected = false;
    this.isAuthorized = false;
    this.isSessionActive = false;
    this.isSubscribed = false;
    this.cortexToken = null;
    this.sessionId = null;
    this.headsetId = null;
  }

  _onOpen() {
    this.isConnected = true;
    this.emit('log', { level: 'success', message: 'Connected to Emotiv Cortex WebSocket successfully!' });
    this.emit('status_change', { state: 'connected' });

    // Automatically begin authorization pipeline if credentials are provided
    if (this.clientId && this.clientSecret) {
      this.authenticateAndSubscribe().catch((err) => {
        this.emit('log', { level: 'error', message: `Cortex Handshake error: ${err.message}` });
      });
    } else {
      this.emit('log', {
        level: 'warn',
        message: 'Cortex connected, but Client ID & Client Secret are missing. Please enter them in settings.'
      });
    }
  }

  _onClose(code, reason) {
    const reasonText = reason ? reason.toString() : 'Unknown';
    this.emit('log', { level: 'warn', message: `Cortex connection closed. Code: ${code}, Reason: ${reasonText}` });
    this._resetState();
    this.emit('status_change', { state: 'disconnected' });

    if (this.autoReconnect) {
      this.emit('log', { level: 'info', message: 'Attempting reconnection in 5s...' });
      this.reconnectTimer = setTimeout(() => this.connect(), 5000);
    }
  }

  _onError(error) {
    const msg = error.message || 'Cortex WebSocket error occurred.';
    this.emit('log', {
      level: 'error',
      message: `Cortex WebSocket Error: ${msg}. Make sure the Emotiv App / Cortex Service is running on this PC.`
    });
    this.emit('error', error);
  }

  _onMessage(raw) {
    let data;
    try {
      data = JSON.parse(raw);
    } catch (e) {
      this.emit('log', { level: 'error', message: `Malformed JSON received from Cortex: ${raw}` });
      return;
    }

    // 1. Handle Response to a Request ID
    if (data.id && this.pendingRequests.has(data.id)) {
      const { resolve, reject, timeout } = this.pendingRequests.get(data.id);
      clearTimeout(timeout);
      this.pendingRequests.delete(data.id);

      if (data.error) {
        reject(new Error(data.error.message || `Cortex Error Code ${data.error.code}`));
      } else {
        resolve(data.result);
      }
      return;
    }

    // 2. Handle Stream Data (Mental Commands 'com', Facial 'fac', System 'sys')
    if (data.com) {
      // 'com' stream payload: ["neutral", 0.0] or ["push", 0.85] or ["pull", 0.7]
      const [action, power] = data.com;
      this.emit('com', {
        action,
        power: typeof power === 'number' ? power : parseFloat(power) || 0,
        time: data.time,
        sid: data.sid
      });
    }

    // 3. Handle System / Warning events from Cortex
    if (data.sys) {
      this.emit('sys', data.sys);
    }

    if (data.warning) {
      this.emit('log', { level: 'warn', message: `Cortex Warning: ${JSON.stringify(data.warning)}` });
    }
  }

  /**
   * Send JSON-RPC 2.0 Request
   */
  request(method, params = {}) {
    return new Promise((resolve, reject) => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
        return reject(new Error('Cortex WebSocket is not open.'));
      }

      const id = this.requestId++;
      const message = {
        jsonrpc: '2.0',
        method,
        params,
        id
      };

      const timeout = setTimeout(() => {
        if (this.pendingRequests.has(id)) {
          this.pendingRequests.delete(id);
          reject(new Error(`Timeout waiting for Cortex response to '${method}' (ID ${id})`));
        }
      }, 15000);

      this.pendingRequests.set(id, { resolve, reject, timeout });
      this.ws.send(JSON.stringify(message));
    });
  }

  /**
   * Full automated pipeline:
   * 1. requestAccess / hasAccess
   * 2. authorize (token)
   * 3. queryHeadsets
   * 4. createSession
   * 5. subscribe to 'com'
   */
  async authenticateAndSubscribe() {
    if (!this.clientId || !this.clientSecret) {
      throw new Error('Client ID and Client Secret are required.');
    }

    this.emit('log', { level: 'info', message: 'Checking access rights with Cortex...' });
    
    // Step 1: Request Access (prompts user in Emotiv app if not yet approved)
    try {
      const accessResult = await this.request('requestAccess', {
        clientId: this.clientId,
        clientSecret: this.clientSecret
      });
      this.emit('log', {
        level: 'info',
        message: `Access status: ${accessResult.accessGranted ? 'Granted' : 'Pending user confirmation in Emotiv App'}`
      });
    } catch (e) {
      this.emit('log', { level: 'warn', message: `requestAccess notice: ${e.message}` });
    }

    // Step 2: Authorize
    this.emit('log', { level: 'info', message: 'Authorizing with Cortex...' });
    const authParams = {
      clientId: this.clientId,
      clientSecret: this.clientSecret,
      debit: this.debit
    };
    if (this.license) {
      authParams.license = this.license;
    }

    const authResult = await this.request('authorize', authParams);
    if (!authResult || !authResult.cortexToken) {
      throw new Error('Authorization failed: No cortexToken returned.');
    }

    this.cortexToken = authResult.cortexToken;
    this.isAuthorized = true;
    this.emit('log', { level: 'success', message: 'Cortex Authorization Successful!' });
    this.emit('status_change', { state: 'authorized' });

    // Step 3: Query Headsets
    this.emit('log', { level: 'info', message: 'Querying connected Emotiv headsets...' });
    const headsets = await this.request('queryHeadsets', {});
    this.headsets = headsets || [];

    if (!this.headsets.length) {
      this.emit('log', {
        level: 'warn',
        message: 'No Emotiv Headset detected. Ensure your EPOC headset is turned ON and paired via Bluetooth/Dongle.'
      });
      return;
    }

    // Pick first connected headset or designated headset
    const connectedHeadset = this.headsets.find((h) => h.status === 'connected') || this.headsets[0];
    this.headsetId = connectedHeadset.id;
    this.emit('log', {
      level: 'success',
      message: `Found headset: ${this.headsetId} (${connectedHeadset.status})`
    });

    // Step 4: Create Session
    this.emit('log', { level: 'info', message: `Creating active session for headset ${this.headsetId}...` });
    const sessionResult = await this.request('createSession', {
      cortexToken: this.cortexToken,
      headset: this.headsetId,
      status: 'active'
    });

    if (!sessionResult || !sessionResult.id) {
      throw new Error('Failed to create active session with headset.');
    }

    this.sessionId = sessionResult.id;
    this.isSessionActive = true;
    this.emit('log', { level: 'success', message: `Active Session Created: ${this.sessionId}` });
    this.emit('status_change', { state: 'session_active', sessionId: this.sessionId });

    // Step 5: Subscribe to Mental Commands stream ('com')
    this.emit('log', { level: 'info', message: "Subscribing to Mental Commands ('com') stream..." });
    const subResult = await this.request('subscribe', {
      cortexToken: this.cortexToken,
      session: this.sessionId,
      streams: ['com', 'sys']
    });

    this.isSubscribed = true;
    this.subscribedStreams = subResult && subResult.success ? subResult.success.map((s) => s.streamName) : ['com'];
    this.emit('log', {
      level: 'success',
      message: `Successfully subscribed to Cortex streams: ${this.subscribedStreams.join(', ')}`
    });
    this.emit('status_change', { state: 'subscribed', streams: this.subscribedStreams });
  }
}

module.exports = CortexBridge;
