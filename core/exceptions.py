from typing import Optional, Any

class SynaptiMeshError(Exception):
    """Base exception for all SynaptiMesh errors."""
    def __init__(self, message: str, error_code: str = "UNKNOWN_ERROR", details: Optional[Any] = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details

class ValidationError(SynaptiMeshError):
    """Raised when command validation fails."""
    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(message, error_code="VALIDATION_FAILED", details=details)

class RoutingError(SynaptiMeshError):
    """Raised when routing/resolution fails."""
    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(message, error_code="COMMAND_NOT_FOUND", details=details)

class ExecutionError(SynaptiMeshError):
    """Raised when an application execution fails."""
    def __init__(self, message: str, error_code: str = "EXECUTION_FAILED", details: Optional[Any] = None):
        super().__init__(message, error_code=error_code, details=details)

class AppNotFoundError(ExecutionError):
    """Raised when an application is not found."""
    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(message, error_code="APP_NOT_FOUND", details=details)

class AutomationError(ExecutionError):
    """Raised during automation failures (e.g., Playwright, pywinauto)."""
    def __init__(self, message: str, error_code: str = "AUTOMATION_ERROR", details: Optional[Any] = None):
        super().__init__(message, error_code=error_code, details=details)

class ExecutionTimeoutError(ExecutionError):
    """Raised when execution times out."""
    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(message, error_code="EXECUTION_TIMEOUT", details=details)

class ExecutionCancelledError(ExecutionError):
    """Raised when execution is cancelled."""
    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(message, error_code="EXECUTION_CANCELLED", details=details)

class DomainError(ExecutionError):
    """Raised when a domain-specific execution error occurs."""
    def __init__(self, message: str, error_code: str = "DOMAIN_ERROR", details: Optional[Any] = None):
        super().__init__(message, error_code=error_code, details=details)

class DomainExecutionError(DomainError):
    """Raised when domain execution fails."""
    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(message, error_code="DOMAIN_EXECUTION_FAILED", details=details)

class DomainTimeoutError(DomainError):
    """Raised when domain execution times out."""
    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(message, error_code="DOMAIN_TIMEOUT", details=details)

class DomainCommunicationError(DomainError):
    """Raised when domain communication fails."""
    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(message, error_code="DOMAIN_COMMUNICATION_ERROR", details=details)


