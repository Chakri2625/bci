"""
EventBus for SynaptiMesh.
Provides publish-subscribe messaging across components with automatic Event History mirroring.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List

logger = logging.getLogger("event_bus")


class EventBus:
    def __init__(self):
        self.subscribers: Dict[str, List[Callable]] = {}
        self.global_subscribers: List[Callable] = []

    def subscribe(self, event_type: str, callback: Callable):
        """Subscribe to a specific event type, or '*' for all events."""
        if event_type == "*":
            if callback not in self.global_subscribers:
                self.global_subscribers.append(callback)
            return

        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        if callback not in self.subscribers[event_type]:
            self.subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: str, callback: Callable):
        """Unsubscribe from a specific event type or wildcard."""
        if event_type == "*":
            if callback in self.global_subscribers:
                self.global_subscribers.remove(callback)
            return

        if event_type in self.subscribers and callback in self.subscribers[event_type]:
            self.subscribers[event_type].remove(callback)

    async def publish(self, event_type: str, payload: Any):
        """Publish an event to all registered and global subscribers with isolated exception handling."""
        # 1. Mirror into event_history_manager if payload is suitable
        try:
            from core.managers.event_history import event_history_manager
            cmd = None
            domain = None
            req_id = None
            status_val = "SUCCESS"
            meta = {}
            dur = None

            if isinstance(payload, dict):
                cmd = payload.get("command") or payload.get("action")
                domain = payload.get("domain")
                req_id = payload.get("request_id") or payload.get("command_id")
                status_val = payload.get("status", "SUCCESS")
                dur = payload.get("execution_duration") or payload.get("duration")
                meta = payload
            else:
                cmd = str(payload)

            event_history_manager.store_event(
                event_type=event_type,
                command=cmd,
                domain=domain,
                status=status_val,
                request_id=req_id,
                execution_duration=dur,
                metadata=meta,
            )
        except Exception as e:
            logger.debug(f"Event history auto-mirror notice: {e}")

        # 2. Dispatch to specific subscribers
        if event_type in self.subscribers:
            for callback in list(self.subscribers[event_type]):
                try:
                    res = callback(payload)
                    if asyncio.iscoroutine(res):
                        await res
                except Exception as ex:
                    logger.warning(f"Error in EventBus subscriber for '{event_type}': {ex}")

        # 3. Dispatch to global wildcard subscribers
        for callback in list(self.global_subscribers):
            try:
                res = callback(payload)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as ex:
                logger.warning(f"Error in EventBus global subscriber: {ex}")


event_bus = EventBus()
