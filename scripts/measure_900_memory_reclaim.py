"""
#900 memory-reclaim @hardware harness — the 14B headline op (route B)
=====================================================================
Measures whether the resident Qwen3-14B's ~9.7 GB actually returns to Windows
on a mid-life ``SharedInferencePipeline.unload()``, or is retained by the GPU
driver (the openvino #33896 Lunar Lake USM-retention hypothesis).

Route B per #900 c.2108/c.2130: the headline op ``shared_pipeline.14b.unload``
only fires on the launcher-built wrapper, and the production route-A trigger
(a hires-fix image generate) is currently impossible — ``[image_generation]
.hires_enabled = false`` in default.toml after the 1536² RAM-spiral incident.
This harness therefore builds the pipeline with the LAUNCHER'S OWN builder and
byte-identical arguments (``build_shared_pipeline``, launcher/__main__.py step
2.5) and drives the REAL ``unload()`` / lazy-reload entry points — the wired
#900 instrumentation fires exactly as it would in the app; nothing is
hand-rolled and no config is flipped.

Method per cycle (N cycles, default 3):
  ensure loaded (lazy reload via ``generate()``) → settle → ``unload()``
  (the armed probe snapshots In-Use = Total − Available around the evict and
  emits a structured ``MEM_RECLAIM`` line) → settle.
A final reload + ``release_gpu_for_exit()`` captures the process-exit op once.

Interpretation: median ``reclaimed_mb`` ≈ 9700 ⇒ memory returns to Windows;
≈ 0 (or negative) ⇒ #33896 CONFIRMED on the Arc 140V.

Preconditions (refused otherwise): BlarAI DOWN (:5001 free — one model on the
GPU at a time), system-available memory above the load floor. Run from the
repo root with the runtime venv:
  .venv\\Scripts\\python.exe scripts\\measure_900_memory_reclaim.py
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import socket
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from shared.constants import NUM_ASSISTANT_TOKENS  # noqa: E402
from shared.diagnostics import (  # noqa: E402
    memory_snapshot,
    reclaim_probe_enabled,
    set_reclaim_probe_enabled,
)
from shared.inference.shared_pipeline import build_shared_pipeline  # noqa: E402
from shared.perf_env_capture import capture_box_state  # noqa: E402

try:
    import psutil  # type: ignore[import-untyped]
except ImportError:
    psutil = None  # type: ignore[assignment]

try:
    import openvino as ov  # type: ignore[import-untyped]
    _OV_VERSION: str = ov.__version__
except ImportError:
    _OV_VERSION = "unavailable"

try:
    import openvino_genai as ov_genai  # type: ignore[import-untyped]
    _OV_GENAI_VERSION: str = ov_genai.__version__
except ImportError:
    _OV_GENAI_VERSION = "unavailable"

logger = logging.getLogger("measure_900")

# Launcher step-2.5 build arguments (launcher/__main__.py:1748) — mirrored, not
# imported, so this harness records exactly what it built with. kv_cache
# precision "" (unset → FP16 default) and digest-only drafts are the shipped
# production defaults as of 2026-07-16 (default.toml [gpu] / #107 dormant).
TARGET_MODEL_DIR = _REPO_ROOT / "models/qwen3-14b/openvino-int4-gpu"
DRAFT_MODEL_DIR = _REPO_ROOT / "models/qwen3-0.6b-pruned-6l/openvino-int8-gpu"

# ~9.7 GB resident + transient CPU staging during load (the 2026-06-21 lesson:
# guard headroom BEFORE the load; a sub-threshold load death-spirals the host).
_HEADROOM_FLOOR_GB = 12.0

_RECLAIM_LINE = re.compile(
    r"MEM_RECLAIM op=(?P<op>\S+) in_use_before=(?P<before>-?\d+)MB "
    r"in_use_after=(?P<after>-?\d+)MB reclaimed=(?P<reclaimed>[+-]?\d+)MB "
    r"avail_before=(?P<avail_before>-?\d+)MB avail_after=(?P<avail_after>-?\d+)MB "
    r"proc_rss_delta=(?P<rss_delta>[+-]?\d+)MB"
)

TINY_PROMPT = "Reply with the single word: ready"


class _ReclaimCollector(logging.Handler):
    """Harvests the wired instrumentation's ``MEM_RECLAIM`` lines.

    The production call sites pass ``log=`` only (no sink), so the harness
    collects the structured lines the armed probe emits — the samples come
    from the REAL instrumented paths, never recomputed here.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.samples: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        m = _RECLAIM_LINE.search(msg)
        if m is None:
            return
        self.samples.append(
            {
                "op": m.group("op"),
                "in_use_before_mb": float(m.group("before")),
                "in_use_after_mb": float(m.group("after")),
                "reclaimed_mb": float(m.group("reclaimed")),
                "available_before_mb": float(m.group("avail_before")),
                "available_after_mb": float(m.group("avail_after")),
                "proc_rss_delta_mb": float(m.group("rss_delta")),
            }
        )


