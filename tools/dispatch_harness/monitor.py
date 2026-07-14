"""SMART run monitoring with stop-doomed-fast — the dev-cycle-speed core.

Do NOT just poll ``SUMMARY.txt``. A coding run can legitimately take a LONG time (a live
rocket-calc run measured ~1 hour and PARKED — a real success), so elapsed time alone is NEVER
the doom signal. Instead we read PROGRESS signals from the fleet's own artifacts and stop only
when a run is DETERMINED-doomed: making no progress AND with no coder process doing work.

The signals (all on the agentic-setup side, under ``state\\``):
  * ``state/fleet-runs/<RunId>/journal.log``         — the orchestrator step log
      (RUN-START → TASK-START → TASK-END → RUN-END). Its mtime advances at task boundaries.
  * ``state/fleet-runs/<RunId>/run-fleet-<slug>.log`` — the per-task fleet log
      ([1/5] Building…, [2/5]…). Its mtime advances as the coder works a task.
  * ``state/logs/ovms-*.out.log``                     — OVMS generation output; its mtime is a
      proxy for "the 30B is generating tokens" (stale == no generation).
  * ``state/fleet-runs/<RunId>/SUMMARY.txt``          — the COMPLETION signal (run-fleet writes
      it when a task finishes; MERGED/PARKED/BLOCKED/NOTHING).
  * ``state/fleet-swap/SWAP_FAILED_<RunId>.txt``      — the out-of-band failure signal.
  * the coder child-process CPU (psutil) — opencode / dotnet / node / playwright-msedge burning
      CPU means the run is alive even if a log is momentarily quiet.

A run is DOOMED when, between two snapshots ``stall_grace_s`` apart, NONE of the progress
artifacts advanced AND the coder CPU is idle AND there is no SUMMARY yet. That is the
"determined-doomed" state the brief says to STOP FAST (via ``/dispatch stop``), not wait out.

We deliberately do NOT grep the coder agent log for tokens like "parked" / "CS0246": that file
echoes seed documentation that contains those words, so token-grepping it is a false-positive
trap. We read the FLEET log mtimes + process CPU, never the agent-log content.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from shared.fleet import doom_check as _doom
from shared.fleet import swap_state as _ss
from shared.fleet.dispatch import FleetDispatchConfig, parse_summary, slugify_task

# The coder-process-name list + CPU threshold were PROMOTED to shared/fleet/doom_check.py
# (#844 C2 — the driver-integrated stop-doomed-fast checks), which is now their SSOT: the
# harness monitor (this external poller) and the driver's DoomWatchdog must never drift on
# what counts as "the run is doing work". Values are byte-identical to the tuple that lived
# here (including the night-20260709 B4 false-doom additions — the [3/5] verify gate's
# uv/ruff/git native workers, which burn CPU while every watched log stays quiet by design).
_CODER_PROC_NAMES: tuple[str, ...] = _doom.CODER_PROC_NAMES

#: CPU-percent above which a process counts as "actively working" for a sample (SSOT:
#: shared/fleet/doom_check.py — see the promotion note above).
_CPU_ACTIVE_THRESHOLD: float = _doom.CPU_ACTIVE_THRESHOLD

# Swap-phase classification (the multi-task #686 fix). A multi-task dispatch runs run-fleet ONCE
# PER TASK — each invocation overwrites SUMMARY.txt — and the 14B swap-back happens in the detached
# driver's teardown AFTER the last task. So a SUMMARY appearing is NOT "the dispatch is done"; only
# the swap reaching a TERMINAL phase is.
#
# A REAL terminal swap phase: the dispatch RAN and ENDED — every task processed + the 14B restored
# (RECOVERED), the swap-back gave up (FAILED), or it was cancelled (CANCELLED). COMPLETE fires here
# regardless of whether a SUMMARY was written: a crashed run can reach a terminal phase without one,
# and the harness must conclude (outcome NONE) rather than hang. IDLE is deliberately EXCLUDED — it
# is the resting/"no swap in flight" state, not the end of a run that ran. ``""`` (no swap pipeline
# at all = a dry-run) is handled separately so SUMMARY.txt stays authoritative there.
_SWAP_TERMINAL_PHASES: frozenset[str] = frozenset(
    {_ss.PHASE_RECOVERED, _ss.PHASE_FAILED, _ss.PHASE_CANCELLED}
)
# The ONLY phase with an active coder process — the sole phase where a no-progress stall means a
# doomed coder. The swap setup/teardown phases (RESERVE..LOAD-30B, UNLOAD-30B..RESTART-AO) have no
# coder, so a quiet log there is the driver working/winding-down, not doom; ``""`` (dry-run) is
# treated as coding so a stalled fake run still dooms. Non-coding phases are bounded by the driver
# itself + the overall-timeout backstop.
_ACTIVE_CODING_PHASES: frozenset[str] = frozenset({_ss.PHASE_CODE, ""})


class DoomVerdict(str, Enum):
    """The monitor's per-poll verdict."""

    WAITING = "WAITING"            # not enough info yet (no progress artifact seen at all)
    RUNNING = "RUNNING"           # progress observed since the prior snapshot — keep going
    COMPLETE = "COMPLETE"         # SUMMARY.txt present — the run finished
    FAILED_SIGNAL = "FAILED"      # the out-of-band SWAP_FAILED file appeared
    DOOMED = "DOOMED"             # determined-doomed (no progress + idle coder + no summary)


