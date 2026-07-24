"""Swap-state persistence + the boot-time recovery reconciler (increment 2).

The model-swap driver tears BlarAI's backend fully down to free the 14B, runs the
fleet's 30B, then restarts the backend. Two on-disk facts make that crash-safe:

* the SWAP-STATE FILE — a write-ahead ``{run_id, session_id, tasks, phase}`` record
  (NO conversation content — privacy-absolute; the conversation stays in the
  encrypted ``sessions.db`` and is reloaded by ``session_id`` on restart), and
* the fleet's ``state/server-should-run.txt`` sentinel — the watchdog's only arm
  signal; removing it keeps a (possibly-registered) watchdog from resurrecting the
  30B while the 14B comes back.

``reconcile_swap_state`` runs on EVERY backend boot, before the AO serves: it
disarms the sentinel, stops any resident OVMS, and reports what to do about a run
that was in flight. It is idempotent — a no-op when no swap was in flight.

This module performs NO model swap and spawns NO fleet subprocess; the driver
(``swap_driver``) does. Here we only persist/read state and converge a crashed swap
back to "14B up, 30B down". DORMANT until ``[fleet_dispatch].enabled``.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

# Phases, in state-machine order (design §2). Persisted write-ahead by whoever
# is currently driving — the AO writes RESERVE..HANDOFF (it is still resident),
# the driver writes SETTLE..RESTART_AO. The reconciler reads whichever was last.
PHASE_IDLE = "IDLE-14B"
PHASE_RESERVE = "RESERVE"
PHASE_ENQUEUE = "ENQUEUE"
PHASE_HANDOFF = "HANDOFF"
PHASE_STEP_ASIDE = "STEP-ASIDE"
PHASE_SETTLE = "SETTLE"
PHASE_GATE = "GATE"
PHASE_LOAD_30B = "LOAD-30B"
PHASE_CODE = "CODE"
PHASE_CRITIC = "CRITIC"          # cross-model 14B code critic (#687 task 2); NOT terminal
PHASE_DESIGN = "DESIGN"          # end-of-run VLM design critique loop (#688 Phase 3); NOT terminal
PHASE_UNLOAD_30B = "UNLOAD-30B"
PHASE_RESTART_AO = "RESTART-AO"
PHASE_REPORT = "REPORT"
PHASE_RECOVERED = "RECOVERED"
PHASE_FAILED = "FAILED"        # RESTART-AO exhausted its retries (design §2.3)
PHASE_CANCELLED = "CANCELLED"

# Terminal phases: a boot here has nothing to converge (no swap in flight).
_PHASES_TERMINAL = frozenset({PHASE_IDLE, PHASE_RECOVERED})

# Phases at which THIS swap could have armed the fleet sentinel / loaded the 30B.
# Write-ahead means LOAD-30B is stamped immediately BEFORE start-llm runs, so it is
# the earliest phase at which an OVMS (or the sentinel arm) of OURS can exist; the
# later phases keep the stop as the named unload-failure backstop. An ALLOWLIST
# (deny-by-default, #902): the reconciler's destructive arms — the sentinel disarm
# and ``stop_ovms`` — fire ONLY for these phases. A record stranded pre-load (the
# AO-written RESERVE..HANDOFF shapes, or the driver's pre-load STEP-ASIDE/SETTLE/
# GATE) or carrying an unrecognized/corrupt phase converges its RECORD only and
# touches nothing external, because our swap provably never started what those
# arms exist to stop — disarming/stopping there could only hit someone ELSE's
# fleet run (the F2 hazard class through the recovery door).
_PHASES_OVMS_POSSIBLE = frozenset({
    PHASE_LOAD_30B,
    PHASE_CODE,
    PHASE_CRITIC,
    PHASE_DESIGN,
    PHASE_UNLOAD_30B,
    PHASE_RESTART_AO,
    PHASE_REPORT,
    PHASE_FAILED,
    PHASE_CANCELLED,
})


def is_in_flight(state: "SwapState | None") -> bool:
    """True iff a BlarAI swap was mid-flight (a non-terminal swap-state record).

    This is THE gate for recovery: never disarm the fleet's sentinel or stop OVMS
    without it. The fleet's ``server-should-run.txt`` sentinel is the FLEET's (armed
    whenever the operator runs the 30B), NOT a BlarAI swap signal — so recovery keys
    off a BlarAI-written, non-terminal swap-state file ONLY.
    """
    return state is not None and state.phase not in _PHASES_TERMINAL


@dataclass(frozen=True)
class SwapState:
    """The write-ahead swap record. Carries NO conversation content (privacy).

    ``tasks`` are the decomposed fleet tasks (``{repo, task, prompt}``) — the same
    specs already written plaintext to the fleet queue; the *conversation* is what
    must never be persisted here (it stays in the encrypted sessions.db).
    """

    run_id: str
    session_id: str
    phase: str
    tasks: list[dict] = field(default_factory=list)
    ts: str = ""        # stamped by the caller (this layer does not read the clock)
    error: str = ""
    # M2 plan-graph (W1/Lane A2, #740): the WRITE-TIME hash of the persisted JobPlan
    # artifact, re-pinned on every plan persist (whatever hash the PlanStore minted —
    # scheme-agnostic; per the W1 hardening the hash covers the IMMUTABLE plan identity,
    # with statuses deliberately outside it as advisory resumption hints only). '' for a
    # non-plan run — every legacy record reads back byte-identically. Defense-in-depth
    # against on-disk plan tamper (§10 S1): the self-hash in plan.json can be recomputed
    # by a tamperer; this pin cannot.
    plan_hash: str = ""
    # #758: the DETACHED driver's pid + process-create-time, stamped by run_swap when the
    # driver takes over. The reconciler uses these to tell a CRASHED swap (driver dead ->
    # recover) from a LIVE one (driver alive -> hands off): on 2026-07-07 an AO boot
    # mid-dispatch "recovered" a healthy swap — stopped the real OVMS mid-request and
    # stamped RECOVERED over the live run. create-time guards pid reuse. 0/0.0 (every
    # legacy record, and the AO-written RESERVE..HANDOFF phases before the driver's first
    # write) preserves the pre-#758 behavior: reconcile recovers unconditionally.
    driver_pid: int = 0
    driver_pid_created: float = 0.0
    # #902: the driver's process IMAGE NAME (e.g. "pythonw.exe"), stamped alongside
    # driver_pid/driver_pid_created. A second, independent identity axis for the
    # reconciler's reuse gate: a recycled PID whose new owner wears a different image
    # is provably NOT our driver even when a create-time read is unavailable. '' for
    # every legacy record (reads back byte-identically; the create-time gate alone
    # then governs, the pre-#902 behavior). Content-free process metadata — same
    # privacy standing as driver_pid.
    driver_image: str = ""

    def with_phase(self, phase: str, *, error: str = "", ts: str = "") -> "SwapState":
        """A copy advanced to *phase* (identity + tasks preserved)."""
        return SwapState(
            run_id=self.run_id,
            session_id=self.session_id,
            phase=phase,
            tasks=self.tasks,
            ts=ts or self.ts,
            error=error or self.error,
            plan_hash=self.plan_hash,
            driver_pid=self.driver_pid,
            driver_pid_created=self.driver_pid_created,
            driver_image=self.driver_image,
        )


def _atomic_write(path: Path, data: str) -> None:
    """Write-ahead, atomic: temp + ``os.replace`` — never a torn half record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)   # atomic rename on Windows + POSIX