def _available_gb() -> float:
    snap = memory_snapshot()
    return float(snap.get("sys_available_mb", 0.0)) / 1024.0


def _port_5001_in_use() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", 5001)) == 0


def _gpu_driver_version() -> str:
    """GPU driver for the community-grade envelope (fail-soft)."""
    try:
        out = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_VideoController | "
                "Where-Object {$_.Name -match 'Arc'}).DriverVersion",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return out.stdout.strip() or "unavailable"
    except Exception:  # noqa: BLE001 — envelope capture must not kill the run
        return "unavailable"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--settle-seconds", type=float, default=8.0)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if _port_5001_in_use():
        logger.error("REFUSED: BlarAI is UP (:5001 listening) — one model on the GPU at a time.")
        return 1
    avail = _available_gb()
    if avail < _HEADROOM_FLOOR_GB:
        logger.error(
            "REFUSED: %.1f GB available < %.1f GB floor — lean the box first.",
            avail,
            _HEADROOM_FLOOR_GB,
        )
        return 1

    collector = _ReclaimCollector()
    logging.getLogger("shared.inference.shared_pipeline").addHandler(collector)

    box_state_at_start = capture_box_state()
    set_reclaim_probe_enabled(True)
    reload_seconds: list[float] = []
    try:
        if not reclaim_probe_enabled():
            logger.error("Probe failed to arm — aborting.")
            return 1
        logger.info("Probe ARMED. Building the launcher-shape shared pipeline…")

        t0 = time.perf_counter()
        build = build_shared_pipeline(
            model_dir=TARGET_MODEL_DIR,
            draft_model_dir=DRAFT_MODEL_DIR,
            enable_prefix_caching=True,
            device="GPU",
            target_manifest_path=TARGET_MODEL_DIR / "manifest.json",
            draft_manifest_path=DRAFT_MODEL_DIR / "manifest.json",
            model_priority="HIGH",
            kv_cache_precision=None,
            require_signed_draft=False,
        )
        if not build.ok or build.pipeline is None:
            logger.error("Shared pipeline build FAILED: %s", build.error)
            return 1
        wrapper = build.pipeline
        logger.info("Initial build+load took %.1f s.", time.perf_counter() - t0)

        for cycle in range(1, args.cycles + 1):
            if not wrapper.is_loaded:
                t0 = time.perf_counter()
                # The spec-decode pipeline REQUIRES an assistant-token setting in
                # every GenerationConfig (ADR-012); mirror the AO's production value.
                wrapper.generate(
                    TINY_PROMPT,
                    max_new_tokens=8,
                    num_assistant_tokens=NUM_ASSISTANT_TOKENS,
                )
                reload_seconds.append(round(time.perf_counter() - t0, 1))
                logger.info(
                    "Cycle %d: lazy reload via generate() took %.1f s.",
                    cycle,
                    reload_seconds[-1],
                )
            time.sleep(args.settle_seconds)
            logger.info("Cycle %d: calling unload()…", cycle)
            wrapper.unload()
            time.sleep(args.settle_seconds)

        # The process-exit sibling op, once (runbook optional item).
        t0 = time.perf_counter()
        wrapper.generate(
            TINY_PROMPT,
            max_new_tokens=8,
            num_assistant_tokens=NUM_ASSISTANT_TOKENS,
        )
        reload_seconds.append(round(time.perf_counter() - t0, 1))
        time.sleep(args.settle_seconds)
        wrapper.release_gpu_for_exit()
        time.sleep(args.settle_seconds)
    finally:
        set_reclaim_probe_enabled(None)

    by_op: dict[str, list[float]] = {}
    for s in collector.samples:
        by_op.setdefault(s["op"], []).append(s["reclaimed_mb"])
    medians = {op: round(statistics.median(v), 1) for op, v in by_op.items()}
    headline = medians.get("shared_pipeline.14b.unload")

    summary: dict[str, Any] = {
        "ticket": "#900",
        "measurement": "memory_reclaim_shared_14b_unload",
        "route": (
            "B — launcher-shape build_shared_pipeline harness driving the real "
            "unload()/lazy-reload entry points (route A impossible: production "
            "[image_generation].hires_enabled=false)"
        ),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "openvino_version": _OV_VERSION,
        "openvino_genai_version": _OV_GENAI_VERSION,
        "gpu_driver": _gpu_driver_version(),
        "model": {
            "target": str(TARGET_MODEL_DIR.relative_to(_REPO_ROOT)),
            "target_precision": "INT4",
            "draft": str(DRAFT_MODEL_DIR.relative_to(_REPO_ROOT)),
            "draft_precision": "INT8 (pruned 6-layer)",
            "kv_cache_precision": "unset (FP16 default)",
            "prefix_caching": True,
        },
        "methodology": (
            f"{args.cycles} unload cycles + 1 release_gpu_for_exit; "
            f"{args.settle_seconds}s settle around each evict; probe armed via "
            "set_reclaim_probe_enabled(True); samples harvested from the wired "
            "MEM_RECLAIM instrumentation (In-Use = Total − Available, never "
            "working-set); box lean (BlarAI down, guest VM off, OVMS down)."
        ),
        "environment": {
            "box_state_at_start": box_state_at_start,
            "box_state_at_end": capture_box_state(),
        },
        "reload_seconds": reload_seconds,
        "samples": collector.samples,
        "median_reclaimed_mb_by_op": medians,
        "interpretation": (
            "median reclaimed ~9700 MB => memory returns to Windows on evict; "
            "~0/negative => driver retains it (openvino #33896 signature on Arc 140V)"
        ),
        "not_measured": [
            "the app-integrated route-A trigger (a production hires-fix generate) — "
            "[image_generation].hires_enabled=false in production config since the "
            "1536² RAM-spiral incident, so the in-app 14B evict path has no live trigger",
            "image_gen.sdxl.unload / vlm.unload / substrate.embed_cache.unload — "
            "recorded separately in the live-app session (same evening)",
            "the reload-side RAM trajectory (only the evict is bracketed by the probe)",
            "other GPU driver versions (single installed driver)",
            "short-lived-process isolation / blob-cache mitigation variants "
            "(the post-measurement follow-ons #900 tees up)",
        ],
    }

    out_dir = _REPO_ROOT / "docs" / "performance"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out_path = out_dir / f"mem_reclaim_900_shared14b_{stamp}.json"
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print()
    print("=== #900 memory-reclaim (14B headline, route B) ===")
    for op, med in medians.items():
        print(f"{op}: median reclaimed {med} MB over {len(by_op[op])} samples")
    if headline is not None:
        verdict = (
            "MEMORY RETURNS to Windows"
            if headline > 5000.0
            else "#33896 SIGNATURE — driver retained the allocation"
            if headline < 1000.0
            else "PARTIAL reclaim — inspect samples"
        )
        print(f"headline shared_pipeline.14b.unload: {verdict}")
    print(f"results: {out_path}")
    return 0 if collector.samples else 1


if __name__ == "__main__":
    sys.exit(main())
