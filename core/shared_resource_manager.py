"""
Shared Resource Management module alias.
"""

from core.managers.shared_resource_manager import (
    Resource,
    ResourceState,
    SharedResourceManager,
    logger,
)

__all__ = [
    "Resource",
    "ResourceState",
    "SharedResourceManager",
    "logger",
]