def write_swap_state(state: SwapState, *, path: Path) -> None:
    """Persist the swap record write-ahead (before the transition it marks)."""
    _atomic_write(path, json.dumps(asdict(state), indent=2))


def read_swap_state(path: Path) -> SwapState | None:
    """Read the swap record, or None if absent/unreadable/blank (fail-soft)."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or not data.get("run_id"):
        return None
    try:
        driver_pid = int(data.get("driver_pid", 0) or 0)
    except (TypeError, ValueError):
        driver_pid = 0
    try:
        driver_pid_created = float(data.get("driver_pid_created", 0.0) or 0.0)
    except (TypeError, ValueError):
        driver_pid_created = 0.0
    return SwapState(
        run_id=str(data.get("run_id", "")),
        session_id=str(data.get("session_id", "")),
        phase=str(data.get("phase", "")),
        tasks=list(data.get("tasks", []) or []),
        ts=str(data.get("ts", "")),
        error=str(data.get("error", "")),
        plan_hash=str(data.get("plan_hash", "")),
        driver_pid=driver_pid,
        driver_pid_created=driver_pid_created,
        driver_image=str(data.get("driver_image", "") or ""),
    )


def clear_swap_state(path: Path) -> None:
    """Remove the swap record (after a clean REPORTED/RECOVERED). Idempotent."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


@dataclass(frozen=True)
class ReconcileResult:
    """What the boot reconciler did + what (if anything) to tell the user."""

    in_flight: bool                  # was a swap mid-flight at boot?
    run_id: str = ""
    session_id: str = ""
    summary_available: bool = False  # does SUMMARY.txt for run_id exist?
    message: str = ""                # human-facing line for the session (or "")


