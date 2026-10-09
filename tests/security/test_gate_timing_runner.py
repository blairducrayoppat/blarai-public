"""scripts/gate_timing_runner.py (#1699): when a timing run may start, when it stops being a clean
measurement, and the machinery around it (lock, orphan reaping, requeue, crash trace).

The decision functions are tested directly, each refusal beside a near-identical case that
passes. The tick itself is driven end to end on a tiny fake arm with the Windows probes
replaced by a scripted clock, because every defect the independent review found (a battery run
recorded clean, input near the start undetected, a reused pid disabling the lock, an orphaned
gate) lived in the part the pure functions do not reach.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import gate_timing_runner as g  # noqa: E402

IDLE = g.IDLE_REQUIRED_S


# ---------------------------------------------------------------- pure decisions

def test_start_allowed_only_when_idle_on_ac_quiet_and_alone() -> None:
    assert g.start_blocker(IDLE, True, 3.0, []) is None


@pytest.mark.parametrize("idle, ac, cpu, others, why", [
    (IDLE - 1, True, 3.0, [], "idle"),
    (IDLE, False, 3.0, [], "not on AC"),
    (IDLE, None, 3.0, [], "unknown"),
    (IDLE, True, g.CPU_QUIET_PCT, [], "cpu"),
    (IDLE, True, 3.0, ["python.exe:9"], "other test runner"),
])
def test_each_start_condition_blocks(idle: float, ac: bool | None, cpu: float, others: list[str], why: str) -> None:
    assert why in (g.start_blocker(idle, ac, cpu, others) or "")


CLEAN = dict(idle_s=IDLE + 600, elapsed_s=600, idle0_s=IDLE, on_ac=True, log_silent_s=5)


def test_a_clean_run_has_no_void_reason() -> None:
    assert g.void_reason(**CLEAN) is None


@pytest.mark.parametrize("change, why", [
    (dict(idle_s=IDLE + 600 - 5), "input resumed"),            # 5 s of input at any point
    (dict(idle_s=3), "input resumed"),
    (dict(on_ac=False), "not AC"),
    (dict(on_ac=None), "unknown"),
    (dict(intruders=["python.exe:7 python -m pytest"]), "another test runner"),
    (dict(log_silent_s=g.STALL_S), "stall"),
])
def test_each_void_condition_voids(change: dict, why: str) -> None:
    assert why in (g.void_reason(**{**CLEAN, **change}) or "")


def test_input_within_the_tolerance_is_jitter_not_input() -> None:
    assert g.void_reason(**{**CLEAN, "idle_s": IDLE + 600 - g.INPUT_TOLERANCE_S + 0.5}) is None


@pytest.mark.parametrize("cmd, hit", [
    (["C:/venv/python.exe", "-u", "-m", "pytest", "shared/"], True),
    (["pytest.exe", "tests"], True),
    (["C:\\venv\\Scripts\\pytest", "-q"], True),
    (["python", "-c", "import time; time.sleep(30)  # grep pytest.ini"], False),
    (["python", "-mpytest", "tests"], True),
    (["rg", "foo", "C:/x/site-packages/pytest"], False),
    (["python", "C:/venv/Scripts/pytest-script.py"], True),
    (["bash", "-c", "cat docs/pytest.ini && echo pytest"], False),
    (["python", "gate_timing_runner.py", "tick", "--state-dir", "pytest-state"], False),
    ([], False),
])
def test_a_test_runner_is_what_executes_not_a_word_in_the_arguments(cmd: list[str], hit: bool) -> None:
    assert g.is_pytest_cmdline(cmd) is hit


def test_plan_alternates_arms_each_round() -> None:
    runs = g.plan_runs(["old", "new"], 2)
    assert [r["arm"] for r in runs] == ["old", "new", "old", "new"]
    assert [r["n"] for r in runs] == [1, 2, 3, 4] and all(r["status"] == "pending" for r in runs)


def test_a_voided_run_is_repeated_next_so_the_alternation_holds() -> None:
    state = {"runs": g.plan_runs(["old", "new"], 2)}
    state["runs"][0]["status"] = "void"
    assert g.requeue(state, state["runs"][0]) is True
    assert [(r["arm"], r["status"]) for r in state["runs"]] == [
        ("old", "void"), ("old", "pending"), ("new", "pending"), ("old", "pending"), ("new", "pending")]
    assert g.next_pending(state)["n"] == 5


def test_requeue_stops_exactly_at_the_cap() -> None:
    state = {"runs": g.plan_runs(["old", "new"], 1)}
    state["runs"] += [{"n": 10 + i, "arm": "old", "status": "void"} for i in range(g.MAX_VOIDS - 2)]
    state["runs"][0]["status"] = "void"                      # MAX_VOIDS - 1 voids so far
    assert g.requeue(state, state["runs"][0]) is True        # the cap allows MAX_VOIDS voids
    state["runs"][1]["status"] = "void"                      # now MAX_VOIDS voids
    assert g.requeue(state, state["runs"][1]) is False


def test_summary_line_is_parsed_with_its_counts_and_the_last_one_wins() -> None:
    log = "= 1 passed in 1.00s =\nmore\n= 6 failed, 13152 passed, 26 skipped, 620 deselected, 29 warnings in 1450.17s (0:24:10) =\n"
    p = g.parse_summary(log)
    assert p and p["passed"] == 13152 and p["failed"] == 6 and p["skipped"] == 26 and p["pytest_s"] == 1450.17
    assert g.parse_summary("no summary here") is None


def test_probes_answer_on_this_machine() -> None:
    assert g.idle_seconds() >= 0
    assert g.on_ac_power() in (True, False, None)


# ---------------------------------------------------------------- the lock

def test_a_lock_whose_pid_was_reused_is_taken_over_and_a_live_holder_is_respected(tmp_path: Path) -> None:
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        lock = tmp_path / "tick.lock"
        lock.write_text(json.dumps({"pid": sleeper.pid, "ctime": 1.0}), encoding="utf-8")   # right pid, wrong start
        assert g.take_lock(tmp_path) is True
        lock.unlink()
        lock.write_text(json.dumps({"pid": sleeper.pid, "ctime": g.proc_ctime(sleeper.pid)}), encoding="utf-8")
        assert g.take_lock(tmp_path) is False
        assert "lock held by live pid" in (tmp_path / "ticks.log").read_text(encoding="utf-8")
    finally:
        sleeper.kill()


# ---------------------------------------------------------------- the tick, end to end

class Scene:
    """A fake arm tree, a state dir and scripted probes. `idle(t)` / `ac(t)` give the readings
    at seconds-since-scene-start; the gate is a two-second pytest run."""

    def __init__(self, tmp: Path, mp: pytest.MonkeyPatch, seconds: float = 3.0) -> None:
        self.tree = tmp / "tree"
        self.tree.mkdir()
        (self.tree / "test_gate.py").write_text(
            f"import time\n\ndef test_it():\n    time.sleep({seconds})\n", encoding="utf-8")
        self.state = tmp / "state"
        self.state.mkdir()
        g.save(self.state, {"python": sys.executable, "arms": {"a": str(self.tree)},
                            "runs": g.plan_runs(["a"], 1)})
        self.t0 = time.monotonic()
        self.input_at: float | None = None
        self.ac_off_at: float | None = None
        self.base_idle = IDLE + 10
        mp.setattr(g, "SAMPLE_S", 0.4)
        mp.setattr(g, "GATE_ARGS", ["."])
        mp.setattr(g, "cpu_percent", lambda: 1.0)
        mp.setattr(g, "other_test_runners", lambda *a, **k: [])   # the outer pytest is one
        mp.setattr(g, "idle_seconds", self.idle)
        mp.setattr(g, "on_ac_power", self.ac)

    def now(self) -> float:
        return time.monotonic() - self.t0

    def idle(self) -> float:
        t = self.now()
        if self.input_at is not None and t >= self.input_at:
            return t - self.input_at
        return self.base_idle + t

    def ac(self) -> bool:
        return not (self.ac_off_at is not None and self.now() >= self.ac_off_at)

    def run(self) -> dict:
        assert g.tick(self.state) == 0
        return g.load(self.state)["runs"][0]


def test_a_quiet_ac_run_is_clean_and_carries_its_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = Scene(tmp_path, monkeypatch).run()
    assert run["status"] == "clean" and run["passed"] == 1 and run["power_at_start"] == "AC"
    assert run["gate_pid"] and run["gate_ctime"], "the gate's pid is persisted so an orphan can be reaped"
    assert (tmp_path / "state" / "la-run01-a").is_dir(), "the run gets its own redirected LOCALAPPDATA"
    assert (tmp_path / "state" / "run01-a.samples.csv").read_text(encoding="utf-8").count("AC") >= 2


def test_input_a_moment_after_the_start_voids_the_run_and_requeues_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sc = Scene(tmp_path, monkeypatch, seconds=6.0)
    sc.input_at = 1.5      # a single touch shortly after the process started
    run = sc.run()
    assert run["status"] == "void" and "input resumed" in run["reason"]
    runs = g.load(sc.state)["runs"]
    assert [r["status"] for r in runs] == ["void", "pending"]


def test_power_lost_mid_run_voids_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sc = Scene(tmp_path, monkeypatch, seconds=6.0)
    sc.ac_off_at = 1.5
    run = sc.run()
    assert run["status"] == "void" and "not AC" in run["reason"]


def test_a_battery_start_never_starts_and_the_run_stays_pending(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sc = Scene(tmp_path, monkeypatch)
    sc.ac_off_at = 0.0
    run = sc.run()
    assert run["status"] == "pending" and "log" not in run
    assert "waiting: not on AC power" in (sc.state / "ticks.log").read_text(encoding="utf-8")


def test_battery_at_the_start_though_ac_at_the_probe_is_refused_by_execute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reaches execute(): the tick probe sees AC, the reading taken at the start does not."""
    sc = Scene(tmp_path, monkeypatch)
    seq = iter([True, False])
    monkeypatch.setattr(g, "on_ac_power", lambda: next(seq))
    run = sc.run()
    assert run["status"] == "pending" and "log" not in run
    assert "not started" in (sc.state / "ticks.log").read_text(encoding="utf-8")


