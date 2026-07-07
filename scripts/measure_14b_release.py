"""Milestone-1 Phase B — 14B release/reload memory measurement harness.

Answers, by measurement on THIS Lunar Lake box: when BlarAI's 14B is released via
``SharedInferencePipeline.unload()``, how much host RAM + iGPU shared-memory
actually returns — and does the Arc-140V carve-out come back on an *in-process*
release (openvino #33896) without a process restart?

This is the **B1 (standalone, non-verdict)** harness: it builds its OWN shared
pipeline (the SAME ``build_shared_pipeline`` the launcher uses, same model/draft/
manifest/device args) in a throwaway process, then cycles
``measure -> unload() -> settle -> measure -> reload -> measure`` and writes every
sample to JSONL. The authoritative #33896 read comes from B2 (the same unload in
the long-lived live BlarAI process) — see ``scripts/measure_b2_hook.py``.

READ-ONLY w.r.t. the system except for loading/unloading a model in ITS OWN
process (fully reversible; touches no config, no OVMS, no VM, makes no network
call). Run with the BlarAI venv and with the live BlarAI shut down (one 14B fits
at a time on the 31.3 GB unified pool).

Usage (elevated not required; BlarAI must be DOWN):
  .venv\\Scripts\\python.exe scripts\\measure_14b_release.py --cycles 3 \\
      --out docs/handoffs/phaseB_b1.jsonl --label B1-standalone
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from statistics import median

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from shared.constants import DRAFT_MODEL_OV_PATH, TARGET_MODEL_OV_PATH  # noqa: E402
from shared.inference.shared_pipeline import build_shared_pipeline  # noqa: E402

# PowerShell one-shot that returns the full memory+GPU vector for one PID as JSON.
# Mirrors scripts/perf_snapshot.py's per-PID GPU pattern, extended with the
# gate-identical \\Memory\\Available MBytes, Committed Bytes, the per-PID GPU
# Local/Shared/Total-Committed, and the adapter-wide shared (driver-residue check).
_PS_SAMPLE = r"""
$ErrorActionPreference='SilentlyContinue'
$tp = __PID__
$paths = @(
 '\Memory\Available MBytes','\Memory\Committed Bytes','\Memory\Free & Zero Page List Bytes',
 '\GPU Process Memory(*)\Local Usage','\GPU Process Memory(*)\Total Committed',
 '\GPU Process Memory(*)\Shared Usage','\GPU Adapter Memory(*)\Shared Usage')
