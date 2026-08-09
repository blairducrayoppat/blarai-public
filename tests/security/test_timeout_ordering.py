"""#1122 — an outer fail-safe must DOMINATE the inner budget it wraps.

THE INCIDENT (2026-07-27, LA-blocking). The `/dispatch` interception in the UI backend
was wrapped in `asyncio.wait_for(..., timeout=_IMAGINE_STREAM_FAILSAFE_S)` — 175 s, a
constant sized for IMAGE GENERATION. The PLAN it wraps is budgeted at
`PLAN_RESPONSE_TIMEOUT_S` = 480 s, deliberately raised 180 → 480 by #766 because a cold
PLAN (~6 chained 14B generations) legitimately exceeds 180 s.

So the operator's plan was abandoned at 175 s and **finished 28 s later** — measured in
`launcher.log`: the interception timed out at 18:20:18, `generate_plan` completed at
18:20:46. The work succeeded and was thrown away, and #766's fix was unreachable from
the UI for as long as the wrapper stayed short.

WHY THIS FILE EXISTS, AND WHY THE REGISTRY WAS NOT ENOUGH.
`shared/timeout_registry.py` held BOTH constants, with full incident prose on each, and
still could not catch this — because it records VALUES and this defect lives in a
RELATIONSHIP between two of them. A wrapper shorter than what it wraps does not protect
the inner budget, it DELETES it: the inner deadline becomes unreachable and the outer one
silently becomes the real limit. No amount of care about individual numbers finds that.

So these tests assert ORDERING, not values. Both sides may be re-tuned freely; what may
never happen again is an outer bound sinking below an inner one.

WHY NO AUTOMATED SUITE CAUGHT IT EITHER: plan latency scales with goal size. Terse
battery cards plan well inside 175 s, so the whole fleet was green while a real
operator goal — ~2,700 characters — took ~203 s and failed every time. A test over
synthetic short inputs could not have found this, which is precisely why the invariant
has to be asserted structurally rather than exercised behaviourally.
"""

from __future__ import annotations

from services.ui_backend.src import dispatcher as disp
from services.ui_gateway.src.constants import (
    PLAN_RESPONSE_TIMEOUT_S,
    PROMPT_RESPONSE_TIMEOUT_S,
)

#: Headroom the dispatch handler needs BEYOND the plan call it makes: `_create_and_plan`
#: does a git init + scaffold + first commit before planning at all, plus IPC framing.
#: Deliberately generous — the cost of over-provisioning a BACKSTOP is that a genuinely
#: wedged handler is caught a little later; the cost of under-provisioning it is this
#: entire incident.
_MIN_DISPATCH_HEADROOM_S = 30.0


def test_dispatch_failsafe_dominates_the_plan_budget_it_wraps() -> None:
    """THE REGRESSION LOCK. The /dispatch wrapper must outlive the PLAN inside it."""
    assert disp._DISPATCH_STREAM_FAILSAFE_S >= (
        PLAN_RESPONSE_TIMEOUT_S + _MIN_DISPATCH_HEADROOM_S
    ), (
        "The /dispatch interception fail-safe "
        f"({disp._DISPATCH_STREAM_FAILSAFE_S}s) must exceed the PLAN budget it wraps "
        f"({PLAN_RESPONSE_TIMEOUT_S}s) plus handler overhead. An outer bound below the "
        "inner one does not backstop the inner budget, it deletes it — the plan is "
        "abandoned while still running and completes into a closed socket (#1122)."
    )


def test_dispatch_no_longer_rides_the_imagine_failsafe() -> None:
    """The specific mistake: /dispatch borrowing a constant sized for image generation.

    Pinned as its own case because the two constants are otherwise unrelated and a
    future edit could quietly re-point the dispatch call site at the imagine value —
    which is exactly how the defect arose.
    """
    assert disp._DISPATCH_STREAM_FAILSAFE_S != disp._IMAGINE_STREAM_FAILSAFE_S, (
        "/dispatch must not share the imagine fail-safe: imagine's inner work fits in "
        "175s, a PLAN's does not (#1122)."
    )
    assert disp._IMAGINE_STREAM_FAILSAFE_S < PLAN_RESPONSE_TIMEOUT_S, (
        "sanity: the imagine fail-safe is SHORTER than the plan budget — which is why "
        "reusing it for /dispatch was a defect, not a harmless alias."
    )


