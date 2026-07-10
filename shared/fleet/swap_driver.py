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

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable
from pathlib import Path

from shared.fleet import context_pack as cp
from shared.fleet import plan_graph as pg
from shared.fleet import swap_state as ss
from shared.fleet.acceptance import ACCEPTANCE_TASK_SLUG
from shared.fleet.decompose import build_failure_evidence
from shared.fleet.dispatch import TaskOutcome, slugify_task


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


def _noop_critic(_app_dir: str, _base_branch: str, _base_sha: str = "") -> dict:
    """Default ``SwapOps.run_critic`` — 14B cross-model critic unavailable, so the critic phase
    no-ops (a single pass that reports nothing actionable). Legacy tests construct ``SwapOps``
    without it; the live ``build_swap_ops`` wires the real critic run (#687 task 2).
    ``_base_sha`` (#693): main's pre-dispatch HEAD, "" when unrecorded."""
    return {"should_iterate": False, "verdict": "UNCLEAR", "findings": ""}


#: Surfaces whose built app can be screenshotted + judged by the VLM design loop (#688 Phase 3).
#: A non-visual surface (command-line / library / automation / unknown) has nothing to look at.
_DESIGN_SURFACES = frozenset({"web", "desktop-gui"})


# ---- M2 plan-graph seam defaults (W3-W6, #740) — all no-op ⇒ legacy byte-stable ------


def _noop_repo_head(_repo: str) -> str:
    """Default ``SwapOps.repo_head`` — HEAD unreadable (''), so as-built deltas degrade
    to contract-only context packs (the contract is the pack's primary content)."""
    return ""


def _noop_dep_delta(_repo: str, _base: str, _merge: str) -> dict:
    """Default ``SwapOps.dep_delta`` — no as-built delta (contract-only packs)."""
    return {}


def _noop_log_pack(_task_id: str, _pack: str) -> None:
    """Default ``SwapOps.log_pack`` — discards the audit copy (tests that don't care)."""


def _noop_wave_gate(_repo: str) -> dict:
    """Default ``SwapOps.run_wave_gate`` — gate unavailable. ``ok=None`` means COULD NOT
    RUN (recorded honestly as unverified, mirroring the fleet's 'none' posture), which is
    NEVER treated as a pass and never as a failure."""
    return {"ok": None, "evidence": "wave gate unavailable"}


def _noop_job_oracle(_repo: str, _rel_path: str) -> dict:
    """Default ``SwapOps.run_job_oracle`` — oracle unavailable ⇒ an honest ``not-run``
    (the job then CANNOT report done-with-oracle-green; never an implied pass)."""
    return {"status": "not-run", "evidence": "job oracle unavailable"}


def _noop_seed_job_oracle(_repo: str, _rel_path: str) -> dict:
    """Default ``SwapOps.seed_job_oracle`` (#748) — seeding unavailable ⇒ the coder
    builds without seeing the job spec (exactly the pre-seeding behavior) and the
    oracle still grades at the end. Honest ``ok=False``, never an implied seed."""
    return {"ok": False, "evidence": "oracle seeding unavailable"}


def _noop_redecompose(_task: dict, _evidence: str) -> "list[dict] | None":
    """Default ``SwapOps.redecompose`` — no re-planner available ⇒ ``None`` (the failed
    task parks and its dependents skip — today's honest behavior). The live model
    transport for the mid-swap re-decompose is a W8 wiring step (the 14B/30B residency
    choreography); the DETERMINISTIC policy (budgets, replace-on-strict-improvement,
    ruler re-validation) is fully built + tested against this seam."""
    return None


def _noop_guest_oracle(_repo: str, _rel_path: str) -> dict:
    """Default ``SwapOps.run_guest_oracle`` (#744) — no guest executor available ⇒ an
    honest ``not-run`` (an unavailable isolation certificate is recorded, never a
    silent pass).  The driver only reaches this seam when
    ``[fleet_dispatch].guest_oracle_enabled`` is true; the live wiring supplies the
    real (still transport-dormant) pipeline."""
    return {"status": "not-run", "reason": "guest-oracle-unavailable",
            "evidence": "guest oracle executor unavailable"}


def _noop_write_guest_oracle(_block: dict) -> None:
    """Default ``SwapOps.write_guest_oracle`` (#744) — discards the advisory evidence
    block (tests that don't care; legacy runs never reach it)."""


def _noop_write_scorecard(_scorecard: dict) -> None:
    """Default ``SwapOps.write_scorecard`` — discards (legacy runs emit no scorecard)."""


def _noop_write_job_summary(_text: str) -> None:
    """Default ``SwapOps.write_job_summary`` — discards (legacy runs emit no summary)."""


def _noop_relaunch_in_flight() -> bool:
    """Default ``SwapOps.relaunch_in_flight`` — unknown (False), so every retry attempt
    respawns exactly as before the RESTART-AO hardening (legacy byte-stable)."""
    return False


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
    # returning ``{should_iterate, verdict, findings}``. Called as (app_dir, base_branch,
    # base_sha) — base_sha (#693) is main's pre-dispatch HEAD ("" -> the script falls back
    # to Resolve-CriticRange). The live impl loads the 14B via ``start-llm.ps1 -Force``
    # (internal model swap; the caller does NOT call stop_ovms).
    # Fail-soft; default no-ops so legacy tests are byte-stable and the driver is DORMANT-safe.
    run_critic: Callable[[str, str, str], dict] = _noop_critic
    # #687 task 2: whether the cross-model 14B critic is ACTIVE this run (BLARAI_ENABLE_CRITIC seen
    # by build_swap_ops in THIS — the swap_driver — process). Surfaced in the progress trail at the
    # critic phase so a DORMANT run is OBSERVABLE; the false-dormant trap is "the env was exported on
    # a different process than the launcher that spawns this driver". Default False = byte-stable.
    critic_enabled: bool = False
    # ---- M2 plan-graph seams (W3-W6, #740) — all defaulted no-op so plan_graph=false and
    # every legacy caller/test are byte-stable. EVERY external effect of the plan-graph
    # path (git reads, gate runs, oracle runs, audit writes) lives behind these, so the
    # §9.2 simulator can drive the whole wave loop model-free (plan §4.3 hard requirement).
    # git rev-parse HEAD of a repo ('' when unreadable) — brackets each task's merge.
    repo_head: Callable[[str], str] = _noop_repo_head
    # (repo, base_ref, merge_ref) -> {"files": [...], "signatures": [...]} — the as-built
    # delta feeding a dependent's context pack (W3). {} degrades to contract-only.
    dep_delta: Callable[[str, str, str], dict] = _noop_dep_delta
    # (task_id, pack) — verbatim per-task pack audit log (plan §4.4 / §10 S2).
    log_pack: Callable[[str, str], None] = _noop_log_pack
    # repo -> {"ok": True|False|None, "evidence": str} — the per-wave integration gate on
    # the INTEGRATED target-repo main (W4). None = could-not-run (honest, non-blocking).
    run_wave_gate: Callable[[str], dict] = _noop_wave_gate
    # (repo, oracle_rel_path) -> {"status": "passed"|"failed"|"not-run", "evidence": str}
    # — the job-level oracle on the final integrated tree (W4; restore-before-grade).
    run_job_oracle: Callable[[str, str], dict] = _noop_job_oracle
    seed_job_oracle: Callable[[str, str], dict] = _noop_seed_job_oracle
    # (fleet_task, evidence) -> replacement children or None — the ONE evidence-fed
    # re-decompose of a consistently-failing task (W5; budgets enforced by the driver).
    redecompose: Callable[[dict, str], "list[dict] | None"] = _noop_redecompose
    # The machine-readable job scorecard (W6, plan §4.3/§9.4) — persisted at REPORT time.
    write_scorecard: Callable[[dict], None] = _noop_write_scorecard
    # The human JOB_SUMMARY (W6) — plan-level + per-wave + per-task with evidence pointers.
    write_job_summary: Callable[[str], None] = _noop_write_job_summary
    # RESTART-AO hardening (routed-in W7, risk R5): is the PREVIOUSLY-spawned relaunch
    # still alive (starting or up)? True ⇒ the retry loop WAITS instead of stacking a
    # second launcher (which would trip the instance lock and burn the attempt). The
    # default False preserves the legacy spawn-every-attempt behavior byte-identically.
    relaunch_in_flight: Callable[[], bool] = _noop_relaunch_in_flight
    # ---- #744 guest-certified oracle (DORMANT) — both defaulted so every legacy
    # caller/test is byte-stable; the driver NEVER touches either seam unless
    # guest_oracle_enabled is true (the [fleet_dispatch].guest_oracle_enabled knob).
    # (repo, oracle_rel_path) -> {"status": "passed"|"failed"|"not-run", "reason",
    # "evidence"} — ONE in-guest re-run of the job oracle per JOB, in the RAM-free
    # window (after UNLOAD-30B, before RESTART-AO). ADVISORY isolation certificate:
    # never a verdict input.
    run_guest_oracle: Callable[[str, str], dict] = _noop_guest_oracle
    # Persist the advisory guest_oracle evidence block beside the scorecard
    # (guest-oracle.json in the run dir; guarded audit write, never on the
    # 14B-restore critical path).
    write_guest_oracle: Callable[[dict], None] = _noop_write_guest_oracle


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
    # #744: the advisory guest-oracle certificate block, or None when the guest phase
    # did not run (knob off / flat mode / nothing merged / cancelled). NEVER a verdict
    # input — evidence attached to the job record only.
    guest_oracle_signal: "dict | None" = None


