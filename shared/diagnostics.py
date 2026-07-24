"""Lightweight runtime memory diagnostics (#561).

Turns "RAM feels high" into logged numbers, so memory behaviour on the shared
32 GB Lunar Lake pool (the iGPU has no separate VRAM — all GPU models consume
system RAM) is observable instead of eyeballed. Built to instrument the VLM
load / describe / evict path now, and to be reused by the forthcoming headless
scenario harness.

psutil-based and fail-soft: if psutil is unavailable every call degrades to a
no-op (empty snapshot) rather than breaking a request. No external network.

Memory-reclaim probe (#900). The lower half of this module adds a structured,
OFF-by-default probe that records how much system RAM an eviction actually
returns to Windows, as ``In-Use = Total − Available`` before/after deltas (NEVER
a process working set). It exists to verify — on the Arc 140V's unified pool —
whether the OpenVINO GPU plugin genuinely frees unified memory on evict/unload
or retains it (the Lunar Lake USM-retention hypothesis, openvino #33896). It is
gated so the instrumented evict paths (SDXL post-generate, the 14B evict/reload,
the embedding-cache idle-unload) pay only a boolean check and change no
behaviour until a measurement run turns it on.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

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


# ===========================================================================
# Memory-reclaim probe (#900) — does an eviction actually return RAM to Windows?
# ===========================================================================
#
# The Arc 140V iGPU has no dedicated VRAM: every GPU model consumes the shared
# 31.3 GB system pool. When BlarAI evicts a model (SDXL after a generate, the
# 14B before a hires refine, the embedding cache when idle) it drops the Python
# reference + ``gc.collect()`` and *assumes* the OS reclaims the memory. Upstream
# reports (openvino #33896/#34416/#31383) say this exact chip generation may
# RETAIN unified GPU memory on idle where the next generation auto-deallocates,
# which matches BlarAI's past "insufficient memory with 22 GB actually free"
# image-gen incident. This probe turns that assumption into a measured number:
# the ``In-Use = Total − Available`` delta across the eviction. A POSITIVE
# ``reclaimed_mb`` means Windows got the memory back; ~0 / negative means the
# driver held it. The @hardware measurement run (BlarAI up, real models loaded)
# reads these deltas; this module is the GPU-free instrumentation that captures
# them.

#: Environment flag that arms the probe. OFF unless set to a truthy value, so the
#: instrumented evict paths add ~zero cost and zero behaviour change in normal
#: operation. The @hardware measurement run sets it (or uses
#: :func:`set_reclaim_probe_enabled`) to collect the deltas.
RECLAIM_PROBE_ENV = "BLARAI_MEM_RECLAIM_PROBE"

#: Process-wide override: ``None`` ⇒ read the env each call (the default); a bool
#: ⇒ force on/off (tests + the measurement harness that wants deterministic
#: control without touching the environment).
_reclaim_probe_override: bool | None = None


def _truthy(val: str | None) -> bool:
    return (val or "").strip().lower() in {"1", "true", "on", "yes"}


def reclaim_probe_enabled() -> bool:
    """True iff the #900 memory-reclaim probe should emit structured records.

    Resolution order: the process override (:func:`set_reclaim_probe_enabled`)
    wins when set; otherwise the ``BLARAI_MEM_RECLAIM_PROBE`` environment flag.
    Default OFF — an instrumented eviction pays only this boolean check and
    changes no behaviour until a measurement run enables it.
    """
    if _reclaim_probe_override is not None:
        return _reclaim_probe_override
    return _truthy(os.environ.get(RECLAIM_PROBE_ENV))


def set_reclaim_probe_enabled(enabled: bool | None) -> None:
    """Force the probe on (``True``) / off (``False``), or defer to the env (``None``).

    The measurement harness and tests use this to drive the probe deterministically
    without mutating the environment. Pass ``None`` to restore env-driven behaviour.
    """
    global _reclaim_probe_override
    _reclaim_probe_override = enabled


def in_use_mb(snap: dict[str, float]) -> float | None:
    """System In-Use RAM in MB = ``Total − Available`` (the project's accounting rule).

    Returns ``None`` for an empty/malformed snapshot (psutil unavailable). This is
    deliberately NOT the process working set: on the unified Lunar Lake pool the
    figure that actually moves when the GPU driver returns (or retains) unified
    memory is the system-wide In-Use, and a working-set sum would miss the GPU
    allocation entirely (CLAUDE.md host_environment accounting rule; #900).
    """
    if not snap:
        return None
    try:
        return float(snap["sys_total_mb"]) - float(snap["sys_available_mb"])
    except (KeyError, TypeError, ValueError):
        return None


@dataclass(frozen=True)
class ReclaimSample:
    """One before/after In-Use delta around an eviction (#900), community-grade.

    ``reclaimed_mb`` = ``in_use_before_mb − in_use_after_mb`` — POSITIVE when the
    OS actually got memory back, ~0 / negative when the driver retained it (the
    openvino #33896 Lunar Lake USM-retention hypothesis this instruments). Every
    figure is system-wide In-Use (``Total − Available``), never a working set. The
    raw available/total/RSS are carried too so a reader can recompute the delta
    and see the process-RSS movement alongside the system figure.

    Deliberately TIMESTAMP-FREE so unit tests are deterministic; the @hardware
    measurement harness wraps these numbers with the hardware / OpenVINO version /
    GPU-driver / model-precision envelope (per the performance-capture rule) when
    it writes the machine-readable docs/performance JSON.
    """

    op: str
    total_mb: float
    in_use_before_mb: float
    in_use_after_mb: float
    reclaimed_mb: float
    available_before_mb: float
    available_after_mb: float
    proc_rss_before_mb: float
    proc_rss_after_mb: float
    extra: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        """A JSON-serialisable dict of this sample (for the community dataset).

        Rounds to 0.1 MB (the probe's meaningful resolution) and includes the
        free-form ``extra`` metadata (e.g. the evicted model/variant) only when
        present, so the record stays clean for an empty-extra call.
        """
        rec: dict[str, Any] = {
            "op": self.op,
            "total_mb": round(self.total_mb, 1),
            "in_use_before_mb": round(self.in_use_before_mb, 1),
            "in_use_after_mb": round(self.in_use_after_mb, 1),
            "reclaimed_mb": round(self.reclaimed_mb, 1),
            "available_before_mb": round(self.available_before_mb, 1),
            "available_after_mb": round(self.available_after_mb, 1),
            "proc_rss_before_mb": round(self.proc_rss_before_mb, 1),
            "proc_rss_after_mb": round(self.proc_rss_after_mb, 1),
        }
        if self.extra:
            rec["extra"] = dict(self.extra)
        return rec


def build_reclaim_sample(
    op: str,
    before: dict[str, float],
    after: dict[str, float],
    **extra: Any,
) -> ReclaimSample | None:
    """Compute a :class:`ReclaimSample` from two memory snapshots, or ``None``.

    Pure and never raises. Returns ``None`` when either snapshot lacks a usable
    In-Use figure (psutil absent / malformed) — there is nothing to difference.
    Ungated on purpose: this is the math, callable directly by the measurement
    harness; the gating lives in :func:`record_reclaim` / :func:`reclaim_probe`.
    """
    iu_before = in_use_mb(before)
    iu_after = in_use_mb(after)
    if iu_before is None or iu_after is None:
        return None
    try:
        total = float(before.get("sys_total_mb") or after.get("sys_total_mb") or 0.0)
        return ReclaimSample(
            op=str(op),
            total_mb=total,
            in_use_before_mb=iu_before,
            in_use_after_mb=iu_after,
            reclaimed_mb=iu_before - iu_after,
            available_before_mb=float(before.get("sys_available_mb", 0.0)),
            available_after_mb=float(after.get("sys_available_mb", 0.0)),
            proc_rss_before_mb=float(before.get("proc_rss_mb", 0.0)),
            proc_rss_after_mb=float(after.get("proc_rss_mb", 0.0)),
            extra=dict(extra),
        )
    except Exception:  # noqa: BLE001 — diagnostics must never raise
        return None


def record_reclaim(
    op: str,
    before: dict[str, float],
    after: dict[str, float],
    *,
    log: logging.Logger | None = None,
    sink: "Callable[[ReclaimSample], None] | None" = None,
    **extra: Any,
) -> ReclaimSample | None:
    """Record an In-Use eviction delta from two EXISTING snapshots (#900).

    For a path that already brackets its evict with :func:`log_memory` (e.g.
    ``image_gen.unload``): pass the before/after snapshots it already took and pay
    no extra probe cost. Gated by :func:`reclaim_probe_enabled` (default OFF): when
    off this is a cheap no-op returning ``None`` and emitting nothing. When on it
    logs a structured ``MEM_RECLAIM`` line and, if *sink* is given, hands it the
    sample (e.g. a JSONL collector the measurement harness installs).

    Fail-soft: any error — a bad snapshot, a logging failure, a raising *sink* —
    is swallowed. Instrumentation never breaks an eviction.
    """
    if not reclaim_probe_enabled():
        return None
    try:
        sample = build_reclaim_sample(op, before, after, **extra)
        if sample is None:
            return None
        if log is not None:
            log.info(
                "MEM_RECLAIM op=%s in_use_before=%.0fMB in_use_after=%.0fMB "
                "reclaimed=%+.0fMB avail_before=%.0fMB avail_after=%.0fMB "
                "proc_rss_delta=%+.0fMB%s",
                sample.op,
                sample.in_use_before_mb,
                sample.in_use_after_mb,
                sample.reclaimed_mb,
                sample.available_before_mb,
                sample.available_after_mb,
                sample.proc_rss_after_mb - sample.proc_rss_before_mb,
                "".join(f" {k}={v}" for k, v in sample.extra.items()),
            )
        if sink is not None:
            sink(sample)
        return sample
    except Exception:  # noqa: BLE001 — diagnostics must never raise
        return None


@contextmanager
def reclaim_probe(
    op: str,
    *,
    log: logging.Logger | None = None,
    snapshot_fn: "Callable[[], dict[str, float]] | None" = None,
    sink: "Callable[[ReclaimSample], None] | None" = None,
    **extra: Any,
) -> Iterator[None]:
    """Bracket an eviction to record its In-Use delta (#900).

    For paths that do NOT already snapshot memory (the 14B evict/reload, the
    embedding-cache idle-unload): wrap the drop-reference + ``gc.collect()`` body
    in this context manager. It snapshots before + after and records the delta.

    OFF by default (:func:`reclaim_probe_enabled`): when disabled the body runs
    with NO snapshots taken — a single boolean check — so an instrumented evict is
    byte-for-byte the work it was before. When enabled it snapshots around the
    body; put the ``gc.collect()`` INSIDE the ``with`` so the after-snapshot sees
    the reclaimed state. Fail-soft on both probe legs: a snapshot error never
    propagates into the eviction, and the body always runs exactly once.

    *snapshot_fn* defaults to :func:`memory_snapshot`, resolved LATE (at call
    time, not definition time) so a test/harness can substitute the module's
    ``memory_snapshot`` without the default capturing the original binding.
    """
    if not reclaim_probe_enabled():
        yield
        return
    snap = snapshot_fn if snapshot_fn is not None else memory_snapshot
    before: dict[str, float] = {}
    try:
        before = snap()
    except Exception:  # noqa: BLE001 — a probe read must never break the eviction
        before = {}
    try:
        yield
    finally:
        after: dict[str, float] = {}
        try:
            after = snap()
        except Exception:  # noqa: BLE001 — a probe read must never break the eviction
            after = {}
        record_reclaim(op, before, after, log=log, sink=sink, **extra)