# Driver-liveness verdicts (#902). Four-valued because "not alive" conflated two
# situations with OPPOSITE safe responses: a provably-GONE driver (crashed swap —
# recover, stop our leftovers) and a RECYCLED pid now worn by a stranger (stale
# record — converge the record, but NEVER kill on an identity you cannot attribute).
DRIVER_ALIVE = "alive"          # pid exists AND identity matches -> healthy, hands-off
DRIVER_DEAD = "dead"            # pid provably absent -> the swap crashed, recover fully
DRIVER_REUSED = "reused"        # pid EXISTS but identity mismatches/unprovable -> stale
DRIVER_UNSTAMPED = "unstamped"  # no pid recorded (legacy / AO-written pre-driver phases)


def driver_liveness(state: "SwapState | None") -> str:
    """Classify the recorded driver as alive / dead / reused / unstamped (#758 + #902).

    Identity = recorded pid + create-time match (±2 s — process create-times are
    stable, the tolerance only absorbs float/clock rounding) + image-name match when
    the record carries one. Fail directions are deliberate and DIFFER by branch:

    * psutil entirely absent, or the pid provably gone -> :data:`DRIVER_DEAD` —
      recovery must not strand a genuinely-crashed swap forever (the pre-#758
      contract preserved).
    * the pid EXISTS but its identity mismatches or cannot be proven ->
      :data:`DRIVER_REUSED` — a live process the record cannot attribute is exactly
      the pid-recycling hazard (#902: a stranded record's pid re-worn by an unrelated
      process, e.g. inside a pytest tree). The kill-capable convergence must refuse.
    """
    if state is None or not state.driver_pid:
        return DRIVER_UNSTAMPED
    try:
        import psutil
    except Exception:  # noqa: BLE001 — no probe at all: recover rather than strand
        return DRIVER_DEAD
    try:
        proc = psutil.Process(state.driver_pid)
        if not proc.is_running():
            return DRIVER_DEAD
    except psutil.NoSuchProcess:
        return DRIVER_DEAD
    except Exception:  # noqa: BLE001 — pid may exist but is unattributable: never kill on a guess
        return DRIVER_REUSED
    try:
        if state.driver_pid_created > 0 and (
            abs(float(proc.create_time()) - state.driver_pid_created) >= 2.0
        ):
            return DRIVER_REUSED
        if state.driver_image and (
            (proc.name() or "").lower() != state.driver_image.lower()
        ):
            return DRIVER_REUSED
    except Exception:  # noqa: BLE001 — identity unprovable on a live pid: refuse-kill direction
        return DRIVER_REUSED
    return DRIVER_ALIVE


def driver_alive(state: "SwapState | None") -> bool:
    """True iff the swap's recorded DETACHED driver process is still running (#758).

    Now a thin verdict over :func:`driver_liveness`: alive means the pid exists AND
    its identity (create-time ±2 s, plus image name when recorded — #902) matches the
    record. Everything else — legacy/unstamped records, a provably-dead pid, a reused
    pid, psutil unavailable — is "not alive"; the RECONCILER further distinguishes
    dead-vs-reused because only one of those may kill.
    """
    return driver_liveness(state) == DRIVER_ALIVE


