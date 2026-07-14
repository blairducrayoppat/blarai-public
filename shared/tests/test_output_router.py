"""Locks for the C3 §7.2 output router (#845 limb 4, design §7).

The acceptance locks this limb owns, per design §11 row 4: the
zero-Vikunja-writes-in-shadow lock (spy live sinks over a REAL born-encrypted
journal — every effect journaled, zero live calls), one-digest-per-cycle,
digest-never-a-ticket-comment (behavioral AND structural — the code shape has
no path from a digest to the comment sink), machinery-health-always-live in
BOTH modes (with the structural never-reads-shadow_mode check), the
graduation seen-set reset firing exactly once on the shadow→live edge, and the
fail-loud journal-fault paths.

Everything drives the REAL router over a REAL journal (the mocks-lie lesson:
the journal, its crypto, and the seen-set algebra are the genuine articles);
only the Vikunja boundary, the operator surface, and the clock are injected
spies. The stall-comment seam is additionally driven through the REAL
``run_stall_cycle`` entry point, so §7.2's "seen-set persists on journal
success" claim is proven against the genuine episode algebra, not a
re-implementation.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from shared.coordinator import shadow_journal as sj
from shared.coordinator.heartbeat_cycle import DigestRecord, SurfacedCondition
from shared.coordinator.output_router import (
    SHADOW_MOVE_REASON,
    OutputRouter,
    RouteOutcome,
    build_output_router,
    reset_seen_set_on_graduation,
)
from shared.fleet import coord_lifecycle as cl
from shared.fleet import coord_stall_monitor as csm
from shared.fleet import vikunja_bridge as vb
from shared.fleet.coord_stall_state import StallSeenState, read_seen_state, write_seen_state

NOW = datetime(2026, 7, 14, 18, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Spies + fixture builders
# ---------------------------------------------------------------------------


class SpyMoveCard:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str, str]] = []

    def __call__(self, project_id: int, run_id: str, bucket: str) -> vb.BoardMoveResult:
        self.calls.append((project_id, run_id, bucket))
        return vb.BoardMoveResult(True, f"moved to {bucket!r}")


class SpyPostComment:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    def __call__(self, task_id: int, markdown: str) -> bool:
        self.calls.append((task_id, markdown))
        return True


class SpyOperatorSurface:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def __call__(self, message: str) -> None:
        self.messages.append(message)


class SpyDigestSurface:
    def __init__(self) -> None:
        self.digests: list[DigestRecord] = []

    def __call__(self, digest: DigestRecord) -> None:
        self.digests.append(digest)


def _digest(cycle: str = NOW.isoformat(), **overrides) -> DigestRecord:
    base = dict(
        cycle_started_at=cycle,
        mode="full",
        queue_depth={"alpha": 2},
        open_by_project={"alpha": 5},
        open_delta_by_project={},
        stalls_new=1,
        stalls_ongoing=0,
        conditions=(SurfacedCondition("gated-inventory", "1 item gated"),),
        proposals_pending=1,
        runs_harvested=("r-1",),
        model_prose="SECRET-DIGEST-PROSE",
        model_drafted=True,
    )
    base.update(overrides)
    return DigestRecord(**base)


@pytest.fixture()
def journal():
    j = sj.build_shadow_journal(":memory:")
    try:
        yield j
    finally:
        j.close()


def _router(
    journal: sj.ShadowJournal,
    *,
    shadow_mode: bool,
    move: SpyMoveCard | None = None,
    comment: SpyPostComment | None = None,
    surface: SpyOperatorSurface | None = None,
    digest_surface: SpyDigestSurface | None = None,
) -> OutputRouter:
    return build_output_router(
        shadow_mode=shadow_mode,
        journal=journal,
        live_move_card=move,
        live_post_comment=comment,
        operator_surface=surface,
        live_digest_surface=digest_surface,
        now_fn=lambda: NOW,
    )


# ---------------------------------------------------------------------------
# The zero-Vikunja-writes-in-shadow lock (#845 acceptance)
# ---------------------------------------------------------------------------


def test_shadow_mode_zero_live_calls_every_effect_journaled(journal) -> None:
    move, comment, surface = SpyMoveCard(), SpyPostComment(), SpyOperatorSurface()
    router = _router(journal, shadow_mode=True, move=move, comment=comment, surface=surface)

    assert router.post_stall_comment(41, "**stall**") is True
    result = router.move_card(3, "r-9", cl.BUCKET_DONE)
    assert result.moved is True and result.reason == SHADOW_MOVE_REASON
    assert router.route_digest(_digest()).delivered is True
    assert router.route_tripwire(
        SurfacedCondition("quiet-queue-tripwire", "3 Ready, nothing pulling")
    ).delivered is True
    assert router.record_proposal_copy({"goal": "redispatch r-9"}).delivered is True

    # ZERO live calls — the whole point of shadow.
    assert move.calls == []
    assert comment.calls == []
    # And zero operator surfacing for non-health effects.
    assert surface.messages == []

    # Every effect journaled, one entry per routed effect, right kinds.
    assert journal.count(kind=sj.KIND_STALL_COMMENT) == 1
    assert journal.count(kind=sj.KIND_BOARD_MOVE) == 1
    assert journal.count(kind=sj.KIND_DIGEST) == 1
    assert journal.count(kind=sj.KIND_TRIPWIRE_ALARM) == 1
    assert journal.count(kind=sj.KIND_PROPOSAL_COPY) == 1

    stall = journal.list_entries(kind=sj.KIND_STALL_COMMENT)[0]
    assert stall.payload == {"task_id": 41, "markdown": "**stall**"}
    board = journal.list_entries(kind=sj.KIND_BOARD_MOVE)[0]
    assert board.payload == {"project_id": 3, "run_id": "r-9", "to_bucket": cl.BUCKET_DONE}
    digest = journal.list_entries(kind=sj.KIND_DIGEST)[0]
    assert digest.payload["model_prose"] == "SECRET-DIGEST-PROSE"


def test_live_mode_routes_to_live_sinks_not_journal(journal) -> None:
    move, comment = SpyMoveCard(), SpyPostComment()
    router = _router(journal, shadow_mode=False, move=move, comment=comment)

    assert router.post_stall_comment(41, "**stall**") is True
    result = router.move_card(3, "r-9", cl.BUCKET_DONE)
    assert result.moved is True and result.reason != SHADOW_MOVE_REASON

    assert comment.calls == [(41, "**stall**")]
    assert move.calls == [(3, "r-9", cl.BUCKET_DONE)]
    assert journal.count(kind=sj.KIND_STALL_COMMENT) == 0
    assert journal.count(kind=sj.KIND_BOARD_MOVE) == 0
    # The proposal-copy journal half is shadow-only (live's record is the store).
    outcome = router.record_proposal_copy({"goal": "g"})
    assert outcome.delivered is False and outcome.destination == "none"
    assert journal.count(kind=sj.KIND_PROPOSAL_COPY) == 0


def test_shadow_stall_comment_persists_seen_set_via_real_cycle(journal, tmp_path) -> None:
    """§7.2 row 1 verbatim: the routed sink returns True on journal success, so
    the REAL run_stall_cycle persists the fingerprint and the SECOND cycle posts
    nothing — dedup behavior is gradable from the journal alone."""
    comment = SpyPostComment()
    router = _router(journal, shadow_mode=True, comment=comment)
    seen_path = tmp_path / "stall_seen.json"
    signal = cl.StallSignal(
        task_id=11,
        title="stuck item",
        service_class=cl.ServiceClass.STANDARD,
        age_seconds=200000.0,
        fingerprint=cl.stall_fingerprint(cl.ServiceClass.STANDARD, 11),
    )

    first = csm.run_stall_cycle(
        [signal], seen_path=seen_path, post_comment=router.post_stall_comment, now=NOW
    )
    assert len(first.posted) == 1
    assert read_seen_state(seen_path).fingerprints == {signal.fingerprint}

    second = csm.run_stall_cycle(
        [signal],
        seen_path=seen_path,
        post_comment=router.post_stall_comment,
        now=NOW + timedelta(minutes=15),
    )
    assert second.posted == () and len(second.ongoing) == 1

    assert journal.count(kind=sj.KIND_STALL_COMMENT) == 1  # ONE episode, ONE entry
    assert comment.calls == []  # and still zero Vikunja writes


def test_journal_fault_reads_as_failed_effect(tmp_path) -> None:
    """A broken journal in shadow mode fails SOFT in the sink shapes (a failed
    post / a non-move with the fault named) — never a raise into the cycle, and
    never a silent success that would poison the seen-set."""
    j = sj.build_shadow_journal(str(tmp_path / "j.db"), dev_mode=True)
    router = _router(j, shadow_mode=True)
    j.close()  # every append now raises (closed connection) — a REAL fault

    assert router.post_stall_comment(1, "x") is False
    moved = router.move_card(1, "r", cl.BUCKET_DONE)
    assert moved.moved is False and "shadow journal append failed" in moved.reason
    copied = router.record_proposal_copy({"goal": "g"})
    assert copied.delivered is False and "journal append failed" in copied.note


# ---------------------------------------------------------------------------
# Digest routing — one per cycle, never a ticket comment (§7.4 / F11)
# ---------------------------------------------------------------------------


def test_one_digest_per_cycle_second_refused(journal) -> None:
    router = _router(journal, shadow_mode=True)
    d = _digest()
    assert router.route_digest(d).delivered is True
    dup = router.route_digest(_digest())  # same cycle_started_at
    assert dup.delivered is False
    assert dup.destination == "refused-duplicate-digest"
    assert journal.count(kind=sj.KIND_DIGEST) == 1
    # A NEW cycle routes normally.
    nxt = router.route_digest(_digest(cycle=(NOW + timedelta(minutes=15)).isoformat()))
    assert nxt.delivered is True
    assert journal.count(kind=sj.KIND_DIGEST) == 2


def test_live_digest_default_is_journal_with_note(journal) -> None:
    """C3 ships NO live digest renderer (§7.4): live mode without an injected
    surface journals the digest WITH a note naming that fact — a deliberate,
    visible fallback."""
    router = _router(journal, shadow_mode=False)
    outcome = router.route_digest(_digest())
    assert outcome.delivered is True and outcome.destination == "journal"
    assert "not built in C3" in outcome.note
    entry = journal.list_entries(kind=sj.KIND_DIGEST)[0]
    assert "not built in C3" in entry.payload["routing_note"]


def test_live_digest_injected_surface_is_used(journal) -> None:
    surface = SpyDigestSurface()
    router = _router(journal, shadow_mode=False, digest_surface=surface)
    d = _digest()
    outcome = router.route_digest(d)
    assert outcome.delivered is True and outcome.destination == "live-digest-surface"
    assert surface.digests == [d]
    assert journal.count(kind=sj.KIND_DIGEST) == 0


def test_digest_never_reaches_the_comment_sink(journal) -> None:
    """The F11 lock, behavioral half: in BOTH modes, routing a digest never
    touches the comment sink."""
    for shadow in (True, False):
        comment = SpyPostComment()
        router = _router(journal, shadow_mode=shadow, comment=comment)
        router.route_digest(_digest(cycle=f"cycle-{shadow}"))
        assert comment.calls == []


def test_digest_route_structurally_cannot_reach_the_comment_sink() -> None:
    """The F11 lock, structural half: the digest path's code SHAPE references
    neither the live comment sink nor the bridge's comment function — there is
    no branch to flag away, the call is absent (structural absence over
    configuration, principle 4)."""
    for fn in (OutputRouter.route_digest, OutputRouter._journal_digest):  # noqa: SLF001
        names = set(fn.__code__.co_names)
        assert "_live_post_comment" not in names, fn.__qualname__
        assert "post_task_comment" not in names, fn.__qualname__
        assert "post_stall_comment" not in names, fn.__qualname__


def test_digest_journal_fault_is_fail_loud(tmp_path) -> None:
    """A digest lost to a journal fault is HEARD: the operator surface carries
    the machinery note (the route return value may be dropped by the caller,
    so the path raises its own alarm — principle 11)."""
    j = sj.build_shadow_journal(str(tmp_path / "j.db"), dev_mode=True)
    surface = SpyOperatorSurface()
    router = _router(j, shadow_mode=True, surface=surface)
    j.close()
    outcome = router.route_digest(_digest())
    assert outcome.delivered is False
    assert any("shadow-journal-fault" in m for m in surface.messages)
    # The failed cycle is NOT latched — a retry with the same key is not refused.
    assert router.route_digest(_digest()).destination != "refused-duplicate-digest"


# ---------------------------------------------------------------------------
# Tripwire routing (§7.2 row 5)
# ---------------------------------------------------------------------------


def test_tripwire_shadow_journaled_live_surfaced(journal) -> None:
    condition = SurfacedCondition("quiet-queue-tripwire", "2 Ready, WIP 0")
    surface = SpyOperatorSurface()

    shadow = _router(journal, shadow_mode=True, surface=surface)
    assert shadow.route_tripwire(condition).destination == "journal"
    assert journal.count(kind=sj.KIND_TRIPWIRE_ALARM) == 1
    assert surface.messages == []

    live = _router(journal, shadow_mode=False, surface=surface)
    assert live.route_tripwire(condition).destination == "operator-surface"
    assert journal.count(kind=sj.KIND_TRIPWIRE_ALARM) == 1  # unchanged
    assert any("quiet-queue-tripwire" in m for m in surface.messages)


def test_tripwire_health_condition_diverted_never_shadow_gated(journal) -> None:
    """Defense-in-depth on §7.2's most load-bearing row: a machinery_health
    condition mis-routed through route_tripwire still reaches the operator, in
    shadow, and is NOT journaled."""
    surface = SpyOperatorSurface()
    router = _router(journal, shadow_mode=True, surface=surface)
    outcome = router.route_tripwire(
        SurfacedCondition("substrate-unreachable", "vikunja down", machinery_health=True)
    )
    assert outcome.destination == "operator-surface"
    assert any("substrate-unreachable" in m for m in surface.messages)
    assert journal.count(kind=sj.KIND_TRIPWIRE_ALARM) == 0


# ---------------------------------------------------------------------------
# Machinery health — the operator surface ALWAYS, both modes (§7.2)
# ---------------------------------------------------------------------------


def test_machinery_health_always_live_in_both_modes(journal) -> None:
    condition = SurfacedCondition(
        "dead-man-stale", "no heartbeat stamp for 2h", machinery_health=True
    )
    for shadow in (True, False):
        surface = SpyOperatorSurface()
        router = _router(journal, shadow_mode=shadow, surface=surface)
        outcome = router.route_health(condition)
        assert outcome.delivered is True
        assert outcome.destination == "operator-surface"
        assert any("dead-man-stale" in m for m in surface.messages)
    assert journal.count() == 0  # health is NEVER journaled


def test_route_health_structurally_ignores_shadow_mode() -> None:
    """route_health's code shape never reads the routing mode — no future edit
    can quietly shadow-gate the watchdog's own alarm without failing this lock."""
    for fn in (OutputRouter.route_health, OutputRouter._surface):  # noqa: SLF001
        assert "_shadow_mode" not in set(fn.__code__.co_names), fn.__qualname__
        assert "_journal" not in set(fn.__code__.co_names), fn.__qualname__


