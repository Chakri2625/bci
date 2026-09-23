"""Best-effort UART transport for canonical dashboard actions.

Serial I/O is isolated on a worker thread so dashboard request handlers and
the Emotiv/FSM pipeline never wait for a receiver response.
"""

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor


logger = logging.getLogger()


def _env_bool(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _decode_terminator(value):
    return value.encode("utf-8").decode("unicode_escape")


class UARTTransmitter:
    """Transmit canonical actions without making UART a dashboard dependency."""

    def __init__(
        self,
        enabled=True,
        port="COM3",
        baudrate=9600,
        timeout=1.0,
        ack_enabled=False,
        terminator="\n",
    ):
        self.enabled = bool(enabled)
        self.port = port
        self.baudrate = int(baudrate)
        self.timeout = float(timeout)
        self.ack_enabled = bool(ack_enabled)
        self.terminator = terminator
        self._serial = None
        self._serial_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="uart")

    @classmethod
    def from_env(cls):
        return cls(
            enabled=_env_bool("UART_ENABLED", True),
            port=os.environ.get("UART_PORT", "COM3"),
            baudrate=int(os.environ.get("UART_BAUDRATE", "9600")),
            timeout=float(os.environ.get("UART_TIMEOUT", "1.0")),
            ack_enabled=_env_bool("UART_ACK_ENABLED", False),
            terminator=_decode_terminator(os.environ.get("UART_TERMINATOR", "\\n")),
        )

    def connect(self):
        if not self.enabled:
            logger.info("[UART] Disabled")
            return False
        with self._serial_lock:
            if self._serial is not None and getattr(self._serial, "is_open", False):
                return True
            try:
                import serial

                logger.info("[UART] Connecting to %s @ %s", self.port, self.baudrate)
                self._serial = serial.Serial(
                    port=self.port,
                    baudrate=self.baudrate,
                    timeout=self.timeout,
                    write_timeout=self.timeout,
                )
                logger.info("[UART] Connected")
                return True
            except Exception as exc:
                self._serial = None
                logger.error("[UART ERROR] Unable to open %s: %s", self.port, exc)
                return False

    def disconnect(self):
        with self._serial_lock:
            serial_port = self._serial
            self._serial = None
            if serial_port is not None:
                try:
                    serial_port.close()
                except Exception as exc:
                    logger.error("[UART ERROR] Serial close failed: %s", exc)

    def is_connected(self):
        with self._serial_lock:
            return self._serial is not None and getattr(self._serial, "is_open", False)

    def _get_serial(self):
        if self.is_connected() or not self.connect():
            with self._serial_lock:
                return self._serial
        with self._serial_lock:
            return self._serial

    def _get_active_uart_transport(self):
        try:
            from core.plugin_manager.manager import get_plugin
            desktop_plugin = get_plugin("desktop")
            if desktop_plugin and getattr(desktop_plugin, "uart_transport", None):
                transport = desktop_plugin.uart_transport
                if not transport.running:
                    transport.start()
                if transport.is_connected():
                    return transport
        except Exception:
            pass
        return None

    def send_command(self, action):
        """Synchronously send one canonical action; intended for the worker/test utility."""
        if not self.enabled:
            return None
        action = str(action).strip()
        if not action:
            logger.error("[UART ERROR] Empty action was not transmitted")
            return None

        shared_transport = self._get_active_uart_transport()
        if shared_transport is not None:
            logger.info("[UART TX] Forwarding '%s' via shared Desktop UART Transport", action)
            res = shared_transport.send_command(action)
            return res.get("message") if isinstance(res, dict) else str(res)

        return self.send_raw(f"action cmd|{action}")

    def send_raw(self, command):
        """Synchronously send exact wire text, without adding a command prefix."""
        if not self.enabled:
            return None
        command = str(command).strip()
        if not command:
            logger.error("[UART ERROR] Empty command was not transmitted")
            return None

        payload = f"{command}{self.terminator}".encode("utf-8")
        display_payload = payload.decode("utf-8", errors="replace").encode("unicode_escape").decode("ascii")
        logger.info("[UART TX] %s", display_payload)

        serial_port = self._get_serial()
        if serial_port is None:
            logger.error("[UART] NOT SENT - %s unavailable", self.port)
            return None

        try:
            with self._serial_lock:
                serial_port.write(payload)
                serial_port.flush()
                if not self.ack_enabled:
                    return ""
                response = serial_port.read_until()
            if response:
                text = response.decode("utf-8", errors="replace").encode("unicode_escape").decode("ascii")
                logger.info("[UART RX] %s", text)
                return response
            logger.warning(
                "[UART] Command WAS transmitted to %s @ %d baud, but receiver sent no ACK within %.1fs "
                "- check receiver BAUD matches, wiring TX->RX / RX->TX / GND->GND, "
                "and that the receiver sends back an ACK line",
                self.port, self.baudrate, self.timeout,
            )
            return None
        except Exception as exc:
            logger.error("[UART ERROR] Serial transmission failed: %s", exc)
            self.disconnect()
            return None

    def send_action(self, action):
        """Queue an action and return immediately to the dashboard caller."""
        if not self.enabled:
            return None
        try:
            return self._executor.submit(self.send_command, action)
        except Exception as exc:
            logger.error("[UART ERROR] Could not queue command: %s", exc)
            return None

    def shutdown(self):
        self._executor.shutdown(wait=False, cancel_futures=True)
        self.disconnect()


uart_transmitter = UARTTransmitter.from_env()
