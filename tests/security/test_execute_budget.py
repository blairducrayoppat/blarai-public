"""#1353 — EXECUTE gets a budget that covers the work it actually does.

**What this cost.** Four consecutive battery nights STALLED at approve, every one reporting
*"No response from the Assistant Orchestrator"*. The assistant was never dead. EXECUTE
generates the plan's dispatch assets on the GPU before the model swap (SEAM A, 14B still
resident) at a measured 59.9 s per image, and the gateway was waiting on the 180 s per-prompt
default. Measured across three nights, it is a THRESHOLD rather than a break — nothing
regressed, the asset plan grew:

    2 images ->  98 s -> fits    -> GREEN    (night-20260807-195325)
    4 images -> 142 s -> exceeds -> STALLED  (night-20260808-230002)
    4 images -> 152 s -> exceeds -> STALLED  (night-20260809-124052)

`shared/timeout_registry.py` had already NAMED the asymmetry — *"PLAN_RESPONSE_TIMEOUT_S is
720 s for a turn that generates NOTHING, while APPROVE — which generates every asset —
inherits 180 s"* — and correctly refused to widen the shared constant, which bounds every
framed message. This is the other move that entry pointed at, and the one #766 made for PLAN:
give EXECUTE its own budget.
"""

from __future__ import annotations

import inspect

from services.ui_gateway.src import constants, transport


def test_execute_has_its_own_budget_not_the_per_prompt_default() -> None:
    """The defect in one line: EXECUTE must not inherit the message default."""
    assert constants.EXECUTE_RESPONSE_TIMEOUT_S > constants.PROMPT_RESPONSE_TIMEOUT_S


def test_the_budget_covers_the_declared_asset_plan_at_the_MEASURED_cost() -> None:
    """Sized from a recorded measurement, not from a round number that felt safe.

    B9 declares 8 assets; generation is 59.9 s/image on this hardware
    (`docs/performance/uc010_dispatch_asset_gen_2026-06-30.json`). The budget must clear that
    with room for the swap hand-off, or the threshold simply moves.
    """
    measured_per_image_s = 59.9
    declared_assets = 8
    generation_s = measured_per_image_s * declared_assets

    assert constants.EXECUTE_RESPONSE_TIMEOUT_S > generation_s, (
        f"budget {constants.EXECUTE_RESPONSE_TIMEOUT_S}s does not cover "
        f"{declared_assets} assets at {measured_per_image_s}s each ({generation_s}s)"
    )
    headroom = constants.EXECUTE_RESPONSE_TIMEOUT_S - generation_s
    assert headroom >= 300, (
        f"only {headroom:.0f}s left for the swap hand-off — too tight to absorb a slow load"
    )


def test_the_night_that_worked_would_still_have_worked() -> None:
    """98 s fit the OLD budget. A fix that changes the good case is not a fix."""
    green_night_generation_s = 98
    assert green_night_generation_s < constants.PROMPT_RESPONSE_TIMEOUT_S
    assert green_night_generation_s < constants.EXECUTE_RESPONSE_TIMEOUT_S


def test_both_stalled_nights_now_fit() -> None:
    """142 s and 152 s exceeded the old budget once the swap is added; both must now fit."""
    for stalled_generation_s in (142, 152):
        assert stalled_generation_s < constants.EXECUTE_RESPONSE_TIMEOUT_S


def test_the_shared_per_prompt_default_was_NOT_widened() -> None:
    """The registry's own reasoning, locked.

    Widening `PROMPT_RESPONSE_TIMEOUT_S` would blunt failure detection on every framed
    message to hide one path's unbudgeted work. That is why this fix is a separate constant.
    """
    assert constants.PROMPT_RESPONSE_TIMEOUT_S == 180.0


def test_execute_actually_asks_for_its_budget() -> None:
    """Reachability: a constant nothing passes is the defect wearing the fix's uniform."""
    src = inspect.getsource(transport.TransportGateway._execute_transport_call)
    assert "EXECUTE_RESPONSE_TIMEOUT_S" in src, (
        "the EXECUTE send path does not pass its own budget — it is still on the default"
    )


def test_no_response_says_WHICH_kind_of_no_response() -> None:
    """A timeout and a closed connection are different facts with different fixes.

    Collapsing them into one sentence that reads as "the assistant is dead" cost six wrong
    diagnoses across four lost nights. This is the same undiagnostic-stamp defect #1350 fixed
    for the fail-to-pass check.
    """
    # Source-level matching, with the line breaks squeezed out: the messages are built from
    # adjacent literals, so a phrase that reads contiguously to a human is split in the file.
    # (Caught by this test's own first run asserting a phrase that spans two string literals.)
    src = " ".join(
        inspect.getsource(transport.TransportGateway._execute_transport_call).split()
    )

    assert "stopped " in src and "waiting after" in src, "the timeout case must name itself"
    assert "connection closed" in src, "the closed case must name itself"
    assert "STILL WORKING" in src, (
        "the timeout message must say the assistant was probably still working - that is the "
        "sentence whose absence sent six investigations after a corpse"
    )
    # And the two cases must be DISTINGUISHABLE, not two spellings of one message.
    assert "budget" in src, "the timeout case must state the budget it exhausted"
    assert "well inside" in src, "the closed case must state that it did NOT run long"
