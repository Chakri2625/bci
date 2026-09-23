(function(){
  function tick(){var el=document.getElementById("utcClock");if(el) el.textContent=new Date().toISOString().slice(11,19)+" UTC";}
  tick(); setInterval(tick,1000);
  var stateEl=document.getElementById("fsmState"),
      targetBadge=document.getElementById("targetBadge"), logEl=document.getElementById("fsmLog"), logEl2=document.getElementById("fsmLog2"),
      latestCmdEl=document.getElementById("latestCommand"), latestConfEl=document.getElementById("latestConfidence"),
      latestLevelEl=document.getElementById("latestLevel"), latestStateEl=document.getElementById("latestState"),
      latestActionEl=document.getElementById("latestAction"), latestLatencyEl=document.getElementById("latestLatency"),
      latestTargetEl=document.getElementById("latestTarget"),
      currentStateEl=document.getElementById("currentState"), currentStateLabelEl=document.getElementById("currentStateLabel"),
      currentTargetEl=document.getElementById("currentTarget"), currentLevelEl=document.getElementById("currentLevel"),
      currentActionEl=document.getElementById("currentAction"),
      historyEl=document.getElementById("commandHistory");
  var MAX_HISTORY=30;

  function setState(s,label,target,level){
    if(stateEl && s) stateEl.textContent=s;
    if(currentStateEl && s) currentStateEl.textContent=s;
    if(currentStateLabelEl && label) currentStateLabelEl.textContent=label;
    if(currentTargetEl) currentTargetEl.textContent="Target: "+(target||"none");
    if(latestTargetEl) latestTargetEl.textContent="Target Device: "+(target||"none");
    if(currentLevelEl && level!=null) currentLevelEl.textContent="Level: "+level;
    if(targetBadge){
      targetBadge.textContent="TARGET: "+(target?target.toUpperCase():"NONE");
      targetBadge.className="target-badge "+(target==="mobile"?"":target==="desktop"?"desktop":"none");
    }
    ["lvl1","lvl2","lvl3"].forEach(function(id,i){
      var el=document.getElementById(id);
      if(el){
        el.classList.toggle("active", level===(i+1));
        el.classList.toggle("done", level>(i+1));
        var icon=el.querySelector(".level-icon");
        if(icon) icon.textContent = level>(i+1) ? "✓" : level===(i+1) ? "●" : "○";
      }
    });
    var c1=document.getElementById("conn1"), c2=document.getElementById("conn2");
    if(c1) c1.classList.toggle("active", level>=2);
    if(c2) c2.classList.toggle("active", level>=3);
  }
  function log(line){
    var txt="["+new Date().toLocaleTimeString()+"] "+line;
    [logEl, logEl2].forEach(function(el){
      if(!el) return;
      var d=document.createElement("div"); d.textContent=txt;
      el.insertBefore(d, el.firstChild);
      while(el.childNodes.length>40) el.removeChild(el.lastChild);
    });
  }
  function updateLatest(res){
    if(!res) return;
    var cmd=res.raw_command||res.command_display||res.command||"--";
    var conf=res.confidence!==undefined?Math.round(res.confidence*100)+"%":"--";
    var level=res.level!==undefined?res.level:"--";
    var state=res.new_state||res.state||"--";
    var action=res.action_label||res.message||res.action||"--";
    var latency=res.latency|| (res.latency_ms?res.latency_ms+" ms":"--");
    var target=res.target_device||"--";
    var ts=res.timestamp||new Date().toLocaleTimeString();
    if(latestCmdEl) latestCmdEl.textContent=cmd;
    if(latestConfEl) latestConfEl.textContent=(conf==="--"?"--":conf+" CONFIDENCE");
    if(latestLevelEl) latestLevelEl.textContent="Level: "+level;
    if(latestStateEl) latestStateEl.textContent="FSM State: "+state;
    if(latestActionEl) latestActionEl.textContent=action;
    if(latestLatencyEl) latestLatencyEl.textContent="Latency: "+latency;
    if(latestTargetEl) latestTargetEl.textContent="Target: "+target;
    if(currentActionEl) currentActionEl.textContent="Last Action: "+action;
    addHistory(ts,cmd,conf,level,action);
  }
  function addHistory(ts,cmd,conf,level,action){
    if(!historyEl) return;
    var empty=historyEl.querySelector(".history-empty"); if(empty) empty.remove();
    var item=document.createElement("div"); item.className="history-item";
    var td=document.createElement("div"); td.className="history-time"; td.textContent=ts;
    var cd=document.createElement("div"); cd.className="history-cmd"; cd.textContent=cmd;
    var md=document.createElement("div"); md.className="history-meta"; md.textContent=conf+" | Level "+level;
    var ad=document.createElement("div"); ad.className="history-action"; ad.textContent="→ "+action;
    item.appendChild(td); item.appendChild(cd); item.appendChild(md); item.appendChild(ad);
    historyEl.insertBefore(item, historyEl.firstChild);
    while(historyEl.childNodes.length>MAX_HISTORY) historyEl.removeChild(historyEl.lastChild);
  }

  function updateJiosaavnStatus(data){
    var j = (data && data.jiosaavn) || data;
    if(!j) return;
    var dot=document.getElementById("jiosaavnDot"), txt=document.getElementById("jiosaavnText");
    if(!dot||!txt) return;
    // prefer overall, else per-device based on current target
    var target = (document.getElementById("currentTarget")||{}).textContent || "";
    var dev = target.includes("desktop") ? "desktop" : target.includes("mobile") ? "mobile" : null;
    var entry = dev && j[dev] ? j[dev] : null;
    var status = entry ? entry.status : (j.overall || "idle");
    var msg = entry ? entry.message : status;
    var colors={idle:"#475569",opening:"#f59e0b",ready:"#22c55e",failed:"#ef4444"};
    dot.style.background = colors[status]||colors.idle;
    txt.textContent = (status==="opening"?"Opening...": status==="ready"?"Ready": status==="failed"?"Launch Failed - "+msg : status==="idle"?"Idle":msg);
    if(data && data.device) log("JIOSAAVN "+data.device+" -> "+data.status+" "+(data.message||""));
  }
  var socket=io("/dashboard",{transports:["polling"]});
  socket.on("connect",function(){ log("Connected /dashboard — server push only");});
  socket.on("disconnect",function(){ log("Disconnected, reconnecting...");});
  socket.on("fsm_state_update",function(data){
    if(data){ setState(data.current_state, data.state_label, data.target_device, data.level); log("STATE "+(data.state_label||data.current_state)+" target="+(data.target_device||"none")); }
  });
  socket.on("fsm_command_result",function(res){
    if(res){ log("COMMAND "+(res.raw_command||res.command)+" → "+(res.action_label||res.message)); updateLatest(res); }
  });
  socket.on("jiosaavn_status", function(data){ updateJiosaavnStatus(data); });

  // Single HTTP path only — no socket emit for BCI (avoids duplicate processing)
  function sendBCI(command, confidence){
    var startTime = performance.now();
    var confVal = confidence || 0.95;
    
    // Optimistically show the incoming command in the card immediately
    if(latestCmdEl) latestCmdEl.textContent = command;
    if(latestConfEl) latestConfEl.textContent = Math.round(confVal * 100) + "% CONFIDENCE";
    
    return fetch("/api/bci/command", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({command: command, confidence: confVal})
    })
      .then(function(r){ return r.json(); })
      .then(function(data){
        var elapsed = Math.round(performance.now() - startTime);
        if(latestLatencyEl) latestLatencyEl.textContent = "Latency: " + elapsed + " ms";
        
        if(data.status === "success"){
          log("POST /api/bci/command " + command + " accepted=" + data.accepted);
          if(data.fsm){
            setState(data.fsm.current_state, data.fsm.state_label, data.fsm.target_device, data.fsm.level);
            updateLatest({
              raw_command: command,
              confidence: confVal,
              level: data.fsm.level,
              state: data.fsm.current_state,
              action: data.fsm.last_action || command,
              latency: elapsed + " ms",
              target_device: data.fsm.target_device,
              timestamp: new Date().toLocaleTimeString()
            });
          }
        } else {
          log("ERROR " + data.message);
        }
        return data;
      })
      .catch(function(err){
        log("NETWORK ERROR: " + err);
      });
  }

  // Polling fallback to keep all HUD cards always updated
  function pollState(){
    fetch("/api/fsm/state")
      .then(function(r){ return r.json(); })
      .then(function(d){
        if(d && d.status === "success" && d.fsm){
          setState(d.fsm.current_state, d.fsm.state_label, d.fsm.target_device, d.fsm.level);
          if(d.jiosaavn) updateJiosaavnStatus(d.jiosaavn);
          if(d.volume !== undefined) updateVolume(d);
          if(d.fsm.last_action && currentActionEl) {
            currentActionEl.textContent = "Last Action: " + d.fsm.last_action;
          }
        }
      })
      .catch(function(){});
  }
  setInterval(pollState, 1000);

  // Native WebSocket fallback for immediate updates
  try {
    var wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
    var telemetryWs = new WebSocket(wsProto + "//" + window.location.host + "/ws");
    telemetryWs.onmessage = function(ev) {
      try {
        var msg = JSON.parse(ev.data);
        if(msg.type === "TELEMETRY_UPDATE" || msg.type === "FSM_UPDATE" || msg.type === "COMMAND_EXECUTED"){
          pollState();
        }
      } catch(e){}
    };
  } catch(e){}
  // Raw single commands: send exactly one primitive through Command Window → FSM
  document.querySelectorAll("[data-raw]").forEach(function(btn){
    btn.addEventListener("click",function(){
      var cmd=btn.dataset.raw;
      log("RAW "+cmd+" → POST /api/bci/command");
      sendBCI(cmd,0.95);
    });
  });
  // Ordered doubles: send two separate POSTs sequentially, preserving order
  document.querySelectorAll("[data-raw-double]").forEach(function(btn){
    btn.addEventListener("click",function(){
      var raw=btn.dataset.rawDouble;
      var parts=raw.split("+");
      var c1=parts[0].trim(), c2=parts[1].trim();
      log("RAW DOUBLE "+c1+" + "+c2+" → POST "+c1+" then POST "+c2);
      sendBCI(c1,0.95).then(function(){ setTimeout(function(){ sendBCI(c2,0.95); }, 160); });
    });
  });
  var resetBtn=document.getElementById("fsmReset");
  if(resetBtn) resetBtn.addEventListener("click",function(){
    fetch("/api/fsm/reset",{method:"POST"}).then(function(r){return r.json();}).then(function(d){
      setState(d.fsm.current_state,d.fsm.state_label,d.fsm.target_device,d.fsm.level);
      if(d.jiosaavn) updateJiosaavnStatus({jiosaavn:d.jiosaavn});
      log("FSM reset → "+d.fsm.current_state);
      if(historyEl) historyEl.innerHTML='<div class="history-empty">No commands yet.</div>';
      if(latestCmdEl) latestCmdEl.textContent="Waiting...";
      if(latestActionEl) latestActionEl.textContent="Action: --";
    });
  });
  var neutralBtn=document.getElementById("fsmNeutral");
  if(neutralBtn) neutralBtn.addEventListener("click",function(){ sendBCI("NEUTRAL",0.9).then(function(){ log("NEUTRAL sent — should be ignored, no history");});});
  fetch("/api/fsm/state").then(function(r){return r.json();}).then(function(d){ if(d.fsm) setState(d.fsm.current_state,d.fsm.state_label,d.fsm.target_device,d.fsm.level); if(d.jiosaavn) updateJiosaavnStatus({jiosaavn:d.jiosaavn}); });
  fetch("/api/jiosaavn/status").then(function(r){return r.json();}).then(function(d){ if(d.jiosaavn) updateJiosaavnStatus({jiosaavn:d.jiosaavn}); });

  // --- BCI Replay panel ---
  var replayFileEl=document.getElementById("replayFile"), replaySpeedEl=document.getElementById("replaySpeed"), replayModeEl=document.getElementById("replayMode"),
      replayBtn=document.getElementById("replayBtn"), replayStopBtn=document.getElementById("replayStopBtn"), replayText=document.getElementById("replayText"),
      replayDot=document.getElementById("replayDot"), replayProgressEl=document.getElementById("replayProgress"), replayLogEl=document.getElementById("replayLog"),
      recToggleBtn=document.getElementById("recToggleBtn"), recStatusEl=document.getElementById("recStatus");
  function replayLog(msg){ if(replayLogEl){ var d=document.createElement("div"); d.textContent="["+new Date().toLocaleTimeString()+"] "+msg; replayLogEl.insertBefore(d,replayLogEl.firstChild); while(replayLogEl.childNodes.length>30) replayLogEl.removeChild(replayLogEl.lastChild);} log(msg); }
  function updateReplayStatus(s){
    if(!s) return;
    var status=s.status||s.replay&&s.replay.status||"idle";
    // handle wrapped {replay: {status}}
    if(s.replay) s=s.replay;
    status=s.status||"idle";
    var colors={idle:"#475569",playing:"#00f6ff",completed:"#22c55e",stopped:"#f59e0b",error:"#ef4444"};
    if(replayDot) replayDot.style.background=colors[status]||colors.idle;
    if(replayText) replayText.textContent=status.charAt(0).toUpperCase()+status.slice(1) + (s.error?" - "+s.error:"");
    if(replayProgressEl) {
      var p=s.progress||{}; replayProgressEl.textContent = (p.total? (" "+(p.sent||0)+"/"+p.total+" sent, "+(p.skipped||0)+" skipped") : "");
    }
  }
  function updateRecStatus(s){
    if(!s) return;
    var r=s.recording||s;
    var on=r.is_recording;
    if(recToggleBtn){ recToggleBtn.textContent = on? "● Recording: ON" : "● Recording: OFF"; recToggleBtn.style.background = on? "rgba(34,197,94,0.15)" : ""; recToggleBtn.style.borderColor = on? "rgba(34,197,94,0.4)" : ""; recToggleBtn.style.color = on? "#22c55e" : ""; }
    if(recStatusEl) recStatusEl.textContent = on? (r.current_file_name+" ("+r.event_count+" events)") : "Idle";
  }
  function loadReplayList(){
    fetch("/api/bci/replay/list").then(function(r){return r.json();}).then(function(d){
      var sessions=d.sessions||[];
      if(replayFileEl){
        replayFileEl.innerHTML="";
        if(sessions.length===0){ var o=document.createElement("option"); o.value=""; o.textContent="-- no sessions --"; replayFileEl.appendChild(o); }
        else sessions.forEach(function(s){ var o=document.createElement("option"); o.value=s; o.textContent=s; replayFileEl.appendChild(o); });
      }
      if(d.replay) updateReplayStatus(d.replay);
    });
    fetch("/api/bci/recording/status").then(function(r){return r.json();}).then(function(d){ if(d.recording) updateRecStatus(d); });
    fetch("/api/bci/replay/status").then(function(r){return r.json();}).then(function(d){ if(d.replay) updateReplayStatus(d.replay); });
  }
  if(replayBtn) replayBtn.addEventListener("click", function(){
    var f=replayFileEl&&replayFileEl.value; if(!f){ replayLog("Select a dataset first"); return; }
    var speed=parseFloat(replaySpeedEl.value)||1.0; var realtime=(replayModeEl.value!=="fast");
    replayLog("Replay start "+f+" speed="+speed+" realtime="+realtime);
    fetch("/api/bci/replay/start",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({file:f,speed:speed,realtime:realtime})}).then(function(r){return r.json();}).then(function(d){
      if(d.status==="success"){ replayLog("Replay started "+f); updateReplayStatus(d.replay); } else { replayLog("Replay error "+(d.message||JSON.stringify(d))); updateReplayStatus(d.replay||d); }
    });
  });
  if(replayStopBtn) replayStopBtn.addEventListener("click", function(){
    fetch("/api/bci/replay/stop",{method:"POST"}).then(function(r){return r.json();}).then(function(d){ replayLog("Replay stop"); if(d.replay) updateReplayStatus(d.replay); });
  });
  if(recToggleBtn) recToggleBtn.addEventListener("click", function(){
    fetch("/api/bci/recording/status").then(function(r){return r.json();}).then(function(d){
      var on=d.recording&&d.recording.is_recording;
      var url= on? "/api/bci/recording/stop" : "/api/bci/recording/start";
      fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"}).then(function(r){return r.json();}).then(function(dd){
        updateRecStatus(dd.recording); replayLog(on? "Recording stopped "+(dd.file||"") : "Recording started "+(dd.file||""));
      });
    });
  });
  socket.on("bci_replay_status", function(s){ updateReplayStatus(s); if(s.status==="completed") replayLog("Replay completed"); if(s.status==="error") replayLog("Replay error "+(s.error||"")); });
  socket.on("bci_recording_status", function(s){ updateRecStatus(s); });
  // initial load
  loadReplayList();

  // --- Volume + Window controls ---
  var volPctEl=document.getElementById("volumePct"), volFill=document.getElementById("volumeBarFill"), volSlider=document.getElementById("volumeSlider"),
      volDetail=document.getElementById("volumeDetail"), volSourceEl=document.getElementById("volumeSource"),
      volUpBtn=document.getElementById("volUpBtn"), volDownBtn=document.getElementById("volDownBtn");
  var winSlider=document.getElementById("windowSlider"), winValueEl=document.getElementById("windowValue"),
      winCurrentEl=document.getElementById("windowCurrent"), winGenEl=document.getElementById("windowGen"),
      winPlus=document.getElementById("winPlus"), winMinus=document.getElementById("winMinus");
  function updateVolume(data){
    if(!data) return;
    var v = (data.volume!==undefined? data.volume : (data.config&&data.config.volume));
    if(v===undefined) return;
    v = Math.round(v);
    if(volPctEl) volPctEl.textContent = v+"%";
    if(volFill) volFill.style.width = v+"%";
    if(volSlider) volSlider.value = v;
    if(volDetail) volDetail.textContent = "Updated "+new Date().toLocaleTimeString();
    if(volSourceEl && data.source) volSourceEl.textContent = "source: "+data.source;
  }
  function updateWindow(data){
    if(!data) return;
    var w = data.command_window_seconds;
    if(w===undefined) w = data.window_duration;
    if(w===undefined && data.config) w = data.config.command_window_seconds;
    if(w===undefined && data.fsm) w = data.fsm.command_window_seconds;
    if(w===undefined) return;
    w = parseFloat(w);
    if(winValueEl) winValueEl.textContent = w.toFixed(1)+"s";
    if(winCurrentEl) winCurrentEl.textContent = w.toFixed(1)+"s";
    if(winSlider) winSlider.value = w;
    // also update footer hint
    var foot = document.querySelector(".hub-foot");
    // keep gen if present
    if(data.window_generation!==undefined && winGenEl) winGenEl.textContent = data.window_generation;
    if(data.fsm && data.fsm.window_generation!==undefined && winGenEl) winGenEl.textContent = data.fsm.window_generation;
  }
  socket.on("volume_update", function(d){ updateVolume(d); log("VOLUME "+d.volume+"%"); });
  socket.on("config_update", function(d){ updateWindow(d); updateVolume(d); if(d.command_window_seconds) log("CONFIG window -> "+d.command_window_seconds+"s"); });
  socket.on("fsm_state_update", function(d){ updateWindow(d); });

  function postWindow(val){
    fetch("/api/config",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({command_window_seconds: parseFloat(val)})})
      .then(function(r){return r.json();}).then(function(d){
        if(d.status==="success"){ updateWindow(d.config||d); log("Window set -> "+ (d.config&&d.config.command_window_seconds)+"s"); }
        else log("Window set error "+d.message);
      });
  }
  function postVolume(val){
    fetch("/api/volume",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({volume: parseInt(val)})})
      .then(function(r){return r.json();}).then(function(d){
        if(d.status==="success"){ updateVolume(d); }
        else log("Volume set error "+d.message);
      });
  }
  if(winSlider) winSlider.addEventListener("input", function(){ var v=parseFloat(this.value); if(winValueEl) winValueEl.textContent=v.toFixed(1)+"s"; });
  if(winSlider) winSlider.addEventListener("change", function(){ postWindow(this.value); });
  if(winPlus) winPlus.addEventListener("click", function(){ var cur=parseFloat(winSlider.value)||4.0; var nxt=Math.min(10, cur+0.5); postWindow(nxt); });
  if(winMinus) winMinus.addEventListener("click", function(){ var cur=parseFloat(winSlider.value)||4.0; var nxt=Math.max(0.5, cur-0.5); postWindow(nxt); });
  if(volSlider) volSlider.addEventListener("change", function(){ postVolume(this.value); });
  if(volUpBtn) volUpBtn.addEventListener("click", function(){ var cur=parseInt(volSlider.value)||50; postVolume(Math.min(100, cur+10)); });
  if(volDownBtn) volDownBtn.addEventListener("click", function(){ var cur=parseInt(volSlider.value)||50; postVolume(Math.max(0, cur-10)); });

  // --- Theme Toggle Logic ---
  window.toggleTheme = function() {
    var currentTheme = document.documentElement.getAttribute("data-theme") || "dark";
    var newTheme = currentTheme === "dark" ? "light" : "dark";
    applyTheme(newTheme);
    try { localStorage.setItem("aiml_dashboard_theme", newTheme); } catch(e){}
  };

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    if(theme === "light") {
      document.body.classList.add("light-theme");
    } else {
      document.body.classList.remove("light-theme");
    }
    var icon = document.getElementById("themeIcon");
    var label = document.getElementById("themeLabel");
    if(label) label.textContent = theme.toUpperCase();
    if(icon) {
      if(theme === "light") {
        // Sun icon
        icon.innerHTML = '<circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>';
      } else {
        // Moon icon
        icon.innerHTML = '<path d="M12 3c-4.97 0-9 4.03-9 9s4.03 9 9 9 9-4.03 9-9c0-.46-.04-.92-.1-1.36-.98 1.37-2.58 2.26-4.4 2.26-2.98 0-5.4-2.42-5.4-5.4 0-1.81.89-3.42 2.26-4.4-.44-.06-.9-.1-1.36-.1z"/>';
      }
    }
  }

  // Return to Master Hub handler
  window.returnToMasterHub = function(e) {
    if(e) e.preventDefault();
    Promise.allSettled([
      fetch('/api/fsm/back', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({level: 1}) }),
      fetch('/api/fsm/reset', { method: 'POST' }),
      fetch('/api/v1/state/reset?session=default', { method: 'POST' })
    ]).finally(function() {
      window.location.href = '/';
    });
  };

  // Restore saved theme on load
  var savedTheme = "dark";
  try { savedTheme = localStorage.getItem("aiml_dashboard_theme") || "dark"; } catch(e){}
  applyTheme(savedTheme);

  // initial fetch
  fetch("/api/volume").then(function(r){return r.json();}).then(function(d){ if(d.volume!==undefined) updateVolume(d); });
  fetch("/api/config").then(function(r){return r.json();}).then(function(d){ if(d.config) { updateWindow(d.config); updateVolume(d.config); }});
  fetch("/api/fsm/state").then(function(r){return r.json();}).then(function(d){ if(d.fsm) updateWindow(d.fsm); });
})();
