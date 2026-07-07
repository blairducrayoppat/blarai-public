"""
Semantic Router Constants
==========================
Service-specific constants for CPU-based intent classification.
"""

from __future__ import annotations

from shared.constants import (
    FAIL_CLOSED,
    SEMANTIC_ROUTER_LATENCY_MS,
    SEMANTIC_ROUTER_MODEL,
    SEMANTIC_ROUTER_MODEL_MB,
)

# Re-export hardware constants
MODEL_NAME: str = SEMANTIC_ROUTER_MODEL
MODEL_SIZE_MB: int = SEMANTIC_ROUTER_MODEL_MB
LATENCY_TARGET_MS: float = SEMANTIC_ROUTER_LATENCY_MS
SECURITY_POSTURE_FAIL_CLOSED: bool = FAIL_CLOSED

# Service metadata
SERVICE_NAME: str = "semantic_router"
INFERENCE_DEVICE: str = "CPU"
"""Runs on CPU — no NPU contention."""

INFERENCE_RUNTIME: str = "ONNX"
"""Uses ONNX Runtime for CPU inference (not OpenVINO)."""

# Intent classification
DEFAULT_INTENT: str = "OUT_OF_SCOPE"
"""Fail-Closed default: unclassified intents are rejected."""

CONFIDENCE_THRESHOLD: float = 0.50
"""Minimum absolute cosine similarity to accept an intent classification.
Emprically calibrated against bge-small-en-v1.5 (P1.7). Valid queries
typically score 0.54–0.82; this floor filters truly unrelated content."""

CONFIDENCE_MARGIN: float = 0.04
"""Minimum margin between best and second-best centroid similarity.
Empirically calibrated (P1.7): valid queries show margins 0.05–0.17,
gibberish/OOD queries show margins < 0.035. This gate rejects ambiguous
input where no single route is clearly dominant — Fail-Closed to
OUT_OF_SCOPE. The Semantic Router is a routing fast-path, not a security
boundary; the Policy Agent dual-gate handles adversarial classification."""
