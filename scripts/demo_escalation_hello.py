r"""Interactive on-box live-verify of the #649 Windows-Hello ESCALATE approval path.

Why this exists
---------------
The ESCALATE consumer (#639) + the new Windows-Hello biometric verifier (#649) are
built and wired into BOTH launcher surfaces (TUI + WinUI), but BlarAI's four current
tools never build a CAR that trips an ESCALATE rule (those rules key on file paths,
large writes, cross-agent params, unverified-code flags — only a future file/network
tool produces them). So no natural user request raises the Hello prompt yet. This
script FORCES a sample Policy-Agent ESCALATE verdict so the LA can SEE the real
``BiometricApprovalVerifier`` raise the real **system Windows Hello dialog**, tap a
fingerprint (or PIN/face), and watch approve/deny resolve — the exact verifier +
``request_escalation_consent`` path the launcher registers, driven by a keypress
instead of the model deciding to call an (as-yet nonexistent) escalating tool.

It is a DEMO/verification harness, not runtime code: it imports the production
verifier + consumer and exercises them unchanged.

The fingerprint tap is the ONE step that needs a human — everything else (build, unit
tests) is automated. This is the LA's on-box live-verify for #649.

Run (from the repo root, with the venv):
    .venv\Scripts\python.exe scripts\demo_escalation_hello.py

What you'll see:
  1. A non-interactive availability check (``--check``) — confirms Hello is Available.
  2. For each sample rule: the SYSTEM Windows Hello dialog appears with the safe
     action descriptor. Approve it (fingerprint / PIN / face) or cancel it.
  3. The script prints APPROVED / DENIED with the verifier identity + reason — the
     same ApprovalResult the AO enforcement point would act on.

If the Hello helper exe is not built yet, the script says so and tells you the one
build command. If Hello is unavailable on this box, it reports that (and the launcher
would fall back: TUI → modal, WinUI → silent-DENY).
"""

from __future__ import annotations

import pathlib
import sys

# Bootstrap: put the repo root on sys.path so the production imports resolve when run
# as a plain script from any cwd.
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.security.escalation_consent import (  # noqa: E402
    EscalationContext,
    clear_verifier,
    register_verifier,
    request_escalation_consent,
)
from shared.security.hello_verifier import (  # noqa: E402
    HELLO_EXE_REL,
    BiometricApprovalVerifier,
)

# Sample ESCALATE verdicts (rule label + SAFE descriptor — never a real secret).
# These mirror what a future file/network tool's CAR would trip; identical to the
# TUI modal demo so the two surfaces can be compared.
_SAMPLES: list[tuple[str, str, str]] = [
    ("ESCALATE_CRYPTO_MATERIAL", "read_keystore", "READ /keystore/master.key"),
    ("ESCALATE_LARGE_WRITE", "write_file", "WRITE /home/user/dump.bin (~250 MB)"),
    ("ESCALATE_INFRA_CONFIG_WRITE", "write_config", "WRITE /internal/config/policy.toml"),
]


def _hr() -> None:
    print("-" * 70)


def main() -> int:
    print()
    print("=" * 70)
    print("  BlarAI #649 — Windows Hello ESCALATE approval — on-box live-verify")
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
        print("  (The launcher resolves this same Release path; until it exists, the")
        print("   TUI surface falls back to the Textual modal and the WinUI surface")
        print("   leaves ESCALATE silent-DENY.)")
        return 2

    print("Checking Windows Hello availability (--check, non-interactive)…")
    if not verifier.is_available():
        print()
        print("  ! Windows Hello reports UNAVAILABLE on this box (no enrolled")
        print("    fingerprint/PIN/face, disabled by policy, or device busy).")
        print("    The launcher would fall back here: TUI → Textual modal;")
        print("    WinUI → ESCALATE stays silent-DENY. Nothing to live-verify.")
        return 3
    print("  Windows Hello is AVAILABLE. ✓")
    print()

    # Register EXACTLY what the launcher registers on a Hello-capable box.
    register_verifier(verifier)
    print("Registered BiometricApprovalVerifier (the production verifier).")
    print()
    print("For each sample below, the SYSTEM Windows Hello dialog will appear.")
    print("Approve with your fingerprint / PIN / face, OR cancel it to see a deny.")
    print()

    try:
        for i, (rule, tool, summary) in enumerate(_SAMPLES, start=1):
            _hr()
            print(f"[{i}/{len(_SAMPLES)}]  Simulating PA verdict: {rule}")
            print(f"        action: {summary}  (tool: {tool})")
            print("        → raising the Windows Hello prompt now…")
            ctx = EscalationContext.from_pa_verdict(
                rule, tool_name=tool, action_summary=summary
            )
            # The exact production call the AO enforcement point makes.
            result = request_escalation_consent(ctx)
            verdict = (
                "APPROVED — the escalated action WOULD run"
                if result.approved
                else "DENIED  — the escalated action is refused"
            )
            print(f"        RESULT: {verdict}")
            print(
                f"        (approved={result.approved}, "
                f"verifier={result.verifier_identity!r}, reason={result.reason!r})"
            )
            print()
    finally:
        clear_verifier()

    _hr()
    print("Live-verify complete. Each APPROVED above was a real Windows Hello match;")
    print("each DENIED was a real cancel/failure — the same ApprovalResult the AO")
    print("tool-dispatch enforcement point acts on. This is the #649 verifier in")
    print("production form, surface-independent (TUI + WinUI register the same one).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
