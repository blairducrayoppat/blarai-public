"""Deterministic lifecycle-coordination decisions (#844 C2, ADR-039 §2.8/§2.10).

The C2 event-driven lifecycle **decision core**. Every function here is a PURE
deterministic transform — no I/O, no Vikunja calls, no clock reads (the caller
supplies ``now``), no model judgment. This is "gate as JUDGE, model as SIGNAL"
(ADR-039 §2.8) applied to the Kanban lifecycle: cards move, tickets become
Ready, and stalls are detected by *code over structured facts*, never by model
opinion.

It answers the questions C2's live limbs and C3's heartbeat ask — how is this
ticket classified (class of service), may this event move this card (board
transition), is this ticket Ready (Definition of Ready), what is stalling
(per-class aging outliers) — while the SIDE EFFECTS those answers drive are the
**C2 second increment** (#844) and are NOT wired here:

  * live board moves (Vikunja bucket writes),
  * stall comments + the operator surface (the anti-firehose "exactly one
    comment + one surface" enforcement — this module supplies the dedup
    *fingerprint*; the seen-set state that makes it one-per-cycle is the live
    limb's),
  * PARKED-HONEST → staged redispatch *proposal* (approval-gated; this module
    supplies the SG-checked target, via #848's ``governed_core``),
  * ACP ``session/update``-stream monitoring,
  * driver-integrated stop-doomed-fast checks (``swap_driver``/``swap_ops`` —
    a battery-sensitive surface, deliberately not touched by this increment).

DORMANCY: this module performs no action and holds no state; importing it
changes nothing. It is the deterministic ruler the approval-gated,
dormant-by-default C2 limbs consult — never an actor. It reuses C1's
:mod:`shared.fleet.flow_metrics` (the age/outlier math) and #848's
:mod:`shared.coordinator.governed_core` (the self-governance target ruler), so
the self-governance boundary is enforced by the *same* code the SG phase
regression-locks, never re-implemented here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

from shared.coordinator.governed_core import (
    GovernedCoreRoots,
    check_target,
    derive_workspace_target,
)
from shared.fleet.flow_metrics import (
    DEFAULT_AGE_BASIS_FIELD,
    DEFAULT_OUTLIER_THRESHOLD_STDDEV,
    WorkItemAge,
    aging_wip_outliers,
    compute_ages,
)

# ---------------------------------------------------------------------------
# Canonical Kanban vocabulary — the SINGLE SOURCE OF TRUTH (ADR-039 §2.8).
# ``tools/dispatch_harness/coordinator_setup.py`` (the operator-run substrate
# migration) imports these, so the buckets/labels the migration CREATES and the
# ones the runtime coordinator REASONS about can never drift apart — one list,
# resolved by NAME at runtime, never a hardcoded id (the stale-label-id lesson).
# ---------------------------------------------------------------------------

#: The 5-stage Kanban workflow, in board order (ADR-039 §2.8).
KANBAN_BUCKETS: tuple[str, ...] = (
    "Backlog",
    "Ready",
    "In Progress",
    "In Review/Verify",
    "Done",
)
(
    BUCKET_BACKLOG,
    BUCKET_READY,
    BUCKET_IN_PROGRESS,
    BUCKET_REVIEW,
    BUCKET_DONE,
) = KANBAN_BUCKETS


class ServiceClass(Enum):
    """The 4 Kanban classes of service (ADR-039 §2.8), highest-pull-priority first.

    The enum's declaration order IS the pull-priority order (Expedite jumps the
    queue; Standard is the FIFO default; Intangible is pulled only when nothing
    else is Ready) — :meth:`pull_rank` reads it, so the ordering lives in one
    place. The *value* is the exact Vikunja label title (name-resolved, never an
    id)."""

    EXPEDITE = "Expedite"
    FIXED_DATE = "Fixed-date"
    STANDARD = "Standard"
    INTANGIBLE = "Intangible"

    @property
    def pull_rank(self) -> int:
        """0 = pulled first. Derived from declaration order (single source)."""
        return list(ServiceClass).index(self)


#: Class-of-service label titles + their board-legible colors — the SSOT the
#: operator-run substrate migration creates from. Order matches
#: :class:`ServiceClass` declaration order.
CLASSES_OF_SERVICE: tuple[tuple[str, str], ...] = (
    ("Expedite", "e91e63"),  # pink — jump the queue, one at a time
    ("Fixed-date", "ff9800"),  # orange — pulled early enough to make the due date
    ("Standard", "2196f3"),  # blue — default FIFO
    ("Intangible", "9e9e9e"),  # gray — maintenance/docs, pulled when nothing else
)

#: The default class when a ticket carries NO class-of-service label — Standard
#: (FIFO), per ADR-039 §2.8. A label-less ticket is ordinary work, never dropped
#: to Intangible (which would silently de-prioritize un-triaged work).
DEFAULT_SERVICE_CLASS: ServiceClass = ServiceClass.STANDARD


def _label_titles(task: Mapping[str, Any]) -> frozenset[str]:
    """The set of label titles on *task* (case-sensitive, Vikunja's own form).

    Fail-soft: a ``None``/missing/malformed ``labels`` field (Vikunja renders an
    unlabeled task's ``labels`` as ``null``) yields the empty set, never a
    crash — label data is ticket-adjacent untrusted input (ADR-039 §2.7)."""
    raw = task.get("labels")
    if not isinstance(raw, (list, tuple)):
        return frozenset()
    titles: set[str] = set()
    for entry in raw:
        if isinstance(entry, Mapping):
            title = entry.get("title")
            if isinstance(title, str) and title:
                titles.add(title)
    return frozenset(titles)


def classify_service_class(task: Mapping[str, Any]) -> ServiceClass:
    """Deterministically classify *task* into a :class:`ServiceClass` by label.

    A ticket may carry several labels; the HIGHEST-priority class-of-service
    label wins (Expedite > Fixed-date > Standard > Intangible — the
    :class:`ServiceClass` declaration order), so an Expedite-flagged ticket that
    is also labelled Standard is treated as Expedite. A ticket with NO
    class-of-service label is :data:`DEFAULT_SERVICE_CLASS` (Standard). Pure and
    fail-soft — the model never classifies; a label set by deterministic code or
    an operator does."""
    titles = _label_titles(task)
    for service_class in ServiceClass:  # declaration order == priority order
        if service_class.value in titles:
            return service_class
    return DEFAULT_SERVICE_CLASS


# ---------------------------------------------------------------------------
# Board movement — deterministic event -> bucket transition (ADR-039 §2.8:
# "cards move on real events, never model opinion").
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BoardTransition:
    """A single deterministic board move: which bucket, and the fact that drove it."""

    to_bucket: str
    reason: str


def resolve_board_transition(
    *,
    dispatch_started: bool = False,
    oracle_passed: bool = False,
    merged: bool = False,
    parked: bool = False,
) -> BoardTransition | None:
    """The bucket a card should move to, derived ONLY from verifiable facts.

    The inputs are structured booleans a caller derives from real dispatch
    events / the fleet gate — NEVER a model's claim that a job "is done". The
    move to **Done** requires BOTH ``oracle_passed`` AND ``merged`` (the existing
    GREEN-plus-merged close discipline): a forged or premature "done" — merged
    without an oracle pass, or an oracle pass never merged — can NEVER produce a
    Done transition (it falls through to the in-progress/None cases). This is the
    "a forged event cannot move a card to Done without GREEN+oracle" acceptance
    lock (#844), enforced by construction here rather than by a caller's
    discipline.

    Precedence (a card can satisfy several at once): Done > Parked > In Progress.
    Returns ``None`` when no fact warrants a move (e.g. nothing started yet), so a
    no-op is explicit, never a spurious transition."""
    if oracle_passed and merged:
        return BoardTransition(BUCKET_DONE, "oracle GREEN + merged (close discipline)")
    if parked:
        return BoardTransition(
            BUCKET_READY, "PARKED-HONEST — returned to Ready for redispatch review"
        )
    if dispatch_started:
        return BoardTransition(BUCKET_IN_PROGRESS, "dispatch started")
    return None


# ---------------------------------------------------------------------------
# Definition of Ready — the deterministic gate a ticket passes before it may
# enter the Ready bucket / be pulled into PLAN (ADR-039 §2.8).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DoRResult:
    """The Definition-of-Ready verdict for one ticket."""

    ready: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)
    """The failure reasons if not ready (empty when ready) — an operator-legible
    checklist of exactly what is missing, never a bare bool."""


def has_acceptance_criteria(task: Mapping[str, Any]) -> bool:
    """True iff *task* carries a non-trivial description (its acceptance criteria).

    A deterministic, deliberately simple content check: a description with real
    content (more than a few characters of non-whitespace) is treated as present.
    The Coordinator *proposes* refinements to get a Backlog item Ready (lane-a
    proposals, ADR-039 §2.8); it never fakes readiness, so an empty/near-empty
    description fails the gate rather than passing silently."""
    description = task.get("description")
    if not isinstance(description, str):
        return False
    return len(description.strip()) >= 12


def evaluate_dor(
    task: Mapping[str, Any],
    *,
    target_repo_id: str | None = None,
    projects_dir: str | Path | None = None,
    roots: GovernedCoreRoots | None = None,
    has_open_blocker: bool = False,
) -> DoRResult:
    """Deterministic Definition-of-Ready checklist (ADR-039 §2.8).

    A ticket is Ready only when ALL hold; each failure is reported so the
    Coordinator (or operator) knows exactly what to fix:

    1. **Acceptance criteria present** — a non-trivial description
       (:func:`has_acceptance_criteria`).
    2. **Target valid under the SG ruler** — ONLY for a dispatch-bound ticket
       (one that names a ``target_repo_id``). The target is re-derived from that
       TRUSTED, structured id by #848's :func:`derive_workspace_target` (the
       CaMeL rule — never from model free text) and then must pass
       :func:`check_target` (not governed core; under ``projects_dir``). A ticket
       with no ``target_repo_id`` is a non-dispatch item (docs, an advisory) and
       skips this check — it has no execution target to validate. When a
       ``target_repo_id`` IS given, ``projects_dir`` and ``roots`` are REQUIRED;
       their absence is a fail-closed "cannot validate" (never a silent pass).
    3. **No unresolved blocker relation** — ``has_open_blocker`` (a Vikunja
       blocking relation whose blocker ticket is still open) is derived by the
       caller from the ticket's relations and gates the item OUT of Ready.

    Pure: no I/O; the filesystem reads live inside #848's ``governed_core``
    (``check_target`` resolves paths), which is the intended, regression-locked
    self-governance ruler."""
    reasons: list[str] = []

    if not has_acceptance_criteria(task):
        reasons.append("no acceptance criteria (empty or near-empty description)")

    if target_repo_id:
        if projects_dir is None or roots is None:
            reasons.append(
                "dispatch target given but projects_dir/roots unavailable — "
                "cannot validate target (fail-closed)"
            )
        else:
            derived = derive_workspace_target(
                target_repo_id, projects_dir=projects_dir
            )
            if derived is None:
                reasons.append(
                    f"target repo id {target_repo_id!r} is not a plain workspace "
                    "component (SG ruler, fail-closed)"
                )
            else:
                verdict = check_target(
                    derived, roots=roots, projects_dir=projects_dir, phase="DoR"
                )
                if verdict.denied:
                    reasons.append(f"target refused by SG ruler: {verdict.reason}")

    if has_open_blocker:
        reasons.append("has an unresolved blocking relation")

    return DoRResult(ready=not reasons, reasons=tuple(reasons))


# ---------------------------------------------------------------------------
# Principled stall detection — per class-of-service aging outliers, so "stalled"
# means "a statistical outlier for ITS class" (ADR-039 §2.8), not a flat timeout.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StallSignal:
    """One detected stall: a work item whose age is an outlier for its class."""

    task_id: int
    title: str
    service_class: ServiceClass
    age_seconds: float
    fingerprint: str
    """A deterministic ``class:task_id`` fingerprint. The live C2 limb dedups on
    this so a condition detected every cycle stages ONE comment/surface, not one
    per cycle (the anti-firehose invariant, ADR-039 §2.8 / review F11) — this
    module supplies the fingerprint; the seen-set state is the limb's."""


def stall_fingerprint(service_class: ServiceClass, task_id: int) -> str:
    """The deterministic dedup key for a stall on *task_id* in *service_class*."""
    return f"{service_class.value}:{task_id}"


def detect_stalls(
    open_tasks: Sequence[Mapping[str, Any]],
    *,
    now: datetime,
    age_basis_field: str = DEFAULT_AGE_BASIS_FIELD,
    outlier_threshold_stddev: float = DEFAULT_OUTLIER_THRESHOLD_STDDEV,
) -> list[StallSignal]:
    """Per-class aging-outlier stall detection over *open_tasks*.

    Groups the open tasks by :func:`classify_service_class`, then within EACH
    class applies C1's :func:`shared.fleet.flow_metrics.aging_wip_outliers` (age >
    mean + k·stddev) — so "stalled" is relative to the item's own class-of-service
    baseline, never a single global timeout that would false-alarm a legitimately
    long Standard item while missing a stuck Expedite one. Fewer than 2 items in a
    class yields no outliers by construction (no meaningful stddev), so a small
    board never false-alarms.

    Deterministic and fail-soft: an unparseable age timestamp drops that item from
    the statistic (C1's ``compute_ages`` contract), never crashes the pass.
    Results are sorted by ``(pull_rank, -age_seconds, task_id)`` — most urgent
    class first, oldest first within a class — a stable order the caller can rely
    on. No I/O; ``now`` is supplied by the caller."""
    by_class: dict[ServiceClass, list[Mapping[str, Any]]] = {}
    for task in open_tasks:
        by_class.setdefault(classify_service_class(task), []).append(task)

    signals: list[StallSignal] = []
    for service_class, tasks in by_class.items():
        ages = compute_ages(tasks, now=now, basis_field=age_basis_field)
        outliers = aging_wip_outliers(
            ages, threshold_stddev=outlier_threshold_stddev
        )
        for age in outliers:
            signals.append(
                StallSignal(
                    task_id=age.task_id,
                    title=age.title,
                    service_class=service_class,
                    age_seconds=age.age_seconds,
                    fingerprint=stall_fingerprint(service_class, age.task_id),
                )
            )

    signals.sort(
        key=lambda s: (s.service_class.pull_rank, -s.age_seconds, s.task_id)
    )
    return signals


def new_stall_signals(
    signals: Sequence[StallSignal],
    already_seen: "frozenset[str] | set[str]",
) -> list[StallSignal]:
    """The subset of *signals* whose fingerprint is NOT in *already_seen*.

    The pure half of the anti-firehose invariant: the live C2 limb keeps the
    ``already_seen`` fingerprint set across cycles and posts a comment/surface
    ONLY for the signals this returns, so a stall detected every cycle produces
    exactly one comment, not one per cycle. State lives in the caller; the set
    algebra is deterministic here."""
    return [s for s in signals if s.fingerprint not in already_seen]
