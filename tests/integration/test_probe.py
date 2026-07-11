"""Tests for the #784 probe-not-predict swap admission.

``run_probe`` is pure over an injected :class:`~tools.dispatch_harness.probe.ProbeOps`
(the AoReensurer / SwapOps injection pattern), so every path — happy, load-fail,
below-floor, exception-mid-load, restore-failure — is driven here with fake callables:
no socket, no process, no GPU. The live wiring (``build_real_probe_ops`` /
``_real_stop_ao`` / ``_real_restore``) is thin glue over legs that are themselves
verified on-hardware; its correctness is the daylight live probe run.

The load-order invariant every restore test asserts: the AO is ALWAYS restored once
the floor is cleared, and NEVER touched when it is not.
"""

from __future__ import annotations

import json

import pytest

from tools.dispatch_harness import probe as pr


def _record():
    """A tiny effect recorder — appends the leg name in call order."""
    calls: list[str] = []
    return calls


def _ops(
    calls,
    *,
    available: float,
    loaded: bool = True,
    ready: bool = True,
    stop_result: dict | None = None,
    load_raises: BaseException | None = None,
    restore_raises: Exception | None = None,
    clock=None,
) -> pr.ProbeOps:
    """Build a ProbeOps whose every seam records into *calls*."""
    def _avail() -> float:
        calls.append("available")
        return available

    def _stop() -> dict:
        calls.append("stop_ao")
        return stop_result or {"stopped": True, "pid": 4321}

    def _load() -> bool:
        calls.append("load_30b")
        if load_raises is not None:
            raise load_raises
        return loaded

    def _wait() -> bool:
        calls.append("wait_ready")
        return ready

    def _restore() -> None:
        calls.append("restore")
        if restore_raises is not None:
            raise restore_raises

    return pr.ProbeOps(
        available_gb=_avail,
        stop_ao=_stop,
        load_30b=_load,
        wait_ready=_wait,
        restore=_restore,
        log=lambda _m: None,
        clock=clock or (lambda: 0.0),
    )


# ---- happy path -----------------------------------------------------------


def test_happy_path_ready_exit_0_and_restores():
    calls = _record()
    # A clock that advances 13s across the load, so load_seconds is measured.
    ticks = iter([100.0, 113.0])
    ops = _ops(calls, available=19.85, clock=lambda: next(ticks))
    res = pr.run_probe(ops, min_free_gb=15.0, timeout_s=480.0)
    assert res.exit_code == pr.EXIT_READY
    assert res.outcome == "READY"
    assert res.available_gb == pytest.approx(19.85)
    assert res.load_seconds == pytest.approx(13.0)
    # Full ordered sequence incl. the always-run restore.
    assert calls == ["available", "stop_ao", "load_30b", "wait_ready", "restore"]


# ---- load-fail path (restore STILL runs) ----------------------------------


def test_load_returns_false_exit_1_and_restores():
    calls = _record()
    ops = _ops(calls, available=18.0, loaded=False)
    res = pr.run_probe(ops, min_free_gb=15.0, timeout_s=480.0)
    assert res.exit_code == pr.EXIT_LOAD_FAILED
    assert res.outcome == "LOAD_FAILED"
    # wait_ready is skipped when the load itself failed; restore still runs.
    assert calls == ["available", "stop_ao", "load_30b", "restore"]


def test_loaded_but_never_ready_exit_1_and_restores():
    calls = _record()
    ops = _ops(calls, available=20.0, loaded=True, ready=False)
    res = pr.run_probe(ops, min_free_gb=15.0, timeout_s=480.0)
    assert res.exit_code == pr.EXIT_LOAD_FAILED
    assert "never served" in res.detail
    assert calls == ["available", "stop_ao", "load_30b", "wait_ready", "restore"]


# ---- below-floor (exit 3, ZERO side effects) ------------------------------


def test_below_floor_exit_3_touches_nothing():
    calls = _record()
    ops = _ops(calls, available=14.4)
    res = pr.run_probe(ops, min_free_gb=15.0, timeout_s=480.0)
    assert res.exit_code == pr.EXIT_BELOW_FLOOR
    assert res.outcome == "BELOW_FLOOR"
    # ONLY the measurement — no stop, no load, no restore.
    assert calls == ["available"]


def test_floor_boundary_equal_is_admitted():
    # Available == floor is NOT below the floor -> it attempts (>= semantics).
    calls = _record()
    ops = _ops(calls, available=15.0)
    res = pr.run_probe(ops, min_free_gb=15.0, timeout_s=480.0)
    assert res.exit_code == pr.EXIT_READY
    assert calls == ["available", "stop_ao", "load_30b", "wait_ready", "restore"]


