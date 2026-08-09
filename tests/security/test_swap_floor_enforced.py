"""The coder swap headroom floor is ENFORCED, not merely stored (#1313).

The floor is the last thing standing between a coder dispatch and a box with too little
RAM to load the 30B. It lives in ``[fleet_dispatch].swap_min_free_gb`` and is read by
:class:`shared.fleet.swap_driver.SwapDriver` at step 8 (GATE).

WHY THIS FILE EXISTS IN ITS PRESENT SHAPE. The obvious lock —
``assert swap_min_free_gb == 19.0`` — passes whether or not a single line of code ever
READS the value. That is the built-but-wired-into-nothing shape, and it produced three
separate defects in this repo inside two days. So the load-bearing tests here drive a real
``SwapDriver`` through its real gate and assert on the OUTCOME, with the threshold resolved
from the shipped config rather than restated as a literal. The one constant assertion that
remains (``test_configured_floor_is_the_la_set_value``) is deliberately NOT the proof that
the gate works; it is the separate, narrower claim that the operator's directive is what
got written down.

Security principle 12 — every control is tested OFF: ``test_floor_is_actually_read_not_ignored``
moves the gate and proves the SAME headroom reading flips from admitted to refused. Without
it, "the driver admitted 19.1 GiB" is indistinguishable from "the driver admits everything".
"""

from __future__ import annotations

import inspect
import re
import tomllib
from pathlib import Path

from shared.fleet import swap_driver as sd

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG = _REPO_ROOT / "services" / "assistant_orchestrator" / "config" / "default.toml"

#: The LA-set floor (#1313, 2026-08-07). A DIRECTIVE, not a measurement: no supervised 30B
#: load has been run at 19 GiB, and 19 sits 0.85 GiB below #777's measured 19.85 GiB success.
#: Named here so that changing the shipped floor without revisiting this file fails loudly.
_LA_SET_FLOOR_GIB = 19.0

#: How far either side of the floor the behavioural tests probe. Small enough that nothing
#: but the gate comparison itself can explain the difference in outcome.
_MARGIN_GIB = 0.1


def _configured_floor() -> float:
    """The floor as SHIPPED — read from default.toml, never restated as a literal."""
    with _CONFIG.open("rb") as fh:
        return float(tomllib.load(fh)["fleet_dispatch"]["swap_min_free_gb"])


def _run_driver_at(tmp_path, available_gb: float, *, gate_gb: float):
    """Drive a real SwapDriver through a real gate at a fixed headroom reading.

    Every side effect is injected, so the only thing under test is the gate decision. The
    wait-verify window is collapsed (``ram_gate_timeout_s=0.0``) because these cases are
    about the THRESHOLD, not about #1128's patience for headroom that is still clearing —
    that behaviour has its own tests in tests/integration/test_swap_driver.py.
    """
    calls: list = []
    ops = sd.SwapOps(
        available_gb=lambda: available_gb,
        backend_alive=lambda: False,
        load_30b=lambda: (calls.append("load"), True)[1],
        wait_ready=lambda: True,
        run_task=lambda t: (calls.append(("task", t["task"])), None)[1],
        cancel_requested=lambda: False,
        disarm_watchdog=lambda: calls.append("disarm"),
        stop_ovms=lambda: calls.append("stop"),
        write_report=lambda rid, outs: calls.append(("report", rid)),
        restart_launcher=lambda: calls.append("restart"),
        backend_ready=lambda: True,
        signal_failure=lambda msg: calls.append(("signal", msg)),
    )
    driver = sd.SwapDriver(
        run_id="R1", session_id="s1", tasks=[],
        swap_state_path=tmp_path / "swap.json", ops=ops,
        gate_gb=gate_gb, sleep=lambda _s: None,
        ram_gate_timeout_s=0.0, ram_gate_poll_s=0.0,
    )
    return driver.run(), calls


# ---- the floor is what the operator set --------------------------------------


def test_configured_floor_is_the_la_set_value():
    """The shipped config carries the operator's directive — and ONLY this test says so.

    Deliberately narrow: it proves the number was written down, nothing more. The proof
    that anything obeys it lives in the behavioural tests below.
    """
    assert _configured_floor() == _LA_SET_FLOOR_GIB


# ---- the floor is ENFORCED (the load-bearing pair) ---------------------------


def test_driver_refuses_just_below_the_configured_floor(tmp_path):
    """0.1 GiB short of the shipped floor: gate-abort, no 30B load, assistant restored."""
    floor = _configured_floor()
    res, calls = _run_driver_at(tmp_path, floor - _MARGIN_GIB, gate_gb=floor)

    assert res.outcome == "gate-abort"
    assert not res.loaded_30b
    assert "load" not in calls           # the 30B was never touched
    assert "restart" in calls            # NEVER-ZERO: the 14B assistant comes back


