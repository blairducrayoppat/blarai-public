r"""Owner-preserving file/dir DACL hardening for BlarAI's sensitive artifacts.

Vikunja #637 (DATA_MAP §7 items 1 & 2 — file-ACL hardening + ACL-hygiene).

What this module is for
-----------------------
BlarAI's most sensitive on-disk files — the session DB (``sessions.db``), the
substrate / long-term-memory DB (``substrate.db``), the production DEK keystore
(``dek_keystore.json``), and the tamper-evident audit log — historically
**inherit** the permissive ``%LOCALAPPDATA%`` ACL (DATA_MAP §4c).  The at-rest
encryption (AES-256-GCM under the TPM-sealed DEK) is the real confidentiality
boundary; these DACLs are **defense-in-depth on top of that**, not a
replacement.  Two helpers live here:

1.  :func:`ensure_owner_only_dacl` — sets a *protected* (inheritance-removed)
    DACL granting full control to ONLY the current user (the file owner / the
    account the app runs as) + SYSTEM, and removing every inherited / other
    ACE.  Invoked at each sensitive file's creation site.

2.  :func:`strip_foreign_sids_from_dir` — removes ACEs whose SID is neither the
    current user, nor a resolvable local/well-known principal — i.e. strips an
    *orphaned foreign SID* (DATA_MAP §4c: ``S-1-5-21-76345465-…`` on ``certs\``)
    while preserving every legitimate principal.

The two load-bearing guarantees (read these before changing anything)
---------------------------------------------------------------------
**OWNER-PRESERVING INVARIANT.**  The current user ALWAYS retains full access.
Both helpers only ever *remove* access for *other* principals — never the
owner's.  This is what makes a no-live-verify deployment safe: the running app
runs as the current user, so it can never be locked out of its own files by
this code.  (We additionally make the current user the explicit owner in the SD
so the user can always re-open the DACL later via ``WRITE_DAC``.)

**FAIL-SAFE.**  If anything goes wrong — pywin32 missing, a non-Windows host, a
permission error, a malformed path — the helper LOGS a warning and RETURNS
``False``.  It NEVER raises and NEVER blocks file access.  An unhardened file
is exactly the prior (inherited-ACL) behaviour, which is functionally fine on a
single-user box; the encryption is still the boundary.  A hardening helper that
could itself crash the app or lock it out would be worse than no hardening.

Both helpers are **idempotent**: re-running on an already-hardened object is a
no-op-shaped success (the same protected DACL is re-applied).

Design constraints (match the rest of ``shared/security/``)
-----------------------------------------------------------
- No external network.  No new dependencies — stdlib + ``pywin32`` (already a
  project dependency; used the same way by ``server.py`` /
  ``process_launch.py`` / ``dpapi_store.py``).
- Importing has NO side effects and NEVER fails: pywin32 is imported lazily
  inside the helpers, so the module imports cleanly on non-Windows / CI.
- Windows-only by nature (NTFS DACLs).  On any non-win32 platform the helpers
  are a logged no-op returning ``False`` — they do not raise.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass


_ON_WIN32: bool = sys.platform == "win32"


# ---------------------------------------------------------------------------
# Well-known SIDs that are always treated as LEGITIMATE on a Windows box.
# ---------------------------------------------------------------------------
# These are machine-independent (their string form is identical on every
# Windows install), so an ACE for any of them is a normal local-machine
# principal — never an "orphaned foreign SID".  An orphaned foreign SID is a
# *domain* SID (``S-1-5-21-<domain>-<rid>``) whose domain is not this machine
# and which does not resolve to a live account.
#
# We compare against the explicit string forms because this pywin32 build does
# not surface ``IsWellKnownSid``; LookupAccountSid (below) is the primary
# resolver and this set is the belt-and-suspenders allow-list for principals
# that may legitimately fail to "resolve" to a named account in some configs.
_WELL_KNOWN_LEGIT_SIDS: frozenset[str] = frozenset(
    {
        "S-1-1-0",  # Everyone
        "S-1-3-0",  # CREATOR OWNER
        "S-1-3-1",  # CREATOR GROUP
        "S-1-5-11",  # Authenticated Users
        "S-1-5-18",  # LOCAL SYSTEM
        "S-1-5-19",  # LOCAL SERVICE
        "S-1-5-20",  # NETWORK SERVICE
        "S-1-5-32-544",  # BUILTIN\\Administrators
        "S-1-5-32-545",  # BUILTIN\\Users
        "S-1-5-32-555",  # BUILTIN\\Remote Desktop Users
        "S-1-5-32-559",  # BUILTIN\\Performance Log Users
    }
)


def _get_current_user_sid(win32security: Any, win32api: Any, win32con: Any) -> Any:
    """Resolve the current process's user SID (the file owner / run-as account)."""
    token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(), win32con.TOKEN_QUERY
    )
    return win32security.GetTokenInformation(token, win32security.TokenUser)[0]


