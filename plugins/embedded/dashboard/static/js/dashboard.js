/* ==========================================================
   SYNAPTIMESH MASTER HUB
   ROBOT CAR DASHBOARD
   NATIVE WEBSOCKET REAL-TIME FRONTEND

   SINGLE DEVICE TARGET ARCHITECTURE

   Device Selector
          |
          v
   selectedDevice
          |
     +----+----+---------+
     |         |         |
   Button   Keyboard   Console
     |         |         |
     +----+----+---------+
          |
          v
       /command
          |
          v
      Flask Hub
========================================================== */


// ==========================================================
// NATIVE WEBSOCKET
// ==========================================================

const websocket = window.SynaptiMeshWebSocket;


// ==========================================================
// STATE
// ==========================================================

let keyboardEnabled = false;

let currentState = "STOP";

let lastCommand = "";


// ----------------------------------------------------------
// SINGLE TARGET DEVICE
//
// This is the ONLY device target used by the dashboard.
// Every control uses this value.
// ----------------------------------------------------------

let selectedDevice = "";

// MQTT connection state is tracked independently for the Master Hub -> Broker
// link and the Broker -> selected Slave link.
const mqttConnection = {
    broker: {
        state: "OFFLINE",
        everConnected: false
    },
    devices: {}
};

function getDeviceMqttState(device) {
    const id = String(device || "").trim();

    if (!id) {
        return {
            state: "OFFLINE",
            everConnected: false
        };
    }

    if (!mqttConnection.devices[id]) {
        mqttConnection.devices[id] = {
            state: "OFFLINE",
            everConnected: false
        };
    }

    return mqttConnection.devices[id];
}


// ==========================================================
// PERSISTENT LOG STORAGE
// ==========================================================

const ACTIVITY_LOG_KEY =
    "synaptimesh_activity_log";

const CONSOLE_LOG_KEY =
    "synaptimesh_console_log";

const MAX_SAVED_LOGS = 200;


// ==========================================================
// HELPERS
// ==========================================================

function element(id) {

    return document.getElementById(id);

}


function now() {

    return new Date().toLocaleTimeString();

}


// ==========================================================
// DEVICE SELECTION
// ==========================================================

function getSelectedDevice() {

    const selector =
        element("deviceSelector");

    if (!selector) {

        return "";

    }

    return selector.value.trim();

}


function updateSelectedDevice() {

    const previousSelectedDevice = selectedDevice;

    selectedDevice =
        getSelectedDevice();

    console.log(
        "[Dashboard Device] SELECTION ->",
        { previousSelectedDevice, selectedDevice }
    );


    const deviceDisplay =
        element("deviceId");


    const deviceInfo =
        element("selectedDeviceInfo");


    // ------------------------------------------------------
    // No device selected
    // ------------------------------------------------------

    if (!selectedDevice) {

        if (deviceDisplay) {

            deviceDisplay.textContent =
                "--";

        }


        if (deviceInfo) {

            deviceInfo.textContent =
                "No device selected";

        }


        addActivity(
            "Target device cleared",
            "system"
        );


        addConsole(
            "TARGET -> NONE",
            "system"
        );


        return;

    }


    // ------------------------------------------------------
    // Update UI
    // ------------------------------------------------------

    if (deviceDisplay) {

        deviceDisplay.textContent =
            selectedDevice;

    }


    if (deviceInfo) {

        const selector =
            element("deviceSelector");


        const option =
            selector
                ? selector.options[
                    selector.selectedIndex
                ]
                : null;


        deviceInfo.textContent =
            option
                ? `Active target: ${option.textContent.trim()}`
                : `Active target: ${selectedDevice}`;

    }


    // ------------------------------------------------------
    // Reset device-specific display
    // ------------------------------------------------------

    updateMovement(
        "STOP"
    );

    updateRobotStatus(
        "UNKNOWN"
    );

    updateMQTT();
    updateSafetyStatus(
    "CLEAR"
    );


    const front =
        element("frontDistance");

    const rear =
        element("rearDistance");


    if (front) {

        front.textContent =
            "-- cm";

    }


    if (rear) {

        rear.textContent =
            "-- cm";

    }


    // ------------------------------------------------------
    // Log selection
    // ------------------------------------------------------

    addActivity(
        `Target device selected: ${selectedDevice}`,
        "system"
    );


    addConsole(
        `TARGET -> ${selectedDevice}`,
        "system"
    );


    notify(
        `Target device: ${selectedDevice}`
    );

}


// ==========================================================
// EMBEDDED DEVICE STATUS UI
// ==========================================================

function updateEmbeddedDeviceStatus(status) {

    console.log(
        "[Dashboard Visual] updateEmbeddedDeviceStatus() INPUT ->",
        status
    );

    status =
        String(status ?? "OFFLINE")
            .trim()
            .toUpperCase();


    if (
        status !== "ONLINE" &&
        status !== "OFFLINE"
    ) {

        console.warn(
            "[Dashboard Visual] updateEmbeddedDeviceStatus() ignored unsupported status ->",
            status
        );

        return;

    }


    const robotStatus =
        element("robotStatus");

    const robotDot =
        element("robotDot");

    const liveIndicator =
        element("deviceLiveIndicator");


    if (robotStatus) {

        robotStatus.textContent =
            status;


        robotStatus.classList.toggle(
            "online",
            status === "ONLINE"
        );


        robotStatus.classList.toggle(
            "offline",
            status === "OFFLINE"
        );

    }


    if (robotDot) {

        robotDot.classList.toggle(
            "online",
            status === "ONLINE"
        );


        robotDot.classList.toggle(
            "offline",
            status === "OFFLINE"
        );

    }


    if (liveIndicator) {

        liveIndicator.classList.toggle(
            "online",
            status === "ONLINE"
        );


        liveIndicator.classList.toggle(
            "offline",
            status === "OFFLINE"
        );


        liveIndicator.innerHTML =
            "";


        const dot =
            document.createElement("span");


        liveIndicator.appendChild(
            dot
        );


        liveIndicator.appendChild(
            document.createTextNode(
                status === "ONLINE"
                    ? " ONLINE"
                    : " OFFLINE"
            )
        );

    }


    console.log(
        "[DEVICE STATUS] UI Updated:",
        status
    );

    console.log(
        "[Dashboard Visual] updateEmbeddedDeviceStatus() COMPLETE ->",
        status
    );

}


// ==========================================================
// SAFETY SENSOR STATUS
// ==========================================================

