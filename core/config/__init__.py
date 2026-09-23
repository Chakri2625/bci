"""
Core Configuration Package.
SynaptiMesh Execution Architecture.
"""

from core.config.retry_config import (
    MAX_RETRIES,
    RETRY_DELAY,
    COMMAND_TIMEOUT,
    RETRYABLE_ERROR_TYPES,
    NON_RETRYABLE_ERROR_TYPES,
    is_retryable_error,
)

from core.config.dashboard_config import (
    DashboardBackendConfig,
    DashboardConfigManager,
    dashboard_config_manager,
    get_dashboard_config,
)

__all__ = [
    "MAX_RETRIES",
    "RETRY_DELAY",
    "COMMAND_TIMEOUT",
    "RETRYABLE_ERROR_TYPES",
    "NON_RETRYABLE_ERROR_TYPES",
    "is_retryable_error",
    "DashboardBackendConfig",
    "DashboardConfigManager",
    "dashboard_config_manager",
    "get_dashboard_config",
]
