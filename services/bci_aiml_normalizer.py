"""
bci_aiml_normalizer.py
======================
Dedicated BCI + AI/ML Analytics Normalization & Correlation Layer for SynaptiMesh.

Combines standardized Brain-Computer Interface (BCI) telemetry and AI/ML prediction metrics
into a single, consistent analytics representation without field overwriting or model duplication.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Union, Tuple

from pydantic import BaseModel, ConfigDict, Field

from models.telemetry_models import (
    AiMlTelemetry,
    BciTelemetry,
    FrequencyBandsTelemetry,
    MentalCommandTelemetry,
    PredictionMetrics,
    TelemetryDomain,
    UnifiedTelemetryPacket,
)

logger = logging.getLogger("bci_aiml_normalizer")

# Configurable default constants
DEFAULT_CORRELATION_WINDOW_MS: float = 2000.0  # Time window for timestamp-based correlation
MAX_BUFFER_SIZE: int = 200                      # Bounded sliding buffer limit
STALE_RETENTION_SECONDS: float = 30.0           # Retention period for unmatched telemetry


# ---------------------------------------------------------------------------
# 1. Analytics Sub-Models
# ---------------------------------------------------------------------------

class BciNormalizedAnalytics(BaseModel):
    """Normalized analytics representation of BCI telemetry."""
    model_config = ConfigDict(extra="ignore")

    headset_id: Optional[str] = Field(None, description="Headset hardware ID or model")
    headset_model: str = Field("Emotiv EPOC X", description="Headset model name")
    signal_quality_pct: float = Field(0.0, ge=0.0, le=100.0, description="Overall average signal quality percentage")
    contact_quality_status: str = Field("UNKNOWN", description="Contact quality rating (EXCELLENT, GOOD, FAIR, POOR, NO_SIGNAL, UNKNOWN)")
    contact_quality_channels: Dict[str, float] = Field(default_factory=dict, description="Contact quality per EEG channel (0.0 to 1.0)")
    mental_command: str = Field("NEUTRAL", description="Classified mental command action")
    command_power: float = Field(0.0, ge=0.0, le=1.0, description="Mental command confidence/power score")
    is_debounced: bool = Field(True, description="Whether command passed debounce threshold")
    duration_ms: Optional[float] = Field(None, ge=0.0, description="Command duration in ms")
    frequency_bands: Optional[Dict[str, Optional[float]]] = Field(None, description="Frequency band power spectral densities")
    battery_pct: int = Field(100, ge=0, le=100, description="Battery level percentage")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    session_id: Optional[str] = Field("default", description="Session identifier")
    trace_id: Optional[str] = Field(None, description="Distributed trace identifier")
    command_id: Optional[str] = Field(None, description="Associated system command ID")


class AiMlNormalizedAnalytics(BaseModel):
    """Normalized analytics representation of AI/ML model predictions."""
    model_config = ConfigDict(extra="ignore")

    model_name: str = Field("CognitiveActionRouter", description="AI/ML model identifier")
    model_version: str = Field("1.0.0", description="Model semantic version")
    predicted_intent: str = Field("NEUTRAL", description="Predicted class intent or action")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Prediction confidence score")
    probabilities: Dict[str, float] = Field(default_factory=dict, description="Probability distribution across candidate classes")
    inference_latency_ms: float = Field(0.0, ge=0.0, description="Forward pass latency in ms")
    pipeline_stage: str = Field("INFERENCE", description="Pipeline stage")
    window_samples: Optional[int] = Field(None, description="Inference window sample count")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    session_id: Optional[str] = Field("default", description="Session identifier")
    trace_id: Optional[str] = Field(None, description="Distributed trace identifier")
    command_id: Optional[str] = Field(None, description="Associated system command ID")


class CorrelationMetadata(BaseModel):
    """Metadata tracking how BCI and AI/ML analytics were correlated."""
    model_config = ConfigDict(extra="ignore")

    is_correlated: bool = Field(False, description="Whether BCI and AI/ML sources were successfully correlated")
    correlation_method: str = Field("UNMATCHED", description="Method used (COMMAND_ID, TRACE_ID, SESSION_TIMESTAMP, TIMESTAMP_WINDOW, UNMATCHED)")
    intent_match: bool = Field(False, description="Whether BCI mental command matches AI/ML predicted intent")
    time_delta_ms: Optional[float] = Field(None, description="Time delta between BCI and AI/ML timestamps in milliseconds")
    correlation_window_ms: float = Field(DEFAULT_CORRELATION_WINDOW_MS, description="Configured correlation time window")


class BciAiMlCombinedAnalytics(BaseModel):
    """
    Combined analytics representation preserving BCI and AI/ML source ownership.
    BCI metrics live under `.bci` and AI/ML metrics live under `.aiml`.
    """
    model_config = ConfigDict(extra="ignore")

    combined_id: str = Field(
        default_factory=lambda: f"COMB-{int(time.time() * 1000)}",
        description="Unique combined analytics identifier"
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        description="ISO-8601 UTC timestamp of combined analytics creation"
    )
    session_id: Optional[str] = Field("default", description="Active user session identifier")
    trace_id: Optional[str] = Field(None, description="Distributed trace identifier")
    command_id: Optional[str] = Field(None, description="Associated command ID")
    status: str = Field("COMBINED_ACTIVE", description="Combined analytics status (COMBINED_ACTIVE, BCI_ONLY, AIML_ONLY, UNCORRELATED)")
    bci: Optional[BciNormalizedAnalytics] = Field(None, description="Normalized BCI analytics sub-object")
    aiml: Optional[AiMlNormalizedAnalytics] = Field(None, description="Normalized AI/ML analytics sub-object")
    correlation: CorrelationMetadata = Field(default_factory=CorrelationMetadata, description="Correlation breakdown metadata")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to clean JSON-serializable dictionary."""
        return self.model_dump(exclude_none=True)


