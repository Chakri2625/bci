/* ==========================================================
   SYNAPTIMESH CAR CONTROL
   Smooth TPP Vehicle Simulation
   ========================================================== */

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

const websocket = window.SynaptiMeshWebSocket;


/* ==========================================================
   STATE
   ========================================================== */

const state = {
    selectedDevice: "",
    keyboardEnabled: true,
    currentCommand: "LIFTCARSTOP",
    modelLoaded: false,
    moving: false
};


/* ==========================================================
   DOM HELPER
   ========================================================== */

const el = (id) => document.getElementById(id);


/* ==========================================================
   MQTT CONNECTION STATE
   ========================================================== */

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

function getOverallMQTTState() {
    const brokerState = mqttConnection.broker.state;

    if (brokerState === "OFFLINE") {
        return "OFFLINE";
    }

    if (brokerState === "DISCONNECTED") {
        return "DISCONNECTED";
    }

    const deviceState =
        state.selectedDevice
            ? getDeviceMqttState(state.selectedDevice).state
            : "OFFLINE";

    if (deviceState === "ONLINE") {
        return "ONLINE";
    }

    if (deviceState === "DISCONNECTED") {
        return "DISCONNECTED";
    }

    return "CONNECTED";
}

function setMQTTLine(id, lineState) {
    const line = el(id);
    if (!line) return;

    line.classList.remove("active", "disconnected", "inactive");
    line.classList.add(lineState);
}

function setMQTTNode(id, nodeState) {
    const node = el(id);
    if (!node) return;

    node.classList.remove("active", "disconnected", "inactive");
    node.classList.add(nodeState);
}

