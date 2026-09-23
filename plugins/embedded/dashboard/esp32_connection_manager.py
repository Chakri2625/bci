"""SynaptiMesh ESP32-C6 transport layer.

Normal robot commands use exactly one selected transport: SERIAL, MQTT, or HTTP.
Firmware flashing is a maintenance operation and is intentionally separate from
normal movement execution.
"""
import asyncio, os, subprocess, sys, tempfile, time
from pathlib import Path
from typing import Any, Dict
try:
    from .esp32_connector import ESP32Connector
except (ImportError, ValueError):
    from esp32_connector import ESP32Connector

class SynaptiMeshESP32Connector(ESP32Connector):
    MODES = {"serial", "mqtt", "wifi", "http"}
    CAR_COMMANDS = {"FORWARD","BACKWARD","LEFT","RIGHT","LEFT360","RIGHT360","STOP","PING"}

    def get_config(self):
        cfg = super().get_config()
        cfg["transportLabel"] = {"serial":"USB Serial / Monitor","mqtt":"MQTT","wifi":"Wi-Fi / HTTP","http":"Wi-Fi / HTTP"}.get(self.mode, self.mode.upper())
        cfg["firmwareFlashSupported"] = sys.platform in ("win32", "linux", "darwin")
        return cfg

    async def send_car_command(self, command: str) -> Dict[str, Any]:
        command = str(command or "").strip().upper()
        if command.startswith("LIFTCAR"):
            command = command[7:]
        if command not in self.CAR_COMMANDS:
            return {"success": False, "error": f"Invalid car command: {command}"}
        wire = f"LIFTCAR{command}"
        start = time.time()
        tx_started = time.perf_counter()
        self.emit("esp32_tx", {"command": wire, "mode": self.mode, "startedAt": int(time.time()*1000)})
        self.emit("log", {"level":"info", "message":f"CAR TX [{wire}] via {self.mode.upper()}"})

        if self.mode == "serial":
            if not self.serial_conn or not self.serial_conn.is_open:
                if not self.init_serial():
                    return {"success":False,"error":self.last_error or "Serial port not connected"}
            try:
                self.serial_conn.write((wire + "\n").encode("utf-8"))
                self.serial_conn.flush()
                latency=int((time.time()-start)*1000)
                self.is_connected=True; self.last_error=None
                self.emit("esp32_tx_result", {"success":True,"mode":"serial","command":wire,"port":self.serial_port_path,"latency":latency})
                return {"success":True,"mode":"serial","command":wire,"port":self.serial_port_path,"latency":latency}
            except Exception as e:
                self.last_error=str(e); self.is_connected=False
                return {"success":False,"mode":"serial","error":str(e)}

        if self.mode in ("wifi","http"):
            return await self._send_car_http_command(wire)

        if self.mode == "mqtt":
            # Create the MQTT client only if none exists. If an existing client
            # is reconnecting, never replace it with another client.
            if not self.mqtt_client:
                self.init_mqtt()
            if not self.mqtt_client or not self.mqtt_connected:
                return {"success":False,"mode":"mqtt","error":self.last_error or "MQTT broker not connected"}
            try:
                # The firmware listens on /control. QoS 1 gives us a broker-level
                # delivery acknowledgement; the ESP32 ACK is tracked separately.
                pending=None
                if self._async_loop and self._async_loop.is_running():
                    import asyncio as _asyncio
                    pending={"command":wire, "sent_at":time.time(), "event":_asyncio.Event()}
                    with self._ack_lock:
                        self._pending_acks.append(pending)

                info=self.mqtt_client.publish(self.mqtt_topic_action, wire, qos=1)
                latency=int((time.time()-start)*1000)
                ok=bool(getattr(info,'rc',0)==0)
                result={"success":ok,"mode":"mqtt","topic":self.mqtt_topic_action,"command":wire,"latency":latency,
                        "brokerAccepted":ok,"ackPending":ok}
                if ok:
                    self.last_error=None
                    if pending is not None and self._async_loop and self._async_loop.is_running():
                        self._async_loop.call_soon_threadsafe(
                            self._async_loop.create_task, self._watch_ack(pending)
                        )
                    self.emit("log", {"level":"info", "message":f"MQTT PUBLISH ACCEPTED [{self.mqtt_topic_action}] {wire} (QoS 1) — waiting for ESP32 ACK."})
                else:
                    if pending is not None:
                        with self._ack_lock:
                            if pending in self._pending_acks:
                                self._pending_acks.remove(pending)
                    self.last_error=f"MQTT publish rejected (rc={getattr(info,'rc',None)})"
                    result["error"]=self.last_error
                self.is_connected=ok
                self.emit("esp32_tx_result", {**result})
                return result
            except Exception as e:
                self.last_error=str(e); return {"success":False,"mode":"mqtt","error":str(e)}

        return {"success":False,"error":f"Unsupported ESP32 transport: {self.mode}"}

    async def _send_car_http_command(self, wire: str) -> Dict[str, Any]:
        import requests
        url=f"http://{self.esp32_ip}:{self.esp32_port}/api/car/command"
        loop=asyncio.get_running_loop(); start=time.time()
        def req():
            try: return requests.get(url,params={"command":wire},timeout=2.5)
            except Exception as e: return e
        res=await loop.run_in_executor(None,req); latency=int((time.time()-start)*1000)
        if isinstance(res, requests.Response):
            ok=res.ok
            self.is_connected=ok; self.last_latency=latency; self.last_error=None if ok else res.text
            self.emit("esp32_tx_result", {"success":ok,"mode":"http","url":url,"command":wire,"latency":latency,"response":res.text})
            return {"success":ok,"mode":"http","url":url,"command":wire,"latency":latency,"response":res.text}
        self.is_connected=False; self.last_latency=None; self.last_error=str(res)
        return {"success":False,"mode":"http","error":str(res)}

    async def test_transport(self) -> Dict[str, Any]:
        start=time.time()
        if self.mode == "serial":
            if not self.serial_conn or not self.serial_conn.is_open:
                if not self.init_serial(): return {"success":False,"mode":"serial","error":self.last_error or "Serial port unavailable"}
            try:
                self.serial_conn.write(b"STATUS\n"); self.serial_conn.flush()
                return {"success":True,"mode":"serial","port":self.serial_port_path,"latency":int((time.time()-start)*1000)}
            except Exception as e: return {"success":False,"mode":"serial","error":str(e)}
        if self.mode in ("wifi","http"):
            return await self.ping()
        if self.mode == "mqtt":
            # Safe end-to-end diagnostic: PING never drives the motors. The
            # firmware answers with CAR PING ACK, proving command RX + ACK TX.
            return await self.send_car_command("PING")
        return {"success":False,"error":"Unsupported transport"}

    @staticmethod
    def flash_firmware(port: str, firmware_path: str, offset: str = "0x10000", baud: int = 460800) -> Dict[str, Any]:
        """Flash an already-compiled ESP32-C6 binary over USB serial using esptool."""
        path=Path(firmware_path)
        if not path.exists() or path.suffix.lower() != ".bin":
            return {"success":False,"error":"A compiled .bin firmware file is required."}
        if not port: return {"success":False,"error":"Serial COM port is required for flashing."}
        try:
            # A merged image contains the bootloader, partition table, boot_app0,
            # and application at their correct offsets.  It must be flashed at
            # 0x0 as one complete image.  Application-only .bin files continue
            # to use the caller-supplied application offset (normally 0x10000).
            is_merged = path.name.lower().endswith(".merged.bin")
            flash_offset = "0x0" if is_merged else offset
            cmd=[sys.executable,"-m","esptool","--chip","esp32c6","--port",port,"--baud",str(int(baud)),"write-flash",flash_offset,str(path)]
            proc=subprocess.run(cmd,capture_output=True,text=True,timeout=180)
            out=(proc.stdout or "") + ("\n"+proc.stderr if proc.stderr else "")
            return {"success":proc.returncode==0,"port":port,"firmware":path.name,"offset":flash_offset,"image_type":"merged" if is_merged else "application","output":out[-12000:],"returncode":proc.returncode}
        except FileNotFoundError:
            return {"success":False,"error":"esptool is not installed. Run: python -m pip install esptool"}
        except subprocess.TimeoutExpired:
            return {"success":False,"error":"Firmware flashing timed out after 180 seconds."}
        except Exception as e:
            return {"success":False,"error":str(e)}
