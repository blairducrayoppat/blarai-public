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
    # plan_hash (M2 #740) is a sha256 hex of the persisted JobPlan artifact — pure
    # integrity metadata, no content of any kind (the tamper re-pin, §10 S1).
    # driver_pid / driver_pid_created (#758) are process-liveness metadata (the
    # reconciler's crashed-vs-live gate) — likewise content-free.
    # driver_image (#902) is the driver's process image name (e.g. "pythonw.exe")
    # — the reconciler's second identity axis for its PID-reuse gate; process
    # metadata, content-free like the pid/created stamps.
    fields = set(ss.SwapState.__dataclass_fields__)
    assert fields == {"run_id", "session_id", "phase", "tasks", "ts", "error",
                      "plan_hash", "driver_pid", "driver_pid_created",
                      "driver_image"}
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


def _reconcile(tmp_path, *, state=None, summary=False, stop_calls=None,
               liveness=None):
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
        driver_liveness_probe=(
            (lambda st: liveness) if liveness is not None else None
        ),
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


# ---- #758: recovery presumes a CRASH — a live driver means hands-off --------
# The 2026-07-07 incident: an AO boot mid-dispatch (a pytest gate run) "recovered"
# a HEALTHY swap — stopped the real OVMS mid-request, disarmed the sentinel, and
# stamped RECOVERED over the live run, killing the battery job.


def test_reconcile_live_driver_is_hands_off(tmp_path):
    swap_p = tmp_path / "swap.json"
    sentinel = tmp_path / "server-should-run.txt"
    sentinel.write_text("coder-30b", encoding="utf-8")
    ss.write_swap_state(_state(phase=ss.PHASE_CODE), path=swap_p)
    calls = []
    res = ss.reconcile_swap_state(
        swap_state_path=swap_p, sentinel_path=sentinel, runs_dir=tmp_path / "runs",
        stop_ovms=lambda: calls.append(1),
        driver_alive_probe=lambda st: True,          # the driver is ALIVE
    )
    assert res.in_flight is True
    assert "still running" in res.message.lower()
    assert sentinel.exists()                          # NOT disarmed
    assert calls == []                                # OVMS NOT stopped (the kill class)
    assert ss.read_swap_state(swap_p).phase == ss.PHASE_CODE   # NOT stamped RECOVERED


def test_reconcile_dead_driver_recovers_as_before(tmp_path):
    swap_p = tmp_path / "swap.json"
    sentinel = tmp_path / "server-should-run.txt"
    sentinel.write_text("coder-30b", encoding="utf-8")
    ss.write_swap_state(_state(phase=ss.PHASE_CODE), path=swap_p)
    calls = []
    res = ss.reconcile_swap_state(
        swap_state_path=swap_p, sentinel_path=sentinel, runs_dir=tmp_path / "runs",
        stop_ovms=lambda: calls.append(1),
        driver_alive_probe=lambda st: False,         # the driver is DEAD -> real crash
    )
    assert res.in_flight is True
    assert not sentinel.exists() and calls == [1]     # full recovery
    assert ss.read_swap_state(swap_p).phase == ss.PHASE_RECOVERED


def test_driver_alive_real_probe():
    import os

    import psutil

    me = os.getpid()
    created = float(psutil.Process(me).create_time())
    assert ss.driver_alive(_state(driver_pid=me, driver_pid_created=created)) is True
    # A create-time mismatch = pid reuse -> NOT the recorded driver.
    assert ss.driver_alive(
        _state(driver_pid=me, driver_pid_created=created - 3600.0)) is False
    # Legacy record (no pid) and a plainly-dead pid both fail closed to "recover".
    assert ss.driver_alive(_state(driver_pid=0)) is False
    assert ss.driver_alive(None) is False


def test_swap_state_driver_pid_roundtrip_and_with_phase(tmp_path):
    p = tmp_path / "swap.json"
    st = _state(phase=ss.PHASE_CODE, driver_pid=4242, driver_pid_created=123.5,
                driver_image="pythonw.exe")
    ss.write_swap_state(st, path=p)
    back = ss.read_swap_state(p)
    assert back.driver_pid == 4242 and back.driver_pid_created == 123.5
    assert back.driver_image == "pythonw.exe"
    advanced = back.with_phase(ss.PHASE_CRITIC)
    assert advanced.driver_pid == 4242 and advanced.driver_pid_created == 123.5
    assert advanced.driver_image == "pythonw.exe"
    # Legacy JSON without the fields reads back as 0/0.0/'' (pre-#758/#902
    # behavior preserved byte-identically).
    p.write_text(
        '{"run_id": "r", "session_id": "s", "phase": "CODE", "tasks": []}',
        encoding="utf-8",
    )
    legacy = ss.read_swap_state(p)
    assert legacy.driver_pid == 0 and legacy.driver_pid_created == 0.0
    assert legacy.driver_image == ""


