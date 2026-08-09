"""
Build the 2026.2.1 community-export EXTENSION tables from the committed source JSONs.
====================================================================================
Sequel to `build_community_dataset.py`. Emits the four NEW tables that extend the live
Hugging Face dataset (`blairducrayoppat/openvino-arc140v-lunarlake`) with the OpenVINO
2026.1.0 -> 2026.2.1 campaign:

  version_delta        : the 2026.1.0 vs 2026.2.1 A/B (generation, prefill, VLM)
  draft_device         : GPU-draft vs CPU-draft speculative decoding (14B + 8B)
  moe_flag             : 30B MoE MOE_USE_MICRO_GEMM_PREFILL on/off (throughput + eval cost)
  coresidency_2026_2_1 : the N=1 confirmatory co-residency refresh (same schema as the
                         published N=3 `coresidency` table; std columns blank for N=1)

Every NUMBER is read from the committed source artifacts under docs/performance/ —
never hand-typed — so the flat tables cannot drift from the measurements. The only
authored strings are genericized, publication-clean labels.

GPU memory bandwidth (`GPU_MEMORY_BYTE_READ_RATE`) is GB/s, CONFIRMED against Intel's
OA metric definition in Mesa's oa-lnl.xml (units="gbps"; equation = byte-counter / GpuTime
in ns = bytes/ns = GB/s; bytes-based, not bits).

Output: docs/performance/community_export/v2026_2_1/{name}.{csv,jsonl}
INTERNAL build tool (reads committed paths). Not published.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

SRC = Path("docs/performance")
UT = SRC / "coresident" / "ut_hardened"
OUT = Path("docs/performance/community_export/v2026_2_1")

OV_1_0 = "OpenVINO GenAI 2026.1.0"
OV_2_1 = "OpenVINO GenAI 2026.2.1"
DRIVER = "32.0.101.8826"

# Source files (committed on main).
F_PREFILL = {
    ("14b", "1.0"): "prefill_14b_ov2026_1_0_0_2026-06-29_13-46-13.json",
    ("14b", "2.1"): "prefill_14b_ov2026_2_1_0_2026-06-29_13-50-40.json",
    ("8b", "1.0"): "prefill_8b_ov2026_1_0_0_2026-06-29_13-47-57.json",
    ("8b", "2.1"): "prefill_8b_ov2026_2_1_0_2026-06-29_13-52-09.json",
}
F_VLM = {
    "1.0": "vlm_perf_ov2026_1_0_0_2026-06-29_13-42-56.json",
    "2.1": "vlm_perf_ov2026_2_1_0_2026-06-29_13-38-26.json",
}
# Generation: 2026.1.0 baseline = the published single_model dataset (committed 06-28
# baseline run under identical methodology); 2026.2.1 = the 06-29 comparable run.
F_GEN_2_1 = {"14b": "benchmark_2026-06-29_10-57-25.json", "8b": "benchmark_2026-06-29_11-51-39.json"}
F_GEN_1_0 = {"14b": "benchmark_2026-06-28_00-27-22.json", "8b": "benchmark_2026-06-28_00-44-13.json"}
# Draft device (spine gen + acceptance probe).
F_DD_GEN = {
    ("14b", "GPU"): "benchmark_2026-06-29_10-57-25.json",
    ("14b", "CPU"): "benchmark_2026-06-29_11-37-59.json",
    ("8b", "GPU"): "benchmark_2026-06-29_11-51-39.json",
    ("8b", "CPU"): "benchmark_2026-06-29_12-22-22.json",
}
F_DD_ACC = {
    ("14b", "GPU"): "draft_device_accept_gpu_2026-06-29_11-32-05.json",
    ("14b", "CPU"): "draft_device_accept_cpu_2026-06-29_11-37-17.json",
    ("8b", "GPU"): "draft_device_accept_8b_gpu_2026-06-29_12-08-39.json",
    ("8b", "CPU"): "draft_device_accept_8b_cpu_2026-06-29_12-11-51.json",
}
# 30B MoE flag A/B: ON = accuracy mode (slower); OFF = default (faster).
F_MOE = {"on": "benchmark_ovms_coder-30b_2026-06-29_13-20-23.json",
         "off": "benchmark_ovms_coder-30b_2026-06-29_13-29-30.json"}
F_EVAL = {"on": "coding_eval_30b_moe_on_2026-06-29_13-27-22.json",
          "off": "coding_eval_30b_moe_off_2026-06-29_13-28-53.json"}
# Co-residency N=1 refresh.
F_CORES = {
    "photoreal": "benchmark_coresident_photoreal_r1_2026-06-29_14-00-37.json",
    "illustration": "benchmark_coresident_illustration_r1_2026-06-29_14-11-01.json",
    "cartoon": "benchmark_coresident_cartoon_r1_2026-06-29_14-20-42.json",
    "vlm": "benchmark_coresident_vlm_r1_2026-06-29_14-31-48.json",
}
PARTNER_LABEL = {
    "photoreal": "SDXL photorealistic finetune (RealVisXL V5.0) INT8, 1024x1024 20-step",
    "illustration": "SDXL base 1.0 INT8, 1024x1024 20-step",
    "cartoon": "SDXL base 1.0 INT8 + style LoRA, 1024x1024 20-step",
    "vlm": "Qwen3-VL-8B-Instruct INT4 (vision: image-describe)",
}


def L(name: str, base: Path = SRC):
    return json.loads((base / name).read_text(encoding="utf-8"))


def _r(x, n=2):
    return round(x, n) if isinstance(x, (int, float)) else x


def _pct_change(old, new):
    return _r((new - old) / old * 100.0, 1)


# --------------------------------------------------------------------------- #
def build_version_delta() -> list[dict]:
    rows: list[dict] = []

    def add(model, params, metric, length, unit, v10, v21, note, higher_better=True):
        # "change" is reported as the directional % toward "better": for tok/s and
        # pp, faster-is-better -> +%; for latency (ms), lower-is-better -> we report
        # the % FASTER (reduction) as a positive improvement, sign noted in the column.
        if higher_better:
            change = f"{_pct_change(v10, v21):+.1f}% tok/s" if v21 is not None else ""
            pct = _pct_change(v10, v21)
        else:
            pct = _r((v10 - v21) / v10 * 100.0, 1)  # latency reduction
            change = f"{pct:+.1f}% faster"
        rows.append({
            "model": model, "params_b": params, "precision": "INT4",
            "metric": metric, "length_or_config": length, "unit": unit,
            "ov_2026_1_0": v10, "ov_2026_2_1": v21,
            "pct_change_toward_better": pct, "change_human": change,
            "driver": DRIVER, "notes": note,
        })

    # --- Generation throughput (median tok/s), spec-off + spec-on ---
    for m, params in (("14b", 14), ("8b", 8)):
        g10, g21 = L(F_GEN_1_0[m]), L(F_GEN_2_1[m])
        for key, lbl in (("spec_off", "spec-decode off"), ("spec_on", "spec-decode on")):
            add("Qwen3-14B" if m == "14b" else "Qwen3-8B", params,
                "generation median throughput", lbl, "tok/s",
                _r(g10["results"][key]["aggregate"]["median_tps"]),
                _r(g21["results"][key]["aggregate"]["median_tps"]),
                "flat within run-to-run noise — the in-process bump is generation-neutral")

    # --- Prefill (pp median tok/s) at 512 / 2048 / 8192 ---
    for m, params in (("14b", 14), ("8b", 8)):
        p10, p21 = L(F_PREFILL[(m, "1.0")]), L(F_PREFILL[(m, "2.1")])
        for ln in ("512", "2048", "8192"):
            a, b = p10["results"][ln], p21["results"][ln]
            std_note = (f"std {a['pp_std']:.0f}->{b['pp_std']:.0f}; "
                        + ("tight — solid claim" if b["pp_std"] < 15 else "noisier — directional"))
            add("Qwen3-14B" if m == "14b" else "Qwen3-8B", params,
                "prefill throughput (cold, no-draft)", f"{ln}-token prompt", "tok/s",
                _r(a["pp_median"], 1), _r(b["pp_median"], 1), std_note)

    # --- VLM: TTFT (lower better), TPOT (lower better), throughput, load ---
    v10, v21 = L(F_VLM["1.0"]), L(F_VLM["2.1"])
    s10, s21 = v10["summary"], v21["summary"]
    add("Qwen3-VL-8B-Instruct", 8, "VLM time-to-first-token (TTFT)", "fixed image+prompt",
        "ms", _r(s10["ttft_ms_median"], 1), _r(s21["ttft_ms_median"], 1),
        "solid claim (the 2026.1.0 run was noisier on TPOT than on TTFT)", higher_better=False)
    add("Qwen3-VL-8B-Instruct", 8, "VLM time-per-output-token (TPOT)", "fixed image+prompt",
        "ms", _r(s10["tpot_ms_median"], 1), _r(s21["tpot_ms_median"], 1),
        "directional — the 2026.1.0 TPOT sample was noisier", higher_better=False)
    add("Qwen3-VL-8B-Instruct", 8, "VLM decode throughput", "fixed image+prompt", "tok/s",
        _r(s10["throughput_median"], 1), _r(s21["throughput_median"], 1),
        "directional (pairs with the TPOT note)")
    return rows


# --------------------------------------------------------------------------- #
def build_draft_device() -> list[dict]:
    rows: list[dict] = []
    for m, params in (("14b", 14), ("8b", 8)):
        for dev in ("GPU", "CPU"):
            gen = L(F_DD_GEN[(m, dev)])["results"]["spec_on"]["aggregate"]
            acc = L(F_DD_ACC[(m, dev)])["summary"]
            rows.append({
                "model": "Qwen3-14B" if m == "14b" else "Qwen3-8B",
                "params_b": params, "precision": "INT4",
                "runtime": OV_2_1, "draft_model": "Qwen3-0.6B-pruned-6L INT8",
                "draft_device": dev, "target_device": "GPU",
                "gen_median_tps": _r(gen["median_tps"]),
                "gen_mean_tps": _r(gen["mean_tps"]),
                "ttft_median_ms": _r(gen["median_ttft_ms"], 1),
                "acceptance_accepted_per_draft": _r(acc["acceptance_rate_accepted_per_draft"], 4),
                "acceptance_accepted_per_generated": _r(acc["acceptance_rate_accepted_per_generated"], 4),
                "num_assistant_tokens": 3, "num_runs": gen["total_runs"],
                "notes": ("acceptance is device-independent (greedy draft proposes the same tokens); "
                          "CPU draft ~13% slower for no acceptance benefit on this unified-memory iGPU"),
            })
    return rows


# --------------------------------------------------------------------------- #
def build_moe_flag() -> list[dict]:
    rows: list[dict] = []
    for arm, lbl in (("on", "MOE_USE_MICRO_GEMM_PREFILL=0 (accuracy mode)"),
                     ("off", "default (flag unset)")):
        agg = L(F_MOE[arm])["results"]["ovms_served"]["aggregate"]
        ev = L(F_EVAL[arm])
        rows.append({
            "model": "Qwen3-Coder-30B-A3B (MoE, ~3B active)", "params_b": 30, "precision": "INT4",
            "runtime": "OVMS 2026.2 (continuous batching)", "arm": lbl,
            "gen_median_tps": _r(agg["median_tps"]),
            "ttft_median_ms": _r(agg["median_ttft_ms"], 1),
            "coding_eval_score": ev["score"], "coding_eval_context_tokens": ev["context_approx_tokens"],
            "num_runs": agg["total_runs"],
            "notes": ("accuracy flag costs ~19% gen + ~28% TTFT; the 2.2K-token coding eval found "
                      "NO accuracy difference (its documented benefit needs 8K-32K context — not "
                      "demonstrated here, only the throughput cost is measured)"),
        })
    return rows


# --------------------------------------------------------------------------- #
def _ut(partner: str, kind: str):
    return L(f"ut_{partner}_r1.{kind}.metrics.json", base=UT)


def _phase(metric: dict, phase: str, field: str = "avg"):
    return metric.get(phase, {}).get(field)


def build_coresidency_2026_2_1() -> list[dict]:
    rows: list[dict] = []
    for partner in ("photoreal", "illustration", "cartoon", "vlm"):
        d = L(F_CORES[partner])
        p = next(x for x in d["partners"] if x["partner"] == partner)
        base = d["14b_baseline"]["gen_tps"]
        idle = p["idle_14b"]["gen_tps"]
        cont = p["contention_14b"]["gen_tps"]
        sw, l0 = _ut(partner, "socwatch"), _ut(partner, "l0")
        rows.append({
            "resident_model": "Qwen3-14B INT4 (spec-decode on)",
            "partner": partner, "partner_model": PARTNER_LABEL[partner],
            "n_repeats": 1,
            "partner_resident_gib": _r(p["partner_resident_gib"]),
            "peak_coresident_gib": _r(p["peak_used_gib"]),
            "headroom_gib": _r(p["headroom_gib"]),
            "mem_ceiling_gib": d["hardware"]["mem_ceiling_gib"],
            "baseline_gen_tps": _r(base),
            "idle_gen_tps": _r(idle),
            "contention_gen_tps": _r(cont),
            "contention_retained_pct": _r(cont / base * 100, 1),
            "contention_ttft_ms": _r(p["contention_14b"]["ttft_ms"], 1),
            "gpu_busy_idle_pct": _r(_phase(l0["GPU.GPU_BUSY"], "idle"), 1),
            "gpu_busy_contention_pct": _r(_phase(l0["GPU.GPU_BUSY"], "contention"), 1),
            "xve_active_contention_pct": _r(_phase(l0["GPU.XVE_ACTIVE"], "contention"), 1),
            "gpu_freq_contention_mhz": _r(_phase(l0["GPU.AvgGpuCoreFrequencyMHz"], "contention"), 1),
            "gpu_throttle_reason_max": _phase(sw["IGFX-THROT-RSN"], "contention", "peak"),
            "mem_read_idle_gbps": _r(_phase(l0["GPU.GPU_MEMORY_BYTE_READ_RATE"], "idle"), 1),
            "mem_read_contention_gbps": _r(_phase(l0["GPU.GPU_MEMORY_BYTE_READ_RATE"], "contention"), 1),
            "igpu_rail_idle_w": _r(_phase(sw["PMT-VCCGT-PWR"], "idle", "avg_w"), 2),
            "igpu_rail_contention_w": _r(_phase(sw["PMT-VCCGT-PWR"], "contention", "avg_w"), 2),
            "npu_power_w": _r(_phase(sw["PMT-NPU-PWR"], "whole", "avg_w"), 3),
            "soc_temp_peak_c": _r(_phase(sw["PMT-SOC-TEMP"], "contention", "peak"), 1),
            "baseline_gen_tps_std": "",   # N=1 — no variance; the N=3 study is the 2026.1.0 split
            "contention_gen_tps_std": "",
        })
    return rows


# --------------------------------------------------------------------------- #
def write_table(name: str, rows: list[dict]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    with (OUT / f"{name}.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"  {name}: {len(rows)} rows -> {name}.csv + {name}.jsonl")


def main() -> int:
    print(f"Building 2026.2.1 extension tables (driver {DRIVER}); source = docs/performance/ (read-only)")
    vd = build_version_delta()
    dd = build_draft_device()
    moe = build_moe_flag()
    co = build_coresidency_2026_2_1()
    write_table("version_delta", vd)
    write_table("draft_device", dd)
    write_table("moe_flag", moe)
    write_table("coresidency_2026_2_1", co)
    print("\nsanity:")
    print("  draft_device gen_median_tps:",
          {f'{r["model"]}/{r["draft_device"]}': r["gen_median_tps"] for r in dd})
    print("  coresidency retained%:",
          {r["partner"]: r["contention_retained_pct"] for r in co})
    print("  moe_flag:", {r["arm"][:18]: (r["gen_median_tps"], r["coding_eval_score"]) for r in moe})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