@dataclass(frozen=True)
class RunSignals:
    """A pure snapshot of a run's progress signals at one instant.

    Everything the doom predicate needs is captured here so the predicate is a pure function of
    two snapshots (trivially unit-testable with hand-built fakes — no disk, no psutil). ``now`` is
    a monotonic stamp (loop timing); ``wall_now`` is the wall clock at capture, needed to age the
    absolute file mtimes (which are wall-clock from ``os.stat``).
    """

    now: float                          # monotonic stamp at capture (loop timing)
    wall_now: float                     # wall-clock stamp at capture (to age mtimes)
    summary_exists: bool                # SUMMARY.txt present
    summary_text: str = ""              # its contents (for outcome classification), or ""
    swap_failed_exists: bool = False    # SWAP_FAILED_<RunId>.txt present
    journal_mtime: float | None = None  # journal.log mtime (None == missing)
    fleet_log_mtime: float | None = None  # run-fleet-<slug>.log mtime (None == missing)
    ovms_log_mtime: float | None = None   # newest ovms-*.out.log mtime (None == missing)
    # The per-task review / coder / design-fix output + the design phase + the swap trail. These
    # advance during work the journal/run-fleet/ovms logs do NOT track -- a long [4/5] 30B review
    # (its tokens go to *.review.log, GPU-bound so the CPU probe reads idle) and the end-of-run
    # design loop. Without them a healthy long review/design phase FALSE-DOOMED (#687).
    review_log_mtime: float | None = None    # newest state/reports/*.review.log + *.agent.log mtime
    design_log_mtime: float | None = None    # <run>/design-critique.log mtime (the design phase)
    swap_progress_mtime: float | None = None  # <run>/swap-progress.log mtime (phase transitions/notes)
    coder_cpu_active: bool = False      # a coder/fleet child burned CPU over the sample window
    phase: str = ""                     # the swap-state phase (diagnostic only)

    @property
    def progress_mtime(self) -> float | None:
        """The most recent of ALL progress-log mtimes (the run's freshest progress timestamp).
        Includes the review/coder/design/swap logs so a long [4/5] review or the end-of-run design
        loop -- GPU-bound (the CPU probe reads idle), writing to logs the journal/run-fleet/ovms set
        misses -- reads as progress, not a stall (the #687 false-doom)."""
        candidates = [
            m for m in (self.journal_mtime, self.fleet_log_mtime, self.ovms_log_mtime,
                        self.review_log_mtime, self.design_log_mtime, self.swap_progress_mtime)
            if m is not None
        ]
        return max(candidates) if candidates else None

    @property
    def has_any_progress_artifact(self) -> bool:
        """True once ANY progress artifact (a log or the summary) exists — i.e. the run has
        actually started producing output. Before this, a stale read is just 'not started yet'."""
        return (
            self.summary_exists
            or self.journal_mtime is not None
            or self.fleet_log_mtime is not None
        )

    def wall_age_of(self, mtime: float | None) -> float | None:
        """Seconds between this snapshot's wall clock and an absolute ``mtime`` (None-safe)."""
        if mtime is None:
            return None
        return self.wall_now - mtime


