try:
    import serial
    import serial.tools.list_ports
except ImportError:
    serial = None

import time
import json
import os
import logging
import threading

logger = logging.getLogger("uart_transport")

class UARTTransport:
    def __init__(
        self,
        port="COM3",
        baudrate=9600,
        timeout=0.1,
        ack_timeout=5,
        max_retries=3,
        retry_delay=1
    ):
        # Load from existing config if available to follow project patterns
        self.config = {
            "enabled": True,
            "port": port,
            "baudrate": baudrate,
            "timeout": timeout,
            "ack_timeout": ack_timeout,
            "max_retries": max_retries,
            "retry_delay": retry_delay
        }
        
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    cfg = json.load(f)
                    if "uart" in cfg:
                        self.config.update(cfg["uart"])
            except Exception as e:
                logger.error(f"Failed to load UART config: {e}")

        # Update properties from config
        self.port = self.config["port"]
        self.baudrate = self.config["baudrate"]
        self.timeout = self.config["timeout"]
        self.ack_timeout = self.config.get("ack_timeout", ack_timeout)
        self.max_retries = self.config.get("retry_attempts", self.config.get("max_retries", max_retries))
        self.retry_delay = self.config.get("retry_delay", retry_delay)

        self.serial_conn = None
        self.connected = False
        self.running = False
        
        self._write_lock = threading.Lock()
        
        self._ack_event = threading.Event()
        self._ack_result = None
        self._expected_ack_cmd = None
        
        self._pong_event = threading.Event()
        self._read_thread = None

    def connect(self):
        if not self.config.get("enabled", True):
            return False
            
        if not serial:
            logger.warning("pyserial package not installed, UART transport disabled")
            return False
            
        if self.serial_conn and self.serial_conn.is_open:
            return True

        if self.config.get("simulate", False):
            self.connected = True
            logger.info("[UART] Simulation mode active")
            return True
            
        # Ports to try: configured port first, then any detected COM ports
        ports_to_try = [self.port] if self.port and self.port.upper() != "AUTO" else []
        if self.config.get("auto_detect_port", True):
            try:
                import serial.tools.list_ports
                available_ports = [p.device for p in serial.tools.list_ports.comports()]
                for p in available_ports:
                    if p not in ports_to_try:
                        ports_to_try.append(p)
            except Exception:
                pass

        if not ports_to_try:
            ports_to_try = ["COM3"]

        for port_candidate in ports_to_try:
            try:
                logger.info(f"[DEBUG] UART port: {port_candidate}")
                logger.info(f"[DEBUG] Opening UART: {port_candidate} at {self.baudrate}")
                logger.info(f"[UART] Runtime port = {port_candidate}")
                logger.info(f"[UART] Runtime baudrate = {self.baudrate}")
                self.serial_conn = serial.Serial(
                    port=port_candidate,
                    baudrate=self.baudrate,
                    timeout=self.timeout,
                    write_timeout=self.timeout
                )
                self.port = port_candidate
                self.connected = True
                logger.info(f"[DEBUG] UART connected: {self.port}")
                logger.info(f"UART connected on {self.port}")
                return True
            except (serial.SerialException, OSError, Exception) as e:
                logger.warning(f"UART connection on {port_candidate} failed: {e}")

        self.connected = False
        logger.error(f"UART connection failure: could not open any port in {ports_to_try}")
        return False

    def start(self):
        if not self.connect():
            return False
            
        self.running = True
        self._read_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._read_thread.start()
        return True

    def send_command(self, command):

            
        if not self.is_connected():
            return {
                "success": False,
                "status": "FAILED",
                "message": "UART disconnected"
            }
            
        with self._write_lock:
            for attempt in range(1, self.max_retries + 1):
                self._expected_ack_cmd = command
                self._ack_result = None
                self._ack_event.clear()
                
                try:
                    msg = f"CMD|{command}\n".encode('utf-8')
                    logger.info(f"[UART TX] CMD|{command}")
                    logger.info(f"[UART] Sending through {self.port}")
                    self.serial_conn.write(msg)
                    self.serial_conn.flush()
                    logger.info(f"UART SEND: CMD|{command} (Attempt {attempt})")
                except serial.SerialException as e:
                    logger.error(f"UART write failure: {e}")
                    self.connected = False
                    return {"success": False, "status": "FAILED", "message": "UART write failure"}
                except Exception as e:
                    logger.error(f"UART unexpected write error: {e}")
                    return {"success": False, "status": "FAILED", "message": "UART write error"}
                    
                logger.info(f"[DEBUG] Waiting for ACK: {command}")
                result = self._wait_for_ack()
                if result:
                    return result
                    
                logger.warning(f"ACK timeout for {command} on attempt {attempt}")
                
                if attempt < self.max_retries:
                    logger.info(f"UART retry: {command}")
                    time.sleep(self.retry_delay)
                    
            self._expected_ack_cmd = None
            return {
                "success": False,
                "status": "TIMEOUT",
                "message": "No ACK received after 3 attempts"
            }

    def _wait_for_ack(self):
        if self._ack_event.wait(self.ack_timeout):
            res = self._ack_result
            self._expected_ack_cmd = None
            self._ack_result = None
            return res
        return None

    def _read_loop(self):
        while self.running:
            if not self.is_connected():
                time.sleep(0.1)
                continue
                
            try:
                if self.serial_conn.in_waiting > 0:
                    line = self.serial_conn.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        self._handle_message(line)
            except serial.SerialException as e:
                logger.error(f"UART read failure/disconnected: {e}")
                self.connected = False
            except Exception as e:
                logger.error(f"UART unexpected read error: {e}")
            time.sleep(0.01)

    def _handle_message(self, message):
        logger.info(f"UART RECEIVE: {message}")
        if message == "PONG":
            logger.info(f"[UART RX] PONG")
            self._pong_event.set()
            return
            
        if message.startswith("ACK|"):
            logger.info(f"[UART RX] {message}")
            parts = message.split("|")
            if len(parts) >= 3:
                command = parts[1]
                status = parts[2]
                msg = parts[3] if len(parts) > 3 else ""
                
                import re
                def _norm(s):
                    return re.sub(r'[^a-zA-Z0-9]+', '_', str(s).strip()).strip('_').upper()

                if self._expected_ack_cmd and _norm(self._expected_ack_cmd) == _norm(command):
                    self._ack_result = {
                        "success": status == "SUCCESS",
                        "command": command,
                        "status": status,
                        "message": msg
                    }
                    logger.info(f"ACK received for {command}: {status}")
                    self._ack_event.set()
                else:
                    logger.warning(f"Received unexpected ACK for {command} (expected {self._expected_ack_cmd})")

    def ping(self, timeout=None):
        if not self.is_connected():
            return False
            
        wait_timeout = timeout if timeout is not None else min(float(self.ack_timeout), 2.0)
        with self._write_lock:
            self._pong_event.clear()
            try:
                logger.info(f"[UART TX] PING")
                self.serial_conn.write(b"PING\n")
                self.serial_conn.flush()
                logger.info("UART SEND: PING")
            except Exception as e:
                logger.error(f"UART write failure on ping: {e}")
                self.connected = False
                return False
                
        if self._pong_event.wait(wait_timeout):
            return True
        return False

    def is_connected(self):
        if self.serial_conn and self.serial_conn.is_open:
            return self.connected
        return False

    def disconnect(self):
        self.running = False
        if self._read_thread and self._read_thread.is_alive():
            self._read_thread.join(timeout=1.0)
            
        if self.serial_conn and self.serial_conn.is_open:
            try:
                self.serial_conn.close()
            except Exception:
                pass
        self.connected = False
        logger.info("UART disconnected")

