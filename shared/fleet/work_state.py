"""Work-state snapshot composer (#843, ADR-039 §2.10 / §2.14.5).

Composes ONE structured "state of the work" snapshot from every substrate
the Coordinator's read surface depends on: the fleet-swap write-ahead
record (``current.json``), the fleet queue, the latest run's SUMMARY /
scorecard, an optional battery-campaign state file, Vikunja board state +
flow metrics per configured project, and each substrate's own tri-state
liveness.

This module is the **composer-only sensory path** ADR-039 §2.14.5 names
explicitly: deterministic code composes a bounded context from exactly
three defined sources — policy, state, work — and the Coordinator model
(when it exists, #848-onward) NEVER self-navigates to a fourth. This module
IS the "state" leg; :mod:`shared.fleet.vikunja_bridge` IS the "work" leg for
ticket data. Every read here is fail-soft and TRI-STATE (ADR-039 §2.12.6): a
substrate being unreachable is a SURFACED CONDITION on the snapshot, never
silently absent data — a caller must never mistake "I couldn't read this"
for "there is nothing here."

DORMANT by construction: this module performs NO gating of its own (no
``[coordinator].enabled`` check lives here) — mirroring
``shared/fleet/vikunja_bridge.py``'s read section, the ENABLED decision
belongs to the caller (the ``/coord status`` gateway command), exactly like
``DispatchCoordinator`` checks its own flag before touching any
collaborator. Composing a snapshot is always safe to CALL; whether anything
calls it in production is the dormancy gate.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Generic, Mapping, Sequence, TypeVar

from shared.fleet import acp_progress as ap
from shared.fleet import coord_board_history as bh
from shared.fleet import coord_lifecycle as cl
from shared.fleet import coord_stall_state as css
from shared.fleet import dispatch as fleet
from shared.fleet import flow_metrics as fm
from shared.fleet import swap_state as ss
from shared.fleet import vikunja_bridge as vb
from shared.fleet.dispatch import FleetDispatchConfig, TaskOutcome
from shared.fleet.swap_ops import swap_state_path

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: The default lookback window for throughput computation — one week. Chosen
#: to match the natural cadence of a solo-operator continuous-flow shop
#: (ADR-039 §2.8): long enough to smooth day-to-day dispatch variance, short
#: enough that a digest stays meaningful. Callers may override per read.
DEFAULT_FLOW_WINDOW = timedelta(days=7)


@dataclass(frozen=True)
class TriStateRead(Generic[T]):
    """A single-value tri-state read result (ADR-039 §2.12.6) — the
    companion to :class:`shared.fleet.vikunja_bridge.ReadResult` for
    substrates that produce ONE structured record (swap state, the queue
    file, a run summary, a campaign file) rather than a collection.

    Reuses :class:`shared.fleet.vikunja_bridge.ReadStatus` so every
    coordinator surface — ticket collections AND single-record state —
    speaks the SAME three-state vocabulary."""

    status: vb.ReadStatus
    value: T | None = None
    error: str = ""

    @property
    def ok(self) -> bool:
        """True for OK or EMPTY; False only for UNREACHABLE — see
        :meth:`shared.fleet.vikunja_bridge.ReadResult.ok` for the identical
        rationale (never conflate 'off/nothing there' with 'could not
        tell')."""
        return self.status is not vb.ReadStatus.UNREACHABLE


def _read_json_file(path: Path) -> TriStateRead[Any]:
    """Generic tri-state JSON-file read shared by the queue + campaign
    reads below: EMPTY if the file does not exist or is blank (a known,
    benign "nothing written yet" state), UNREACHABLE if it exists but
    cannot be read or does not parse as JSON, OK with the parsed value
    otherwise."""
    if not path.exists():
        return TriStateRead(status=vb.ReadStatus.EMPTY, value=None)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("work_state: could not read %s (fail-soft): %s", path, exc)
        return TriStateRead(status=vb.ReadStatus.UNREACHABLE, value=None, error=str(exc))
    if not raw.strip():
        return TriStateRead(status=vb.ReadStatus.EMPTY, value=None)
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError) as exc:
        logger.warning("work_state: malformed JSON at %s (fail-soft): %s", path, exc)
        return TriStateRead(
            status=vb.ReadStatus.UNREACHABLE, value=None, error=f"malformed JSON: {exc}"
        )
    return TriStateRead(status=vb.ReadStatus.OK, value=parsed)