def classify_run_health(
    prev: RunSignals | None,
    cur: RunSignals,
    *,
    stall_grace_s: float,
    terminal_phases: frozenset[str] = _SWAP_TERMINAL_PHASES,
    coding_phases: frozenset[str] = _ACTIVE_CODING_PHASES,
) -> DoomVerdict:
    """Decide a run's health from two snapshots — the PURE doom-detection predicate.

    Precedence (a definite signal beats a heuristic):
      1. the ``SWAP_FAILED`` file present              -> FAILED_SIGNAL.
      2. the swap pipeline reached a TERMINAL phase (RECOVERED/FAILED/CANCELLED — the dispatch ran
         and ended, the 14B restored or gave up)       -> COMPLETE, with OR without a SUMMARY (a
         crashed run can reach a terminal phase having written none; outcome then = NONE).
      3. no swap pipeline at all (phase ``""`` — a dry-run / fake AO) AND ``SUMMARY.txt`` present
         (SUMMARY is authoritative there)              -> COMPLETE.
      4. no progress artifact has appeared yet         -> WAITING (the run hasn't started).
      5. the coder CPU is active                       -> RUNNING (work is happening).
      6. a progress mtime advanced since ``prev``      -> RUNNING.
      7. a stall (freshest progress older than ``stall_grace_s``, confirmed by a prior snapshot)
         AND the swap is in the ACTIVE-CODING phase    -> DOOMED.
      8. not confidently stalled, or stalled OUTSIDE the coding phase -> WAITING.

    The #686 fix is rules 2/3 and 7. A multi-task dispatch runs ``run-fleet`` ONCE PER TASK, each
    overwriting ``SUMMARY.txt`` — so a SUMMARY appearing mid-CODE is NOT "the dispatch is done";
    only the swap reaching a terminal phase (after the LAST task + the 14B swap-back) is. And a
    no-progress stall is doom ONLY during CODING: the swap setup/teardown phases have no coder, so
    a quiet log there is the driver working/winding-down, not a doomed run.

    ``cur.phase`` MUST already be scoped to THIS run (a stale phase from a PRIOR dispatch is treated
    as ``""`` by the caller — see ``RunMonitor._phase``) so a leftover RECOVERED cannot falsely
    complete a fresh run.

    ``stall_grace_s`` is the no-progress window that defines doom. It must comfortably exceed the
    longest expected gap BETWEEN progress writes within a healthy run (build/test steps can be
    quiet for a while), NOT the whole run length. The overall-timeout cap (handled by the caller)
    is the separate backstop.
    """
    if cur.swap_failed_exists:
        return DoomVerdict.FAILED_SIGNAL
    if cur.phase in terminal_phases:
        return DoomVerdict.COMPLETE
    if not cur.phase and cur.summary_exists:
        return DoomVerdict.COMPLETE
    if not cur.has_any_progress_artifact:
        return DoomVerdict.WAITING
    if cur.coder_cpu_active:
        return DoomVerdict.RUNNING

    cur_progress = cur.progress_mtime
    prev_progress = prev.progress_mtime if prev is not None else None
    if cur_progress is not None and prev_progress is not None and cur_progress > prev_progress:
        return DoomVerdict.RUNNING

    # No CPU, no mtime advance. A stall is DOOM only while a coder is supposed to be working
    # (the CODE phase); a quiet swap setup/teardown phase is bounded by the driver, not doomed.
    if cur.phase in coding_phases and cur_progress is not None:
        age = cur.wall_age_of(cur_progress)
        if age is not None and age >= stall_grace_s and prev is not None:
            return DoomVerdict.DOOMED
    return DoomVerdict.WAITING


# ---------------------------------------------------------------------------
# Outcome classification (off the real fleet parser)
# ---------------------------------------------------------------------------


def classify_outcome(summary_text: str) -> str:
    """Classify a run's overall outcome from its ``SUMMARY.txt`` body.

    Uses the REAL :func:`shared.fleet.dispatch.parse_summary` so the harness and the gateway
    agree byte-for-byte on the result words. The run-level outcome is the "worst" task result by
    severity (BLOCKED > PARKED > NOTHING > UNKNOWN > MERGED): a sweep wants the headline to flag
    any task that did not cleanly merge. Returns one of
    ``MERGED | PARKED | BLOCKED | NOTHING | UNKNOWN | NONE`` (``NONE`` == no task lines parsed).
    """
    outcomes = parse_summary(summary_text or "")
    if not outcomes:
        return "NONE"
    severity = {"BLOCKED": 4, "PARKED": 3, "NOTHING": 2, "UNKNOWN": 1, "MERGED": 0}
    worst = max(outcomes, key=lambda o: severity.get(o.result, 1))
    return worst.result


# ---------------------------------------------------------------------------
# Live signal gathering (disk + psutil) and the poll loop
# ---------------------------------------------------------------------------


