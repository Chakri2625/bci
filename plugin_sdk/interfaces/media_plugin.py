from typing import Dict, Any, Optional
from .base_plugin import BasePlugin


class MediaPluginInterface(BasePlugin):
    """Base interface for SynaptiMesh Media domain plugins."""

    plugin_id = "media"

    async def execute(
        self,
        command: str,
        payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        raise NotImplementedError


class BaseMediaProvider:
    """Base interface for media providers."""

    async def execute(
        self,
        action: str,
        payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        raise NotImplementedError