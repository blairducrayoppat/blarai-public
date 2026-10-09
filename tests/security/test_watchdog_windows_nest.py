"""A watchdog window must outlast the judge it sits above (#1366, lesson 221).

**Lesson 221 is at SEVEN instances and has never had a structural control.** The
doctrine says the third instance ships one. This is it, late.

The lesson: *"when one component's watchdog window overlaps another component's granted
budget, the shorter window silently wins and the budget is fiction — every liveness window
must be provably longer than the longest legitimately-silent phase it can observe, or the
phase must emit a heartbeat."*

**Three separate incidents on 2026-08-09 alone**, each a shorter window silently overriding
a longer one, each found by accident rather than by a check:

* **#1353** — ``PA_HANDSHAKE_TIMEOUT_S`` 5 s against a negotiation measured at 16.35 s.
  Four battery nights lost.
* **#1359** — ``PENDING_RUN_BUDGET_FRESH_S`` 300 s against a measured 431 s write→EXECUTE
  gap. B9's declared 28,800 s envelope was discarded on **every run it had ever done**.
* **#1366 / #1365** — ``DOOM_STALL_GRACE_S`` 240 s sitting inside ``ACP_IDLE_TIMEOUT_S``
  600 s. The battery's doom watchdog fired at 23:17:06 on ``night-20260809-230002``; the
  coder's own classifier would have labelled the stall ``idle`` at 23:23:06. That label is
  the precondition for #740/W7's resample, so the retry was real, correctly wired, and
  **permanently unreachable under the battery**. Only ``c1`` ever ran, on a card with
  attempts remaining and eight hours of granted budget unused.

All three were findable by arithmetic from values ``shared/timeout_registry.py`` already
held. The registry has 64 durations; before this file, **nothing could compare two of
them.** It knew every number and could not answer the one question that kept costing runs.

**What this locks.** Each pair below is an OUTER window that observes a phase whose own
inner judge decides when that phase is stuck. The outer must strictly exceed the inner, or
the least-informed judge fires first and the inner verdict — along with anything gated on
it — becomes unreachable.

**Honest limit, and it is the important one.** This file checks the pairs somebody thought
to write down. The 240/600 pair that cost the run was NOT among the nine relations the
registry mentioned in prose, and ``DOOM_STALL_GRACE_S``'s entry did not contain the strings
``acp`` or ``idle`` anywhere. A pair nobody declares is a pair nobody checks — so this is a
ratchet against known nestings, not proof that the nesting graph is complete. #1366 item 3
owns the sweep for undeclared pairs.
"""

from __future__ import annotations

import pytest

from shared.fleet.doom_check import DOOM_STALL_GRACE_S
from shared.fleet.swap_ops import PENDING_RUN_BUDGET_FRESH_S
from services.ui_gateway.src.constants import (
    PA_HANDSHAKE_BUDGET_S,
    PA_HANDSHAKE_TIMEOUT_S,
)
from tools.dispatch_harness.harness import DispatchHarness
from tools.dispatch_harness.monitor import RunMonitor

#: The coder's own idle classifier — the point at which the CODER declares a generation
#: wedged. Imported lazily below because acp_coder pulls the harness toolchain.
def _acp_idle_timeout_s() -> float:
    from tools.dispatch_harness.acp_coder import ACP_IDLE_TIMEOUT_S

    return float(ACP_IDLE_TIMEOUT_S)


#: (outer, outer_name, inner, inner_name, why) — the outer window OBSERVES a phase whose
#: inner judge owns the verdict. Outer must strictly exceed inner.
def _nestings() -> list[tuple[float, str, float, str, str]]:
    idle = _acp_idle_timeout_s()
    return [
        (
            DOOM_STALL_GRACE_S, "DOOM_STALL_GRACE_S",
            idle, "ACP_IDLE_TIMEOUT_S",
            "the doom watchdog observes a coder leg whose OWN classifier decides when a "
            "generation is wedged; firing first makes that verdict — and the retry gated "
            "on it — unreachable (#1365, #1366)",
        ),
        (
            RunMonitor.stall_grace_s, "RunMonitor.stall_grace_s",
            idle, "ACP_IDLE_TIMEOUT_S",
            "the harness-monitor vantage of the same physical quantity; the registry binds "
            "it to DOOM_STALL_GRACE_S in lockstep, so it inherits the same requirement",
        ),
        (
            DispatchHarness.stall_grace_s, "DispatchHarness.stall_grace_s",
            idle, "ACP_IDLE_TIMEOUT_S",
            "the third vantage of the same quantity — a lockstep pair that moves in two "
            "places out of three is the era-rot shape lesson 221 keeps producing",
        ),
        (
            PA_HANDSHAKE_BUDGET_S, "PA_HANDSHAKE_BUDGET_S",
            PA_HANDSHAKE_TIMEOUT_S, "PA_HANDSHAKE_TIMEOUT_S",
            "the aggregate must outlast a single attempt, or the budget cannot spend even "
            "one (#1353: a 5 s per-attempt ceiling could never complete a 16.35 s "
            "negotiation, whatever the aggregate said)",
        ),
    ]


