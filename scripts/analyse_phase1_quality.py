"""Summarise a #1663 quality campaign directory (one model) into one JSON.

Reads the per-job ``<tag>_report.json`` and ``<tag>_io.jsonl`` files that
``run_phase1_campaign.py`` writes and computes, per model-driven suite:

* the pass count of every run, and the spread across the random-marker repeats
* per-case verdict vectors across the pinned-marker repeats (V0 x3)
* INPUT IDENTITY of the pinned repeats, measured from the logged prompt hashes:
  a repeat is only evidence of the model's determinism if the prompts it was
  sent were byte-identical, so verdict agreement is reported only alongside it
* OUTPUT identity of the pinned repeats (hash of the returned text)
* the verdict flips caused by the V1 / V2 meaning-preserving perturbations
* tool-call format counts (XML ``<function=`` vs JSON ``<tool_call>``)

Cross-model comparison (MTP on vs off identity, a Qwen3.5 size vs the 14B verdicts) is done by
``--compare DIR_A MODEL_A DIR_B MODEL_B``: every pinned run both sides have (V0 repeats and the
V1/V2/V3 perturbations), call by call, plus every suite the two ``all-random-r1`` reports share.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def load_report(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def case_status(report: dict[str, Any], suite: str) -> dict[str, str]:
    block = report["suites"][suite]
    return {c["id"]: c["status"] for c in block["cases"]}


def aggregates(report: dict[str, Any], suite: str) -> dict[str, Any]:
    return report["suites"][suite]["aggregates"]


def io_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def identity(rows_by_repeat: list[list[dict[str, Any]]], key: str) -> dict[str, Any]:
    """Compare the ordered ``key`` hash sequence across repeats."""
    seqs = [[r.get(key) for r in rows] for rows in rows_by_repeat]
    if len(seqs) < 2:
        # one observation proves nothing: identity needs at least two repeats
        return {"repeats": len(seqs), "identical": None, "note": "fewer than 2 repeats: identity not assessable"}
    lengths = {len(s) for s in seqs}
    same_len = len(lengths) == 1
    first = seqs[0]
    mismatches = 0
    if same_len:
        for s in seqs[1:]:
            mismatches += sum(1 for a, b in zip(first, s) if a != b)
    return {
        "repeats": len(seqs),
        "calls_per_repeat": sorted(lengths),
        "same_call_count": same_len,
        "identical": same_len and mismatches == 0,
        "mismatched_calls": mismatches if same_len else None,
    }


def verdict_vectors(statuses: list[dict[str, str]]) -> dict[str, list[str]]:
    ids = sorted({i for s in statuses for i in s})
    return {i: [s.get(i, "absent") for s in statuses] for i in ids}


def unstable(vectors: dict[str, list[str]]) -> dict[str, list[str]]:
    return {i: v for i, v in vectors.items() if len(set(v)) > 1}


SCRIPTED_PREFIX = "ag-det-"  # offline, scripted cases: the model never runs for them


def is_scripted(case_id: str) -> bool:
    return case_id.startswith(SCRIPTED_PREFIX)


def model_driven(status: dict[str, str]) -> dict[str, str]:
    return {i: v for i, v in status.items() if not is_scripted(i)}


def passes(status: dict[str, str]) -> int:
    return sum(1 for v in status.values() if v == "pass")


def prompts_changed(base_rows: list[dict[str, Any]], var_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """How many model calls actually received a different prompt under a perturbation.

    A perturbation that changes no prompt measured nothing: a chat template that
    trims whitespace erases a trailing space before the model sees it, and a
    'no verdict flipped' line over zero changed prompts is vacuous.
    """
    n = min(len(base_rows), len(var_rows))
    changed = sum(1 for a, b in zip(base_rows[:n], var_rows[:n]) if a.get("prompt_sha") != b.get("prompt_sha"))
    return {"calls": n, "calls_with_changed_prompt": changed, "same_call_count": len(base_rows) == len(var_rows)}


def summarise_model(directory: Path, model: str) -> dict[str, Any]:
    out: dict[str, Any] = {"model": model, "dir": str(directory)}
    for suite in ("agentic", "conversation"):
        block: dict[str, Any] = {}
        random_reports: list[Path] = []
        first = directory / f"{model}-all-random-r1_report.json"
        if first.exists():
            random_reports.append(first)
        for r in (2, 3):
            p = directory / f"{model}-{suite}-random-r{r}_report.json"
            if p.exists():
                random_reports.append(p)
        rand_status = [case_status(load_report(p), suite) for p in random_reports]
        block["random_marker"] = {
            "runs": len(rand_status),
            "pass_counts_all_cases": [passes(s) for s in rand_status],
            "pass_counts_model_driven": [passes(model_driven(s)) for s in rand_status],
            "model_driven_cases": [len(model_driven(s)) for s in rand_status],
            "scripted_cases": [len(s) - len(model_driven(s)) for s in rand_status],
            "unstable_cases": unstable(verdict_vectors(rand_status)),
        }
        pinned_status, pinned_io = [], []
        for r in (1, 2, 3):
            tag = f"{model}-{suite}-pinned-V0-r{r}"
            p = directory / f"{tag}_report.json"
            if p.exists():
                pinned_status.append(case_status(load_report(p), suite))
                pinned_io.append(io_rows(directory / f"{tag}_io.jsonl"))
        block["pinned_marker_V0"] = {
            "runs": len(pinned_status),
            "pass_counts_all_cases": [passes(s) for s in pinned_status],
            "pass_counts_model_driven": [passes(model_driven(s)) for s in pinned_status],
            "unstable_cases": unstable(verdict_vectors(pinned_status)),
            "input_identity": identity(pinned_io, "prompt_sha"),
            "output_identity": identity(pinned_io, "out_sha"),
        }
        flips: dict[str, Any] = {}
        base = pinned_status[0] if pinned_status else {}
        base_io = pinned_io[0] if pinned_io else []
        for variant in ("V1", "V2", "V3"):
            tag = f"{model}-{suite}-pinned-{variant}-r1"
            p = directory / f"{tag}_report.json"
            if p.exists() and base:
                st = case_status(load_report(p), suite)
                pc = prompts_changed(base_io, io_rows(directory / f"{tag}_io.jsonl"))
                entry = {
                    "pass_count_all_cases": passes(st),
                    "pass_count_model_driven": passes(model_driven(st)),
                    "prompts": pc,
                    "flipped_vs_V0": {i: [base.get(i), st.get(i)] for i in sorted(set(base) | set(st)) if base.get(i) != st.get(i)},
                }
                if pc["calls_with_changed_prompt"] == 0:
                    entry["interpretation"] = "NOT MEASURED: no model call received a different prompt, so zero flips says nothing"
                flips[variant] = entry
        block["perturbation"] = flips
        xml = json_calls = ao_calls = 0
        for path in directory.glob(f"{model}-{suite}-*_io.jsonl"):
            for r in io_rows(path):
                if r.get("kind") == "ao":
                    ao_calls += 1
                    xml += 1 if r.get("xml_tool_call") else 0
                    json_calls += 1 if r.get("json_tool_call") else 0
        block["tool_call_format"] = {"ao_calls": ao_calls, "xml_function_calls": xml, "json_tool_calls": json_calls}
        out[suite] = block

    # Policy Agent + answer quality + preference memory: every repeat that exists
    for suite in ("pa_classification", "answer_quality", "preference_memory"):
        statuses, ios = [], []
        first = directory / f"{model}-all-random-r1_report.json"
        if first.exists():
            statuses.append(case_status(load_report(first), suite))
            ios.append([r for r in io_rows(directory / f"{model}-all-random-r1_io.jsonl") if r.get("kind") == ("pa" if suite == "pa_classification" else "ao")]
                       if suite == "pa_classification" else [])
        for r in (2, 3):
            tag = f"{model}-{suite}-random-r{r}"
            p = directory / f"{tag}_report.json"
            if p.exists():
                statuses.append(case_status(load_report(p), suite))
                ios.append([x for x in io_rows(directory / f"{tag}_io.jsonl") if x.get("kind") == "pa"] if suite == "pa_classification" else [])
        if statuses:
            vec = verdict_vectors(statuses)
            blk = {
                "runs": len(statuses),
                "pass_counts": [passes(s) for s in statuses],
                "unstable_cases": unstable(vec),
                "failing_in_every_run": sorted(i for i, v in vec.items() if all(x != "pass" for x in v)),
                "single_run": len(statuses) == 1,
            }
            if len(statuses) == 1:
                blk["single_run_note"] = ("one run only: failing_in_every_run lists the cases that failed in that one run; "
                                          "it is not a repeated finding and no conclusion is drawn from it")
            if suite == "pa_classification":
                blk["output_identity"] = identity(ios, "out_sha")
            out[f"{suite}_repeats"] = blk

    allp = directory / f"{model}-all-random-r1_report.json"
    if allp.exists():
        rep = load_report(allp)
        out["all_suites_random_r1"] = {
            s: {k: v for k, v in b["aggregates"].items() if k in ("passed", "failed", "errors", "skipped_hardware", "tool_calls", "evaluated", "total")}
            for s, b in rep["suites"].items()
        }
    engines = {}
    for p in directory.glob("*_engine.json"):
        engines[p.name] = json.loads(p.read_text(encoding="utf-8"))
    if engines:
        out["engine_witness"] = engines
        out["engine_witness_failures"] = sorted(
            f"{name}: {w.get('witness_error')}" for name, ws in engines.items() for w in ws if w.get("witness_error")
        )
    return out


NO_RUNTIME = "runtime not recorded in these reports"


def side_runtime(directory: Path, model: str) -> dict[str, Any]:
    """The OpenVINO GenAI version(s) the side ran on, from its engine witnesses (14B jobs write none)."""
    versions: set[str] = set()
    for p in directory.glob(f"{model}-*_engine.json"):
        try:
            for w in json.loads(p.read_text(encoding="utf-8")):
                if w.get("genai_version"):
                    versions.add(str(w["genai_version"]))
        except (ValueError, TypeError, AttributeError):
            continue
    return {"genai_versions": sorted(versions)} if versions else {"genai_versions": [], "note": NO_RUNTIME}


def pinned_runs(directory: Path, model: str) -> dict[tuple[str, str, int], str]:
    """{(suite, variant, repeat): tag} for every pinned-marker job report of ``model`` in ``directory``."""
    pat = re.compile(rf"^{re.escape(model)}-(?P<suite>[a-z_]+)-pinned-(?P<variant>V\d+)-r(?P<rep>\d+)_report\.json$")
    out: dict[tuple[str, str, int], str] = {}
    for p in sorted(directory.glob(f"{model}-*-pinned-*_report.json")):
        m = pat.match(p.name)
        if m:
            out[(m["suite"], m["variant"], int(m["rep"]))] = p.name[: -len("_report.json")]
    return out


def common_prefix_len(a: Any, b: Any) -> int | None:
    """Length of the shared leading text of two outputs, a count only. None when either text is absent."""
    if not isinstance(a, str) or not isinstance(b, str):
        return None
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def compare_run(ia: list[dict[str, Any]], ib: list[dict[str, Any]]) -> dict[str, Any]:
    """One pinned run, call by call (matched on position): prompts, then outputs. Never carries text."""
    n = min(len(ia), len(ib))
    prompts_differing = outputs_differing = outputs_differing_same_prompt = 0
    differing: list[dict[str, Any]] = []
    for k in range(n):
        a, b = ia[k], ib[k]
        same_prompt = a.get("prompt_sha") == b.get("prompt_sha")
        same_out = a.get("out_sha") == b.get("out_sha")
        prompts_differing += 0 if same_prompt else 1
        if not same_out:
            outputs_differing += 1
            outputs_differing_same_prompt += 1 if same_prompt else 0
            differing.append({
                "call_index": k, "kind": a.get("kind"), "prompt_sha": a.get("prompt_sha"), "same_prompt": same_prompt,
                "a_out_len": a.get("out_len"), "b_out_len": b.get("out_len"),
                "common_prefix_chars": common_prefix_len(a.get("out_text"), b.get("out_text")),
            })
    return {
        "calls_a": len(ia), "calls_b": len(ib), "calls_compared": n, "same_call_count": len(ia) == len(ib),
        "prompts_identical": prompts_differing == 0 and len(ia) == len(ib),
        "prompts_differing": prompts_differing,
        "outputs_differing": outputs_differing,
        "outputs_differing_with_identical_prompt": outputs_differing_same_prompt,
        "differing_calls": differing,
    }


OVERALL_RUNS_LISTED = 6
OVERALL_CALLS_LISTED = 6


def overall_statement(runs: list[dict[str, Any]]) -> str:
    """A sentence that is true of ``runs``: 'identical' only when every compared call is."""
    if not runs:
        return "NOT ASSESSABLE: the two sides share no pinned run"
    calls = sum(r["calls_compared"] for r in runs)
    out_diff = sum(r["outputs_differing"] for r in runs)
    prompt_diff = sum(r["prompts_differing"] for r in runs)
    count_mismatch = [f"{r['suite']}-{r['variant']}-r{r['repeat']}" for r in runs if not r["same_call_count"]]
    if not out_diff and not prompt_diff and not count_mismatch:
        return f"identical: all {calls} calls in all {len(runs)} compared pinned runs have identical prompts and identical outputs"
    bad_runs = [r for r in runs if r["outputs_differing"]]
    parts = [f"NOT identical: {out_diff} of {calls} compared calls differ in output across {len(bad_runs)} of {len(runs)} pinned runs"]
    if prompt_diff:
        parts.append(f"prompts differ in {prompt_diff} of {calls} calls (output identity is not meaningful for those)")
    if count_mismatch:
        parts.append("call counts differ in " + ", ".join(count_mismatch))
    shown = bad_runs[:OVERALL_RUNS_LISTED]
    where = [f"{r['suite']}-{r['variant']}-r{r['repeat']}: " +
             (f"calls {[d['call_index'] for d in r['differing_calls']]}" if r["outputs_differing"] <= OVERALL_CALLS_LISTED
              else f"{r['outputs_differing']} calls") for r in shown]
    if len(bad_runs) > len(shown):
        where.append(f"and {len(bad_runs) - len(shown)} more runs")
    if where:
        parts.append("differing calls: " + "; ".join(where))
    return "; ".join(parts)


def compare(dir_a: Path, model_a: str, dir_b: Path, model_b: str) -> dict[str, Any]:
    """Compare two sides over everything they share.

    * ``pinned_runs``: EVERY pinned-marker job (V0 repeats and the V1/V2/V3 perturbations) both sides have,
      matched on (suite, variant, repeat); per run the prompt and output identity, call by call.
    * ``suites_all_random_r1``: per-case verdict differences for EVERY suite both ``all-random-r1`` reports carry.
    * ``runtime``: each side's GenAI version when the data records one."""
    out: dict[str, Any] = {
        "a": model_a, "b": model_b,
        "runtime": {"a": side_runtime(dir_a, model_a), "b": side_runtime(dir_b, model_b)},
    }
    ra, rb = pinned_runs(dir_a, model_a), pinned_runs(dir_b, model_b)
    runs: list[dict[str, Any]] = []
    for key in sorted(set(ra) & set(rb)):
        suite, variant, rep = key
        sa = case_status(load_report(dir_a / f"{ra[key]}_report.json"), suite)
        sb = case_status(load_report(dir_b / f"{rb[key]}_report.json"), suite)
        run: dict[str, Any] = {"suite": suite, "variant": variant, "repeat": rep, "tag_a": ra[key], "tag_b": rb[key]}
        run.update(compare_run(io_rows(dir_a / f"{ra[key]}_io.jsonl"), io_rows(dir_b / f"{rb[key]}_io.jsonl")))
        run["verdict_differences"] = {i: [sa.get(i), sb.get(i)] for i in sorted(set(sa) | set(sb)) if sa.get(i) != sb.get(i)}
        runs.append(run)
    out["pinned_runs"] = runs
    out["pinned_runs_only_one_side"] = {
        "only_a": sorted("-".join(map(str, k)) for k in set(ra) - set(rb)),
        "only_b": sorted("-".join(map(str, k)) for k in set(rb) - set(ra)),
    }
    out["pinned_totals"] = {
        "runs_compared": len(runs),
        "calls_compared": sum(r["calls_compared"] for r in runs),
        "prompts_differing": sum(r["prompts_differing"] for r in runs),
        "outputs_differing": sum(r["outputs_differing"] for r in runs),
        "outputs_differing_with_identical_prompt": sum(r["outputs_differing_with_identical_prompt"] for r in runs),
        "runs_with_differing_outputs": [f"{r['suite']}-{r['variant']}-r{r['repeat']}" for r in runs if r["outputs_differing"]],
    }
    out["overall"] = overall_statement(runs)

    pa_, pb_ = dir_a / f"{model_a}-all-random-r1_report.json", dir_b / f"{model_b}-all-random-r1_report.json"
    if pa_.exists() and pb_.exists():
        rep_a, rep_b = load_report(pa_), load_report(pb_)
        suites: dict[str, Any] = {}
        for suite in sorted(set(rep_a["suites"]) & set(rep_b["suites"])):
            sa, sb = case_status(rep_a, suite), case_status(rep_b, suite)
            suites[suite] = {
                "cases_a": len(sa), "cases_b": len(sb),
                "verdict_differences": {i: [sa.get(i), sb.get(i)] for i in sorted(set(sa) | set(sb)) if sa.get(i) != sb.get(i)},
            }
        out["suites_all_random_r1"] = suites
        out["suites_only_one_side"] = {"only_a": sorted(set(rep_a["suites"]) - set(rep_b["suites"])),
                                       "only_b": sorted(set(rep_b["suites"]) - set(rep_a["suites"]))}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--dir", type=Path)
    ap.add_argument("--model")
    ap.add_argument("--compare", nargs=4, metavar=("DIR_A", "MODEL_A", "DIR_B", "MODEL_B"))
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    if a.compare:
        res = compare(Path(a.compare[0]), a.compare[1], Path(a.compare[2]), a.compare[3])
    else:
        if not (a.dir and a.model):
            ap.error("--dir and --model are required without --compare")
        res = summarise_model(a.dir, a.model)
    a.out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1)[:3000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
