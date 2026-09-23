"""
test_bci_aiml_normalization.py
===============================
Unit and Integration Tests for BCI + AI/ML Analytics Normalization and Correlation Layer.
"""

from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from main import app
from models.telemetry_models import (
    AiMlTelemetry,
    BciTelemetry,
    FrequencyBandsTelemetry,
    MentalCommandTelemetry,
    PredictionMetrics,
    TelemetryDomain,
    UnifiedTelemetryPacket,
)
from services.bci_aiml_normalizer import (
    BciAiMlNormalizerService,
    BciAiMlCombinedAnalytics,
    BciNormalizedAnalytics,
    AiMlNormalizedAnalytics,
    bci_aiml_normalizer,
)


@pytest.fixture
def normalizer():
    """Create a fresh instance of BciAiMlNormalizerService for testing."""
    return BciAiMlNormalizerService(correlation_window_ms=2000.0, max_buffer_size=50)


# ---------------------------------------------------------------------------
# 1. BCI Normalization Tests
# ---------------------------------------------------------------------------

def test_bci_telemetry_model_normalization(normalizer):
    bci = BciTelemetry(
        headset_id="EPOC-X-TEST-01",
        headset_model="Emotiv EPOC X",
        signal_quality={"AF3": 1.0, "F7": 0.8, "F3": 0.9, "FC5": 0.7},
        battery_pct=92,
        mental_command=MentalCommandTelemetry(
            action="LEFT",
            power=0.85,
            is_debounced=True,
            duration_ms=450.0
        ),
        frequency_bands=FrequencyBandsTelemetry(
            alpha_uv2=24.5,
            beta_low_uv2=12.3
        )
    )

    norm = normalizer.normalize_bci(bci, session_id="sess_1", trace_id="trace_1")
    assert norm is not None
    assert norm.headset_id == "EPOC-X-TEST-01"
    assert norm.headset_model == "Emotiv EPOC X"
    assert norm.signal_quality_pct == 85.0
    assert norm.contact_quality_status == "EXCELLENT"
    assert norm.contact_quality_channels["AF3"] == 1.0
    assert norm.mental_command == "LEFT"
    assert norm.command_power == 0.85
    assert norm.is_debounced is True
    assert norm.duration_ms == 450.0
    assert norm.frequency_bands["alpha_uv2"] == 24.5
    assert norm.battery_pct == 92
    assert norm.session_id == "sess_1"
    assert norm.trace_id == "trace_1"


def test_bci_raw_dict_normalization(normalizer):
    raw_bci = {
        "headsetId": "EPOC-X-RAW",
        "contact_quality": {"AF3": 0.5, "F7": 0.4},
        "command": "PUSH",
        "power": 0.72,
        "battery": 80,
        "band_powers": {"theta_uv2": 15.0}
    }

    norm = normalizer.normalize_bci(raw_bci)
    assert norm is not None
    assert norm.headset_id == "EPOC-X-RAW"
    assert norm.signal_quality_pct == 45.0
    assert norm.contact_quality_status == "FAIR"
    assert norm.mental_command == "PUSH"
    assert norm.command_power == 0.72
    assert norm.frequency_bands["theta_uv2"] == 15.0


def test_bci_normalization_invalid_input(normalizer):
    assert normalizer.normalize_bci(None) is None
    assert normalizer.normalize_bci("invalid_string_input") is None


# ---------------------------------------------------------------------------
# 2. AI/ML Normalization Tests
# ---------------------------------------------------------------------------

def test_aiml_prediction_metrics_normalization(normalizer):
    pred = PredictionMetrics(
        predicted_intent="LEFT",
        confidence=0.88,
        probabilities={"LEFT": 0.88, "RIGHT": 0.08, "NEUTRAL": 0.04},
        window_samples=128
    )

    norm = normalizer.normalize_aiml(pred, session_id="sess_1", trace_id="trace_1")
    assert norm is not None
    assert norm.predicted_intent == "LEFT"
    assert norm.confidence == 0.88
    assert norm.probabilities["LEFT"] == 0.88
    assert norm.window_samples == 128
    assert norm.model_name == "CognitiveActionRouter"
    assert norm.session_id == "sess_1"
    assert norm.trace_id == "trace_1"