def test_driver_phase_writes_carry_the_driver_stamp(tmp_path):
    """#758 follow-up (2026-07-08): the driver entrypoint stamped driver_pid
    into the swap-state after spawn — but SwapDriver._phase constructed a
    FRESH SwapState, so the driver's very first phase write clobbered the
    stamp back to 0/0.0 (found LIVE: the real current.json read phase CODE,
    driver_pid 0 mid-battery), leaving the reconciler's driver-alive gate
    inert exactly when it must tell a live dispatch from a crashed one.
    Every _phase write must carry the driver's own pid + create-time, and
    driver_alive must hold on the read-back."""
    import os

    from shared.fleet import swap_driver as sd

    p = tmp_path / "swap.json"
    driver = sd.SwapDriver(
        run_id="R1", session_id="s1", tasks=[],
        swap_state_path=p, ops=None, sleep=lambda _s: None,
    )
    driver._phase(ss.PHASE_CODE)
    st = ss.read_swap_state(p)
    assert st is not None and st.phase == ss.PHASE_CODE
    assert st.driver_pid == os.getpid(), (
        "the CODE phase write dropped the #758 driver stamp — the clobber "
        "this lock exists for"
    )
    assert ss.driver_alive(st) is True
    # The stamp must survive EVERY subsequent write (incl. error re-writes),
    # not just the first — one unstamped write un-guards the rest of the run.
    driver._phase(ss.PHASE_UNLOAD_30B, error="x")
    st2 = ss.read_swap_state(p)
    assert st2 is not None and st2.driver_pid == os.getpid()
    assert ss.driver_alive(st2) is True


def test_driver_run_stamps_terminal_phase_on_healthy_completion(tmp_path):
    """2026-07-08 (B4 wedge): before the driver-alive stamp survived phase
    writes, the terminal RECOVERED came from the restarted AO's boot reconcile
    — whose recover branch only fired because driver_pid read 0. Once the
    stamp was carried correctly, the reconcile went hands-off on the
    still-alive driver and NOTHING ever stamped terminal: B4's run finished at
    05:34 and the battery monitor waited blind until its 3 h doom. A healthy
    driver must stamp its OWN run terminal as its last act."""
    from shared.fleet import swap_driver as sd

    p = tmp_path / "swap.json"
    calls = []
    ops = sd.SwapOps(
        available_gb=lambda: 26.0,
        backend_alive=lambda: False,
        load_30b=lambda: True,
        wait_ready=lambda: True,
        run_task=lambda t: sd.TaskOutcome(
            task=t["task"], outcome="processed", result="MERGED", detail="ok"),
        cancel_requested=lambda: False,
        disarm_watchdog=lambda: calls.append("disarm"),
        stop_ovms=lambda: calls.append("stop"),
        write_report=lambda rid, outs: calls.append("report"),
        restart_launcher=lambda: calls.append("restart"),
        backend_ready=lambda: True,
        signal_failure=lambda msg: calls.append(("signal", msg)),
    )
    driver = sd.SwapDriver(
        run_id="R1", session_id="s1",
        tasks=[{"repo": str(tmp_path), "task": "t1", "prompt": "p"}],
        swap_state_path=p, ops=ops, gate_gb=21.0, sleep=lambda _s: None,
    )
    result = driver.run()
    assert result.restart_ok is True
    st = ss.read_swap_state(p)
    assert st is not None and st.phase == ss.PHASE_RECOVERED, (
        "a healthy driver run must END on a terminal phase — the monitor "
        "completes only on one, and the reconcile's recover branch no longer "
        "fires for a correctly-stamped live driver (the B4 wedge)"
    )
    assert not ss.is_in_flight(st)


def test_driver_run_leaves_in_flight_when_restore_fails(tmp_path):
    """The crash-net half of the same fix: a FAILED 14B restore must NOT stamp
    terminal — the state stays in-flight so the next AO boot's reconcile keeps
    ownership of the unhealthy path (disarm + stop + operator message)."""
    from shared.fleet import swap_driver as sd

    p = tmp_path / "swap.json"
    ops = sd.SwapOps(
        available_gb=lambda: 26.0,
        backend_alive=lambda: False,
        load_30b=lambda: True,
        wait_ready=lambda: True,
        run_task=lambda t: sd.TaskOutcome(
            task=t["task"], outcome="processed", result="MERGED", detail="ok"),
        cancel_requested=lambda: False,
        disarm_watchdog=lambda: None,
        stop_ovms=lambda: None,
        write_report=lambda rid, outs: None,
        restart_launcher=lambda: None,
        backend_ready=lambda: False,   # the restore never comes up
        signal_failure=lambda msg: None,
    )
    driver = sd.SwapDriver(
        run_id="R1", session_id="s1",
        tasks=[{"repo": str(tmp_path), "task": "t1", "prompt": "p"}],
        swap_state_path=p, ops=ops, gate_gb=21.0, sleep=lambda _s: None,
        restart_retries=1, restart_backoff_s=0.0,
    )
    result = driver.run()
    assert result.restart_ok is False
    st = ss.read_swap_state(p)
    assert st is not None and st.phase != ss.PHASE_RECOVERED
    assert ss.is_in_flight(st), (
        "a failed restore must stay in-flight — the reconcile owns the "
        "unhealthy path"
    )