function updateOneMQTTDiagram(ids) {
    const overall = getOverallMQTTState();
    const brokerConnected = mqttConnection.broker.state === "CONNECTED";
    const brokerBroken = mqttConnection.broker.state === "DISCONNECTED";

    const deviceState =
        state.selectedDevice
            ? getDeviceMqttState(state.selectedDevice).state
            : "OFFLINE";

    const deviceOnline = deviceState === "ONLINE";
    const deviceBroken = deviceState === "DISCONNECTED";

    const stateElement = el(ids.state);
    if (stateElement) {
        stateElement.textContent = overall;
        stateElement.classList.toggle("online", overall === "ONLINE");
        stateElement.classList.toggle("connected", overall === "CONNECTED");
        stateElement.classList.toggle("disconnected", overall === "DISCONNECTED");
        stateElement.classList.toggle("offline", overall === "OFFLINE");
    }

    if (brokerConnected) {
        setMQTTLine(ids.hubBrokerLine, "active");
        setMQTTNode(ids.hubNode, "active");
        setMQTTNode(ids.brokerNode, "active");
    } else if (brokerBroken) {
        setMQTTLine(ids.hubBrokerLine, "disconnected");
        setMQTTNode(ids.hubNode, "disconnected");
        setMQTTNode(ids.brokerNode, "disconnected");
    } else {
        setMQTTLine(ids.hubBrokerLine, "inactive");
        setMQTTNode(ids.hubNode, "inactive");
        setMQTTNode(ids.brokerNode, "inactive");
    }

    if (deviceOnline) {
        setMQTTLine(ids.brokerSlaveLine, "active");
        setMQTTNode(ids.slaveNode, "active");
    } else if (deviceBroken) {
        setMQTTLine(ids.brokerSlaveLine, "disconnected");
        setMQTTNode(ids.slaveNode, "disconnected");
    } else {
        setMQTTLine(ids.brokerSlaveLine, "inactive");
        setMQTTNode(ids.slaveNode, "inactive");
    }

    const brokerText = el(ids.brokerText);
    const slaveText = el(ids.slaveText);

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

function updateMQTTConnectionUI() {
    updateOneMQTTDiagram({
        state: "mqttDiagramState",
        hubBrokerLine: "mqttLineHubBroker",
        hubNode: "mqttNodeHub",
        brokerNode: "mqttNodeBroker",
        brokerSlaveLine: "mqttLineBrokerSlave",
        slaveNode: "mqttNodeSlave",
        brokerText: "mqttBrokerConnectionText",
        slaveText: "mqttSlaveConnectionText"
    });

    updateOneMQTTDiagram({
        state: "fullscreenMqttDiagramState",
        hubBrokerLine: "fullscreenMqttLineHubBroker",
        hubNode: "fullscreenMqttNodeHub",
        brokerNode: "fullscreenMqttNodeBroker",
        brokerSlaveLine: "fullscreenMqttLineBrokerSlave",
        slaveNode: "fullscreenMqttNodeSlave",
        brokerText: "fullscreenMqttBrokerConnectionText",
        slaveText: "fullscreenMqttSlaveConnectionText"
    });
}


/* ==========================================================
   VISUAL STATE HELPER
   ========================================================== */

function updateVisualState(value) {
    const visual = el("visualState");

    if (visual) {
        visual.textContent = String(value || "STOP");
    }
}


/* ==========================================================
   TIME
   ========================================================== */

function now() {
    return new Date().toLocaleTimeString();
}


/* ==========================================================
   NOTIFICATION
   ========================================================== */

function notify(message) {
    const box = el("notification");
    const text = el("notificationMessage");

    if (!box || !text) return;

    text.textContent = message;
    box.classList.add("show");

    clearTimeout(notify.timer);

    notify.timer = setTimeout(() => {
        box.classList.remove("show");
    }, 2200);
}


/* ==========================================================
   FOOTER CLOCK
   ========================================================== */

function updateFooterTime() {
    const footer = el("footerTime");

    if (footer) {
        footer.textContent = now();
    }
}

setInterval(updateFooterTime, 1000);
updateFooterTime();


/* ==========================================================
   3D VARIABLES
   ========================================================== */

let scene;
let camera;
let renderer;
let carRoot;
let timer;

let lastFrameTime = performance.now();
let frameCount = 0;
let fps = 0;

const WORLD_CHUNK_SIZE = 30;
const WORLD_RENDER_RADIUS = 2;
const WORLD_PATTERN_CELL_SIZE = 5;
const worldChunks = new Map();
let currentWorldChunkX = null;
let currentWorldChunkZ = null;
let worldMaterial = null;
let worldGrid = null;
let worldPatternGrid = null;

/*
 * Simulation floor themes.
 * NIGHT keeps the original dark environment. HIGH CONTRAST
 * makes the square pattern much easier to see while driving.
 */
let simulationTheme = "night";
let simulationThemeButton = null;
let simulationFullscreenButton = null;

const SIMULATION_THEMES = {
    night: {
        label: "NIGHT",
        background: 0x050812,
        floor: 0x101522,
        majorA: 0x24354a,
        majorB: 0x172333,
        fineA: 0x26394f,
        fineB: 0x1b2a3b
    },
    contrast: {
        label: "HIGH CONTRAST",
        background: 0x20252b,
        floor: 0x68727d,
        majorA: 0x17202a,
        majorB: 0x2b3742,
        fineA: 0xd7e0e8,
        fineB: 0x8e9aa6
    }
};

let wheelObjects = [];

/*
 * Each wheel stores its local axle axis and approximate radius.
 * The GLB contains the model appearance; this file handles
 * loading, movement, wheel animation, controls and sensors.
 */

let frontObstacleMesh = null;
let rearObstacleMesh = null;
const obstacleMaterial = new THREE.MeshStandardMaterial({
    color: 0xff5a36,
    roughness: 0.65,
    metalness: 0.05
});


/*
 * Ultrasonic obstacle state.
 *
 * The dashboard starts CLEAR. An obstacle message activates the
 * corresponding direction and refreshes its timeout. If no newer
 * obstacle message arrives before the timeout expires, that side
 * automatically returns to CLEAR.
 */
const OBSTACLE_DISPLAY_TIMEOUT = 2000;

const obstacleState = {
    front: false,
    rear: false,
    frontTimer: null,
    rearTimer: null
};


/* ==========================================================
   VEHICLE PHYSICS / MOTION
   ========================================================== */

/*
 * carRoot is the vehicle controller.
 *
 * The GLB is a child of carRoot.
 *
 * Y = vertical
 * X/Z = ground movement
 *
 * carRoot.rotation.y = vehicle heading
 */

let carHeading = 0;

/* Fullscreen third-person mouse look state. */
let mouseLookYaw = 0;
let mouseLookPitch = 0;
let mousePointerLocked = false;
const MOUSE_LOOK_SENSITIVITY = 0.0025;
const MOUSE_LOOK_MIN_PITCH = -0.55;
const MOUSE_LOOK_MAX_PITCH = 0.35;


/*
 * Current velocity.
 *
 * These are intentionally separate from the target values.
 * That gives us smooth acceleration/deceleration.
 */

let currentSpeed = 0;
let targetSpeed = 0;


/*
 * Turning velocity.
 */

let currentTurnSpeed = 0;
let targetTurnSpeed = 0;


/*
 * Smooth movement tuning.
 */

const MAX_FORWARD_SPEED = 2.8;
const MAX_REVERSE_SPEED = 2.0;

const ACCELERATION = 7.0;
const DECELERATION = 9.0;

const MAX_TURN_SPEED = 2.2;
const TURN_ACCELERATION = 8.0;
const TURN_DECELERATION = 10.0;


/*
 * 360° spin state.
 */

let spinRemaining = 0;

const SPIN_SPEED = Math.PI * 2.5;


/* ==========================================================
   3D INITIALIZATION
   ========================================================== */

function init3D() {

    const viewport = el("car3dViewport");

    if (!viewport) {

        if (el("modelStatus")) {
            el("modelStatus").textContent = "3D ERROR";
        }

        return;
    }


    /* ------------------------------------------------------
       SCENE
       ------------------------------------------------------ */

    scene = new THREE.Scene();

    scene.background =
        new THREE.Color(0x050812);


    /* ------------------------------------------------------
       CAMERA
       ------------------------------------------------------ */

    camera =
        new THREE.PerspectiveCamera(
            45,
            viewport.clientWidth /
                Math.max(viewport.clientHeight, 1),
            0.1,
            1000
        );


    /*
     * Initial camera position.
     *
     * This is only the starting position.
     * updateTPPCamera() continuously moves it.
     */

    camera.position.set(
        3.2,
        3.8,
        6.8
    );


    camera.lookAt(
        0,
        0.65,
        0
    );


    /* ------------------------------------------------------
       RENDERER
       ------------------------------------------------------ */

    renderer =
        new THREE.WebGLRenderer({
            antialias: true,
            alpha: true,
            powerPreference: "high-performance"
        });


    renderer.setPixelRatio(
        Math.min(
            window.devicePixelRatio || 1,
            2.0
        )
    );


    renderer.setSize(
        viewport.clientWidth,
        viewport.clientHeight
    );


    /*
     * PBR Color Management & ACES Filmic Tone Mapping.
     * Crucial for GLTF models so metallic and roughness materials
     * match Babylon.js Sandbox and standard glTF viewers.
     */
    THREE.ColorManagement.enabled = true;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.35;

    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;


    viewport.appendChild(
        renderer.domElement
    );


    /* ------------------------------------------------------
       STUDIO PBR ENVIRONMENT & LIGHTING RIG
       ------------------------------------------------------ */

    /*
     * 1. Studio IBL Environment:
     * Reflective metallic materials (e.g. blue body & sensor bars)
     * require an environment map to produce natural surface reflections.
     */
    try {
        const pmremGenerator = new THREE.PMREMGenerator(renderer);
        pmremGenerator.compileEquirectangularShader();
        const roomEnv = new RoomEnvironment();
        scene.environment = pmremGenerator.fromScene(roomEnv, 0.04).texture;
        roomEnv.dispose();
        pmremGenerator.dispose();
    } catch (e) {
        console.warn("[3D] RoomEnvironment setup skipped:", e);
    }

    /*
     * 2. Ambient Sky/Ground fill light
     */
    const ambient =
        new THREE.HemisphereLight(
            0xffffff,
            0x334455,
            2.0
        );

    scene.add(ambient);


    /*
     * 3. Key top-front directional light with soft shadows
     */
    const key =
        new THREE.DirectionalLight(
            0xffffff,
            2.8
        );

    key.position.set(
        6,
        12,
        8
    );

    key.castShadow = true;
    key.shadow.mapSize.width = 2048;
    key.shadow.mapSize.height = 2048;
    key.shadow.bias = -0.0001;

    scene.add(key);


    /*
     * 4. Fill Left Light (cool cyan-white)
     */
    const fillLeft =
        new THREE.DirectionalLight(
            0xddeeff,
            2.0
        );

    fillLeft.position.set(
        -8,
        9,
        6
    );

    scene.add(fillLeft);


    /*
     * 5. Fill Right Light (warm white)
     */
    const fillRight =
        new THREE.DirectionalLight(
            0xffeedd,
            1.8
        );

    fillRight.position.set(
        8,
        7,
        7
    );

    scene.add(fillRight);


    /*
     * 6. Rear Rim / Silhouette Light
     * Emphasizes wheels, spoiler, and chassis contour.
     */
    const rimLight =
        new THREE.DirectionalLight(
            0x88ccff,
            2.2
        );

    rimLight.position.set(
        0,
        8,
        -9
    );

    scene.add(rimLight);


    /*
     * 7. Undercarriage Bounce Light
     * Illuminates tires, bottom chassis, and wheel wells.
     */
    const underLight =
        new THREE.DirectionalLight(
            0x556677,
            1.2
        );

    underLight.position.set(
        0,
        -6,
        0
    );

    scene.add(underLight);


    /*
     * 8. Front Accent Point Light
     */
    const accentLight =
        new THREE.PointLight(
            0x00f6ff,
            15,
            25
        );

    accentLight.position.set(
        0,
        3,
        5
    );

    scene.add(accentLight);


    /* ------------------------------------------------------
       SIMULATION THEME
       ------------------------------------------------------ */

    createSimulationThemeToggle();


    /* ------------------------------------------------------
       PROCEDURAL WORLD
       ------------------------------------------------------ */

    worldMaterial = new THREE.MeshStandardMaterial({
        color: SIMULATION_THEMES.night.floor,
        roughness: 0.92,
        metalness: 0.08
    });

    const worldSize =
        WORLD_CHUNK_SIZE *
        (WORLD_RENDER_RADIUS * 2 + 1);

    /*
     * Major grid: keeps the existing large navigation grid.
     */
    worldGrid = new THREE.GridHelper(
        worldSize,
        WORLD_RENDER_RADIUS * 2 + 1,
        SIMULATION_THEMES.night.majorA,
        SIMULATION_THEMES.night.majorB
    );
    worldGrid.position.y = 0.012;
    scene.add(worldGrid);

    /*
     * Fine square pattern: adds smaller, evenly sized floor
     * cells so movement is much easier to see from the TPP camera.
     * The pattern is world-based and follows the same chunk origin
     * as the existing grid, so it does not move with the car.
     */
    const patternDivisions =
        Math.round(worldSize / WORLD_PATTERN_CELL_SIZE);

    worldPatternGrid = new THREE.GridHelper(
        worldSize,
        patternDivisions,
        SIMULATION_THEMES.night.fineA,
        SIMULATION_THEMES.night.fineB
    );
    worldPatternGrid.position.y = 0.016;
    scene.add(worldPatternGrid);

    /* Re-apply the active theme now that both grid objects exist. */
    const activeTheme = SIMULATION_THEMES[simulationTheme];
    if (activeTheme) {
        const setGridColors = (grid, colorA, colorB) => {
            if (!grid?.material) return;
            const materials = Array.isArray(grid.material)
                ? grid.material
                : [grid.material];
            if (materials[0]?.color) materials[0].color.setHex(colorA);
            if (materials[1]?.color) materials[1].color.setHex(colorB);
        };
        worldMaterial.color.setHex(activeTheme.floor);
        setGridColors(worldGrid, activeTheme.majorA, activeTheme.majorB);
        setGridColors(worldPatternGrid, activeTheme.fineA, activeTheme.fineB);
    }

    updateWorldChunks(true);


    /* ------------------------------------------------------
       VEHICLE CONTROLLER
       ------------------------------------------------------ */

    carRoot =
        new THREE.Group();


    carRoot.position.set(
        0,
        0,
        0
    );


    carRoot.rotation.y = 0;

    scene.add(carRoot);


    /* ------------------------------------------------------
       LOAD ROBOT
       ------------------------------------------------------ */

    loadRobotModel();


    /* ------------------------------------------------------
       TIMER
       Three.js Timer replaces the deprecated Clock API.
       ------------------------------------------------------ */

    timer =
        new THREE.Timer();

    timer.connect(document);


    /* ------------------------------------------------------
       RESIZE
       ------------------------------------------------------ */

    resize3D();


    window.addEventListener(
        "resize",
        resize3D
    );

    setupFullscreenMouseLook();


    /* ------------------------------------------------------
       START ANIMATION
       ------------------------------------------------------ */

    animate();
}


/* ==========================================================
   PROCEDURAL WORLD CHUNKS
   ========================================================== */

function getChunkKey(x, z) {
    return `${x},${z}`;
}

function getCurrentChunkCoordinate(value) {
    return Math.floor(value / WORLD_CHUNK_SIZE);
}

function performQuarterTurn(direction) {
    if (!state.selectedDevice) {
        notify("Select a device first before turning.");
        return;
    }

    if (!carRoot) {
        return;
    }

    /*
     * A / D are precise 90° simulation turns. They rotate the
     * 3D vehicle in place without introducing a new MQTT command
     * that the ESP32 firmware may not understand.
     */
    heldMovementKeys.clear();
    lastKeyboardHardwareCommand = "LIFTCARSTOP";
    targetSpeed = 0;
    targetTurnSpeed = 0;

    spinRemaining +=
        direction === "left"
            ? Math.PI / 2
            : -Math.PI / 2;

    state.currentCommand =
        direction === "left"
            ? "LIFTCARLEFT90"
            : "LIFTCARRIGHT90";

    updateVisualState(
        direction === "left"
            ? "LEFT 90°"
            : "RIGHT 90°"
    );

    notify(
        direction === "left"
            ? "Simulation turned left 90°."
            : "Simulation turned right 90°."
    );

    /*
     * LEFT/RIGHT are one-shot hardware commands.
     * The ESP32 slave performs the 90° turn and stops itself, so
     * the browser must NOT send a follow-up LIFTCARSTOP.
     */
    sendCommand(
        direction === "left"
            ? "LIFTCARLEFT"
            : "LIFTCARRIGHT",
        false
    );
}


function setupSimulationFullscreen(card, viewport, button) {
    if (!card || !viewport || !button) {
        return;
    }

    /*
     * IMPORTANT:
     * The fullscreen device menu is defined in the HTML itself.
     * We do NOT create or move the dropdown dynamically.
     *
     * Normal page selector:
     *   #deviceSelector
     * Fullscreen selector:
     *   #fullscreenDeviceSelector
     *
     * Both controls use the same SynaptiMeshCommand manager, so there is
     * only one actual selected-device state.
     */
    const deviceSelector = document.querySelector("#deviceSelector");
    const fullscreenHud = document.querySelector("#fullscreenDeviceHud");
    const fullscreenSelector =
        document.querySelector("#fullscreenDeviceSelector");
    const fullscreenDeviceInfo =
        document.querySelector("#fullscreenSelectedDeviceInfo");
    const fullscreenStatus =
        document.querySelector("#fullscreenTargetStatus");

    const fullscreenMqttPanel =
        document.querySelector("#fullscreenMqttConnectionPanel");

    if (!fullscreenHud || !fullscreenSelector) {
        console.warn("[3D] Fullscreen device dropdown markup is missing.");
        return;
    }

    const syncFullscreenSelection = () => {
        const selected =
            window.SynaptiMeshCommand?.getSelectedDevice?.() ||
            deviceSelector?.value ||
            "";

        if (fullscreenSelector.value !== selected) {
            fullscreenSelector.value = selected;
        }

        if (fullscreenDeviceInfo) {
            fullscreenDeviceInfo.textContent = selected
                ? `Target: ${selected}`
                : "No device selected";
        }
    };

    const syncFullscreenStatus = () => {
        const sourceStatus = document.querySelector("#robotStatus");

        const rawStatus = String(
            sourceStatus?.textContent || "UNKNOWN"
        ).trim().toUpperCase();

        let label = "UNKNOWN";
        let online = false;

        if (
            rawStatus.includes("ONLINE") ||
            rawStatus.includes("CONNECTED") ||
            rawStatus === "READY" ||
            rawStatus === "LIVE"
        ) {
            label = "ONLINE";
            online = true;
        } else if (
            rawStatus.includes("OFFLINE") ||
            rawStatus.includes("DISCONNECTED")
        ) {
            label = "OFFLINE";
        } else if (rawStatus) {
            label = rawStatus;
        }

        if (fullscreenStatus) {
            fullscreenStatus.textContent = label;
            fullscreenStatus.classList.toggle("online", online);
            fullscreenStatus.classList.toggle("offline", !online);
        }
    };

    const handleFullscreenSelection = () => {
        const value = fullscreenSelector.value;

        if (window.SynaptiMeshCommand?.setSelectedDevice) {
            window.SynaptiMeshCommand.setSelectedDevice(value);
        } else if (deviceSelector) {
            deviceSelector.value = value;
            deviceSelector.dispatchEvent(
                new Event("change", { bubbles: true })
            );
        }

        syncFullscreenSelection();
    };

    fullscreenSelector.addEventListener(
        "change",
        handleFullscreenSelection
    );

    const updateFullscreenState = () => {
        const active = document.fullscreenElement === card;

        fullscreenHud.hidden = !active;
        fullscreenHud.setAttribute("aria-hidden", active ? "false" : "true");

        if (fullscreenMqttPanel) {
            fullscreenMqttPanel.hidden = !active;
            fullscreenMqttPanel.setAttribute(
                "aria-hidden",
                active ? "false" : "true"
            );
        }

        if (active) {
            mouseLookYaw = 0;
            mouseLookPitch = 0;
            syncFullscreenSelection();
            syncFullscreenStatus();

            button.textContent = "FULLSCREEN";
            button.setAttribute(
                "aria-label",
                "Simulation is fullscreen; press Esc to exit"
            );
            button.setAttribute("aria-pressed", "true");
            button.hidden = true;
        } else {
            button.textContent = "FULLSCREEN";
            button.setAttribute(
                "aria-label",
                "Open simulation fullscreen"
            );
            button.setAttribute("aria-pressed", "false");
            button.hidden = false;
        }

        resize3D();
    };

    button.addEventListener(
        "click",
        async () => {
            try {
                if (document.fullscreenElement === card) {
                    await document.exitFullscreen();
                } else if (
                    card.requestFullscreen &&
                    document.fullscreenEnabled !== false
                ) {
                    await card.requestFullscreen({
                        navigationUI: "hide"
                    });
                } else {
                    notify(
                        "Fullscreen is not supported by this browser."
                    );
                }
            } catch (error) {
                console.warn(
                    "[3D] Fullscreen request failed.",
                    error
                );

                button.hidden = false;
                button.setAttribute("aria-pressed", "false");

                notify("Fullscreen could not be opened.");
            }
        }
    );

    document.addEventListener(
        "fullscreenchange",
        updateFullscreenState
    );

    window.addEventListener(
        "resize",
        () => {
            if (document.fullscreenElement === card) {
                resize3D();
            }
        }
    );

    window.addEventListener(
        "synaptimesh:device-changed",
        syncFullscreenSelection
    );

    window.addEventListener(
        "synaptimesh:robot-status-updated",
        syncFullscreenStatus
    );

    syncFullscreenSelection();
    syncFullscreenStatus();
    updateMQTTConnectionUI();
    updateFullscreenState();
}

function createSimulationThemeToggle() {
    /*
     * Keep the theme control OUTSIDE the WebGL viewport.
     * This prevents it from overlapping the simulation state/ACK overlay
     * and makes it a normal, reliable UI control.
     */
    const card = document.querySelector(".car-view-card");
    const header = card?.querySelector(".card-header");

    if (!header || simulationThemeButton) {
        return;
    }

    const control = document.createElement("button");
    control.type = "button";
    control.className = "simulation-theme-toggle";
    control.setAttribute("aria-label", "Switch simulation theme");
    control.setAttribute("aria-pressed", "false");
    control.style.cssText = [
        "display:flex",
        "align-items:center",
        "gap:9px",
        "min-width:142px",
        "justify-content:space-between",
        "padding:7px 9px 7px 11px",
        "border:1px solid rgba(255,255,255,.14)",
        "border-radius:999px",
        "background:rgba(255,255,255,.045)",
        "color:inherit",
        "font:800 9px/1 Arial,sans-serif",
        "letter-spacing:.06em",
        "cursor:pointer",
        "user-select:none",
        "outline:none",
        "transition:background .2s ease,border-color .2s ease,transform .12s ease"
    ].join(";");

    const text = document.createElement("span");
    text.textContent = "SIM: NIGHT";
    text.style.cssText = "white-space:nowrap;pointer-events:none";

    const track = document.createElement("span");
    track.style.cssText = [
        "position:relative",
        "flex:0 0 auto",
        "width:34px",
        "height:18px",
        "display:block",
        "border-radius:999px",
        "background:#26394f",
        "border:1px solid rgba(255,255,255,.28)",
        "box-sizing:border-box",
        "transition:.2s ease",
        "pointer-events:none"
    ].join(";");

    const knob = document.createElement("span");
    knob.style.cssText = [
        "position:absolute",
        "top:2px",
        "left:2px",
        "width:12px",
        "height:12px",
        "border-radius:50%",
        "background:#fff",
        "box-shadow:0 1px 4px rgba(0,0,0,.35)",
        "transition:.2s ease",
        "pointer-events:none"
    ].join(";");

    track.appendChild(knob);
    control.appendChild(text);
    control.appendChild(track);

    /* ------------------------------------------------------
       SIMULATION HEADER CONTROLS
       ------------------------------------------------------ */

    const controls = document.createElement("div");
    controls.className = "simulation-header-controls";
    controls.style.cssText = [
        "display:flex",
        "align-items:center",
        "justify-content:flex-end",
        "gap:7px",
        "flex-wrap:wrap",
        "margin-left:auto"
    ].join(";");

    const makeActionButton = (label, title) => {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = label;
        button.title = title;
        button.style.cssText = [
            "min-height:32px",
            "padding:6px 10px",
            "border:1px solid rgba(255,255,255,.14)",
            "border-radius:9px",
            "background:rgba(255,255,255,.045)",
            "color:inherit",
            "font:800 8px/1 Arial,sans-serif",
            "letter-spacing:.06em",
            "cursor:pointer",
            "white-space:nowrap",
            "user-select:none",
            "transition:background .2s ease,border-color .2s ease,transform .12s ease"
        ].join(";");

        button.addEventListener("mousedown", () => {
            button.style.transform = "scale(.97)";
        });
        button.addEventListener("mouseup", () => {
            button.style.transform = "scale(1)";
        });
        button.addEventListener("mouseleave", () => {
            button.style.transform = "scale(1)";
        });

        return button;
    };

    simulationFullscreenButton =
        makeActionButton("FULLSCREEN", "Open simulation fullscreen");
    simulationFullscreenButton.setAttribute("aria-pressed", "false");

    controls.appendChild(control);
    controls.appendChild(simulationFullscreenButton);

    /* All controls stay in the card header, outside the WebGL canvas. */
    header.appendChild(controls);
    simulationThemeButton = control;

    setupSimulationFullscreen(
        card,
        el("car3dViewport"),
        simulationFullscreenButton
    );

    const applyTheme = (themeName) => {
        const theme = SIMULATION_THEMES[themeName];
        if (!theme) return;

        simulationTheme = themeName;

        if (scene) {
            scene.background.setHex(theme.background);
        }

        if (worldMaterial) {
            worldMaterial.color.setHex(theme.floor);
        }

        const setGridColors = (grid, colorA, colorB) => {
            if (!grid?.material) return;

            const materials = Array.isArray(grid.material)
                ? grid.material
                : [grid.material];

            if (materials[0]?.color) {
                materials[0].color.setHex(colorA);
            }

            if (materials[1]?.color) {
                materials[1].color.setHex(colorB);
            }
        };

        setGridColors(worldGrid, theme.majorA, theme.majorB);
        setGridColors(worldPatternGrid, theme.fineA, theme.fineB);

        const contrast = themeName === "contrast";

        text.textContent = `SIM: ${theme.label}`;
        control.setAttribute("aria-pressed", contrast ? "true" : "false");
        control.style.background = contrast
            ? "rgba(215,224,232,.12)"
            : "rgba(255,255,255,.045)";
        control.style.borderColor = contrast
            ? "rgba(215,224,232,.34)"
            : "rgba(255,255,255,.14)";
        track.style.background = contrast
            ? "#d7e0e8"
            : "#26394f";
        knob.style.left = contrast ? "18px" : "2px";
    };

    /*
     * Use one real button click handler.
     * The previous label/input implementation could toggle twice because
     * the label's native activation and the custom click handler both ran.
     */
    control.addEventListener("click", () => {
        const nextTheme = simulationTheme === "night"
            ? "contrast"
            : "night";

        applyTheme(nextTheme);
    });

    control.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") {
            return;
        }

        event.preventDefault();
        control.click();
    });

    control.addEventListener("mousedown", () => {
        control.style.transform = "scale(.97)";
    });

    control.addEventListener("mouseup", () => {
        control.style.transform = "scale(1)";
    });

    control.addEventListener("mouseleave", () => {
        control.style.transform = "scale(1)";
    });

    applyTheme("night");
}

