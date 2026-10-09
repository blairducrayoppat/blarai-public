"""scripts/run_standing_gate.py (#1707): the parallel standing gate must run EXACTLY the tests the sequential gate runs.

Pure functions first (collection parse, grouping, summary parse, combination), each refusal beside a near-identical
case that passes; then the runner end to end on a tiny tree with real pytest subprocesses, including a failing test,
a collection count that the groups do not reproduce, and a group that prints no summary.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import run_standing_gate as g  # noqa: E402

COLLECT = """\
a/test_one.py::test_a
a/test_one.py::test_b[x]
b/test_two.py::test_c

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
3/5 tests collected (2 deselected) in 0.10s
"""


def test_collection_output_gives_tests_per_file_total_and_deselected() -> None:
    per_file, total, deselected = g.parse_collect(COLLECT)
    assert per_file == {"a/test_one.py": 2, "b/test_two.py": 1} and (total, deselected) == (3, 2)


def test_a_collection_whose_lines_do_not_add_up_to_its_total_is_refused() -> None:
    with pytest.raises(ValueError, match="lists 3 tests but reports 4"):
        g.parse_collect(COLLECT.replace("3/5 tests", "4/6 tests"))
    with pytest.raises(ValueError, match="lists no tests"):
        g.parse_collect("-- Docs: x\n")


def test_the_per_file_count_shape_of_default_verbosity_is_understood() -> None:
    per_file, total, deselected = g.parse_collect("a/test_one.py: 2\nb/test_two.py: 1\n\n3 tests collected in 0.01s\n")
    assert per_file == {"a/test_one.py": 2, "b/test_two.py": 1} and (total, deselected) == (3, 0)


def test_every_file_lands_in_exactly_one_group_and_the_load_is_balanced() -> None:
    files = {f"t/test_{i:02d}.py": 3 for i in range(40)}
    weights = {f: float(1 + (i * 7) % 23) for i, f in enumerate(files)}
    groups = g.assign_groups(files, weights, 4)
    flat = [f for grp in groups for f in grp]
    assert sorted(flat) == sorted(files) and len(flat) == len(set(flat)), "disjoint and complete"
    loads = [sum(weights[f] for f in grp) for grp in groups]
    assert max(loads) - min(loads) <= max(weights.values()), "longest-first keeps the spread within one file"
    assert g.assign_groups(files, weights, 4) == groups, "deterministic"


def test_files_keep_their_collection_order_inside_a_group() -> None:
    """A canary test failed once because grouping sorted files alphabetically across directories and put a file that
    leaves a registered adjudicator in front of the file that expects it clear."""
    files = {"shared/test_z.py": 1, "services/test_y.py": 1, "tests/test_a.py": 1, "launcher/test_m.py": 1}
    for grp in g.assign_groups(files, {}, 2):
        listed = list(files)
        assert grp == sorted(grp, key=listed.index), grp
    (only,) = g.assign_groups(files, {}, 1)
    assert only == list(files), "one group reproduces the sequential order exactly"


def test_an_unweighted_file_is_estimated_from_its_test_count_and_n_larger_than_files_is_clamped() -> None:
    groups = g.assign_groups({"big.py": 1000, "small.py": 1}, {}, 8)
    assert len(groups) == 2 and ["big.py"] in groups, "the heavy file sits alone"
    assert g.assign_groups({}, {}, 4) == [[]]


@pytest.mark.parametrize("text, want", [
    ("= 5 failed, 13152 passed, 26 skipped, 620 deselected, 29 warnings in 1450.17s (0:24:10) =",
     dict(failed=5, passed=13152, skipped=26, deselected=620, errors=0, secs=1450.17)),
    ("======== 2 errors, 7 passed in 3.10s ========", dict(failed=0, passed=7, errors=2, secs=3.10)),
])
def test_summary_line_parse(text: str, want: dict) -> None:
    got = g.parse_summary("noise\n" + text + "\n")
    assert got and all(got[k] == v for k, v in want.items())


def test_no_summary_line_is_none() -> None:
    assert g.parse_summary("12 passed in 0.5s") is None and g.parse_summary("") is None


def _s(**kw) -> dict:
    return {"passed": 0, "failed": 0, "skipped": 0, "deselected": 0, "errors": 0, "xfailed": 0, "xpassed": 0, "secs": 1.0, **kw}


def test_combination_sums_the_groups_and_demands_the_collected_total() -> None:
    tot, problems = g.combine([_s(passed=5, skipped=1), _s(passed=3, failed=1)], 10, 620)
    assert problems == [] and tot["passed"] == 8 and tot["failed"] == 1 and tot["skipped"] == 1 and tot["deselected"] == 620
    _tot, problems = g.combine([_s(passed=5), _s(passed=3)], 10, 0)
    assert any("ran 8 tests (+0 errors) but the single collection found 10" in p for p in problems), "a missing test is a problem"
    _tot, problems = g.combine([_s(passed=5), None], 5, 0)
    assert any("printed no pytest summary line" in p for p in problems)


def test_the_combined_line_has_the_shape_of_a_single_run_plus_the_group_count() -> None:
    line = g.summary_line({"passed": 9, "failed": 1, "skipped": 0, "errors": 0, "xfailed": 0, "xpassed": 0, "deselected": 4}, 12.3456, 4)
    assert line == "= 1 failed, 9 passed, 4 deselected in 12.35s (parallel x4) ="


def test_weights_are_read_back_from_a_durations_log(tmp_path: Path) -> None:
    log = tmp_path / "d.log"
    log.write_text("1.50s call     a/test_one.py::test_a\n0.50s setup    a/test_one.py::test_a\n2.00s call     b/test_two.py::t\n", encoding="utf-8")
    assert g.weights_from_logs([log]) == {"a/test_one.py": 2.0, "b/test_two.py": 2.0}


# ---------------------------------------------------------------- end to end on a tiny tree

def _tree(tmp: Path, failing: bool = False) -> Path:
    t = tmp / "tree"
    t.mkdir()
    (t / "test_a.py").write_text("def test_a1():\n    pass\n\ndef test_a2():\n    pass\n", encoding="utf-8")
    (t / "test_b.py").write_text("def test_b1():\n    pass\n", encoding="utf-8")
    (t / "test_c.py").write_text("def test_c1():\n    assert %s\n" % ("False" if failing else "True"), encoding="utf-8")
    return t


def _run(tree: Path, tmp: Path, capsys: pytest.CaptureFixture, groups: int = 2) -> tuple[int, str]:
    rc = g.main(["--cwd", str(tree), "--python", sys.executable, "--roots", ".", "--groups", str(groups),
                 "--logdir", str(tmp / "logs"), "--weights", str(tmp / "none.json")])
    return rc, capsys.readouterr().out


def test_a_clean_tree_runs_every_test_in_parallel_groups(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    rc, out = _run(_tree(tmp_path), tmp_path, capsys)
    assert rc == 0, out
    assert "collected 4 tests in 3 files" in out and "= 4 passed, 0 deselected in " in out and "(parallel x2)" in out
    assert (tmp_path / "logs" / "group1.log").is_file() and (tmp_path / "logs" / "group2.log").is_file()


def test_a_failing_test_in_any_group_fails_the_run_and_is_named(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    rc, out = _run(_tree(tmp_path, failing=True), tmp_path, capsys)
    assert rc == 1 and "FAILED test_c.py::test_c1" in out and "1 failed, 3 passed" in out


def test_groups_that_do_not_reproduce_the_collected_count_fail_loud(tmp_path: Path, capsys: pytest.CaptureFixture,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    real = g.collect

    def lying(python, cwd, targets):
        files, total, desel = real(python, cwd, targets)
        return files, total + 1, desel      # the single collection claims a test the groups cannot run

    monkeypatch.setattr(g, "collect", lying)
    rc, out = _run(_tree(tmp_path), tmp_path, capsys)
    assert rc == 3 and "GATE PROBLEM: the groups ran 4 tests (+0 errors) but the single collection found 5" in out


def test_a_group_that_dies_without_a_summary_fails_loud(tmp_path: Path, capsys: pytest.CaptureFixture,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(g, "pytest_args", lambda py, targets, extra: [py, "-c", "import sys; sys.exit(9)"] if extra and extra[0] == "--durations=0" else
                        [py, "-u", "-m", "pytest", *targets, "-m", g.SELECTION_MARKERS, "-p", "no:cacheprovider", *extra])
    rc, out = _run(_tree(tmp_path), tmp_path, capsys)
    assert rc == 3 and "printed no pytest summary line" in out