# ---------------------------------------------------------------------------
# Individual substrate reads — each independently testable + fail-soft.
# ---------------------------------------------------------------------------


def read_swap_snapshot(config: FleetDispatchConfig) -> TriStateRead[ss.SwapState]:
    """Tri-state wrapper over :func:`shared.fleet.swap_state.read_swap_state`.

    That function's OWN contract predates the tri-state discipline and
    already fail-softs to ``None`` for "absent OR unreadable OR malformed"
    combined — this wrapper distinguishes them WITHOUT changing that
    module's contract (a widely-depended-on production module; this stays
    additive, not a shared-shape change):

    * ``EMPTY`` — the write-ahead file genuinely does not exist: a normal
      idle-boot state (no swap has ever run on this box, or the last one
      cleaned up after itself via ``clear_swap_state``).
    * ``UNREACHABLE`` — the file EXISTS but ``read_swap_state`` still
      returned ``None`` (unreadable or corrupt) — a real condition worth
      surfacing, never silently "nothing going on".
    * ``OK`` — a record parsed.
    """
    path = swap_state_path(config)
    if not path.exists():
        return TriStateRead(status=vb.ReadStatus.EMPTY, value=None)
    state = ss.read_swap_state(path)
    if state is None:
        return TriStateRead(
            status=vb.ReadStatus.UNREACHABLE,
            value=None,
            error=f"{path} exists but could not be read/parsed",
        )
    return TriStateRead(status=vb.ReadStatus.OK, value=state)


def read_fleet_queue(config: FleetDispatchConfig) -> TriStateRead[Any]:
    """The fleet's queue JSON (``state/fleet-queue.json``).

    The queue is written/read by the fleet's own PowerShell scripts
    (``add-fleet-task.ps1`` / ``run-fleet.ps1``); BlarAI's Python side has
    no queue schema of its own today, so this is a generic structural read
    — tri-state only. The composer/renderer decides how much of the raw
    parsed shape to surface; this function makes no assumption about its
    internal fields beyond "it is JSON"."""
    return _read_json_file(config.queue_path)


def read_campaign_state(path: Path | None) -> TriStateRead[Any]:
    """An optional battery-campaign-state JSON file.

    Returns ``EMPTY`` (not ``UNREACHABLE``) when *path* is ``None`` /
    unconfigured — "the operator hasn't pointed this at a campaign file" is
    a known, benign state, not a read failure. No campaign-state file with a
    stable schema is produced inside the BlarAI tree today (the battery
    harness's campaign bookkeeping lives partly in the sibling
    ``agentic-setup`` install); the path is therefore config-driven
    (``[coordinator].battery_campaign_state_path``) so an operator can point
    it at whatever their own install actually writes, and an unset default
    degrades honestly to EMPTY rather than assuming a fictitious schema."""
    if path is None:
        return TriStateRead(status=vb.ReadStatus.EMPTY, value=None)
    return _read_json_file(path)


#: #882: scorecard task ``status`` → the classified :class:`TaskOutcome.result`
#: token existing consumers test against (``RESULT_MERGED`` / ``RESULT_PARKED``,
#: ``REDISPATCH_ELIGIBLE_RESULTS``). Status is the state truth — a park is a park
#: whatever its cause (BUILD, TIMEOUT); the cause token rides ``detail``.
_SCORECARD_STATUS_RESULT: Mapping[str, str] = {
    "merged": "MERGED",
    "parked": "PARKED",
    "skipped": "SKIPPED",
}