def reconcile_swap_state(
    *,
    swap_state_path: Path,
    sentinel_path: Path,
    runs_dir: Path,
    stop_ovms: Callable[[], None],
    driver_alive_probe: "Callable[[SwapState | None], bool] | None" = None,
    driver_liveness_probe: "Callable[[SwapState | None], str] | None" = None,
) -> ReconcileResult:
    """Boot-time convergence to "14B up, 30B down". Idempotent; runs every boot.

    1. DISARM: remove the watchdog sentinel FIRST, so a (possibly-registered)
       watchdog cannot resurrect the 30B while the 14B comes back.
    2. FREE: stop any resident OVMS (injected; idempotent; fail-soft — a stop
       failure must never block the 14B boot).
    3. RECONCILE: if a swap was mid-flight, decide report-vs-interrupted from the
       persisted phase + whether ``SUMMARY.txt`` for the run exists, then mark the
       record RECOVERED so a second boot is a clean no-op.

    #758 PRECONDITION: recovery presumes the swap CRASHED. When the recorded driver
    process is still ALIVE (identity-verified — see :func:`driver_liveness`), the
    swap is healthy — a boot that "recovered" it would kill the live run (stop its
    OVMS mid-task + stamp RECOVERED over it, the 2026-07-07 incident). In that case
    this is HANDS-OFF: nothing disarmed, nothing stopped, nothing stamped — the
    driver finishes and restores the 14B itself.

    #902 KILL-SAFETY (both new gates are identity-first, never bare-PID/bare-name):

    * REUSED pid -> record-only convergence. When the recorded driver pid EXISTS but
      its identity no longer matches the record (create-time/image mismatch — the
      pid was recycled by an unrelated process, e.g. one inside a test tree), the
      record is stale beyond trust and NOTHING now running can be attributed to our
      swap. The destructive arms are REFUSED outright: no sentinel disarm, no
      ``stop_ovms``. Only the record is stamped RECOVERED so the stale state stops
      haunting every boot.
    * PHASE ALLOWLIST on the destructive arms. The sentinel disarm + ``stop_ovms``
      fire only for phases at which OUR swap could actually have armed/loaded
      (:data:`_PHASES_OVMS_POSSIBLE`, LOAD-30B onward). A record stranded pre-load
      (RESERVE..GATE) or carrying an unrecognized phase converges record-only —
      disarming/stopping there could only hit someone ELSE's fleet run.

    ``driver_alive_probe`` (bool) is the legacy injection seam and wins when given
    (True -> alive, False -> dead); ``driver_liveness_probe`` injects the four-valued
    verdict. The live default is :func:`driver_liveness`.

    The caller (the normal backend boot) cold-loads the 14B AFTER this returns.
    """
    # GATE FIRST (F2): only a BlarAI swap that was mid-flight gets recovered. With NO
    # in-flight swap-state this is a TOTAL no-op — we must NOT touch the sentinel or
    # OVMS, because ``server-should-run.txt`` is the FLEET's sentinel (armed whenever
    # the operator runs the 30B), not a BlarAI swap signal. Disarming/stopping here
    # unconditionally would kill the operator's running 30B on any BlarAI boot.
    state = read_swap_state(swap_state_path)
    if not is_in_flight(state):
        return ReconcileResult(in_flight=False)

    # #758 GATE SECOND: a LIVE driver means the swap did not crash — hands off.
    if driver_alive_probe is not None:
        liveness = DRIVER_ALIVE if driver_alive_probe(state) else DRIVER_DEAD
    elif driver_liveness_probe is not None:
        liveness = driver_liveness_probe(state)
    else:
        liveness = driver_liveness(state)
    if liveness == DRIVER_ALIVE:
        return ReconcileResult(
            in_flight=True,
            run_id=state.run_id,
            session_id=state.session_id,
            summary_available=False,
            message=(
                f"Coding dispatch {state.run_id} is STILL RUNNING (its driver process "
                f"is alive) — left untouched; it restores the assistant when it "
                f"finishes. Check `/dispatch status {state.run_id}`."
            ),
        )

    # #902 GATE THIRD: a REUSED pid means the record is stale and nothing running is
    # attributable to our swap — converge the RECORD only; refuse every destructive arm.
    if liveness == DRIVER_REUSED:
        write_swap_state(state.with_phase(PHASE_RECOVERED), path=swap_state_path)
        return ReconcileResult(
            in_flight=True,
            run_id=state.run_id,
            session_id=state.session_id,
            summary_available=False,
            message=(
                f"Coding dispatch {state.run_id}: stale swap record expired (its "
                f"recorded driver PID now belongs to a different process) — nothing "
                f"was stopped or disarmed. Check `/dispatch status {state.run_id}`."
            ),
        )

    # A real BlarAI swap was mid-flight and its driver is GONE -> converge to
    # "14B up, 30B down". The destructive arms fire ONLY for phases at which OUR
    # swap could have armed the sentinel / loaded the 30B (#902 allowlist).
    if state.phase in _PHASES_OVMS_POSSIBLE:
        # 1. DISARM the fleet's watchdog sentinel that OUR start-llm armed (so the
        #    watchdog can't re-raise OUR 30B). The file belongs to the fleet; the
        #    phase allowlist above is what proves OUR swap was the arming actor.
        try:
            sentinel_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

        # 2. STOP the 30B OUR swap loaded (idempotent; fail-soft — must not block boot).
        try:
            stop_ovms()
        except Exception:  # noqa: BLE001 — a stop failure must not block the 14B boot
            pass

    # 3. RECONCILE the run.
    summary = bool(
        state.run_id and (runs_dir / state.run_id / "SUMMARY.txt").exists()
    )
    if summary:
        message = (
            f"Coding dispatch {state.run_id} finished while the assistant was "
            f"swapped out — see its result (or `/dispatch status {state.run_id}`)."
        )
    else:
        message = (
            f"Coding dispatch {state.run_id} was interrupted by a restart. Its "
            f"completed tasks are recorded; it is resumable — re-dispatch or check "
            f"`/dispatch status {state.run_id}`."
        )

    # Mark RECOVERED so a second boot is a clean no-op (idempotent convergence).
    # The durable record is SUMMARY.txt + `/dispatch status`, so a missed surface
    # here is recoverable; we do NOT block on the AO confirming it showed the line.
    write_swap_state(state.with_phase(PHASE_RECOVERED), path=swap_state_path)
    return ReconcileResult(
        in_flight=True,
        run_id=state.run_id,
        session_id=state.session_id,
        summary_available=summary,
        message=message,
    )
