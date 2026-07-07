r"""Headless before/after view of the launcher token privilege-strip (#652 D-a).

Why this exists
---------------
``launcher/privilege_hardening.strip_unused_privileges()`` runs early in the
elevated launcher's ``main()`` and permanently removes every token privilege not
on the keep-allowlist. The full effect is only dramatic when run from an ELEVATED
shell (the elevated token carries ~20 privileges including SeDebug / SeLoadDriver
/ SeTcb / SeTakeOwnership); from an ordinary shell it still demonstrates the
mechanism on the small standard privilege set.

This script needs NO GPU and NO WinUI boot — it just enumerates the CURRENT
process's token privileges, prints them, calls ``strip_unused_privileges()``, and
prints them again, so the LA can see the strip in one before/after read. It is a
DIAGNOSTIC harness, not runtime code: it imports the production stripper and a
read-only enumeration helper and exercises them unchanged.

Run it from an ELEVATED PowerShell to see the real production-shaped strip:

    .venv\Scripts\python.exe scripts\show_launcher_privileges.py

(From a normal shell it removes the handful of non-allowlisted standard
privileges — still a faithful, if smaller, demonstration. Whatever process runs
this has its OWN privileges stripped, exactly as the launcher strips its own;
that is the point — there is nothing else to strip.)
"""

from __future__ import annotations

import ctypes
import pathlib
import sys
from ctypes import wintypes

# Bootstrap: put the repo root on sys.path so the production import resolves when
# run as a plain script from any cwd (mirrors scripts/demo_escalation_*.py).
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from launcher.privilege_hardening import (  # noqa: E402
    KEEP_PRIVILEGES,
    _api,
    _enumerate_privileges,
    _is_elevated,
    strip_unused_privileges,
)

_TOKEN_QUERY = 0x0008
_TOKEN_ADJUST_PRIVILEGES = 0x0020


def _hr() -> None:
    print("-" * 70)


def _enumerate_current() -> list[tuple[str, bool]]:
    """Return the current process token's privileges as (name, enabled) pairs.

    Read-only — opens the token with TOKEN_QUERY only and reuses the production
    enumeration helper. Returns [] off-Windows / on any failure (the script then
    prints an explanatory note rather than crashing).
    """
    if sys.platform != "win32":
        return []
    api = _api()
    if api is None:
        return []
    advapi32, kernel32 = api
    token = wintypes.HANDLE()
    opened = advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)
    )
    if not opened:
        return []
    try:
        return [(name, enabled) for _luid, name, enabled in _enumerate_privileges(advapi32, token)]
    finally:
        try:
            kernel32.CloseHandle(token)
        except Exception:  # noqa: BLE001
            pass


def _print_privileges(privs: list[tuple[str, bool]]) -> None:
    if not privs:
        print("    (none enumerated)")
        return
    for name, enabled in sorted(privs):
        keep = "  KEEP" if name in KEEP_PRIVILEGES else ""
        state = "enabled" if enabled else "disabled"
        print(f"    {name:<34} [{state}]{keep}")


def main() -> int:
    print()
    print("=" * 70)
    print("  BlarAI #652 — launcher token privilege-strip — headless before/after")
    print("=" * 70)
    print()

    if sys.platform != "win32":
        print(f"  This is a Windows-only token operation; platform is {sys.platform!r}.")
        print("  Nothing to demonstrate here.")
        return 0

    elevated = _is_elevated()
    print(f"Current process elevation : {'ELEVATED (High)' if elevated else 'normal (Medium)'}")
    if not elevated:
        print(
            "  NOTE: run from an ELEVATED PowerShell to see the full production-shaped\n"
            "        strip (SeDebug / SeLoadDriver / SeTcb / SeTakeOwnership / …). From\n"
            "        a normal shell only the small standard privilege set is present."
        )
    print()
    print(f"Keep-allowlist (never removed): {', '.join(sorted(KEEP_PRIVILEGES))}")
    print()

    _hr()
    print("BEFORE — token privileges:")
    before = _enumerate_current()
    _print_privileges(before)
    print()

    _hr()
    print("Running strip_unused_privileges() …")
    report = strip_unused_privileges()
    print(
        f"  removed {len(report['removed'])}: "
        f"{', '.join(report['removed']) or 'none'}"
    )
    print(
        f"  kept    {len(report['kept'])}: "
        f"{', '.join(report['kept']) or 'none'}"
    )
    if report["errors"]:
        print(f"  errors  {len(report['errors'])}: {', '.join(report['errors'])}")
    print()

    _hr()
    print("AFTER — token privileges:")
    after = _enumerate_current()
    _print_privileges(after)
    print()

    _hr()
    before_names = {n for n, _ in before}
    after_names = {n for n, _ in after}
    gone = sorted(before_names - after_names)
    print(
        f"Net effect: {len(gone)} privilege(s) removed from the token for this "
        f"process's lifetime."
    )
    if gone:
        print(f"  removed: {', '.join(gone)}")
    print(
        "  (The strip is permanent for the process — SE_PRIVILEGE_REMOVED — so a\n"
        "   second run finds nothing left to remove. In the launcher this runs once,\n"
        "   before the in-process Policy Agent / Assistant Orchestrator threads start\n"
        "   and before any child is spawned, so neither inherits the removed rights.)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
