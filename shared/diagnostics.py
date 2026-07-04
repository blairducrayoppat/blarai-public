"""Lightweight runtime memory diagnostics (#561).

Turns "RAM feels high" into logged numbers, so memory behaviour on the shared
32 GB Lunar Lake pool (the iGPU has no separate VRAM — all GPU models consume
system RAM) is observable instead of eyeballed. Built to instrument the VLM
load / describe / evict path now, and to be reused by the forthcoming headless
scenario harness.

psutil-based and fail-soft: if psutil is unavailable every call degrades to a
no-op (empty snapshot) rather than breaking a request. No external network.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    import psutil  # type: ignore[import-untyped]

    _PSUTIL_AVAILABLE = True
except ImportError:  # pragma: no cover — psutil is a dev/runtime dep, normally present
    psutil = None  # type: ignore[assignment]
    _PSUTIL_AVAILABLE = False


def memory_snapshot() -> dict[str, float]:
    """Return a system + current-process memory snapshot in megabytes.

    Keys: ``sys_total_mb``, ``sys_available_mb``, ``sys_used_pct``,
    ``proc_rss_mb``. Returns ``{}`` when psutil is unavailable (fail-soft).
    """
    if not _PSUTIL_AVAILABLE:
        return {}
    vm = psutil.virtual_memory()
    try:
        rss = float(psutil.Process().memory_info().rss)
    except Exception:  # noqa: BLE001 — diagnostics must never raise
        rss = 0.0
    return {
        "sys_total_mb": vm.total / 1_000_000.0,
        "sys_available_mb": vm.available / 1_000_000.0,
        "sys_used_pct": float(vm.percent),
        "proc_rss_mb": rss / 1_000_000.0,
    }


def log_memory(log: logging.Logger, label: str, **extra: Any) -> dict[str, float]:
    """Log a memory snapshot at *label* (INFO) and return it. Never raises.

    Bracket an expensive operation with two calls so the real before/after
    numbers land in the log. ``extra`` keyword pairs are appended verbatim
    (e.g. ``img="8160x6144"`` to correlate cost with input size).
    """
    snap = memory_snapshot()
    try:
        if not snap:
            log.info("MEM[%s] (psutil unavailable)", label)
            return snap
        extra_str = "".join(f" {k}={v}" for k, v in extra.items())
        log.info(
            "MEM[%s] sys_used=%.1f%% avail=%.0fMB proc_rss=%.0fMB%s",
            label,
            snap["sys_used_pct"],
            snap["sys_available_mb"],
            snap["proc_rss_mb"],
            extra_str,
        )
    except Exception:  # noqa: BLE001 — diagnostics must never break the caller
        pass
    return snap
