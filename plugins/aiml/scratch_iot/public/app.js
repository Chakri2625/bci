/**
 * app.js - Emotiv BCI Neuro-Hub & Stream Dashboard Controller
 * Pure BCI & Cortex Telemetry Suite
 */

// Application State
const appState = {
  ws: null,
  reconnectInterval: null,
  config: {
    powerThreshold: 0.35,
    debounceMs: 900,
    singleFireWindowMs: 1500,
    comboWindowMs: 2000,
    framingWindowMs: 4000,
    framingEnabled: true
  },
  cortexStatus: {
    connected: false,
    authorized: false,
    sessionActive: false,
    subscribed: false,
    headsetId: 'EPOCX-14CH',
    availableProfiles: ['Default_User', 'Master_BCI_Profile', 'Focus_Calibrated'],
    activeProfile: 'Master_BCI_Profile'
  },
  activeAction: 'NEUTRAL',
  activePower: 0,
  framingTimer: null,
  comboTimer: null
};

// DOM References
const elements = {
  cortexBadge: document.getElementById('cortexBadge'),
  cortexDot: document.getElementById('cortexDot'),
  cortexStatusText: document.getElementById('cortexStatusText'),
  headsetBatteryText: document.getElementById('headsetBatteryText'),
  
  headsetName: document.getElementById('headsetName'),
  cmdActionText: document.getElementById('cmdActionText'),
  cmdPowerPercent: document.getElementById('cmdPowerPercent'),
  cmdPowerFill: document.getElementById('cmdPowerFill'),
  thresholdLine: document.getElementById('thresholdLine'),

  // 3D Cube Stage
  stageCubeIntent: document.getElementById('stageCubeIntent'),
  stageCubePower: document.getElementById('stageCubePower'),

  // Frequency Bands
  fillDelta: document.getElementById('fillDelta'),
  fillTheta: document.getElementById('fillTheta'),
  fillAlpha: document.getElementById('fillAlpha'),
  fillBeta: document.getElementById('fillBeta'),
  fillGamma: document.getElementById('fillGamma'),
  valDelta: document.getElementById('valDelta'),
  valTheta: document.getElementById('valTheta'),
  valAlpha: document.getElementById('valAlpha'),
  valBeta: document.getElementById('valBeta'),
  valGamma: document.getElementById('valGamma'),

  // Framing
  temporalFramingCard: document.getElementById('temporalFramingCard'),
  framingCircleFill: document.getElementById('framingCircleFill'),
  framingCountdownText: document.getElementById('framingCountdownText'),
  framingStatusPill: document.getElementById('framingStatusPill'),
  framingDescription: document.getElementById('framingDescription'),
  framingBottomFill: document.getElementById('framingBottomFill'),
  btnCancelFraming: document.getElementById('btnCancelFraming'),
  framingCurrentDuration: document.getElementById('framingCurrentDuration'),
  framingCardSlider: document.getElementById('framingCardSlider'),
  btnFramingDec: document.getElementById('btnFramingDec'),
  btnFramingInc: document.getElementById('btnFramingInc'),
  btnFramingPushPull: document.getElementById('btnFramingPushPull'),
  framingPresets: document.querySelectorAll('#framingPresets .preset-btn'),

  // Simulator
  simButtons: document.querySelectorAll('.sim-btn'),
  simPushPullCombo: document.getElementById('simPushPullCombo'),
  simPowerSlider: document.getElementById('simPowerSlider'),
  simPowerLabel: document.getElementById('simPowerLabel'),

  // Console
  consoleBody: document.getElementById('consoleBody'),
  btnClearLog: document.getElementById('btnClearLog'),

  // Modal
  openSettingsBtn: document.getElementById('openSettingsBtn'),
  closeSettingsBtn: document.getElementById('closeSettingsBtn'),
  settingsModal: document.getElementById('settingsModal'),
  modalTabs: document.querySelectorAll('.modal-tab'),
  tabContents: document.querySelectorAll('.tab-content'),
  btnSaveConfig: document.getElementById('btnSaveConfig'),

  // Cortex Settings
  cfgClientId: document.getElementById('cfgClientId'),
  cfgClientSecret: document.getElementById('cfgClientSecret'),
  cfgProfileSelect: document.getElementById('cfgProfileSelect'),
  btnRefreshProfiles: document.getElementById('btnRefreshProfiles'),
  btnLoadProfile: document.getElementById('btnLoadProfile'),
  btnCortexConnect: document.getElementById('btnCortexConnect'),
  btnCortexDisconnect: document.getElementById('btnCortexDisconnect'),
  cortexDiagBadge: document.getElementById('cortexDiagBadge'),

  // BCI Tuning
  cfgThreshold: document.getElementById('cfgThreshold'),
  valThreshold: document.getElementById('valThreshold'),
  cfgDebounce: document.getElementById('cfgDebounce'),
  valDebounce: document.getElementById('valDebounce'),
  cfgSingleFire: document.getElementById('cfgSingleFire'),
  valSingleFire: document.getElementById('valSingleFire'),
  cfgComboWindow: document.getElementById('cfgComboWindow'),
  valComboWindow: document.getElementById('valComboWindow'),
  cfgFramingWindow: document.getElementById('cfgFramingWindow'),
  valFramingWindow: document.getElementById('valFramingWindow'),
  cfgFramingEnabled: document.getElementById('cfgFramingEnabled')
};