function updateSafetyStatus(status) {

    status =
        String(status ?? "CLEAR")
            .trim()
            .toUpperCase();


    const frontItem =
        element("frontSafetyItem");

    const rearItem =
        element("rearSafetyItem");


    const frontText =
        element("frontSafety");

    const rearText =
        element("rearSafety");


    const frontPointer =
        element("frontSafetyPointer");

    const rearPointer =
        element("rearSafetyPointer");


    // ------------------------------------------------------
    // RESET
    // ------------------------------------------------------

    if (frontItem) {

        frontItem.classList.remove(
            "obstacle"
        );

    }


    if (rearItem) {

        rearItem.classList.remove(
            "obstacle"
        );

    }


    if (frontText) {

        frontText.textContent =
            "CLEAR";

    }


    if (rearText) {

        rearText.textContent =
            "CLEAR";

    }


    if (frontPointer) {

        frontPointer.textContent =
            "●";

    }


    if (rearPointer) {

        rearPointer.textContent =
            "●";

    }


    // ------------------------------------------------------
    // FRONT OBSTACLE
    // ------------------------------------------------------

    if (
        status === "FRONT OBSTACLE"
    ) {

        if (frontItem) {

            frontItem.classList.add(
                "obstacle"
            );

        }


        if (frontText) {

            frontText.textContent =
                "OBSTACLE";

        }


        if (frontPointer) {

            frontPointer.textContent =
                "⚠";

        }


        console.log(
            "[SAFETY] FRONT OBSTACLE"
        );

        return;

    }


    // ------------------------------------------------------
    // REAR OBSTACLE
    // ------------------------------------------------------

    if (
        status === "REAR OBSTACLE"
    ) {

        if (rearItem) {

            rearItem.classList.add(
                "obstacle"
            );

        }


        if (rearText) {

            rearText.textContent =
                "OBSTACLE";

        }


        if (rearPointer) {

            rearPointer.textContent =
                "⚠";

        }


        console.log(
            "[SAFETY] REAR OBSTACLE"
        );

        return;

    }


    // ------------------------------------------------------
    // CLEAR
    // ------------------------------------------------------

    if (
        status === "CLEAR"
    ) {

        console.log(
            "[SAFETY] Sensors CLEAR"
        );

    }

}


// ==========================================================
// DEVICE SELECTOR EVENT
// ==========================================================

const deviceSelector =
    element("deviceSelector");


if (deviceSelector) {

    deviceSelector.addEventListener(
        "change",
        updateSelectedDevice
    );


    updateSelectedDevice();

}


// ==========================================================
// SAVE LOG
//
// IMPORTANT:
// WebSocket listeners MUST NOT be placed inside this
// function. This function can execute hundreds of times.
// ==========================================================

function saveLog(
    key,
    entry
) {

    try {

        const logs =
            JSON.parse(
                localStorage.getItem(
                    key
                ) || "[]"
            );


        logs.push(
            entry
        );


        while (
            logs.length >
            MAX_SAVED_LOGS
        ) {

            logs.shift();

        }


        localStorage.setItem(
            key,
            JSON.stringify(logs)
        );


    } catch (error) {

        console.error(
            "Failed to save log:",
            error
        );

    }

}


// ==========================================================
// DEVICE STATUS SNAPSHOT
//
// REGISTERED ONCE.
// ==========================================================

websocket?.on(
    "device_status_snapshot",
    function (data) {

        console.log(
            "[Dashboard Device Snapshot] RECEIVED <-",
            data
        );


        const devices =
            data?.devices || {};


        if (
            typeof devices !== "object" ||
            Array.isArray(devices)
        ) {

            console.error(
                "[Dashboard Device Snapshot] Invalid devices payload ->",
                devices
            );

            return;

        }


        console.log(
            "[Dashboard Device Snapshot] DEVICES ->",
            devices
        );


        const selector =
            element("deviceSelector");


        // --------------------------------------------------
        // Automatically select the first known device when
        // no target has been selected yet.
        // --------------------------------------------------

        if (
            selector &&
            !selector.value
        ) {

            const ids =
                Object.keys(
                    devices
                );


            if (ids.length > 0) {

                const firstDevice =
                    ids[0];


                const option =
                    Array.from(
                        selector.options
                    ).find(
                        function (item) {

                            return (
                                String(
                                    item.value
                                ).trim() ===
                                String(
                                    firstDevice
                                ).trim()
                            );

                        }
                    );


                if (option) {

                    selector.value =
                        firstDevice;


                    selectedDevice =
                        firstDevice;


                    updateSelectedDevice();


                    console.log(
                        "[DEVICE STATUS] Auto-selected:",
                        firstDevice
                    );

                }

            }

        }


        // --------------------------------------------------
        // Apply status only to selected device.
        // --------------------------------------------------

        Object.entries(
            devices
        ).forEach(
            function (
                [deviceId, status]
            ) {

                console.log(
                    `[DEVICE STATUS SNAPSHOT] ${deviceId} => ${status}`
                );


                if (
                    selectedDevice &&
                    String(
                        deviceId
                    ).trim() ===
                    String(
                        selectedDevice
                    ).trim()
                ) {

                    updateEmbeddedDeviceStatus(
                        status
                    );

                }

            }
        );

    }
);


// ==========================================================
// DEVICE STATUS LIVE UPDATE
//
// REGISTERED ONCE.
// ==========================================================

websocket?.on(
    "device_status",
    function (data) {

        console.log(
            "[Dashboard Device Status] RECEIVED <-",
            data,
            { selectedDevice }
        );


        if (
            !data ||
            !data.device
        ) {

            return;

        }


        if (
            selectedDevice &&
            String(
                data.device
            ).trim() ===
            String(
                selectedDevice
            ).trim()
        ) {

            const status =
                String(
                    data.status ?? ""
                )
                    .trim()
                    .toUpperCase();


            // ----------------------------------------------
            // Normal embedded device status
            // ----------------------------------------------

            if (
                status === "ONLINE" ||
                status === "OFFLINE"
            ) {

                updateEmbeddedDeviceStatus(
                    status
                );

            }


            // ----------------------------------------------
            // Safety sensor status
            // ----------------------------------------------

            if (
                status === "FRONT OBSTACLE" ||
                status === "REAR OBSTACLE" ||
                status === "CLEAR"
            ) {

                updateSafetyStatus(
                    status
                );

            }

        }

    }
);


// ==========================================================
// SERVER-SIDE ALERT GENERATION LISTENER (Member 6)
// ==========================================================

function handleIncomingAlert(data) {
    const payload = data?.payload || data;
    if (!payload || typeof payload !== "object") return;

    const severity = String(payload.severity || "WARNING").toUpperCase();
    const msg = payload.message || "Alert condition detected";
    const devId = payload.device_id || selectedDevice || "DEVICE";
    const status = String(payload.status || "ACTIVE").toUpperCase();

    const logType = (severity === "CRITICAL" || severity === "ERROR") ? "error" : "warning";
    const prefix = status === "RESOLVED" ? "[ALERT RESOLVED]" : `[${severity} ALERT]`;

    addActivity(`${prefix} ${devId}: ${msg}`, logType);
    addConsole(`${prefix} ${devId} -> ${msg}`, logType);

    if (severity === "CRITICAL" && status === "ACTIVE") {
        if (typeof showNotification === "function") {
            showNotification(`🚨 ${msg}`, "error");
        }
    }
}

websocket?.on("alert", handleIncomingAlert);
websocket?.on("ALERT", handleIncomingAlert);


// ==========================================================
// RENDER ACTIVITY
// ==========================================================


function renderActivity(
    message,
    type = "system",
    timestamp = null
) {

    const log =
        element("activityLog");


    if (!log) {

        return;

    }


    const entry =
        document.createElement("div");


    entry.className =
        `log-entry ${type}`;


    const time =
        document.createElement("span");


    time.className =
        "log-time";


    time.textContent =
        timestamp || now();


    const text =
        document.createElement("span");


    text.className =
        "log-message";


    text.textContent =
        message;


    entry.appendChild(
        time
    );


    entry.appendChild(
        text
    );


    log.appendChild(
        entry
    );

}


