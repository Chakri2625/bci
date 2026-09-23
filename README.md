# SynaptiMesh – BCI Desktop Automation Architecture

## 1. Project Overview
**SynaptiMesh** is a modular, plugin-based automation framework designed to translate Brain-Computer Interface (BCI) commands into direct operating system actions. 

Currently, the project is in the **Manual BCI Simulator Phase**. Users input commands (`PUSH`, `PULL`, `LEFT`, `RIGHT`) via a futuristic dashboard. In the future phase, this manual input will be replaced by an ML-driven server parsing real EEG telemetry. The architecture is strictly plugin-based and state-driven, allowing for seamless integration of new applications and devices without touching the core routing logic.

## 2. High-Level Architecture
The command source is highly pluggable, ensuring that the execution pipeline remains completely agnostic to whether a command comes from a human click or a machine learning inference engine.

```text
Headset (future)
       |
   ML Server (future)
       |
Manual Dashboard (current)
       |
POST /api/v1/bci/command
       |
Rule Router
       |
State Manager
       |
Desktop Router
       |
Subplugin
       |
OS Automation
```

## 3. Folder Structure
```text
SynaptiMesh/
├── config/             # Configuration yaml files (e.g., app.yaml, plugins.yaml)
├── core/               # Unmodified system microkernel
│   ├── communication/  # API endpoints and pluggable command sources
│   ├── events/         # Event bus (for future async messaging)
│   ├── logging/        # Centralized system logger
│   ├── plugin_manager/ # Discovers, loads, and executes plugins dynamically
│   ├── queue/          # Task queueing for background automation
│   └── routing/        # Rules engines for translating commands into actions
│   └── state/          # Central in-memory state tracking
├── data/               # Ephemeral and runtime data (logs, cache, state dumps)
├── docs/               # System documentation
├── plugin_sdk/         # Interfaces and manifest loaders for strict plugin contracts
├── plugins/            # The automation boundary
│   ├── aiml/
│   ├── desktop/        # The primary domain router for PC automation
│   │   ├── shared/     # Utilities shared across desktop plugins (e.g. PyAutoGUI helpers)
│   │   ├── subplugins/ # Isolated lightweight automation targets (Chrome, YouTube, etc.)
│   │   └── ui/         # The FastAPI + JS Glassmorphism Simulator Dashboard
│   ├── embedded/
│   └── iot/
└── scripts/            # Development utilities (e.g. plugin scaffolds)
```

## 4. What Each Important File Does

| File | Responsibility |
| :--- | :--- |
| `main.py` | Entry point. Bootstraps FastAPI, initializes plugins, and mounts UI. |
| `api_server.py` | Exposes the single universal entry point `/api/v1/bci/command`. |
| `rule_router.py` | Evaluates current state and input commands to determine transitions or actions. |
| `state_manager.py` | Stores the active session context (Level, Domain, App, History). |
| `desktop/plugin.py` | The strict parent router. Forwards requests to the appropriate subplugin. |
| `desktop/registry.py` | Discovers and loads the dynamic subplugins. |
| `handlers.py` | Contains the actual OS automation logic (e.g. `pyautogui` or `subprocess`). |
| `widget.py` | Defines the UI actions exposed to the dashboard for that specific app. |
| `services.py` | Centralized OS-level helpers (e.g., `focus_window`, `open_url`). |

## 5. Three-Level Command Hierarchy

### LEVEL 1 – Domain Selection
| Command | Target |
| :--- | :--- |
| `PUSH` | `PYTHON` |
| `PULL` | `EMBEDDED` |
| `LEFT` | `IOT` |
| `RIGHT` | `AIML` |

### LEVEL 2 – Application Selection
| Command | Target |
| :--- | :--- |
| `PUSH` | `YOUTUBE` |
| `PULL` | `CHROME` |
| `LEFT` | `NOTEPAD` |
| `RIGHT` | `GMAIL` |