function createWorldChunk(chunkX, chunkZ) {
    const key = getChunkKey(chunkX, chunkZ);
    if (worldChunks.has(key)) return;

    const geometry = new THREE.PlaneGeometry(WORLD_CHUNK_SIZE, WORLD_CHUNK_SIZE);
    geometry.rotateX(-Math.PI / 2);

    const chunk = new THREE.Mesh(geometry, worldMaterial);
    chunk.position.set(
        chunkX * WORLD_CHUNK_SIZE + WORLD_CHUNK_SIZE / 2,
        0,
        chunkZ * WORLD_CHUNK_SIZE + WORLD_CHUNK_SIZE / 2
    );
    chunk.receiveShadow = true;
    scene.add(chunk);
    worldChunks.set(key, chunk);
}

function removeWorldChunk(chunkX, chunkZ) {
    const key = getChunkKey(chunkX, chunkZ);
    const chunk = worldChunks.get(key);
    if (!chunk) return;
    scene.remove(chunk);
    chunk.geometry.dispose();
    worldChunks.delete(key);
}

function updateWorldChunks(force = false) {
    if (!carRoot || !scene) return;

    const chunkX = getCurrentChunkCoordinate(carRoot.position.x);
    const chunkZ = getCurrentChunkCoordinate(carRoot.position.z);

    if (!force && chunkX === currentWorldChunkX && chunkZ === currentWorldChunkZ) return;

    currentWorldChunkX = chunkX;
    currentWorldChunkZ = chunkZ;

    const required = new Set();

    for (let x = chunkX - WORLD_RENDER_RADIUS; x <= chunkX + WORLD_RENDER_RADIUS; x++) {
        for (let z = chunkZ - WORLD_RENDER_RADIUS; z <= chunkZ + WORLD_RENDER_RADIUS; z++) {
            required.add(getChunkKey(x, z));
            createWorldChunk(x, z);
        }
    }

    for (const [key, chunk] of worldChunks) {
        if (required.has(key)) continue;
        scene.remove(chunk);
        chunk.geometry.dispose();
        worldChunks.delete(key);
    }

    const gridCenterX =
        chunkX * WORLD_CHUNK_SIZE + WORLD_CHUNK_SIZE / 2;
    const gridCenterZ =
        chunkZ * WORLD_CHUNK_SIZE + WORLD_CHUNK_SIZE / 2;

    if (worldGrid) {
        worldGrid.position.set(
            gridCenterX,
            0.012,
            gridCenterZ
        );
    }

    if (worldPatternGrid) {
        worldPatternGrid.position.set(
            gridCenterX,
            0.016,
            gridCenterZ
        );
    }
}