def outcomes_from_scorecard(scorecard: Any) -> "tuple[TaskOutcome, ...] | None":
    """#882: per-task outcomes from an ALREADY-PARSED ``scorecard.json`` document —
    the WHOLE-JOB truth. ``SUMMARY.txt`` is rewritten PER WAVE in plan-graph (M2)
    mode and at run end lists only the final wave, so a parked earlier wave was
    invisible to every outcomes consumer (redispatch eligibility, the harvest
    parked flag) — observed live 2026-07-14 on run 20260714-191219-bd.

    PURE (no I/O) and public, mirroring
    :func:`shared.coordinator.heartbeat_cycle.oracle_passed_from_scorecard`: the
    two functions are the complete scorecard→facts derivation, so any consumer
    grading or re-deriving a run's outcomes uses the SAME code the live harvest
    does rather than re-implementing the status/result precedence below (a
    re-implementation that reads ``result`` alone silently misses a
    ``status: "parked"`` task whose cause token is ``NOTHING``).
    :func:`_outcomes_from_scorecard` is the file-reading shell over this.

    TWO writer shapes, both supported (review MAJOR-1): plan-graph scorecards carry
    the state in per-task ``status`` (mapped via :data:`_SCORECARD_STATUS_RESULT`;
    the cause token like TIMEOUT rides ``detail``); FLAT scorecards
    (``build_flat_scorecard``, swap_driver — every single-task dispatch, incl. a
    coordinator redispatch) write ``status: ""`` and carry the ALREADY-classified
    ``dispatch._classify_result`` token in ``result`` — used verbatim (an
    unrecognized token flows through and is ineligible at every consumer, the
    fail-closed direction). A never-started plan-graph task (status ``pending``)
    surfaces as UNKNOWN — deliberately visible, unlike its silent absence from
    SUMMARY. Note ``TaskOutcome.outcome`` on this path carries the scorecard
    status word (``parked``), not run-fleet's SUMMARY word (``processed``) — no
    consumer reads ``.outcome`` today; ``.result`` is the contract.

    ``None`` = no USABLE outcomes (malformed / no tasks / zero parseable entries)
    → a caller falls back to SUMMARY parsing. Returning an empty tuple here would
    silently defeat that fallback (review MAJOR-1)."""
    tasks = scorecard.get("tasks") if isinstance(scorecard, Mapping) else None
    if not isinstance(tasks, list):
        return None
    outcomes: list[TaskOutcome] = []
    for entry in tasks:
        if not isinstance(entry, Mapping):
            continue
        task = str(entry.get("id") or "").strip()
        status = str(entry.get("status") or "").strip().lower()
        cause = str(entry.get("result") or "").strip()
        detail = str(entry.get("detail") or "").strip()
        if not task:
            continue
        if status:
            result = _SCORECARD_STATUS_RESULT.get(status, "UNKNOWN")
            if cause and cause.upper() != result and cause not in detail:
                detail = f"{cause}: {detail}" if detail else cause
        elif cause:
            result = cause.upper()
        else:
            continue  # neither status nor result — unusable entry
        outcomes.append(
            TaskOutcome(task=task, outcome=status or "scorecard", result=result, detail=detail)
        )
    return tuple(outcomes) if outcomes else None


def _outcomes_from_scorecard(
    config: FleetDispatchConfig, run_id: str
) -> "tuple[TaskOutcome, ...] | None":
    """The file-reading shell over :func:`outcomes_from_scorecard`.

    ``None`` = no USABLE outcomes (absent / unreadable / malformed / no tasks /
    zero parseable entries) → the caller falls back to SUMMARY parsing."""
    path = config.runs_dir / run_id / "scorecard.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return outcomes_from_scorecard(data)


