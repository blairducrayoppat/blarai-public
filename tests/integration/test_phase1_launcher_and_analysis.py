"""
#1663 Phase 1 instruments — launcher patches, analysers, dataset sanitiser, CB empty-result guard.

Every control is tested ON and OFF: the effect must appear with the patch
installed and be absent without it. CPU-only; the OpenVINO boundary is faked.
Patch installers mutate global classes, so each test registers the original with
``monkeypatch`` BEFORE calling the installer; teardown restores it.
"""

from __future__ import annotations

import ast
import argparse
import hashlib
import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

# Imported BEFORE any test installs a fake openvino_genai (see test_eval_cb_engine).
import shared.inference.shared_pipeline  # noqa: F401
from evals import cb_pipeline, loader
from evals import types as eval_types
from evals.cb_pipeline import CBEngineError, CBEnginePipeline

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ---------------------------------------------------------------------------
# A1. perturbation wraps load_golden
# ---------------------------------------------------------------------------


def _golden(tmp_path: Path, prompt: str = "Hello there. Is it ok?") -> Path:
    p = tmp_path / "g.jsonl"
    case = {"id": "c1", "description": "d", "prompt": prompt,
            "prior_turns": [{"role": "user", "content": "Earlier. Text here."}, {"role": "x", "content": 5}]}
    p.write_text(json.dumps(case) + "\n", encoding="utf-8")
    return p