/* ==========================================================
   LOAD ROBOT GLB
   ========================================================== */

async function loadRobotModel() {

    const loader =
        new GLTFLoader();


    try {

        const modelPaths = [
            "/static/models/robot-car.glb",
            "/static/models/robot-car-detailed-babylon.glb"
        ];

        let gltf = null;
        let lastLoadError = null;

        for (const modelPath of modelPaths) {
            try {
                gltf = await loader.loadAsync(modelPath);
                console.log(`[3D] Robot GLB loaded from ${modelPath}`);
                break;
            } catch (error) {
                lastLoadError = error;
                console.warn(`[3D] Could not load ${modelPath}`, error);
            }
        }

        if (!gltf) {
            throw lastLoadError || new Error("No robot GLB could be loaded.");
        }


        /*
         * Keep carRoot as the vehicle controller.
         */

        const model =
            gltf.scene;


        /*
         * Your GLB's visual forward axis is
         * rotated into the controller's -Z axis.
         *
         * The model remains upright.
         */

        model.rotation.set(
            0,
            -Math.PI / 2,
            0
        );


        model.position.set(
            0,
            0,
            0
        );


        model.scale.set(
            1,
            1,
            1
        );


        /*
         * Enable shadows.
         */

        wheelObjects = [];

        model.traverse(
            (object) => {

                if (!object.isMesh) {
                    return;
                }

                /*
                 * Compute vertex normals if missing in GLB primitives.
                 * robot-car.glb primitives supply POSITION data without
                 * vertex NORMAL attributes. Computing vertex normals at
                 * runtime allows PBR shaders to compute accurate diffuse
                 * and metallic specular reflections.
                 */
                if (object.geometry) {
                    if (!object.geometry.attributes.normal) {
                        object.geometry.computeVertexNormals();
                    }
                }

                object.castShadow = true;
                object.receiveShadow = true;

                if (object.material) {
                    object.material.needsUpdate = true;
                    if ('envMapIntensity' in object.material) {
                        object.material.envMapIntensity = 1.25;
                    }
                }

                const name = String(object.name || "").toLowerCase();

                if (
                    name.includes("wheel") ||
                    name.includes("tire") ||
                    name.includes("tyre")
                ) {
                    prepareWheelForRolling(object);
                    wheelObjects.push(object);
                }
            }
        );

        console.log(`[3D] Wheel meshes detected: ${wheelObjects.length}`);


        /*
         * Put the visual model inside
         * the vehicle controller.
         */

        carRoot.add(model);


        state.modelLoaded = true;


        if (el("modelStatus")) {

            el("modelStatus").textContent =
                "3D READY";
        }


        console.log(
            "[3D] Robot GLB model loaded successfully."
        );


    } catch (error) {

        console.error(
            "[3D] Failed to load robot-car.glb:",
            error
        );


        /*
         * Keep a procedural fallback if the
         * GLB cannot be loaded.
         */

        createFallbackCar();


        if (el("modelStatus")) {

            el("modelStatus").textContent =
                "3D FALLBACK";
        }
    }
}


/* ==========================================================
   FALLBACK CAR
   ========================================================== */

function createFallbackCar() {

    if (!carRoot) return;


    const bodyMaterial =
        new THREE.MeshStandardMaterial({
            color: 0x2d3b50,
            roughness: 0.45,
            metalness: 0.55
        });


    const body =
        new THREE.Mesh(
            new THREE.BoxGeometry(
                2.6,
                0.55,
                1.55
            ),
            bodyMaterial
        );


    body.position.y = 0.62;
    body.castShadow = true;

    carRoot.add(body);


    const upper =
        new THREE.Mesh(
            new THREE.BoxGeometry(
                1.65,
                0.38,
                1.18
            ),

            new THREE.MeshStandardMaterial({
                color: 0x151e2d,
                roughness: 0.35,
                metalness: 0.65
            })
        );


    upper.position.y = 1.05;
    upper.castShadow = true;

    carRoot.add(upper);


    const wheelMaterial =
        new THREE.MeshStandardMaterial({
            color: 0x080a0e,
            roughness: 0.82,
            metalness: 0.15
        });


    const wheelPositions = [
        [-0.82, 0.43, 0.86],
        [0.82, 0.43, 0.86],
        [-0.82, 0.43, -0.86],
        [0.82, 0.43, -0.86]
    ];


    for (
        const [x, y, z]
        of wheelPositions
    ) {

        const wheel =
            new THREE.Mesh(
                new THREE.CylinderGeometry(
                    0.38,
                    0.38,
                    0.24,
                    24
                ),
                wheelMaterial
            );


        wheel.rotation.z =
            Math.PI / 2;


        wheel.position.set(
            x,
            y,
            z
        );


        wheel.castShadow = true;

        prepareWheelForRolling(wheel);

        wheelObjects.push(wheel);

        carRoot.add(wheel);
    }


    const frontLight =
        new THREE.Mesh(
            new THREE.BoxGeometry(
                0.42,
                0.12,
                0.08
            ),

            new THREE.MeshStandardMaterial({
                color: 0xbcefff,
                emissive: 0x55ccff,
                emissiveIntensity: 2.5
            })
        );


    frontLight.position.set(
        -1.31,
        0.72,
        0
    );


    carRoot.add(frontLight);


    state.modelLoaded = true;
}


/* ==========================================================
   WHEEL ROTATION
   ========================================================== */

/*
 * Prepare a wheel so its THREE.Object3D origin is at the actual
 * center of the tire.
 *
 * Why this is important:
 *
 * A GLB mesh can have its object origin somewhere other than the
 * physical center of the wheel. Rotating that mesh directly then
 * makes the tire orbit around the car instead of rolling in place.
 *
 * We solve that by:
 *
 *   1. Reading the wheel's geometry bounding box.
 *   2. Detecting the tire's axle from its thinnest dimension.
 *   3. Cloning the geometry so other wheels are not affected.
 *   4. Moving the geometry so its center is exactly at (0, 0, 0).
 *   5. Moving the wheel object by the same transformed offset.
 *   6. Rotating the wheel around the detected local axle.
 */
function prepareWheelForRolling(wheel) {
    if (!wheel || !wheel.geometry) {
        return;
    }

    if (wheel.userData.synaptiMeshWheelPrepared) {
        return;
    }

    const originalGeometry = wheel.geometry;

    if (!originalGeometry.boundingBox) {
        originalGeometry.computeBoundingBox();
    }

    const box = originalGeometry.boundingBox;

    if (!box) {
        return;
    }

    const size = new THREE.Vector3();
    const center = new THREE.Vector3();

    box.getSize(size);
    box.getCenter(center);

    /*
     * The smallest dimension is normally the tire thickness,
     * therefore it represents the wheel axle direction.
     */
    const dimensions = [
        {
            axis: new THREE.Vector3(1, 0, 0),
            size: size.x
        },
        {
            axis: new THREE.Vector3(0, 1, 0),
            size: size.y
        },
        {
            axis: new THREE.Vector3(0, 0, 1),
            size: size.z
        }
    ];

    dimensions.sort((a, b) => a.size - b.size);

    const axle =
        dimensions[0].axis.clone();

    /*
     * The remaining two dimensions approximate the wheel diameter.
     */
    const diameter =
        (dimensions[1].size + dimensions[2].size) / 2;

    const radius =
        Math.max(diameter / 2, 0.001);

    /*
     * Clone the geometry.
     *
     * A GLB can reuse one BufferGeometry for multiple wheel meshes.
     * Modifying the original geometry would therefore move all wheels
     * together. Every wheel gets its own geometry copy.
     */
    const centeredGeometry =
        originalGeometry.clone();

    /*
     * Move the vertices so the tire's geometric center becomes
     * the mesh origin.
     */
    centeredGeometry.translate(
        -center.x,
        -center.y,
        -center.z
    );

    wheel.geometry =
        centeredGeometry;

    /*
     * Moving the geometry by -center requires moving the object's
     * origin to the old geometric center to keep the wheel visually
     * in exactly the same place.
     *
     * The center is in wheel-local coordinates, so apply the wheel's
     * existing scale and rotation before adding it to position.
     */
    const originOffset =
        center.clone().applyEuler(wheel.rotation);

    originOffset.x *= wheel.scale.x;
    originOffset.y *= wheel.scale.y;
    originOffset.z *= wheel.scale.z;

    wheel.position.add(originOffset);

    wheel.userData.synaptiMeshWheelAxleAxis =
        axle;

    wheel.userData.synaptiMeshWheelRadius =
        radius;

    wheel.userData.synaptiMeshWheelPrepared =
        true;
}

/*
 * Roll all tires around their own physical axle.
 *
 * distance = speed * time
 * wheel angle = distance / radius
 *
 * We rotate the wheel itself now that its origin has been moved to
 * the actual tire center. No external pivot is required.
 */
