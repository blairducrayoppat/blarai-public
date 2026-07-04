"""Guaranteed-termination step-aside watchdog (#670 Phase-B run-1 fix C).

The model-swap step-aside asks the launcher's MAIN thread to exit by raising
``KeyboardInterrupt`` via ``_thread.interrupt_main()`` (the AO runs on a daemon thread
and cannot ``sys.exit`` the process). On the run-1 box that interrupt was never
delivered -- the WinUI native event loop was parked -- so the old launcher never
exited, the swap driver's settle (which waits on ``old_pid`` death) timed out, and the
NEVER-ZERO relaunch fired anyway -> two launchers -> the cert stomp.

The load-bearing fix is GUARANTEED TERMINATION, not a wider window: a daemon watchdog
forces the process down if the graceful interrupt+teardown does not complete. Graceful
is still attempted first (clean 14B unload + GPU release + VM stop); the forceful
``os._exit`` is the backstop. A forceful exit SKIPS cleanup -> the OS reclaims GPU
memory on process death (verified at the re-run, not assumed) and the single-instance
lock is left stale for the relaunch to reclaim.

Widening the settle window only helps a teardown that is slow-but-completes; it cannot
help an interrupt that was never delivered. So the watchdog distinguishes the two via a
"cleanup started" signal and forces immediately for the wedged case.

``should_force_exit`` is pure (injected elapsed + cleanup-started) -> unit-tested; the
real thread/clock and the actual ``os._exit`` are the thin live-only parts.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

# LIVE-TUNABLE budgets (#670 run-1). Defaults coordinate with the swap driver's 60s
# settle window: force well before the driver gives up. Pin the real settle cause
# on-hardware before tuning these.
DEFAULT_DELIVER_GRACE_S: float = float(
    os.environ.get("BLARAI_STEP_ASIDE_DELIVER_GRACE_S", "4.0")
)
DEFAULT_TEARDOWN_MAX_S: float = float(
    os.environ.get("BLARAI_STEP_ASIDE_TEARDOWN_MAX_S", "30.0")
)
# How long the watchdog waits for the graceful 14B GPU-unload to complete before it
# hard-exits anyway (#670 run-2 fix 2a). A hung unload must NEVER defeat termination.
DEFAULT_UNLOAD_GRACE_S: float = float(
    os.environ.get("BLARAI_STEP_ASIDE_UNLOAD_GRACE_S", "10.0")
)


def _bounded_unload(unload: Callable[[], object], timeout_s: float) -> bool:
    """Run ``unload()`` on a daemon thread and wait up to ``timeout_s``; return whether it
    finished. The graceful 14B GPU-release (#670 run-2) runs here BEFORE the hard exit so
    the 30B loads onto a clean GPU instead of relying on the OS to reclaim the 14B's
    Level-Zero context on its own schedule (run-2 fit by timing luck). Bounded in its own
    thread so a hung unload can never block the force-exit guarantee; exceptions swallowed."""
    done = threading.Event()

    def _wrap() -> None:
        try:
            unload()
        except Exception:  # noqa: BLE001 — best-effort; never propagate into the watchdog
            pass
        finally:
            done.set()

    threading.Thread(target=_wrap, name="blarai-step-aside-gpu-unload", daemon=True).start()
    return done.wait(timeout=timeout_s)


def should_force_exit(
    *,
    elapsed_s: float,
    cleanup_started: bool,
    deliver_grace_s: float,
    teardown_max_s: float,
) -> bool:
    """Whether the watchdog must force-terminate the process NOW.

    * interrupt NOT delivered (``cleanup_started`` is False) and the short
      ``deliver_grace_s`` has passed -> force now. This is the ONLY remedy for a
      never-delivered interrupt; no settle-window widening can wake a parked main thread.
    * delivered but slow (cleanup running) -> allow up to ``teardown_max_s`` for a real
      graceful teardown (14B unload + GPU release + VM stop) to finish on its own; force
      only as the final backstop if it overruns.
    """
    if not cleanup_started and elapsed_s >= deliver_grace_s:
        return True
    if elapsed_s >= teardown_max_s:
        return True
    return False


def force_exit_watchdog(
    cleanup_started: Callable[[], bool],
    *,
    unload_gpu: "Callable[[], object] | None" = None,
    unload_grace_s: float = DEFAULT_UNLOAD_GRACE_S,
    deliver_grace_s: float = DEFAULT_DELIVER_GRACE_S,
    teardown_max_s: float = DEFAULT_TEARDOWN_MAX_S,
    poll_s: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    hard_exit: Callable[[int], None] = os._exit,
    run_unload: Callable[[Callable[[], object], float], bool] = _bounded_unload,
) -> None:
    """Poll until :func:`should_force_exit`, then GRACEFULLY release the 14B GPU and
    hard-exit the process.

    Run as a daemon during a step-aside: on a clean graceful exit the interpreter
    shutdown reaps this thread before it fires; on a wedge (the confirmed WinUI case —
    ``interrupt_main`` never woke the main thread) it is the only thread making progress.
    Before the hard exit it runs ``unload_gpu`` (#670 run-2 fix 2a) so the 14B's GPU
    context is released for the incoming 30B instead of left to the OS's reclaim schedule;
    bounded so it can't defeat termination. Clock/sleep/exit/unload injected for tests.
    """
    start = monotonic()
    while True:
        elapsed = monotonic() - start
        if should_force_exit(
            elapsed_s=elapsed,
            cleanup_started=cleanup_started(),
            deliver_grace_s=deliver_grace_s,
            teardown_max_s=teardown_max_s,
        ):
            if unload_gpu is not None:
                # GRACEFUL 14B GPU release before the hard exit — the load-bearing fix
                # (run-2: os._exit alone left the GPU for the OS to reclaim on its own
                # schedule; the 30B fit by timing luck). Bounded; never blocks the exit.
                released = run_unload(unload_gpu, unload_grace_s)
                logger.critical(
                    "Step-aside: 14B GPU-unload before force-exit %s (#670).",
                    "completed" if released else f"did not finish in {unload_grace_s:.0f}s",
                )
            logger.critical(
                "Step-aside watchdog forcing termination (#670): elapsed=%.1fs "
                "cleanup_started=%s — graceful exit did not complete; the relaunch "
                "reclaims the stale lock.",
                elapsed,
                cleanup_started(),
            )
            hard_exit(0)
            return
        sleep(poll_s)


def start_force_exit_watchdog(
    cleanup_started: Callable[[], bool],
    *,
    unload_gpu: "Callable[[], object] | None" = None,
) -> threading.Thread:
    """Spawn the daemon force-exit watchdog for a step-aside; returns the started thread.

    ``unload_gpu`` (the 14B GPU release, #670 run-2 fix 2a) runs bounded before the hard
    exit so the incoming 30B loads onto a clean GPU."""
    t = threading.Thread(
        target=force_exit_watchdog,
        args=(cleanup_started,),
        kwargs={"unload_gpu": unload_gpu},
        name="blarai-step-aside-watchdog",
        daemon=True,
    )
    t.start()
    return t
