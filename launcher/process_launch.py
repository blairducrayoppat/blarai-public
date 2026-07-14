"""De-elevated child-process launch for the WinUI surface (ADR-019).

The launcher self-elevates for Hyper-V VM management (``vm_manager`` needs
Administrator rights for ``Start-VM`` / ``Stop-VM``). The WinUI surface does
**not** need admin — but it was being spawned as an ordinary child of the
elevated launcher, so it inherited the launcher's HIGH integrity level. That
broke file attach two ways:

  * the Win32 open dialog could not reach OneDrive cloud-only files (an
    elevated process cannot drive the shell's Files-On-Demand hydration), and
  * Windows UIPI (User Interface Privilege Isolation) blocked drag-drop from
    medium-integrity Explorer into the high-integrity window.

The fix keeps the launcher elevated (Hyper-V is unchanged) but spawns the UI
child at MEDIUM integrity with a *filtered* token — the same shape Windows
itself mints for the standard-user side of a split UAC token: Administrators
demoted to deny-only, privileges stripped, integrity dropped to Medium. The
child then runs exactly as it would have had BlarAI never elevated, so
Explorer ↔ UI is a same-integrity boundary and the shell namespace (cloud
files, drag-drop) is reachable.

Mechanism (each step verified on the Arc 140V host, 2026-06-03):
  1. Duplicate the launcher's primary token.
  2. ``CreateRestrictedToken`` with ``DISABLE_MAX_PRIVILEGE`` + the
     Administrators SID in *SidsToDisable* → privileges stripped to
     ``SeChangeNotify``, admin group becomes use-for-deny-only.
  3. Stamp the token's mandatory label down to Medium (S-1-16-8192).
  4. Launch via ``CreateProcessWithTokenW`` (needs only ``SeImpersonate``,
     which the elevated launcher holds — ``CreateProcessAsUser`` rejects a
     filtered token with ERROR_PRIVILEGE_NOT_HELD, and pywin32 does not expose
     ``CreateProcessWithTokenW``, so it is bound here via ctypes).

This is the privilege-boundary lesson (BUILD_JOURNAL #11) applied in reverse:
the integrity the UI runs at must cross the elevation boundary, so it is
carried by a channel defined to cross it — the process token — not left to
inheritance.

Design posture: **fail-safe, never fail-dead.** Every de-elevation step is
guarded; if any fails the launcher falls back (filtered token → plain Medium
label → ordinary elevated launch) so the surface always comes up. The worst
case is the old behavior (attach of cloud files / drag-drop degraded), never a
dead window. Which path was taken — and the integrity actually achieved — is
logged so the live-verify screen confirms it in one read (BUILD_JOURNAL #16 —
instrument the layer the tests cannot reach).
"""

from __future__ import annotations

import ctypes
import logging
import subprocess
import time
from ctypes import wintypes
from typing import Any

logger = logging.getLogger(__name__)

# Mandatory-integrity RIDs (winnt.h SECURITY_MANDATORY_*_RID); the RID is the
# last sub-authority of the integrity SID. Named for human-readable logs.
_RID_LOW = 0x1000
_RID_MEDIUM = 0x2000
_RID_HIGH = 0x3000
_RID_SYSTEM = 0x4000
_MEDIUM_SID_STR = "S-1-16-8192"  # SECURITY_MANDATORY_MEDIUM_RID (0x2000)

# Win32 constants
_TOKEN_INTEGRITY_LEVEL = 25  # TOKEN_INFORMATION_CLASS.TokenIntegrityLevel
_SE_GROUP_INTEGRITY = 0x20
_DISABLE_MAX_PRIVILEGE = 0x1  # CreateRestrictedToken flag
_WIN_BUILTIN_ADMINISTRATORS_SID = 26  # WELL_KNOWN_SID_TYPE.WinBuiltinAdministratorsSid
_INFINITE = 0xFFFFFFFF

# WaitForSingleObject return codes (winbase.h) — read by the child-wait loop.
_WAIT_OBJECT_0 = 0x00000000  # the handle is signaled: the child has exited
_WAIT_TIMEOUT = 0x00000102  # the supervisory chunk elapsed; the child is still up
_WAIT_FAILED = 0xFFFFFFFF  # the wait itself failed (treat the child as gone)

#: Supervisory wake cadence for the launcher's WinUI child-wait (#812 / AUDIT-13).
#: The child-wait blocks the launcher's MAIN thread until the WinUI surface
#: exits; the previous single unconditional ``WaitForSingleObject(_INFINITE)``
#: made launcher liveness hostage to a wedged child handle with no supervisory
#: wake. The wait now loops in bounded chunks of this length instead, so it can
#: never sit in one un-woken INFINITE syscall. This is a POLL CADENCE, not an
#: abort budget — with ``timeout=None`` (the launcher's call) the wait still
#: blocks until the child exits. REGISTERED: ``shared/timeout_registry.py``.
_WAIT_SUPERVISORY_INTERVAL_S = 5.0


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