// ==========================================================
// RENDER CONSOLE
// ==========================================================

function renderConsole(
    message,
    type = "system",
    timestamp = null
) {

    const output =
        element("consoleOutput");


    if (!output) {

        return;

    }


    const line =
        document.createElement("div");


    line.className =
        `console-line ${type}`;


    const time =
        document.createElement("span");


    time.className =
        "console-time";


    time.textContent =
        timestamp || now();


    const text =
        document.createElement("span");


    text.className =
        "console-message";


    text.textContent =
        `> ${message}`;


    line.appendChild(
        time
    );


    line.appendChild(
        text
    );


    output.appendChild(
        line
    );

}


// ==========================================================
// LOAD SAVED LOGS
// ==========================================================

function loadSavedLogs() {

    // ------------------------------------------------------
    // ACTIVITY LOG
    // ------------------------------------------------------

    try {

        const activityLogs =
            JSON.parse(
                localStorage.getItem(
                    ACTIVITY_LOG_KEY
                ) || "[]"
            );


        activityLogs.forEach(
            entry => {

                renderActivity(
                    entry.message,
                    entry.type,
                    entry.time
                );

            }
        );


    } catch (error) {

        console.error(
            "Failed to load activity logs:",
            error
        );

    }


    // ------------------------------------------------------
    // CONSOLE LOG
    // ------------------------------------------------------

    try {

        const consoleLogs =
            JSON.parse(
                localStorage.getItem(
                    CONSOLE_LOG_KEY
                ) || "[]"
            );


        consoleLogs.forEach(
            entry => {

                renderConsole(
                    entry.message,
                    entry.type,
                    entry.time
                );

            }
        );


        const output =
            element("consoleOutput");


        if (output) {

            output.scrollTop =
                output.scrollHeight;

        }


    } catch (error) {

        console.error(
            "Failed to load console logs:",
            error
        );

    }

}


// ==========================================================
// ACTIVITY LOG
// ==========================================================

function addActivity(
    message,
    type = "system"
) {

    const timestamp =
        now();


    saveLog(
        ACTIVITY_LOG_KEY,
        {
            time:
                timestamp,

            message:
                message,

            type:
                type
        }
    );


    renderActivity(
        message,
        type,
        timestamp
    );


    const log =
        element("activityLog");


    if (log) {

        while (
            log.children.length >
            100
        ) {

            log.removeChild(
                log.firstChild
            );

        }

    }

}


// ==========================================================
// CONSOLE
// ==========================================================

function addConsole(
    message,
    type = "system"
) {

    const timestamp =
        now();


    saveLog(
        CONSOLE_LOG_KEY,
        {
            time:
                timestamp,

            message:
                message,

            type:
                type
        }
    );


    renderConsole(
        message,
        type,
        timestamp
    );


    const output =
        element("consoleOutput");


    if (output) {

        while (
            output.children.length >
            100
        ) {

            output.removeChild(
                output.firstChild
            );

        }


        output.scrollTop =
            output.scrollHeight;

    }

}


// ==========================================================
// NOTIFICATION
// ==========================================================

function notify(
    message
) {

    const notification =
        element("notification");


    const text =
        element("notificationMessage");


    if (
        !notification ||
        !text
    ) {

        return;

    }


    text.textContent =
        message;


    notification.classList.add(
        "show"
    );


    setTimeout(
        () => {

            notification.classList.remove(
                "show"
            );

        },
        2500
    );

}


// ==========================================================
// STATE DISPLAY
// ==========================================================

function updateMovement(
    state
) {

    console.log(
        "[Dashboard Visual] updateMovement() INPUT ->",
        state,
        { selectedDevice, currentState }
    );

    if (!state) {

        console.warn(
            "[Dashboard Visual] updateMovement() skipped: empty state"
        );

        return;

    }


    state =
        String(
            state
        ).toUpperCase();


    const previousState = currentState;

    currentState =
        state;

    console.log(
        "[Dashboard Visual] STATE ->",
        { previousState, newState: state }
    );


    const stateText =
        element("currentState");


    const commandText =
        element("currentCommand");


    const icon =
        element("robotStateIcon");


    if (stateText) {

        console.log(
            "[Dashboard Visual] #currentState FOUND -> updating text",
            stateText.textContent,
            "=>",
            state
        );

        stateText.textContent =
            state;

    } else {

        console.error(
            "[Dashboard Visual] #currentState NOT FOUND"
        );

    }


    if (commandText) {

        console.log(
            "[Dashboard Visual] #currentCommand update ->",
            state
        );

        commandText.textContent =
            state === "STOP"
                ? "Robot stopped"
                : `Robot ${state.toLowerCase()}`;

    }


    if (icon) {

        const icons = {

            FORWARD:
                "▲",

            BACKWARD:
                "▼",

            LEFT:
                "◀",

            RIGHT:
                "▶",

            LEFT360:
                "↶",

            RIGHT360:
                "↷",

            STOP:
                "■"

        };


        icon.textContent =
            icons[state] || "●";

        console.log(
            "[Dashboard Visual] #robotStateIcon update ->",
            icon.textContent
        );

    } else {

        console.error(
            "[Dashboard Visual] #robotStateIcon NOT FOUND"
        );

    }

    console.log(
        "[Dashboard Visual] updateMovement() COMPLETE ->",
        { state, currentState }
    );

}


// ==========================================================
// MASTER HUB CONNECTION
// ==========================================================

function updateMasterConnection(
    connected
) {

    const status =
        element("connectionStatus");


    const dot =
        element("connectionDot");


    if (status) {

        status.textContent =
            connected
                ? "CONNECTED"
                : "DISCONNECTED";

    }


    if (dot) {

        dot.classList.toggle(
            "online",
            connected
        );


        dot.classList.toggle(
            "offline",
            !connected
        );

    }

}


// ==========================================================
// ROBOT STATUS
// ==========================================================

function updateRobotStatus(
    status
) {

    const robotStatus =
        element("robotStatus");


    const robotDot =
        element("robotDot");


    if (robotStatus) {

        robotStatus.textContent =
            status || "UNKNOWN";

    }


    if (robotDot) {

        const online =
            String(
                status
            ).toUpperCase() ===
            "ONLINE";


        robotDot.classList.toggle(
            "online",
            online
        );


        robotDot.classList.toggle(
            "offline",
            !online
        );

    }

}


function updateDeviceMQTTState(
    device,
    incomingState
) {

    const id =
        String(device || "").trim();

    if (!id) {
        return;
    }

    const state =
        getDeviceMqttState(id);

    const value =
        String(incomingState || "")
            .trim()
            .toUpperCase();


    if (
        value === "ONLINE" ||
        value === "CONNECTED"
    ) {

        state.state =
            "ONLINE";

        state.everConnected =
            true;

    } else if (
        value === "DISCONNECTED"
    ) {

        // DISCONNECTED is an explicit broken-connection state.
        // Do not downgrade it to OFFLINE just because this browser
        // has not previously observed ONLINE.
        state.state =
            "DISCONNECTED";

    } else if (
        value === "OFFLINE"
    ) {

        // OFFLINE means the device has not established its MQTT
        // connection (or is explicitly reporting itself offline).
        state.state =
            "OFFLINE";

    }


    if (
        isSelectedDeviceEvent({
            device: id
        })
    ) {

        updateMQTT();

    }

}


