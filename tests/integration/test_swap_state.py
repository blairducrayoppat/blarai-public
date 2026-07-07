"""Tests for swap_state — increment-2 swap-state persistence + boot reconciler.

Covers gap #2 (privacy: no conversation content persisted) and gap #1's recovery
anchor (the idempotent boot reconciler: disarm → stop-ovms → report-vs-interrupted).
"""

from __future__ import annotations

from shared.fleet import swap_state as ss


def _state(**kw):
    base = dict(
        run_id="20260101-000000-bd",
        session_id="sess-1",
        phase=ss.PHASE_CODE,
        tasks=[{"repo": "r", "task": "t", "prompt": "p"}],
        ts="2026-01-01T00:00:00Z",
    )
    base.update(kw)
    return ss.SwapState(**base)


# ---- persistence ----------------------------------------------------------


def test_write_read_round_trip(tmp_path):
    p = tmp_path / "swap.json"
    st = _state()
    ss.write_swap_state(st, path=p)
    assert ss.read_swap_state(p) == st


def test_no_conversation_field_persisted():
    # Privacy ruling: the record carries ONLY these fields — no conversation.
    fields = set(ss.SwapState.__dataclass_fields__)
    assert fields == {"run_id", "session_id", "phase", "tasks", "ts", "error"}
    for forbidden in ("conversation", "conv", "messages", "turns", "history"):
        assert forbidden not in fields


def test_read_absent_returns_none(tmp_path):
    assert ss.read_swap_state(tmp_path / "nope.json") is None


def test_read_blank_or_corrupt_returns_none(tmp_path):
    p = tmp_path / "swap.json"
    p.write_text("", encoding="utf-8")
    assert ss.read_swap_state(p) is None
    p.write_text("not json {", encoding="utf-8")
    assert ss.read_swap_state(p) is None
    p.write_text('{"no_run_id": true}', encoding="utf-8")
    assert ss.read_swap_state(p) is None


def test_atomic_write_leaves_no_tmp(tmp_path):
    p = tmp_path / "swap.json"
    ss.write_swap_state(_state(), path=p)
    assert p.exists()
    assert not (tmp_path / "swap.json.tmp").exists()


def test_with_phase_preserves_identity_and_tasks():
    st = _state()
    nxt = st.with_phase(ss.PHASE_UNLOAD_30B)
    assert nxt.phase == ss.PHASE_UNLOAD_30B
    assert nxt.run_id == st.run_id
    assert nxt.session_id == st.session_id
    assert nxt.tasks == st.tasks


def test_clear_is_idempotent(tmp_path):
    p = tmp_path / "swap.json"
    ss.write_swap_state(_state(), path=p)
    ss.clear_swap_state(p)
    assert not p.exists()
    ss.clear_swap_state(p)  # no raise on absent


# ---- #674: the build-signal survives the BlarAI-owned EXECUTE -> queue write ----
# The swap-state file (current.json) and the per-task task-queue.json (fed to run-fleet)
# are the two writes BlarAI owns on the live /dispatch path (execute_swap_dispatch ->
# prepare_and_launch_swap writes the swap-state; the detached driver re-reads it and
# real_run_task writes task-queue.json). Both serialise the task dicts WHOLE, so the
# goal-level build-signal fields threaded on at PLAN time (acceptance.compile_prompts)
# must survive untouched all the way to the file handed to the fleet. This is the
# cross-module contract the LA's fleet lane reads ($t.surface / $t.complexity).


def test_build_signal_fields_survive_swap_state_round_trip(tmp_path):
    # A task object carrying the build-signal fields (as compile_prompts stamps them) must
    # round-trip through write_swap_state -> read_swap_state byte-for-byte.
    task = {
        "repo": "R", "task": "add-calc", "prompt": "build it",
        "surface": "desktop-gui", "complexity": "complex", "language_hint": "dotnet",
    }
    p = tmp_path / "swap.json"
    ss.write_swap_state(_state(tasks=[task]), path=p)
    back = ss.read_swap_state(p)
    assert back.tasks[0] == task  # the WHOLE dict, signal fields included


def test_build_signal_fields_reach_task_queue_json(tmp_path):
    # The driver's per-task queue write (write_single_task_queue -> task-queue.json, the file
    # run-fleet.ps1 reads) must carry the signal fields. This is BlarAI's LAST owned write —
    # the fleet boundary is run-fleet.ps1 reading this file.
    from shared.fleet.dispatch import FleetDispatchConfig
    from shared.fleet.swap_ops import write_single_task_queue
    import json

    cfg = FleetDispatchConfig(
        scripts_dir=tmp_path, queue_path=tmp_path / "fleet-queue.json",
        runs_dir=tmp_path / "runs", projects_dir=tmp_path / "projects",
    )
    task = {
        "repo": "R", "task": "add-calc", "prompt": "build it",
        "surface": "web", "complexity": "moderate", "language_hint": "node",
    }
    qpath = write_single_task_queue(cfg, task)
    on_disk = json.loads(qpath.read_text(encoding="utf-8"))
    assert on_disk == [task]
    assert on_disk[0]["surface"] == "web"
    assert on_disk[0]["complexity"] == "moderate"
    assert on_disk[0]["language_hint"] == "node"


