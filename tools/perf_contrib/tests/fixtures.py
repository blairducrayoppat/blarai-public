"""Fixture factory for perf record tests.

All fixtures are pure Python dicts — no disk I/O, no GPU, no network.
The ``minimal_valid`` record is the baseline that satisfies every required field.
Each ``invalid_*`` factory returns a dict that violates exactly one rule.
"""
from __future__ import annotations

import copy
from typing import Any


def minimal_valid() -> dict[str, Any]:
    """Smallest record that passes schema validation."""
    return {
        "name": "router_latency",
        "timestamp": "2026-06-04T17:20:28.995057+00:00",
        "model": "bge-small-en-v1.5",
        "precision": "ONNX-FP16",
        "methodology": (
            "SemanticRouter.classify() over 5 representative queries, "
            "single process, CPUExecutionProvider, cold load timed separately."
        ),
        "environment": {
            "cpu": "Intel Core Ultra 7 258V (Lunar Lake)",
            "gpu": "Intel Arc 140V (Xe2)",
            "memory_ceiling_gb": 31.323,
            "openvino_version": "2026.1.0-21367-63e31528c62",
            "openvino_genai_version": "2026.1.0.0-2957-1dabb8c2255",
            "not_measured": [
                "GPU driver version (read from dxdiag / Device Manager; not introspectable here)",
                "co-resident memory cost when other models are loaded alongside",
            ],
        },
        "measurements": {
            "load_ms": 8913.4,
            "classify": {
                "count": 5,
                "min_ms": 4.031,
                "mean_ms": 5.058,
            },
        },
        "notes": "",
        "source": "tests/harness",
    }


def harness_chat_record() -> dict[str, Any]:
    """Realistic harness_chat record (mirrors the actual file on disk)."""
    return {
        "name": "chat",
        "timestamp": "2026-06-04T17:21:56.906527+00:00",
        "model": "Qwen3-14B",
        "precision": "INT4",
        "methodology": (
            "OrchestratorGPUInference.generate_text(max_new_tokens=64) on a single cold prompt; "
            "cold load timed separately; speculative decoding ON; greedy/deterministic. "
            "KV-cache cold (first turn) — warm first-token would be lower."
        ),
        "environment": {
            "cpu": "Intel Core Ultra 7 258V (Lunar Lake)",
            "gpu": "Intel Arc 140V (Xe2)",
            "memory_ceiling_gb": 31.323,
            "openvino_version": "2026.1.0-21367-63e31528c62-releases/2026/1",
            "openvino_genai_version": "2026.1.0.0-2957-1dabb8c2255",
            "not_measured": [
                "GPU driver version (read from dxdiag / Device Manager; not introspectable here)",
                "co-resident memory cost when other models are loaded alongside",
                "subjective voice naturalness / visual answer quality",
            ],
        },
        "measurements": {
            "available": True,
            "model": "Qwen3-14B",
            "precision": "INT4",
            "device": "GPU",
            "speculative_decoding": True,
            "load_ms": 19333.4,
            "wall_clock_generate_ms": 6137.8,
            "engine_first_token_ms": 1500.0,
            "engine_total_ms": 6122.6,
            "max_new_tokens": 64,
            "reply_chars": 221,
            # reply_preview is intentionally present here; the scrubber removes it.
            "reply_preview": "A local-first AI assistant is an AI system...",
        },
        "notes": "",
        "source": "tests/harness (Vikunja #563)",
    }


# ---- invalid record factories -----------------------------------------------

def invalid_missing_name() -> dict[str, Any]:
    rec = minimal_valid()
    del rec["name"]
    return rec


def invalid_empty_name() -> dict[str, Any]:
    rec = minimal_valid()
    rec["name"] = "  "
    return rec


def invalid_missing_timestamp() -> dict[str, Any]:
    rec = minimal_valid()
    del rec["timestamp"]
    return rec


def invalid_bad_timestamp() -> dict[str, Any]:
    rec = minimal_valid()
    rec["timestamp"] = "not-a-date"
    return rec


def invalid_missing_model() -> dict[str, Any]:
    rec = minimal_valid()
    del rec["model"]
    return rec


def invalid_missing_precision() -> dict[str, Any]:
    rec = minimal_valid()
    del rec["precision"]
    return rec


def invalid_methodology_too_short() -> dict[str, Any]:
    rec = minimal_valid()
    rec["methodology"] = "too short"  # < 20 chars
    return rec


def invalid_missing_methodology() -> dict[str, Any]:
    rec = minimal_valid()
    del rec["methodology"]
    return rec


def invalid_missing_environment() -> dict[str, Any]:
    rec = minimal_valid()
    del rec["environment"]
    return rec


def invalid_environment_not_dict() -> dict[str, Any]:
    rec = minimal_valid()
    rec["environment"] = "a string"
    return rec


def invalid_missing_cpu() -> dict[str, Any]:
    rec = minimal_valid()
    rec = copy.deepcopy(rec)
    del rec["environment"]["cpu"]
    return rec


def invalid_missing_not_measured() -> dict[str, Any]:
    """not_measured is absent — the most important community-grade guard."""
    rec = copy.deepcopy(minimal_valid())
    del rec["environment"]["not_measured"]
    return rec


def invalid_empty_not_measured() -> dict[str, Any]:
    """not_measured present but empty list — implies false full coverage."""
    rec = copy.deepcopy(minimal_valid())
    rec["environment"]["not_measured"] = []
    return rec


def invalid_not_measured_not_list() -> dict[str, Any]:
    rec = copy.deepcopy(minimal_valid())
    rec["environment"]["not_measured"] = "should be a list"
    return rec


def invalid_missing_measurements() -> dict[str, Any]:
    rec = minimal_valid()
    del rec["measurements"]
    return rec


def invalid_empty_measurements() -> dict[str, Any]:
    rec = minimal_valid()
    rec["measurements"] = {}
    return rec


def invalid_measurements_not_dict() -> dict[str, Any]:
    rec = minimal_valid()
    rec["measurements"] = [1, 2, 3]
    return rec