// ==========================================================
// MQTT CONNECTION DIAGRAM + STATUS
// ==========================================================

function getOverallMQTTState() {

    const brokerState =
        mqttConnection.broker.state;

    const deviceState =
        selectedDevice
            ? getDeviceMqttState(selectedDevice).state
            : "OFFLINE";


    if (
        brokerState === "OFFLINE" &&
        !mqttConnection.broker.everConnected
    ) {
        return "OFFLINE";
    }


    if (
        brokerState === "DISCONNECTED"
    ) {
        return "DISCONNECTED";
    }


    if (
        brokerState === "CONNECTED" &&
        deviceState === "ONLINE"
    ) {
        return "ONLINE";
    }


    if (
        brokerState === "CONNECTED" &&
        deviceState === "DISCONNECTED"
    ) {
        return "DISCONNECTED";
    }


    if (
        brokerState === "CONNECTED"
    ) {
        return "CONNECTED";
    }


    return "OFFLINE";
}


function setConnectionLine(
    lineId,
    state
) {

    const line =
        element(lineId);

    if (!line) {
        return;
    }

    line.classList.remove(
        "active",
        "disconnected",
        "inactive"
    );

    line.classList.add(
        state
    );
}


function setConnectionNode(
    nodeId,
    state
) {

    const node =
        element(nodeId);

    if (!node) {
        return;
    }

    node.classList.remove(
        "active",
        "disconnected",
        "inactive"
    );

    node.classList.add(
        state
    );
}


function updateMQTT() {

    const status =
        element("mqttStatus");

    const overall =
        getOverallMQTTState();

    const diagramState =
        element("mqttDiagramState");


    if (diagramState) {

        diagramState.textContent =
            overall;

        diagramState.classList.toggle(
            "online",
            overall === "ONLINE"
        );

        diagramState.classList.toggle(
            "connected",
            overall === "CONNECTED"
        );

        diagramState.classList.toggle(
            "disconnected",
            overall === "DISCONNECTED"
        );

        diagramState.classList.toggle(
            "offline",
            overall === "OFFLINE"
        );

    }


    if (status) {

        status.textContent =
            overall;

        status.classList.toggle(
            "online",
            overall === "ONLINE"
        );

        status.classList.toggle(
            "connected",
            overall === "CONNECTED"
        );

        status.classList.toggle(
            "disconnected",
            overall === "DISCONNECTED"
        );

        status.classList.toggle(
            "offline",
            overall === "OFFLINE"
        );

    }


    const brokerConnected =
        mqttConnection.broker.state ===
        "CONNECTED";

    const brokerBroken =
        mqttConnection.broker.state ===
        "DISCONNECTED";

    const deviceState =
        selectedDevice
            ? getDeviceMqttState(selectedDevice).state
            : "OFFLINE";

    const deviceOnline =
        deviceState === "ONLINE";

    const deviceBroken =
        deviceState === "DISCONNECTED";


    // MASTER HUB -> BROKER

    if (brokerConnected) {

        setConnectionLine(
            "mqttLineHubBroker",
            "active"
        );

        setConnectionNode(
            "mqttNodeHub",
            "active"
        );

        setConnectionNode(
            "mqttNodeBroker",
            "active"
        );

    } else if (brokerBroken) {

        setConnectionLine(
            "mqttLineHubBroker",
            "disconnected"
        );

        setConnectionNode(
            "mqttNodeHub",
            "disconnected"
        );

        setConnectionNode(
            "mqttNodeBroker",
            "disconnected"
        );

    } else {

        setConnectionLine(
            "mqttLineHubBroker",
            "inactive"
        );

        setConnectionNode(
            "mqttNodeHub",
            "inactive"
        );

        setConnectionNode(
            "mqttNodeBroker",
            "inactive"
        );

    }


    // BROKER -> SLAVE

    if (deviceOnline) {

        setConnectionLine(
            "mqttLineBrokerSlave",
            "active"
        );

        setConnectionNode(
            "mqttNodeSlave",
            "active"
        );

    } else if (deviceBroken) {

        setConnectionLine(
            "mqttLineBrokerSlave",
            "disconnected"
        );

        setConnectionNode(
            "mqttNodeSlave",
            "disconnected"
        );

    } else {

        setConnectionLine(
            "mqttLineBrokerSlave",
            "inactive"
        );

        setConnectionNode(
            "mqttNodeSlave",
            "inactive"
        );

    }


    const brokerText =
        element("mqttBrokerConnectionText");

    const slaveText =
        element("mqttSlaveConnectionText");


    if (brokerText) {

        brokerText.textContent =
            brokerConnected
                ? "CONNECTED"
                : brokerBroken
                    ? "DISCONNECTED"
                    : "OFFLINE";

    }


    if (slaveText) {

        slaveText.textContent =
            deviceOnline
                ? "ONLINE"
                : deviceBroken
                    ? "DISCONNECTED"
                    : "OFFLINE";

    }

}


// ==========================================================
// CHECK EVENT DEVICE
//
// Prevent telemetry/ACK/status belonging to another device
// from changing the currently selected device UI.
// ==========================================================

function isSelectedDeviceEvent(
    data
) {

    if (!data) {

        return false;

    }


    // ------------------------------------------------------
    // No device specified in event.
    //
    // Keep existing behavior for system-level events.
    // ------------------------------------------------------

    if (!data.device) {

        return true;

    }


    if (!selectedDevice) {

        return false;

    }


    return (
        String(
            data.device
        ).trim() ===
        String(
            selectedDevice
        ).trim()
    );

}


// ==========================================================
// TELEMETRY
// ==========================================================