### LEVEL 3 – Internal Actions
| Application | PUSH | PULL | LEFT | RIGHT |
| :--- | :--- | :--- | :--- | :--- |
| **YouTube** | Previous Video | Next Video | Play/Pause | Search |
| **Chrome** | Open Article | Scroll Up | Scroll Down | Open Search Bar |
| **Notepad** | Open Notepad | Save File | - | - |
| **Gmail** | Compose Email | Send Email | - | - |

## 6. Global Navigation
| Action | Combination | Result |
| :--- | :--- | :--- |
| **BACK** | `PUSH` + `LEFT` | Retreats one level. Clears Active App (L3→L2) or Active Domain (L2→L1). |
| **HOME** | `PUSH` + `RIGHT`| Resets completely to Level 1. Clears App and Domain. |

## 7. State Machine
The system relies on a rigid, predictable state loop.
- `active_domain`: e.g. `PYTHON`
- `active_app`: e.g. `YOUTUBE`
- `current_level`: 1, 2, or 3
- `last_command`: e.g. `PUSH`
- `last_resolved_action`: e.g. `toggle_play_pause`
- `command_history`: Rolling list of all received commands.

## 8. Data Flow

### Current Manual Flow
1. User clicks `PUSH` on the dashboard.
2. Dashboard `fetch()` POSTs to API.
3. API pushes command through `Rule Router`.
4. Router updates `State`.
5. Router invokes `Desktop Plugin` (if Level 3 Action).
6. Plugin forwards to `Subplugin Handler`.
7. Handler performs OS Automation.
8. UI polls `/api/v1/state` and updates visually.

### Future ML Flow
1. Headset transmits EEG telemetry.
2. ML Server decodes intent into `PUSH`.
3. ML Server POSTs to the EXACT same API.
4. (The rest of the pipeline remains entirely unmodified).

## 9. Dashboard Architecture
The BCI Simulator UI (`index.html`) relies on a 3-panel dynamic glassmorphism layout:
- **Left Panel:** Domain tracking and active Level indicator.
- **Center Workspace:** Dynamic grid showing contextual mapping targets. Previews execution animations.
- **Right Telemetry:** Real-time state readouts and Manual Control Buttons.
- **Bottom Timeline:** Scrolling history of received commands.
- **Polling:** Lightweight Vanilla JS polls state every **300ms** and widgets every **5s**.

## 10. Plugin Architecture
SynaptiMesh enforces a Parent Router -> Subplugin hierarchy. The `DesktopPlugin` is purely a traffic router. All heavy lifting occurs in completely isolated Subplugins (`youtube`, `browser`, etc.). Subplugins MUST NOT import each other, ensuring high decoupling.

## 11. Developer Workflow
1. Pull latest `main`.
2. Create a feature branch.
3. Edit **ONLY** your assigned subplugin (e.g. `plugins/desktop/subplugins/gmail/`).
4. Run locally to test OS bindings.
5. Create Pull Request for architecture-team review.

## 12. Editable Boundaries

### ALLOWED
- `handlers.py` (Automation logic)
- `commands.py` (Command definitions)
- `services.py` (Shared helpers)
- `state.py` (Local tracking)
- `widget.py` (UI exports)

### NOT ALLOWED
- `core/` (Microkernel)
- `desktop/plugin.py` (Parent Router)
- `desktop/registry.py` (Registry loader)
- `shared/` (Without architecture-team approval)
- `ui/` (Unless assigned frontend task)

## 13. Running the Project
```bash
pip install -r requirements.txt
python main.py
```
Open `http://127.0.0.1:8000` in your browser.

## 14. Testing the Simulator
1. Click **PUSH** on the right panel to select the Python Domain.
2. Click **PUSH** to select the YouTube Application.
3. Click **LEFT** to trigger the Play/Pause OS macro.
4. Click **BACK** to return to Application Selection.
5. Click **HOME** to completely reset the session.

## 15. Future Roadmap
- **Phase 3:** ML Server integration and EEG streaming.
- **Phase 4:** Client/Server structural split (local worker node vs cloud router).
- **Phase 5:** MQTT adapters for IoT smart home integrations.
- **Phase 6:** Embedded device control APIs.
