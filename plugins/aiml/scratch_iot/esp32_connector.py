import sys
import os
import time
import json
import asyncio
import threading
from typing import Dict, Any, Optional, Callable, List
import requests

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class ESP32Connector:
    def __init__(
        self,
        mode: str = "serial",
        esp32_ip: str = "192.168.1.100",
        esp32_port: int = 80,
        serial_port_path: str = "COM5",
        baud_rate: int = 115200,
    ):
        self.mode = mode or os.getenv("ESP32_MODE", "serial")
        self.esp32_ip = (esp32_ip or os.getenv("ESP32_IP", "192.168.1.100")).strip()
        self.esp32_port = int(esp32_port or os.getenv("ESP32_PORT", 80))
        self.serial_port_path = (serial_port_path or os.getenv("ESP32_SERIAL_PORT", "COM5")).strip()
        self.baud_rate = int(baud_rate or os.getenv("ESP32_BAUD_RATE", 115200))

        self.serial_conn = None
        self._serial_thread = None
        self._stop_serial = False

        self.is_connected = False
        self.last_latency: Optional[int] = None
        self.last_error: Optional[str] = None
        self.active_ws_client = None  # WebSocket object

        self.device_states: Dict[str, str] = {
            "light": "OFF",
            "fan": "OFF",
            "pump": "OFF",
        }

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
                    print(f"[ERROR in ESP32 listener '{event_name}']: {e}")

    @staticmethod
    def get_available_ports() -> List[Dict[str, str]]:
        """Scans and lists all system COM / Serial ports with hardware descriptions."""
        ports_list = []
        try:
            import serial.tools.list_ports
            for p in serial.tools.list_ports.comports():
                ports_list.append({
                    "port": p.device,
                    "description": p.description,
                    "hwid": p.hwid or "",
                    "isEsp32": "cp210" in (p.description or "").lower() or "ch340" in (p.description or "").lower() or "usb" in (p.description or "").lower()
                })
        except Exception as err:
            print(f"[COM Ports scan error]: {err}")
        return ports_list

    def update_config(self, config: Dict[str, Any]):
        old_mode = self.mode
        old_port = self.serial_port_path
        old_baud = self.baud_rate

        if "mode" in config:
            self.mode = str(config["mode"]).strip()
        if "esp32Ip" in config:
            self.esp32_ip = str(config["esp32Ip"]).strip()
        elif "esp32_ip" in config:
            self.esp32_ip = str(config["esp32_ip"]).strip()

        if "esp32Port" in config:
            self.esp32_port = int(config["esp32Port"])
        elif "esp32_port" in config:
            self.esp32_port = int(config["esp32_port"])

        if "serialPortPath" in config:
            self.serial_port_path = str(config["serialPortPath"]).strip()
        elif "serial_port_path" in config:
            self.serial_port_path = str(config["serial_port_path"]).strip()

        if "baudRate" in config:
            self.baud_rate = int(config["baudRate"])
        elif "baud_rate" in config:
            self.baud_rate = int(config["baud_rate"])

        # Auto-reconnect if serial settings changed while in serial mode
        if self.mode == "serial":
            if old_mode != "serial" or old_port != self.serial_port_path or old_baud != self.baud_rate or not self.is_connected:
                self.init_serial()
        elif old_mode == "serial" and self.mode != "serial":
            self.disconnect_serial()

        self.emit("config_updated", self.get_config())
        self.emit("status_change", self.get_config())

    def get_config(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "esp32Ip": self.esp32_ip,
            "esp32Port": self.esp32_port,
            "serialPortPath": self.serial_port_path,
            "baudRate": self.baud_rate,
            "isConnected": self.is_connected,
            "lastLatency": self.last_latency,
            "lastError": self.last_error,
            "availablePorts": self.get_available_ports(),
        }

    # -------------------------------------------------------------------------
    # WebSocket Direct Client Handling
    # -------------------------------------------------------------------------
    def register_websocket_client(self, ws):
        self.active_ws_client = ws
        self.is_connected = True
        self.last_error = None
        self.mode = "wifi_ws"
        self.emit("log", {"level": "success", "message": "ESP32 connected directly via WebSocket!"})
        self.emit("status_change", self.get_config())

    def unregister_websocket_client(self):
        self.active_ws_client = None
        self.is_connected = False
        self.emit("log", {"level": "warn", "message": "ESP32 WebSocket connection closed."})
        self.emit("status_change", self.get_config())

    def handle_ws_message(self, text: str):
        try:
            data = json.loads(text)
            if data.get("type") == "status_sync" and "states" in data:
                self.device_states.update(data["states"])
                self.emit("states_sync", self.device_states)
            elif "states" in data:
                self.device_states.update(data["states"])
                self.emit("states_sync", self.device_states)
        except Exception:
            self.emit("log", {"level": "info", "message": f"ESP32 WS: {text}"})

    # -------------------------------------------------------------------------
    # Serial UART (PySerial)
    # -------------------------------------------------------------------------
    def init_serial(self) -> bool:
        try:
            import serial
        except ImportError:
            self.last_error = "pyserial not installed"
            self.emit("log", {
                "level": "warn",
                "message": "pyserial not installed. Run `pip install pyserial` for USB COM port mode.",
            })
            return False

        try:
            self.disconnect_serial()
            time.sleep(0.15)  # Allow Windows kernel to release COM port handle

            self.serial_conn = serial.Serial(self.serial_port_path, self.baud_rate, timeout=1)
            self.is_connected = True
            self._stop_serial = False
            self.last_error = None
            self.emit("log", {
                "level": "success",
                "message": f"Opened ESP32 Serial Port {self.serial_port_path} @ {self.baud_rate} baud",
            })
            self.emit("status_change", self.get_config())

            self._serial_thread = threading.Thread(target=self._serial_reader_loop, daemon=True)
            self._serial_thread.start()

            # Request initial status
            try:
                self.serial_conn.write(b"STATUS\n")
            except Exception:
                pass

            return True
        except PermissionError:
            self.is_connected = False
            self.last_error = f"Port {self.serial_port_path} is busy (Access Denied). Close Arduino Serial Monitor / PuTTY."
            self.emit("log", {
                "level": "error",
                "message": f"Serial port {self.serial_port_path} is locked by another app (e.g. Arduino Serial Monitor). Please close it and click Connect.",
            })
            self.emit("status_change", self.get_config())
            return False
        except Exception as err:
            self.is_connected = False
            self.last_error = str(err)
            self.emit("log", {"level": "error", "message": f"Failed to open Serial Port {self.serial_port_path}: {err}"})
            self.emit("status_change", self.get_config())
            return False

    def disconnect_serial(self):
        self._stop_serial = True
        if self.serial_conn:
            try:
                if self.serial_conn.is_open:
                    self.serial_conn.close()
            except Exception:
                pass
            self.serial_conn = None
        self.is_connected = False
        self.emit("status_change", self.get_config())

    def _serial_reader_loop(self):
        while not self._stop_serial and self.serial_conn and self.serial_conn.is_open:
            try:
                line = self.serial_conn.readline().decode("utf-8", errors="replace").strip()
                if line:
                    self.emit("log", {"level": "info", "message": f"[ESP32 Serial] {line}"})
                    # Parse JSON ACK or status
                    if line.startswith("{") and line.endswith("}"):
                        try:
                            json_data = json.loads(line)
                            if "states" in json_data:
                                self.device_states.update(json_data["states"])
                                self.emit("states_sync", self.device_states)
                        except Exception:
                            pass
            except Exception:
                break
        self.is_connected = False
        self.emit("status_change", self.get_config())

    # -------------------------------------------------------------------------
    # Command Dispatch
    # -------------------------------------------------------------------------
    async def send_command(self, device: str, state: str) -> Dict[str, Any]:
        device = (device or "").lower().strip()
        state = (state or "").upper().strip()
        self.device_states[device] = state

        command_payload = {
            "device": device,
            "state": state,
            "timestamp": int(time.time() * 1000),
        }

        self.emit("log", {
            "level": "info",
            "message": f"Dispatching to ESP32: [{device.upper()} -> {state}] via Mode: {self.mode.upper()}",
        })

        # 1. Direct WebSocket client
        if self.active_ws_client:
            try:
                await self.active_ws_client.send_text(json.dumps({"type": "control", **command_payload}))
                return {"success": True, "mode": "websocket"}
            except Exception as err:
                self.emit("log", {"level": "error", "message": f"WS Dispatch error: {err}"})

        # 2. Serial Mode
        if self.mode == "serial":
            if not self.serial_conn or not self.serial_conn.is_open:
                # Attempt auto-connect
                self.init_serial()

            if self.serial_conn and self.serial_conn.is_open:
                try:
                    cmd = f"{device.upper()}:{state}\n"
                    self.serial_conn.write(cmd.encode("utf-8"))
                    return {"success": True, "mode": "serial", "command": cmd.strip()}
                except Exception as err:
                    self.emit("log", {"level": "error", "message": f"Serial write error: {err}"})
                    return {"success": False, "error": str(err)}
            else:
                return {"success": False, "error": self.last_error or "Serial port not connected"}

        # 3. WiFi HTTP REST Mode
        if self.mode in ("wifi", "http"):
            return await self._send_http_request(device, state)

        # Virtual / Simulation Fallback
        return {"success": True, "mode": "virtual"}

    async def _send_http_request(self, device: str, state: str) -> Dict[str, Any]:
        url = f"http://{self.esp32_ip}:{self.esp32_port}/api/control?device={device}&state={state}"
        start_time = time.time()
        loop = asyncio.get_running_loop()

        def _do_get():
            try:
                return requests.get(url, timeout=2.5)
            except Exception as e:
                return e

        res = await loop.run_in_executor(None, _do_get)
        latency_ms = int((time.time() - start_time) * 1000)

        if isinstance(res, requests.Response):
            self.last_latency = latency_ms
            self.is_connected = True
            self.last_error = None
            self.emit("log", {
                "level": "success",
                "message": f"ESP32 HTTP Response ({latency_ms}ms): {res.text.strip() or res.status_code}",
            })
            self.emit("status_change", self.get_config())
            return {"success": True, "latency": latency_ms, "response": res.text}
        else:
            self.last_latency = None
            self.is_connected = False
            self.last_error = str(res)
            self.emit("log", {
                "level": "warn",
                "message": f"ESP32 HTTP Request failed ({self.esp32_ip}:{self.esp32_port}): {res}",
            })
            self.emit("status_change", self.get_config())
            return {"success": False, "error": str(res)}

    async def ping(self) -> Dict[str, Any]:
        """Pings the ESP32 hardware according to the current active communication mode."""
        start_time = time.time()

        # Serial Mode Ping
        if self.mode == "serial":
            if not self.serial_conn or not self.serial_conn.is_open:
                if not self.init_serial():
                    return {"success": False, "error": self.last_error or "Serial port not connected"}

            try:
                self.serial_conn.write(b"STATUS\n")
                latency_ms = int((time.time() - start_time) * 1000)
                self.is_connected = True
                self.last_latency = latency_ms
                self.last_error = None
                self.emit("log", {"level": "success", "message": f"ESP32 Serial Ping OK ({self.serial_port_path} @ {self.baud_rate})"})
                self.emit("status_change", self.get_config())
                return {"success": True, "mode": "serial", "latency": latency_ms, "port": self.serial_port_path}
            except Exception as e:
                self.is_connected = False
                self.last_error = str(e)
                self.emit("status_change", self.get_config())
                return {"success": False, "error": str(e)}

        # WebSocket Mode Ping
        if self.mode == "wifi_ws":
            if self.active_ws_client:
                try:
                    await self.active_ws_client.send_text(json.dumps({"type": "ping"}))
                    return {"success": True, "mode": "websocket", "connected": True}
                except Exception as e:
                    return {"success": False, "error": str(e)}
            return {"success": False, "error": "No ESP32 WebSocket client connected"}

        # HTTP REST Ping
        url = f"http://{self.esp32_ip}:{self.esp32_port}/api/status"
        loop = asyncio.get_running_loop()

        def _do_ping():
            try:
                return requests.get(url, timeout=2.0)
            except Exception as e:
                return e

        res = await loop.run_in_executor(None, _do_ping)
        latency_ms = int((time.time() - start_time) * 1000)

        if isinstance(res, requests.Response):
            self.is_connected = True
            self.last_latency = latency_ms
            self.last_error = None
            self.emit("log", {"level": "success", "message": f"ESP32 HTTP Ping OK ({latency_ms}ms)"})
            self.emit("status_change", self.get_config())
            return {"success": True, "latency": latency_ms, "body": res.text}
        else:
            self.is_connected = False
            self.last_latency = None
            self.last_error = str(res)
            self.emit("log", {"level": "warn", "message": f"ESP32 HTTP Ping Failed: {res}"})
            self.emit("status_change", self.get_config())
            return {"success": False, "error": str(res)}
