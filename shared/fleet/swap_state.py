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

    def with_phase(self, phase: str, *, error: str = "", ts: str = "") -> "SwapState":
        """A copy advanced to *phase* (identity + tasks preserved)."""
        return SwapState(
            run_id=self.run_id,
            session_id=self.session_id,
            phase=phase,
            tasks=self.tasks,
            ts=ts or self.ts,
            error=error or self.error,
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
    return SwapState(
        run_id=str(data.get("run_id", "")),
        session_id=str(data.get("session_id", "")),
        phase=str(data.get("phase", "")),
        tasks=list(data.get("tasks", []) or []),
        ts=str(data.get("ts", "")),
        error=str(data.get("error", "")),
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


def reconcile_swap_state(
    *,
    swap_state_path: Path,
    sentinel_path: Path,
    runs_dir: Path,
    stop_ovms: Callable[[], None],
) -> ReconcileResult:
    """Boot-time convergence to "14B up, 30B down". Idempotent; runs every boot.

    1. DISARM: remove the watchdog sentinel FIRST, so a (possibly-registered)
       watchdog cannot resurrect the 30B while the 14B comes back.
    2. FREE: stop any resident OVMS (injected; idempotent; fail-soft — a stop
       failure must never block the 14B boot).
    3. RECONCILE: if a swap was mid-flight, decide report-vs-interrupted from the
       persisted phase + whether ``SUMMARY.txt`` for the run exists, then mark the
       record RECOVERED so a second boot is a clean no-op.

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

    # A real BlarAI swap was mid-flight -> converge to "14B up, 30B down":
    # 1. DISARM the sentinel OUR start-llm armed (so the watchdog can't re-raise OUR 30B).
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
