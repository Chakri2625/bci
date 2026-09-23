"""
Retry, Timeout, and Execution Timing Configuration.
SynaptiMesh Core Execution Architecture.
"""

from typing import Set, Union

# Centralized Retry & Timeout Configuration
MAX_RETRIES: int = 3          # 3 total execution attempts (Attempt 1/3, 2/3, 3/3; never a 4th)
RETRY_DELAY: float = 2.0      # 2 seconds wait between retry attempts
COMMAND_TIMEOUT: float = 10.0 # 10 seconds timeout per execution attempt

# Standard Retryable Error Types
RETRYABLE_ERROR_TYPES: Set[str] = {
    "TIMEOUT",
    "TEMPORARY_COMMUNICATION_ERROR",
    "TEMPORARY_DEVICE_ERROR",
    "TEMPORARY_APPLICATION_ERROR",
    "CONNECTION_ERROR",
}

# Standard Non-Retryable Error Types
NON_RETRYABLE_ERROR_TYPES: Set[str] = {
    "INVALID_COMMAND",
    "INVALID_JSON",
    "MISSING_PARAMETER",
    "UNSUPPORTED_COMMAND",
    "INVALID_COMMAND_FORMAT",
    "PERMANENT_CONFIGURATION_ERROR",
    "VALIDATION_ERROR",
}

# Keyword heuristics for classifying errors
TEMPORARY_ERROR_KEYWORDS = [
    "timeout",
    "timed out",
    "not responding",
    "busy",
    "connection loss",
    "connection error",
    "temporary",
    "disconnected",
    "unavailable",
    "unreachable",
    "refused",
    "broken pipe",
    "connection reset",
    "device error",
    "communication error",
    "stall detected",
]

PERMANENT_ERROR_KEYWORDS = [
    "invalid command",
    "unknown command",
    "invalid json",
    "missing parameter",
    "missing device_id",
    "unsupported command",
    "invalid command format",
    "permanent configuration error",
    "validation error",
    "validation",
    "invalid sequence",
]


def is_retryable_error(error: Union[str, Exception, None]) -> bool:
    """
    Determine whether an error is transient and retryable.
    Returns False for validation/invalid command errors, True for temporary/timeout errors.
    """
    if error is None:
        return False

    err_str = str(error).strip()
    err_upper = err_str.upper()

    # Exact type match
    if err_upper in NON_RETRYABLE_ERROR_TYPES:
        return False
    if err_upper in RETRYABLE_ERROR_TYPES:
        return True

    err_lower = err_str.lower()

    # Permanent keywords take priority
    for kw in PERMANENT_ERROR_KEYWORDS:
        if kw in err_lower:
            return False

    # Temporary keywords
    for kw in TEMPORARY_ERROR_KEYWORDS:
        if kw in err_lower:
            return True

    return False
