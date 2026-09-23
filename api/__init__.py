"""
API Module for SynaptiMesh.
"""

from api.event_history_routes import router as event_history_router

__all__ = ["event_history_router"]
