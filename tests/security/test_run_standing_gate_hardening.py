"""The holes the independent review found in scripts/run_standing_gate.py (#1707), each with a lock that fails when
the fix is removed: a file pytest skips while collecting, the fixed-port tail, teardown errors, marker selection,
a collection error, a group exit code that disagrees with its counts, a spoofed summary line, a hung group, a
corrupt weights file, and the balance of a heavy file.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import run_standing_gate as g  # noqa: E402


def _tree(tmp: Path, files: dict[str, str]) -> Path:
    t = tmp / "tree"
    t.mkdir()
    for name, body in files.items():
        (t / name).write_text(body, encoding="utf-8")
    return t


def _run(tree: Path, tmp: Path, capsys: pytest.CaptureFixture, *extra: str) -> tuple[int, str]:
    rc = g.main(["--cwd", str(tree), "--python", sys.executable, "--roots", ".", "--logdir", str(tmp / "logs"),
                 "--weights", str(tmp / "none.json"), *extra])
    return rc, capsys.readouterr().out


PASS = "def test_ok():\n    pass\n"


# ------------------------------------------------------------ collection-time skips are neither dropped nor hidden

def test_a_module_skipped_at_collection_is_assigned_counted_and_reported_as_skipped(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    tree = _tree(tmp_path, {"test_a.py": PASS, "test_b.py": PASS,
                            "test_m.py": "import pytest\npytest.importorskip('no_such_module_for_the_gate')\n"})
    rc, out = _run(tree, tmp_path, capsys, "--groups", "2")
    assert rc == 0, out
    assert "collected 3 tests in 3 files" in out and "2 passed, 1 skipped" in out, out


def test_parse_collect_reads_the_skipped_module_from_the_rs_lines() -> None:
    out = "t/test_a.py::test_x\n\n=== short test summary info ===\nSKIPPED [1] t/test_m.py:2: no module\n1/1 tests collected in 0.1s\n"
    per_file, expected, _d = g.parse_collect(out)
    assert per_file == {"t/test_a.py": 1, "t/test_m.py": 0} and expected == 2


# ------------------------------------------------------------ fixed-port files run alone, after the parallel phase

def test_serial_files_leave_the_parallel_groups_and_run_in_a_tail_of_their_own(tmp_path: Path, capsys: pytest.CaptureFixture,
                                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(g, "SERIAL_TAIL", ("test_b.py",))
    tree = _tree(tmp_path, {"test_a.py": PASS, "test_b.py": PASS, "test_c.py": PASS})
    rc, out = _run(tree, tmp_path, capsys, "--groups", "2")
    assert rc == 0 and "2 groups + a serial tail of 1 files" in out and "3 passed" in out, out
    assert "test_b.py" not in (tmp_path / "logs" / "group1.log").read_text(encoding="utf-8") + (tmp_path / "logs" / "group2.log").read_text(encoding="utf-8")
    assert "test_b.py" in (tmp_path / "logs" / "tail1.log").read_text(encoding="utf-8")


def test_split_serial_keeps_collection_order_and_only_named_files() -> None:
    files = {"a.py": 1, "b.py": 1, "c.py": 1}
    assert g.split_serial(files, ("c.py", "a.py", "zzz.py")) == ({"b.py": 1}, ["a.py", "c.py"])


def test_the_real_fixed_port_binders_are_in_the_tail() -> None:
    assert {"tests/integration/test_boot_cascade_smoke.py", "tests/integration/test_production_boot_integration.py"} <= set(g.SERIAL_TAIL)


# ------------------------------------------------------------ errors, markers, collection errors, exit codes, spoofs

def test_a_teardown_error_beside_a_passed_test_is_an_error_not_a_dropped_test(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    td = "import pytest\n\n@pytest.fixture\ndef boom():\n    yield\n    raise RuntimeError('td')\n\ndef test_m(boom):\n    pass\n"
    rc, out = _run(_tree(tmp_path, {"test_a.py": PASS, "test_m.py": td}), tmp_path, capsys, "--groups", "2")
    assert rc == 1 and "GATE PROBLEM" not in out and "1 errors" in out, out


def test_combine_accepts_an_error_that_overlaps_a_pass_and_refuses_a_real_shortfall() -> None:
    s = {"passed": 4, "failed": 0, "skipped": 0, "deselected": 0, "errors": 1, "xfailed": 0, "xpassed": 0, "secs": 1.0}
    assert g.combine([s], 4, 0)[1] == []
    assert g.combine([s], 6, 0)[1], "5 outcomes cannot account for 6 tests"
    assert g.combine([{**s, "passed": 3, "errors": 0}], 4, 0)[1], "3 outcomes cannot account for 4 tests"


def test_the_groups_apply_the_selection_markers_so_deselected_tests_never_run(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    slow = "import pytest\n\n@pytest.mark.slow\ndef test_slow():\n    raise AssertionError('must not run')\n\ndef test_ok():\n    pass\n"
    rc, out = _run(_tree(tmp_path, {"test_a.py": PASS, "test_s.py": slow}), tmp_path, capsys)
    assert rc == 0 and "2 passed" in out and "failed" not in out, out


def test_a_collection_error_stops_the_run_before_any_group_starts(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    tree = _tree(tmp_path, {"test_a.py": PASS, "test_bad.py": "import module_that_does_not_exist_xyz\n"})
    with pytest.raises(SystemExit, match="collection failed"):
        _run(tree, tmp_path, capsys)
    assert not (tmp_path / "logs" / "group1.log").exists(), "no group may start after a failed collection"


def test_a_non_zero_group_exit_fails_the_run_even_when_the_counts_are_clean(tmp_path: Path, capsys: pytest.CaptureFixture,
                                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    real = g.run_phase

    def lying_rc(*a, **k):
        return [(1, text) for _rc, text in real(*a, **k)]     # exit 1 with an all-passed summary

    monkeypatch.setattr(g, "run_phase", lying_rc)
    rc, out = _run(_tree(tmp_path, {"test_a.py": PASS, "test_b.py": PASS}), tmp_path, capsys)
    assert rc == 1 and "2 passed" in out


def test_exit_code_levels() -> None:
    clean = {"failed": 0, "errors": 0}
    assert g.exit_code([], [], clean) == 0
    assert g.exit_code([], [2], clean) == 1 and g.exit_code([], [], {"failed": 1, "errors": 0}) == 1
    assert g.exit_code(["x"], [], clean) == 3 and g.exit_code(["x"], [1], {"failed": 2, "errors": 0}) == 3


def test_a_summary_shaped_text_in_a_test_name_or_before_the_real_line_does_not_win() -> None:
    log = ("shared/t.py::test_x[= 1 passed in 0.39s =] PASSED [ 5%]\n"
           "= 2 failed, 7 passed in 12.00s =\n")
    got = g.parse_summary(log)
    assert got and got["failed"] == 2 and got["passed"] == 7
    assert g.parse_summary("shared/t.py::test_x[= 1 passed in 0.39s =] PASSED\n") is None, "mid-line text is not a summary"


def test_the_last_collected_total_line_wins_and_the_first_is_not_enough() -> None:
    out = "t/a.py::x\n1/1 tests collected in 0.1s\nnoise\n2/2 tests collected in 0.2s\nt/b.py::y\n"
    per_file, expected, _d = g.parse_collect(out)
    assert expected == 2 and sum(per_file.values()) == 2


# ------------------------------------------------------------ a hung group, corrupt weights, balance

def test_a_group_that_hangs_is_killed_and_the_run_fails(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    hang = "import time\n\ndef test_hang():\n    time.sleep(60)\n"
    rc, out = _run(_tree(tmp_path, {"test_h.py": hang}), tmp_path, capsys, "--timeout-s", "3")
    assert rc == 3 and "timed out" in out, out
    assert "GATE TIMEOUT" in (tmp_path / "logs" / "group1.log").read_text(encoding="utf-8")


def test_a_weights_file_that_exists_but_is_not_one_is_a_named_error(tmp_path: Path) -> None:
    for body in ("{not json", '{"nope": {}}', '{"seconds_per_file": []}'):
        p = tmp_path / "w.json"
        p.write_text(body, encoding="utf-8")
        with pytest.raises(SystemExit, match="is not a weights file"):
            g.load_weights(p)
    assert g.load_weights(tmp_path / "absent.json") == {}


def test_a_heavy_file_sits_alone_so_the_groups_balance() -> None:
    files = {"heavy.py": 3, "a.py": 3, "b.py": 3, "c.py": 3}
    weights = {"heavy.py": 100.0, "a.py": 1.0, "b.py": 1.0, "c.py": 1.0}
    groups = g.assign_groups(files, weights, 2)
    assert ["heavy.py"] in groups and sorted(f for grp in groups for f in grp) == sorted(files)


def test_a_summary_shaped_text_after_the_real_line_does_not_replace_it() -> None:
    log = "= 2 failed, 7 passed in 12.00s =\nsys:1: note printed later = 1 passed in 0.39s =\n"
    got = g.parse_summary(log)
    assert got and got["failed"] == 2 and got["passed"] == 7, "only a line that STARTS with '=' is a summary"


def test_an_inner_pytest_summary_printed_by_a_test_never_beats_the_final_line() -> None:
    log = "= 1 failed in 0.50s =\nmore test output\n= 5 passed, 1 skipped in 9.00s =\n"
    got = g.parse_summary(log)
    assert got and got["passed"] == 5 and got["failed"] == 0 and got["skipped"] == 1, "the LAST summary line wins"


def test_a_fixture_setup_error_is_an_error_exit_not_a_dropped_test(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    setup = "import pytest\n\n@pytest.fixture\ndef boom():\n    raise RuntimeError('setup')\n\ndef test_m(boom):\n    pass\n"
    rc, out = _run(_tree(tmp_path, {"test_a.py": PASS, "test_m.py": setup}), tmp_path, capsys, "--groups", "2")
    assert rc == 1 and "GATE PROBLEM" not in out and "1 errors" in out and "1 passed" in out, out