# ---------------------------------------------------------------------------
# 2. Normalization & Correlation Service
# ---------------------------------------------------------------------------

class BciAiMlNormalizerService:
    """
    Thread-safe service for normalizing BCI and AI/ML telemetry into standard analytics structures,
    correlating them across command IDs, trace IDs, session timestamps, and time windows,
    and producing combined analytics packets.
    """

    def __init__(self, correlation_window_ms: float = DEFAULT_CORRELATION_WINDOW_MS, max_buffer_size: int = MAX_BUFFER_SIZE):
        self.correlation_window_ms = float(correlation_window_ms)
        self.max_buffer_size = max_buffer_size
        self._lock = threading.Lock()

        # Bounded sliding buffers for unmatched telemetry frames
        # Stored as tuples: (timestamp_epoch_sec, normalized_model)
        self._bci_buffer: deque[Tuple[float, BciNormalizedAnalytics]] = deque(maxlen=self.max_buffer_size)
        self._aiml_buffer: deque[Tuple[float, AiMlNormalizedAnalytics]] = deque(maxlen=self.max_buffer_size)

        # Cache of latest combined analytics
        self._latest_combined: Optional[BciAiMlCombinedAnalytics] = None

    # -----------------------------------------------------------------------
    # Normalization Helpers
    # -----------------------------------------------------------------------

    def normalize_bci(
        self,
        bci_input: Union[BciTelemetry, Dict[str, Any]],
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        timestamp: Optional[str] = None
    ) -> Optional[BciNormalizedAnalytics]:
        """
        Normalize BCI telemetry into BciNormalizedAnalytics.
        Supports BciTelemetry instances or raw dict structures. Returns None on unparseable input.
        """
        if bci_input is None:
            return None

        try:
            if isinstance(bci_input, BciTelemetry):
                data = bci_input.model_dump()
            elif isinstance(bci_input, dict):
                # If wrapped in UnifiedTelemetryPacket payload format
                data = bci_input.get("payload") if isinstance(bci_input.get("payload"), dict) else bci_input
            else:
                return None

            # Extract headset information
            headset_id = data.get("headset_id") or data.get("headsetId")
            headset_model = data.get("headset_model") or data.get("headsetModel") or "Emotiv EPOC X"

            # Extract signal quality & channels
            cq_channels: Dict[str, float] = {}
            raw_sq = data.get("signal_quality") or data.get("signalQuality") or data.get("contact_quality") or data.get("contactQuality") or {}
            
            if isinstance(raw_sq, dict):
                for k, v in raw_sq.items():
                    try:
                        cq_channels[str(k).upper()] = float(v)
                    except (ValueError, TypeError):
                        pass
            
            # Compute average signal quality %
            if cq_channels:
                avg_cq = sum(cq_channels.values()) / len(cq_channels)
                # If values are 0.0-1.0 scale vs 0-100 scale
                signal_quality_pct = avg_cq * 100.0 if avg_cq <= 1.0 else avg_cq
            elif isinstance(raw_sq, (int, float)):
                signal_quality_pct = float(raw_sq) if float(raw_sq) <= 100.0 else 100.0
            else:
                signal_quality_pct = 0.0

            # Contact quality status rating
            if signal_quality_pct >= 85.0:
                cq_status = "EXCELLENT"
            elif signal_quality_pct >= 70.0:
                cq_status = "GOOD"
            elif signal_quality_pct >= 40.0:
                cq_status = "FAIR"
            elif signal_quality_pct > 0.0:
                cq_status = "POOR"
            else:
                # Check string signal_quality / contact_quality fallback
                cq_str = str(data.get("contact_quality") or data.get("signal_quality") or "UNKNOWN").upper()
                if cq_str in ("EXCELLENT", "GOOD", "FAIR", "POOR", "NO_SIGNAL"):
                    cq_status = cq_str
                else:
                    cq_status = "UNKNOWN"

            # Extract mental command
            cmd_data = data.get("mental_command") or data.get("mentalCommand")
            if isinstance(cmd_data, MentalCommandTelemetry):
                action = cmd_data.action.upper()
                power = cmd_data.power
                is_debounced = cmd_data.is_debounced
                duration_ms = cmd_data.duration_ms
            elif isinstance(cmd_data, dict) and cmd_data:
                action = str(cmd_data.get("action") or cmd_data.get("command") or "NEUTRAL").upper()
                power = float(cmd_data.get("power", 0.0))
                is_debounced = bool(cmd_data.get("is_debounced", True))
                duration_ms = float(cmd_data["duration_ms"]) if cmd_data.get("duration_ms") is not None else None
            else:
                action = str(data.get("command") or data.get("action") or "NEUTRAL").upper()
                power = float(data.get("power", 0.0))
                is_debounced = True
                duration_ms = None

            if action == "NEUTRAL":
                override_cmd = data.get("command") or data.get("action")
                if override_cmd:
                    action = str(override_cmd).upper()
                if data.get("power") is not None and power == 0.0:
                    power = float(data["power"])

            # Extract frequency bands
            freq_data = data.get("frequency_bands") or data.get("frequencyBands") or data.get("band_powers") or data.get("bandPowers")
            freq_dict: Optional[Dict[str, Optional[float]]] = None
            if isinstance(freq_data, FrequencyBandsTelemetry):
                freq_dict = freq_data.model_dump(exclude_none=True)
            elif isinstance(freq_data, dict):
                freq_dict = {k: float(v) for k, v in freq_data.items() if v is not None and isinstance(v, (int, float))}

            # Battery level
            battery = int(data.get("battery_pct") or data.get("battery") or 100)
            battery = max(0, min(100, battery))

            # Metadata IDs & timestamp
            ts_str = timestamp or data.get("timestamp") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            sess_id = session_id or data.get("session_id") or "default"
            tr_id = trace_id or data.get("trace_id")
            cmd_id = data.get("command_id")

            return BciNormalizedAnalytics(
                headset_id=headset_id,
                headset_model=headset_model,
                signal_quality_pct=round(signal_quality_pct, 2),
                contact_quality_status=cq_status,
                contact_quality_channels=cq_channels,
                mental_command=action,
                command_power=round(power, 4),
                is_debounced=is_debounced,
                duration_ms=duration_ms,
                frequency_bands=freq_dict,
                battery_pct=battery,
                timestamp=ts_str,
                session_id=sess_id,
                trace_id=tr_id,
                command_id=cmd_id
            )

        except Exception as exc:
            logger.warning(f"Error normalizing BCI telemetry: {exc}")
            return None

    def normalize_aiml(
        self,
        aiml_input: Union[PredictionMetrics, AiMlTelemetry, Dict[str, Any]],
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        timestamp: Optional[str] = None
    ) -> Optional[AiMlNormalizedAnalytics]:
        """
        Normalize AI/ML prediction telemetry into AiMlNormalizedAnalytics.
        Supports PredictionMetrics, AiMlTelemetry, or raw dict structures. Returns None on unparseable input.
        """
        if aiml_input is None:
            return None

        try:
            model_name = "CognitiveActionRouter"
            model_version = "1.0.0"
            pipeline_stage = "INFERENCE"
            latency_ms = 0.0
            predicted_intent = "NEUTRAL"
            confidence = 0.0
            probabilities: Dict[str, float] = {}
            window_samples: Optional[int] = None

            if isinstance(aiml_input, PredictionMetrics):
                predicted_intent = aiml_input.predicted_intent.upper()
                confidence = aiml_input.confidence
                probabilities = dict(aiml_input.probabilities)
                window_samples = aiml_input.window_samples

            elif isinstance(aiml_input, AiMlTelemetry):
                model_name = aiml_input.model_name
                model_version = aiml_input.model_version
                pipeline_stage = aiml_input.pipeline_stage
                latency_ms = aiml_input.inference_latency_ms
                pred = aiml_input.prediction
                predicted_intent = pred.predicted_intent.upper()
                confidence = pred.confidence
                probabilities = dict(pred.probabilities)
                window_samples = pred.window_samples

            elif isinstance(aiml_input, dict):
                # If wrapped in UnifiedTelemetryPacket payload format
                data = aiml_input.get("payload") if isinstance(aiml_input.get("payload"), dict) else aiml_input
                
                model_name = data.get("model_name") or data.get("model") or "CognitiveActionRouter"
                model_version = data.get("model_version") or data.get("version") or "1.0.0"
                pipeline_stage = data.get("pipeline_stage") or "INFERENCE"
                latency_ms = float(data.get("inference_latency_ms") or data.get("latency_ms") or 0.0)

                # Check if nested 'prediction' object exists
                pred_data = data.get("prediction")
                if isinstance(pred_data, PredictionMetrics):
                    predicted_intent = pred_data.predicted_intent.upper()
                    confidence = pred_data.confidence
                    probabilities = dict(pred_data.probabilities)
                    window_samples = pred_data.window_samples
                elif isinstance(pred_data, dict) and pred_data:
                    predicted_intent = str(pred_data.get("predicted_intent") or pred_data.get("intent") or "NEUTRAL").upper()
                    confidence = float(pred_data.get("confidence", 0.0))
                    raw_probs = pred_data.get("probabilities", {})
                    if isinstance(raw_probs, dict):
                        probabilities = {k: float(v) for k, v in raw_probs.items()}
                    window_samples = pred_data.get("window_samples")
                else:
                    predicted_intent = str(data.get("predicted_intent") or data.get("intent") or data.get("command") or "NEUTRAL").upper()
                    confidence = float(data.get("confidence", 0.0))
                    raw_probs = data.get("probabilities", {})
                    if isinstance(raw_probs, dict):
                        probabilities = {k: float(v) for k, v in raw_probs.items()}
                    window_samples = data.get("window_samples")

                if predicted_intent == "NEUTRAL":
                    override_intent = data.get("predicted_intent") or data.get("intent") or data.get("command")
                    if override_intent:
                        predicted_intent = str(override_intent).upper()

            else:
                return None

            # Metadata IDs & timestamp
            ts_str = timestamp or (aiml_input.get("timestamp") if isinstance(aiml_input, dict) else None) or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            sess_id = session_id or (aiml_input.get("session_id") if isinstance(aiml_input, dict) else None) or "default"
            tr_id = trace_id or (aiml_input.get("trace_id") if isinstance(aiml_input, dict) else None)
            cmd_id = aiml_input.get("command_id") if isinstance(aiml_input, dict) else None

            return AiMlNormalizedAnalytics(
                model_name=model_name,
                model_version=model_version,
                predicted_intent=predicted_intent,
                confidence=round(confidence, 4),
                probabilities=probabilities,
                inference_latency_ms=round(latency_ms, 2),
                pipeline_stage=pipeline_stage,
                window_samples=window_samples,
                timestamp=ts_str,
                session_id=sess_id,
                trace_id=tr_id,
                command_id=cmd_id
            )

        except Exception as exc:
            logger.warning(f"Error normalizing AI/ML telemetry: {exc}")
            return None

    # -----------------------------------------------------------------------
    # Correlation & Combination Logic
    # -----------------------------------------------------------------------

    def _parse_iso_timestamp(self, ts_str: str) -> float:
        """Parse ISO-8601 string to epoch timestamp in seconds."""
        try:
            if ts_str.endswith("Z"):
                ts_str = ts_str[:-1] + "+00:00"
            dt = datetime.fromisoformat(ts_str)
            return dt.timestamp()
        except Exception:
            return time.time()

    def combine(
        self,
        bci: Optional[BciNormalizedAnalytics],
        aiml: Optional[AiMlNormalizedAnalytics],
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        command_id: Optional[str] = None
    ) -> BciAiMlCombinedAnalytics:
        """
        Combine normalized BCI analytics and AI/ML analytics, evaluating correlation criteria in priority order:
          1. command_id match
          2. trace_id match
          3. session_id + compatible timestamp
          4. timestamp-window correlation
        """
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        sess_id = session_id or (bci.session_id if bci else None) or (aiml.session_id if aiml else None) or "default"
        tr_id = trace_id or (bci.trace_id if bci else None) or (aiml.trace_id if aiml else None)
        cmd_id = command_id or (bci.command_id if bci else None) or (aiml.command_id if aiml else None)

        # If only one source is available
        if bci is not None and aiml is None:
            return BciAiMlCombinedAnalytics(
                timestamp=bci.timestamp,
                session_id=sess_id,
                trace_id=tr_id,
                command_id=cmd_id,
                status="BCI_ONLY",
                bci=bci,
                aiml=None,
                correlation=CorrelationMetadata(
                    is_correlated=False,
                    correlation_method="BCI_UNMATCHED",
                    intent_match=False,
                    time_delta_ms=None,
                    correlation_window_ms=self.correlation_window_ms
                )
            )

        if aiml is not None and bci is None:
            return BciAiMlCombinedAnalytics(
                timestamp=aiml.timestamp,
                session_id=sess_id,
                trace_id=tr_id,
                command_id=cmd_id,
                status="AIML_ONLY",
                bci=None,
                aiml=aiml,
                correlation=CorrelationMetadata(
                    is_correlated=False,
                    correlation_method="AIML_UNMATCHED",
                    intent_match=False,
                    time_delta_ms=None,
                    correlation_window_ms=self.correlation_window_ms
                )
            )

        if bci is None and aiml is None:
            return BciAiMlCombinedAnalytics(
                timestamp=now_iso,
                session_id=sess_id,
                trace_id=tr_id,
                command_id=cmd_id,
                status="EMPTY",
                bci=None,
                aiml=None,
                correlation=CorrelationMetadata(
                    is_correlated=False,
                    correlation_method="EMPTY",
                    intent_match=False,
                    time_delta_ms=None,
                    correlation_window_ms=self.correlation_window_ms
                )
            )

        # Both BCI and AI/ML are present: evaluate correlation
        bci_time = self._parse_iso_timestamp(bci.timestamp)
        aiml_time = self._parse_iso_timestamp(aiml.timestamp)
        delta_ms = abs(bci_time - aiml_time) * 1000.0

        intent_match = (bci.mental_command == aiml.predicted_intent)
        is_correlated = False
        method = "UNMATCHED"

        # Priority 1: command_id match
        if bci.command_id and aiml.command_id and bci.command_id == aiml.command_id:
            is_correlated = True
            method = "COMMAND_ID"

        # Priority 2: trace_id match
        elif bci.trace_id and aiml.trace_id and bci.trace_id == aiml.trace_id:
            is_correlated = True
            method = "TRACE_ID"

        # Priority 3: session_id + compatible timestamp window
        elif bci.session_id and aiml.session_id and bci.session_id == aiml.session_id and delta_ms <= self.correlation_window_ms:
            is_correlated = True
            method = "SESSION_TIMESTAMP"

        # Priority 4: timestamp-window correlation (when explicit IDs are unavailable/different)
        elif delta_ms <= self.correlation_window_ms:
            is_correlated = True
            method = "TIMESTAMP_WINDOW"

        status_str = "COMBINED_ACTIVE" if is_correlated else "UNCORRELATED"

        combined = BciAiMlCombinedAnalytics(
            timestamp=max(bci.timestamp, aiml.timestamp),
            session_id=sess_id,
            trace_id=tr_id,
            command_id=cmd_id,
            status=status_str,
            bci=bci,
            aiml=aiml,
            correlation=CorrelationMetadata(
                is_correlated=is_correlated,
                correlation_method=method,
                intent_match=intent_match,
                time_delta_ms=round(delta_ms, 2),
                correlation_window_ms=self.correlation_window_ms
            )
        )

        with self._lock:
            self._latest_combined = combined

        return combined

    # -----------------------------------------------------------------------
    # Async / Sliding Buffer Ingestion
    # -----------------------------------------------------------------------

    def _clean_stale_buffers(self, current_time: float) -> None:
        """Remove stale items from sliding buffers exceeding STALE_RETENTION_SECONDS."""
        cutoff = current_time - STALE_RETENTION_SECONDS

        while self._bci_buffer and self._bci_buffer[0][0] < cutoff:
            self._bci_buffer.popleft()

        while self._aiml_buffer and self._aiml_buffer[0][0] < cutoff:
            self._aiml_buffer.popleft()

    def ingest_bci(
        self,
        bci_payload: Union[BciTelemetry, Dict[str, Any]],
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None
    ) -> Tuple[BciNormalizedAnalytics, BciAiMlCombinedAnalytics]:
        """
        Ingest incoming BCI telemetry, search buffer for matching AI/ML prediction frame,
        correlate if possible, or retain in bounded buffer for async arrival.
        """
        norm_bci = self.normalize_bci(bci_payload, session_id=session_id, trace_id=trace_id)
        if norm_bci is None:
            # Fallback for unparseable input
            norm_bci = BciNormalizedAnalytics(
                mental_command="NEUTRAL",
                timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                session_id=session_id or "default",
                trace_id=trace_id
            )

        now_sec = time.time()

        with self._lock:
            self._clean_stale_buffers(now_sec)

            # Search _aiml_buffer for correlation
            matched_idx = -1
            best_aiml: Optional[AiMlNormalizedAnalytics] = None

            for idx, (aiml_ts, candidate_aiml) in enumerate(self._aiml_buffer):
                # 1. Match by command_id
                if norm_bci.command_id and candidate_aiml.command_id and norm_bci.command_id == candidate_aiml.command_id:
                    matched_idx = idx
                    best_aiml = candidate_aiml
                    break
                # 2. Match by trace_id
                if norm_bci.trace_id and candidate_aiml.trace_id and norm_bci.trace_id == candidate_aiml.trace_id:
                    matched_idx = idx
                    best_aiml = candidate_aiml
                    break
                # 3. Match by session_id & timestamp window
                bci_epoch = self._parse_iso_timestamp(norm_bci.timestamp)
                if abs(bci_epoch - aiml_ts) * 1000.0 <= self.correlation_window_ms:
                    if norm_bci.session_id and candidate_aiml.session_id and norm_bci.session_id == candidate_aiml.session_id:
                        matched_idx = idx
                        best_aiml = candidate_aiml
                        break
                    elif best_aiml is None:
                        matched_idx = idx
                        best_aiml = candidate_aiml

            if matched_idx >= 0 and best_aiml is not None:
                # Remove matched AI/ML frame from buffer
                del self._aiml_buffer[matched_idx]

            if best_aiml is None:
                # Store normalized BCI in buffer for future AI/ML arrival
                bci_epoch = self._parse_iso_timestamp(norm_bci.timestamp)
                self._bci_buffer.append((bci_epoch, norm_bci))

        combined = self.combine(bci=norm_bci, aiml=best_aiml, session_id=session_id, trace_id=trace_id)
        return norm_bci, combined

    def ingest_aiml(
        self,
        aiml_payload: Union[PredictionMetrics, AiMlTelemetry, Dict[str, Any]],
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None
    ) -> Tuple[AiMlNormalizedAnalytics, BciAiMlCombinedAnalytics]:
        """
        Ingest incoming AI/ML prediction telemetry, search buffer for matching BCI frame,
        correlate if possible, or retain in bounded buffer for async arrival.
        """
        norm_aiml = self.normalize_aiml(aiml_payload, session_id=session_id, trace_id=trace_id)
        if norm_aiml is None:
            norm_aiml = AiMlNormalizedAnalytics(
                predicted_intent="NEUTRAL",
                timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                session_id=session_id or "default",
                trace_id=trace_id
            )

        now_sec = time.time()

        with self._lock:
            self._clean_stale_buffers(now_sec)

            # Search _bci_buffer for correlation
            matched_idx = -1
            best_bci: Optional[BciNormalizedAnalytics] = None

            for idx, (bci_ts, candidate_bci) in enumerate(self._bci_buffer):
                # 1. Match by command_id
                if norm_aiml.command_id and candidate_bci.command_id and norm_aiml.command_id == candidate_bci.command_id:
                    matched_idx = idx
                    best_bci = candidate_bci
                    break
                # 2. Match by trace_id
                if norm_aiml.trace_id and candidate_bci.trace_id and norm_aiml.trace_id == candidate_bci.trace_id:
                    matched_idx = idx
                    best_bci = candidate_bci
                    break
                # 3. Match by session_id & timestamp window
                aiml_epoch = self._parse_iso_timestamp(norm_aiml.timestamp)
                if abs(aiml_epoch - bci_ts) * 1000.0 <= self.correlation_window_ms:
                    if norm_aiml.session_id and candidate_bci.session_id and norm_aiml.session_id == candidate_bci.session_id:
                        matched_idx = idx
                        best_bci = candidate_bci
                        break
                    elif best_bci is None:
                        matched_idx = idx
                        best_bci = candidate_bci

            if matched_idx >= 0 and best_bci is not None:
                # Remove matched BCI frame from buffer
                del self._bci_buffer[matched_idx]

            if best_bci is None:
                # Store normalized AI/ML in buffer for future BCI arrival
                aiml_epoch = self._parse_iso_timestamp(norm_aiml.timestamp)
                self._aiml_buffer.append((aiml_epoch, norm_aiml))

        combined = self.combine(bci=best_bci, aiml=norm_aiml, session_id=session_id, trace_id=trace_id)
        return norm_aiml, combined

    def process_telemetry_packet(self, packet: UnifiedTelemetryPacket) -> Optional[BciAiMlCombinedAnalytics]:
        """
        Process a standard UnifiedTelemetryPacket envelope.
        If domain is BCI or AI_ML, normalizes and correlates telemetry and returns combined analytics.
        """
        domain_str = packet.source_domain.value if hasattr(packet.source_domain, "value") else str(packet.source_domain)
        payload = packet.payload

        if domain_str == "BCI":
            _, combined = self.ingest_bci(payload, session_id=packet.session_id, trace_id=packet.trace_id)
            return combined

        elif domain_str == "AI_ML":
            _, combined = self.ingest_aiml(payload, session_id=packet.session_id, trace_id=packet.trace_id)
            return combined

        return None

    def create_unified_transport_packet(self, combined: BciAiMlCombinedAnalytics) -> UnifiedTelemetryPacket:
        """Wrap BciAiMlCombinedAnalytics inside standard UnifiedTelemetryPacket transport envelope."""
        return UnifiedTelemetryPacket(
            source_domain=TelemetryDomain.BCI,
            source_id="bci_aiml_normalizer",
            session_id=combined.session_id,
            trace_id=combined.trace_id,
            payload=combined.to_dict()
        )

    def get_latest_combined(self) -> Optional[BciAiMlCombinedAnalytics]:
        """Retrieve the latest cached BciAiMlCombinedAnalytics snapshot."""
        with self._lock:
            return self._latest_combined


# Global singleton instance
bci_aiml_normalizer = BciAiMlNormalizerService()
