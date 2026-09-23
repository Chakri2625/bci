"""
Master Hub Cortex Integration Service for Emotiv EPOC X Headset.
Manages communication with Emotiv Cortex API v2 (wss://localhost:6868),
headset discovery, session lifecycle, telemetry streaming, command extraction,
and real-time WebSocket broadcast to Training Cube and BCI Suite.
"""

import sys
import os
import ssl
import json
import time
import asyncio
import logging
from typing import Dict, Any, Optional, Callable, List, Set
from pydantic import BaseModel, Field

logger = logging.getLogger("cortex_service")


class CortexConfig(BaseModel):
    url: str = Field(default="wss://localhost:6868", description="Emotiv Cortex WebSocket API URL")
    client_id: str = Field(default="LeIpR00oXMhYpKNsnH5I26capksi3LV4hA3QjCLR", description="Emotiv Cortex Client ID")
    client_secret: str = Field(default="1yjXoxkw4aPujipgvVxtLGYN1hu6ZgctD9YI7zptmlLUynkzNdZoux3oipQyTV1Nnu65284semeJ4UT02po3ikzPDrxaYewrM9AyUzmwfhJJDR7UEgNIHQurIvWE2jj3", description="Emotiv Cortex Client Secret")
    license_key: str = Field(default="", description="Optional Emotiv License Key")
    debit: int = Field(default=1, description="Cortex session debit units")
    power_threshold: float = Field(default=0.35, description="Minimum confidence/power threshold for BCI commands")
    debounce_ms: int = Field(default=900, description="Debounce period in milliseconds")
    temporal_window_ms: int = Field(default=4000, description="Global temporal framing window duration in ms")
    temporal_window_enabled: bool = Field(default=True, description="Whether temporal window framing is active")
    reconnect_base_delay: float = Field(default=2.0, description="Initial reconnect delay in seconds")
    reconnect_max_delay: float = Field(default=30.0, description="Maximum reconnect delay cap in seconds")
    max_reconnect_attempts: int = Field(default=10, description="Maximum consecutive reconnect attempts")
    backoff_multiplier: float = Field(default=2.0, description="Exponential backoff multiplier")


