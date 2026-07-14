"""Deterministic flow-metrics computation (#843, ADR-039 §2.8 / §2.12.8).

Cycle time, throughput, work-item age, and aging-WIP — computed from Vikunja
task timestamps (tz-aware), never from model judgment. This is the "gate as
JUDGE, model as SIGNAL" discipline (ADR-039 §2.8) applied to the Kanban
method itself: every function here is a PURE function over the task dicts
:mod:`shared.fleet.vikunja_bridge`'s read surface returns — no I/O, no
Vikunja calls, no clock reads (the caller supplies ``now``/window bounds so
the whole module stays a deterministic, fixture-testable transform).

OPEN DECISION, NOT MADE HERE (ADR-039 §2.14.2 — "the most load-bearing open
item" the ADR carries to implementation). Vikunja holds no bucket-transition
history, so "age in Ready" / per-stage cycle time has no native data source
today; the ADR names two mechanism options (heartbeat snapshot-diffing each
cycle, and/or the Coordinator journaling its own bucket moves) and leaves
the choice between "age = ticket-created" and "age = entered-Ready" for
"C1/C3 implementation kickoff, with both options on the table and no default
preference stated." This module computes age from the ONE timestamp Vikunja
natively provides today WITHOUT any additional infrastructure — ``created``
— via the explicit, swappable :data:`DEFAULT_AGE_BASIS_FIELD`. This is a
provisional, LA-confirmable choice, not a resolution of the ADR's open
question: swapping to an entered-Ready basis (once #845's snapshot-diffing
or a bucket-move journal exists) is a single ``age_basis_field`` argument
change at every call site — nothing else in this module assumes the CREATED
basis. Flagged prominently in the C1 report this module ships with.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

#: The provisional age-timestamp source (ADR-039 §2.14.2 — OPEN, see the
#: module docstring). Vikunja's native ``created`` field is the only
#: zero-additional-infrastructure option; ``entered_ready`` is the ADR's
#: named alternative and requires bucket-transition tracking this module
#: does not (and structurally cannot, on its own) provide.
DEFAULT_AGE_BASIS_FIELD: str = "created"

#: Aging-WIP outlier sensitivity (ADR-039 §2.8: "an item whose age is a
#: statistical outlier for its class"). 1.5 standard deviations above the
#: group mean — a conservative default (roughly the top ~7% of a normal
#: distribution) chosen to flag genuine stragglers without false-alarming on
#: ordinary variance; tunable per call, never a magic constant callers can't
#: override.
DEFAULT_OUTLIER_THRESHOLD_STDDEV: float = 1.5


def parse_vikunja_timestamp(raw: "str | None") -> datetime | None:
    """Parse a Vikunja RFC3339 timestamp into a tz-AWARE UTC ``datetime``.

    Accepts a ``Z`` UTC suffix or an explicit ``+HH:MM`` offset. A naive
    (offset-less) timestamp is treated as UTC (Vikunja's own convention)
    rather than rejected, so a differently-shaped-but-still-ISO record still
    parses. Fail-soft: returns ``None`` for empty/malformed input — never
    raises. Ticket-adjacent timestamps are untrusted-input-adjacent (ADR-039
    §2.7); a malformed one must degrade this module's signal to "no data
    point", never crash a flow-metrics pass over an otherwise-healthy board.
    """
    text = (raw or "").strip()
    if not text:
        return None
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class WorkItemAge:
    """The age of one work item as of a given instant."""

    task_id: int
    title: str
    age_seconds: float
    basis_field: str
    """Which task field the age was computed from (see
    :data:`DEFAULT_AGE_BASIS_FIELD` and the module's open-decision note)."""


def compute_age(
    task: Mapping[str, Any],
    *,
    now: datetime,
    basis_field: str = DEFAULT_AGE_BASIS_FIELD,
) -> WorkItemAge | None:
    """Age of *task* as of *now*, computed from ``task[basis_field]``.

    Returns ``None`` (fail-soft) if the timestamp is missing or
    unparseable — an unparseable timestamp must never silently compute as
    ``age=0``, which would misrepresent a data-quality gap as "brand new".
    Negative ages (clock skew, a future-dated fixture/record) are clamped to
    zero rather than propagated, so a single bad record cannot poison a mean
    with a negative outlier.
    """
    ts = parse_vikunja_timestamp(task.get(basis_field))
    if ts is None:
        return None
    age_seconds = (now - ts).total_seconds()
    if age_seconds < 0:
        age_seconds = 0.0
    try:
        task_id = int(task.get("id", 0) or 0)
    except (TypeError, ValueError):
        task_id = 0
    return WorkItemAge(
        task_id=task_id,
        title=str(task.get("title", "")),
        age_seconds=age_seconds,
        basis_field=basis_field,
    )


def compute_ages(
    tasks: Sequence[Mapping[str, Any]],
    *,
    now: datetime,
    basis_field: str = DEFAULT_AGE_BASIS_FIELD,
) -> list[WorkItemAge]:
    """:func:`compute_age` over every task, silently dropping the
    unparseable ones (fail-soft — the caller sees fewer ages, never a
    crash; ``len(tasks) - len(result)`` is the caller's data-quality
    signal if it wants one)."""
    ages = (compute_age(t, now=now, basis_field=basis_field) for t in tasks)
    return [a for a in ages if a is not None]


def compute_cycle_time(task: Mapping[str, Any]) -> float | None:
    """Seconds from ``created`` to ``done_at`` for a DONE task.

    Returns ``None`` (fail-soft) if the task is not done, or either
    timestamp is missing/unparseable. Clamped to non-negative for the same
    clock-skew reason :func:`compute_age` clamps."""
    if not bool(task.get("done", False)):
        return None
    done_at = parse_vikunja_timestamp(task.get("done_at"))
    created = parse_vikunja_timestamp(task.get("created"))
    if done_at is None or created is None:
        return None
    return max((done_at - created).total_seconds(), 0.0)


def compute_cycle_times(tasks: Sequence[Mapping[str, Any]]) -> list[float]:
    """:func:`compute_cycle_time` over every DONE task with computable
    timestamps, dropping the rest (fail-soft, mirrors :func:`compute_ages`)."""
    return [
        ct for ct in (compute_cycle_time(t) for t in tasks) if ct is not None
    ]


def compute_throughput(
    tasks: Sequence[Mapping[str, Any]],
    *,
    window_start: datetime,
    window_end: datetime,
) -> int:
    """Count of tasks DONE within ``[window_start, window_end)`` — a
    half-open interval so adjacent windows never double-count a task whose
    ``done_at`` lands exactly on a boundary."""
    count = 0
    for t in tasks:
        if not bool(t.get("done", False)):
            continue
        done_at = parse_vikunja_timestamp(t.get("done_at"))
        if done_at is None:
            continue
        if window_start <= done_at < window_end:
            count += 1
    return count


def aging_wip_outliers(
    ages: Sequence[WorkItemAge],
    *,
    threshold_stddev: float = DEFAULT_OUTLIER_THRESHOLD_STDDEV,
) -> list[WorkItemAge]:
    """Items whose age exceeds ``mean + threshold_stddev * stddev`` within
    *ages* — the "statistical outlier for its class" detector (ADR-039
    §2.8).

    The caller supplies an already CLASS-GROUPED age list (e.g. every
    Standard-class WIP item's age) so "its class" is the caller's grouping,
    not one hardcoded here — this module computes the statistic; the
    classes-of-service grouping itself (label-driven: Expedite/Fixed-date/
    Standard/Intangible) is C2/C4 territory (ADR-039 §2.10), out of C1's
    read-surface scope. Returns ``[]`` for fewer than 2 samples (no
    meaningful stddev) or a zero-variance group (uniform ages -> no
    outliers by construction, not a division-by-zero crash)."""
    if len(ages) < 2:
        return []
    values = [a.age_seconds for a in ages]
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    stddev = variance**0.5
    if stddev == 0:
        return []
    threshold = mean + threshold_stddev * stddev
    return [a for a in ages if a.age_seconds > threshold]


@dataclass(frozen=True)
class FlowMetrics:
    """The composed flow-metrics snapshot for one board read (ADR-039 §2.8)."""

    computed_at: str
    """ISO 8601 UTC timestamp this snapshot was computed at (the ``now`` the
    caller supplied, recorded for audit/reproducibility)."""
    age_basis_field: str
    """Which task timestamp field ages were computed from (see the module's
    open-decision note — :data:`DEFAULT_AGE_BASIS_FIELD` unless overridden)."""
    open_count: int
    ages: tuple[WorkItemAge, ...] = field(default_factory=tuple)
    oldest_age_seconds: float | None = None
    mean_age_seconds: float | None = None
    cycle_times_seconds: tuple[float, ...] = field(default_factory=tuple)
    mean_cycle_time_seconds: float | None = None
    throughput_window_start: str = ""
    throughput_window_end: str = ""
    throughput_count: int = 0
    aging_outliers: tuple[WorkItemAge, ...] = field(default_factory=tuple)
    skipped_unparseable: int = 0
    """``len(open_tasks) - len(ages)`` — open tasks whose age timestamp was
    missing/unparseable. A data-quality signal, not a failure: a nonzero
    value means SOME open tasks are invisible to age-based metrics, which
    the composer/renderer should surface rather than silently under-report
    aging-WIP against a partial population."""


def compute_flow_metrics(
    open_tasks: Sequence[Mapping[str, Any]],
    all_tasks: Sequence[Mapping[str, Any]],
    *,
    now: datetime,
    window_start: datetime,
    window_end: datetime,
    age_basis_field: str = DEFAULT_AGE_BASIS_FIELD,
    outlier_threshold_stddev: float = DEFAULT_OUTLIER_THRESHOLD_STDDEV,
) -> FlowMetrics:
    """Compose age / cycle-time / throughput / aging-WIP into one snapshot.

    *open_tasks* drives age + aging-WIP; *all_tasks* (open AND done) drives
    cycle time + throughput (a done task contributes no age, but does
    contribute a cycle time and a throughput count). Every timestamp
    argument (*now*, *window_start*, *window_end*) MUST be tz-aware —
    comparing a naive and an aware ``datetime`` raises ``TypeError`` in
    Python by design, which is the correct failure mode here (a caller
    passing a naive clock read is a caller bug, not untrusted input to
    degrade gracefully around).
    """
    ages = compute_ages(open_tasks, now=now, basis_field=age_basis_field)
    cycle_times = compute_cycle_times(all_tasks)
    throughput = compute_throughput(
        all_tasks, window_start=window_start, window_end=window_end
    )
    outliers = aging_wip_outliers(ages, threshold_stddev=outlier_threshold_stddev)

    return FlowMetrics(
        computed_at=now.astimezone(timezone.utc).isoformat(),
        age_basis_field=age_basis_field,
        open_count=len(open_tasks),
        ages=tuple(ages),
        oldest_age_seconds=max((a.age_seconds for a in ages), default=None),
        mean_age_seconds=(
            sum(a.age_seconds for a in ages) / len(ages) if ages else None
        ),
        cycle_times_seconds=tuple(cycle_times),
        mean_cycle_time_seconds=(
            sum(cycle_times) / len(cycle_times) if cycle_times else None
        ),
        throughput_window_start=window_start.astimezone(timezone.utc).isoformat(),
        throughput_window_end=window_end.astimezone(timezone.utc).isoformat(),
        throughput_count=throughput,
        aging_outliers=tuple(outliers),
        skipped_unparseable=len(open_tasks) - len(ages),
    )
