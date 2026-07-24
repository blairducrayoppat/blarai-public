"""C3 heartbeat wake cycle — the pure §2 orchestration over the merged substrate (#845).

The LA-approved C3 design (`docs/research/c3-heartbeat-design-2026-07.md` §2) names
one wake cycle's composition order over the already-merged C1/C2 pieces; this module
IS that cycle, as pure-as-possible code over INJECTED substrate handles and sinks
(:class:`CycleEnv`): the caller (the limb-6 launcher thread, or a test) supplies every
clock value, probe, store handle, and output sink — :func:`run_wake_cycle` reads no
wall clock and holds no cross-cycle state of its own (cross-cycle state lives in the
injected durable artifacts: the board-history record, the stall seen-set, the proposal
store, the absence stamp).

The cycle, in design §2's order — every step fail-soft toward the CYCLE (a step
failure is recorded on the :class:`CycleResult` and the cycle proceeds or ends
cleanly, never raises out — §3.3 wall 2), while targeting checks INSIDE steps stay
fail-closed (a refused target refuses that action, §5):

  1.  Mode resolution (:func:`shared.coordinator.cadence.resolve_cycle_mode`) from the
      swap tri-state read, the injected power probe, the overnight window, and the
      teardown/single-flight flags. ``SKIP`` ends the cycle immediately (nothing but
      the caller's liveness-stamp note).
  2.  Absence reconcile + store TTL sweep (``expire_stale``) — ORDER MATTERS: an
      absence exit applies the sanctioned :meth:`ProposalStore.extend_ttl` pause
      BEFORE any sweep runs, so returning from an absence can never demote every
      surfaced ask at once (design §8.2; the pause is real, not a sweep-skip).
  3.  Snapshot compose (:func:`shared.fleet.work_state.compose_work_state`) — the
      PRIOR cycle's board-history record injects the observed age basis
      (read-inject-before-compose, design §2 steps 3–4).
  4.  Board-history observe + write (AFTER compose): pure diff of each project's
      fresh bucket membership, **only over ``OK`` board reads** (the load-bearing
      caller precondition on :func:`shared.fleet.coord_board_history.observe_board` —
      an UNREACHABLE board's project carries its prior observations forward untouched).
  5.  Harvest the latest run → board movement through the deterministic ruler
      (:func:`shared.fleet.coord_lifecycle.resolve_board_transition`; ``oracle_passed``
      comes ONLY from the run's ``scorecard.json`` ``evidence.oracle_status`` — a
      merged-without-oracle run can never move a card to Done, by the C2 ruler's
      construction) → the injected ``move_card`` sink (live: the real
      ``vikunja_bridge.move_job_card``; shadow: the limb-4 router's journal sink).
  6.  Stall pass (:func:`shared.fleet.coord_stall_monitor.run_stall_cycle`) — one
      comment per NEW stall episode through the injected ``post_stall_comment`` sink;
      during operator absence only Expedite-class stalls post (suppressed ones are
      NOT persisted to the seen-set, so they retry on the first present cycle).
  7.  Redispatch staging — the TRUSTED ``repo_id`` sourced per design §5
      (:func:`normalize_trusted_repo_id` over the dispatch-written acceptance
      record; NEVER from ``SUMMARY.txt``/run-report text; no structured record ⇒ no
      staging + surfaced condition), then the WHOLE
      :func:`shared.fleet.coord_redispatch.stage_redispatch_proposals` invocation
      wrapped defensively (the #844 c.1876 caller obligation — a raise is recorded
      and the same evidence retries next cycle because no proposal was written).
      In live mode (``shadow_mode=False``) fresh heartbeat-originated DRAFTs are
      promoted to STAGED; in shadow mode proposals STAY DRAFT (design §7.2).
  8.  Quiet-queue tripwire (:func:`evaluate_quiet_queue_tripwire`, pure) —
      suppressed on ANY consulted-substrate UNREACHABLE (unknown ≠ quiet), during
      swaps, inside the overnight window, within the post-boot idle-grace, and
      during operator absence (it is not Expedite-class).
  9.  Model drafting (``FULL`` mode only) through the injected limb-5 seam —
      bounded single-decision calls; ``busy``/``not_resident`` are NORMAL deferrals
      recorded on the result, never errors; a mid-swap cycle makes ZERO model calls
      (the mode ladder settles that before this step is reached).
  10. Digest — at most ONE :class:`DigestRecord` per cycle: deterministic skeleton
      plus the step-9 prose when available; routing (shadow journal vs operator
      surface) is the limb-4 router's job, NOT this module's.

The liveness stamp (design §2 step 11 / §6.1) is written by the limb-6 thread loop
around this function — the cycle itself stays clock-free and I/O-bounded.

Crash convergence (design §2): every persistent write here is single-artifact atomic
(board-history record, absence stamp — temp + ``os.replace``) or a single-row SQLite
commit (the store), and every cross-cycle dedup is derived from those artifacts
(seen-set episode algebra, store fingerprint idempotency, board moves that are
no-ops onto the current bucket) — so a crash between any two steps leaves no
duplicate comment, no duplicate proposal, and no duplicate board move on the next
full cycle.

REACHABILITY: :func:`run_wake_cycle` is driven by the ``build_heartbeat`` factory,
which constructs nothing while ``[coordinator].heartbeat_enabled`` is false (the
dormant default) and runs the cycle on its interval when true. Importing this module
arms nothing.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Final, Mapping, Sequence

from shared.coordinator import cadence
from shared.coordinator.config import CoordinatorConfig, GovernedCoreRoots
from shared.coordinator.proposal_store import ProposalStatus, ProposalStore
from shared.fleet import coord_board_history as bh
from shared.fleet import coord_lifecycle as cl
from shared.fleet import coord_redispatch as cr
from shared.fleet import coord_stall_monitor as csm
from shared.fleet import vikunja_bridge as vb
from shared.fleet import work_state as ws
from shared.coordinator.prose_guard import (
    VERDICT_SUCCEEDED,
    GuardDecision,
    ProseGuard,
    RunTruth,
    compose_run_headline,
)
from shared.fleet.coord_stall_state import coordinator_state_dir
from shared.fleet.dispatch import FleetDispatchConfig, read_acceptance_record
from shared.security.file_dacl import ensure_owner_only_dacl

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Run-outcome vocabulary (SUMMARY RESULT literals). Keying on cross-module string
# literals is silently wrong after a rename — the drift lock in
# shared/tests/test_heartbeat_cycle.py asserts these against the SAME
# dispatch._classify_result source extraction shared/tests/test_coord_redispatch.py
# already locks, so the fleet's vocabulary cannot drift from this module unnoticed.
# ---------------------------------------------------------------------------

RESULT_MERGED: Final[str] = "MERGED"
RESULT_PARKED: Final[str] = "PARKED"

#: ``scorecard.json`` → ``evidence.oracle_status`` value that alone means the
#: job-level oracle passed. Anything else — absent file, absent key, "failed",
#: "skipped", a malformed document — resolves to ``oracle_passed=False``
#: (fail-soft toward NOT-Done: a merged-without-oracle run can then never move a
#: card to Done, by the C2 ruler's construction).
ORACLE_STATUS_PASSED: Final[str] = "passed"


# ---------------------------------------------------------------------------
# Result / record types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StepOutcome:
    """One cycle step's outcome — the per-step wrap's record (§3.3 wall 2)."""

    name: str
    ok: bool
    detail: str = ""


@dataclass(frozen=True)
class SurfacedCondition:
    """A named condition the cycle surfaces (digest line / operator surface).

    ``machinery_health`` marks the class the design's §7.2 router must NEVER
    shadow-gate (substrate-UNREACHABLE, corrupt records, store faults): routing a
    health alarm into an unread journal would re-create the vigilance dependence
    §2.14.1 exists to kill. ``expedite`` marks conditions that still surface during
    operator absence (§8.2 — only Expedite-class conditions surface)."""

    kind: str
    detail: str
    machinery_health: bool = False
    expedite: bool = False


@dataclass(frozen=True)
class BoardMoveRecord:
    """One harvested run's board-move attempt through the routed sink."""

    run_id: str
    to_bucket: str
    reason: str
    moved: bool
    project_id: int | None = None
    attempts: tuple[str, ...] = ()
    """Per-project non-move reasons, operator-legible (fail-soft trail)."""


