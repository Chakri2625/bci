/* ==========================================================
   SYNAPTIMESH NATIVE WEBSOCKET CLIENT

   Browser <-> Master Hub
   Native WebSocket only.

   No Socket.IO
   No Engine.IO
   No HTTP polling
   ========================================================== */

(() => {
    "use strict";

    const WS_PATH = window.location.pathname.startsWith("/embedded") ? "/embedded/ws" : "/ws";
    const MIN_RECONNECT_DELAY = 1000;
    const MAX_RECONNECT_DELAY = 10000;

    let socket = null;
    let reconnectTimer = null;
    let reconnectDelay = MIN_RECONNECT_DELAY;
    let manuallyClosed = false;

    const listeners = new Map();

    function on(type, handler) {
        if (typeof handler !== "function") return () => {};

        if (!listeners.has(type)) {
            listeners.set(type, new Set());
        }

        listeners.get(type).add(handler);

        return () => off(type, handler);
    }

    function off(type, handler) {
        const set = listeners.get(type);
        if (!set) return;

        set.delete(handler);

        if (set.size === 0) {
            listeners.delete(type);
        }
    }

    function emit(type, data) {
        console.debug(
            "[SynaptiMesh WS] EMIT ->",
            type,
            data
        );

        const set = listeners.get(type);
        if (!set) return;

        for (const handler of [...set]) {
            try {
                handler(data);
            } catch (error) {
                console.error(
                    `[WebSocket] Listener error for ${type}:`,
                    error
                );
            }
        }
    }

    function getUrl() {
        const protocol =
            window.location.protocol === "https:"
                ? "wss:"
                : "ws:";

        return `${protocol}//${window.location.host}${WS_PATH}`;
    }

    function isConnected() {
        return Boolean(
            socket &&
            socket.readyState === WebSocket.OPEN
        );
    }

    function send(type, payload = {}) {
        console.log(
            "[SynaptiMesh WS] SEND ->",
            type,
            payload
        );

        if (!isConnected()) {
            return false;
        }

        const message = {
            type,
            ...payload
        };

        try {
            socket.send(JSON.stringify(message));
            return true;
        } catch (error) {
            console.error("[WebSocket] Send failed:", error);
            return false;
        }
    }

    function scheduleReconnect() {
        if (manuallyClosed || reconnectTimer) {
            return;
        }

        reconnectTimer = window.setTimeout(() => {
            reconnectTimer = null;
            connect();
        }, reconnectDelay);

        reconnectDelay = Math.min(
            reconnectDelay * 2,
            MAX_RECONNECT_DELAY
        );
    }

    function connect() {
        if (
            manuallyClosed ||
            socket && (
                socket.readyState === WebSocket.OPEN ||
                socket.readyState === WebSocket.CONNECTING
            )
        ) {
            return;
        }

        const url = getUrl();

        console.log(
            "[SynaptiMesh WS] CONNECTING ->",
            url
        );

        try {
            socket = new WebSocket(url);
        } catch (error) {
            console.error("[WebSocket] Creation failed:", error);
            emit("error", error);
            scheduleReconnect();
            return;
        }

        socket.addEventListener("open", () => {
            console.log(
                "[SynaptiMesh WS] OPEN",
                { url }
            );

            reconnectDelay = MIN_RECONNECT_DELAY;

            emit("open", {
                url,
                transport: "websocket"
            });

            startHeartbeat();

            try {
                socket.send(JSON.stringify({
                    type: "hello",
                    client: "SynaptiMesh Dashboard"
                }));
            } catch (_) {
                // Connection is already open; normal event flow continues.
            }
        });

        socket.addEventListener("message", event => {
            let data;
            try {
                data = JSON.parse(event.data);
            } catch (error) {
                console.error(
                    "[WebSocket] Invalid server message:",
                    event.data
                );
                emit("error", error);
                return;
            }

            if (!data || typeof data !== "object") {
                return;
            }

            const type = String(data.type || "message").toUpperCase();

            if (type === "PONG") {
                const clientTime = (data.payload && data.payload.client_time) || lastPingTime;
                if (clientTime) {
                    lastLatencyMs = Math.max(0, Date.now() - clientTime);
                    data.latencyMs = lastLatencyMs;
                }
            }

            emit(type, data);
            emit("message", data);
        });

        socket.addEventListener("error", event => {
            console.error(
                "[SynaptiMesh WS] ERROR",
                event
            );

            emit("error", event);
        });

        socket.addEventListener("close", event => {
            console.warn(
                "[SynaptiMesh WS] CLOSE",
                { code: event.code, reason: event.reason, wasClean: event.wasClean }
            );

            stopHeartbeat();
            emit("close", event);
            socket = null;
            scheduleReconnect();
        });
    }

    let heartbeatTimer = null;
    let lastPingTime = 0;
    let lastLatencyMs = 0;

    function startHeartbeat() {
        stopHeartbeat();
        heartbeatTimer = window.setInterval(() => {
            if (isConnected()) {
                lastPingTime = Date.now();
                send("PING", { time: lastPingTime, client: "SynaptiMesh Dashboard" });
            }
        }, 10000);
    }

    function stopHeartbeat() {
        if (heartbeatTimer) {
            window.clearInterval(heartbeatTimer);
            heartbeatTimer = null;
        }
    }

    function close() {
        manuallyClosed = true;
        stopHeartbeat();

        if (reconnectTimer) {
            window.clearTimeout(reconnectTimer);
            reconnectTimer = null;
        }

        if (socket) {
            socket.close(1000, "Client closed");
        }

        socket = null;
    }

    window.SynaptiMeshWebSocket = {
        connect,
        close,
        send,
        on,
        off,
        isConnected,
        getLatency: () => lastLatencyMs,
        getState: () => ({
            connected: isConnected(),
            readyState: socket
                ? socket.readyState
                : WebSocket.CLOSED,
            url: getUrl(),
            latencyMs: lastLatencyMs
        })
    };

    if (document.readyState === "loading") {
        document.addEventListener(
            "DOMContentLoaded",
            connect,
            { once: true }
        );
    } else {
        connect();
    }
})();