def read_latest_run_summary(
    config: FleetDispatchConfig,
) -> TriStateRead["tuple[str, tuple[TaskOutcome, ...]]"]:
    """The latest run's id + per-task outcomes — scorecard-first (#882), falling
    back to :func:`shared.fleet.dispatch.parse_summary` over its ``SUMMARY.txt``
    when no usable scorecard exists (pre-M2 runs, still-running runs).

    ``EMPTY`` — no run has ever produced output yet: either no run exists at
    all, or the latest run's ``SUMMARY.txt`` hasn't been written (still
    running / not yet started) or parsed to zero outcomes. ``UNREACHABLE`` —
    a run directory + ``SUMMARY.txt`` exist but could not be read. ``OK`` —
    at least one task outcome parsed."""
    run_id = fleet.latest_run_id(config=config)
    if not run_id:
        return TriStateRead(status=vb.ReadStatus.EMPTY, value=None)
    scorecard_outcomes = _outcomes_from_scorecard(config, run_id)
    if scorecard_outcomes is not None:
        status = vb.ReadStatus.OK if scorecard_outcomes else vb.ReadStatus.EMPTY
        return TriStateRead(status=status, value=(run_id, scorecard_outcomes))
    summary_path = config.runs_dir / run_id / "SUMMARY.txt"
    if not summary_path.is_file():
        return TriStateRead(status=vb.ReadStatus.EMPTY, value=(run_id, ()))
    try:
        text = summary_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning(
            "work_state: could not read %s (fail-soft): %s", summary_path, exc
        )
        return TriStateRead(status=vb.ReadStatus.UNREACHABLE, value=None, error=str(exc))
    outcomes = tuple(fleet.parse_summary(text))
    status = vb.ReadStatus.OK if outcomes else vb.ReadStatus.EMPTY
    return TriStateRead(status=status, value=(run_id, outcomes))


def read_acp_run_progress(
    config: FleetDispatchConfig, *, now: datetime
) -> TriStateRead[ap.AcpProgressAssessment]:
    """The latest coder run's durable ACP progress (#844 C2), assessed for the
    coordinator's cross-run OPERATIONAL view.

    Reads ``runs_dir/<latest_run_id>/acp-progress.json`` — the artifact the ACP
    driver writes per ``session/update`` — and runs the pure operational ruler
    :func:`shared.fleet.acp_progress.assess_acp_progress`. Tri-state + fail-soft:

    * ``EMPTY`` — no run yet, or the latest run produced no ACP artifact (e.g. it
      ran under the default ``stdin`` driver, not ``driver=acp``): a normal, benign
      "nothing to show" state, never a failure.
    * ``UNREACHABLE`` — the artifact exists but could not be read/parsed.
    * ``OK`` — an assessment. Whether the run is ACTIVE is derived from the presence
      of that run's ``SUMMARY.txt`` (the fleet writes it at run end), so a FINISHED
      run is never reported as a live 'quiet' stall.
    """
    run_id = fleet.latest_run_id(config=config)
    if not run_id:
        return TriStateRead(status=vb.ReadStatus.EMPTY, value=None)
    run_dir = config.runs_dir / run_id
    path = run_dir / ap.ACP_PROGRESS_FILENAME
    if not path.exists():
        return TriStateRead(status=vb.ReadStatus.EMPTY, value=None)
    snapshot = ap.read_acp_progress(path)
    if snapshot is None:
        return TriStateRead(
            status=vb.ReadStatus.UNREACHABLE,
            value=None,
            error=f"{path} exists but could not be read/parsed",
        )
    run_active = not (run_dir / "SUMMARY.txt").is_file()
    assessment = ap.assess_acp_progress(snapshot, now=now, run_active=run_active)
    return TriStateRead(status=vb.ReadStatus.OK, value=assessment)


# ---------------------------------------------------------------------------
# Per-project Vikunja read (board + summary + flow metrics, composed)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectWorkState:
    """One Vikunja project's contribution to the snapshot: its board,
    rollup summary, and flow metrics — or, on failure, the UNREACHABLE
    condition, never a silent empty board."""

    name: str
    project_id: int
    board: vb.ReadResult
    summary: vb.ReadResult
    flow: fm.FlowMetrics | None
    """``None`` exactly when ``board.status is UNREACHABLE`` — flow metrics
    have no meaningful computation over an unknown board (computing "zero
    open items" would silently misrepresent UNREACHABLE as EMPTY at one
    remove, exactly the conflation ADR-039 §2.12.6 forbids)."""
    stalls: tuple[cl.StallSignal, ...] = ()
    """Per-class aging-outlier stalls
    (:func:`shared.fleet.coord_lifecycle.detect_stalls`) over this project's REAL
    open tasks — the principled, class-relative stall detection the C2 stall-comments
    limb consumes, DISTINCT from ``flow.aging_outliers`` (project-wide age, not
    class-relative). #887: synthetic battery/test tickets are EXCLUDED from this
    ACTIONABLE channel (a synthetic park must never generate an operator stall
    comment); their aging is still surfaced via ``test_flow``. Empty when the board
    is UNREACHABLE (no stalls over an unknown board — the same honesty as
    ``flow=None``)."""
    test_flow: fm.FlowMetrics | None = None
    """#887: flow metrics over this project's SYNTHETIC battery/test-labelled
    (:data:`shared.fleet.coord_lifecycle.TEST_CLASS_LABEL`) open+done tasks,
    computed identically to ``flow`` but kept OFF the operator's headline — a
    synthetic park (its honest park WAS the deliverable) must not inflate the
    open-count / oldest / mean the ``/coord`` surface steers by. ``None`` exactly
    when ``flow`` is ``None`` (board UNREACHABLE — no partition over an unknown
    board). SURFACED on its own ``/coord`` line, never hidden."""