function updateWheelRotation(delta) {
    if (!wheelObjects.length) {
        return;
    }

    if (Math.abs(currentSpeed) < 0.000001) {
        return;
    }

    const distance =
        currentSpeed * delta;

    for (const wheel of wheelObjects) {
        if (!wheel) {
            continue;
        }

        const axle =
            wheel.userData.synaptiMeshWheelAxleAxis;

        const radius =
            wheel.userData.synaptiMeshWheelRadius;

        if (!axle || !radius) {
            continue;
        }

        /*
         * The GLB wheel orientation is opposite to the simulator's
         * forward direction, so the negative sign makes W visually
         * roll forward and S visually roll backward.
         */
        const rollAmount =
            -(distance / radius);

        /*
         * rotateOnAxis() rotates around the wheel's LOCAL axle.
         */
        wheel.rotateOnAxis(
            axle,
            rollAmount
        );
    }
}

/* ==========================================================
   OBSTACLE VISUALIZATION
   ========================================================== */

function createObstacleMesh() {
    const mesh = new THREE.Mesh(
        new THREE.BoxGeometry(1.4, 1.0, 1.4),
        obstacleMaterial
    );
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    mesh.visible = false;
    scene.add(mesh);
    return mesh;
}

function showObstacle(direction) {
    if (!carRoot || !scene) return;
    const forward = new THREE.Vector3(0, 0, -1);
    forward.applyQuaternion(carRoot.quaternion);
    const position = carRoot.position.clone();
    const distance = 3.0;

    if (direction === "FRONT") {
        position.add(forward.multiplyScalar(distance));
        if (!frontObstacleMesh) frontObstacleMesh = createObstacleMesh();
        frontObstacleMesh.position.copy(position);
        frontObstacleMesh.visible = true;
    } else if (direction === "REAR") {
        position.add(forward.multiplyScalar(-distance));
        if (!rearObstacleMesh) rearObstacleMesh = createObstacleMesh();
        rearObstacleMesh.position.copy(position);
        rearObstacleMesh.visible = true;
    }
}

function clearObstacleVisualization() {
    if (frontObstacleMesh) frontObstacleMesh.visible = false;
    if (rearObstacleMesh) rearObstacleMesh.visible = false;
}


/* ==========================================================
   FULLSCREEN MOUSE LOOK
   ========================================================== */

function isSimulationFullscreen() {
    const card = document.querySelector(".car-view-card");
    return Boolean(card && document.fullscreenElement === card);
}

function lockSimulationMouse() {
    if (!isSimulationFullscreen()) return;

    const viewport = el("car3dViewport");
    if (!viewport || !viewport.requestPointerLock) {
        notify("Mouse look is not supported by this browser.");
        return;
    }

    viewport.requestPointerLock();
}

function unlockSimulationMouse() {
    if (document.pointerLockElement) {
        document.exitPointerLock?.();
    }
}

function setupFullscreenMouseLook() {
    const viewport = el("car3dViewport");
    if (!viewport) return;

    /* Middle mouse toggles mouse look, but ONLY in fullscreen. */
    viewport.addEventListener("mousedown", (event) => {
        if (event.button !== 1 || !isSimulationFullscreen()) return;

        event.preventDefault();

        if (document.pointerLockElement === viewport) {
            unlockSimulationMouse();
        } else {
            lockSimulationMouse();
        }
    });

    viewport.addEventListener("auxclick", (event) => {
        if (event.button === 1 && isSimulationFullscreen()) {
            event.preventDefault();
        }
    });

    viewport.addEventListener("contextmenu", (event) => {
        if (isSimulationFullscreen()) event.preventDefault();
    });

    document.addEventListener("pointerlockchange", () => {
        mousePointerLocked = document.pointerLockElement === viewport;
        viewport.classList.toggle("mouse-look-locked", mousePointerLocked);
    });

    document.addEventListener("pointerlockerror", () => {
        mousePointerLocked = false;
        viewport.classList.remove("mouse-look-locked");
        notify("Mouse look could not be locked.");
    });

    document.addEventListener("mousemove", (event) => {
        if (!mousePointerLocked || !isSimulationFullscreen()) return;

        mouseLookYaw -= event.movementX * MOUSE_LOOK_SENSITIVITY;
        /*
         * Inverted vertical mouse look:
         * moving the mouse up makes the camera look downward,
         * matching the user's familiar inverted Y-axis control.
         */
        mouseLookPitch += event.movementY * MOUSE_LOOK_SENSITIVITY;

        mouseLookPitch = THREE.MathUtils.clamp(
            mouseLookPitch,
            MOUSE_LOOK_MIN_PITCH,
            MOUSE_LOOK_MAX_PITCH
        );
    });

    document.addEventListener("fullscreenchange", () => {
        if (!isSimulationFullscreen()) {
            unlockSimulationMouse();
            mousePointerLocked = false;
            viewport.classList.remove("mouse-look-locked");
            mouseLookYaw = 0;
            mouseLookPitch = 0;
        }
    });
}


/* ==========================================================
   RESIZE
   ========================================================== */

function resize3D() {

    const viewport =
        el("car3dViewport");


    if (
        !renderer ||
        !camera ||
        !viewport
    ) {
        return;
    }


    const width =
        Math.max(
            viewport.clientWidth,
            1
        );


    const height =
        Math.max(
            viewport.clientHeight,
            1
        );


    camera.aspect =
        width / height;


    camera.updateProjectionMatrix();


    renderer.setSize(
        width,
        height
    );
}


/* ==========================================================
   TPP CAMERA
   ========================================================== */

function updateTPPCamera() {

    if (!camera || !carRoot) {
        return;
    }

    /*
     * Third-person perspective (TPP) camera with three-quarter angle.
     * Keeps all 9 components (chassis, upper deck, sensor module,
     * wheels, and sensor bars) clearly visible and properly framed.
     */
    const distance = 8.5;
    const baseHeight = 3.8;
    const horizontalDistance =
        Math.cos(mouseLookPitch) * distance;

    const localOffset =
        new THREE.Vector3(
            Math.sin(mouseLookYaw + 0.35) * horizontalDistance,
            baseHeight + Math.sin(mouseLookPitch) * distance,
            Math.cos(mouseLookYaw + 0.35) * horizontalDistance
        );

    localOffset.applyQuaternion(carRoot.quaternion);

    const desiredPosition =
        carRoot.position.clone().add(localOffset);

    camera.position.lerp(desiredPosition, 0.10);

    camera.lookAt(
        carRoot.position.x,
        carRoot.position.y + 0.65,
        carRoot.position.z
    );
}

/* ==========================================================
   SMOOTH VALUE HELPER
   ========================================================== */

function moveTowards(
    current,
    target,
    maxDelta
) {

    if (
        Math.abs(
            target - current
        ) <= maxDelta
    ) {
        return target;
    }


    return current +
        Math.sign(
            target - current
        ) * maxDelta;
}


/* ==========================================================
   VEHICLE UPDATE
   ========================================================== */

function updateVehicle(delta) {

    if (!carRoot) {
        return;
    }


    /* ------------------------------------------------------
       SMOOTH ACCELERATION
       ------------------------------------------------------ */

    const accelerationRate =
        Math.abs(targetSpeed) >
        Math.abs(currentSpeed)
            ? ACCELERATION
            : DECELERATION;


    currentSpeed =
        moveTowards(
            currentSpeed,
            targetSpeed,
            accelerationRate * delta
        );


    /* ------------------------------------------------------
       SMOOTH TURNING
       ------------------------------------------------------ */

    const turnRate =
        Math.abs(targetTurnSpeed) >
        Math.abs(currentTurnSpeed)
            ? TURN_ACCELERATION
            : TURN_DECELERATION;


    currentTurnSpeed =
        moveTowards(
            currentTurnSpeed,
            targetTurnSpeed,
            turnRate * delta
        );


    /* ------------------------------------------------------
       ROTATE VEHICLE
       ------------------------------------------------------ */

    if (
        Math.abs(currentTurnSpeed) >
        0.0001
    ) {

        carHeading +=
            currentTurnSpeed * delta;


        carRoot.rotation.y =
            carHeading;
    }


    /* ------------------------------------------------------
       MOVE VEHICLE
       ------------------------------------------------------ */

    if (
        Math.abs(currentSpeed) >
        0.0001
    ) {

        /*
         * Controller forward = -Z.
         *
         * Convert local forward into
         * world-space direction.
         */

        const forward =
            new THREE.Vector3(
                0,
                0,
                -1
            );


        forward.applyQuaternion(
            carRoot.quaternion
        );


        carRoot.position.x +=
            forward.x *
            currentSpeed *
            delta;


        carRoot.position.z +=
            forward.z *
            currentSpeed *
            delta;
    }


    /* ------------------------------------------------------
       360° SPIN
       ------------------------------------------------------ */

    if (
        Math.abs(spinRemaining) >
        0.0001
    ) {

        const amount =
            Math.min(
                Math.abs(spinRemaining),
                SPIN_SPEED * delta
            );


        const direction =
            Math.sign(
                spinRemaining
            );


        carHeading +=
            direction * amount;


        carRoot.rotation.y =
            carHeading;


        spinRemaining -=
            direction * amount;

        if (Math.abs(spinRemaining) <= 0.0001) {
            spinRemaining = 0;
            state.currentCommand = "LIFTCARSTOP";
            updateVisualState("STOP");
        }
    }


    /*
     * Determine whether the robot is currently moving.
     */

    state.moving =
        Math.abs(currentSpeed) > 0.01 ||
        Math.abs(currentTurnSpeed) > 0.01 ||
        Math.abs(spinRemaining) > 0.01;
}


/* ==========================================================
   ANIMATION LOOP
   ========================================================== */

function animate(timestamp) {

    requestAnimationFrame(
        animate
    );


    if (
        !renderer ||
        !scene ||
        !camera
    ) {
        return;
    }


    /*
     * Timer must be updated once per simulation frame before
     * reading getDelta(). Passing requestAnimationFrame's
     * timestamp also keeps timing stable when the tab is hidden.
     */
    if (timer) {
        timer.update(timestamp);
    }

    const delta =
        timer
            ? Math.min(
                timer.getDelta(),
                0.05
            )
            : 0.016;


    /*
     * A 3D simulation is only allowed to run while a target
     * device is selected. This is the master safety gate for
     * the visual simulation.
     */

    if (!state.selectedDevice) {

        heldMovementKeys.clear();

        targetSpeed = 0;
        targetTurnSpeed = 0;
        spinRemaining = 0;

        state.currentCommand =
            "LIFTCARSTOP";

        updateVisualState("STOP");

    } else if (Math.abs(spinRemaining) <= 0.0001) {

        /*
         * Evaluate the physical keyboard state every frame.
         * A precise 90°/360° turn owns the vehicle until its
         * rotation completes, so keyboard state does not cancel it.
         */

        applyKeyboardDriveState();

    } else {

        updateVisualState(
            spinRemaining > 0
                ? "LEFT TURN"
                : "RIGHT TURN"
        );
    }


    /*
     * Update smooth vehicle movement.
     */

    updateVehicle(delta);

    updateWorldChunks();
    updateWheelRotation(delta);


    /*
     * Follow vehicle with TPP camera.
     */

    updateTPPCamera();


    /*
     * Render.
     */

    renderer.render(
        scene,
        camera
    );


    /* ------------------------------------------------------
       FPS
       ------------------------------------------------------ */

    frameCount++;


    const current =
        performance.now();


    if (
        current - lastFrameTime >=
        1000
    ) {

        fps = frameCount;

        frameCount = 0;

        lastFrameTime =
            current;


        const fpsElement =
            el("fpsStatus");


        if (fpsElement) {

            fpsElement.textContent =
                `FPS: ${fps}`;
        }
    }
}