def _integrity_rid_name(rid: int | None) -> str:
    if rid is None:
        return "unknown"
    return {
        _RID_LOW: "Low",
        _RID_MEDIUM: "Medium",
        _RID_HIGH: "High",
        _RID_SYSTEM: "System",
    }.get(rid, f"0x{rid:x}")


def _token_integrity_rid(token: Any) -> int | None:
    try:
        import win32security

        sid, _attrs = win32security.GetTokenInformation(token, _TOKEN_INTEGRITY_LEVEL)
        return sid.GetSubAuthority(sid.GetSubAuthorityCount() - 1)
    except Exception:  # noqa: BLE001 — diagnostics only
        return None


def _current_integrity_name() -> str:
    """Human-readable integrity level of the *current* process (for logs)."""
    try:
        import win32api
        import win32con
        import win32security

        tok = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(), win32con.TOKEN_QUERY
        )
        return _integrity_rid_name(_token_integrity_rid(tok))
    except Exception:  # noqa: BLE001
        return "unknown"


def _is_elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return False


class _HandleProc:
    """Minimal ``subprocess.Popen``-shaped wrapper over a raw process handle.

    Exposes only the surface ``_run_winui_surface`` uses: :attr:`pid`,
    :attr:`returncode`, and :meth:`wait` — a drop-in for the previous
    ``subprocess.Popen([exe])``. Backed by a raw Win32 HANDLE, waited on via
    ctypes ``kernel32`` (ctypes argtypes are set so 64-bit handles are not
    truncated).
    """

    def __init__(self, h_process: int, pid: int) -> None:
        self._h = h_process
        self.pid = pid
        self.returncode: int | None = None

    def wait(self, timeout: float | None = None) -> int:
        """Block until the child exits; raise on *timeout* if one is given.

        Drop-in for ``subprocess.Popen.wait(timeout=None)``. The wait is a
        BOUNDED-CHUNK poll loop (#812 / AUDIT-13): instead of one unconditional
        ``WaitForSingleObject(_INFINITE)`` — which wedged the launcher's main
        thread on a stuck child handle with no supervisory wake — it waits in
        ``_WAIT_SUPERVISORY_INTERVAL_S`` chunks and re-checks each lap. With the
        default ``timeout=None`` the semantics are UNCHANGED (block until the
        child exits, return its code); a supplied ``timeout`` (seconds) bounds
        the wait and raises ``subprocess.TimeoutExpired`` on expiry — matching
        Popen so a supervisory caller can impose a real deadline.
        """
        # Popen-parity: a completed wait is cached, so re-calling never re-closes
        # the (already-closed) handle.
        if self.returncode is not None:
            return self.returncode

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k32.WaitForSingleObject.restype = wintypes.DWORD
        k32.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        k32.GetExitCodeProcess.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.CloseHandle.restype = wintypes.BOOL

        chunk_ms = max(1, int(_WAIT_SUPERVISORY_INTERVAL_S * 1000))
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            wait_ms = chunk_ms
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    # Handle intentionally NOT closed — the child is still up and
                    # a caller may wait() again (Popen.wait(timeout) semantics).
                    raise subprocess.TimeoutExpired(
                        cmd=f"winui pid {self.pid}", timeout=timeout
                    )
                wait_ms = min(chunk_ms, max(1, int(remaining * 1000)))
            result = int(k32.WaitForSingleObject(self._h, wait_ms))
            if result == _WAIT_OBJECT_0:
                break
            if result == _WAIT_FAILED:
                err = ctypes.get_last_error()
                logger.warning(
                    "WinUI child-wait: WaitForSingleObject failed (err %s); "
                    "treating child pid %s as exited.",
                    err,
                    self.pid,
                )
                break
            # _WAIT_TIMEOUT → the supervisory chunk elapsed; loop and re-check.

        code = wintypes.DWORD()
        k32.GetExitCodeProcess(self._h, ctypes.byref(code))
        self.returncode = int(code.value)
        k32.CloseHandle(self._h)
        return self.returncode