websocket?.on(
    "telemetry",
    data => {

        console.log(
            "[Dashboard Telemetry] RECEIVED <-",
            data,
            { selectedDevice, currentState }
        );

        if (!data) {

            console.warn(
                "[Dashboard Telemetry] Ignored: empty payload"
            );

            return;

        }


        // --------------------------------------------------
        // Ignore telemetry from another device
        // --------------------------------------------------

        const selectedMatch =
            isSelectedDeviceEvent(data);

        console.log(
            "[Dashboard Telemetry] DEVICE FILTER ->",
            {
                eventDevice: data.device,
                selectedDevice,
                selectedMatch
            }
        );

        if (
            data.device &&
            !selectedMatch
        ) {

            addConsole(
                `Telemetry ignored from ${data.device} (target: ${selectedDevice || "NONE"})`,
                "system"
            );


            return;

        }


        // --------------------------------------------------
        // Device
        // --------------------------------------------------

        if (data.device) {

            const device =
                element("deviceId");


            if (device) {

                device.textContent =
                    data.device;

            }

        }


        // --------------------------------------------------
        // State
        // --------------------------------------------------

        if (data.state) {

            console.log(
                "[Dashboard Telemetry] STATE PRESENT ->",
                data.state
            );

            updateMovement(
                data.state
            );

        } else {

            console.warn(
                "[Dashboard Telemetry] No state field in telemetry payload"
            );

        }


        // --------------------------------------------------
        // Status
        // --------------------------------------------------

        if (data.status) {

            updateRobotStatus(
                data.status
            );

        }


        // --------------------------------------------------
        // MQTT DEVICE LINK
        // --------------------------------------------------

        if (data.device && data.mqtt) {

            updateDeviceMQTTState(
                data.device,
                data.mqtt
            );

        }


        // --------------------------------------------------
        // Front
        // --------------------------------------------------

        if (
            data.front_distance !==
            undefined
        ) {

            const front =
                element("frontDistance");


            if (front) {

                front.textContent =
                    `${data.front_distance} cm`;

            }

        }


        // --------------------------------------------------
        // Rear
        // --------------------------------------------------

        if (
            data.rear_distance !==
            undefined
        ) {

            const rear =
                element("rearDistance");


            if (rear) {

                rear.textContent =
                    `${data.rear_distance} cm`;

            }

        }


        // --------------------------------------------------
        // Front Safety
        // --------------------------------------------------

        if (
            data.front_obstacle !==
            undefined
        ) {

            const frontSafety =
                element("frontSafety");


            if (frontSafety) {

                frontSafety.textContent =
                    data.front_obstacle
                        ? "BLOCKED"
                        : "CLEAR";

            }

        }


        // --------------------------------------------------
        // Rear Safety
        // --------------------------------------------------

        if (
            data.rear_obstacle !==
            undefined
        ) {

            const rearSafety =
                element("rearSafety");


            if (rearSafety) {

                rearSafety.textContent =
                    data.rear_obstacle
                        ? "BLOCKED"
                        : "CLEAR";

            }

        }


        // --------------------------------------------------
        // Battery SoC
        // --------------------------------------------------

        if (
            data.battery_soc_pct !==
            undefined &&
            data.battery_soc_pct !==
            null
        ) {

            const battery =
                element("batterySoc");


            if (battery) {

                battery.textContent =
                    `${data.battery_soc_pct}%`;

            }

        }

    }
);


// ==========================================================
// ACK
// ==========================================================

websocket?.on(
    "ack",
    data => {

        if (!data) {

            return;

        }


        // An ACK is direct proof that the slave is reachable through MQTT.
        if (data.device) {

            updateDeviceMQTTState(
                data.device,
                "ONLINE"
            );

        }


        // --------------------------------------------------
        // Ignore ACK from another device
        // --------------------------------------------------

        if (
            data.device &&
            !isSelectedDeviceEvent(
                data
            )
        ) {

            addConsole(
                `ACK ignored from ${data.device} (target: ${selectedDevice || "NONE"})`,
                "system"
            );


            return;

        }


        const message =
            data.ack ||
            data.message ||
            data.status ||
            "UNKNOWN";


        const ackMessage =
            element("ackMessage");


        const ackType =
            element("ackType");


        const ackTime =
            element("ackTime");


        const indicator =
            element("responseIndicator");


        if (ackMessage) {

            ackMessage.textContent =
                message;

        }


        if (ackType) {

            ackType.textContent =
                "ACK";

        }


        if (ackTime) {

            ackTime.textContent =
                now();

        }


        if (indicator) {

            indicator.textContent =
                "RECEIVED";

        }


        addActivity(

            `${data.device || selectedDevice || "DEVICE"} ACK: ${message}`,

            "ack"

        );


        addConsole(

            `ACK <- ${message}`,

            "ack"

        );


        notify(
            `ESP32: ${message}`
        );

    }
);


// ==========================================================
// ACTIVITY STATUS EVENT
// ==========================================================

websocket?.on(
    "activity",
    data => {

        if (!data) {

            return;

        }


        // --------------------------------------------------
        // Ignore another device
        // --------------------------------------------------

        if (
            data.device &&
            !isSelectedDeviceEvent(
                data
            )
        ) {

            return;

        }


        if (
            data.type ===
            "status"
        ) {

            updateRobotStatus(
                data.message
            );


            addActivity(

                `${data.device || selectedDevice || "DEVICE"} STATUS: ${data.message}`,

                "status"

            );


            addConsole(

                `STATUS <- ${data.message}`,

                "status"

            );

        }

    }
);


// ==========================================================
// MQTT CONNECTION
// ==========================================================

websocket?.on(
    "mqtt_status",
    data => {

        const connected =
            Boolean(
                data &&
                data.connected
            );


        if (connected) {

            mqttConnection.broker.state =
                "CONNECTED";

            mqttConnection.broker.everConnected =
                true;

        } else {

            mqttConnection.broker.state =
                mqttConnection.broker.everConnected
                    ? "DISCONNECTED"
                    : "OFFLINE";

        }


        updateMQTT();


        addActivity(

            connected
                ? "MQTT Broker Connected"
                : "MQTT Broker Disconnected",

            "system"

        );

    }
);


websocket?.on(
    "mqtt_device_snapshot",
    data => {

        if (!data) {
            return;
        }

        // Restore the cached slave MQTT states when the dashboard
        // connects after the Master Hub has already received them.
        const devices =
            data.devices || {};

        Object.entries(devices).forEach(
            ([device, status]) => {
                updateDeviceMQTTState(
                    device,
                    status
                );
            }
        );

        updateMQTT();
    }
);


websocket?.on(
    "mqtt_device_status",
    data => {

        if (
            !data ||
            !data.device
        ) {
            return;
        }

        updateDeviceMQTTState(
            data.device,
            data.status
        );

    }
);


// ==========================================================
// RAW MQTT
// ==========================================================

websocket?.on(
    "mqtt_message",
    data => {

        if (!data) {

            return;

        }


        // --------------------------------------------------
        // If MQTT message contains a device, only show the
        // selected device's messages.
        // --------------------------------------------------

        if (
            data.device &&
            !isSelectedDeviceEvent(
                data
            )
        ) {

            return;

        }


        // Receiving any MQTT packet from the slave proves that the
        // slave -> broker -> Master Hub path is active.
        if (data.device) {

            const payload =
                String(data.payload ?? "")
                    .trim()
                    .toUpperCase();

            updateDeviceMQTTState(
                data.device,
                payload === "OFFLINE" ||
                payload === "DISCONNECTED"
                    ? "DISCONNECTED"
                    : "ONLINE"
            );

        }

        addConsole(

            `${data.topic || "MQTT"} -> ${data.payload || ""}`

        );

    }
);




// ==========================================================
// COMMAND RESULT DIAGNOSTICS
//
// Temporary deployment diagnostics. This does not change the UI.
// ==========================================================

websocket?.on(
    "command_result",
    data => {

        console.log(
            "[Dashboard Command Result] RECEIVED <-",
            data
        );

    }
);


// ==========================================================
// SOCKET CONNECTION STATE
//
// The native WebSocket client automatically reconnects after a
// close. Do not flood the Activity/Console panels with the same
// disconnect message on every retry. One outage produces one
// disconnect/reconnecting entry, followed by a reconnected entry.
// ==========================================================

let dashboardWsWasConnected = false;
let dashboardWsOfflineNoticeShown = false;


// ==========================================================
// SOCKET CONNECT
// ==========================================================

websocket?.on(
    "open",
    () => {

        console.log(
            "[Dashboard WS] OPEN event received"
        );

        updateMasterConnection(
            true
        );

        const wasReconnect =
            dashboardWsWasConnected ||
            dashboardWsOfflineNoticeShown;

        dashboardWsWasConnected = true;
        dashboardWsOfflineNoticeShown = false;

        addActivity(
            wasReconnect
                ? "WebSocket Reconnected"
                : "WebSocket Connected",
            "system"
        );

        addConsole(
            wasReconnect
                ? "Native WebSocket connection re-established"
                : "Native WebSocket connection established"
        );

    }
);


