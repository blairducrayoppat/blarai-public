"""Follow-ups from the re-review of scripts/run_standing_gate.py (#1707): the group count in the result line, a group
whose files were all skipped at collection (pytest exit 5), the fixed-port files existing on disk, a heavy file that
is not first, and a timed-out group's process really being gone.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import run_standing_gate as g  # noqa: E402

PASS = "def test_ok():\n    pass\n"
TOT = {"passed": 9, "failed": 0, "skipped": 0, "errors": 0, "xfailed": 0, "xpassed": 0, "deselected": 4}


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


def test_the_result_line_names_the_parallel_groups_and_flags_the_serial_tail_separately() -> None:
    assert g.summary_line(TOT, 12.0, 6) == "= 9 passed, 4 deselected in 12.00s (parallel x6) ="
    assert g.summary_line(TOT, 12.0, 6, serial_tail=True).endswith("(parallel x6 + serial tail) =")


def test_the_line_of_a_real_run_with_a_tail_says_the_group_count_asked_for(tmp_path: Path, capsys: pytest.CaptureFixture,
                                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(g, "SERIAL_TAIL", ("test_b.py",))
    rc, out = _run(_tree(tmp_path, {"test_a.py": PASS, "test_b.py": PASS, "test_c.py": PASS}), tmp_path, capsys, "--groups", "2")
    assert rc == 0 and "(parallel x2 + serial tail)" in out, out


@pytest.mark.parametrize("rc, summary, ok", [
    (0, None, True),
    (5, {"failed": 0, "errors": 0}, True),
    (5, {"failed": 1, "errors": 0}, False),
    (5, None, False),
    (1, {"failed": 0, "errors": 0}, False),
    (2, {"failed": 0, "errors": 0}, False),
])
def test_which_group_exit_codes_are_acceptable(rc: int, summary: dict | None, ok: bool) -> None:
    assert g.group_rc_ok(rc, summary) is ok


def test_a_serial_tail_whose_files_are_all_skipped_at_collection_is_not_a_failure(tmp_path: Path, capsys: pytest.CaptureFixture,
                                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(g, "SERIAL_TAIL", ("test_m.py",))
    skipped = "import pytest\npytest.importorskip('no_such_module_for_the_gate')\n"
    rc, out = _run(_tree(tmp_path, {"test_a.py": PASS, "test_m.py": skipped}), tmp_path, capsys, "--groups", "1")
    assert rc == 0 and "1 passed, 1 skipped" in out and "GATE" not in out, out


def test_a_group_that_exits_non_zero_with_clean_counts_is_named(tmp_path: Path, capsys: pytest.CaptureFixture,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    real = g.run_phase
    monkeypatch.setattr(g, "run_phase", lambda *a, **k: [(2, text) for _rc, text in real(*a, **k)])
    rc, out = _run(_tree(tmp_path, {"test_a.py": PASS}), tmp_path, capsys, "--groups", "1")
    assert rc == 1 and "GATE: group 1 exited with code 2 although its counts show no failure" in out, out


def test_every_serial_tail_file_exists_in_the_repository() -> None:
    missing = [f for f in g.SERIAL_TAIL if not (ROOT / f).is_file()]
    assert not missing, f"a renamed fixed-port file would silently rejoin the parallel groups: {missing}"


def test_the_heavy_file_sits_alone_wherever_it_is_in_the_collection_order() -> None:
    files = {"a.py": 3, "b.py": 3, "c.py": 3, "heavy.py": 3}
    weights = {"heavy.py": 100.0, "a.py": 1.0, "b.py": 1.0, "c.py": 1.0}
    groups = g.assign_groups(files, weights, 2)
    assert ["heavy.py"] in groups, "with plain insertion order the heavy file would share a group"


def test_a_timed_out_group_leaves_no_process_behind(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    psutil = pytest.importorskip("psutil")
    pidfile = tmp_path / "child.pid"
    body = ("import os, time\n\ndef test_hang():\n    open(r'%s', 'w').write(str(os.getpid()))\n    time.sleep(120)\n" % pidfile)
    rc, out = _run(_tree(tmp_path, {"test_h.py": body}), tmp_path, capsys, "--timeout-s", "4")
    assert rc == 3 and "timed out" in out
    deadline = time.monotonic() + 10
    pid = int(pidfile.read_text(encoding="utf-8"))
    while time.monotonic() < deadline and psutil.pid_exists(pid):
        time.sleep(0.2)
    assert not psutil.pid_exists(pid), "the hung test process must be killed with its group"