def test_default_operator_surface_is_error_log(journal, caplog) -> None:
    router = build_output_router(shadow_mode=True, journal=journal, now_fn=lambda: NOW)
    with caplog.at_level(logging.ERROR, logger="shared.coordinator.output_router"):
        router.route_health(
            SurfacedCondition("store-fault", "TTL sweep failed", machinery_health=True)
        )
    assert any(
        r.levelno == logging.ERROR and "store-fault" in r.getMessage()
        for r in caplog.records
    )


def test_broken_operator_surface_falls_back_to_error_log(journal, caplog) -> None:
    """An injected surface that raises must not swallow the alarm it carries —
    the fallback ERROR log names both the alarm and the surface's own fault."""

    def broken(_msg: str) -> None:
        raise RuntimeError("notice path down")

    router = _router(journal, shadow_mode=False, surface=broken)  # type: ignore[arg-type]
    with caplog.at_level(logging.ERROR, logger="shared.coordinator.output_router"):
        outcome = router.route_health(
            SurfacedCondition("thread-dead", "heartbeat thread died", machinery_health=True)
        )
    assert outcome.delivered is True
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert any("thread-dead" in m and "notice path down" in m for m in messages)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_factory_requires_a_real_shadow_journal() -> None:
    with pytest.raises(TypeError):
        build_output_router(shadow_mode=True, journal=object())  # type: ignore[arg-type]


