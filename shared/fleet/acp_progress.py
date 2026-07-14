"""Durable ACP coder-run progress artifact + the coordinator's operational ruler (#844 C2).

The C2 "ACP ``session/update``-stream monitoring" limb. The fleet's ACP coder driver
(:mod:`tools.dispatch_harness.acp_coder`) drives opencode over a typed
``session/update`` event stream and tracks per-run progress (steps, edits, tokens,
last-event time) — but that state is PROCESS-LOCAL to the driver's live run (a
``time.monotonic()`` clock), so a SEPARATE process (the coordinator) cannot see it.
This module is the durable bridge: a small, plaintext, WALL-CLOCK progress snapshot
the driver writes per event and the coordinator reads to compose its cross-run
OPERATIONAL view.

Two roles, one shared contract (this module lives in ``shared/`` so BOTH sides use
ONE shape, never a re-implementation that could drift — ``tools/`` -> ``shared/`` is
an allowed import direction):

  * The FLEET driver (the acting limb) WRITES a snapshot each ``session/update`` —
    an additive, FAIL-SOFT side effect that never changes how the coder is driven or
    watched. The in-run idle/kill logic (``acp_coder.ACP_IDLE_TIMEOUT_S``, the hard
    600 s wedged-coder cancel) is UNTOUCHED; this is pure observability.
  * The COORDINATOR READS the latest run's snapshot and runs
    :func:`assess_acp_progress` — a pure operational ruler that computes last-event
    age and a SOFT ``quiet`` signal (:data:`DEFAULT_ACP_QUIET_THRESHOLD_S`), DISTINCT
    from the driver's hard idle KILL. The coordinator SURFACES a quiet run for
    operator visibility (ADR-039 §2.13 item 6 cross-run monitoring); it NEVER kills —
    the kill stays with the fleet's own watchdog (the acting limb, §2.1 item 9). The
    coordinator observes durable outputs; it does not reach into the live run.

Non-content-bearing (the same posture as the stall seen-set, ADR-039 §2.13 item 2):
the snapshot is run-id + deterministic counts + timestamps — fleet run metadata, no
goals/ticket text — so it is PLAINTEXT (atomic write, fail-soft), never
born-encrypted.

DORMANCY: the write side only runs inside the ACP driver, which is itself dormant
(imported only when ``driver=acp``; the default ``stdin`` driver never loads it). The
read side is behind ``[coordinator].enabled=false``. Importing this module arms
nothing.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

#: The coordinator's SOFT operational "this run has been quiet a while" threshold
#: (seconds of wall-clock since the last ``session/update``). DISTINCT from
#: ``acp_coder.ACP_IDLE_TIMEOUT_S`` (600 s), which is the FLEET's in-run KILL bound:
#: this one only makes ``/coord status`` show a run "QUIET" for operator visibility —
#: NOTHING dies at this threshold. Set to half the kill window so the operator SEES a
#: run go silent well before the fleet's watchdog cancels it. Registered in
#: ``shared/timeout_registry.py``.
DEFAULT_ACP_QUIET_THRESHOLD_S: Final[float] = 300.0

#: The well-known artifact filename the driver writes into the run dir; the
#: coordinator reads the same name from ``runs_dir/<latest_run_id>/``.
ACP_PROGRESS_FILENAME: Final[str] = "acp-progress.json"


@dataclass(frozen=True)
class AcpProgressSnapshot:
    """One durable, wall-clock progress record for the currently-driven ACP run.

    Non-content-bearing fleet metadata: the run id, deterministic counts, and
    wall-clock ISO timestamps. NO goals or ticket text — so it is plaintext at
    rest."""

    run_id: str = ""
    last_event_at: str = ""     # ISO-8601 UTC wall-clock of the last session/update
    updated_at: str = ""        # ISO-8601 UTC wall-clock of this write
    event_count: int = 0
    steps: int = 0
    edits: int = 0
    failed_tool_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _coerce_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def snapshot_from_json(raw: str) -> AcpProgressSnapshot | None:
    """Parse a snapshot from JSON text, or ``None`` on any trouble (fail-soft).

    Every field is coerced defensively — a wrong-typed field degrades to its zero
    value rather than raising, so a partially-corrupt artifact never crashes a
    read."""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return AcpProgressSnapshot(
        run_id=_coerce_str(data.get("run_id")),
        last_event_at=_coerce_str(data.get("last_event_at")),
        updated_at=_coerce_str(data.get("updated_at")),
        event_count=_coerce_int(data.get("event_count")),
        steps=_coerce_int(data.get("steps")),
        edits=_coerce_int(data.get("edits")),
        failed_tool_calls=_coerce_int(data.get("failed_tool_calls")),
        tokens_in=_coerce_int(data.get("tokens_in")),
        tokens_out=_coerce_int(data.get("tokens_out")),
    )


def write_acp_progress(snapshot: AcpProgressSnapshot, *, path: Path) -> bool:
    """Atomically write *snapshot* to *path* — FAIL-SOFT (returns ``False``, never raises).

    Called by the ACP driver per ``session/update``. It is a PURE observability side
    effect: a write failure (disk full, a race, a permission error) must NEVER affect
    the coder run, so every failure is swallowed and reported as ``False``. The write
    is atomic (temp + ``os.replace``) so the coordinator can never read a torn file."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(snapshot.to_json(), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def read_acp_progress(path: Path) -> AcpProgressSnapshot | None:
    """Read a snapshot from *path*, or ``None`` if absent/unreadable/malformed
    (fail-soft)."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return snapshot_from_json(raw)


@dataclass(frozen=True)
class AcpProgressAssessment:
    """The coordinator's operational read of one ACP run's progress."""

    run_id: str
    last_event_age_s: float | None   # None when last_event_at is absent/unparseable
    quiet: bool                       # age >= threshold AND the run is still active
    run_active: bool
    event_count: int
    steps: int
    edits: int
    failed_tool_calls: int
    tokens_in: int
    tokens_out: int
    summary: str


def _parse_iso(ts: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def assess_acp_progress(
    snapshot: AcpProgressSnapshot,
    *,
    now: datetime,
    run_active: bool,
    quiet_threshold_s: float = DEFAULT_ACP_QUIET_THRESHOLD_S,
) -> AcpProgressAssessment:
    """The pure operational ruler over one ACP progress *snapshot*.

    Computes the wall-clock age of the last ``session/update`` and a SOFT operational
    ``quiet`` flag — the coordinator's cross-run visibility signal, NOT a kill.
    ``quiet`` requires the run to still be ACTIVE: the fleet writes a ``SUMMARY.txt``
    when a run finishes, and a finished run's stale last-event age is NOT a stall.
    Fail-soft: an absent/unparseable ``last_event_at`` yields ``age=None`` and
    ``quiet=False`` (never a false alarm on a malformed timestamp)."""
    last_event = _parse_iso(snapshot.last_event_at)
    if last_event is None:
        age: float | None = None
        quiet = False
    else:
        age = (now - last_event).total_seconds()
        quiet = run_active and age >= quiet_threshold_s

    run_label = snapshot.run_id or "?"
    if not run_active:
        summary = f"latest coder run {run_label} finished"
    elif age is None:
        summary = f"coder run {run_label} active (no event timestamp yet)"
    else:
        state = "QUIET" if quiet else "active"
        summary = (
            f"coder run {run_label} {state}: step {snapshot.steps}, "
            f"{snapshot.edits} edits, last event {age:.0f}s ago"
        )

    return AcpProgressAssessment(
        run_id=snapshot.run_id,
        last_event_age_s=age,
        quiet=quiet,
        run_active=run_active,
        event_count=snapshot.event_count,
        steps=snapshot.steps,
        edits=snapshot.edits,
        failed_tool_calls=snapshot.failed_tool_calls,
        tokens_in=snapshot.tokens_in,
        tokens_out=snapshot.tokens_out,
        summary=summary,
    )
