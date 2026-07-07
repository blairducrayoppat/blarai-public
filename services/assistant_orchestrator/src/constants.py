"""
Orchestrator Constants
=======================
Service-specific constants derived from shared hardware constants + Use Case specs.
"""

from __future__ import annotations

from shared.constants import (
    COSINE_SIMILARITY_THRESHOLD,
    DRAFT_MODEL_OV_PATH,
    FAIL_CLOSED,
    MAX_OUTPUT_TOKENS,
    MAX_TOOL_CALL_DEPTH,
    NPU_KV_CACHE_PERSISTS,
    NPU_ORCH_PRIORITY,
    NUM_ASSISTANT_TOKENS,
    ORCH_FIRST_TOKEN_COLD_MS,
    ORCH_FIRST_TOKEN_WARM_MS,
    ORCH_MODEL_QUANT,
    ORCH_MODEL_SIZE_PARAMS,
    ORCH_MODEL_WEIGHT_MB,
    ORCH_RESUME_BUDGET_MS,
    SPECULATIVE_DECODING_ENABLED,
    TARGET_MODEL_OV_PATH,
)

# Re-export hardware constants
NPU_PRIORITY: int = NPU_ORCH_PRIORITY
MODEL_PARAMS: str = ORCH_MODEL_SIZE_PARAMS
MODEL_QUANT: str = ORCH_MODEL_QUANT
MODEL_WEIGHT_MB: int = ORCH_MODEL_WEIGHT_MB
KV_CACHE_PERSISTS: bool = NPU_KV_CACHE_PERSISTS
RESUME_BUDGET_MS: float = ORCH_RESUME_BUDGET_MS
FIRST_TOKEN_WARM_MS: float = ORCH_FIRST_TOKEN_WARM_MS
FIRST_TOKEN_COLD_MS: float = ORCH_FIRST_TOKEN_COLD_MS
SECURITY_POSTURE_FAIL_CLOSED: bool = FAIL_CLOSED

# Speculative decoding constants (ADR-012)
DRAFT_MODEL_DIR: str = DRAFT_MODEL_OV_PATH
SPECULATIVE_DECODING: bool = SPECULATIVE_DECODING_ENABLED
ASSISTANT_TOKENS: int = NUM_ASSISTANT_TOKENS
MODEL_DIR: str = TARGET_MODEL_OV_PATH

# Circuit breaker limits
OUTPUT_TOKEN_CAP: int = MAX_OUTPUT_TOKENS
TOOL_CALL_DEPTH_CAP: int = MAX_TOOL_CALL_DEPTH

# PGOV thresholds (P1.9)
PGOV_COSINE_THRESHOLD: float = COSINE_SIMILARITY_THRESHOLD
"""Above this threshold, generated content is flagged as potential leakage."""

PGOV_PII_ENABLED: bool = True
"""Enable PII/secret pattern detection in PGOV pipeline."""

PGOV_DELIMITER_ECHO_ENABLED: bool = True
"""Enable Context Spotlighting delimiter echo detection."""

PGOV_TOOL_ALLOWLIST_ENABLED: bool = True
"""Enable deterministic tool-call allowlist enforcement."""

PGOV_LEAKAGE_ENABLED: bool = True
"""Enable embedding-based leakage detection (requires bge-small-en-v1.5)."""

# Preemption detection (P1.8, ADR-008)
PREEMPTION_TIMING_MULTIPLIER: float = 5.0
"""Step latency must exceed this multiple of running median to flag preemption."""

MIN_PREEMPTION_SAMPLES: int = 3
"""Minimum completed token steps before preemption detection activates."""

# Generation defaults (P1.8, USE-CASE-004)
DEFAULT_TEMPERATURE: float = 0.7
DEFAULT_TOP_K: int = 50
DEFAULT_TOP_P: float = 0.9
DEFAULT_REPETITION_PENALTY: float = 1.1

# Service metadata
SERVICE_NAME: str = "assistant_orchestrator"
