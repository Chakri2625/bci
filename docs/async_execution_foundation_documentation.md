# Async Execution Foundation — Implementation and Technical Documentation

---

## 1. Introduction

**SynaptiMesh** is a modular Brain-Computer Interface (BCI) automation framework designed to translate mental telemetry and input commands (`PUSH`, `PULL`, `LEFT`, `RIGHT`, `STOP`) into operating system actions, IoT device commands, and embedded hardware operations. 

The purpose of the **Async Execution Foundation** is to establish a non-blocking asynchronous execution mechanism across the backend. In a multi-domain architecture interacting with external peripherals (e.g. HiveMQ MQTT brokers, ESP32 microcontrollers, OS desktop macros via PyAutoGUI, and browser sessions), operations can vary widely in execution time. Without an asynchronous execution model, blocking I/O or long-running synchronous automation tasks stall the FastAPI event loop, delaying API responses, blocking state polling, and risking server responsiveness.

The Async Execution Foundation introduces non-blocking task creation, execution lifecycle tracking, transparent synchronous-to-asynchronous compatibility, and centralized error handling while preserving 100% backward compatibility with all existing plugins, routes, and services.

---

## 2. Existing Architecture

Prior to implementing the Async Execution Foundation, the backend processing pipeline operated along the following pathway:

```text
HTTP Request (POST /api/v1/bci/command)
      │
      ▼
Command Normalization & Sequence Validation
      │
      ▼
Rule Router (resolve_command)
      │
      ▼
Ecosystem Orchestrator
      │
      ▼
Plugin Manager (manager.execute)
      │
      ▼
Domain Plugin (Desktop / Embedded / IoT / AIML)
      │
      ▼
Standard Response / UI State Polling
```

Key observations of the initial architecture:
- `core.plugin_manager.manager.execute` simply issued `await plugin.execute(command, payload)`. If a plugin or handler was synchronous, this raised an `await` type error or blocked the event loop.
- Background tasks in `ecosystem_orchestrator.py` were spawned using unmanaged `asyncio.create_task()`, which left task exceptions unhandled and omitted lifecycle state tracking.
- `core.queue.task_queue.TaskQueue` was a minimal placeholder with an `asyncio.Queue` that lacked status tracking, execution metrics, cancellation, or error propagation.
- `core.events.event_bus.EventBus` directly awaited subscriber callbacks without isolating subscriber exceptions or supporting synchronous callback handlers.

---

## 3. Problem Addressed

The core requirement was to provide a dependable execution foundation that allows commands and background tasks to be dispatched without unnecessarily blocking the main request/routing flow.

Specifically:
1. **Event Loop Stalling**: Synchronous desktop automation routines (e.g. `pyautogui` keypresses, `subprocess.Popen`, window focusing, and file I/O) executed directly in the main async thread, blocking concurrent HTTP request handling and WebSocket/MQTT polling.
2. **Silent Task Failures**: Background coroutines created via unmanaged `asyncio.create_task()` had no lifecycle tracking or done-callbacks. If a background action failed, the exception was lost without state updates.
3. **Lack of Lifecycle Visibility**: Callers and telemetry systems had no structured way to query whether an asynchronous operation was `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`, or `CANCELLED`.
4. **Fragile Event Publishing**: A single failing subscriber callback in `EventBus` could crash the event publishing loop and prevent other subscribers from receiving messages.

---

## 4. Async Execution Design

The implemented Async Execution Foundation provides a clean layer of capabilities embedded directly into the existing modules:

```text
┌─────────────────────────────────────────────────────────────┐
│                      Task Creation                          │
│  (submit_background / enqueue / execute)                    │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                      AsyncTask                              │
│  - Unique ID (UUID) & Name                                  │
│  - Status: QUEUED ➔ RUNNING ➔ COMPLETED / FAILED / CANCELLED│
│  - Timestamps: created_at, started_at, completed_at         │
│  - Captured Result or Error Message                         │
└──────────────────────────────┬──────────────────────────────┘
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
┌───────────────────────┐             ┌───────────────────────┐
│ Coroutine (async def) │             │ Sync Callable (def)   │
│ Awaited in Event Loop │             │ Run via               │
│                       │             │ asyncio.to_thread     │
└───────────────────────┘             └───────────────────────┘
```