def _build_owner_only_dacl(win32security: Any, ntsecuritycon: Any, user_sid: Any) -> Any:
    """Build a fresh DACL granting FULL control to ONLY (current user + SYSTEM).

    No inherited entries, no other principals.  The caller applies it as a
    *protected* DACL so inheritance from the parent (the permissive
    ``%LOCALAPPDATA%`` ACL) is severed.
    """
    system_sid = win32security.CreateWellKnownSid(win32security.WinLocalSystemSid)
    dacl = win32security.ACL()
    # Order: explicit allow ACEs.  Current user FIRST (owner-preserving — the
    # account the app runs as always retains full access), then SYSTEM.
    dacl.AddAccessAllowedAce(
        win32security.ACL_REVISION, ntsecuritycon.FILE_ALL_ACCESS, user_sid
    )
    dacl.AddAccessAllowedAce(
        win32security.ACL_REVISION, ntsecuritycon.FILE_ALL_ACCESS, system_sid
    )
    return dacl


def ensure_owner_only_dacl(path: str | Path) -> bool:
    """Lock *path*'s DACL to (current user + SYSTEM) full control; remove the rest.

    Sets a **protected** DACL (inheritance severed) on the file/dir at *path*
    granting full control to only the current user (the owner / the account the
    app runs as) and SYSTEM, and removes all inherited and other ACEs.  Also
    sets the current user as the explicit owner so the user can always re-open
    the DACL via ``WRITE_DAC`` (owner-preserving).

    Idempotent: re-running on an already-hardened object re-applies the same
    protected DACL (a no-op-shaped success).

    **OWNER-PRESERVING:** the current user is always granted full control — this
    function only ever removes access for *other* principals.

    **FAIL-SAFE:** on ANY failure (non-Windows, pywin32 missing, permission
    error, bad input) this logs a warning and returns ``False`` — it never
    raises and never blocks access to the file.  The file then keeps its prior
    (inherited) ACL, which is the pre-#637 behaviour.

    Args:
        path: The file or directory whose DACL to harden.

    Returns:
        ``True`` if the restrictive DACL was applied; ``False`` on any failure
        or no-op (e.g. non-Windows, missing pywin32, target does not exist).
    """
    if not _ON_WIN32:
        logger.debug(
            "ensure_owner_only_dacl: non-win32 platform (%s); skipping (no-op)",
            sys.platform,
        )
        return False

    try:
        p = Path(path)
    except (TypeError, ValueError) as exc:
        logger.warning("ensure_owner_only_dacl: bad path %r (%s); skipping", path, exc)
        return False

    if not p.exists():
        # Nothing to harden — caller invoked before the file was created, or a
        # bad path.  Not an error; just nothing to do.
        logger.debug("ensure_owner_only_dacl: path does not exist: %s; skipping", p)
        return False

    try:
        import ntsecuritycon  # type: ignore[import-untyped]
        import win32api  # type: ignore[import-untyped]
        import win32con  # type: ignore[import-untyped]
        import win32security  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - exercised only off-Windows
        logger.warning(
            "ensure_owner_only_dacl: pywin32 unavailable (%s); leaving inherited "
            "ACL on %s",
            exc,
            p,
        )
        return False

    try:
        user_sid = _get_current_user_sid(win32security, win32api, win32con)
        dacl = _build_owner_only_dacl(win32security, ntsecuritycon, user_sid)

        # PROTECTED_DACL severs inheritance from the parent dir; the explicit
        # DACL replaces whatever was inherited.  We also set OWNER so the
        # current user can always reassert control (owner-preserving).
        sec_info = (
            win32security.DACL_SECURITY_INFORMATION
            | win32security.PROTECTED_DACL_SECURITY_INFORMATION
            | win32security.OWNER_SECURITY_INFORMATION
        )
        win32security.SetNamedSecurityInfo(
            str(p),
            win32security.SE_FILE_OBJECT,
            sec_info,
            user_sid,  # owner = current user (owner-preserving)
            None,  # group unchanged
            dacl,  # the new protected DACL
            None,  # SACL unchanged
        )
        logger.info(
            "ensure_owner_only_dacl: hardened %s (owner-only DACL: current user "
            "+ SYSTEM, inheritance removed)",
            p,
        )
        return True
    except Exception as exc:  # noqa: BLE001 — fail-safe: never block file access
        logger.warning(
            "ensure_owner_only_dacl: failed to set DACL on %s (%s); proceeding "
            "with existing ACLs",
            p,
            exc,
        )
        return False


