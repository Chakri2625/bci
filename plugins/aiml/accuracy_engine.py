"""
accuracy_engine.py
==================
Real-time AI/ML Command Accuracy Ingestion, Analytics & Telemetry Engine.
Tracks classification performance, ground truth vs predictions, confusion matrices,
rolling window accuracy, and confidence metrics for BCI/ML models.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Union
import uuid

from pydantic import BaseModel, ConfigDict, Field

from models.telemetry_models import (
    AiMlTelemetry,
    HardwareMetrics,
    PredictionMetrics,
    TelemetryDomain,
    UnifiedTelemetryPacket,
)

logger = logging.getLogger("aiml_accuracy_engine")


class CommandAccuracyEvaluation(BaseModel):
    """Data model representing a single evaluated AI/ML classification event."""
    model_config = ConfigDict(extra="ignore")

    evaluation_id: str = Field(
        default_factory=lambda: f"EVAL-{uuid.uuid4().hex[:8].upper()}",
        description="Unique evaluation identifier"
    )
    command_id: Optional[str] = Field(None, description="Associated system command ID if applicable")
    session_id: str = Field("default", description="Active user session identifier")
    predicted_intent: str = Field(..., description="Classified intent (e.g. PUSH, PULL, LEFT, RIGHT, NEUTRAL)")
    ground_truth_intent: Optional[str] = Field(None, description="Actual / intended ground truth command")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Model prediction confidence score")
    probabilities: Dict[str, float] = Field(
        default_factory=dict,
        description="Probability distribution across all candidate classes"
    )
    is_accurate: Optional[bool] = Field(
        None,
        description="Explicit accuracy flag; auto-calculated from ground_truth_intent if not provided"
    )
    model_name: str = Field("Cortex-EEG-v2", description="AI/ML model architecture identifier")
    model_version: str = Field("2.1.0", description="Model version string")
    inference_latency_ms: float = Field(12.5, ge=0.0, description="Forward pass latency in milliseconds")
    preprocess_latency_ms: Optional[float] = Field(None, ge=0.0, description="Feature extraction / filter duration")
    postprocess_latency_ms: Optional[float] = Field(None, ge=0.0, description="Smoothing / debounce duration")
    source: str = Field("BCI_CORTEX", description="Origin pipeline (BCI_CORTEX, BCI_SIMULATOR, BENCHMARK, USER_FEEDBACK)")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        description="UTC ISO-8601 timestamp"
    )
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional context or raw channel features")

    def model_post_init(self, __context: Any) -> None:
        # Standardize intent strings
        self.predicted_intent = self.predicted_intent.strip().upper()
        if self.ground_truth_intent:
            self.ground_truth_intent = self.ground_truth_intent.strip().upper()
            if self.is_accurate is None:
                self.is_accurate = (self.predicted_intent == self.ground_truth_intent)
        elif self.is_accurate is None:
            # When no ground truth is provided, treat confidence >= threshold (0.65) as accurate or neutral
            self.is_accurate = (self.confidence >= 0.65)


class AccuracyMetricsSummary(BaseModel):
    """Comprehensive analytical summary of ingested AI/ML accuracy."""
    model_config = ConfigDict(extra="ignore")

    total_samples: int = 0
    accurate_samples: int = 0
    overall_accuracy_pct: float = 0.0
    mean_confidence: float = 0.0
    mean_latency_ms: float = 0.0
    rolling_accuracy_50: float = 0.0
    rolling_accuracy_100: float = 0.0
    per_intent_metrics: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    confusion_matrix: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    model_breakdown: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    last_updated: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))


class AIMLAccuracyEngine:
    """
    Thread-safe engine for ingesting AI/ML classification evaluations,
    computing rolling accuracy metrics, generating confusion matrices,
    and broadcasting standard telemetry packets.
    """

    def __init__(self, history_maxlen: int = 1000):
        self._lock = threading.Lock()
        self._history: deque[CommandAccuracyEvaluation] = deque(maxlen=history_maxlen)
        self._total_samples: int = 0
        self._accurate_samples: int = 0
        self._total_confidence: float = 0.0
        self._total_latency_ms: float = 0.0

        # Per intent: {intent: {"total": int, "accurate": int, "total_conf": float}}
        self._per_intent: Dict[str, Dict[str, Any]] = {}
        # Confusion matrix: {ground_truth: {predicted: count}}
        self._confusion_matrix: Dict[str, Dict[str, int]] = {}
        # Model breakdown: {model_name: {"total": int, "accurate": int}}
        self._model_breakdown: Dict[str, Dict[str, Any]] = {}

    def ingest(self, evaluation_data: Union[CommandAccuracyEvaluation, Dict[str, Any]]) -> Dict[str, Any]:
        """
        Ingest an accuracy evaluation, update analytics, and broadcast telemetry.
        """
        if isinstance(evaluation_data, dict):
            eval_obj = CommandAccuracyEvaluation(**evaluation_data)
        else:
            eval_obj = evaluation_data

        with self._lock:
            self._history.append(eval_obj)
            self._total_samples += 1
            if eval_obj.is_accurate:
                self._accurate_samples += 1
            self._total_confidence += eval_obj.confidence
            self._total_latency_ms += eval_obj.inference_latency_ms

            # Update per-intent stats
            intent = eval_obj.predicted_intent
            if intent not in self._per_intent:
                self._per_intent[intent] = {"total": 0, "accurate": 0, "total_conf": 0.0}
            self._per_intent[intent]["total"] += 1
            if eval_obj.is_accurate:
                self._per_intent[intent]["accurate"] += 1
            self._per_intent[intent]["total_conf"] += eval_obj.confidence

            # Update confusion matrix
            actual = eval_obj.ground_truth_intent or intent
            if actual not in self._confusion_matrix:
                self._confusion_matrix[actual] = {}
            self._confusion_matrix[actual][intent] = self._confusion_matrix[actual].get(intent, 0) + 1

            # Update model breakdown
            model_key = f"{eval_obj.model_name}:{eval_obj.model_version}"
            if model_key not in self._model_breakdown:
                self._model_breakdown[model_key] = {"total": 0, "accurate": 0}
            self._model_breakdown[model_key]["total"] += 1
            if eval_obj.is_accurate:
                self._model_breakdown[model_key]["accurate"] += 1

        # Broadcast telemetry packet asynchronously in background
        telemetry_packet = self._create_telemetry_packet(eval_obj)
        self._broadcast_packet(telemetry_packet)

        return {
            "status": "success",
            "evaluation_id": eval_obj.evaluation_id,
            "is_accurate": eval_obj.is_accurate,
            "predicted_intent": eval_obj.predicted_intent,
            "ground_truth_intent": eval_obj.ground_truth_intent,
            "confidence": eval_obj.confidence,
            "timestamp": eval_obj.timestamp,
        }

    def ingest_batch(self, evaluations: List[Union[CommandAccuracyEvaluation, Dict[str, Any]]]) -> Dict[str, Any]:
        """Ingest multiple evaluations in a single batch operation."""
        results = []
        for item in evaluations:
            results.append(self.ingest(item))
        return {
            "status": "success",
            "count": len(results),
            "results": results
        }

    def get_metrics(self) -> Dict[str, Any]:
        """Compute and return current statistical accuracy metrics."""
        with self._lock:
            total = self._total_samples
            accurate = self._accurate_samples
            overall_pct = round((accurate / total * 100.0), 2) if total > 0 else 0.0
            mean_conf = round((self._total_confidence / total), 4) if total > 0 else 0.0
            mean_lat = round((self._total_latency_ms / total), 2) if total > 0 else 0.0

            # Rolling window calculations
            recent_list = list(self._history)
            r50_items = recent_list[-50:] if len(recent_list) >= 50 else recent_list
            r50_acc = round((sum(1 for x in r50_items if x.is_accurate) / len(r50_items) * 100.0), 2) if r50_items else 0.0

            r100_items = recent_list[-100:] if len(recent_list) >= 100 else recent_list
            r100_acc = round((sum(1 for x in r100_items if x.is_accurate) / len(r100_items) * 100.0), 2) if r100_items else 0.0

            # Per intent metrics
            per_intent_out = {}
            for k, v in self._per_intent.items():
                t = v["total"]
                a = v["accurate"]
                per_intent_out[k] = {
                    "total_samples": t,
                    "accurate_samples": a,
                    "accuracy_pct": round((a / t * 100.0), 2) if t > 0 else 0.0,
                    "mean_confidence": round((v["total_conf"] / t), 4) if t > 0 else 0.0,
                }

            # Model breakdown metrics
            model_out = {}
            for m, v in self._model_breakdown.items():
                t = v["total"]
                a = v["accurate"]
                model_out[m] = {
                    "total_samples": t,
                    "accurate_samples": a,
                    "accuracy_pct": round((a / t * 100.0), 2) if t > 0 else 0.0,
                }

            summary = AccuracyMetricsSummary(
                total_samples=total,
                accurate_samples=accurate,
                overall_accuracy_pct=overall_pct,
                mean_confidence=mean_conf,
                mean_latency_ms=mean_lat,
                rolling_accuracy_50=r50_acc,
                rolling_accuracy_100=r100_acc,
                per_intent_metrics=per_intent_out,
                confusion_matrix=self._confusion_matrix,
                model_breakdown=model_out,
            )
            return summary.model_dump()

    def get_history(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """Retrieve historical accuracy records in reverse chronological order."""
        with self._lock:
            all_records = list(self._history)
            all_records.reverse()
            paged = all_records[offset: offset + limit]
            return [rec.model_dump() for rec in paged]

    def reset(self) -> None:
        """Clear all historical and aggregate accuracy tracking."""
        with self._lock:
            self._history.clear()
            self._total_samples = 0
            self._accurate_samples = 0
            self._total_confidence = 0.0
            self._total_latency_ms = 0.0
            self._per_intent.clear()
            self._confusion_matrix.clear()
            self._model_breakdown.clear()
            logger.info("AIMLAccuracyEngine state reset complete.")

    def _create_telemetry_packet(self, eval_obj: CommandAccuracyEvaluation) -> Dict[str, Any]:
        """Convert evaluation into a standard UnifiedTelemetryPacket."""
        prediction = PredictionMetrics(
            predicted_intent=eval_obj.predicted_intent,
            confidence=eval_obj.confidence,
            probabilities=eval_obj.probabilities or {eval_obj.predicted_intent: eval_obj.confidence},
            window_samples=eval_obj.metadata.get("window_samples", 128)
        )

        aiml_payload = AiMlTelemetry(
            model_name=eval_obj.model_name,
            model_version=eval_obj.model_version,
            pipeline_stage="EVALUATION",
            inference_latency_ms=eval_obj.inference_latency_ms,
            preprocess_latency_ms=eval_obj.preprocess_latency_ms,
            postprocess_latency_ms=eval_obj.postprocess_latency_ms,
            prediction=prediction,
            hardware_metrics=HardwareMetrics(
                execution_device=eval_obj.metadata.get("device", "CPU"),
                cpu_utilization_pct=eval_obj.metadata.get("cpu_pct", 15.0),
                ram_memory_used_mb=eval_obj.metadata.get("ram_mb", 256.0)
            )
        )

        packet = UnifiedTelemetryPacket(
            source_domain=TelemetryDomain.AI_ML,
            source_id=f"aiml_accuracy_engine_{eval_obj.model_name}",
            session_id=eval_obj.session_id,
            trace_id=eval_obj.evaluation_id,
            payload=aiml_payload
        )
        return packet.to_dict()

    def _broadcast_packet(self, packet_dict: Dict[str, Any]) -> None:
        """Broadcast packet to WebSocket server and update telemetry cache."""
        try:
            from api.telemetry_routes import _LATEST_TELEMETRY, _TELEMETRY_HISTORY, broadcast_telemetry_packet
            _LATEST_TELEMETRY["AI_ML"] = packet_dict
            _TELEMETRY_HISTORY.append(packet_dict)

            # Fire and forget async broadcast
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(broadcast_telemetry_packet(packet_dict))
            except RuntimeError:
                # Outside running loop, use threading or sync wrapper
                threading.Thread(
                    target=lambda: asyncio.run(broadcast_telemetry_packet(packet_dict)),
                    daemon=True
                ).start()
        except Exception as e:
            logger.debug(f"Telemetry broadcast note: {e}")


# Singleton instance
accuracy_engine = AIMLAccuracyEngine()
