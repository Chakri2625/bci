/* ==========================================================
   SYNAPTIMESH MQTT BROKER POPUP
   ----------------------------------------------------------
   Opens when the MQTT connection status pill is clicked.

   Supports:
       DevOps MQTT 1
       DevOps MQTT 2
       Public HiveMQ
       Custom

   Backend:
       GET  /mqtt/config
       POST /mqtt/config
   ========================================================== */

(() => {
    "use strict";


    // ======================================================
    // ELEMENT HELPER
    // ======================================================

    const el = (id) =>
        document.getElementById(id);


    // ======================================================
    // STATE
    // ======================================================

    const state = {
        profiles: {},
        current: {
            broker: "",
            port: 1883,
            connected: false,
            state: "OFFLINE"
        }
    };


    // ======================================================
    // POPUP ELEMENTS
    // ======================================================

    const popup =
        el("mqttBrokerPopup");

    const backdrop =
        el("mqttBrokerPopupBackdrop");

    const closeButton =
        el("mqttBrokerPopupClose");

    const profileSelect =
        el("mqttBrokerProfile");

    const brokerInput =
        el("mqttBrokerHost");

    const portInput =
        el("mqttBrokerPort");

    const applyButton =
        el("mqttBrokerApply");

    const popupStatus =
        el("mqttPopupStatus");

    const popupStatusText =
        el("mqttPopupStatusText");

    const mqttStatus =
        el("mqttDiagramState");


    if (
        !popup ||
        !profileSelect ||
        !brokerInput ||
        !portInput ||
        !applyButton ||
        !mqttStatus
    ) {
        return;
    }


    // ======================================================
    // OPEN
    // ======================================================

    function openPopup() {

        popup.classList.add("open");

        backdrop?.classList.add(
            "open"
        );

        popup.setAttribute(
            "aria-hidden",
            "false"
        );

        loadConfiguration();

        setTimeout(() => {

            profileSelect.focus();

        }, 50);
    }


    // ======================================================
    // CLOSE
    // ======================================================

    function closePopup() {

        popup.classList.remove(
            "open"
        );

        backdrop?.classList.remove(
            "open"
        );

        popup.setAttribute(
            "aria-hidden",
            "true"
        );
    }


    // ======================================================
    // STATUS
    // ======================================================

    function setPopupStatus(
        text,
        type = ""
    ) {

        if (popupStatusText) {

            popupStatusText.textContent =
                text;
        }

        if (popupStatus) {

            popupStatus.classList.remove(
                "online",
                "error"
            );

            if (type) {

                popupStatus.classList.add(
                    type
                );
            }
        }
    }


    // ======================================================
    // LOAD MQTT CONFIG
    // ======================================================

    async function loadConfiguration() {

        try {

            const response =
                await fetch(
                    "/mqtt/config",
                    {
                        method: "GET",
                        cache: "no-store"
                    }
                );

            const data =
                await response.json();

            if (
                !response.ok ||
                !data.success
            ) {

                throw new Error(
                    data.error ||
                    "Unable to load MQTT configuration."
                );
            }


            state.profiles =
                data.profiles || {};


            state.current =
                data.current || state.current;


            brokerInput.value =
                state.current.broker || "";


            portInput.value =
                state.current.port || 1883;


            updateConnectionStatus(
                state.current
            );


            selectMatchingProfile(
                state.current
            );

            applyProfileToInputs();

        } catch (error) {

            console.error(
                "[MQTT POPUP] Configuration load failed:",
                error
            );

            setPopupStatus(
                "CONFIGURATION ERROR",
                "error"
            );
        }
    }


    // ======================================================
    // MATCH PROFILE
    // ======================================================

    function selectMatchingProfile(
        current
    ) {

        const broker =
            String(
                current?.broker || ""
            ).trim();

        const port =
            Number(
                current?.port || 1883
            );


        let matched = "custom";


        for (
            const [
                key,
                profile
            ] of Object.entries(
                state.profiles
            )
        ) {

            if (
                String(
                    profile.broker
                ).trim() === broker &&
                Number(
                    profile.port
                ) === port
            ) {

                matched = key;

                break;
            }
        }


        profileSelect.value =
            matched;
    }


    // ======================================================
    // UPDATE INPUTS FROM PROFILE
    // ======================================================

    function applyProfileToInputs() {

        const key = String(profileSelect.value || "").trim();

        console.log(
            "[MQTT POPUP] PROFILE SELECTED ->",
            key
        );


        if (
            key === "custom"
        ) {

            brokerInput.disabled =
                false;

            portInput.disabled =
                false;

            return;
        }


        const profile =
            state.profiles[key];


        if (!profile) {
            return;
        }


        brokerInput.value =
            profile.broker;


        portInput.value =
            profile.port;


        brokerInput.disabled =
            true;

        portInput.disabled =
            true;
    }


    // ======================================================
    // CONNECTION STATUS
    // ======================================================

    function updateConnectionStatus(
        config
    ) {

        const connected =
            Boolean(
                config?.connected
            );


        if (connected) {

            setPopupStatus(
                "CONNECTED",
                "online"
            );

        } else {

            setPopupStatus(
                String(
                    config?.state ||
                    "OFFLINE"
                ).toUpperCase(),
                ""
            );
        }
    }


    // ======================================================
    // APPLY MQTT CONFIGURATION
    // ======================================================

    async function applyConfiguration() {

        const profile =
            profileSelect.value;


        const broker =
            String(
                brokerInput.value || ""
            ).trim();


        const port =
            Number(
                portInput.value
            );


        if (!broker) {

            setPopupStatus(
                "BROKER REQUIRED",
                "error"
            );

            return;
        }


        if (
            !Number.isInteger(port) ||
            port < 1 ||
            port > 65535
        ) {

            setPopupStatus(
                "INVALID PORT",
                "error"
            );

            return;
        }


        applyButton.disabled =
            true;


        setPopupStatus(
            "CONNECTING...",
            ""
        );


        try {

            const response =
                await fetch(
                    "/mqtt/config",
                    {
                        method: "POST",

                        headers: {
                            "Content-Type":
                                "application/json"
                        },

                        body: JSON.stringify({
                            profile,
                            broker,
                            port
                        }),

                        cache: "no-store"
                    }
                );


            const data =
                await response.json();


            if (
                !response.ok ||
                !data.success
            ) {

                throw new Error(
                    data.error ||
                    "MQTT configuration failed."
                );
            }


            state.current =
                data.config ||
                state.current;


            brokerInput.value =
                state.current.broker;


            portInput.value =
                state.current.port;


            updateConnectionStatus(
                state.current
            );


            selectMatchingProfile(
                state.current
            );

            applyProfileToInputs();


            /*
             * Let the existing dashboard MQTT listener
             * update the connection diagram.
             */

            window.dispatchEvent(
                new CustomEvent(
                    "synaptimesh:mqtt-config-changed",
                    {
                        detail:
                            state.current
                    }
                )
            );


        } catch (error) {

            console.error(
                "[MQTT POPUP] Apply failed:",
                error
            );

            setPopupStatus(
                "CONNECTION FAILED",
                "error"
            );

        } finally {

            applyButton.disabled =
                false;
        }
    }


    // ======================================================
    // PROFILE CHANGE
    // ======================================================

    profileSelect.addEventListener(
        "change",
        () => {
            applyProfileToInputs();
        }
    );


    // ======================================================
    // OPEN / CLOSE EVENTS
    // ======================================================

    mqttStatus.addEventListener(
        "click",
        openPopup
    );


    closeButton?.addEventListener(
        "click",
        closePopup
    );


    backdrop?.addEventListener(
        "click",
        closePopup
    );


    applyButton.addEventListener(
        "click",
        applyConfiguration
    );


    // ======================================================
    // ESCAPE KEY
    // ======================================================

    document.addEventListener(
        "keydown",
        event => {

            if (
                event.key === "Escape" &&
                popup.classList.contains(
                    "open"
                )
            ) {

                closePopup();
            }
        }
    );


    // ======================================================
    // INITIAL PROFILE STATE
    // ======================================================

    applyProfileToInputs();

})();