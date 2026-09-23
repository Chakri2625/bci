"""
Shared Resource Management Layer (Day 3 - Member 5)

Provides thread-safe resource tracking, registration, availability checking,
assignment, release, and task-resource relationship management for concurrent
command execution in SynaptiMesh.

This module serves as the foundational resource coordination layer for
Member 6's Resource Locking and Conflict Prevention module.
"""

from datetime import datetime
from enum import Enum
import logging
import threading
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field


logger = logging.getLogger("synaptimesh.resource_manager")


class ResourceState(str, Enum):
    """
    Standard lifecycle states for shared resources.
    """
    AVAILABLE = "available"
    IN_USE = "in_use"
    RESERVED = "reserved"
    ERROR = "error"


class Resource(BaseModel):
    """
    Data model representing a managed shared resource.
    """
    resource_id: str = Field(..., description="Unique resource identifier (e.g. 'browser', 'notepad', 'mqtt')")
    status: str = Field(default=ResourceState.AVAILABLE.value, description="Current operational status")
    task_id: Optional[str] = Field(default=None, description="ID of the task currently holding this resource")
    description: Optional[str] = Field(default=None, description="Human-readable resource description")
    acquired_at: Optional[datetime] = Field(default=None, description="Timestamp when resource was assigned")
    released_at: Optional[datetime] = Field(default=None, description="Timestamp when resource was last released")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary resource metadata")

    def is_available(self) -> bool:
        """Check if resource is currently available and unassigned."""
        return self.status == ResourceState.AVAILABLE.value and self.task_id is None

    def to_dict(self) -> Dict[str, Any]:
        """Convert resource to structured dictionary."""
        return {
            "resource_id": self.resource_id,
            "status": self.status,
            "task_id": self.task_id,
            "description": self.description,
            "acquired_at": self.acquired_at.isoformat() if self.acquired_at else None,
            "released_at": self.released_at.isoformat() if self.released_at else None,
            "metadata": dict(self.metadata),
        }


