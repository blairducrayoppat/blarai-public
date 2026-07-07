r"""Strip unused token privileges from the elevated launcher (Vikunja #652, D-a).

What this module is for
-----------------------
BlarAI's launcher (``python -m launcher``) runs **elevated** (Administrator /
High integrity) because it drives Hyper-V (``Start-VM`` / ``Stop-VM`` via
``vm_manager``). An elevated process is handed a large set of *privileges* in
its primary access token — ``SeDebugPrivilege``, ``SeLoadDriverPrivilege``,
``SeTcbPrivilege``, ``SeTakeOwnershipPrivilege``, … — most of which the launcher
never uses. Each enabled-or-enableable privilege is attack surface: a code-exec
foothold inside the launcher inherits the *whole* set, and the launcher hosts,
**in-process**, the Policy Agent + Assistant Orchestrator + the model (they are
``threading.Thread`` workers, not separate processes — see ``launcher/__main__``
``main()``). So the privileges the launcher holds are exactly the privileges any
in-process component (including the LLM tool loop) could abuse.

:func:`strip_unused_privileges` removes every privilege from the current
process token that is **not** on a tight keep-allowlist, using
``AdjustTokenPrivileges`` with ``SE_PRIVILEGE_REMOVED``. Removal is **permanent
for the process lifetime** — a removed privilege cannot be re-enabled by the
process (or anything that later runs inside it), which is strictly stronger than
merely *disabling* it. Called early in ``main()`` (after elevation is settled,
before the PA/AO threads start and before any child is spawned), it shrinks the
ambient authority every downstream component — and every spawned child that
inherits a fresh filtered token — operates under.

Why an ALLOWLIST, not a remove-list
-----------------------------------
We enumerate the token's *actual* privileges and remove everything not
explicitly kept. This is fail-safe and future-proof: a privilege we never
anticipated (a new Windows version, a different elevation path, a policy that
grants more) is removed by default rather than silently surviving a hard-coded
remove-list. The keep-set is the small, audited set of privileges BlarAI's own
code genuinely depends on; everything else goes.

The keep-allowlist (load-bearing — read before changing)
--------------------------------------------------------
* ``SeChangeNotifyPrivilege`` — "bypass traverse checking". Ubiquitous; every
  normal file-path access relies on it. Removing it breaks ordinary path
  traversal across the whole process. KEPT.
* ``SeImpersonatePrivilege`` — **REQUIRED** for ``CreateProcessWithTokenW``,
  which the launcher uses to spawn the WinUI surface de-elevated to Medium
  integrity (ADR-019 §2.3: ``CreateProcessWithTokenW`` "needs only
  ``SeImpersonate``, which the elevated launcher holds"). Remove it and the UI
  de-elevation primitive fails and the surface either does not come up or comes
  up High-integrity (the very regression ADR-019 fixed). KEPT.
* ``SeRestorePrivilege`` — **conservatively KEPT** (see the #637 analysis
  below). BlarAI's DACL hardening only ever sets owner-to-SELF on files it owns,
  which needs only ``WRITE_OWNER`` — so the *expectation* is that neither
  ``SeRestore`` nor ``SeTakeOwnership`` is required. But ``SetNamedSecurityInfo``
  owner/DACL writes are exactly where a missing privilege would silently flip
  #637's defense-in-depth hardening from "applied" to "logged-and-skipped" on a
  no-live-verify deployment, and ``SeRestorePrivilege`` is the privilege that
  governs setting owner + bypassing checks on a restore-style security write. The
  cost of keeping it is one privilege; the cost of wrongly removing it is a
  silently-degraded security control. Conservative-keep-on-doubt wins here.
* ``SeTakeOwnershipPrivilege`` — also **conservatively KEPT**, same rationale: it
  is the other privilege implicated in owner writes (taking ownership of an
  object you do not already have ``WRITE_OWNER`` on). #637 should not need it
  (owner-to-self on owned files), but it is in the owner/DACL blast radius, so it
  is kept rather than risk breaking the hardening helpers on the no-live-verify
  path. Removing it is a future tightening once #637 is live-verified to keep
  working without it.

Everything else the elevated token carries — ``SeDebugPrivilege``,
``SeLoadDriverPrivilege``, ``SeTcbPrivilege``, ``SeBackupPrivilege``,
``SeCreateTokenPrivilege``, ``SeAssignPrimaryTokenPrivilege``,
``SeIncreaseQuotaPrivilege``, ``SeSecurityPrivilege``,
``SeSystemEnvironmentPrivilege``, ``SeManageVolumePrivilege``,
``SeShutdownPrivilege``, ``SeRemoteShutdownPrivilege``, … — is **removed**.
Hyper-V management itself runs out-of-process (``vm_manager`` spawns
``powershell.exe`` for ``Start-VM`` / ``Stop-VM``); the Hyper-V control plane is
gated on the *child's* Administrators group membership and integrity, not on a
privilege the launcher process must itself hold, so stripping these does not
break VM control.

The #637 owner/DACL privilege analysis (why neither is *expected* to be needed)
-------------------------------------------------------------------------------
``shared/security/file_dacl.py`` ``ensure_owner_only_dacl()`` calls
``SetNamedSecurityInfo(path, SE_FILE_OBJECT, OWNER|DACL|PROTECTED_DACL, owner=<
current user SID>, dacl=<owner-only>)`` on each sensitive file (DEK keystore,
``sessions.db``, ``substrate.db``, audit log, ``certs\``). Two privilege facts:

  1. **Setting the DACL** needs ``WRITE_DAC`` on the object — a *permission* the
     owner/creator holds, NOT a token privilege. BlarAI creates these files, so
     it has ``WRITE_DAC``. No privilege involved.
  2. **Setting the owner to the *current user*** needs ``WRITE_OWNER`` — again a
     permission the creator/owner holds. The Windows rule is: you may set an
     object's owner to any SID present in your token as owner-eligible (your own
     user SID always qualifies) *given* ``WRITE_OWNER``. Only setting the owner
     to an *arbitrary* SID you are not, or taking ownership *without*
     ``WRITE_OWNER``, requires ``SeTakeOwnershipPrivilege`` /
     ``SeRestorePrivilege``.

BlarAI sets owner-to-SELF on files it owns → it has ``WRITE_OWNER`` → the
expectation is **neither** privilege is required. We nonetheless keep both
(above) because the failure mode of being wrong is a *silently* weakened
security control on a deployment we do not live-verify, and the price of keeping
them is two privileges out of the ~20 the elevated token carries.

Design posture — **fail-safe, NEVER fail-boot**
-----------------------------------------------
Every step is individually guarded. On ANY error — non-Windows, ``ctypes`` /
``advapi32`` load failure, ``OpenProcessToken`` denial, an ``AdjustTokenPrivileges``
that reports failure for one privilege — the module **logs and continues**. A
hardening step must NEVER prevent BlarAI from starting; the worst acceptable
outcome is "fewer privileges stripped than hoped", never "the launcher did not
boot". If the process is not elevated (a dev run), it simply finds the small
standard privilege set and removes the handful that are not on the allowlist —
harmless and a faithful dry-run of the production path.

This module mirrors the established ``ctypes`` → ``advapi32`` idiom in
``launcher/process_launch.py`` and ``shared/security/tpm_sealer.py``:
``argtypes`` / ``restype`` are set on every bound function so 64-bit handles and
pointers are not truncated to 32 bits.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Keep-allowlist — the ONLY privileges never removed (see module docstring).
# ---------------------------------------------------------------------------
# Compared by canonical privilege name (the stable, machine-independent identity
# — LUIDs are assigned per boot and are NOT stable, so we resolve each LUID to
# its name and compare names).
KEEP_PRIVILEGES: frozenset[str] = frozenset(
    {
        "SeChangeNotifyPrivilege",   # bypass traverse checking — ubiquitous path access
        "SeImpersonatePrivilege",    # CreateProcessWithTokenW WinUI de-elevation (ADR-019 §2.3)
        "SeRestorePrivilege",        # conservatively kept — #637 owner/DACL writes (see docstring)
        "SeTakeOwnershipPrivilege",  # conservatively kept — #637 owner writes (see docstring)
    }
)


# ---------------------------------------------------------------------------
# Win32 constants (winnt.h).
# ---------------------------------------------------------------------------
_TOKEN_QUERY: int = 0x0008
_TOKEN_ADJUST_PRIVILEGES: int = 0x0020

# TOKEN_INFORMATION_CLASS.TokenPrivileges
_TOKEN_PRIVILEGES_CLASS: int = 3

# LUID_AND_ATTRIBUTES.Attributes flags.
_SE_PRIVILEGE_ENABLED: int = 0x00000002
_SE_PRIVILEGE_REMOVED: int = 0x00000004

# AdjustTokenPrivileges returns TRUE but sets last-error to this when it could
# not adjust ALL of the requested privileges (partial / no-op success). We treat
# it as a non-fatal "not fully applied" signal, never as a hard failure.
_ERROR_NOT_ALL_ASSIGNED: int = 1300


# ---------------------------------------------------------------------------
# ctypes structures (winnt.h).  Pointer/handle-safe field types throughout.
# ---------------------------------------------------------------------------
class _LUID(ctypes.Structure):
    _fields_ = [
        ("LowPart", wintypes.DWORD),
        ("HighPart", wintypes.LONG),
    ]


class _LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Luid", _LUID),
        ("Attributes", wintypes.DWORD),
    ]


def _token_privileges_struct(count: int) -> type[ctypes.Structure]:
    """Return a ``TOKEN_PRIVILEGES`` struct type sized for *count* privileges.

    ``TOKEN_PRIVILEGES`` is a variable-length struct (a DWORD count followed by a
    ``LUID_AND_ATTRIBUTES`` array). ctypes needs a concrete type per length, so
    we build one on demand. For the single-privilege adjust calls we use
    ``count == 1``; for parsing the enumeration we read the array out of a raw
    buffer instead (the count is only known at runtime).
    """

    class _TOKEN_PRIVILEGES(ctypes.Structure):
        _fields_ = [
            ("PrivilegeCount", wintypes.DWORD),
            ("Privileges", _LUID_AND_ATTRIBUTES * count),
        ]

    return _TOKEN_PRIVILEGES


# ---------------------------------------------------------------------------
# Lazy advapi32 / kernel32 loader (mirrors tpm_sealer._api()).
# ---------------------------------------------------------------------------
_API: object = None  # cached (advapi32, kernel32) with argtypes/restype configured


def _api():
    """Lazily load + configure ``advapi32`` / ``kernel32``; ``None`` off-Windows.

    Returns ``(advapi32, kernel32)`` with every used function's ``argtypes`` /
    ``restype`` set so 64-bit handles and pointers are not truncated. Returns
    ``None`` on a non-Windows platform or if the DLLs cannot be loaded — callers
    treat ``None`` as "nothing to do" (fail-safe, never raise).
    """
    global _API
    if sys.platform != "win32":
        return None
    if _API is not None:
        return _API

    try:
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except OSError as exc:  # pragma: no cover - platform specific
        logger.warning("privilege-hardening: could not load advapi32/kernel32 (%s)", exc)
        return None

    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE

    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,                    # ProcessHandle
        wintypes.DWORD,                     # DesiredAccess
        ctypes.POINTER(wintypes.HANDLE),    # TokenHandle (out)
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL

    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,                    # TokenHandle
        ctypes.c_int,                       # TokenInformationClass
        wintypes.LPVOID,                    # TokenInformation (out)
        wintypes.DWORD,                     # TokenInformationLength
        ctypes.POINTER(wintypes.DWORD),     # ReturnLength (out)
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL

    advapi32.LookupPrivilegeNameW.argtypes = [
        wintypes.LPCWSTR,                   # lpSystemName
        ctypes.POINTER(_LUID),              # lpLuid
        wintypes.LPWSTR,                    # lpName (out)
        ctypes.POINTER(wintypes.DWORD),     # cchName (in/out)
    ]
    advapi32.LookupPrivilegeNameW.restype = wintypes.BOOL

    advapi32.AdjustTokenPrivileges.argtypes = [
        wintypes.HANDLE,                    # TokenHandle
        wintypes.BOOL,                      # DisableAllPrivileges
        wintypes.LPVOID,                    # NewState (TOKEN_PRIVILEGES*)
        wintypes.DWORD,                     # BufferLength
        wintypes.LPVOID,                    # PreviousState (out, optional)
        ctypes.POINTER(wintypes.DWORD),     # ReturnLength (out, optional)
    ]
    advapi32.AdjustTokenPrivileges.restype = wintypes.BOOL

    _API = (advapi32, kernel32)
    return _API


def _is_elevated() -> bool:
    """Best-effort elevation probe (for the report only; never gates behaviour)."""
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return False


def _lookup_privilege_name(advapi32, luid: _LUID) -> str | None:
    """Resolve a ``LUID`` to its canonical privilege name (e.g. ``SeDebugPrivilege``).

    Returns ``None`` if the name cannot be resolved (the privilege is then left
    untouched — we never remove something we could not positively identify).
    """
    try:
        cch = wintypes.DWORD(0)
        # First call: probe the required buffer length (expected to "fail" with
        # the buffer-too-small signal while filling cch).
        advapi32.LookupPrivilegeNameW(None, ctypes.byref(luid), None, ctypes.byref(cch))
        if cch.value == 0:
            return None
        name_buf = ctypes.create_unicode_buffer(cch.value + 1)
        cch2 = wintypes.DWORD(cch.value + 1)
        ok = advapi32.LookupPrivilegeNameW(
            None, ctypes.byref(luid), name_buf, ctypes.byref(cch2)
        )
        if not ok:
            return None
        return name_buf.value or None
    except Exception:  # noqa: BLE001 — diagnostics path; treat as "unknown"
        return None


def _enumerate_privileges(advapi32, token: wintypes.HANDLE) -> list[tuple[_LUID, str, bool]]:
    """Enumerate the token's privileges as ``(luid, name, enabled)`` triples.

    Reads ``GetTokenInformation(TokenPrivileges)`` into a right-sized buffer and
    walks the ``LUID_AND_ATTRIBUTES`` array. Privileges whose name cannot be
    resolved are skipped (and thus never removed — fail-safe). Returns an empty
    list on any failure.
    """
    size = wintypes.DWORD(0)
    # Probe the required size (this call is expected to "fail" while setting size).
    advapi32.GetTokenInformation(
        token, _TOKEN_PRIVILEGES_CLASS, None, 0, ctypes.byref(size)
    )
    if size.value == 0:
        logger.warning("privilege-hardening: GetTokenInformation reported zero size")
        return []

    buf = (ctypes.c_byte * size.value)()
    ok = advapi32.GetTokenInformation(
        token, _TOKEN_PRIVILEGES_CLASS, buf, size.value, ctypes.byref(size)
    )
    if not ok:
        err = ctypes.get_last_error()
        logger.warning("privilege-hardening: GetTokenInformation failed (err %s)", err)
        return []

    # TOKEN_PRIVILEGES: DWORD PrivilegeCount; LUID_AND_ATTRIBUTES Privileges[].
    count = ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0]
    if count == 0:
        return []

    # The array begins at offset sizeof(DWORD) == 4 (the PrivilegeCount field).
    # LUID_AND_ATTRIBUTES has no padding before it on this layout (DWORD count +
    # {DWORD,LONG,DWORD}); read it out of the buffer at that fixed offset.
    array_offset = ctypes.sizeof(wintypes.DWORD)
    array_type = _LUID_AND_ATTRIBUTES * count
    array = array_type.from_buffer(buf, array_offset)

    triples: list[tuple[_LUID, str, bool]] = []
    for i in range(count):
        entry = array[i]
        # Copy the LUID out of the borrowed buffer so it stays valid after the
        # buffer is reused/freed (we pass it to AdjustTokenPrivileges later).
        luid = _LUID(LowPart=entry.Luid.LowPart, HighPart=entry.Luid.HighPart)
        name = _lookup_privilege_name(advapi32, luid)
        if name is None:
            logger.info(
                "privilege-hardening: a privilege LUID could not be named; "
                "leaving it untouched (fail-safe)."
            )
            continue
        enabled = bool(entry.Attributes & _SE_PRIVILEGE_ENABLED)
        triples.append((luid, name, enabled))
    return triples


def _remove_privilege(advapi32, token: wintypes.HANDLE, luid: _LUID) -> bool:
    """Permanently remove a single privilege via ``SE_PRIVILEGE_REMOVED``.

    ``SE_PRIVILEGE_REMOVED`` deletes the privilege from the token for the
    remaining lifetime of the process — it cannot be re-enabled afterwards
    (stronger than disabling). Returns ``True`` if the privilege was removed,
    ``False`` if the API reported it could not be (``ERROR_NOT_ALL_ASSIGNED``)
    or on any error. Never raises.
    """
    try:
        tp_type = _token_privileges_struct(1)
        tp = tp_type()
        tp.PrivilegeCount = 1
        tp.Privileges[0].Luid = luid
        tp.Privileges[0].Attributes = _SE_PRIVILEGE_REMOVED

        ctypes.set_last_error(0)
        ok = advapi32.AdjustTokenPrivileges(
            token,
            False,                       # DisableAllPrivileges = FALSE (use NewState)
            ctypes.byref(tp),
            ctypes.sizeof(tp),
            None,                        # PreviousState — not needed
            None,                        # ReturnLength — not needed
        )
        err = ctypes.get_last_error()
        if not ok:
            logger.warning(
                "privilege-hardening: AdjustTokenPrivileges call failed (err %s)", err
            )
            return False
        if err == _ERROR_NOT_ALL_ASSIGNED:
            # The call "succeeded" but the privilege was not actually adjusted
            # (e.g. not held). Non-fatal: nothing to remove.
            return False
        return True
    except Exception as exc:  # noqa: BLE001 — fail-safe: a removal must never raise
        logger.warning("privilege-hardening: error removing a privilege (%r)", exc)
        return False


def strip_unused_privileges() -> dict[str, list[str]]:
    """Remove every token privilege not on :data:`KEEP_PRIVILEGES`; return a report.

    Enumerates the current process token's privileges and, for each privilege
    whose canonical name is **not** in the keep-allowlist, removes it permanently
    for the process lifetime (``AdjustTokenPrivileges`` + ``SE_PRIVILEGE_REMOVED``
    — stronger than disabling). Implemented as an allowlist ("remove everything
    not explicitly kept") so an unanticipated privilege is removed by default.

    Call this **early in ``main()``** — after elevation is settled, BEFORE the
    Policy Agent / Assistant Orchestrator threads start and BEFORE any child
    (WinUI, Hello helper, ``powershell.exe``) is spawned — so the removed
    privileges are absent from every in-process component and not inherited by
    children.

    **FAIL-SAFE, NEVER FAIL-BOOT.** Every step is guarded; on any error this
    logs and continues, returning whatever report it assembled. It NEVER raises.
    On a non-elevated dev run it simply removes the few non-allowlisted
    privileges in the standard token (a faithful dry-run of the production path).

    Returns:
        A report ``dict`` with three lists of privilege names (each sorted):

          * ``"removed"`` — privileges successfully removed from the token.
          * ``"kept"``    — privileges retained because they are on the
            keep-allowlist (only those actually present in the token).
          * ``"errors"``  — privileges that were targeted for removal but whose
            removal the API declined/failed (held but not removed), plus a
            synthetic marker on a hard pre-enumeration failure.
    """
    report: dict[str, list[str]] = {"removed": [], "kept": [], "errors": []}

    if sys.platform != "win32":
        logger.info(
            "privilege-hardening: non-win32 platform (%s); nothing to strip (no-op).",
            sys.platform,
        )
        return report

    api = _api()
    if api is None:
        # DLL load failed — already logged in _api(). Fail-safe no-op.
        return report
    advapi32, kernel32 = api

    token = wintypes.HANDLE()
    try:
        proc = kernel32.GetCurrentProcess()
        opened = advapi32.OpenProcessToken(
            proc, _TOKEN_QUERY | _TOKEN_ADJUST_PRIVILEGES, ctypes.byref(token)
        )
        if not opened:
            err = ctypes.get_last_error()
            logger.warning(
                "privilege-hardening: OpenProcessToken failed (err %s); skipping "
                "(fail-safe — boot continues).",
                err,
            )
            report["errors"].append(f"OpenProcessToken failed (err {err})")
            return report
    except Exception as exc:  # noqa: BLE001 — fail-safe
        logger.warning(
            "privilege-hardening: could not open process token (%r); skipping.", exc
        )
        report["errors"].append(f"OpenProcessToken exception: {type(exc).__name__}")
        return report

    try:
        privileges = _enumerate_privileges(advapi32, token)
        if not privileges:
            logger.info(
                "privilege-hardening: no privileges enumerated; nothing to strip."
            )
            return report

        for luid, name, _enabled in privileges:
            if name in KEEP_PRIVILEGES:
                report["kept"].append(name)
                continue
            removed = _remove_privilege(advapi32, token, luid)
            if removed:
                report["removed"].append(name)
            else:
                # Held but not removable / API declined — surface, never fatal.
                report["errors"].append(name)

        report["removed"].sort()
        report["kept"].sort()
        report["errors"].sort()

        logger.info(
            "privilege-hardening: removed %d (%s), kept %d (%s)%s [elevated=%s]",
            len(report["removed"]),
            ", ".join(report["removed"]) or "none",
            len(report["kept"]),
            ", ".join(report["kept"]) or "none",
            (
                f", {len(report['errors'])} not-removed ("
                + ", ".join(report["errors"])
                + ")"
            )
            if report["errors"]
            else "",
            _is_elevated(),
        )
        return report
    except Exception as exc:  # noqa: BLE001 — fail-safe: never let hardening break boot
        logger.warning(
            "privilege-hardening: unexpected error during strip (%r); returning "
            "partial report (boot continues).",
            exc,
        )
        report["errors"].append(f"strip exception: {type(exc).__name__}")
        return report
    finally:
        try:
            kernel32.CloseHandle(token)
        except Exception:  # noqa: BLE001 — handle close is best-effort
            pass
