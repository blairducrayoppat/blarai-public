"""Blessed Windows process-spawn helpers — the learned rules, encoded once (#774).

WHY THIS EXISTS
===============
Spawning child processes on Windows has cost this project at least five separate
paid incidents, each fixed locally and each carrying its lesson only in a
docstring at the fix site.  The rules kept being re-discovered one scar at a
time.  This module is the single blessed surface: a small typed API where every
rule carries the incident that justified it (timeout-registry style, per lesson
217 — a value/rule class that has earned its scars gets a registered home).

Nothing here is wired into a live script yet — existing spawn sites migrate
deliberately, later.  The conformance suite (``shared/tests/test_procspawn.py``)
is the positive control (2026-07-09 lesson: a verdict-issuing instrument needs a
positive control): each blessed shape asserts its OBSERVABLE END PROPERTY on a
real child process, never the flag at the spawn site (lesson 219).

THE RULES → THE INCIDENTS
=========================
R1  A console-less DETACHED python child must be spawned via the interpreter's
    ``pythonw.exe`` sibling, NOT the venv ``python.exe`` shim.
    *(#761 / lesson 219 — "The flag that worked, one process too early".)*  The
    Windows venv ``.venv\\Scripts\\python.exe`` is a LAUNCHER SHIM that re-spawns
    the base console-subsystem interpreter as a CHILD; ``DETACHED_PROCESS`` on the
    shim does not inherit, so the child — born to a console-less parent — is
    allocated a fresh VISIBLE console the operator can accidentally close.
    ``pythonw.exe`` is GUI-subsystem the whole way down: no console is ever
    allocated, and a Textual launcher takes its proven headless-driver fallback.

R2  NEVER ``CREATE_NO_WINDOW`` on a launcher / Textual / interactive python child.
    *(#761 / lesson 219; FIELD_NOTES venv-shim/pythonw/CREATE_NO_WINDOW triad.)*
    ``CREATE_NO_WINDOW`` means a HIDDEN console, and a hidden console crashed
    Textual on 2026-07-06 ("Driver must be in application mode").  It is safe ONLY
    for NON-interactive console-subsystem children (pwsh / tasklist / git) of a
    console-less parent — where it suppresses the per-child visible console that
    a console-less parent would otherwise force.  Console-at-all vs
    console-hidden are DIFFERENT states: R1 wants none, R2 hides one.

R3  A console-less child spawned with NO explicit std handles may inherit a
    broken-but-present cp1252 stderr and CRASH on its first non-ASCII print.
    *(#761 / lesson 219 second half — the banner-print crash on the first live
    swap-back.)*  Always wire detached/captured children with DEVNULL stdin, a
    UTF-8 sink for stdout/stderr, and ``PYTHONUTF8=1`` + ``PYTHONIOENCODING=utf-8``
    in the child env.  "A stray print is a silent no-op under pythonw" is FALSE
    when the handles are present-but-broken.

R4  A child reading an inherited non-TTY stdin that never reaches EOF blocks
    forever; a parent holding a captured PIPE that the child's grandchildren
    inherit deadlocks at drain.
    *(opencode-run init stall, fleet-lib Invoke-AgentRun 2026-06-18; the
    Tee-Object server-launcher hang, FIELD_NOTES lesson 161; the #759 ACP-spike
    undrained-PIPE dodge.)*  ``run_captured`` feeds DEVNULL (EOF-immediately)
    stdin unless input is given, and drains stdout+stderr to files/buffers with a
    real timeout so a wedged child cannot bleed the budget.

R5  On timeout, kill the whole PROCESS TREE, not just the launched process.
    *(#630 tests/harness/process_tree.py — a bare ``terminate()`` orphaned the
    Python backend child that held port 5001, silently degrading the gate.)*  A
    launcher's grandchildren (OVMS, backends, workers) outlive a parent-only kill.
    ``terminate_process_tree`` here mirrors that proven psutil-first / taskkill-
    fallback walk.

CAVEAT (documented, not an API method): a process's EXIT CODE is not proof its
side effect completed.  ``msedge --screenshot`` hands the write to a DETACHED
worker and the launcher exits 0 ~4s before the PNG lands (capture-app.ps1, pinned
2026-06-26); its ``--screenshot`` also silently no-ops on flag order.  When a
spawn's real deliverable is a side effect, POLL for the end property — do not
trust process exit.  ``run_captured`` reports the launched process's own exit
honestly; it cannot vouch for a detached worker it never sees.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Windows creation flags.  Guarded to 0 off-Windows (``creationflags`` raises on
# POSIX; the live detached/hidden paths are Windows-only by construction, the
# pure resolution/capture paths are cross-platform).
# ---------------------------------------------------------------------------
_DETACHED = 0x00000008 if os.name == "nt" else 0  # DETACHED_PROCESS — no console at all
_NEW_GROUP = 0x00000200 if os.name == "nt" else 0  # CREATE_NEW_PROCESS_GROUP
_BREAKAWAY = 0x01000000 if os.name == "nt" else 0  # CREATE_BREAKAWAY_FROM_JOB
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW — HIDDEN console (R2)


# ---------------------------------------------------------------------------
# R1 — interpreter resolution
# ---------------------------------------------------------------------------


def pythonw_sibling(python_exe: str) -> str:
    """The GUI-subsystem ``pythonw.exe`` beside *python_exe*, else *python_exe*.

    R1 (#761 / lesson 219).  On Windows ``.venv\\Scripts\\python.exe`` is the venv
    LAUNCHER SHIM — it spawns the base console-subsystem interpreter as a CHILD, so
    a ``DETACHED_PROCESS`` spawn is defeated one hop down and the child is allocated
    a fresh VISIBLE console.  ``pythonw.exe`` is GUI-subsystem the whole way down
    (its shim child is ``pythonw`` too): no console is ever allocated.

    Fail-safe: no sibling (POSIX layout, non-standard exe name) -> the original
    interpreter unchanged, never a broken spawn.  Mirrors
    ``shared.fleet.swap_ops.pythonw_sibling`` (the proven live copy); duplicated
    rather than imported to keep this module free of fleet dependencies.
    """
    path = Path(python_exe)
    if path.name.lower() == "python.exe":
        sibling = path.with_name("pythonw.exe")
        if sibling.exists():
            return str(sibling)
    return python_exe


def _is_python_argv0(arg0: str) -> bool:
    """True iff *arg0* names a CPython interpreter this module should R1-resolve."""
    return Path(arg0).name.lower() in ("python.exe", "python", "python3", "python3.exe")


def _child_env(env: "dict[str, str] | None") -> "dict[str, str]":
    """*env* (or the current environment) with the R3 UTF-8 pins forced on.

    R3 (#761 / lesson 219).  ``PYTHONUTF8=1`` + ``PYTHONIOENCODING=utf-8`` guarantee
    the child's stdout/stderr encode UTF-8 rather than inheriting a broken cp1252
    handle that crashes the first non-ASCII print.
    """
    merged = dict(os.environ if env is None else env)
    merged["PYTHONUTF8"] = "1"
    merged["PYTHONIOENCODING"] = "utf-8"
    return merged


# ---------------------------------------------------------------------------
# R1+R3 — detached, console-less spawn (launcher / Textual chains)
# ---------------------------------------------------------------------------


def detached_no_console(
    argv: "list[str]",
    *,
    cwd: "str | Path | None" = None,
    log_path: "str | Path | None" = None,
    env: "dict[str, str] | None" = None,
    breakaway: bool = True,
) -> subprocess.Popen:
    """Spawn *argv* DETACHED with NO console, to OUTLIVE this process (R1+R3).

    For long-lived children that must survive the parent and never present a
    console window — the launcher / Textual chain (``python -m launcher``), swap
    drivers, night-boot.  Encodes:

    * R1 — if ``argv[0]`` is a venv ``python.exe`` shim, it is transparently
      resolved to the ``pythonw.exe`` sibling so the detach is not defeated one
      hop down (the child never gets a fresh visible console).
    * R3 — DEVNULL stdin, a UTF-8 append log for stdout+stderr (or DEVNULL when
      no *log_path*), and the ``PYTHONUTF8``/``PYTHONIOENCODING`` env pins, so the
      console-less child cannot crash on its first non-ASCII print.
    * ``DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`` [``| CREATE_BREAKAWAY_FROM_JOB``].
      NEVER ``CREATE_NO_WINDOW`` here (R2) — a hidden console crashes Textual.

    Deliberately NOT ``CREATE_NO_WINDOW`` (R2).  Returns the ``Popen`` handle; the
    caller owns it (this function does not wait — the child is detached by design).
    """
    resolved = list(argv)
    if resolved and _is_python_argv0(resolved[0]):
        resolved[0] = pythonw_sibling(resolved[0])

    if log_path is not None:
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # UTF-8 append log, errors='replace' so a stray byte never crashes the sink.
        sink = open(log_path, "a", encoding="utf-8", errors="replace")  # noqa: SIM115 — handed to child
        stdout_target: "int | object" = sink
    else:
        sink = None
        stdout_target = subprocess.DEVNULL

    flags = _DETACHED | _NEW_GROUP | (_BREAKAWAY if breakaway else 0)
    popen_kwargs = dict(
        cwd=None if cwd is None else str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=stdout_target,
        stderr=subprocess.STDOUT if sink is not None else subprocess.DEVNULL,
        env=_child_env(env),
        creationflags=flags,
        close_fds=True,
    )
    try:
        return subprocess.Popen(resolved, **popen_kwargs)  # noqa: S603 — caller-owned argv
    except OSError:
        # Not inside a Windows job object -> BREAKAWAY is invalid; retry without it
        # (mirrors the battery boot_launcher_detached fallback).
        if breakaway:
            popen_kwargs["creationflags"] = _DETACHED | _NEW_GROUP
            return subprocess.Popen(resolved, **popen_kwargs)  # noqa: S603
        raise


# ---------------------------------------------------------------------------
# R2 — hidden-console spawn (NON-interactive console children only)
# ---------------------------------------------------------------------------


def hidden_console(
    argv: "list[str]",
    *,
    cwd: "str | Path | None" = None,
    timeout_s: "float | None" = None,
    env: "dict[str, str] | None" = None,
) -> subprocess.CompletedProcess:
    """Run a NON-interactive console-subsystem child with its console HIDDEN (R2).

    For ``pwsh`` / ``tasklist`` / ``git`` children of a console-less parent: without
    ``CREATE_NO_WINDOW`` each would flash its own visible console window (the
    per-child multiplication of the accidental-close hazard).  ``CREATE_NO_WINDOW``
    hides it.

    DO NOT use this for a python launcher / Textual / any interactive child — a
    HIDDEN console crashed Textual on 2026-07-06 (R2 / lesson 219).  For those,
    use :func:`detached_no_console`, which allocates NO console at all.

    Captures stdout+stderr as UTF-8 (``errors='replace'``) and blocks up to
    *timeout_s*.  Returns the ``CompletedProcess``.
    """
    return subprocess.run(  # noqa: S603 — caller-owned argv
        list(argv),
        cwd=None if cwd is None else str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
        env=_child_env(env),
        creationflags=_NO_WINDOW,
        stdin=subprocess.DEVNULL,
    )


# ---------------------------------------------------------------------------
# R4+R5 — captured run with UTF-8, EOF stdin, timeout + tree-kill
# ---------------------------------------------------------------------------


@dataclass
class CapturedResult:
    """The outcome of :func:`run_captured` — the honest, complete record."""

    pid: int
    returncode: "int | None"  # None iff killed on timeout before it could exit
    stdout: str
    stderr: str
    timed_out: bool
    seconds: float
    tree_killed_pids: "list[int]" = field(default_factory=list)


def run_captured(
    argv: "list[str]",
    *,
    cwd: "str | Path | None" = None,
    env: "dict[str, str] | None" = None,
    timeout_s: float,
    input_text: "str | None" = None,
) -> CapturedResult:
    """Run *argv* to completion, capturing stdout/stderr, with R4+R5 guarantees.

    * R3/R4 — UTF-8 decode (``errors='replace'``), the child env UTF-8-pinned, and
      DEVNULL stdin (EOF-immediately) unless *input_text* is supplied.  A child
      that reads an inherited non-TTY stdin therefore never blocks forever
      (the opencode-run init-stall class).
    * R4 — stdout and stderr are drained to the returned strings; the parent never
      holds a PIPE a grandchild could deadlock on (drained via ``communicate``).
    * R5 — on timeout the WHOLE process tree is killed (``terminate_process_tree``),
      not just the launched process, so orphaned grandchildren cannot bleed the
      budget or hold a port.

    Never raises ``TimeoutExpired`` — a timeout is reported as ``timed_out=True``
    with ``returncode=None`` and whatever partial output was captured.  The
    hidden-window flag is applied on Windows so a console child of a console-less
    parent does not flash a window (R2 — safe here: captured, non-interactive).
    """
    import time

    flags = _NO_WINDOW  # captured, non-interactive -> hidden console is safe (R2)
    started = time.monotonic()
    proc = subprocess.Popen(  # noqa: S603 — caller-owned argv
        list(argv),
        cwd=None if cwd is None else str(cwd),
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_child_env(env),
        creationflags=flags,
        close_fds=True,
    )
    timed_out = False
    killed: "list[int]" = []
    try:
        out, err = proc.communicate(input=input_text, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        killed = terminate_process_tree(proc.pid)
        # Drain whatever the (now-dying) child buffered; the pipes are ours to read.
        try:
            out, err = proc.communicate(timeout=5)
        except Exception:  # noqa: BLE001 — best-effort drain after a kill
            out, err = "", ""
    seconds = time.monotonic() - started
    return CapturedResult(
        pid=proc.pid,
        returncode=None if timed_out else proc.returncode,
        stdout=out or "",
        stderr=err or "",
        timed_out=timed_out,
        seconds=seconds,
        tree_killed_pids=killed,
    )


# ---------------------------------------------------------------------------
# R5 — process-tree teardown (mirrors tests/harness/process_tree.py, #630)
# ---------------------------------------------------------------------------


def terminate_process_tree(pid: int) -> "list[int]":
    """Terminate *pid* and all descendants, best-effort; return the PIDs targeted.

    R5 (#630).  A bare ``terminate()`` kills only the named process; its
    grandchildren (a launcher's OVMS/backend, a build's workers) are re-parented to
    the OS and keep running — holding ports, bleeding budget.  psutil-first
    (deterministic, auditable tree walk); ``taskkill /T /F`` fallback when psutil is
    absent.  Never raises — safe from a ``finally`` block.  Mirrors the proven
    ``tests/harness/process_tree.py`` helper; duplicated into ``shared`` so the
    blessed spawn surface carries no test-harness dependency.
    """
    try:
        return _terminate_via_psutil(pid)
    except Exception:  # noqa: BLE001 — psutil absent or failed -> taskkill fallback
        return _terminate_via_taskkill(pid)


def _terminate_via_psutil(pid: int) -> "list[int]":
    import psutil  # type: ignore[import]

    try:
        root = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return []
    children = root.children(recursive=True)
    targeted = [c.pid for c in children] + [pid]
    for child in reversed(children):  # leaves first
        try:
            child.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    try:
        root.terminate()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    # Escalate to kill for anything that ignored SIGTERM, then reap.
    try:
        _, alive = psutil.wait_procs([root, *children], timeout=3.0)
        for p in alive:
            try:
                p.kill()
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass
    return targeted


def _terminate_via_taskkill(pid: int) -> "list[int]":
    try:
        subprocess.run(  # noqa: S603,S607
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            capture_output=True,
            timeout=10,
            creationflags=_NO_WINDOW,
        )
    except Exception:  # noqa: BLE001
        pass
    return [pid]


# The blessed public surface.
__all__ = [
    "CapturedResult",
    "detached_no_console",
    "hidden_console",
    "pythonw_sibling",
    "run_captured",
    "terminate_process_tree",
]
