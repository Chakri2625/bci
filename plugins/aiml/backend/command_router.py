"""Unified command router.

Single-target dispatch (``mobile`` | ``desktop``) is wired now and reuses each
dashboard's existing control path:

    {"command": "NEXT_TRACK", "target": "mobile"}   -> MQTT publish
    {"command": "NEXT_TRACK", "target": "desktop"}  -> Selenium execute

Broadcast-to-both is intentionally not implemented yet.
"""

from .device_manager import device_manager


class CommandRouter:
    def route(self, command, target="mobile"):
        if target not in ("mobile", "desktop"):
            raise ValueError(f"Unknown target: {target} (expected 'mobile' or 'desktop')")

        if target == "mobile":
            mqtt = device_manager.get_mobile().get("mqtt_service")
            if mqtt is None:
                return {
                    "command": command,
                    "target": target,
                    "dispatched": False,
                    "reason": "mobile backend not registered",
                }
            import time

            mqtt.publish_command(command, 0.99, time.time())
            return {"command": command, "target": target, "dispatched": True, "channel": "mqtt"}

        try:
            from uart_transmitter import uart_transmitter
        except ImportError:
            try:
                from plugins.aiml.uart_transmitter import uart_transmitter
            except ImportError:
                uart_transmitter = None

        if uart_transmitter and uart_transmitter.enabled:
            # Forward action to secondary device via UART (no local execution on Host PC)
            uart_transmitter.send_action(command)
            return {
                "command": command,
                "target": target,
                "dispatched": True,
                "channel": "uart",
                "result": f"Forwarded to remote device via UART: {command}",
            }

        controller = device_manager.get_desktop().get("controller")
        if controller is None:
            return {
                "command": command,
                "target": target,
                "dispatched": False,
                "reason": "desktop backend not registered",
            }
        result = controller.execute_action(command)
        return {"command": command, "target": target, "dispatched": True, "result": result}

    def route_multi(self, command, targets=("mobile", "desktop")):
        """Future-proof multi-target dispatch. ``'both'`` is not supported yet."""
        if targets == "both":
            raise NotImplementedError(
                "Broadcast-to-both is not implemented yet; use ['mobile'] or ['desktop']."
            )
        return [self.route(command, target=t) for t in targets]


command_router = CommandRouter()