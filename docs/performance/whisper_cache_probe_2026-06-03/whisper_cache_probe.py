#!/usr/bin/env python
"""Whisper compile-cache empirical probe — BlarAI Vikunja #546.

Settles whether enabling the OpenVINO GPU compile cache (CACHE_DIR=<dir>) for
the Whisper-small STT pipeline saves startup time, net of the cache blob's
on-load integrity-hash cost — the accounting #545 mandated. #545 killed the
14B's cache (9 GB blob, cold read ~ fresh compile); Whisper's blob is far
smaller (~0.5 GB), so the math may come out differently here.

Mirrors the production load path EXACTLY (services/voice/src/engine.py:
``og.WhisperPipeline(model_dir, device="GPU")``) with ONE variable changed:
CACHE_DIR. Does NOT import or modify committed runtime code. Each ``run`` builds
ONE pipeline in a FRESH PROCESS so cold/warm load timing is not contaminated by
in-process GPU/runtime warm state (the confound the in-process de-risk showed:
a second back-to-back load reads faster than a first, masking the write cost —
BUILD_JOURNAL #7/#8).

Output-identity witness: a fixed synthetic 16 kHz signal is transcribed greedily
and the transcript SHA-256'd, so a warm-cache compile that differs from a fresh
compile would be caught (the #545 governance question, for Whisper).
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

def _find_repo_root(start: Path) -> Path:
    """Walk up to the dir holding pyproject.toml (robust to nesting depth)."""
    resolved = start.resolve()
    for cand in [resolved, *resolved.parents]:
        if (cand / "pyproject.toml").is_file():
            return cand
    return resolved.parents[3]


REPO_ROOT = _find_repo_root(Path(__file__))
WHISPER_DIR = REPO_ROOT / "models" / "whisper-small" / "openvino"
SELF = Path(__file__).resolve()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dir_size(p: Path) -> tuple[int, int]:
    files = [f for f in p.rglob("*") if f.is_file()]
    return len(files), sum(f.stat().st_size for f in files)


def _synthetic_speech():
    """Deterministic 3 s, 16 kHz mono float32 signal (a 440 Hz tone)."""
    import math

    sr = 16000
    n = sr * 3
    return [0.1 * math.sin(2 * math.pi * 440 * i / sr) for i in range(n)]


def build_whisper(cache_dir: str):
    """Mirror engine.py's load, CACHE_DIR parametrised. Returns (pipe, load_s)."""
    import openvino_genai as og

    props: dict[str, object] = {}
    if cache_dir:
        props["CACHE_DIR"] = cache_dir
    t0 = time.perf_counter()
    pipe = og.WhisperPipeline(str(WHISPER_DIR), "GPU", **props)
    return pipe, time.perf_counter() - t0


