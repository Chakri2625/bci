(function () {
  function tick() {
    var now = new Date();
    var utc = now.toISOString().slice(11, 19);
    var el = document.getElementById("utcClock");
    if (el) el.textContent = utc + " UTC";
  }

  tick();
  setInterval(tick, 1000);

  // -------------------------------------------------------------------
  // FSM command panel (hierarchical command interpretation)
  // -------------------------------------------------------------------
  var stateEl = document.getElementById("fsmState");
  var logEl = document.getElementById("fsmLog");
  var latestCmdEl = document.getElementById("latestCommand");
  var latestConfEl = document.getElementById("latestConfidence");
  var latestLevelEl = document.getElementById("latestLevel");
  var latestStateEl = document.getElementById("latestState");
  var latestActionEl = document.getElementById("latestAction");
  var latestLatencyEl = document.getElementById("latestLatency");
  var currentStateEl = document.getElementById("currentState");
  var currentStateLabelEl = document.getElementById("currentStateLabel");
  var historyEl = document.getElementById("commandHistory");
  var connected = false;
  var pending = []; // commands clicked before the socket connected
  var historyCount = 0;
  var MAX_HISTORY = 30;

  function setState(state) {
    if (stateEl && state) stateEl.textContent = state;
    if (currentStateEl && state) currentStateEl.textContent = state;
  }

  function setStateLabel(label) {
    if (currentStateLabelEl && label) currentStateLabelEl.textContent = label;
  }

  function log(line) {
    if (!logEl) return;
    var div = document.createElement("div");
    div.textContent = line;
    logEl.insertBefore(div, logEl.firstChild);
    while (logEl.childNodes.length > 40) logEl.removeChild(logEl.lastChild);
  }

  function updateLatestBCI(res) {
    if (!res) return;
    // Use enriched fields from backend: raw_command/command_display, confidence, level, timestamp, latency, action_label
    var cmd = res.raw_command || res.command_display || res.command || "--";
    var conf = res.confidence !== undefined ? Math.round(res.confidence * 100) + "%" : "--";
    var level = res.level !== undefined ? res.level : "--";
    var state = res.new_state || res.state || "--";
    var action = res.action_label || res.message || res.action || "--";
    var latency = res.latency || (res.latency_ms ? res.latency_ms + " ms" : "--");
    var timestamp = res.timestamp || new Date().toLocaleTimeString();

    if (latestCmdEl) latestCmdEl.textContent = cmd;
    if (latestConfEl) latestConfEl.textContent = "Confidence: " + conf;
    if (latestLevelEl) latestLevelEl.textContent = "Level: " + level;
    if (latestStateEl) latestStateEl.textContent = "State: " + state;
    if (latestActionEl) latestActionEl.textContent = "Action: " + action;
    if (latestLatencyEl) latestLatencyEl.textContent = "Latency: " + latency;

    // Add to history (only for accepted commands – backend dedup ensures repeated PUSH only once)
    addToHistory(timestamp, cmd, conf, level, action);
  }

  function addToHistory(timestamp, cmd, conf, level, action) {
    if (!historyEl) return;
    // Remove empty placeholder
    var empty = historyEl.querySelector(".history-empty");
    if (empty) empty.remove();

    var item = document.createElement("div");
    item.className = "history-item";
    var timeDiv = document.createElement("div");
    timeDiv.className = "history-time";
    timeDiv.textContent = timestamp;
    var cmdDiv = document.createElement("div");
    cmdDiv.className = "history-cmd";
    cmdDiv.textContent = cmd;
    var metaDiv = document.createElement("div");
    metaDiv.className = "history-meta";
    metaDiv.textContent = conf + " | Level " + level;
    var actionDiv = document.createElement("div");
    actionDiv.className = "history-action";
    actionDiv.textContent = "→ " + action;

    item.appendChild(timeDiv);
    item.appendChild(cmdDiv);
    item.appendChild(metaDiv);
    item.appendChild(actionDiv);

    historyEl.insertBefore(item, historyEl.firstChild);
    historyCount++;
    while (historyEl.childNodes.length > MAX_HISTORY) {
      historyEl.removeChild(historyEl.lastChild);
      historyCount--;
    }
  }

  // The Werkzeug dev server cannot upgrade to WebSocket, so python-engineio
  // intentionally answers the upgrade with a 500 and the browser falls back to
  // long-polling. Using polling-only avoids that 500 and its silent command
  // loss window during page load.
  var socket = io("/master", {
    transports: ["polling"],
    reconnection: true,
    reconnectionDelay: 500,
    reconnectionDelayMax: 2000,
  });

  function setConnected(state) {
    connected = state;
    var panel = document.querySelector(".fsm-panel");
    if (panel) panel.classList.toggle("fsm-offline", !state);
    var btn = document.querySelectorAll(".fsm-btn[data-cmd]");
    btn.forEach(function (b) {
      b.classList.toggle("fsm-disabled", !state);
    });
  }

  socket.on("connect", function () {
    setConnected(true);
    log("[CONNECTED] FSM panel linked to /master namespace");
    // Flush anything clicked while the socket was still connecting.
    pending.forEach(function (cmd) {
      socket.emit("manual_command", { raw_command: cmd, confidence: 0.95 });
      log("[QUEUED] flushed command: " + cmd);
    });
    pending = [];
  });

  socket.on("disconnect", function () {
    setConnected(false);
    log("[DISCONNECTED] reconnecting...");
  });

  socket.on("fsm_state_update", function (data) {
    if (data) {
      setState(data.current_state);
      setStateLabel(data.state_label || data.current_state);
      log("[STATE] " + (data.state_label || data.current_state) + (data.target_device ? " · target=" + data.target_device : ""));
      // Update Current FSM State card
      if (currentStateEl) currentStateEl.textContent = data.current_state;
      if (currentStateLabelEl) currentStateLabelEl.textContent = data.state_label || data.current_state;
    }
  });

  socket.on("fsm_command_result", function (res) {
    if (res) {
      log("[COMMAND] " + (res.raw_command || res.command) + " -> " + (res.action_label || res.message));
      // Update Latest BCI Command and History (only for accepted commands, dedup already handled backend)
      updateLatestBCI(res);
      // An "open" action means the dashboard was activated: navigate to it.
      if (res.action === "open_mobile_dashboard") {
        window.location.href = "/mobile";
      } else if (res.action === "open_desktop_dashboard") {
        window.location.href = "/desktop";
      }
    }
  });

  var buttons = document.querySelectorAll(".fsm-btn[data-cmd]");
  buttons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      var cmd = btn.dataset.cmd;
      if (connected) {
        socket.emit("manual_command", { raw_command: cmd, confidence: 0.95 });
      } else {
        pending.push(cmd);
        log("[QUEUED] socket not ready, holding: " + cmd);
      }
    });
  });

  var startBtn = document.getElementById("fsmStart");
  if (startBtn) {
    startBtn.addEventListener("click", function () {
      fetch("/api/fsm/start_automation", { method: "POST" })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.status === "success") {
            log("[ACTION] Start Automation -> " + data.device + " dashboard opened");
            setState(data.fsm.current_state);
            window.location.href = data.url;
          } else {
            log("[ERROR] " + data.message);
          }
        });
    });
  }

  var resetBtn = document.getElementById("fsmReset");
  if (resetBtn) {
    resetBtn.addEventListener("click", function () {
      fetch("/api/fsm/reset", { method: "POST" })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          setState(data.fsm.current_state);
          log("[RESET] FSM -> " + data.fsm.current_state);
        });
    });
  }

  // Load initial FSM state on page load.
  fetch("/api/fsm/state")
    .then(function (r) { return r.json(); })
    .then(function (data) {
      setState(data.fsm.current_state);
      setStateLabel(data.fsm.state_label || data.fsm.current_state);
      if (currentStateEl) currentStateEl.textContent = data.fsm.current_state;
      if (currentStateLabelEl) currentStateLabelEl.textContent = data.fsm.state_label || data.fsm.current_state;
    });

  window.returnToMasterHub = function (e) {
    if (e) e.preventDefault();
    Promise.allSettled([
      fetch("/api/fsm/back", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ level: 1 }) }),
      fetch("/api/fsm/reset", { method: "POST" }),
      fetch("/api/v1/state/reset?session=default", { method: "POST" })
    ]).finally(function () {
      window.location.href = "/";
    });
  };
})();