// -------------------------------------------------------------
// 1. THREE.JS 3D EMOTIV TRAINING CUBE ENGINE
// -------------------------------------------------------------
let cubeScene = null, cubeCamera = null, cubeRenderer = null;
let cubeOuterMesh = null, cubeCoreMesh = null, cubeGlowMesh = null;
let cubeTargetPos = { x: 0, y: 0, z: 0 };
let cubeCurrentPos = { x: 0, y: 0, z: 0 };
let cubeTargetRot = { x: 0, y: 0, z: 0 };
let cubeCurrentRot = { x: 0, y: 0, z: 0 };

function init3DStageCube() {
  const canvas = document.getElementById('bci-stage-canvas');
  if (!canvas) return;

  const w = canvas.clientWidth || 450;
  const h = canvas.clientHeight || 230;

  cubeScene = new THREE.Scene();
  cubeCamera = new THREE.PerspectiveCamera(45, w / h, 0.1, 100);
  cubeCamera.position.set(0, 0, 7.5);

  cubeRenderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true });
  cubeRenderer.setSize(w, h, false);
  cubeRenderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

  // Lighting
  const amb = new THREE.AmbientLight(0xffffff, 0.9);
  cubeScene.add(amb);

  const pLight1 = new THREE.PointLight(0x00f2fe, 3.0, 25);
  pLight1.position.set(5, 5, 5);
  cubeScene.add(pLight1);

  const pLight2 = new THREE.PointLight(0x7928ca, 2.5, 25);
  pLight2.position.set(-5, -5, 5);
  cubeScene.add(pLight2);

  // Outer Wireframe Cage
  const boxGeo = new THREE.BoxGeometry(2.5, 2.5, 2.5);
  const edges = new THREE.EdgesGeometry(boxGeo);
  const lineMat = new THREE.LineBasicMaterial({ color: 0x00f2fe, linewidth: 2 });
  cubeOuterMesh = new THREE.LineSegments(edges, lineMat);
  cubeScene.add(cubeOuterMesh);

  // Core Glowing Crystal Cube
  const coreGeo = new THREE.BoxGeometry(2.15, 2.15, 2.15);
  const coreMat = new THREE.MeshStandardMaterial({
    color: 0x07122b,
    emissive: 0x00f2fe,
    emissiveIntensity: 0.35,
    roughness: 0.15,
    metalness: 0.85,
    transparent: true,
    opacity: 0.85
  });
  cubeCoreMesh = new THREE.Mesh(coreGeo, coreMat);
  cubeScene.add(cubeCoreMesh);

  // Inner Neural Sphere
  const glowGeo = new THREE.SphereGeometry(0.8, 16, 16);
  const glowMat = new THREE.MeshBasicMaterial({ color: 0x00f2fe, transparent: true, opacity: 0.7 });
  cubeGlowMesh = new THREE.Mesh(glowGeo, glowMat);
  cubeScene.add(cubeGlowMesh);

  function resize3D() {
    if (cubeRenderer && canvas && canvas.clientWidth > 0 && canvas.clientHeight > 0) {
      const rw = canvas.clientWidth;
      const rh = canvas.clientHeight;
      cubeRenderer.setSize(rw, rh, false);
      cubeCamera.aspect = rw / rh;
      cubeCamera.updateProjectionMatrix();
    }
  }

  window.addEventListener('resize', resize3D);
  setTimeout(resize3D, 200);
  setTimeout(resize3D, 800);

  animate3DStageCube();
}