def test_another_test_runner_appearing_mid_run_voids_the_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sc = Scene(tmp_path, monkeypatch, seconds=6.0)
    monkeypatch.setattr(g, "INTRUDER_SCAN_S", 0.0)
    calls = iter(range(100))
    monkeypatch.setattr(g, "other_test_runners", lambda *a, **k: ["python.exe:1 python -m pytest"] if next(calls) >= 1 else [])
    run = sc.run()
    assert run["status"] == "void" and "another test runner" in run["reason"]


def test_a_silent_log_voids_the_run_as_a_stall(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sc = Scene(tmp_path, monkeypatch, seconds=8.0)
    monkeypatch.setattr(g, "STALL_S", 2.0)
    run = sc.run()
    assert run["status"] == "void" and "stall" in run["reason"]


def test_a_gate_that_cannot_start_is_voided_with_the_cause(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sc = Scene(tmp_path, monkeypatch)
    state = g.load(sc.state)
    state["arms"]["a"] = str(tmp_path / "no-such-tree")
    g.save(sc.state, state)
    run = sc.run()
    assert run["status"] == "void" and "gate failed to start" in run["reason"]


def test_a_missing_state_is_logged_not_silent(tmp_path: Path) -> None:
    assert g.tick(tmp_path / "never-initialised") == 2
    assert "no state.json" in (tmp_path / "never-initialised" / "ticks.log").read_text(encoding="utf-8")


def test_a_reused_gate_pid_is_not_killed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sc = Scene(tmp_path, monkeypatch)
    bystander = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        state = g.load(sc.state)
        state["runs"][0].update(status="running", tick_pid=2 ** 22 - 3, tick_ctime=1.0, gate_pid=bystander.pid,
                                gate_ctime=g.proc_ctime(bystander.pid) - 500)   # a different process, same pid
        g.save(sc.state, state)
        g.reap_dead_running(sc.state, state)
        assert bystander.poll() is None, "an unrelated process holding the recorded pid must survive"
    finally:
        bystander.kill()


def test_an_empty_fresh_lock_is_a_tick_mid_write_not_a_stale_lock(tmp_path: Path) -> None:
    (tmp_path / "tick.lock").write_text("", encoding="utf-8")
    assert g.take_lock(tmp_path) is False


def test_input_between_the_tick_probe_and_the_start_is_caught_at_the_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The review's repro: the passing idle reading is older than the start. execute() re-reads."""
    sc = Scene(tmp_path, monkeypatch)
    seq = iter([IDLE + 5, 4.0])          # tick probe passes, the reading taken at the start does not
    monkeypatch.setattr(g, "idle_seconds", lambda: next(seq))
    run = sc.run()
    assert run["status"] == "pending"
    assert "not started" in (sc.state / "ticks.log").read_text(encoding="utf-8")


def test_a_dead_tick_leaves_an_orphaned_gate_that_the_next_tick_kills(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sc = Scene(tmp_path, monkeypatch)
    child_pid = sc.state / "child.pid"
    orphan = subprocess.Popen([sys.executable, "-c",
                               "import subprocess, sys, time; c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']);"
                               f"open(r'{child_pid}', 'w').write(str(c.pid)); time.sleep(120)"])
    try:
        for _ in range(100):
            if child_pid.exists() and child_pid.read_text(encoding="utf-8"):
                break
            time.sleep(0.1)
        state = g.load(sc.state)
        state["runs"][0].update(status="running", tick_pid=2 ** 22 - 3, tick_ctime=1.0, gate_pid=orphan.pid,
                                gate_ctime=g.proc_ctime(orphan.pid))
        g.save(sc.state, state)
        g.reap_dead_running(sc.state, state)
        orphan.wait(timeout=10)
        import psutil
        grandchild = int(child_pid.read_text(encoding="utf-8"))
        time.sleep(0.5)
        assert not psutil.pid_exists(grandchild), "the whole tree dies, not only the recorded pid"
        runs = g.load(sc.state)["runs"]
        assert runs[0]["status"] == "void" and "orphaned gate" in runs[0]["reason"]
        assert runs[1]["status"] == "pending"
    finally:
        orphan.kill()


def test_a_crash_in_the_tick_is_written_to_the_log_with_its_traceback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sc = Scene(tmp_path, monkeypatch)
    (sc.state / "state.json").write_text("{not json", encoding="utf-8")
    assert g.tick(sc.state) == 1
    assert "TICK FAILED" in (sc.state / "ticks.log").read_text(encoding="utf-8")
    assert not (sc.state / "tick.lock").exists()
