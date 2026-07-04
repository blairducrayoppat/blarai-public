"""Tests — guaranteed-termination step-aside watchdog (#670 Phase-B run-1 fix C).

``should_force_exit`` is pure; ``force_exit_watchdog`` is driven over an injected clock
+ ``hard_exit`` (never a real ``os._exit``). The actual process death + GPU release are
live-only at the on-hardware re-run.
"""

from __future__ import annotations

from launcher.step_aside import force_exit_watchdog, should_force_exit


def test_force_when_interrupt_not_delivered_after_grace():
    # cleanup never started + past the short deliver grace -> the wedged case -> force.
    assert should_force_exit(
        elapsed_s=4.0, cleanup_started=False, deliver_grace_s=4.0, teardown_max_s=30.0
    )


def test_no_force_before_deliver_grace():
    assert not should_force_exit(
        elapsed_s=3.9, cleanup_started=False, deliver_grace_s=4.0, teardown_max_s=30.0
    )


def test_no_force_while_teardown_in_progress():
    # delivered (cleanup running) + under the teardown budget -> let it finish.
    assert not should_force_exit(
        elapsed_s=20.0, cleanup_started=True, deliver_grace_s=4.0, teardown_max_s=30.0
    )


def test_force_backstop_when_teardown_overruns():
    assert should_force_exit(
        elapsed_s=30.0, cleanup_started=True, deliver_grace_s=4.0, teardown_max_s=30.0
    )


def test_watchdog_forces_exit_on_wedge():
    # Wedged: cleanup never starts. The watchdog must hard_exit(0) once the deliver grace
    # passes — driven over a fake clock, no real os._exit.
    calls: list[int] = []
    clock = {"t": 0.0}
    force_exit_watchdog(
        lambda: False,  # cleanup never starts (interrupt not delivered)
        deliver_grace_s=4.0,
        teardown_max_s=30.0,
        poll_s=1.0,
        sleep=lambda s: clock.__setitem__("t", clock["t"] + s),
        monotonic=lambda: clock["t"],
        hard_exit=lambda code: calls.append(code),
    )
    assert calls == [0]


def test_watchdog_backstop_fires_at_teardown_max():
    # Delivered but never completes (cleanup_started True, process never exits) -> the
    # backstop forces at teardown_max, never before.
    fired: list[tuple[float, int]] = []
    clock = {"t": 0.0}
    force_exit_watchdog(
        lambda: True,  # delivered + running, but never finishes
        deliver_grace_s=4.0,
        teardown_max_s=10.0,
        poll_s=1.0,
        sleep=lambda s: clock.__setitem__("t", clock["t"] + s),
        monotonic=lambda: clock["t"],
        hard_exit=lambda code: fired.append((clock["t"], code)),
    )
    assert fired == [(10.0, 0)]


# ---- (2a) graceful 14B GPU-unload before the force-exit (#670 run-2) --------


def test_watchdog_unloads_gpu_before_force_exit():
    # On force-exit, the 14B GPU release MUST run BEFORE the hard exit so the incoming 30B
    # loads onto a clean GPU (run-2: os._exit alone left the GPU to the OS's reclaim luck).
    events: list = []
    clock = {"t": 0.0}
    force_exit_watchdog(
        lambda: False,  # wedged (the WinUI case) -> force at the deliver grace
        unload_gpu=lambda: events.append("unload"),
        deliver_grace_s=4.0,
        teardown_max_s=30.0,
        poll_s=1.0,
        sleep=lambda s: clock.__setitem__("t", clock["t"] + s),
        monotonic=lambda: clock["t"],
        hard_exit=lambda code: events.append(("exit", code)),
        run_unload=lambda fn, _t: bool(fn()) or True,  # synchronous, for the ordering assert
    )
    assert events == ["unload", ("exit", 0)]  # unload strictly BEFORE the hard exit


def test_watchdog_without_unload_still_force_exits():
    # No unload_gpu wired -> the termination guarantee still holds.
    fired: list[int] = []
    clock = {"t": 0.0}
    force_exit_watchdog(
        lambda: False,
        unload_gpu=None,
        deliver_grace_s=4.0,
        teardown_max_s=30.0,
        poll_s=1.0,
        sleep=lambda s: clock.__setitem__("t", clock["t"] + s),
        monotonic=lambda: clock["t"],
        hard_exit=lambda code: fired.append(code),
    )
    assert fired == [0]


def test_bounded_unload_completes_fast():
    from launcher.step_aside import _bounded_unload

    done: list[int] = []
    assert _bounded_unload(lambda: done.append(1), timeout_s=2.0) is True
    assert done == [1]


def test_bounded_unload_times_out_on_hang_without_blocking():
    import threading as _t

    from launcher.step_aside import _bounded_unload

    block = _t.Event()
    # A hung unload must NOT block the exit: the bounded wait returns False quickly.
    assert _bounded_unload(lambda: block.wait(), timeout_s=0.2) is False
    block.set()  # release the daemon thread