def _build_filtered_medium_token() -> Any | None:
    """Build a primary, Medium-integrity, de-privileged token, or None.

    Preferred shape mirrors the UAC standard-user token (admin deny-only,
    privileges stripped). Falls back to a plain Medium-label duplicate if
    ``CreateRestrictedToken`` is unavailable, then to None.
    """
    import win32api
    import win32con
    import win32security
    import pywintypes

    try:
        proc_token = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(),
            win32con.TOKEN_QUERY
            | win32con.TOKEN_DUPLICATE
            | win32con.TOKEN_ASSIGN_PRIMARY,
        )
        dup = win32security.DuplicateTokenEx(
            proc_token,
            win32security.SecurityImpersonation,
            win32con.MAXIMUM_ALLOWED,
            win32security.TokenPrimary,
        )
    except pywintypes.error as exc:
        logger.warning("De-elevation: could not duplicate launcher token (%s)", exc)
        return None

    medium_sid = win32security.ConvertStringSidToSid(_MEDIUM_SID_STR)

    # Preferred: filter to the standard-user shape (admin → deny-only,
    # privileges stripped), then drop integrity to Medium.
    try:
        admins = win32security.CreateWellKnownSid(_WIN_BUILTIN_ADMINISTRATORS_SID)
        token = win32security.CreateRestrictedToken(
            dup, _DISABLE_MAX_PRIVILEGE, [(admins, 0)], [], []
        )
        win32security.SetTokenInformation(
            token, _TOKEN_INTEGRITY_LEVEL, (medium_sid, _SE_GROUP_INTEGRITY)
        )
        logger.info("De-elevation: built filtered standard-user token (admin deny-only)")
        return token
    except pywintypes.error as exc:
        logger.info(
            "De-elevation: CreateRestrictedToken unavailable (%s); using Medium "
            "label only",
            exc,
        )

    # Fallback: just stamp the duplicated token's integrity down to Medium.
    try:
        win32security.SetTokenInformation(
            dup, _TOKEN_INTEGRITY_LEVEL, (medium_sid, _SE_GROUP_INTEGRITY)
        )
        return dup
    except pywintypes.error as exc:
        logger.warning("De-elevation: could not set Medium integrity (%s)", exc)
        return None


def launch_medium_integrity(
    app_name: str, cmd_line: str | None = None
) -> _HandleProc | None:
    """Launch *app_name* at Medium integrity via a filtered token.

    Returns a proc-like handle, or None if the de-elevation primitive was
    unavailable for any reason (caller falls back to an ordinary launch).
    """
    try:
        import win32security  # noqa: F401 — ensure pywin32 present before token work
    except ImportError as exc:
        logger.warning("De-elevation: pywin32 unavailable (%s)", exc)
        return None

    token = _build_filtered_medium_token()
    if token is None:
        return None

    rid = _token_integrity_rid(token)

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.CreateProcessWithTokenW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPCWSTR,
        ctypes.POINTER(_STARTUPINFOW),
        ctypes.POINTER(_PROCESS_INFORMATION),
    ]
    advapi32.CreateProcessWithTokenW.restype = wintypes.BOOL

    startup = _STARTUPINFOW()
    startup.cb = ctypes.sizeof(_STARTUPINFOW)
    info = _PROCESS_INFORMATION()
    cmd_buf = ctypes.create_unicode_buffer(cmd_line) if cmd_line else None

    ok = advapi32.CreateProcessWithTokenW(
        int(token),  # hToken — token kept alive for the duration of this call
        0,  # dwLogonFlags
        app_name,
        cmd_buf,
        0,  # dwCreationFlags
        None,  # lpEnvironment (inherit caller's; same user/session)
        None,  # lpCurrentDirectory
        ctypes.byref(startup),
        ctypes.byref(info),
    )
    if not ok:
        err = ctypes.get_last_error()
        logger.warning("De-elevation: CreateProcessWithTokenW failed (err %s)", err)
        return None

    # Close the thread handle; keep the process handle for wait().
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL
    if info.hThread:
        k32.CloseHandle(info.hThread)

    logger.info(
        "De-elevation: launched pid %s at %s integrity (launcher is %s)",
        info.dwProcessId,
        _integrity_rid_name(rid),
        _current_integrity_name(),
    )
    return _HandleProc(info.hProcess, int(info.dwProcessId))


def launch_winui(exe_path: str) -> Any:
    """Launch the WinUI surface, de-elevated when the launcher is elevated.

    Always returns a ``Popen``-shaped object (``.wait()`` / ``.returncode``).
    When elevated, attempts the Medium-integrity launch and falls back to an
    ordinary (inherited-integrity) launch if the primitive fails — so the UI
    always comes up. Raises only if even the ordinary launch fails.
    """
    if _is_elevated():
        proc = launch_medium_integrity(exe_path, f'"{exe_path}"')
        if proc is not None:
            return proc
        logger.warning(
            "De-elevation unavailable; launching WinUI elevated. Attach of "
            "OneDrive cloud-only files and drag-drop may not work."
        )
    else:
        logger.info(
            "Launcher not elevated; launching WinUI as a normal child "
            "(already Medium integrity)."
        )
    return subprocess.Popen([exe_path])