class SharedResourceManager:
    """
    Thread-safe coordinator for shared system, desktop, and communication resources.
    
    Guarantees atomic check-and-assign operations using internal reentrant locks
    to eliminate race conditions in concurrent execution environments.
    """

    def __init__(
        self,
        default_resources: Optional[List[str]] = None,
        custom_logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize the SharedResourceManager.

        Args:
            default_resources: Optional list of resource IDs to pre-register.
            custom_logger: Optional logger instance.
        """
        self._resources: Dict[str, Resource] = {}
        self._lock = threading.RLock()
        self._logger = custom_logger or logger

        if default_resources:
            self.register_resources(default_resources)

    # ----------------------------------------------------------------------
    # Registration & Existence
    # ----------------------------------------------------------------------

    def register_resource(
        self,
        resource_id: str,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Register a new shared resource.

        If the resource is already registered, existing state and ownership are
        preserved to avoid accidental overwrites or duplicate entries.

        Args:
            resource_id: Unique string identifier for the resource.
            description: Optional descriptive text.
            metadata: Optional dictionary of attributes.

        Returns:
            bool: True if registered anew, False if already registered or invalid ID.
        """
        if not resource_id or not isinstance(resource_id, str):
            self._logger.warning("[RESOURCE] Registration failed: Invalid resource_id.")
            return False

        clean_id = resource_id.strip().lower()
        if not clean_id:
            self._logger.warning("[RESOURCE] Registration failed: Empty resource_id.")
            return False

        with self._lock:
            if clean_id in self._resources:
                self._logger.info(f"[RESOURCE] Already registered: {clean_id}")
                return False

            self._resources[clean_id] = Resource(
                resource_id=clean_id,
                status=ResourceState.AVAILABLE.value,
                task_id=None,
                description=description,
                metadata=metadata or {},
            )
            self._logger.info(f"[RESOURCE] Registered: {clean_id}")
            return True

    def register_resources(self, resource_ids: List[str]) -> List[str]:
        """
        Batch-register multiple resources.

        Args:
            resource_ids: List of resource identifiers to register.

        Returns:
            List[str]: List of resource IDs that were newly registered.
        """
        registered = []
        for rid in resource_ids:
            if self.register_resource(rid):
                registered.append(rid.strip().lower())
        return registered

    def is_registered(self, resource_id: str) -> bool:
        """
        Check whether a resource is registered in the manager.

        Args:
            resource_id: Resource identifier.

        Returns:
            bool: True if registered, False otherwise.
        """
        if not resource_id or not isinstance(resource_id, str):
            return False
        clean_id = resource_id.strip().lower()
        with self._lock:
            return clean_id in self._resources

    def unregister_resource(self, resource_id: str, force: bool = False) -> bool:
        """
        Unregister and remove a resource.

        Args:
            resource_id: Identifier of the resource to unregister.
            force: If True, unregisters even if currently in use.

        Returns:
            bool: True if removed, False if not found or occupied when force=False.
        """
        if not resource_id or not isinstance(resource_id, str):
            return False
        clean_id = resource_id.strip().lower()

        with self._lock:
            if clean_id not in self._resources:
                return False

            res = self._resources[clean_id]
            if not res.is_available() and not force:
                self._logger.warning(
                    f"[RESOURCE] Cannot unregister occupied resource '{clean_id}' owned by '{res.task_id}' (force=False)"
                )
                return False

            del self._resources[clean_id]
            self._logger.info(f"[RESOURCE] Unregistered: {clean_id}")
            return True

    # ----------------------------------------------------------------------
    # Availability & Inspection
    # ----------------------------------------------------------------------

    def is_available(self, resource_id: str) -> bool:
        """
        Check if a resource exists and is currently available for assignment.

        Args:
            resource_id: Identifier of the resource.

        Returns:
            bool: True if available, False otherwise (including unregistered).
        """
        if not resource_id or not isinstance(resource_id, str):
            return False
        clean_id = resource_id.strip().lower()

        with self._lock:
            if clean_id not in self._resources:
                return False
            return self._resources[clean_id].is_available()

    def get_resource_status(self, resource_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the current status and metadata of a specific resource.

        Args:
            resource_id: Identifier of the resource.

        Returns:
            Optional[Dict[str, Any]]: Resource status dictionary, or None if unregistered.
        """
        if not resource_id or not isinstance(resource_id, str):
            return None
        clean_id = resource_id.strip().lower()

        with self._lock:
            if clean_id not in self._resources:
                return None
            return self._resources[clean_id].to_dict()

    def get_resource(self, resource_id: str) -> Optional[Resource]:
        """
        Get a snapshot copy of the Resource model instance.

        Args:
            resource_id: Identifier of the resource.

        Returns:
            Optional[Resource]: Resource model or None.
        """
        if not resource_id or not isinstance(resource_id, str):
            return None
        clean_id = resource_id.strip().lower()

        with self._lock:
            if clean_id not in self._resources:
                return None
            return self._resources[clean_id].model_copy(deep=True)

    def get_all_resources(self) -> Dict[str, Dict[str, Any]]:
        """
        Retrieve status dictionaries for all registered resources.

        Returns:
            Dict[str, Dict[str, Any]]: Mapping of resource_id -> status dictionary.
        """
        with self._lock:
            return {
                rid: res.to_dict()
                for rid, res in self._resources.items()
            }

    def get_available_resources(self) -> List[str]:
        """
        Get a list of all currently available resource identifiers.

        Returns:
            List[str]: Available resource IDs.
        """
        with self._lock:
            return [
                rid for rid, res in self._resources.items()
                if res.is_available()
            ]

    def get_occupied_resources(self) -> List[str]:
        """
        Get a list of all currently occupied (in use) resource identifiers.

        Returns:
            List[str]: Occupied resource IDs.
        """
        with self._lock:
            return [
                rid for rid, res in self._resources.items()
                if not res.is_available()
            ]

    # ----------------------------------------------------------------------
    # Assignment & Release (Thread-safe atomic operations)
    # ----------------------------------------------------------------------

    def assign_resource(
        self,
        resource_id: str,
        task_id: str,
        auto_register: bool = False,
    ) -> bool:
        """
        Safely and atomically assign a resource to a task.

        If the resource is already in use by another task, assignment is rejected.
        If the resource is already assigned to the SAME task, the assignment is
        treated as successful (idempotent).

        Args:
            resource_id: Target resource identifier.
            task_id: Identifier of the task requesting assignment.
            auto_register: If True, registers an unregistered resource automatically.

        Returns:
            bool: True if assigned (or already owned by task_id), False otherwise.
        """
        if not resource_id or not isinstance(resource_id, str):
            self._logger.warning("[RESOURCE] Assignment failed: Invalid resource_id.")
            return False
        if not task_id or not isinstance(task_id, str):
            self._logger.warning("[RESOURCE] Assignment failed: Invalid task_id.")
            return False

        clean_rid = resource_id.strip().lower()
        clean_tid = task_id.strip()

        with self._lock:
            if clean_rid not in self._resources:
                if auto_register:
                    self.register_resource(clean_rid)
                else:
                    self._logger.warning(
                        f"[RESOURCE] Cannot assign unregistered resource: {clean_rid}"
                    )
                    return False

            res = self._resources[clean_rid]

            # Case 1: Already assigned to this exact task
            if res.task_id == clean_tid:
                self._logger.info(
                    f"[RESOURCE] {clean_rid} is already assigned to {clean_tid}"
                )
                return True

            # Case 2: In use by another task
            if not res.is_available():
                self._logger.warning(
                    f"[RESOURCE] {clean_rid} already in use by {res.task_id}"
                )
                return False

            # Case 3: Available -> assign atomically
            res.status = ResourceState.IN_USE.value
            res.task_id = clean_tid
            res.acquired_at = datetime.now()
            res.released_at = None

            self._logger.info(f"[RESOURCE] {clean_rid} assigned to {clean_tid}")
            return True

    def assign_resources(
        self,
        resource_ids: List[str],
        task_id: str,
        atomic: bool = True,
        auto_register: bool = False,
    ) -> bool:
        """
        Assign multiple resources to a single task.

        Args:
            resource_ids: List of resource IDs required by the task.
            task_id: Task identifier.
            atomic: If True, ensures ALL resources are available before assigning any (all-or-nothing).
            auto_register: If True, registers any unregistered resources on-the-fly.

        Returns:
            bool: True if all resources were assigned, False if any failed.
        """
        if not resource_ids or not task_id:
            return False

        clean_rids = [r.strip().lower() for r in resource_ids if r and isinstance(r, str)]
        clean_tid = task_id.strip()

        with self._lock:
            if auto_register:
                for rid in clean_rids:
                    if rid not in self._resources:
                        self.register_resource(rid)

            if atomic:
                # Pre-check all resources are either available or already owned by this task
                for rid in clean_rids:
                    if rid not in self._resources:
                        self._logger.warning(
                            f"[RESOURCE] Cannot batch assign: '{rid}' is unregistered."
                        )
                        return False
                    res = self._resources[rid]
                    if not res.is_available() and res.task_id != clean_tid:
                        self._logger.warning(
                            f"[RESOURCE] Cannot batch assign: '{rid}' already in use by '{res.task_id}'."
                        )
                        return False

            # Assign all
            all_success = True
            for rid in clean_rids:
                success = self.assign_resource(rid, clean_tid, auto_register=auto_register)
                if not success:
                    all_success = False

            return all_success

    def release_resource(self, resource_id: str, task_id: str) -> bool:
        """
        Release a resource currently held by a specific task.

        If the task attempting release does not own the resource, release is
        rejected and the resource remains held by its current owner.

        Args:
            resource_id: Identifier of the resource.
            task_id: Identifier of the task releasing the resource.

        Returns:
            bool: True if successfully released or already free, False if release rejected.
        """
        if not resource_id or not isinstance(resource_id, str):
            return False
        if not task_id or not isinstance(task_id, str):
            return False

        clean_rid = resource_id.strip().lower()
        clean_tid = task_id.strip()

        with self._lock:
            if clean_rid not in self._resources:
                self._logger.warning(
                    f"[RESOURCE] Release failed: '{clean_rid}' is not registered."
                )
                return False

            res = self._resources[clean_rid]

            # If already available and unowned
            if res.is_available():
                self._logger.info(f"[RESOURCE] {clean_rid} is already available")
                return True

            # Verify ownership
            if res.task_id != clean_tid:
                self._logger.warning(
                    f"[RESOURCE] Release rejected: {clean_rid} is owned by {res.task_id}, not {clean_tid}"
                )
                return False

            # Release
            res.status = ResourceState.AVAILABLE.value
            res.task_id = None
            res.released_at = datetime.now()

            self._logger.info(f"[RESOURCE] {clean_rid} released by {clean_tid}")
            return True

    def force_release_resource(self, resource_id: str) -> bool:
        """
        Forcefully release a resource regardless of ownership (e.g. on emergency stop/cleanup).

        Args:
            resource_id: Identifier of the resource to reset.

        Returns:
            bool: True if reset, False if unregistered.
        """
        if not resource_id or not isinstance(resource_id, str):
            return False
        clean_rid = resource_id.strip().lower()

        with self._lock:
            if clean_rid not in self._resources:
                return False

            res = self._resources[clean_rid]
            prev_owner = res.task_id
            res.status = ResourceState.AVAILABLE.value
            res.task_id = None
            res.released_at = datetime.now()

            self._logger.info(
                f"[RESOURCE] {clean_rid} forcefully released (previously held by {prev_owner})"
            )
            return True

    # ----------------------------------------------------------------------
    # Task-Resource Tracking
    # ----------------------------------------------------------------------

    def get_task_resources(self, task_id: str) -> List[str]:
        """
        Get all resource IDs currently assigned to a specific task.

        Args:
            task_id: Task identifier.

        Returns:
            List[str]: List of resource IDs held by the task.
        """
        if not task_id or not isinstance(task_id, str):
            return []
        clean_tid = task_id.strip()

        with self._lock:
            return [
                rid for rid, res in self._resources.items()
                if res.task_id == clean_tid
            ]

    def release_all_for_task(self, task_id: str) -> List[str]:
        """
        Release all resources currently held by a given task.
        Useful when a task finishes, fails, or is cancelled.

        Args:
            task_id: Task identifier.

        Returns:
            List[str]: List of resource IDs that were released.
        """
        if not task_id or not isinstance(task_id, str):
            return []
        clean_tid = task_id.strip()

        with self._lock:
            task_resources = self.get_task_resources(clean_tid)
            released = []
            for rid in task_resources:
                if self.release_resource(rid, clean_tid):
                    released.append(rid)

            if released:
                self._logger.info(
                    f"[RESOURCE] Released all resources for {clean_tid}: {released}"
                )
            return released

    # ----------------------------------------------------------------------
    # Summary & Maintenance
    # ----------------------------------------------------------------------

    def get_resource_summary(self) -> Dict[str, Any]:
        """
        Provide high-level summary metrics of all resources.

        Returns:
            Dict[str, Any]: Summary containing total, available, and occupied statistics.
        """
        with self._lock:
            available = self.get_available_resources()
            occupied = self.get_occupied_resources()
            return {
                "total_count": len(self._resources),
                "available_count": len(available),
                "occupied_count": len(occupied),
                "available_resources": available,
                "occupied_resources": occupied,
            }

    def clear(self) -> None:
        """
        Reset and clear all registered resources.
        """
        with self._lock:
            self._resources.clear()
            self._logger.info("[RESOURCE] All resources cleared.")

    def reset_all_states(self) -> None:
        """
        Reset all existing registered resources to AVAILABLE and unassigned.
        """
        with self._lock:
            for res in self._resources.values():
                res.status = ResourceState.AVAILABLE.value
                res.task_id = None
                res.acquired_at = None
                res.released_at = datetime.now()
            self._logger.info("[RESOURCE] All resource states reset to AVAILABLE.")

    def __len__(self) -> int:
        with self._lock:
            return len(self._resources)

    def __contains__(self, resource_id: str) -> bool:
        return self.is_registered(resource_id)