class TestPerturbation:
    def test_without_installer_cases_are_unchanged(self, tmp_path: Path) -> None:
        _load("run_evals_instrumented")
        c = loader.load_golden(_golden(tmp_path))[0]
        assert c["prompt"] == "Hello there. Is it ok?"
        assert c["prior_turns"][0]["content"] == "Earlier. Text here."

    @pytest.mark.parametrize("variant,prompt,prior", [
        ("V1", "Hello there. Is it ok? ", "Earlier. Text here. "),
        ("V2", "Hello there.  Is it ok?", "Earlier.  Text here."),
        ("V3", "Hello there. Is it ok ?", "Earlier. Text here ."),
        ("V0", "Hello there. Is it ok?", "Earlier. Text here."),
    ])
    def test_variant_perturbs_prompt_and_prior_turns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variant: str, prompt: str, prior: str
    ) -> None:
        monkeypatch.setattr(loader, "load_golden", loader.load_golden)
        launcher = _load("run_evals_instrumented")
        path = _golden(tmp_path)
        launcher._install_perturbation(variant)
        c = loader.load_golden(path)[0]
        assert c["prompt"] == prompt
        assert c["prior_turns"][0]["content"] == prior
        assert c["prior_turns"][1]["content"] == 5  # non-string left alone

    def test_v3_leaves_unpunctuated_prompt_unchanged(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(loader, "load_golden", loader.load_golden)
        launcher = _load("run_evals_instrumented")
        launcher._install_perturbation("V3")
        assert loader.load_golden(_golden(tmp_path, "no terminal mark"))[0]["prompt"] == "no terminal mark"

    def test_patch_is_restored_by_monkeypatch_scope(self, tmp_path: Path) -> None:
        # runs after the installing tests: the original must be back in place
        assert loader.load_golden(_golden(tmp_path))[0]["prompt"] == "Hello there. Is it ok?"


# ---------------------------------------------------------------------------
# A2. progress
# ---------------------------------------------------------------------------


class TestProgress:
    def _result(self, cid: str) -> Any:
        return eval_types.CaseResult(case_id=cid, status=eval_types.CaseStatus.PASS)

    def test_off_writes_nothing(self, tmp_path: Path) -> None:
        sf = tmp_path / "status.jsonl"
        rep = eval_types.SuiteReport(suite="x")
        rep.results.append(self._result("a"))
        assert not sf.exists()

    def test_on_appends_one_line_per_result(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(eval_types.SuiteReport, "__init__", eval_types.SuiteReport.__init__)
        launcher = _load("run_evals_instrumented")
        sf = tmp_path / "sub" / "status.jsonl"
        launcher._install_progress(sf, "tagX")
        rep = eval_types.SuiteReport(suite="x")
        rep.results.append(self._result("a"))
        rep.results.append(self._result("b"))
        rows = _rows(sf)
        assert [(r["suite"], r["case"], r["status"], r["n"], r["tag"]) for r in rows] == [
            ("x", "a", "pass", 1, "tagX"), ("x", "b", "pass", 2, "tagX")]


# ---------------------------------------------------------------------------
# A3. io log
# ---------------------------------------------------------------------------


class _Gen:
    def __init__(self, text: str) -> None:
        self.text = text


class _Cls:
    label, confidence, error = "ALLOW", 0.9, None


class TestIoLog:
    def _fakes(self, monkeypatch: pytest.MonkeyPatch, text: str) -> tuple[Any, Any, Any]:
        from services.assistant_orchestrator.src.gpu_inference import OrchestratorGPUInference as AO
        from services.policy_agent.src.gpu_inference import CARPromptFormatter, ClassificationParser, PolicyGPUInference as PA

        monkeypatch.setattr(ClassificationParser, "parse", ClassificationParser.parse)  # restore the io-log wrapper at teardown
        monkeypatch.setattr(AO, "_generate_from_prompt", lambda self, prompt, *a, **k: _Gen(text))
        monkeypatch.setattr(PA, "classify_car", lambda self, car, *a, **k: _Cls())
        monkeypatch.setattr(CARPromptFormatter, "build_prompt", staticmethod(lambda car: f"PA:{car}"))
        return AO, PA, CARPromptFormatter

    def test_off_writes_no_rows(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        AO, PA, _ = self._fakes(monkeypatch, "hi")
        AO._generate_from_prompt(object(), "p")
        PA.classify_car(object(), "car")
        assert not (tmp_path / "io.jsonl").exists()

    @pytest.mark.parametrize("text,xml,js", [
        ("a <function=f> b", True, False),
        ("a <tool_call>{}</tool_call>", False, True),
        ("<tool_call>x <function=f>", True, False),
        ("plain", False, False),
    ])
    def test_ao_row_witnesses(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str, xml: bool, js: bool) -> None:
        AO, _, _ = self._fakes(monkeypatch, text)
        launcher = _load("run_evals_instrumented")
        log = tmp_path / "io.jsonl"
        launcher._install_io_log(log, "T")
        res = AO._generate_from_prompt(object(), "the prompt")
        assert res.text == text  # result passes through unchanged
        (row,) = _rows(log)
        assert row["kind"] == "ao" and row["tag"] == "T"
        assert row["prompt_sha"] == _sha("the prompt") and row["out_sha"] == _sha(text)
        assert row["xml_tool_call"] is xml and row["json_tool_call"] is js
        assert row["out_text"] == text

    def test_ao_out_text_truncated_to_4000(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        AO, _, _ = self._fakes(monkeypatch, "z" * 5000)
        launcher = _load("run_evals_instrumented")
        log = tmp_path / "io.jsonl"
        launcher._install_io_log(log, "T")
        AO._generate_from_prompt(object(), "p")
        (row,) = _rows(log)
        assert len(row["out_text"]) == 4000 and row["out_len"] == 5000

    def test_pa_row_has_hashes_and_no_out_text(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _, PA, _ = self._fakes(monkeypatch, "x")
        launcher = _load("run_evals_instrumented")
        log = tmp_path / "io.jsonl"
        launcher._install_io_log(log, "T")
        PA.classify_car(object(), "carX")
        (row,) = _rows(log)
        assert row["kind"] == "pa" and row["label"] == "ALLOW"
        assert row["prompt_sha"] == _sha("PA:carX")
        assert row["out_sha"] == _sha("ALLOW|0.9|None")
        assert "out_text" not in row

    def test_pa_raw_text_is_opt_in_and_parse_result_unchanged(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from services.policy_agent.src.gpu_inference import ClassificationParser

        _, PA, _ = self._fakes(monkeypatch, "x")
        raw = "DECISION: DENY CONFIDENCE: 0.95"

        def classify(self, car, *a, **k):  # type: ignore[no-untyped-def]
            ClassificationParser.parse(raw)
            return _Cls()

        monkeypatch.setattr(PA, "classify_car", classify)
        launcher = _load("run_evals_instrumented")
        monkeypatch.setenv("BLARAI_EVAL_PA_RAW", "1")
        log = tmp_path / "io.jsonl"
        launcher._install_io_log(log, "T")
        PA.classify_car(object(), "carX")
        (row,) = _rows(log)
        assert row["out_text"] == raw
        assert ClassificationParser.parse(raw) == "DENY"  # the wrapper passes the parse through

    def test_pa_raw_text_absent_without_the_opt_in(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from services.policy_agent.src.gpu_inference import ClassificationParser

        _, PA, _ = self._fakes(monkeypatch, "x")

        def classify(self, car, *a, **k):  # type: ignore[no-untyped-def]
            ClassificationParser.parse("DECISION: ALLOW")
            return _Cls()

        monkeypatch.setattr(PA, "classify_car", classify)
        monkeypatch.delenv("BLARAI_EVAL_PA_RAW", raising=False)
        launcher = _load("run_evals_instrumented")
        log = tmp_path / "io.jsonl"
        launcher._install_io_log(log, "T")
        PA.classify_car(object(), "carX")
        (row,) = _rows(log)
        assert "out_text" not in row


# ---------------------------------------------------------------------------
# A4/A5. report path + argparse
# ---------------------------------------------------------------------------


class TestLauncherArgs:
    def test_report_path_made_absolute(self) -> None:
        launcher = _load("run_evals_instrumented")
        a = launcher._absolutize_report_path(["--report", "x.json", "--suite", "s"])
        assert Path(a[1]).is_absolute() and a[1].endswith("x.json") and a[2:] == ["--suite", "s"]
        b = launcher._absolutize_report_path(["--report=x.json"])
        assert b[0].startswith("--report=") and Path(b[0].split("=", 1)[1]).is_absolute()

    def test_allow_abbrev_false_is_in_source(self) -> None:
        tree = ast.parse((SCRIPTS / "run_evals_instrumented.py").read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and getattr(n.func, "attr", "") == "ArgumentParser"]
        assert calls and all(any(k.arg == "allow_abbrev" and getattr(k.value, "value", None) is False
                                 for k in c.keywords) for c in calls)

    def test_main_does_not_abbreviate_engine_into_engine_summary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import evals.run as eval_run

        launcher = _load("run_evals_instrumented")
        seen: dict[str, Any] = {}
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(eval_run, "main", lambda rest: seen.setdefault("rest", rest) and 0)
        for name in ("_install_progress", "_install_perturbation", "_install_io_log", "_pin_marker"):
            monkeypatch.setattr(launcher, name, lambda *a, **k: None)
        monkeypatch.setattr(sys, "argv", ["x", "--engine", "cb-mtp-on", "--status-file", "s.jsonl",
                                          "--models-root", str(tmp_path), "--report", "r.json"])
        launcher.main()
        assert seen["rest"][:2] == ["--engine", "cb-mtp-on"]
        assert Path(seen["rest"][seen["rest"].index("--report") + 1]).is_absolute()
        # no engine summary was requested, so the end-of-run summary path never ran
        assert not list(tmp_path.glob("*summary*"))
        assert "job_done" in (tmp_path / "s.jsonl").read_text(encoding="utf-8")

    def test_abbreviating_parser_would_have_swallowed_engine(self) -> None:
        # control: the same parser WITH abbreviation set engine_summary, so the probe above can fail
        ap = argparse.ArgumentParser(add_help=False, allow_abbrev=True)
        ap.add_argument("--engine-summary", default=None)
        ours, rest = ap.parse_known_args(["--engine", "cb-mtp-on"])
        assert ours.engine_summary == "cb-mtp-on" and rest == []


# ---------------------------------------------------------------------------
# B. speed analyser
# ---------------------------------------------------------------------------


def _row(arm: str, genai: str, tps: float, ttft: float, visit: int = 0, rep: int = 0) -> dict[str, Any]:
    return {"arm": arm, "visit": visit, "cell": "pa", "protocol": "cold", "genai_version": genai,
            "openvino_version": "ov", "status": "ok", "rep": rep, "decode_tps": tps, "ttft_ms": ttft,
            "output_sha256": "h", "thermal_before": {"temp_c": 70.0}}


def _invocation(path: Path, scale: float) -> None:
    g14, g4 = "2026.2.1.0-3123-x", "2026.4.0.0-3407-x"
    rows = [_row("4b-mtp-off", g4, 30 * scale, 1000 * scale), _row("4b-mtp-on", g4, 60 * scale, 900 * scale),
            _row("14b-ship", g14, 10 * scale, 2000 * scale)]
    arms = [{"arm": r["arm"], "visit": 0, "genai_version": r["genai_version"], "peak_in_use_gb": 12.0} for r in rows]
    meta = {"uptime_h": 1.0, "thermal_at_start": {}, "gpu_driver": {"intel": []}, "baseline_in_use_gb": 8.0,
            "started": "s", "finished": "f"}
    path.write_text(json.dumps({"meta": meta, "arm_rounds": arms, "rows": rows, "summary": {}}), encoding="utf-8")


class TestSpeedAnalyser:
    def test_labels(self) -> None:
        s = _load("analyse_phase1_speed")
        assert s.label("14b-ship", "2026.2.1.0-3123-7dea0459b2a") == "14b-ship@2026.2.1"
        assert s.label("14b-ship", "2026.4.0.0-3407-x") == "14b-ship@2026.4"
        assert s.label("4b-mtp-on", "2026.2.1.0-3123-x") == "4b-mtp-on"
        assert s.runtime_name("2027.1.0.0-9-z") == "2027.1.0.0-9-z"

    def test_ratio_refusals_and_ok(self) -> None:
        s = _load("analyse_phase1_speed")
        good, other = s.stat([10.0, 10.2]), s.stat([5.0, 5.1])
        assert s.ratio(good, other)["ratio"] == round(good["mean"] / other["mean"], 3)
        noisy = s.stat([5.0, 9.0])  # CV far above 15%
        assert noisy["cv_pct"] > s.CV_LIMIT
        assert s.ratio(good, noisy)["ratio"] is None and s.ratio(noisy, good)["ratio"] is None
        assert s.ratio(good, s.stat([5.0]))["ratio"] is None  # n < 2

    def test_main_forms_4b_vs_14b_ratio_and_reports_missing_pairs(self, tmp_path: Path) -> None:
        s = _load("analyse_phase1_speed")
        _invocation(tmp_path / "A1-x.json", 1.0)
        _invocation(tmp_path / "A2-x.json", 1.05)
        out = tmp_path / "out.json"
        sys.argv, saved = ["x", "--dir", str(tmp_path), "--out", str(out)], sys.argv
        try:
            assert s.main() == 0
        finally:
            sys.argv = saved
        res = json.loads(out.read_text(encoding="utf-8"))
        key = "cold:pa:4b-mtp-on/14b-ship@2026.2.1"
        assert key in res["ratios"]
        assert res["ratios"][key]["decode_tps"]["ratio"] == pytest.approx(6.0, abs=0.05)
        assert "4b-mtp-on/4b-prefix-cache" in res["ratio_pairs_not_formed"]
        assert "14b-ship@2026.4/14b-ship@2026.2.1" in res["ratio_pairs_not_formed"]

    def test_mislabelled_14b_forms_no_pair(self, tmp_path: Path) -> None:
        # OFF side of the bug: a 14B on an unknown runtime label cannot pair with the 4B
        s = _load("analyse_phase1_speed")
        assert s.label("14b-ship", "2026.2.0.0-1-x") != "14b-ship@2026.2.1"


# ---------------------------------------------------------------------------
# C. quality analyser
# ---------------------------------------------------------------------------


def _report(path: Path, ids: list[str]) -> None:
    block = {"cases": [{"id": i, "status": "pass"} for i in ids], "aggregates": {"passed": len(ids)}}
    path.write_text(json.dumps({"suites": {"agentic": block, "conversation": block}}), encoding="utf-8")


def _io(path: Path, shas: list[str]) -> None:
    path.write_text("".join(json.dumps({"kind": "ao", "prompt_sha": s, "out_sha": s}) + "\n" for s in shas), encoding="utf-8")


class TestQualityAnalyser:
    def test_identity(self) -> None:
        q = _load("analyse_phase1_quality")
        a, b = [{"k": "1"}, {"k": "2"}], [{"k": "1"}, {"k": "9"}]
        assert q.identity([a], "k")["identical"] is None
        assert q.identity([a, list(a)], "k")["identical"] is True
        bad = q.identity([a, b], "k")
        assert bad["identical"] is False and bad["mismatched_calls"] == 1

    def test_is_scripted(self) -> None:
        q = _load("analyse_phase1_quality")
        assert q.is_scripted("ag-det-001") and not q.is_scripted("ag-tool-01")

    def test_prompts_changed(self) -> None:
        q = _load("analyse_phase1_quality")
        base = [{"prompt_sha": "a"}, {"prompt_sha": "b"}]
        assert q.prompts_changed(base, [{"prompt_sha": "a"}, {"prompt_sha": "b"}])["calls_with_changed_prompt"] == 0
        assert q.prompts_changed(base, [{"prompt_sha": "a"}, {"prompt_sha": "c"}])["calls_with_changed_prompt"] == 1

    def test_summarise_marks_unchanged_prompt_perturbation_not_measured(self, tmp_path: Path) -> None:
        q = _load("analyse_phase1_quality")
        for suite in ("agentic", "conversation"):
            for tag, shas in ((f"m-{suite}-pinned-V0-r1", ["a", "b"]), (f"m-{suite}-pinned-V1-r1", ["a", "b"]),
                              (f"m-{suite}-pinned-V2-r1", ["a", "z"])):
                _report(tmp_path / f"{tag}_report.json", ["ag-det-001", "ag-tool-01"])
                _io(tmp_path / f"{tag}_io.jsonl", shas)
        out = q.summarise_model(tmp_path, "m")
        pert = out["agentic"]["perturbation"]
        assert pert["V1"]["interpretation"].startswith("NOT MEASURED")
        assert pert["V1"]["prompts"]["calls_with_changed_prompt"] == 0
        assert "interpretation" not in pert["V2"] and pert["V2"]["prompts"]["calls_with_changed_prompt"] == 1
        assert out["agentic"]["pinned_marker_V0"]["input_identity"]["identical"] is None  # one repeat


# ---------------------------------------------------------------------------
# D. dataset sanitiser
# ---------------------------------------------------------------------------


class TestSanitise:
    def test_drops_detail_and_long_actual_keeps_short_label(self) -> None:
        b = _load("build_phase1_dataset")
        rep = {"suites": {"s": {"cases": [
            {"id": "1", "actual": "ALLOW", "detail": "model said x"},
            {"id": "2", "actual": "y" * 25, "detail": "d"},
            {"id": "3", "actual": "y" * 24},
        ]}}}
        cases = b.sanitise_report(rep)["suites"]["s"]["cases"]
        assert cases[0]["actual"] == "ALLOW" and "detail" not in cases[0]
        assert cases[1]["actual"] is None and "detail" not in cases[1]
        assert cases[2]["actual"] == "y" * 24


# ---------------------------------------------------------------------------
# E. CB empty generation
# ---------------------------------------------------------------------------


class _Cfg:
    num_assistant_tokens = 0
    assistant_confidence_threshold = -1.0


class _Sched:
    cache_size = 0
    max_num_seqs = 0
    enable_prefix_caching = None


def _fake_genai(monkeypatch: pytest.MonkeyPatch, ids: list[str]) -> None:
    class _Pipe:
        def __init__(self, path: str, sched: Any, device: str, props: dict[str, Any]) -> None:
            pass

        def generate(self, prompts: list[str], cfgs: list[Any], streamer: Any) -> list[Any]:
            return [types.SimpleNamespace(m_generation_ids=ids, perf_metrics=None, extended_perf_metrics=None)]

    fake = types.SimpleNamespace(__version__="f", SchedulerConfig=_Sched, GenerationConfig=_Cfg,
                                 ContinuousBatchingPipeline=_Pipe,
                                 StreamingStatus=types.SimpleNamespace(RUNNING="RUNNING"),
                                 draft_model=lambda p, d, **k: None)
    monkeypatch.setitem(sys.modules, "openvino_genai", fake)


class TestCBEmptyResult:
    def _dir(self, root: Path) -> Path:
        d = root / "q"
        d.mkdir()
        (d / "openvino_language_model.xml").write_text("<n/>", encoding="utf-8")
        return d

    def test_empty_generation_ids_raise(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _fake_genai(monkeypatch, [])
        p = CBEnginePipeline(self._dir(tmp_path), "cb-mtp-off")
        with pytest.raises(CBEngineError, match="no sequence"):
            p.generate("hi", generation_config=_Cfg())

    def test_nonempty_generation_ids_do_not_raise(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # toggle: the same call with a sequence present does not raise (the guard is the difference)
        _fake_genai(monkeypatch, ["ok"])
        p = CBEnginePipeline(self._dir(tmp_path), "cb-mtp-off")
        try:
            out = p.generate("hi", generation_config=_Cfg())
        except CBEngineError as exc:
            assert "no sequence" not in str(exc)
        else:
            assert str(out) == "ok"
        assert cb_pipeline.CBEngineError is CBEngineError