def read_project_work_state(
    name: str,
    project_id: int,
    *,
    now: datetime,
    flow_window: timedelta = DEFAULT_FLOW_WINDOW,
    age_basis_field: str = fm.DEFAULT_AGE_BASIS_FIELD,
    board_history: "bh.BoardHistoryState | None" = None,
    transport: vb.Transport | None = None,
) -> ProjectWorkState:
    """Board (display) + rollup summary + flow metrics for one Vikunja
    project.

    Flow metrics are fed by :func:`shared.fleet.vikunja_bridge.list_all_tasks`
    — ONE paginated read covering both open and done tasks — rather than by
    flattening ``board_state``'s per-bucket task lists: a task whose
    ``bucket_id`` is unset (never dragged onto the board) is, by
    ``board_state``'s own contract, NOT attributed to any bucket, so
    flattening buckets would silently under-count open work relative to
    ``list_all_tasks``'s complete population. Using ``list_all_tasks`` once
    also avoids a second independent paginated read racing a mutating board
    (see that function's docstring).

    *board_history* (#845 C3, ADR-039 §2.14.2): when supplied, ages and stall
    detection compute on the OBSERVED entered-bucket basis — every open task
    gets :data:`shared.fleet.coord_board_history.OBSERVED_AGE_FIELD` injected
    (observed ``first_seen`` where recorded, own ``created`` as the fallback)
    and that field overrides *age_basis_field*. When ``None`` (every caller
    today — dormant), behavior is byte-identical to the pre-C3 read."""
    board = vb.board_state(project_id, transport=transport)
    summary = vb.project_read_summary(project_id, transport=transport)
    all_tasks_read = vb.list_all_tasks(project_id, transport=transport)

    if not all_tasks_read.ok:
        # UNREACHABLE -> no flow metrics; computing metrics over an empty
        # task list here would silently look identical to a genuinely quiet
        # project (ADR-039 §2.12.6) — None is the honest signal instead.
        return ProjectWorkState(
            name=name, project_id=project_id, board=board, summary=summary, flow=None,
        )

    all_tasks = list(all_tasks_read.items)
    open_tasks = [t for t in all_tasks if not bool(t.get("done", False))]
    # #845 C3: the observed entered-bucket basis. Injection copies the open
    # tasks; ``all_tasks`` (cycle time + throughput — created/done_at driven)
    # is deliberately untouched by the age basis.
    open_for_age: Sequence[Mapping[str, Any]]
    if board_history is not None:
        open_for_age = bh.inject_observed_basis(
            open_tasks, state=board_history, project_id=project_id
        )
        effective_basis = bh.OBSERVED_AGE_FIELD
    else:
        open_for_age = open_tasks
        effective_basis = age_basis_field
    # #887: partition the flow metrics into the operator's actionable HEADLINE
    # (REAL work) and the surfaced-but-non-actionable TEST class (synthetic
    # battery/test tickets). ``flow`` becomes the headline; ``test_flow`` carries
    # the test partition, shown on its own /coord line. With ZERO test tickets the
    # headline is byte-identical to the pre-#887 whole-board computation.
    partitioned = fm.compute_partitioned_flow_metrics(
        open_for_age,
        all_tasks,
        is_test_class=cl.is_test_class,
        now=now,
        window_start=now - flow_window,
        window_end=now,
        age_basis_field=effective_basis,
    )
    flow = partitioned.headline
    test_flow = partitioned.test_class
    # Per-class aging-outlier stall detection over the SAME open-task population
    # (the data is already in hand — no extra fetch), EXCLUDING synthetic test
    # tickets: a battery/test park must never generate an operator stall comment
    # (the actionable channel) — its aging is surfaced via ``test_flow`` instead.
    # Pure + fail-soft: an unparseable age drops that item from the statistic,
    # never raises.
    real_open_for_age = [t for t in open_for_age if not cl.is_test_class(t)]
    stalls = tuple(
        cl.detect_stalls(real_open_for_age, now=now, age_basis_field=effective_basis)
    )
    return ProjectWorkState(
        name=name, project_id=project_id, board=board, summary=summary, flow=flow,
        stalls=stalls, test_flow=test_flow,
    )


