"""Locks for the round-2 review of #1665 (G4 strict sensitivity, G5 preflight holes, G6 builder, G12, G13).

CPU-only: synthetic directories through the real scripts; no model.
"""

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
sys.path.insert(0, str(ROOT))


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GEN = ("The model said that the assistant should proceed with the requested operation and then summarise "
       "what it did for the user in a friendly tone. ") * 10  # about 1,300 chars of prose
NL = chr(10)


# ---------------------------------------------------------------------------
# G4 / G13: cold-gate exclusion and the strict start-temperature sensitivity
# ---------------------------------------------------------------------------

def _row(arm: str, visit: int, rep: int, tps: float, *, reached: Any = True, start_c: float | None = 70.0,
         protocol: str = "cold", gate_present: bool = True) -> dict[str, Any]:
    row: dict[str, Any] = {"arm": arm, "visit": visit, "cell": "pa", "protocol": protocol, "genai_version": "2026.4.0.0-x",
                           "openvino_version": "ov", "status": "ok", "rep": rep, "decode_tps": tps, "ttft_ms": 900.0,
                           "output_sha256": "h", "input_tokens": 100,
                           "thermal_before": {"temp_c": start_c} if start_c is not None else {}}
    if gate_present:
        row["cold_wait"] = {"reached": reached, "temp_c": 70.0, "waited_s": 1.0}
    return row


def _speed(tmp_path: Path, rows_by_arm: dict[str, list[dict[str, Any]]], *extra: str) -> dict[str, Any]:
    s = _load("analyse_phase1_speed")
    d = tmp_path / "speed"
    d.mkdir(parents=True, exist_ok=True)
    rounds = [{"arm": arm, "visit": v, "genai_version": "2026.4.0.0-x", "peak_in_use_gb": 20.0} for arm in rows_by_arm for v in range(6)]
    rows = [r for rs in rows_by_arm.values() for r in rs]
    (d / "A1-x.json").write_text(json.dumps({"meta": {"uptime_h": 1.0, "gpu_driver": {"intel": []}, "baseline_in_use_gb": 8.0},
                                             "arm_rounds": rounds, "rows": rows}), encoding="utf-8")
    out = tmp_path / "s.json"
    old, sys.argv = sys.argv, ["x", "--dir", str(d), "--out", str(out), *extra]
    try:
        assert s.main() == 0
    finally:
        sys.argv = old
    return json.loads(out.read_text(encoding="utf-8"))