def test_aiml_telemetry_model_normalization(normalizer):
    aiml = AiMlTelemetry(
        model_name="NeuralIntentClassifier",
        model_version="2.0.0",
        pipeline_stage="INFERENCE",
        inference_latency_ms=14.2,
        prediction=PredictionMetrics(
            predicted_intent="PULL",
            confidence=0.91,
            probabilities={"PULL": 0.91, "PUSH": 0.09}
        )
    )

    norm = normalizer.normalize_aiml(aiml)
    assert norm is not None
    assert norm.model_name == "NeuralIntentClassifier"
    assert norm.model_version == "2.0.0"
    assert norm.pipeline_stage == "INFERENCE"
    assert norm.inference_latency_ms == 14.2
    assert norm.predicted_intent == "PULL"
    assert norm.confidence == 0.91


def test_aiml_raw_dict_normalization(normalizer):
    raw_aiml = {
        "model": "CustomModel",
        "intent": "RIGHT",
        "confidence": 0.75,
        "latency_ms": 8.5,
        "probabilities": {"RIGHT": 0.75, "NEUTRAL": 0.25}
    }

    norm = normalizer.normalize_aiml(raw_aiml)
    assert norm is not None
    assert norm.model_name == "CustomModel"
    assert norm.predicted_intent == "RIGHT"
    assert norm.confidence == 0.75
    assert norm.inference_latency_ms == 8.5


def test_aiml_normalization_invalid_input(normalizer):
    assert normalizer.normalize_aiml(None) is None
    assert normalizer.normalize_aiml(12345) is None


# ---------------------------------------------------------------------------
# 3. Combination & Preservation Tests
# ---------------------------------------------------------------------------

def test_bci_aiml_combination_structure(normalizer):
    bci = normalizer.normalize_bci(
        BciTelemetry(
            headset_id="EPOC-1",
            mental_command=MentalCommandTelemetry(action="RIGHT", power=0.82)
        ),
        session_id="sess_comb",
        trace_id="tr_comb"
    )

    aiml = normalizer.normalize_aiml(
        PredictionMetrics(
            predicted_intent="RIGHT",
            confidence=0.89,
            probabilities={"RIGHT": 0.89, "NEUTRAL": 0.11}
        ),
        session_id="sess_comb",
        trace_id="tr_comb"
    )

    combined = normalizer.combine(bci, aiml)
    assert combined is not None
    assert combined.status == "COMBINED_ACTIVE"
    assert combined.session_id == "sess_comb"
    assert combined.trace_id == "tr_comb"

    # Verify namespace separation
    assert combined.bci is not None
    assert combined.aiml is not None
    assert combined.bci.mental_command == "RIGHT"
    assert combined.bci.command_power == 0.82
    assert combined.aiml.predicted_intent == "RIGHT"
    assert combined.aiml.confidence == 0.89

    # Verify correlation metadata
    assert combined.correlation.is_correlated is True
    assert combined.correlation.intent_match is True
    assert combined.correlation.correlation_method in ("TRACE_ID", "SESSION_TIMESTAMP", "TIMESTAMP_WINDOW")


# ---------------------------------------------------------------------------
# 4. Correlation Tests
# ---------------------------------------------------------------------------

def test_command_id_correlation(normalizer):
    bci = BciTelemetry(
        mental_command=MentalCommandTelemetry(action="LEFT", power=0.8),
    )
    norm_bci = normalizer.normalize_bci(bci)
    norm_bci.command_id = "CMD-1001"

    aiml = PredictionMetrics(predicted_intent="LEFT", confidence=0.85)
    norm_aiml = normalizer.normalize_aiml(aiml)
    norm_aiml.command_id = "CMD-1001"

    combined = normalizer.combine(norm_bci, norm_aiml)
    assert combined.correlation.is_correlated is True
    assert combined.correlation.correlation_method == "COMMAND_ID"
    assert combined.correlation.intent_match is True


