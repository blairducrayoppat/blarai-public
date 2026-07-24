"""C3 heartbeat — the launcher-owned timer thread, liveness stamp, and factory (#845 limb 6).

The design (`docs/research/c3-heartbeat-design-2026-07.md` §3) puts the heartbeat on a
NAMED DAEMON THREAD owned by the launcher (the `launcher/step_aside.py` injected-clock
idiom): started immediately before the UI surface blocks (after the Step-6b prompt-flow
preflight, so a heartbeat can never delay or fail boot), stopped FIRST in the launcher's
``_cleanup()`` (before services stop, so a mid-cycle action can never race teardown),
observing the launcher's ``_cleanup_started`` flag as belt-and-suspenders, and daemonic
so it can never hold the process open — the timer dies with the app (§2.13.1).

**Construction gating — structural absence (§3.2, the C2 doom-watchdog precedent
reused exactly):** :func:`build_heartbeat` returns ``None`` unless the AO-resolved
``[coordinator].heartbeat_enabled`` is true — no object, no thread, no store handle,
nothing constructed — and the cycle/router/journal machinery is imported INSIDE the
factory, so the OFF path never even imports it. This is deliberately stricter than
C1's construct-always/check-inside dormancy: the heartbeat is a thread with
side-effect sinks, so flag-false means the thread does not exist.

**Refuse-to-start (fail-closed):** in shadow mode the journal IS the output path, so a
journal that cannot build (no provisioned keystore) refuses the WHOLE heartbeat —
``build_heartbeat`` logs at ERROR and returns ``None`` rather than running cycles whose
evidence would be silently discarded (or, worse, diverted live). A proposal-store
fault alone degrades softer: the cycle already treats ``store=None`` as a surfaced
machinery-health condition while the deterministic organizing continues.

**The liveness stamp (§6.1):** written atomically after EVERY cycle (and on
thread-death) to the coordinator state dir — plaintext, owner-DACL, non-content-bearing
(timestamps, mode, step names/dispositions; no ticket text, no digest prose). It
carries the cycle's OWN declaration of when the next beat is due
(``next_expected_by`` = completion + the mode ladder's chosen interval), so the limb-7
dead-man needs no knowledge of intervals or modes and cannot false-alarm across
battery/overnight cadence stretching. ``thread_dead=true`` is stamped by the thread's
outer handler (§3.3 wall 3) — a silent heartbeat death is structurally impossible to
miss twice. The stamp also records the cycle's ``shadow_mode``, which is what
:func:`shared.coordinator.output_router.reset_seen_set_on_graduation` compares against
the current config at the next boot (§7.2 graduation hygiene — the reset fires exactly
once because every subsequent stamp records the new mode).

**Review obligations discharged here (limbs 4/5 reviews, #845 c.1895/c.1896):**
every :class:`~shared.coordinator.heartbeat_cycle.SurfacedCondition` on the cycle
result is routed through ``route_tripwire`` (the single safe entry — machinery health
auto-diverts to the always-live surface); every shadow-staged DRAFT gets a
``record_proposal_copy`` journal entry; and the drafting seam maps the limb-5
tri-state into the cycle's vocabulary preserving the ``has_text`` distinction — an
empty ``drafted`` reports as ``failed`` (a degradation), never as a successful draft.

Boot-cost honesty (review 8c18ed43 NIT-2): "never delays boot" is literal for the
dormant default (flag false ⇒ one attribute read, nothing else). An ENABLED boot
pays a bounded, post-preflight construction cost on the boot thread (two DEK-envelope
DB opens + a TTL reconcile) before ``start()`` — the same order of work the session
store's own DEK open already does earlier in boot, and the whole block is wrapped so
a fault degrades to a log line, never a failed boot.

Lifecycle contract (review 8c18ed43 NIT-3): one ``start()``/``stop()`` per instance —
the launcher's single boot/teardown pair. ``start()`` after ``stop()`` is a no-op by
design (the thread handle is not reset); a restart is a new factory build.

REACHABILITY: the launcher's factory call returns ``None`` — constructing nothing —
whenever ``[coordinator].heartbeat_enabled`` is false (the dormant default), and
builds the live heartbeat when it is true. Read the resolved value from
``services/assistant_orchestrator/config/default.toml``, never from here. Importing
this module arms nothing (bare-import locked).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Final, Mapping

if TYPE_CHECKING:  # typing only — the OFF path never imports the machinery
    from shared.coordinator.heartbeat_cycle import CycleEnv, CycleResult, DigestRecord
    from shared.coordinator.output_router import OutputRouter

logger = logging.getLogger(__name__)

#: The heartbeat thread's name (§3.1) — greppable in thread dumps, mirrors
#: ``blarai-step-aside-watchdog``.
HEARTBEAT_THREAD_NAME: Final[str] = "blarai-coord-heartbeat"

#: The liveness stamp's filename in the coordinator state dir (§6.1).
LIVENESS_STAMP_FILENAME: Final[str] = "heartbeat-liveness.json"

#: Bounded join at stop — teardown must never hang on a mid-cycle heartbeat; the
#: thread is a daemon, so an overrun simply dies with the process (§2.13.1).
_STOP_JOIN_S: Final[float] = 5.0


def default_liveness_stamp_path(fleet_config: Any) -> Path:
    """``.../coordinator/heartbeat-liveness.json`` — beside the seen-set/record."""
    from shared.fleet.coord_stall_state import coordinator_state_dir

    return coordinator_state_dir(fleet_config) / LIVENESS_STAMP_FILENAME


# ---------------------------------------------------------------------------
# The liveness stamp (§6.1) — atomic, plaintext, owner-DACL, self-declaring
# ---------------------------------------------------------------------------


def write_liveness_stamp(
    path: Path,
    *,
    started_at: str,
    completed_at: str,
    mode: str,
    next_interval_s: float,
    next_expected_by: str,
    shadow_mode: bool,
    thread_dead: bool = False,
    stopped_cleanly: bool = False,
    session_id: str = "",
    steps: "tuple[Mapping[str, Any], ...]" = (),
    note: str = "",
) -> None:
    """Persist the stamp atomically (temp + ``os.replace``) then apply the
    owner-only DACL — the :mod:`shared.fleet.coord_stall_state` posture: ids,
    timestamps, step names — never content. Never raises past an OSError (the
    caller decides how loud a stamp-write failure is)."""
    from shared.security.file_dacl import ensure_owner_only_dacl

    payload = {
        "started_at": started_at,
        "completed_at": completed_at,
        "mode": mode,
        "next_interval_s": next_interval_s,
        "next_expected_by": next_expected_by,
        "shadow_mode": shadow_mode,
        "thread_dead": thread_dead,
        "stopped_cleanly": stopped_cleanly,
        "session_id": session_id,
        "steps": [dict(s) for s in steps],
        "note": note,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    ensure_owner_only_dacl(path)


def read_liveness_stamp(path: Path) -> "Mapping[str, Any] | None":
    """The stamp, or ``None`` for missing/corrupt (fail-soft — the dead-man and
    the graduation reset both treat an unreadable stamp as 'no recording')."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return data if isinstance(data, Mapping) else None