@dataclass(frozen=True)
class TripwireResult:
    """The quiet-queue tripwire's evaluation (design §8.1) — pure."""

    fired: bool
    suppressed_reasons: tuple[str, ...] = ()
    ready_eligible_total: int = 0
    ready_by_project: Mapping[str, int] = field(default_factory=dict)
    gated_inventory: int = 0
    """Ready items filtered out by the eligibility seam — reported as the
    gated-inventory digest line, NEVER as a tripwire alarm (#845 c.1839 V4)."""


@dataclass(frozen=True)
class DraftOutcome:
    """The limb-5 drafting seam's tri-state result (design §3.4).

    ``busy`` (the single-flight inference lock was held) and ``not_resident``
    (the 14B is not positively resident) are NORMAL deferrals — recorded, never
    retried within the cycle, never errors. ``failed`` covers a fail-soft
    adapter/grammar failure; the digest's deterministic skeleton is the fallback
    rendering (facts without prose — no correctness ever depends on this path)."""

    status: str
    text: str = ""
    reason: str = ""


DRAFT_STATUSES: Final[frozenset[str]] = frozenset(
    {"drafted", "busy", "not_resident", "failed"}
)

#: The drafted-span kinds, in digest-precedence order (#946). ``_draft`` tags
#: every prompt with one of these and ``_guard_prose`` iterates EXACTLY this
#: tuple — a new kind added to one without the other is a test-visible drift
#: (see test_draft_kinds_are_exhaustive), never a silently un-guarded span.
DRAFT_KIND_RUN_SUMMARY: Final[str] = "run_summary"
DRAFT_KIND_PROPOSAL: Final[str] = "proposal"
DRAFT_KINDS: Final[tuple[str, ...]] = (DRAFT_KIND_RUN_SUMMARY, DRAFT_KIND_PROPOSAL)

#: The snapshot substrates the §8.1 tripwire predicate actually CONSULTS (review
#: 66789b24 finding 2): the Vikunja transport (Ready counting) and the swap state
#: (the WIP leg). ``board_history`` is age metadata — irrelevant to counting
#: eligible Ready — and the queue file is not part of the predicate; their faults
#: surface through their own conditions and must never mask a genuine quiet-queue
#: alarm behind a "PM substrate unreachable" label.
_TRIPWIRE_CONSULTED_SUBSTRATES: Final[frozenset[str]] = frozenset(
    {"vikunja", "fleet_swap_state"}
)

#: The drafting seam: a bounded, single-decision prompt (composed HERE by
#: deterministic code from the snapshot's three legs — §2.14.5) → tri-state
#: outcome. Limb 6 wires the AO's ``coordinator_draft()`` (limb 5) into this shape.
DraftFn = Callable[[str], DraftOutcome]

#: The board-move sink: ``(project_id, run_id, to_bucket_title) → BoardMoveResult``.
#: Live wiring is :func:`shared.fleet.vikunja_bridge.move_job_card`; the limb-4
#: shadow router substitutes a journal sink with the same shape.
MoveCardSink = Callable[[int, str, str], vb.BoardMoveResult]


@dataclass(frozen=True)
class AbsenceOutcome:
    """What the absence reconcile did this cycle (design §8.2)."""

    active: bool
    started_this_cycle: bool = False
    ended_this_cycle: bool = False
    extended_count: int = 0
    paused_duration_s: float = 0.0
    note: str = ""


@dataclass(frozen=True)
class DigestRecord:
    """The at-most-one-per-cycle digest (design §7.4): a deterministic skeleton
    plus optional, provenance-tagged model prose. Routing (shadow journal until the
    #855 graduation; NEVER a Vikunja comment) is the limb-4 router's contract."""

    cycle_started_at: str
    mode: str
    queue_depth: Mapping[str, int]
    """Per-project Ready-bucket depth (eligible Ready, from OK board reads only)."""
    open_by_project: Mapping[str, int]
    """Per-project open-task count (flow ``open_count``) — the flow-delta basis."""
    open_delta_by_project: Mapping[str, int]
    """Change in ``open_by_project`` vs the injected prior digest (empty mapping
    when no prior digest was supplied — absolute numbers still stand)."""
    stalls_new: int
    stalls_ongoing: int
    conditions: tuple[SurfacedCondition, ...]
    proposals_pending: int
    runs_harvested: tuple[str, ...]
    gated_inventory: int = 0
    model_prose: str = ""
    model_drafted: bool = False
    """Provenance honesty (§7.4): True iff ``model_prose`` came from the 14B."""
    absence_accumulated: bool = False
    """True when this digest was produced during operator absence — the router
    accumulates it into the catch-up brief instead of surfacing it (§8.2)."""
    run_headline: str = ""
    """#946 layer 1: the DETERMINISTIC verdict headline for the harvested run
    (composed by :func:`shared.coordinator.prose_guard.compose_run_headline`
    from the same truth the board-move ruler used; "" when no run harvested).
    RENDERER CONTRACT: any live digest surface MUST lead with this line and
    render ``model_prose`` beneath it under an explicit model label — model
    text never stands as the claim of record."""
    prose_guard_action: str = ""
    """#946 audit: the guard's decision on this cycle's draft — "accepted",
    "rejected:<reason>", or "" when nothing was drafted. Journaled so the #855
    re-shadow window measures catch rate AND false-refusal rate."""
    model_prose_rejected: str = ""
    """The raw draft the guard refused ("" when none) — kept as evidence for
    the false-refusal measurement; NEVER rendered to the operator."""


@dataclass(frozen=True)
class CycleResult:
    """Everything one wake cycle did — the limb-6 loop renders the liveness stamp
    (and the limb-4 router routes the outputs) from this."""

    started_at: str
    decision: cadence.CycleDecision
    steps: tuple[StepOutcome, ...] = ()
    conditions: tuple[SurfacedCondition, ...] = ()
    snapshot: "ws.WorkStateSnapshot | None" = None
    ttl_expired: int = 0
    absence: AbsenceOutcome | None = None
    board_moves: tuple[BoardMoveRecord, ...] = ()
    stall_result: "csm.StallCycleResult | None" = None
    redispatch: "cr.RedispatchCycleResult | None" = None
    promoted_proposal_ids: tuple[str, ...] = ()
    tripwire: TripwireResult | None = None
    drafts: tuple[DraftOutcome, ...] = ()
    digest: DigestRecord | None = None


# ---------------------------------------------------------------------------
# Injected environment — the cycle's ONLY reach into the world
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CycleEnv:
    """Substrate handles + sinks for one heartbeat, injected by the limb-6 factory
    (production) or a test. Every I/O surface is swappable; the defaults are the
    real production wirings."""

    fleet_config: FleetDispatchConfig
    coordinator_config: CoordinatorConfig
    coordinator_projects: Mapping[str, int]
    roots: GovernedCoreRoots
    board_history_path: Path
    stall_seen_path: Path
    absence_stamp_path: Path
    store: ProposalStore | None = None
    """``None`` = the store could not be built (e.g. keystore unavailable at the
    fail-closed factory). Every store-dependent step surfaces the condition and
    proceeds — a missing store must never stop the deterministic organizing."""
    campaign_state_path: Path | None = None
    shadow_mode: bool = True
    """Design §7.2: True (the default, flipped only at the #855 graduation
    ceremony) keeps redispatch proposals DRAFT; False promotes fresh DRAFTs to
    STAGED. The output sinks below are ALREADY routed by the limb-4 router — this
    flag only governs the store-promotion side effect that lives here."""
    move_card: MoveCardSink | None = None
    """Defaults to the real :func:`shared.fleet.vikunja_bridge.move_job_card`."""
    post_stall_comment: "csm.PostComment | None" = None
    """Defaults to the real :func:`shared.fleet.vikunja_bridge.post_task_comment`."""
    draft: DraftFn | None = None
    """The limb-5 seam; ``None`` (default — dormant) records drafting as absent."""
    power_probe: "Callable[[], cadence.PowerProbe] | None" = None
    """Defaults to :func:`shared.coordinator.cadence.read_power_probe`."""
    read_swap: "Callable[[], ws.TriStateRead[Any]] | None" = None
    """Defaults to :func:`shared.fleet.work_state.read_swap_snapshot` over
    ``fleet_config`` — the mode ladder's step-1 swap read (compose re-reads it for
    the snapshot; both are cheap file reads of the same WAL record)."""
    compose_snapshot: "Callable[[datetime], ws.WorkStateSnapshot] | None" = None
    """Defaults to the real :func:`shared.fleet.work_state.compose_work_state`
    over this env's paths. Tests inject a fixture-snapshot builder."""
    read_acceptance: "Callable[[str], dict | None] | None" = None
    """``run_id → {"spec", "repo"}`` — the TRUSTED dispatch-written acceptance
    record (design §5). Defaults to
    :func:`shared.fleet.dispatch.read_acceptance_record` over ``fleet_config``."""
    read_scorecard: "Callable[[str], Any | None] | None" = None
    """``run_id →`` parsed ``scorecard.json`` (or ``None``). Defaults to a
    fail-soft JSON read of ``runs_dir/<run_id>/scorecard.json``."""
    eligible_ready: "Callable[[Mapping[str, Any]], bool] | None" = None
    """The §8.1 resource-eligibility seam: a predicate over one Ready task.
    ``None`` (today) means "eligible ≡ all Ready" — the §2.9 ``Resource:*``
    registry is C4-era; when it lands, an all-gated Ready column reports as the
    gated-inventory digest line, never a tripwire alarm (#845 c.1839 V4)."""
    vikunja_transport: "vb.Transport | None" = None


