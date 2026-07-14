"""Coordinator bucket-transition record — the observed age basis (#845 C3, ADR-039 §2.14.2).

The C3 heartbeat limb that gives "age" its settled meaning. ADR-039 §2.14.2 left
the flow-metric age definition open (Vikunja stores no bucket-transition history);
the LA-approved C3 design (`docs/research/c3-heartbeat-design-2026-07.md` §4)
settles it: **age = time since the card entered its current bucket, operationalized
as first-observed-in-bucket** by per-cycle snapshot-diffing — the Kanban-correct
quantity (backlog dwell is not queue wait), with Vikunja's native ``created``
demoted to tie-break and surfaced fallback. This module is that mechanism:

  * :func:`extract_bucket_membership` — pure: the enriched bucket list a
    :func:`shared.fleet.vikunja_bridge.board_state` read returns → one
    ``{task_id: bucket_title}`` mapping.
  * :func:`observe_board` — pure diff (no I/O, no clock; the caller supplies
    ``now``): prior record + fresh membership → updated record. EPISODE
    semantics, mirroring the stall seen-set: a card still in its recorded bucket
    keeps its ``first_seen``; a card observed in a DIFFERENT bucket is re-stamped
    (a new wait began); a card gone from the board is pruned (a card that
    returns later starts a fresh episode — its serviced wait is not credited
    forward).
  * :func:`inject_observed_basis` — pure: copies of the open-task mappings with
    :data:`OBSERVED_AGE_FIELD` set to the observed ``first_seen`` where one
    exists, else the task's own ``created`` (the design's fallback — every task
    keeps an age; an unobserved task must never silently vanish from the age
    population, which is worse than a created-basis age). ``flow_metrics``
    consumes the synthetic field via its existing ``age_basis_field`` parameter
    and does not change.
  * :func:`read_board_history` / :func:`write_board_history` — the durable
    record, in the affirmed non-content-bearing posture (task ids, bucket
    titles, timestamps — no goals, no ticket text): plaintext owner-DACL JSON,
    atomic ``temp + os.replace``, exactly the :mod:`shared.fleet.coord_stall_state`
    idiom. The read distinguishes MISSING (cold start — normal; observations
    begin accumulating) from CORRUPT (surfaced by the composer as a degraded
    substrate; the cycle falls back to the created basis rather than trusting a
    torn record — ADR-039 §2.12.6/§2.14.4: unknown never renders as data).

Known, documented bias (design §4.4): entered-bucket is *observed* no finer than
the heartbeat cadence, and the record injected each cycle is the PRIOR cycle's
(read-inject-before-compose; diff-and-write after — design §2 steps 3–4), so a
card that moved since the last cycle carries its old bucket's ``first_seen`` for
one cycle. Bounded by the cycle interval and honest, not hidden.

DORMANCY: no production path constructs or reads this record today. The C3
heartbeat cycle wires it later, dormant behind ``[coordinator].heartbeat_enabled``;
:func:`shared.fleet.work_state.compose_work_state` consumes it only when its new
optional ``board_history_path`` is supplied, which no production caller does.
Importing this module arms nothing.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from shared.fleet.coord_stall_state import coordinator_state_dir
from shared.fleet.dispatch import FleetDispatchConfig
from shared.security.file_dacl import ensure_owner_only_dacl

#: The synthetic task-mapping key :func:`inject_observed_basis` writes and
#: ``flow_metrics``/``detect_stalls`` consume via ``age_basis_field``. Underscore
#: prefix: never a real Vikunja field, so injection can never shadow server data.
OBSERVED_AGE_FIELD: Final[str] = "_observed_entered_bucket"


@dataclass(frozen=True)
class ObservedBucketEntry:
    """One card's current observation: which bucket, first seen when.

    ``first_seen`` is an ISO-8601 stamp supplied by the caller (this module
    never reads the clock) — the cycle timestamp of the first cycle that saw
    the card in this bucket."""

    bucket: str
    first_seen: str


@dataclass(frozen=True)
class BoardHistoryState:
    """The cross-cycle bucket-transition record.

    ``entries`` maps ``"{project_id}:{task_id}"`` → :class:`ObservedBucketEntry`.
    One entry per card (a kanban card sits in exactly one bucket; departed
    buckets are pruned by :func:`observe_board`'s episode semantics), so the
    record's size is bounded by the open-card population of the projects still
    being observed — entries for a project REMOVED from ``coordinator_projects``
    are never diffed again and persist until a maintenance prune (a named,
    bounded residue: stale ids and timestamps only, no content). ``updated_at``
    is advisory operator-legible metadata, never a gate."""

    entries: Mapping[str, ObservedBucketEntry] = field(default_factory=dict)
    updated_at: str = ""


@dataclass(frozen=True)
class BoardHistoryRead:
    """A record read with the MISSING-vs-CORRUPT distinction the composer needs.

    ``corrupt=False`` with an empty state = cold start (normal — observations
    begin). ``corrupt=True`` = the file existed but could not be trusted; the
    consumer must fall back to the created basis AND surface the condition
    (ADR-039 §2.14.4 — never silently, in either direction)."""

    state: BoardHistoryState = field(default_factory=BoardHistoryState)
    corrupt: bool = False
    error: str = ""


def _entry_key(project_id: int, task_id: int) -> str:
    return f"{project_id}:{task_id}"


def _valid_entry_key(key: str) -> bool:
    """``"{int}:{int}"`` exactly — anchored validation before trust (a tampered
    or drifted key shape is dropped at read, never carried forward)."""
    left, sep, right = key.partition(":")
    return bool(sep) and left.isdigit() and right.isdigit()


def default_board_history_path(config: FleetDispatchConfig) -> Path:
    """The default record location (``.../coordinator/board_history.json``) —
    the same coordinator state dir as the stall seen-set."""
    return coordinator_state_dir(config) / "board_history.json"


def read_board_history(path: Path) -> BoardHistoryRead:
    """Read the record; MISSING degrades to empty, CORRUPT is flagged.

    Element-by-element validation: a partially-corrupt file keeps its
    well-formed entries only when the overall document parses; an unparseable
    document (or a wrong-shaped payload) is CORRUPT — flagged for the composer
    to surface, never silently treated as an empty board history (which would
    quietly re-stamp every card's age this cycle)."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return BoardHistoryRead()
    except OSError as exc:
        return BoardHistoryRead(corrupt=True, error=str(exc))
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as exc:
        return BoardHistoryRead(corrupt=True, error=f"unparseable JSON: {exc}")
    if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
        return BoardHistoryRead(corrupt=True, error="wrong-shaped payload")
    entries: dict[str, ObservedBucketEntry] = {}
    for key, value in data["entries"].items():
        if not isinstance(key, str) or not _valid_entry_key(key):
            continue
        if not isinstance(value, dict):
            continue
        bucket = value.get("bucket")
        first_seen = value.get("first_seen")
        if isinstance(bucket, str) and bucket and isinstance(first_seen, str) and first_seen:
            entries[key] = ObservedBucketEntry(bucket=bucket, first_seen=first_seen)
    updated_at = data.get("updated_at")
    return BoardHistoryRead(
        state=BoardHistoryState(
            entries=entries,
            updated_at=updated_at if isinstance(updated_at, str) else "",
        )
    )


def _atomic_write(path: Path, text: str) -> None:
    """Temp + ``os.replace`` — never a torn half-record (the
    :mod:`shared.fleet.coord_stall_state` / ``swap_state`` idiom)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_board_history(state: BoardHistoryState, *, path: Path) -> None:
    """Persist the record atomically, then apply an owner-only DACL (fail-safe
    defense-in-depth, mirrors :func:`shared.fleet.coord_stall_state.write_seen_state`)."""
    payload = {
        "entries": {
            key: {"bucket": entry.bucket, "first_seen": entry.first_seen}
            for key, entry in sorted(state.entries.items())
        },
        "updated_at": state.updated_at,
    }
    _atomic_write(path, json.dumps(payload, indent=2))
    ensure_owner_only_dacl(path)


def extract_bucket_membership(
    buckets: Sequence[Mapping[str, Any]],
) -> dict[int, str]:
    """``board_state``'s enriched bucket list → ``{task_id: bucket_title}``.

    **Caller precondition (load-bearing):** *buckets* must come from an ``OK``
    board read. An UNREACHABLE board that degraded to empty/absent buckets is
    indistinguishable from a genuinely empty board at this layer — feeding it
    onward would let :func:`observe_board` prune the project's whole history
    (ADR-039 §2.12.6: unknown must never render as empty). The cycle skips
    observing any project whose board read was not OK.

    Pure and fail-soft: malformed buckets/tasks are skipped, empty titles are
    skipped (a title-less bucket cannot anchor an episode), and a task somehow
    listed under two buckets keeps the first (deterministic — bucket order is
    the board's own position order)."""
    membership: dict[int, str] = {}
    for bucket in buckets:
        if not isinstance(bucket, Mapping):
            continue
        title = str(bucket.get("title", "") or "").strip()
        if not title:
            continue
        tasks = bucket.get("tasks")
        if not isinstance(tasks, Sequence):
            continue
        for task in tasks:
            if not isinstance(task, Mapping):
                continue
            try:
                task_id = int(task.get("id"))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            membership.setdefault(task_id, title)
    return membership


def observe_board(
    prior: BoardHistoryState,
    *,
    project_id: int,
    membership: Mapping[int, str],
    now: datetime,
) -> BoardHistoryState:
    """Pure diff: fold one project's fresh bucket membership into the record.

    **Caller precondition (load-bearing, review finding 1):** *membership* must
    derive from an ``OK`` board read for this project. This function cannot
    distinguish "the board is empty" from "the board was unreachable and
    degraded to empty" — calling it with the latter silently prunes the whole
    project's history and resets every observed age next cycle (a false-fresh
    blip, the §2.12.6 conflation). The heartbeat cycle therefore SKIPS the
    observe step for any project whose board read was not OK; the record simply
    carries the prior cycle's observations forward.

    **Tie-break note (design §4.1):** cards first observed in the same cycle
    share one ``first_seen`` and therefore tie on age; breaking those ties by
    Vikunja ``created`` is the PULL-ORDERING consumer's job (C4) — this record
    deliberately stores the observation, not the ordering.

    Episode semantics (the whole contract):

      * same card, same bucket  -> entry kept, ``first_seen`` UNCHANGED;
      * same card, new bucket   -> re-stamped at *now* (a new wait began);
      * card newly on the board -> stamped at *now* (first observation);
      * card gone from the board-> pruned (a return later is a fresh episode).

    Entries belonging to OTHER projects are untouched — the record is one file,
    the diff is per-project (each project's board is read separately)."""
    prefix = f"{project_id}:"
    now_iso = now.isoformat()
    entries: dict[str, ObservedBucketEntry] = {
        key: entry
        for key, entry in prior.entries.items()
        if not key.startswith(prefix)
    }
    for task_id, bucket in membership.items():
        key = _entry_key(project_id, task_id)
        existing = prior.entries.get(key)
        if existing is not None and existing.bucket == bucket:
            entries[key] = existing
        else:
            entries[key] = ObservedBucketEntry(bucket=bucket, first_seen=now_iso)
    return BoardHistoryState(entries=entries, updated_at=now_iso)


def observed_first_seen(
    state: BoardHistoryState, project_id: int, task_id: int
) -> ObservedBucketEntry | None:
    """The recorded observation for one card, or ``None`` if never observed."""
    return state.entries.get(_entry_key(project_id, task_id))


def inject_observed_basis(
    tasks: Sequence[Mapping[str, Any]],
    *,
    state: BoardHistoryState,
    project_id: int,
) -> list[dict[str, Any]]:
    """Copies of *tasks* with :data:`OBSERVED_AGE_FIELD` set on every one.

    Observed cards get their recorded ``first_seen``; unobserved cards (cold
    start, never dragged onto the board, or moved during an app-off window and
    not yet re-observed) get their own ``created`` — the design's surfaced
    fallback, chosen over omission because a task with NO age silently drops
    out of the age population (``compute_age`` returns ``None``), which would
    under-report aging work — worse than an honest created-basis age."""
    injected: list[dict[str, Any]] = []
    for task in tasks:
        copy = dict(task)
        entry = None
        try:
            entry = observed_first_seen(state, project_id, int(task.get("id")))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            pass
        copy[OBSERVED_AGE_FIELD] = (
            entry.first_seen if entry is not None else str(task.get("created", "") or "")
        )
        injected.append(copy)
    return injected