# ---- #902: PID-reuse-safe reconcile — identity before every kill ------------
# The 2026-07-15 hazard: a STRANDED swap record (hours old) whose recorded driver
# PID has since been RECYCLED by an unrelated process (e.g. one inside a pytest
# tree). Pre-#902 the reconcile classified "identity mismatch" as "crashed" and ran
# the destructive convergence — disarming the LIVE fleet's sentinel and force-
# stopping a LIVE OVMS it could not attribute (the same class as the 2026-07-07
# live-dispatch kill, through the recovery door). The contract locked here:
#   (a) a planted stranded record pointing at a since-reused PID completes WITHOUT
#       killing anything (REAL identity probe, gate-shaped);
#   (b) the reconcile REFUSES the destructive arms whenever the recorded identity
#       no longer matches (create-time OR image-name mismatch);
#   (c) the kill path STILL fires when the identity evidence says the driver is
#       genuinely GONE (control tested ON as well as OFF — principle 12);
# plus the phase allowlist: a record stranded BEFORE LOAD-30B (or with a garbage
# phase) never disarms/stops — that swap provably armed and loaded nothing.


def test_reconcile_reused_pid_kills_nothing_real_probe(tmp_path):
    # (a) + (b), REAL probe: THIS live pytest process wears the recorded driver_pid
    # (guaranteed-alive, deterministic), with a deliberately-wrong create-time —
    # exactly the since-reused-PID shape. The reconcile must complete, touch
    # nothing external, and expire the stale record.
    import os

    me = os.getpid()
    st = _state(phase=ss.PHASE_CODE, driver_pid=me, driver_pid_created=1.0)
    res, sentinel, swap_p, calls = _reconcile(tmp_path, state=st)
    assert res.in_flight is True
    assert calls == []                 # NOTHING stopped — the load-bearing refusal
    assert sentinel.exists()           # fleet sentinel UNTOUCHED
    assert "stale" in res.message.lower()
    assert ss.read_swap_state(swap_p).phase == ss.PHASE_RECOVERED  # record converged
    # Idempotent: the expired record makes the next boot a TOTAL no-op.
    res2, sentinel2, _, calls2 = _reconcile(tmp_path, state=None, stop_calls=calls)
    assert calls == []


def test_reconcile_refuses_kill_on_image_name_mismatch(tmp_path):
    # (b) second identity axis: right pid + right create-time but the WRONG image
    # name is still NOT our driver — refuse the destructive arms.
    import os

    import psutil

    me = os.getpid()
    created = float(psutil.Process(me).create_time())
    st = _state(phase=ss.PHASE_CODE, driver_pid=me, driver_pid_created=created,
                driver_image="ovms.exe")
    res, sentinel, swap_p, calls = _reconcile(tmp_path, state=st)
    assert calls == [] and sentinel.exists()
    assert ss.read_swap_state(swap_p).phase == ss.PHASE_RECOVERED


def test_reconcile_matching_identity_is_hands_off_real_probe(tmp_path):
    # Full identity match (pid + create-time + image) on a live process = a HEALTHY
    # swap: hands-off entirely (#758 semantics through the new probe).
    import os

    import psutil

    proc = psutil.Process(os.getpid())
    st = _state(phase=ss.PHASE_CODE, driver_pid=proc.pid,
                driver_pid_created=float(proc.create_time()),
                driver_image=proc.name())
    res, sentinel, swap_p, calls = _reconcile(tmp_path, state=st)
    assert "still running" in res.message.lower()
    assert sentinel.exists() and calls == []
    assert ss.read_swap_state(swap_p).phase == ss.PHASE_CODE   # NOT stamped


def test_reconcile_dead_driver_kill_path_still_fires(tmp_path):
    # (c) control ON: identity evidence says the driver is GONE (a genuine crash)
    # -> the destructive convergence still fires for a post-load phase. Injected
    # verdict for determinism (a real "dead" pid can be re-worn between spawn and
    # probe on Windows, which would flip the verdict to "reused").
    st = _state(phase=ss.PHASE_CODE, driver_pid=4242, driver_pid_created=99.0)
    res, sentinel, swap_p, calls = _reconcile(
        tmp_path, state=st, liveness=ss.DRIVER_DEAD
    )
    assert res.in_flight is True
    assert not sentinel.exists() and calls == [1]   # full recovery still works
    assert ss.read_swap_state(swap_p).phase == ss.PHASE_RECOVERED


