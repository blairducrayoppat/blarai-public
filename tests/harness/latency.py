"""Latency measurement + community-grade perf recording for the harness.

Pure-Python timing primitives shared by Layer A (deterministic regression
locks) and Layer B (real-model benchmarks). No model, GPU, or service import
lives here, so it is cheap to import from anywhere.

The community-grade recorder (:func:`write_perf_record`) follows the CLAUDE.md
testing-data mandate: it captures hardware + OpenVINO version + methodology and
explicitly NAMES what is not measured, rather than implying full coverage. The
caller supplies the timestamp (the harness keeps no clock authority of its own).
"""

from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
PERF_DIR = _REPO_ROOT / "docs" / "performance"


@dataclass(frozen=True)
class LatencySample:
    """One timed operation: a label, its wall-clock milliseconds, and metadata."""

    label: str
    ms: float
    meta: dict[str, Any] = field(default_factory=dict)


def percentile(values: Sequence[float], p: float) -> float:
    """Linear-interpolated percentile (``p`` in ``[0, 100]``). Empty -> 0.0."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    k = (len(ordered) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    frac = k - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def summarize(samples: Sequence[float]) -> dict[str, float]:
    """min / mean / p50 / p95 / max over a list of millisecond values."""
    if not samples:
        return {
            "count": 0, "min_ms": 0.0, "mean_ms": 0.0,
            "p50_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0,
        }
    return {
        "count": len(samples),
        "min_ms": round(min(samples), 3),
        "mean_ms": round(statistics.fmean(samples), 3),
        "p50_ms": round(percentile(samples, 50), 3),
        "p95_ms": round(percentile(samples, 95), 3),
        "max_ms": round(max(samples), 3),
    }


class Stopwatch:
    """Context manager measuring elapsed wall-clock milliseconds.

    >>> with Stopwatch() as sw:
    ...     do_work()
    >>> sw.ms
    """

    def __init__(self) -> None:
        self.ms: float = 0.0
        self._t0: float = 0.0

    def __enter__(self) -> "Stopwatch":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.ms = (time.perf_counter() - self._t0) * 1000.0


def build_environment(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Reproducibility metadata for a perf record: hardware + OpenVINO version.

    Names what is NOT introspectable here (GPU driver version, co-resident
    memory cost) so a reader does not mistake the record for full coverage.
    """
    env: dict[str, Any] = {
        "cpu": "Intel Core Ultra 7 258V (Lunar Lake)",
        "gpu": "Intel Arc 140V (Xe2)",
        "memory_ceiling_gb": 31.323,
    }
    try:
        import openvino as ov  # noqa: PLC0415 — optional, only present on the runtime host

        env["openvino_version"] = ov.__version__
    except Exception:  # noqa: BLE001 — absence is data, not an error
        env["openvino_version"] = "unavailable"
    try:
        import openvino_genai  # noqa: PLC0415

        env["openvino_genai_version"] = getattr(openvino_genai, "__version__", "present")
    except Exception:  # noqa: BLE001
        env["openvino_genai_version"] = "unavailable"
    env["not_measured"] = [
        "GPU driver version (read from dxdiag / Device Manager; not introspectable here)",
        "co-resident memory cost when other models are loaded alongside",
        "subjective voice naturalness / visual answer quality",
    ]
    if extra:
        env.update(extra)
    return env


def write_perf_record(
    name: str,
    measurements: dict[str, Any],
    *,
    when_iso: str,
    model: str,
    precision: str,
    methodology: str,
    notes: str = "",
    extra_env: dict[str, Any] | None = None,
) -> Path:
    """Write a community-grade perf JSON to ``docs/performance/``.

    Args:
        name: Short scenario name (e.g. ``"ao_chat_first_token"``).
        measurements: Arbitrary JSON-able dict of the measured numbers.
        when_iso: ISO-8601 timestamp from the CALLER (the harness keeps no
            clock of its own — the runner passes ``datetime.now(...).isoformat()``).
        model: Model + size (e.g. ``"Qwen3-14B"``).
        precision: Weight precision (e.g. ``"INT4"``).
        methodology: Prompt set / run count / config — enough to reproduce.
        notes: Free-form caveats.
        extra_env: Extra environment keys to merge.

    Returns:
        The path written.
    """
    PERF_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "name": name,
        "timestamp": when_iso,
        "model": model,
        "precision": precision,
        "methodology": methodology,
        "environment": build_environment(extra_env),
        "measurements": measurements,
        "notes": notes,
        "source": "tests/harness (Vikunja #563)",
    }
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in when_iso)
    out = PERF_DIR / f"harness_{name}_{safe}.json"
    out.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return out