def do_run(args: argparse.Namespace) -> None:
    import openvino
    import openvino_genai as og

    cache_dir = "" if args.mode == "prod" else args.cache_dir
    if args.mode == "cache":
        Path(cache_dir).mkdir(parents=True, exist_ok=True)

    pipe, load_seconds = build_whisper(cache_dir)

    # Output-identity witness (greedy, deterministic). Fail-soft: load-only if
    # the generate API rejects the synthetic input on this build.
    transcript_sha = None
    try:
        cfg = og.WhisperGenerationConfig()
        if hasattr(cfg, "language"):
            cfg.language = "<|en|>"
        text = pipe.generate(_synthetic_speech(), cfg)
        transcript_sha = _sha(str(text).encode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — identity is secondary to load timing
        transcript_sha = f"skip:{type(exc).__name__}"

    cache_files, cache_bytes = (0, 0)
    if args.mode == "cache":
        cache_files, cache_bytes = _dir_size(Path(cache_dir))

    out = {
        "label": args.label,
        "mode": args.mode,
        "cache_dir": cache_dir,
        "openvino": openvino.__version__,
        "openvino_genai": og.__version__,
        "load_seconds": round(load_seconds, 3),
        "transcript_sha256": transcript_sha,
        "cache_dir_files": cache_files,
        "cache_dir_bytes": cache_bytes,
    }
    Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(
        f"[{args.label}] mode={args.mode} load={load_seconds:.2f}s "
        f"cache_files={cache_files} cache_bytes={cache_bytes:,} "
        f"sha={str(transcript_sha)[:12]}"
    )
    del pipe
    gc.collect()


def _integrity_hash_seconds(blob_dir: Path) -> tuple[float, int]:
    """Time a SHA-256 over the whole cache blob — the cost production would pay
    to verify a derived cache before trusting it. Returns (seconds, bytes)."""
    h = hashlib.sha256()
    total = 0
    t0 = time.perf_counter()
    for f in sorted(blob_dir.rglob("*")):
        if f.is_file():
            data = f.read_bytes()
            total += len(data)
            h.update(data)
    return time.perf_counter() - t0, total


def do_compare(args: argparse.Namespace) -> None:
    d = Path(args.dir)
    runs: dict[str, dict] = {}
    for jf in sorted(d.glob("run_*.json")):
        data = json.loads(jf.read_text(encoding="utf-8"))
        runs[data["label"]] = data
    if not runs:
        print("no run_*.json found")
        return

    labels = list(runs.keys())
    print("=== WHISPER CACHE_DIR PROBE — COMPARISON ===")
    first = next(iter(runs.values()))
    print(f"ov={first['openvino']}  genai={first['openvino_genai']}")
    print(f"labels: {labels}\n")

    print("LOAD TIMES (fresh process each):")
    for lab in labels:
        r = runs[lab]
        print(
            f"  {lab:6s} mode={r['mode']:5s} load={r['load_seconds']:7.2f}s "
            f"cache_bytes={r['cache_dir_bytes']:,} sha={str(r['transcript_sha256'])[:12]}"
        )
    print()

    def mean(labs: list[str]) -> float | None:
        vals = [runs[l]["load_seconds"] for l in labs if l in runs]
        return sum(vals) / len(vals) if vals else None

    prod_mean = mean(["prod1", "prod2"])
    warm_mean = mean(["warm1", "warm2"])
    cold = runs.get("cold", {}).get("load_seconds")

    shas = {runs[l]["transcript_sha256"] for l in labels if not str(runs[l]["transcript_sha256"]).startswith("skip")}
    identity = (len(shas) <= 1)

    hash_seconds = blob_bytes = None
    blob = runs.get("cold", {}).get("cache_dir") or runs.get("warm1", {}).get("cache_dir")
    if blob and Path(blob).is_dir():
        hash_seconds, blob_bytes = _integrity_hash_seconds(Path(blob))

    print("VERDICT:")
    print(f"  output identity across runs: {identity}  ({sorted(shas)})")
    if prod_mean is not None:
        print(f"  fresh compile  (prod mean): {prod_mean:.2f}s")
    if cold is not None:
        print(f"  cold cache     (compile+write): {cold:.2f}s")
    if warm_mean is not None:
        print(f"  warm cache     (read, mean):  {warm_mean:.2f}s")
    if hash_seconds is not None:
        print(f"  integrity-hash of {blob_bytes/1e6:.0f} MB blob: {hash_seconds:.2f}s")
    if prod_mean is not None and warm_mean is not None and hash_seconds is not None:
        warm_total = warm_mean + hash_seconds
        net = prod_mean - warm_total
        print(
            f"  warm + integrity-hash = {warm_total:.2f}s  vs fresh {prod_mean:.2f}s  "
            f"=> net {'SAVE' if net > 0 else 'LOSS'} {abs(net):.2f}s"
        )

    verdict = {
        "openvino": first["openvino"],
        "openvino_genai": first["openvino_genai"],
        "labels": labels,
        "load_seconds_by_label": {l: runs[l]["load_seconds"] for l in labels},
        "fresh_compile_mean_s": prod_mean,
        "cold_cache_s": cold,
        "warm_cache_mean_s": warm_mean,
        "blob_bytes": blob_bytes,
        "integrity_hash_seconds": hash_seconds,
        "warm_plus_hash_s": (warm_mean + hash_seconds) if (warm_mean and hash_seconds) else None,
        "net_save_vs_fresh_s": (prod_mean - (warm_mean + hash_seconds)) if (prod_mean and warm_mean and hash_seconds) else None,
        "output_identity": identity,
        "transcript_shas": sorted(shas),
    }
    (d / "_verdict.json").write_text(json.dumps(verdict, indent=2), encoding="utf-8")
    print(f"\nwrote {d / '_verdict.json'}")


def do_all(args: argparse.Namespace) -> None:
    """Orchestrate the 5 fresh-process runs with cooldowns, then compare."""
    d = Path(args.dir)
    d.mkdir(parents=True, exist_ok=True)
    cache_dir = str(d / "_cache")
    import shutil

    shutil.rmtree(cache_dir, ignore_errors=True)
    plan = [
        ("prod", "", "prod1"),
        ("prod", "", "prod2"),
        ("cache", cache_dir, "cold"),  # empty -> compile + write
        ("cache", cache_dir, "warm1"),  # populated -> read
        ("cache", cache_dir, "warm2"),
    ]
    for i, (mode, cd, label) in enumerate(plan):
        cmd = [
            sys.executable, str(SELF), "run",
            "--mode", mode, "--label", label,
            "--out", str(d / f"run_{label}.json"),
        ]
        if mode == "cache":
            cmd += ["--cache-dir", cd]
        print(f"--- run {label} ({mode}) ---", flush=True)
        subprocess.run(cmd, check=True)
        if i < len(plan) - 1:
            print(f"  cooldown {args.cooldown}s...", flush=True)
            time.sleep(args.cooldown)
    do_compare(argparse.Namespace(dir=str(d)))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("run")
    rp.add_argument("--mode", choices=["prod", "cache"], required=True)
    rp.add_argument("--cache-dir", default="", dest="cache_dir")
    rp.add_argument("--label", required=True)
    rp.add_argument("--out", required=True)
    cp = sub.add_parser("compare")
    cp.add_argument("--dir", required=True)
    al = sub.add_parser("all")
    al.add_argument("--dir", required=True)
    al.add_argument("--cooldown", type=float, default=25.0)
    args = ap.parse_args()
    {"run": do_run, "compare": do_compare, "all": do_all}[args.cmd](args)


if __name__ == "__main__":
    main()
