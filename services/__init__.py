"""Execution services used by the SynaptiMesh orchestration layer."""

from .embedded_telemetry_normalizer import (
    normalize_embedded_telemetry,
    subplugin_to_telemetry_packet,
)
from .iot_telemetry_normalizer import normalize_iot_telemetry