"""Isolated tests for the driver-integrated stop-doomed-fast checks (#844 C2).

`shared/fleet/doom_check.py` + its swap_ops/swap_driver integration seams. The
limb is DORMANT (the dispatch spec carries no flag; `build_doom_watchdog` returns
``None``); these tests drive the pure predicate, the watchdog loop/lifecycle, the
sampler over a tmp fleet layout, the spec bridge, the honest kill relabel, and the
driver's start/stop + doom-aware stop labeling — all with injected fakes, no real
processes, no psutil dependence.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

import shared.fleet.doom_check as dc
import shared.fleet.swap_driver as sd
from shared.fleet.dispatch import FleetDispatchConfig, TaskOutcome
from shared.fleet.swap_ops import (
    _CurrentChild,
    build_doom_watchdog,
    relabel_unexplained_kill,
)


def _sample(
    *,
    wall_now: float = 1000.0,
    mtime: "float | None" = 500.0,
    cpu: bool = False,
    child: bool = True,
) -> dc.DoomSample:
    return dc.DoomSample(
        wall_now=wall_now,
        newest_progress_mtime=mtime,
        coder_cpu_active=cpu,
        child_active=child,
    )


# ---------------------------------------------------------------------------
# The pure doom predicate
# ---------------------------------------------------------------------------


class TestClassifyDoom:
    def test_determined_doom_all_conditions(self) -> None:
        prev = _sample(wall_now=700.0, mtime=500.0)
        cur = _sample(wall_now=1000.0, mtime=500.0)  # 500s stale >= 240 grace
        assert dc.classify_doom(prev, cur) is True

    def test_no_child_registered_never_dooms(self) -> None:
        prev = _sample(wall_now=700.0, mtime=500.0, child=False)
        cur = _sample(wall_now=1000.0, mtime=500.0, child=False)
        assert dc.classify_doom(prev, cur) is False

    def test_coder_cpu_active_never_dooms(self) -> None:
        prev = _sample(wall_now=700.0, mtime=500.0)
        cur = _sample(wall_now=1000.0, mtime=500.0, cpu=True)
        assert dc.classify_doom(prev, cur) is False

    def test_first_sample_never_dooms(self) -> None:
        cur = _sample(wall_now=1000.0, mtime=500.0)
        assert dc.classify_doom(None, cur) is False

    def test_no_artifacts_yet_never_dooms(self) -> None:
        prev = _sample(wall_now=700.0, mtime=None)
        cur = _sample(wall_now=1000.0, mtime=None)
        assert dc.classify_doom(prev, cur) is False

    def test_first_artifact_appearance_is_progress(self) -> None:
        prev = _sample(wall_now=700.0, mtime=None)
        cur = _sample(wall_now=1000.0, mtime=500.0)
        assert dc.classify_doom(prev, cur) is False

    def test_mtime_advance_is_progress(self) -> None:
        prev = _sample(wall_now=700.0, mtime=500.0)
        cur = _sample(wall_now=1000.0, mtime=900.0)
        assert dc.classify_doom(prev, cur) is False

    def test_stale_but_inside_grace_waits(self) -> None:
        prev = _sample(wall_now=900.0, mtime=800.0)
        cur = _sample(wall_now=1000.0, mtime=800.0)  # 200s stale < 240 grace
        assert dc.classify_doom(prev, cur) is False

    def test_non_positive_grace_disables(self) -> None:
        prev = _sample(wall_now=700.0, mtime=500.0)
        cur = _sample(wall_now=99999.0, mtime=500.0)
        assert dc.classify_doom(prev, cur, stall_grace_s=0.0) is False
        assert dc.classify_doom(prev, cur, stall_grace_s=-1.0) is False


# ---------------------------------------------------------------------------
# The watchdog loop (pure, driven directly — no thread)
# ---------------------------------------------------------------------------


def _loop_recorder():
    calls: list = []
    return calls, {
        "mark_fired": lambda: calls.append("fired"),
        "request_stop": lambda: calls.append("stop"),
        "abort": lambda: calls.append("abort"),
        "on_doom": lambda msg: calls.append(("doom", msg)),
    }


class TestRunDoomWatchdog:
    def test_finished_first_exits_without_sampling(self) -> None:
        calls, hooks = _loop_recorder()
        dc.run_doom_watchdog(
            stall_grace_s=240.0,
            finished=lambda: True,
            sample=lambda: (_ for _ in ()).throw(AssertionError("must not sample")),
            sleep=lambda _s: None,
            **hooks,
        )
        assert calls == []

    def test_doom_fires_once_in_order_then_returns(self) -> None:
        calls, hooks = _loop_recorder()
        samples = iter(
            [
                _sample(wall_now=700.0, mtime=500.0),   # baseline
                _sample(wall_now=1000.0, mtime=500.0),  # doom
                _sample(wall_now=2000.0, mtime=500.0),  # never reached
            ]
        )
        dc.run_doom_watchdog(
            stall_grace_s=240.0,
            finished=lambda: False,
            sample=lambda: next(samples),
            sleep=lambda _s: None,
            **hooks,
        )
        doom_msgs = [c for c in calls if isinstance(c, tuple) and c[0] == "doom"]
        assert [c for c in calls if not isinstance(c, tuple)] == ["fired", "stop", "abort"]
        assert len(doom_msgs) == 1
        assert "DOOM-STOP" in doom_msgs[0][1]

    def test_sampling_error_is_alive_and_resets_baseline(self) -> None:
        """A raising sampler must never doom — AND it resets the baseline, so the
        next good sample starts a fresh confirmation window."""
        calls, hooks = _loop_recorder()
        finished_after = {"n": 0}

        def finished() -> bool:
            finished_after["n"] += 1
            return finished_after["n"] > 4  # let ~3 sample attempts happen

        seq = iter(
            [
                _sample(wall_now=700.0, mtime=500.0),   # baseline
                RuntimeError("unreadable"),              # reset
                _sample(wall_now=1000.0, mtime=500.0),  # NEW baseline (no doom: prev None)
            ]
        )

        def sample() -> dc.DoomSample:
            item = next(seq)
            if isinstance(item, Exception):
                raise item
            return item

        dc.run_doom_watchdog(
            stall_grace_s=240.0,
            finished=finished,
            sample=sample,
            sleep=lambda _s: None,
            **hooks,
        )
        assert calls == []  # never doomed despite the 500s-stale final sample

    def test_hook_exceptions_do_not_escape(self) -> None:
        samples = iter(
            [_sample(wall_now=700.0, mtime=500.0), _sample(wall_now=1000.0, mtime=500.0)]
        )

        def raiser(*_a) -> None:
            raise RuntimeError("hook blew up")

        dc.run_doom_watchdog(  # must return cleanly, not raise
            stall_grace_s=240.0,
            finished=lambda: False,
            sample=lambda: next(samples),
            mark_fired=raiser,
            request_stop=raiser,
            abort=raiser,
            on_doom=raiser,
            sleep=lambda _s: None,
        )


# ---------------------------------------------------------------------------
# The DoomWatchdog thread owner
# ---------------------------------------------------------------------------


class TestDoomWatchdog:
    def test_disabled_start_spawns_no_thread(self) -> None:
        w = dc.DoomWatchdog(
            enabled=False,
            sample=lambda: _sample(),
            abort=lambda: None,
            request_stop=lambda: None,
        )
        w.start()
        assert w._thread is None  # noqa: SLF001 — lifecycle assertion
        w.stop()  # idempotent clean no-op
        assert w.fired is False

    def test_non_positive_grace_spawns_no_thread(self) -> None:
        w = dc.DoomWatchdog(
            enabled=True,
            sample=lambda: _sample(),
            abort=lambda: None,
            request_stop=lambda: None,
            stall_grace_s=0.0,
        )
        w.start()
        assert w._thread is None  # noqa: SLF001

    def test_malformed_grace_coerces_to_disabled(self) -> None:
        w = dc.DoomWatchdog(
            enabled=True,
            sample=lambda: _sample(),
            abort=lambda: None,
            request_stop=lambda: None,
            stall_grace_s="not-a-number",  # type: ignore[arg-type]
        )
        w.start()
        assert w._thread is None  # noqa: SLF001

    def test_live_thread_dooms_sets_fired_and_stops(self) -> None:
        calls: list = []
        samples = iter(
            [_sample(wall_now=700.0, mtime=500.0), _sample(wall_now=1000.0, mtime=500.0)]
        )
        last = _sample(wall_now=1000.0, mtime=500.0)

        def sample() -> dc.DoomSample:
            nonlocal last
            try:
                last = next(samples)
            except StopIteration:
                pass
            return last

        w = dc.DoomWatchdog(
            enabled=True,
            sample=sample,
            abort=lambda: calls.append("abort"),
            request_stop=lambda: calls.append("stop"),
            on_doom=lambda msg: calls.append(("doom", msg)),
            sleep=lambda _s: None,
        )
        assert w.fired is False
        w.start()
        w_thread = w._thread  # noqa: SLF001
        assert w_thread is not None
        w_thread.join(timeout=10.0)  # the loop self-returns on doom
        assert not w_thread.is_alive()
        w.stop()
        assert w.fired is True
        assert "stop" in calls and "abort" in calls

    def test_stop_is_idempotent_and_exits_a_quiet_loop(self) -> None:
        w = dc.DoomWatchdog(
            enabled=True,
            sample=lambda: _sample(cpu=True),  # always alive — never dooms
            abort=lambda: None,
            request_stop=lambda: None,
            sleep=lambda _s: None,
        )
        w.start()
        w.stop()
        w.stop()
        assert w.fired is False
        assert w._thread is None  # noqa: SLF001


# ---------------------------------------------------------------------------
# Sampling over a real (tmp) fleet layout
# ---------------------------------------------------------------------------


def _config(tmp_path: Path) -> FleetDispatchConfig:
    state = tmp_path / "state"
    (state / "fleet-runs").mkdir(parents=True, exist_ok=True)
    return FleetDispatchConfig(
        scripts_dir=tmp_path / "scripts",
        queue_path=state / "fleet-queue.json",
        runs_dir=state / "fleet-runs",
        projects_dir=tmp_path / "projects",
    )


class TestSampling:
    def test_no_artifacts_reads_none(self, tmp_path: Path) -> None:
        cfg = _config(tmp_path)
        assert dc.newest_progress_mtime(cfg, "R1") is None

    def test_newest_across_all_watched_artifacts(self, tmp_path: Path) -> None:
        import os

        cfg = _config(tmp_path)
        run_dir = cfg.runs_dir / "R1"
        run_dir.mkdir()
        (run_dir / "journal.log").write_text("j", encoding="utf-8")
        (run_dir / "run-fleet-task-a.log").write_text("f", encoding="utf-8")
        logs = cfg.queue_path.parent / "logs"
        logs.mkdir()
        (logs / "ovms-1.out.log").write_text("o", encoding="utf-8")
        reports = cfg.queue_path.parent / "reports"
        reports.mkdir()
        newest = reports / "task-a.review.log"
        newest.write_text("r", encoding="utf-8")
        # Force a strict ordering: the review log is newest by 100s.
        base = 1_700_000_000
        os.utime(run_dir / "journal.log", (base, base))
        os.utime(run_dir / "run-fleet-task-a.log", (base + 10, base + 10))
        os.utime(logs / "ovms-1.out.log", (base + 20, base + 20))
        os.utime(newest, (base + 100, base + 100))
        assert dc.newest_progress_mtime(cfg, "R1") == pytest.approx(base + 100)

    def test_sampler_skips_cpu_probe_when_no_child(self, tmp_path: Path) -> None:
        cfg = _config(tmp_path)
        probe_calls = {"n": 0}

        def probe() -> bool:
            probe_calls["n"] += 1
            return True

        sampler = dc.build_doom_sampler(
            cfg, "R1", child_active=lambda: False, cpu_probe=probe,
            wall_clock=lambda: 123.0,
        )
        s = sampler()
        assert s.child_active is False and s.coder_cpu_active is False
        assert probe_calls["n"] == 0  # the probe is only paid while armed
        assert s.wall_now == 123.0

    def test_sampler_probes_cpu_when_child_registered(self, tmp_path: Path) -> None:
        cfg = _config(tmp_path)
        sampler = dc.build_doom_sampler(
            cfg, "R1", child_active=lambda: True, cpu_probe=lambda: True,
            wall_clock=lambda: 123.0,
        )
        s = sampler()
        assert s.child_active is True and s.coder_cpu_active is True


class TestCpuProbeFailSoft:
    def test_unreadable_psutil_reads_active(self, monkeypatch) -> None:
        """A broken probe must read ALIVE (never doom on an unreadable box)."""
        fake = types.ModuleType("psutil")

        def _raise(*_a, **_k):
            raise RuntimeError("probe unavailable")

        fake.process_iter = _raise  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "psutil", fake)
        assert dc.coder_cpu_active(sleep=lambda _s: None) is True

    def test_no_coder_processes_reads_idle(self, monkeypatch) -> None:
        fake = types.ModuleType("psutil")
        fake.process_iter = lambda _attrs: iter(())  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "psutil", fake)
        assert dc.coder_cpu_active(sleep=lambda _s: None) is False


# ---------------------------------------------------------------------------
# The _CurrentChild arming accessor
# ---------------------------------------------------------------------------


class _FakeProc:
    def poll(self):  # pragma: no cover - identity only
        return None


class TestChildRegistered:
    def test_lifecycle(self) -> None:
        holder = _CurrentChild()
        assert holder.is_child_registered() is False
        holder.register(_FakeProc())
        assert holder.is_child_registered() is True
        holder.register(None)
        assert holder.is_child_registered() is False

    def test_teardown_disarms(self) -> None:
        holder = _CurrentChild()
        holder.register(_FakeProc())
        holder.begin_teardown()
        assert holder.is_child_registered() is False


# ---------------------------------------------------------------------------
# Honest kill relabel (#757 lineage, doom-aware)
# ---------------------------------------------------------------------------


def _unknown_kill() -> TaskOutcome:
    return TaskOutcome(
        task="t", outcome="errored", result="UNKNOWN",
        detail="no SUMMARY line for this task",
    )


class TestRelabelUnexplainedKill:
    def test_no_stop_stays_unknown(self) -> None:
        oc = _unknown_kill()
        assert relabel_unexplained_kill(oc, stop_fired=False, doom_fired=False) is oc

    def test_budget_stop_labels_budget(self) -> None:
        out = relabel_unexplained_kill(_unknown_kill(), stop_fired=True, doom_fired=False)
        assert out.result == "TIMEOUT"
        assert "TIMED OUT" in out.detail and "budget" in out.detail
        assert "doomed" not in out.detail

    def test_doom_stop_labels_doom_not_budget(self) -> None:
        out = relabel_unexplained_kill(_unknown_kill(), stop_fired=True, doom_fired=True)
        assert out.result == "TIMEOUT"
        assert "TIMED OUT" in out.detail  # SUMMARY round-trip stays TIMEOUT (#686)
        assert "stop-doomed-fast" in out.detail
        assert "budget" not in out.detail

    def test_real_parsed_outcome_always_wins(self) -> None:
        real = TaskOutcome(task="t", outcome="processed", result="PARKED",
                           detail="not merged (parked)")
        assert relabel_unexplained_kill(real, stop_fired=True, doom_fired=True) is real

    def test_unknown_without_the_no_summary_shape_stays(self) -> None:
        oc = TaskOutcome(task="t", outcome="errored", result="UNKNOWN",
                         detail="some other mystery")
        assert relabel_unexplained_kill(oc, stop_fired=True, doom_fired=True) is oc


# ---------------------------------------------------------------------------
# The spec bridge (dormant-by-absence, the #744 pattern)
# ---------------------------------------------------------------------------


class TestBuildDoomWatchdog:
    def _bridge(self, tmp_path: Path, spec: dict):
        import threading

        return build_doom_watchdog(
            spec, _config(tmp_path),
            current_child=_CurrentChild(), stop_event=threading.Event(),
        )

    def test_absent_key_is_none(self, tmp_path: Path) -> None:
        assert self._bridge(tmp_path, {"run_id": "R1"}) is None

    def test_false_key_is_none(self, tmp_path: Path) -> None:
        spec = {"run_id": "R1", "swap_doom_checks_enabled": False}
        assert self._bridge(tmp_path, spec) is None

    def test_true_key_builds_with_registered_default_grace(self, tmp_path: Path) -> None:
        spec = {"run_id": "R1", "swap_doom_checks_enabled": True}
        w = self._bridge(tmp_path, spec)
        assert isinstance(w, dc.DoomWatchdog)
        assert w._stall_grace_s == dc.DOOM_STALL_GRACE_S  # noqa: SLF001

    def test_custom_grace_and_malformed_grace(self, tmp_path: Path) -> None:
        good = self._bridge(
            tmp_path,
            {"run_id": "R1", "swap_doom_checks_enabled": True, "doom_stall_grace_s": 60},
        )
        assert good is not None and good._stall_grace_s == 60.0  # noqa: SLF001
        bad = self._bridge(
            tmp_path,
            {"run_id": "R1", "swap_doom_checks_enabled": True,
             "doom_stall_grace_s": "garbage"},
        )
        assert bad is not None and bad._stall_grace_s == dc.DOOM_STALL_GRACE_S  # noqa: SLF001


# ---------------------------------------------------------------------------
# SwapDriver integration — lifecycle + honest stop labeling
# ---------------------------------------------------------------------------

_TASKS = [{"task": "a", "repo": "r"}, {"task": "b", "repo": "r"}]


def _merged(t: dict) -> TaskOutcome:
    return TaskOutcome(task=t["task"], outcome="processed", result="MERGED",
                       detail="merged")


def _ops(calls, **overrides) -> sd.SwapOps:
    base = dict(
        available_gb=lambda: 26.0,
        backend_alive=lambda: False,
        load_30b=lambda: (calls.append("load"), True)[1],
        wait_ready=lambda: True,
        run_task=lambda t: (calls.append(("task", t["task"])), _merged(t))[1],
        cancel_requested=lambda: False,
        disarm_watchdog=lambda: calls.append("disarm"),
        stop_ovms=lambda: calls.append("stop"),
        write_report=lambda rid, outs: calls.append(("report", rid, len(outs))),
        restart_launcher=lambda: calls.append("restart"),
        backend_ready=lambda: True,
        signal_failure=lambda msg: calls.append(("signal", msg)),
    )
    base.update(overrides)
    return sd.SwapOps(**base)


class _FakeDoom:
    """Duck-typed stand-in recording the driver's lifecycle calls."""

    def __init__(self, fired: bool = False) -> None:
        self.fired = fired
        self.calls: list[str] = []

    def start(self) -> None:
        self.calls.append("start")

    def stop(self) -> None:
        self.calls.append("stop")


