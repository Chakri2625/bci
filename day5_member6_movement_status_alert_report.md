# SynaptiMesh Sprint 11 — Day 5 Member 6 Implementation Report

## Server-Side Movement / Status Alert Generation

**Author / Role:** Member 6 — Embedded & Robotics Server Alert Engineering  
**Sprint:** 11 — Day 5  
**Domain:** Embedded / Robotics (RC Car, Smart Wheelchair, Microcontrollers, Safety Systems)

---

## 1. Task Objective

The goal of Sprint 11 Day 5 Member 6 is to implement the **server-side movement/status alert generation** pipeline for the Embedded/Robotics domain within SynaptiMesh. 

According to the system separation of concerns:
* **Embedded Hardware / Agents:** Report raw hardware telemetry, kinematics, distance readings, emergency conditions, and battery status.
* **Server (Backend):** Ingests standardized telemetry, continuously monitors and evaluates safety/movement/hardware conditions, generates normalized dashboard-facing alerts with deterministic lifecycle management (trigger, deduplicate, auto-resolve), and broadcasts alerts over existing WebSockets and EventBus channels.
* **Client Dashboards:** Receive normalized alerts and render live visual notifications, log entries with severity badges, and audible/visual toast notifications.

---

## 2. Client / Server Responsibility Summary

| Layer | Responsibility | Details |
|---|---|---|
| **Hardware / Agent** | Status & Sensor Reporting | Publishes distance sensors (front/rear), emergency stop flags, speed/throttle, battery level/voltage, collision flags, and hardware health over MQTT / Mesh. |
| **Telemetry Standard** | Schema Normalization | Standardizes raw device payloads via `models.embedded_telemetry` and `services.embedded_telemetry_standard` into unified `movement`, `speed`, `status`, `battery`, and `sensors` structures. |
| **Alert Generator (Server)** | Condition Evaluation & Lifecycle | `EmbeddedAlertGenerator` evaluates rules across 8 distinct categories, manages active alert states per device, suppresses duplicate floods, resolves cleared faults, and attaches standardized metadata. |
| **Communication Layer** | Real-Time Dispatch | Routes generated alerts through FastAPI REST API, Centralized State Manager, EventBus (`embedded.alert`), and WebSocket server (`alert` event). |
| **Client UI** | Visual & Audible Display | Embedded Dashboard (`dashboard.js`) and Desktop UI (`index.html`) listen on the WebSocket stream, render severity badges (`CRITICAL`, `ERROR`, `WARNING`, `INFO`), and append to system logs. |

---

## 3. Existing Architecture Used

The implementation seamlessly builds upon the established SynaptiMesh framework without introducing parallel or conflicting subsystems:
1. **Telemetry Models & Standard (`models/telemetry_models.py` & `models/embedded_telemetry.py`):** Extended with `AlertSeverity`, `AlertStatus`, and `TelemetryAlert` models.
2. **Centralized State Manager (`services/centralized_state_manager.py`):** Broadcasts alerts into the state store and triggers background asynchronous WebSocket broadcasts.
3. **Embedded Dashboard WebSocket (`plugins/embedded/dashboard/embedded_backend/socket_manager.py`):** Added native `alert(data)` emission method.
4. **Telemetry Ingestion Pipelines (`api/telemetry_routes.py` & `plugins/embedded/dashboard/embedded_backend/telemetry.py`):** Hooked alert evaluation directly into `ingest_telemetry()` and `handle_status()` so all incoming MQTT and HTTP telemetry triggers real-time alert evaluation.

---

## 4. Implementation Details

### 4.1 Alert Data Models (`models/telemetry_models.py`)
- **`AlertSeverity` Enum:** `INFO`, `WARNING`, `ERROR`, `CRITICAL`.
- **`AlertStatus` Enum:** `ACTIVE`, `RESOLVED`, `ACKNOWLEDGED`.
- **`TelemetryAlert` Schema:** Fields include `alert_id`, `domain`, `device_id`, `alert_type`, `severity`, `status`, `message`, `metric_name`, `metric_value`, `threshold`, `timestamp`, `resolved_at`, and `metadata`.