- **Task Creation & Scheduling**: Tasks can be enqueued for sequential execution via `task_queue.enqueue(task)` or dispatched immediately as non-blocking background jobs via `task_queue.submit_background(target, *args, **kwargs)`.
- **Hybrid Execution Engine**: Inspects targets using `inspect.iscoroutinefunction`. Coroutines are awaited directly; synchronous callables are offloaded to worker threads using `asyncio.to_thread` to maintain event loop responsiveness.
- **Task Lifecycle**: Each task progresses through explicit states: `QUEUED` ➔ `RUNNING` ➔ `COMPLETED` (or `FAILED` / `CANCELLED`).
- **Error Propagation**: All executions are wrapped in guarded `try...except` blocks. Exceptions are captured, stored in `task.error`, logged via `core.logging.logger`, and returned as structured error dictionaries.
- **Cancellation**: Tasks expose `.cancel()` and `task_queue.cancel_task(task_id)` to cancel pending or running async jobs cleanly.

---

## 5. Detailed Implementation

### 5.1 Plugin Manager Execution Engine
- **File**: `core/plugin_manager/manager.py`
- **Component**: `async def execute(plugin_id, command, payload=None)`
- **Behavior**:
  - Validates plugin presence; returns `{"status": "error", "message": "Plugin not found"}` if missing.
  - Dynamically distinguishes between async coroutine functions (`inspect.iscoroutinefunction`) and synchronous callables.
  - Automatically wraps synchronous plugin calls in `asyncio.to_thread(plugin.execute, command, payload)` to ensure non-blocking operation.
  - Catches any unhandled plugin exceptions, logs the full traceback with `logger.error`, and returns a structured error dictionary.

```python
async def execute(plugin_id, command, payload=None):
    plugin = get_plugin(plugin_id)
    if not plugin:
        logger.warning(f"[PluginManager] Plugin not found: {plugin_id}")
        return {"status": "error", "message": "Plugin not found"}
        
    if not hasattr(plugin, "execute"):
        logger.error(f"[PluginManager] Plugin {plugin_id} does not implement execute method")
        return {"status": "error", "message": f"Plugin {plugin_id} does not implement execute"}

    try:
        if inspect.iscoroutinefunction(plugin.execute):
            return await plugin.execute(command, payload)
        elif callable(plugin.execute):
            result = await asyncio.to_thread(plugin.execute, command, payload)
            if inspect.isawaitable(result):
                result = await result
            return result
        else:
            return {"status": "error", "message": f"Plugin {plugin_id} execute is not callable"}
    except Exception as e:
        logger.error(f"[PluginManager] Error executing command '{command}' on plugin '{plugin_id}': {e}", exc_info=True)
        return {"status": "error", "message": str(e)}
```

---

### 5.2 Task Lifecycle & TaskQueue Engine
- **File**: `core/queue/task_queue.py`
- **Classes**:
  - `TaskStatus(str, Enum)`: Enumerates `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`, and `CANCELLED`.
  - `AsyncTask`: Wraps targets, arguments, lifecycle states, timestamps, results, errors, and cancellation controls.
  - `TaskQueue`: Manages the async queue, background task submission, task lookup registry, and background worker loop.

```python
class AsyncTask:
    def __init__(self, target: Any, args: tuple = (), kwargs: dict = None, name: Optional[str] = None):
        self.id = str(uuid.uuid4())
        self.name = name or f"task_{self.id[:8]}"
        self.target = target
        self.status = TaskStatus.QUEUED
        self.result: Any = None
        self.error: Optional[str] = None
        self.created_at: float = time.time()
        self.started_at: Optional[float] = None
        self.completed_at: Optional[float] = None
        self._asyncio_task: Optional[asyncio.Task] = None
        self._cancel_requested: bool = False

    def cancel(self) -> bool:
        self._cancel_requested = True
        if self._asyncio_task and not self._asyncio_task.done():
            self._asyncio_task.cancel()
            self.status = TaskStatus.CANCELLED
            self.completed_at = time.time()
            return True
        elif self.status == TaskStatus.QUEUED:
            self.status = TaskStatus.CANCELLED
            self.completed_at = time.time()
            return True
        return False
```