def _driver(tmp_path, ops, **kw) -> sd.SwapDriver:
    return sd.SwapDriver(
        run_id="R1", session_id="s1", tasks=_TASKS,
        swap_state_path=tmp_path / "swap.json", ops=ops,
        gate_gb=21.0, sleep=lambda _s: None, **kw,
    )


class TestDriverIntegration:
    def test_lifecycle_started_in_run_stopped_in_teardown(self, tmp_path) -> None:
        calls: list = []
        doom = _FakeDoom()
        res = _driver(tmp_path, _ops(calls), doom_watchdog=doom).run()
        assert res.outcome == "complete"
        assert doom.calls == ["start", "stop"]

    def test_default_none_is_byte_identical(self, tmp_path) -> None:
        calls: list = []
        res = _driver(tmp_path, _ops(calls)).run()
        assert res.outcome == "complete"
        assert calls == ["load", ("task", "a"), ("task", "b"), ("report", "R1", 2),
                         "disarm", "stop", "restart"]

    def test_doom_fired_stop_labels_doom_stop_mid_code(self, tmp_path) -> None:
        """A stop issued after task 'a' with the doom watchdog fired reports
        doom-stop — never the budget's words (#757 honesty at the new source)."""
        calls: list = []
        stop_box = {"stop": False}
        doom = _FakeDoom(fired=True)

        def run_task(t: dict) -> TaskOutcome:
            calls.append(("task", t["task"]))
            stop_box["stop"] = True  # the doom watchdog killed this task out-of-band
            return _merged(t)

        ops = _ops(calls, run_task=run_task, stop_requested=lambda: stop_box["stop"])
        res = _driver(tmp_path, ops, doom_watchdog=doom).run()
        assert res.outcome == "doom-stop"
        assert "stop-doomed-fast" in res.message
        assert "budget" not in res.message
        assert len(res.outcomes) == 1  # stopped at the task boundary after 'a'

    def test_budget_stop_without_doom_is_byte_identical(self, tmp_path) -> None:
        calls: list = []
        stop_box = {"stop": False}
        doom = _FakeDoom(fired=False)

        def run_task(t: dict) -> TaskOutcome:
            calls.append(("task", t["task"]))
            stop_box["stop"] = True
            return _merged(t)

        ops = _ops(calls, run_task=run_task, stop_requested=lambda: stop_box["stop"])
        res = _driver(tmp_path, ops, doom_watchdog=doom).run()
        assert res.outcome == "budget-timeout"
        assert res.message == "the overall run budget elapsed — restoring the 14B"

    def test_pre_code_stop_with_doom_fired_labels_doom(self, tmp_path) -> None:
        calls: list = []
        doom = _FakeDoom(fired=True)
        ops = _ops(calls, stop_requested=lambda: True)
        res = _driver(tmp_path, ops, doom_watchdog=doom).run()
        assert res.outcome == "doom-stop"
        assert res.loaded_30b is False  # stopped before the expensive 30B load
        assert "load" not in calls