def recorded_shadow_mode(stamp: "Mapping[str, Any] | None") -> "bool | None":
    """The stamp's recorded routing mode, or ``None`` when absent/foreign-typed
    — exactly the tri-state :func:`reset_seen_set_on_graduation` consumes (an
    unknown recording never triggers a reset, the fail-closed direction)."""
    if stamp is None:
        return None
    value = stamp.get("shadow_mode")
    return value if isinstance(value, bool) else None


def _stamp_step(step: Any) -> "dict[str, Any]":
    """Bound one step record to the stamp's non-content-bearing posture (review
    8c18ed43 MINOR-2): a SUCCESSFUL step's detail is deterministic by the cycle
    engine's construction (counts, run ids, bucket/project names) and stays; a
    FAILED step's detail embeds ``{exc}`` text from deep layers, which could
    carry ticket content — the stamp keeps only the exception TYPE (the full
    message lives in the ERROR log, the diagnostic surface, and in the
    born-encrypted journal where content belongs)."""
    if step.ok:
        return {"name": step.name, "ok": True, "detail": step.detail}
    detail = step.detail.split(":", 1)[0].strip() if step.detail else ""
    return {"name": step.name, "ok": False, "detail": detail}


# ---------------------------------------------------------------------------
# The thread
# ---------------------------------------------------------------------------


