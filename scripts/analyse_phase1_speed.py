"""Pool the interleaved #1663 speed-campaign invocations into one summary.

Unit of analysis is the VISIT MEAN: one arm loaded once, its consecutive reps of
a cell averaged. Consecutive reps inside a visit share thermal state, weights and
cache, so they are not independent observations; visits (separate loads,
separated by cool-downs, interleaved with other arms) are the closest thing to
independent repeats this instrument has. The campaign's arm CV and the
ratio-refusal rule are therefore computed over visit means.

Prefix-cache arms (``<size>-prefix-cache`` and ``14b-ship``) hit their own cache on a
repeated identical prompt, so their TTFT is reported from the COLD protocol only
(rep 0, the first time that load sees the prompt); their plateau TTFT is not
reported. Decode rate is unaffected and uses every rep.

Plateau and cold protocols are never pooled with each other. The 14B is pooled
only within a runtime (``genai_version``): 2026.2.1 as it ships, 2026.4 as the
runtime-confound control.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase1_sizes as sizes  # noqa: E402

CACHE_ARMS = {sizes.arm_name(s, "prefix-cache") for s in sizes.SIZES} | {sizes.ARM_14B}
CV_LIMIT = 15.0
COLD_LIMIT_C = 72.0
HOT_C = 88.0
SLOW_OUTLIER_FRAC = 0.25
EXPLORATORY_STATUS = "exploratory, not pre-registered; the pre-registered rule refused the mean-based ratio"
EXPLORATORY_NOTES = [
    "POST-HOC AND EXPLORATORY: this block was added after the campaign was read, to show WHY the pre-registered "
    "CV rule refused some ratios. It is not a finding and must not be quoted as a finding; the pre-registered 'ratios' "
    "block is the only ratio result and its refusals stand.",
    f"A slow outlier visit is a visit mean more than {int(SLOW_OUTLIER_FRAC * 100)}% worse than the median of that "
    f"arm/cell: decode below {1 - SLOW_OUTLIER_FRAC:.2f} x median, TTFT above median / {1 - SLOW_OUTLIER_FRAC:.2f}.",
    "Medians over a handful of visits are exploratory summaries, not tests; no interval is claimed.",
]


def stat(vals: list[float]) -> dict[str, Any]:
    vals = [v for v in vals if v is not None]
    n = len(vals)
    if not n:
        return {"n": 0}
    mean = statistics.fmean(vals)
    sd = statistics.stdev(vals) if n > 1 else None
    return {"n": n, "mean": round(mean, 3), "sd": None if sd is None else round(sd, 3),
            "cv_pct": None if (sd is None or not mean) else round(sd / abs(mean) * 100, 2),
            "min": round(min(vals), 3), "max": round(max(vals), 3)}


def ratio(num: dict, den: dict) -> dict[str, Any]:
    for side in (num, den):
        if side.get("n", 0) < 2 or side.get("cv_pct") is None or side["cv_pct"] > CV_LIMIT or not side.get("mean"):
            return {"ratio": None, "status": "refused: n<2 or CV>15% on a side"}
    return {"ratio": round(num["mean"] / den["mean"], 3), "status": "ok"}


def explore_stat(points: list[dict[str, Any]], higher_is_better: bool) -> dict[str, Any]:
    """POST-HOC summary of one arm/cell/metric over its visit means (see EXPLORATORY_NOTES)."""
    vals = [p["value"] for p in points]
    if not vals:
        return {"n": 0, "median": None, "min": None, "max": None, "slow_outlier_visits": 0, "visit_means": []}
    med = statistics.median(vals)
    if higher_is_better:
        slow = [v < (1 - SLOW_OUTLIER_FRAC) * med for v in vals]
    else:
        slow = [v > med / (1 - SLOW_OUTLIER_FRAC) for v in vals]
    return {"n": len(vals), "median": round(med, 3), "min": round(min(vals), 3), "max": round(max(vals), 3),
            "slow_outlier_visits": sum(slow),
            "visit_means": [{**p, "value": round(p["value"], 3), "slow_outlier": sl} for p, sl in zip(points, slow)]}


def median_ratio(num: dict, den: dict) -> dict[str, Any]:
    ok = bool(num.get("n")) and bool(den.get("n")) and bool(den.get("median"))
    return {"ratio": round(num["median"] / den["median"], 3) if ok else None,
            "n_num": num.get("n", 0), "n_den": den.get("n", 0),
            "outliers_num": num.get("slow_outlier_visits", 0), "outliers_den": den.get("slow_outlier_visits", 0),
            "status": EXPLORATORY_STATUS}


def runtime_name(genai: str) -> str:
    """Runtime label for a GenAI build string: ``2026.4.0.0-3407-...`` -> ``2026.4``,
    ``2026.2.1.0-3123-...`` -> ``2026.2.1``. Anything else keeps its full string, so a
    new runtime can never be silently merged into an existing one."""
    for known in ("2026.4", "2026.2.1"):
        if genai.startswith(known):
            return known
    return genai


def label(arm: str, genai: str) -> str:
    return f"{sizes.ARM_14B}@{runtime_name(genai)}" if arm == sizes.ARM_14B else arm


def _size_label(size: str) -> str:
    return size.upper()


def _identical_phrase(stable_by_size: dict[str, list[str]]) -> str:
    """'the three 4B arms' / 'the one 4B arm that ran (4b-mtp-on)', joined across the sizes actually present."""
    parts = []
    for size, arms in stable_by_size.items():
        if len(arms) == len(sizes.cb_arms(size)):
            parts.append(f"the three {_size_label(size)} arms")
        else:
            count = {1: "one", 2: "two"}.get(len(arms), str(len(arms)))
            parts.append(f"the {count} {_size_label(size)} arm{'s' if len(arms) != 1 else ''} that ran ({', '.join(arms)})")
    return " and ".join(parts) if parts else "no CB arm"


def build_notes(table: dict[str, Any], present: list[str], tokens_14b: dict[str, set]) -> list[str]:
    """Notes computed from the arms and cells in THIS data; nothing here names an arm that did not run."""
    arms_here: dict[str, list[tuple[str, str, int]]] = defaultdict(list)  # base arm -> [(protocol, cell, n_distinct)]
    varying_labels: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))  # base arm -> {label: cells that vary}
    for prot, cells in table.items():
        for cell, labs in cells.items():
            for lab, v in labs.items():
                arms_here[lab.split("@")[0]].append((prot, cell, v["output_identity"]["n_distinct"]))
                if v["output_identity"]["n_distinct"] > 1:
                    varying_labels[lab.split("@")[0]][lab] += 1
    cache_present = [a for a in [sizes.arm_name(sz, "prefix-cache") for sz in sizes.SIZES] + [sizes.ARM_14B] if a in arms_here]

    varying: dict[str, set[tuple[str, str]]] = {}
    for arm, cells in arms_here.items():
        bad = {(prot, cell) for prot, cell, n in cells if n > 1}
        if bad:
            varying[arm] = bad
    order = list(sizes.SIZES)
    stable_by_size: dict[str, list[str]] = {}
    for arm in sorted(arms_here, key=lambda x: (order.index(sizes.parse_arm(x)[0]) if sizes.parse_arm(x) else 99, x)):
        parsed = sizes.parse_arm(arm)
        if parsed and arm not in varying:
            stable_by_size.setdefault(parsed[0], []).append(arm)
    prefix = ("output_identity.n_distinct > 1 for a cell means that arm produced different bytes across visits "
              "for the same prompt; ")
    if varying:
        clauses = []
        for arm in sorted(varying):
            who = "the shipped 14B" if arm == sizes.ARM_14B else arm
            prots = sorted({p for p, _ in varying[arm]})
            cells = {c for _, c in varying[arm]}
            kind = "multi-turn " if all(c.startswith("multiturn") for c in cells) else ""
            split = ""
            if len(varying_labels[arm]) > 1:  # two runtimes of one arm: say which cell belongs to which
                split = " [" + ", ".join(f"{lab} on {n}" for lab, n in sorted(varying_labels[arm].items())) + "]"
            clauses.append(f"{who} does so on {len(cells)} of its {'/'.join(prots)} {kind}cells (speed rows){split}")
        if set(varying) == {sizes.ARM_14B}:
            tail = ", not for the 14B on long multi-turn prompts"
        else:
            tail = ", not for " + ", ".join(sorted(varying))
        identity_note = prefix + "; ".join(clauses) + f", so 'identical outputs' holds for {_identical_phrase(stable_by_size)}" + tail + "."
    else:
        identity_note = (prefix + f"no arm did so in this data, so 'identical outputs' holds for {_identical_phrase(stable_by_size)} "
                         "(visit to visit, same prompt, the cells measured).")

    present_names = " and ".join(_size_label(sz) for sz in present)
    if len(present) == 1:
        tokenizer_phrase = f"the {present_names} tokenizer's"
    else:
        tokenizer_phrase = f"each arm's own tokenizer's (sizes in this data: {present_names or 'none'})"
    counts = []
    for c in ("pa", "ao-long"):
        if c in tokens_14b:
            counts.append(f"{'/'.join(str(x) for x in sorted(tokens_14b[c]))} ({c})")
    tokens_note = f"Input-token counts in the cell labels are {tokenizer_phrase}"
    tokens_note += f"; the 14B tokenizer counts {' and '.join(counts)}." if counts else "."
    return [
        f"Cache arms ({', '.join(cache_present)}) report TTFT from the COLD protocol only: the plateau protocol repeats prompts the cold one already cached, so their plateau ttft_ms_visit_means is {{n: 0}} by design.",
        identity_note,
        tokens_note,
        "Plateau-protocol ratios are recorded but not used for conclusions: a faster arm heats less (see PERFORMANCE_LOG 2026-10-04).",
    ]


def main() -> int:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--include-gate-failures", action="store_true",
                    help="keep cold rows whose cold_wait.reached is False in the cold statistics (pre-exclusion behaviour)")
    ap.add_argument("--strict-start-temp", type=float, default=None, metavar="C",
                    help="SENSITIVITY: additionally drop cold rows whose thermal_before temperature (read immediately before "
                         "generate) is above C, or unmeasured; adds new keys only")
    a = ap.parse_args()

    visits: dict[tuple, dict[str, list[float]]] = defaultdict(lambda: {"tps": [], "ttft": [], "ttft0": []})
    visit_t: dict[tuple, str] = {}
    hashes: dict[tuple, set[str]] = defaultdict(set)
    tokens_14b: dict[str, set] = defaultdict(set)
    hot = total = 0
    acceptance: list[dict[str, Any]] = []
    heat: list[dict[str, Any]] = []
    errors: list[str] = []
    gate_not_reached: list[dict[str, Any]] = []
    strict_dropped: list[dict[str, Any]] = []
    kept_cold = kept_cold_above = 0
    invalid = 0
    meta_files = []
    for f in sorted(a.dir.glob("[AB][0-9]*-*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        meta_files.append({"file": f.name, "uptime_h": d["meta"].get("uptime_h"),
                           "thermal_at_start": d["meta"].get("thermal_at_start"),
                           "driver": d["meta"].get("gpu_driver", {}).get("intel"),
                           "started": d["meta"].get("started"), "finished": d["meta"].get("finished")})
        for ar in d["arm_rounds"]:
            if ar.get("error"):
                errors.append(f"{f.name} {ar['arm']} visit {ar.get('visit')}: {ar['error']}")
            if ar.get("mtp_summary"):
                acceptance.append({"file": f.name, "arm": ar["arm"], "visit": ar.get("visit"), **{k: ar["mtp_summary"].get(k) for k in ("generations", "draft_tokens", "accepted_tokens", "acceptance_rate", "think_first_chunk_count")}})
            if ar.get("mtp_error"):
                errors.append(f"{f.name} {ar['arm']}: {ar['mtp_error']}")
            heat.append({"file": f.name, "arm": ar["arm"], "visit": ar.get("visit"), "plateau_reached": ar.get("plateau_reached"), "heat_generations": ar.get("heat_generations"), "peak_in_use_gb": ar.get("peak_in_use_gb")})
        for r in d["rows"]:
            if r.get("status") != "ok":
                invalid += r.get("status") not in (None, "heat")
                continue
            cw = r.get("cold_wait")
            if r["protocol"] == "cold" and isinstance(cw, dict) and cw.get("reached") is False:
                gate_not_reached.append({"file": f.name, "arm": r["arm"], "visit": r.get("visit"), "cell": r["cell"],
                                         "decode_tps": r.get("decode_tps"), "ttft_ms": r.get("ttft_ms"),
                                         "waited_s": cw.get("waited_s"), "temp_c_at_start": (r.get("thermal_before") or {}).get("temp_c"),
                                         "temp_c_after_wait": cw.get("temp_c")})
                if not a.include_gate_failures:
                    continue
            if r["protocol"] == "cold":
                kept_cold += 1
                tb0 = (r.get("thermal_before") or {}).get("temp_c")
                kept_cold_above += 1 if (tb0 is not None and tb0 > COLD_LIMIT_C) else 0
            if r["protocol"] == "cold" and a.strict_start_temp is not None:
                t0 = (r.get("thermal_before") or {}).get("temp_c")
                if t0 is None or t0 > a.strict_start_temp:
                    strict_dropped.append({"file": f.name, "arm": r["arm"], "visit": r.get("visit"), "cell": r["cell"],
                                           "rep": r.get("rep"), "decode_tps": r.get("decode_tps"),
                                           "temp_c_at_start": t0,
                                           "gate_reached": cw.get("reached") if isinstance(cw, dict) else None})
                    continue
            lab = label(r["arm"], r["genai_version"])
            key = (lab, r["protocol"], r["cell"], f.name, r.get("visit"))
            visit_t.setdefault(key, r.get("t"))
            if r.get("decode_tps") is not None:
                visits[key]["tps"].append(r["decode_tps"])
            if r.get("ttft_ms") is not None:
                visits[key]["ttft"].append(r["ttft_ms"])
                if r.get("rep", 0) == 0:
                    visits[key]["ttft0"].append(r["ttft_ms"])
            hashes[(lab, r["protocol"], r["cell"])].add(r.get("output_sha256"))
            if r["arm"] == sizes.ARM_14B and r.get("input_tokens") is not None:
                tokens_14b[r["cell"]].add(r["input_tokens"])
            tb = (r.get("thermal_before") or {}).get("temp_c")
            if tb is not None:
                total += 1
                hot += 1 if tb >= HOT_C else 0

    per: dict[tuple, dict[str, list[float]]] = defaultdict(lambda: {"tps": [], "ttft": []})
    detail: dict[tuple, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: {"tps": [], "ttft": []})
    for (lab, prot, cell, _f, _v), v in visits.items():
        tag = {"invocation": _f.removesuffix(".json"), "visit": _v, "t": visit_t.get((lab, prot, cell, _f, _v))}
        if v["tps"]:
            per[(lab, prot, cell)]["tps"].append(statistics.fmean(v["tps"]))
            detail[(lab, prot, cell)]["tps"].append({**tag, "value": statistics.fmean(v["tps"])})
        if lab.split("@")[0] in CACHE_ARMS:
            # The cold protocol runs first in every visit, so only there is a
            # prompt a cache arm has never seen; the plateau protocol repeats
            # prompts the cold one already cached.
            src = v["ttft0"] if prot == "cold" else []
        else:
            src = v["ttft"]
        if src:
            per[(lab, prot, cell)]["ttft"].append(statistics.fmean(src))
            detail[(lab, prot, cell)]["ttft"].append({**tag, "value": statistics.fmean(src)})

    table: dict[str, Any] = {}
    for (lab, prot, cell), v in sorted(per.items()):
        table.setdefault(prot, {}).setdefault(cell, {})[lab] = {
            "decode_tps_visit_means": stat(v["tps"]),
            "ttft_ms_visit_means": stat(v["ttft"]),
            "output_identity": {"n_distinct": len(hashes[(lab, prot, cell)])},
        }

    ratios: dict[str, Any] = {}
    missing_pairs: dict[str, list[str]] = {}
    pair_index: dict[str, tuple[str, str, str, str]] = {}
    present = sizes.sizes_in({lab for cells in table.values() for arms in cells.values() for lab in arms})
    for prot, cells in table.items():
        for cell, arms in cells.items():
            for num, den in sizes.ratio_pairs(present):
                if num not in arms or den not in arms:
                    # a pair that cannot be formed is REPORTED, never skipped: a silent
                    # skip here once hid every 4B-vs-14B comparison
                    missing_pairs.setdefault(f"{num}/{den}", []).append(f"{prot}:{cell}")
                if num in arms and den in arms:
                    pair_index[f"{prot}:{cell}:{num}/{den}"] = (prot, cell, num, den)
                    ratios[f"{prot}:{cell}:{num}/{den}"] = {
                        "decode_tps": ratio(arms[num]["decode_tps_visit_means"], arms[den]["decode_tps_visit_means"]),
                        "ttft_ms": ratio(arms[num]["ttft_ms_visit_means"], arms[den]["ttft_ms_visit_means"]),
                    }

    exp_cells: dict[str, Any] = {}
    for (lab, prot, cell), dv in sorted(detail.items()):
        exp_cells.setdefault(prot, {}).setdefault(cell, {})[lab] = {
            "decode_tps": explore_stat(dv["tps"], True), "ttft_ms": explore_stat(dv["ttft"], False)}
    exp_ratios: dict[str, Any] = {}
    for rkey, rv in ratios.items():
        prot, cell, num, den = pair_index[rkey]
        refused = {m: median_ratio(exp_cells[prot][cell][num][m], exp_cells[prot][cell][den][m])
                   for m in ("decode_tps", "ttft_ms") if rv[m]["ratio"] is None}
        if refused:
            exp_ratios[rkey] = refused
    exploratory = {"notes": EXPLORATORY_NOTES, "per_protocol_cell_arm": exp_cells,
                   "exploratory_median_ratios": exp_ratios}

    mem: dict[str, list[float]] = defaultdict(list)
    base: dict[str, list[float]] = defaultdict(list)
    for f in sorted(a.dir.glob("[AB][0-9]*-*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for ar in d["arm_rounds"]:
            if ar.get("error") or ar.get("peak_in_use_gb") is None:
                continue
            lab = label(ar["arm"], ar.get("genai_version", ""))
            mem[lab].append(ar["peak_in_use_gb"])
            base[lab].append(d["meta"].get("baseline_in_use_gb"))
    memory = {lab: {"peak_in_use_gb": stat(v), "baseline_in_use_gb": stat([b for b in base[lab] if b is not None]),
                    "delta_gb_mean": round(statistics.fmean(v) - statistics.fmean([b for b in base[lab] if b is not None]), 2)}
              for lab, v in mem.items()}

    notes = build_notes(table, present, tokens_14b)
    res = {
        "memory_in_use_total_minus_available": memory,
        "unit_of_analysis": "visit mean (one load of one arm, consecutive reps averaged)",
        "cv_limit_pct": CV_LIMIT,
        "per_protocol_cell_arm": table,
        "ratios": ratios,
        "ratio_pairs_not_formed": missing_pairs,
        "notes": notes,
        "mtp_witness": acceptance,
        "thermal": {"rows_with_temp": total, "rows_at_or_above_hot_c": hot, "hot_c": HOT_C},
        "plateau_and_memory": heat,
        "invocations": meta_files,
        "arm_errors": errors,
        "invalid_rows": invalid,
        "cold_gate_not_reached": gate_not_reached,
        "cold_gate_note": (
            "The COLD protocol is defined as thermal zone <= 72 C before every generation; a row whose cold_wait.reached "
            "is False did not meet it and is not a cold row. "
            + ("Those rows are EXCLUDED from every cold statistic, ratio and the exploratory block, applied to every arm "
               "uniformly and decided on the gate flag, never on the outcome; a visit left with no cold rep for a cell "
               "counts as one visit fewer. The numbers WITH them are in speed_summary_with_gate_failures.json "
               "(--include-gate-failures)."
               if not a.include_gate_failures else
               "This file was generated with --include-gate-failures: those rows are INCLUDED in the cold statistics "
               "(pre-exclusion behaviour); the default file excludes them.")),
        "exploratory": exploratory,
        "cold_gate_operationalisation_note": (
            "POST-HOC DISCLOSURE: 'reached' is the flag the wait loop recorded (one poll at or below the limit), not the "
            "temperature read immediately before generate, which can be higher. The exclusion rule was chosen after the data "
            "was read. Some rows kept as cold started above the limit (counted in cold_gate_kept_rows_started_above_limit); "
            "--strict-start-temp 72 reports the stricter reading (speed_summary_strict_gate.json lists the rows it drops)."),
        "cold_gate_kept_rows_started_above_limit": {
            "limit_c": COLD_LIMIT_C, "kept_cold_rows": kept_cold, "started_above_limit": kept_cold_above,
            "fraction": round(kept_cold_above / kept_cold, 3) if kept_cold else None},
    }
    if a.strict_start_temp is not None:
        res["cold_strict_start_temp_c"] = a.strict_start_temp
        res["cold_strict_start_dropped"] = strict_dropped
        res["cold_strict_start_note"] = (
            f"SENSITIVITY ANALYSIS, added after the data was read: cold rows whose thermal reading immediately before "
            f"generate was above {a.strict_start_temp:g} C (or missing) are dropped as well, in every cold statistic, ratio and "
            f"the exploratory block. {len(strict_dropped)} further rows were dropped. The default file keeps them."
        )
    a.out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("thermal", "arm_errors", "invalid_rows")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