def default_absence_stamp_path(config: FleetDispatchConfig) -> Path:
    """The absence-start stamp's default home (``.../coordinator/absence_start.json``)
    — the same coordinator state dir as the stall seen-set and board history."""
    return coordinator_state_dir(config) / "absence_start.json"


# ---------------------------------------------------------------------------
# §5 — the trusted repo_id (CaMeL): sourced from the dispatch-written structured
# record ONLY, normalized deterministically, never recovered from run text.
# ---------------------------------------------------------------------------


def normalize_trusted_repo_id(
    repo: Any, *, projects_dir: str | Path
) -> "tuple[str | None, str]":
    """Normalize an acceptance-record ``repo`` value → a plain workspace component.

    The dispatch path writes ``repo`` at approve time; it may be a plain name OR a
    path (both occur in real records). Deterministic normalization (design §5 /
    handoff-verified): a plain component passes through; a path is accepted ONLY if
    it resolves to a DIRECT child of *projects_dir* (a workspace repo is a direct
    child — a nested subpath is not a repo root), in which case its final component
    is the id. Anything else — non-string, blank, traversal, outside the workspace —
    returns ``(None, reason)``: the caller SKIPS redispatch staging for that run and
    surfaces the condition (fail-closed for targeting, fail-soft for the cycle). The
    returned id still passes ``derive_workspace_target`` + the SG ruler inside
    :func:`shared.fleet.coord_redispatch.stage_redispatch_proposals` regardless —
    this normalization is defense-in-depth on top of the ruler, never a substitute.
    """
    from shared.coordinator.governed_core import derive_workspace_target

    if not isinstance(repo, str) or not repo.strip():
        return None, "acceptance record carries no usable 'repo' string"
    candidate = repo.strip()
    if derive_workspace_target(candidate, projects_dir=projects_dir) is not None:
        return candidate, ""
    # Path form: accept only a direct child of projects_dir, by resolved identity.
    try:
        resolved = Path(candidate).resolve()
        pd = Path(projects_dir).resolve()
    except (OSError, ValueError) as exc:
        return None, f"repo path could not be resolved: {exc}"
    if resolved.parent != pd:
        return None, (
            f"repo path {candidate!r} does not resolve to a direct child of "
            "projects_dir — refusing to derive a target from it"
        )
    name = resolved.name
    if derive_workspace_target(name, projects_dir=projects_dir) is None:
        return None, (
            f"repo path {candidate!r} resolves inside projects_dir but its final "
            f"component {name!r} is not a plain workspace id"
        )
    return name, ""


def oracle_passed_from_scorecard(scorecard: Any) -> bool:
    """``evidence.oracle_status == "passed"`` — the runtime ``oracle_passed`` fact.

    Pure + fail-soft: an absent/malformed scorecard, an absent ``evidence`` block,
    or any other status value resolves ``False`` — toward NOT-Done (the forged-Done
    lock's conservative direction)."""
    if not isinstance(scorecard, Mapping):
        return False
    evidence = scorecard.get("evidence")
    if not isinstance(evidence, Mapping):
        return False
    return evidence.get("oracle_status") == ORACLE_STATUS_PASSED


def _default_read_scorecard(config: FleetDispatchConfig, run_id: str) -> Any | None:
    """Fail-soft JSON read of ``runs_dir/<run_id>/scorecard.json``."""
    from shared.fleet.swap_ops import scorecard_path

    path = scorecard_path(config, run_id)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# §8.1 — the quiet-queue tripwire (pure, tri-state-aware)
# ---------------------------------------------------------------------------


def evaluate_quiet_queue_tripwire(
    snapshot: "ws.WorkStateSnapshot",
    *,
    in_overnight_window: bool,
    in_boot_grace: bool,
    absence_active: bool,
    eligible_ready: "Callable[[Mapping[str, Any]], bool] | None" = None,
) -> TripwireResult:
    """Design §8.1: fire ONLY when eligible Ready work exists (from ``OK`` board
    reads), dispatch WIP is below the global cap of 1 (no swap in flight, no active
    run), and no suppression window applies. Suppressions are themselves surfaced
    where informative — a dead Vikunja must never look like a finished backlog."""
    suppressed: list[str] = []

    unreachable = [
        s.name
        for s in snapshot.substrate
        if s.status is vb.ReadStatus.UNREACHABLE
        and s.name in _TRIPWIRE_CONSULTED_SUBSTRATES
    ]
    unreachable += [
        f"board:{p.name}"
        for p in snapshot.projects
        if p.board.status is vb.ReadStatus.UNREACHABLE
    ]
    if unreachable:
        suppressed.append(
            "PM substrate unreachable: " + ", ".join(sorted(unreachable))
        )
    if snapshot.latest_run.status is vb.ReadStatus.UNREACHABLE:
        # The WIP leg is unknown — unknown ≠ idle, same direction as the swap gate.
        suppressed.append("latest run state unreachable (WIP unknown)")
    if snapshot.swap_in_flight:
        suppressed.append("model swap in flight")
    if in_overnight_window:
        suppressed.append("inside the overnight quiet window (the fleet owns the night)")
    if in_boot_grace:
        suppressed.append("within the post-boot idle-grace")
    if absence_active:
        suppressed.append("operator absent (tripwire is not Expedite-class)")

    # Active-run detection: read_latest_run_summary yields EMPTY with a
    # ``(run_id, ())`` value in TWO cases — SUMMARY.txt absent (a run still in
    # flight) or present-but-zero-outcomes (a finished, anomalous run). Both are
    # treated as active WIP: for the anomalous case that is conservative
    # (suppress rather than alarm over evidence we cannot read — review 66789b24
    # finding 5 names the ambiguity). WIP cap is global = 1.
    lr = snapshot.latest_run
    run_active = (
        lr.status is vb.ReadStatus.EMPTY
        and lr.value is not None
        and not lr.value[1]
    )
    if run_active:
        suppressed.append(f"a dispatch run is active ({lr.value[0]})")

    ready_by_project: dict[str, int] = {}
    eligible_total = 0
    gated = 0
    for project in snapshot.projects:
        if project.board.status is not vb.ReadStatus.OK:
            continue
        ready_tasks: list[Mapping[str, Any]] = []
        for bucket in project.board.items:
            if str(bucket.get("title", "")).strip() == cl.BUCKET_READY:
                tasks = bucket.get("tasks")
                if isinstance(tasks, (list, tuple)):
                    ready_tasks.extend(t for t in tasks if isinstance(t, Mapping))
        # #887: a SYNTHETIC battery/test ticket in Ready is not real work waiting to
        # be pulled — it must never fire the quiet-queue alarm. Filtered BEFORE the
        # resource-eligibility seam so it is neither an alarm nor gated-inventory
        # (its honest park was its deliverable; the /coord test-class line surfaces
        # it instead).
        ready_tasks = [t for t in ready_tasks if not cl.is_test_class(t)]
        if eligible_ready is None:
            eligible = list(ready_tasks)
        else:
            eligible = [t for t in ready_tasks if _eligible_fail_closed(eligible_ready, t)]
        gated += len(ready_tasks) - len(eligible)
        ready_by_project[project.name] = len(eligible)
        eligible_total += len(eligible)

    fired = eligible_total > 0 and not suppressed
    return TripwireResult(
        fired=fired,
        suppressed_reasons=tuple(suppressed),
        ready_eligible_total=eligible_total,
        ready_by_project=ready_by_project,
        gated_inventory=gated,
    )


