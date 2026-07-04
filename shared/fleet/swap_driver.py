"""The detached model-swap driver — executes the swap (design §2 steps 7-15).

Spawned breakaway by the AO just before the AO exits (full step-aside), this runs
in its own host process and OUTLIVES BlarAI's teardown. It settles, gates on real
headroom, loads the fleet's 30B, runs the queue per-task (cancel-aware), stops the
30B (disarm-then-stop, VERIFIED), and restarts BlarAI's backend with a bounded retry —
ALWAYS converging to "14B up, 30B down," and signalling out-of-band if the backend
won't come back (design §2.3).

Every side-effect (memory read, start-llm, run-fleet, Stop-Process, launcher
relaunch, the AO health probe, the out-of-band signal, the worktree sweep) is an
injected ``SwapOps`` callable, so the whole state machine is testable without a real
swap; the live wiring supplies the real subprocess/process operations. DORMANT until
enabled.

NEVER-ZERO is structural (#670 Problem 2): teardown runs on EVERY run() path inside a
``finally`` that catches ``BaseException`` too — every step is BaseException-guarded so an
early failure can never mask the original exception nor skip the RESTART-AO 14B restore,
which is UNCONDITIONALLY reached. The out-of-band budget watchdog (which tree-kills a
wedged run-fleet child so a hung task can never strand the swap) is stopped+joined and made
STRUCTURALLY INERT at teardown ENTRY, so it can never fire during the restore.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable
from pathlib import Path

from shared.fleet import swap_state as ss
from shared.fleet.acceptance import ACCEPTANCE_TASK_SLUG
from shared.fleet.dispatch import TaskOutcome


def _noop_progress(_message: str) -> None:
    """Default ``SwapOps.write_progress`` — discards the trail (tests that don't care about
    progress construct SwapOps without it)."""


def _noop_gpu_free() -> "float | None":
    """Default ``SwapOps.gpu_free_gb`` — probe unavailable (None), so the swap relies on the
    graceful 14B unload (legacy tests construct SwapOps without it)."""
    return None


def _noop_ovms_alive() -> bool:
    """Default ``SwapOps.ovms_alive`` — False == not-resident == verify-satisfied, so the
    new verify-stop branch is SKIPPED by default and the legacy exact-call-list tests stay
    green. The live ``real_ovms_alive`` supplies the real probe."""
    return False


def _noop_void() -> None:
    """Default for the injected no-op ``SwapOps`` actions (begin_teardown / sweep_worktrees)."""


def _false() -> bool:
    """Default ``SwapOps.stop_requested`` — no out-of-band stop unless a live budget watchdog
    wires a real per-run flag."""
    return False


def _noop_design_loop(_app_dir: str, _goal: str, _visual_criteria_json: str) -> dict:
    """Default ``SwapOps.run_design_loop`` — design critique unavailable, so the design phase
    no-ops (a single pass that reports nothing actionable). Legacy tests construct ``SwapOps``
    without it; the live ``build_swap_ops`` wires the real capture+critique pass."""
    return {"should_iterate": False, "needs_work": False,
            "feedback": "design critique unavailable", "layout_hard": False, "capture_tier": ""}


def _noop_critic(_app_dir: str, _base_branch: str) -> dict:
    """Default ``SwapOps.run_critic`` — 14B cross-model critic unavailable, so the critic phase
    no-ops (a single pass that reports nothing actionable). Legacy tests construct ``SwapOps``
    without it; the live ``build_swap_ops`` wires the real critic run (#687 task 2)."""
    return {"should_iterate": False, "verdict": "UNCLEAR", "findings": ""}


#: Surfaces whose built app can be screenshotted + judged by the VLM design loop (#688 Phase 3).
#: A non-visual surface (command-line / library / automation / unknown) has nothing to look at.
_DESIGN_SURFACES = frozenset({"web", "desktop-gui"})


# ---- out-of-band overall-run budget watchdog (#670 Problem 2 sharpening #2) ----------


def should_abort_run(*, elapsed_s: float, budget_s: float) -> bool:
    """Pure: has the overall-run budget elapsed? ``budget_s <= 0`` disables (never aborts)."""
    return budget_s > 0 and elapsed_s >= budget_s


def run_budget_watchdog(
    *,
    budget_s: float,
    finished: Callable[[], bool],
    abort: Callable[[], None],
    request_stop: Callable[[], None],
    poll_s: float = 1.0,
    sleep: "Callable[[float], None] | None" = None,
    monotonic: "Callable[[], float] | None" = None,
) -> None:
    """Daemon poll loop for the overall-run budget. ``finished()`` is checked the FIRST thing
    in EVERY iteration, so ``BudgetWatchdog.stop()`` (which sets the finished event) makes the
    loop self-exit. At the deadline it calls ``request_stop()`` (so the CODE loop breaks to
    teardown the instant the wedged task returns) THEN ``abort()`` (tree-kill the wedged child
    so the blocked ``run_task`` returns NOW), then returns. Clock/sleep injected for tests.

    It NEVER force-stops the driver — ``abort`` only tree-kills the registered run-fleet child,
    and once teardown begins ``abort`` is structurally inert (see ``_CurrentChild``)."""
    sleep = sleep or time.sleep
    monotonic = monotonic or time.monotonic
    start = monotonic()
    while True:
        if finished():
            return
        if should_abort_run(elapsed_s=monotonic() - start, budget_s=budget_s):
            try:
                request_stop()
            except Exception:  # noqa: BLE001
                pass
            try:
                abort()
            except Exception:  # noqa: BLE001
                pass
            return
        sleep(poll_s)


class BudgetWatchdog:
    """Owns the out-of-band budget daemon thread for ONE swap run.

    ``start()`` spawns the daemon (a NO-OP when ``budget_s <= 0`` — so the disable path and
    every budget-less existing test spawn no thread). ``stop()`` is idempotent and
    exception-proof: it sets the finished event then joins the thread with NO finite timeout —
    once ``finished`` is set each loop iteration is a cheap poll, so the loop exits within one
    poll interval and an unbounded join cannot hang. ``join(timeout)`` is deliberately NOT used:
    a bounded wait is not proof of death (the ``step_aside.py`` precedent returns with the
    thread alive on timeout), which would let a surviving daemon fire during the 14B restore.
    ``start()`` is fail-soft (a missing watchdog is a degradation, never a reason to abort a
    swap that must converge to 14B-up)."""

    def __init__(
        self,
        *,
        budget_s: float,
        abort: Callable[[], None],
        request_stop: Callable[[], None],
        poll_s: float = 1.0,
        sleep: "Callable[[float], None] | None" = None,
        monotonic: "Callable[[], float] | None" = None,
    ) -> None:
        try:
            self._budget_s = float(budget_s or 0.0)
        except (TypeError, ValueError):
            self._budget_s = 0.0
        self._abort = abort
        self._request_stop = request_stop
        self._poll_s = poll_s
        self._sleep = sleep
        self._monotonic = monotonic
        self._finished = threading.Event()
        self._thread: "threading.Thread | None" = None

    def start(self) -> None:
        if self._budget_s <= 0:
            return
        try:
            t = threading.Thread(
                target=run_budget_watchdog,
                kwargs=dict(
                    budget_s=self._budget_s,
                    finished=self._finished.is_set,
                    abort=self._abort,
                    request_stop=self._request_stop,
                    poll_s=self._poll_s,
                    sleep=self._sleep,
                    monotonic=self._monotonic,
                ),
                name="blarai-swap-run-budget",
                daemon=True,
            )
            t.start()
            self._thread = t
        except Exception:  # noqa: BLE001 — degrade to no-watchdog; NEVER raise into run()
            self._thread = None

    def stop(self) -> None:
        # Idempotent + exception-proof: the budget=0 / no-thread path must be a clean no-op
        # (every existing test) — never an AttributeError that masks `raised` in _teardown.
        self._finished.set()
        t = self._thread
        if t is None:
            return
        try:
            t.join()   # UNBOUNDED — finished is set, so the loop exits within one poll
        except Exception:  # noqa: BLE001
            pass
        self._thread = None


@dataclass
class SwapOps:
    """The injected side-effecting boundary (real subprocess/process ops live here)."""

    available_gb: Callable[[], float]            # \Memory\Available MBytes -> GB
    backend_alive: Callable[[], bool]            # is the OLD backend still resident?
    load_30b: Callable[[], bool]                 # start-llm -Force; True if launched ok
    wait_ready: Callable[[], bool]               # poll :8000/v3/models for coder-30b
    run_task: Callable[[dict], TaskOutcome]      # run-fleet ONE task -> its outcome
    cancel_requested: Callable[[], bool]         # cancel sentinel present?
    disarm_watchdog: Callable[[], None]          # rm server-should-run.txt (FIRST)
    stop_ovms: Callable[[], None]                # Stop-Process -Force -Name ovms
    write_report: Callable[[str, list], None]    # cumulative SUMMARY.txt for run_id
    restart_launcher: Callable[[], None]         # python -m launcher --winui
    backend_ready: Callable[[], bool]            # AO health probe after a relaunch
    signal_failure: Callable[[str], None]        # OUT-OF-BAND: status file + toast
    # Human-readable swap trail (#670), written to the SAME run-id-keyed progress log the AO
    # started (write_swap_progress under the same config root) so the operator can read what
    # happened during the swap after the box comes back. Default: discard (legacy tests).
    write_progress: Callable[[str], None] = _noop_progress
    # GPU-free probe (GiB) for the run-2 GPU wait-verify + instrumentation (#670). Returns
    # None when the device can't be read (best-effort on the Arc iGPU). On this shared-memory
    # iGPU "GPU-free" is read as system-RAM-free — the GPU's memory pool IS system RAM; a
    # discrete-GPU budget probe isn't reliable here (the Windows perf counters under-report).
    gpu_free_gb: Callable[[], "float | None"] = _noop_gpu_free
    # ---- #670 Problem 2 (teardown robustness) — all defaulted so legacy tests are byte-stable ----
    # Verify-the-stop: is OVMS still resident after stop_ovms? Default False == verify-satisfied
    # (the verify-stop branch is skipped), so the legacy exact-call-list tests stay green.
    ovms_alive: Callable[[], bool] = _noop_ovms_alive
    # The out-of-band budget watchdog asked the CODE loop to stop (per-run in-memory flag).
    stop_requested: Callable[[], bool] = _false
    # Teardown ENTRY: make any in-flight budget abort STRUCTURALLY INERT + clear the registered
    # child, under the holder's lock, so a late budget fire can never act during the restore.
    begin_teardown: Callable[[], None] = _noop_void
    # Hygiene: remove THIS run's leftover task worktree DIRS (runs AFTER the 14B restore).
    sweep_worktrees: Callable[[], None] = _noop_void
    # #688 Phase 3: ONE end-of-run VLM capture+critique pass over the built app, returning
    # ``{should_iterate, needs_work, feedback, layout_hard, capture_tier}``. The driver calls it
    # with the 30B already unloaded (GPU free). Fail-soft in the live impl; default no-ops.
    run_design_loop: Callable[[str, str, str], dict] = _noop_design_loop
    # #687 task 2: cross-model 14B code critic — one post-merge pass over the 30B's diff,
    # returning ``{should_iterate, verdict, findings}``. The live impl loads the 14B via
    # ``start-llm.ps1 -Force`` (internal model swap; the caller does NOT call stop_ovms).
    # Fail-soft; default no-ops so legacy tests are byte-stable and the driver is DORMANT-safe.
    run_critic: Callable[[str, str], dict] = _noop_critic
    # #687 task 2: whether the cross-model 14B critic is ACTIVE this run (BLARAI_ENABLE_CRITIC seen
    # by build_swap_ops in THIS — the swap_driver — process). Surfaced in the progress trail at the
    # critic phase so a DORMANT run is OBSERVABLE; the false-dormant trap is "the env was exported on
    # a different process than the launcher that spawns this driver". Default False = byte-stable.
    critic_enabled: bool = False


@dataclass(frozen=True)
class SwapDriverResult:
    """The driver's outcome (logging/tests). The user-facing report is surfaced by
    the RESTARTED AO via the reconciler + read_summary, not by the driver."""

    # complete | cancelled | budget-timeout | gate-abort | gpu-gate-abort | settle-timeout
    # | load-fail | error
    outcome: str
    loaded_30b: bool = False
    cancelled: bool = False
    restart_ok: bool = True
    available_gb: float = 0.0
    outcomes: list = field(default_factory=list)   # list[TaskOutcome]
    message: str = ""
    # #688 Phase 3: the LAST VLM design-critique result dict (loop signal, NOT a verdict), or None
    # when the design phase did not run (non-visual dispatch / nothing merged / cancelled / skipped).
    design_signal: "dict | None" = None
    # #687 task 2: the LAST 14B cross-model critic result dict (loop signal, NOT a verdict), or
    # None when the critic phase did not run (nothing merged / cancelled / skipped).
    critic_signal: "dict | None" = None


class SwapDriver:
    """Drives the swap state machine (design §2 steps 7-15)."""

    def __init__(
        self,
        *,
        run_id: str,
        session_id: str,
        tasks: list[dict],
        swap_state_path: Path,
        ops: SwapOps,
        gate_gb: float = 21.0,   # GiB (F1); matches start-llm's proven coder-30b gate ($needGB=21)
        settle_timeout_s: float = 60.0,
        settle_poll_s: float = 2.0,
        gpu_gate_gb: float = 15.0,            # 30B GPU need (GiB) — the wait-verify target (#670 run-2)
        gpu_settle_timeout_s: float = 15.0,   # how long to wait for the 14B's GPU to release
        gpu_settle_poll_s: float = 2.0,
        ovms_stop_timeout_s: float = 60.0,    # let a ~15 GB OVMS unload finish before crying wolf (#670 B2)
        ovms_stop_poll_s: float = 3.0,
        ovms_stop_retry_timeout_s: float = 15.0,  # shorter window after the forced Stop-Process
        restart_retries: int = 3,
        restart_backoff_s: float = 3.0,
        max_design_iterations: int = 2,  # #688 Phase 3: bound on critique->fix->re-critique laps
        max_critic_iterations: int = 2,  # #687 task 2: bound on critic->fix->re-critic laps
        sleep: Callable[[float], None] = time.sleep,
        budget_watchdog: "BudgetWatchdog | None" = None,
    ) -> None:
        self._run_id = run_id
        self._session_id = session_id
        self._tasks = list(tasks)
        self._path = swap_state_path
        self._ops = ops
        self._gate_gb = gate_gb
        self._settle_timeout_s = settle_timeout_s
        self._settle_poll_s = max(0.01, settle_poll_s)
        self._gpu_gate_gb = gpu_gate_gb
        self._gpu_settle_timeout_s = gpu_settle_timeout_s
        self._gpu_settle_poll_s = max(0.01, gpu_settle_poll_s)
        self._ovms_stop_timeout_s = ovms_stop_timeout_s
        self._ovms_stop_poll_s = max(0.01, ovms_stop_poll_s)
        self._ovms_stop_retry_timeout_s = ovms_stop_retry_timeout_s
        self._restart_retries = max(1, restart_retries)
        self._restart_backoff_s = restart_backoff_s
        self._max_design_iterations = max(1, max_design_iterations)
        self._max_critic_iterations = max(1, max_critic_iterations)
        self._sleep = sleep
        self._watchdog = budget_watchdog
        self._restart_ok = False
        self._design_signal: "dict | None" = None
        self._critic_signal: "dict | None" = None

    def _phase(self, phase: str, *, error: str = "") -> None:
        # Best-effort: a phase-write failure (e.g. a full disk) must never derail the
        # swap or, worse, the never-zero teardown — the write is the audit trail, not a
        # control dependency.
        try:
            ss.write_swap_state(
                ss.SwapState(run_id=self._run_id, session_id=self._session_id,
                             phase=phase, tasks=self._tasks, error=error),
                path=self._path,
            )
        except BaseException:  # noqa: BLE001 — a pure audit write must NEVER derail teardown
            pass

    def _progress(self, message: str) -> None:
        # Best-effort human-readable trail; never derails the swap or the never-zero teardown.
        try:
            self._ops.write_progress(message)
        except BaseException:  # noqa: BLE001 — a pure trail write must NEVER derail teardown
            pass

    def _guard(self, label: str, fn: Callable[[], None]) -> None:
        """Run a teardown step fail-soft, logging any failure to the progress trail. Catches
        ``BaseException`` (not just ``Exception``) — a step failure must NEVER mask the original
        exception nor skip the never-zero 14B restore."""
        try:
            fn()
        except BaseException as exc:  # noqa: BLE001 — catch EVERYTHING; the restore must proceed
            self._progress(f"Teardown step '{label}' failed: {exc!r} (continuing).")

    def _settle(self) -> bool:
        """Wait until the OLD backend process has fully RELEASED (step 7).

        Settle waits only for the PID to be GONE — the headroom decision is the
        GATE (step 8). Separating them means a "released but still too loaded" box
        yields a clear graceful gate-abort, not an opaque settle-timeout.
        """
        waited = 0.0
        while True:
            if not self._ops.backend_alive():
                return True
            if waited >= self._settle_timeout_s:
                return False
            self._sleep(self._settle_poll_s)
            waited += self._settle_poll_s

    def _await_gpu_clear(self) -> "float | None":
        """Poll GPU-free until it clears the 30B's need or the GPU settle window expires.

        Returns the last GPU-free reading (GiB), or None when the probe can't read the
        device (best-effort on the iGPU — the caller then proceeds on the graceful 14B
        unload). The wait-verify (vs a single snapshot) gives the 14B's GPU allocation time
        to drop after the step-aside before the 30B loads (#670 run-2)."""
        waited = 0.0
        while True:
            free = self._ops.gpu_free_gb()
            if free is None:
                return None
            if free >= self._gpu_gate_gb or waited >= self._gpu_settle_timeout_s:
                return free
            self._sleep(self._gpu_settle_poll_s)
            waited += self._gpu_settle_poll_s

    def run(self) -> SwapDriverResult:
        outcomes: list = []
        raised: BaseException | None = None
        outcome, loaded, cancelled, avail, message = ("error", False, False, 0.0, "swap error")
        self._restart_ok = False
        try:
            if self._watchdog is not None:
                # INSIDE the try — a start() failure (already fail-soft) still routes to teardown.
                self._watchdog.start()
            outcome, loaded, cancelled, avail, message = self._run_phases(outcomes)
        except Exception as exc:  # noqa: BLE001 — teardown must still restore the 14B
            raised = exc
            outcome, loaded, cancelled, avail, message = (
                "error", False, False, 0.0, f"swap error: {exc}"
            )
        except BaseException as exc:  # noqa: BLE001 — KeyboardInterrupt/SystemExit/async-injected
            raised = exc
            outcome, loaded, cancelled, avail, message = (
                "error", False, False, 0.0, f"swap aborted: {exc!r}"
            )
        finally:
            # NEVER-ZERO teardown — runs on EVERY path. Holds ONLY _teardown (no return/raise in
            # the finally — that would swallow `raised`).
            self._teardown(outcomes)

        if raised is not None:
            raise raised                            # re-raise AFTER the 14B is restored
        return SwapDriverResult(
            outcome=outcome, loaded_30b=loaded, cancelled=cancelled,
            restart_ok=self._restart_ok, available_gb=avail, outcomes=outcomes, message=message,
            design_signal=self._design_signal,
            critic_signal=self._critic_signal,
        )

    def _teardown(self, outcomes: list) -> None:
        """The never-zero teardown (steps 11-12). Every step is BaseException-guarded and the
        RESTART-AO 14B restore is UNCONDITIONALLY reached regardless of any earlier failure."""
        try:
            # (1) TEARDOWN ENTRY: make any in-flight budget abort STRUCTURALLY INERT + clear the
            #     registered child (under the holder's lock) BEFORE joining the watchdog thread,
            #     so a deadline that lands right now can never act during the restore (obligation A).
            self._guard("begin teardown (inert abort)", self._ops.begin_teardown)
            if self._watchdog is not None:
                self._guard("stop budget watchdog", self._watchdog.stop)
            # (2) cumulative report (run-fleet overwrote SUMMARY.txt per task)
            if outcomes:
                self._guard("write report",
                            lambda: self._ops.write_report(self._run_id, outcomes))
            # (3) UNLOAD-30B — disarm first, then stop, then VERIFY the stop took (fail-loud)
            self._progress("Stopping the 30B and swapping the 14B back…")
            self._phase(ss.PHASE_UNLOAD_30B)
            self._guard("disarm watchdog", self._ops.disarm_watchdog)
            self._guard("stop OVMS", self._ops.stop_ovms)
            self._verify_ovms_stopped()
        except BaseException:  # noqa: BLE001 — NOTHING above may stop the 14B restore below
            pass
        # (4) RESTART-AO — UNCONDITIONALLY reached; the 14B restore.
        self._phase(ss.PHASE_RESTART_AO)
        self._restart_ok = self._restart_with_retry()
        # (5) hygiene — AFTER the 14B is restored (OFF the critical path); bounded git, best-effort.
        self._progress("Cleaning up leftover task worktrees (parked branches kept)…")
        self._guard("sweep worktrees", self._ops.sweep_worktrees)

    def _poll_ovms_gone(self, timeout_s: float) -> bool:
        """Poll ``ovms_alive`` until it reports GONE or ``timeout_s`` elapses (#670 B2).

        Returns True as soon as OVMS is gone — so a slow ~15 GB unload that finishes within
        the window is NOT a failure (the false alarm this fixes: the old single check fired
        before the big-model unload completed). Returns False only if OVMS is STILL resident
        at the deadline. Mirrors ``_settle``: a ``waited``-accumulator on the injected
        ``self._sleep``, so it is unit-testable with no real sleep."""
        waited = 0.0
        while True:
            if not self._ops.ovms_alive():
                return True
            if waited >= timeout_s:
                return False
            self._sleep(self._ovms_stop_poll_s)
            waited += self._ovms_stop_poll_s

    def _verify_ovms_stopped(self) -> None:
        """Fail-loud verify-the-stop: confirm OVMS actually unloaded after stop_ovms. A ~15 GB
        unload is SLOWER than a single check, so POLL it (up to ``ovms_stop_timeout_s``) before
        escalating — only a genuinely-stuck OVMS, still resident after the poll AND a forced
        retry (+ a shorter post-retry poll), signals failure (#670 B2). The fail-loud MECHANISM
        and the signal text are unchanged; only the TIMING is given room.

        Best-effort: a verify failure must NEVER derail the rest of teardown. The never-zero
        14B restore runs unconditionally after this returns, on every path."""
        try:
            if self._poll_ovms_gone(self._ovms_stop_timeout_s):
                self._progress("OVMS confirmed stopped — the 30B is unloaded.")
                return
            self._progress("OVMS still resident after the unload window — escalating to a forced retry…")
            self._guard("stop OVMS (retry)", self._ops.stop_ovms)
            if self._poll_ovms_gone(self._ovms_stop_retry_timeout_s):
                self._progress("OVMS stopped on the forced retry — the 30B is unloaded.")
                return
            self._progress("OVMS STILL resident after a forced stop — the 30B may remain loaded; "
                           "the next boot's reconciler will converge it.")
            self._phase(ss.PHASE_UNLOAD_30B, error="OVMS did not stop")
            self._guard("signal OVMS-stop failure", lambda: self._ops.signal_failure(
                f"Model swap teardown: OVMS did not stop for run {self._run_id} — the 30B may "
                f"still be resident. Restart BlarAI; boot recovery will stop it."))
        except BaseException:  # noqa: BLE001 — verify is best-effort; never derail teardown
            pass

    def _budget_stop(self, avail: float) -> "tuple[str, bool, bool, float, str] | None":
        """If the out-of-band budget watchdog asked to stop, return a budget-timeout phase tuple;
        else None. Checked at every phase boundary BEFORE the CODE loop so a pre-CODE deadline
        aborts to teardown WITHOUT paying the expensive 30B load."""
        if self._ops.stop_requested():
            self._progress("The overall run budget elapsed before the coder started — "
                           "restoring the 14B.")
            return ("budget-timeout", False, False, avail,
                    "the overall run budget elapsed — restoring the 14B")
        return None

    def _run_phases(self, outcomes: list) -> tuple[str, bool, bool, float, str]:
        """Steps 7-10. Returns (outcome, loaded_30b, cancelled, available_gb, message).
        Never runs teardown — ``run`` does that on every path."""
        # 7 SETTLE
        self._phase(ss.PHASE_SETTLE)
        if not self._settle():
            self._progress("The old assistant didn't fully release in time — nothing was "
                           "swapped; restoring the 14B.")
            return ("settle-timeout", False, False, self._ops.available_gb(),
                    "the backend did not fully release in time — nothing was swapped; "
                    "restoring the assistant")
        stop = self._budget_stop(self._ops.available_gb())
        if stop is not None:
            return stop

        # 8 GATE — graceful + recoverable
        self._phase(ss.PHASE_GATE)
        avail = self._ops.available_gb()
        if avail < self._gate_gb:
            self._progress(f"Aborted safely: only {avail:.1f} GiB free (need "
                           f"{self._gate_gb:.0f} GiB) — restoring the 14B. Lean the box and retry.")
            return ("gate-abort", False, False, avail,
                    f"not enough headroom now ({avail:.1f} GiB < {self._gate_gb:.0f} GiB) "
                    "— free something or retry")
        stop = self._budget_stop(avail)
        if stop is not None:
            return stop

        # 8b GPU WAIT-VERIFY + instrumentation (#670 run-2): the step-aside watchdog
        # gracefully released the 14B's GPU/Level-Zero context (fix 2a); its memory (system
        # RAM on this iGPU) frees as the old launcher exits + the OS reclaims. POLL until
        # GPU-free clears the 30B's need — not a single snapshot that could abort while the
        # 14B is mid-release — and LOG it so the handoff is MEASURED, not luck. Best-effort:
        # None (unreadable probe) -> proceed on the graceful unload alone.
        gpu_free = self._await_gpu_clear()
        if gpu_free is None:
            self._progress("GPU-free unreadable on this device — proceeding on the graceful "
                           "14B unload (the swap's GPU guarantee).")
        elif gpu_free < self._gpu_gate_gb:
            self._progress(f"Aborted safely: GPU still busy ({gpu_free:.1f} GiB free < "
                           f"{self._gpu_gate_gb:.0f} needed for the 30B) — the 14B hasn't "
                           "released the GPU. Restoring the 14B.")
            return ("gpu-gate-abort", False, False, avail,
                    f"GPU not free for the 30B ({gpu_free:.1f} GiB < {self._gpu_gate_gb:.0f} GiB)"
                    " — the 14B's GPU context did not release in time")
        else:
            self._progress(f"GPU clear: {gpu_free:.1f} GiB free for the 30B "
                           f"(need {self._gpu_gate_gb:.0f}).")
        stop = self._budget_stop(avail)
        if stop is not None:
            return stop

        # 9 LOAD-30B
        self._progress("Headroom OK — loading the 30B coder model…")
        self._phase(ss.PHASE_LOAD_30B)
        if not self._ops.load_30b() or not self._ops.wait_ready():
            self._progress("The 30B coder failed to load — restoring the 14B.")
            return ("load-fail", True, False, avail,
                    "the coder model failed to load — restoring the assistant")

        # 10 CODE — per-task; cancel + out-of-band budget-stop checked at each task boundary
        self._progress("The coder fleet is running your approved tasks…")
        self._phase(ss.PHASE_CODE)
        cancelled = False
        stopped = False
        for task in self._tasks:
            if self._ops.cancel_requested():
                cancelled = True
                break
            if self._ops.stop_requested():
                stopped = True
                break
            # #670 FIX (b): never strand the 30B on an empty-workspace test grind. The
            # acceptance task is appended LAST (acceptance.compile_prompts) only for >=2
            # features, so every prior outcome here is a feature. If any preceding feature
            # parked (result != MERGED) there is no merged code to test — SKIP it rather
            # than run-fleet a worktree branched from a feature-less main. All-MERGED falls
            # through and runs it; an empty `outcomes` (no preceding features) runs it too.
            if task["task"] == ACCEPTANCE_TASK_SLUG:
                unmerged = [o.task for o in outcomes if o.result != "MERGED"]
                if unmerged:
                    outcomes.append(TaskOutcome(
                        task=task["task"], outcome="skipped", result="SKIPPED",
                        detail=("acceptance tests skipped: feature task(s) "
                                + ", ".join(unmerged)
                                + " parked/did not merge — no merged code to test"),
                    ))
                    self._progress(
                        "Skipping the acceptance tests — the feature work didn't merge ("
                        + ", ".join(unmerged) + "); there's nothing built to test."
                    )
                    continue
            outcomes.append(self._ops.run_task(task))
        if stopped:
            self._progress("The overall run budget elapsed — restoring the 14B.")
            return ("budget-timeout", True, False, avail,
                    "the overall run budget elapsed — restoring the 14B")
        # 10b CRITIC — the cross-model 14B code critic (#687 task 2). Runs post-merge BEFORE the
        # VLM design loop; the live impl swaps models via start-llm -Force (no stop_ovms call here).
        # Wholly fail-soft + cancel/budget-aware; can NEVER block teardown / the 14B restore.
        # No-ops on an unmerged run. With _noop_critic wired, byte-identical to today.
        self._critic_phase(outcomes)
        # 10c DESIGN — the end-of-run VLM design loop (#688 Phase 3). It runs AFTER the CODE loop
        # so it can unload the 30B and have the GPU free for the headless capture + the in-process
        # VLM (the per-task post-merge critique fails silently under 30B GPU contention). Fully
        # fail-soft + cancel/budget-aware; it can NEVER block this return / the teardown / the 14B
        # restore (the NEVER-ZERO discipline is absolute). No-ops on a non-visual / unmerged run.
        self._design_phase(outcomes)
        return (("cancelled" if cancelled else "complete"), True, cancelled, avail,
                ("dispatch cancelled after the current task" if cancelled
                 else "dispatch complete"))

    # ---- cross-model 14B code critic (#687 task 2) -----------------------------------

    def _critic_target(self, outcomes: list) -> "dict | None":
        """The first task that MERGED and has a non-empty ``repo`` — the 14B critic's target.

        Looks up the repo in ``self._tasks`` by matching the outcome's task slug. ``None``
        when nothing merged (no code diff to review)."""
        merged = {getattr(o, "task", "") for o in outcomes
                  if getattr(o, "result", "") == "MERGED"}
        for t in self._tasks:
            if t.get("task") in merged and t.get("repo"):
                return t
        return None

    @staticmethod
    def _critic_fix_prompt(findings: str) -> str:
        """The coder prompt for one critic fix lap — embeds the 14B reviewer's findings
        verbatim (the closed-loop step) and scopes the change to only the identified blockers."""
        return (
            "A code reviewer examined the merged diff and reported these blockers:\n\n"
            + str(findings or "").strip()
            + "\n\nFix each blocker. Keep all existing passing tests green and do not "
            "change behaviour beyond what the fixes require."
        )

    def _critic_phase(self, outcomes: list) -> None:
        """Cross-model 14B code critic (#687 task 2) — a BOUNDED critique -> fix -> re-critique.

        Calls ``run_critic(app_dir, base_branch)`` which in the live impl loads the 14B via
        ``start-llm.ps1 -Force`` (internal OVMS model swap) and returns
        ``{should_iterate, verdict, findings}``. On ``should_iterate=True`` below the cap:
        reload the 30B and run ONE coder fix task embedding the critic's findings, then
        re-critique with the 14B.

        KEY DIFFERENCE FROM ``_design_phase``: does NOT call ``stop_ovms()`` at any point.
        The live ``real_run_critic`` manages the model swap internally via ``-Force``; the
        teardown's ``stop_ovms`` handles cleanup on every exit path regardless.

        WHOLLY FAIL-SOFT + cancel/budget-aware: skipped on cancel/budget or nothing merged;
        any exception is swallowed so teardown / 14B restore are NEVER blocked. With the
        default ``_noop_critic``, this phase is byte-identical to not existing (DORMANT-safe)."""
        try:
            if self._ops.cancel_requested() or self._ops.stop_requested():
                return
            target = self._critic_target(outcomes)
            if target is None:
                return  # nothing merged — no code to review
            app_dir = str(target.get("repo", ""))
            base_branch = str(target.get("base_branch", "main"))

            # Make dormancy OBSERVABLE (the false-dormant trap: BLARAI_ENABLE_CRITIC exported on the
            # wrong process never reaches this driver, so a working build silently looks "dormant").
            self._progress(
                "14B code critic is ACTIVE on the merged diff (cross-model swap incoming)."
                if self._ops.critic_enabled
                else "14B code critic is DORMANT (BLARAI_ENABLE_CRITIC not seen by swap_driver) — "
                     "skipping the cross-model swap; this critic pass is a no-op."
            )

            for i in range(self._max_critic_iterations):
                if self._ops.cancel_requested() or self._ops.stop_requested():
                    break
                self._phase(ss.PHASE_CRITIC)
                self._progress("Running the 14B cross-model code critic on the merged diff...")
                result = self._ops.run_critic(app_dir, base_branch)
                if not isinstance(result, dict):
                    result = {}
                self._critic_signal = result
                if not result.get("should_iterate"):
                    break  # no blockers found -> done
                if i == self._max_critic_iterations - 1:
                    self._progress("Code-critic iteration cap reached.")
                    break
                # ---- FIX LAP: reload the 30B and apply the critic's findings ----
                self._progress("Reloading the coder to apply the code critic's findings...")
                if not (self._ops.load_30b() and self._ops.wait_ready()):
                    self._progress("Could not reload the coder for the critic fix -- "
                                   "stopping the code critic.")
                    break
                fix_task = {
                    "repo": app_dir,
                    "task": f"critic-fix-{i + 1}",
                    "base_branch": base_branch,
                    "prompt": self._critic_fix_prompt(str(result.get("findings", ""))),
                }
                outcomes.append(self._ops.run_task(fix_task))
                # loop back: the next lap re-critiques with the 14B (run_critic uses -Force).
        except BaseException:  # noqa: BLE001 — critic is best-effort; NEVER block teardown / the 14B
            self._progress("code critic skipped (non-blocking)")
            return

    # ---- end-of-run VLM design loop (#688 Phase 3) -----------------------------------

    def _design_target(self) -> "dict | None":
        """The first task eligible for a VLM design review: a visual SURFACE
        (:data:`_DESIGN_SURFACES`) carrying real visual criteria (a non-empty, non-``"[]"``
        ``visual_criteria_json``). ``None`` when no task qualifies (a non-visual dispatch)."""
        for task in self._tasks:
            surface = str(task.get("surface", ""))
            vcj = str(task.get("visual_criteria_json", "") or "").strip()
            if surface in _DESIGN_SURFACES and vcj and vcj != "[]":
                return task
        return None

    def _design_note(self, result: dict) -> str:
        """An operator-facing, SUGGESTION-only summary of one critique. The VLM verdict is a LOOP
        SIGNAL and the operator's eyeball is the final verdict, so this NEVER says done/verified/
        passed — it leads with the deterministic layout findings (when ``layout_hard``) then the VLM
        feedback, and always defers to the operator ("open the app and judge for yourself")."""
        layout_hard = bool(result.get("layout_hard"))
        needs_work = bool(result.get("needs_work"))
        feedback = " ".join(str(result.get("feedback", "") or "").split())  # flatten newlines
        parts: list[str] = []
        if layout_hard:
            parts.append("a deterministic layout check flagged hard issues")
        if feedback:
            parts.append(feedback)
        body = "; ".join(parts)
        if needs_work or layout_hard:
            if body:
                return (f"The design reviewer suggests changes: {body} "
                        "(open the app and judge for yourself).")
            return "The design reviewer suggests changes (open the app and judge for yourself)."
        if body:
            return f"The design reviewer noted: {body} (open the app and judge for yourself)."
        return ("The design reviewer found nothing obvious to change "
                "(open the app and judge for yourself).")

    @staticmethod
    def _design_fix_prompt(feedback: str) -> str:
        """The coder prompt for one design-fix lap — it EMBEDS the reviewer's feedback verbatim
        (the closed-loop "feed the critique back to the model" step) and scopes the change to the
        look, keeping existing behaviour + passing tests green."""
        return (
            "A design reviewer looked at the BUILT, running app and reported:\n\n"
            + str(feedback or "").strip()
            + "\n\nApply these visual / layout fixes so the app matches the intended look. "
            "Change ONLY what's needed for the design -- keep all existing behaviour and "
            "all passing tests green."
        )

    def _design_phase(self, outcomes: list) -> None:
        """The end-of-run VLM design loop (#688 Phase 3) — a BOUNDED critique -> fix -> re-critique.

        Each lap UNLOADS the 30B (GPU free for the headless capture + the in-process VLM), runs one
        capture+critique pass, and — if the reviewer says iterate and the cap is not hit — RELOADS
        the 30B and runs ONE coder fix task whose prompt embeds the critique feedback, then loops to
        re-capture. The model swap each lap is intentional (a working process beats a contended,
        silently-failing one). The VLM ``should_iterate`` DRIVES the loop but is NEVER the verdict —
        the operator's eyeball is; every line is phrased as the reviewer's suggestion.

        WHOLLY FAIL-SOFT + cancel/budget-aware: skipped entirely on cancel/budget or a non-visual /
        unmerged run, and any exception is swallowed (logged to the trail) so the return / teardown /
        14B restore are NEVER blocked. On exit the 30B is left unloaded so the teardown stop is a
        harmless no-op."""
        try:
            # Cancel / budget: skip the whole phase (straight to teardown), no model churn.
            if self._ops.cancel_requested() or self._ops.stop_requested():
                return
            target = self._design_target()
            if target is None:
                return  # non-visual dispatch — nothing to look at
            if not any(getattr(o, "result", "") == "MERGED" for o in outcomes):
                return  # nothing merged — no built app to review
            app_dir = str(target.get("repo", ""))
            goal = str(target.get("goal", ""))
            vcj = str(target.get("visual_criteria_json", "[]"))
            surface = str(target.get("surface", ""))

            for i in range(self._max_design_iterations):
                if self._ops.cancel_requested() or self._ops.stop_requested():
                    break  # a cancel/budget mid-review -> stop and restore
                self._phase(ss.PHASE_DESIGN)
                self._progress("Reviewing the finished design -- swapping the coder out "
                               "for the vision model...")
                self._ops.stop_ovms()  # unload the 30B: GPU free for capture + the in-process VLM
                result = self._ops.run_design_loop(app_dir, goal, vcj)
                if not isinstance(result, dict):
                    result = {}
                self._design_signal = result
                self._progress(self._design_note(result))
                if not result.get("should_iterate"):
                    break  # good enough / no actionable feedback -> the operator judges the look
                if i == self._max_design_iterations - 1:
                    self._progress("Design-review iteration cap reached -- the operator judges "
                                   "the final look.")
                    break
                # ---- FEED BACK + FIX (the closed loop): reload the coder, apply the critique ----
                self._progress("Reloading the coder to apply the design fixes...")
                if not (self._ops.load_30b() and self._ops.wait_ready()):
                    self._progress("Could not reload the coder for the design fix -- "
                                   "stopping the design review.")
                    break
                fix_task = {
                    "repo": app_dir,
                    "task": f"design-fix-{i + 1}",
                    "surface": surface,
                    "visual_criteria_json": vcj,
                    "goal": goal,
                    "prompt": self._design_fix_prompt(str(result.get("feedback", ""))),
                }
                outcomes.append(self._ops.run_task(fix_task))
                # loop back: the next lap stops the 30B, re-captures, and re-critiques.

            # Leave the 30B unloaded so the teardown's stop_ovms is a harmless no-op.
            self._ops.stop_ovms()
        except BaseException:  # noqa: BLE001 — design is best-effort; NEVER block teardown / the 14B
            self._progress("design review skipped (non-blocking)")
            return

    def _restart_with_retry(self) -> bool:
        """Relaunch the backend up to N times, proving it actually came up (§2.3)."""
        for attempt in range(1, self._restart_retries + 1):
            try:
                self._ops.restart_launcher()
            except BaseException:  # noqa: BLE001 — a restore-internal error OR signal is "this attempt
                pass                # failed, retry"; it must NEVER escape _teardown and mask `raised` (#670 P2)
            try:
                came_up = self._ops.backend_ready()
            except BaseException:  # noqa: BLE001 — a probe failure OR signal means "not up yet", retry
                came_up = False
            if came_up:
                self._progress("BlarAI's 14B is back — read the run with /dispatch status.")
                return True  # the 14B is back; the restarted reconciler reports
            if attempt < self._restart_retries:
                try:
                    self._sleep(self._restart_backoff_s)
                except BaseException:  # noqa: BLE001 — a signal must NOT truncate the 14B restore
                    pass
        # Persistent failure: zero models, but LOUD + one-action recoverable (§2.3).
        self._progress("The 14B did NOT restart after retries — restart BlarAI to recover.")
        self._phase(ss.PHASE_FAILED, error="backend did not restart after retries")
        try:
            self._ops.signal_failure(
                f"Model swap failed — BlarAI's assistant did not restart after "
                f"{self._restart_retries} tries. Run {self._run_id} is done; "
                f"restart BlarAI to recover."
            )
        except BaseException:  # noqa: BLE001 — the loud signal is best-effort; never raise out
            pass
        return False