def test_trace_id_correlation(normalizer):
    norm_bci = normalizer.normalize_bci(
        BciTelemetry(mental_command=MentalCommandTelemetry(action="PUSH", power=0.9)),
        trace_id="TRACE-99"
    )
    norm_aiml = normalizer.normalize_aiml(
        PredictionMetrics(predicted_intent="PUSH", confidence=0.92),
        trace_id="TRACE-99"
    )

    combined = normalizer.combine(norm_bci, norm_aiml)
    assert combined.correlation.is_correlated is True
    assert combined.correlation.correlation_method == "TRACE_ID"


def test_session_timestamp_correlation(normalizer):
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    norm_bci = normalizer.normalize_bci(
        BciTelemetry(mental_command=MentalCommandTelemetry(action="PULL", power=0.75)),
        session_id="SESS-42",
        timestamp=now_iso
    )
    norm_aiml = normalizer.normalize_aiml(
        PredictionMetrics(predicted_intent="PULL", confidence=0.78),
        session_id="SESS-42",
        timestamp=now_iso
    )

    combined = normalizer.combine(norm_bci, norm_aiml)
    assert combined.correlation.is_correlated is True
    assert combined.correlation.correlation_method in ("SESSION_TIMESTAMP", "TIMESTAMP_WINDOW")


def test_async_bci_first_arrival(normalizer):
    raw_bci = {
        "command": "LEFT",
        "power": 0.8,
        "trace_id": "ASYNC-TRACE-01",
        "session_id": "sess_async"
    }
    raw_aiml = {
        "intent": "LEFT",
        "confidence": 0.84,
        "trace_id": "ASYNC-TRACE-01",
        "session_id": "sess_async"
    }

    # BCI arrives first
    _, comb1 = normalizer.ingest_bci(raw_bci, session_id="sess_async", trace_id="ASYNC-TRACE-01")
    assert comb1.status == "BCI_ONLY"
    assert comb1.correlation.is_correlated is False

    # AI/ML arrives later and correlates with retained BCI frame
    _, comb2 = normalizer.ingest_aiml(raw_aiml, session_id="sess_async", trace_id="ASYNC-TRACE-01")
    assert comb2.status == "COMBINED_ACTIVE"
    assert comb2.correlation.is_correlated is True
    assert comb2.correlation.correlation_method == "TRACE_ID"
    assert comb2.bci.mental_command == "LEFT"
    assert comb2.aiml.predicted_intent == "LEFT"


def test_async_aiml_first_arrival(normalizer):
    raw_aiml = {
        "intent": "RIGHT",
        "confidence": 0.9,
        "trace_id": "ASYNC-TRACE-02",
        "session_id": "sess_async"
    }
    raw_bci = {
        "command": "RIGHT",
        "power": 0.88,
        "trace_id": "ASYNC-TRACE-02",
        "session_id": "sess_async"
    }

    # AI/ML arrives first
    _, comb1 = normalizer.ingest_aiml(raw_aiml, session_id="sess_async", trace_id="ASYNC-TRACE-02")
    assert comb1.status == "AIML_ONLY"

    # BCI arrives later
    _, comb2 = normalizer.ingest_bci(raw_bci, session_id="sess_async", trace_id="ASYNC-TRACE-02")
    assert comb2.status == "COMBINED_ACTIVE"
    assert comb2.correlation.is_correlated is True
    assert comb2.correlation.correlation_method == "TRACE_ID"


# ---------------------------------------------------------------------------
# 5. Missing Data & Error Handling
# ---------------------------------------------------------------------------

