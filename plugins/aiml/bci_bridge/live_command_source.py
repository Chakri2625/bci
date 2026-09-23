import threading
import asyncio
import logging
from typing import Any, Dict

logger = logging.getLogger("LiveCommandSource")

class LiveCommandSource:
    def __init__(self, bridge, fsm_controller, confidence_threshold: float = 0.60):
        self.bridge = bridge
        self.fsm = fsm_controller
        self.confidence_threshold = confidence_threshold
        self.is_running = False
        self._thread = None

        # Register the 'com' event listener
        self.bridge.on("com", self._on_com_event)

    def _on_com_event(self, data: Dict[str, Any]):
        action = data.get("action", "neutral").lower()
        power = float(data.get("power", 0.0))

        if action == "neutral":
            return
            
        if action not in ["push", "pull", "left", "right"]:
            logger.info(f"[LIVE SOURCE] Unmapped action ignored: {action}")
            return

        if power >= self.confidence_threshold:
            logger.debug(f"[LIVE SOURCE] Forwarding {action} (power: {power:.2f}) to FSM")
            self.fsm.process_command(action)
        else:
            logger.debug(f"[LIVE SOURCE] Command {action} ignored due to low confidence ({power:.2f} < {self.confidence_threshold})")

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("[LIVE SOURCE] Live Emotiv Cortex source started.")

    def stop(self):
        self.is_running = False
        logger.info("[LIVE SOURCE] Live Emotiv Cortex source stopping...")
        if self.bridge.is_connected:
            # We would normally want to disconnect here, but asyncio operations
            # need to run in the loop. The thread will eventually die if daemon.
            pass

    def _run_loop(self):
        # Create a new event loop for this thread
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        try:
            # Run the bridge connection task
            self.loop.run_until_complete(self.bridge.connect())
            
            # Keep the loop alive to process events
            # We run forever, but since it's a daemon thread, it will close when app stops.
            # We can also periodically check self.is_running
            async def keep_alive():
                while self.is_running:
                    await asyncio.sleep(1)
                
                # Cleanup
                if self.bridge.is_connected:
                    await self.bridge.disconnect()
            
            self.loop.run_until_complete(keep_alive())
        except Exception as e:
            logger.error(f"[LIVE SOURCE] Cortex Bridge error: {e}")
        finally:
            self.loop.close()