class Heartbeat:
    """One heartbeat: the timer loop around the (already-merged) wake cycle.

    Construct via :func:`build_heartbeat` in production; tests construct
    directly with injected clocks/env/router. Every collaborator is injected —
    the loop itself reads no config and parses no TOML (§3.2: one source of
    truth, resolved once at build)."""

    def __init__(
        self,
        *,
        env: "CycleEnv",
        router: "OutputRouter",
        interval_s: float,
        boot_grace_s: float,
        shadow_mode: bool,
        stamp_path: Path,
        seen_path: Path,
        cleanup_started: Callable[[], bool],
        clock: "Callable[[], datetime] | None" = None,
        local_clock: "Callable[[], datetime] | None" = None,
        cycle_fn: "Callable[..., CycleResult] | None" = None,
        max_cycles: "int | None" = None,
        watchdog: "Any | None" = None,
        session_id: str = "",
    ) -> None:
        self._env = env
        self._router = router
        self._interval_s = float(interval_s)
        self._boot_grace_s = float(boot_grace_s)
        self._shadow_mode = bool(shadow_mode)
        self._stamp_path = stamp_path
        self._seen_path = seen_path
        self._cleanup_started = cleanup_started
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._local_clock = local_clock or datetime.now  # naive local wall clock
        self._cycle_fn = cycle_fn
        self._max_cycles = max_cycles  # tests bound the loop; production runs open
        self._watchdog = watchdog  # the limb-7 dead-man (same factory gate, §6.2)
        # This boot's stamp identity (review 06a5b435 MAJOR 1): the dead-man
        # only voices present-tense alarms over stamps carrying THIS id; a
        # prior session's leftover is the boot reconcile's, past tense, once.
        self._session_id = session_id
        self._next_interval_s = float(interval_s)
        self._stop = threading.Event()
        self._thread: "threading.Thread | None" = None

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        """Spawn the named daemon thread — and the dead-man watchdog beside it
        (§6.2: same factory gate; no heartbeat, no watchdog). Idempotent."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name=HEARTBEAT_THREAD_NAME, daemon=True
        )
        self._thread.start()
        if self._watchdog is not None:
            self._watchdog.start()

    def stop(self) -> None:
        """Signal the loop and join briefly — called FIRST in the launcher's
        ``_cleanup()`` (§3.1), before services stop. Bounded: a mid-cycle
        heartbeat gets :data:`_STOP_JOIN_S` to finish its step; past that the
        daemon flag guarantees it dies with the process rather than holding
        teardown open. Writes the CLEAN-STOP marker (§6.3) so the next boot's
        reconcile can tell 'the app was off' from 'beats stopped coming', then
        stops the watchdog (which reads a cleanly-stopped stamp as quiet)."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=_STOP_JOIN_S)
        self._write_clean_stop()
        if self._watchdog is not None:
            self._watchdog.stop()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -- the loop (§2 step 11 + §3.3 walls 2/3) ------------------------------

    def _run(self) -> None:
        try:
            self._graduation_reset()
            # Boot grace: the first cycle waits out boot/preflights (§9); a stop
            # during the wait exits cleanly without a cycle.
            if self._stop.wait(self._boot_grace_s):
                return
            cycles = 0
            prior_digest: "DigestRecord | None" = None
            while not self._stop.is_set() and not self._cleanup_started():
                prior_digest = self._one_cycle(
                    # The tripwire's idle-grace floor (§9): the FIRST cycle after
                    # boot still counts as inside the grace (floor = grace + one
                    # interval), so a fresh morning boot never alarms instantly.
                    in_boot_grace=(cycles == 0),
                    prior_digest=prior_digest,
                )
                cycles += 1
                if self._max_cycles is not None and cycles >= self._max_cycles:
                    return
                if self._stop.wait(self._next_interval_s):
                    return
        except Exception as exc:  # noqa: BLE001 — §3.3 wall 3: fail-LOUD, then die
            logger.error(
                "heartbeat: thread died on an escaped exception (wall 3): %s",
                exc,
                exc_info=True,
            )
            self._stamp_thread_dead(exc)

    def _one_cycle(
        self, *, in_boot_grace: bool, prior_digest: "DigestRecord | None"
    ) -> "DigestRecord | None":
        from shared.coordinator import heartbeat_cycle as hc

        cycle_fn = self._cycle_fn or hc.run_wake_cycle
        started = self._clock()
        result: "CycleResult" = cycle_fn(
            self._env,
            now=started,
            local_now=self._local_clock(),
            teardown_started=self._cleanup_started(),
            previous_cycle_running=False,  # structurally serial in this loop
            in_boot_grace=in_boot_grace,
            prior_digest=prior_digest,
        )
        self._next_interval_s = result.decision.next_interval_s
        self._route_outputs(result)
        completed = self._clock()
        try:
            write_liveness_stamp(
                self._stamp_path,
                started_at=result.started_at,
                completed_at=completed.isoformat(),
                mode=result.decision.mode.value,
                next_interval_s=result.decision.next_interval_s,
                next_expected_by=(
                    completed + timedelta(seconds=result.decision.next_interval_s)
                ).isoformat(),
                shadow_mode=self._shadow_mode,
                session_id=self._session_id,
                steps=tuple(_stamp_step(s) for s in result.steps),
            )
        except OSError as exc:
            # A stamp-write failure starves the dead-man of fresh evidence — the
            # dead-man will trip on staleness (its job), and we say why here.
            logger.error("heartbeat: liveness stamp write failed: %s", exc)
        return result.digest or prior_digest

    def _route_outputs(self, result: "CycleResult") -> None:
        """Discharge the limb-4/5 review obligations for one cycle result.

        The cycle's SINKS (stall comments, board moves) were already routed —
        they ARE the router's bound methods, injected into the env at build.
        What remains on the result: the surfaced conditions (every one through
        ``route_tripwire``, the single safe entry — health auto-diverts), the
        shadow proposal copies, and the digest. Each wrapped: a routing fault
        must never kill the loop (§3.3 wall 2)."""
        for condition in result.conditions:
            try:
                self._router.route_tripwire(condition)
            except Exception as exc:  # noqa: BLE001
                logger.error("heartbeat: condition routing failed: %s", exc)
        if result.redispatch is not None and result.redispatch.staged:
            for staged in result.redispatch.staged:
                try:
                    copy: "dict[str, Any]" = {
                        "proposal_id": staged.proposal_id,
                        "task": staged.task,
                        "fingerprint": staged.fingerprint,
                        "run_id": (
                            result.snapshot.latest_run.value[0]
                            if result.snapshot is not None
                            and result.snapshot.latest_run.value is not None
                            else ""
                        ),
                    }
                    # The FULL-context copy (review 8c18ed43 MINOR-4): the
                    # target/goal live on the store's proposal record, not on
                    # StagedRedispatch — enrich from the store so #855 can grade
                    # from the journal ALONE. Fail-soft: a store fault degrades
                    # to the pointer-grade copy (join on proposal_id still works).
                    store = getattr(self._env, "store", None)
                    if store is not None:
                        try:
                            proposal = store.get(staged.proposal_id)
                            if proposal is not None:
                                copy["payload"] = dict(proposal.payload)
                                copy["status"] = proposal.status.value
                        except Exception as exc:  # noqa: BLE001
                            logger.warning(
                                "heartbeat: proposal-copy enrichment failed "
                                "(pointer-grade copy journaled): %s",
                                exc,
                            )
                    self._router.record_proposal_copy(copy)
                except Exception as exc:  # noqa: BLE001
                    logger.error("heartbeat: proposal-copy journal failed: %s", exc)
        if result.digest is not None:
            try:
                self._router.route_digest(result.digest)
            except Exception as exc:  # noqa: BLE001
                logger.error("heartbeat: digest routing failed: %s", exc)

    def _graduation_reset(self) -> None:
        """§7.2 graduation hygiene, once per boot: compare the PRIOR stamp's
        recorded mode against this boot's — the shadow→live edge resets the
        stall seen-set so ongoing stalls earn fresh first live comments. Every
        subsequent stamp this boot records the current mode, completing the
        exactly-once contract."""
        from shared.coordinator.output_router import reset_seen_set_on_graduation

        try:
            recorded = recorded_shadow_mode(read_liveness_stamp(self._stamp_path))
            fired = reset_seen_set_on_graduation(
                recorded, self._shadow_mode, self._seen_path, now=self._clock()
            )
            if fired:
                # Close the re-fire window (review 8c18ed43 MINOR-3): without
                # this, the current mode is first recorded a boot-grace + one
                # full cycle later — a crash inside that window (live comments
                # posted, stamp still saying shadow) would re-fire the reset
                # next boot and re-comment every ongoing stall. Stamping the
                # current mode HERE, atomically, right after the reset makes
                # the exactly-once contract crash-tight.
                now = self._clock()
                write_liveness_stamp(
                    self._stamp_path,
                    started_at=now.isoformat(),
                    completed_at=now.isoformat(),
                    mode="GRADUATED",
                    next_interval_s=self._interval_s,
                    next_expected_by=(
                        now
                        + timedelta(seconds=self._boot_grace_s + self._interval_s)
                    ).isoformat(),
                    shadow_mode=self._shadow_mode,
                    session_id=self._session_id,
                    note="stall seen-set reset at shadow->live graduation",
                )
        except Exception as exc:  # noqa: BLE001 — hygiene must not kill the thread
            logger.error("heartbeat: graduation seen-set reset failed: %s", exc)

    def _write_clean_stop(self) -> None:
        """Best-effort clean-stop marker (§6.3) — mode STOPPED, no beat due.

        Skipped when the thread died (the wall-3 ``thread_dead`` stamp is the
        louder, truer record and must not be overwritten by teardown) — and
        skipped when THIS session's heartbeat was already OVERDUE at teardown
        (review 06a5b435 MAJOR 2): a wedge that rode into shutdown is exactly
        what §6.3's boot reconcile exists to surface, and a clean marker over
        its stale stamp would bury the only evidence. Overdue = past the
        stamp's own ``next_expected_by`` by more than the registered dead-man
        slack; an UNPARSEABLE deadline on a current-session stamp also skips
        (doubt never buries evidence). A ``None`` prior (stopped during boot
        grace — nothing was ever due) and a FOREIGN prior (already voiced by
        this boot's reconcile, past tense) still write the marker: those stops
        are genuinely clean."""
        try:
            prior = read_liveness_stamp(self._stamp_path)
            if prior is not None and bool(prior.get("thread_dead")):
                return
            if prior is not None and bool(prior.get("stopped_cleanly")):
                return  # already clean (double-stop) — idempotent
            now = self._clock()
            if prior is not None and prior.get("session_id") == self._session_id:
                from shared.coordinator.deadman import DEADMAN_SLACK_S, _parse_iso

                deadline = _parse_iso(prior.get("next_expected_by"))
                if deadline is None or (
                    (now - deadline).total_seconds() > DEADMAN_SLACK_S
                ):
                    logger.warning(
                        "heartbeat: NOT writing the clean-stop marker — this "
                        "session's heartbeat was overdue (or its deadline "
                        "unreadable) at teardown; the stale stamp stays as "
                        "wedge evidence for the boot reconcile (§6.3)."
                    )
                    return
            write_liveness_stamp(
                self._stamp_path,
                started_at=str(prior.get("started_at", "")) if prior else "",
                completed_at=now.isoformat(),
                mode="STOPPED",
                next_interval_s=self._next_interval_s,
                next_expected_by="",
                shadow_mode=self._shadow_mode,
                stopped_cleanly=True,
                session_id=self._session_id,
                note="clean heartbeat stop (launcher teardown)",
            )
        except Exception as exc:  # noqa: BLE001 — a failed marker degrades to a
            # (false-positive-leaning) boot notice next session, never a raise
            logger.warning("heartbeat: clean-stop marker write failed: %s", exc)

    def _stamp_thread_dead(self, exc: Exception) -> None:
        """Best-effort ``thread_dead=true`` stamp — what the limb-7 dead-man
        reads to trip immediately (§6.2). Best-effort by design: if even this
        write fails, the stamp goes stale and the dead-man trips on staleness."""
        try:
            now = self._clock()
            write_liveness_stamp(
                self._stamp_path,
                started_at=now.isoformat(),
                completed_at=now.isoformat(),
                mode="DEAD",
                next_interval_s=self._interval_s,
                next_expected_by=(
                    now + timedelta(seconds=self._interval_s)
                ).isoformat(),
                shadow_mode=self._shadow_mode,
                thread_dead=True,
                session_id=self._session_id,
                # Exception TYPE only (review 8c18ed43 MINOR-2): the message can
                # carry deep-layer content; the full text is in the ERROR log.
                note=type(exc).__name__,
            )
        except Exception:  # noqa: BLE001 — staleness is the fallback alarm
            logger.error("heartbeat: could not stamp thread_dead (stamp stale)")


