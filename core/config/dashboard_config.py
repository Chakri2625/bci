"""
Dashboard Backend Configuration & Environment Setup Module.
Member 8 — SynaptiMesh Core Execution Architecture.

Provides centralized, thread-safe dashboard backend configuration,
environment variable detection, declarative YAML overrides, and WebSocket
layer communication parameters required by REST APIs and telemetry streams.
"""

import os
import sys
import logging
import threading
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

# Ensure workspace root is in sys.path
_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

logger = logging.getLogger("dashboard_config")


class DashboardBackendConfig(BaseModel):
    """Structured Pydantic model for Dashboard Backend & WebSocket Layer configuration."""
    
    # Environment & Application Settings
    app_name: str = Field(default="SynaptiMesh Dashboard", description="Application display title")
    env: str = Field(default="development", description="Execution environment (development, staging, production)")
    debug: bool = Field(default=True, description="Debug mode flag")
    host: str = Field(default="0.0.0.0", description="Backend binding host interface")
    port: int = Field(default=8000, description="Backend HTTP/WebSocket server port")
    api_prefix: str = Field(default="/api/v1", description="API route prefix")
    cors_origins: List[str] = Field(default_factory=lambda: ["*"], description="Allowed CORS origins")
    log_level: str = Field(default="INFO", description="Logging verbosity level")

    # WebSocket Layer & Real-time Telemetry Settings
    ws_enabled: bool = Field(default=True, description="Enable WebSocket server endpoints")
    ws_host: str = Field(default="0.0.0.0", description="WebSocket server binding host")
    ws_port: int = Field(default=8000, description="WebSocket server port")
    ws_path: str = Field(default="/ws", description="Default WebSocket channel path")
    ws_bci_path: str = Field(default="/api/v1/bci/ws", description="BCI Telemetry WebSocket endpoint")
    ws_heartbeat_interval_sec: float = Field(default=15.0, description="WebSocket ping/pong heartbeat interval in seconds")
    ws_client_timeout_sec: float = Field(default=30.0, description="Client connection timeout in seconds")
    ws_max_message_bytes: int = Field(default=1048576, description="Maximum WebSocket payload size in bytes (1MB default)")
    ws_broadcast_rate_hz: float = Field(default=30.0, description="Maximum telemetry broadcast frequency in Hz")
    ws_auto_reconnect: bool = Field(default=True, description="Client auto-reconnection hint flag")
    ws_reconnect_backoff_sec: float = Field(default=2.0, description="Initial reconnect backoff delay in seconds")
    ws_ssl_enabled: bool = Field(default=False, description="Enable WSS secure WebSocket transport")
    cortex_ws_url: str = Field(default="wss://localhost:6868", description="Emotiv Cortex WebSocket API URL")

    # Dashboard Domain & Execution Tuning
    framing_duration_sec: float = Field(default=4.0, description="Default temporal framing window duration in seconds")
    power_threshold: float = Field(default=0.65, description="BCI activation power threshold [0.0 - 1.0]")
    sensitivity: float = Field(default=0.65, description="BCI signal sensitivity factor [0.0 - 1.0]")
    telemetry_history_size: int = Field(default=100, description="Bounded memory buffer size for event history")
    authoritative_dashboards: Dict[str, str] = Field(
        default_factory=lambda: {
            "PYTHON": "/",
            "IOT": "/iot",
            "EMBEDDED": "/embedded",
            "AIML": "/aiml"
        },
        description="Mapping of canonical domain keys to authoritative team dashboard routes"
    )