/* ==========================================================
   MOVEMENT SAFETY
   ========================================================== */

function isMovementBlocked(command) {

    const normalized =
        String(command || "")
            .trim()
            .toUpperCase();


    if (
        normalized === "LIFTCARFORWARD" &&
        obstacleState.front
    ) {
        return true;
    }


    if (
        normalized === "LIFTCARBACKWARD" &&
        obstacleState.rear
    ) {
        return true;
    }


    return false;
}


function enforceObstacleSafety() {

    if (!carRoot) {
        return;
    }


    const forwardBlocked =
        obstacleState.front &&
        (
            targetSpeed > 0 ||
            state.currentCommand ===
                "LIFTCARFORWARD" ||
            state.currentCommand.includes(
                "LIFTCARFORWARD +"
            )
        );


    const reverseBlocked =
        obstacleState.rear &&
        (
            targetSpeed < 0 ||
            state.currentCommand ===
                "LIFTCARBACKWARD" ||
            state.currentCommand.includes(
                "LIFTCARBACKWARD +"
            )
        );


    if (forwardBlocked || reverseBlocked) {
        targetSpeed = 0;
    }
}


/* ==========================================================
   VISUAL COMMAND
   ========================================================== */

function applyVisualCommand(command) {

    command =
        String(command || "")
            .toUpperCase();


    state.currentCommand =
        command;


    const visual =
        el("visualState");


    if (visual) {

        visual.textContent =
            command
                .replace(
                    "LIFTCAR",
                    ""
                )
                .replace(
                    "360",
                    " 360°"
                );
    }


    if (!carRoot) {
        return;
    }


    switch (command) {


        /* --------------------------------------------------
           FORWARD
           -------------------------------------------------- */

        case "LIFTCARFORWARD":

            targetSpeed =
                obstacleState.front
                    ? 0
                    : MAX_FORWARD_SPEED;

            targetTurnSpeed = 0;

            break;


        /* --------------------------------------------------
           BACKWARD
           -------------------------------------------------- */

        case "LIFTCARBACKWARD":

            targetSpeed =
                obstacleState.rear
                    ? 0
                    : -MAX_REVERSE_SPEED;

            targetTurnSpeed = 0;

            break;


        /* --------------------------------------------------
           LEFT
           -------------------------------------------------- */

        case "LIFTCARLEFT":

            /* One-shot 90° turn. The slave stops after the turn. */
            targetSpeed = 0;
            targetTurnSpeed = 0;
            spinRemaining = Math.PI / 2;

            break;


        /* --------------------------------------------------
           RIGHT
           -------------------------------------------------- */

        case "LIFTCARRIGHT":

            /* One-shot 90° turn. The slave stops after the turn. */
            targetSpeed = 0;
            targetTurnSpeed = 0;
            spinRemaining = -Math.PI / 2;

            break;


        /* --------------------------------------------------
           LEFT 360
           -------------------------------------------------- */

        case "LIFTCARLEFT360":

            targetSpeed = 0;

            targetTurnSpeed = 0;

            spinRemaining =
                Math.PI * 2;

            break;


        /* --------------------------------------------------
           RIGHT 360
           -------------------------------------------------- */

        case "LIFTCARRIGHT360":

            targetSpeed = 0;

            targetTurnSpeed = 0;

            spinRemaining =
                -Math.PI * 2;

            break;


        /* --------------------------------------------------
           STOP
           -------------------------------------------------- */

        case "LIFTCARSTOP":

        default:

            targetSpeed = 0;

            targetTurnSpeed = 0;

            break;
    }
}


/* ==========================================================
   COMMAND TRANSMISSION
   ========================================================== */

async function sendCommand(command, updateVisual = true) {

    command =
        String(command || "")
            .trim()
            .toUpperCase();


    if (!command) {
        return false;
    }


    /*
     * Global device safety gate. The visual simulation must not
     * react to movement commands when there is no selected target.
     */
    if (!state.selectedDevice) {
        targetSpeed = 0;
        targetTurnSpeed = 0;
        spinRemaining = 0;
        state.currentCommand = "LIFTCARSTOP";
        updateVisualState("STOP");
        notify("Select a device first before driving.");
        return false;
    }


    /*
     * Keep all command transmission in the global command manager.
     * car_control.js remains responsible for the 3D vehicle and
     * visual simulation only.
     */
    if (updateVisual) {
        applyVisualCommand(command);
    }


    if (window.SynaptiMeshCommand &&
        typeof window.SynaptiMeshCommand.send === "function") {

        return window.SynaptiMeshCommand.send(command);
    }


    notify("Command system is not ready. Please refresh the page.");
    console.warn(`[COMMAND BLOCKED] Global command manager unavailable: ${command}`);
    return false;
}


/* ==========================================================
   BUTTON CONTROLS
   ========================================================== */

const movementCommands = new Set([
    "LIFTCARFORWARD",
    "LIFTCARBACKWARD"
]);


/*
 * Fullscreen touch controls deliberately use the same global command
 * manager as every other Car Control command.  They do not depend on
 * the visual state object for transmission.
 */
function sendTouchHardwareCommand(command) {
    const normalized = String(command || "").trim().toUpperCase();

    if (!normalized) {
        return false;
    }

    const managerDevice =
        window.SynaptiMeshCommand?.getSelectedDevice?.() || "";

    const selectorDevice =
        String(el("deviceSelector")?.value || "").trim();

    const fullscreenDevice =
        String(el("fullscreenDeviceSelector")?.value || "").trim();

    const device =
        managerDevice ||
        selectorDevice ||
        fullscreenDevice ||
        state.selectedDevice ||
        "";

    if (!device) {
        notify("Select a robot car before driving.");
        return false;
    }

    /* Keep the local simulation and the global manager synchronized. */
    state.selectedDevice = device;

    if (window.SynaptiMeshCommand?.setSelectedDevice) {
        window.SynaptiMeshCommand.setSelectedDevice(device);
    }

    /* Preferred path: the single global command manager. */
    if (typeof window.SynaptiMeshCommand?.send === "function") {
        return window.SynaptiMeshCommand.send(normalized);
    }

    /* Safety fallback for a transient command-manager initialization race. */
    const ws = window.SynaptiMeshWebSocket;

    if (ws?.isConnected?.() && typeof ws.send === "function") {
        console.log(`[Touch Command] Device: ${device} | Command: ${normalized}`);
        return ws.send("command", {
            device,
            command: normalized
        });
    }

    notify("Master Hub WebSocket is not connected.");
    return false;
}


/* ----------------------------------------------------------
   NORMAL PAGE BUTTONS
   ---------------------------------------------------------- */

document
    .querySelectorAll("[data-command]:not(.fullscreen-drive-button)")
    .forEach((button) => {
        const command = String(button.dataset.command || "")
            .toUpperCase();

        if (
            command === "LIFTCARLEFT" ||
            command === "LIFTCARRIGHT"
        ) {
            button.addEventListener("click", () => {
                sendCommand(command);
            });
            return;
        }

        if (movementCommands.has(command)) {
            let pressed = false;

            button.addEventListener("pointerdown", (event) => {
                event.preventDefault();
                if (pressed) return;

                pressed = true;
                button.classList.add("is-pressed");
                button.setPointerCapture?.(event.pointerId);
                sendCommand(command);
            });

            const release = (event) => {
                if (!pressed) return;

                pressed = false;
                button.classList.remove("is-pressed");

                try {
                    button.releasePointerCapture?.(event.pointerId);
                } catch (_) {}

                sendCommand("LIFTCARSTOP");
            };

            button.addEventListener("pointerup", release);
            button.addEventListener("pointercancel", release);
            button.addEventListener("lostpointercapture", () => {
                if (!pressed) return;

                pressed = false;
                button.classList.remove("is-pressed");
                sendCommand("LIFTCARSTOP");
            });
            return;
        }

        button.addEventListener("click", () => {
            sendCommand(command);
        });
    });


/* ----------------------------------------------------------
   FULLSCREEN TOUCH BUTTONS
   ---------------------------------------------------------- */

document
    .querySelectorAll(".fullscreen-drive-button")
    .forEach((button) => {
        const command = String(button.dataset.command || "")
            .trim()
            .toUpperCase();

        button.style.touchAction = "none";

        if (
            command === "LIFTCARFORWARD" ||
            command === "LIFTCARBACKWARD"
        ) {
            let pressed = false;

            const stop = () => {
                if (!pressed) return;

                pressed = false;
                button.classList.remove("is-pressed");
                sendTouchHardwareCommand("LIFTCARSTOP");
            };

            button.addEventListener("pointerdown", (event) => {
                event.preventDefault();
                event.stopPropagation();

                if (pressed) return;

                pressed = true;
                button.classList.add("is-pressed");

                try {
                    button.setPointerCapture(event.pointerId);
                } catch (_) {}

                sendTouchHardwareCommand(command);
            }, { passive: false });

            button.addEventListener("pointerup", (event) => {
                event.preventDefault();
                event.stopPropagation();
                stop();
            }, { passive: false });

            button.addEventListener("pointercancel", (event) => {
                event.preventDefault();
                event.stopPropagation();
                stop();
            }, { passive: false });

            button.addEventListener("lostpointercapture", stop);
            button.addEventListener("click", (event) => {
                /* Prevent the browser's synthetic touch click. */
                event.preventDefault();
                event.stopPropagation();
            });

            return;
        }

        /* LEFT / RIGHT are one-shot 90° hardware commands. */
        button.addEventListener("pointerup", (event) => {
            event.preventDefault();
            event.stopPropagation();
            sendTouchHardwareCommand(command);
        }, { passive: false });

        button.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
        });
    });


