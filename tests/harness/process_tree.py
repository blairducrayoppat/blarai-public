"""Process-tree teardown helper for WinUI harness tests (#630, Sprint 18).

WHY THIS EXISTS
===============
The WinUI harness launches BlarAI.Desktop.exe via ``subprocess.Popen``.  That
.NET process immediately spawns a Python backend child that binds AO loopback
port 5001.  A bare ``proc.terminate()`` (the prior teardown) kills only the
.NET parent; the Python child is re-parented to PID 1 / the OS and continues
holding port 5001.  On the next gate run, the ~7 boot-cascade and
production-boot tests that guard on the port being free all defensively skip
("a live BlarAI instance?"), silently degrading coverage from 2342/0 to
~2333/9 with zero test-suite signal.

APPROACH
========
psutil 7.x is already in the project venv, so we use
``psutil.Process(pid).children(recursive=True)`` to collect the entire
descendant tree, then SIGTERM each child before terminating the parent.  The
``taskkill /T /F /PID`` alternative is equally effective but less portable
and harder to unit-test; psutil is preferred while it's available.

All operations are wrapped in broad exception handling and best-effort only —
this must never raise out of a ``finally`` block.
"""

from __future__ import annotations

import subprocess


def terminate_process_tree(pid: int) -> None:
    """Terminate *pid* and all its descendant processes, best-effort.

    Tries psutil first (cross-platform, already a project dep).  Falls back
    to ``taskkill /T /F`` on Windows if psutil is absent or raises.  Never
    raises — safe to call from a ``finally`` block.

    Parameters
    ----------
    pid:
        The PID of the root process to terminate (the Popen child).
    """
    try:
        _terminate_via_psutil(pid)
    except Exception:  # noqa: BLE001
        # psutil absent or failed — fall back to taskkill on Windows.
        _terminate_via_taskkill(pid)


# ---------------------------------------------------------------------------
# Implementation — psutil path
# ---------------------------------------------------------------------------


def _terminate_via_psutil(pid: int) -> None:
    """Terminate the process tree rooted at *pid* using psutil.

    Raises if psutil is unavailable or the root PID lookup fails (caller
    catches and falls back).
    """
    import psutil  # type: ignore[import]

    try:
        root = psutil.Process(pid)
    except psutil.NoSuchProcess:
        # Process already gone — nothing to do.
        return

    # Collect descendants first, while the parent is still alive to anchor
    # the tree.  recursive=True walks grandchildren too.
    children: list[psutil.Process] = root.children(recursive=True)

    # Terminate leaves first (reverse BFS order), then the root.
    for child in reversed(children):
        try:
            child.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    try:
        root.terminate()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    # Best-effort wait so the OS reaps the PIDs.
    _wait_all([root, *children], timeout_s=3.0)


def _wait_all(procs: list[object], timeout_s: float) -> None:
    """Wait for all *procs* to exit; suppress any error."""
    try:
        import psutil  # type: ignore[import]

        _, alive = psutil.wait_procs(procs, timeout=timeout_s)  # type: ignore[arg-type]
        for p in alive:
            try:
                p.kill()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Implementation — taskkill fallback (Windows only)
# ---------------------------------------------------------------------------


def _terminate_via_taskkill(pid: int) -> None:
    """Terminate the process tree via ``taskkill /T /F /PID``.

    Best-effort — swallows all errors.
    """
    try:
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            capture_output=True,
            timeout=10,
        )
    except Exception:  # noqa: BLE001
        pass