class DashboardConfigManager:
    """
    Centralized, thread-safe manager for dashboard backend configuration.
    Loads declarative YAML defaults, applies environment variables,
    and supports dynamic runtime configuration updates.
    """

    def __init__(self, config_dir: Optional[str] = None):
        self._lock = threading.RLock()
        self._config_dir = config_dir or os.path.join(_ROOT_DIR, "config")
        self._config = DashboardBackendConfig()
        self.load_configuration()

    def load_configuration(self) -> DashboardBackendConfig:
        """
        Loads configuration from YAML files and environment variable overrides.
        """
        with self._lock:
            config_dict = self._config.model_dump()

            # 1. Attempt loading config/dashboard.yaml or config/app.yaml
            yaml_data = self._load_yaml_config()
            if yaml_data:
                config_dict = self._merge_yaml_dict(config_dict, yaml_data)

            # 2. Environment Variable Overrides
            env_overrides = self._extract_env_variables()
            for key, val in env_overrides.items():
                if val is not None:
                    config_dict[key] = val

            self._config = DashboardBackendConfig(**config_dict)
            logger.info(
                f"[DASHBOARD_CONFIG] Loaded configuration for env='{self._config.env}', "
                f"port={self._config.port}, ws_enabled={self._config.ws_enabled}"
            )
            return self._config

    def _load_yaml_config(self) -> Dict[str, Any]:
        """Reads declarative YAML files if PyYAML is installed and files exist."""
        result = {}
        target_files = [
            os.path.join(self._config_dir, "app.yaml"),
            os.path.join(self._config_dir, "dashboard.yaml"),
        ]
        
        for filepath in target_files:
            if not os.path.exists(filepath):
                continue
            try:
                import yaml
                with open(filepath, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if isinstance(data, dict):
                        result.update(data)
            except Exception as e:
                logger.warning(f"[DASHBOARD_CONFIG] Could not parse YAML file '{filepath}': {e}")
        return result

    def _merge_yaml_dict(self, current: Dict[str, Any], yaml_data: Dict[str, Any]) -> Dict[str, Any]:
        """Flattens nested YAML structure (e.g. app.*, websocket.*, dashboard.*) into DashboardBackendConfig fields."""
        merged = dict(current)
        
        # Top level app block
        app_block = yaml_data.get("app", {})
        if isinstance(app_block, dict):
            for k, v in app_block.items():
                if k in merged:
                    merged[k] = v

        # Top level websocket block
        ws_block = yaml_data.get("websocket", {})
        if isinstance(ws_block, dict):
            for k, v in ws_block.items():
                target_key = f"ws_{k}" if not k.startswith("ws_") and k != "cortex_ws_url" else k
                if target_key in merged:
                    merged[target_key] = v

        # Top level dashboard block
        dash_block = yaml_data.get("dashboard", {})
        if isinstance(dash_block, dict):
            for k, v in dash_block.items():
                if k in merged:
                    merged[k] = v

        # Direct root attributes override
        for k, v in yaml_data.items():
            if k in merged and not isinstance(v, dict):
                merged[k] = v

        return merged

    def _extract_env_variables(self) -> Dict[str, Any]:
        """Reads environment variables with prefix fallbacks."""
        def get_env_str(var_name: str) -> Optional[str]:
            return os.getenv(var_name, os.getenv(f"DASHBOARD_{var_name}"))

        def get_env_bool(var_name: str) -> Optional[bool]:
            val = get_env_str(var_name)
            if val is None:
                return None
            return val.strip().lower() in ("true", "1", "yes", "on")

        def get_env_int(var_name: str) -> Optional[int]:
            val = get_env_str(var_name)
            if val is None:
                return None
            try:
                return int(val.strip())
            except ValueError:
                return None

        def get_env_float(var_name: str) -> Optional[float]:
            val = get_env_str(var_name)
            if val is None:
                return None
            try:
                return float(val.strip())
            except ValueError:
                return None

        return {
            "env": get_env_str("ENV"),
            "host": get_env_str("HOST"),
            "port": get_env_int("PORT"),
            "debug": get_env_bool("DEBUG"),
            "log_level": get_env_str("LOG_LEVEL"),
            "ws_enabled": get_env_bool("WS_ENABLED"),
            "ws_host": get_env_str("WS_HOST"),
            "ws_port": get_env_int("WS_PORT"),
            "ws_path": get_env_str("WS_PATH"),
            "ws_heartbeat_interval_sec": get_env_float("WS_HEARTBEAT_INTERVAL_SEC"),
            "ws_client_timeout_sec": get_env_float("WS_CLIENT_TIMEOUT_SEC"),
            "ws_broadcast_rate_hz": get_env_float("WS_BROADCAST_RATE_HZ"),
            "cortex_ws_url": get_env_str("CORTEX_WS_URL") or get_env_str("CORTEX_URL"),
            "framing_duration_sec": get_env_float("FRAMING_DURATION_SEC"),
            "power_threshold": get_env_float("POWER_THRESHOLD"),
            "sensitivity": get_env_float("SENSITIVITY"),
        }

    def get_config(self) -> DashboardBackendConfig:
        """Returns the current active configuration snapshot."""
        with self._lock:
            return self._config.model_copy()

    def update_config(self, updates: Dict[str, Any]) -> DashboardBackendConfig:
        """
        Dynamically updates backend configuration fields at runtime.
        """
        with self._lock:
            current_dict = self._config.model_dump()
            valid_keys = set(current_dict.keys())
            
            applied = False
            for k, v in updates.items():
                if k in valid_keys and v is not None:
                    current_dict[k] = v
                    applied = True

            if applied:
                self._config = DashboardBackendConfig(**current_dict)
                logger.info(f"[DASHBOARD_CONFIG] Runtime configuration updated: {list(updates.keys())}")
            return self._config.model_copy()

    def reset_to_defaults(self) -> DashboardBackendConfig:
        """Resets configuration back to default baseline."""
        with self._lock:
            self._config = DashboardBackendConfig()
            return self.load_configuration()

    def to_websocket_config(self) -> Dict[str, Any]:
        """
        Exports WebSocket layer setup parameters for frontend and server connection layers.
        """
        cfg = self.get_config()
        return {
            "enabled": cfg.ws_enabled,
            "host": cfg.ws_host,
            "port": cfg.ws_port,
            "path": cfg.ws_path,
            "bci_path": cfg.ws_bci_path,
            "heartbeat_interval_sec": cfg.ws_heartbeat_interval_sec,
            "client_timeout_sec": cfg.ws_client_timeout_sec,
            "max_message_bytes": cfg.ws_max_message_bytes,
            "broadcast_rate_hz": cfg.ws_broadcast_rate_hz,
            "auto_reconnect": cfg.ws_auto_reconnect,
            "reconnect_backoff_sec": cfg.ws_reconnect_backoff_sec,
            "ssl_enabled": cfg.ws_ssl_enabled,
            "cortex_ws_url": cfg.cortex_ws_url,
        }

    def to_environment_summary(self) -> Dict[str, Any]:
        """
        Provides summary telemetry of the runtime environment setup.
        """
        cfg = self.get_config()
        import platform
        return {
            "app_name": cfg.app_name,
            "environment": cfg.env,
            "debug": cfg.debug,
            "python_version": sys.version.split()[0],
            "os_platform": platform.system(),
            "server": {
                "host": cfg.host,
                "port": cfg.port,
                "api_prefix": cfg.api_prefix,
            },
            "websocket": {
                "enabled": cfg.ws_enabled,
                "endpoint": f"ws://{cfg.host}:{cfg.port}{cfg.ws_path}",
                "bci_endpoint": f"ws://{cfg.host}:{cfg.port}{cfg.ws_bci_path}",
                "heartbeat_interval_sec": cfg.ws_heartbeat_interval_sec,
            },
            "authoritative_dashboards": cfg.authoritative_dashboards,
        }


# Singleton Global Manager Instance
dashboard_config_manager = DashboardConfigManager()


def get_dashboard_config() -> DashboardBackendConfig:
    """Helper function to get current dashboard backend configuration."""
    return dashboard_config_manager.get_config()