def _arms(**cold_fault: Any) -> dict[str, list[dict[str, Any]]]:
    """Two arms, 4 visits each, one rep per visit. ``cold_fault`` overrides row 3 of arm 'a' (visit 3)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for arm, base in (("9b-mtp-on", 20.0), ("9b-mtp-off", 10.0)):
        rows = [_row(arm, v, 0, base + v * 0.1) for v in range(4)]
        out[arm] = rows
    if cold_fault:
        out["9b-mtp-on"][3] = _row("9b-mtp-on", 3, 0, 5.0, **cold_fault)  # a very slow reading
    return out


def _mean_on(res: dict[str, Any]) -> dict[str, Any]:
    return res["per_protocol_cell_arm"]["cold"]["pa"]["9b-mtp-on"]["decode_tps_visit_means"]


def test_strict_flag_off_adds_no_strict_keys_and_keeps_start_hot_rows(tmp_path):
    res = _speed(tmp_path, _arms(start_c=75.9))
    assert "cold_strict_start_dropped" not in res and "cold_strict_start_temp_c" not in res
    assert _mean_on(res)["n"] == 4  # reached=True: kept, as the default rule has always done
    assert "POST-HOC" in res["cold_gate_operationalisation_note"]


def test_strict_flag_drops_cold_rows_that_started_above_the_limit(tmp_path):
    res = _speed(tmp_path, _arms(start_c=75.9), "--strict-start-temp", "72")
    assert _mean_on(res)["n"] == 3
    assert [d["temp_c_at_start"] for d in res["cold_strict_start_dropped"]] == [75.9]
    assert res["cold_strict_start_dropped"][0]["gate_reached"] is True
    assert "SENSITIVITY" in res["cold_strict_start_note"] and "1 further rows" in res["cold_strict_start_note"]


def test_strict_flag_keeps_a_row_exactly_at_the_limit(tmp_path):
    res = _speed(tmp_path, _arms(start_c=72.0), "--strict-start-temp", "72")
    assert _mean_on(res)["n"] == 4 and res["cold_strict_start_dropped"] == []


def test_strict_flag_drops_a_row_with_no_start_temperature(tmp_path):
    res = _speed(tmp_path, _arms(start_c=None), "--strict-start-temp", "72")
    assert _mean_on(res)["n"] == 3 and res["cold_strict_start_dropped"][0]["temp_c_at_start"] is None


def test_strict_flag_leaves_the_plateau_protocol_alone(tmp_path):
    arms = _arms()
    arms["9b-mtp-on"].append(_row("9b-mtp-on", 0, 1, 20.0, protocol="plateau", start_c=90.0))
    res = _speed(tmp_path, arms, "--strict-start-temp", "72")
    assert res["cold_strict_start_dropped"] == []
    assert res["per_protocol_cell_arm"]["plateau"]["pa"]["9b-mtp-on"]["decode_tps_visit_means"]["n"] == 1


def test_strict_output_equals_default_output_apart_from_the_new_keys_and_the_dropped_rows(tmp_path):
    base = _speed(tmp_path / "a", _arms())
    strict = _speed(tmp_path / "b", _arms(), "--strict-start-temp", "72")
    assert set(strict) - set(base) == {"cold_strict_start_temp_c", "cold_strict_start_dropped", "cold_strict_start_note"}
    assert {k for k in base if base[k] != strict[k]} == set()


def test_gate_flag_false_is_still_excluded_and_unmeasured_gate_is_kept(tmp_path):
    """G13: a row with cold_wait.reached False is not cold; a row whose gate was never measured (no cold_wait,
    or reached None) is KEPT. Locks both directions so widening the exclusion to unmeasured rows is seen."""
    res = _speed(tmp_path, _arms(reached=False))
    assert _mean_on(res)["n"] == 3 and len(res["cold_gate_not_reached"]) == 1
    res = _speed(tmp_path / "n", _arms(reached=None))
    assert _mean_on(res)["n"] == 4 and res["cold_gate_not_reached"] == []
    arms = _arms()
    arms["9b-mtp-on"][3] = _row("9b-mtp-on", 3, 0, 5.0, gate_present=False)
    res = _speed(tmp_path / "m", arms)
    assert _mean_on(res)["n"] == 4


# ---------------------------------------------------------------------------
# G5: the preflight holes
# ---------------------------------------------------------------------------

hf = _load("hf_publish")


def _put(tmp_path: Path, name: str, content: str | bytes) -> list[str]:
    root = tmp_path / "ds"
    root.mkdir(parents=True, exist_ok=True)
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        p.write_bytes(content)
    else:
        p.write_text(content, encoding="utf-8")
    return hf.preflight(root)


def test_list_of_strings_under_an_unlisted_key_is_refused(tmp_path):
    assert _put(tmp_path, "a.json", json.dumps({"outs": [GEN]}))


def test_list_of_short_prose_strings_under_a_text_key_is_refused(tmp_path):
    assert _put(tmp_path, "a.json", json.dumps({"reply": ["x" * 30]}))


def test_bare_json_string_line_is_refused(tmp_path):
    assert _put(tmp_path, "a.jsonl", json.dumps(GEN) + NL)


def test_nested_string_of_moderate_length_under_an_unlisted_key_is_refused(tmp_path):
    assert _put(tmp_path, "a.json", json.dumps({"turns": [{"c": GEN[:400]}]}))


def test_authored_note_keys_may_carry_a_long_sentence_but_not_over_the_hard_cap(tmp_path):
    assert _put(tmp_path, "a.json", json.dumps({"notes": ["x" * 300]})) == []
    assert _put(tmp_path / "t", "a.json", json.dumps({"notes": ["x" * 600]}))


def test_csv_unknown_column_is_refused_and_known_columns_pass(tmp_path):
    assert _put(tmp_path, "a.csv", "arm,gen" + NL + "a," + GEN[:30] + NL)
    assert _put(tmp_path / "ok", "a.csv", "arm,decode_tps" + NL + "a,1.5" + NL) == []


def test_csv_overlong_cell_in_a_known_column_is_refused(tmp_path):
    assert _put(tmp_path, "a.csv", "arm,decode_tps" + NL + "a," + "9" * 300 + NL)


def test_nested_readme_is_scanned_like_any_prose_file(tmp_path):
    assert _put(tmp_path, "raw/README.md", GEN)
    assert _put(tmp_path / "root", "README.md", GEN) == []  # the dataset's own root card is authored


def test_markdown_wrapped_below_the_old_cap_is_refused(tmp_path):
    assert _put(tmp_path, "a.md", ("word " * 39)[:199])


@pytest.mark.parametrize("name", ["a.yaml", "a.tsv", "LOG"])
def test_other_file_types_are_refused(tmp_path, name):
    assert any("not accepted" in h for h in _put(tmp_path, name, "k: v"))


def test_secret_and_email_shapes_in_file_names_are_refused(tmp_path):
    assert any("file name" in h for h in _put(tmp_path, "hf_" + "A" * 34 + ".json", "{}"))
    assert any("file name" in h for h in _put(tmp_path / "e", "someone@example.org.json", "{}"))


def test_json_escaped_identity_forms_are_refused(tmp_path):
    assert _put(tmp_path, "a.json", '{"k":"someone\\u0040example.org"}')
    assert _put(tmp_path / "t", "a.json", '{"k":"hf\\u005f' + "A" * 30 + '"}')
    assert _put(tmp_path / "h", "a.json", '{"k":"NORTHSTAR\\u003100"}')


def test_every_metric_column_of_the_builders_is_allowed(tmp_path):
    """Reachability: the allowlist must cover what the builder writes, or a clean dataset would be refused."""
    b = _load("build_phase1_dataset")
    src = (SCRIPTS / "build_phase1_dataset.py").read_text(encoding="utf-8")
    assert "speed_rows.csv" in src and b is not None
    cols = {"invocation", "arm", "visit", "protocol", "cell", "rep", "status", "t", "ttft_ms", "tpot_ms", "decode_tps",
            "decode_tps_wall", "input_tokens", "generated_tokens", "wall_ms", "output_sha256", "draft_tokens",
            "accepted_tokens", "temp_c_before", "temp_c_after", "passive_limit_pct_before", "throttle_reasons_before",
            "genai_version", "openvino_version", "gpu_driver", "uptime_h", "n_reps", "decode_tps_mean", "ttft_ms_rep0",
            "ttft_ms_mean", "model", "job", "suite", "case_id", "passed", "failed", "errors", "skipped_hardware",
            "tool_calls", "evaluated", "total", "turn", "reply_sha256"}
    assert cols <= hf.KNOWN_CSV_COLUMNS


# ---------------------------------------------------------------------------
# G12: trailing-newline option values and a non-console refusal message
# ---------------------------------------------------------------------------

def test_trailing_newline_is_refused_in_config_and_path(tmp_path):
    assert hf._validate_target("c1" + NL, "ok/data") is not None
    assert hf._validate_target("c1", "x" + NL) is not None
    assert hf._validate_target("c1", "ok/data") is None


def test_main_survives_a_refusal_message_with_non_console_text(tmp_path, monkeypatch):
    import io

    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="ascii", errors="strict"))
    rc = hf.main(["plan", "--dir", str(tmp_path), "--config", "c‐x", "--path-in-repo", "ok/data"])
    sys.stdout.flush()
    assert rc == 2 and b"FAIL config name" in raw.getvalue()


# ---------------------------------------------------------------------------
# G6: the builder
# ---------------------------------------------------------------------------

def _mini_run(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    (run / "speed").mkdir(parents=True)
    row = {"arm": "4b-mtp-on", "visit": 0, "cell": "pa", "protocol": "cold", "rep": 0, "status": "ok", "t": "t", "decode_tps": 30.0,
           "ttft_ms": 800.0, "genai_version": "2026.4.0.0-x", "openvino_version": "ov", "output_sha256": "ab" * 32,
           "thermal_before": {"temp_c": 60.0}}
    (run / "speed" / "A1-x.json").write_text(json.dumps({"meta": {"uptime_h": 1.0, "gpu_driver": {"intel": []}}, "rows": [row],
                                                        "arm_rounds": []}), encoding="utf-8")
    return run


def test_builder_refuses_a_non_empty_out_and_writes_nothing(tmp_path, monkeypatch, capsys):
    b = _load("build_phase1_dataset")
    run = _mini_run(tmp_path)
    out = tmp_path / "existing"
    out.mkdir()
    (out / "keep.txt").write_text("a committed dataset file", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["x", "--run-dir", str(run), "--out", str(out)])
    assert b.main() == 2
    assert sorted(p.name for p in out.iterdir()) == ["keep.txt"]
    assert "REFUSED" in capsys.readouterr().out


def test_builder_accepts_an_absent_or_empty_out(tmp_path, monkeypatch):
    b = _load("build_phase1_dataset")
    run = _mini_run(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    for out in (empty, tmp_path / "absent"):
        monkeypatch.setattr(sys, "argv", ["x", "--run-dir", str(run), "--out", str(out)])
        assert b.main() == 0
        assert (out / "speed_rows.csv").is_file()


def test_builder_strips_raw_text_from_the_probe_rows_and_keeps_the_rest(tmp_path, monkeypatch):
    b = _load("build_phase1_dataset")
    run = _mini_run(tmp_path)
    pv = run / "pa_variants"
    pv.mkdir()
    row = {"case_id": "c", "variant": "V0", "gpu_label": "ALLOW", "confidence": 0.95, "prompt_sha": "abc", "raw_text": "DECISION: ALLOW"}
    (pv / "9b_rows.jsonl").write_text(json.dumps(row) + NL + json.dumps({**row, "case_id": "d"}) + NL, encoding="utf-8")
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["x", "--run-dir", str(run), "--out", str(out)])
    assert b.main() == 0
    rows = [json.loads(ln) for ln in (out / "raw/pa_variants/9b_rows.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2 and all("raw_text" not in r for r in rows)
    assert rows[0]["gpu_label"] == "ALLOW" and rows[0]["prompt_sha"] == "abc" and rows[1]["case_id"] == "d"
    assert "DECISION: ALLOW" not in (out / "raw/pa_variants/9b_rows.jsonl").read_text(encoding="utf-8")


def test_builder_scrubs_long_expected_fixture_values(tmp_path):
    b = _load("build_phase1_dataset")
    rep = {"suites": {"s": {"cases": [{"id": "x", "expected": {"body": "a" * 500, "label": "DENY"}}]}}}
    out = b.sanitise_report(rep)["suites"]["s"]["cases"][0]["expected"]
    assert out["label"] == "DENY" and out["body"] == "<omitted 500 chars>"


# ---------------------------------------------------------------------------
# G11: a divergence note says which runtime each varying cell belongs to
# ---------------------------------------------------------------------------

def test_identity_note_splits_a_14b_divergence_across_its_two_runtimes(tmp_path):
    arms: dict[str, list[dict[str, Any]]] = {"9b-mtp-on": [_row("9b-mtp-on", 0, 0, 20.0)], "14b-ship": []}
    for v, (genai, cell) in enumerate((("2026.2.1.0-x", "multiturn:t6"), ("2026.4.0.0-x", "multiturn:t3"))):
        for sha in ("h1", "h2"):
            r = _row("14b-ship", v, 0, 10.0, protocol="plateau")
            r.update(genai_version=genai, cell=cell, output_sha256=sha)
            arms["14b-ship"].append(r)
    res = _speed(tmp_path, arms)
    note = res["notes"][1]
    assert "the shipped 14B does so on 2 of its plateau multi-turn cells (speed rows) [14b-ship@2026.2.1 on 1, 14b-ship@2026.4 on 1]" in note


# ---------------------------------------------------------------------------
# Round 3: H3 (preflight holes), H4 (public metadata), H5 (4B compare file), N2, N4, N7/M8
# ---------------------------------------------------------------------------

def test_dict_key_that_is_free_text_is_refused(tmp_path):
    assert any("object key" in h for h in _put(tmp_path, "a.json", json.dumps({GEN: 1})))
    assert _put(tmp_path / "ok", "a.json", json.dumps({"decode_tps": 1})) == []


def test_csv_cells_beyond_the_header_are_refused(tmp_path):
    assert any("more cells" in h for h in _put(tmp_path, "a.csv", "arm,visit" + NL + "x,1," + GEN + NL))


def test_csv_numeric_hash_and_id_columns_are_enforced_per_cell(tmp_path):
    assert _put(tmp_path, "a.csv", "arm,decode_tps" + NL + "a,hello there" + NL)
    assert _put(tmp_path / "h", "a.csv", "arm,output_sha256" + NL + "a,not a hash" + NL)
    assert _put(tmp_path / "i", "a.csv", "case_id,visit" + NL + "this is a sentence of prose,1" + NL)
    assert _put(tmp_path / "ok", "a.csv", "arm,decode_tps,output_sha256" + NL + "14b-ship@2026.2.1,1.5e1," + "ab" * 32 + NL) == []


def test_chunked_free_text_is_bounded_by_the_per_file_budget(tmp_path):
    chunk = "w" * 230
    assert any("budget" in h for h in _put(tmp_path, "a.json", json.dumps({"outs": [chunk] * 300})))
    assert any("budget" in h for h in _put(tmp_path / "n", "a.json", json.dumps({"notes": ["x" * 499] * 50})))
    assert any("budget" in h for h in _put(tmp_path / "m", "a.md", (("word " * 19) + NL) * 400))
    assert _put(tmp_path / "ok", "a.json", json.dumps({"outs": [chunk] * 20})) == []


@pytest.mark.parametrize("msg", ["contact someone@example.org", "token hf_" + "A" * 30, "by mrbla", "host NORTHSTAR100"])
def test_commit_message_with_identity_or_credential_shapes_is_refused(msg):
    assert hf._validate_target("c1", "ok/data", msg) is not None


def test_config_and_path_in_repo_are_scanned_too():
    assert hf._validate_target("c1", "mrbla/data", "m") is not None
    assert hf._validate_target("hf_" + "A" * 30, "ok/data", "m") is not None
    assert hf._validate_target("c1", "ok/data", "plain message") is None


def test_env_identity_values_are_refused_in_the_message(monkeypatch):
    monkeypatch.setenv("USERNAME", "zzqqxxuser")
    assert hf._validate_target("c1", "ok/data", "by zzqqxxuser") is not None


def test_upload_refuses_before_any_subprocess_when_the_message_leaks(tmp_path, monkeypatch):
    (tmp_path / "ds").mkdir()
    (tmp_path / "ds" / "a.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(hf.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("subprocess ran")))
    rc = hf.main(["upload", "--dir", str(tmp_path / "ds"), "--config", "c1", "--path-in-repo", "ok/data",
                  "--message", "by someone@example.org"])
    assert rc == 2


def test_builder_recomputes_the_4b_on_off_compare_file(tmp_path, monkeypatch):
    b = _load("build_phase1_dataset")
    run = _mini_run(tmp_path)
    (run / "compare_on_vs_off.json").write_text("{}", encoding="utf-8")
    (run / "q4b_on").mkdir()
    (run / "q4b_off").mkdir()
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["x", "--run-dir", str(run), "--out", str(out)])
    assert b.main() == 0
    f = out / "raw" / "compare_4b_on_vs_off_recomputed.json"
    assert f.is_file()
    res = json.loads(f.read_text(encoding="utf-8"))
    assert res["a"] == "4b-on" and res["b"] == "4b-off" and "pinned_totals" in res
    assert hf.preflight(out) == []


def test_builder_does_not_invent_the_compare_file_for_a_run_without_the_legacy_one(tmp_path, monkeypatch):
    b = _load("build_phase1_dataset")
    run = _mini_run(tmp_path)
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["x", "--run-dir", str(run), "--out", str(out)])
    assert b.main() == 0
    assert not (out / "raw" / "compare_4b_on_vs_off_recomputed.json").exists()


def _campaign_dry(monkeypatch, capsys, sizes_arg: str) -> tuple[int, str]:
    c = _load("run_phase1_speed_campaign")
    monkeypatch.setattr(sys, "argv", ["x", "--out-dir", "o", "--status-file", "s", "--sizes", sizes_arg, "--dry-run"])
    rc = c.main()
    return rc, capsys.readouterr().out


def test_campaign_deduplicates_repeated_sizes(monkeypatch, capsys):
    _, once = _campaign_dry(monkeypatch, capsys, "9b")
    _, twice = _campaign_dry(monkeypatch, capsys, "9b,9b")
    assert once == twice


def test_campaign_rejects_an_empty_size_list(monkeypatch, capsys):
    for bad in ("", ",", " , "):
        with pytest.raises(SystemExit) as e:
            _campaign_dry(monkeypatch, capsys, bad)
        assert e.value.code == 2


def test_build_orders_does_not_repeat_arms_for_a_repeated_size():
    c = _load("run_phase1_speed_campaign")
    assert c.build_orders(["9b", "9b"], []) == c.build_orders(["9b"], [])


def test_single_run_quality_blocks_say_so(tmp_path):
    q = _load("analyse_phase1_quality")
    d = tmp_path / "q"
    d.mkdir()
    cases = [{"id": "aq-1", "status": "fail"}, {"id": "aq-2", "status": "pass"}]
    rep = {"suites": {s: {"cases": cases, "aggregates": {"passed": 1, "failed": 1, "errors": 0, "skipped_hardware": 0,
                                                         "evaluated": 2, "total": 2}}
                      for s in ("pa_classification", "answer_quality", "preference_memory", "agentic", "conversation")}}
    (d / "m-all-random-r1_report.json").write_text(json.dumps(rep), encoding="utf-8")
    (d / "m-all-random-r1_io.jsonl").write_text("", encoding="utf-8")
    res = q.summarise_model(d, "m")
    blk = res["answer_quality_repeats"]
    assert blk["runs"] == 1 and blk["single_run"] is True and "not a repeated finding" in blk["single_run_note"]
    assert blk["failing_in_every_run"] == ["aq-1"]  # kept for continuity; the flag and note qualify it


def test_repeated_quality_blocks_are_not_flagged_single_run(tmp_path):
    q = _load("analyse_phase1_quality")
    d = tmp_path / "q"
    d.mkdir()
    block = {"cases": [{"id": "c", "status": "pass"}], "aggregates": {
        "passed": 1, "failed": 0, "errors": 0, "skipped_hardware": 0, "evaluated": 1, "total": 1}}
    rep = {"suites": {s: block for s in ("pa_classification", "answer_quality", "preference_memory", "agentic", "conversation")}}
    for tag in ("m-all-random-r1", "m-pa_classification-random-r2"):
        (d / f"{tag}_report.json").write_text(json.dumps(rep), encoding="utf-8")
        (d / f"{tag}_io.jsonl").write_text("", encoding="utf-8")
    blk = q.summarise_model(d, "m")["pa_classification_repeats"]
    assert blk["runs"] == 2 and blk["single_run"] is False and "single_run_note" not in blk


def test_bench_meta_carries_a_model_entry_for_every_size_that_ran():
    bench = _load("bench_qwen35_speed")
    sizes = _load("phase1_sizes")
    ns = type("A", (), {"model_4b": "d4", "model_14b": "d14", "models_root": "root"})()
    for s in sizes.SIZES:
        setattr(ns, f"model_{s}", f"dir-{s}")
    for s in sizes.SIZES:
        arms = list(sizes.cb_arms(s)) + [sizes.ARM_14B]
        m = bench.models_meta(ns, arms)
        assert m["model_4b"] == "dir-4b" and m["model_14b"] == "d14" and m["models_root"] == "root"
        assert m[f"model_{s}"] == f"dir-{s}"
    both = bench.models_meta(ns, [a for s in sizes.SIZES for a in sizes.cb_arms(s)])
    assert all(f"model_{s}" in both for s in sizes.SIZES)


def test_default_summary_counts_kept_cold_rows_that_started_above_the_limit(tmp_path):
    res = _speed(tmp_path, _arms(start_c=75.9))
    k = res["cold_gate_kept_rows_started_above_limit"]
    assert k["limit_c"] == 72.0 and k["kept_cold_rows"] == 8 and k["started_above_limit"] == 1 and k["fraction"] == 0.125
    res = _speed(tmp_path / "g", _arms(reached=False))
    assert res["cold_gate_kept_rows_started_above_limit"]["kept_cold_rows"] == 7


def test_a_numeric_column_refuses_a_short_word(tmp_path):
    assert any("generated-text column" in h for h in _put(tmp_path, "a.csv", "arm,decode_tps" + NL + "a,abc" + NL))


def test_bench_run_builds_its_models_meta_through_the_helper():
    import inspect

    bench = _load("bench_qwen35_speed")
    assert '"models": models_meta(args, arms)' in inspect.getsource(bench.run)
