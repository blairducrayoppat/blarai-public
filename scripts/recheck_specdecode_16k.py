"""Targeted re-check: does speculative decoding still collapse at 16K context?

BACKGROUND
----------
March 2026 Task 4.3 (NAT sweep x context bands) found speculative-decode
acceptance = 0.000 at >=16K context — but that run used the OLD draft model
(Qwen3-0.6B INT4 28L) on OpenVINO 2026.0. Since then TWO things changed:
  * ISS-1 fix (2026-05-21): num_assistant_tokens moved to per-request GenerationConfig.
  * Draft swap (2026-05-22): Qwen3-0.6B-pruned-6L INT8 is the current production draft.
  * OpenVINO upgraded to 2026.1.

This re-runs ONLY the 16K band (plus 2K + 8K controls, to show the acceptance
*curve* rather than a lone number) with the CURRENT production draft + NAT=3
(the locked DEC-01 value). It reuses the proven March measurement functions
verbatim (loaded by file path) so the acceptance math (m_batch_sizes) is identical.

Writes a fresh file under docs/performance/ — it does NOT touch the March evidence.
"""
from __future__ import annotations

import datetime as dt
import gc
import importlib.util
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Reuse the proven March measurement module verbatim (load by file path).
_SRC = ROOT / "phase2_gates" / "scripts" / "run_p5_task4_3_nat_sweep.py"
_spec = importlib.util.spec_from_file_location("nat_sweep_proven", _SRC)
nat = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nat)  # runs imports + defs only (main is __main__-guarded)

import openvino as ov  # noqa: E402
import openvino_genai as ov_genai  # noqa: E402
from transformers import AutoTokenizer  # noqa: E402

MODEL_14B = ROOT / "models" / "qwen3-14b" / "openvino-int4-gpu"
DRAFT_CURRENT = ROOT / "models" / "qwen3-0.6b-pruned-6l" / "openvino-int8-gpu"
BANDS = [2048, 8192, 16384]   # short control, mid control, the question
NAT = 3                        # locked DEC-01 production value
WARMUP = 2
MEASURED = 4


def main() -> None:
    print("=" * 64)
    print("Spec-decode 16K re-check (post-ISS-1 fix, current pruned-6L INT8 draft)")
    print("=" * 64)

    power = nat.enforce_ac_power_or_fail_closed()
    print(f"Power: plugged={power.get('power_plugged')}")

    for path, label in [(MODEL_14B, "target 14B"), (DRAFT_CURRENT, "draft")]:
        assert (path / "openvino_model.xml").exists(), f"{label} missing: {path}"
    print(f"Target: {MODEL_14B.name}  Draft: {DRAFT_CURRENT.parent.name}/{DRAFT_CURRENT.name}")

    tok = AutoTokenizer.from_pretrained(str(MODEL_14B), trust_remote_code=True)
    prompts = {}
    for b in BANDS:
        p, actual = nat.build_prompt_for_band(tok, b)
        prompts[b] = (p, actual)
        print(f"  built band={b}: actual {actual} tokens")

    pipe, compile_ms, err = nat.create_main_pipeline(MODEL_14B, DRAFT_CURRENT)
    if pipe is None:
        print(f"FATAL: pipeline compile failed: {err}")
        sys.exit(1)
    print(f"Pipeline compiled in {compile_ms:.0f} ms")

    gen_cfg = nat.make_gen_config(NAT)
    results = []
    for b in BANDS:
        prompt, actual = prompts[b]
        print(f"\n[band={b} nat={NAT}] warmup x{WARMUP}, measure x{MEASURED}")
        for _ in range(WARMUP):
            nat.run_single_generation(pipe, tok, prompt, gen_cfg, NAT, True)
        runs = [nat.run_single_generation(pipe, tok, prompt, gen_cfg, NAT, True)
                for _ in range(MEASURED)]
        valid = [r for r in runs if r["ok"]]
        tps = [r["combined_tps"] for r in valid if r["combined_tps"] is not None]
        drafted = sum(r["tokens_drafted_total"] or 0 for r in valid)
        accepted = sum(r["tokens_accepted_total"] or 0 for r in valid)
        agg_ar = (accepted / drafted) if drafted else None
        rss = max((r["peak_rss_mb"] for r in valid if r.get("peak_rss_mb")), default=None)
        rec = {
            "band": b,
            "actual_prompt_tokens": actual,
            "nat": NAT,
            "valid_runs": len(valid),
            "combined_tps_mean": round(statistics.fmean(tps), 3) if tps else None,
            "acceptance_rate_aggregate": round(agg_ar, 4) if agg_ar is not None else None,
            "acceptance_rate_by_step_last": valid[-1]["acceptance_rate_by_step"] if valid else None,
            "tokens_drafted_total": drafted,
            "tokens_accepted_total": accepted,
            "peak_rss_mb": rss,
        }
        results.append(rec)
        print(f"  -> tps={rec['combined_tps_mean']} "
              f"AR={rec['acceptance_rate_aggregate']} rss={rss} MB")
        gc.collect()

    out = {
        "benchmark": "specdecode_16k_recheck_post_iss1",
        "purpose": ("Re-check spec-decode acceptance at 16K after the 2026-05 ISS-1 fix "
                    "+ pruned-6L INT8 draft swap. Compare vs March Task 4.3 which found "
                    "acceptance 0.000 at >=16K on the old INT4 28L draft."),
        "timestamp_utc": nat.now_iso(),
        "commit": nat.git_head(),
        "config": {
            "target_model": str(MODEL_14B),
            "draft_model": str(DRAFT_CURRENT),
            "openvino_version": ov.__version__,
            "openvino_genai_version": ov_genai.__version__,
            "nat": NAT,
            "bands": BANDS,
            "warmup_runs": WARMUP,
            "measured_runs": MEASURED,
            "max_new_tokens": nat.MAX_NEW_TOKENS,
            "scheduler_cache_gb": nat.SCHEDULER_CACHE_GB,
            "pipeline_compile_ms": compile_ms,
            "power_envelope": power,
        },
        "march_comparison": {
            "march_acceptance_at_16k": 0.0,
            "march_draft": "Qwen3-0.6B INT4 28L",
            "march_source": "phase2_gates/evidence/p5_task4_3_nat_sweep_matrix.json",
        },
        "results": results,
    }
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    out_path = ROOT / "docs" / "performance" / f"specdecode_16k_recheck_{ts}.json"
    nat.write_json_atomic(out_path, out)
    print(f"\nWROTE {out_path}")
    print("DONE")


if __name__ == "__main__":
    main()
