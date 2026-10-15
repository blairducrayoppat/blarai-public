"""Summarise the #1740 phase-2 raw data into comparison tables.

Reads <root>/arm-<variant>/run-*.json (written by run_arm.py and run_arm_e.py) and prints Markdown:
  1. one row per variant: runs, did the payload start, identity, each tool's exit code, loopback, egress,
     secret reads, fixture writes allowed, inheritance, and whether every categorical outcome was identical
     across that variant's runs;
  2. timings of the payload-internal measurements against the control's run-to-run variation;
  3. variants that did not start or were refused, with the launcher's message.

Usage:  python -I summarise_phase2.py <phase2 raw dir> [--control D-fixture]
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path


def load(root: Path) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for d in sorted(root.glob("arm-*")):
        runs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("run-*.json"))]
        out[d.name[len("arm-"):]] = runs
    return out


def outcome_vector(rec: dict) -> dict[str, str]:
    p = rec.get("payload")
    if not p:
        return {"started": "no"}
    v: dict[str, str] = {"started": "yes"}
    ident = p.get("identity", {})
    v["container"] = "AppContainer" if ident.get("appcontainer_sid") else ("restricted" if ident.get("restricting_sids") else
                                                                          ("none" if ident.get("user") else "unknown"))
    v["integrity"] = {"S-1-16-4096": "low", "S-1-16-8192": "medium", "S-1-16-12288": "high"}.get(ident.get("integrity", ""), ident.get("integrity", "?") or "?")
    for k, t in p.get("toolchain", {}).items():
        v[f"tool:{k}"] = ("ok" if t.get("ok") else "FAIL") if k == "task" else ("ok" if t.get("rc") == 0 else f"rc={t.get('rc')}")
    for c in p.get("loopback", []):
        tgt = c["target"]
        key = "loopback:listener" if not tgt.endswith((":8099", ":8000")) else f"loopback:{tgt.split(':')[-1]}"
        v[key] = c["result"] if c["result"] == "connected" else f"{c['result']}({c.get('winerror')})"
    for c in p.get("egress", []):
        v[f"egress:{c['target'].split(':')[0]}"] = c["result"]
    fr = p.get("file_reach", {})
    v["secrets_denied"] = f"{sum(1 for x in fr.get('secret_reads', {}).values() if x == 'denied')}/{len(fr.get('secret_reads', {}))}"
    allowed = sorted(k.split("1740\\")[-1] for k, x in fr.get("fixture_writes", {}).items() if x == "allowed")
    v["writes_allowed"] = ",".join(allowed) or "none"
    n, depth, same = p.get("inheritance"), 0, True
    first = None
    while n:
        sig = (n.get("write_authusers"), (n.get("egress") or {}).get("result"), (n.get("identity") or {}).get("integrity"))
        first = first or sig
        same = same and sig == first
        n, depth = n.get("child"), depth + 1
    v["children_inherit"] = "yes" if same and depth >= 3 else "NO"
    return v


def timings(rec: dict) -> dict[str, float]:
    p = rec.get("payload") or {}
    out = {k: t["secs"] for k, t in (p.get("toolchain") or {}).items() if isinstance(t, dict) and "secs" in t}
    if "total_secs" in p:
        out["payload_total"] = p["total_secs"]
    return out


SETUP_OF_PREFIX = [("D-", "D_real_limited"), ("B1-", "B1_safer_normaluser"), ("B2-", "B2_write_restricted"),
                   ("B3-", "B3_fully_restricted"), ("C", "C_appcontainer_PREDICTION")]
_HOME = str(__import__("os").environ.get("USERPROFILE") or Path.home())  # never a literal account name
SECRET_PATHS = [_HOME + r"\.ssh", _HOME + r"\.git-credentials", _HOME + r"\AppData\Local\BlarAI",
                _HOME + r"\.config\opencode", _HOME + r"\.codex\.sandbox-secrets"]


def newest(root: Path, pattern: str) -> Path | None:
    files = sorted(root.glob(pattern))
    return files[-1] if files else None


def prediction_section(data: dict[str, list[dict]], fixtures_inv: Path, real_inv: Path) -> list[str]:
    fx = {r["path"]: r for r in json.loads(fixtures_inv.read_text(encoding="utf-8"))["rows"] if r.get("status") == "ok"}
    rl = {r["path"]: r for r in json.loads(real_inv.read_text(encoding="utf-8"))["rows"] if r.get("status") == "ok"}
    if not fx or not rl:
        raise SystemExit(f"refusing to compare: {fixtures_inv.name} or {real_inv.name} has no usable rows (an inventory taken after teardown?)")
    lines = ["", "### Prediction (Windows' access check, before launch) against what the payload did", "",
             (f"Predictions from `{fixtures_inv.name}` (fixtures) and `{real_inv.name}` (secret paths). A fixture write counts as "
              "allowed when the probe file was created (deleting it may still have been refused)."), "",
             "| variant | fixture writes agreeing | disagreements | secret reads agreeing | disagreements |", "|---|---|---|---|---|"]
    for name, runs in data.items():
        setup = next((s for pre, s in SETUP_OF_PREFIX if name.startswith(pre) and not name.startswith("E")), None)
        started = [r for r in runs if r.get("payload")]
        if not setup or not started:
            continue
        w_ok = w_total = r_ok = r_total = 0
        w_bad, r_bad = [], []
        for rec in started:
            fr = rec["payload"]["file_reach"]
            for path, res in fr["fixture_writes"].items():
                row = fx.get(path)
                if not row or setup not in row["access"]:
                    continue
                ran_write = res in ("allowed", "allowed-undeletable")
                w_total += 1
                if ran_write == row["access"][setup]["write"]:
                    w_ok += 1
                else:
                    w_bad.append(path.split("1740\\")[-1])
            for path, res in fr["secret_reads"].items():
                row = rl.get(path)
                if not row or setup not in row["access"]:
                    continue
                r_total += 1
                if (res == "allowed") == row["access"][setup]["read"]:
                    r_ok += 1
                else:
                    r_bad.append(path)
        lines.append(f"| {name} | {w_ok}/{w_total} | {', '.join(sorted(set(w_bad))) or 'none'} | {r_ok}/{r_total} | {', '.join(sorted(set(r_bad))) or 'none'} |")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", type=Path)
    ap.add_argument("--control", default="D-fixture")
    ap.add_argument("--inventories", type=Path, default=None,
                    help="directory holding effective-access-fixtures-*.json and effective-access-real-*.json "
                         "(default: ../effective-access next to the phase2 folder); the newest of each is used")
    args = ap.parse_args()
    data = load(args.root)
    lines = ["# #1740 phase-2 summary", "", "### Outcomes per variant (every run of a variant agreed unless marked)", ""]
    keys = ["started", "container", "integrity", "tool:node", "tool:git", "tool:bash", "tool:python", "tool:opencode", "tool:task",
            "loopback:listener", "loopback:8099", "egress:1.1.1.1", "egress:example.com", "secrets_denied", "writes_allowed",
            "children_inherit"]
    lines += ["| variant | runs | " + " | ".join(k.replace("tool:", "") for k in keys) + " | stable |", "|---|---|" + "---|" * (len(keys) + 1)]
    refused = []
    for name, runs in data.items():
        if not runs:
            continue
        vecs = [outcome_vector(r) for r in runs]
        started = [v for v in vecs if v["started"] == "yes"]
        if not started:
            refused.append((name, runs[0]))
            lines.append(f"| {name} | {len(runs)} | " + " | ".join(["NOT STARTED"] + [""] * (len(keys) - 1)) + " | |")
            continue
        merged = defaultdict(set)
        for v in started:
            for k in keys:
                merged[k].add(v.get(k, "-"))
        stable = all(len(merged[k]) == 1 for k in keys) and len(started) == len(vecs)
        cells = [" / ".join(sorted(merged[k])) for k in keys]
        lines.append(f"| {name} | {len(started)}/{len(runs)} | " + " | ".join(cells) + f" | {'yes' if stable else 'NO'} |")
    lines += ["", f"### Timings (seconds, payload-internal) against the control `{args.control}`", ""]
    series: dict[str, dict[str, list[float]]] = {}
    for name, runs in data.items():
        agg: dict[str, list[float]] = defaultdict(list)
        for r in runs:
            for k, x in timings(r).items():
                agg[k].append(x)
        series[name] = agg
    cv: dict[str, float] = {}
    for k, xs in series.get(args.control, {}).items():
        if len(xs) > 1 and statistics.fmean(xs):
            cv[k] = 100 * statistics.stdev(xs) / statistics.fmean(xs)
    lines += ["| variant | payload_total | node | git | python | task |", "|---|---|---|---|---|---|"]
    for name, agg in series.items():
        if not agg:
            continue
        lines.append(f"| {name} | " + " | ".join(f"{statistics.fmean(agg[k]):.3f} (n={len(agg[k])})" if agg.get(k) else "-" for k in
                                                   ["payload_total", "node", "git", "python", "task"]) + " |")
    if cv:
        lines += ["", "Control run-to-run variation (CV %): " + ", ".join(f"{k} {v:.1f}" for k, v in sorted(cv.items())) +
                  ". A difference smaller than the control's CV for that measurement is not a finding."]
    inv_dir = args.inventories or args.root.parent / "effective-access"
    fx_inv, real_inv = newest(inv_dir, "effective-access-fixtures-*.json"), newest(inv_dir, "effective-access-real-*.json")
    if fx_inv and real_inv:
        lines += prediction_section(data, fx_inv, real_inv)
    if refused:
        lines += ["", "### Variants that did not start", ""]
        for name, rec in refused:
            msg = (rec.get("dry_run", {}).get("stderr") or rec.get("launch", {}).get("stderr_tail") or "").strip().splitlines()
            lines.append(f"- `{name}`: {msg[0] if msg else 'no payload; see the record'}")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
