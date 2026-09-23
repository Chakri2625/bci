import importlib
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("desktop_registry")

# Standard mapping from incoming application name to subplugin identifier
DEFAULT_APP_ROUTING: Dict[str, str] = {
    "YOUTUBE": "youtube",
    "CHROME": "chrome",
    "NOTEPAD": "notepad",
    "GMAIL": "email",
    "EMAIL": "email",
}


def load_subplugins() -> Dict[str, Any]:
    """
    Load all desktop application subplugins.
    Preserves exact existing behavior and signature.
    """
    plugins: Dict[str, Any] = {}
    
    try:
        from plugins.desktop.subplugins.chrome.plugin import ChromePlugin
        plugins['chrome'] = ChromePlugin()
    except Exception as e:
        logger.error(f"Failed to load chrome subplugin: {e}")
    
    try:
        from plugins.desktop.subplugins.notepad.plugin import NotepadPlugin
        plugins['notepad'] = NotepadPlugin()
    except Exception as e:
        logger.error(f"Failed to load notepad subplugin: {e}")

    try:
        from plugins.desktop.subplugins.youtube.plugin import YoutubePlugin
        plugins['youtube'] = YoutubePlugin()
    except Exception as e:
        logger.error(f"Failed to load youtube subplugin: {e}")

    try:
        from plugins.desktop.subplugins.email.plugin import EmailPlugin
        plugins['email'] = EmailPlugin()
    except Exception as e:
        logger.error(f"Failed to load email subplugin: {e}")

    return plugins


def get_target_subplugin_id(app: str) -> Optional[str]:
    """Resolve an incoming application identifier to a registered subplugin ID."""
    if not isinstance(app, str):
        return None
    return DEFAULT_APP_ROUTING.get(app.strip().upper())


def get_supported_applications() -> List[str]:
    """Return list of supported application names."""
    return sorted(list(DEFAULT_APP_ROUTING.keys()))