# ---------------------------------------------------------------------------
# The composed snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SubstrateLiveness:
    """One substrate's tri-state reachability, named for the digest/status
    renderer (never OK/EMPTY/UNREACHABLE alone without a label attached)."""

    name: str
    status: vb.ReadStatus
    error: str = ""


@dataclass(frozen=True)
class WorkStateSnapshot:
    """The composed "state of the work" — fleet-swap state, queue, latest
    run, battery campaign, every configured Vikunja project's board + flow
    metrics, and the tri-state liveness of every substrate consulted.

    Nothing on this dataclass is ever silently absent: every field that
    could fail to read is a :class:`TriStateRead`/:class:`vikunja_bridge.ReadResult`/
    :class:`ProjectWorkState`, each carrying its own OK/EMPTY/UNREACHABLE —
    a renderer can walk this snapshot and NEVER mistake "could not read"
    for "nothing to report"."""

    computed_at: str
    swap: TriStateRead[ss.SwapState]
    swap_in_flight: bool
    queue: TriStateRead[Any]
    latest_run: TriStateRead["tuple[str, tuple[TaskOutcome, ...]]"]
    campaign: TriStateRead[Any]
    projects: tuple[ProjectWorkState, ...]
    substrate: tuple[SubstrateLiveness, ...]
    stall_seen_fingerprints: frozenset[str] = frozenset()
    """The stall fingerprints already commented/surfaced, read from the ONE seen-set
    (:mod:`shared.fleet.coord_stall_state`) at compose time — so the rendered STALLS
    rollup marks each stall 'flagged' (already commented on its ticket) vs 'NEW',
    deduped by the SAME set the posting cycle maintains. ``frozenset()`` when no
    seen-set path was supplied (the surface stays honest — everything reads as NEW
    rather than falsely 'flagged')."""
    acp_progress: "TriStateRead[ap.AcpProgressAssessment]" = field(
        default_factory=lambda: TriStateRead(status=vb.ReadStatus.EMPTY, value=None)
    )
    """The latest coder run's ACP progress (#844 C2), or an EMPTY tri-state when no
    run/artifact exists. The read surface is fail-soft — a dead/absent artifact never
    crashes ``/coord status``."""
    age_basis_field: str = fm.DEFAULT_AGE_BASIS_FIELD
    """Which basis every project's ages/stalls were computed on this compose
    (#845 C3, ADR-039 §2.14.2): the observed entered-bucket field when a healthy
    board-history record was supplied, else the ``created`` default — the
    snapshot itself says which, so a renderer/digest never has to guess. Valid
    ONLY while the basis is uniform across projects (true today: one shared
    record, all-or-nothing); each project's ``flow.age_basis_field`` is the
    per-project authority, and any future per-project-record change must key on
    those, not this scalar (design §4.4's mixed-basis note for C4)."""