# ---------------------------------------------------------------------------
# M2 W6 (#740) — the job verdict, machine scorecard, and human JOB_SUMMARY (pure)
# ---------------------------------------------------------------------------

#: The pinned DRIVER scorecard schema id. The battery runner's
#: ``adopt_driver_scorecard`` (Lane V, ``tools/dispatch_harness/battery.py``) reads
#: this file, OVERLAYS the battery context (its own ``battery-scorecard/v1`` schema
#: id, job_id, card_path, timestamps, versions), validates, and cross-checks — so
#: this dict must be ADOPTABLE: shared field names/types/vocabularies match
#: ``tools/dispatch_harness/scorecard.py`` exactly; the driver-only extras
#: (tasks/waves/job_acceptance/goal/…) are ignored by its ``from_dict`` by design.
#: Structural throughout (§10 S6): verdicts, tags, and evidence POINTERS — never logs.
SCORECARD_SCHEMA = "m2-scorecard/v1"

#: §9.4 verdict taxonomy (vocabulary-identical to ``scorecard.VERDICTS`` — the
#: adoption contract). FALSE-DONE is in the enum because the schema names it, but
#: this module can never EMIT it — a FALSE-DONE is by definition a defect an external
#: audit (the runner's cross-check) finds; the honest self-reports are the other four.
VERDICT_GREEN = "GREEN"
VERDICT_PARKED_HONEST = "PARKED-HONEST"  # refused with evidence — a verification success
VERDICT_FALSE_DONE = "FALSE-DONE"        # never self-emitted
VERDICT_STALLED = "STALLED"              # could not run / had to be killed / could not be scored
VERDICT_RECOVERED = "RECOVERED"          # crash path fired and recovery worked (boot-side)

#: §9.4 failure-attribution tags — REQUIRED for every non-GREEN (the adoption
#: validator enforces it), '' only for GREEN.
ATTRIBUTION_PLAN = "PLAN"
ATTRIBUTION_BUILD = "BUILD"
ATTRIBUTION_VERIFY = "VERIFY"
ATTRIBUTION_HARNESS = "HARNESS"


def compute_job_verdict(
    plan: "pg.JobPlan",
    *,
    cancelled: bool,
    stopped: bool,
    wave_gates: list[dict],
    degraded: bool = False,
) -> tuple[str, str]:
    """``(verdict, attribution)`` per the §9.4 taxonomy — pure, evidence-driven,
    vocabulary-aligned with Lane V's ``scorecard.py`` glosses (the adoption contract).

    GREEN requires ALL of: not cancelled/stopped, every task ``merged``, no failed
    wave gate, and the job oracle ``passed`` (the "job reports done ONLY when the job
    oracle passes" rule as a computation — an unrun oracle can never be GREEN).

    PARKED-HONEST = the system refused with evidence (a verification SUCCESS): work
    parked/blocked, a gate or the oracle FAILED on built code, or the operator
    cancelled (attributed HARNESS — the run was externally stopped; the scorecard's
    ``interventions`` counter carries the operator signal).

    STALLED = could not run / had to be killed / could not be scored: the budget
    watchdog fired (HARNESS), the run died mid-task or never started (HARNESS), or
    everything merged but the oracle never ran — merged-but-unverifiable is exactly
    the FALSE-DONE class, so it must never be GREEN and is honestly STALLED (VERIFY:
    the oracle was missing, not the build)."""
    if stopped:
        return (VERDICT_STALLED, ATTRIBUTION_HARNESS)
    statuses = [t.status for t in plan.tasks]
    all_merged = bool(statuses) and all(s == pg.STATUS_MERGED for s in statuses)
    gates_failed = any(g.get("status") == "failed" for g in wave_gates)
    acc = plan.job_acceptance.status
    if not cancelled and all_merged and not gates_failed and acc == "passed":
        return (VERDICT_GREEN, "")
    if cancelled:
        return (VERDICT_PARKED_HONEST, ATTRIBUTION_HARNESS)
    if any(s in (pg.STATUS_PARKED, pg.STATUS_BLOCKED) for s in statuses):
        return (VERDICT_PARKED_HONEST, ATTRIBUTION_BUILD)
    if gates_failed or acc == "failed":
        return (VERDICT_PARKED_HONEST, ATTRIBUTION_BUILD)
    if all_merged and acc == "not-run":
        return (VERDICT_STALLED, ATTRIBUTION_VERIFY)
    if any(s == pg.STATUS_BUILDING for s in statuses):
        # A task frozen mid-build means the RUN died around it (crash path) — the
        # coder never returned a RESULT: could-not-be-scored, a harness fault.
        return (VERDICT_STALLED, ATTRIBUTION_HARNESS)
    if statuses and all(s == pg.STATUS_PENDING for s in statuses):
        # Nothing ever started: a settle-timeout / headroom gate-abort / load-fail
        # refused the swap before the first task — could-not-run, environmental.
        return (VERDICT_STALLED, ATTRIBUTION_HARNESS)
    if degraded and not all_merged:
        return (VERDICT_PARKED_HONEST, ATTRIBUTION_PLAN)
    return (VERDICT_STALLED, ATTRIBUTION_VERIFY)


