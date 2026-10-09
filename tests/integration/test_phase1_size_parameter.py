"""
#1663 Phase 1 harness, generalised over the Qwen3.5 size (4b / 9b).

Locks: an arm's name picks that arm's OWN model directory and engine; the analysers
form every size's ratio pairs from the sizes present and name every pair they cannot
form; 4b-only data still yields the Phase 1 pairs; the dataset builder maps each
quality directory to its own model name. CPU-only; the OpenVINO boundary is faked.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import types
from pathlib import Path
from typing import Any

import pytest

# Imported BEFORE any test installs a fake openvino_genai (see test_eval_cb_engine).
import shared.inference.shared_pipeline  # noqa: F401
from evals.cb_pipeline import CBEnginePipeline  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
G_NEW, G_SHIP = "2026.4.0.0-3407-x", "2026.2.1.0-3123-x"


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# (a) an arm name resolves to its own size's directory and engine
# ---------------------------------------------------------------------------


class _Cfg:
    num_assistant_tokens = 0
    assistant_confidence_threshold = -1.0


class _Sched:
    cache_size = 0
    max_num_seqs = 0
    enable_prefix_caching = None


def _fake_genai(monkeypatch: pytest.MonkeyPatch, loaded: list[str]) -> None:
    class _Pipe:
        def __init__(self, path: str, sched: Any, device: str, props: dict[str, Any]) -> None:
            loaded.append(path)

        def get_tokenizer(self) -> str:
            return "tok"

    fake = types.SimpleNamespace(__version__="f", SchedulerConfig=_Sched, GenerationConfig=_Cfg,
                                 ContinuousBatchingPipeline=_Pipe,
                                 StreamingStatus=types.SimpleNamespace(RUNNING="RUNNING"),
                                 draft_model=lambda p, d, **k: None)
    monkeypatch.setitem(sys.modules, "openvino_genai", fake)


def _model_dir(root: Path, name: str, mtp: bool) -> Path:
    d = root / name
    d.mkdir()
    (d / "openvino_language_model.xml").write_text("<n/>", encoding="utf-8")
    if mtp:
        (d / "openvino_mtp_model.xml").write_text("<n/>", encoding="utf-8")
    return d


class TestArmResolvesOwnSize:
    def _args(self, tmp_path: Path) -> argparse.Namespace:
        # the 4b directory has NO mtp head: a 9b-mtp-on arm that wrongly took it would raise
        return argparse.Namespace(model_4b=str(_model_dir(tmp_path, "m4b", mtp=False)),
                                  model_9b=str(_model_dir(tmp_path, "m9b", mtp=True)),
                                  model_14b="unused", models_root="unused")

    def test_9b_arm_loads_the_9b_dir_and_engine(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        bench = _load("bench_qwen35_speed")
        loaded: list[str] = []
        _fake_genai(monkeypatch, loaded)
        args = self._args(tmp_path)
        arm = bench.load_arm("9b-mtp-on", args)
        assert arm.name == "9b-mtp-on"
        assert arm.header["model_dir"] == args.model_9b != args.model_4b
        assert arm.header["engine"] == "cb-mtp-on"
        assert loaded == [args.model_9b]

    def test_every_variant_pairs_with_its_own_engine_and_size(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        bench = _load("bench_qwen35_speed")
        args = self._args(tmp_path)
        for size, variant, engine in (("9b", "mtp-off", "cb-mtp-off"), ("9b", "prefix-cache", "cb-prefix-cache"),
                                      ("4b", "mtp-off", "cb-mtp-off"), ("4b", "prefix-cache", "cb-prefix-cache")):
            loaded: list[str] = []
            _fake_genai(monkeypatch, loaded)
            arm = bench.load_arm(f"{size}-{variant}", args)
            assert arm.header["engine"] == engine
            assert arm.header["model_dir"] == getattr(args, f"model_{size}")
            assert loaded == [getattr(args, f"model_{size}")]

    def test_unknown_size_is_refused_not_defaulted(self) -> None:
        sizes = _load("phase1_sizes")
        assert sizes.parse_arm("7b-mtp-on") is None
        with pytest.raises(KeyError):
            sizes.model_dir_for("7b-mtp-on", argparse.Namespace(model_4b="a", model_9b="b"))
        bench = _load("bench_qwen35_speed")
        assert "9b-mtp-on" in bench.KNOWN_ARMS and "7b-mtp-on" not in bench.KNOWN_ARMS

    def test_parse_args_resolves_both_model_flags(self, tmp_path: Path) -> None:
        bench = _load("bench_qwen35_speed")
        a = bench.parse_args(["--out", str(tmp_path / "o.json"), "--protocol", "plateau", "--model-9b", str(tmp_path / "x9")])
        assert Path(a.model_9b) == (tmp_path / "x9").resolve()
        assert Path(a.model_4b).name == "Qwen3.5-4B-int8-ov"

    def test_summarize_keeps_4b_key_and_labels_9b_identity_by_size(self) -> None:
        bench = _load("bench_qwen35_speed")

        def row(arm: str, h: str) -> dict[str, Any]:
            return {"arm": arm, "cell": "pa", "decode_tps": 30.0, "ttft_ms": 100.0, "output_sha256": h,
                    "status": "ok", "protocol": "cold", "visit": 0}

        s9 = bench.summarize([row("9b-mtp-off", "h"), row("9b-mtp-on", "h")])["protocols"]["cold"]
        assert s9["mtp_off_vs_on_identity"] == {}  # nothing was measured for 4b: no 9b data under the 4b key
        assert s9["mtp_off_vs_on_identity_9b"]["pa"]["identical"] is True
        s4 = bench.summarize([row("4b-mtp-off", "h"), row("4b-mtp-on", "h")])["protocols"]["cold"]
        assert s4["mtp_off_vs_on_identity"]["pa"]["identical"] is True
        assert not [k for k in s4 if k.endswith("_9b")]


# ---------------------------------------------------------------------------
# (b)/(c) speed analyser ratio pairs
# ---------------------------------------------------------------------------


def _row(arm: str, genai: str, tps: float, ttft: float) -> dict[str, Any]:
    return {"arm": arm, "visit": 0, "cell": "pa", "protocol": "cold", "genai_version": genai,
            "openvino_version": "ov", "status": "ok", "rep": 0, "decode_tps": tps, "ttft_ms": ttft,
            "output_sha256": "h", "thermal_before": {"temp_c": 70.0}}


def _invocation(path: Path, arms: dict[str, tuple[str, float, float]], scale: float) -> None:
    rows = [_row(a, g, tps * scale, ttft * scale) for a, (g, tps, ttft) in arms.items()]
    arm_rounds = [{"arm": r["arm"], "visit": 0, "genai_version": r["genai_version"], "peak_in_use_gb": 12.0} for r in rows]
    meta = {"uptime_h": 1.0, "thermal_at_start": {}, "gpu_driver": {"intel": []}, "baseline_in_use_gb": 8.0,
            "started": "s", "finished": "f"}
    path.write_text(json.dumps({"meta": meta, "arm_rounds": arm_rounds, "rows": rows, "summary": {}}), encoding="utf-8")


def _analyse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arms: dict[str, tuple[str, float, float]]) -> dict[str, Any]:
    s = _load("analyse_phase1_speed")
    _invocation(tmp_path / "A1-x.json", arms, 1.0)
    _invocation(tmp_path / "A2-x.json", arms, 1.05)
    out = tmp_path / "out.json"
    monkeypatch.setattr(sys, "argv", ["x", "--dir", str(tmp_path), "--out", str(out)])
    assert s.main() == 0
    return json.loads(out.read_text(encoding="utf-8"))


SHIP14 = ("14b-ship", (G_SHIP, 10.0, 2000.0))


class TestSpeedAnalyserSizes:
    def test_9b_pairs_formed_and_unformable_pair_named(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        res = _analyse(tmp_path, monkeypatch, {"9b-mtp-off": (G_NEW, 20.0, 1500.0), "9b-mtp-on": (G_NEW, 50.0, 1400.0),
                                               SHIP14[0]: SHIP14[1]})
        assert res["ratios"]["cold:pa:9b-mtp-on/9b-mtp-off"]["decode_tps"]["ratio"] == pytest.approx(2.5, abs=0.05)
        assert res["ratios"]["cold:pa:9b-mtp-on/14b-ship@2026.2.1"]["decode_tps"]["ratio"] == pytest.approx(5.0, abs=0.05)
        assert "cold:pa:9b-mtp-off/14b-ship@2026.2.1" in res["ratios"]
        # the denominator arm 9b-prefix-cache was never run: the pair is named, not skipped
        assert res["ratio_pairs_not_formed"]["9b-mtp-on/9b-prefix-cache"] == ["cold:pa"]
        assert "9b-prefix-cache/9b-mtp-off" in res["ratio_pairs_not_formed"]
        # a 9b-only dataset never carries a 4b label anywhere
        everything = json.dumps(res["ratios"]) + json.dumps(res["ratio_pairs_not_formed"]) + json.dumps(res["per_protocol_cell_arm"])
        assert not re.search(r"(?<!1)4b-", everything)
        notes = " ".join(res["notes"])
        # only two 9b arms ran: the note names those two, never "the three 9B arms", and no 4B arm at all
        assert "the two 9B arms that ran (9b-mtp-off, 9b-mtp-on)" in notes and "three" not in notes and "4B arm" not in notes
        assert "Cache arms (14b-ship)" in notes and "9b-prefix-cache" not in notes

    def test_cross_size_pairs_formed_when_both_sizes_present(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        res = _analyse(tmp_path, monkeypatch, {"4b-mtp-on": (G_NEW, 60.0, 900.0), "9b-mtp-on": (G_NEW, 30.0, 1400.0),
                                               "9b-mtp-off": (G_NEW, 12.0, 1500.0), SHIP14[0]: SHIP14[1]})
        assert res["ratios"]["cold:pa:9b-mtp-on/4b-mtp-on"]["decode_tps"]["ratio"] == pytest.approx(0.5, abs=0.02)
        # 4b-mtp-off was not run: the cross-size off/off pair is named, not skipped
        assert res["ratio_pairs_not_formed"]["9b-mtp-off/4b-mtp-off"] == ["cold:pa"]

    def test_cross_size_pairs_absent_with_one_size(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        res = _analyse(tmp_path, monkeypatch, {"9b-mtp-on": (G_NEW, 30.0, 1400.0)})
        assert not any("9b-mtp-on/4b" in k for k in list(res["ratios"]) + list(res["ratio_pairs_not_formed"]))

    def test_4b_only_data_yields_the_phase1_pairs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        sizes = _load("phase1_sizes")
        assert sizes.ratio_pairs(["4b"]) == [
            ("4b-mtp-on", "4b-mtp-off"), ("4b-prefix-cache", "4b-mtp-off"), ("4b-mtp-on", "4b-prefix-cache"),
            ("4b-mtp-off", "14b-ship@2026.2.1"), ("4b-mtp-on", "14b-ship@2026.2.1"),
            ("14b-ship@2026.4", "14b-ship@2026.2.1"),
        ]
        res = _analyse(tmp_path, monkeypatch, {"4b-mtp-off": (G_NEW, 30.0, 1000.0), "4b-mtp-on": (G_NEW, 60.0, 900.0),
                                               SHIP14[0]: SHIP14[1]})
        assert set(res["ratios"]) == {"cold:pa:4b-mtp-on/4b-mtp-off", "cold:pa:4b-mtp-off/14b-ship@2026.2.1",
                                      "cold:pa:4b-mtp-on/14b-ship@2026.2.1"}
        assert set(res["ratio_pairs_not_formed"]) == {"4b-prefix-cache/4b-mtp-off", "4b-mtp-on/4b-prefix-cache",
                                                      "14b-ship@2026.4/14b-ship@2026.2.1"}
        assert res["ratios"]["cold:pa:4b-mtp-on/14b-ship@2026.2.1"]["decode_tps"]["ratio"] == pytest.approx(6.0, abs=0.05)
        notes = " ".join(res["notes"])
        assert "the two 4B arms that ran (4b-mtp-off, 4b-mtp-on)" in notes and "the 4B tokenizer's" in notes
        assert "Cache arms (14b-ship)" in notes and "4b-prefix-cache" not in notes

    def test_cache_arm_ttft_policy_covers_every_size(self) -> None:
        s = _load("analyse_phase1_speed")
        assert {"4b-prefix-cache", "9b-prefix-cache", "14b-ship"} == s.CACHE_ARMS


class TestTtftAnalyserSizes:
    def _rows(self, arm: str, base: float) -> list[dict[str, Any]]:
        return [{"arm": arm, "turn": t, "visit": v, "ttft_ms": base * (1 + 0.01 * v), "tpot_ms": 20.0, "input_tokens": 100 * t,
                 "reply_sha256": f"r{t}", "thermal_before": {"temp_c": 60.0}} for t in range(1, 7) for v in range(3)]

    def test_9b_pairs_and_unformable_named(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        t = _load("analyse_phase1_ttft")
        rows = self._rows("9b-mtp-on", 400.0) + self._rows("9b-mtp-off", 800.0) + self._rows("4b-mtp-on", 200.0)
        f = tmp_path / "in.json"
        f.write_text(json.dumps({"meta": {"genai": G_NEW}, "rows": rows}), encoding="utf-8")
        out = tmp_path / "o.json"
        monkeypatch.setattr(sys, "argv", ["x", "--in", str(f), "--out", str(out)])
        assert t.main() == 0
        res = json.loads(out.read_text(encoding="utf-8"))
        assert res["ttft_ratios"]["t1:9b-mtp-on/9b-mtp-off"]["ratio"] == pytest.approx(0.5, abs=0.01)
        assert res["ttft_ratios"]["t1:9b-mtp-on/4b-mtp-on"]["ratio"] == pytest.approx(2.0, abs=0.01)
        assert res["ratio_pairs_not_formed"]["9b-mtp-on/14b-ship"][0] == "t1"
        assert res["reply_identity"]["t1"]["9b_arms_agree"] is True
        assert res["reply_identity"]["t1"]["four_b_arms_agree"] is True


# ---------------------------------------------------------------------------
# campaigns
# ---------------------------------------------------------------------------


class TestCampaigns:
    def test_quality_target_names_its_own_dir_and_engine(self) -> None:
        c = _load("run_phase1_campaign")
        py, args = c.target_args("9b-on")
        assert args[args.index("--model-dir") + 1].endswith("Qwen3.5-9B-int8-ov")
        assert args[args.index("--engine") + 1] == "cb-mtp-on"
        _, args4 = c.target_args("4b-off")
        assert args4[args4.index("--model-dir") + 1].endswith("Qwen3.5-4B-int8-ov")
        assert args4[args4.index("--engine") + 1] == "cb-mtp-off"
        _, args9 = c.target_args("9b-off", Path("X:/other"))
        assert args9[args9.index("--model-dir") + 1] == str(Path("X:/other"))
        with pytest.raises(SystemExit):
            c.target_args("7b-on")

    def test_quality_dry_run_per_size(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        c = _load("run_phase1_campaign")
        monkeypatch.setattr(sys, "argv", ["x", "--model", "9b-on", "--out-dir", str(tmp_path / "o"),
                                          "--status-file", str(tmp_path / "s.jsonl"), "--dry-run"])
        assert c.main() == 0
        out = capsys.readouterr().out
        assert "Qwen3.5-9B-int8-ov" in out and "cb-mtp-on" in out and "Qwen3.5-4B" not in out
        assert "9b-on-all-random-r1" in out and not re.search(r"(?<!1)4b-", out)

    def test_speed_default_orders_unchanged(self) -> None:
        c = _load("run_phase1_speed_campaign")
        assert c.ORDERS == [
            ["4b-mtp-off", "4b-mtp-on", "4b-prefix-cache", "14b-ship", "4b-mtp-off"],
            ["4b-mtp-on", "4b-prefix-cache", "14b-ship", "4b-mtp-off", "4b-mtp-on"],
            ["4b-prefix-cache", "14b-ship", "4b-mtp-off", "4b-mtp-on", "4b-prefix-cache"],
            ["14b-ship", "4b-mtp-off", "4b-mtp-on", "4b-prefix-cache", "14b-ship"],
        ]

    def test_speed_9b_orders_rotate_with_reference_and_aba(self) -> None:
        c = _load("run_phase1_speed_campaign")
        orders = c.build_orders(["9b"], ["4b-mtp-on"])
        base = ["9b-mtp-off", "9b-mtp-on", "9b-prefix-cache", "4b-mtp-on", "14b-ship"]
        assert len(orders) == 5
        for i, o in enumerate(orders):
            assert o[:-1] == base[i:] + base[:i] and o[-1] == o[0] and sorted(o[:-1]) == sorted(base)

    def test_speed_dry_run_9b(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        c = _load("run_phase1_speed_campaign")
        monkeypatch.setattr(sys, "argv", ["x", "--out-dir", str(tmp_path / "o"), "--status-file", str(tmp_path / "s.jsonl"),
                                          "--sizes", "9b", "--reference", "4b-mtp-on", "--dry-run"])
        assert c.main() == 0
        lines = capsys.readouterr().out.splitlines()
        assert len(lines) == 10 and lines[0].startswith("A1-2026.4") and "9b-mtp-off" in lines[0]
        assert all("'4b-mtp-off'" not in ln and "4b-prefix-cache" not in ln for ln in lines)
        assert lines[1].startswith("B1-2026.2.1") and "'14b-ship'" in lines[1]

    def test_speed_rejects_unknown_size_and_reference(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        c = _load("run_phase1_speed_campaign")
        for extra in (["--sizes", "7b"], ["--reference", "14b-ship"]):
            monkeypatch.setattr(sys, "argv", ["x", "--out-dir", str(tmp_path / "o"), "--status-file", str(tmp_path / "s"),
                                              "--dry-run", *extra])
            with pytest.raises(SystemExit):
                c.main()


# ---------------------------------------------------------------------------
# (d) dataset builder
# ---------------------------------------------------------------------------


def _quality_report(path: Path) -> None:
    case = {"id": "c1", "status": "pass", "actual": "ALLOW", "detail": "model said something"}
    block = {"cases": [case], "aggregates": {"passed": 1, "failed": 0, "errors": 0, "skipped_hardware": 0, "evaluated": 1, "total": 1}}
    path.write_text(json.dumps({"suites": {"agentic": block}}), encoding="utf-8")


class TestDatasetBuilder:
    def _build(self, tmp_path: Path) -> tuple[Path, Any]:
        b = _load("build_phase1_dataset")
        run = tmp_path / "run"
        (run / "speed").mkdir(parents=True)
        _invocation(run / "speed" / "A1-2026.4.json", {"9b-mtp-on": (G_NEW, 30.0, 1400.0)}, 1.0)
        for d in ("q9b_on", "q9b_off", "q4b_on", "q14b"):
            (run / d).mkdir()
            _quality_report(run / d / f"{d[1:].replace('_', '-')}-all-random-r1_report.json")
        (run / "q9b_on_summary.json").write_text('{"dir": "C:/Users/mrbla/x"}', encoding="utf-8")
        out = tmp_path / "out"
        return out, (b, run)

    def test_q9b_dirs_map_to_9b_model_names(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        out, (b, run) = self._build(tmp_path)
        monkeypatch.setattr(sys, "argv", ["x", "--out", str(out), "--run-dir", str(run)])
        assert b.main() == 0
        import csv

        rows = list(csv.DictReader(open(out / "quality_runs.csv", encoding="utf-8")))
        by_job = {r["job"]: r["model"] for r in rows}
        assert by_job == {"9b-on-all-random-r1": "qwen3.5-9b-int8+mtp", "9b-off-all-random-r1": "qwen3.5-9b-int8",
                          "4b-on-all-random-r1": "qwen3.5-4b-int8+mtp", "14b-all-random-r1": "qwen3-14b-int4+draft"}
        speed = list(csv.DictReader(open(out / "speed_rows.csv", encoding="utf-8")))
        assert {r["arm"] for r in speed} == {"9b-mtp-on"}
        # size-keyed summary copied, user name sanitised, generated text dropped
        copied = (out / "raw" / "q9b_on_summary.json").read_text(encoding="utf-8")
        assert "mrbla" not in copied and "<user>" in copied
        rep = (out / "raw/quality/9b-on-all-random-r1_report.json").read_text(encoding="utf-8")
        assert "model said something" not in rep

    def test_registry_names_are_size_keyed(self) -> None:
        sizes = _load("phase1_sizes")
        assert sizes.dataset_quality_dirs() == {
            "q4b_on": "qwen3.5-4b-int8+mtp", "q4b_off": "qwen3.5-4b-int8",
            "q9b_on": "qwen3.5-9b-int8+mtp", "q9b_off": "qwen3.5-9b-int8", "q14b": "qwen3-14b-int4+draft"}
        assert {"q9b_on_summary.json", "q9b_off_summary.json", "q4b_on_summary.json"} <= set(sizes.dataset_summary_files())
        assert sizes.quality_models() == ("4b-on", "4b-off", "9b-on", "9b-off", "14b")
