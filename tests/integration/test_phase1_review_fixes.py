"""Locks for the independent review of the #1665 harness (F2, F5, F10 here; the builder and the
speed/TTFT analysers are covered below). CPU-only: synthetic run directories through the real scripts."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# synthetic quality directories
# ---------------------------------------------------------------------------

def _write_run(d: Path, tag: str, suite: str, outs: list[str], prompts: list[str] | None = None,
               statuses: dict[str, str] | None = None) -> None:
    d.mkdir(parents=True, exist_ok=True)
    cases = [{"id": f"c{i}", "status": (statuses or {}).get(f"c{i}", "pass")} for i in range(2)]
    report = {"suites": {suite: {"cases": cases, "aggregates": {"passed": 2, "failed": 0, "errors": 0,
                                                                "skipped_hardware": 0, "evaluated": 2, "total": 2}}}}
    (d / f"{tag}_report.json").write_text(json.dumps(report), encoding="utf-8")
    prompts = prompts or [f"p{i}" for i in range(len(outs))]
    rows = [{"kind": "ao", "prompt_sha": p, "out_sha": "h" + o, "out_len": len(o), "out_text": o, "tag": tag}
            for p, o in zip(prompts, outs)]
    (d / f"{tag}_io.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _side(d: Path, model: str, overrides: dict[str, list[str]] | None = None, genai: str | None = "2026.4.0.0-x") -> None:
    """Pinned V0 r1-r3 + V1 r1 + V3 r1 for agentic and conversation; ``overrides`` maps a tag suffix
    (e.g. 'agentic-pinned-V3-r1') to a different output list."""
    base = ["alpha", "bravo", "charlie"]
    for suite in ("agentic", "conversation"):
        for variant, reps in (("V0", (1, 2, 3)), ("V1", (1,)), ("V3", (1,))):
            for r in reps:
                suffix = f"{suite}-pinned-{variant}-r{r}"
                _write_run(d, f"{model}-{suffix}", suite, (overrides or {}).get(suffix, base))
    _write_run(d, f"{model}-all-random-r1", "agentic", base)
    if genai:
        (d / f"{model}-agentic-pinned-V0-r1_engine.json").write_text(json.dumps([{"genai_version": genai}]), encoding="utf-8")


@pytest.fixture
def q():
    return _load("analyse_phase1_quality")


# ---- F2 -------------------------------------------------------------------------------------------

def test_compare_reports_a_difference_in_a_run_other_than_v0_r1(q, tmp_path):
    """The old instrument looked at V0-r1 only and called this 'identical'."""
    _side(tmp_path / "on", "m-on", {"agentic-pinned-V3-r1": ["alpha", "BRAVO-different", "charlie"]})
    _side(tmp_path / "off", "m-off")
    res = q.compare(tmp_path / "on", "m-on", tmp_path / "off", "m-off")
    assert res["pinned_totals"]["runs_compared"] == 10
    assert res["pinned_totals"]["outputs_differing"] == 1
    assert res["pinned_totals"]["runs_with_differing_outputs"] == ["agentic-V3-r1"]
    assert res["overall"].startswith("NOT identical: 1 of 30 compared calls differ")
    assert "agentic-V3-r1: calls [1]" in res["overall"]
    bad = [r for r in res["pinned_runs"] if r["outputs_differing"]][0]
    assert bad["prompts_differing"] == 0 and bad["differing_calls"][0]["call_index"] == 1
    assert bad["differing_calls"][0]["common_prefix_chars"] == 0
    assert "out_text" not in json.dumps(res) and "BRAVO" not in json.dumps(res)


def test_compare_says_identical_only_when_every_compared_run_is(q, tmp_path):
    _side(tmp_path / "on", "m-on")
    _side(tmp_path / "off", "m-off")
    res = q.compare(tmp_path / "on", "m-on", tmp_path / "off", "m-off")
    assert res["overall"] == "identical: all 30 calls in all 10 compared pinned runs have identical prompts and identical outputs"


def test_compare_flags_differing_call_count(q, tmp_path):
    _side(tmp_path / "on", "m-on")
    _side(tmp_path / "off", "m-off", {"conversation-pinned-V1-r1": ["alpha", "bravo"]})
    res = q.compare(tmp_path / "on", "m-on", tmp_path / "off", "m-off")
    assert "call counts differ in conversation-V1-r1" in res["overall"]
    assert not res["overall"].startswith("identical")


def test_compare_with_no_shared_pinned_run_is_not_assessable(q, tmp_path):
    _side(tmp_path / "on", "m-on")
    (tmp_path / "off").mkdir()
    assert q.compare(tmp_path / "on", "m-on", tmp_path / "off", "m-off")["overall"].startswith("NOT ASSESSABLE")


def test_compare_run_counts_first_token_vs_later_divergence(q):
    a = [{"prompt_sha": "p", "out_sha": "1", "out_len": 5, "out_text": "hello"}]
    b = [{"prompt_sha": "p", "out_sha": "2", "out_len": 6, "out_text": "help!!"}]
    r = q.compare_run(a, b)
    assert r["differing_calls"][0]["common_prefix_chars"] == 3 and r["differing_calls"][0]["a_out_len"] == 5


# ---- F10 ------------------------------------------------------------------------------------------

def test_compare_covers_every_shared_suite_and_labels_each_runtime(q, tmp_path):
    def allr(d: Path, model: str, statuses: dict[str, dict[str, str]], genai: str | None) -> None:
        d.mkdir(parents=True, exist_ok=True)
        suites = {s: {"cases": [{"id": f"{s}-{i}", "status": st.get(f"{s}-{i}", "pass")} for i in range(2)], "aggregates": {}}
                  for s, st in statuses.items()}
        (d / f"{model}-all-random-r1_report.json").write_text(json.dumps({"suites": suites}), encoding="utf-8")
        if genai:
            (d / f"{model}-x_engine.json").write_text(json.dumps([{"genai_version": genai}]), encoding="utf-8")

    allr(tmp_path / "a", "9b-on", {"agentic": {}, "pa_classification": {"pa_classification-1": "fail"}, "answer_quality": {}}, "2026.4.0.0-x")
    allr(tmp_path / "b", "14b", {"agentic": {}, "pa_classification": {}, "preference_memory": {}}, None)
    res = q.compare(tmp_path / "a", "9b-on", tmp_path / "b", "14b")
    assert sorted(res["suites_all_random_r1"]) == ["agentic", "pa_classification"]
    assert res["suites_all_random_r1"]["pa_classification"]["verdict_differences"] == {"pa_classification-1": ["fail", "pass"]}
    assert res["suites_only_one_side"] == {"only_a": ["answer_quality"], "only_b": ["preference_memory"]}
    assert res["runtime"]["a"]["genai_versions"] == ["2026.4.0.0-x"]
    assert res["runtime"]["b"] == {"genai_versions": [], "note": "runtime not recorded in these reports"}


# ---- F5 -------------------------------------------------------------------------------------------

def _campaign_argv(monkeypatch, tmp_path, model: str) -> list[list[str]]:
    c = _load("run_phase1_campaign")
    seen: list[list[str]] = []

    class _R:
        returncode = 0

    monkeypatch.setattr(c.subprocess, "run", lambda cmd, **kw: (seen.append(list(cmd)), _R())[1])
    monkeypatch.setattr(sys, "argv", ["x", "--model", model, "--out-dir", str(tmp_path / "o"),
                                      "--status-file", str(tmp_path / "s.jsonl"), "--only", "pinned-V0-r1"])
    assert c.main() == 0
    return seen


@pytest.mark.parametrize("model", ["9b-on", "9b-off", "4b-on", "4b-off"])
def test_quality_campaign_passes_engine_summary_for_every_qwen35_job(monkeypatch, tmp_path, model):
    seen = _campaign_argv(monkeypatch, tmp_path, model)
    assert len(seen) == 2  # agentic + conversation pinned V0 r1
    for cmd in seen:
        assert "--engine-summary" in cmd
        assert cmd[cmd.index("--engine-summary") + 1].endswith("_engine.json")
        assert cmd[cmd.index("--engine") + 1] == ("cb-mtp-on" if model.endswith("on") else "cb-mtp-off")


def test_quality_campaign_does_not_pass_engine_summary_for_the_14b(monkeypatch, tmp_path):
    seen = _campaign_argv(monkeypatch, tmp_path, "14b")
    assert seen and all("--engine-summary" not in cmd and "--engine" not in cmd for cmd in seen)


# ---------------------------------------------------------------------------
# F3 / F9: the dataset builder
# ---------------------------------------------------------------------------

LONG = "A generated sentence that is far longer than a short verdict label."


def _speed_inv(path: Path) -> None:
    g = "2026.4.0.0-3407-x"
    rows = [{"arm": a, "visit": 0, "cell": "pa", "protocol": "cold", "genai_version": g, "openvino_version": "ov",
             "status": "ok", "rep": r, "decode_tps": 20.0 + r, "ttft_ms": 900.0, "output_sha256": "ab" * 32,
             "thermal_before": {"temp_c": 70.0}} for a in ("9b-mtp-on", "9b-mtp-off") for r in (0, 1)]
    meta = {"uptime_h": 1.0, "gpu_driver": {"intel": []}}
    path.write_text(json.dumps({"meta": meta, "rows": rows}), encoding="utf-8")


def _quality_dir(run: Path) -> None:
    q9 = run / "q9b_on"
    q9.mkdir(parents=True)
    cases = [
        {"id": "oq-1", "status": "pass", "description": "d", "detail": LONG,
         "actual": {"assert_counts": {"t": 1}, "detail": LONG, "flags": [], "test_count": 1}, "expected": {}},
        {"id": "pa-1", "status": "fail", "description": "x" * 900, "detail": LONG, "actual": "ALLOW", "expected": "DENY"},
        {"id": "ag-1", "status": "pass", "description": "d", "detail": LONG, "actual": LONG, "expected": "x"},
        {"id": "pm-1", "status": "pass", "description": "d", "detail": "", "actual": {"label": "DENY", "nested": {"text": LONG}}},
    ]
    agg = {"passed": 3, "failed": 1, "errors": 0, "skipped_hardware": 0, "evaluated": 4, "total": 4}
    rep = {"regressions": ["pa: regressed vs baseline: " + LONG * 3], "suites": {"oracle_quality": {"cases": cases, "aggregates": agg,
                                                    "baseline_comparison": {"regressions": ["pa: regressed " + LONG * 3]}}}}
    (q9 / "9b-on-all-random-r1_report.json").write_text(json.dumps(rep), encoding="utf-8")
    (q9 / "9b-on-all-random-r1_io.jsonl").write_text(
        json.dumps({"kind": "ao", "out_text": LONG, "out_sha": "h", "prompt_sha": "p"}) + "\n", encoding="utf-8")


def _build_run(tmp_path: Path) -> tuple[Path, Path]:
    run = tmp_path / "run"
    (run / "speed").mkdir(parents=True)
    (run / "ttft").mkdir()
    _speed_inv(run / "speed" / "A1-x.json")
    _speed_inv(run / "speed" / "A10-x.json")
    _quality_dir(run)
    for name in ("variance_9b_on_A.json", "variance_9b_off_A.json", "compare_9b_vs_4b.json", "compare_9b_on_vs_off.json",
                 "q9b_on_summary.json", "speed_summary.json", "stray_notes.json"):
        (run / name).write_text(json.dumps({"k": 1}), encoding="utf-8")
    (run / "campaign_speed.jsonl").write_text("{}\n", encoding="utf-8")
    return run, tmp_path / "out"


def _build(tmp_path: Path, monkeypatch, capsys) -> tuple[Path, str]:
    b = _load("build_phase1_dataset")
    run, out = _build_run(tmp_path)
    monkeypatch.setattr(sys, "argv", ["x", "--run-dir", str(run), "--out", str(out)])
    assert b.main() == 0
    return out, capsys.readouterr().out


def test_builder_output_passes_hf_preflight_with_no_exemption(tmp_path, monkeypatch, capsys):
    out, _ = _build(tmp_path, monkeypatch, capsys)
    hf = _load("hf_publish")
    assert hf.preflight(out) == []
    rep = json.loads((out / "raw/quality/9b-on-all-random-r1_report.json").read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in rep["suites"]["oracle_quality"]["cases"]}
    assert "detail" not in cases["oq-1"] and "detail" not in cases["oq-1"]["actual"]
    assert cases["oq-1"]["actual"]["test_count"] == 1
    assert cases["pa-1"]["actual"] == "ALLOW" and len(cases["pa-1"]["description"]) < 210
    assert cases["ag-1"]["actual"] is None
    assert cases["pm-1"]["actual"]["label"] == "DENY" and cases["pm-1"]["actual"]["nested"]["text"].startswith("<omitted")
    text = (out / "raw/quality/9b-on-all-random-r1_report.json").read_text(encoding="utf-8")
    assert LONG * 3 not in text  # the regression line is cut, not copied whole
    assert max(len(m) for m in rep["regressions"]) <= 163
    assert all(len(m) <= 163 for m in rep["suites"]["oracle_quality"]["baseline_comparison"]["regressions"])
    assert LONG not in (out / "raw/quality/9b-on-all-random-r1_io.jsonl").read_text(encoding="utf-8")


def test_builder_copies_per_size_files_and_names_what_it_dropped(tmp_path, monkeypatch, capsys):
    out, said = _build(tmp_path, monkeypatch, capsys)
    for name in ("variance_9b_on_A.json", "variance_9b_off_A.json", "compare_9b_vs_4b.json", "compare_9b_on_vs_off.json",
                 "q9b_on_summary.json", "speed_summary.json"):
        assert (out / "raw" / name).is_file(), name
    assert (out / "raw/speed/A10-x.json").is_file()  # two-digit invocation number is not dropped
    assert not (out / "raw/stray_notes.json").exists()
    assert "stray_notes.json" in said and "campaign_speed.jsonl" in said and "NOT copied" in said


def test_builder_copies_the_superseded_speed_summaries_when_present(tmp_path, monkeypatch, capsys):
    b = _load("build_phase1_dataset")
    run, out = _build_run(tmp_path)
    (run / "speed_summary_pre_topup.json").write_text(json.dumps({"k": 1}), encoding="utf-8")
    (run / "speed_summary_with_gate_failures.json").write_text(json.dumps({"k": 1}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["x", "--run-dir", str(run), "--out", str(out)])
    assert b.main() == 0
    said = capsys.readouterr().out
    for name in ("speed_summary_pre_topup.json", "speed_summary_with_gate_failures.json"):
        assert (out / "raw" / name).is_file(), name
        assert name not in said


def test_builder_copies_the_variant_probe_and_wraps_long_prose(tmp_path, monkeypatch, capsys):
    b = _load("build_phase1_dataset")
    hf = _load("hf_publish")
    run, out = _build_run(tmp_path)
    pv = run / "pa_variants"
    pv.mkdir()
    long_para = " ".join(["word"] * 200)
    nl = chr(10)
    (pv / "ANALYSIS.md").write_text(nl.join(["# T", "", long_para, "", "- " + long_para, "", "| a | b |", "|---|---|", ""]), encoding="utf-8")
    (pv / "tables.md").write_text("| a |" + nl, encoding="utf-8")
    (pv / "9b_rows.jsonl").write_text(json.dumps({"case_id": "c", "raw_text": "DECISION: ALLOW"}) + nl, encoding="utf-8")
    (pv / "scratch.bin").write_bytes(b"x")
    monkeypatch.setattr(sys, "argv", ["x", "--run-dir", str(run), "--out", str(out)])
    assert b.main() == 0
    dst = out / "raw/pa_variants"
    assert (dst / "tables.md").is_file() and (dst / "9b_rows.jsonl").is_file() and not (dst / "scratch.bin").exists()
    text = (dst / "ANALYSIS.md").read_text(encoding="utf-8")
    assert max(len(ln) for ln in text.splitlines()) <= 110
    assert text.split().count("word") == 400  # wrapping loses no words
    assert "| a | b |" in text
    assert hf.preflight(out) == []


def test_builder_requires_an_explicit_out(monkeypatch):
    b = _load("build_phase1_dataset")
    monkeypatch.setattr(sys, "argv", ["x", "--run-dir", "whatever"])
    with pytest.raises(SystemExit) as e:
        b.main()
    assert e.value.code == 2


# ---------------------------------------------------------------------------
# F6 / F7 / F8: the speed and TTFT analysers read what is in the data
# ---------------------------------------------------------------------------

G4, G14 = "2026.4.0.0-3407-x", "2026.2.1.0-3123-x"


def _inv(path: Path, arms: list[str], *, vary: set[tuple[str, str]] = frozenset(), tokens_14b: dict[str, int] | None = None) -> None:
    """One speed invocation with two visits per arm. ``vary`` = {(arm, cell)} get two distinct output hashes."""
    rows, rounds = [], []
    for arm in arms:
        genai = G14 if arm == "14b-ship" else G4
        for visit in (0, 1):
            rounds.append({"arm": arm, "visit": visit, "genai_version": genai, "peak_in_use_gb": 20.0,
                           **({"mtp_summary": {"generations": 5, "draft_tokens": 100, "accepted_tokens": 70 + (10 if arm.startswith("9b") else 0),
                                               "acceptance_rate": 0.7 + (0.1 if arm.startswith("9b") else 0.0),
                                               "think_first_chunk_count": 0}} if arm.endswith("mtp-on") else {})})
            for protocol, cell in (("cold", "pa"), ("cold", "ao-long"), ("plateau", "multiturn:t3")):
                for rep in (0, 1):
                    sha = f"h{visit}" if (arm, cell) in vary and cell == "multiturn:t3" else "h"
                    tok = (tokens_14b or {}).get(cell, 100) if arm == "14b-ship" else 100
                    rows.append({"arm": arm, "visit": visit, "cell": cell, "protocol": protocol, "genai_version": genai,
                                 "openvino_version": "ov", "status": "ok", "rep": rep, "decode_tps": 20.0 + visit * 0.1 + rep * 0.01,
                                 "ttft_ms": 900.0 + visit, "output_sha256": sha, "input_tokens": tok, "thermal_before": {"temp_c": 70.0}})
    meta = {"uptime_h": 1.0, "gpu_driver": {"intel": []}, "baseline_in_use_gb": 8.0}
    path.write_text(json.dumps({"meta": meta, "arm_rounds": rounds, "rows": rows}), encoding="utf-8")


def _speed(tmp_path: Path, arms: list[str], **kw: Any) -> dict[str, Any]:
    s = _load("analyse_phase1_speed")
    d = tmp_path / "speed"
    d.mkdir(exist_ok=True)
    _inv(d / "A1-x.json", arms, **kw)
    _inv(d / "A10-x.json", arms, **kw)  # two-digit invocation number is read too
    out = tmp_path / "s.json"
    old, sys.argv = sys.argv, ["x", "--dir", str(d), "--out", str(out)]
    try:
        assert s.main() == 0
    finally:
        sys.argv = old
    return json.loads(out.read_text(encoding="utf-8"))


PHASE1_ARMS = ["4b-mtp-on", "4b-mtp-off", "4b-prefix-cache", "14b-ship"]


def test_speed_notes_keep_the_phase1_wording_for_phase1_shaped_data(tmp_path):
    res = _speed(tmp_path, PHASE1_ARMS, vary={("14b-ship", "multiturn:t3")}, tokens_14b={"pa": 811, "ao-long": 6075})
    assert res["notes"][0] == ("Cache arms (4b-prefix-cache, 14b-ship) report TTFT from the COLD protocol only: the plateau protocol repeats "
                               "prompts the cold one already cached, so their plateau ttft_ms_visit_means is {n: 0} by design.")
    assert res["notes"][1] == ("output_identity.n_distinct > 1 for a cell means that arm produced different bytes across visits for the same "
                               "prompt; the shipped 14B does so on 1 of its plateau multi-turn cells (speed rows), so 'identical outputs' holds "
                               "for the three 4B arms, not for the 14B on long multi-turn prompts.")
    assert res["notes"][2] == ("Input-token counts in the cell labels are the 4B tokenizer's; the 14B tokenizer counts 811 (pa) and 6075 (ao-long).")


def test_speed_notes_name_only_arms_that_ran(tmp_path):
    res = _speed(tmp_path, ["9b-mtp-on", "9b-mtp-off", "9b-prefix-cache", "4b-mtp-on", "14b-ship"],
                 vary={("14b-ship", "multiturn:t3")}, tokens_14b={"pa": 811, "ao-long": 6075})
    text = " ".join(res["notes"])
    assert "4b-prefix-cache" not in text and "three arms of each" not in text
    assert "Cache arms (9b-prefix-cache, 14b-ship)" in res["notes"][0]
    assert "holds for the one 4B arm that ran (4b-mtp-on) and the three 9B arms" in res["notes"][1]


def test_speed_notes_do_not_assert_a_14b_divergence_the_data_lacks(tmp_path):
    res = _speed(tmp_path, ["9b-mtp-on", "9b-mtp-off", "9b-prefix-cache", "14b-ship"])
    assert "the shipped 14B does so" not in res["notes"][1]
    assert "no arm did so in this data" in res["notes"][1]


def test_speed_notes_report_a_9b_divergence_when_it_happens(tmp_path):
    res = _speed(tmp_path, ["9b-mtp-on", "9b-mtp-off", "9b-prefix-cache"], vary={("9b-mtp-on", "multiturn:t3")})
    assert "9b-mtp-on does so on 1 of its plateau multi-turn cells" in res["notes"][1]
    assert "the two 9B arms that ran (9b-mtp-off, 9b-prefix-cache)" in res["notes"][1]
    assert res["notes"][1].endswith(", not for 9b-mtp-on.")


def test_speed_reads_two_digit_invocation_numbers(tmp_path):
    res = _speed(tmp_path, ["9b-mtp-on"])
    assert [i["file"] for i in res["invocations"]] == ["A1-x.json", "A10-x.json"]
    assert res["memory_in_use_total_minus_available"]["9b-mtp-on"]["peak_in_use_gb"]["n"] == 4


def test_speed_notes_take_the_14b_token_counts_from_the_rows(tmp_path):
    res = _speed(tmp_path, ["9b-mtp-on", "14b-ship"], tokens_14b={"pa": 1000, "ao-long": 7000})
    assert "the 9B tokenizer's; the 14B tokenizer counts 1000 (pa) and 7000 (ao-long)." in res["notes"][2]


def test_speed_mtp_acceptance_rows_carry_the_arm(tmp_path):
    res = _speed(tmp_path, ["9b-mtp-on", "4b-mtp-on"])
    by_arm = {}
    for r in res["mtp_witness"]:
        by_arm.setdefault(r["arm"], set()).add(round(r["acceptance_rate"], 2))
    assert by_arm == {"9b-mtp-on": {0.8}, "4b-mtp-on": {0.7}}


def _ttft_file(path: Path, arms: list[str]) -> None:
    rows = [{"arm": a, "turn": t, "visit": v, "ttft_ms": 100.0 + v, "tpot_ms": 10.0, "input_tokens": 50 * t,
             "reply_sha256": "r" + str(t), "thermal_before": {"temp_c": 70.0}} for a in arms for t in range(1, 7) for v in (0, 1)]
    path.write_text(json.dumps({"meta": {"genai": G4}, "rows": rows}), encoding="utf-8")


def _ttft(tmp_path: Path, arms: list[str]) -> dict[str, Any]:
    t = _load("analyse_phase1_ttft")
    f, out = tmp_path / "t.json", tmp_path / "ts.json"
    _ttft_file(f, arms)
    old, sys.argv = sys.argv, ["x", "--in", str(f), "--out", str(out)]
    try:
        assert t.main() == 0
    finally:
        sys.argv = old
    return json.loads(out.read_text(encoding="utf-8"))


def test_ttft_agreement_keys_follow_the_sizes_present(tmp_path):
    only9 = _ttft(tmp_path, ["9b-mtp-on", "9b-mtp-off", "14b-ship"])["reply_identity"]["t1"]
    assert "four_b_arms_agree" not in only9 and only9["9b_arms_agree"] is True
    only4 = _ttft(tmp_path, ["4b-mtp-on", "4b-mtp-off", "14b-ship"])["reply_identity"]["t1"]
    assert only4["four_b_arms_agree"] is True and "9b_arms_agree" not in only4
    both = _ttft(tmp_path, ["4b-mtp-on", "9b-mtp-on"])["reply_identity"]["t1"]
    assert "four_b_arms_agree" in both and "9b_arms_agree" in both


# ---------------------------------------------------------------------------
# N7: the speed campaign forwards each size's model directory to the bench
# ---------------------------------------------------------------------------

def test_speed_campaign_forwards_model_dir_flags_to_every_bench_job(monkeypatch, tmp_path):
    c = _load("run_phase1_speed_campaign")
    seen: list[list[str]] = []

    class _R:
        returncode = 0

    monkeypatch.setattr(c.subprocess, "run", lambda cmd, **kw: (seen.append(list(cmd)), _R())[1])
    monkeypatch.setattr(c.time, "sleep", lambda s: None)
    monkeypatch.setattr(sys, "argv", ["x", "--out-dir", str(tmp_path / "o"), "--status-file", str(tmp_path / "s.jsonl"),
                                      "--sizes", "9b", "--reference", "4b-mtp-on", "--model-9b", "X:/nine", "--model-4b", "X:/four"])
    assert c.main() == 0
    assert len(seen) == 10
    for cmd in seen:
        assert cmd[cmd.index("--model-9b") + 1] == "X:/nine"
        assert cmd[cmd.index("--model-4b") + 1] == "X:/four"