def build_scorecard(
    plan: "pg.JobPlan",
    *,
    run_id: str,
    outcomes: list,
    wave_gates: list[dict],
    job_evidence: str,
    cancelled: bool,
    stopped: bool,
    degraded: bool,
    packs_consumed: int,
    wall_clock_s: float,
    evidence_paths: "dict | None" = None,
) -> dict:
    """The machine-readable DRIVER job scorecard (plan §4.3/§9.4; §10 S6-structural),
    shaped to be ADOPTABLE by the battery runner's ``adopt_driver_scorecard``:

      * shared fields match ``tools/dispatch_harness/scorecard.py`` types/vocab
        exactly (``samples_consumed`` uses its ``-1 == not instrumented`` convention
        — best-of-N counts are fleet-internal, honestly not measured here; a
        non-GREEN always carries a valid attribution; ``interventions`` carries the
        operator-cancel signal);
      * ``evidence`` holds single-line POINTERS + ``oracle_status`` (the runner's
        FALSE-DONE cross-check hook: passed/failed/not-run/unknown — never a log);
      * the driver-only extras (goal/tasks/waves/job_acceptance/…) are ignored by
        the adopter's ``from_dict`` by design and serve the human JOB_SUMMARY."""
    verdict, attribution = compute_job_verdict(
        plan, cancelled=cancelled, stopped=stopped, wave_gates=wave_gates,
        degraded=degraded,
    )
    by_task = {getattr(o, "task", ""): o for o in outcomes}
    tasks = []
    for t in plan.tasks:
        o = by_task.get(t.id)
        tasks.append({
            "id": t.id,
            "status": t.status,
            "result": getattr(o, "result", "") if o is not None else "",
            "detail": getattr(o, "detail", "") if o is not None else "",
        })
    acc_status = plan.job_acceptance.status
    oracle_status = acc_status if acc_status in ("passed", "failed", "not-run") else "unknown"
    evidence = {k: str(v) for k, v in (evidence_paths or {}).items()}
    evidence["oracle_status"] = oracle_status
    notes = []
    if cancelled:
        notes.append("cancelled by the operator mid-run")
    if degraded:
        notes.append("plan degraded to the linear chain (logged)")
    return {
        "schema": SCORECARD_SCHEMA,
        "run_id": run_id,
        "plan_id": plan.plan_id,
        "goal": plan.goal,
        "repo": plan.repo,
        "verdict": verdict,
        "attribution": attribution,
        "cancelled": bool(cancelled),
        "degraded": bool(degraded),
        "wall_clock_s": round(float(wall_clock_s), 1),
        "tasks": tasks,
        "waves": list(wave_gates),
        "job_acceptance": {
            "status": acc_status,
            "oracle_path": plan.job_acceptance.oracle_path,
            "evidence": job_evidence,
        },
        "packs_consumed": int(packs_consumed),
        "samples_consumed": -1,
        "interventions": 1 if cancelled else 0,
        "redecompose_spent": plan.redecompose_budget.spent,
        "not_measured": ["samples_consumed"],
        "notes": "; ".join(notes),
        "evidence": evidence,
    }


def compute_flat_verdict(
    outcomes: list,
    *,
    cancelled: bool,
    stopped: bool,
) -> tuple[str, str]:
    """``(verdict, attribution)`` for the LEGACY FLAT queue (no ``JobPlan``) — the
    plan-less mirror of :func:`compute_job_verdict`, same §9.4 philosophy, and the
    same load-bearing safety property: **flat mode can NEVER return GREEN.**

    A flat run has no job oracle to grade the integrated whole, so 'done' is
    unprovable — every all-merged flat run is honestly STALLED (VERIFY: the oracle was
    missing, not the build), exactly the merged-but-unverifiable FALSE-DONE class that
    :func:`compute_job_verdict` guards (its lines 433-434). ``outcomes`` is the list of
    ``dispatch.TaskOutcome``; the per-task ``.result`` vocab is
    ``dispatch._classify_result`` + the acceptance SKIP — MERGED / PARKED / BLOCKED /
    NOTHING / UNKNOWN / TIMEOUT / SKIPPED (#757) — so ANY non-MERGED outcome is an honest
    RED (a task parked, failed its gate, timed out, or was skipped-because-unmerged)."""
    if stopped:
        return (VERDICT_STALLED, ATTRIBUTION_HARNESS)
    if not outcomes:
        # Nothing ran (a settle/gate/load abort before the first task): could-not-run.
        return (VERDICT_STALLED, ATTRIBUTION_HARNESS)
    if cancelled:
        return (VERDICT_PARKED_HONEST, ATTRIBUTION_HARNESS)
    if any(getattr(o, "result", "") != "MERGED" for o in outcomes):
        # A task parked / failed its gate / was skipped-because-unmerged — honest RED.
        return (VERDICT_PARKED_HONEST, ATTRIBUTION_BUILD)
    # Everything merged, but flat mode ran NO job oracle: merged-but-unverifiable is
    # exactly the FALSE-DONE class, so it must NEVER be GREEN — honestly STALLED
    # (VERIFY: the oracle was missing, not the build). This is the anti-false-done lock.
    return (VERDICT_STALLED, ATTRIBUTION_VERIFY)


def build_flat_scorecard(
    outcomes: list,
    *,
    run_id: str,
    repo: str,
    goal: str,
    wall_clock_s: float,
    cancelled: bool,
    stopped: bool,
    degraded: bool,
) -> dict:
    """The DRIVER job scorecard for the LEGACY FLAT queue (no ``JobPlan``) — the
    plan-less sibling of :func:`build_scorecard`, the SAME ``m2-scorecard/v1`` shape and
    keys so the battery runner's ``adopt_driver_scorecard`` adopts it identically (F4,
    #752 — closes the 'no driver scorecard ⇒ synthesize STALLED [HARNESS]' seam).

    Derived purely from the per-task ``outcomes`` (no plan, no waves, no job oracle):
    ``waves=[]`` and ``job_acceptance``/``evidence.oracle_status`` are an honest
    ``not-run`` (flat mode grades no integrated whole). ``verdict``/``attribution`` come
    from :func:`compute_flat_verdict` — never GREEN by construction (§9 zero-FALSE-DONE:
    a flat run has no oracle to prove the whole). Every string value is single-line so
    the adopter's ``validate`` (``^[^\\r\\n]*$``) accepts it."""
    verdict, attribution = compute_flat_verdict(
        outcomes, cancelled=cancelled, stopped=stopped,
    )
    tasks = [{
        "id": getattr(o, "task", ""),
        "status": "",
        "result": getattr(o, "result", ""),
        "detail": getattr(o, "detail", ""),
    } for o in outcomes]
    return {
        "schema": SCORECARD_SCHEMA,
        "run_id": run_id,
        "plan_id": "",
        "goal": goal,
        "repo": repo,
        "verdict": verdict,
        "attribution": attribution,
        "cancelled": bool(cancelled),
        "degraded": bool(degraded),
        "wall_clock_s": round(float(wall_clock_s), 1),
        "tasks": tasks,
        "waves": [],
        "job_acceptance": {"status": "not-run", "oracle_path": "", "evidence": ""},
        "packs_consumed": 0,
        "samples_consumed": -1,
        "interventions": 1 if cancelled else 0,
        "redecompose_spent": 0,
        "not_measured": ["samples_consumed"],
        "notes": ("flat-queue mode (no plan-graph): job-level verdict computed from "
                  "per-task outcomes; no job oracle ran"),
        "evidence": {"oracle_status": "not-run"},
    }


def render_job_summary(scorecard: dict) -> str:
    """The human JOB_SUMMARY (W6): plan-level verdict, per-wave gate outcomes, per-task
    statuses, and the failure sections (W5) — with verification-evidence pointers.

    Deliberately avoids the ``- <task>: <outcome>`` + ``RESULT:`` line shapes so
    ``dispatch.parse_summary`` (which scans SUMMARY.txt) can never mis-parse this file
    if the two are ever concatenated."""
    lines = [
        f"JOB {scorecard.get('run_id', '')} — {scorecard.get('goal', '') or '(no goal)'}",
        f"verdict: {scorecard.get('verdict', '')}"
        + (f" (attribution: {scorecard.get('attribution')})" if scorecard.get("attribution") else ""),
        f"repo: {scorecard.get('repo', '')}",
        "",
        "Tasks:",
    ]
    for t in scorecard.get("tasks", []):
        detail = f" | {t['detail']}" if t.get("detail") else ""
        lines.append(f"  [{t.get('status', '?')}] {t.get('id', '?')}{detail}")
    waves = scorecard.get("waves", [])
    if waves:
        lines += ["", "Wave integration gates:"]
        for g in waves:
            lines.append(
                f"  wave {g.get('wave', '?')}: {g.get('status', '?')} | {g.get('evidence', '')}"
            )
    acc = scorecard.get("job_acceptance", {})
    lines += [
        "",
        "Job acceptance (the finish line):",
        f"  status: {acc.get('status', '?')} | oracle: {acc.get('oracle_path', '')}",
    ]
    if acc.get("evidence"):
        lines.append(f"  evidence: {acc['evidence']}")
    failures = [
        t for t in scorecard.get("tasks", [])
        if t.get("status") in (pg.STATUS_PARKED, pg.STATUS_BLOCKED, pg.STATUS_SKIPPED)
    ]
    if failures:
        lines += ["", "Failure sections (what did not ship, and why):"]
        for t in failures:
            lines.append(f"  {t.get('id', '?')}: {t.get('status', '?')}"
                         + (f" | {t['detail']}" if t.get("detail") else ""))
    if scorecard.get("redecompose_spent"):
        lines.append(f"  re-decompositions spent: {scorecard['redecompose_spent']}")
    if scorecard.get("degraded"):
        lines.append("  note: the dependency graph DEGRADED to the serial chain (logged, not hidden).")
    ev = scorecard.get("evidence", {})
    if ev:
        lines += ["", "Evidence pointers:"]
        for name, path in ev.items():
            lines.append(f"  {name}: {path}")
    return "\n".join(lines) + "\n"


