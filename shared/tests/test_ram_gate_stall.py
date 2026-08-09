"""#1274 — the RAM gate stops waiting when headroom is not clearing.

MEASURED INCIDENT, 2026-08-06 07:52. A manually triggered battery run
(``battery-bootstrap.ps1 -Now``) measured 19.4 GiB against the wrapper's 20.5 GiB fast-path
gate, proceeded — the ``-Now`` path warns and never blocks, by design, because a human is
watching — and the swap driver then sat the FULL ``RAM_GATE_TIMEOUT_S`` (1800 s) at
19.7 GiB before aborting against its 20 GiB gate. Thirty minutes and a STALLED[HARNESS]
scorecard spent re-reading a number that never moved, because the shortfall was RESIDENT
processes (the development tooling itself), not pages still being reclaimed.

The distinction these locks pin is the whole point, and it is why the fix is not simply
"wait less": ``RAM_GATE_TIMEOUT_S`` exists for pressure that is CLEARING (#1128 — the
admission probe's own 30B-unload and 14B reboot still returning pages, where a single
snapshot false-aborted a whole job in ~100 s). Shortening the window would re-open #1128.
What is safe to cut is the case where availability is provably not moving at all.

So both directions are locked here, and neither is optional: a STALLED system must exit
early, and a CLEARING system must still get its full settling room.
"""

from __future__ import annotations

from pathlib import Path

from shared.fleet import swap_driver as sd


def _driver(tmp_path: Path, readings: list[float], *, gate_gb: float = 20.0):
    """A driver whose ``available_gb`` walks *readings* (the last value repeats forever),
    with instant sleeps so the test measures POLL COUNT rather than wall-clock."""
    seen: list[float] = []

    def _available() -> float:
        value = readings[min(len(seen), len(readings) - 1)]
        seen.append(value)
        return value

    ops = sd.SwapOps(
        available_gb=_available,
        backend_alive=lambda: False,
        load_30b=lambda: True,
        wait_ready=lambda: True,
        run_task=lambda t: None,
        cancel_requested=lambda: False,
        disarm_watchdog=lambda: None,
        stop_ovms=lambda: None,
        write_report=lambda rid, outs: None,
        restart_launcher=lambda: None,
        backend_ready=lambda: True,
        signal_failure=lambda msg: None,
        run_job_oracle=lambda r, rel: {"status": "passed", "evidence": ""},
        write_scorecard=lambda sc: None,
    )
    driver = sd.SwapDriver(
        run_id="R1", session_id="s1", tasks=[],
        swap_state_path=tmp_path / "swap.json", ops=ops,
        gate_gb=gate_gb, sleep=lambda _s: None,
    )
    return driver, seen


def test_a_stalled_system_stops_waiting_long_before_the_full_window(tmp_path) -> None:
    """THE REGRESSION LOCK. 19.7 GiB against a 20 GiB gate, never moving — the measured
    2026-08-06 shape. Before this fix the driver polled the whole 1800 s."""
    driver, seen = _driver(tmp_path, [19.7])
    avail = driver._await_ram_clear()

    assert avail == 19.7, "it still reports the real reading, not a synthesised one"
    polls_for_full_window = sd.RAM_GATE_TIMEOUT_S / driver._ram_gate_poll_s
    assert len(seen) < polls_for_full_window, (
        f"polled {len(seen)} times; the full window would be {polls_for_full_window:.0f}. "
        "A stalled system must not consume the settling window."
    )
    # It must still wait the stall window itself — an instant abort is #1128 all over again.
    assert len(seen) >= sd.RAM_GATE_STALL_S / driver._ram_gate_poll_s


def test_a_clearing_system_still_gets_its_full_settling_room(tmp_path) -> None:
    """THE CONVERSE, and the one that matters most. #1128's incident was a system whose pages
    WERE coming back. Availability that climbs past the progress threshold must keep the
    driver waiting past the stall cutoff, all the way to the gate.

    Modelled as GRADUAL reclamation, which is what returning pages actually look like — a
    13 GB unload does not sit perfectly flat and then jump. See the named limitation in
    :data:`~shared.fleet.swap_driver.RAM_GATE_STALL_S`'s registry row: a system that shows
    ZERO movement for the whole stall window and only then clears would now abort early.
    That case is the deliberate trade, and it is why the threshold is 0.25 GiB and not 2 GiB.
    """
    stall_polls = int(sd.RAM_GATE_STALL_S / 30.0)
    # Climbs slowly but visibly: 0.05 GiB per poll clears the 0.25 GiB progress threshold
    # well inside the stall window, yet does not reach the 20 GiB gate until roughly twice
    # that many polls — so the driver must demonstrably keep waiting past the cutoff.
    readings = [19.0 + (i * 0.05) for i in range(stall_polls * 3)]
    driver, seen = _driver(tmp_path, readings)
    avail = driver._await_ram_clear()

    assert avail >= 20.0, (
        f"a clearing system reached only {avail} GiB — the early exit fired on pressure "
        "that was genuinely being reclaimed, which is the #1128 regression"
    )
    assert len(seen) > stall_polls, "it must have waited past the stall cutoff"


def test_the_early_exit_does_not_fire_when_the_gate_is_already_satisfied(tmp_path) -> None:
    """A healthy start returns immediately on the first reading — one poll, no waiting."""
    driver, seen = _driver(tmp_path, [26.0])
    assert driver._await_ram_clear() == 26.0
    assert len(seen) == 1


def test_progress_below_the_threshold_is_noise_not_reclamation(tmp_path) -> None:
    """Drift smaller than RAM_GATE_PROGRESS_GIB must NOT keep the driver waiting — otherwise
    ordinary measurement jitter re-opens the full 30-minute stall the fix exists to close."""
    driver, _seen = _driver(tmp_path, [19.7, 19.75, 19.8, 19.79, 19.8])
    driver._await_ram_clear()
    # The last reading is 19.8: 0.1 GiB above the first, under the 0.25 GiB threshold.
    assert sd.RAM_GATE_PROGRESS_GIB > 0.1, (
        "this test's fixture assumes the threshold is above the jitter it simulates"
    )


def test_the_stall_cutoff_is_registered_as_a_timeout(tmp_path) -> None:
    """Every duration this project waits on is registered — the registry is the budget SSOT,
    and an unregistered wait is one nobody can find when it misbehaves."""
    from shared import timeout_registry as tr

    names = {e.attribute for e in tr.REGISTRY}
    assert "RAM_GATE_STALL_S" in names
    entry = next(e for e in tr.REGISTRY if e.attribute == "RAM_GATE_STALL_S")
    assert entry.seconds == sd.RAM_GATE_STALL_S, "the registry and the code must agree"
    assert entry.module == "shared.fleet.swap_driver"