# ---- reconciler -----------------------------------------------------------


def _reconcile(tmp_path, *, state=None, summary=False, stop_calls=None):
    swap_p = tmp_path / "swap.json"
    sentinel = tmp_path / "server-should-run.txt"
    sentinel.write_text("coder-30b", encoding="utf-8")
    runs = tmp_path / "runs"
    if state is not None:
        ss.write_swap_state(state, path=swap_p)
        if summary:
            d = runs / state.run_id
            d.mkdir(parents=True, exist_ok=True)
            (d / "SUMMARY.txt").write_text("ok", encoding="utf-8")
    calls = stop_calls if stop_calls is not None else []
    res = ss.reconcile_swap_state(
        swap_state_path=swap_p,
        sentinel_path=sentinel,
        runs_dir=runs,
        stop_ovms=lambda: calls.append(1),
    )
    return res, sentinel, swap_p, calls


def test_reconcile_no_swap_is_total_noop(tmp_path):
    # F2: with NO in-flight swap-state, reconcile MUST NOT touch the fleet's sentinel
    # or OVMS — server-should-run.txt is the fleet's, armed when the operator runs the
    # 30B; touching it would kill the operator's running 30B on any BlarAI boot.
    res, sentinel, _, calls = _reconcile(tmp_path, state=None)
    assert res.in_flight is False
    assert sentinel.exists()       # fleet sentinel UNTOUCHED
    assert calls == []             # OVMS NOT stopped


def test_reconcile_terminal_swap_is_total_noop(tmp_path):
    # A RECOVERED/IDLE swap-state is also a no-op (no re-disarm, no re-stop).
    res, sentinel, _, calls = _reconcile(tmp_path, state=_state(phase=ss.PHASE_RECOVERED))
    assert res.in_flight is False
    assert sentinel.exists() and calls == []


def test_reconcile_in_flight_with_summary_reports_finished(tmp_path):
    res, sentinel, swap_p, calls = _reconcile(
        tmp_path, state=_state(phase=ss.PHASE_CODE), summary=True
    )
    assert res.in_flight and res.summary_available
    assert res.run_id == "20260101-000000-bd" and res.session_id == "sess-1"
    assert "finished" in res.message.lower()
    assert not sentinel.exists()   # OUR sentinel disarmed (real recovery)
    assert calls == [1]            # OUR 30B stopped
    assert ss.read_swap_state(swap_p).phase == ss.PHASE_RECOVERED  # idempotency mark


def test_reconcile_in_flight_without_summary_reports_interrupted(tmp_path):
    res, sentinel, _, calls = _reconcile(
        tmp_path, state=_state(phase=ss.PHASE_LOAD_30B), summary=False
    )
    assert res.in_flight and not res.summary_available
    assert "interrupted" in res.message.lower()
    assert "resumable" in res.message.lower()
    assert not sentinel.exists() and calls == [1]   # real recovery disarms + stops


def test_reconcile_idempotent_second_boot_is_noop(tmp_path):
    swap_p = tmp_path / "swap.json"
    sentinel = tmp_path / "server-should-run.txt"
    runs = tmp_path / "runs"
    ss.write_swap_state(_state(phase=ss.PHASE_CODE), path=swap_p)
    sentinel.write_text("coder-30b", encoding="utf-8")
    calls = []
    ss.reconcile_swap_state(swap_state_path=swap_p, sentinel_path=sentinel,
                            runs_dir=runs, stop_ovms=lambda: calls.append(1))
    assert not sentinel.exists() and calls == [1]   # first boot recovered
    # second boot: phase now RECOVERED (terminal) -> TOTAL no-op; a re-armed sentinel stays
    sentinel.write_text("coder-30b", encoding="utf-8")
    res2 = ss.reconcile_swap_state(swap_state_path=swap_p, sentinel_path=sentinel,
                                   runs_dir=runs, stop_ovms=lambda: calls.append(1))
    assert res2.in_flight is False
    assert sentinel.exists()        # untouched on the no-op boot
    assert calls == [1]             # NOT stopped again


def test_reconcile_stop_ovms_failure_is_fail_soft(tmp_path):
    swap_p = tmp_path / "swap.json"
    sentinel = tmp_path / "server-should-run.txt"
    sentinel.write_text("x", encoding="utf-8")
    ss.write_swap_state(_state(phase=ss.PHASE_CODE), path=swap_p)  # in-flight

    def boom():
        raise RuntimeError("ovms stop failed")

    res = ss.reconcile_swap_state(  # must NOT raise (the 14B boot must proceed)
        swap_state_path=swap_p, sentinel_path=sentinel,
        runs_dir=tmp_path / "runs", stop_ovms=boom,
    )
    assert res.in_flight is True       # proceeds past the (failed) stop
    assert not sentinel.exists()       # disarm happened before the stop attempt


def test_is_in_flight():
    assert ss.is_in_flight(_state(phase=ss.PHASE_CODE)) is True
    assert ss.is_in_flight(_state(phase=ss.PHASE_IDLE)) is False
    assert ss.is_in_flight(_state(phase=ss.PHASE_RECOVERED)) is False
    assert ss.is_in_flight(None) is False
