"""The post-hoc exploratory block of scripts/analyse_phase1_speed.py (#1665).

The pre-registered rule (a ratio is refused when either arm's visit-mean CV > 15%) must stay
untouched; the exploratory block only adds medians, outlier counts and per-visit values beside it.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
G_NEW, G_SHIP = "2026.4.0.0-3407-x", "2026.2.1.0-3123-x"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("analyse_phase1_speed", ROOT / "scripts" / "analyse_phase1_speed.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write(path: Path, rows_by_visit: dict[str, list[tuple[float, float]]], cell: str = "pa") -> None:
    """One invocation file; each arm gets one visit per (tps, ttft) pair."""
    rows, rounds = [], []
    for arm, vals in rows_by_visit.items():
        genai = G_SHIP if arm == "14b-ship" else G_NEW
        for v, (tps, ttft) in enumerate(vals):
            rows.append({"t": f"2026-10-04T12:{v:02d}:00-04:00", "arm": arm, "visit": v, "cell": cell,
                         "protocol": "cold", "genai_version": genai, "status": "ok", "rep": 0,
                         "decode_tps": tps, "ttft_ms": ttft, "output_sha256": "h",
                         "thermal_before": {"temp_c": 70.0}})
            rounds.append({"arm": arm, "visit": v, "genai_version": genai, "peak_in_use_gb": 12.0})
    meta = {"uptime_h": 1.0, "thermal_at_start": {}, "gpu_driver": {"intel": []}, "baseline_in_use_gb": 8.0,
            "started": "s", "finished": "f"}
    path.write_text(json.dumps({"meta": meta, "arm_rounds": rounds, "rows": rows, "summary": {}}), encoding="utf-8")


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, files: dict[str, dict[str, list[tuple[float, float]]]]) -> dict[str, Any]:
    for name, rows in files.items():
        _write(tmp_path / name, rows)
    out = tmp_path / "out.json"
    monkeypatch.setattr(sys, "argv", ["x", "--dir", str(tmp_path), "--out", str(out)])
    assert _load().main() == 0
    return json.loads(out.read_text(encoding="utf-8"))


# 9b-mtp-on: three steady visits and one slow one (CV far above 15%); 14b-ship is steady.
NOISY = {"9b-mtp-on": [(22.0, 1000.0), (22.5, 1010.0), (23.0, 990.0), (7.0, 3000.0)],
         "14b-ship": [(10.0, 2000.0), (10.1, 2010.0), (9.9, 1990.0), (10.0, 2000.0)]}


class TestExploratoryBlock:
    def test_preregistered_ratio_stays_refused_and_median_ratio_is_correct(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        res = _run(tmp_path, monkeypatch, {"A1-x.json": NOISY})
        pre = res["ratios"]["cold:pa:9b-mtp-on/14b-ship@2026.2.1"]
        assert pre["decode_tps"] == {"ratio": None, "status": "refused: n<2 or CV>15% on a side"}
        assert pre["ttft_ms"]["ratio"] is None
        exp = res["exploratory"]["exploratory_median_ratios"]["cold:pa:9b-mtp-on/14b-ship@2026.2.1"]["decode_tps"]
        # medians: 9b (7.0, 22.0, 22.5, 23.0) -> 22.25 ; 14b -> 10.0
        assert exp["ratio"] == pytest.approx(2.225, abs=0.001)
        assert (exp["n_num"], exp["n_den"], exp["outliers_num"], exp["outliers_den"]) == (4, 4, 1, 0)
        assert exp["status"] == "exploratory, not pre-registered; the pre-registered rule refused the mean-based ratio"

    def test_ratio_that_the_rule_accepted_gets_no_exploratory_entry(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        steady = {"9b-mtp-on": [(22.0, 1000.0), (22.5, 1010.0)], "14b-ship": [(10.0, 2000.0), (10.1, 2010.0)]}
        res = _run(tmp_path, monkeypatch, {"A1-x.json": steady})
        assert res["ratios"]["cold:pa:9b-mtp-on/14b-ship@2026.2.1"]["decode_tps"]["ratio"] is not None
        assert "cold:pa:9b-mtp-on/14b-ship@2026.2.1" not in res["exploratory"]["exploratory_median_ratios"]

    def test_outlier_count_direction_and_visit_values(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        res = _run(tmp_path, monkeypatch, {"A1-x.json": NOISY})
        cell = res["exploratory"]["per_protocol_cell_arm"]["cold"]["pa"]["9b-mtp-on"]
        d, t = cell["decode_tps"], cell["ttft_ms"]
        assert (d["n"], d["median"], d["min"], d["max"], d["slow_outlier_visits"]) == (4, 22.25, 7.0, 23.0, 1)
        # TTFT is lower-is-better: the 3000 ms visit is the slow one
        assert (t["median"], t["slow_outlier_visits"]) == (1005.0, 1)
        slow = [v for v in d["visit_means"] if v["slow_outlier"]]
        assert [(v["invocation"], v["visit"], v["value"], v["t"]) for v in slow] == [("A1-x", 3, 7.0, "2026-10-04T12:03:00-04:00")]
        assert cell["decode_tps"]["slow_outlier_visits"] == 1 and res["exploratory"]["per_protocol_cell_arm"]["cold"]["pa"]["14b-ship@2026.2.1"]["decode_tps"]["slow_outlier_visits"] == 0

    def test_exploratory_notes_say_post_hoc_not_a_finding(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        res = _run(tmp_path, monkeypatch, {"A1-x.json": NOISY})
        text = " ".join(res["exploratory"]["notes"])
        assert "POST-HOC" in text and "must not be quoted as a finding" in text

    def test_every_preexisting_key_is_unchanged_by_the_exploratory_block(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        res = _run(tmp_path, monkeypatch, {"A1-x.json": NOISY})
        assert set(res) == {"memory_in_use_total_minus_available", "unit_of_analysis", "cv_limit_pct", "per_protocol_cell_arm",
                            "ratios", "ratio_pairs_not_formed", "notes", "mtp_witness", "thermal", "plateau_and_memory",
                            "invocations", "arm_errors", "invalid_rows", "exploratory", "cold_gate_not_reached", "cold_gate_note", "cold_gate_operationalisation_note", "cold_gate_kept_rows_started_above_limit"}
        assert res["cv_limit_pct"] == 15.0
        assert res["per_protocol_cell_arm"]["cold"]["pa"]["9b-mtp-on"]["decode_tps_visit_means"]["n"] == 4


def _set_cold_wait(path: Path, arm: str, visit: int, cw: dict[str, Any] | None) -> None:
    d = json.loads(path.read_text(encoding="utf-8"))
    for r in d["rows"]:
        if r["arm"] == arm and r["visit"] == visit:
            if cw is None:
                r.pop("cold_wait", None)
            else:
                r["cold_wait"] = cw
    path.write_text(json.dumps(d), encoding="utf-8")


def _gate_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, include: bool, cw: dict[str, Any] | None) -> dict[str, Any]:
    vals = {"9b-mtp-on": [(22.0, 1000.0), (22.5, 1010.0), (23.0, 990.0), (7.0, 3000.0)],
            "14b-ship": [(10.0, 2000.0), (10.1, 2010.0), (9.9, 1990.0), (10.0, 2000.0)]}
    _write(tmp_path / "A1-x.json", vals)
    _set_cold_wait(tmp_path / "A1-x.json", "9b-mtp-on", 3, cw)
    out = tmp_path / "out.json"
    argv = ["x", "--dir", str(tmp_path), "--out", str(out)] + (["--include-gate-failures"] if include else [])
    monkeypatch.setattr(sys, "argv", argv)
    assert _load().main() == 0
    return json.loads(out.read_text(encoding="utf-8"))


NOT_REACHED = {"waited_s": 182.0, "temp_c": 80.1, "reached": False, "measured": True}


class TestColdGateExclusion:
    def test_not_reached_row_is_excluded_listed_and_ratio_follows(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        res = _gate_run(tmp_path, monkeypatch, False, NOT_REACHED)
        st = res["per_protocol_cell_arm"]["cold"]["pa"]["9b-mtp-on"]["decode_tps_visit_means"]
        assert st["n"] == 3 and st["min"] == 22.0
        listed = res["cold_gate_not_reached"]
        assert [(x["file"], x["arm"], x["visit"], x["cell"], x["decode_tps"], x["waited_s"], x["temp_c_after_wait"]) for x in listed] == \
            [("A1-x.json", "9b-mtp-on", 3, "pa", 7.0, 182.0, 80.1)]
        # with the slow visit gone the mean-based ratio is no longer refused
        assert res["ratios"]["cold:pa:9b-mtp-on/14b-ship@2026.2.1"]["decode_tps"]["ratio"] is not None
        assert "EXCLUDED" in res["cold_gate_note"]

    def test_include_flag_restores_the_row(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        res = _gate_run(tmp_path, monkeypatch, True, NOT_REACHED)
        assert res["per_protocol_cell_arm"]["cold"]["pa"]["9b-mtp-on"]["decode_tps_visit_means"]["n"] == 4
        assert res["ratios"]["cold:pa:9b-mtp-on/14b-ship@2026.2.1"]["decode_tps"]["ratio"] is None
        assert len(res["cold_gate_not_reached"]) == 1 and "INCLUDED" in res["cold_gate_note"]

    def test_row_without_cold_wait_and_reached_true_are_kept(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        for cw in (None, {"waited_s": 1.0, "temp_c": 70.0, "reached": True}):
            sub = tmp_path / str(cw is None)
            sub.mkdir()
            res = _gate_run(sub, monkeypatch, False, cw)
            assert res["per_protocol_cell_arm"]["cold"]["pa"]["9b-mtp-on"]["decode_tps_visit_means"]["n"] == 4
            assert res["cold_gate_not_reached"] == []