def compose_work_state(
    *,
    fleet_config: FleetDispatchConfig,
    coordinator_projects: Mapping[str, int],
    now: datetime | None = None,
    flow_window: timedelta = DEFAULT_FLOW_WINDOW,
    campaign_state_path: Path | None = None,
    stall_seen_path: Path | None = None,
    board_history_path: Path | None = None,
    vikunja_transport: vb.Transport | None = None,
) -> WorkStateSnapshot:
    """Compose the full :class:`WorkStateSnapshot`.

    *coordinator_projects* maps a DISPLAY NAME to a Vikunja project id — ids
    are resolved by the caller (never hardcoded inside this module, ADR-039
    §2.12.11); an empty mapping is valid (no Vikunja projects configured
    yet) and yields an empty ``projects`` tuple, not an error.

    *now* defaults to the real UTC clock; a caller MAY inject it (tests,
    reproducible digests) — this is the one place a wall-clock read happens
    in the read-surface's otherwise pure computation chain (ADR-039 §2.14.5:
    deterministic code composes state; injecting ``now`` keeps this function
    itself deterministic given its inputs).
    """
    resolved_now = now if now is not None else datetime.now(timezone.utc)

    swap = read_swap_snapshot(fleet_config)
    swap_in_flight = swap.status == vb.ReadStatus.OK and ss.is_in_flight(swap.value)
    queue = read_fleet_queue(fleet_config)
    latest_run = read_latest_run_summary(fleet_config)
    campaign = read_campaign_state(campaign_state_path)

    # #845 C3: the PRIOR cycle's bucket-transition record (read-inject-before-
    # compose; the heartbeat cycle diffs and re-writes AFTER compose — design
    # §2 steps 3-4). MISSING = cold start (observed basis over an empty record:
    # every task falls back to its own ``created`` and observation begins).
    # CORRUPT = fall back to the created basis for the WHOLE compose and
    # surface it as a degraded substrate (ADR-039 §2.14.4 — never silently).
    board_history: "bh.BoardHistoryState | None" = None
    board_history_liveness: SubstrateLiveness | None = None
    if board_history_path is not None:
        history_read = bh.read_board_history(board_history_path)
        if history_read.corrupt:
            board_history_liveness = SubstrateLiveness(
                name="board_history",
                status=vb.ReadStatus.UNREACHABLE,
                error=history_read.error,
            )
        else:
            board_history = history_read.state
            board_history_liveness = SubstrateLiveness(
                name="board_history",
                status=(
                    vb.ReadStatus.OK
                    if history_read.state.entries
                    else vb.ReadStatus.EMPTY
                ),
            )

    projects = tuple(
        read_project_work_state(
            name, project_id,
            now=resolved_now, flow_window=flow_window,
            board_history=board_history,
            transport=vikunja_transport,
        )
        for name, project_id in coordinator_projects.items()
    )

    vikunja_liveness = vb.health_check(transport=vikunja_transport)
    substrate = (
        SubstrateLiveness(
            name="vikunja",
            status=vikunja_liveness.status,
            error=vikunja_liveness.error,
        ),
        SubstrateLiveness(
            name="fleet_swap_state",
            status=swap.status,
            error=swap.error,
        ),
        SubstrateLiveness(
            name="fleet_queue",
            status=queue.status,
            error=queue.error,
        ),
    ) + ((board_history_liveness,) if board_history_liveness is not None else ())

    # The ONE seen-set (read-only here; the posting cycle WRITES it). Read-surface
    # fail-soft: an absent/unreadable seen-set degrades to 'everything NEW', never a
    # raise (ADR-039 §2.12.6 — the read surface must never crash on a state read).
    stall_seen_fingerprints = (
        css.read_seen_state(stall_seen_path).fingerprints
        if stall_seen_path is not None
        else frozenset()
    )

    # The latest coder run's durable ACP progress (#844 C2) — tri-state, fail-soft;
    # derived entirely from fleet_config (runs_dir + latest run id), so no new
    # caller wiring is needed. Dormant with the rest of the read surface.
    acp_progress = read_acp_run_progress(fleet_config, now=resolved_now)

    return WorkStateSnapshot(
        computed_at=resolved_now.astimezone(timezone.utc).isoformat(),
        swap=swap,
        swap_in_flight=swap_in_flight,
        queue=queue,
        latest_run=latest_run,
        campaign=campaign,
        projects=projects,
        substrate=substrate,
        stall_seen_fingerprints=stall_seen_fingerprints,
        acp_progress=acp_progress,
        age_basis_field=(
            bh.OBSERVED_AGE_FIELD
            if board_history is not None
            else fm.DEFAULT_AGE_BASIS_FIELD
        ),
    )