function animate3DStageCube() {
  requestAnimationFrame(animate3DStageCube);
  if (!cubeRenderer) return;

  // Lerp position & rotation
  cubeCurrentPos.x += (cubeTargetPos.x - cubeCurrentPos.x) * 0.12;
  cubeCurrentPos.y += (cubeTargetPos.y - cubeCurrentPos.y) * 0.12;
  cubeCurrentPos.z += (cubeTargetPos.z - cubeCurrentPos.z) * 0.12;

  cubeCurrentRot.x += (cubeTargetRot.x - cubeCurrentRot.x) * 0.12;
  cubeCurrentRot.y += (cubeTargetRot.y - cubeCurrentRot.y) * 0.12;
  cubeCurrentRot.z += (cubeTargetRot.z - cubeCurrentRot.z) * 0.12;

  // Idle floating breathing wave
  const time = performance.now() * 0.0015;
  const idleY = Math.sin(time) * 0.14;
  const idleRotY = time * 0.45;

  if (cubeOuterMesh && cubeCoreMesh) {
    cubeOuterMesh.position.set(cubeCurrentPos.x, cubeCurrentPos.y + idleY, cubeCurrentPos.z);
    cubeCoreMesh.position.set(cubeCurrentPos.x, cubeCurrentPos.y + idleY, cubeCurrentPos.z);
    if (cubeGlowMesh) cubeGlowMesh.position.set(cubeCurrentPos.x, cubeCurrentPos.y + idleY, cubeCurrentPos.z);

    cubeOuterMesh.rotation.set(cubeCurrentRot.x, cubeCurrentRot.y + idleRotY, cubeCurrentRot.z);
    cubeCoreMesh.rotation.set(cubeCurrentRot.x, cubeCurrentRot.y + idleRotY, cubeCurrentRot.z);
  }

  cubeRenderer.render(cubeScene, cubeCamera);
}

