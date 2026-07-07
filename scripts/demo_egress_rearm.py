r"""Interactive on-box live-verify of the #653 egress kill-switch fingerprint re-arm.

Why this exists
---------------
The egress kill-switch (:mod:`shared.security.egress_guard`) is a latched control:
on an egress anomaly it trips and cuts ALL network egress until an operator clears
it. ADR-027 §3 makes that re-arm a deliberate human act. #653 wires the clear to
the #649 Windows-Hello verifier: "Egress LOCKED — reason: X" → tap Re-arm → the
system Hello dialog appears → a fingerprint (or PIN/face) clears the latch; a
cancel leaves it locked.

BlarAI's current runtime never trips the kill-switch on its own (the external
allowlist is empty and dormant — no web feature ships yet), so no natural event
raises this prompt. This script FORCES a trip so the LA can SEE the real
:class:`shared.security.hello_verifier.BiometricApprovalVerifier` raise the real
**system Windows Hello dialog**, tap a fingerprint, and watch the latch clear — the
exact ``request_egress_rearm`` path a "Re-arm" button drives, triggered by a
keypress instead of an actual egress anomaly.

It is a DEMO/verification harness, not runtime code: it imports the production
verifier + re-arm core and exercises them unchanged. The fingerprint tap is the
ONE step that needs a human; everything else (build, unit tests) is automated.

Run (from the repo root, with the venv):
    .venv\Scripts\python.exe scripts\demo_egress_rearm.py

What you'll see:
  1. A non-interactive availability check (``--check``) — confirms Hello is Available.
  2. Sample 1 (APPROVE): egress is tripped ("Egress LOCKED — reason: …"); the SYSTEM
     Windows Hello dialog appears; approve it → "Egress UNLOCKED" and is_tripped()==False.
  3. Sample 2 (CANCEL): egress is tripped again; the Hello dialog appears; CANCEL it
     → "Still LOCKED" and is_tripped()==True.
  4. The script clears the latch at the end so it does not leave global state tripped.

If the Hello helper exe is not built yet, the script says so and tells you the one
build command. If Hello is unavailable on this box, it reports that and exits — it
does NOT fall back to a TUI modal (the TUI is deprecated; the primary surface is
WinUI, and the Hello prompt is surface-independent).
"""

from __future__ import annotations

import pathlib
import sys

# Bootstrap: put the repo root on sys.path so the production imports resolve when run
# as a plain script from any cwd.
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.security import egress_guard  # noqa: E402
from shared.security.egress_rearm import request_egress_rearm  # noqa: E402
from shared.security.escalation_consent import (  # noqa: E402
    clear_verifier,
    register_verifier,
)
from shared.security.hello_verifier import (  # noqa: E402
    HELLO_EXE_REL,
    BiometricApprovalVerifier,
)


def _hr() -> None:
    print("-" * 70)


def _run_sample(label: str, reason: str) -> None:
    """Trip the kill-switch, raise the Hello re-arm prompt, and report the outcome."""
    egress_guard.trip(reason)
    print(f"        Egress LOCKED — reason: {egress_guard.trip_reason()}")
    print("        → tap Re-arm: raising the Windows Hello prompt now…")
    result = request_egress_rearm()
    if result.approved and not egress_guard.is_tripped():
        print("        Egress UNLOCKED ✓ (re-armed via Windows Hello)")
    else:
        print("        Still LOCKED (re-arm denied/cancelled)")
    print(
        f"        (approved={result.approved}, "
        f"verifier={result.verifier_identity!r}, reason={result.reason!r}, "
        f"is_tripped()={egress_guard.is_tripped()})"
    )
    print()


def main() -> int:
    print()
    print("=" * 70)
    print("  BlarAI #653 — Egress kill-switch Hello re-arm — on-box live-verify")
    print("=" * 70)
    print()

    exe_path = _REPO_ROOT / HELLO_EXE_REL
    verifier = BiometricApprovalVerifier(exe_path=exe_path)

    print(f"Hello helper exe : {exe_path}")
    if not exe_path.is_file():
        print()
        print("  ! Helper exe NOT found. Build it first (Release), then re-run:")
        print("      dotnet build -c Release -p:Platform=x64 tools/hello_verify")
        print()
        print("  (This is the SAME #649 helper the ESCALATE Hello prompt uses; until")
        print("   it exists there is no Hello prompt to raise. The TUI is deprecated —")
        print("   this demo does NOT fall back to a modal.)")
        return 2

    print("Checking Windows Hello availability (--check, non-interactive)…")
    if not verifier.is_available():
        print()
        print("  ! Windows Hello reports UNAVAILABLE on this box (no enrolled")
        print("    fingerprint/PIN/face, disabled by policy, or device busy).")
        print("    Nothing to live-verify — and this demo does NOT fall back to a")
        print("    TUI modal (the TUI is deprecated; the primary surface is WinUI).")
        return 3
    print("  Windows Hello is AVAILABLE. ✓")
    print()

    # Register EXACTLY what the launcher registers on a Hello-capable box (#649).
    register_verifier(verifier)
    print("Registered BiometricApprovalVerifier (the production verifier).")
    print()
    print("Two samples below show BOTH directions. The SYSTEM Windows Hello dialog")
    print("appears each time; approve the first, CANCEL the second.")
    print()

    try:
        _hr()
        print("[1/2]  APPROVE this one — your fingerprint should CLEAR the lock.")
        _run_sample("approve", "demo: simulated exfiltration anomaly")

        _hr()
        print("[2/2]  CANCEL this one — the lock must STAY engaged on a cancel.")
        _run_sample("cancel", "demo: second simulated anomaly")
    finally:
        # Leave global state clean: clear the latch (so this process does not exit
        # with egress tripped) and drop the verifier. rearm() is a no-op if sample 1
        # already cleared it; it clears sample 2's still-engaged latch on cancel.
        egress_guard.rearm()
        clear_verifier()

    _hr()
    print("Live-verify complete. Sample 1's UNLOCK was a real Windows Hello match;")
    print("sample 2's STILL-LOCKED was a real cancel — the same ApprovalResult a")
    print("WinUI 'Re-arm' button would act on. The kill-switch is left CLEARED.")
    print(f"Final state: is_tripped()={egress_guard.is_tripped()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
