"""
test_aiml_accuracy_ingestion.py
===============================
Comprehensive test suite for AI/ML Command Accuracy Ingestion, Analytics Engine,
FastAPI REST endpoints, and Telemetry WebSocket integration.
"""

import pytest
from fastapi.testclient import TestClient

from main import app
from plugins.aiml.accuracy_engine import (
    AIMLAccuracyEngine,
    CommandAccuracyEvaluation,
    accuracy_engine,
)
from plugins.aiml.plugin import AIMLPlugin
from api.telemetry_routes import _LATEST_TELEMETRY, _TELEMETRY_HISTORY


@pytest.fixture(autouse=True)
def reset_engine():
    """Reset accuracy engine state before and after each test."""
    accuracy_engine.reset()
    yield
    accuracy_engine.reset()


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Model & Evaluation Unit Tests
# ---------------------------------------------------------------------------

def test_evaluation_model_auto_calculation():
    """Verify is_accurate is automatically calculated when ground truth is provided."""
    eval_correct = CommandAccuracyEvaluation(
        predicted_intent="push",
        ground_truth_intent="PUSH",
        confidence=0.92
    )
    assert eval_correct.predicted_intent == "PUSH"
    assert eval_correct.ground_truth_intent == "PUSH"
    assert eval_correct.is_accurate is True

    eval_wrong = CommandAccuracyEvaluation(
        predicted_intent="LEFT",
        ground_truth_intent="RIGHT",
        confidence=0.45
    )
    assert eval_wrong.is_accurate is False

    # When no ground truth, confidence >= 0.65 threshold
    eval_thresh_pass = CommandAccuracyEvaluation(
        predicted_intent="PULL",
        confidence=0.88
    )
    assert eval_thresh_pass.is_accurate is True

    eval_thresh_fail = CommandAccuracyEvaluation(
        predicted_intent="NEUTRAL",
        confidence=0.35
    )
    assert eval_thresh_fail.is_accurate is False


# ---------------------------------------------------------------------------
# 2. Engine Analytics & Metric Computations
# ---------------------------------------------------------------------------

def test_accuracy_engine_metrics_calculation():
    """Verify overall accuracy %, average confidence, latency, and per-intent metrics."""
    engine = AIMLAccuracyEngine()

    samples = [
        {"predicted_intent": "PUSH", "ground_truth_intent": "PUSH", "confidence": 0.90, "inference_latency_ms": 10.0},
        {"predicted_intent": "PUSH", "ground_truth_intent": "PUSH", "confidence": 0.80, "inference_latency_ms": 12.0},
        {"predicted_intent": "LEFT", "ground_truth_intent": "LEFT", "confidence": 0.85, "inference_latency_ms": 14.0},
        {"predicted_intent": "LEFT", "ground_truth_intent": "RIGHT", "confidence": 0.50, "inference_latency_ms": 16.0}, # incorrect
    ]

    for s in samples:
        engine.ingest(s)

    metrics = engine.get_metrics()
    assert metrics["total_samples"] == 4
    assert metrics["accurate_samples"] == 3
    assert metrics["overall_accuracy_pct"] == 75.0
    assert metrics["mean_confidence"] == round((0.90 + 0.80 + 0.85 + 0.50) / 4, 4)
    assert metrics["mean_latency_ms"] == round((10.0 + 12.0 + 14.0 + 16.0) / 4, 2)

    # Check per intent metrics
    assert "PUSH" in metrics["per_intent_metrics"]
    push_m = metrics["per_intent_metrics"]["PUSH"]
    assert push_m["total_samples"] == 2
    assert push_m["accurate_samples"] == 2
    assert push_m["accuracy_pct"] == 100.0

    assert "LEFT" in metrics["per_intent_metrics"]
    left_m = metrics["per_intent_metrics"]["LEFT"]
    assert left_m["total_samples"] == 2
    assert left_m["accurate_samples"] == 1
    assert left_m["accuracy_pct"] == 50.0


def test_confusion_matrix_generation():
    """Verify confusion matrix tracks actual vs predicted intent classifications."""
    engine = AIMLAccuracyEngine()

    engine.ingest({"predicted_intent": "PUSH", "ground_truth_intent": "PUSH", "confidence": 0.95})
    engine.ingest({"predicted_intent": "LEFT", "ground_truth_intent": "PUSH", "confidence": 0.40}) # misclassified PUSH as LEFT
    engine.ingest({"predicted_intent": "RIGHT", "ground_truth_intent": "RIGHT", "confidence": 0.88})

    metrics = engine.get_metrics()
    cm = metrics["confusion_matrix"]
    assert cm["PUSH"]["PUSH"] == 1
    assert cm["PUSH"]["LEFT"] == 1
    assert cm["RIGHT"]["RIGHT"] == 1


def test_rolling_window_accuracy():
    """Verify rolling accuracy over 50 and 100 sample windows."""
    engine = AIMLAccuracyEngine()

    # Ingest 60 samples: first 30 correct, next 30 incorrect
    for i in range(30):
        engine.ingest({"predicted_intent": "PUSH", "ground_truth_intent": "PUSH", "confidence": 0.9})
    for i in range(30):
        engine.ingest({"predicted_intent": "PUSH", "ground_truth_intent": "PULL", "confidence": 0.4})

    metrics = engine.get_metrics()
    assert metrics["total_samples"] == 60
    assert metrics["overall_accuracy_pct"] == 50.0
    # Last 50 items = 20 correct + 30 incorrect = 20/50 = 40.0%
    assert metrics["rolling_accuracy_50"] == 40.0