$cs = (Get-Counter -Counter $paths -ErrorAction SilentlyContinue).CounterSamples
function S($pat){ ($cs | Where-Object { $_.Path -like $pat -and $_.InstanceName -like "pid_${tp}_*" } | Measure-Object CookedValue -Sum).Sum }
$av  = ($cs | Where-Object { $_.Path -like '*available mbytes*' }).CookedValue
$cm  = ($cs | Where-Object { $_.Path -like '*committed bytes*' }).CookedValue/1MB
$fz  = ($cs | Where-Object { $_.Path -like '*free*zero page list*' }).CookedValue/1MB
$gl  = (S '*gpu process memory*local usage*')/1MB
$gt  = (S '*gpu process memory*total committed*')/1MB
$gsh = (S '*gpu process memory*shared usage*')/1MB
$ash = ($cs | Where-Object { $_.Path -like '*gpu adapter memory*shared usage*' } | Measure-Object CookedValue -Sum).Sum/1MB
$ws  = 0; $p = Get-Process -Id $tp -ErrorAction SilentlyContinue; if ($p) { $ws = $p.WorkingSet64/1MB }
[pscustomobject]@{
  avail_mb=[int]$av; committed_mb=[int]$cm; freezero_mb=[int]$fz;
  gpu_local_mb=[int]$gl; gpu_totcommit_mb=[int]$gt; gpu_shared_mb=[int]$gsh;
  adapter_shared_mb=[int]$ash; host_ws_mb=[int]$ws
} | ConvertTo-Json -Compress
"""


def ps_sample(pid: int) -> dict:
    """One full memory+GPU vector for *pid* via PowerShell perf counters."""
    script = _PS_SAMPLE.replace("__PID__", str(pid))
    for _ in range(3):
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, text=True, timeout=40,
            )
            txt = out.stdout.strip()
            if txt:
                return json.loads(txt)
        except Exception:  # noqa: BLE001 — measurement must not crash on a flaky counter read
            time.sleep(0.5)
    return {}


def sample_n(pid: int, n: int, interval: float) -> tuple[dict, list[dict]]:
    """Take *n* samples; return (medians, raw). Medians per numeric key."""
    raw = []
    for i in range(n):
        s = ps_sample(pid)
        if s:
            raw.append(s)
        if i < n - 1:
            time.sleep(interval)
    med = {}
    if raw:
        for k in raw[0]:
            vals = [r[k] for r in raw if k in r]
            med[k] = int(median(vals)) if vals else None
    return med, raw


def _gen(pipe, prompt: str, n: int = 8) -> str:
    """Tiny generation (forces first-touch GPU alloc / triggers lazy reload)."""
    import openvino_genai as ov  # type: ignore[import-untyped]
    try:
        cfg = ov.GenerationConfig()
        cfg.max_new_tokens = n
        return str(pipe.generate(prompt, cfg))
    except Exception:  # noqa: BLE001
        return str(pipe.generate(prompt, max_new_tokens=n))


def settle_gpu(pid: int, settle_max: float, log) -> tuple[int, float, bool]:
    """After unload(): poll per-PID GPU until stable (Δ<100MB over 3 reads) or timeout.

    Returns (settled_gpu_local_mb, seconds_to_settle, stabilized?).
    """
    t0 = time.time()
    last3: list[int] = []
    while time.time() - t0 < settle_max:
        s = ps_sample(pid)
        g = s.get("gpu_local_mb", -1)
        last3 = (last3 + [g])[-3:]
        log(f"      settle t+{time.time()-t0:4.0f}s gpu_local={g}MB")
        if len(last3) == 3 and (max(last3) - min(last3)) < 100:
            return g, time.time() - t0, True
        time.sleep(2)
    return (last3[-1] if last3 else -1), time.time() - t0, False


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase B 14B release/reload measurement")
    ap.add_argument("--cycles", type=int, default=3)
    ap.add_argument("--samples", type=int, default=10, help="samples per before/after phase")
    ap.add_argument("--settle-max", type=float, default=60.0)
    ap.add_argument("--out", default="docs/handoffs/phaseB_b1.jsonl")
    ap.add_argument("--label", default="B1-standalone")
    args = ap.parse_args()

    out_path = (_REPO / args.out) if not os.path.isabs(args.out) else Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pid = os.getpid()

    def log(msg: str) -> None:
        print(msg, flush=True)

    def emit(rec: dict) -> None:
        rec = {"label": args.label, "pid": pid, **rec}
        with out_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")

    log(f"=== Phase B harness ({args.label}) pid={pid} -> {out_path} ===")
    log(f"  target={TARGET_MODEL_OV_PATH}  draft={DRAFT_MODEL_OV_PATH}")

    # --- Build the 14B (same args as launcher __main__.py:1385) -------------
    t0 = time.time()
    build = build_shared_pipeline(
        model_dir=_REPO / TARGET_MODEL_OV_PATH,
        draft_model_dir=_REPO / DRAFT_MODEL_OV_PATH,
        enable_prefix_caching=True,
        device="GPU",
        target_manifest_path=_REPO / TARGET_MODEL_OV_PATH / "manifest.json",
        draft_manifest_path=_REPO / DRAFT_MODEL_OV_PATH / "manifest.json",
        model_priority="HIGH",
    )
    if not build.ok or build.pipeline is None:
        log(f"  BUILD FAILED: {build.error}")
        return 1
    pipe = build.pipeline
    log(f"  built in {time.time()-t0:.1f}s; warming…")
    log(f"  warm out: {_gen(pipe, 'Hello', 8)!r}")

    for c in range(1, args.cycles + 1):
        log(f"\n--- cycle {c}/{args.cycles} ---")
        before, _ = sample_n(pid, args.samples, 1.0)
        log(f"  BEFORE: avail={before.get('avail_mb')} commit={before.get('committed_mb')} "
            f"gpu_local={before.get('gpu_local_mb')} adapter={before.get('adapter_shared_mb')} "
            f"hostWS={before.get('host_ws_mb')}")
        emit({"cycle": c, "phase": "before", **before})

        # --- the mutation: production unload() (one gc.collect inside) -------
        tu = time.time()
        pipe.unload()
        log(f"  unload() returned in {time.time()-tu:.2f}s; settling…")

        settled_gpu, settle_s, stable = settle_gpu(pid, args.settle_max, log)
        after, _ = sample_n(pid, args.samples, 1.0)
        log(f"  AFTER : avail={after.get('avail_mb')} commit={after.get('committed_mb')} "
            f"gpu_local={after.get('gpu_local_mb')} adapter={after.get('adapter_shared_mb')} "
            f"hostWS={after.get('host_ws_mb')}  (settled {settle_s:.0f}s stable={stable})")
        emit({"cycle": c, "phase": "after", "settle_s": round(settle_s, 1),
              "stabilized": stable, **after})

        # --- labeled DIAGNOSTIC: a SECOND gc.collect (NOT the verdict read) --
        gc.collect()
        time.sleep(5)
        diag, _ = sample_n(pid, 3, 1.0)
        log(f"  +5s 2nd-gc DIAG: gpu_local={diag.get('gpu_local_mb')} "
            f"avail={diag.get('avail_mb')} (diagnostic only)")
        emit({"cycle": c, "phase": "after_2nd_gc_diag", **diag})

        # --- reload (fresh build via lazy generate) + coherence -------------
        tr = time.time()
        coh = _gen(pipe, "What is two plus two? Reply with just the number.", 16)
        reload_s = time.time() - tr
        ok = "4" in coh or "four" in coh.lower()
        log(f"  reload+coherence in {reload_s:.1f}s: ok={ok} out={coh!r}")
        rel, _ = sample_n(pid, args.samples, 1.0)
        emit({"cycle": c, "phase": "reloaded", "reload_s": round(reload_s, 1),
              "coherent": ok, "coherence_out": coh[:120], **rel})

        # --- per-cycle deltas (the headline) --------------------------------
        d_avail = (after.get("avail_mb", 0) - before.get("avail_mb", 0))
        d_gpu = (before.get("gpu_local_mb", 0) - after.get("gpu_local_mb", 0))
        d_adapter = (before.get("adapter_shared_mb", 0) - after.get("adapter_shared_mb", 0))
        log(f"  >> cycle {c} DELTAS: freed RAM(avail +)={d_avail}MB  "
            f"freed GPU(local -)={d_gpu}MB  freed adapter-shared={d_adapter}MB")
        emit({"cycle": c, "phase": "delta", "freed_avail_mb": d_avail,
              "freed_gpu_local_mb": d_gpu, "freed_adapter_shared_mb": d_adapter})

    log("\n=== done ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