def test_factory_defaults_are_the_production_wirings(journal) -> None:
    router = build_output_router(shadow_mode=True, journal=journal)
    assert router._live_move_card is vb.move_job_card  # noqa: SLF001
    assert router._live_post_comment is vb.post_task_comment  # noqa: SLF001
    assert router._live_digest_surface is None  # noqa: SLF001 — no live renderer in C3


# ---------------------------------------------------------------------------
# Graduation hygiene — the seen-set reset (§7.2)
# ---------------------------------------------------------------------------


def _seed_seen(path: Path) -> None:
    write_seen_state(
        StallSeenState(fingerprints=frozenset({"Standard:11", "Expedite:7"}), updated_at="x"),
        path=path,
    )


def test_seen_set_reset_fires_only_on_the_shadow_to_live_edge(tmp_path) -> None:
    path = tmp_path / "stall_seen.json"
    for recorded, current in ((False, False), (True, True), (False, True), (None, False)):
        _seed_seen(path)
        assert reset_seen_set_on_graduation(recorded, current, path) is False
        assert read_seen_state(path).fingerprints == {"Standard:11", "Expedite:7"}

    _seed_seen(path)
    assert reset_seen_set_on_graduation(True, False, path, now=NOW) is True
    state = read_seen_state(path)
    assert state.fingerprints == frozenset()  # a VALID empty seen-set
    assert state.updated_at == NOW.isoformat()


