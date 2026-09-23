/* ==========================================================
   SYNAPTIMESH GLOBAL COMMAND MANAGER
   Central device selection + command transmission layer
   ========================================================== */

(() => {
    "use strict";

    const state = {
        selectedDevice: "",
        busy: false
    };

    const el = (id) =>
        document.getElementById(id);

    function notify(message) {
        const box =
            el("notification");

        const text =
            el("notificationMessage");

        if (!box || !text) {
            return;
        }

        text.textContent =
            message;

        box.classList.add("show");

        clearTimeout(
            notify.timer
        );

        notify.timer =
            setTimeout(() => {
                box.classList.remove("show");
            }, 2200);
    }


    function getSelector() {
        return el("deviceSelector");
    }


    function getSelectedDevice() {
        const selector =
            getSelector();

        if (selector) {
            state.selectedDevice =
                String(
                    selector.value || ""
                ).trim();
        }

        return state.selectedDevice;
    }


    function updateSelectionUI() {
        const device =
            getSelectedDevice();

        const info =
            el("selectedDeviceInfo");

        if (info) {
            info.textContent =
                device
                    ? `Selected: ${device}`
                    : "No device selected";
        }
    }


    function setSelectedDevice(device) {
        const value =
            String(device || "").trim();

        const selector =
            getSelector();

        if (selector) {
            selector.value =
                value;
        }

        state.selectedDevice =
            value;

        updateSelectionUI();

        window.dispatchEvent(
            new CustomEvent(
                "synaptimesh:device-changed",
                {
                    detail: {
                        device: value
                    }
                }
            )
        );

        if (value) {
            console.log(
                `[DEVICE] Selected device=${value}`
            );

            notify(
                `Device selected: ${value}`
            );

        } else {
            console.log(
                "[DEVICE] No device selected; command transmission disabled."
            );

            notify(
                "Select a device first before sending commands."
            );
        }
    }


    async function send(command) {

        const normalized =
            String(command || "")
                .trim()
                .toUpperCase();

        if (!normalized) {
            return false;
        }


        const device =
            getSelectedDevice();


        /* --------------------------------------------------
           GLOBAL DEVICE SAFETY GATE
           -------------------------------------------------- */

        if (!device) {

            console.warn(
                `[COMMAND BLOCKED] No device selected: ${normalized}`
            );

            notify(
                "Select a device first before sending commands."
            );

            return false;
        }


        /* --------------------------------------------------
           SINGLE GLOBAL COMMAND LOG
           -------------------------------------------------- */

        console.log(
            `[COMMAND] Device: ${device} | Command: ${normalized}`
        );


        const ws =
            window.SynaptiMeshWebSocket;


        /* ==================================================
           PRIMARY TRANSPORT
           NATIVE WEBSOCKET
           ================================================== */

        if (
            ws &&
            ws.isConnected()
        ) {

            const sent =
                ws.send(
                    "command",
                    {
                        device,
                        command: normalized
                    }
                );


            /*
             * WebSocket transmission succeeded.
             *
             * IMPORTANT:
             * Do NOT send the HTTP fallback after this,
             * otherwise the ESP32 could receive the same
             * command twice.
             */
            if (sent) {
                return true;
            }


            console.warn(
                `[COMMAND] WebSocket send unavailable; using HTTP fallback | Device: ${device} | Command: ${normalized}`
            );

        } else {

            console.warn(
                `[COMMAND] WebSocket not connected; using HTTP fallback | Device: ${device} | Command: ${normalized}`
            );
        }


        /* ==================================================
           HTTP FALLBACK
           EXISTING MASTER HUB /command ENDPOINT
           ================================================== */

        try {
            const cmdEndpoint = window.location.pathname.startsWith("/embedded") ? "/embedded/command" : "/command";
            const response =
                await fetch(
                    cmdEndpoint,
                    {
                        method: "POST",

                        headers: {
                            "Content-Type":
                                "text/plain",

                            "X-SynaptiMesh-Device":
                                device
                        },

                        body:
                            normalized,

                        cache:
                            "no-store"
                    }
                );


            const responseText =
                await response.text();


            if (!response.ok) {

                throw new Error(
                    responseText ||
                    `HTTP ${response.status}`
                );
            }


            console.log(
                `[COMMAND] HTTP fallback accepted | Device: ${device} | Command: ${normalized}`
            );

            return true;

        } catch (error) {

            console.error(
                `[COMMAND ERROR] WebSocket + HTTP transmission failed | Device: ${device} | Command: ${normalized} | ${error.message}`
            );

            notify(
                `Command failed: ${error.message}`
            );

            return false;
        }
    }


    function init() {

        const selector =
            getSelector();


        if (selector) {

            state.selectedDevice =
                String(
                    selector.value || ""
                ).trim();

            updateSelectionUI();


            selector.addEventListener(
                "change",
                () => {
                    setSelectedDevice(
                        selector.value
                    );
                }
            );
        }


        window.SynaptiMeshCommand = {

            send,

            getSelectedDevice,

            setSelectedDevice,

            isDeviceSelected:
                () =>
                    Boolean(
                        getSelectedDevice()
                    ),

            getState:
                () => ({
                    ...state
                })
        };


        window.dispatchEvent(
            new CustomEvent(
                "synaptimesh:command-manager-ready"
            )
        );
    }


    if (
        document.readyState ===
        "loading"
    ) {

        document.addEventListener(
            "DOMContentLoaded",
            init,
            {
                once: true
            }
        );

    } else {

        init();
    }

})();