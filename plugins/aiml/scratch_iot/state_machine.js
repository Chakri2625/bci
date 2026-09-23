/**
 * state_machine.js
 * Hierarchical Brain-Computer Interface (BCI) State Machine for IoT Control.
 * 
 * Logic:
 *  - Selection Mode (Root):
 *      'push'  -> Selects LIGHT
 *      'pull'  -> Selects FAN
 *      'left'  -> Selects PUMP
 *  - Device Control Mode (Inside Selected Appliance):
 *      'right' -> Turn ON
 *      'left'  -> Turn OFF
 */

const EventEmitter = require('events');

class BCIStateMachine extends EventEmitter {
  constructor(options = {}) {
    super();
    this.powerThreshold = options.powerThreshold || 0.35;
    this.debounceMs = options.debounceMs || 900;
    this.autoReturnTimeoutMs = options.autoReturnTimeoutMs || 12000; // 12s timeout to return to selection
    
    // State Variables
    this.currentState = 'SELECT_APPLIANCE'; // 'SELECT_APPLIANCE' | 'CONTROL_DEVICE'
    this.selectedDevice = null;             // 'light' | 'fan' | 'pump' | null
    this.deviceStates = {
      light: 'OFF',
      fan: 'OFF',
      pump: 'OFF'
    };

    this.lastTriggerTime = 0;
    this.autoReturnTimer = null;

    this.stats = {
      totalCommandsReceived: 0,
      totalActionsDispatched: 0,
      lastCommand: null,
      lastPower: 0,
      lastActionDispatched: null
    };
  }

  /**
   * Update configuration parameters dynamically
   */
  updateConfig(config = {}) {
    if (config.powerThreshold !== undefined) {
      this.powerThreshold = Math.max(0.05, Math.min(1.0, parseFloat(config.powerThreshold)));
    }
    if (config.debounceMs !== undefined) {
      this.debounceMs = Math.max(200, parseInt(config.debounceMs, 10));
    }
    if (config.autoReturnTimeoutMs !== undefined) {
      this.autoReturnTimeoutMs = Math.max(3000, parseInt(config.autoReturnTimeoutMs, 10));
    }
    this.emit('config_updated', this.getConfig());
  }

  getConfig() {
    return {
      powerThreshold: this.powerThreshold,
      debounceMs: this.debounceMs,
      autoReturnTimeoutMs: this.autoReturnTimeoutMs
    };
  }

  getFullState() {
    return {
      currentState: this.currentState,
      selectedDevice: this.selectedDevice,
      deviceStates: { ...this.deviceStates },
      config: this.getConfig(),
      stats: { ...this.stats }
    };
  }

  /**
   * Process a mental command event from Cortex 'com' stream
   * @param {string} action - 'push' | 'pull' | 'left' | 'right' | 'neutral' etc.
   * @param {number} power - 0.0 to 1.0
   * @param {boolean} isSimulation - whether triggered from simulator
   */
  processMentalCommand(action, power = 1.0, isSimulation = false) {
    action = (action || '').toLowerCase().trim();
    power = typeof power === 'number' ? power : parseFloat(power) || 0;

    this.stats.totalCommandsReceived++;
    this.stats.lastCommand = action;
    this.stats.lastPower = power;

    // Emit live telemetry for UI visualizer
    this.emit('telemetry', {
      action,
      power,
      isSimulation,
      timestamp: Date.now()
    });

    if (action === 'neutral' || !action) {
      return null;
    }

    // Power Threshold check (Simulation can bypass or test thresholds)
    if (power < this.powerThreshold && !isSimulation) {
      this.emit('command_filtered', {
        action,
        power,
        threshold: this.powerThreshold,
        reason: 'Below power threshold'
      });
      return null;
    }

    // Debounce check
    const now = Date.now();
    if (now - this.lastTriggerTime < this.debounceMs) {
      this.emit('command_filtered', {
        action,
        power,
        reason: 'Debounce cooldown active'
      });
      return null;
    }

    this.lastTriggerTime = now;
    return this._evaluateStateTransition(action, power);
  }