// ==========================================================
// SOCKET DISCONNECT
// ==========================================================

websocket?.on(
    "close",
    event => {

        console.warn(
            "[Dashboard WS] CLOSE event received ->",
            event
        );

        updateMasterConnection(
            false
        );

        // The WebSocket client schedules its own reconnect. Treat
        // the close as a temporary connection state, not as a
        // command/system error, and log it only once per outage.
        if (!dashboardWsOfflineNoticeShown) {

            dashboardWsOfflineNoticeShown = true;

            addActivity(
                "WebSocket Disconnected — reconnecting...",
                "system"
            );

            addConsole(
                "Native WebSocket disconnected — reconnecting..."
            );

        }

    }
);


// ==========================================================
// SEND COMMAND
//
// EVERY COMMAND GOES TO selectedDevice.
//
// No command can be sent without a selected device.
//
// COMMAND FORMAT:
//
//     LIFTCARFORWARD
//     LIFTCARBACKWARD
//     LIFTCARLEFT
//     LIFTCARRIGHT
//     LIFTCARSTOP
//     LIFTCARLEFT360
//     LIFTCARRIGHT360
//
// The complete command is sent as PLAINTEXT.
// ==========================================================

async function sendCommand(
    command
) {

    command =
        String(
            command
        )
        .trim()
        .toUpperCase();


    if (!command) {

        return;

    }


    // ------------------------------------------------------
    // Always refresh the selected device from the ONE
    // selector.
    // ------------------------------------------------------

    selectedDevice =
        getSelectedDevice();


    // ------------------------------------------------------
    // BLOCK COMMAND IF NO DEVICE
    // ------------------------------------------------------

    if (!selectedDevice) {

        addActivity(
            "COMMAND BLOCKED: No device selected",
            "error"
        );


        addConsole(
            "ERROR: Select a target device first",
            "error"
        );


        notify(
            "Select a device before sending a command."
        );


        return;

    }


    lastCommand =
        command;


    // ------------------------------------------------------
    // UI
    // ------------------------------------------------------

    const lastCommandElement =
        element("lastCommand");


    const lastCommandTime =
        element("lastCommandTime");


    const result =
        element("lastCommandResult");


    if (lastCommandElement) {

        lastCommandElement.textContent =
            command;

    }


    if (lastCommandTime) {

        lastCommandTime.textContent =
            now();

    }


    if (result) {

        result.textContent =
            "TRANSMITTING";

    }


    // ------------------------------------------------------
    // ACTIVITY
    // ------------------------------------------------------

    addActivity(

        `COMMAND TX [${selectedDevice}]: ${command}`,

        "tx"

    );


    addConsole(

        `TX -> ${selectedDevice} -> ${command}`,

        "tx"

    );


    // ------------------------------------------------------
    // ------------------------------------------------------
    // SEND TO MASTER HUB OVER NATIVE WEBSOCKET
    // ------------------------------------------------------

    console.log(
        "[Dashboard Command] PRE-SEND ->",
        { device: selectedDevice, command }
    );

    try {

        if (!websocket || !websocket.isConnected()) {
            throw new Error("Master Hub WebSocket is not connected");
        }

        const sent =
            websocket.send(
                "command",
                {
                    device: selectedDevice,
                    command
                }
            );

        console.log(
            "[Dashboard Command] WS SEND RESULT ->",
            { sent, device: selectedDevice, command }
        );

        if (!sent) {
            throw new Error("WebSocket transmission failed");
        }

        if (result) {
            result.textContent = "SENT";
        }

        addConsole(
            `MASTER HUB -> ${selectedDevice} -> ${command}`,
            "tx"
        );

    }
    catch (error) {

        if (result) {
            result.textContent = "FAILED";
        }

        addActivity(
            `COMMAND FAILED [${selectedDevice}]: ${error.message}`,
            "error"
        );

        addConsole(
            `ERROR: ${error.message}`,
            "error"
        );

        notify(
            `Command failed: ${error.message}`
        );
    }

}


// ==========================================================
// BUTTON CONTROLS
//
// Every data-command button uses sendCommand().
// sendCommand() always targets selectedDevice.
// ==========================================================

document
    .querySelectorAll(
        "[data-command]:not(.mobile-game-button)"
    )
    .forEach(
        button => {

            button.addEventListener(
                "click",
                () => {

                    const command =
                        button.dataset.command;


                    sendCommand(
                        command
                    );

                }
            );

        }
    );


// ==========================================================
// MOBILE GAME CONTROLS
//
// Mobile/tablet uses a game-style touch layout.
// Forward/Backward are press-and-hold movement controls.
// Releasing them sends STOP.
// Left/Right are one-shot 90-degree commands.
// ==========================================================

const mobileGameButtons =
    document.querySelectorAll(
        ".mobile-game-button"
    );

const mobileHoldCommands = new Set([
    "LIFTCARFORWARD",
    "LIFTCARBACKWARD"
]);

mobileGameButtons.forEach(button => {

    const command =
        String(
            button.dataset.command || ""
        ).trim().toUpperCase();

    if (!command) {
        return;
    }

    if (mobileHoldCommands.has(command)) {

        let active = false;

        const startMovement = event => {

            event.preventDefault();

            if (active) {
                return;
            }

            active = true;

            try {
                button.setPointerCapture(
                    event.pointerId
                );
            } catch (_) {
                // Pointer capture is optional.
            }

            button.classList.add("pressed");

            sendCommand(command);
        };

        const stopMovement = event => {

            if (event) {
                event.preventDefault();
            }

            if (!active) {
                return;
            }

            active = false;

            button.classList.remove("pressed");

            sendCommand("LIFTCARSTOP");
        };

        button.addEventListener(
            "pointerdown",
            startMovement
        );

        button.addEventListener(
            "pointerup",
            stopMovement
        );

        button.addEventListener(
            "pointercancel",
            stopMovement
        );

        button.addEventListener(
            "lostpointercapture",
            () => {
                if (active) {
                    stopMovement();
                }
            }
        );

    } else {

        button.addEventListener(
            "click",
            event => {

                event.preventDefault();

                button.classList.add("pressed");

                sendCommand(command);

                setTimeout(
                    () => {
                        button.classList.remove("pressed");
                    },
                    120
                );
            }
        );

    }

});


// ==========================================================
// EMERGENCY STOP
//
// Emergency stop also follows the selected-device model.
// ==========================================================

const emergencyButton =
    element("emergencyBtn");


if (emergencyButton) {

    emergencyButton.addEventListener(
        "click",
        () => {

            sendCommand(
                "LIFTCARSTOP"
            );


            const emergencyStatus =
                element("emergencyStatus");


            if (emergencyStatus) {

                emergencyStatus.textContent =
                    "STOP SENT";

            }


            setTimeout(
                () => {

                    if (emergencyStatus) {

                        emergencyStatus.textContent =
                            "READY";

                    }

                },
                2000
            );

        }
    );

}


// ==========================================================
// KEYBOARD TOGGLE
// ==========================================================

const keyboardToggle =
    element("keyboardToggle");


