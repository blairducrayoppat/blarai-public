"""
#796 - Meaning-based preference-contradiction feasibility measurement.
=====================================================================
D-3 follow-up to #792 (docs/research/preference_memory_m2_m3_iteration_plan_2026-07.md
2.2). Measures whether the on-box bge-small-en-v1.5 encoder can serve as the
ADVISORY meaning-based near-duplicate/contradiction signal beside the M1
deterministic Jaccard probe (find_similar_preference), i.e. can it flag
paraphrase/opposite-value preference pairs that share almost no words - the
pairs Jaccard structurally misses - WITHOUT false-alarming on the
word-overlapping-but-different "hard negative" pairs Jaccard is (correctly)
blind to.

For every pair in docs/research/fixtures/preference_contradiction_pairs.json:
  - bge-small cosine similarity (NPU path via the production LeakageDetector
    surface, exactly the encoder the AO already runs for PGOV Stage-5) at the
    128-token window (preferences are short strings).
  - The PRODUCTION Jaccard score (knowledge_bank._pref_similarity_tokens +
    the exact overlap formula from find_similar_preference).

Then:
  - cosine + Jaccard distributions per class (contradiction / hard_negative /
    easy_negative).
  - An ROC-style threshold sweep on cosine: TPR (hit-rate on should_flag
    pairs) vs FPR (false-alarm on negatives), overall and split by
    hard/easy negative, with the rank-based AUC.
  - The same for Jaccard at its production 0.6 gate (the miss quantified).
  - A recommended cosine threshold if a usable operating point exists.

Community-grade recording (testing-data-capture rule): a JSON artifact under
docs/performance/ with hardware/OpenVINO/driver identity, methodology, the
encoder-device actually served, and an explicit "what is NOT measured" list.
NO GPU, NO OVMS, NO AO touched - encoder only, on NPU (or CPU fail-soft).

Usage (from the worktree repo root, with the main-checkout venv + model):
  C:/Users/mrbla/blarai/.venv/Scripts/python.exe \
    scripts/measure_796_contradiction_feasibility.py \
    --model C:/Users/mrbla/blarai/models/bge-small-en-v1.5/onnx-fp16/model.onnx \
    --device NPU
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np

_FIXTURE = _REPO_ROOT / "docs" / "research" / "fixtures" / "preference_contradiction_pairs.json"


def _default_model() -> str:
    local = _REPO_ROOT / "models" / "bge-small-en-v1.5" / "onnx-fp16" / "model.onnx"
    if local.is_file():
        return str(local)
    # Worktrees gitignore models/; fall back to the canonical main checkout.
    return "C:/Users/mrbla/blarai/models/bge-small-en-v1.5/onnx-fp16/model.onnx"


def _quantiles(xs: list[float]) -> dict[str, float]:
    xs = sorted(xs)
    n = len(xs)

    def q(p: float) -> float:
        if n == 1:
            return xs[0]
        k = (n - 1) * p
        lo = int(k)
        hi = min(lo + 1, n - 1)
        return xs[lo] * (1 - (k - lo)) + xs[hi] * (k - lo)

    return {
        "n": n,
        "min": round(min(xs), 4),
        "q25": round(q(0.25), 4),
        "median": round(q(0.50), 4),
        "mean": round(statistics.fmean(xs), 4),
        "q75": round(q(0.75), 4),
        "max": round(max(xs), 4),
        "stdev": round(statistics.stdev(xs), 4) if n > 1 else 0.0,
    }


def _roc_auc(pos: list[float], neg: list[float]) -> float:
    """Rank-based AUC (Mann-Whitney U), tie-aware."""
    if not pos or not neg:
        return float("nan")
    allv = [(s, 1) for s in pos] + [(s, 0) for s in neg]
    allv.sort(key=lambda t: t[0])
    # Average ranks over ties.
    ranks = [0.0] * len(allv)
    i = 0
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # 1-based average rank
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    rank_sum_pos = sum(r for r, (_, lab) in zip(ranks, allv) if lab == 1)
    n_pos, n_neg = len(pos), len(neg)
    u = rank_sum_pos - n_pos * (n_pos + 1) / 2.0
    return round(u / (n_pos * n_neg), 4)


def _sweep(
    pos: list[float], neg_hard: list[float], neg_easy: list[float],
    lo: float, hi: float, step: float,
) -> list[dict[str, Any]]:
    neg_all = neg_hard + neg_easy
    P, Nh, Ne, Na = len(pos), len(neg_hard), len(neg_easy), len(neg_hard) + len(neg_easy)
    rows: list[dict[str, Any]] = []
    t = lo
    while t <= hi + 1e-9:
        tp = sum(1 for s in pos if s >= t)
        fp_h = sum(1 for s in neg_hard if s >= t)
        fp_e = sum(1 for s in neg_easy if s >= t)
        fp = fp_h + fp_e
        tpr = tp / P if P else 0.0
        fpr = fp / Na if Na else 0.0
        precision = tp / (tp + fp) if (tp + fp) else float("nan")
        youden = tpr - fpr
        rows.append({
            "threshold": round(t, 3),
            "tp": tp, "fn": P - tp,
            "fp": fp, "fp_hard": fp_h, "fp_easy": fp_e,
            "tpr_hitrate": round(tpr, 4),
            "fpr_falsealarm": round(fpr, 4),
            "fpr_hard": round(fp_h / Nh, 4) if Nh else 0.0,
            "fpr_easy": round(fp_e / Ne, 4) if Ne else 0.0,
            "precision": round(precision, 4) if precision == precision else None,
            "youden_j": round(youden, 4),
        })
        t += step
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default=_default_model())
    ap.add_argument("--device", default="NPU", help="Encoder device: NPU (production) | CPU | GPU-FORBIDDEN")
    ap.add_argument("--window", type=int, default=128, help="Token window for the encoder (preferences are short).")
    args = ap.parse_args()

    if args.device.upper() == "GPU":
        print("REFUSED: GPU is reserved by another workstream; use NPU or CPU.", file=sys.stderr)
        return 3
    if not Path(args.model).is_file():
        print(f"ERROR: model not found at {args.model}", file=sys.stderr)
        return 2

    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    pairs = data["pairs"]

    # Production Jaccard tokenizer + threshold (imported, not reimplemented).
    from services.assistant_orchestrator.src.knowledge_bank import (
        _pref_similarity_tokens,
        PREFERENCE_SIMILARITY_THRESHOLD,
    )
    from services.assistant_orchestrator.src.pgov import LeakageDetector

    def jaccard(a: str, b: str) -> float:
        ta, tb = _pref_similarity_tokens(a), _pref_similarity_tokens(b)
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / len(ta | tb)

    # Encoder load (NPU production path; fail-soft to CPU inside LeakageDetector).
    det = LeakageDetector(model_path=args.model, max_input_length=args.window, device=args.device)
    t0 = time.perf_counter()
    ok = det.load_model()
    load_s = time.perf_counter() - t0
    if not ok:
        print("ERROR: encoder failed to load", file=sys.stderr)
        return 4

    # Embed every unique string once, then look vectors up per pair.
    uniq = sorted({p["a"] for p in pairs} | {p["b"] for p in pairs})
    embed_t0 = time.perf_counter()
    vecs = det._embed(uniq)  # (len(uniq), 384) L2-normalized
    embed_s = time.perf_counter() - embed_t0
    idx = {s: i for i, s in enumerate(uniq)}

    per_pair: list[dict[str, Any]] = []
    for p in pairs:
        va, vb = vecs[idx[p["a"]]], vecs[idx[p["b"]]]
        cos = float(np.dot(va, vb))  # both already L2-normalized
        jac = jaccard(p["a"], p["b"])
        per_pair.append({
            "id": p["id"], "class": p["class"], "subclass": p.get("subclass"),
            "should_flag": p["should_flag"],
            "a": p["a"], "b": p["b"],
            "cosine": round(cos, 4), "jaccard": round(jac, 4),
        })

    det.unload()

    # Partition scores.
    cos_pos = [r["cosine"] for r in per_pair if r["should_flag"]]
    cos_hard = [r["cosine"] for r in per_pair if r["class"] == "hard_negative"]
    cos_easy = [r["cosine"] for r in per_pair if r["class"] == "easy_negative"]
    jac_pos = [r["jaccard"] for r in per_pair if r["should_flag"]]
    jac_hard = [r["jaccard"] for r in per_pair if r["class"] == "hard_negative"]
    jac_easy = [r["jaccard"] for r in per_pair if r["class"] == "easy_negative"]

    cos_sweep = _sweep(cos_pos, cos_hard, cos_easy, 0.30, 0.98, 0.01)
    jac_sweep = _sweep(jac_pos, jac_hard, jac_easy, 0.05, 0.95, 0.05)

    cos_auc = _roc_auc(cos_pos, cos_hard + cos_easy)
    cos_auc_hard = _roc_auc(cos_pos, cos_hard)
    jac_auc = _roc_auc(jac_pos, jac_hard + jac_easy)

    # Candidate operating points on cosine.
    # (1) Youden-J optimal. (2) Highest threshold with zero hard-negative FP
    # (the precision-first operating point the advisory use case wants).
    best_j = max(cos_sweep, key=lambda r: r["youden_j"])
    zero_hard_fp = [r for r in cos_sweep if r["fp_hard"] == 0]
    # among zero-hard-FP thresholds, the LOWEST threshold (max recall) with no hard FP
    precision_first = min(zero_hard_fp, key=lambda r: r["threshold"]) if zero_hard_fp else None

    # Jaccard at the production gate.
    jac_at_gate = next(
        (r for r in jac_sweep if abs(r["threshold"] - PREFERENCE_SIMILARITY_THRESHOLD) < 1e-9),
        None,
    )

    # Environment / device identity.
    env: dict[str, Any] = {
        "python": sys.version.split()[0],
        "os": f"Windows {sys.getwindowsversion().major}.{sys.getwindowsversion().build}",  # type: ignore[attr-defined]
    }
    try:
        import onnxruntime as ort
        env["onnxruntime"] = ort.__version__
    except Exception:  # noqa: BLE001
        env["onnxruntime"] = "unavailable"
    try:
        import openvino as ov
        env["openvino"] = ov.__version__
        core = ov.Core()
        env["devices"] = {}
        for dev in core.available_devices:
            entry: dict[str, str] = {}
            try:
                entry["name"] = str(core.get_property(dev, "FULL_DEVICE_NAME"))
            except Exception:  # noqa: BLE001
                pass
            for key in ("NPU_DRIVER_VERSION", "GPU_DRIVER_VERSION", "DRIVER_VERSION"):
                try:
                    entry["driver"] = str(core.get_property(dev, key))
                    break
                except Exception:  # noqa: BLE001
                    continue
            env["devices"][dev] = entry
    except Exception:  # noqa: BLE001
        env["openvino"] = "unavailable"

    payload = {
        "measurement": "preference_contradiction_feasibility_796",
        "ticket": "#796",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "encoder": "BAAI/bge-small-en-v1.5 ONNX fp16 (384-dim), mean-pool + L2-norm",
        "surface": "services.assistant_orchestrator.src.pgov.LeakageDetector._embed",
        "requested_device": args.device,
        "active_device": det.active_device,
        "backend": det.backend,
        "token_window": args.window,
        "load_s": round(load_s, 3),
        "embed_s_all_texts": round(embed_s, 3),
        "n_unique_texts": len(uniq),
        "environment": env,
        "fixture": {
            "path": str(_FIXTURE.relative_to(_REPO_ROOT)).replace("\\", "/"),
            "n_pairs": len(pairs),
            "n_should_flag": sum(1 for p in pairs if p["should_flag"]),
            "n_hard_negative": sum(1 for p in pairs if p["class"] == "hard_negative"),
            "n_easy_negative": sum(1 for p in pairs if p["class"] == "easy_negative"),
        },
        "methodology": {
            "cosine": "dot product of L2-normalized bge-small vectors (both texts embedded at the 128-token window).",
            "jaccard": "production knowledge_bank._pref_similarity_tokens + |A n B|/|A u B|; the exact signal find_similar_preference gates on.",
            "roc": "should_flag pairs are the positive class; hard+easy negatives the negative class; threshold sweep 0.30..0.98 step 0.01 on cosine, 0.05..0.95 step 0.05 on jaccard.",
            "auc": "rank-based (Mann-Whitney U), tie-aware.",
        },
        "distributions": {
            "cosine": {
                "should_flag": _quantiles(cos_pos),
                "hard_negative": _quantiles(cos_hard),
                "easy_negative": _quantiles(cos_easy),
            },
            "jaccard": {
                "should_flag": _quantiles(jac_pos),
                "hard_negative": _quantiles(jac_hard),
                "easy_negative": _quantiles(jac_easy),
            },
        },
        "auc": {
            "cosine_vs_all_negatives": cos_auc,
            "cosine_vs_hard_negatives": cos_auc_hard,
            "jaccard_vs_all_negatives": jac_auc,
        },
        "jaccard_at_production_gate": {
            "threshold": PREFERENCE_SIMILARITY_THRESHOLD,
            "point": jac_at_gate,
        },
        "cosine_operating_points": {
            "youden_optimal": best_j,
            "precision_first_zero_hard_fp": precision_first,
        },
        "cosine_sweep": cos_sweep,
        "jaccard_sweep": jac_sweep,
        "per_pair": per_pair,
        "not_measured": [
            "co-resident Qwen3-14B contention (encoder run in isolation; the GPU is reserved by another workstream so no LLM was loaded).",
            "any larger local encoder or a dedicated NLI model (bge-large, gte, e5-large, a cross-encoder, or a local NLI head) - out of scope here; named in the verdict as the option-(b) path if bge-small is insufficient.",
            "the operator's real preference corpus (this is a synthetic golden set; production has <=64 rows).",
            "prompt-prefix variants (bge query/passage instruction prefixes) - symmetric no-prefix similarity is used, matching the LeakageDetector surface.",
            "cross-run variance across NPU vs CPU numerics (prior #720 parity 0.999996; distributions are device-insensitive by construction).",
        ],
    }

    out_dir = _REPO_ROOT / "docs" / "performance"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out_path = out_dir / f"preference_contradiction_796_{stamp}.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # ---- human summary ----
    print(f"\nJSON written: {out_path}")
    print(f"encoder: {det_active(payload)}  load={payload['load_s']}s  embed_all={payload['embed_s_all_texts']}s")
    print("\n=== cosine distributions (bge-small) ===")
    for cls in ("should_flag", "hard_negative", "easy_negative"):
        d = payload["distributions"]["cosine"][cls]
        print(f"  {cls:14} n={d['n']:2}  min={d['min']:.3f}  q25={d['q25']:.3f}  median={d['median']:.3f}  q75={d['q75']:.3f}  max={d['max']:.3f}")
    print("\n=== jaccard distributions (production probe) ===")
    for cls in ("should_flag", "hard_negative", "easy_negative"):
        d = payload["distributions"]["jaccard"][cls]
        print(f"  {cls:14} n={d['n']:2}  min={d['min']:.3f}  median={d['median']:.3f}  max={d['max']:.3f}")
    print(f"\nAUC cosine vs all-neg = {cos_auc}   vs hard-neg = {cos_auc_hard}   |  jaccard vs all-neg = {jac_auc}")
    jg = jac_at_gate
    print(f"\nJaccard @ production gate {PREFERENCE_SIMILARITY_THRESHOLD}: hit-rate={jg['tpr_hitrate']}  false-alarm={jg['fpr_falsealarm']} (the miss #796 targets)")
    print("\n=== cosine sweep (selected rows) ===")
    print(f"  {'thr':>5} {'hit':>6} {'FA':>6} {'FA_hard':>8} {'FA_easy':>8} {'prec':>6} {'J':>6}")
    for r in cos_sweep:
        if abs((r['threshold'] * 100) % 5) < 1e-6:  # every 0.05
            prec = r['precision'] if r['precision'] is not None else float('nan')
            print(f"  {r['threshold']:>5.2f} {r['tpr_hitrate']:>6.2f} {r['fpr_falsealarm']:>6.2f} {r['fpr_hard']:>8.2f} {r['fpr_easy']:>8.2f} {prec:>6.2f} {r['youden_j']:>6.2f}")
    print(f"\nYouden-optimal cosine: thr={best_j['threshold']} hit={best_j['tpr_hitrate']} FA={best_j['fpr_falsealarm']} (hard {best_j['fpr_hard']}, easy {best_j['fpr_easy']})")
    if precision_first:
        print(f"Precision-first (lowest thr with 0 hard-neg FP): thr={precision_first['threshold']} hit={precision_first['tpr_hitrate']} FA_easy={precision_first['fpr_easy']}")
    else:
        print("Precision-first: NO threshold reaches zero hard-negative false alarms.")
    return 0


def det_active(payload: dict[str, Any]) -> str:
    return f"{payload['requested_device']}->{payload['active_device']} ({payload['backend']}, {payload['token_window']}-tok)"


if __name__ == "__main__":
    raise SystemExit(main())
