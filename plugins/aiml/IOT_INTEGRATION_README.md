# Sub-Master API Integration Guide (For IoT Team)

This guide provides the necessary backend information and API endpoints required for the IoT dashboard to interface with the Sub-Master controlling mobile and desktop operations. The IoT team only needs to run this Python backend folder and consume the exposed REST APIs.

## 1. Running the Backend Server

The backend runs on Python and Flask. It exposes the necessary APIs and bridges the gap between web requests, MQTT (for Mobile), and System Automation (for Desktop).

### Prerequisites
Make sure you have Python installed and the required dependencies from the project:
```bash
cd master_hub
pip install -r requirements.txt
```

### Start the Server
```bash
python app.py
```
*The server runs locally on `http://localhost:5000` by default.*

---

## 2. Master FSM (Finite State Machine) APIs

These APIs control the high-level state of the Sub-Master, allowing you to select and activate dashboards programmatically.

### 2.1 Select Dashboard
Use this to set the active context (Mobile or Desktop) before executing commands.

- **Endpoint:** `POST /api/master/select_dashboard`
- **Payload:**
```json
{
  "dashboard": "mobile" // or "desktop"
}
```
- **Response:** `{"status": "success"}`

### 2.2 Start Automation (Activate Features)
Once a dashboard is selected, start the automation to allow operations on that specific platform.

- **Endpoint:** `POST /api/master/start_automation`
- **Payload:**
```json
{
  "dashboard": "mobile" // or "desktop"
}
```
- **Response:** `{"status": "success", "message": "mobile dashboard activated"}`

### 2.3 Reset FSM State
Resets the state machine back to the default `DOMAIN_SELECTION` state.

- **Endpoint:** `POST /api/master/reset_state`
- **Response:** `{"status": "success"}`

### 2.4 Get Current FSM State
Fetch the current active state of the state machine.

- **Endpoint:** `GET /api/master/fsm_state`
- **Response:** 
```json
{
  "state": "MOBILE_DASHBOARD_ACTIVE",
  "selected": "mobile"
}
```

---

## 3. Desktop Sub-Master APIs

If the IoT dashboard needs to trigger specific actions on the desktop directly, bypassing the state machine, it can use the following endpoints:

### 3.1 Trigger Desktop Action
Executes media and system commands on the local desktop.

- **Endpoint:** `POST /desktop/api/action`
- **Payload:**
```json
{
  "action": "Play / Pause" 
}
```
*Available Actions:* `"Play / Pause"`, `"Next Track"`, `"Previous Track"`, `"Launch JioSaavn"`, `"Search Album/Playlist"`, `"Volume Up"`, `"Volume Down"`

### 3.2 Change Desktop Volume Directly
- **Endpoint:** `POST /desktop/api/volume`
- **Payload:**
```json
{
  "volume": 75
}
```

### 3.3 Search for a Song/Playlist
- **Endpoint:** `POST /desktop/api/search`
- **Payload:**
```json
{
  "query": "Blinding Lights"
}
```

---

## 4. How the IoT Dashboard should integrate it

The IoT Dashboard can make direct HTTP requests to the local Python backend to trigger the features.

### Example: Activating Mobile Operations (JavaScript)
```javascript
// 1. Select the Mobile Dashboard
await fetch('http://localhost:5000/api/master/select_dashboard', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dashboard: 'mobile' })
});

// 2. Start Automation to activate features
await fetch('http://localhost:5000/api/master/start_automation', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dashboard: 'mobile' })
});
```

### Example: Sending a Desktop Action (Python)
```python
import requests

url = "http://localhost:5000/desktop/api/action"
payload = {"action": "Play / Pause"}

response = requests.post(url, json=payload)
print(response.json())
```

Once the automation is active via these APIs, the sub-master seamlessly routes commands over MQTT to mobile apps or via local system hooks to desktop applications.