def test_reconcile_injected_reused_verdict_refuses(tmp_path):
    # (b) through the injection seam: the reconcile's refusal keys off the verdict,
    # not off any incidental probe detail.
    st = _state(phase=ss.PHASE_CODE, driver_pid=4242, driver_pid_created=99.0)
    res, sentinel, swap_p, calls = _reconcile(
        tmp_path, state=st, liveness=ss.DRIVER_REUSED
    )
    assert calls == [] and sentinel.exists()
    assert ss.read_swap_state(swap_p).phase == ss.PHASE_RECOVERED


def test_reconcile_pre_load_phase_converges_record_only(tmp_path):
    # Phase allowlist: a record stranded at HANDOFF (the AO-side write; the driver
    # never took over — the 2026-07-15 stranded-state shape) armed no sentinel and
    # loaded no OVMS, so the reconcile converges the RECORD only.
    st = _state(phase=ss.PHASE_HANDOFF)   # driver_pid 0 -> unstamped -> crash path
    res, sentinel, swap_p, calls = _reconcile(tmp_path, state=st)
    assert res.in_flight is True
    assert sentinel.exists() and calls == []   # destructive arms NEVER fired
    assert ss.read_swap_state(swap_p).phase == ss.PHASE_RECOVERED


def test_reconcile_unrecognized_phase_never_kills(tmp_path):
    # Deny-by-default: an unknown/corrupt phase is not on the may-stop allowlist —
    # a record we cannot interpret must not authorize a kill.
    st = _state(phase="GARBAGE-PHASE")
    res, sentinel, swap_p, calls = _reconcile(tmp_path, state=st)
    assert sentinel.exists() and calls == []
    assert ss.read_swap_state(swap_p).phase == ss.PHASE_RECOVERED


def test_driver_liveness_real_probe_verdicts():
    # The four-valued probe over REAL process facts (this pytest process).
    import os

    import psutil

    proc = psutil.Process(os.getpid())
    me, created, image = proc.pid, float(proc.create_time()), proc.name()
    assert ss.driver_liveness(
        _state(driver_pid=me, driver_pid_created=created, driver_image=image)
    ) == ss.DRIVER_ALIVE
    assert ss.driver_liveness(
        _state(driver_pid=me, driver_pid_created=created - 3600.0)
    ) == ss.DRIVER_REUSED
    assert ss.driver_liveness(
        _state(driver_pid=me, driver_pid_created=created, driver_image="ovms.exe")
    ) == ss.DRIVER_REUSED
    assert ss.driver_liveness(_state(driver_pid=0)) == ss.DRIVER_UNSTAMPED
    assert ss.driver_liveness(None) == ss.DRIVER_UNSTAMPED
    # driver_alive stays the thin boolean verdict over the same probe.
    assert ss.driver_alive(
        _state(driver_pid=me, driver_pid_created=created, driver_image=image)
    ) is True
    assert ss.driver_alive(
        _state(driver_pid=me, driver_pid_created=created - 3600.0)
    ) is False


def test_driver_liveness_exited_child_is_dead_or_reused():
    # A REAL exited child: its pid is either gone (dead) or already re-worn by a
    # stranger (reused) — both verdicts are non-alive and, critically, only "dead"
    # may kill. Never "alive": an exited driver can never read as healthy.
    import subprocess
    import sys

    import psutil

    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        created = float(psutil.Process(child.pid).create_time())
    finally:
        child.kill()
        child.wait(timeout=10)
    verdict = ss.driver_liveness(
        _state(driver_pid=child.pid, driver_pid_created=created)
    )
    assert verdict in (ss.DRIVER_DEAD, ss.DRIVER_REUSED)


def test_driver_stamp_carries_image_name(tmp_path):
    # The driver's phase writes carry the #902 image stamp end to end, and the
    # read-back verifies ALIVE against this real process.
    from shared.fleet import swap_driver as sd

    p = tmp_path / "swap.json"
    driver = sd.SwapDriver(
        run_id="R1", session_id="s1", tasks=[],
        swap_state_path=p, ops=None, sleep=lambda _s: None,
    )
    driver._phase(ss.PHASE_CODE)
    st = ss.read_swap_state(p)
    assert st is not None and st.driver_image != "", (
        "the phase write dropped the #902 image stamp — the reconciler loses its "
        "second identity axis"
    )
    assert ss.driver_liveness(st) == ss.DRIVER_ALIVE