### 4.2 Centralized Server-Side Alert Generator (`services/embedded_alert_generator.py`)
Implemented `EmbeddedAlertGenerator` as a thread-safe singleton.
* **Evaluated Alert Conditions & Established Thresholds:**
  1. **Emergency Stop:** Triggered when `emergency_stop == True` or movement state is `"EMERGENCY_STOP"` $\rightarrow$ `CRITICAL` severity (`EMERGENCY_STOP_TRIGGERED`).
  2. **Collision Warning:** Triggered when `collision == True` or `impact == True` $\rightarrow$ `CRITICAL` severity (`COLLISION_DETECTED`).
  3. **Proximity Obstacle Detection:**
     * Front obstacle $\le$ 15 cm $\rightarrow$ `CRITICAL` (`OBSTACLE_PROXIMITY_CRITICAL`).
     * Front obstacle $\le$ 30 cm $\rightarrow$ `WARNING` (`OBSTACLE_PROXIMITY_WARNING`).
     * Rear obstacle $\le$ 15 cm $\rightarrow$ `CRITICAL` (`REAR_OBSTACLE_PROXIMITY_CRITICAL`).
     * Rear obstacle $\le$ 30 cm $\rightarrow$ `WARNING` (`REAR_OBSTACLE_PROXIMITY_WARNING`).
  4. **Battery & Voltage Sag:**
     * Battery $\le$ 15% $\rightarrow$ `CRITICAL` (`BATTERY_CRITICAL`).
     * Battery $\le$ 25% $\rightarrow$ `WARNING` (`BATTERY_LOW`).
     * Supply Voltage $\le$ 10.0 V $\rightarrow$ `WARNING` (`VOLTAGE_SAG`).
  5. **Kinematic & Overspeed:**
     * Normalized speed $>$ 1.0 $\rightarrow$ `WARNING` (`ABNORMAL_SPEED`).
  6. **Unsafe Movement Lockout:**
     * Movement command active (e.g. `FORWARD`) while `emergency_stop == True` $\rightarrow$ `CRITICAL` (`UNSAFE_MOVEMENT_BLOCKED`).
  7. **Hardware & Subsystem Health:**
     * Hardware status in `["ERROR", "TIMEOUT", "DEGRADED", "OFFLINE"]` $\rightarrow$ `ERROR`/`WARNING` (`HARDWARE_STATUS_ERROR` / `HARDWARE_TIMEOUT`).
     * CPU Temperature $\ge$ 75°C $\rightarrow$ `CRITICAL`, $\ge$ 65°C $\rightarrow$ `WARNING` (`CPU_OVERHEATING`).
* **Lifecycle & Flood Control:**
  * Active alerts tracked in `_active_alerts[device_id][alert_type]`.
  * Alerts are deduplicated; rapid consecutive readings for the same ongoing condition update the timestamp without re-broadcasting identical alerts.
  * Auto-resolution is performed automatically when condition metrics return to safe operating ranges, generating an alert event with status `RESOLVED` and timestamp `resolved_at`.

### 4.3 Ingestion & Broadcast Pipelines
* **`api/telemetry_routes.py`:**
  * Integrated `EmbeddedAlertGenerator.get_instance().evaluate_telemetry(...)` inside `ingest_telemetry()` and `record_telemetry_packet()`.
  * Added REST query and management endpoints:
    * `GET /api/telemetry/alerts`: Filter alerts by domain, device_id, severity, or active status.
    * `POST /api/telemetry/alerts/evaluate`: Manually trigger evaluation for ad-hoc payloads.
    * `POST /api/telemetry/alerts/resolve`: Acknowledge and resolve an alert.
    * `POST /api/telemetry/alerts/clear`: Clear alert history and active states.
* **`plugins/embedded/dashboard/embedded_backend/telemetry.py`:**
  * Updated `TelemetryManager.handle_status()` to evaluate incoming MQTT status payloads and route alerts directly to `SocketManager.alert()`.

---

## 5. UI / Dashboard Changes

Minimal, non-intrusive UI updates were added to the dashboards to ensure end-to-end alert visibility:
1. **Embedded Dashboard (`plugins/embedded/dashboard/static/js/dashboard.js`):**
   * Registered native WebSocket event listener for `"alert"` and `"ALERT"`.
   * Displays toast notifications for `CRITICAL` alerts with danger styling.
   * Logs all alert events directly into the Activity Log and Command Console with appropriate severity badges (`[CRITICAL]`, `[ERROR]`, `[WARNING]`, `[INFO]`).
2. **Desktop UI (`plugins/desktop/ui/templates/index.html`):**
   * Enhanced the telemetry stream handler to recognize incoming alert packets (`type === 'ALERT'` or `p.alert_type`) and append formatted alert log entries into the live system stream.

---

## 6. Files Changed

| File Path | Action | Description |
|---|---|---|
| `models/telemetry_models.py` | **MODIFY** | Added `AlertSeverity`, `AlertStatus` enums and `TelemetryAlert` Pydantic schema. |
| `services/embedded_alert_generator.py` | **NEW** | Centralized singleton service evaluating 8 alert categories, managing lifecycle, deduplication, auto-resolution, and multi-channel dispatch. |
| `api/telemetry_routes.py` | **MODIFY** | Hooked alert generator into telemetry ingestion and added `/alerts` REST query/lifecycle endpoints. |
| `plugins/embedded/dashboard/embedded_backend/socket_manager.py` | **MODIFY** | Added `alert(data)` broadcast helper method. |
| `plugins/embedded/dashboard/embedded_backend/telemetry.py` | **MODIFY** | Added real-time alert evaluation hook inside MQTT status handler `handle_status()`. |
| `plugins/embedded/dashboard/static/js/dashboard.js` | **MODIFY** | Added WebSocket client listener for alerts, toast display, and console logging. |
| `plugins/desktop/ui/templates/index.html` | **MODIFY** | Added live alert log entry formatting in desktop telemetry view. |
| `tests/test_embedded_alert_generation.py` | **NEW** | 18 comprehensive test cases covering all alert rules, lifecycle, deduplication, and REST endpoints. |