def test_history_and_reset():
    """Verify history pagination and engine reset."""
    engine = AIMLAccuracyEngine()

    for i in range(15):
        engine.ingest({"predicted_intent": "PUSH", "confidence": 0.9, "command_id": f"CMD-{i}"})

    paged = engine.get_history(limit=5, offset=0)
    assert len(paged) == 5
    assert paged[0]["command_id"] == "CMD-14" # reverse chronological order

    engine.reset()
    assert engine.get_metrics()["total_samples"] == 0
    assert len(engine.get_history()) == 0


# ---------------------------------------------------------------------------
# 3. Telemetry Integration Tests
# ---------------------------------------------------------------------------

def test_telemetry_packet_creation_and_caching():
    """Verify ingesting accuracy updates the latest AI/ML telemetry cache and history buffer."""
    accuracy_engine.reset()

    res = accuracy_engine.ingest({
        "predicted_intent": "PUSH",
        "ground_truth_intent": "PUSH",
        "confidence": 0.94,
        "model_name": "Cortex-EEG-v2",
        "model_version": "2.1.0",
        "inference_latency_ms": 11.2
    })

    assert res["status"] == "success"
    assert "AI_ML" in _LATEST_TELEMETRY
    latest_pkt = _LATEST_TELEMETRY["AI_ML"]
    assert latest_pkt["source_domain"] == "AI_ML"
    assert latest_pkt["payload"]["model_name"] == "Cortex-EEG-v2"
    assert latest_pkt["payload"]["prediction"]["predicted_intent"] == "PUSH"
    assert latest_pkt["payload"]["prediction"]["confidence"] == 0.94


# ---------------------------------------------------------------------------
# 4. REST API Endpoint Tests
# ---------------------------------------------------------------------------

def test_rest_api_single_ingest(client):
    """Test POST /api/v1/aiml/accuracy/ingest for single evaluation."""
    payload = {
        "command_id": "CMD-201",
        "predicted_intent": "PULL",
        "ground_truth_intent": "PULL",
        "confidence": 0.91,
        "model_name": "BCI-ResNet",
        "inference_latency_ms": 13.4
    }
    resp = client.post("/api/v1/aiml/accuracy/ingest", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["is_accurate"] is True
    assert data["predicted_intent"] == "PULL"


def test_rest_api_batch_ingest(client):
    """Test POST /api/v1/aiml/accuracy/ingest for batch evaluations."""
    batch_payload = {
        "evaluations": [
            {"predicted_intent": "LEFT", "ground_truth_intent": "LEFT", "confidence": 0.89},
            {"predicted_intent": "RIGHT", "ground_truth_intent": "RIGHT", "confidence": 0.92},
            {"predicted_intent": "PUSH", "ground_truth_intent": "NEUTRAL", "confidence": 0.45},
        ]
    }
    resp = client.post("/api/v1/aiml/accuracy/ingest", json=batch_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["count"] == 3


def test_rest_api_metrics_and_history(client):
    """Test GET /api/v1/aiml/accuracy/metrics and GET /api/v1/aiml/accuracy/history."""
    # Ingest test items
    client.post("/api/v1/aiml/accuracy/ingest", json={"predicted_intent": "PUSH", "ground_truth_intent": "PUSH", "confidence": 0.95})
    client.post("/api/v1/aiml/accuracy/ingest", json={"predicted_intent": "PULL", "ground_truth_intent": "PULL", "confidence": 0.85})

    # Metrics
    resp = client.get("/api/v1/aiml/accuracy/metrics")
    assert resp.status_code == 200
    m_data = resp.json()
    assert m_data["status"] == "success"
    assert m_data["metrics"]["total_samples"] == 2
    assert m_data["metrics"]["overall_accuracy_pct"] == 100.0

    # History
    resp_hist = client.get("/api/v1/aiml/accuracy/history?limit=10")
    assert resp_hist.status_code == 200
    h_data = resp_hist.json()
    assert h_data["status"] == "success"
    assert h_data["count"] == 2


def test_rest_api_benchmark_endpoint(client):
    """Test POST /api/v1/aiml/accuracy/benchmark."""
    resp = client.post("/api/v1/aiml/accuracy/benchmark", json={"sample_count": 25, "simulated_noise": 0.05})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["benchmark"]["samples_ingested"] == 25
    assert data["benchmark"]["metrics"]["total_samples"] >= 25


def test_rest_api_telemetry_accuracy_route(client):
    """Test POST /api/v1/telemetry/aiml/accuracy and GET /api/v1/telemetry/aiml/accuracy/metrics."""
    payload = {
        "predicted_intent": "RIGHT",
        "ground_truth_intent": "RIGHT",
        "confidence": 0.96,
        "inference_latency_ms": 10.5
    }
    resp = client.post("/api/v1/telemetry/aiml/accuracy", json=payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    resp_m = client.get("/api/v1/telemetry/aiml/accuracy/metrics")
    assert resp_m.status_code == 200
    assert resp_m.json()["status"] == "success"


# ---------------------------------------------------------------------------
# 5. AIMLPlugin Command Execution Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_aiml_plugin_accuracy_execution():
    """Verify AIMLPlugin handles INGEST_ACCURACY and GET_ACCURACY commands."""
    plugin = AIMLPlugin()
    plugin.initialize()

    # Ingest via plugin.execute
    ingest_res = await plugin.execute("INGEST_ACCURACY", {
        "predicted_intent": "PUSH",
        "ground_truth_intent": "PUSH",
        "confidence": 0.93
    })
    assert ingest_res["status"] == "success"
    assert ingest_res["result"]["is_accurate"] is True

    # Query metrics via plugin.execute
    query_res = await plugin.execute("GET_ACCURACY")
    assert query_res["status"] == "success"
    assert query_res["metrics"]["total_samples"] >= 1
