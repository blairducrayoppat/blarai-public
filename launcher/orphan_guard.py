r"""Orphan-guard spawned children via a Windows Job Object (Vikunja #652, deliverable B).

What this module is for
-----------------------
The launcher spawns child processes: the WinUI surface (de-elevated to Medium
integrity via ``CreateProcessWithTokenW`` — ``launcher/process_launch.py``) and
the Windows-Hello helper (``shared/security/hello_verifier.py``,
``subprocess.run``). If the launcher dies abnormally (crash, kill, power event),
a child spawned without an orphan-guard can survive as an *orphan* — a windowed
UI with no backend, or a stuck helper.

A Windows **Job Object** with ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` solves this
at the kernel level: every process assigned to the job is terminated when the
job's last handle closes. Because the launcher process holds the only handle,
that "last handle closes" event fires when the launcher exits **for any reason**,
including an abnormal exit that no atexit/finally can cover. Assigning the
children to such a job means they can never outlive the launcher.

What this module deliberately does NOT do
-----------------------------------------
* It does **not** set ``JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 1``. Capping the job to
  one active process would break multi-child spawning (the launcher legitimately
  runs the WinUI surface *and*, on each ESCALATE, a Hello-helper subprocess).
  The only limit set is kill-on-close.
* It does **not** gate the boot path. Per ADR-019's fail-safe posture, the WinUI
  surface must ALWAYS come up. Assigning the de-elevated WinUI child to a job can
  conflict with ``CreateProcessWithTokenW`` (the child is created via the
  secondary-logon service and may already sit in a system-managed job; job
  *nesting* has kernel limits and some hosts refuse the assignment). So
  :func:`assign_process_to_job` is **best-effort**: if the assignment fails, it
  logs and returns ``False`` — the caller proceeds with the child unguarded
  rather than risk the surface. The orphan-guard is a safety net, never a gate.

Design posture — **fail-safe, never fail-boot** (matches ``process_launch.py``)
-------------------------------------------------------------------------------
Every step is guarded. Job creation returns ``None`` on any failure (non-Windows,
ctypes/kernel32 load failure, ``CreateJobObject`` error) and the caller simply
skips orphan-guarding. Assignment returns ``False`` on any failure. Nothing here
raises into the boot path. On a non-Windows host the whole module is a logged
no-op.

ctypes idiom mirrors ``launcher/process_launch.py`` / ``shared/security/
tpm_sealer.py``: ``argtypes`` / ``restype`` set on every bound function so 64-bit
handles are not truncated.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Win32 constants.
# ---------------------------------------------------------------------------
# JOBOBJECTINFOCLASS.JobObjectExtendedLimitInformation
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS: int = 9
# JOB_OBJECT_LIMIT flags (winnt.h).
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: int = 0x00002000


# ---------------------------------------------------------------------------
# ctypes structures (winnt.h) — sized for both 32- and 64-bit via native types.
# ---------------------------------------------------------------------------
class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
        ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


# ---------------------------------------------------------------------------
# Lazy kernel32 loader (configured argtypes/restype).
# ---------------------------------------------------------------------------
_K32: object = None


def _k32():
    """Lazily load + configure ``kernel32``; ``None`` off-Windows / on load failure."""
    global _K32
    if sys.platform != "win32":
        return None
    if _K32 is not None:
        return _K32
    try:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
    except OSError as exc:  # pragma: no cover - platform specific
        logger.warning("orphan-guard: could not load kernel32 (%s)", exc)
        return None

    k.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    k.CreateJobObjectW.restype = wintypes.HANDLE

    k.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,            # hJob
        ctypes.c_int,               # JobObjectInformationClass
        wintypes.LPVOID,            # lpJobObjectInformation
        wintypes.DWORD,             # cbJobObjectInformationLength
    ]
    k.SetInformationJobObject.restype = wintypes.BOOL

    k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k.AssignProcessToJobObject.restype = wintypes.BOOL

    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE

    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.CloseHandle.restype = wintypes.BOOL

    _K32 = k
    return _K32


def create_kill_on_close_job() -> int | None:
    """Create a Job Object that kills its members when the job's last handle closes.

    Creates an anonymous (unnamed) Job Object and sets
    ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` — and **only** that flag (no
    ``ACTIVE_PROCESS`` cap, so multiple children may be assigned). The launcher
    holds the returned handle for its whole lifetime; when the launcher exits for
    any reason, the handle closes and every assigned child is terminated.

    **FAIL-SAFE:** returns the raw job handle (an ``int``) on success, or
    ``None`` on any failure (non-Windows, kernel32 load failure,
    ``CreateJobObject`` / ``SetInformationJobObject`` error). The caller treats
    ``None`` as "orphan-guard unavailable" and proceeds without it. Never raises.

    Returns:
        The Job Object handle as an ``int``, or ``None`` if a kill-on-close job
        could not be created.
    """
    k = _k32()
    if k is None:
        return None

    try:
        job = k.CreateJobObjectW(None, None)
        if not job:
            err = ctypes.get_last_error()
            logger.warning("orphan-guard: CreateJobObject failed (err %s)", err)
            return None

        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = k.SetInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            err = ctypes.get_last_error()
            logger.warning(
                "orphan-guard: SetInformationJobObject(KILL_ON_JOB_CLOSE) failed "
                "(err %s); closing job, proceeding unguarded.",
                err,
            )
            try:
                k.CloseHandle(job)
            except Exception:  # noqa: BLE001
                pass
            return None

        logger.info(
            "orphan-guard: created kill-on-close Job Object (children assigned to "
            "it cannot outlive the launcher)."
        )
        return int(job)
    except Exception as exc:  # noqa: BLE001 — fail-safe: never raise into boot
        logger.warning("orphan-guard: error creating Job Object (%r)", exc)
        return None


def assign_process_to_job(job_handle: int | None, process_handle: int) -> bool:
    """Assign a process (by handle) to *job_handle*; best-effort, degrades cleanly.

    Calls ``AssignProcessToJobObject``. This is the step that can legitimately
    fail for the de-elevated WinUI child: ``CreateProcessWithTokenW`` runs the
    child via the secondary-logon service, which may already place it in a
    system-managed job, and job nesting has kernel limits — some hosts refuse the
    assignment. That is acceptable: the orphan-guard is a safety net, NOT a gate.

    **FAIL-SAFE:** returns ``True`` only if the assignment succeeded; returns
    ``False`` on a ``None`` job (orphan-guard unavailable), a falsy process
    handle, or any API/exception failure — the caller logs and proceeds with the
    child unguarded so the surface always comes up. Never raises.

    Args:
        job_handle: the Job Object handle from :func:`create_kill_on_close_job`,
            or ``None`` if no job was created.
        process_handle: the child's process handle (e.g.
            ``_HandleProc._h`` / ``Popen._handle``) as an ``int``.

    Returns:
        ``True`` if the process was assigned to the job; ``False`` otherwise.
    """
    if job_handle is None:
        return False
    if not process_handle:
        logger.info("orphan-guard: no process handle to assign; skipping.")
        return False

    k = _k32()
    if k is None:
        return False

    try:
        ok = k.AssignProcessToJobObject(
            wintypes.HANDLE(job_handle), wintypes.HANDLE(process_handle)
        )
        if not ok:
            err = ctypes.get_last_error()
            logger.warning(
                "orphan-guard: AssignProcessToJobObject failed (err %s) — the "
                "child runs UNGUARDED (degraded gracefully; surface unaffected). "
                "This is expected when CreateProcessWithTokenW already placed the "
                "child in a system job that does not permit nesting.",
                err,
            )
            return False
        logger.info(
            "orphan-guard: child assigned to kill-on-close job (cannot outlive "
            "the launcher)."
        )
        return True
    except Exception as exc:  # noqa: BLE001 — fail-safe: never block the surface
        logger.warning(
            "orphan-guard: error assigning child to job (%r) — child runs "
            "unguarded (degraded gracefully).",
            exc,
        )
        return False
