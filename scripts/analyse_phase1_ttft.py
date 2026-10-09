"""Summarise the live multi-turn TTFT runs (bench_multiturn_live_ttft.py) into one JSON.

Per arm and turn: input tokens, TTFT mean / sd / CV over visits, decode time per token.
Also whether every arm produced the same reply on every turn (the history each turn
carries is the model's own previous reply, so a differing reply would change later
prompts and make the turns incomparable).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase1_sizes as sizes  # noqa: E402


def ttft_pairs(present: list[str]) -> list[tuple[str, str]]:
    """(numerator, denominator) arms, per size present then larger-over-smaller across
    sizes; the 14B here is the bare ``14b-ship`` arm: its rows carry ``genai_version`` (kept per turn as
    ``genai``) but the arm name does not, so a ratio against it is read together with that field."""
    pairs: list[tuple[str, str]] = []
    for s in present:
        on, off, pc = (sizes.arm_name(s, v) for v in ("mtp-on", "mtp-off", "prefix-cache"))
        pairs += [(on, sizes.ARM_14B), (on, pc), (off, sizes.ARM_14B), (on, off)]
    order = list(sizes.SIZES)
    for i, small in enumerate(order):
        for big in order[i + 1:]:
            if small in present and big in present:
                pairs.append((sizes.arm_name(big, "mtp-on"), sizes.arm_name(small, "mtp-on")))
    return pairs


def main() -> int:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--in", dest="inputs", type=Path, nargs="+", required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    rows = []
    genai = {}
    for f in a.inputs:
        d = json.loads(f.read_text(encoding="utf-8"))
        rows += [{**r, "_genai": d["meta"]["genai"]} for r in d["rows"]]
    arms = sorted({r["arm"] for r in rows})
    per: dict = {}
    for arm in arms:
        per[arm] = {}
        for turn in range(1, 7):
            rs = [r for r in rows if r["arm"] == arm and r["turn"] == turn]
            ttft = [r["ttft_ms"] for r in rs if r.get("ttft_ms") is not None]
            tpot = [r["tpot_ms"] for r in rs if r.get("tpot_ms") is not None]
            mean = statistics.fmean(ttft)
            sd = statistics.stdev(ttft) if len(ttft) > 1 else None
            per[arm][f"t{turn}"] = {
                "input_tokens": sorted({r["input_tokens"] for r in rs}),
                "ttft_ms_mean": round(mean, 1), "ttft_ms_sd": None if sd is None else round(sd, 1),
                "ttft_ms_cv_pct": None if sd is None else round(sd / mean * 100, 1), "n_visits": len(ttft),
                "tpot_ms_mean": round(statistics.fmean(tpot), 1) if tpot else None,
                "genai": sorted({r["_genai"] for r in rs}),
                "temp_c_before": [(r.get("thermal_before") or {}).get("temp_c") for r in rs],
            }
    # Ratios of first-token delay between arms, with the speed analyser's refusal rule
    # (no ratio when either side's CV exceeds 15 percent or n < 2).
    ratios = {}
    not_formed: dict[str, list[str]] = {}
    present = sizes.sizes_in(arms)
    for turn in range(1, 7):
        for num, den in ttft_pairs(present):
            if num not in per or den not in per:
                # reported, never skipped: a silent skip hides a missing comparison
                not_formed.setdefault(f"{num}/{den}", []).append(f"t{turn}")
            if num in per and den in per:
                x, y = per[num][f"t{turn}"], per[den][f"t{turn}"]
                bad = any(v["n_visits"] < 2 or v["ttft_ms_cv_pct"] is None or v["ttft_ms_cv_pct"] > 15.0 for v in (x, y))
                ratios[f"t{turn}:{num}/{den}"] = (
                    {"ratio": None, "status": "refused: n<2 or CV>15% on a side"} if bad
                    else {"ratio": round(x["ttft_ms_mean"] / y["ttft_ms_mean"], 3), "status": "ok"})
    identity = {}
    for turn in range(1, 7):
        sets = {arm: {r["reply_sha256"] for r in rows if r["arm"] == arm and r["turn"] == turn} for arm in arms}
        def agree(size: str) -> bool:
            group = [v for k, v in sets.items() if sizes.size_of(k) == size]
            return bool(group) and len(set().union(*group)) == 1

        # one key per size PRESENT in the data: an absent size has no agreement to report
        identity[f"t{turn}"] = {"distinct_per_arm": {k: len(v) for k, v in sets.items()},
                                **{("four_b_arms_agree" if s == "4b" else f"{s}_arms_agree"): agree(s) for s in present},
                                "all_arms_agree_including_14b": len(set().union(*sets.values())) == 1}
    cache_on = " and ".join([sizes.arm_name(s, "prefix-cache") for s in (present or ["4b"])] + [sizes.ARM_14B])
    a.out.write_text(json.dumps({"per_arm_turn": per, "ttft_ratios": ratios, "reply_identity": identity,
                                 "note": f"history = the model's own greedy replies; prefix caching on only for {cache_on}",
                                 "ratio_pairs_not_formed": not_formed}, indent=1), encoding="utf-8")
    print(json.dumps(identity))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