  /**
   * Evaluate State Transition & Action Dispatches
   */
  _evaluateStateTransition(action, power) {
    let result = null;

    if (this.currentState === 'SELECT_APPLIANCE') {
      // Root Level Selection
      switch (action) {
        case 'push':
          this._selectDevice('light', action, power);
          result = { type: 'SELECT', device: 'light', action, power };
          break;

        case 'pull':
          this._selectDevice('fan', action, power);
          result = { type: 'SELECT', device: 'fan', action, power };
          break;

        case 'left':
          this._selectDevice('pump', action, power);
          result = { type: 'SELECT', device: 'pump', action, power };
          break;

        case 'right':
          this.emit('info', {
            message: "Gesture 'right' received in Selection Mode. Select Light (push), Fan (pull), or Pump (left) first.",
            action
          });
          break;

        default:
          break;
      }
    } else if (this.currentState === 'CONTROL_DEVICE') {
      // Domain is LOCKED to this.selectedDevice
      switch (action) {
        case 'right':
          // Turn ON locked device
          result = this._setDeviceState(this.selectedDevice, 'ON', action, power);
          this._resetAutoReturnTimer();
          break;

        case 'left':
          this._cancelComboTimer();
          // Turn OFF locked device
          result = this._setDeviceState(this.selectedDevice, 'OFF', action, power);
          this._resetAutoReturnTimer();
          break;

        case 'push':
          // Start combo window waiting for PULL to exit domain
          this._startComboWindow('push');
          result = {
            type: 'COMBO_WINDOW_OPEN',
            action: 'push',
            device: this.selectedDevice,
            message: `Domain locked on ${this.selectedDevice.toUpperCase()}. PUSH detected: combo window active (think PULL to exit domain).`
          };
          this.emit('info', result);
          break;

        case 'pull':
          if (this._comboFirstAction === 'push') {
            // Combo PUSH + PULL -> BACK / EXIT DOMAIN
            this._cancelComboTimer();
            const comboEvent = {
              type: 'COMBO_COMMAND',
              combo: 'PUSH+PULL',
              action: 'BACK',
              power,
              message: 'Combination Detected: [PUSH + PULL] ➔ BACK (Exited domain to Selection Mode)',
              timestamp: Date.now()
            };
            this.emit('combo_triggered', comboEvent);
            this.returnToSelectionMode('combo_push_pull');
            return comboEvent;
          }
          // Domain is locked! 'pull' without preceding 'push' does NOT switch to fan.
          this._cancelComboTimer();
          this.emit('info', {
            message: `Domain locked on ${this.selectedDevice.toUpperCase()}. Think RIGHT (ON), LEFT (OFF), or PUSH+PULL to exit back to Main Menu.`,
            action
          });
          break;

        default:
          break;
      }
    }

    if (result) {
      this.emit('transition', {
        ...result,
        currentState: this.currentState,
        selectedDevice: this.selectedDevice,
        deviceStates: { ...this.deviceStates }
      });
    }

    return result;
  }

  _startComboWindow(firstAction) {
    this._cancelComboTimer();
    this._comboFirstAction = firstAction;
    const windowMs = this.comboWindowMs || 2000;
    this.emit('combo_window_started', {
      firstAction,
      comboExpected: 'PUSH + PULL ➔ BACK (Exit Domain)',
      windowMs: windowMs
    });
    this._comboTimer = setTimeout(() => {
      this._comboFirstAction = null;
      this.emit('combo_window_expired', { reason: 'Combo window timed out' });
    }, windowMs);
  }

  _cancelComboTimer() {
    if (this._comboTimer) {
      clearTimeout(this._comboTimer);
      this._comboTimer = null;
    }
    this._comboFirstAction = null;
  }

  /**
   * Select an appliance and switch state to CONTROL_DEVICE
   */
  _selectDevice(device, action, power) {
    this.selectedDevice = device;
    this.currentState = 'CONTROL_DEVICE';

    this._startAutoReturnTimer();

    this.emit('device_selected', {
      device,
      action,
      power,
      message: `Selected ${device.toUpperCase()}. Think 'RIGHT' to turn ON, 'LEFT' to turn OFF.`
    });
  }

  /**
   * Set Actuator Output State (ON / OFF) and dispatch to ESP32
   */
  _setDeviceState(device, state, triggerAction = 'manual', power = 1.0) {
    if (!device || !this.deviceStates.hasOwnProperty(device)) {
      return null;
    }

    const previousState = this.deviceStates[device];
    this.deviceStates[device] = state;
    this.stats.totalActionsDispatched++;
    this.stats.lastActionDispatched = { device, state, time: Date.now() };

    const dispatchEvent = {
      device,
      state,
      previousState,
      triggerAction,
      power,
      timestamp: Date.now()
    };

    // Emit event for ESP32 and Web Dashboard
    this.emit('actuator_command', dispatchEvent);
    return dispatchEvent;
  }

  /**
   * Direct manual override from Web Dashboard
   */
  manualOverride(device, state) {
    return this._setDeviceState(device, state, 'manual_override', 1.0);
  }

  /**
   * Return to Root Selection Mode
   */
  returnToSelectionMode(reason = 'timeout') {
    if (this.autoReturnTimer) {
      clearTimeout(this.autoReturnTimer);
      this.autoReturnTimer = null;
    }

    const prevDevice = this.selectedDevice;
    this.currentState = 'SELECT_APPLIANCE';
    this.selectedDevice = null;

    this.emit('state_reset', {
      reason,
      previousDevice: prevDevice,
      currentState: this.currentState,
      message: 'Returned to Appliance Selection Mode (Push: Light, Pull: Fan, Left: Pump)'
    });
  }

  _startAutoReturnTimer() {
    if (this.autoReturnTimer) {
      clearTimeout(this.autoReturnTimer);
    }
    this.autoReturnTimer = setTimeout(() => {
      this.returnToSelectionMode('inactivity_timeout');
    }, this.autoReturnTimeoutMs);
  }

  _resetAutoReturnTimer() {
    this._startAutoReturnTimer();
  }
}

module.exports = BCIStateMachine;