function trigger3DCubeReaction(cmd, power = 0.85) {
  const norm = cmd.toUpperCase();
  if (elements.stageCubeIntent) elements.stageCubeIntent.innerText = norm;
  if (elements.stageCubePower) elements.stageCubePower.innerText = `${Math.round(power * 100)}%`;

  if (norm === 'PUSH') {
    cubeTargetPos = { x: 0, y: 0.3, z: -2.4 };
    cubeTargetRot = { x: 0.5, y: 0, z: 0 };
    if (cubeCoreMesh) {
      cubeCoreMesh.material.emissive.setHex(0x00f2fe);
      cubeCoreMesh.material.emissiveIntensity = 0.95;
    }
  } else if (norm === 'PULL') {
    cubeTargetPos = { x: 0, y: -0.3, z: 2.4 };
    cubeTargetRot = { x: -0.5, y: 0, z: 0 };
    if (cubeCoreMesh) {
      cubeCoreMesh.material.emissive.setHex(0x7928ca);
      cubeCoreMesh.material.emissiveIntensity = 0.95;
    }
  } else if (norm === 'LEFT') {
    cubeTargetPos = { x: -1.8, y: 0, z: 0 };
    cubeTargetRot = { x: 0, y: -1.5, z: 0.25 };
    if (cubeCoreMesh) {
      cubeCoreMesh.material.emissive.setHex(0x10b981);
      cubeCoreMesh.material.emissiveIntensity = 0.95;
    }
  } else if (norm === 'RIGHT') {
    cubeTargetPos = { x: 1.8, y: 0, z: 0 };
    cubeTargetRot = { x: 0, y: 1.5, z: -0.25 };
    if (cubeCoreMesh) {
      cubeCoreMesh.material.emissive.setHex(0xf59e0b);
      cubeCoreMesh.material.emissiveIntensity = 0.95;
    }
  } else {
    cubeTargetPos = { x: 0, y: 0, z: 0 };
    cubeTargetRot = { x: 0, y: 0, z: 0 };
    if (cubeCoreMesh) {
      cubeCoreMesh.material.emissive.setHex(0x00f2fe);
      cubeCoreMesh.material.emissiveIntensity = 0.35;
    }
  }

  if (norm !== 'NEUTRAL') {
    setTimeout(() => {
      cubeTargetPos = { x: 0, y: 0, z: 0 };
      cubeTargetRot = { x: 0, y: 0, z: 0 };
      if (cubeCoreMesh) cubeCoreMesh.material.emissiveIntensity = 0.35;
      if (elements.stageCubeIntent) elements.stageCubeIntent.innerText = 'NEUTRAL';
      if (elements.stageCubePower) elements.stageCubePower.innerText = '0%';
    }, 2200);
  }
}

// -------------------------------------------------------------
// 2. REAL-TIME EEG OSCILLOSCOPE CANVAS
// -------------------------------------------------------------
let eegCanvas = null, eegCtx = null, eegAnimId = null;
let eegPoints = [];

function initEEGVisualizer() {
  eegCanvas = document.getElementById('eegCanvas');
  if (!eegCanvas) return;
  eegCtx = eegCanvas.getContext('2d');

  function resizeEEG() {
    if (eegCanvas) {
      eegCanvas.width = eegCanvas.parentElement.clientWidth || 400;
      eegCanvas.height = 95;
    }
  }
  window.addEventListener('resize', resizeEEG);
  resizeEEG();

  let phase = 0;
  function renderEEG() {
    eegAnimId = requestAnimationFrame(renderEEG);
    if (!eegCtx || !eegCanvas) return;

    const w = eegCanvas.width;
    const h = eegCanvas.height;
    eegCtx.clearRect(0, 0, w, h);

    // Subtle background grid
    eegCtx.strokeStyle = 'rgba(255, 255, 255, 0.04)';
    eegCtx.lineWidth = 1;
    for (let x = 0; x < w; x += 30) {
      eegCtx.beginPath();
      eegCtx.moveTo(x, 0);
      eegCtx.lineTo(x, h);
      eegCtx.stroke();
    }
    for (let y = 0; y < h; y += 20) {
      eegCtx.beginPath();
      eegCtx.moveTo(0, y);
      eegCtx.lineTo(w, y);
      eegCtx.stroke();
    }

    // Dynamic EEG wave trace
    phase += 0.05;
    const powerBoost = appState.activePower > 0.1 ? (1 + appState.activePower * 1.5) : 1;

    eegCtx.lineWidth = 2;
    eegCtx.strokeStyle = appState.activePower >= appState.config.powerThreshold ? '#00f2fe' : '#7928ca';
    eegCtx.shadowColor = eegCtx.strokeStyle;
    eegCtx.shadowBlur = 8;

    eegCtx.beginPath();
    for (let x = 0; x < w; x++) {
      const freq1 = Math.sin((x * 0.04) + phase) * 12 * powerBoost;
      const freq2 = Math.cos((x * 0.09) - (phase * 1.3)) * 6;
      const freq3 = Math.sin((x * 0.18) + (phase * 0.7)) * 4;
      const y = (h / 2) + freq1 + freq2 + freq3;
      if (x === 0) eegCtx.moveTo(x, y);
      else eegCtx.lineTo(x, y);
    }
    eegCtx.stroke();
    eegCtx.shadowBlur = 0;
  }
  renderEEG();
}