@dataclass
class MonitorResult:
    """The terminal result of monitoring one run."""

    verdict: DoomVerdict
    outcome: str = ""               # the classified SUMMARY outcome (when COMPLETE)
    stop_reason: str = ""           # human text for a DOOMED/timeout/failed stop
    elapsed_s: float = 0.0
    last_phase: str = ""
    progress_tail: str = ""         # the swap-progress trail (for the report)
    polls: int = 0


@dataclass
class RunMonitor:
    """Polls a live run's signals and stops a determined-doomed run fast.

    Pure logic lives in :func:`classify_run_health` / :func:`classify_outcome`; this class is the
    thin I/O shell that reads the real fleet artifacts + process CPU and drives the loop. The
    ``stop_fn`` (the harness wires it to ``/dispatch stop``) is called once on a DOOMED or
    overall-timeout verdict; ``sleep`` / ``clock`` / ``proc_cpu_probe`` are injectable for tests.
    """

    config: FleetDispatchConfig
    run_id: str
    poll_interval_s: float = 5.0
    # 90 -> 240 (2026-07-09, night B4 false-doom): the [3/5] verify gate runs
    # verify-project.ps1 with a 600 s budget of its own, and its checks write
    # NOTHING to the watched logs until they finish — so the only in-gate
    # liveness signal is worker CPU, and a check whose worker name escapes
    # _CODER_PROC_NAMES reads as dead at 90 s inside a window the pipeline
    # explicitly granted. 240 s survives CPU-quiet gaps between checks while
    # still dooming a truly dead run in minutes (the overall bound backstops).
    # Registered: shared/timeout_registry.py.
    stall_grace_s: float = 240.0
    # 5400 -> 10800 (2026-07-08, #767/#757): this default was still sized to
    # pre-plan-graph runs while every production sibling had moved to the
    # measured 10800 family — the timeout registry's seeding inventory caught
    # the drift (dormant: production callers pass the config value, but a
    # dormant default must agree with its family or the first un-overridden
    # caller inherits the stale scar). Registered: shared/timeout_registry.py.
    overall_timeout_s: float = 10800.0
    # After a doom/timeout stop, wait up to this long for the detached swap driver to wind the
    # dispatch down to a TERMINAL phase (the 14B restored) before returning — so the harness never
    # reports "done" mid-swap-back (#686). The detached driver restores the 14B regardless.
    swapback_grace_s: float = 180.0
    cpu_sample_s: float = 1.5
    stop_fn: Callable[[], None] | None = None
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    wall_clock: Callable[[], float] = time.time
    log: Callable[[str], None] = lambda _msg: None
    # Injectable process-CPU probe: () -> bool ("a coder child is active"). Default uses psutil.
    proc_cpu_probe: Callable[[], bool] | None = None

    def _run_dir(self) -> Path:
        return self.config.runs_dir / self.run_id

    def _summary_path(self) -> Path:
        return self._run_dir() / "SUMMARY.txt"

    def _journal_path(self) -> Path:
        return self._run_dir() / "journal.log"

    def _ovms_logs_dir(self) -> Path:
        # state/logs lives beside the fleet queue's state dir.
        return self.config.queue_path.parent / "logs"

    @staticmethod
    def _mtime(path: Path) -> float | None:
        try:
            return path.stat().st_mtime
        except OSError:
            return None

    def _newest_ovms_mtime(self) -> float | None:
        try:
            logs = list(self._ovms_logs_dir().glob("ovms-*.out.log"))
        except OSError:
            return None
        mtimes = [m for m in (self._mtime(p) for p in logs) if m is not None]
        return max(mtimes) if mtimes else None

    def _fleet_log_mtime(self) -> float | None:
        """The newest ``run-fleet-*.log`` mtime in the run dir (the per-task fleet log).

        We glob rather than reconstruct the slug from the queued task name so a multi-task run
        (several ``run-fleet-<slug>.log`` files) tracks the latest-written one without us needing
        the task list here. :func:`shared.fleet.dispatch.slugify_task` is referenced only to keep
        the slug-scheme dependency explicit/visible for a future single-task fast-path."""
        _ = slugify_task  # explicit: the slug scheme is the fleet's; we glob the family here.
        try:
            logs = list(self._run_dir().glob("run-fleet-*.log"))
        except OSError:
            return None
        mtimes = [m for m in (self._mtime(p) for p in logs) if m is not None]
        return max(mtimes) if mtimes else None

    def _newest_report_mtime(self) -> float | None:
        """Newest ``state/reports/*.review.log`` + ``*.agent.log`` mtime -- the per-task review /
        coder / design-fix output. NOT run-scoped (the reports dir is shared), but during an ACTIVE
        run the freshest such log IS this run's (a prior run's is older and ages past stall_grace).
        This is the signal a long [4/5] review advances while journal/run-fleet/ovms stay quiet
        (the GPU-bound review writes tokens here, not to the fleet logs -- the #687 false-doom)."""
        reports = self.config.queue_path.parent / "reports"
        try:
            logs = list(reports.glob("*.review.log")) + list(reports.glob("*.agent.log"))
        except OSError:
            return None
        mtimes = [m for m in (self._mtime(p) for p in logs) if m is not None]
        return max(mtimes) if mtimes else None

    def _design_log_mtime(self) -> float | None:
        """``<run>/design-critique.log`` mtime -- advances during the end-of-run design phase."""
        return self._mtime(self._run_dir() / "design-critique.log")

    def _swap_progress_mtime(self) -> float | None:
        """``<run>/swap-progress.log`` mtime -- advances on swap phase transitions + design notes."""
        return self._mtime(self._run_dir() / "swap-progress.log")

    def _swap_failed_exists(self) -> bool:
        from shared.fleet.swap_ops import status_path

        try:
            return status_path(self.config, self.run_id).exists()
        except OSError:
            return False

    def _phase(self) -> str:
        from shared.fleet import swap_state as ss
        from shared.fleet.swap_ops import swap_state_path

        try:
            state = ss.read_swap_state(swap_state_path(self.config))
        except OSError:
            return ""
        # Trust the swap-state ONLY for OUR run. ``state/fleet-swap/current.json`` is per-box,
        # shared across dispatches — a stale RECOVERED from a PRIOR run must NOT make this run's
        # monitor falsely complete. No state, or a mismatched run_id -> "" (treated as no swap
        # pipeline; the monitor waits for THIS run's swap-state to be written).
        if state is None or state.run_id != self.run_id:
            return ""
        return state.phase

    def _progress_tail(self) -> str:
        from shared.fleet.swap_ops import read_swap_progress

        try:
            return read_swap_progress(self.config, self.run_id)
        except OSError:
            return ""

    def _default_cpu_probe(self) -> bool:
        """psutil-based 'is a coder child burning CPU?' over a short sample window. Fail-soft:
        any error -> True (conservative — never DOOM a run on an unreadable CPU probe; the
        mtime-stall condition still has to hold too, and the overall timeout is the backstop)."""
        try:
            import psutil
        except Exception:  # noqa: BLE001
            return True  # can't measure -> assume active (don't kill on a missing probe)
        try:
            procs = []
            for p in psutil.process_iter(["name"]):
                name = (p.info.get("name") or "").lower()
                if any(name == n or name.startswith(n) for n in _CODER_PROC_NAMES):
                    try:
                        p.cpu_percent(None)  # prime the per-process counter
                        procs.append(p)
                    except Exception:  # noqa: BLE001
                        pass
            if not procs:
                return False  # no coder/fleet process at all -> definitely idle
            self.sleep(self.cpu_sample_s)
            for p in procs:
                try:
                    if p.cpu_percent(None) >= _CPU_ACTIVE_THRESHOLD:
                        return True
                except Exception:  # noqa: BLE001
                    continue
            return False
        except Exception:  # noqa: BLE001
            return True  # unreadable -> assume active (fail-soft)

    def snapshot(self) -> RunSignals:
        """Capture a :class:`RunSignals` from the live artifacts + a CPU sample."""
        summary_path = self._summary_path()
        summary_text = ""
        summary_exists = summary_path.is_file()
        if summary_exists:
            try:
                summary_text = summary_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                summary_text = ""
        probe = self.proc_cpu_probe or self._default_cpu_probe
        return RunSignals(
            now=self.clock(),
            wall_now=self.wall_clock(),
            summary_exists=summary_exists,
            summary_text=summary_text,
            swap_failed_exists=self._swap_failed_exists(),
            journal_mtime=self._mtime(self._journal_path()),
            fleet_log_mtime=self._fleet_log_mtime(),
            ovms_log_mtime=self._newest_ovms_mtime(),
            review_log_mtime=self._newest_report_mtime(),
            design_log_mtime=self._design_log_mtime(),
            swap_progress_mtime=self._swap_progress_mtime(),
            coder_cpu_active=probe(),
            phase=self._phase(),
        )

    def run(self) -> MonitorResult:
        """Poll until the dispatch is TRULY done, the driver signals failure, or — after a
        doom/timeout stop — the bounded swap-back grace elapses.

        "Truly done" is the swap pipeline reaching a TERMINAL phase (every task processed + the
        14B restored), NOT the first per-task ``SUMMARY.txt`` (#686). On a DOOMED coder or the
        overall-timeout the ``stop_fn`` (``/dispatch stop``) is invoked ONCE; the monitor then
        keeps polling for the swap to wind down — so the harness never reports "done" while the
        14B swap-back is still in flight — bounded by ``swapback_grace_s`` (the detached driver
        restores the 14B regardless of whether the harness keeps waiting).
        """
        start = self.clock()
        prev: RunSignals | None = None
        polls = 0
        last_phase = ""
        stopping = False            # a doom/timeout stop was issued; now awaiting the swap-back
        stop_reason = ""
        stop_verdict = DoomVerdict.DOOMED
        stopped_elapsed = 0.0
        while True:
            cur = self.snapshot()
            polls += 1
            last_phase = cur.phase or last_phase
            verdict = classify_run_health(prev, cur, stall_grace_s=self.stall_grace_s)
            elapsed = self.clock() - start

            # ── Terminal: the dispatch is truly over (or there is no swap pipeline — dry-run). ──
            if verdict is DoomVerdict.COMPLETE:
                outcome = classify_outcome(cur.summary_text)
                final = stop_verdict if stopping else DoomVerdict.COMPLETE
                self.log(f"[{self.run_id}] complete — {outcome} ({elapsed:.0f}s, {polls} polls)")
                return MonitorResult(
                    verdict=final, outcome=outcome, stop_reason=stop_reason, elapsed_s=elapsed,
                    last_phase=last_phase, progress_tail=self._progress_tail(), polls=polls,
                )
            if verdict is DoomVerdict.FAILED_SIGNAL:
                reason = "the swap driver reported an out-of-band failure (SWAP_FAILED)"
                self.log(f"[{self.run_id}] FAILED — {reason}")
                return MonitorResult(
                    verdict=verdict, stop_reason=reason, elapsed_s=elapsed,
                    last_phase=last_phase, progress_tail=self._progress_tail(), polls=polls,
                )

            if not stopping:
                # ── Decide whether to STOP (a doomed coder during CODE, or the overall timeout). ──
                if verdict is DoomVerdict.DOOMED:
                    stop_reason = (
                        f"determined-doomed: no fleet progress for ≥{self.stall_grace_s:.0f}s "
                        f"(journal/run-fleet/ovms logs stale) and no coder process active; "
                        f"phase={last_phase or 'unknown'}"
                    )
                    self.log(f"[{self.run_id}] DOOMED — stopping fast. {stop_reason}")
                    self._invoke_stop()
                    stopping, stop_verdict, stopped_elapsed = True, DoomVerdict.DOOMED, elapsed
                elif elapsed >= self.overall_timeout_s:
                    stop_reason = (
                        f"overall timeout: exceeded {self.overall_timeout_s:.0f}s without completing"
                    )
                    self.log(f"[{self.run_id}] TIMEOUT — stopping. {stop_reason}")
                    self._invoke_stop()
                    stopping, stop_verdict, stopped_elapsed = True, DoomVerdict.DOOMED, elapsed
                # else WAITING/RUNNING — keep polling.
            elif elapsed - stopped_elapsed >= self.swapback_grace_s:
                # The stop was issued; give the detached driver this long to reach a terminal
                # phase, then return (it continues restoring the 14B independently). This bounds a
                # wedged swap-back so the harness cannot hang, without reporting "done" too early.
                self.log(
                    f"[{self.run_id}] stop issued; swap-back not terminal after "
                    f"{self.swapback_grace_s:.0f}s — the detached driver continues restoring the 14B"
                )
                return MonitorResult(
                    verdict=stop_verdict, outcome=classify_outcome(cur.summary_text),
                    stop_reason=stop_reason + " (swap-back still finishing in the detached driver)",
                    elapsed_s=elapsed, last_phase=last_phase,
                    progress_tail=self._progress_tail(), polls=polls,
                )

            prev = cur
            self.sleep(self.poll_interval_s)

    def _invoke_stop(self) -> None:
        if self.stop_fn is None:
            return
        try:
            self.stop_fn()
        except Exception as exc:  # noqa: BLE001 — a stop failure must not crash the sweep
            self.log(f"[{self.run_id}] stop_fn raised (continuing): {exc}")