def test_the_dispatch_call_site_actually_uses_the_dispatch_failsafe() -> None:
    """Reachability, not just definition (the built-but-wired-into-nothing class).

    A correctly-sized constant that no call site reads is worth nothing. This reads the
    SOURCE of the dispatch interception and asserts the wrapper it passes, because the
    defect was never in the constants — both were correct in isolation — but in which
    one the call site handed to `asyncio.wait_for`.
    """
    import inspect

    source = inspect.getsource(disp.RpcDispatcher._m_prompt)
    marker = "dispatch_handler(session_id, prompt)"
    assert marker in source, (
        "the dispatch interception call site moved — re-anchor this test rather than "
        "deleting it; it is the only check that the constant is actually WIRED."
    )
    # The wait_for wrapping the dispatch handler must name the dispatch fail-safe.
    window = source[source.index(marker) - 400: source.index(marker) + 400]
    assert "self._dispatch_failsafe_s" in window, (
        "the /dispatch interception must pass self._dispatch_failsafe_s to wait_for"
    )
    assert "self._imagine_failsafe_s" not in window, (
        "the /dispatch interception is riding the IMAGINE fail-safe again (#1122)"
    )


def test_imagine_failsafe_still_respects_its_own_socket_cap() -> None:
    """The imagine constant's original constraint is unchanged by #1122.

    Its comment justifies 175 as 'just under the 180 s per-socket receive cap'. That
    reasoning still has to hold, or fixing one ordering bug would introduce another.
    """
    assert disp._IMAGINE_STREAM_FAILSAFE_S < PROMPT_RESPONSE_TIMEOUT_S, (
        "the imagine fail-safe must stay under the per-socket receive cap so a "
        "completed generate still arrives before the socket closes"
    )


def test_both_failsafes_are_registered_in_the_timeout_registry() -> None:
    """Doctrine: every duration/budget/watchdog registers. The registry is the SSOT.

    #1122's own lesson is that registration alone is insufficient — but it remains
    necessary: an unregistered constant cannot even be reasoned about at review time.
    """
    from shared import timeout_registry as reg

    registered = {
        (e.module, e.attribute)
        for e in reg.REGISTRY
    }
    for attribute in ("_DISPATCH_STREAM_FAILSAFE_S", "_IMAGINE_STREAM_FAILSAFE_S"):
        assert ("services.ui_backend.src.dispatcher", attribute) in registered, (
            f"{attribute} must be registered in shared/timeout_registry.py"
        )


# ---- #1139: the critic progress line must not contradict the dormancy line --
#
# On battery run 20260727-230115-bd (card B2, GREEN) swap-progress.log carried these
# two lines back to back:
#   "14B code critic is DORMANT (BLARAI_ENABLE_CRITIC not seen by swap_driver) —
#    skipping the cross-model swap; this critic pass is a no-op."
#   "Running the 14B cross-model code critic on the merged diff..."
# Both cannot be true. The dormancy line was correct; the "Running…" line was emitted
# unconditionally inside the loop, where run_critic is bound to _noop_critic.
#
# This is not cosmetic. That trail is what a later session greps to answer "was this
# diff reviewed?", and B2's GREEN reads as reviewed when it was not. swap_ops.py already
# states the intent: "the observable critic_enabled flag always agree".


def test_the_running_critic_line_is_gated_on_critic_enabled() -> None:
    """Read the source: the claim must sit inside the enabled branch."""
    import inspect

    from shared.fleet import swap_driver

    source = inspect.getsource(swap_driver.SwapDriver._critic_phase)
    marker = 'Running the 14B cross-model code critic'
    assert marker in source, (
        "the critic progress line moved — re-anchor this test rather than deleting it"
    )
    # rindex, not index: the explanatory comment above the call quotes the same string,
    # and anchoring on the first hit matched the COMMENT rather than the code (caught
    # while writing this test — the same read-the-artifact-not-its-description lesson).
    before = source[: source.rindex(marker)]
    # The nearest preceding control-flow line must be the enabled check, not the loop.
    assert "if self._ops.critic_enabled:" in before.rsplit("for i in range", 1)[-1], (
        "the 'Running the critic' claim must be gated on critic_enabled (#1139) — "
        "unconditional, it contradicts the DORMANT line printed moments earlier and "
        "makes an unreviewed GREEN read as reviewed"
    )