/* ==========================================================
   KEYBOARD CONTROL
   ========================================================== */

const keyboardToggle =
    el("keyboardToggle");

const desktopMediaQuery =
    window.matchMedia("(min-width: 1101px)");


function updateKeyboardUI() {
    const text =
        el("keyboardStatusText");

    if (keyboardToggle) {
        keyboardToggle.checked =
            state.keyboardEnabled;
    }


    if (text) {

        text.textContent =
            state.keyboardEnabled
                ? "Keyboard control enabled"
                : "Keyboard control disabled";
    }
}


if (keyboardToggle) {
    keyboardToggle.checked = desktopMediaQuery.matches && state.keyboardEnabled;
    updateKeyboardUI();

    keyboardToggle.addEventListener(
        "change",
        () => {

            state.keyboardEnabled =
                keyboardToggle.checked;


            /*
             * If keyboard control gets disabled,
             * immediately stop the visual vehicle.
             */

            if (!state.keyboardEnabled) {

                heldMovementKeys.clear();

                lastKeyboardHardwareCommand =
                    "LIFTCARSTOP";

                sendCommand(
                    "LIFTCARSTOP"
                );
            }


            updateKeyboardUI();


            if (state.keyboardEnabled) {

                notify(
                    "Keyboard control enabled."
                );
            }
        }
    );
}


/* ----------------------------------------------------------
   DESKTOP / MOBILE MODE SWITCH
   ---------------------------------------------------------- */

const handleControlViewportChange = (event) => {
    const isDesktop = event.matches;

    if (isDesktop) {
        state.keyboardEnabled = Boolean(keyboardToggle?.checked ?? true);
    } else {
        /* Touch devices never use the desktop keyboard controller. */
        if (state.keyboardEnabled && heldMovementKeys.size) {
            heldMovementKeys.clear();
            lastKeyboardHardwareCommand = "LIFTCARSTOP";
            sendCommand("LIFTCARSTOP");
        }
        state.keyboardEnabled = false;
    }

    updateKeyboardUI();
};

if (typeof desktopMediaQuery.addEventListener === "function") {
    desktopMediaQuery.addEventListener("change", handleControlViewportChange);
} else {
    desktopMediaQuery.addListener(handleControlViewportChange);
}



/* ----------------------------------------------------------
   KEY MAP
   ---------------------------------------------------------- */

/* ----------------------------------------------------------
   KEYBOARD DRIVE STATE
   ---------------------------------------------------------- */

const keyboardCommands = {

    w:
        "LIFTCARFORWARD",

    arrowup:
        "LIFTCARFORWARD",

    s:
        "LIFTCARBACKWARD",

    arrowdown:
        "LIFTCARBACKWARD",

    /* A / D are handled as precise 90° turns in KEYDOWN. */
};


/*
 * Keep the physical keyboard state continuously.
 *
 * W/S remain state-driven so throttle continues while held.
 * A/D are discrete 90° simulation turns and are handled on KEYDOWN.
 */
const heldMovementKeys = new Set();


/*
 * Prevent duplicate MQTT/HTTP transmissions while the same
 * effective hardware command remains active.
 */
let lastKeyboardHardwareCommand =
    "LIFTCARSTOP";


function applyKeyboardDriveState() {

    if (!state.keyboardEnabled) {
        return;
    }


    const forwardPressed =
        heldMovementKeys.has("w") ||
        heldMovementKeys.has("arrowup");


    const reversePressed =
        heldMovementKeys.has("s") ||
        heldMovementKeys.has("arrowdown");


    const leftPressed = false;
    const rightPressed = false;


    /* ------------------------------------------------------
       THROTTLE
       ------------------------------------------------------ */

    let keyboardSpeed = 0;


    if (forwardPressed && !reversePressed) {

        /* Front ultrasonic obstacle blocks forward travel. */
        if (!obstacleState.front) {
            keyboardSpeed =
                MAX_FORWARD_SPEED;
        }

    } else if (
        reversePressed &&
        !forwardPressed
    ) {

        /* Rear ultrasonic obstacle blocks reverse travel. */
        if (!obstacleState.rear) {
            keyboardSpeed =
                -MAX_REVERSE_SPEED;
        }
    }


    /* ------------------------------------------------------
       STEERING
       ------------------------------------------------------ */

    let keyboardTurn = 0;


    if (leftPressed && !rightPressed) {
        keyboardTurn =
            MAX_TURN_SPEED;

    } else if (
        rightPressed &&
        !leftPressed
    ) {
        keyboardTurn =
            -MAX_TURN_SPEED;
    }


    /*
     * These values are consumed by updateVehicle() every frame.
     * Therefore W+A means the car continues moving while turning.
     */
    targetSpeed =
        keyboardSpeed;

    targetTurnSpeed =
        keyboardTurn;


    /* ------------------------------------------------------
       VISUAL STATE
       ------------------------------------------------------ */

    if (keyboardSpeed > 0) {

        state.currentCommand =
            keyboardTurn > 0
                ? "LIFTCARFORWARD + LEFT"
                : keyboardTurn < 0
                    ? "LIFTCARFORWARD + RIGHT"
                    : "LIFTCARFORWARD";

    } else if (keyboardSpeed < 0) {

        state.currentCommand =
            keyboardTurn > 0
                ? "LIFTCARBACKWARD + LEFT"
                : keyboardTurn < 0
                    ? "LIFTCARBACKWARD + RIGHT"
                    : "LIFTCARBACKWARD";

    } else if (keyboardTurn > 0) {

        state.currentCommand =
            "LIFTCARLEFT";

    } else if (keyboardTurn < 0) {

        state.currentCommand =
            "LIFTCARRIGHT";

    } else {

        state.currentCommand =
            "LIFTCARSTOP";
    }


    const visual =
        el("visualState");


    if (visual) {

        visual.textContent =
            state.currentCommand
                .replaceAll(
                    "LIFTCAR",
                    ""
                )
                .replaceAll(
                    "360",
                    " 360°"
                );
    }


    enforceObstacleSafety();


    /* ------------------------------------------------------
       HARDWARE COMMAND
       ------------------------------------------------------ */

    /*
     * The current ESP32/MQTT command format carries one movement
     * command at a time. For that reason the hardware receives the
     * throttle command when W/S is held, while the 3D simulation
     * simultaneously applies A/D steering.
     *
     * Crucially, releasing A or D does NOT send STOP while W/S
     * remains held. The next frame simply keeps the throttle active.
     */

    let hardwareCommand =
        "LIFTCARSTOP";


    if (
        forwardPressed &&
        !reversePressed
    ) {

        /* Never transmit FORWARD while the front is blocked. */
        if (!obstacleState.front) {
            hardwareCommand =
                "LIFTCARFORWARD";
        }

    } else if (
        reversePressed &&
        !forwardPressed
    ) {

        /* Never transmit BACKWARD while the rear is blocked. */
        if (!obstacleState.rear) {
            hardwareCommand =
                "LIFTCARBACKWARD";
        }

    } else if (
        leftPressed &&
        !rightPressed
    ) {

        hardwareCommand =
            "LIFTCARLEFT";

    } else if (
        rightPressed &&
        !leftPressed
    ) {

        hardwareCommand =
            "LIFTCARRIGHT";
    }


    if (
        hardwareCommand !==
        lastKeyboardHardwareCommand
    ) {

        lastKeyboardHardwareCommand =
            hardwareCommand;

        sendCommand(
            hardwareCommand,
            false
        );
    }
}


/* ----------------------------------------------------------
   KEYDOWN
   ---------------------------------------------------------- */

document.addEventListener(
    "keydown",
    (event) => {

        if (!state.keyboardEnabled) {
            return;
        }


        const target =
            event.target;


        if (
            target &&
            (
                target.tagName === "INPUT" ||
                target.tagName === "TEXTAREA" ||
                target.tagName === "SELECT" ||
                target.isContentEditable
            )
        ) {
            return;
        }


        const key =
            event.key.toLowerCase();


        /* A / D (and arrow left/right) are precise 90° turns. */
        if (key === "a" || key === "arrowleft") {
            event.preventDefault();
            if (!event.repeat) {
                performQuarterTurn("left");
            }
            return;
        }

        if (key === "d" || key === "arrowright") {
            event.preventDefault();
            if (!event.repeat) {
                performQuarterTurn("right");
            }
            return;
        }


        if (keyboardCommands[key]) {

            event.preventDefault();

            heldMovementKeys.add(key);

            applyKeyboardDriveState();

            return;
        }


        /* Q = 360° left. */
        if (key === "q") {

            event.preventDefault();

            if (!event.repeat) {

                heldMovementKeys.clear();

                lastKeyboardHardwareCommand =
                    "LIFTCARSTOP";

                sendCommand(
                    "LIFTCARLEFT360"
                );
            }

            return;
        }


        /* E = 360° right. */
        if (key === "e") {

            event.preventDefault();

            if (!event.repeat) {

                heldMovementKeys.clear();

                lastKeyboardHardwareCommand =
                    "LIFTCARSTOP";

                sendCommand(
                    "LIFTCARRIGHT360"
                );
            }

            return;
        }


        /* Space = stop. */
        if (key === " ") {

            event.preventDefault();

            if (!event.repeat) {

                heldMovementKeys.clear();

                lastKeyboardHardwareCommand =
                    "LIFTCARSTOP";

                sendCommand(
                    "LIFTCARSTOP"
                );
            }
        }
    }
);


/* ----------------------------------------------------------
   KEYUP
   ---------------------------------------------------------- */

document.addEventListener(
    "keyup",
    (event) => {

        if (!state.keyboardEnabled) {
            return;
        }


        const target =
            event.target;


        if (
            target &&
            (
                target.tagName === "INPUT" ||
                target.tagName === "TEXTAREA" ||
                target.tagName === "SELECT" ||
                target.isContentEditable
            )
        ) {
            return;
        }


        const key =
            event.key.toLowerCase();


        if (keyboardCommands[key]) {

            event.preventDefault();

            heldMovementKeys.delete(key);

            /*
             * Recalculate from every key still held.
             *
             * W + A -> release A -> W remains held -> FORWARD.
             * W + D -> release D -> W remains held -> FORWARD.
             * W      -> release W -> no throttle -> STOP.
             */
            applyKeyboardDriveState();
        }
    }
);


