"""
Build the community-export flat tables from the committed source JSONs.
=======================================================================
Emits viewer-friendly `single_model` + `coresidency` tables (CSV + JSONL) for the
Hugging Face dataset. Every NUMBER is read from the committed source artifacts — never
hand-typed — so the flat tables cannot drift from the measurements. The only authored
strings are genericized, publication-clean labels (no internal slash-command names).

Source of truth (read-only):
  - benchmark_2026-06-28_00-27-22.json   (Qwen3-14B INT4, OpenVINO GenAI)
  - benchmark_2026-06-28_00-44-13.json   (Qwen3-8B  INT4, OpenVINO GenAI)
  - benchmark_ovms_coder-30b_2026-06-28_08-32-38.json  (Qwen3-Coder-30B-A3B, OVMS)
  - coresident_14b_pairings_hardened_2026-06-28.json   (co-residency, N=3, UT)

Output: docs/performance/community_export/{single_model,coresidency}.{csv,jsonl}
INTERNAL build tool (reads committed paths). Not published.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

SRC = Path("docs/performance")
OUT = Path("docs/performance/community_export")

HARDWARE = "Intel Core Ultra 7 258V (Lunar Lake) + Arc 140V (Xe2 iGPU)"
DRIVER = "32.0.101.8826"

# Genericized, publication-clean co-residency partner labels (the internal
# slash-command tags in the source are intentionally dropped).
PARTNER_LABEL = {
    "photoreal": "SDXL photorealistic finetune (RealVisXL V5.0) INT8, 1024x1024 30-step",
    "illustration": "SDXL base 1.0 INT8, 1024x1024 30-step",
    "cartoon": "SDXL base 1.0 INT8 + style LoRA, 1024x1024 30-step",
    "vlm": "Qwen3-VL-8B-Instruct INT4 (vision: image-describe)",
}


def _round(x, n=2):
    return round(x, n) if isinstance(x, (int, float)) else x


def build_single_model() -> list[dict]:
    rows: list[dict] = []

    def gen_rows(path: str, model: str, params_b, runtime: str, draft: str):
        d = json.loads((SRC / path).read_text(encoding="utf-8"))
        for key, label in (("spec_off", "spec-decode off"), ("spec_on", "spec-decode on")):
            r = d["results"][key]
            agg, pf = r["aggregate"], r["prefill"]
            pp_note = (
                "true prefill rate (config-independent)"
                if key == "spec_off"
                else "backend artifact under speculative ContinuousBatching — cite the spec-off pp as the prefill rate"
            )
            rows.append({
                "model": model, "params_b": params_b, "precision": "INT4", "runtime": runtime,
                "config": label,
                "gen_median_tps": _round(agg["median_tps"]),
                "gen_mean_tps": _round(agg["mean_tps"]),
                "gen_p95_tps": _round(agg["p95_tps"]),
                "ttft_median_ms": _round(agg["median_ttft_ms"], 1),
                "prefill_pp_median_tps": _round(pf["median_pp"], 1),
                "prefill_pp_note": pp_note,
                "prefill_input_tokens": int(pf["mean_input_tokens"]),
                "num_runs": agg["total_runs"], "num_warmup": d["config_stamp"]["num_warmup"],
                "draft_model": draft if key == "spec_on" else "",
                "notes": "",
            })

    gen_rows("benchmark_2026-06-28_00-27-22.json", "Qwen3-14B", 14,
             "OpenVINO GenAI 2026.1.0", "Qwen3-0.6B-pruned-6L INT8 (GPU)")
    gen_rows("benchmark_2026-06-28_00-44-13.json", "Qwen3-8B", 8,
             "OpenVINO GenAI 2026.1.0", "Qwen3-0.6B-pruned-6L INT8 (GPU)")

    # 30B MoE via OVMS — different shape (results.ovms_served)
    d = json.loads((SRC / "benchmark_ovms_coder-30b_2026-06-28_08-32-38.json").read_text(encoding="utf-8"))
    r = d["results"]["ovms_served"]
    agg, pf = r["aggregate"], r["prefill"]
    rows.append({
        "model": "Qwen3-Coder-30B-A3B (MoE, ~3B active)", "params_b": 30, "precision": "INT4",
        "runtime": "OVMS 2026.2 (continuous batching)", "config": "single-stream",
        "gen_median_tps": _round(agg["median_tps"]), "gen_mean_tps": _round(agg["mean_tps"]),
        "gen_p95_tps": _round(agg["p95_tps"]), "ttft_median_ms": _round(agg["median_ttft_ms"], 1),
        "prefill_pp_median_tps": _round(pf["median_pp"], 1),
        "prefill_pp_note": "MoE prefill routes every token across all experts (full ~30B compute)",
        "prefill_input_tokens": int(pf["mean_input_tokens"]),
        "num_runs": agg["total_runs"], "num_warmup": d["config_stamp"]["num_warmup"],
        "draft_model": "", "notes": "MoE: fastest decode + TTFT, slowest prefill of the set",
    })
    return rows


def build_coresidency() -> list[dict]:
    d = json.loads((SRC / "coresident_14b_pairings_hardened_2026-06-28.json").read_text(encoding="utf-8"))
    rows: list[dict] = []
    for p in d["pairings"]:
        m = p["metrics"]

        def mean(k):
            return m[k]["mean"]

        def std(k):
            return m[k]["std"]

        base = mean("baseline_gen_tps")
        cont = mean("contention_gen_tps")
        rows.append({
            "resident_model": "Qwen3-14B INT4 (spec-decode on)",
            "partner": p["partner"],
            "partner_model": PARTNER_LABEL[p["partner"]],
            "n_repeats": p["n_runs"],
            "partner_resident_gib": _round(mean("partner_resident_gib")),
            "peak_coresident_gib": _round(mean("peak_co_resident_gib")),
            "headroom_gib": _round(mean("headroom_gib")),
            "mem_ceiling_gib": d["hardware"]["mem_ceiling_gib"],
            "baseline_gen_tps": _round(base),
            "idle_gen_tps": _round(mean("idle_gen_tps")),
            "contention_gen_tps": _round(cont),
            "contention_retained_pct": _round(cont / base * 100, 1),
            "contention_ttft_ms": _round(mean("contention_ttft_ms"), 1),
            "gpu_busy_idle_pct": _round(mean("busy_idle_pct"), 1),
            "gpu_busy_contention_pct": _round(mean("busy_contention_pct"), 1),
            "xve_active_contention_pct": _round(mean("xve_active_contention_pct"), 1),
            "gpu_freq_contention_mhz": _round(mean("freq_contention_mhz"), 1),
            "gpu_throttle_reason_max": mean("igfx_throttle_max"),
            "mem_read_idle_gbps": _round(mean("mem_read_idle"), 1),
            "mem_read_contention_gbps": _round(mean("mem_read_contention"), 1),
            "igpu_rail_idle_w": _round(mean("vccgt_idle_w"), 2),
            "igpu_rail_contention_w": _round(mean("vccgt_contention_w"), 2),
            "npu_power_w": mean("npu_whole_w"),
            "soc_temp_peak_c": _round(mean("soc_temp_contention_peak_c"), 1),
            "baseline_gen_tps_std": _round(std("baseline_gen_tps"), 3),
            "contention_gen_tps_std": _round(std("contention_gen_tps"), 3),
        })
    return rows


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
    print(f"hardware: {HARDWARE}; driver {DRIVER}")
    sm = build_single_model()
    co = build_coresidency()
    write_table("single_model", sm)
    write_table("coresidency", co)
    # echo headline rows for a sanity eyeball
    print("\nsingle_model gen_median_tps:",
          {f'{r["model"].split()[0]}/{r["config"]}': r["gen_median_tps"] for r in sm})
    print("coresidency contention_retained_pct:",
          {r["partner"]: r["contention_retained_pct"] for r in co})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
