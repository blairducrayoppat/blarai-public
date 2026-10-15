"""Summarise the #1740 raw data: run-to-run variation, outcome stability, prediction vs run.

Reads a raw-data folder laid out as  arm-<X>/run-*.json  and  effective-access/*.json  and
prints Markdown tables. For each arm:
  * timing per probe (mean, standard deviation, coefficient of variation, min, max, n);
  * outcome stability: every categorical result (each fixture write, each secret read,
    each connect, each inheritance step) and whether it was identical in all n runs;
  * prediction vs run: each fixture write the payload attempted, against what
    effective_access.py predicted for that setup on that folder.
And for the permission instrument: whether repeated inventories returned identical masks.

Usage:  python -I analyse.py <raw-data dir> [--inventory <fixtures inventory file name>]
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

ARM_TO_SETUP = {"D": "D_real_limited", "A": "A_dedicated_account", "B1": "B1_safer_normaluser",
                "B2": "B2_write_restricted", "B3": "B3_fully_restricted",
                "C": "C_appcontainer_PREDICTION"}


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8-sig"))


def timings(run: dict) -> dict[str, float]:
    p = run.get("payload") or {}
    out: dict[str, float] = {}
    for k, v in (p.get("toolchain") or {}).items():
        if isinstance(v, dict) and "secs" in v:
            out[f"tool:{k}"] = v["secs"]
    if "total_secs" in p:
        out["payload_total"] = p["total_secs"]
    launch = run.get("launch") or {}
    if "wall_secs" in launch:
        out["launch_wall"] = launch["wall_secs"]
    elif "wall_secs" in run:
        out["launch_wall"] = run["wall_secs"]
    return out


def outcomes(run: dict) -> dict[str, str]:
    p = run.get("payload") or {}
    out: dict[str, str] = {}
    ident = p.get("identity") or {}
    out["identity:user"] = str(ident.get("user"))
    out["identity:integrity"] = str(ident.get("integrity"))
    out["identity:appcontainer"] = str(bool(ident.get("appcontainer_sid")))
    out["identity:restricting_sids"] = str(len(ident.get("restricting_sids") or []))
    for k, v in (p.get("toolchain") or {}).items():
        out[f"tool:{k}"] = str(v.get("ok") if k == "task" else v.get("rc"))
    for c in p.get("loopback") or []:
        tgt = c["target"].replace(str(c["target"]).split(":")[-1], "listener") \
            if not c["target"].endswith((":8099", ":8000")) else c["target"]
        out[f"loopback:{tgt}"] = f"{c['result']}/{c.get('winerror')}"
    for c in p.get("egress") or []:
        out[f"egress:{c['target']}"] = f"{c['result']}/{c.get('winerror')}"
    fr = p.get("file_reach") or {}
    for k, v in (fr.get("secret_reads") or {}).items():
        out[f"read:{k}"] = v
    for k, v in (fr.get("fixture_writes") or {}).items():
        out[f"write:{k}"] = v
    node, depth = p.get("inheritance"), 0
    while node:
        out[f"inherit:d{depth}:integrity"] = str((node.get("identity") or {}).get("integrity"))
        out[f"inherit:d{depth}:write_authusers"] = str(node.get("write_authusers"))
        out[f"inherit:d{depth}:egress"] = str((node.get("egress") or {}).get("result"))
        node, depth = node.get("child"), depth + 1
    return out


def prediction_file(ea_files: list[Path], chosen: str | None) -> Path | None:
    """The fixtures inventory predictions are read from: the one named, else the newest."""
    fixtures = [f for f in ea_files if "fixtures" in f.name]
    if chosen:
        named = [f for f in fixtures if f.name == chosen]
        if not named:
            raise SystemExit(f"--inventory {chosen} is not among {[f.name for f in fixtures]}")
        return named[0]
    return max(fixtures, key=lambda f: f.name) if fixtures else None


def prediction(inventory: Path | None, setup: str) -> dict[str, bool]:
    """Fixture folder -> predicted write (FILE_WRITE_DATA granted) for a setup."""
    if inventory is None:
        return {}
    data = _load(inventory)
    return {r["path"]: bool(r["access"][setup]["write"]) for r in data["rows"]
            if r.get("status") == "ok" and setup in r.get("access", {})}


def agrees(ran: set[str], predicted_write: bool) -> bool:
    """One clean outcome in every run that matches the prediction. An error, an absent
    folder or an undeletable probe file never counts as agreeing."""
    only = next(iter(ran)) if len(ran) == 1 else None
    return only in ("allowed", "denied") and (only == "allowed") == predicted_write


def summarise_arm(name: str, runs: list[dict], inventory: Path | None) -> list[str]:
    lines = [f"### Arm {name}: {len(runs)} runs", ""]
    t = defaultdict(list)
    for r in runs:
        for k, v in timings(r).items():
            t[k].append(v)
    lines += ["| timing (s) | mean | sd | CV % | min | max | n |", "|---|---|---|---|---|---|---|"]
    for k in sorted(t):
        v = t[k]
        mean = statistics.fmean(v)
        sd = statistics.stdev(v) if len(v) > 1 else 0.0
        cv = 100 * sd / mean if mean else 0.0
        lines.append(f"| {k} | {mean:.3f} | {sd:.3f} | {cv:.1f} | {min(v):.3f} | {max(v):.3f} | {len(v)} |")
    o = defaultdict(list)
    for r in runs:
        for k, v in outcomes(r).items():
            o[k].append(v)
    unstable = {k: v for k, v in o.items() if len(set(v)) > 1}
    lines += ["", (f"Categorical outcomes: {len(o)}; identical in every run: "
                   f"{len(o) - len(unstable)}; varying: {len(unstable)}."), ""]
    for k, v in sorted(unstable.items()):
        lines.append(f"- VARYING `{k}`: {v}")
    lines += ["", "| outcome | value (all runs) |", "|---|---|"]
    for k in sorted(o):
        vals = sorted(set(o[k]))
        lines.append(f"| `{k}` | {' / '.join(vals)} |")
    setup = ARM_TO_SETUP.get(name)
    pred = prediction(inventory, setup) if setup else {}
    if pred and inventory is not None:
        lines += ["", f"Predictions from `{inventory.name}`.", "",
                  "| fixture | predicted write | run result | agree |", "|---|---|---|---|"]
        agree_n = total = 0
        for k, vals in sorted(o.items()):
            if not k.startswith("write:"):
                continue
            path = k[len("write:"):]
            if path not in pred:
                continue
            ran = set(vals)
            ok = agrees(ran, pred[path])
            agree_n += ok
            total += 1
            lines.append(f"| `{path}` | {pred[path]} | {'/'.join(sorted(ran))} | {'yes' if ok else 'NO'} |")
        lines += ["", f"Prediction vs run: {agree_n} of {total} agree."]
    return lines + [""]


def summarise_instrument(ea_files: list[Path]) -> list[str]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for f in ea_files:
        groups["fixtures" if "fixtures" in f.name else "real"].append(_load(f))
    lines = ["### Permission instrument repeatability", ""]
    for g, datas in sorted(groups.items()):
        # Compare only the setups every inventory measured (a later inventory may add one).
        common = set.intersection(*[set(r.get("access", {})) for d in datas for r in d["rows"]
                                    if r.get("status") == "ok"])
        sig = [json.dumps([(r["path"], {k: v["mask"] for k, v in r.get("access", {}).items()
                                        if k in common}) for r in d["rows"]], sort_keys=True)
               for d in datas]
        disagree = sum(1 for d in datas for r in d["rows"]
                       if r.get("status") == "ok" and not all(r["instrument_agreement"].values()))
        lines.append(f"- {g}: {len(datas)} inventories; identical masks in all: "
                     f"{len(set(sig)) == 1}; rows where an instrument disagreed with the "
                     f"kernel reference: {disagree}")
    return lines + [""]


def main() -> int:
    ap = argparse.ArgumentParser(description="Summarise #1740 raw data.")
    ap.add_argument("root", type=Path)
    ap.add_argument("--inventory", help="fixtures inventory file name to predict from "
                    "(default: the newest)")
    args = ap.parse_args()
    root = args.root
    ea_files = sorted((root / "effective-access").glob("effective-access-*.json"))
    inventory = prediction_file(ea_files, args.inventory)
    out = ["# #1740 raw-data summary", "", *summarise_instrument(ea_files)]
    for arm_dir in sorted(root.glob("arm-*")):
        runs = [_load(p) for p in sorted(arm_dir.glob("run-*.json"))]
        if runs:
            out += summarise_arm(arm_dir.name[len("arm-"):], runs, inventory)
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
