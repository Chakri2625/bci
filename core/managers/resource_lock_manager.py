import asyncio
import logging
from typing import Dict, Optional, Any
from contextlib import asynccontextmanager

logger = logging.getLogger("resource_lock_manager")


class ResourceConflictError(Exception):
    """Raised when a non-blocking lock cannot be acquired because the resource is busy."""
    pass


class ResourceLockManager:
    """
    Manages granular, keyed asynchronous resource locks to prevent conflicting
    or race-condition operations on shared resources (e.g., specific devices,
    applications, or domains) without blocking independent resources.
    """

    def __init__(self):
        self._locks: Dict[str, asyncio.Lock] = {}
        self._holders: Dict[str, Optional[str]] = {}

    def _get_or_create_lock(self, resource_id: str) -> asyncio.Lock:
        """Retrieve existing lock or initialize a new asyncio.Lock for the resource."""
        if resource_id not in self._locks:
            self._locks[resource_id] = asyncio.Lock()
        return self._locks[resource_id]

    def is_locked(self, resource_id: str) -> bool:
        """Check if a specific resource is currently locked."""
        lock = self._locks.get(resource_id)
        return lock.locked() if lock is not None else False

    def get_holder(self, resource_id: str) -> Optional[str]:
        """Return the owner/session currently holding the lock, or None."""
        if self.is_locked(resource_id):
            return self._holders.get(resource_id)
        return None

    async def acquire(
        self,
        resource_id: str,
        owner: Optional[str] = None,
        blocking: bool = True,
        timeout: Optional[float] = None,
    ) -> bool:
        """
        Acquire the lock for a given resource_id.

        Args:
            resource_id: Identifier for the target resource (e.g. 'device:LIGHT', 'app:PYTHON:YOUTUBE').
            owner: Optional identifier for the task/session acquiring the lock.
            blocking: If True, waits for lock availability. If False, fails immediately if locked.
            timeout: Optional max time in seconds to wait when blocking is True.

        Returns:
            bool: True if lock acquired, False if non-blocking acquisition failed or timeout occurred.
        """
        lock = self._get_or_create_lock(resource_id)

        if not blocking:
            if lock.locked():
                logger.debug(f"[ResourceLockManager] Conflict: Resource '{resource_id}' is busy (held by {self._holders.get(resource_id)})")
                return False
            # Acquire without waiting
            try:
                # In asyncio, acquire() is a coroutine; if not locked, it resolves immediately
                await lock.acquire()
                self._holders[resource_id] = owner
                logger.debug(f"[ResourceLockManager] Acquired lock for '{resource_id}' by owner='{owner}' (non-blocking)")
                return True
            except Exception as e:
                logger.error(f"[ResourceLockManager] Error during non-blocking acquire for '{resource_id}': {e}")
                return False

        # Blocking acquire
        try:
            if timeout is not None:
                await asyncio.wait_for(lock.acquire(), timeout=timeout)
            else:
                await lock.acquire()

            self._holders[resource_id] = owner
            logger.debug(f"[ResourceLockManager] Acquired lock for '{resource_id}' by owner='{owner}'")
            return True
        except asyncio.TimeoutError:
            logger.warning(f"[ResourceLockManager] Timeout acquiring lock for '{resource_id}' after {timeout}s")
            return False
        except Exception as e:
            logger.error(f"[ResourceLockManager] Error acquiring lock for '{resource_id}': {e}")
            return False

    async def release(self, resource_id: str, owner: Optional[str] = None) -> bool:
        """
        Safely release the lock for a given resource_id.

        Args:
            resource_id: Identifier for the resource to release.
            owner: Optional identifier; logs warning if releaser is not current holder.

        Returns:
            bool: True if released, False if lock was not held.
        """
        lock = self._locks.get(resource_id)
        if lock is None or not lock.locked():
            logger.debug(f"[ResourceLockManager] Release called on unlocked resource '{resource_id}'")
            self._holders.pop(resource_id, None)
            return False

        current_holder = self._holders.get(resource_id)
        if owner is not None and current_holder is not None and current_holder != owner:
            logger.warning(
                f"[ResourceLockManager] Owner mismatch releasing '{resource_id}': current='{current_holder}', releaser='{owner}'"
            )

        self._holders.pop(resource_id, None)
        try:
            lock.release()
            logger.debug(f"[ResourceLockManager] Released lock for '{resource_id}'")
            return True
        except RuntimeError as e:
            logger.error(f"[ResourceLockManager] Failed to release lock for '{resource_id}': {e}")
            return False

    @asynccontextmanager
    async def lock(
        self,
        resource_id: str,
        owner: Optional[str] = None,
        blocking: bool = True,
        timeout: Optional[float] = None,
    ):
        """
        Async context manager for safe lock acquire and guaranteed release.

        Usage:
            async with resource_lock_manager.lock("device:LIGHT", owner="session_1"):
                await perform_action()
        """
        acquired = await self.acquire(resource_id, owner=owner, blocking=blocking, timeout=timeout)
        if not acquired:
            raise ResourceConflictError(
                f"Resource '{resource_id}' is currently locked by '{self.get_holder(resource_id)}'"
            )
        try:
            yield self
        finally:
            await self.release(resource_id, owner=owner)

    def clear(self):
        """Reset all locks and holders (primarily for testing fixtures)."""
        self._locks.clear()
        self._holders.clear()


resource_lock_manager = ResourceLockManager()