# ---------------------------------------------------------------------------
# The drafting-seam adapter (limb-5 review finding 2)
# ---------------------------------------------------------------------------


def draft_fn_from_service(service: Any) -> "Callable[[str], Any] | None":
    """Wrap the AO's ``coordinator_draft()`` (limb 5) into the cycle engine's
    ``DraftFn`` shape, preserving the ``has_text`` distinction: the adapter's
    in-band model-path failure (``drafted`` with no text) maps to the cycle's
    ``failed`` — a recorded degradation whose deterministic-skeleton fallback
    stands in — never to a successful-looking empty draft (limb-5 review
    finding 2; #845 c.1895 obligation c)."""
    method = getattr(service, "coordinator_draft", None)
    if method is None or not callable(method):
        return None

    from shared.coordinator.heartbeat_cycle import DraftOutcome

    def _draft(prompt: str) -> DraftOutcome:
        outcome = method(prompt)
        status = getattr(outcome, "status", None)
        status_value = getattr(status, "value", status)
        text = str(getattr(outcome, "text", "") or "")
        reason = str(getattr(outcome, "reason", "") or "")
        if status_value == "drafted" and not text.strip():
            return DraftOutcome(
                status="failed",
                reason=reason or "model path failed in-band (drafted with no text)",
            )
        if status_value in ("drafted", "busy", "not_resident"):
            return DraftOutcome(status=str(status_value), text=text, reason=reason)
        return DraftOutcome(
            status="failed", reason=f"unrecognized draft status {status_value!r}"
        )

    return _draft