---

## 7. Tests Added and Verified

A dedicated test suite was implemented in `tests/test_embedded_alert_generation.py`. All 18 tests, along with the full regression suite of 75 total tests across telemetry and state management, pass with 100% success rate:

* `test_normal_telemetry_produces_no_alerts`: Verifies safe telemetry produces zero alerts.
* `test_emergency_stop_generates_critical_alert`: Verifies `emergency_stop=True` triggers `CRITICAL` alert.
* `test_collision_detected_generates_critical_alert`: Verifies collision sensor flags trigger `CRITICAL` alert.
* `test_front_obstacle_warning_distance`: Verifies distance between 15cm and 30cm triggers `WARNING`.
* `test_front_obstacle_critical_distance`: Verifies distance $\le$ 15cm triggers `CRITICAL`.
* `test_rear_obstacle_proximity_alerts`: Verifies rear distance sensor warnings and critical alerts.
* `test_low_battery_warning_alert`: Verifies battery level $\le$ 25% triggers `WARNING`.
* `test_critical_battery_alert`: Verifies battery level $\le$ 15% triggers `CRITICAL`.
* `test_supply_voltage_sag_alert`: Verifies battery voltage $\le$ 10.0V triggers `WARNING`.
* `test_abnormal_overspeed_alert`: Verifies normalized speed $> 1.0$ triggers `WARNING`.
* `test_unsafe_movement_during_emergency_stop`: Verifies active movement command while E-stop is active triggers `CRITICAL`.
* `test_hardware_status_error_and_timeout`: Verifies `ERROR` and `TIMEOUT` hardware status triggers alerts.
* `test_cpu_overheating_alerts`: Verifies CPU temperatures $\ge 65^\circ\text{C}$ and $\ge 75^\circ\text{C}$ trigger warning/critical alerts.
* `test_wheelchair_and_robot_device_identification`: Verifies multi-device and smart wheelchair support.
* `test_alert_deduplication_prevents_flood`: Verifies flood prevention and deduplication.
* `test_alert_lifecycle_auto_resolution`: Verifies automatic resolution when metric returns to safe bounds.
* `test_malformed_telemetry_safe_handling`: Verifies resilient handling of missing fields and bad types.
* `test_telemetry_alert_api_endpoints`: Verifies FastAPI REST endpoints (`/alerts`, `/evaluate`, `/resolve`, `/clear`).

---

## 8. End-to-End Movement / Status Alert Flow

```text
[Embedded Hardware / Robot / Smart Wheelchair]
                       │ (MQTT / Mesh Telemetry)
                       ▼
         [TelemetryManager.handle_status()]
                       │
                       ▼
       [EmbeddedAlertGenerator.evaluate_telemetry()]
                       │
        ┌──────────────┴──────────────┐
        ▼                             ▼
 [Condition Triggered]        [Condition Cleared]
   - E-Stop, Collision          - Distance > 30cm
   - Distance ≤ 30/15cm         - Battery > 25%
   - Battery ≤ 25/15%           - Status == OK
   - Voltage Sag ≤ 10V          (Auto-Resolve Active Alert)
   - Status ERROR/TIMEOUT
        │                             │
        └──────────────┬──────────────┘
                       ▼
            [TelemetryAlert Model]
         (Normalized Alert Payload)
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
   [EventBus]   [StateManager]   [SocketManager]
                       │             │
                       ▼             ▼
               [REST API Client]  [WebSocket]
                                     │
                                     ▼
                            [Client Dashboard]
                        - Visual Toast Notification
                        - Log Entry with Severity Badge
```

---

## 9. Architecture Preservation Confirmation

* **No Domain Interference:** All alert rules operate exclusively on Embedded / Robotics telemetry and standard models without altering BCI, AI/ML, or IoT pipeline logic.
* **No Breaking Schema Changes:** Existing fields in `TelemetryData`, `EmbeddedTelemetry`, and `SystemState` remain completely intact.
* **Standardized Lifecycles:** Alert states strictly adhere to `ACTIVE` $\rightarrow$ `RESOLVED` transitions with standard timestamps.
* **Deduplication:** Prevents client WebSocket floods by maintaining in-memory device alert states.

---

## 10. Final Result

All requirements for **Sprint 11 — Day 5 Member 6: Server-Side Movement / Status Alert Generation** have been fully implemented, integrated, and verified against all automated test suites.
