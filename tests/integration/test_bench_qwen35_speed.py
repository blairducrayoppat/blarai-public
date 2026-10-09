"""Pure-function tests for scripts/bench_qwen35_speed.py (no openvino needed)."""

import importlib.util
import math
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "bench_qwen35_speed", Path(__file__).resolve().parents[2] / "scripts" / "bench_qwen35_speed.py"
)
b = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(b)


def test_describe_known_values():
    d = b.describe([10.0, 12.0, 14.0])
    assert d["n"] == 3 and d["mean"] == 12.0 and d["sd"] == 2.0
    assert d["cv_pct"] == round(2.0 / 12.0 * 100, 2)


def test_describe_single_and_empty():
    assert b.describe([5.0])["sd"] is None
    assert b.describe([])["n"] == 0


def test_mde_formula():
    assert b.min_detectable_effect([3.0, 4.0], 5) == round(
        2 * math.sqrt((9 + 16) / 2) / math.sqrt(5), 4
    )
    assert b.min_detectable_effect([None], 5) is None
    assert b.min_detectable_effect([1.0], 1) is None


def test_identity():
    assert b.identity_group(["a", "a"]) == {"n": 2, "identical": True, "n_distinct": 1}
    assert b.identity_group(["a", "b"])["identical"] is False
    assert b.cross_identity(["a", "a"], ["a"])["identical"] is True
    assert b.cross_identity(["a"], ["a", "b"])["identical"] is False


def test_ratio_refusal():
    ok = {"mean": 20.0, "cv_pct": 5.0}
    assert b.ratio_or_refuse(ok, {"mean": 10.0, "cv_pct": 5.0}) == {"ratio": 2.0, "status": "ok"}
    r = b.ratio_or_refuse(ok, {"mean": 10.0, "cv_pct": 15.01})
    assert r["ratio"] is None and r["status"] == "unstable: no ratio"
    assert b.ratio_or_refuse(ok, {"mean": 10.0, "cv_pct": None})["ratio"] is None


def _row(arm, cell, tps, ttft, h, status="ok", protocol="plateau", visit=0):
    return {"arm": arm, "cell": cell, "decode_tps": tps, "ttft_ms": ttft,
            "output_sha256": h, "status": status, "protocol": protocol, "visit": visit}


def test_summarize_excludes_invalid_and_compares_mtp():
    rows = [
        _row("4b-mtp-off", "pa", 20.0, 100.0, "h"), _row("4b-mtp-off", "pa", 20.2, 101.0, "h"),
        _row("4b-mtp-on", "pa", 40.0, 90.0, "h"), _row("4b-mtp-on", "pa", 40.4, 91.0, "h"),
        _row("4b-mtp-on", "pa", 1.0, 1.0, "zzz", status="invalid_mtp_not_engaged"),
        _row("4b-mtp-on", "heat", 1.0, 1.0, "zzz", status="heat"),
    ]
    s = b.summarize(rows)
    assert s["invalid_rows"] == 1 and s["heat_rows_excluded"] == 1
    p = s["protocols"]["plateau"]
    assert p["mtp_off_vs_on_identity"]["pa"]["identical"] is True
    assert p["per_arm_cell"]["4b-mtp-on"]["pa"]["decode_tps"]["n"] == 2
    assert "heat" not in p["per_arm_cell"]["4b-mtp-on"]
    assert p["ratios"]["4b-mtp-off/4b-mtp-on:pa"]["decode_tps"]["status"] == "ok"
    s2 = b.summarize(rows + [_row("4b-mtp-off", "pa", 60.0, 100.0, "h")])
    assert s2["protocols"]["plateau"]["ratios"]["4b-mtp-off/4b-mtp-on:pa"]["decode_tps"]["ratio"] is None


def test_protocols_never_mixed():
    rows = [
        _row("4b-mtp-off", "pa", 20.0, 100.0, "h", protocol="plateau"),
        _row("4b-mtp-off", "pa", 20.0, 100.0, "h", protocol="plateau"),
        _row("4b-mtp-off", "pa", 50.0, 40.0, "h2", protocol="cold"),
    ]
    s = b.summarize(rows)["protocols"]
    assert set(s) == {"plateau", "cold"}
    assert s["plateau"]["per_arm_cell"]["4b-mtp-off"]["pa"]["decode_tps"]["n"] == 2
    assert s["cold"]["per_arm_cell"]["4b-mtp-off"]["pa"]["decode_tps"]["mean"] == 50.0
    assert s["plateau"]["arm_output_identity"]["4b-mtp-off"]["identical"] is True


def test_per_visit_means_and_visit_cv():
    rows = [
        _row("4b-mtp-off", "pa", 20.0, 100.0, "h", visit=0), _row("4b-mtp-off", "pa", 22.0, 100.0, "h", visit=0),
        _row("4b-mtp-off", "pa", 10.0, 100.0, "h", visit=1), _row("4b-mtp-off", "pa", 12.0, 100.0, "h", visit=1),
    ]
    c = b.summarize(rows)["protocols"]["plateau"]["per_arm_cell"]["4b-mtp-off"]["pa"]
    assert c["per_visit_mean_decode_tps"] == {"0": 21.0, "1": 11.0}
    assert c["visit_cv_pct_decode_tps"] == b.describe([21.0, 11.0])["cv_pct"]


def test_plateau_reached():
    flat = [160.0, 161.0, 159.0, 160.0]
    assert b.plateau_reached([48.0] * 3 + flat) is False  # only 7 generations
    assert b.plateau_reached([48.0, 60, 90, 120] + flat) is True
    assert b.plateau_reached([48.0, 60, 90, 120, 140, 150, 155, 160]) is False  # tail still rising
    assert b.plateau_reached([100.0] * 8 + [100.0, 100.0, 100.0, 106.0]) is True  # 4.4% off mean: within 5%
    assert b.plateau_reached([100.0] * 8 + [100.0, 100.0, 100.0, 120.0]) is False
    assert b.plateau_reached([None, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0]) is False


class _Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_cold_wait_reaches_target():
    clk = _Clock()
    temps = iter([70.0, 62.0, 55.0, 50.0])
    r = b.wait_for_cold(lambda: {"temp_c": next(temps)}, 52.0, 180.0, clock=clk.now, sleep=clk.sleep, poll_s=5.0)
    assert r == {"waited_s": 15.0, "temp_c": 50.0, "reached": True, "measured": True}


def test_cold_wait_times_out():
    clk = _Clock()
    r = b.wait_for_cold(lambda: {"temp_c": 70.0}, 50.0, 20.0, clock=clk.now, sleep=clk.sleep, poll_s=5.0)
    assert r["reached"] is False and r["temp_c"] == 70.0 and r["waited_s"] >= 20.0


def test_cold_wait_unmeasured_returns_immediately():
    clk = _Clock()
    r = b.wait_for_cold(lambda: {}, 50.0, 180.0, clock=clk.now, sleep=clk.sleep)
    assert r["measured"] is False and r["reached"] is None and clk.t == 0.0


def test_multiturn_prompts_grow_and_nest():
    p = b.build_multiturn_prompts()
    assert len(p) == b.MULTITURN_TURNS
    for prev, nxt in zip(p, p[1:]):
        assert len(nxt) > len(prev)
    assert p[0].endswith(b.EMPTY_THINK)