# ---- SwapDriver timing defaults (#767 item 2 — the literals named as constants) ------
# Production (``run_swap_from_spec``) constructs the driver WITHOUT overriding these, so
# the defaults ARE the live values; naming them lets the timeout registry's drift locks
# bind them by import (shared/timeout_registry.py). Tests keep passing tiny overrides.

#: Step-7 settle: how long to wait for the OLD backend's PID to be GONE before a
#: settle-timeout abort (design value, #670; never bitten). Settle waits ONLY for the
#: PID — the headroom GATE (step 8) owns the "released but still too loaded" case.
SETTLE_TIMEOUT_S = 60.0
#: Step-8 GPU wait-verify: how long to wait for the 14B's GPU (shared-RAM) allocation to
#: release before the 30B loads (#670 run-2 — a single snapshot raced the release; the
#: wait-verify replaced it). On expiry the driver proceeds on the graceful 14B unload.
GPU_SETTLE_TIMEOUT_S = 15.0
#: Teardown verify-the-stop, first window: let a ~15 GB OVMS unload finish before crying
#: wolf (#670 B2 — a too-short window manufactures a phantom "still alive" and a needless
#: forced Stop-Process while a large unload is legitimately finishing).
OVMS_STOP_TIMEOUT_S = 60.0
#: Teardown verify-the-stop, retry window: the shorter re-verify after the forced
#: Stop-Process (#670 B2 sibling) — a force-killed process should vanish fast, and the
#: teardown must keep moving toward the 14B restore.
OVMS_STOP_RETRY_TIMEOUT_S = 15.0


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
        gate_gb: float = 20.0,   # GiB (F1); matches start-llm's coder-30b gate ($needGB=20, #777 measured 2026-07-09)
        settle_timeout_s: float = SETTLE_TIMEOUT_S,
        settle_poll_s: float = 2.0,
        gpu_gate_gb: float = 15.0,            # 30B GPU need (GiB) — the wait-verify target (#670 run-2)
        gpu_settle_timeout_s: float = GPU_SETTLE_TIMEOUT_S,
        gpu_settle_poll_s: float = 2.0,
        ovms_stop_timeout_s: float = OVMS_STOP_TIMEOUT_S,
        ovms_stop_poll_s: float = 3.0,
        ovms_stop_retry_timeout_s: float = OVMS_STOP_RETRY_TIMEOUT_S,
        restart_retries: int = 3,
        restart_backoff_s: float = 3.0,
        max_design_iterations: int = 2,  # #688 Phase 3: bound on critique->fix->re-critique laps
        max_critic_iterations: int = 2,  # #687 task 2: bound on critic->fix->re-critic laps
        sleep: Callable[[float], None] = time.sleep,
        budget_watchdog: "BudgetWatchdog | None" = None,
        # ---- M2 plan-graph mode (W3-W6, #740). plan=None (the default) is the legacy flat
        # queue, byte-identical. A validated JobPlan switches the CODE phase to the wave
        # scheduler; plan_store (an injected seam — pure file I/O on a caller-chosen path)
        # persists every evidence-gated transition; restart_backoff_cap_s bounds the
        # RESTART-AO escalating backoff (routed-in W7 hardening).
        plan: "pg.JobPlan | None" = None,
        plan_store: "pg.PlanStore | None" = None,
        plan_degraded: bool = False,
        restart_backoff_cap_s: float = 30.0,
        # #744 guest-certified oracle. False (the default, and the
        # [fleet_dispatch].guest_oracle_enabled shipped value) means the driver NEVER
        # touches the run_guest_oracle/write_guest_oracle seams — byte-identical
        # today-behavior, regression-locked.
        guest_oracle_enabled: bool = False,
    ) -> None:
        self._run_id = run_id
        self._session_id = session_id
        self._tasks = list(tasks)
        self._path = swap_state_path
        self._ops = ops
        # M2 plan-graph state (inert when plan is None).
        self._plan = plan
        self._plan_store = plan_store
        self._plan_degraded = bool(plan_degraded)
        self._plan_hash = plan.plan_hash if plan is not None else ""
        self._current_phase = ss.PHASE_SETTLE
        self._fleet_tasks: dict[str, dict] = {
            slugify_task(str(t.get("task", ""))): t for t in self._tasks
        }
        self._task_refs: dict[str, tuple[str, str]] = {}   # task_id -> (base, merge)
        self._repo_bases: dict[str, str] = {}              # repo -> pre-dispatch HEAD (#693)
        self._skip_reasons: dict[str, str] = {}            # task_id -> why skipped
        self._wave_gates: list[dict] = []                  # {wave, status, evidence}
        self._job_evidence = ""
        self._packs_consumed = 0
        self._plan_cancelled = False
        self._plan_stopped = False
        self._started_monotonic = time.monotonic()
        self._restart_backoff_cap_s = max(1.0, float(restart_backoff_cap_s))
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
        self._guest_oracle_enabled = bool(guest_oracle_enabled)
        self._guest_oracle_signal: "dict | None" = None
        # #758 driver-alive stamp — computed ONCE here and carried on EVERY phase
        # write below. The entrypoint's post-spawn stamp alone was clobbered back
        # to 0/0.0 by the driver's first _phase write (found live 2026-07-08:
        # phase CODE, driver_pid 0 in the real current.json), leaving the
        # reconcile's driver-alive gate inert for real AO boots mid-dispatch —
        # the exact operator-opens-app kill #758 closed. psutil-less degrades to
        # pid-only (narrow reuse window), same as the entrypoint stamp.
        self._driver_pid = os.getpid()
        self._driver_pid_created = 0.0
        try:
            import psutil

            self._driver_pid_created = float(
                psutil.Process(self._driver_pid).create_time()
            )
        except Exception:  # noqa: BLE001 — pid-only still guards
            self._driver_pid_created = 0.0

    def _phase(self, phase: str, *, error: str = "") -> None:
        # Best-effort: a phase-write failure (e.g. a full disk) must never derail the
        # swap or, worse, the never-zero teardown — the write is the audit trail, not a
        # control dependency. In plan mode the CURRENT plan_hash rides every write —
        # the seam-note (b) re-pin: plan_hash covers task statuses, so it changes on
        # each persist and the swap-state pin must follow it. The #758 driver-alive
        # stamp rides every write too — a single write without it un-guards the run.
        self._current_phase = phase
        try:
            ss.write_swap_state(
                ss.SwapState(run_id=self._run_id, session_id=self._session_id,
                             phase=phase, tasks=self._tasks, error=error,
                             plan_hash=self._plan_hash,
                             driver_pid=self._driver_pid,
                             driver_pid_created=self._driver_pid_created),
                path=self._path,
            )
        except BaseException:  # noqa: BLE001 — a pure audit write must NEVER derail teardown
            pass

    def _persist_plan(self) -> None:
        """Persist the plan after an evidence-gated transition + RE-PIN the write-time
        hash in swap-state (seam note (b): the pin always follows whatever hash the
        store minted for THIS persist — scheme-agnostic, whether the hash covers
        statuses or only the immutable plan identity). Persisted statuses are ADVISORY
        resumption hints, never authority: this driver re-derives every done-ness from
        the fleet RESULT lines + a fresh oracle run in THIS process (§9 zero-FALSE-
        DONE); it never reads a status back from disk mid-run. Best-effort —
        persistence is the audit/recovery trail, never a control dependency."""
        if self._plan is None or self._plan_store is None:
            return
        try:
            self._plan = self._plan_store.write(self._plan)
            self._plan_hash = self._plan.plan_hash
            self._phase(self._current_phase)   # re-pin under the same phase
        except BaseException:  # noqa: BLE001 — never derail the run on an audit write
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
            guest_oracle_signal=self._guest_oracle_signal,
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
            # (2b) M2 W6: the machine scorecard + human JOB_SUMMARY (plan mode only;
            # guarded audit writes — never on the critical path of the 14B restore).
            self._guard("emit plan artifacts", lambda: self._emit_plan_artifacts(outcomes))
            # (3) UNLOAD-30B — disarm first, then stop, then VERIFY the stop took (fail-loud)
            self._progress("Stopping the 30B and swapping the 14B back…")
            self._phase(ss.PHASE_UNLOAD_30B)
            self._guard("disarm watchdog", self._ops.disarm_watchdog)
            self._guard("stop OVMS", self._ops.stop_ovms)
            self._verify_ovms_stopped()
            # (3b) #744 guest oracle certificate — EXACTLY the RAM-free window (the 30B
            # is down, the 14B not yet restored; the NIC-less guest has the box to
            # itself). ONE run per JOB, advisory-only, guarded like _critic_phase /
            # _design_phase so it can NEVER block the 14B restore. With the knob off
            # (the shipped default) _guest_oracle_phase returns before touching ANY
            # seam — byte-identical today-behavior.
            self._guard("guest oracle certificate", self._guest_oracle_phase)
        except BaseException:  # noqa: BLE001 — NOTHING above may stop the 14B restore below
            pass
        # (4) RESTART-AO — UNCONDITIONALLY reached; the 14B restore.
        self._phase(ss.PHASE_RESTART_AO)
        self._restart_ok = self._restart_with_retry()
        # (5) hygiene — AFTER the 14B is restored (OFF the critical path); bounded git, best-effort.
        self._progress("Cleaning up leftover task worktrees (parked branches kept)…")
        self._guard("sweep worktrees", self._ops.sweep_worktrees)
        # (6) TERMINAL STAMP (2026-07-08) — the driver marks its OWN healthy run
        # terminal as its LAST act. Before the #758 driver-alive stamp actually
        # survived phase writes, the terminal RECOVERED always came — accidentally
        # but load-bearing — from the restarted AO's boot reconcile, whose recover
        # branch only fired because driver_pid read 0. With the stamp carried
        # correctly, the reconcile now (rightly) goes hands-off on the still-alive
        # driver during cleanup — and NOTHING ever stamped terminal, so the battery
        # monitor waited on a phase that never came (B4, night-20260707-230002:
        # run finished 05:34, monitor blind until its 3 h doom). Stamp ONLY on a
        # successful restore: a failed restore stays in-flight so the next AO
        # boot's reconcile keeps ownership of the unhealthy path (disarm + stop +
        # operator message), exactly the crash-net semantics #758 intended.
        if self._restart_ok:
            self._phase(ss.PHASE_RECOVERED)

    def _guest_oracle_phase(self) -> None:
        """#744 guest-certified oracle — the ADVISORY isolation certificate.

        Runs ONCE per JOB in the RAM-free teardown window (after UNLOAD-30B, before
        RESTART-AO — the only point in the swap where neither model holds the box).
        Scoped to plan mode with a graded host oracle: the guest re-runs the SAME
        job-level spec-blind oracle, and the outcome is recorded as evidence BESIDE
        the host result — verdict/attribution semantics are untouched (the host gate
        stays the fidelity gate; the LA has not ratified more). A host-pass/guest-fail
        divergence is FLAGGED in the block. Every other path records an honest
        ``not-run`` with a stable reason — never a silent pass, never a raise (the
        caller guards this again; the 14B restore is NEVER blocked).

        DORMANT-SAFE: with ``guest_oracle_enabled`` false (the shipped default) this
        returns before touching ANY seam or writing ANY trail line — byte-identical
        today-behavior, regression-locked."""
        if not self._guest_oracle_enabled:
            return
        from shared.fleet.guest_oracle import certificate_block

        host_status = "not-run"
        if self._plan is None:
            guest = {"status": "not-run", "reason": "flat-queue-mode",
                     "evidence": "flat-queue mode — no job-level oracle to certify"}
        else:
            host_status = self._plan.job_acceptance.status
            merged_any = any(t.status == pg.STATUS_MERGED for t in self._plan.tasks)
            if self._plan_cancelled or self._plan_stopped:
                guest = {"status": "not-run", "reason": "run-cancelled-or-stopped",
                         "evidence": "the run was cancelled or budget-stopped — "
                                     "no integrated tree to certify"}
            elif not merged_any:
                guest = {"status": "not-run", "reason": "nothing-merged",
                         "evidence": "nothing merged — no integrated tree to certify"}
            elif host_status not in ("passed", "failed"):
                guest = {"status": "not-run", "reason": "host-oracle-not-run",
                         "evidence": "the host job oracle did not run — there is no "
                                     "host outcome to certify against"}
            else:
                try:
                    guest = self._ops.run_guest_oracle(
                        self._repo(), self._plan.job_acceptance.oracle_path)
                except Exception:  # noqa: BLE001 — executor failure is an honest not-run
                    guest = {"status": "not-run", "reason": "guest-oracle-raised",
                             "evidence": "the guest oracle executor raised"}
                if not isinstance(guest, dict):
                    guest = {"status": "not-run", "reason": "guest-oracle-non-dict",
                             "evidence": "the guest oracle executor returned a non-dict"}
        block = certificate_block(guest, host_status=host_status)
        self._guest_oracle_signal = block
        self._guard("write guest-oracle evidence",
                    lambda: self._ops.write_guest_oracle(block))
        if block["divergence"]:
            self._progress(
                "Guest oracle certificate: DIVERGENCE — the host oracle passed but the "
                "in-guest run FAILED (advisory; flagged for review, verdict unchanged)."
            )
        elif block["status"] == "not-run":
            self._progress(
                f"Guest oracle certificate: not-run ({block['reason']}) — the isolation "
                "certificate is unavailable for this job (advisory; verdict unchanged)."
            )
        else:
            self._progress(
                f"Guest oracle certificate: {block['status'].upper()} in the NIC-less "
                "guest (advisory isolation certificate; verdict unchanged)."
            )

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
            self._plan_stopped = True   # plan-mode scorecard honesty (STALLED); inert otherwise
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

        # 10 CODE — per-task; cancel + out-of-band budget-stop checked at each task boundary.
        # M2 (#740): with a validated JobPlan the CODE phase runs the WAVE scheduler
        # (dependency-ordered, context-packed, wave-gated — W3/W4/W5); plan=None is the
        # legacy flat loop below, byte-identical.
        self._progress("The coder fleet is running your approved tasks…")
        self._phase(ss.PHASE_CODE)
        cancelled = False
        stopped = False
        if self._plan is not None:
            cancelled, stopped = self._run_plan_waves(outcomes)
            if stopped:
                self._progress("The overall run budget elapsed — restoring the 14B.")
                return ("budget-timeout", True, False, avail,
                        "the overall run budget elapsed — restoring the 14B")
            self._critic_phase(outcomes)
            self._design_phase(outcomes)
            return (("cancelled" if cancelled else "complete"), True, cancelled, avail,
                    ("dispatch cancelled after the current task" if cancelled
                     else "dispatch complete"))
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
            self._note_repo_base(str(task.get("repo", "") or ""))
            outcomes.append(self._ops.run_task(task))
        # F4 (#752): record the flat run's cancel/stop state on self so the teardown's
        # REPORT phase (_emit_plan_artifacts, flat branch) can build an honest flat
        # scorecard. Covers BOTH flat returns below (budget-timeout and complete/cancelled);
        # plan mode returns above and sets these in _run_plan_waves, so this never runs there.
        self._plan_cancelled, self._plan_stopped = cancelled, stopped
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

    # ---- M2 plan-graph wave scheduler (W3-W5, #740) -----------------------------------

    def _repo(self) -> str:
        return self._plan.repo if self._plan is not None else ""

    def _next_wave(self) -> "list[pg.PlanTask]":
        """The DYNAMIC wave frontier: every ``pending`` task whose dependencies are ALL
        ``merged``, in original plan order. Executes exactly the ``compile_waves``
        topology on a static plan (regression-locked) while staying correct when the
        graph MUTATES mid-run (a W5 re-decompose replaces a node) — the frontier simply
        picks up the children on the next lap."""
        assert self._plan is not None
        by_id = {t.id: t for t in self._plan.tasks}
        return [
            t for t in self._plan.tasks
            if t.status == pg.STATUS_PENDING
            and all(by_id[d].status == pg.STATUS_MERGED for d in t.depends_on)
        ]

    def _build_pack(self, ptask: "pg.PlanTask") -> str:
        """W3: the task's context pack (contract + as-built delta per dependency).
        Pure assembly (context_pack) over the injected git seam (ops.repo_head /
        ops.dep_delta via the recorded per-task merge refs). '' when dependency-less."""
        assert self._plan is not None
        repo = self._repo()

        def _delta(dep_id: str) -> dict:
            refs = self._task_refs.get(dep_id)
            if not refs or not refs[0] or not refs[1] or refs[0] == refs[1]:
                return {}
            return self._ops.dep_delta(repo, refs[0], refs[1])

        return cp.context_pack_for_task(ptask, self._plan, delta_fn=_delta)

    def _fleet_task_for(self, ptask: "pg.PlanTask") -> dict:
        """The fleet task dict to enqueue for *ptask*: the ORIGINAL compiled dict (all
        fleet fields — surface/complexity/goal/…) with the plan prompt, plus the W3
        context pack appended at enqueue when the task has dependencies. Every pack is
        logged VERBATIM (plan §4.4 auditability)."""
        base = dict(self._fleet_tasks.get(ptask.id, {"repo": self._repo(), "task": ptask.id}))
        base["task"] = ptask.id
        base.setdefault("repo", self._repo())
        prompt = ptask.prompt
        # #748: when the job oracle was seeded, every task is TOLD the job spec file
        # exists (the #690 "it IS the specification" sentence, job-scoped) — the
        # final integrated layout must satisfy those imports and tests.
        if getattr(self, "_oracle_seeded", False) and self._plan is not None:
            oracle_rel = self._plan.job_acceptance.oracle_path
            prompt = (
                f"{prompt}\n\nA protected job-level acceptance file `{oracle_rel}` is "
                "ALREADY in this project — the FINAL integrated application must make "
                "every test in it pass (its imports define the required module layout). "
                "Do NOT edit, weaken, or delete it; it is restored before grading."
            )
        base["prompt"] = prompt
        pack = self._build_pack(ptask)
        if pack:
            base["prompt"] = f"{prompt}\n\n{pack}"
            self._packs_consumed += 1
            try:
                self._ops.log_pack(ptask.id, pack)
            except Exception:  # noqa: BLE001 — the audit log must never block the task
                pass
        return base

    def _statuses(self) -> dict:
        assert self._plan is not None
        return {t.id: t.status for t in self._plan.tasks}

    def _record_new_skips(self, before: dict, outcomes: list, reason: str) -> None:
        """After a park/block propagated, surface every NEWLY-skipped task as an explicit
        SKIPPED outcome (fail loud — a skipped subtree must be visible in the report,
        never an implied nothing-happened)."""
        assert self._plan is not None
        for t in self._plan.tasks:
            if t.status == pg.STATUS_SKIPPED and before.get(t.id) not in (None, pg.STATUS_SKIPPED):
                self._skip_reasons[t.id] = reason
                outcomes.append(TaskOutcome(
                    task=t.id, outcome="skipped", result="SKIPPED",
                    detail=f"skipped: {reason}",
                ))
        newly = sorted(
            t.id for t in self._plan.tasks
            if t.status == pg.STATUS_SKIPPED and before.get(t.id) not in (None, pg.STATUS_SKIPPED)
        )
        if newly:
            self._progress(
                "Skipping dependent task(s) " + ", ".join(newly) + f" — {reason}."
            )

    def _skip_all_pending(self, outcomes: list, reason: str) -> None:
        """W4 short-circuit: a failed wave gate means later waves must NOT build on the
        broken base — every still-pending task is marked ``skipped`` (fail loud)."""
        assert self._plan is not None
        from dataclasses import replace as _replace
        before = self._statuses()
        new_tasks = [
            _replace(t, status=pg.STATUS_SKIPPED) if t.status == pg.STATUS_PENDING else t
            for t in self._plan.tasks
        ]
        self._plan = _replace(self._plan, tasks=new_tasks)
        self._record_new_skips(before, outcomes, reason)

    def _try_redecompose(self, ptask: "pg.PlanTask", fleet_task: dict, outcome) -> bool:
        """W5: ONE evidence-fed re-decompose of a consistently-failing task (the fleet's
        own best-of-N + resample budget is already exhausted when a run_task returns
        non-MERGED). Budgets are the plan's (per_job, persisted); the replacement lands
        ONLY on a strict improvement re-validated by ``replace_task_with_children``;
        anything else returns False and the caller parks the task honestly."""
        assert self._plan is not None
        budget = self._plan.redecompose_budget
        if budget.spent >= budget.per_job:
            return False
        evidence = build_failure_evidence(
            getattr(outcome, "detail", ""), getattr(outcome, "outcome", "")
        ) or str(getattr(outcome, "detail", "") or "")[:200]
        try:
            children = self._ops.redecompose(dict(fleet_task), evidence)
        except Exception:  # noqa: BLE001 — a re-planner failure parks, never crashes
            children = None
        if not children:
            return False
        new_plan = pg.replace_task_with_children(self._plan, ptask.id, children)
        if new_plan is None:
            return False
        try:
            self._plan = pg.spend_redecompose(new_plan)
        except ValueError:
            return False
        # Children need fleet dicts: inherit the parent's fleet fields (surface/goal/…),
        # swap in their own slug/prompt; graph keys live in the plan, not the queue dict.
        parent_fields = {
            k: v for k, v in fleet_task.items()
            if k not in ("task", "prompt", "depends_on", "contract",
                         "acceptance_test_code", "acceptance_test_path")
        }
        child_ids = []
        for t in self._plan.tasks:
            if t.id in self._fleet_tasks:
                continue
            child_ids.append(t.id)
            self._fleet_tasks[t.id] = {**parent_fields, "task": t.id, "prompt": t.prompt}
        self._persist_plan()
        self._progress(
            f"Task {ptask.id} failed consistently — re-decomposed it into "
            + ", ".join(child_ids)
            + f" (evidence-fed; budget {self._plan.redecompose_budget.spent}"
            f"/{self._plan.redecompose_budget.per_job})."
        )
        return True

    def _run_plan_waves(self, outcomes: list) -> tuple[bool, bool]:
        """The W3-W5 wave loop (plan §4.3): run the dynamic frontier wave-by-wave, each
        task through the UNCHANGED per-task fleet gate; evidence-gate every status;
        wave-gate the integrated main after each merging wave (first failure
        short-circuits); park/block propagates skip; a consistent failure gets ONE
        bounded evidence-fed re-decompose; the job oracle is the finish line.
        Returns ``(cancelled, stopped)``."""
        assert self._plan is not None
        cancelled = stopped = False
        # #748: seed the job oracle into the repo BEFORE wave 1 so every task
        # worktree carries the job spec the coder codes toward (plan §4.5 — the
        # proven #690 per-task mechanic at job level; run 20260705-214803-bd failed
        # its oracle on a layout the coder was never shown). The seeded copy is
        # guard-wrapped (skips in gates); grading overwrites with plan bytes.
        # Fail-soft: an unseeded run behaves exactly as before seeding existed.
        self._oracle_seeded = False
        oracle_rel = self._plan.job_acceptance.oracle_path
        try:
            seed = self._ops.seed_job_oracle(self._repo(), oracle_rel)
        except Exception as exc:  # noqa: BLE001 — seeding must never block the run
            seed = {"ok": False, "evidence": f"seed op raised: {type(exc).__name__}"}
        if isinstance(seed, dict) and seed.get("ok") is True:
            self._oracle_seeded = True
            self._progress(
                f"Job acceptance oracle seeded into the repo ({oracle_rel}) — "
                "protected; the final integrated app must satisfy it."
            )
        else:
            evidence = ""
            if isinstance(seed, dict):
                evidence = str(seed.get("evidence", "") or "")
            self._progress(
                f"Job oracle NOT seeded ({evidence or 'unavailable'}) — the coder "
                "builds without seeing it; it still grades the final tree."
            )
        wave_no = 0
        while True:
            if self._ops.cancel_requested():
                cancelled = True
                break
            if self._ops.stop_requested():
                stopped = True
                break
            wave = self._next_wave()
            if not wave:
                break
            wave_no += 1
            self._progress(
                f"Wave {wave_no}: " + ", ".join(t.id for t in wave)
                + f" ({len(wave)} task(s))."
            )
            wave_merged = False
            for ptask in wave:
                if self._ops.cancel_requested():
                    cancelled = True
                    break
                if self._ops.stop_requested():
                    stopped = True
                    break
                current = self._plan.task(ptask.id)
                if current.status != pg.STATUS_PENDING:
                    continue  # a same-wave sibling's failure cannot skip it; defensive
                self._plan = pg.mark_ready(self._plan, ptask.id)
                self._plan = pg.mark_building(self._plan, ptask.id)
                self._persist_plan()
                fleet_task = self._fleet_task_for(current)
                repo = str(fleet_task.get("repo", "") or self._repo())
                base_ref = ""
                try:
                    base_ref = str(self._ops.repo_head(repo) or "")
                except Exception:  # noqa: BLE001 — an unreadable HEAD degrades the pack only
                    base_ref = ""
                self._note_repo_base(repo, base_ref)
                outcome = self._ops.run_task(fleet_task)
                outcomes.append(outcome)
                result = getattr(outcome, "result", "")
                detail = getattr(outcome, "detail", "") or result or "no RESULT line"
                before = self._statuses()
                if result == "MERGED":
                    merge_ref = ""
                    try:
                        merge_ref = str(self._ops.repo_head(repo) or "")
                    except Exception:  # noqa: BLE001
                        merge_ref = ""
                    self._task_refs[ptask.id] = (base_ref, merge_ref)
                    self._plan = pg.mark_merged(self._plan, ptask.id, detail)
                    wave_merged = True
                elif result == "BLOCKED":
                    self._plan = pg.mark_blocked(self._plan, ptask.id, detail)
                    self._record_new_skips(
                        before, outcomes, f"dependency {ptask.id} was BLOCKED"
                    )
                else:
                    # PARKED / NOTHING / UNKNOWN — no merged foundation either way.
                    if not self._try_redecompose(ptask, fleet_task, outcome):
                        self._plan = pg.mark_parked(self._plan, ptask.id, detail)
                        self._record_new_skips(
                            before, outcomes,
                            f"dependency {ptask.id} parked ({result or 'no result'})",
                        )
                self._persist_plan()
            if cancelled or stopped:
                break
            # ---- W4 wave gate: verify the INTEGRATED main after a merging wave --------
            if wave_merged:
                try:
                    gate = self._ops.run_wave_gate(self._repo())
                except Exception:  # noqa: BLE001 — a gate-machinery failure is could-not-run
                    gate = {"ok": None, "evidence": "wave gate raised"}
                if not isinstance(gate, dict):
                    gate = {"ok": None, "evidence": "wave gate returned a non-dict"}
                ok = gate.get("ok")
                evidence = str(gate.get("evidence", "") or "wave gate ran")
                if ok is True:
                    self._wave_gates.append(
                        {"wave": wave_no, "status": "passed", "evidence": evidence})
                    self._plan = pg.mark_integration(
                        self._plan, wave_no, passed=True, evidence=evidence)
                    self._persist_plan()
                    self._progress(f"Wave {wave_no} integration gate: PASSED.")
                elif ok is False:
                    self._wave_gates.append(
                        {"wave": wave_no, "status": "failed", "evidence": evidence})
                    self._plan = pg.mark_integration(
                        self._plan, wave_no, passed=False, evidence=evidence)
                    self._progress(
                        f"Wave {wave_no} integration gate FAILED on the merged tree — "
                        "stopping later waves (they must not build on a broken base). "
                        f"Evidence: {evidence}"
                    )
                    self._skip_all_pending(
                        outcomes, f"wave {wave_no} integration gate failed")
                    self._persist_plan()
                    break
                else:
                    # could-not-run: honest, non-blocking (mirrors the fleet's 'none').
                    self._wave_gates.append(
                        {"wave": wave_no, "status": "not-run", "evidence": evidence})
                    self._progress(
                        f"Wave {wave_no} integration gate could not run — integration "
                        "is UNVERIFIED for this wave (recorded, not implied passed)."
                    )
        # ---- W4 job oracle: the finish line on the final integrated tree -------------
        if not cancelled and not stopped:
            self._run_job_acceptance()
        else:
            self._plan_cancelled, self._plan_stopped = cancelled, stopped
        return (cancelled, stopped)

    def _run_job_acceptance(self) -> None:
        """Grade the job oracle on the final integrated tree (restore-before-grade in
        the live seam) and record the outcome evidence-gated. The job may only report
        DONE when this is ``passed`` — every other path records an honest non-pass."""
        assert self._plan is not None
        merged_any = any(t.status == pg.STATUS_MERGED for t in self._plan.tasks)
        gates_failed = any(g["status"] == "failed" for g in self._wave_gates)
        if not merged_any:
            status, evidence = "not-run", "nothing merged — no integrated tree to grade"
        elif gates_failed:
            status, evidence = "not-run", "a wave integration gate failed — the tree is not a candidate"
        else:
            try:
                res = self._ops.run_job_oracle(
                    self._repo(), self._plan.job_acceptance.oracle_path)
            except Exception as exc:  # noqa: BLE001 — oracle machinery failure is not-run
                res = {"status": "not-run", "evidence": f"job oracle raised: {exc!r}"}
            if not isinstance(res, dict):
                res = {"status": "not-run", "evidence": "job oracle returned a non-dict"}
            status = str(res.get("status", "not-run"))
            if status not in ("passed", "failed", "not-run"):
                status = "not-run"
            evidence = str(res.get("evidence", "") or "job oracle ran")
        self._job_evidence = evidence
        self._plan = pg.mark_job_acceptance(self._plan, status, evidence)
        self._persist_plan()
        if status == "passed":
            self._progress("JOB acceptance oracle PASSED on the integrated tree — the job is done.")
        elif status == "failed":
            self._progress(
                "JOB acceptance oracle FAILED on the integrated tree — the job is NOT "
                f"done (unit-green does not equal job-green). Evidence: {evidence}"
            )
        else:
            self._progress(
                f"JOB acceptance oracle did not run — the job CANNOT report verified-done ({evidence})."
            )

    def _emit_plan_artifacts(self, outcomes: list) -> None:
        """W6: the machine scorecard + the human JOB_SUMMARY (teardown-time, guarded).
        Emitted for BOTH modes — plan mode from the ``JobPlan``, flat mode (no
        plan-graph) from the per-task outcomes (F4, #752). Both writes ride the SAME
        injected seams."""
        if self._plan is None:
            # FLAT (legacy) queue — no JobPlan. Build the plan-less scorecard from the
            # per-task outcomes so the battery ADOPTS a real verdict instead of
            # synthesizing STALLED/HARNESS ("no driver scorecard … W6 REPORT-phase seam
            # pending"). run_id/repo/goal come from the driver's own attributes (there is
            # no plan to read them from); cancelled/stopped were recorded by the flat CODE
            # loop onto self before this teardown-time call; wall_clock mirrors the plan
            # branch. Both writes are guarded audit writes — never on the 14B-restore path.
            repo = next((str(t.get("repo", "")) for t in self._tasks if t.get("repo")), "")
            goal = next((str(t.get("goal", "")) for t in self._tasks if t.get("goal")), "")
            scorecard = build_flat_scorecard(
                outcomes,
                run_id=self._run_id,
                repo=repo,
                goal=goal,
                wall_clock_s=time.monotonic() - self._started_monotonic,
                cancelled=self._plan_cancelled,
                stopped=self._plan_stopped,
                degraded=self._plan_degraded,
            )
            self._guard("write scorecard", lambda: self._ops.write_scorecard(scorecard))
            self._guard("write job summary",
                        lambda: self._ops.write_job_summary(render_job_summary(scorecard)))
            self._progress(
                f"JOB verdict: {scorecard['verdict']}"
                + (f" (attribution: {scorecard['attribution']})" if scorecard["attribution"] else "")
                + " (flat-queue mode)."
            )
            return
        scorecard = build_scorecard(
            self._plan,
            run_id=self._run_id,
            outcomes=outcomes,
            wave_gates=self._wave_gates,
            job_evidence=self._job_evidence,
            cancelled=self._plan_cancelled,
            stopped=self._plan_stopped,
            degraded=self._plan_degraded,
            packs_consumed=self._packs_consumed,
            wall_clock_s=time.monotonic() - self._started_monotonic,
            evidence_paths={
                "plan": str(self._plan_store.path) if self._plan_store is not None else "",
            },
        )
        self._guard("write scorecard", lambda: self._ops.write_scorecard(scorecard))
        self._guard("write job summary",
                    lambda: self._ops.write_job_summary(render_job_summary(scorecard)))
        # #749 dispatch→Vikunja bridge (driver-side seam — NOT wired here):
        # this REPORT phase is the natural home for posting the durable per-job
        # ticket outcome (shared.fleet.vikunja_bridge.ensure_job_ticket +
        # post_outcome, gated on config.vikunja_bridge / vikunja_bridge_project_id).
        # It is DELIBERATELY left as a TODO: the swap driver is detached and must
        # not take on mid-campaign ticket I/O (a Vikunja stall must never touch a
        # live swap). The bridge is wired from the battery runner and the standalone
        # harness (which own the REPORT-time post); the driver leg lands when #749's
        # supervised live proof clears it. Do not add ticket I/O inside _guard here.
        self._progress(
            f"JOB verdict: {scorecard['verdict']}"
            + (f" (attribution: {scorecard['attribution']})" if scorecard["attribution"] else "")
            + "."
        )

    # ---- cross-model 14B code critic (#687 task 2) -----------------------------------

    def _note_repo_base(self, repo: str, head: "str | None" = None) -> None:
        """Record the FIRST observed HEAD per repo — main's pre-dispatch SHA (#693).

        Called before a repo's first task runs (flat + plan-graph loops), so the critic can
        diff ``<base>..HEAD`` and see ALL merged work even when a multi-commit agent branch
        fast-forwards onto an unchanged main (``HEAD~1..HEAD`` sees only the last commit).
        Only a non-empty first read is recorded; an unreadable HEAD leaves the repo
        unrecorded and the critic script falls back to ``Resolve-CriticRange``. The critic-
        and design-fix laps re-enter run_task for an already-recorded repo, so the base can
        never be reset mid-run."""
        if not repo or repo in self._repo_bases:
            return
        if head is None:
            try:
                head = str(self._ops.repo_head(repo) or "")
            except Exception:  # noqa: BLE001 — an unreadable HEAD only degrades the critic range
                head = ""
        if head:
            self._repo_bases[repo] = head

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

        Calls ``run_critic(app_dir, base_branch, base_sha)`` — ``base_sha`` is the repo's
        pre-dispatch HEAD from :meth:`_note_repo_base` ("" when unrecorded -> the script
        falls back to ``Resolve-CriticRange``; #693) — which in the live impl loads the 14B
        via ``start-llm.ps1 -Force`` (internal OVMS model swap) and returns
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
                result = self._ops.run_critic(
                    app_dir, base_branch, self._repo_bases.get(app_dir, ""))
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

    def _relaunch_in_flight(self) -> bool:
        """Probe the RESTART-AO in-flight seam fail-soft (unknown == False, the legacy
        spawn-every-attempt behavior)."""
        try:
            return bool(self._ops.relaunch_in_flight())
        except BaseException:  # noqa: BLE001 — an unreadable probe must never derail the restore
            return False

    def _restart_with_retry(self) -> bool:
        """Relaunch the backend up to N times, proving it actually came up (§2.3).

        M2 hardening (routed-in W7, the 2026-07-03 ``SWAP_FAILED → RECOVERED`` — plan
        risk R5), preserving the never-zero discipline end-to-end:

          * **No launcher stacking:** when the previously-spawned relaunch is STILL
            ALIVE (``relaunch_in_flight`` — a cold 14B load under post-swap memory
            pressure can outlast one ready-poll window), the retry WAITS on it instead
            of spawning a second launcher — a second spawn would hit the launcher's
            single-instance lock and exit immediately, silently burning the attempt
            (the suspected live failure shape). The default seam returns False, so
            legacy wiring/tests keep the exact spawn-every-attempt behavior.
          * **Bounded escalating backoff:** the between-attempt sleep doubles per
            attempt, capped at ``restart_backoff_cap_s`` — transient contention gets
            room to clear without unbounded waiting.
          * **Terminal-vs-recoverable distinction:** a spawn failure (the relaunch
            Popen itself raised) is logged distinctly from ready-timeout, and the
            give-up signal names whether a launcher is still alive (recoverable —
            "give it a minute") or dead/never-spawned (terminal — "restart BlarAI").
        """
        backoff = self._restart_backoff_s
        for attempt in range(1, self._restart_retries + 1):
            if self._relaunch_in_flight():
                self._progress(
                    f"Restart attempt {attempt}/{self._restart_retries}: the relaunched "
                    "backend is still starting — waiting for it instead of spawning a "
                    "second launcher (the instance lock would refuse it)."
                )
            else:
                try:
                    self._ops.restart_launcher()
                except BaseException as exc:  # noqa: BLE001 — a restore-internal error OR signal is "this
                    # attempt failed, retry"; it must NEVER escape _teardown and mask `raised` (#670 P2)
                    self._progress(
                        f"Restart attempt {attempt}/{self._restart_retries}: the relaunch "
                        f"could not be spawned ({exc!r}) — will retry."
                    )
            try:
                came_up = self._ops.backend_ready()
            except BaseException:  # noqa: BLE001 — a probe failure OR signal means "not up yet", retry
                came_up = False
            if came_up:
                self._progress("BlarAI's 14B is back — read the run with /dispatch status.")
                return True  # the 14B is back; the restarted reconciler reports
            if attempt < self._restart_retries:
                try:
                    self._sleep(backoff)
                except BaseException:  # noqa: BLE001 — a signal must NOT truncate the 14B restore
                    pass
                backoff = min(backoff * 2, self._restart_backoff_cap_s)
        # Persistent failure: zero models, but LOUD + one-action recoverable (§2.3).
        # Terminal-vs-recoverable: name whether a launcher survives (it may yet come up).
        if self._relaunch_in_flight():
            self._progress(
                "A relaunched backend process is STILL ALIVE and may finish starting — "
                "give it a minute before restarting BlarAI manually."
            )
        else:
            self._progress(
                "No relaunched backend process survives — the launcher exited or never "
                "spawned; restart BlarAI to recover."
            )
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