# ---------------------------------------------------------------------------
# The factory (§3.2 — structural absence; the four dormancy lock shapes)
# ---------------------------------------------------------------------------


def build_heartbeat(
    service: Any,
    *,
    cleanup_started: Callable[[], bool],
    data_dir: "str | Path | None" = None,
    dev_mode: bool = False,
) -> "Heartbeat | None":
    """Build the heartbeat from the started AO service's resolved properties —
    or ``None``, constructing NOTHING, when ``heartbeat_enabled`` is false
    (structural absence, §3.2; the doom-watchdog factory pattern verbatim:
    absent-attribute→None, false→None, true→built with the registered cadence).

    *service* is the started ``AssistantOrchestratorService`` (the single
    source of truth for every ``[coordinator]`` value — never a second TOML
    parse, mirroring ``coordinator_enabled``'s threading). *cleanup_started*
    is the launcher's teardown flag (read live each cycle). *data_dir*
    overrides the content-bearing store home (default
    ``%LOCALAPPDATA%/BlarAI``); the coordinator store root becomes
    ``<data_dir>/coordinator`` — enumerated into ``GovernedCoreRoots`` so the
    SG ruler protects the stores it just created (§2.1 item 10). *dev_mode*
    threads into BOTH store factories (the dev path stays a loud, explicit
    opt-in — never a silent fallback).

    Fail-closed refusals: no journal ⇒ no heartbeat (in shadow the journal IS
    the output path; running without it would discard or mis-route every
    effect). A proposal-store fault alone degrades to ``store=None`` — the
    cycle surfaces it as machinery health while the deterministic organizing
    continues."""
    if not bool(getattr(service, "coordinator_heartbeat_enabled", False)):
        return None

    # Lazy imports — the OFF path above never touches any of this machinery.
    from shared.coordinator.config import default_governed_core_roots
    from shared.coordinator.heartbeat_cycle import (
        CycleEnv,
        default_absence_stamp_path,
    )
    from shared.coordinator.output_router import build_output_router
    from shared.coordinator.proposal_store import build_proposal_store
    from shared.coordinator.shadow_journal import build_shadow_journal
    from shared.fleet.coord_board_history import default_board_history_path
    from shared.fleet.coord_stall_state import default_stall_seen_path
    from shared.fleet.dispatch import build_default_config

    fleet_config = build_default_config(
        getattr(service, "fleet_dispatch_agentic_setup_dir", "") or None,
        getattr(service, "fleet_dispatch_projects_dir", "") or None,
    )

    if data_dir is None:
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        data_dir = Path(local_app_data) / "BlarAI" if local_app_data else Path("BlarAI")
    store_root = Path(data_dir) / "coordinator"
    try:
        store_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error(
            "heartbeat: coordinator store root %s could not be created — "
            "REFUSING to start (no home for the shadow journal): %s",
            store_root,
            exc,
        )
        return None

    shadow_mode = bool(getattr(service, "coordinator_shadow_mode", True))

    try:
        journal = build_shadow_journal(
            str(store_root / "shadow-journal.db"), dev_mode=dev_mode
        )
    except Exception as exc:  # noqa: BLE001 — refuse-to-start, fail-closed + loud
        logger.error(
            "heartbeat: shadow journal could not be provisioned — REFUSING to "
            "start the heartbeat (in shadow the journal is the output path; "
            "running without it would silently discard evidence): %s",
            exc,
        )
        return None

    store = None
    try:
        store = build_proposal_store(
            str(store_root / "proposals.db"), dev_mode=dev_mode
        )
        store.reconcile_at_boot()
    except Exception as exc:  # noqa: BLE001 — cycle surfaces store=None as health
        logger.error(
            "heartbeat: proposal store unavailable (deterministic organizing "
            "continues; staging skipped + surfaced as machinery health): %s",
            exc,
        )
        store = None

    router = build_output_router(shadow_mode=shadow_mode, journal=journal)

    # ── Limb 7 (§6): the dead-man watchdog + the boot reconcile ────────────
    # Same factory gate — no heartbeat, no watchdog. The alert sink is the
    # router's route_health (machinery health: operator surface in BOTH modes,
    # never shadow-gated); the boot reconcile surfaces the PREVIOUS session's
    # wedge/crash evidence once, through the same sink.
    from shared.coordinator.deadman import (
        DEADMAN_SLACK_S,
        DeadManWatchdog,
        reconcile_boot_stamp,
    )
    from shared.coordinator.heartbeat_cycle import SurfacedCondition

    stamp_path = default_liveness_stamp_path(fleet_config)

    def _health_alert(message: str) -> None:
        router.route_health(
            SurfacedCondition("dead-man", message, machinery_health=True)
        )

    boot_notice = reconcile_boot_stamp(read_liveness_stamp(stamp_path))
    if boot_notice is not None:
        _health_alert(boot_notice)

    interval_s = float(getattr(service, "coordinator_heartbeat_interval_s", 900.0))
    boot_grace_s = float(
        getattr(service, "coordinator_heartbeat_boot_grace_s", 300.0)
    )
    # This boot's stamp identity (review 06a5b435 MAJOR 1): a leftover stamp
    # from a crashed prior session can never raise the in-session watchdog's
    # present-tense alarm — the boot reconcile above already voiced it once.
    session_id = uuid.uuid4().hex
    watchdog = DeadManWatchdog(
        stamp_path=stamp_path,
        session_id=session_id,
        alert=_health_alert,
        # Anchored at the watchdog's FIRST check (review 06a5b435 NIT 9).
        initial_grace_s=boot_grace_s + interval_s + DEADMAN_SLACK_S,
    )

    roots = default_governed_core_roots(coordinator_store_root=store_root)
    env = CycleEnv(
        fleet_config=fleet_config,
        coordinator_config=_coordinator_config_from_service(service),
        coordinator_projects=dict(getattr(service, "coordinator_projects", {}) or {}),
        roots=roots,
        board_history_path=default_board_history_path(fleet_config),
        stall_seen_path=default_stall_seen_path(fleet_config),
        absence_stamp_path=default_absence_stamp_path(fleet_config),
        store=store,
        campaign_state_path=(
            Path(p)
            if (p := getattr(service, "coordinator_battery_campaign_state_path", ""))
            else None
        ),
        shadow_mode=shadow_mode,
        move_card=router.move_card,
        post_stall_comment=router.post_stall_comment,
        draft=draft_fn_from_service(service),
    )

    return Heartbeat(
        env=env,
        router=router,
        interval_s=interval_s,
        boot_grace_s=boot_grace_s,
        shadow_mode=shadow_mode,
        stamp_path=stamp_path,
        seen_path=default_stall_seen_path(fleet_config),
        cleanup_started=cleanup_started,
        watchdog=watchdog,
        session_id=session_id,
    )


