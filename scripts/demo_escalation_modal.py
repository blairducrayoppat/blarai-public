r"""Interactive demo of the #639 ESCALATE human-review modal (ADR-024 §2.5).

Why this exists
---------------
The ESCALATE consumer + the Textual approval verifier are built, wired, and now
ACTIVATED on the TUI surface, but BlarAI's four current tools (time / date /
day-of-week / calculate) never build a CAR that hits an ESCALATE rule (those rules
key on file paths, large writes, cross-agent params, unverified-code flags — which
only a future file / network tool produces). So no natural user request can trigger
the modal yet. This script FORCES a sample Policy-Agent ESCALATE verdict so you can
SEE the real ``TUIApprovalVerifier`` surface the real modal and watch approve/deny
work — the exact verifier + ``request_escalation_consent`` path the launcher now
registers, driven by a keypress instead of the model deciding to call an (as-yet
nonexistent) escalating tool.

It is a DEMO/verification harness, not runtime code: it imports the production
verifier + consumer and exercises them unchanged.

Run (from the repo root, with the venv):
    .venv\Scripts\python.exe scripts\demo_escalation_modal.py

Then: press 'e' to simulate a PA ESCALATE verdict — the modal appears; approve (y)
or deny (n) — the result is shown. Press 'e' again to cycle through a few sample
rules. Press 'q' to quit.
"""

from __future__ import annotations

import pathlib
import sys
import threading

# Bootstrap: put the repo root on sys.path so the production imports resolve when
# run as a plain script from any cwd.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from textual.app import App, ComposeResult  # noqa: E402
from textual.widgets import Footer, Header, Static  # noqa: E402

from shared.security.escalation_consent import (  # noqa: E402
    ApprovalResult,
    EscalationContext,
    clear_verifier,
    register_verifier,
    request_escalation_consent,
)
from services.ui_shell.src.escalation_prompt import TUIApprovalVerifier  # noqa: E402

# Sample ESCALATE verdicts (rule label + SAFE descriptor — never a real secret).
# These mirror what a future file/network tool's CAR would trip.
_SAMPLES: list[tuple[str, str, str]] = [
    ("ESCALATE_CRYPTO_MATERIAL", "read_keystore", "READ /keystore/master.key"),
    ("ESCALATE_LARGE_WRITE", "write_file", "WRITE /home/user/dump.bin (~250 MB)"),
    ("ESCALATE_INFRA_CONFIG_WRITE", "write_config", "WRITE /internal/config/policy.toml"),
]


class EscalationDemoApp(App[None]):
    """Press 'e' to fire a sample ESCALATE; the real verifier surfaces the modal."""

    TITLE = "#639 ESCALATE human-review modal — demo"
    CSS = """
    #hint   { padding: 1 2; color: $text-muted; }
    #status { padding: 1 2; }
    """
    BINDINGS = [
        ("e", "escalate", "Simulate ESCALATE"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._n = 0

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "Press [b]e[/b] to simulate a Policy-Agent ESCALATE verdict. The real "
            "TUIApprovalVerifier will surface the real modal; approve [b]y[/b] or "
            "deny [b]n[/b]. Press [b]e[/b] again to cycle samples, [b]q[/b] to quit.",
            id="hint",
        )
        yield Static("No escalation fired yet.", id="status")
        yield Footer()

    def on_mount(self) -> None:
        # Register exactly what the launcher registers on the TUI surface.
        register_verifier(TUIApprovalVerifier(self))

    def on_unmount(self) -> None:
        clear_verifier()

    def action_escalate(self) -> None:
        rule, tool, summary = _SAMPLES[self._n % len(_SAMPLES)]
        self._n += 1
        self.query_one("#status", Static).update(
            f"ESCALATE fired: [b]{rule}[/b] — awaiting your approval in the modal…"
        )

        def _worker() -> None:
            # Off the event loop: request_escalation_consent is synchronous and
            # spawns the consent worker that pushes the modal onto the loop.
            ctx = EscalationContext.from_pa_verdict(
                rule, tool_name=tool, action_summary=summary
            )
            result = request_escalation_consent(ctx)
            self.call_from_thread(self._show_result, rule, result)

        threading.Thread(target=_worker, name="demo-escalate", daemon=True).start()

    def _show_result(self, rule: str, result: ApprovalResult) -> None:
        verdict = (
            "APPROVED — the escalated action WOULD run"
            if result.approved
            else "DENIED — the escalated action is refused"
        )
        self.query_one("#status", Static).update(
            f"[b]{rule}[/b]: {verdict}\n"
            f"(verifier={result.verifier_identity}, reason={result.reason!r})\n\n"
            f"Press 'e' for the next sample, or 'q' to quit."
        )


if __name__ == "__main__":
    EscalationDemoApp().run()