def test_missing_bci_or_aiml_fields(normalizer):
    bci_only = normalizer.combine(
        normalizer.normalize_bci(BciTelemetry(mental_command=MentalCommandTelemetry(action="NEUTRAL"))),
        None
    )
    assert bci_only.status == "BCI_ONLY"
    assert bci_only.aiml is None

    aiml_only = normalizer.combine(
        None,
        normalizer.normalize_aiml(PredictionMetrics(predicted_intent="NEUTRAL", confidence=0.5))
    )
    assert aiml_only.status == "AIML_ONLY"
    assert aiml_only.bci is None


# ---------------------------------------------------------------------------
# 6. UnifiedTelemetryPacket Transport Envelope Tests
# ---------------------------------------------------------------------------

def test_unified_telemetry_packet_transport_integration(normalizer):
    bci = BciTelemetry(
        headset_id="EPOC-X-TRANSPORT",
        mental_command=MentalCommandTelemetry(action="LEFT", power=0.88)
    )
    pkt_bci = UnifiedTelemetryPacket(
        source_domain=TelemetryDomain.BCI,
        source_id="EPOC-X-TRANSPORT",
        session_id="sess_trans",
        trace_id="tr_trans",
        payload=bci
    )

    combined = normalizer.process_telemetry_packet(pkt_bci)
    assert combined is not None
    assert combined.status == "BCI_ONLY"

    # Wrap combined inside transport envelope
    transport_pkt = normalizer.create_unified_transport_packet(combined)
    assert isinstance(transport_pkt, UnifiedTelemetryPacket)
    assert transport_pkt.source_domain == TelemetryDomain.BCI
    assert transport_pkt.session_id == "sess_trans"
    assert transport_pkt.trace_id == "tr_trans"

    data = transport_pkt.to_dict()
    assert "payload" in data
    assert data["payload"]["status"] == "BCI_ONLY"


# ---------------------------------------------------------------------------
# 7. API Integration Tests
# ---------------------------------------------------------------------------

client = TestClient(app)


def test_api_get_combined_telemetry_endpoint():
    bci_aiml_normalizer._bci_buffer.clear()
    bci_aiml_normalizer._aiml_buffer.clear()
    bci_aiml_normalizer._latest_combined = None

    # Ingest BCI telemetry
    bci_payload = {
        "source_domain": "BCI",
        "source_id": "EPOC-X-API-TEST",
        "session_id": "sess_api_test",
        "trace_id": "tr_api_test",
        "payload": {
            "headset_id": "EPOC-X-API-TEST",
            "contact_quality": {"AF3": 1.0, "F7": 0.9},
            "mental_command": {
                "action": "PUSH",
                "power": 0.86,
                "is_debounced": True
            }
        }
    }
    res1 = client.post("/api/v1/telemetry", json=bci_payload)
    assert res1.status_code == 200

    # Ingest AI/ML telemetry with matching trace_id
    aiml_payload = {
        "source_domain": "AI_ML",
        "source_id": "AIML-NODE-01",
        "session_id": "sess_api_test",
        "trace_id": "tr_api_test",
        "payload": {
            "model_name": "CognitiveRouter",
            "inference_latency_ms": 11.2,
            "prediction": {
                "predicted_intent": "PUSH",
                "confidence": 0.91
            }
        }
    }
    res2 = client.post("/api/v1/telemetry", json=aiml_payload)
    assert res2.status_code == 200

    # Fetch combined analytics endpoint
    res_comb = client.get("/api/v1/telemetry/combined")
    assert res_comb.status_code == 200
    json_data = res_comb.json()
    assert json_data["status"] == "success"
    assert json_data["combined"] is not None

    comb_obj = json_data["combined"]
    assert comb_obj["session_id"] == "sess_api_test"
    assert comb_obj["bci"]["mental_command"] == "PUSH"
    assert comb_obj["aiml"]["predicted_intent"] == "PUSH"
    assert comb_obj["correlation"]["is_correlated"] is True


def test_api_get_latest_telemetry_includes_combined():
    res = client.get("/api/v1/telemetry/latest")
    assert res.status_code == 200
    json_data = res.json()
    assert "COMBINED" in json_data["domains"]