- **Important `TaskQueue` Methods**:
  - `enqueue(task)`: Enqueues an `AsyncTask` or legacy object for sequential execution; backward compatible with existing calls.
  - `dequeue()`: Dequeues the next pending task.
  - `submit_background(target, *args, name=None, **kwargs) -> AsyncTask`: Spawns a non-blocking background task with lifecycle tracking and history recording.
  - `cancel_task(task_id: str) -> bool`: Cancels a task by ID.
  - `get_task(task_id: str) -> Optional[Dict]`: Returns task status, timing, result, and errors.
  - `worker()`: Asynchronous worker consuming queued tasks.

---

### 5.3 Asynchronous Event Bus
- **File**: `core/events/event_bus.py`
- **Component**: `EventBus`
- **Behavior**:
  - `subscribe(event_type, callback)`: Registers a callback for an event type without duplicate registrations.
  - `unsubscribe(event_type, callback)`: Safely unregisters a callback.
  - `async publish(event_type, payload)`: Iterates subscribers, invoking async coroutines with `await` and synchronous callables directly. Wraps each callback execution in an isolated `try...except` block so an error in one subscriber does not disrupt others.

---

### 5.4 Orchestrator Background Task Tracking
- **File**: `core/orchestration/ecosystem_orchestrator.py`
- **Behavior**:
  - Dispatches non-blocking desktop actions using `task_queue.submit_background(run_action, name=f"action_{resolution['action']}")` instead of unmanaged `asyncio.create_task`.

---

## 6. Async Execution Flow

```text
1. User or Simulator initiates command (POST /api/v1/bci/command)
   │
2. EcosystemOrchestrator receives command, normalizes, and validates state
   │
3. RuleRouter determines command type (Action on Desktop/Embedded/IoT)
   │
4. Action Dispatch:
   ├── For IoT / Embedded: Awaited directly via retry_manager and plugin_manager.execute
   └── For Desktop: Submitted non-blocking via task_queue.submit_background
   │
5. Execution Engine (execute):
   ├── Inspects plugin.execute method signature
   ├── If async: awaits in running event loop
   └── If sync: delegates to worker thread via asyncio.to_thread
   │
6. Completion & Error Handling:
   ├── On Success: status = COMPLETED, records execution timestamp, updates state
   └── On Error: status = FAILED, captures exception message, logs to logger.error
   │
7. Telemetry & State Polling:
   └── Client polls /api/v1/state and UI reflects status badge and action logs
```

---

## 7. Synchronous vs Asynchronous Execution

| Operational Area | Execution Model | Mechanism | Backward Compatible |
| :--- | :--- | :--- | :--- |
| **API Endpoints (FastAPI)** | Asynchronous (`async def`) | Native ASGI event loop | Yes |
| **Plugin Manager (`execute`)** | Hybrid Async/Sync | Inspects coroutines; dispatches sync to `asyncio.to_thread` | Yes |
| **Desktop Subplugins (PyAutoGUI)** | Synchronous | Executed in worker thread pool | Yes |
| **IoT / MQTT Communication** | Asynchronous | Awaited via Paho-MQTT loop | Yes |
| **Background Automation Tasks** | Asynchronous | Managed via `AsyncTask` & `TaskQueue` | Yes |
| **Event Bus (`publish`)** | Hybrid Async/Sync | Awaits coroutines, executes sync callbacks safely | Yes |

---

## 8. Error Handling

- **Invalid Input / Plugin Not Found**: Returns structured response `{"status": "error", "message": "Plugin not found"}` with a warning log.
- **Runtime Exceptions in Plugins**: Intercepted in `execute()`; records error details in `task.error` and logs traceback with `logger.error`.
- **Background Task Errors**: Logged upon failure and stored in task history; does not cause unhandled task exceptions in Python runtime.
- **Subscriber Failures in EventBus**: Caught per subscriber; logs error without terminating event distribution to remaining subscribers.
- **Task Cancellation**: Handled via `asyncio.CancelledError`; transitions task state to `CANCELLED` and logs the cancellation event.