def _sid_is_legitimate(
    win32security: Any, sid: Any, current_user_sid: Any
) -> bool:
    """Return True iff *sid* is a principal we KEEP (never strip).

    Legitimate iff any of:
      - it equals the current user SID (owner-preserving — never strip the
        account the app runs as), OR
      - it is a recognised well-known/builtin SID (machine-independent), OR
      - it is an AppContainer / capability SID (``S-1-15-*`` — package identity
        the OS adds, never a foreign-domain principal), OR
      - it resolves to a named account on THIS machine via LookupAccountSid.

    Everything else — notably a domain SID (``S-1-5-21-<foreign-domain>-<rid>``)
    that does not resolve — is a foreign / orphaned principal and is stripped.

    SID comparison is by canonical string form (``ConvertSidToStringSid``) — a
    SID has exactly one string representation, so string equality is a correct
    identity test and avoids depending on ``EqualSid`` (absent in some pywin32
    builds).
    """
    # Canonical string form (the stable identity for comparison + classification).
    try:
        sid_str = win32security.ConvertSidToStringSid(sid)
    except Exception:  # noqa: BLE001 - if we can't even stringify it, be safe
        # Cannot identify it → conservative: KEEP it (fail-safe never removes
        # something we couldn't positively classify as foreign).
        return True

    # 1. Current user — always kept (owner-preserving).
    try:
        current_str = win32security.ConvertSidToStringSid(current_user_sid)
        if sid_str == current_str:
            return True
    except Exception:  # noqa: BLE001 - can't stringify the current user? keep, be safe
        return True

    # 2. Well-known / builtin SID (string form is identical on every machine).
    if sid_str in _WELL_KNOWN_LEGIT_SIDS:
        return True

    # 3. AppContainer / capability SIDs (S-1-15-*) — OS-managed package identity,
    #    not a foreign-domain principal.  Keep them (the de-elevated UI relies on
    #    package identity; never an orphaned cross-machine SID).
    if sid_str.startswith("S-1-15-"):
        return True

    # 4. Resolves to a live local account?  LookupAccountSid raises if the SID
    #    has no name on this machine (the orphaned-foreign-SID case).
    try:
        name, _domain, _type = win32security.LookupAccountSid(None, sid)
        if name:
            return True
    except Exception:  # noqa: BLE001 - "No mapping" → not a live account here
        return False

    return False