function updateKeyboardUI() {

    const text =
        element("keyboardStatusText");


    if (text) {

        text.textContent =
            keyboardEnabled
                ? "Keyboard control enabled"
                : "Keyboard control disabled";

    }


    if (keyboardToggle) {

        keyboardToggle.checked =
            keyboardEnabled;

    }

}


if (keyboardToggle) {

    keyboardToggle.addEventListener(
        "change",
        () => {

            keyboardEnabled =
                keyboardToggle.checked;


            const text =
                element("keyboardStatusText");


            if (text) {

                text.textContent =
                    keyboardEnabled
                        ? "Keyboard control enabled"
                        : "Keyboard control disabled";

            }


            addActivity(

                keyboardEnabled
                    ? "Keyboard control ENABLED"
                    : "Keyboard control DISABLED",

                "system"

            );


            if (
                keyboardEnabled &&
                !selectedDevice
            ) {

                notify(
                    "Select a target device before using keyboard control."
                );

            }

        }
    );


    updateKeyboardUI();

}


// ==========================================================
// KEYBOARD INPUT
//
// ONE keyboard listener only.
//
// WASD:
// W -> Forward
// S -> Backward
// A -> Left
// D -> Right
//
// Q -> Left 360
// E -> Right 360
//
// Arrow keys also supported.
//
// Space does NOTHING.
// Text fields are ignored.
// ==========================================================

document.addEventListener(
    "keydown",
    event => {

        if (!keyboardEnabled) {

            return;

        }


        const target =
            event.target;


        // --------------------------------------------------
        // Never interfere with typing
        // --------------------------------------------------

        if (
            target.tagName ===
                "INPUT" ||

            target.tagName ===
                "TEXTAREA" ||

            target.tagName ===
                "SELECT" ||

            target.isContentEditable
        ) {

            return;

        }


        // --------------------------------------------------
        // SPACEBAR
        //
        // SPACE -> Emergency STOP
        // --------------------------------------------------

        if (
            event.code === "Space"
        ) {

            event.preventDefault();

            // Prevent repeated STOP commands while holding Space.
            if (event.repeat) {
                return;
            }

            sendCommand(
                "LIFTCARSTOP"
            );

            return;
        }


        switch (
            event.key.toLowerCase()
        ) {

            case "w":

                command =
                    "LIFTCARFORWARD";

                break;


            case "s":

                command =
                    "LIFTCARBACKWARD";

                break;


            case "a":

                command =
                    "LIFTCARLEFT";

                break;


            case "d":

                command =
                    "LIFTCARRIGHT";

                break;


            case "q":

                command =
                    "LIFTCARLEFT360";

                break;


            case "e":

                command =
                    "LIFTCARRIGHT360";

                break;


            case "arrowup":

                command =
                    "LIFTCARFORWARD";

                break;


            case "arrowdown":

                command =
                    "LIFTCARBACKWARD";

                break;


            case "arrowleft":

                command =
                    "LIFTCARLEFT";

                break;


            case "arrowright":

                command =
                    "LIFTCARRIGHT";

                break;

        }


        if (!command) {

            return;

        }


        event.preventDefault();


        sendCommand(
            command
        );

    }
);


// ==========================================================
// CONSOLE
//
// Console commands also use selectedDevice.
// ==========================================================

const consoleForm =
    element("consoleForm");


if (consoleForm) {

    consoleForm.addEventListener(
        "submit",
        event => {

            event.preventDefault();


            const input =
                element("consoleInput");


            if (!input) {

                return;

            }


            const command =
                input.value
                    .trim()
                    .toUpperCase();


            if (!command) {

                return;

            }


            sendCommand(
                command
            );


            input.value =
                "";

        }
    );

}


// ==========================================================
// CLEAR LOGS
// ==========================================================

const clearLogs =
    element("clearLogsBtn");


if (clearLogs) {

    clearLogs.addEventListener(
        "click",
        () => {

            const activity =
                element("activityLog");


            const consoleOutput =
                element("consoleOutput");


            if (activity) {

                activity.innerHTML =
                    "";

            }


            if (consoleOutput) {

                consoleOutput.innerHTML =
                    "";

            }


            localStorage.removeItem(
                ACTIVITY_LOG_KEY
            );


            localStorage.removeItem(
                CONSOLE_LOG_KEY
            );


            renderConsole(
                "Logs cleared.",
                "system",
                now()
            );

        }
    );

}


// ==========================================================
// DOWNLOAD ACTIVITY / CONSOLE LOGS
//
// Supported sources:
//   activity -> Activity Log only
//   console  -> Command Console only
//   both     -> Activity + Console
//
// Supported formats:
//   txt -> Human-readable text
//   csv -> Spreadsheet-friendly CSV
//   json -> Structured JSON
// ==========================================================

const downloadActivityButton =
    element("downloadActivityBtn");

const downloadLogSource =
    element("downloadLogSource");

const downloadLogFormat =
    element("downloadLogFormat");


function readStoredLogs(key) {

    try {

        const parsed =
            JSON.parse(
                localStorage.getItem(key) || "[]"
            );

        return Array.isArray(parsed)
            ? parsed
            : [];

    }
    catch (error) {

        console.error(
            "Failed to read stored logs:",
            error
        );

        return [];

    }

}


function csvEscape(value) {

    const text =
        String(value ?? "");

    return `"${text.replace(/"/g, '""')}"`;

}


function buildTxtLog(logGroups) {

    let output =
        "============================================================\n";

    output +=
        "SYNAPTIMESH MASTER HUB\n";

    output +=
        "SYSTEM LOG EXPORT\n";

    output +=
        "============================================================\n\n";


    logGroups.forEach(group => {

        output +=
            `-------------------- ${group.title} --------------------\n`;

        output +=
            `Entries: ${group.logs.length}\n\n`;


        if (group.logs.length === 0) {

            output +=
                "No logs available.\n\n";

            return;

        }


        group.logs.forEach(entry => {

            const time =
                entry.time || "--";

            const type =
                entry.type || "system";

            const message =
                entry.message || "";

            output +=
                `[${time}] [${type}] ${message}\n`;

        });


        output += "\n";

    });


    output +=
        "============================================================\n";

    output +=
        "END OF SYSTEM LOG EXPORT\n";

    output +=
        "============================================================\n";


    return output;

}


function buildJsonLog(logGroups) {

    const exportedAt =
        new Date().toISOString();

    const result = {
        application:
            "SynaptiMesh Master Hub",

        exported_at:
            exportedAt,

        logs: {}
    };


    logGroups.forEach(group => {

        result.logs[group.key] =
            group.logs;

    });


    return JSON.stringify(
        result,
        null,
        2
    );

}


function getLogExportGroups(source) {

    const activityLogs =
        readStoredLogs(
            ACTIVITY_LOG_KEY
        );

    const consoleLogs =
        readStoredLogs(
            CONSOLE_LOG_KEY
        );


    if (source === "console") {

        return [
            {
                key: "console",
                title: "COMMAND CONSOLE",
                logs: consoleLogs
            }
        ];

    }


    if (source === "both") {

        return [
            {
                key: "activity",
                title: "ACTIVITY LOG",
                logs: activityLogs
            },
            {
                key: "console",
                title: "COMMAND CONSOLE",
                logs: consoleLogs
            }
        ];

    }


    return [
        {
            key: "activity",
            title: "ACTIVITY LOG",
            logs: activityLogs
        }
    ];

}


