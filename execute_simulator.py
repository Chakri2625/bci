import os
from pathlib import Path

base_dir = Path(__file__).parent

files = {
    # RULE ROUTER
    "core/routing/rule_router.py": """def resolve_command(command, state):
    level = state.get("current_level", 1)
    domain = state.get("active_domain")
    app = state.get("active_app")

    if level == 1:
        domain_map = {"PUSH": "PYTHON", "PULL": "EMBEDDED", "LEFT": "IOT", "RIGHT": "AIML"}
        if command in domain_map:
            return {"type": "transition", "level": 2, "domain": domain_map[command], "app": None}
            
    elif level == 2 and domain == "PYTHON":
        app_map = {"PUSH": "YOUTUBE", "PULL": "CHROME", "LEFT": "NOTEPAD", "RIGHT": "GMAIL"}
        if command in app_map:
            return {"type": "transition", "level": 3, "domain": domain, "app": app_map[command]}

    elif level == 3 and domain == "PYTHON" and app is not None:
        action_map = {
            "YOUTUBE": {"PUSH": "previous_video", "PULL": "next_video", "LEFT": "toggle_play_pause", "RIGHT": "search"},
            "CHROME": {"PUSH": "open_predefined_article", "PULL": "scroll_up", "LEFT": "scroll_down", "RIGHT": "open_search_bar"},
            "NOTEPAD": {"PUSH": "open_notepad", "PULL": "save_file"},
            "GMAIL": {"PUSH": "compose_email", "PULL": "send_email"}
        }
        app_actions = action_map.get(app, {})
        if command in app_actions:
            return {"type": "action", "level": 3, "domain": domain, "app": app, "action": app_actions[command]}

    return {"type": "no_action"}

def navigate_back(state):
    level = state.get("current_level", 1)
    if level == 3:
        return {"current_level": 2, "active_app": None, "last_resolved_action": None}
    elif level == 2:
        return {"current_level": 1, "active_domain": None, "active_app": None, "last_resolved_action": None}
    return {}

def navigate_home(state):
    return {"current_level": 1, "active_domain": None, "active_app": None, "last_resolved_action": None}
""",
    # API SERVER
    "core/communication/api_server.py": """from fastapi import APIRouter
from pydantic import BaseModel
from typing import Any, Optional
from core.plugin_manager.manager import get_all_plugins, execute
from core.state.state_manager import state_manager
from core.routing.rule_router import resolve_command, navigate_back, navigate_home

router = APIRouter(prefix="/api/v1")

class BCICommandRequest(BaseModel):
    command: str

@router.get("/state")
def get_state(session: str = "default"):
    return state_manager.get_state(session)

@router.post("/bci/command")
async def process_bci_command(request: BCICommandRequest, session: str = "default"):
    cmd = request.command.upper()
    state_manager.add_command(session, cmd)
    state = state_manager.get_state(session)
    
    resolution = resolve_command(cmd, state)
    result = {"status": "success", "resolved": resolution, "executed": False}
    
    if resolution["type"] == "transition":
        state_manager.update_state(session, {
            "current_level": resolution["level"],
            "active_domain": resolution["domain"],
            "active_app": resolution["app"],
            "last_resolved_action": None
        })
    elif resolution["type"] == "action":
        action_res = await execute("desktop", resolution["action"], {"domain": resolution["domain"], "app": resolution["app"]})
        result["action_result"] = action_res
        result["executed"] = True
        state_manager.update_state(session, {
            "last_resolved_action": resolution["action"]
        })
    else:
        result["status"] = "no_action"
        
    result["state"] = state_manager.get_state(session)
    return result

@router.post("/bci/back")
async def process_bci_back(session: str = "default"):
    state_manager.add_command(session, "BACK (PUSH+LEFT)")
    state = state_manager.get_state(session)
    updates = navigate_back(state)
    if updates:
        state_manager.update_state(session, updates)
    return {"status": "success", "state": state_manager.get_state(session)}

@router.post("/bci/home")
async def process_bci_home(session: str = "default"):
    state_manager.add_command(session, "HOME (PUSH+RIGHT)")
    state = state_manager.get_state(session)
    updates = navigate_home(state)
    state_manager.update_state(session, updates)
    return {"status": "success", "state": state_manager.get_state(session)}

@router.get("/widgets")
async def get_widgets():
    res = await execute("desktop", "get_widgets", None)
    return res

def setup_routes(app):
    app.include_router(router)
""",
    # UI
    "plugins/desktop/ui/templates/index.html": """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SynaptiMesh BCI Simulator</title>
    <style>
        :root {
            --bg-base: #0f172a;
            --glass-bg: rgba(30, 41, 59, 0.7);
            --glass-border: rgba(255, 255, 255, 0.1);
            --neon-blue: #38bdf8;
            --neon-purple: #c084fc;
            --neon-green: #4ade80;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
        }

        body, html {
            margin: 0; padding: 0;
            font-family: 'Inter', 'Segoe UI', sans-serif;
            background: radial-gradient(circle at center, #1e293b 0%, var(--bg-base) 100%);
            color: var(--text-main);
            height: 100vh;
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }

        .top-bar {
            height: 60px;
            background: rgba(0,0,0,0.4);
            border-bottom: 1px solid var(--glass-border);
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 30px;
        }
        
        .top-bar .title { font-size: 1.2rem; font-weight: bold; letter-spacing: 1px; color: var(--neon-blue); }
        .top-bar .status { display: flex; align-items: center; gap: 10px; color: var(--neon-green); font-size: 0.9rem; font-weight: bold; }
        .pulse-dot { width: 10px; height: 10px; background: var(--neon-green); border-radius: 50%; box-shadow: 0 0 10px var(--neon-green); animation: pulse 1s infinite alternate; }

        .glass-panel {
            background: var(--glass-bg);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid var(--glass-border);
            border-radius: 16px;
            box-shadow: 0 4px 30px rgba(0, 0, 0, 0.5);
        }

        .main-layout {
            display: flex;
            flex: 1;
            padding: 20px;
            gap: 20px;
            height: calc(100vh - 180px);
        }

        /* LEFT PANEL */
        .panel-left { width: 250px; display: flex; flex-direction: column; padding: 20px; }
        .panel-title { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 2px; color: var(--text-muted); margin-bottom: 20px; border-bottom: 1px solid var(--glass-border); padding-bottom: 10px; }
        .domain-card { padding: 15px; margin-bottom: 10px; border-radius: 8px; background: rgba(255,255,255,0.03); border: 1px solid transparent; transition: all 0.3s ease; }
        .domain-card.active { background: rgba(56, 189, 248, 0.1); border-color: var(--neon-blue); box-shadow: 0 0 15px rgba(56, 189, 248, 0.3); transform: scale(1.02); }
        .domain-card.active h3 { color: var(--neon-blue); margin:0;}
        .domain-card h3 { margin: 0; font-size: 1rem; }

        /* CENTER PANEL */
        .panel-center { flex: 1; display: flex; flex-direction: column; position: relative; overflow-y: auto; }
        .workspace-content { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 20px; }
        .level-prompt { font-size: 2rem; font-weight: 300; margin-bottom: 30px; animation: pulseText 2s infinite alternate; text-align: center;}
        
        .bci-mapping-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; width: 100%; max-width: 500px; }
        .mapping-card { background: rgba(255,255,255,0.05); border: 1px solid var(--glass-border); padding: 15px; border-radius: 12px; text-align: center; transition: all 0.3s; }
        .mapping-card .cmd-label { color: var(--neon-purple); font-weight: bold; font-size: 1.1rem; margin-bottom: 5px; }
        .mapping-card .action-label { font-size: 1rem; text-transform: capitalize; }
        .mapping-card.flash { animation: flashNeon 0.5s ease-out; }

        .preview-area { margin-top: 30px; padding: 20px; background: rgba(0,0,0,0.3); border-radius: 12px; width: 100%; max-width: 500px; text-align: center; border: 1px dashed var(--glass-border); min-height: 80px; display: flex; align-items: center; justify-content: center; font-size: 1.2rem; color: var(--neon-green); font-weight: bold; }
        .preview-area.flash { animation: flashNeonGreen 0.5s ease-out; }

        /* RIGHT PANEL */
        .panel-right { width: 300px; padding: 20px; display: flex; flex-direction: column; gap: 15px; }
        .telemetry-item { background: rgba(0,0,0,0.2); padding: 12px 15px; border-radius: 8px; display: flex; flex-direction: column; }
        .telemetry-label { font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; }
        .telemetry-val { font-size: 1rem; font-weight: 600; color: var(--neon-green); margin-top: 5px; word-wrap: break-word; }

        /* MANUAL CONTROL PANEL */
        .manual-controls { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 20px; border-top: 1px solid var(--glass-border); padding-top: 20px;}
        .bci-btn { background: rgba(192, 132, 252, 0.1); border: 1px solid var(--neon-purple); color: var(--neon-purple); padding: 15px; border-radius: 8px; font-weight: bold; font-size: 1.1rem; cursor: pointer; transition: all 0.2s; text-align: center;}
        .bci-btn:hover { background: var(--neon-purple); color: #fff; box-shadow: 0 0 15px var(--neon-purple); transform: scale(1.05);}
        .bci-btn:active { transform: scale(0.95); }
        .nav-btn { grid-column: span 1; background: rgba(255,255,255,0.05); border-color: var(--text-muted); color: var(--text-main); }
        .nav-btn:hover { background: var(--text-muted); box-shadow: 0 0 10px var(--text-muted); }

        /* BOTTOM TIMELINE */
        .panel-bottom { height: 60px; margin: 0 20px 20px 20px; padding: 10px 20px; display: flex; align-items: center; overflow-x: auto; gap: 15px; white-space: nowrap; }
        .timeline-entry { background: rgba(255,255,255,0.05); padding: 8px 15px; border-radius: 20px; font-size: 0.85rem; border: 1px solid var(--glass-border); display: inline-flex; align-items: center; gap: 10px; }
        .timeline-cmd { color: var(--neon-purple); font-weight: bold; }
        .timeline-target { color: var(--text-main); }

        /* TOAST */
        .toast { position: fixed; top: 70px; left: 50%; transform: translateX(-50%); background: var(--neon-green); color: #000; padding: 15px 30px; border-radius: 30px; font-weight: bold; box-shadow: 0 5px 20px rgba(74, 222, 128, 0.4); opacity: 0; transition: opacity 0.3s; z-index: 1000; pointer-events: none; }

        @keyframes pulse { from { box-shadow: 0 0 5px var(--neon-green); } to { box-shadow: 0 0 15px var(--neon-green); } }
        @keyframes pulseText { from { text-shadow: 0 0 5px rgba(56, 189, 248, 0.2); } to { text-shadow: 0 0 15px rgba(56, 189, 248, 0.8); } }
        @keyframes flashNeon { 0% { background: rgba(192, 132, 252, 0.8); transform: scale(1.05); } 100% { background: rgba(255,255,255,0.05); transform: scale(1); } }
        @keyframes flashNeonGreen { 0% { background: rgba(74, 222, 128, 0.4); border-color: var(--neon-green); transform: scale(1.02); } 100% { background: rgba(0,0,0,0.3); border-color: var(--glass-border); transform: scale(1); } }
    </style>
</head>
<body>

    <div id="toast" class="toast">Action Executed</div>

    <div class="top-bar">
        <div class="title">SynaptiMesh BCI Simulator</div>
        <div class="status"><div class="pulse-dot"></div> MANUAL MODE</div>
    </div>

    <div class="main-layout">
        <!-- LEFT: DOMAINS -->
        <div class="glass-panel panel-left">
            <div class="panel-title">Domains (Level <span id="ui-lvl">1</span>)</div>
            <div id="domains-list"></div>
        </div>

        <!-- CENTER: WORKSPACE -->
        <div class="glass-panel panel-center">
            <div class="workspace-content" id="workspace">
                <h2 class="level-prompt" id="ws-prompt">Connecting...</h2>
                <div class="bci-mapping-grid" id="ws-grid"></div>
                <div class="preview-area" id="preview-area" style="display:none;"></div>
            </div>
        </div>

        <!-- RIGHT: TELEMETRY & CONTROLS -->
        <div class="glass-panel panel-right">
            <div class="panel-title">Live Telemetry</div>
            <div class="telemetry-item">
                <span class="telemetry-label">Session ID</span>
                <span class="telemetry-val">Manual</span>
            </div>
            <div class="telemetry-item">
                <span class="telemetry-label">Active App</span>
                <span class="telemetry-val" id="tel-app">None</span>
            </div>
            <div class="telemetry-item">
                <span class="telemetry-label">Last Command</span>
                <span class="telemetry-val" style="color:var(--neon-purple)" id="tel-cmd">-</span>
            </div>
            <div class="telemetry-item">
                <span class="telemetry-label">Last Action</span>
                <span class="telemetry-val" style="color:var(--neon-blue)" id="tel-action">-</span>
            </div>
            
            <div class="panel-title" style="margin-top:10px;">BCI Input</div>
            <div class="manual-controls">
                <button class="bci-btn" onclick="sendCommand('PUSH')">PUSH</button>
                <button class="bci-btn" onclick="sendCommand('PULL')">PULL</button>
                <button class="bci-btn" onclick="sendCommand('LEFT')">LEFT</button>
                <button class="bci-btn" onclick="sendCommand('RIGHT')">RIGHT</button>
                <button class="bci-btn nav-btn" onclick="sendBack()">BACK</button>
                <button class="bci-btn nav-btn" onclick="sendHome()">HOME</button>
            </div>
        </div>
    </div>

    <!-- BOTTOM: TIMELINE -->
    <div class="glass-panel panel-bottom" id="timeline"></div>

    <script>
        const elLvl = document.getElementById('ui-lvl');
        const elDomains = document.getElementById('domains-list');
        const elWsPrompt = document.getElementById('ws-prompt');
        const elWsGrid = document.getElementById('ws-grid');
        const elPreview = document.getElementById('preview-area');
        
        const elTelApp = document.getElementById('tel-app');
        const elTelCmd = document.getElementById('tel-cmd');
        const elTelAction = document.getElementById('tel-action');
        const elTimeline = document.getElementById('timeline');
        const toast = document.getElementById('toast');

        let lastStateStr = "";
        let widgets = [];
        let prevHistoryLen = 0;
        let lastExecutedAction = null;

        const allDomains = ["PYTHON", "EMBEDDED", "IOT", "AIML"];

        const lvl1Map = [
            { cmd: "PUSH", target: "PYTHON" },
            { cmd: "PULL", target: "EMBEDDED" },
            { cmd: "LEFT", target: "IOT" },
            { cmd: "RIGHT", target: "AIML" }
        ];

        const lvl2Map = [
            { cmd: "PUSH", target: "YOUTUBE" },
            { cmd: "PULL", target: "CHROME" },
            { cmd: "LEFT", target: "NOTEPAD" },
            { cmd: "RIGHT", target: "GMAIL" }
        ];

        // API CALLS
        async function sendCommand(cmd) {
            await fetch('/api/v1/bci/command', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ command: cmd })
            });
            fetchState(); // Immediate refresh
        }

        async function sendBack() {
            await fetch('/api/v1/bci/back', { method: 'POST' });
            fetchState();
        }

        async function sendHome() {
            await fetch('/api/v1/bci/home', { method: 'POST' });
            fetchState();
        }

        async function fetchWidgets() {
            try {
                const res = await fetch('/api/v1/widgets');
                const data = await res.json();
                if (data.widgets) widgets = data.widgets;
            } catch (e) {}
        }

        function showToast(msg) {
            toast.innerText = msg;
            toast.style.opacity = '1';
            setTimeout(() => { toast.style.opacity = '0'; }, 2000);
        }

        function triggerPreviewAnimation(actionText) {
            elPreview.style.display = 'flex';
            elPreview.innerText = "Executing: " + actionText;
            elPreview.classList.remove('flash');
            void elPreview.offsetWidth; // trigger reflow
            elPreview.classList.add('flash');
            showToast("Action Executed: " + actionText);
        }

        function renderTimeline(history) {
            elTimeline.innerHTML = '';
            history.forEach(cmd => {
                const entry = document.createElement('div');
                entry.className = 'timeline-entry';
                entry.innerHTML = `<span class="timeline-cmd">${cmd}</span> <span class="timeline-target">→ Recv</span>`;
                elTimeline.appendChild(entry);
            });
            elTimeline.scrollLeft = elTimeline.scrollWidth;
        }

        async function fetchState() {
            try {
                const res = await fetch('/api/v1/state');
                const state = await res.json();
                
                const currStateStr = JSON.stringify(state);
                if (currStateStr !== lastStateStr) {
                    updateUI(state);
                    lastStateStr = currStateStr;
                }
            } catch (e) {}
        }

        function updateUI(state) {
            elLvl.innerText = state.current_level;
            elTelApp.innerText = state.active_app || "None";
            elTelCmd.innerText = state.last_command || "-";
            elTelAction.innerText = state.last_resolved_action || "-";
            
            if (state.command_history.length > prevHistoryLen) {
                // Flash mapping card
                const cards = document.querySelectorAll('.mapping-card');
                cards.forEach(c => {
                    const cmdText = state.last_command.split(" ")[0]; // Handle BACK (PUSH+LEFT)
                    if (c.dataset.cmd === cmdText) {
                        c.classList.add('flash');
                        setTimeout(() => c.classList.remove('flash'), 500);
                    }
                });
                
                // Trigger preview if action executed
                if (state.last_resolved_action && state.last_resolved_action !== lastExecutedAction) {
                    triggerPreviewAnimation(state.last_resolved_action);
                    lastExecutedAction = state.last_resolved_action;
                } else if (!state.last_resolved_action) {
                    lastExecutedAction = null;
                    elPreview.style.display = 'none';
                }

                prevHistoryLen = state.command_history.length;
            }

            elDomains.innerHTML = '';
            allDomains.forEach(d => {
                const card = document.createElement('div');
                card.className = 'domain-card' + (state.active_domain === d ? ' active' : '');
                card.innerHTML = `<h3>${d}</h3>`;
                elDomains.appendChild(card);
            });

            renderTimeline(state.command_history);

            elWsGrid.innerHTML = '';
            
            if (state.current_level === 1) {
                elWsPrompt.innerText = "Select a Domain";
                lvl1Map.forEach(m => {
                    elWsGrid.innerHTML += `
                        <div class="mapping-card" data-cmd="${m.cmd}">
                            <div class="cmd-label">${m.cmd}</div>
                            <div class="action-label">${m.target}</div>
                        </div>`;
                });
            } 
            else if (state.current_level === 2) {
                elWsPrompt.innerText = "Select an Application";
                lvl2Map.forEach(m => {
                    elWsGrid.innerHTML += `
                        <div class="mapping-card" data-cmd="${m.cmd}">
                            <div class="cmd-label">${m.cmd}</div>
                            <div class="action-label">${m.target}</div>
                        </div>`;
                });
            }
            else if (state.current_level === 3) {
                const appName = state.active_app.toLowerCase();
                const widget = widgets.find(w => w.id === appName);
                elWsPrompt.innerText = state.active_app + " Active";
                
                if (widget) {
                    const cmds = ["PUSH", "PULL", "LEFT", "RIGHT"];
                    widget.actions.forEach((act, idx) => {
                        const bciCmd = cmds[idx] || "N/A";
                        const friendlyAct = act.replace(/_/g, ' ');
                        elWsGrid.innerHTML += `
                            <div class="mapping-card" data-cmd="${bciCmd}">
                                <div class="cmd-label">${bciCmd}</div>
                                <div class="action-label" style="text-transform:capitalize;">${friendlyAct}</div>
                            </div>`;
                    });
                }
            }
        }

        setInterval(fetchState, 300);
        setInterval(fetchWidgets, 5000);
        
        fetchWidgets().then(fetchState);
    </script>
</body>
</html>
"""
}

for rel_path, content in files.items():
    full_path = os.path.join(base_dir, rel_path.replace("/", os.sep))
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Created/Updated: {full_path}")