def _coordinator_config_from_service(service: Any):
    """Rebuild a :class:`CoordinatorConfig` value object from the AO service's
    resolved properties — the SAME values ``CoordinatorConfig.from_toml``
    produced at AO start (one source of truth; this is a re-materialization,
    never a second TOML parse).

    DELIBERATELY PARTIAL (review 8c18ed43 MINOR-1, dispositioned): only the
    fields the cycle engine actually reads are carried; the non-heartbeat
    fields (``work_origination_enabled``, ``swap_doom_checks_enabled``,
    ``require_signed_policy``, ``policy_path``, ``enabled_auto_classes``)
    revert to their dormant defaults here. The drift trap — a future cycle
    step silently reading a dropped field's default — is closed by a source-
    scan lock (``test_rematerialized_config_covers_every_cycle_read``): any
    new ``cfg.<field>`` read in the cycle engine fails the gate until the
    field is carried here (or a real ``coordinator_config`` AO property
    replaces this re-materialization)."""
    from shared.coordinator.config import CoordinatorConfig

    return CoordinatorConfig(
        enabled=bool(getattr(service, "coordinator_enabled", False)),
        heartbeat_enabled=True,  # build_heartbeat gates on it before reaching here
        heartbeat_interval_s=float(
            getattr(service, "coordinator_heartbeat_interval_s", 900.0)
        ),
        heartbeat_battery_multiplier=float(
            getattr(service, "coordinator_heartbeat_battery_multiplier", 4.0)
        ),
        heartbeat_boot_grace_s=float(
            getattr(service, "coordinator_heartbeat_boot_grace_s", 300.0)
        ),
        overnight_window=str(
            getattr(service, "coordinator_overnight_window", "23:00-09:00")
        ),
        operator_absent=bool(getattr(service, "coordinator_operator_absent", False)),
        shadow_mode=bool(getattr(service, "coordinator_shadow_mode", True)),
    )
