from typing import Dict, Any, Optional
from .base_plugin import BasePlugin

class EmbeddedPluginInterface(BasePlugin):
    plugin_id = "embedded"
    
    async def execute(self, command: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        raise NotImplementedError