/* ----------------------------------------------------------
   WINDOW BLUR SAFETY
   ---------------------------------------------------------- */

window.addEventListener(
    "blur",
    () => {

        if (!state.keyboardEnabled) {
            return;
        }


        if (!heldMovementKeys.size) {
            return;
        }


        heldMovementKeys.clear();

        lastKeyboardHardwareCommand =
            "LIFTCARSTOP";

        sendCommand(
            "LIFTCARSTOP"
        );
    }
);


/* ==========================================================
   GLOBAL DEVICE SELECTION
   ========================================================== */

window.addEventListener(
    "synaptimesh:device-changed",
    (event) => {
        state.selectedDevice =
            event.detail?.device ||
            "";

        /* Clear held keys when changing or clearing the target. */
        heldMovementKeys.clear();
        lastKeyboardHardwareCommand =
            "LIFTCARSTOP";

        /*
         * Clearing the target must immediately stop the 3D
         * simulation as well as command transmission.
         */
        targetSpeed = 0;
        targetTurnSpeed = 0;
        spinRemaining = 0;
        state.currentCommand = "LIFTCARSTOP";
        updateVisualState("STOP");
        updateMQTTConnectionUI();
    }
);


/* ==========================================================
   NATIVE WEBSOCKET
   ========================================================== */

if (websocket) {

    websocket.on(
        "open",
        () => {
            const status =
                el("connectionStatus");

            if (status) {
                status.textContent = "CONNECTED";
            }
        }
    );

    websocket.on(
        "close",
        () => {
            const status =
                el("connectionStatus");

            if (status) {
                status.textContent = "DISCONNECTED";
            }
        }
    );

    websocket.on(
        "device_status_snapshot",
        (data) => {
            const snapshot =
                data && data.devices
                    ? data.devices
                    : data;

            if (
                !snapshot ||
                typeof snapshot !== "object"
            ) {
                return;
            }

            if (
                state.selectedDevice &&
                snapshot[state.selectedDevice]
            ) {
                updateRobotStatus(
                    snapshot[state.selectedDevice]
                );
            }
        }
    );

    websocket.on(
        "device_status",
        (data) => {
            if (
                !data ||
                !data.device
            ) {
                return;
            }

            if (
                state.selectedDevice &&
                data.device !== state.selectedDevice
            ) {
                return;
            }

            updateRobotStatus(data.status);
        }
    );

    websocket.on(
        "mqtt_status",
        (data) => {
            if (!data) {
                return;
            }

            const connected = Boolean(data.connected);

            if (connected) {
                mqttConnection.broker.state = "CONNECTED";
                mqttConnection.broker.everConnected = true;
            } else {
                mqttConnection.broker.state =
                    data.ever_connected || mqttConnection.broker.everConnected
                        ? "DISCONNECTED"
                        : "OFFLINE";
            }

            updateMQTTConnectionUI();
        }
    );

    websocket.on(
        "mqtt_device_snapshot",
        (data) => {
            const snapshot =
                data && data.devices
                    ? data.devices
                    : data;

            if (!snapshot || typeof snapshot !== "object") {
                return;
            }

            for (const [device, status] of Object.entries(snapshot)) {
                const entry = getDeviceMqttState(device);
                entry.state = String(status || "OFFLINE").toUpperCase();
                entry.everConnected =
                    entry.everConnected ||
                    entry.state === "ONLINE";
            }

            updateMQTTConnectionUI();
        }
    );

    websocket.on(
        "mqtt_device_status",
        (data) => {
            if (!data || !data.device) {
                return;
            }

            const entry = getDeviceMqttState(data.device);
            entry.state = String(data.status || "OFFLINE").toUpperCase();

            if (entry.state === "ONLINE") {
                entry.everConnected = true;
            }

            updateMQTTConnectionUI();
        }
    );

    websocket.on(
        "ack",
        (data) => {
            if (!data) {
                return;
            }

            if (
                state.selectedDevice &&
                data.device &&
                data.device !== state.selectedDevice
            ) {
                return;
            }

            const message =
                data.ack ||
                data.message ||
                data.status ||
                "UNKNOWN";

            const ackMessage = el("ackMessage");
            const ackTime = el("ackTime");
            const ackType = el("ackType");
            const responseIndicator =
                el("responseIndicator");

            if (ackMessage) {
                ackMessage.textContent = message;
            }

            if (ackTime) {
                ackTime.textContent = now();
            }

            if (ackType) {
                ackType.textContent = "ACK";
            }

            if (responseIndicator) {
                responseIndicator.textContent = "RECEIVED";
            }

            handleSensorStatus(message);
        }
    );
}


/* ==========================================================
   ROBOT STATUS
   ========================================================== */

function updateRobotStatus(status) {

    const text =
        String(
            status || "UNKNOWN"
        ).toUpperCase();


    const robotStatus =
        el("robotStatus");


    if (robotStatus) {

        robotStatus.textContent =
            text;
    }

    window.dispatchEvent(
        new CustomEvent("synaptimesh:robot-status-updated")
    );
}


/* ==========================================================
   SENSOR STATUS
   ========================================================== */

function setObstacleDirection(direction, blocked) {

    const normalized =
        String(direction || "")
            .toLowerCase();


    const isFront =
        normalized === "front";

    const item =
        el(isFront
            ? "frontSafetyItem"
            : "rearSafetyItem");

    const text =
        el(isFront
            ? "frontSafety"
            : "rearSafety");

    const warning =
        el(isFront
            ? "frontWarning"
            : "rearWarning");


    if (isFront) {
        obstacleState.front = blocked;
    } else {
        obstacleState.rear = blocked;
    }


    if (item) {
        item.classList.toggle(
            "obstacle",
            blocked
        );
    }


    if (text) {
        text.textContent =
            blocked
                ? "OBSTACLE"
                : "CLEAR";
    }


    if (warning) {
        warning.classList.toggle(
            "active",
            blocked
        );
    }


    /*
     * If the physical robot was already travelling into the blocked
     * direction, issue one STOP immediately. The keyboard state is
     * then marked as stopped so it does not transmit a duplicate STOP.
     */
    const movementWasBlocked =
        (
            isFront &&
            (
                targetSpeed > 0 ||
                state.currentCommand.includes(
                    "LIFTCARFORWARD"
                )
            )
        ) ||
        (
            !isFront &&
            (
                targetSpeed < 0 ||
                state.currentCommand.includes(
                    "LIFTCARBACKWARD"
                )
            )
        );


    enforceObstacleSafety();


    if (blocked && movementWasBlocked) {
        lastKeyboardHardwareCommand =
            "LIFTCARSTOP";

        sendCommand(
            "LIFTCARSTOP",
            true
        );
    }


    if (blocked) {
        showObstacle(
            isFront
                ? "FRONT"
                : "REAR"
        );
    } else {
        updateObstacleVisualization();
    }


    /*
     * Re-evaluate movement immediately.
     * If W/S is still held, the newly-clear direction can resume;
     * if an obstacle appeared, the blocked direction is stopped.
     */
    if (state.keyboardEnabled) {
        applyKeyboardDriveState();
    }
}


function scheduleObstacleClear(direction) {

    const normalized =
        String(direction || "")
            .toLowerCase();


    const timerKey =
        normalized === "front"
            ? "frontTimer"
            : "rearTimer";


    if (obstacleState[timerKey]) {
        clearTimeout(
            obstacleState[timerKey]
        );
    }


    obstacleState[timerKey] =
        setTimeout(
            () => {
                obstacleState[timerKey] = null;
                setObstacleDirection(
                    normalized,
                    false
                );
            },
            OBSTACLE_DISPLAY_TIMEOUT
        );
}


function updateObstacleVisualization() {

    if (frontObstacleMesh) {
        frontObstacleMesh.visible =
            obstacleState.front;
    }

    if (rearObstacleMesh) {
        rearObstacleMesh.visible =
            obstacleState.rear;
    }
}


function clearObstacleState(direction = null) {

    const normalized =
        String(direction || "")
            .toLowerCase();


    if (!direction || normalized === "front") {
        if (obstacleState.frontTimer) {
            clearTimeout(
                obstacleState.frontTimer
            );
            obstacleState.frontTimer = null;
        }

        setObstacleDirection(
            "front",
            false
        );
    }


    if (!direction || normalized === "rear") {
        if (obstacleState.rearTimer) {
            clearTimeout(
                obstacleState.rearTimer
            );
            obstacleState.rearTimer = null;
        }

        setObstacleDirection(
            "rear",
            false
        );
    }
}


function handleSensorStatus(message) {

    const text =
        String(message || "")
            .toUpperCase();


    /* ------------------------------------------------------
       FRONT OBSTACLE
       ------------------------------------------------------ */

    if (
        text.includes("FRONT OBSTACLE")
    ) {
        setObstacleDirection(
            "front",
            true
        );

        scheduleObstacleClear(
            "front"
        );
    }


    /* ------------------------------------------------------
       REAR OBSTACLE
       ------------------------------------------------------ */

    if (
        text.includes("REAR OBSTACLE")
    ) {
        setObstacleDirection(
            "rear",
            true
        );

        scheduleObstacleClear(
            "rear"
        );
    }


    /* ------------------------------------------------------
       EXPLICIT CLEAR MESSAGES
       ------------------------------------------------------ */

    if (
        text.includes("FRONT CLEAR")
    ) {
        clearObstacleState("front");
    }


    if (
        text.includes("REAR CLEAR")
    ) {
        clearObstacleState("rear");
    }


    /*
     * A generic CLEAR from the ultrasonic system means the whole
     * safety state is clear. This also fixes the old behaviour where
     * the UI could remain stuck on OBSTACLE.
     */
    if (
        text === "CLEAR" ||
        text.includes("ALL CLEAR")
    ) {
        clearObstacleState();
    }
}



window.addEventListener(
    "synaptimesh:command-manager-ready",
    () => {
        if (window.SynaptiMeshCommand) {
            state.selectedDevice =
                window.SynaptiMeshCommand.getSelectedDevice();
        }
    }
);

if (window.SynaptiMeshCommand) {
    state.selectedDevice =
        window.SynaptiMeshCommand.getSelectedDevice();
}


/* ==========================================================
   START
   ========================================================== */

init3D();

updateKeyboardUI();

clearObstacleState();
updateObstacleVisualization();
