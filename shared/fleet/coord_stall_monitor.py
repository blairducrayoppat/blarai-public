"""Coordinator stall-comment cycle — deduped one-comment-per-episode posting (#844 C2).

The C2 stall-comments limb's ACTOR half (ADR-039 §2.8). Ties together the pure
detection/dedup math (:mod:`shared.fleet.coord_lifecycle`) and the cross-cycle
seen-set state (:mod:`shared.fleet.coord_stall_state`): given the stalls detected
this cycle, it posts EXACTLY ONE Vikunja comment per NEW stall (outcomes-only,
never one per cycle), updates the seen-set with EPISODE semantics, and returns a
structured result the operator surface renders.

The seen-set algebra IS the anti-firehose + episode contract, in one place::

    already_seen = <the persisted set from prior cycles>
    current      = {s.fingerprint for s in this cycle's stalls}
    new          = current - already_seen   # never-yet-commented -> one comment each
    ongoing      = already_seen & current   # still stalled, already commented -> silent
    cleared      = already_seen - current    # stall resolved -> PRUNE (episode ends)
    persisted    = ongoing | {posted new}    # only SUCCESSFULLY-posted new joins

Three consequences fall out by construction: (1) a stall detected every cycle is
commented ONCE — after the first cycle its fingerprint is in ``already_seen`` and
moves to ``ongoing``; (2) a NEW stall whose comment POST FAILED is NOT persisted,
so the next cycle retries it rather than silently dropping the only notice (a
Vikunja outage delays a comment, never loses it); (3) a cleared fingerprint is
pruned, so a task that re-stalls later is a fresh EPISODE with a fresh comment.

FAIL-SOFT (ADR-039 §2.12.6, mirrored from the #749 bridge): a comment post that
raises or returns ``False`` is recorded as a failure and the cycle proceeds — a
ticket-board outage must never crash a dispatch/heartbeat cycle. The post itself
is an injected callable, so this module has no hard dependency on a live Vikunja
bridge; the production caller wires
:func:`shared.fleet.vikunja_bridge.post_task_comment`.

DORMANCY: no production boot path calls :func:`run_stall_cycle` today. The C3
heartbeat / a C2 dispatch-event hook wires it later, dormant behind
``[coordinator]``. Importing this module arms nothing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence

from shared.fleet.coord_lifecycle import StallSignal, new_stall_signals
from shared.fleet.coord_stall_state import (
    StallSeenState,
    read_seen_state,
    write_seen_state,
)

logger = logging.getLogger(__name__)

#: ``(task_id, comment_markdown) -> posted_ok``. The production wiring is
#: :func:`shared.fleet.vikunja_bridge.post_task_comment` (fail-soft, loopback-
#: pinned, 2 s cap); a test injects a fake. A callable that RAISES is treated as a
#: failed post (caught in :func:`_try_post`), so a caller need not be
#: exception-clean itself.
PostComment = Callable[[int, str], bool]


@dataclass(frozen=True)
class StallCycleResult:
    """What one stall cycle did — the operator surface + tests read this."""

    posted: tuple[StallSignal, ...]
    """NEW stalls whose comment posted successfully this cycle (one comment each)."""

    ongoing: tuple[StallSignal, ...]
    """Stalls still present that were already commented in a prior cycle — silent."""

    cleared: frozenset[str]
    """Fingerprints pruned this cycle (their stall resolved — the episode ended)."""

    current: tuple[StallSignal, ...]
    """Every stall detected this cycle (posted + ongoing + any post-failed)."""

    post_failures: tuple[tuple[StallSignal, str], ...] = ()
    """NEW stalls whose post FAILED (retried next cycle) + the failure reason."""


def render_stall_comment(signal: StallSignal) -> str:
    """The outcomes-only comment text for one stall — deliberately TITLE-FREE.

    The comment is posted ON the stalled ticket, so the ticket identifies itself;
    interpolating the (untrusted, ADR-039 §2.7) ticket title would add an injection
    surface for zero benefit. The text states only deterministic facts — the class
    of service and the age — so there is nothing attacker-influenced to
    neutralize."""
    age_days = signal.age_seconds / 86400.0
    return (
        "**Coordinator — stall detected.** This item's age "
        f"({age_days:.1f}d) is a statistical outlier for its "
        f"**{signal.service_class.value}** class of service "
        "(ADR-039 §2.8 aging-outlier detection). Flagged once per stall episode; "
        "no further comment while it remains stalled."
    )


def run_stall_cycle(
    current_stalls: Sequence[StallSignal],
    *,
    seen_path: Path,
    post_comment: PostComment,
    now: datetime,
) -> StallCycleResult:
    """Post one comment per NEW stall, then update the seen-set (episode semantics).

    *current_stalls* is this cycle's detection output
    (:func:`shared.fleet.coord_lifecycle.detect_stalls`); the caller chooses the
    task population (per-project or global). *post_comment* is the fail-soft sink
    (production: :func:`shared.fleet.vikunja_bridge.post_task_comment`). *now* is
    supplied by the caller — this function reads no clock."""
    already_seen = read_seen_state(seen_path).fingerprints
    current_fingerprints = frozenset(s.fingerprint for s in current_stalls)

    new = new_stall_signals(current_stalls, already_seen)

    posted: list[StallSignal] = []
    failures: list[tuple[StallSignal, str]] = []
    for signal in new:
        ok, reason = _try_post(post_comment, signal)
        if ok:
            posted.append(signal)
        else:
            failures.append((signal, reason))

    ongoing = tuple(s for s in current_stalls if s.fingerprint in already_seen)
    cleared = already_seen - current_fingerprints

    # EPISODE prune: keep still-stalled fingerprints that were already seen, and
    # add ONLY successfully-posted new ones. A cleared fingerprint falls out (so a
    # later re-stall is a fresh episode); a failed post is NOT added (so it retries
    # next cycle rather than being silently suppressed forever).
    persisted = (already_seen & current_fingerprints) | frozenset(
        s.fingerprint for s in posted
    )
    write_seen_state(
        StallSeenState(fingerprints=persisted, updated_at=now.isoformat()),
        path=seen_path,
    )

    return StallCycleResult(
        posted=tuple(posted),
        ongoing=ongoing,
        cleared=cleared,
        current=tuple(current_stalls),
        post_failures=tuple(failures),
    )


def _try_post(post_comment: PostComment, signal: StallSignal) -> tuple[bool, str]:
    """Call *post_comment* fail-soft: a raise or a ``False`` both read as
    'not posted' (with a reason), never propagating out of the cycle."""
    try:
        ok = post_comment(signal.task_id, render_stall_comment(signal))
    except Exception as exc:  # noqa: BLE001 — a board outage must not crash the cycle
        logger.warning(
            "coord_stall_monitor: post for task %s failed (fail-soft): %s",
            signal.task_id,
            exc,
        )
        return False, f"post raised: {exc}"
    if not ok:
        return False, "post returned False (fail-soft)"
    return True, ""