---

## 9. Task Lifecycle

```text
[ Task Created ]
       │
       ▼
 [ QUEUED ]  ────── (cancel() before execution) ──────► [ CANCELLED ]
       │                                                      ▲
       ▼                                                      │
 [ RUNNING ] ────── (cancel() during execution) ──────────────┘
       │
       ├──────────────────────────────┐
       ▼                              ▼
 [ COMPLETED ]                   [ FAILED ]
 (result captured)           (error captured & logged)
```

1. **`QUEUED`**: Task is initialized, assigned a unique UUID, timestamped (`created_at`), and placed into the task registry/queue.
2. **`RUNNING`**: Execution begins, `started_at` timestamp is recorded, and target callable/coroutine is invoked.
3. **`COMPLETED`**: Execution succeeds, `completed_at` timestamp is recorded, and `result` is saved.
4. **`FAILED`**: Exception occurs during execution, `error` string is recorded, and stack trace is logged.
5. **`CANCELLED`**: Cancellation is requested, underlying task is cancelled, and `completed_at` is stamped.

---

## 10. UI Changes

### File Modified:
`plugins/desktop/ui/templates/index.html`

### Why the Change Was Made:
While async execution runs entirely within the backend, the dashboard's telemetry panel, status badges, and action chat preview needed to recognize and render all backend execution lifecycle states (`QUEUED`, `RUNNING` / `EXECUTING`, `COMPLETED` / `SUCCESS`, `RETRYING`, `CANCELLED`, `FAILED`).

### What Was Changed:
- Extended `getBadgeHTML()` to format all task status states with dedicated color mapping (e.g. Amber for `QUEUED`, Purple for `RUNNING`/`EXECUTING`, Cyan for `COMPLETED`/`SUCCESS`, Gray for `CANCELLED`, Red for `FAILED`).
- Updated `renderTimeline()` and `currentLogs` chat rendering to display detailed status messages for async executions.
- Preserved the existing 3-panel glassmorphism layout, Three.js 3D canvas, and 300ms state polling mechanism without introducing external UI frameworks or layout changes.

---

## 11. Files Changed

| File | Status | Changes Made | Purpose |
| :--- | :----- | :----------- | :------ |
| `core/plugin_manager/manager.py` | **Modified** | Added coroutine inspection, `asyncio.to_thread` thread offloading for sync plugins, centralized error handling, and logger integration. | Enables non-blocking execution of both async and sync plugins with robust error containment. |
| `core/queue/task_queue.py` | **Modified** | Implemented `TaskStatus`, `AsyncTask` lifecycle model, `submit_background`, cancellation, and error tracking while retaining legacy queue methods. | Provides the core asynchronous task execution, lifecycle management, and cancellation foundation. |
| `core/events/event_bus.py` | **Modified** | Added support for sync and async subscriber callbacks with isolated exception handling. | Ensures event publishing is concurrency-safe and resilient against faulty subscribers. |
| `core/orchestration/ecosystem_orchestrator.py` | **Modified** | Connected background action execution to `task_queue.submit_background`. | Eliminates unmanaged background tasks and prevents silent task failures. |
| `plugins/desktop/ui/templates/index.html` | **Modified** | Extended badge color mapping and timeline chat rendering for async lifecycle states. | Reflects actual backend async task lifecycle states in the dashboard UI. |
| `tests/test_async_execution.py` | **Created** | Added unit and integration tests covering `AsyncTask`, `TaskQueue`, hybrid plugin execution, `EventBus`, error handling, and cancellation. | Validates correctness of the Async Execution Foundation. |

---

## 12. Architecture Integration

