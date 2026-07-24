"""C3 heartbeat output router — the design-§7.2 routing table realized (#845 limb 4).

ONE routing decision per side-effect class, made HERE and nowhere else: the
limb-3 cycle engine (:mod:`shared.coordinator.heartbeat_cycle`) emits effects
through injected sinks in fixed shapes, and this module supplies those sinks
already routed by ``[coordinator].shadow_mode`` — so the cycle never knows (or
checks) whether it is shadowed, and no second flag-check can drift. The two
independent locks on live output (§7.1, principle 3): ``heartbeat_enabled=true``
(its own LA ceremony) starts SHADOW cycles; only the #855 graduation ceremony
flips ``shadow_mode=false``. No single flip produces operator-visible output.

The §7.2 table, row by row, as realized here:

  * **Stall comment** — shadow: journal entry, and the routed sink returns
    ``True`` on journal success so the seen-set persists exactly as it would
    live (dedup behavior is gradable, §7.2 verbatim); live: the real Vikunja
    comment via the injected ``live_post_comment``.
  * **Board move** — shadow: journal entry, returned as
    ``BoardMoveResult(moved=True, reason="journaled (shadow)")`` — ``moved=True``
    because the cycle's records (and #855's grading) must account the move as
    APPLIED, exactly as live would: a ``False`` here would make every shadow
    cycle try the remaining projects and surface a spurious
    ``board-move-not-applied`` condition, polluting the very evidence shadow
    exists to collect. Live: the injected ``live_move_card``.
  * **Redispatch proposal** — the store half lives in the cycle engine (DRAFTs
    stay DRAFT in shadow, §7.2); THIS module's :meth:`OutputRouter.record_proposal_copy`
    supplies the row's other half, the full-context journal copy (shadow only —
    live's record IS the store's DRAFT→STAGED transition).
  * **Digest** — shadow: journal entry. Live: the injected
    ``live_digest_surface`` seam; C3 deliberately ships NO live digest renderer
    (§7.4 "not built live in C3" — it lands with graduation), so the default
    live behavior is journal-with-note, never a fabricated surface. At most ONE
    digest per cycle is routed (see :meth:`OutputRouter.route_digest`).
    Structurally, no digest path can reach the comment sink — the F11
    digest-never-a-ticket-comment lock is code SHAPE, not a flag check.
  * **Tripwire alarm** — shadow: journal entry; live: the operator surface. A
    condition marked ``machinery_health`` that arrives here is DIVERTED to
    :meth:`OutputRouter.route_health` (defense-in-depth — health is never
    shadow-gated, even when mis-routed).
  * **Machinery health** — the operator surface ALWAYS, in BOTH modes
    (§7.2's most load-bearing row): routing the watchdog's own alarm into an
    unread journal would re-create the vigilance dependence §2.14.1 exists to
    kill. :meth:`OutputRouter.route_health` never consults ``shadow_mode`` —
    structurally, not conditionally.

The operator surface at C3 is an injected callable the limb-6 launcher wires to
its ERROR-log/notice path; the default is ``logging.error`` — fail-loud, never
silent (principle 11). Absence-mode digest accumulation into the catch-up brief
(§8.2) rides with the live digest renderer at graduation: in shadow every
digest is journaled with its ``absence_accumulated`` flag intact, so #855 can
grade the accumulation decision without a renderer existing.

Graduation hygiene (§7.2): :func:`reset_seen_set_on_graduation` resets the
stall seen-set exactly once on the shadow→live edge, so every stall ongoing at
graduation earns its first LIVE comment as a fresh episode (the shadow-era
fingerprint would otherwise suppress it). Limb 6 wires the recorded mode from
the liveness stamp.

REACHABILITY: an :class:`OutputRouter` is constructed by the ``build_heartbeat``
factory, which builds nothing while ``[coordinator].heartbeat_enabled`` is false (the
dormant default). Whether its output reaches the board or the shadow journal is
decided by the recorded mode, not by this module. Importing this module arms nothing.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Final, Mapping

from shared.coordinator import shadow_journal as sj
from shared.coordinator.heartbeat_cycle import DigestRecord, SurfacedCondition
from shared.fleet import vikunja_bridge as vb
from shared.fleet.coord_stall_state import StallSeenState, write_seen_state

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Seam shapes
# ---------------------------------------------------------------------------

#: The operator surface: one plain-language message → the operator's attention
#: path. Limb 6 wires the launcher's ERROR-log/notice channel; the default is
#: :func:`_default_operator_surface` (``logging.error`` — fail-loud, principle 11).
OperatorSurface = Callable[[str], None]

#: The post-graduation live digest surface (§7.4 — the AO chat render under
#: UNTRUSTED provenance + the WinUI typed feed). NOT built in C3: the seam
#: exists so graduation wires a renderer without touching routing, and the
#: default live behavior is journal-with-note.
LiveDigestSurface = Callable[[DigestRecord], None]

#: The shadow board-move reason — the gradable marker #855 keys on.
SHADOW_MOVE_REASON: Final[str] = "journaled (shadow)"


def _default_operator_surface(message: str) -> None:
    """The default operator surface: an ERROR-level log line. Deliberately loud —
    a machinery-health alarm that lands here was NOT wired to a richer notice
    path, and an unread WARNING would be a silently-degraded control."""
    logger.error("COORDINATOR OPERATOR NOTICE: %s", message)


def _utc_now() -> datetime:
    """Production ``now_fn`` default (tz-aware UTC). Tests inject a fixed clock."""
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class RouteOutcome:
    """What one ``route_*`` call did — the caller-legible routing record.

    ``delivered`` is True when the effect reached its routed destination
    (journal, operator surface, or live surface); False for a refused duplicate
    digest, a journal fault, or a deliberate no-op. ``destination`` names where
    it went; ``note`` carries the operator-legible why for every non-obvious
    outcome (a router that drops an effect must say so, never fail silently)."""

    delivered: bool
    destination: str
    note: str = ""


# ---------------------------------------------------------------------------
# The router
# ---------------------------------------------------------------------------


class OutputRouter:
    """The §7.2 routing table as an object — build via :func:`build_output_router`.

    Bound methods ARE the limb-3 sink shapes: :meth:`move_card` is a
    ``MoveCardSink`` (``(project_id, run_id, bucket_title) → BoardMoveResult``)
    and :meth:`post_stall_comment` is a ``PostComment``
    (``(task_id, markdown) → bool``) — the limb-6 factory passes them straight
    into :class:`~shared.coordinator.heartbeat_cycle.CycleEnv` and drives
    :meth:`route_digest` / :meth:`route_tripwire` / :meth:`route_health` over
    the returned :class:`~shared.coordinator.heartbeat_cycle.CycleResult`.

    One router per heartbeat thread, constructed once at build time: the routing
    mode is fixed for the router's lifetime (a ``shadow_mode`` flip is a config
    change the operator makes outside BlarAI, picked up at the next boot — never
    re-read mid-flight, so a cycle can never straddle two modes)."""

    def __init__(
        self,
        *,
        shadow_mode: bool,
        journal: sj.ShadowJournal,
        live_move_card: "Callable[[int, str, str], vb.BoardMoveResult]",
        live_post_comment: "Callable[[int, str], bool]",
        operator_surface: OperatorSurface,
        live_digest_surface: LiveDigestSurface | None,
        now_fn: "Callable[[], datetime]",
    ) -> None:
        self._shadow_mode = bool(shadow_mode)
        self._journal = journal
        self._live_move_card = live_move_card
        self._live_post_comment = live_post_comment
        self._operator_surface = operator_surface
        self._live_digest_surface = live_digest_surface
        self._now_fn = now_fn
        #: The one-digest-per-cycle latch (see :meth:`route_digest`).
        self._last_digest_cycle: str | None = None

    # ------------------------------------------------------------------
    # §7.2 row 1 — stall comment (a PostComment: (task_id, markdown) → bool)
    # ------------------------------------------------------------------

    def post_stall_comment(self, task_id: int, markdown: str) -> bool:
        """The routed stall-comment sink.

        Shadow: journal the comment and return ``True`` — §7.2 verbatim: the
        seen-set persists on journal success exactly as it would on a live post,
        so episode dedup is gradable. A journal fault returns ``False`` (the
        seen-set algebra then treats it as a failed post and retries next cycle
        — a lost journal write never silently suppresses a stall episode).
        Live: the real Vikunja comment."""
        if self._shadow_mode:
            try:
                self._journal.append(
                    sj.KIND_STALL_COMMENT,
                    {"task_id": task_id, "markdown": markdown},
                    now=self._now_fn(),
                )
            except Exception as exc:  # noqa: BLE001 — reads as a failed post, retried
                logger.warning(
                    "output_router: shadow journal append failed for a stall "
                    "comment (task %s) — reads as a failed post, retried next "
                    "cycle: %s",
                    task_id,
                    exc,
                )
                return False
            return True
        return self._live_post_comment(task_id, markdown)

    # ------------------------------------------------------------------
    # §7.2 row 2 — board move (a MoveCardSink: (pid, run, bucket) → BoardMoveResult)
    # ------------------------------------------------------------------

    def move_card(
        self, project_id: int, run_id: str, to_bucket_title: str
    ) -> vb.BoardMoveResult:
        """The routed board-move sink.

        Shadow: journal the intended move and return
        ``BoardMoveResult(moved=True, reason="journaled (shadow)")``. WHY
        ``moved=True``: the cycle engine records the move from this result and
        stops trying further projects on success — a ``False`` would make every
        shadow cycle fan out across all configured projects and surface a
        spurious ``board-move-not-applied`` condition, corrupting exactly the
        evidence #855 grades; the reason string keeps the record honest about
        WHERE the move went. A journal fault returns ``moved=False`` with the
        fault named (fail-soft, same shape as a live transport failure).
        Live: the real kanban move."""
        if self._shadow_mode:
            try:
                self._journal.append(
                    sj.KIND_BOARD_MOVE,
                    {
                        "project_id": project_id,
                        "run_id": run_id,
                        "to_bucket": to_bucket_title,
                    },
                    now=self._now_fn(),
                )
            except Exception as exc:  # noqa: BLE001 — same shape as a live transport failure
                logger.warning(
                    "output_router: shadow journal append failed for a board "
                    "move (run %s -> %r): %s",
                    run_id,
                    to_bucket_title,
                    exc,
                )
                return vb.BoardMoveResult(
                    False, f"shadow journal append failed: {exc}"
                )
            return vb.BoardMoveResult(True, SHADOW_MOVE_REASON)
        return self._live_move_card(project_id, run_id, to_bucket_title)

    # ------------------------------------------------------------------
    # §7.2 row 3 (journal half) — the full-context proposal copy
    # ------------------------------------------------------------------

    def record_proposal_copy(self, payload: Mapping[str, Any]) -> RouteOutcome:
        """Journal the full-context copy of a proposal staged during shadow.

        The store half of §7.2 row 3 lives in the cycle engine (fresh DRAFTs
        stay DRAFT in shadow); this method supplies the row's journal half so
        #855 grades the proposal WITH the context that produced it. Live: a
        deliberate no-op — the store's DRAFT→STAGED transition IS the live
        record, and duplicating it here would double-count graduation evidence."""
        if not self._shadow_mode:
            return RouteOutcome(
                False,
                "none",
                note="live mode: the proposal store transition is the record (§7.2)",
            )
        try:
            self._journal.append(
                sj.KIND_PROPOSAL_COPY, dict(payload), now=self._now_fn()
            )
        except Exception as exc:  # noqa: BLE001 — surfaced via the outcome, fail-loud below
            logger.warning(
                "output_router: shadow journal append failed for a proposal "
                "copy: %s",
                exc,
            )
            return RouteOutcome(
                False, "journal", note=f"journal append failed: {exc}"
            )
        return RouteOutcome(True, "journal")

    # ------------------------------------------------------------------
    # §7.2 row 4 — digest (at most one per cycle; NEVER a ticket comment)
    # ------------------------------------------------------------------

    def route_digest(self, digest: DigestRecord) -> RouteOutcome:
        """Route the cycle's digest — at most ONE per ``cycle_started_at``.

        THE ONE-DIGEST MECHANISM (chosen + documented per the limb brief): an
        in-router latch on the last routed ``cycle_started_at``. It is
        sufficient — not merely convenient — because cycle start instants are
        strictly monotonic within a router's lifetime (one heartbeat thread,
        one router, built together by limb 6), so the only possible duplicate
        key is the immediately-previous one; and across a crash-restart the
        retry cycle mints a NEW ``started_at``, so a durable cross-process
        latch would guard a collision that cannot occur. A refused duplicate
        is fail-loud (logged + named in the outcome), never silent.

        Shadow: journal entry. Live: the injected ``live_digest_surface``;
        when none is wired (C3 ships no live renderer, §7.4) the digest is
        journaled WITH a note naming that fact — a deliberate, visible
        fallback, not a fabricated surface. This method has no reachable path
        to the comment sink — digest-never-a-ticket-comment is structural
        (the F11 lock asserts the shape)."""
        if (
            self._last_digest_cycle is not None
            and digest.cycle_started_at == self._last_digest_cycle
        ):
            note = (
                f"duplicate digest for cycle {digest.cycle_started_at} refused "
                "(at most one per cycle, §7.4)"
            )
            logger.warning("output_router: %s", note)
            return RouteOutcome(False, "refused-duplicate-digest", note=note)

        payload = asdict(digest)
        if self._shadow_mode:
            outcome = self._journal_digest(payload, note="")
        elif self._live_digest_surface is not None:
            try:
                self._live_digest_surface(digest)
                outcome = RouteOutcome(True, "live-digest-surface")
            except Exception as exc:  # noqa: BLE001 — preserve the digest, name the fault
                logger.warning(
                    "output_router: live digest surface raised — journaling "
                    "the digest instead: %s",
                    exc,
                )
                outcome = self._journal_digest(
                    payload, note=f"live digest surface raised: {exc} — journaled"
                )
        else:
            outcome = self._journal_digest(
                payload,
                note=(
                    "live digest surface not built in C3 (design §7.4) — "
                    "journaled with note"
                ),
            )
        if outcome.delivered:
            self._last_digest_cycle = digest.cycle_started_at
        return outcome

    def _journal_digest(
        self, payload: dict[str, Any], *, note: str
    ) -> RouteOutcome:
        """Append a digest payload to the journal (with the routing *note* kept
        INSIDE the payload, so #855 sees why a live-mode digest was journaled).
        A journal fault is fail-loud: the outcome names it AND the operator
        surface hears the machinery note (the route_* return value may be
        dropped by the caller, so this path carries its own alarm — principle 11)."""
        if note:
            payload = dict(payload)
            payload["routing_note"] = note
        try:
            self._journal.append(sj.KIND_DIGEST, payload, now=self._now_fn())
        except Exception as exc:  # noqa: BLE001 — a lost digest must be heard, not dropped
            logger.warning(
                "output_router: shadow journal append failed for a digest: %s", exc
            )
            self._surface(
                f"[machinery-health] shadow-journal-fault: digest journal append "
                f"failed ({exc})"
            )
            return RouteOutcome(
                False, "journal", note=f"journal append failed: {exc}"
            )
        return RouteOutcome(True, "journal", note=note)

    # ------------------------------------------------------------------
    # §7.2 row 5 — quiet-queue tripwire alarm
    # ------------------------------------------------------------------

    def route_tripwire(self, condition: SurfacedCondition) -> RouteOutcome:
        """Route a quiet-queue tripwire alarm (a coordinator JUDGMENT — its
        false-alarm rate is precisely what shadow measures, §7.2).

        Shadow: journal entry. Live: the operator surface. A condition marked
        ``machinery_health`` is DIVERTED to :meth:`route_health` — health is
        never shadow-gated, even when a caller mis-routes it here
        (defense-in-depth on the table's most load-bearing row). A journal
        fault is fail-loud via the operator surface, exactly as for digests —
        a swallowed alarm is a silently-degraded control (principle 11)."""
        if condition.machinery_health:
            return self.route_health(condition)
        if self._shadow_mode:
            try:
                self._journal.append(
                    sj.KIND_TRIPWIRE_ALARM, asdict(condition), now=self._now_fn()
                )
            except Exception as exc:  # noqa: BLE001 — a lost alarm must be heard
                logger.warning(
                    "output_router: shadow journal append failed for a tripwire "
                    "alarm: %s",
                    exc,
                )
                self._surface(
                    f"[machinery-health] shadow-journal-fault: tripwire alarm "
                    f"journal append failed ({exc})"
                )
                return RouteOutcome(
                    False, "journal", note=f"journal append failed: {exc}"
                )
            return RouteOutcome(True, "journal")
        self._surface(f"[tripwire] {condition.kind}: {condition.detail}")
        return RouteOutcome(True, "operator-surface")

    # ------------------------------------------------------------------
    # §7.2 row 6 — machinery health: the operator surface ALWAYS, both modes
    # ------------------------------------------------------------------

    def route_health(self, condition: SurfacedCondition) -> RouteOutcome:
        """Surface a machinery-health condition to the operator — ALWAYS.

        §7.2's most load-bearing row: dead-man staleness, ``thread_dead``,
        substrate-``UNREACHABLE`` and store faults go to the operator surface in
        BOTH modes — never the journal, never shadow-gated. Structurally so:
        this method does not read the routing mode at all (the
        machinery-health-always-live lock asserts that shape), so no future
        edit can quietly re-gate it without failing the lock."""
        self._surface(f"[machinery-health] {condition.kind}: {condition.detail}")
        return RouteOutcome(True, "operator-surface")

    def _surface(self, message: str) -> None:
        """Deliver *message* to the operator surface — NEVER silently.

        The injected surface raising must not swallow the alarm it carries: the
        fallback is the default ERROR log (fail-loud, principle 11), with the
        surface's own fault appended so a broken notice path is itself heard."""
        try:
            self._operator_surface(message)
        except Exception as exc:  # noqa: BLE001 — the alarm outlives a broken surface
            _default_operator_surface(
                f"{message} (injected operator surface raised: {exc})"
            )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_output_router(
    *,
    shadow_mode: bool,
    journal: sj.ShadowJournal,
    live_move_card: "Callable[[int, str, str], vb.BoardMoveResult] | None" = None,
    live_post_comment: "Callable[[int, str], bool] | None" = None,
    operator_surface: OperatorSurface | None = None,
    live_digest_surface: LiveDigestSurface | None = None,
    now_fn: "Callable[[], datetime] | None" = None,
) -> OutputRouter:
    """Build the routed output sinks for one heartbeat (design §7.2).

    *shadow_mode* comes from the resolved
    :class:`~shared.coordinator.config.CoordinatorConfig` (fail-closed toward
    ``True`` — see ``CoordinatorConfig.from_toml``). *journal* is REQUIRED and
    must be a real :class:`~shared.coordinator.shadow_journal.ShadowJournal`
    (fail-closed type gate: in shadow mode the journal IS the output path, so a
    wrong object here would silently discard every effect). The live sinks
    default to the real production wirings
    (:func:`shared.fleet.vikunja_bridge.move_job_card` /
    :func:`~shared.fleet.vikunja_bridge.post_task_comment` — the same defaults
    ``CycleEnv`` documents); the operator surface defaults to the ERROR log;
    the live digest surface defaults to ``None`` (C3 ships no live renderer,
    §7.4 — the router journals-with-note); *now_fn* defaults to UTC wall clock
    (tests inject a fixed clock for deterministic journal timestamps)."""
    if not isinstance(journal, sj.ShadowJournal):
        raise TypeError(
            "build_output_router requires a ShadowJournal (the shadow output "
            f"path); got {type(journal).__name__!r}."
        )
    return OutputRouter(
        shadow_mode=shadow_mode,
        journal=journal,
        live_move_card=live_move_card or vb.move_job_card,
        live_post_comment=live_post_comment or vb.post_task_comment,
        operator_surface=operator_surface or _default_operator_surface,
        live_digest_surface=live_digest_surface,
        now_fn=now_fn or _utc_now,
    )


# ---------------------------------------------------------------------------
# Graduation hygiene (§7.2) — the seen-set reset on the shadow→live edge
# ---------------------------------------------------------------------------


def reset_seen_set_on_graduation(
    recorded_shadow_mode: bool | None,
    current_shadow_mode: bool,
    seen_path: Path,
    *,
    now: datetime | None = None,
) -> bool:
    """Reset the stall seen-set exactly once on the shadow→live edge.

    ``run_stall_cycle`` persists posted fingerprints regardless of sink, so a
    stall ongoing at graduation carries a shadow-era fingerprint and its first
    LIVE comment would be suppressed (§7.2 graduation hygiene). When the
    liveness stamp's *recorded_shadow_mode* is exactly ``True`` and the
    current config's is exactly ``False`` — the one edge — the seen-set is
    rewritten as a valid EMPTY state, so every ongoing stall earns its first
    live comment as a fresh episode. Every other combination (live→live,
    shadow→shadow, live→shadow, or an unknown ``None`` recording from a
    missing/corrupt stamp) is a pure no-op: no write, ``False`` returned —
    the fail-closed direction, since a spurious reset would re-fire a comment
    for every already-commented stall.

    Pure decision + one write. The ONCE is completed by the caller's contract:
    limb 6 re-stamps the liveness record with the current mode in the same
    motion, so the next comparison sees live→live and never resets again.
    *now* (tz-aware, injected) stamps the empty state's advisory ``updated_at``;
    ``None`` leaves it blank (both are valid empty seen-sets). Returns ``True``
    iff the reset was performed."""
    if recorded_shadow_mode is not True or current_shadow_mode is not False:
        return False
    write_seen_state(
        StallSeenState(
            fingerprints=frozenset(),
            updated_at=now.isoformat() if now is not None else "",
        ),
        path=seen_path,
    )
    logger.info(
        "output_router: stall seen-set reset on shadow->live graduation (%s) — "
        "ongoing stalls will earn fresh first live comments",
        seen_path,
    )
    return True
