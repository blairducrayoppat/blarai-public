"""Assemble the #1663 Phase 1 research dataset (CSV + JSON) for banking and upload.

Reads the raw campaign output of one study (``--run-dir``, default ``docs/performance/_run/``) and writes
a self-contained directory to ``--out`` (required: a build never defaults into a committed dataset):

* ``speed_rows.csv``       every generation of the speed campaign, thermal-stamped
* ``speed_visits.csv``     visit means (the unit of analysis) per arm/protocol/cell
* ``quality_cases.csv``    every case verdict of every quality job
* ``quality_runs.csv``     one row per quality job and suite (pass/fail/skip counts)
* ``conditions_summary.json``  min/mean/max of the continuous system sampler
* ``raw/``                 the speed invocation JSONs, the quality reports and
                           engine witnesses, and the analysis summaries.

Model OUTPUT TEXT is deliberately not copied: io logs are reduced to hashes and
format flags, the copied case reports keep ``actual`` and ``expected`` only as short labels (a verdict such
as ALLOW/DENY, at most 24 characters per string, at any depth) and drop every ``detail``, and the Policy
Agent variant-probe rows lose their ``raw_text`` key (they keep the parsed label, confidence, prompt SHA and
variant ids). The output passes ``hf_publish.py preflight`` with no exemption. The dataset carries
measurements, not generations. Run-directory data files it does not copy are printed by name. When the run carries the legacy one-run `compare_on_vs_off.json` and the 4B
quality directories, `raw/compare_4b_on_vs_off_recomputed.json` is recomputed from them (not copied by hand).

``--out`` must be absent or empty: a build never writes into an existing dataset (a mixed directory once
carried two studies' summaries side by side).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import statistics
import sys
from pathlib import Path

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
import identity_lock as _il  # noqa: E402

RUN = Path(__file__).resolve().parents[1] / "docs/performance/_run"
sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase1_sizes as sizes  # noqa: E402


def label(arm: str, genai: str) -> str:
    from analyse_phase1_speed import label as _label

    return _label(arm, genai)


SHORT_LABEL_MAX = 24


OMITTED = "<omitted {n} chars>"


def _scrub_labels(node):
    """Keep structure, drop prose: every string longer than SHORT_LABEL_MAX becomes an '<omitted N chars>'
    marker and every 'detail' value is dropped, at any depth."""
    if isinstance(node, str):
        return OMITTED.format(n=len(node)) if len(node) > SHORT_LABEL_MAX else node
    if isinstance(node, dict):
        return {k: _scrub_labels(v) for k, v in node.items() if k != "detail"}
    if isinstance(node, list):
        return [_scrub_labels(v) for v in node]
    return node


def _scrub_messages(items):
    """Grader regression lines: the id and the verdict words stay, anything past SHORT_MESSAGE_MAX is cut."""
    return [m if not isinstance(m, str) or len(m) <= SHORT_MESSAGE_MAX else m[:SHORT_MESSAGE_MAX] + "..." for m in items]


SHORT_MESSAGE_MAX = 160
DESCRIPTION_MAX = 200


def sanitise_report(report: dict) -> dict:
    """Drop generated text from a suite report: keep ids, statuses and expected labels; ``actual`` keeps
    only short labels at any depth; ``detail`` is dropped wherever it occurs."""
    for block in report.get("suites", {}).values():
        for c in block.get("cases", []):
            if "expected" in c:
                c["expected"] = _scrub_labels(c["expected"])  # a fixture value, not a measurement
            if "actual" in c:
                actual = c["actual"]
                c["actual"] = None if isinstance(actual, str) and len(actual) > SHORT_LABEL_MAX else _scrub_labels(actual)
            c.pop("detail", None)
            desc = c.get("description")
            if isinstance(desc, str) and len(desc) > DESCRIPTION_MAX:
                c["description"] = desc[:DESCRIPTION_MAX] + "..."  # fixture prose with ticket history, not a measurement
        cmp_ = block.get("baseline_comparison")
        if isinstance(cmp_, dict):
            for key in ("regressions", "improvements", "known_failures", "known_tool_calls"):
                if isinstance(cmp_.get(key), list):
                    cmp_[key] = _scrub_messages(cmp_[key])
    if isinstance(report.get("regressions"), list):
        report["regressions"] = _scrub_messages(report["regressions"])
    return report


def sanitise_tree(root: Path) -> int:
    """Replace the local user name in paths and the host name in every text file under root."""
    import re

    import getpass
    import os
    import platform

    # The operator and host names are read from the machine, never held as literals (gate lock: tests/security/test_no_host_identity_in_tree.py).
    user = re.compile(r"(Users.{1,4})" + re.escape(os.environ.get("USERNAME") or getpass.getuser()), re.I)
    host = re.compile(re.escape(os.environ.get("COMPUTERNAME") or platform.node()), re.I)
    serials = _il.live_volume_serials()
    if not serials:
        raise SystemExit("sanitise_tree: no local fixed volume serial is readable; refusing (a live serial could not be cleared)")
    digests = _il.serial_digests(serials)
    changed = 0
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        try:
            t = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        t2 = host.sub("<host>", user.sub(lambda m: m.group(1) + "<user>", t))
        raw, _ = _il.rewrite_serials(t2.encode('utf-8', 'surrogatepass'), serials)  # volume serials (#1786): live ones and any header
        t2 = raw.decode('utf-8', 'surrogatepass')
        hosts, users = _il.find_hits(t2.encode('utf-8', 'surrogatepass'))  # digest recognition: holds under any account
        for tok in hosts:
            t2 = re.sub(re.escape(tok.decode()), '<host>', t2, flags=re.I)
        for tok in users:
            t2 = re.sub(r'(?<![A-Za-z])' + re.escape(tok.decode()) + r'(?![A-Za-z])', '<user>', t2, flags=re.I)
        if _il.find_serial_hits(t2.encode('utf-8', 'surrogatepass'), digests):
            raise SystemExit(f"sanitise_tree: {p.name} still carries a volume serial after the rewrite (an encoded form); hand edit")
        if t2 != t:
            p.write_text(t2, encoding="utf-8", newline="")
            changed += 1
    return changed


WRAP_AT = 100


def _wrap_markdown(text: str) -> str:
    """Soft-wrap over-long prose lines (tables and short lines untouched) so no .md line reaches the
    publisher's prose-line cap; the words are unchanged."""
    import textwrap

    out: list[str] = []
    for ln in text.splitlines():
        if len(ln) <= WRAP_AT + 20 or ln.lstrip().startswith("|"):
            out.append(ln)
            continue
        indent = " " * (len(ln) - len(ln.lstrip()))
        hang = indent + ("  " if ln.lstrip().startswith(("-", "*")) else "")
        out.extend(textwrap.wrap(ln, width=WRAP_AT, initial_indent="", subsequent_indent=hang, break_long_words=False))
    return chr(10).join(out) + chr(10)


