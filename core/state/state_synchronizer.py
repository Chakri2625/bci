"""Cross-domain state synchronization.

This module mirrors domain-owned state into the existing central StateManager.
It does not replace or modify the StateManager's existing state fields.
"""

import asyncio
import inspect
from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, Optional

from core.events.event_bus import event_bus as default_event_bus
from core.state.state_manager import state_manager as default_state_manager


class CrossDomainStateSynchronizer:
    """Merge independent domain snapshots into one session-scoped view."""

    def __init__(self, state_manager, event_bus=None):
        self.state_manager = state_manager
        self.event_bus = event_bus
        self.lock = Lock()
        self.version = 0

    def sync_domain(
        self,
        session_id: str,
        domain: str,
        domain_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Synchronize one domain snapshot and return the combined session state."""
        with self.lock:
            state = self.state_manager.get_state(session_id)
            if state is None:
                state = {"session_id": session_id, "domains": {}, "version": 0}

            state_updates = {
                "session_id": session_id,
                "domains": deepcopy(state.get("domains", {})),
                "version": self.version + 1,
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
            state_updates["domains"][domain] = deepcopy(domain_state)
            self.version = state_updates["version"]

            self.state_manager.update_state(session_id, state_updates)
            synchronized_state = deepcopy(self.state_manager.get_state(session_id))

        self._publish_sync_event(session_id, domain, self.version)
        self._broadcast_state_change(session_id, domain, synchronized_state)
        return synchronized_state

    def get_combined_state(self, session_id: str) -> Dict[str, Any]:
        """Return a snapshot of the synchronized state for a session."""
        return deepcopy(self.state_manager.get_state(session_id))

    def _publish_sync_event(self, session_id: str, domain: str, version: int) -> None:
        if self.event_bus is None:
            return

        result = self.event_bus.publish(
            "state.synced",
            {
                "session_id": session_id,
                "domain": domain,
                "version": version,
            },
        )
        if not inspect.isawaitable(result):
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(result)
        else:
            loop.create_task(result)

    def _broadcast_state_change(
        self,
        session_id: str,
        domain: str,
        synchronized_state: Dict[str, Any],
    ) -> None:
        """Asynchronously dispatch state mutation to connected WebSocket clients."""
        try:
            from core.communication.websocket_server import websocket_server
            envelope = websocket_server.create_envelope(
                msg_type="STATE_UPDATE",
                source_domain=domain,
                session_id=session_id,
                payload={
                    "session_id": session_id,
                    "domain": domain,
                    "version": self.version,
                    "state": synchronized_state,
                },
            )
            websocket_server.broadcast_envelope_sync(envelope)
        except Exception:
            # Broadcast failures must never crash or block core state synchronization
            pass


cross_domain_state_synchronizer = CrossDomainStateSynchronizer(
    default_state_manager,
    default_event_bus,
)