def strip_foreign_sids_from_dir(path: str | Path) -> bool:
    """Remove ACEs for orphaned / foreign SIDs from *path*'s DACL.

    Walks the existing DACL of the directory at *path* and removes every ACE
    whose SID is **not** the current user, **not** a recognised well-known /
    builtin principal, and does **not** resolve to a live local account — i.e.
    strips an *orphaned foreign SID* (DATA_MAP §4c) while preserving every
    legitimate principal's access.

    This is the targeted ACL-hygiene remediation for the
    ``S-1-5-21-76345465-…`` ACE on the ``certs\\`` tree.  Unlike
    :func:`ensure_owner_only_dacl` it does **not** sever inheritance or rebuild
    the DACL from scratch — it preserves the existing DACL exactly, minus the
    foreign ACEs (least surprise for the cert tree, which legitimately grants
    the three local principals).

    Idempotent: if there are no foreign ACEs, the DACL is left unchanged and the
    function returns ``True`` (nothing to strip is success).

    **OWNER-PRESERVING:** the current user's ACEs are always preserved.

    **FAIL-SAFE:** on ANY failure (non-Windows, pywin32 missing, permission
    error, bad input) this logs a warning and returns ``False`` — it never
    raises and never blocks access.

    Args:
        path: The directory (or file) whose DACL to clean.

    Returns:
        ``True`` if the DACL is clean afterwards (whether or not a strip was
        needed); ``False`` on any failure or no-op.
    """
    if not _ON_WIN32:
        logger.debug(
            "strip_foreign_sids_from_dir: non-win32 platform (%s); skipping",
            sys.platform,
        )
        return False

    try:
        p = Path(path)
    except (TypeError, ValueError) as exc:
        logger.warning(
            "strip_foreign_sids_from_dir: bad path %r (%s); skipping", path, exc
        )
        return False

    if not p.exists():
        logger.debug(
            "strip_foreign_sids_from_dir: path does not exist: %s; skipping", p
        )
        return False

    try:
        import win32api  # type: ignore[import-untyped]
        import win32con  # type: ignore[import-untyped]
        import win32security  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - exercised only off-Windows
        logger.warning(
            "strip_foreign_sids_from_dir: pywin32 unavailable (%s); leaving ACL "
            "on %s",
            exc,
            p,
        )
        return False

    try:
        current_user_sid = _get_current_user_sid(win32security, win32api, win32con)

        sd = win32security.GetNamedSecurityInfo(
            str(p),
            win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION,
        )
        dacl = sd.GetSecurityDescriptorDacl()
        if dacl is None:
            # NULL DACL == everyone full access; no named ACEs to strip.  This
            # is unusual for our dirs; treat as nothing-to-do success.
            logger.debug(
                "strip_foreign_sids_from_dir: %s has a NULL DACL; nothing to strip",
                p,
            )
            return True

        ace_count = dacl.GetAceCount()
        foreign_indices: list[int] = []
        for i in range(ace_count):
            ace = dacl.GetAce(i)
            # ace shape: ((AceType, AceFlags), Mask, Sid)
            sid = ace[2]
            if not _sid_is_legitimate(win32security, sid, current_user_sid):
                foreign_indices.append(i)
                try:
                    foreign_str = win32security.ConvertSidToStringSid(sid)
                except Exception:  # noqa: BLE001
                    foreign_str = "<unprintable>"
                logger.warning(
                    "strip_foreign_sids_from_dir: foreign/orphaned SID %s on %s "
                    "— removing ACE",
                    foreign_str,
                    p,
                )

        if not foreign_indices:
            logger.debug(
                "strip_foreign_sids_from_dir: %s — no foreign SIDs (clean)", p
            )
            return True

        # Delete by descending index so earlier deletions don't shift the
        # indices of the ones still to remove.
        for i in sorted(foreign_indices, reverse=True):
            dacl.DeleteAce(i)

        # Write the cleaned DACL back.  We do NOT set PROTECTED here — we keep
        # the dir's existing inheritance posture, only removing the foreign
        # ACEs (least surprise for the cert tree).
        win32security.SetNamedSecurityInfo(
            str(p),
            win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION,
            None,  # owner unchanged
            None,  # group unchanged
            dacl,  # the cleaned DACL
            None,  # SACL unchanged
        )
        logger.info(
            "strip_foreign_sids_from_dir: removed %d foreign ACE(s) from %s",
            len(foreign_indices),
            p,
        )
        return True
    except Exception as exc:  # noqa: BLE001 — fail-safe: never block access
        logger.warning(
            "strip_foreign_sids_from_dir: failed to clean DACL on %s (%s); "
            "proceeding with existing ACLs",
            p,
            exc,
        )
        return False