The implementation adhered strictly to the principle of minimal, non-destructive extension:
- **FastAPI Application (`main.py`)**: Preserved without routing modifications.
- **Routing Engine (`rule_router.py`)**: Fully preserved with unmodified transition and action rules.
- **Plugin Interfaces (`plugin_sdk/interfaces/`)**: Preserved existing plugin contracts without breaking changes.
- **Domain Modules**: Desktop, Embedded, and IoT plugins continue to operate with their existing method signatures.
- **Logging & State Tracking**: Integrated with `core.logging.logger` and `core.state.state_manager` without adding competing subsystems.

---

## 13. Validation and Verification

### 13.1 Automated Tests
1. **Targeted Async Execution Tests**:
   - Command: `python -m pytest tests/test_async_execution.py`
   - Result: **8 passed in 0.22s**
   - Verified async task lifecycle, sync task execution in worker threads, error propagation, task cancellation, queue submission, plugin manager async/sync dispatch, and event bus subscriber isolation.

2. **Full Regression Test Suite**:
   - Command: `python -m pytest tests`
   - Result: **80 passed, 0 failed in 87.99s**
   - Verified zero regressions across command normalization, sequence validation, invalid combination rules, IoT adapter, IoT routing, navigation controller, RC Car plugin, and sequential processor.

### 13.2 Integration & Runtime Verification
- Verified server bootstrap and plugin discovery in `main.py`.
- Verified non-blocking execution of background desktop actions and state polling via `/api/v1/state`.

---

## 14. Example Execution

### Example: Executing a Desktop Action Asynchronously

1. **Request Ingestion**:
   ```http
   POST /api/v1/bci/command HTTP/1.1
   Content-Type: application/json

   {
       "command": "LEFT",
       "session": "default"
   }
   ```

2. **Resolution**:
   State is at Level 3 (Domain: `PYTHON`, App: `NOTEPAD`). `rule_router` resolves `LEFT` to Action `"open_notepad"`.

3. **Orchestrator Dispatch**:
   `ecosystem_orchestrator` submits the action to the async execution engine:
   ```python
   task_queue.submit_background(run_action, name="action_open_notepad")
   ```

4. **Execution in Plugin Manager**:
   `manager.execute("desktop", "open_notepad", payload)` detects that the Notepad handler contains synchronous OS operations (`subprocess.Popen` / `time.sleep`) and offloads it via `asyncio.to_thread`.

5. **Lifecycle State Transition**:
   - Status transitions from `QUEUED` ➔ `RUNNING` (stamping `started_at`).
   - On completion, status transitions to `COMPLETED` (stamping `completed_at`).

6. **State & UI Update**:
   - Action log is appended with `status: "SUCCESS"` and duration.
   - UI polls `/api/v1/state` (300ms cycle) and displays the `COMPLETED` badge and action confirmation in the command preview panel.

---

## 15. Benefits of the Implementation

- **Non-Blocking Operation**: Synchronous automation routines no longer freeze the FastAPI event loop or delay state polling.
- **Traceable Task Lifecycle**: Background tasks have distinct identifiers, lifecycle states, timestamps, and captured outputs.
- **Robust Error Containment**: Exceptions during asynchronous execution are captured, logged, and propagated as structured error responses rather than unhandled server crashes.
- **Zero Architectural Disruption**: Existing synchronous and asynchronous modules work interchangeably without rewriting plugin code.

---

## 16. Limitations / Future Considerations

- **In-Memory History**: `TaskQueue` history is maintained in-memory (retaining the last 100 tasks). If distributed multi-worker scaling is required in future phases, a persistent backend (e.g. Redis or SQLite) can be integrated.
- **Cooperative Cancellation**: Synchronous functions executing inside a worker thread via `asyncio.to_thread` complete their current blocking operation before thread termination, as native OS threads in Python cannot be forcefully interrupted.

---

## 17. Final Summary

The **Async Execution Foundation** delivers a reliable, non-blocking asynchronous execution layer for SynaptiMesh. By enhancing `manager.execute()`, expanding `TaskQueue` with the `AsyncTask` lifecycle model, securing `EventBus` subscriber execution, and connecting UI telemetry to actual execution states, the backend achieves full asynchronous execution capability while maintaining 100% backward compatibility with all existing plugins, routes, and test suites.
