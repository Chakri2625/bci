import sys
import os
import ssl
import json
import asyncio
from typing import Dict, Any, Optional, Callable, List
import websockets

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class CortexBridge:
    def __init__(
        self,
        url: str = "wss://localhost:6868",
        client_id: str = "",
        client_secret: str = "",
        license_key: str = "",
        debit: int = 1,
    ):
        self.url = url or "wss://localhost:6868"
        self.client_id = (client_id or os.getenv("CORTEX_CLIENT_ID", "")).strip()
        self.client_secret = (client_secret or os.getenv("CORTEX_CLIENT_SECRET", "")).strip()
        self.license_key = (license_key or os.getenv("CORTEX_LICENSE", "")).strip()
        self.debit = int(debit)

        self.ws: Optional[websockets.WebSocketClientProtocol] = None
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
        self.signal_quality: Optional[str] = None

        self.is_connected = False
        self.is_authorized = False
        self.is_session_active = False
        self.is_subscribed = False

        self._listen_task: Optional[asyncio.Task] = None
        self._listeners: Dict[str, List[Callable]] = {}

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
                    print(f"[ERROR in Cortex listener '{event_name}']: {e}")

    def set_credentials(self, credentials: Dict[str, Any]):
        if "clientId" in credentials:
            self.client_id = str(credentials["clientId"]).strip()
        elif "client_id" in credentials:
            self.client_id = str(credentials["client_id"]).strip()

        if "clientSecret" in credentials:
            self.client_secret = str(credentials["clientSecret"]).strip()
        elif "client_secret" in credentials:
            self.client_secret = str(credentials["client_secret"]).strip()

        if "license" in credentials:
            self.license_key = str(credentials["license"]).strip()
        elif "license_key" in credentials:
            self.license_key = str(credentials["license_key"]).strip()

        if "debit" in credentials:
            self.debit = int(credentials["debit"])

    def get_status(self) -> Dict[str, Any]:
        return {
            "connected": self.is_connected,
            "authorized": self.is_authorized,
            "sessionActive": self.is_session_active,
            "subscribed": self.is_subscribed,
            "headsetId": self.headset_id,
            "sessionId": self.session_id,
            "headsets": list(self.headsets),
            "availableProfiles": list(self.available_profiles),
            "activeProfile": self.active_profile,
            "battery": self.battery_level,
            "signalQuality": self.signal_quality,
            "subscribedStreams": list(self.subscribed_streams),
            "hasCredentials": bool(self.client_id and self.client_secret),
        }

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

    async def connect(self):
        if self.is_ws_alive:
            self.emit("log", {"level": "info", "message": "Cortex WebSocket is already connected."})
            if self.client_id and self.client_secret and not self.is_subscribed:
                asyncio.create_task(self.authenticate_and_subscribe())
            return

        self.emit("log", {"level": "info", "message": f"Connecting to Emotiv Cortex Service at {self.url}..."})
        self.emit("status_change", {"state": "connecting"})

        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        try:
            self.ws = await websockets.connect(self.url, ssl=ssl_ctx)
            self.is_connected = True
            self.emit("log", {"level": "success", "message": "Connected to Emotiv Cortex Service WebSocket (port 6868)!"})
            self.emit("status_change", {"state": "connected"})

            # Start message listener
            self._listen_task = asyncio.create_task(self._listener_loop())

            if self.client_id and self.client_secret:
                asyncio.create_task(self.authenticate_and_subscribe())
            else:
                self.emit("log", {
                    "level": "info",
                    "message": "Cortex connected. Please enter your Emotiv Client ID & Secret in settings to authorize data streaming.",
                })
        except Exception as err:
            self.is_connected = False
            self.emit("log", {
                "level": "error",
                "message": f"Cortex connection failed: {err}. Ensure Emotiv App / Cortex Service is running on port 6868.",
            })
            self.emit("status_change", {"state": "disconnected"})

    async def disconnect(self):
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None

        self._reset_state()
        self.emit("status_change", {"state": "disconnected"})
        self.emit("log", {"level": "info", "message": "Disconnected from Cortex."})

    def _reset_state(self):
        self.is_connected = False
        self.is_authorized = False
        self.is_session_active = False
        self.is_subscribed = False
        self.cortex_token = None
        self.session_id = None
        self.headset_id = None
        self.available_profiles = []
        self.active_profile = None
        self.battery_level = None
        self.signal_quality = None

    async def request(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 15.0) -> Any:
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

    async def _listener_loop(self):
        try:
            async for raw in self.ws:
                try:
                    data = json.loads(raw)
                except Exception:
                    continue

                try:
                    # 1. Handle Response to a Request ID
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
                        com_val = data.get("com")
                        action = "neutral"
                        power = 0.0

                        if isinstance(com_val, (list, tuple)):
                            if len(com_val) >= 1 and com_val[0] is not None:
                                action = str(com_val[0]).strip()
                            if len(com_val) >= 2 and com_val[1] is not None:
                                try:
                                    power = float(com_val[1])
                                except (ValueError, TypeError):
                                    power = 0.0
                        elif isinstance(com_val, dict):
                            action = str(com_val.get("action", "neutral")).strip()
                            try:
                                power = float(com_val.get("power", 0.0))
                            except (ValueError, TypeError):
                                power = 0.0
                        elif isinstance(com_val, str):
                            action = com_val.strip()
                            power = 1.0

                        self.emit("com", {
                            "action": action,
                            "power": power,
                            "time": data.get("time"),
                            "sid": data.get("sid"),
                        })

                    # 3. Band Power ('pow') or Raw EEG ('eeg')
                    if "pow" in data:
                        self.emit("pow", {
                            "data": data.get("pow"),
                            "time": data.get("time"),
                        })

                    # 4. System / Battery events ('sys' / 'dev')
                    if "sys" in data:
                        sys_data = data.get("sys")
                        if isinstance(sys_data, (list, tuple)) and len(sys_data) >= 2:
                            if sys_data[0] == "battery":
                                self.battery_level = int(sys_data[1])
                                self.emit("status_change", self.get_status())
                        self.emit("sys", sys_data)

                    if "dev" in data:
                        dev_data = data.get("dev")
                        self.emit("dev", dev_data)

                    if "warning" in data:
                        self.emit("log", {
                            "level": "warn",
                            "message": f"Cortex Warning: {json.dumps(data['warning'])}",
                        })

                except Exception as frame_err:
                    print(f"[Cortex frame error]: {frame_err}")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.emit("log", {"level": "error", "message": f"Cortex listener disconnected: {e}"})
        finally:
            self._reset_state()
            self.emit("status_change", {"state": "disconnected"})

    async def authenticate_and_subscribe(self):
        if not self.client_id or not self.client_secret:
            raise ValueError("Client ID and Client Secret are required.")

        self.emit("log", {"level": "info", "message": "Checking access rights with Cortex..."})

        # 1. requestAccess
        try:
            access_result = await self.request("requestAccess", {
                "clientId": self.client_id,
                "clientSecret": self.client_secret,
            })
            granted = access_result.get("accessGranted", False) if isinstance(access_result, dict) else False
            self.emit("log", {
                "level": "info",
                "message": f"Access status: {'Granted' if granted else 'Pending confirmation in Emotiv App'}",
            })
        except Exception as e:
            self.emit("log", {"level": "warn", "message": f"requestAccess notice: {e}"})

        # 2. authorize
        self.emit("log", {"level": "info", "message": "Authorizing with Cortex..."})
        auth_params = {
            "clientId": self.client_id,
            "clientSecret": self.client_secret,
            "debit": self.debit,
        }
        if self.license_key:
            auth_params["license"] = self.license_key

        auth_result = await self.request("authorize", auth_params)
        if not auth_result or "cortexToken" not in auth_result:
            raise RuntimeError("Authorization failed: No cortexToken returned.")

        self.cortex_token = auth_result["cortexToken"]
        self.is_authorized = True
        self.emit("log", {"level": "success", "message": "Cortex Authorization Successful!"})
        self.emit("status_change", {"state": "authorized"})

        # 3. queryHeadsets
        self.emit("log", {"level": "info", "message": "Querying connected Emotiv headsets..."})
        headsets = await self.request("queryHeadsets", {})
        self.headsets = headsets or []

        if not self.headsets:
            self.emit("log", {
                "level": "warn",
                "message": "Headset is in sleep/standby mode. Turn on your EPOC headset — connection will attach automatically.",
            })
            self.emit("status_change", self.get_status())
            asyncio.create_task(self._poll_for_headset())
            return

        connected_headset = next((h for h in self.headsets if h.get("status") == "connected"), self.headsets[0])
        self.headset_id = connected_headset.get("id")

        if connected_headset.get("status") != "connected":
            # Auto connect headset
            try:
                self.emit("log", {"level": "info", "message": f"Connecting headset {self.headset_id}..."})
                await self.request("controlDevice", {"command": "connect", "headset": self.headset_id})
            except Exception:
                pass

        self.emit("log", {
            "level": "success",
            "message": f"Found active headset: {self.headset_id} ({connected_headset.get('status')})",
        })

        # 4. createSession (or reuse open session from Emotiv Launcher)
        self.emit("log", {"level": "info", "message": f"Establishing session for headset {self.headset_id}..."})
        session_id = None

        # Check existing sessions in Emotiv Launcher first
        try:
            existing_sessions = await self.request("querySessions", {"cortexToken": self.cortex_token})
            if existing_sessions and isinstance(existing_sessions, list):
                for s in existing_sessions:
                    if s.get("headset", {}).get("id") == self.headset_id and s.get("status") in ("active", "open"):
                        session_id = s.get("id")
                        self.emit("log", {"level": "info", "message": f"Attached to existing Emotiv session: {session_id}"})
                        break
        except Exception:
            pass

        if not session_id:
            # Try open session first (no debit needed), then active
            for attempt_status in ["open", "active"]:
                try:
                    session_result = await self.request("createSession", {
                        "cortexToken": self.cortex_token,
                        "headset": self.headset_id,
                        "status": attempt_status,
                    })
                    if session_result and "id" in session_result:
                        session_id = session_result["id"]
                        self.emit("log", {"level": "info", "message": f"Created session ({attempt_status}): {session_id}"})
                        break
                except Exception as s_err:
                    continue

        if not session_id:
            # Final fallback: query sessions
            try:
                existing = await self.request("querySessions", {"cortexToken": self.cortex_token})
                if existing and isinstance(existing, list) and len(existing) > 0:
                    session_id = existing[0].get("id")
            except Exception:
                pass

        if not session_id:
            raise RuntimeError("Failed to obtain active session for headset.")

        self.session_id = session_id
        self.is_session_active = True
        self.emit("log", {"level": "success", "message": f"Active Session Ready: {self.session_id}"})
        self.emit("status_change", {"state": "session_active", "sessionId": self.session_id})

        # 5. Optional profile discovery (NO profile required to stream!)
        try:
            await self.query_and_load_profiles()
        except Exception:
            pass

        # 6. Subscribe to Mental Commands ('com') stream only
        self.emit("log", {"level": "info", "message": "Subscribing to Mental Commands ('com') stream..."})
        stream_candidates = [
            ["com", "sys"],
            ["com"],
        ]

        subscribed = False
        for streams in stream_candidates:
            try:
                await self.request("subscribe", {
                    "cortexToken": self.cortex_token,
                    "session": self.session_id,
                    "streams": streams,
                })
                self.subscribed_streams = streams
                subscribed = True
                break
            except Exception:
                continue

        if not subscribed:
            raise RuntimeError("Could not subscribe to Cortex streams.")

        self.is_subscribed = True
        self.emit("log", {
            "level": "success",
            "message": f"Live stream active! Subscribed streams: {', '.join(self.subscribed_streams)}",
        })
        self.emit("status_change", self.get_status())

    async def query_and_load_profiles(self) -> List[str]:
        if not self.cortex_token:
            return []
        try:
            profiles = await self.request("queryProfile", {"cortexToken": self.cortex_token})
            if profiles and isinstance(profiles, list):
                self.available_profiles = [p.get("name") for p in profiles if isinstance(p, dict) and p.get("name")]

            # Check if a profile is currently active in headset session
            if self.headset_id:
                try:
                    cur = await self.request("getCurrentProfile", {
                        "cortexToken": self.cortex_token,
                        "headset": self.headset_id,
                    })
                    if cur and isinstance(cur, dict) and cur.get("name"):
                        self.active_profile = cur.get("name")
                        self.emit("log", {
                            "level": "success",
                            "message": f"Active profile detected in headset: '{self.active_profile}' (Ready for mental commands)",
                        })
                except Exception:
                    pass

            return self.available_profiles
        except Exception:
            return []

    async def load_profile(self, profile_name: str) -> bool:
        if not self.cortex_token or not self.headset_id or not profile_name:
            return False
        try:
            if self.active_profile == profile_name:
                self.emit("log", {"level": "info", "message": f"Profile '{profile_name}' is already active."})
                return True

            self.emit("log", {"level": "info", "message": f"Loading profile '{profile_name}' into headset session..."})

            # Check current profile first
            try:
                cur = await self.request("getCurrentProfile", {
                    "cortexToken": self.cortex_token,
                    "headset": self.headset_id,
                })
                cur_name = cur.get("name") if isinstance(cur, dict) else None
                if cur_name and cur_name != profile_name:
                    try:
                        await self.request("setupProfile", {
                            "cortexToken": self.cortex_token,
                            "headset": self.headset_id,
                            "profile": cur_name,
                            "status": "unload",
                        })
                    except Exception:
                        pass
            except Exception:
                pass

            try:
                await self.request("setupProfile", {
                    "cortexToken": self.cortex_token,
                    "headset": self.headset_id,
                    "profile": profile_name,
                    "status": "load",
                })
                self.active_profile = profile_name
                self.emit("log", {"level": "success", "message": f"Profile '{profile_name}' loaded successfully!"})
                self.emit("status_change", self.get_status())
                return True
            except Exception as load_err:
                err_str = str(load_err)
                if "-32046" in err_str or "-32127" in err_str or "already loaded" in err_str.lower():
                    # Re-query current profile
                    try:
                        cur = await self.request("getCurrentProfile", {
                            "cortexToken": self.cortex_token,
                            "headset": self.headset_id,
                        })
                        if cur and isinstance(cur, dict) and cur.get("name"):
                            self.active_profile = cur.get("name")
                            self.emit("log", {
                                "level": "info",
                                "message": f"Profile '{self.active_profile}' is actively loaded via Emotiv App. To switch profiles, select '{profile_name}' in the Emotiv App.",
                            })
                            self.emit("status_change", self.get_status())
                            return (self.active_profile == profile_name)
                    except Exception:
                        pass
                raise load_err
        except Exception as e:
            self.emit("log", {"level": "error", "message": f"Failed to load profile '{profile_name}': {e}"})
            return False

    async def _poll_for_headset(self):
        """Continuously check for headset until it wakes up and connects."""
        retries = 0
        while self.is_ws_alive and self.is_authorized and not self.is_subscribed and retries < 60:
            await asyncio.sleep(4)
            retries += 1
            try:
                headsets = await self.request("queryHeadsets", {})
                if headsets:
                    self.headsets = headsets
                    self.emit("log", {"level": "success", "message": f"Headset detected! Attaching session..."})
                    await self.authenticate_and_subscribe()
                    break
            except Exception:
                pass