def test_seen_set_reset_once_semantics_via_restamped_recording(tmp_path) -> None:
    """The caller's contract completes the ONCE: after the reset, limb 6
    re-stamps the recording as live, so the next comparison is live→live and
    resets nothing (an ongoing stall commented live is never re-fired)."""
    path = tmp_path / "stall_seen.json"
    _seed_seen(path)
    assert reset_seen_set_on_graduation(True, False, path) is True
    # A live comment lands after graduation...
    write_seen_state(
        StallSeenState(fingerprints=frozenset({"Standard:11"}), updated_at="y"), path=path
    )
    # ...and the restamped recording (now False) never resets again.
    assert reset_seen_set_on_graduation(False, False, path) is False
    assert read_seen_state(path).fingerprints == {"Standard:11"}


def test_seen_set_reset_creates_a_valid_file_when_absent(tmp_path) -> None:
    path = tmp_path / "coordinator" / "stall_seen.json"
    assert reset_seen_set_on_graduation(True, False, path) is True
    assert path.exists()
    assert read_seen_state(path) == StallSeenState(fingerprints=frozenset(), updated_at="")


# ---------------------------------------------------------------------------
# RouteOutcome shape sanity
# ---------------------------------------------------------------------------


def test_route_outcome_is_a_frozen_value_object() -> None:
    import dataclasses

    outcome = RouteOutcome(True, "journal")
    with pytest.raises(dataclasses.FrozenInstanceError):
        outcome.delivered = False  # type: ignore[misc]