def test_driver_admits_just_above_the_configured_floor(tmp_path):
    """0.1 GiB over the shipped floor: the gate passes and the 30B loads.

    Without this half, a gate that refused EVERYTHING would satisfy the refusal test above
    and the floor would read as working while blocking every dispatch — which is the exact
    complaint (#1313) that caused the floor to be lowered in the first place.
    """
    floor = _configured_floor()
    res, calls = _run_driver_at(tmp_path, floor + _MARGIN_GIB, gate_gb=floor)

    assert res.outcome != "gate-abort"
    assert res.loaded_30b
    assert "load" in calls


# ---- the control, tested OFF (principle 12) ----------------------------------


def test_floor_is_actually_read_not_ignored(tmp_path):
    """Move the gate above a previously-admitted reading; it must now refuse.

    This is what separates "the driver enforces the configured floor" from "the driver
    happens to admit this number". Same headroom, higher gate, opposite outcome — so the
    gate value is demonstrably consulted rather than stored and forgotten.
    """
    floor = _configured_floor()
    admitted_reading = floor + _MARGIN_GIB

    res_low, _ = _run_driver_at(tmp_path / "a", admitted_reading, gate_gb=floor)
    res_high, calls_high = _run_driver_at(
        tmp_path / "b", admitted_reading, gate_gb=admitted_reading + _MARGIN_GIB
    )

    assert res_low.loaded_30b, "precondition: this reading clears the shipped floor"
    assert res_high.outcome == "gate-abort"
    assert "load" not in calls_high


# ---- the fallback can never be laxer than the shipped floor ------------------


def test_driver_fallback_default_is_not_laxer_than_the_shipped_floor():
    """``SwapDriver``'s own ``gate_gb`` default: a fallback for a caller that passes none.

    NOTE ON REACH (found by pre-merge review, #1313): this default is currently
    UNREACHABLE by any gate decision — every production construction passes ``gate_gb``
    explicitly, and the two call sites that omit it never invoke ``run()``. It is guarded
    anyway, cheaply, so it cannot drift into being reachable and wrong at the same time.
    The fallback that CAN fire is guarded by the test below — do not delete that one
    believing this covers it, which is the mistake this note exists to prevent.

    Direction matters: a stale HIGHER fallback is merely conservative, a stale LOWER one
    silently admits swaps the operator's floor refuses. Only the second is a defect.
    """
    default = inspect.signature(sd.SwapDriver.__init__).parameters["gate_gb"].default
    assert default >= _configured_floor()


def test_reachable_spec_fallback_is_not_laxer_than_the_shipped_floor():
    """The fallback that actually decides a live swap: ``swap_ops``' spec rehydration.

    The detached driver is rebuilt from a persisted ``spec`` dict, so the value that gates
    a real swap when that dict lacks ``gate_gb`` is the literal in
    ``spec.get("gate_gb", ...)`` — NOT ``SwapDriver``'s signature default. A spec written
    by an older AO across an upgrade, or by hand, takes exactly that path.

    Asserted by source scan because the literal lives inside a function body and cannot be
    introspected. The scan also pins the SITE COUNT: a second such fallback appearing
    anywhere in the module is itself the finding, since it would be a second place for the
    floor to drift out of lockstep silently.
    """
    src = (_REPO_ROOT / "shared" / "fleet" / "swap_ops.py").read_text(encoding="utf-8")
    sites = re.findall(r"""spec\.get\(\s*["']gate_gb["']\s*,\s*([0-9.]+)\s*\)""", src)

    assert len(sites) == 1, (
        f"expected exactly one gate_gb spec fallback in swap_ops.py, found {len(sites)}: "
        f"{sites} — every one of them can gate a live swap"
    )
    assert float(sites[0]) >= _configured_floor(), (
        f"the reachable spec fallback ({sites[0]}) is LAXER than the shipped floor "
        f"({_configured_floor()}) — it would admit swaps the operator's gate refuses"
    )


# ---- the config comment cannot quietly outlive the value it explains ---------


def test_config_comment_does_not_claim_the_floor_is_measured():
    """The 19 GiB floor is a directive, and the config must not describe it as measured.

    A future raise back to a measured value should update this prose; a future LOWER
    unmeasured value must keep the honesty. Guards the specific rot named in CLAUDE.md:
    a time-anchored comment decaying into a false safety assertion.
    """
    text = _CONFIG.read_text(encoding="utf-8")
    # rsplit on a MISSING separator silently returns the whole string, which would widen
    # this search to the entire file and let it pass on unrelated prose. Pin the anchor.
    assert text.count("# Increment-2 swap") == 1, (
        "the comment-block anchor moved or duplicated; this test would otherwise degrade "
        "into scanning the whole file and passing on any unrelated text"
    )
    block = text.split("swap_min_free_gb")[0].rsplit("# Increment-2 swap", 1)[-1]
    assert "NOT a measurement" in block, (
        "the swap_min_free_gb comment must state plainly that the current floor is an "
        "operator directive rather than a measured result"
    )
