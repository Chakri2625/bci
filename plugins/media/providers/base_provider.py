from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseMediaProvider(ABC):
    """
    Abstract base provider interface for media streaming/playback services.
    Ensures modularity and loose coupling across media targets (YouTube, JioSaavn, etc.).
    """
    provider_name: str = "base"

    def is_available(self) -> bool:
        """Check if the provider runtime/dependencies are available."""
        return True

    def get_supported_actions(self) -> List[str]:
        """Return the list of supported action names for this provider."""
        return []

    @abstractmethod
    async def execute(self, action: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute a media action on the provider.
        
        Args:
            action: The media action (e.g. 'PLAY', 'PAUSE', 'TOGGLE_PLAY_PAUSE', 'NEXT', 'PREVIOUS', 'SEARCH')
            payload: Parameters including query, volume, app info, etc.
            
        Returns:
            Structured dictionary with 'status', 'success', 'message', 'execution_time_ms', etc.
        """
        raise NotImplementedError