def _eligible_fail_closed(
    predicate: "Callable[[Mapping[str, Any]], bool]", task: Mapping[str, Any]
) -> bool:
    """An evaluator that raises returns UNKNOWN — the card stays GATED-and-visible
    (counted as gated inventory), never silently released (#845 c.1839 V3)."""
    try:
        return bool(predicate(task))
    except Exception as exc:  # noqa: BLE001 — UNKNOWN never releases a card
        logger.warning(
            "heartbeat_cycle: eligibility evaluator raised (task stays gated): %s", exc
        )
        return False


# ---------------------------------------------------------------------------
# Absence stamp (design §8.2) — non-content-bearing, atomic, owner-DACL
# ---------------------------------------------------------------------------


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(payload), indent=2), encoding="utf-8")
    os.replace(tmp, path)
    ensure_owner_only_dacl(path)


def _read_absence_stamp(path: Path) -> "tuple[datetime | None, bool]":
    """``(absent_since, applied)`` — or ``(None, False)`` for missing/corrupt
    (fail-soft: a corrupt stamp is re-stamped by the caller with a surfaced note;
    the cost is an under-counted pause, the conservative direction).

    ``applied`` is the per-episode idempotency marker (review 66789b24 finding 3):
    set the moment the exit extension has landed but the stamp could not be
    cleared, so a lingering stamp NEVER re-extends — without it, a stuck unlink
    would compound the extension every cycle and STAGED proposals would never
    expire."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None, False
    if not isinstance(data, Mapping):
        return None, False
    raw = data.get("absent_since")
    if not isinstance(raw, str):
        return None, False
    try:
        absent_since = datetime.fromisoformat(raw)
    except ValueError:
        return None, False
    return absent_since, isinstance(data.get("applied_at"), str)


# ---------------------------------------------------------------------------
# The cycle
# ---------------------------------------------------------------------------


def run_wake_cycle(
    env: CycleEnv,
    *,
    now: datetime,
    local_now: datetime,
    teardown_started: bool = False,
    previous_cycle_running: bool = False,
    in_boot_grace: bool = False,
    prior_digest: DigestRecord | None = None,
) -> CycleResult:
    """One heartbeat wake cycle (design §2). Never raises past entry validation:
    every step is individually wrapped (§3.3 wall 2), every failure is recorded on
    the result, and the caller's thread loop adds the outer wall.

    *now* must be tz-AWARE (UTC — store timestamps, compose, record stamps);
    *local_now* must be NAIVE local wall-clock (the overnight window's contract —
    :meth:`shared.coordinator.cadence.OvernightWindow.contains` raises on aware).
    Both validated here, fail-loud, BEFORE any side effect: a wrong clock kind is a
    caller bug, not a substrate fault."""
    if now.tzinfo is None:
        raise ValueError("run_wake_cycle: 'now' must be timezone-aware (UTC)")
    if local_now.tzinfo is not None:
        raise ValueError(
            "run_wake_cycle: 'local_now' must be a NAIVE local datetime "
            "(the overnight window is local wall-clock)"
        )

    started_at = now.isoformat()
    steps: list[StepOutcome] = []
    conditions: list[SurfacedCondition] = []
    cfg = env.coordinator_config

    # ── Step 1: mode resolution (pure ladder over probes) ──────────────────
    try:
        power = (env.power_probe or cadence.read_power_probe)()
    except Exception as exc:  # noqa: BLE001 — probe error never reads as AC
        power = cadence.PowerProbe(
            cadence.PowerState.UNKNOWN, note=f"power probe raised: {exc}"
        )
    window, window_note = cadence.parse_overnight_window(cfg.overnight_window)
    if window_note:
        conditions.append(SurfacedCondition("overnight-window-malformed", window_note))
    in_window = window.contains(local_now) if window is not None else False

    try:
        swap_read = (
            env.read_swap() if env.read_swap is not None
            else ws.read_swap_snapshot(env.fleet_config)
        )
        swap_read_ok = swap_read.ok
        swap_in_flight = False
        if swap_read.status is vb.ReadStatus.OK and swap_read.value is not None:
            from shared.fleet import swap_state as ss

            swap_in_flight = ss.is_in_flight(swap_read.value)
    except Exception as exc:  # noqa: BLE001 — unknown ≠ idle (design-review F1)
        swap_read_ok = False
        swap_in_flight = False
        conditions.append(
            SurfacedCondition(
                "swap-read-failed", f"swap state read raised: {exc}",
                machinery_health=True,
            )
        )

    decision = cadence.resolve_cycle_mode(
        teardown_started=teardown_started,
        previous_cycle_running=previous_cycle_running,
        swap_read_ok=swap_read_ok,
        swap_in_flight=swap_in_flight,
        power=power,
        in_overnight_window=in_window,
        interval_s=cfg.heartbeat_interval_s,
        battery_multiplier=cfg.heartbeat_battery_multiplier,
    )
    steps.append(StepOutcome("mode-resolution", True, decision.mode.value))
    if not swap_read_ok:
        conditions.append(
            SurfacedCondition(
                "substrate-unreachable",
                "fleet swap state unreadable (unknown ≠ idle — deterministic-only)",
                machinery_health=True,
            )
        )

    if decision.mode is cadence.CycleMode.SKIP:
        return CycleResult(
            started_at=started_at,
            decision=decision,
            steps=tuple(steps),
            conditions=tuple(conditions),
        )

    # ── Step 2: absence reconcile, THEN TTL sweep (order is load-bearing) ──
    absence, ttl_expired = _absence_and_ttl_sweep(env, now, steps, conditions)
    absence_active = absence.active

    # ── Step 3: compose the snapshot (prior record injects the age basis) ──
    snapshot: "ws.WorkStateSnapshot | None" = None
    try:
        if env.compose_snapshot is not None:
            snapshot = env.compose_snapshot(now)
        else:
            snapshot = ws.compose_work_state(
                fleet_config=env.fleet_config,
                coordinator_projects=env.coordinator_projects,
                now=now,
                campaign_state_path=env.campaign_state_path,
                stall_seen_path=env.stall_seen_path,
                board_history_path=env.board_history_path,
                vikunja_transport=env.vikunja_transport,
            )
        steps.append(StepOutcome("compose-snapshot", True))
    except Exception as exc:  # noqa: BLE001 — a compose fault fails the cycle softly
        logger.warning("heartbeat_cycle: compose failed (fail-soft): %s", exc)
        steps.append(StepOutcome("compose-snapshot", False, f"{type(exc).__name__}: {exc}"))
        conditions.append(
            SurfacedCondition(
                "compose-failed", f"work-state compose failed: {exc}",
                machinery_health=True,
            )
        )
        return CycleResult(
            started_at=started_at,
            decision=decision,
            steps=tuple(steps),
            conditions=tuple(conditions),
            ttl_expired=ttl_expired,
            absence=absence,
        )

    for liveness in snapshot.substrate:
        if liveness.status is vb.ReadStatus.UNREACHABLE:
            conditions.append(
                SurfacedCondition(
                    "substrate-unreachable",
                    f"{liveness.name}: {liveness.error or 'unreachable'}",
                    machinery_health=True,
                )
            )

    # ── Step 4: board-history observe + write (AFTER compose; OK reads only) ──
    _observe_board_history(env, snapshot, now, steps, conditions)

    # ── Step 5: harvest the latest run → board movement (deterministic ruler) ──
    board_moves, run_truth = _harvest_and_move(env, snapshot, steps, conditions)

    # ── Step 6: stall pass (one comment per NEW episode; absence-filtered) ──
    stall_result = _stall_pass(env, snapshot, now, absence_active, steps, conditions)

    # ── Step 7: redispatch staging (trusted repo_id §5; whole call wrapped) ──
    redispatch, promoted = _stage_redispatch(env, snapshot, now, steps, conditions)

    # ── Step 8: quiet-queue tripwire (pure; suppressions surfaced) ──────────
    tripwire: TripwireResult | None = None
    try:
        tripwire = evaluate_quiet_queue_tripwire(
            snapshot,
            in_overnight_window=in_window,
            in_boot_grace=in_boot_grace,
            absence_active=absence_active,
            eligible_ready=env.eligible_ready,
        )
        steps.append(
            StepOutcome(
                "tripwire",
                True,
                "FIRED" if tripwire.fired else (
                    "suppressed: " + "; ".join(tripwire.suppressed_reasons)
                    if tripwire.suppressed_reasons
                    else "quiet conditions not met"
                ),
            )
        )
        if tripwire.fired:
            conditions.append(
                SurfacedCondition(
                    "quiet-queue-tripwire",
                    f"{tripwire.ready_eligible_total} eligible Ready item(s) and "
                    "nothing is pulling (WIP 0, no suppression window)",
                )
            )
        elif tripwire.suppressed_reasons and tripwire.ready_eligible_total > 0:
            conditions.append(
                SurfacedCondition(
                    "tripwire-suppressed",
                    "; ".join(tripwire.suppressed_reasons),
                    machinery_health=any(
                        r.startswith("PM substrate unreachable")
                        for r in tripwire.suppressed_reasons
                    ),
                )
            )
        if tripwire.gated_inventory:
            conditions.append(
                SurfacedCondition(
                    "gated-inventory",
                    f"{tripwire.gated_inventory} Ready item(s) resource-gated "
                    "(inventory, not an alarm)",
                )
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("heartbeat_cycle: tripwire failed (fail-soft): %s", exc)
        steps.append(StepOutcome("tripwire", False, f"{type(exc).__name__}: {exc}"))

    # ── Step 9: model drafting (FULL mode only; deferrals are normal) ───────
    drafts, drafts_by_kind = _draft(
        env, decision, snapshot, redispatch, run_truth, steps, conditions
    )

    # ── Step 9.5: prose guard (#946) — model spans validated, fail-closed ───
    # The harvested task names travel with the truth: they are the ONLY
    # vocabulary #1067's negated-failure carve-out accepts in a variable
    # position, and they come from the same snapshot leg compose_run_headline
    # reads — one harvest, several consumers, no re-derivation. An unreadable
    # leg yields an empty tuple, which NARROWS the carve-out rather than
    # widening it (fail-closed by construction, not by vigilance).
    #
    # The FULL harvested record travels — (task, result) pairs, the same shape
    # compose_run_headline takes. The guard partitions it itself: merged names
    # may only appear in a merged claim, non-merged names only in a
    # not-run/skipped/parked one. An earlier cut split it HERE and forwarded
    # merged-only names to every clause, which inverted the not-merged clause
    # completely — "bill-splitter was parked" accepted when it had merged, and
    # refused when it truly had. Splitting at one place removes the mismatch.
    # An unreadable leg yields an empty tuple, which NARROWS the carve-out
    # (fail-closed by construction, not by vigilance).
    _lr = snapshot.latest_run
    run_task_results: tuple[tuple[str, str], ...] = (
        tuple((o.task, o.result) for o in _lr.value[1])
        if _lr.status is vb.ReadStatus.OK and _lr.value is not None
        else ()
    )
    guarded = _guard_prose(run_truth, drafts_by_kind, steps, run_task_results)

    # ── Step 10: the digest (at most one; routing is limb 4's) ─────────────
    digest: DigestRecord | None = None
    try:
        digest = _compose_digest(
            env,
            started_at=started_at,
            decision=decision,
            snapshot=snapshot,
            conditions=conditions,
            stall_result=stall_result,
            tripwire=tripwire,
            run_truth=run_truth,
            guarded=guarded,
            absence_active=absence_active,
            prior_digest=prior_digest,
        )
        steps.append(StepOutcome("digest", True))
    except Exception as exc:  # noqa: BLE001 — every step is wrapped, this one too
        logger.warning("heartbeat_cycle: digest compose failed (fail-soft): %s", exc)
        steps.append(StepOutcome("digest", False, f"{type(exc).__name__}: {exc}"))

    return CycleResult(
        started_at=started_at,
        decision=decision,
        steps=tuple(steps),
        conditions=tuple(conditions),
        snapshot=snapshot,
        ttl_expired=ttl_expired,
        absence=absence,
        board_moves=tuple(board_moves),
        stall_result=stall_result,
        redispatch=redispatch,
        promoted_proposal_ids=tuple(promoted),
        tripwire=tripwire,
        drafts=tuple(drafts),
        digest=digest,
    )


# ---------------------------------------------------------------------------
# Step bodies (each fail-soft toward the cycle)
# ---------------------------------------------------------------------------


def _absence_and_ttl_sweep(
    env: CycleEnv,
    now: datetime,
    steps: list[StepOutcome],
    conditions: list[SurfacedCondition],
) -> "tuple[AbsenceOutcome, int]":
    """Design §8.2 + §2 step 2. The absence-exit TTL extension MUST land before any
    sweep runs — otherwise returning from an absence demotes every surfaced ask at
    once (the exact failure the sanctioned ``extend_ttl`` pause exists to prevent).
    On an extension fault the sweep is ALSO skipped this cycle and the stamp kept,
    so the pair retries together next cycle (overshoot bounded by the outage,
    surfaced, and in the conservative direction — asks live longer, never vanish)."""
    cfg = env.coordinator_config
    stamp_path = env.absence_stamp_path
    absent = bool(cfg.operator_absent)
    stamp, applied = _read_absence_stamp(stamp_path)
    stamp_exists = stamp_path.exists()

    absence = AbsenceOutcome(active=absent)
    sweep_allowed = not absent

    try:
        if absent:
            if stamp is None or applied:
                # No usable episode stamp: never stamped, unreadable/corrupt, or a
                # lingering ALREADY-APPLIED stamp from the previous episode (whose
                # clear failed) — each starts a fresh episode stamp.
                if stamp is None and not stamp_exists:
                    note = "operator absence began — TTLs paused"
                elif applied:
                    note = (
                        "operator absence began (previous episode's applied stamp "
                        "superseded) — TTLs paused"
                    )
                else:
                    note = (
                        "absence stamp unreadable — re-stamped (pause under-counts "
                        "from now; surfaced, conservative)"
                    )
                _atomic_write_json(
                    stamp_path,
                    {"absent_since": now.isoformat(), "noted_at": now.isoformat()},
                )
                absence = AbsenceOutcome(active=True, started_this_cycle=True, note=note)
                conditions.append(SurfacedCondition("operator-absence", note))
            steps.append(StepOutcome("absence-reconcile", True, "absence active"))
        elif stamp is not None:
            duration = now - stamp
            if duration < timedelta(0):
                duration = timedelta(0)
            extended = 0
            if applied:
                # The extension already landed a prior cycle; only the clear
                # remains (finding 3: a lingering stamp must NEVER re-extend).
                note = "absence stamp cleanup — extension already applied"
            else:
                if env.store is None:
                    raise RuntimeError(
                        "proposal store unavailable for absence TTL pause"
                    )
                extended = env.store.extend_ttl(delta=duration, now=now)
                note = (
                    f"operator absence ended — {extended} STAGED proposal TTL(s) "
                    f"extended by {duration.total_seconds():.0f}s"
                )
            try:
                stamp_path.unlink()
            except OSError:
                # Cannot clear (AV/indexer lock): pin the per-episode applied
                # marker atomically so the NEXT cycle only retries the clear —
                # the extension itself is applied exactly once per episode.
                _atomic_write_json(
                    stamp_path,
                    {
                        "absent_since": stamp.isoformat(),
                        "applied_at": now.isoformat(),
                    },
                )
            if applied:
                absence = AbsenceOutcome(active=False, note=note)
                steps.append(StepOutcome("absence-reconcile", True, note))
            else:
                absence = AbsenceOutcome(
                    active=False,
                    ended_this_cycle=True,
                    extended_count=extended,
                    paused_duration_s=duration.total_seconds(),
                    note=note,
                )
                conditions.append(SurfacedCondition("operator-absence-ended", note))
                steps.append(StepOutcome("absence-reconcile", True, note))
        else:
            steps.append(StepOutcome("absence-reconcile", True, "not absent"))
    except Exception as exc:  # noqa: BLE001 — keep the stamp; retry the pair next cycle
        logger.warning("heartbeat_cycle: absence reconcile failed (fail-soft): %s", exc)
        steps.append(
            StepOutcome("absence-reconcile", False, f"{type(exc).__name__}: {exc}")
        )
        conditions.append(
            SurfacedCondition(
                "absence-reconcile-failed",
                f"absence TTL pause could not be applied (sweep skipped, retried "
                f"next cycle): {exc}",
                machinery_health=True,
            )
        )
        sweep_allowed = False
        absence = AbsenceOutcome(active=absent, note=str(exc))

    ttl_expired = 0
    if not sweep_allowed:
        steps.append(
            StepOutcome(
                "ttl-sweep",
                True,
                "skipped (operator absent)" if absent else "skipped (absence reconcile failed)",
            )
        )
        return absence, ttl_expired

    if env.store is None:
        steps.append(StepOutcome("ttl-sweep", True, "skipped (no store)"))
        conditions.append(
            SurfacedCondition(
                "store-unavailable",
                "proposal store unavailable — TTL sweep and staging skipped",
                machinery_health=True,
            )
        )
        return absence, ttl_expired

    try:
        ttl_expired = env.store.expire_stale(now=now)
        steps.append(StepOutcome("ttl-sweep", True, f"{ttl_expired} demoted"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("heartbeat_cycle: TTL sweep failed (fail-soft): %s", exc)
        steps.append(StepOutcome("ttl-sweep", False, f"{type(exc).__name__}: {exc}"))
        conditions.append(
            SurfacedCondition(
                "store-fault", f"TTL sweep failed: {exc}", machinery_health=True
            )
        )
    return absence, ttl_expired


def _observe_board_history(
    env: CycleEnv,
    snapshot: "ws.WorkStateSnapshot",
    now: datetime,
    steps: list[StepOutcome],
    conditions: list[SurfacedCondition],
) -> None:
    """§2 step 4: pure diff AFTER compose, over ``OK`` board reads ONLY (the
    :func:`observe_board` caller precondition — an UNREACHABLE project's history is
    carried forward untouched). A CORRUPT record is rebuilt from this cycle's
    observations — the bounded, surfaced cold-start degradation (ages reset), chosen
    over a permanently-degraded record that only vigilance would notice."""
    try:
        read = bh.read_board_history(env.board_history_path)
        prior = read.state
        if read.corrupt:
            conditions.append(
                SurfacedCondition(
                    "board-history-corrupt",
                    f"record rebuilt this cycle (observed ages reset to cold start): "
                    f"{read.error}",
                    machinery_health=True,
                )
            )
            prior = bh.BoardHistoryState()
        state = prior
        observed = 0
        skipped: list[str] = []
        for project in snapshot.projects:
            if project.board.status is not vb.ReadStatus.OK:
                skipped.append(project.name)
                continue
            membership = bh.extract_bucket_membership(project.board.items)
            state = bh.observe_board(
                state, project_id=project.project_id, membership=membership, now=now
            )
            observed += 1
        if state.entries != prior.entries or read.corrupt:
            bh.write_board_history(
                bh.BoardHistoryState(entries=state.entries, updated_at=now.isoformat()),
                path=env.board_history_path,
            )
        detail = f"{observed} project(s) observed"
        if skipped:
            detail += f"; skipped (board not OK): {', '.join(skipped)}"
        steps.append(StepOutcome("board-history-observe", True, detail))
    except Exception as exc:  # noqa: BLE001
        logger.warning("heartbeat_cycle: board-history observe failed (fail-soft): %s", exc)
        steps.append(
            StepOutcome("board-history-observe", False, f"{type(exc).__name__}: {exc}")
        )
        conditions.append(
            SurfacedCondition(
                "board-history-fault",
                f"board-history observe failed: {exc}",
                machinery_health=True,
            )
        )


def _harvest_and_move(
    env: CycleEnv,
    snapshot: "ws.WorkStateSnapshot",
    steps: list[StepOutcome],
    conditions: list[SurfacedCondition],
) -> "tuple[list[BoardMoveRecord], RunTruth | None]":
    """§2 step 5: the latest run's STRUCTURED facts → the deterministic ruler → the
    routed move sink. ``oracle_passed`` comes only from the scorecard; a repeat move
    onto the current bucket is a no-op at the board, so re-driving this every cycle
    is crash-convergent by construction.

    Also returns the run's :class:`RunTruth` (#946): the SAME facts the ruler
    consumed, computed once here, feed the drafting contract, the prose guard,
    and the deterministic digest headline — one source of truth, no
    re-derivation. ``None`` when no finished run (or this leg faulted): with no
    truth there is no run drafting and no headline — fail-closed."""
    moves: list[BoardMoveRecord] = []
    truth: "RunTruth | None" = None
    try:
        lr = snapshot.latest_run
        if lr.status is not vb.ReadStatus.OK or lr.value is None:
            steps.append(StepOutcome("harvest-board-move", True, "no finished run"))
            return moves, truth
        run_id, outcomes = lr.value
        merged = any(o.result == RESULT_MERGED for o in outcomes)
        parked = any(o.result == RESULT_PARKED for o in outcomes)
        read_scorecard = env.read_scorecard or (
            lambda rid: _default_read_scorecard(env.fleet_config, rid)
        )
        oracle_passed = oracle_passed_from_scorecard(read_scorecard(run_id))
        truth = RunTruth(
            run_id=run_id,
            oracle_passed=oracle_passed,
            merged=merged,
            parked=parked,
        )
        transition = cl.resolve_board_transition(
            dispatch_started=True,
            oracle_passed=oracle_passed,
            merged=merged,
            parked=parked,
        )
        if transition is None:
            steps.append(
                StepOutcome("harvest-board-move", True, f"run {run_id}: no move warranted")
            )
            return moves, truth

        move_card = env.move_card or vb.move_job_card
        attempts: list[str] = []
        moved_record: BoardMoveRecord | None = None
        for name, project_id in env.coordinator_projects.items():
            result = move_card(project_id, run_id, transition.to_bucket)
            if result.moved:
                moved_record = BoardMoveRecord(
                    run_id=run_id,
                    to_bucket=transition.to_bucket,
                    reason=transition.reason,
                    moved=True,
                    project_id=project_id,
                    attempts=tuple(attempts),
                )
                break
            attempts.append(f"{name}: {result.reason}")
        if moved_record is None:
            moved_record = BoardMoveRecord(
                run_id=run_id,
                to_bucket=transition.to_bucket,
                reason=transition.reason,
                moved=False,
                attempts=tuple(attempts),
            )
            conditions.append(
                SurfacedCondition(
                    "board-move-not-applied",
                    f"run {run_id} → {transition.to_bucket!r}: no configured project "
                    f"accepted the move ({'; '.join(attempts) or 'no projects configured'})",
                )
            )
        moves.append(moved_record)
        steps.append(
            StepOutcome(
                "harvest-board-move",
                True,
                f"run {run_id} → {transition.to_bucket!r} "
                f"({'moved' if moved_record.moved else 'not applied'})",
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("heartbeat_cycle: harvest/board-move failed (fail-soft): %s", exc)
        steps.append(
            StepOutcome("harvest-board-move", False, f"{type(exc).__name__}: {exc}")
        )
    return moves, truth


def _stall_pass(
    env: CycleEnv,
    snapshot: "ws.WorkStateSnapshot",
    now: datetime,
    absence_active: bool,
    steps: list[StepOutcome],
    conditions: list[SurfacedCondition],
) -> "csm.StallCycleResult | None":
    """§2 step 6. During operator absence only Expedite-class stalls post (§8.2);
    a suppressed post reads as a failed post to the seen-set algebra, so it is NOT
    persisted and retries naturally on the first present cycle — episode semantics
    and the anti-firehose invariant both hold across the absence."""
    try:
        current: list[cl.StallSignal] = []
        for project in snapshot.projects:
            current.extend(project.stalls)
        post_sink: csm.PostComment = env.post_stall_comment or vb.post_task_comment
        if absence_active:
            expedite_ids = {
                s.task_id for s in current if s.service_class is cl.ServiceClass.EXPEDITE
            }
            real_post = post_sink

            def _absent_post(task_id: int, text: str) -> bool:
                if task_id not in expedite_ids:
                    return False  # suppressed (absence): not persisted, retried later
                return real_post(task_id, text)

            post_sink = _absent_post

        result = csm.run_stall_cycle(
            current, seen_path=env.stall_seen_path, post_comment=post_sink, now=now
        )
        if absence_active:
            suppressed_count = sum(
                1
                for signal, _reason in result.post_failures
                if signal.service_class is not cl.ServiceClass.EXPEDITE
            )
            if suppressed_count:
                conditions.append(
                    SurfacedCondition(
                        "stall-comments-suppressed",
                        f"{suppressed_count} non-Expedite stall comment(s) held during "
                        "operator absence (retried on return)",
                    )
                )
        steps.append(
            StepOutcome(
                "stall-pass",
                True,
                f"{len(result.posted)} posted, {len(result.ongoing)} ongoing, "
                f"{len(result.post_failures)} deferred/failed",
            )
        )
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("heartbeat_cycle: stall pass failed (fail-soft): %s", exc)
        steps.append(StepOutcome("stall-pass", False, f"{type(exc).__name__}: {exc}"))
        return None


def _stage_redispatch(
    env: CycleEnv,
    snapshot: "ws.WorkStateSnapshot",
    now: datetime,
    steps: list[StepOutcome],
    conditions: list[SurfacedCondition],
) -> "tuple[cr.RedispatchCycleResult | None, list[str]]":
    """§2 step 7 (design §5). The trusted ``repo_id`` comes ONLY from the
    dispatch-written acceptance record; no structured record ⇒ no staging + a
    surfaced condition (fail-closed targeting, fail-soft cycle). The WHOLE
    ``stage_redispatch_proposals`` invocation is wrapped (the #844 c.1876 caller
    obligation). Live mode promotes fresh DRAFTs to STAGED; shadow keeps DRAFTs."""
    promoted: list[str] = []
    try:
        lr = snapshot.latest_run
        if lr.status is not vb.ReadStatus.OK or lr.value is None:
            steps.append(StepOutcome("redispatch-staging", True, "no finished run"))
            return None, promoted
        run_id, outcomes = lr.value
        if not any(o.result in cr.REDISPATCH_ELIGIBLE_RESULTS for o in outcomes):
            steps.append(
                StepOutcome("redispatch-staging", True, "no redispatch-eligible outcome")
            )
            return None, promoted
        if env.store is None:
            steps.append(StepOutcome("redispatch-staging", True, "skipped (no store)"))
            return None, promoted

        read_acceptance = env.read_acceptance or (
            lambda rid: read_acceptance_record(env.fleet_config, rid)
        )
        record = read_acceptance(run_id)
        repo_raw = record.get("repo") if isinstance(record, Mapping) else None
        repo_id, refuse_reason = normalize_trusted_repo_id(
            repo_raw, projects_dir=env.fleet_config.projects_dir
        )
        if repo_id is None:
            detail = (
                f"run {run_id}: no trusted repo id from the dispatch record — "
                f"staging skipped ({refuse_reason}); the target is never recovered "
                "from run-report text"
            )
            steps.append(StepOutcome("redispatch-staging", True, detail))
            conditions.append(SurfacedCondition("redispatch-target-unresolved", detail))
            return None, promoted

        result = cr.stage_redispatch_proposals(
            outcomes,
            run_id=run_id,
            repo_id=repo_id,
            projects_dir=env.fleet_config.projects_dir,
            roots=env.roots,
            store=env.store,
            runs_dir=env.fleet_config.runs_dir,
            now=now,
        )
        if not env.shadow_mode:
            promotion_ids = [s.proposal_id for s in result.staged]
            # Review 66789b24 finding 1: a crash/fault between add_draft and
            # mark_staged leaves a NEVER-SURFACED DRAFT (staged_at == "") that the
            # stager reports as deduped, not staged — without this, it would strand
            # in DRAFT forever (dedup keeps finding it; expire_stale only sweeps
            # STAGED). Re-promote exactly those. A TTL-demoted DRAFT carries a
            # non-empty staged_at and is deliberately NOT re-surfaced here (that
            # would rebuild the wall of stale asks §2.12.5 forbids).
            for dup in result.deduped:
                proposal = env.store.get(dup.proposal_id)
                if (
                    proposal is not None
                    and proposal.status is ProposalStatus.DRAFT
                    and not proposal.staged_at
                ):
                    promotion_ids.append(dup.proposal_id)
            for proposal_id in promotion_ids:
                try:
                    env.store.mark_staged(proposal_id, now=now)
                    promoted.append(proposal_id)
                except Exception as exc:  # noqa: BLE001 — per-proposal fail-soft
                    logger.warning(
                        "heartbeat_cycle: promotion of %s failed (stays DRAFT): %s",
                        proposal_id,
                        exc,
                    )
                    conditions.append(
                        SurfacedCondition(
                            "store-fault",
                            f"DRAFT→STAGED promotion failed for {proposal_id}: {exc} "
                            "(stays a never-surfaced DRAFT; the dedup path re-promotes "
                            "it next cycle)",
                            machinery_health=True,
                        )
                    )
        steps.append(
            StepOutcome(
                "redispatch-staging",
                True,
                f"run {run_id}: {len(result.staged)} staged, {len(result.deduped)} "
                f"deduped, {len(result.refused)} refused, {len(promoted)} promoted",
            )
        )
        if result.refused:
            conditions.append(
                SurfacedCondition(
                    "redispatch-refused",
                    f"run {run_id}: {result.refused[0].reason}",
                )
            )
        return result, promoted
    except Exception as exc:  # noqa: BLE001 — the #844 c.1876 whole-invocation wrap
        logger.warning("heartbeat_cycle: redispatch staging failed (fail-soft): %s", exc)
        steps.append(
            StepOutcome("redispatch-staging", False, f"{type(exc).__name__}: {exc}")
        )
        conditions.append(
            SurfacedCondition(
                "redispatch-staging-failed",
                f"stage_redispatch_proposals raised (retried next cycle — no "
                f"proposal was written): {exc}",
                machinery_health=True,
            )
        )
        return None, promoted


def _draft(
    env: CycleEnv,
    decision: cadence.CycleDecision,
    snapshot: "ws.WorkStateSnapshot",
    redispatch: "cr.RedispatchCycleResult | None",
    run_truth: "RunTruth | None",
    steps: list[StepOutcome],
    conditions: list[SurfacedCondition],
) -> "tuple[list[DraftOutcome], dict[str, DraftOutcome]]":
    """§2 step 9: bounded single-decision drafting, FULL mode only. The prompt is
    composed HERE by deterministic code from the snapshot's already-composed legs
    (§2.14.5 — the model never navigates to a fourth source). ``busy`` /
    ``not_resident`` stop further calls this cycle (one deferral is the fact; the
    next cycle retries). No correctness depends on any of this.

    #946 drafting contract: the run summary is drafted ONLY when the harvest leg
    produced a :class:`RunTruth` (no truth → no run prose, fail-closed), and its
    prompt carries the deterministic verdict plus the verdict-echo requirement
    the prose guard enforces. Returns ``(all outcomes, outcomes by kind)`` —
    kinds are ``"run_summary"`` / ``"proposal"`` — so the guard step validates
    each span against the right contract."""
    if decision.mode is not cadence.CycleMode.FULL:
        steps.append(
            StepOutcome(
                "drafting", True, "deferred: " + "; ".join(decision.reasons or ("mode",))
            )
        )
        return [], {}
    if env.draft is None:
        steps.append(StepOutcome("drafting", True, "no drafting seam wired (dormant)"))
        return [], {}

    prompts: list[tuple[str, str]] = []
    lr = snapshot.latest_run
    if lr.status is vb.ReadStatus.OK and lr.value is not None:
        if run_truth is None:
            steps.append(
                StepOutcome(
                    "drafting-run-summary",
                    True,
                    "run summary not drafted: harvest produced no truth "
                    "(fail-closed — no verdict, no prose)",
                )
            )
        else:
            run_id, outcomes = lr.value
            facts = "; ".join(f"{o.task}: {o.result}" for o in outcomes)
            verdict = run_truth.verdict()
            prompts.append(
                (
                    DRAFT_KIND_RUN_SUMMARY,
                    f"The run's recorded verdict is {verdict}. Begin your reply "
                    f'with exactly "{verdict}: " and do not contradict this '
                    "verdict. Summarize this finished coding-fleet run in two "
                    "plain-language sentences for the operator. "
                    # #1067: the measured false-suppression case is prose that
                    # states a failure by NEGATING a success word ("the run did
                    # not complete successfully"). Deciding whether such a
                    # sentence asserts success or failure is a parsing problem
                    # the guard cannot do reliably — six designs were rejected
                    # trying. Asking for the positive statement of the failure
                    # instead removes the ambiguity at the source, and costs
                    # nothing: it never widens what the guard accepts, so there
                    # is no new way for a false claim to get through.
                    + (
                        "State what happened directly rather than by negating a "
                        'success word: write "the run did not finish" rather '
                        'than "the run did not complete successfully". '
                        if verdict != VERDICT_SUCCEEDED
                        else ""
                    )
                    + f"Run {run_id} outcomes: {facts}.",
                )
            )
    if redispatch is not None and redispatch.staged:
        first = redispatch.staged[0]
        prompts.append(
            (
                DRAFT_KIND_PROPOSAL,
                "In one plain-language sentence, describe this pending proposal "
                f"for the operator: redispatch of parked task {first.task!r}.",
            )
        )

    results: list[DraftOutcome] = []
    by_kind: dict[str, DraftOutcome] = {}
    for kind, prompt in prompts:
        try:
            outcome = env.draft(prompt)
        except Exception as exc:  # noqa: BLE001 — the seam is fail-soft
            outcome = DraftOutcome(status="failed", reason=f"draft seam raised: {exc}")
        results.append(outcome)
        by_kind[kind] = outcome
        if outcome.status in ("busy", "not_resident"):
            conditions.append(
                SurfacedCondition(
                    "drafting-deferred",
                    f"model drafting deferred ({outcome.status}) — deterministic "
                    "skeleton stands in",
                )
            )
            break  # a deferral is the cycle's answer; never queue behind the model
    steps.append(
        StepOutcome(
            "drafting",
            True,
            ", ".join(r.status for r in results) if results else "nothing to draft",
        )
    )
    return results, by_kind


#: The one process-wide guard instance (#946). Deliberately not injectable via
#: ``CycleEnv``: the guard is integrity machinery, not a seam — tests exercise
#: it through the REAL instance (and prove the locks off via direct
#: construction, principle 12), never by substituting a permissive fake here.
_PROSE_GUARD: Final[ProseGuard] = ProseGuard()


@dataclass(frozen=True)
class GuardedProse:
    """The prose-guard step's outcome (#946): at most one accepted span for the
    digest, plus the audit trail the shadow journal keeps."""

    accepted_text: str = ""
    action: str = ""
    rejected_text: str = ""


def _guard_prose(
    run_truth: "RunTruth | None",
    drafts_by_kind: "dict[str, DraftOutcome]",
    steps: list[StepOutcome],
    run_task_results: "Sequence[tuple[str, str]]" = (),
) -> GuardedProse:
    """§2 step 9.5 (#946): validate the drafted span that would become the
    digest's ``model_prose``. Run summaries validate against the harvest truth
    (verdict echo + consistency screen); verdict-less annotations pass the
    success-claim screen only. A refused draft is DROPPED — no fall-through to
    a second span, no rewrite — the deterministic skeleton and headline stand
    alone, and the raw refusal is preserved for the #855 false-refusal
    measurement.

    *run_task_results* carries this run's harvested ``(task, result)`` pairs to
    #1067's negated-failure carve-out, which accepts that vocabulary and
    nothing else in its variable positions and partitions it by result itself.
    Defaulting to empty keeps every caller fail-closed: no vocabulary means the
    carve-out consumes strictly less."""
    for kind in DRAFT_KINDS:
        outcome = drafts_by_kind.get(kind)
        if outcome is None or outcome.status != "drafted" or not outcome.text:
            continue
        if kind == DRAFT_KIND_RUN_SUMMARY:
            if run_truth is None:
                # _draft never drafts a run summary without truth; keep the
                # refusal anyway so a future regression fails closed, not open.
                decision = GuardDecision(False, "rejected:no-truth")
            else:
                decision = _PROSE_GUARD.validate_run_summary(
                    run_truth, outcome.text, task_results=run_task_results
                )
        else:
            decision = _PROSE_GUARD.validate_annotation(
                outcome.text, task_results=run_task_results
            )
        steps.append(StepOutcome("prose-guard", True, f"{kind}: {decision.action}"))
        if decision.accepted:
            return GuardedProse(
                accepted_text=outcome.text.strip(), action=decision.action
            )
        return GuardedProse(action=decision.action, rejected_text=outcome.text)
    return GuardedProse()


def _compose_digest(
    env: CycleEnv,
    *,
    started_at: str,
    decision: cadence.CycleDecision,
    snapshot: "ws.WorkStateSnapshot",
    conditions: list[SurfacedCondition],
    stall_result: "csm.StallCycleResult | None",
    tripwire: TripwireResult | None,
    run_truth: "RunTruth | None",
    guarded: GuardedProse,
    absence_active: bool,
    prior_digest: DigestRecord | None,
) -> DigestRecord:
    """§2 step 10 / §7.4: the deterministic skeleton — now including the #946
    deterministic verdict headline — plus step-9 prose ONLY when the prose
    guard accepted it. Never raises (pure over already-computed values)."""
    open_by_project: dict[str, int] = {}
    for project in snapshot.projects:
        if project.flow is not None:
            open_by_project[project.name] = project.flow.open_count
    open_delta: dict[str, int] = {}
    if prior_digest is not None:
        for name, count in open_by_project.items():
            prior = prior_digest.open_by_project.get(name)
            if prior is not None:
                open_delta[name] = count - prior

    proposals_pending = 0
    if env.store is not None:
        try:
            proposals_pending = len(env.store.list_active())
        except Exception:  # noqa: BLE001 — the store fault is already surfaced upstream
            proposals_pending = 0

    lr = snapshot.latest_run
    runs = (
        (lr.value[0],)
        if lr.status is vb.ReadStatus.OK and lr.value is not None
        else ()
    )

    run_headline = ""
    if (
        run_truth is not None
        and lr.status is vb.ReadStatus.OK
        and lr.value is not None
    ):
        run_headline = compose_run_headline(
            run_truth, [(o.task, o.result) for o in lr.value[1]]
        )

    prose = guarded.accepted_text

    return DigestRecord(
        cycle_started_at=started_at,
        mode=decision.mode.value,
        queue_depth=dict(tripwire.ready_by_project) if tripwire is not None else {},
        open_by_project=open_by_project,
        open_delta_by_project=open_delta,
        stalls_new=len(stall_result.posted) if stall_result is not None else 0,
        stalls_ongoing=len(stall_result.ongoing) if stall_result is not None else 0,
        conditions=tuple(conditions),
        proposals_pending=proposals_pending,
        runs_harvested=runs,
        gated_inventory=tripwire.gated_inventory if tripwire is not None else 0,
        model_prose=prose,
        model_drafted=bool(prose),
        absence_accumulated=absence_active,
        run_headline=run_headline,
        prose_guard_action=guarded.action,
        model_prose_rejected=guarded.rejected_text,
    )