function downloadLogFile() {

    try {

        const source =
            downloadLogSource?.value ||
            "activity";

        const format =
            downloadLogFormat?.value ||
            "txt";

        const logGroups =
            getLogExportGroups(source);

        const timestamp =
            new Date();

        const date =
            timestamp
                .toISOString()
                .slice(0, 10);

        const time =
            timestamp
                .toTimeString()
                .slice(0, 8)
                .replace(/:/g, "-");

        const sourceName =
            source === "both"
                ? "Activity_Console"
                : source === "console"
                    ? "Console"
                    : "Activity";


        let content;
        let mimeType;
        let extension;


        if (format === "csv") {

            // CSV exports use one combined table. When both logs are
            // selected, the Source column keeps Activity and Console
            // entries distinguishable.
            const rows = [
                [
                    "Source",
                    "Timestamp",
                    "Type",
                    "Message"
                ]
            ];


            logGroups.forEach(group => {

                group.logs.forEach(entry => {

                    rows.push([
                        group.key,
                        entry.time || "--",
                        entry.type || "system",
                        entry.message || ""
                    ]);

                });

            });


            content =
                rows
                    .map(row =>
                        row
                            .map(csvEscape)
                            .join(",")
                    )
                    .join("\r\n") + "\r\n";

            mimeType =
                "text/csv;charset=utf-8";

            extension =
                "csv";

        }
        else if (format === "json") {

            content =
                buildJsonLog(
                    logGroups
                );

            mimeType =
                "application/json;charset=utf-8";

            extension =
                "json";

        }
        else {

            content =
                buildTxtLog(
                    logGroups
                );

            mimeType =
                "text/plain;charset=utf-8";

            extension =
                "txt";

        }


        const blob =
            new Blob(
                [content],
                { type: mimeType }
            );

        const url =
            URL.createObjectURL(
                blob
            );

        const filename =
            `SynaptiMesh_${sourceName}_Log_${date}_${time}.${extension}`;

        const link =
            document.createElement("a");

        link.href =
            url;

        link.download =
            filename;

        document.body.appendChild(
            link
        );

        link.click();

        document.body.removeChild(
            link
        );

        URL.revokeObjectURL(
            url
        );


        const sourceLabel =
            source === "both"
                ? "Activity + Console"
                : source === "console"
                    ? "Console"
                    : "Activity";

        const formatLabel =
            format.toUpperCase();

        addActivity(
            `${sourceLabel} log downloaded as ${formatLabel}.`,
            "system"
        );

        notify(
            `${sourceLabel} log downloaded as ${formatLabel}.`
        );

    }
    catch (error) {

        console.error(
            "Failed to download logs:",
            error
        );

        addActivity(
            "Failed to download log.",
            "error"
        );

        notify(
            "Unable to download log."
        );

    }

}


if (downloadActivityButton) {

    downloadActivityButton.addEventListener(
        "click",
        downloadLogFile
    );

}


// ==========================================================
// FOOTER CLOCK
// ==========================================================

function updateClock() {

    const footer =
        element("footerTime");


    if (footer) {

        footer.textContent =
            new Date()
                .toLocaleTimeString();

    }

}


setInterval(
    updateClock,
    1000
);


updateClock();


// ==========================================================
// INITIAL
// ==========================================================

loadSavedLogs();


addActivity(
    "Dashboard initialized",
    "system"
);


addConsole(
    "Single-device targeting active.",
    "system"
);


// ==========================================================
// WEBSOCKET TELEMETRY & ALERT INTEGRATION (Sprint 11 Day 5)
// ==========================================================
if (websocket && typeof websocket.on === "function") {
    websocket.on("open", () => {
        const status = element("connectionStatus");
        if (status) status.textContent = "CONNECTED";
        addActivity("WebSocket Connected to Master Hub", "system");
    });

    websocket.on("close", () => {
        const status = element("connectionStatus");
        if (status) status.textContent = "DISCONNECTED";
        addActivity("WebSocket Disconnected", "system");
    });

    websocket.on("telemetry", (data) => {
        if (!data) return;
        const devId = data.device || data.device_id;
        if (selectedDevice && devId && devId !== selectedDevice && selectedDevice !== "98:A3:16:BF:2C:C0") {
            return;
        }

        // Update Movement
        if (data.state) {
            updateMovement(data.state);
        }

        // Update Robot / Device Status
        if (data.status) {
            updateRobotStatus(data.status);
        }

        // Update Battery SoC
        if (data.battery_soc_pct !== undefined && data.battery_soc_pct !== null) {
            const pct = Math.min(100, Math.max(0, Number(data.battery_soc_pct)));
            const batEl = element("carBatterySoc") || element("batteryLevel");
            if (batEl) batEl.textContent = `${pct}%`;
        }

        // Update Supply Voltage
        if (data.supply_voltage_v !== undefined && data.supply_voltage_v !== null) {
            const voltEl = element("carSupplyVoltage") || element("supplyVoltage");
            if (voltEl) voltEl.textContent = `${data.supply_voltage_v} V`;
        }

        // Update Obstacles & Distances
        if (data.front_distance !== undefined && data.front_distance !== null) {
            const front = element("frontDistance");
            if (front) front.textContent = `${data.front_distance} cm`;
        }
        if (data.rear_distance !== undefined && data.rear_distance !== null) {
            const rear = element("rearDistance");
            if (rear) rear.textContent = `${data.rear_distance} cm`;
        }
    });

    websocket.on("alert", (data) => {
        if (!data) return;
        const devId = data.device_id || data.device;
        if (selectedDevice && devId && devId !== selectedDevice) {
            return;
        }
        const sev = String(data.severity || "INFO").toUpperCase();
        const msg = data.message || `Alert: ${data.alert_type}`;
        addActivity(`[${sev} ALERT] ${msg}`, sev === "CRITICAL" || sev === "ERROR" ? "error" : "warning");
        addConsole(`ALERT -> [${sev}] ${msg}`, "alert");
        if (sev === "CRITICAL") {
            notify(`CRITICAL: ${msg}`, true);
        }
    });

    websocket.on("ALERT", (data) => {
        if (!data) return;
        const payload = data.payload || data;
        const devId = payload.device_id || payload.device || data.source_id;
        if (selectedDevice && devId && devId !== selectedDevice) {
            return;
        }
        const sev = String(payload.severity || "INFO").toUpperCase();
        const msg = payload.message || `Alert: ${payload.alert_type}`;
        addActivity(`[${sev} ALERT] ${msg}`, sev === "CRITICAL" || sev === "ERROR" ? "error" : "warning");
        addConsole(`ALERT -> [${sev}] ${msg}`, "alert");
        if (sev === "CRITICAL") {
            notify(`CRITICAL: ${msg}`, true);
        }
    });

    websocket.on("device_status", (data) => {
        if (!data || !data.device) return;
        if (selectedDevice && data.device !== selectedDevice) return;
        updateRobotStatus(data.status);
    });

    websocket.on("ack", (data) => {
        if (!data) return;
        if (selectedDevice && data.device && data.device !== selectedDevice) return;
        const ack = data.ack || data.message || "ACK";
        const ackEl = element("ackMessage");
        if (ackEl) ackEl.textContent = ack;
    });
}