# ---- exception mid-load (restore runs, exit 2) ----------------------------


def test_unexpected_exception_mid_load_exit_2_and_restores():
    calls = _record()
    ops = _ops(calls, available=19.0, load_raises=RuntimeError("gpu vanished"))
    res = pr.run_probe(ops, min_free_gb=15.0, timeout_s=480.0)
    assert res.exit_code == pr.EXIT_ERROR
    assert res.outcome == "ERROR"
    assert "gpu vanished" in res.detail
    # stop_ao fired, load raised, restore STILL runs.
    assert calls == ["available", "stop_ao", "load_30b", "restore"]


def test_keyboard_interrupt_is_aborted_exit_1_and_restores():
    calls = _record()
    ops = _ops(calls, available=19.0, load_raises=KeyboardInterrupt())
    res = pr.run_probe(ops, min_free_gb=15.0, timeout_s=480.0)
    assert res.exit_code == pr.EXIT_LOAD_FAILED
    assert res.outcome == "ABORTED"
    assert calls == ["available", "stop_ao", "load_30b", "restore"]


# ---- restore-failure is LOUD but the exit code is preserved ---------------


def test_restore_raising_does_not_mask_the_exit_code():
    calls = _record()
    ops = _ops(
        calls,
        available=19.85,
        restore_raises=OSError("reboot spawn failed"),
    )
    # The restore raises in the finally; run_probe must still return READY (0),
    # never propagate the restore error.
    res = pr.run_probe(ops, min_free_gb=15.0, timeout_s=480.0)
    assert res.exit_code == pr.EXIT_READY
    assert res.outcome == "READY"
    assert calls[-1] == "restore"


def test_restore_raising_preserves_a_load_failure_code():
    calls = _record()
    ops = _ops(
        calls, available=18.0, loaded=False, restore_raises=OSError("boom")
    )
    res = pr.run_probe(ops, min_free_gb=15.0, timeout_s=480.0)
    assert res.exit_code == pr.EXIT_LOAD_FAILED  # not masked to an error by the restore


# ---- --json shape ---------------------------------------------------------


def test_json_line_shape_is_stable():
    res = pr.ProbeResult(
        exit_code=pr.EXIT_READY,
        outcome="READY",
        available_gb=19.853,
        min_free_gb=15.0,
        load_seconds=12.61,
        detail="30B loaded and served in 12.6s",
    )
    data = json.loads(res.json_line())
    assert data == {
        "schema": "probe/v1",
        "outcome": "READY",
        "exit_code": 0,
        "available_gb": 19.85,
        "min_free_gb": 15.0,
        "load_seconds": 12.6,
        "detail": "30B loaded and served in 12.6s",
    }


def test_json_line_is_single_line():
    res = pr.ProbeResult(
        exit_code=pr.EXIT_BELOW_FLOOR, outcome="BELOW_FLOOR",
        available_gb=14.4, min_free_gb=15.0,
    )
    assert "\n" not in res.json_line()


# ---- timeout-registry compliance (no new timeout minted) ------------------


def test_default_timeout_is_the_registered_start_llm_ceiling(monkeypatch):
    """The probe deliberately reuses the REGISTERED START_LLM_TIMEOUT_S rather than
    minting a new timeout (registry governance: pull a fitting budget if one exists).
    Drive ``main`` with only the required arg and capture the timeout it threads —
    a drift from the registered constant would fail here AND in the registry gate."""
    from shared.fleet.swap_ops import START_LLM_TIMEOUT_S

    assert START_LLM_TIMEOUT_S == 480.0
    captured: dict = {}

    def _fake_build_ops(*, timeout_s, log, repo_root=None):
        captured["build_timeout_s"] = timeout_s
        return _ops(_record(), available=100.0)  # never actually loads (floor cleared, all fakes)

    def _fake_run_probe(ops, *, min_free_gb, timeout_s):
        captured["run_timeout_s"] = timeout_s
        return pr.ProbeResult(
            exit_code=pr.EXIT_READY, outcome="READY",
            available_gb=100.0, min_free_gb=min_free_gb,
        )

    monkeypatch.setattr(pr, "build_real_probe_ops", _fake_build_ops)
    monkeypatch.setattr(pr, "run_probe", _fake_run_probe)
    code = pr.main(["--min-free-gb", "15.0", "--json"])
    assert code == pr.EXIT_READY
    assert captured["build_timeout_s"] == START_LLM_TIMEOUT_S
    assert captured["run_timeout_s"] == START_LLM_TIMEOUT_S
