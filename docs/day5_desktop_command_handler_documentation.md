# Day 5 – Desktop Command Handler Documentation

## 1. Member 1 Responsibility
As **Member 1 (Desktop Command Handler)**, the responsibility is strictly confined to the **Routing and Validation Layer** within the Desktop Domain of SynaptiMesh.

Member 1 serves as the gatekeeper between incoming high-level system commands and the application-specific subplugins.

```
Incoming Unified Command
           ↓
Desktop Command Handler (Member 1: Routing + Validation)
           ↓
Target Subplugin Identification & Validation (Chrome / YouTube / Notepad / Email)
           ↓
Application Automation Execution (Member 2: Selenium / PyAutoGUI / Handlers)
```

---

## 2. Desktop Command Handler Purpose
The Desktop Command Handler:
- Accepts desktop domain commands and payloads.
- Validates the structural integrity of incoming requests.
- Maps application targets in a case-insensitive, normalized manner.
- Verifies that target subplugins are registered and loaded in the subplugin registry.
- Pre-validates incoming commands against the subplugin's actual `COMMANDS` definition before forwarding.
- Forwards valid actions asynchronously to the target subplugin without blocking.
- Isolates errors and exceptions so subplugin failures never crash the Master Hub.
- Returns predictable, structured success and error responses.

---

## 3. Input Format
Commands to the Desktop Command Handler follow the standard SynaptiMesh plugin execution convention:

```python
await desktop_plugin.execute(command, payload)
```

### Example Payload:
```json
{
  "domain": "DESKTOP",
  "app": "CHROME",
  "confidence": 0.95,
  "source": "BCI"
}
```

### Parameters:
- `command` (*str*): The specific application command (e.g., `"open_search_bar"`).
- `payload` (*dict*): Metadata dictionary containing at minimum the `"app"` field indicating the target application.

---

## 4. Input Validation & Error Boundaries
The handler validates inputs across multiple checkpoints before attempting any delegation:

1. **Special Commands**:
   - `command == "get_widgets"`: Directly aggregates widgets from registered subplugins and returns `{"status": "success", "widgets": [...]}`.
2. **Command Validation**:
   - Verifies `command` is a non-empty string.
   - Rejects missing, empty, or non-string commands with structured error.
3. **Payload Validation**:
   - Rejects `None` payload.
   - Rejects non-dictionary payloads (e.g., strings, lists, numbers).
4. **Application Validation**:
   - Verifies `"app"` key exists in `payload`.
   - Verifies `payload["app"]` is a non-empty string.
   - Normalizes application strings case-insensitively (e.g., `"chrome"` -> `"CHROME"`).
   - Rejects unsupported applications (e.g., `"SPOTIFY"`) with a clear error listing supported applications.
5. **Subplugin Registration Check**:
   - Verifies the resolved subplugin identifier exists in `self.subplugins`.
   - If not loaded, returns `{"status": "error", "app": app, "command": command, "message": "Subplugin for <app> not found"}`.
6. **Command Pre-Validation**:
   - Inspects the target subplugin's actual `COMMANDS` list:
     - **Chrome**: `open_predefined_article`, `scroll_up`, `scroll_down`, `open_search_bar`, `close_app`
     - **YouTube**: `previous_video`, `next_video`, `toggle_play_pause`, `search`, `close_app`, `volume_up`, `volume_down`
     - **Notepad**: `open_notepad`, `save_file`, `close_app`
     - **Email**: `compose_email`, `send_email`, `close_app`
   - Rejects unknown commands before forwarding, preventing unnecessary subplugin invocation.
7. **Exception Boundary**:
   - Subplugin execution is wrapped in a `try...except Exception` block.
   - Exceptions are logged with full traceback without crashing the Master Hub.

---

## 5. Application Routing Mapping
The Desktop Command Handler maintains the existing registry mapping:

| Input Application Identifier (`app`) | Target Subplugin (`subplugins`) | Subplugin Class |
| :--- | :--- | :--- |
| `CHROME` (or `chrome`) | `chrome` | `ChromePlugin` |
| `YOUTUBE` (or `youtube`) | `youtube` | `YoutubePlugin` |
| `NOTEPAD` (or `notepad`) | `notepad` | `NotepadPlugin` |
| `GMAIL` / `EMAIL` (or `gmail`/`email`) | `email` | `EmailPlugin` |

---

## 6. Response Contract

### Success Response:
```json
{
  "status": "success",
  "app": "CHROME",
  "command": "open_search_bar",
  "message": "Chrome: Search bar focused",
  "result": {
    "status": "success",
    "message": "Chrome: Search bar focused"
  }
}
```

### Error Response:
```json
{
  "status": "error",
  "app": "CHROME",
  "command": "invalid_command",
  "message": "Unknown or unsupported command 'invalid_command' for application 'CHROME'. Supported commands: ['open_predefined_article', 'scroll_up', 'scroll_down', 'open_search_bar', 'close_app']"
}
```

---

## 7. Interaction with Existing Subplugins
The handler preserves the subplugin architecture:
- Subplugins implement `DesktopPluginInterface`.
- Subplugins provide their own `COMMANDS` definition in `commands.py`.
- Execution is delegated via `await subplugin.execute(command, payload)`.
- The handler preserves backward compatibility for existing callers including `EcosystemOrchestrator` and `YouTubeProvider`.

---

## 8. What is Intentionally NOT Handled by Member 1
In accordance with task constraints and architecture boundaries:
1. **No Application Automation**: Selenium browser drivers, PyAutoGUI keyboard/mouse automation, and OS process launching belong strictly to Member 2 and individual subplugins.
2. **No Media Coordination**: Audio/video stream management, JioSaavn providers, and MediaManager logic reside in `plugins/media/`.
3. **No Embedded / IoT / BCI Logic**: Hardware protocols, MQTT messaging, serial communication, and Cortex BCI streaming remain untouched in their respective modules.