// -------------------------------------------------------------
// 3. WEBSOCKET CONTROLLER & TELEMETRY SYNC
// -------------------------------------------------------------
function initWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws`;

  try {
    appState.ws = new WebSocket(wsUrl);

    appState.ws.onopen = () => {
      addLog('WEBSOCKET', 'info', `Connected to BCI Hub at ${wsUrl}`);
      if (appState.reconnectInterval) {
        clearInterval(appState.reconnectInterval);
        appState.reconnectInterval = null;
      }
    };

    appState.ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        handleWsMessage(msg);
      } catch (err) {}
    };

    appState.ws.onclose = () => {
      if (!appState.reconnectInterval) {
        appState.reconnectInterval = setInterval(initWebSocket, 3000);
      }
    };
  } catch (e) {
    if (!appState.reconnectInterval) {
      appState.reconnectInterval = setInterval(initWebSocket, 3000);
    }
  }
}

function handleWsMessage(msg) {
  const { type, payload } = msg;

  switch (type) {
    case 'init_snapshot':
      if (payload.cortex) updateCortexUI(payload.cortex);
      if (payload.stateMachine && payload.stateMachine.config) {
        appState.config = { ...appState.config, ...payload.stateMachine.config };
        syncConfigUI();
      }
      break;

    case 'telemetry':
    case 'cortex_com':
      updateTelemetryUI(payload);
      break;

    case 'cortex_status':
      updateCortexUI(payload);
      break;

    case 'framing_window_started':
      startFramingTimer(payload.windowMs || 4000, payload.description);
      break;

    case 'framing_executed':
      stopFramingTimer('EXECUTED');
      break;

    case 'framing_cancelled':
      stopFramingTimer('CANCELLED', payload.message);
      break;

    case 'log':
      addLog(payload.source || 'CORTEX', payload.level || 'info', payload.message);
      break;
  }
}

function updateTelemetryUI(data) {
  const action = (data.action || 'NEUTRAL').toUpperCase();
  const power = data.power !== undefined ? data.power : 0;

  appState.activeAction = action;
  appState.activePower = power;

  if (elements.cmdActionText) {
    elements.cmdActionText.textContent = action;
    if (action !== 'NEUTRAL') elements.cmdActionText.classList.add('cmd-active');
    else elements.cmdActionText.classList.remove('cmd-active');
  }

  const pct = Math.round(power * 100);
  if (elements.cmdPowerPercent) elements.cmdPowerPercent.textContent = `${pct}%`;
  if (elements.cmdPowerFill) {
    elements.cmdPowerFill.style.width = `${pct}%`;
    if (power >= appState.config.powerThreshold) {
      elements.cmdPowerFill.style.background = 'linear-gradient(90deg, #10b981, #00f2fe)';
      elements.cmdPowerFill.style.boxShadow = '0 0 15px #00f2fe';
    } else {
      elements.cmdPowerFill.style.background = 'linear-gradient(90deg, #4facfe, #00f2fe)';
      elements.cmdPowerFill.style.boxShadow = 'none';
    }
  }

  trigger3DCubeReaction(action, power);

  // Update frequency bands dynamically
  if (action !== 'NEUTRAL') {
    if (elements.fillBeta) elements.fillBeta.style.width = `${Math.min(98, 70 + pct * 0.3)}%`;
    if (elements.valBeta) elements.valBeta.innerText = `${Math.min(98, Math.round(70 + pct * 0.3))}%`;
    if (elements.fillAlpha) elements.fillAlpha.style.width = `${Math.max(20, 80 - pct * 0.4)}%`;
    if (elements.valAlpha) elements.valAlpha.innerText = `${Math.max(20, Math.round(80 - pct * 0.4))}%`;
  }
}

function updateCortexUI(data) {
  appState.cortexStatus = { ...appState.cortexStatus, ...data };
  const isOnline = appState.cortexStatus.connected && appState.cortexStatus.authorized;

  if (elements.cortexDot) {
    elements.cortexDot.className = `status-dot ${isOnline ? 'dot-online' : 'dot-offline'}`;
  }
  if (elements.cortexStatusText) {
    elements.cortexStatusText.textContent = isOnline ? 'CONNECTED (6868)' : 'DISCONNECTED';
    elements.cortexStatusText.style.color = isOnline ? 'var(--accent-green)' : 'var(--accent-red)';
  }
  if (elements.cortexDiagBadge) {
    elements.cortexDiagBadge.textContent = isOnline ? 'Status: Active Session' : 'Status: Ready to Connect';
  }
}

function syncConfigUI() {
  if (elements.thresholdLine) elements.thresholdLine.style.left = `${Math.round(appState.config.powerThreshold * 100)}%`;
  if (elements.cfgThreshold) elements.cfgThreshold.value = appState.config.powerThreshold;
  if (elements.valThreshold) elements.valThreshold.innerText = appState.config.powerThreshold;
  if (elements.cfgDebounce) elements.cfgDebounce.value = appState.config.debounceMs;
  if (elements.valDebounce) elements.valDebounce.innerText = `${appState.config.debounceMs} ms`;
  if (elements.cfgSingleFire) elements.cfgSingleFire.value = appState.config.singleFireWindowMs || 1500;
  if (elements.valSingleFire) elements.valSingleFire.innerText = `${appState.config.singleFireWindowMs || 1500} ms`;
  if (elements.cfgComboWindow) elements.cfgComboWindow.value = appState.config.comboWindowMs || 2000;
  if (elements.valComboWindow) elements.valComboWindow.innerText = `${appState.config.comboWindowMs || 2000} ms`;
  if (elements.cfgFramingWindow) elements.cfgFramingWindow.value = (appState.config.framingWindowMs || 4000) / 1000;
  if (elements.valFramingWindow) elements.valFramingWindow.innerText = `${(appState.config.framingWindowMs || 4000) / 1000} s`;
  setFramingDuration((appState.config.framingWindowMs || 4000) / 1000, false);
}

// -------------------------------------------------------------
// 4. TEMPORAL WINDOW FRAMING TIMER
// -------------------------------------------------------------
let framingStartTime = 0;
let framingDurationMs = 4000;

function startFramingTimer(durationMs = 4000, desc = '') {
  framingDurationMs = durationMs;
  framingStartTime = Date.now();

  if (elements.temporalFramingCard) elements.temporalFramingCard.classList.add('holding');
  if (elements.framingStatusPill) {
    elements.framingStatusPill.className = 'framing-status-pill status-holding';
    elements.framingStatusPill.textContent = 'HOLDING FRAME';
  }
  if (elements.btnCancelFraming) elements.btnCancelFraming.style.display = 'inline-block';
  if (desc && elements.framingDescription) elements.framingDescription.innerHTML = desc;

  if (appState.framingTimer) clearInterval(appState.framingTimer);
  appState.framingTimer = setInterval(tickFraming, 40);
}

function tickFraming() {
  const elapsed = Date.now() - framingStartTime;
  const remaining = Math.max(0, framingDurationMs - elapsed);
  const progress = Math.min(1.0, elapsed / framingDurationMs);

  if (elements.framingCountdownText) elements.framingCountdownText.textContent = `${(remaining / 1000).toFixed(1)}s`;
  if (elements.framingCircleFill) {
    const dash = 263.89 * (1.0 - progress);
    elements.framingCircleFill.style.strokeDashoffset = dash;
  }
  if (elements.framingBottomFill) elements.framingBottomFill.style.width = `${progress * 100}%`;

  if (remaining <= 0) {
    stopFramingTimer('EXECUTED');
  }
}

function stopFramingTimer(status = 'STANDBY', reason = '') {
  if (appState.framingTimer) {
    clearInterval(appState.framingTimer);
    appState.framingTimer = null;
  }
  if (elements.temporalFramingCard) elements.temporalFramingCard.classList.remove('holding');
  if (elements.btnCancelFraming) elements.btnCancelFraming.style.display = 'none';

  if (elements.framingStatusPill) {
    if (status === 'EXECUTED') {
      elements.framingStatusPill.className = 'framing-status-pill status-ready';
      elements.framingStatusPill.textContent = 'EXECUTED';
    } else if (status === 'CANCELLED') {
      elements.framingStatusPill.className = 'framing-status-pill status-holding';
      elements.framingStatusPill.textContent = 'ABORTED';
    } else {
      elements.framingStatusPill.className = 'framing-status-pill status-ready';
      elements.framingStatusPill.textContent = 'STANDBY';
    }
  }

  setTimeout(() => {
    if (elements.framingStatusPill && !appState.framingTimer) {
      elements.framingStatusPill.className = 'framing-status-pill status-ready';
      elements.framingStatusPill.textContent = 'STANDBY';
    }
    if (elements.framingCountdownText) elements.framingCountdownText.textContent = `${(framingDurationMs / 1000).toFixed(1)}s`;
    if (elements.framingCircleFill) elements.framingCircleFill.style.strokeDashoffset = '0';
    if (elements.framingBottomFill) elements.framingBottomFill.style.width = '0%';
  }, 1200);
}

function setFramingDuration(sec, notifyServer = true) {
  const s = Math.max(0.5, Math.min(15.0, parseFloat(sec)));
  framingDurationMs = s * 1000;
  if (elements.framingCurrentDuration) elements.framingCurrentDuration.innerText = `${s.toFixed(1)}s`;
  if (elements.framingCardSlider) elements.framingCardSlider.value = s;
  if (elements.framingCountdownText && !appState.framingTimer) elements.framingCountdownText.innerText = `${s.toFixed(1)}s`;

  if (elements.framingPresets) {
    elements.framingPresets.forEach(b => {
      if (parseFloat(b.getAttribute('data-sec')) === s) b.classList.add('active');
      else b.classList.remove('active');
    });
  }

  if (notifyServer && appState.ws && appState.ws.readyState === WebSocket.OPEN) {
    appState.ws.send(JSON.stringify({ type: 'update_config', payload: { framingWindowMs: framingDurationMs } }));
  }
}

function cancelFraming() {
  if (appState.ws && appState.ws.readyState === WebSocket.OPEN) {
    appState.ws.send(JSON.stringify({ type: 'cancel_framing' }));
  }
  stopFramingTimer('CANCELLED', 'User Aborted');
  addLog('GESTURE', 'warn', 'Temporal Window Aborted via PUSH + PULL Gesture');
}

// -------------------------------------------------------------
// 5. INTERACTIVE SIMULATOR & KEYBOARD HANDLERS
// -------------------------------------------------------------
function sendSimulatedCommand(action) {
  const power = parseFloat(elements.simPowerSlider ? elements.simPowerSlider.value : 0.85);
  updateTelemetryUI({ action: action.toUpperCase(), power: power });

  if (appState.ws && appState.ws.readyState === WebSocket.OPEN) {
    appState.ws.send(JSON.stringify({
      type: 'cortex_com',
      payload: { action: action.toLowerCase(), power: power, simulated: true }
    }));
  }
  addLog('SIMULATOR', 'info', `Dispatched Mental Command: ${action.toUpperCase()} (${Math.round(power * 100)}% power)`);
}

function triggerSimCombo() {
  cancelFraming();
}

function addLog(source, level, message) {
  if (!elements.consoleBody) return;
  const time = new Date().toTimeString().split(' ')[0];
  const row = document.createElement('div');
  row.className = `log-entry log-${level}`;
  row.innerHTML = `<span class="log-time">[${time}]</span><span class="log-source">[${source}]</span><span>${message}</span>`;
  elements.consoleBody.appendChild(row);
  elements.consoleBody.scrollTop = elements.consoleBody.scrollHeight;
}

// -------------------------------------------------------------
// 6. EVENT LISTENERS & INITIALIZATION
// -------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
  init3DStageCube();
  initEEGVisualizer();
  initWebSocket();

  // Simulator Buttons
  if (elements.simButtons) {
    elements.simButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        const action = btn.getAttribute('data-action');
        if (action) sendSimulatedCommand(action);
      });
    });
  }

  if (elements.simPushPullCombo) {
    elements.simPushPullCombo.addEventListener('click', triggerSimCombo);
  }

  if (elements.simPowerSlider && elements.simPowerLabel) {
    elements.simPowerSlider.addEventListener('input', (e) => {
      elements.simPowerLabel.innerText = `${Math.round(e.target.value * 100)}%`;
    });
  }

  // Framing Presets & Controls
  if (elements.framingPresets) {
    elements.framingPresets.forEach(btn => {
      btn.addEventListener('click', () => {
        setFramingDuration(btn.getAttribute('data-sec'), true);
      });
    });
  }

  if (elements.btnFramingDec) elements.btnFramingDec.addEventListener('click', () => setFramingDuration(framingDurationMs / 1000 - 0.5, true));
  if (elements.btnFramingInc) elements.btnFramingInc.addEventListener('click', () => setFramingDuration(framingDurationMs / 1000 + 0.5, true));
  if (elements.framingCardSlider) elements.framingCardSlider.addEventListener('input', (e) => setFramingDuration(e.target.value, true));
  if (elements.btnCancelFraming) elements.btnCancelFraming.addEventListener('click', cancelFraming);
  if (elements.btnFramingPushPull) elements.btnFramingPushPull.addEventListener('click', cancelFraming);

  // Clear Log
  if (elements.btnClearLog) {
    elements.btnClearLog.addEventListener('click', () => {
      if (elements.consoleBody) elements.consoleBody.innerHTML = '';
    });
  }

  // Modal Dialogs
  if (elements.openSettingsBtn) elements.openSettingsBtn.addEventListener('click', () => elements.settingsModal.classList.add('active'));
  if (elements.cortexBadge) elements.cortexBadge.addEventListener('click', () => elements.settingsModal.classList.add('active'));
  if (elements.closeSettingsBtn) elements.closeSettingsBtn.addEventListener('click', () => elements.settingsModal.classList.remove('active'));

  if (elements.modalTabs) {
    elements.modalTabs.forEach(tab => {
      tab.addEventListener('click', () => {
        elements.modalTabs.forEach(t => t.classList.remove('active'));
        elements.tabContents.forEach(c => c.classList.remove('active'));
        tab.classList.add('active');
        const target = document.getElementById(tab.getAttribute('data-tab'));
        if (target) target.classList.add('active');
      });
    });
  }

  // Keyboard Shortcuts
  window.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
    const k = e.key.toLowerCase();
    if (k === 'w' || k === 'arrowup') sendSimulatedCommand('push');
    else if (k === 's' || k === 'arrowdown') sendSimulatedCommand('pull');
    else if (k === 'a' || k === 'arrowleft') sendSimulatedCommand('left');
    else if (k === 'd' || k === 'arrowright') sendSimulatedCommand('right');
    else if (k === ' ' || k === 'space') sendSimulatedCommand('neutral');
    else if (k === 'x') triggerSimCombo();
    else if (k === 'escape') cancelFraming();
  });
});