class CortexService:
    """
    Master Hub Native Cortex Service.
    Maintains shared EPOC X headset state and bridges real-time mental commands
    and neural telemetry to the central command orchestrator and UI dashboards.
    """

    _instance: Optional["CortexService"] = None

    def __init__(self, config: Optional[CortexConfig] = None):
        self.config = config or CortexConfig()
        self.url = self.config.url
        self.client_id = os.getenv("CORTEX_CLIENT_ID", self.config.client_id).strip()
        self.client_secret = os.getenv("CORTEX_CLIENT_SECRET", self.config.client_secret).strip()
        self.license_key = os.getenv("CORTEX_LICENSE", self.config.license_key).strip()
        self.debit = self.config.debit

        # State tracking
        self.ws = None
        self.request_id = 1
        self.pending_requests: Dict[int, asyncio.Future] = {}

        self.cortex_token: Optional[str] = None
        self.headset_id: Optional[str] = None
        self.headsets: List[Dict[str, Any]] = []
        self.session_id: Optional[str] = None
        self.subscribed_streams: List[str] = []
        self.available_profiles: List[str] = []
        self.active_profile: Optional[str] = None
        self.battery_level: Optional[int] = None
        self.signal_quality: Optional[str] = "GOOD"
        self.contact_quality: Dict[str, float] = {}
        self.band_powers: Dict[str, float] = {}
        self.last_action: str = "NEUTRAL"
        self.last_power: float = 0.0
        self.last_timestamp: float = 0.0

        # Connection status flags
        self.is_connected = False
        self.is_authorized = False
        self.is_session_active = False
        self.is_subscribed = False

        # Tasks and listeners
        self._listen_task: Optional[asyncio.Task] = None
        self._reconnect_task: Optional[asyncio.Task] = None
        self._auth_task: Optional[asyncio.Task] = None
        self._should_reconnect = False
        self._ws_clients: Set[Any] = set()
        self._listeners: Dict[str, List[Callable]] = {}

        # Debounce and last command time
        self._last_cmd_time = 0.0

        # Reconnect parameters
        self.reconnect_base_delay: float = float(os.getenv("CORTEX_RECONNECT_BASE_DELAY", str(self.config.reconnect_base_delay)))
        self.reconnect_max_delay: float = float(os.getenv("CORTEX_RECONNECT_MAX_DELAY", str(self.config.reconnect_max_delay)))
        self.max_reconnect_attempts: int = int(os.getenv("CORTEX_MAX_RECONNECT_ATTEMPTS", str(self.config.max_reconnect_attempts)))
        self.backoff_multiplier: float = float(os.getenv("CORTEX_BACKOFF_MULTIPLIER", str(self.config.backoff_multiplier)))
        self.reconnect_attempts: int = 0
        self._saved_profile: Optional[str] = None

    @property
    def auth_token(self) -> Optional[str]:
        return self.cortex_token

    @property
    def power_threshold(self) -> float:
        return self.config.power_threshold

    @property
    def debounce_ms(self) -> int:
        return self.config.debounce_ms

    @property
    def _power_threshold(self) -> float:
        return self.config.power_threshold

    @property
    def _debounce_ms(self) -> int:
        return self.config.debounce_ms

    @classmethod
    def get_instance(cls) -> "CortexService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def load_profile(self, profile_name: str) -> Dict[str, Any]:
        """Load a trained BCI profile via Cortex setupProfile JSON-RPC method."""
        self.active_profile = profile_name
        if not self.is_ws_alive or not self.cortex_token:
            return {"status": "success", "profile": profile_name, "loaded": True, "offline": True}
        try:
            res = await self.request("setupProfile", {
                "cortexToken": self.cortex_token,
                "headset": self.headset_id,
                "profile": profile_name,
                "status": "load"
            })
            await self.broadcast_event("cortex_status", self.get_status())
            return {"status": "success", "profile": profile_name, "result": res}
        except Exception as e:
            logger.warning(f"[CORTEX] load_profile warning: {e}")
            return {"status": "error", "message": str(e), "profile": profile_name}

    async def query_profiles(self) -> List[str]:
        """Query available trained user profiles in Cortex."""
        if not self.is_ws_alive or not self.cortex_token:
            return list(self.available_profiles)
        try:
            res = await self.request("queryProfile", {"cortexToken": self.cortex_token})
            if isinstance(res, list):
                self.available_profiles = [p.get("name", str(p)) if isinstance(p, dict) else str(p) for p in res]
            return list(self.available_profiles)
        except Exception:
            return list(self.available_profiles)

    def get_status(self) -> Dict[str, Any]:
        """Return comprehensive live status of the Cortex & EPOC X connection."""
        return {
            "connected": self.is_connected,
            "authorized": self.is_authorized,
            "sessionActive": self.is_session_active,
            "session_active": self.is_session_active,
            "subscribed": self.is_subscribed,
            "headsetId": self.headset_id,
            "headset_id": self.headset_id,
            "headsets": list(self.headsets),
            "sessionId": self.session_id,
            "session_id": self.session_id,
            "availableProfiles": list(self.available_profiles),
            "available_profiles": list(self.available_profiles),
            "activeProfile": self.active_profile,
            "active_profile": self.active_profile,
            "battery": self.battery_level,
            "signalQuality": self.signal_quality,
            "signal_quality": self.signal_quality,
            "contactQuality": dict(self.contact_quality),
            "contact_quality": dict(self.contact_quality),
            "bandPowers": dict(self.band_powers),
            "band_powers": dict(self.band_powers),
            "subscribedStreams": list(self.subscribed_streams),
            "subscribed_streams": list(self.subscribed_streams),
            "activeAction": self.last_action,
            "active_action": self.last_action,
            "activePower": self.last_power,
            "active_power": self.last_power,
            "lastTimestamp": self.last_timestamp,
            "hasCredentials": bool(self.client_id and self.client_secret),
            "has_credentials": bool(self.client_id and self.client_secret),
            "reconnectAttempts": self.reconnect_attempts,
            "reconnect_attempts": self.reconnect_attempts,
            "maxReconnectAttempts": self.max_reconnect_attempts,
            "max_reconnect_attempts": self.max_reconnect_attempts,
            "url": self.url,
            "config": self.config.model_dump()
        }

    def set_credentials(self, client_id: str, client_secret: str, license_key: str = "", license_id: str = "", profile_name: str = "", **kwargs):
        self.client_id = (client_id or "").strip()
        self.client_secret = (client_secret or "").strip()
        lic = license_key or license_id
        if lic:
            self.license_key = lic.strip()
            self.config.license_key = self.license_key
        if profile_name:
            self.active_profile = profile_name.strip()
            self.config.active_profile = self.active_profile
        self.config.client_id = self.client_id
        self.config.client_secret = self.client_secret
        logger.info("[CORTEX] Credentials updated")

    async def run_diagnostic(self) -> Dict[str, Any]:
        """Run active diagnostic check on Cortex connection, headsets, and subscriptions."""
        headsets_list = list(self.headsets)
        if self.is_ws_alive and self.auth_token:
            try:
                headsets_res = await self.request("queryHeadsets", timeout=3.0)
                if isinstance(headsets_res, list):
                    headsets_list = headsets_res
            except Exception:
                pass
        return {
            "status": "success",
            "endpoint": self.url,
            "socket_connected": self.is_ws_alive,
            "authorized": self.is_authorized,
            "session_active": self.is_session_active,
            "subscribed": self.is_subscribed,
            "headset_id": self.headset_id,
            "headsets": headsets_list,
            "subscriptions": list(self.subscribed_streams),
            "active_profile": self.active_profile,
            "battery": self.battery_level,
            "signal_quality": self.signal_quality,
            "client_id_configured": bool(self.client_id),
            "timestamp": time.time()
        }

    def register_client(self, ws):
        """Register a connected frontend WebSocket client for telemetry broadcasting."""
        self._ws_clients.add(ws)
        logger.debug(f"[CORTEX] Frontend client registered (total: {len(self._ws_clients)})")

    def unregister_client(self, ws):
        """Unregister a disconnected frontend WebSocket client."""
        self._ws_clients.discard(ws)
        logger.debug(f"[CORTEX] Frontend client unregistered (remaining: {len(self._ws_clients)})")

    async def broadcast_event(self, event_type: str, payload: Any):
        """Broadcast an event to all connected dashboard WebSocket clients."""
        if not self._ws_clients:
            return

        message = json.dumps({"type": event_type, "payload": payload})
        dead_clients = []

        for ws in list(self._ws_clients):
            try:
                await ws.send_text(message)
            except Exception:
                dead_clients.append(ws)

        for ws in dead_clients:
            self.unregister_client(ws)

    def on(self, event_name: str, callback: Callable):
        if event_name not in self._listeners:
            self._listeners[event_name] = []
        self._listeners[event_name].append(callback)

    def emit(self, event_name: str, data: Any = None):
        if event_name in self._listeners:
            for callback in self._listeners[event_name]:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        try:
                            loop = asyncio.get_running_loop()
                            loop.create_task(callback(data))
                        except RuntimeError:
                            pass
                    else:
                        callback(data)
                except Exception as e:
                    logger.error(f"[CORTEX] Error in listener '{event_name}': {e}")

    @property
    def is_ws_alive(self) -> bool:
        if self.ws is None:
            return False
        try:
            if hasattr(self.ws, "state"):
                return str(self.ws.state).endswith("OPEN") or getattr(self.ws.state, "name", "") == "OPEN"
            if hasattr(self.ws, "closed"):
                return not self.ws.closed
            if hasattr(self.ws, "open"):
                return bool(self.ws.open)
        except Exception:
            pass
        return True

    async def request(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 15.0) -> Any:
        """Send a JSON-RPC 2.0 request over the Cortex WebSocket and await the response."""
        if not self.is_ws_alive or not self.ws:
            raise RuntimeError("Cortex WebSocket is not open.")

        params = params or {}
        msg_id = self.request_id
        self.request_id += 1

        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": msg_id,
        }

        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self.pending_requests[msg_id] = fut

        await self.ws.send(json.dumps(payload))

        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self.pending_requests.pop(msg_id, None)
            raise TimeoutError(f"Timeout waiting for Cortex response to '{method}' (ID {msg_id})")

    async def connect(self) -> Dict[str, Any]:
        """Initiate connection and authorization handshake with Cortex Service."""
        import websockets

        if self.is_ws_alive:
            logger.info("[CORTEX] WebSocket already connected")
            if self.client_id and self.client_secret and not self.is_subscribed:
                self._auth_task = asyncio.create_task(self.authenticate_and_subscribe())
            return {"status": "already_connected", "state": self.get_status()}

        logger.info(f"[CORTEX] Connecting to Emotiv Cortex Service at {self.url}...")
        self._should_reconnect = True

        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        try:
            self.ws = await websockets.connect(self.url, ssl=ssl_ctx)
            self.is_connected = True
            self.reconnect_attempts = 0
            self._sync_state_manager()
            logger.info("[CORTEX] Connected to Emotiv Cortex WebSocket successfully")
            
            # Start listener loop
            self._listen_task = asyncio.create_task(self._listener_loop())

            # Broadcast status update
            await self.broadcast_event("cortex_status", self.get_status())
            await self.broadcast_event("log", {"level": "success", "message": "Connected to Emotiv Cortex API (port 6868)"})

            if self.client_id and self.client_secret:
                self._auth_task = asyncio.create_task(self.authenticate_and_subscribe())
            else:
                logger.info("[CORTEX] Connected. Awaiting Client ID & Secret to authorize.")

            return {"status": "connected", "state": self.get_status()}

        except Exception as err:
            self.is_connected = False
            logger.warning(f"[CORTEX] Connection failed: {err}")
            await self.broadcast_event("cortex_status", self.get_status())
            await self.broadcast_event("log", {"level": "error", "message": f"Cortex connection failed: {err}"})
            return {"status": "error", "message": str(err), "state": self.get_status()}

    async def disconnect(self):
        """Disconnect active Cortex WebSocket session."""
        self._should_reconnect = False
        if self._reconnect_task and not self._reconnect_task.done():
            task = self._reconnect_task
            self._reconnect_task = None
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        if self._listen_task and not self._listen_task.done():
            task = self._listen_task
            self._listen_task = None
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        if self._auth_task and not self._auth_task.done():
            task = self._auth_task
            self._auth_task = None
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None

        self._reset_state()
        logger.info("[CORTEX] Disconnected from Cortex")
        await self.broadcast_event("cortex_status", self.get_status())
        await self.broadcast_event("log", {"level": "info", "message": "Disconnected from Emotiv Cortex"})

    def _sync_state_manager(self):
        """Synchronize BCI domain state in the Master Hub StateManager."""
        try:
            from core.state.state_manager import state_manager
            if "BCI" in state_manager.domain_states:
                state_manager.domain_states["BCI"]["session_active"] = self.is_session_active
                if self.is_connected or self.is_session_active:
                    status = "CONNECTED"
                elif self._reconnect_task and not self._reconnect_task.done() and self._should_reconnect:
                    status = "RECOVERING"
                else:
                    status = "READY"
                state_manager.domain_states["BCI"]["status"] = status
        except Exception:
            pass

    def _reset_state(self):
        self.is_connected = False
        self.is_authorized = False
        self.is_session_active = False
        self.is_subscribed = False
        self.cortex_token = None
        self.session_id = None
        self.headset_id = None
        self.headsets = []
        self.available_profiles = []
        if self.active_profile:
            self._saved_profile = self.active_profile
        self.active_profile = None
        self.battery_level = None
        self.signal_quality = None
        self.last_action = "NEUTRAL"
        self.last_power = 0.0
        self._sync_state_manager()

    async def authenticate_and_subscribe(self):
        """Perform requestAccess, authorize, queryHeadsets, createSession, and subscribe."""
        if not self.client_id or not self.client_secret:
            logger.warning("[CORTEX] Missing Client ID or Client Secret")
            return

        try:
            # 1. requestAccess
            logger.info("[CORTEX] Requesting access rights...")
            try:
                access_res = await self.request("requestAccess", {
                    "clientId": self.client_id,
                    "clientSecret": self.client_secret
                })
                granted = access_res.get("accessGranted", False) if isinstance(access_res, dict) else False
                logger.info(f"[CORTEX] Access status: {'Granted' if granted else 'Pending confirmation in Emotiv App'}")
            except Exception as ex:
                logger.warning(f"[CORTEX] requestAccess note: {ex}")

            # 2. authorize
            logger.info("[CORTEX] Authorizing with client credentials...")
            auth_params = {
                "clientId": self.client_id,
                "clientSecret": self.client_secret,
                "debit": self.debit
            }
            if self.license_key:
                auth_params["license"] = self.license_key

            auth_res = await self.request("authorize", auth_params)
            if not auth_res or "cortexToken" not in auth_res:
                raise RuntimeError("Authorization failed: No cortexToken returned.")

            self.cortex_token = auth_res["cortexToken"]
            self.is_authorized = True
            logger.info("[CORTEX] Authorized successfully! cortexToken acquired.")
            await self.broadcast_event("cortex_status", self.get_status())

            # 3. queryHeadsets
            logger.info("[CORTEX] Querying connected headsets...")
            headsets = await self.request("queryHeadsets", {})
            self.headsets = headsets or []

            if not self.headsets:
                logger.info("[CORTEX] No headsets detected or in standby. Ready for headset connection.")
                await self.broadcast_event("cortex_status", self.get_status())
                asyncio.create_task(self._poll_for_headsets())
                return

            connected_headset = next((h for h in self.headsets if h.get("status") == "connected"), self.headsets[0])
            self.headset_id = connected_headset.get("id")

            if connected_headset.get("status") != "connected":
                try:
                    logger.info(f"[CORTEX] Connecting to headset {self.headset_id}...")
                    await self.request("controlDevice", {"command": "connect", "headset": self.headset_id})
                except Exception:
                    pass

            logger.info(f"[CORTEX] Active headset attached: {self.headset_id} ({connected_headset.get('status')})")

            # 4. createSession / querySessions
            logger.info(f"[CORTEX] Establishing session for {self.headset_id}...")
            session_id = None

            try:
                existing = await self.request("querySessions", {"cortexToken": self.cortex_token})
                if existing and isinstance(existing, list):
                    for s in existing:
                        if s.get("headset", {}).get("id") == self.headset_id and s.get("status") in ("active", "open"):
                            session_id = s.get("id")
                            logger.info(f"[CORTEX] Attached to existing session: {session_id}")
                            break
            except Exception:
                pass

            if not session_id:
                for st in ["open", "active"]:
                    try:
                        res = await self.request("createSession", {
                            "cortexToken": self.cortex_token,
                            "headset": self.headset_id,
                            "status": st
                        })
                        if res and "id" in res:
                            session_id = res["id"]
                            logger.info(f"[CORTEX] Session created ({st}): {session_id}")
                            break
                    except Exception:
                        continue

            if not session_id:
                raise RuntimeError("Could not establish active Cortex session.")

            self.session_id = session_id
            self.is_session_active = True
            await self.broadcast_event("cortex_status", self.get_status())

            # 5. Subscribe to mental commands and telemetry streams
            logger.info("[CORTEX] Subscribing to mental commands ('com') and telemetry streams...")
            stream_candidates = [
                ["com", "sys", "pow", "dev"],
                ["com", "sys"],
                ["com"]
            ]

            subscribed = False
            for streams in stream_candidates:
                try:
                    await self.request("subscribe", {
                        "cortexToken": self.cortex_token,
                        "session": self.session_id,
                        "streams": streams
                    })
                    self.subscribed_streams = streams
                    subscribed = True
                    logger.info(f"[CORTEX] Subscribed successfully to streams: {streams}")
                    break
                except Exception:
                    continue

            if not subscribed:
                raise RuntimeError("Failed to subscribe to mental command streams.")

            self.is_subscribed = True
            self._sync_state_manager()
            target_profile = self.active_profile or getattr(self, "_saved_profile", None) or getattr(self.config, "active_profile", None)
            if target_profile:
                try:
                    await self.load_profile(target_profile)
                except Exception as p_err:
                    logger.warning(f"[CORTEX] Could not re-load profile '{target_profile}': {p_err}")
            await self.broadcast_event("cortex_status", self.get_status())
            await self.broadcast_event("log", {
                "level": "success",
                "message": f"Cortex Ready — Headset: {self.headset_id}, Session: {self.session_id}"
            })

        except Exception as err:
            logger.error(f"[CORTEX] Authentication / subscription error: {err}")
            await self.broadcast_event("log", {"level": "error", "message": f"Cortex Setup Error: {err}"})

    async def _poll_for_headsets(self):
        """Poll periodically when no headset is initially connected."""
        while self.is_connected and self.is_authorized and not self.is_session_active:
            await asyncio.sleep(4.0)
            try:
                headsets = await self.request("queryHeadsets", {})
                if headsets and len(headsets) > 0:
                    self.headsets = headsets
                    await self.authenticate_and_subscribe()
                    break
            except Exception:
                pass

    async def _listener_loop(self):
        """Listen to incoming WebSocket stream from Cortex."""
        try:
            async for raw in self.ws:
                try:
                    data = json.loads(raw)
                except Exception:
                    continue

                try:
                    # 1. JSON-RPC Response to pending request ID
                    msg_id = data.get("id")
                    if msg_id and msg_id in self.pending_requests:
                        fut = self.pending_requests.pop(msg_id)
                        if not fut.done():
                            if "error" in data:
                                err_msg = data["error"].get("message", f"Cortex Error Code {data['error'].get('code')}")
                                fut.set_exception(RuntimeError(err_msg))
                            else:
                                fut.set_result(data.get("result"))
                        continue

                    # 2. Mental Commands ('com') stream
                    if "com" in data:
                        await self._handle_mental_command_data(data)

                    # 3. System events ('sys') & Battery
                    if "sys" in data:
                        sys_data = data.get("sys")
                        if isinstance(sys_data, (list, tuple)) and len(sys_data) >= 2:
                            if sys_data[0] == "battery":
                                try:
                                    self.battery_level = int(sys_data[1])
                                    await self.broadcast_event("cortex_status", self.get_status())
                                except (ValueError, TypeError):
                                    pass
                        await self.broadcast_event("sys", sys_data)

                    # 4. Band Power ('pow')
                    if "pow" in data:
                        await self._handle_band_power_data(data)

                    # 5. Device / Contact Quality ('dev')
                    if "dev" in data:
                        await self._handle_contact_quality_data(data)

                except Exception as frame_err:
                    logger.error(f"[CORTEX] Frame handling error: {frame_err}")

        except asyncio.CancelledError:
            disconnect_reason = "Connection cancelled"
            return
        except Exception as e:
            disconnect_reason = str(e) or "WebSocket stream error"
            logger.warning(f"[CORTEX] [CONNECTION_LOST] Listener stream disconnected: {disconnect_reason}")
        finally:
            self._reset_state()
            await self.broadcast_event("cortex_status", self.get_status())
            if self._should_reconnect:
                # Terminal visual output: CONNECTION LOST
                print("\n========== BCI CONNECTION ==========", flush=True)
                print("Status      : DISCONNECTED", flush=True)
                print(f"Reason      : {disconnect_reason}", flush=True)
                print("=====================================\n", flush=True)

                logger.warning(f"[CORTEX] [CONNECTION_LOST] Cortex connection lost: {disconnect_reason}")

                try:
                    from core.state.state_manager import state_manager
                    state_manager.record_failure(
                        domain="BCI",
                        affected_component="CortexService",
                        failure_type="CONNECTION_LOST",
                        failure_reason=disconnect_reason,
                        recovery_status="PENDING"
                    )
                except Exception:
                    pass

                if self._reconnect_task is None or self._reconnect_task.done():
                    self._reconnect_task = asyncio.create_task(self._reconnect_loop(disconnect_reason))

    async def _reconnect_loop(self, reason: str = "Connection lost"):
        """Robust exponential backoff reconnection handler with terminal output and recovery tracking."""
        self.reconnect_attempts = 0
        current_delay = self.reconnect_base_delay

        while self._should_reconnect and self.reconnect_attempts < self.max_reconnect_attempts:
            self.reconnect_attempts += 1
            attempt = self.reconnect_attempts

            # Terminal visual output: RECONNECTING
            print("\n========== RECONNECT HANDLER ==========", flush=True)
            print("Status      : RECONNECTING", flush=True)
            print(f"Attempt     : {attempt}", flush=True)
            print(f"Next Retry  : {current_delay:.1f} seconds", flush=True)
            print("========================================\n", flush=True)

            logger.info(f"[CORTEX] [RECONNECT_ATTEMPT] Attempt {attempt}/{self.max_reconnect_attempts} - Next retry in {current_delay:.1f}s")

            # Update StateManager to RECOVERING
            try:
                from core.state.state_manager import state_manager
                state_manager.update_recovery_status(
                    domain="BCI",
                    affected_component="CortexService",
                    recovery_status="RECOVERING",
                    attempt=attempt,
                    reason=f"Attempt {attempt}/{self.max_reconnect_attempts} (backoff {current_delay:.1f}s)"
                )
            except Exception:
                pass

            # Await exponential backoff delay
            try:
                await asyncio.sleep(current_delay)
            except asyncio.CancelledError:
                logger.info("[CORTEX] Reconnect loop cancelled during sleep.")
                return

            if not self._should_reconnect:
                return

            # Perform reconnect attempt
            last_err = None
            try:
                res = await self.connect()
                if res.get("status") in ("connected", "already_connected"):
                    # Wait briefly for authenticate_and_subscribe if task started
                    if hasattr(self, "_auth_task") and self._auth_task and not self._auth_task.done():
                        try:
                            await asyncio.wait_for(asyncio.shield(self._auth_task), timeout=5.0)
                        except (asyncio.TimeoutError, Exception):
                            pass

                    # Terminal visual output: SUCCESSFUL RECOVERY
                    print("\n========== BCI CONNECTION ==========", flush=True)
                    print("Status      : CONNECTED", flush=True)
                    print("Result      : Reconnected Successfully", flush=True)
                    print(f"Attempts    : {attempt}", flush=True)
                    print("=====================================\n", flush=True)

                    logger.info(f"[CORTEX] [RECONNECT_SUCCESS] Reconnected successfully on attempt {attempt}")

                    try:
                        from core.state.state_manager import state_manager
                        state_manager.update_recovery_status(
                            domain="BCI",
                            affected_component="CortexService",
                            recovery_status="RECOVERED",
                            attempt=attempt,
                            reason="Reconnected successfully"
                        )
                    except Exception:
                        pass

                    self.reconnect_attempts = 0
                    return
                else:
                    last_err = res.get("message", "Connection rejected")
            except Exception as conn_err:
                last_err = str(conn_err)

            # Failure on this attempt
            next_delay = min(current_delay * self.backoff_multiplier, self.reconnect_max_delay)
            print(f"[RECONNECT] Attempt {attempt} FAILED", flush=True)
            print(f"[RECONNECT] Retrying with backoff: {next_delay:.1f} seconds\n", flush=True)

            logger.warning(f"[CORTEX] [RECONNECT_FAILED] Attempt {attempt} failed: {last_err}")
            current_delay = next_delay

        # Reconnection loop exhausted
        if self._should_reconnect and not self.is_connected:
            print("\n========== BCI CONNECTION ==========", flush=True)
            print("Status      : FAILED", flush=True)
            print(f"Attempts    : {self.reconnect_attempts}", flush=True)
            print(f"Reason      : {reason}", flush=True)
            print("=====================================\n", flush=True)

            logger.error(f"[CORTEX] [FINAL_RECONNECT_FAILURE] Maximum attempts reached ({self.reconnect_attempts}). Reason: {reason}")

            try:
                from core.state.state_manager import state_manager
                state_manager.update_recovery_status(
                    domain="BCI",
                    affected_component="CortexService",
                    recovery_status="RECOVERY_FAILED",
                    attempt=self.reconnect_attempts,
                    reason=f"Exhausted {self.max_reconnect_attempts} reconnect attempts: {reason}"
                )
            except Exception:
                pass

    async def _handle_mental_command_data(self, data: Dict[str, Any]):
        """Extract and normalize mental command, apply threshold & debounce, and forward to Master Hub."""
        com_val = data.get("com")
        action = "neutral"
        power = 0.0

        if isinstance(com_val, (list, tuple)):
            if len(com_val) >= 1 and com_val[0] is not None:
                action = str(com_val[0]).strip().lower()
            if len(com_val) >= 2 and com_val[1] is not None:
                try:
                    power = float(com_val[1])
                except (ValueError, TypeError):
                    power = 0.0
        elif isinstance(com_val, dict):
            action = str(com_val.get("action", "neutral")).strip().lower()
            try:
                power = float(com_val.get("power", 0.0))
            except (ValueError, TypeError):
                power = 0.0
        elif isinstance(com_val, str):
            action = com_val.strip().lower()
            power = 1.0

        self.last_action = action.upper()
        self.last_power = power
        self.last_timestamp = data.get("time") or time.time()

        # Broadcast live telemetry event to Training Cube and BCI Suite
        telemetry_payload = {
            "source_domain": "BCI",
            "type": "MENTAL_COMMAND",
            "action": self.last_action,
            "power": power,
            "time": self.last_timestamp,
            "battery": self.battery_level,
            "headsetId": self.headset_id,
            "signalQuality": self.signal_quality,
            "contactQuality": dict(self.contact_quality),
            "bandPowers": dict(self.band_powers)
        }
        await self.broadcast_event("cortex_com", telemetry_payload)
        await self.broadcast_event("telemetry", telemetry_payload)

        # Filter NEUTRAL
        if action == "neutral":
            return

        # Confidence Threshold Check
        if power < self.config.power_threshold:
            logger.debug(f"[CORTEX] Command {action} power ({power:.2f}) < threshold ({self.config.power_threshold})")
            return

        # Debounce Filter
        now = time.time()
        if (now - self._last_cmd_time) * 1000.0 < self.config.debounce_ms:
            logger.debug(f"[CORTEX] Command {action} debounced (interval < {self.config.debounce_ms}ms)")
            return
        self._last_cmd_time = now

        # Normalize command name
        cmd_upper = action.upper()
        from core.validation.command_normalizer import normalize_command
        normalized_cmd = normalize_command(cmd_upper)

        logger.info(f"[BCI HEADSET] Dispatched command '{normalized_cmd}' (power={power:.2f}) to Master Hub")

        # Forward into Master Hub Ecosystem Orchestrator
        from core.orchestration.ecosystem_orchestrator import ecosystem_orchestrator
        try:
            asyncio.create_task(ecosystem_orchestrator.process_command(
                command=normalized_cmd,
                session="default",
                confidence=power,
                source="emotiv_epoc_x"
            ))
        except Exception as err:
            logger.error(f"[CORTEX] Error forwarding command to orchestrator: {err}")

    async def _handle_contact_quality_data(self, data: Dict[str, Any]):
        """Parse contact quality per electrode channel and broadcast BCI telemetry."""
        dev_val = data.get("dev")
        cq_dict = {}
        channel_names = ["AF3", "F7", "F3", "FC5", "T7", "P7", "O1", "O2", "P8", "T8", "FC6", "F4", "F8", "AF4"]

        if isinstance(dev_val, dict):
            if "cq" in dev_val and isinstance(dev_val["cq"], (list, tuple)):
                raw_cqs = dev_val["cq"]
                for i, score in enumerate(raw_cqs):
                    ch_name = channel_names[i] if i < len(channel_names) else f"CH{i+1}"
                    try:
                        val = float(score)
                        cq_dict[ch_name] = round(val / 4.0 if val <= 4.0 else val / 100.0, 3)
                    except (ValueError, TypeError):
                        cq_dict[ch_name] = 0.0
            else:
                for k, v in dev_val.items():
                    if k in ["battery", "signal"]:
                        continue
                    try:
                        val = float(v)
                        cq_dict[k] = round(val / 4.0 if val <= 4.0 else (val / 100.0 if val > 1.0 else val), 3)
                    except (ValueError, TypeError):
                        pass
        elif isinstance(dev_val, (list, tuple)):
            cq_items = dev_val
            if len(dev_val) >= 4 and isinstance(dev_val[3], (list, tuple)):
                cq_items = dev_val[3]
            elif len(dev_val) >= 2 and isinstance(dev_val[1], (list, tuple)):
                cq_items = dev_val[1]

            for i, score in enumerate(cq_items):
                ch_name = channel_names[i] if i < len(channel_names) else f"CH{i+1}"
                try:
                    val = float(score)
                    cq_dict[ch_name] = round(val / 4.0 if val <= 4.0 else (val / 100.0 if val > 1.0 else val), 3)
                except (ValueError, TypeError):
                    cq_dict[ch_name] = 0.0

        if cq_dict:
            self.contact_quality = cq_dict
            avg_cq = sum(cq_dict.values()) / max(1, len(cq_dict))
            self.signal_quality = "EXCELLENT" if avg_cq > 0.85 else ("GOOD" if avg_cq > 0.6 else ("POOR" if avg_cq > 0.3 else "NO_SIGNAL"))

        payload = {
            "source_domain": "BCI",
            "type": "CONTACT_QUALITY",
            "headsetId": self.headset_id,
            "battery": self.battery_level,
            "signal_quality_summary": self.signal_quality,
            "signal_quality": self.contact_quality,
            "time": data.get("time") or time.time()
        }
        await self.broadcast_event("cortex_dev", payload)
        await self.broadcast_event("cortex_cq", payload)
        await self.broadcast_event("telemetry", payload)

    async def _handle_band_power_data(self, data: Dict[str, Any]):
        """Parse frequency band powers and broadcast BCI spectral telemetry."""
        pow_val = data.get("pow")
        band_dict = {}

        if isinstance(pow_val, dict):
            band_dict = {str(k): float(v) for k, v in pow_val.items() if isinstance(v, (int, float))}
        elif isinstance(pow_val, (list, tuple)):
            labels = ["theta_uv2", "alpha_uv2", "beta_low_uv2", "beta_high_uv2", "gamma_uv2"]
            if len(pow_val) == 5:
                for i, lbl in enumerate(labels):
                    try:
                        band_dict[lbl] = round(float(pow_val[i]), 3)
                    except (ValueError, TypeError):
                        pass
            elif len(pow_val) > 5:
                theta_sum, alpha_sum, beta_l_sum, beta_h_sum, gamma_sum = 0.0, 0.0, 0.0, 0.0, 0.0
                num_ch = max(1, len(pow_val) // 5)
                for c in range(num_ch):
                    base = c * 5
                    if base + 4 < len(pow_val):
                        try:
                            theta_sum += float(pow_val[base])
                            alpha_sum += float(pow_val[base + 1])
                            beta_l_sum += float(pow_val[base + 2])
                            beta_h_sum += float(pow_val[base + 3])
                            gamma_sum += float(pow_val[base + 4])
                        except (ValueError, TypeError):
                            pass
                band_dict = {
                    "theta_uv2": round(theta_sum / num_ch, 3),
                    "alpha_uv2": round(alpha_sum / num_ch, 3),
                    "beta_low_uv2": round(beta_l_sum / num_ch, 3),
                    "beta_high_uv2": round(beta_h_sum / num_ch, 3),
                    "gamma_uv2": round(gamma_sum / num_ch, 3)
                }

        if band_dict:
            self.band_powers = band_dict

        payload = {
            "source_domain": "BCI",
            "type": "FREQUENCY_BANDS",
            "headsetId": self.headset_id,
            "frequency_bands": self.band_powers,
            "time": data.get("time") or time.time()
        }
        await self.broadcast_event("cortex_pow", payload)
        await self.broadcast_event("telemetry", payload)


# Global Singleton Instance
cortex_service = CortexService.get_instance()