def copy_variant_probe(src: Path, dst: Path, copied: set[Path]) -> None:
    """The Policy Agent prompt-variant probe (``pa_variants/``): tables, analysis (wrapped) and the
    per-cell rows. Absent directory: nothing to do."""
    if not src.is_dir():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for f in sorted(src.iterdir()):
        if not f.is_file():
            continue
        if f.suffix == ".md":
            (dst / f.name).write_text(_wrap_markdown(f.read_text(encoding="utf-8")), encoding="utf-8")
        elif f.suffix == ".jsonl":
            with open(dst / f.name, "w", encoding="utf-8", newline="") as fh:
                for ln in f.read_text(encoding="utf-8").splitlines():
                    if ln.strip():
                        r = json.loads(ln)
                        r.pop("raw_text", None)  # model output text: never published
                        fh.write(json.dumps(r) + chr(10))
        else:
            continue
        copied.add(f)


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--out", type=Path, required=True, help="output directory (required; never defaults into a committed dataset)")
    ap.add_argument("--run-dir", type=Path, default=RUN, help="raw campaign output (speed/, ttft/, q*/ and the summaries)")
    a = ap.parse_args()
    run = a.run_dir
    out = a.out
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        print(f"REFUSED: --out {out} exists and is not an empty directory; a build never writes into an existing dataset")
        return 2
    (out / "raw/speed").mkdir(parents=True, exist_ok=True)
    (out / "raw/quality").mkdir(parents=True, exist_ok=True)

    # ---- speed rows + visits -------------------------------------------------
    rows: list[dict] = []
    visits: dict[tuple, list[float]] = {}
    ttft_v: dict[tuple, list[float]] = {}
    copied: set[Path] = set()
    for f in sorted((run / "speed").glob("[AB][0-9]*-*.json")):
        shutil.copy(f, out / "raw/speed" / f.name)
        copied.add(f)
        d = json.loads(f.read_text(encoding="utf-8"))
        for r in d["rows"]:
            tb, ta = r.get("thermal_before") or {}, r.get("thermal_after") or {}
            lab = label(r["arm"], r["genai_version"])
            rows.append({
                "invocation": f.stem, "arm": lab, "visit": r.get("visit"), "protocol": r["protocol"], "cell": r["cell"],
                "rep": r.get("rep"), "status": r["status"], "t": r.get("t"),
                "ttft_ms": r.get("ttft_ms"), "tpot_ms": r.get("tpot_ms"), "decode_tps": r.get("decode_tps"),
                "decode_tps_wall": r.get("decode_tps_wall"), "input_tokens": r.get("input_tokens"),
                "generated_tokens": r.get("generated_tokens"), "wall_ms": r.get("wall_ms"),
                "output_sha256": r.get("output_sha256"),
                "draft_tokens": r.get("draft_tokens"), "accepted_tokens": r.get("accepted_tokens"),
                "temp_c_before": tb.get("temp_c"), "temp_c_after": ta.get("temp_c"),
                "passive_limit_pct_before": tb.get("passive_limit_pct"), "throttle_reasons_before": tb.get("throttle_reasons"),
                "genai_version": r["genai_version"], "openvino_version": r["openvino_version"],
                "gpu_driver": (d["meta"].get("gpu_driver", {}).get("intel") or [{}])[0].get("DriverVersion"),
                "uptime_h": d["meta"].get("uptime_h"),
            })
            if r["status"] == "ok" and r.get("decode_tps") is not None:
                visits.setdefault((f.stem, lab, r.get("visit"), r["protocol"], r["cell"]), []).append(r["decode_tps"])
                if r.get("ttft_ms") is not None:
                    ttft_v.setdefault((f.stem, lab, r.get("visit"), r["protocol"], r["cell"]), []).append(r["ttft_ms"])
    write_csv(out / "speed_rows.csv", rows, list(rows[0].keys()))
    vrows = []
    for (inv, lab, vis, prot, cell), v in sorted(visits.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        t = ttft_v.get((inv, lab, vis, prot, cell), [])
        vrows.append({"invocation": inv, "arm": lab, "visit": vis, "protocol": prot, "cell": cell, "n_reps": len(v),
                      "decode_tps_mean": round(statistics.fmean(v), 3), "ttft_ms_rep0": ttft_v[(inv, lab, vis, prot, cell)][0] if t else None,
                      "ttft_ms_mean": round(statistics.fmean(t), 2) if t else None})
    write_csv(out / "speed_visits.csv", vrows, list(vrows[0].keys()))

    # ---- quality -----------------------------------------------------------
    qcases: list[dict] = []
    qruns: list[dict] = []
    for qdir in sorted(run.glob("q*")):
        if not qdir.is_dir():
            continue
        model = sizes.dataset_quality_dirs().get(qdir.name, qdir.name)
        for rep in sorted(qdir.glob("*_report.json")):
            tag = rep.name[: -len("_report.json")]
            (out / "raw/quality" / rep.name).write_text(
                json.dumps(sanitise_report(json.loads(rep.read_text(encoding="utf-8"))), indent=1), encoding="utf-8")
            for extra in (f"{tag}_engine.json",):
                if (qdir / extra).exists():
                    shutil.copy(qdir / extra, out / "raw/quality" / extra)
            io = qdir / f"{tag}_io.jsonl"
            if io.exists():  # hashes and format flags only - never the generated text
                with open(out / "raw/quality" / f"{tag}_io.jsonl", "w", encoding="utf-8") as fh:
                    for ln in io.read_text(encoding="utf-8").splitlines():
                        if ln.strip():
                            r = json.loads(ln)
                            r.pop("out_text", None)
                            fh.write(json.dumps(r, sort_keys=True) + chr(10))
            d = json.loads(rep.read_text(encoding="utf-8"))
            for suite, block in d["suites"].items():
                ag = block["aggregates"]
                qruns.append({"model": model, "job": tag, "suite": suite, "passed": ag["passed"], "failed": ag["failed"],
                              "errors": ag["errors"], "skipped_hardware": ag["skipped_hardware"], "tool_calls": ag.get("tool_calls"),
                              "evaluated": ag["evaluated"], "total": ag["total"]})
                for c in block["cases"]:
                    qcases.append({"model": model, "job": tag, "suite": suite, "case_id": c["id"], "status": c["status"]})
    if qcases:
        write_csv(out / "quality_cases.csv", qcases, ["model", "job", "suite", "case_id", "status"])
        write_csv(out / "quality_runs.csv", qruns, list(qruns[0].keys()))

    ttft_rows: list[dict] = []
    for f in sorted((run / "ttft").glob("*_*.json")):
        shutil.copy(f, out / "raw" / f.name)
        copied.add(f)
        d = json.loads(f.read_text(encoding="utf-8"))
        for r in d["rows"]:
            ttft_rows.append({"arm": label(r["arm"], r["genai_version"]), "visit": r["visit"], "turn": r["turn"],
                              "input_tokens": r["input_tokens"], "ttft_ms": r["ttft_ms"], "tpot_ms": r["tpot_ms"],
                              "generated_tokens": r["generated_tokens"], "reply_sha256": r["reply_sha256"],
                              "temp_c_before": (r.get("thermal_before") or {}).get("temp_c"),
                              "genai_version": r["genai_version"]})
    if ttft_rows:
        write_csv(out / "multiturn_ttft_turns.csv", ttft_rows, list(ttft_rows[0].keys()))

    # Every analysis file of the study, per size: summaries, comparisons, variance runs, thermal recovery.
    summary_names = {"speed_summary.json", "speed_summary_pre_topup.json",
                     "speed_summary_with_gate_failures.json", "speed_summary_strict_gate.json", "ttft_summary.json", "thermal_recovery.json",
                     *sizes.dataset_summary_files(),
                     *sizes.dataset_compare_files()}
    for f in sorted(run.glob("*.json")):
        if f.name in summary_names or f.name.startswith(("compare_", "variance_")) or re.fullmatch(r"q[0-9a-z]+_(?:on_|off_)?summary\.json", f.name):
            shutil.copy(f, out / "raw" / f.name)
            copied.add(f)

    # The legacy ``compare_on_vs_off.json`` checked one run only (superseded); its replacement is recomputed here from
    # the quality directories, never hand-copied, so a rebuilt dataset carries the file its README cites.
    if (run / "compare_on_vs_off.json").exists() and (run / "q4b_on").is_dir() and (run / "q4b_off").is_dir():
        from analyse_phase1_quality import compare as _compare

        res = _compare(run / "q4b_on", "4b-on", run / "q4b_off", "4b-off")
        (out / "raw" / "compare_4b_on_vs_off_recomputed.json").write_text(json.dumps(res, indent=1), encoding="utf-8")

    copy_variant_probe(run / "pa_variants", out / "raw/pa_variants", copied)

    cond = run / "conditions.jsonl"
    if cond.exists():
        import subprocess
        import sys

        res = subprocess.run([sys.executable, str(Path(__file__).parent / "sample_system.py"), "--summarise", str(cond)],
                             capture_output=True, text=True)
        (out / "conditions_summary.json").write_text(res.stdout, encoding="utf-8")
    sanitise_tree(out)
    dropped = sorted(p.name for p in run.iterdir()
                     if p.is_file() and p.suffix in (".json", ".jsonl", ".csv") and p not in copied and p.name != "conditions.jsonl")
    dropped += sorted(f"speed/{p.name}" for p in (run / "speed").glob("*.json") if p not in copied)
    if dropped:
        print(f"NOT copied from {run} ({len(dropped)}): " + ", ".join(dropped))
    print(f"wrote {out}: {len(rows)} speed rows, {len(vrows)} visit rows, {len(qcases)} quality cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