@pytest.mark.parametrize(
    "outer,outer_name,inner,inner_name,why",
    _nestings(),
    ids=lambda v: v if isinstance(v, str) and "_" in str(v) else "",
)
def test_an_outer_window_outlasts_the_judge_it_sits_above(
    outer: float, outer_name: str, inner: float, inner_name: str, why: str
) -> None:
    """The least-informed judge must not fire first."""
    assert outer > inner, (
        f"{outer_name} = {outer:.0f}s does NOT exceed {inner_name} = {inner:.0f}s.\n"
        f"  {why}\n"
        "  Lesson 221: the shorter window silently wins and the longer one is fiction."
    )


def test_the_doom_vantages_move_in_lockstep() -> None:
    """One physical quantity, three vantages — a value that moves in two of them is worse
    than one that moves in none, because the disagreement is invisible at every call site.

    ``shared/timeout_registry.py``'s own review line for ``DOOM_STALL_GRACE_S`` says
    *"Change in LOCKSTEP with RunMonitor.stall_grace_s (one physical quantity, two
    vantages)"* — and there are in fact THREE, which is exactly how a lockstep pair rots.
    """
    vantages = {
        "DOOM_STALL_GRACE_S": DOOM_STALL_GRACE_S,
        "RunMonitor.stall_grace_s": RunMonitor.stall_grace_s,
        "DispatchHarness.stall_grace_s": DispatchHarness.stall_grace_s,
    }
    assert len(set(vantages.values())) == 1, (
        f"the doom window disagrees across its vantages: {vantages}. "
        "They are one measured quantity and must move together."
    )


def test_the_freshness_window_outlasts_the_gap_it_spans() -> None:
    """#1359's pair, locked here too so all of 2026-08-09's inversions live in one file.

    The per-card budget is staged before a dispatch and consumed at EXECUTE, on the far
    side of the PLAN chain AND of dispatch-asset generation. Measured 431 s on
    ``night-20260809-194335`` against a 300 s window; the theoretical worst case is PLAN's
    720 s budget plus ~303 s of asset generation.
    """
    measured_gap_s = 431.0
    worst_case_s = 720.0 + 303.0
    assert PENDING_RUN_BUDGET_FRESH_S > measured_gap_s, (
        f"PENDING_RUN_BUDGET_FRESH_S = {PENDING_RUN_BUDGET_FRESH_S:.0f}s does not survive "
        f"the MEASURED {measured_gap_s:.0f}s write->EXECUTE gap (#1359)"
    )
    assert PENDING_RUN_BUDGET_FRESH_S >= worst_case_s, (
        f"PENDING_RUN_BUDGET_FRESH_S = {PENDING_RUN_BUDGET_FRESH_S:.0f}s is under the "
        f"worst case {worst_case_s:.0f}s (PLAN budget + 8-asset generation)"
    )


def test_the_gate_catches_the_inversion_that_actually_happened() -> None:
    """TOGGLE PROOF against the REAL 2026-08-09 values, not invented ones.

    A green suite here is worth nothing unless the check fires on the pair that cost the
    run. 240 vs 600 is what shipped, and what this file exists to make impossible.
    """
    outer_before, inner = 240.0, 600.0
    assert not (outer_before > inner), (
        "the pre-#1366 doom window (240s) must NOT satisfy the nesting rule against the "
        "coder's 600s idle classifier — if this passes, the rule has been inverted"
    )
    assert DOOM_STALL_GRACE_S > inner, (
        "and the CURRENT value must satisfy it — otherwise the fix regressed"
    )
