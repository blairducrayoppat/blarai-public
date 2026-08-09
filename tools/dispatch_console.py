"""BlarAI Dispatch Console — the operator's typed face for ``/dispatch``.

The same production corridor the WinUI app uses (TransportGateway -> per-boot
mTLS -> the live assistant), wrapped in a type-what-you-mean console so the
Lead Architect can drive dispatch when the app is closed. Construction rides
:meth:`DispatchHarness.for_live` — the parity-locked corridor
(tests/integration/test_dispatch_harness.py pins its gateway kwargs against the
launcher's) — and the ceremony-gated gateway flags are READ from the shipped
``default.toml`` (validated-not-coerced, via :func:`load_harness_config`), so
the console always mirrors the shipped posture and never hardcodes one.

Fail-closed by construction: without the per-boot mTLS certs a running
production launcher mints, ``for_live`` refuses to build — the console cannot
talk plaintext to production. The running AO's own engagement gates adjudicate
every command regardless of what this process passes.

Run:  python -m tools.dispatch_console   (from the repo root, any venv python)
"""
from __future__ import annotations

import asyncio

from tools.dispatch_harness.config import HarnessConfig, load_harness_config
from tools.dispatch_harness.harness import DispatchHarness

# ONE session identity for both the gateway construction and every command sent
# through it — two literals here could diverge silently (review finding, 2026-07-29).
_SESSION_ID = "la-ceremony-console"


def console_gateway_kwargs(cfg: HarnessConfig) -> dict[str, object]:
    """The :meth:`DispatchHarness.for_live` kwargs a console derives from config.

    Pure so the flag->kwarg threading is testable without certs or a live AO:
    the ceremony-gated seams mirror the SHIPPED values ``cfg`` resolved
    (strict ``is True`` upstream), never a hardcoded posture.
    """
    return {
        "port": cfg.port,
        "agentic_setup_dir": cfg.agentic_setup_dir,
        "projects_dir": cfg.projects_dir,
        "fleet_dispatch_enabled": cfg.fleet_dispatch_enabled,
        "fleet_dispatch_advanced_intake_enabled": cfg.advanced_intake_enabled,
        "fleet_dispatch_advanced_intake_interview_enabled": (
            cfg.advanced_intake_interview_enabled
        ),
        "fleet_dispatch_advanced_intake_assets_pipeline_enabled": (
            cfg.advanced_intake_assets_pipeline_enabled
        ),
        "fleet_dispatch_advanced_intake_interview_playback_enabled": (
            cfg.advanced_intake_interview_playback_enabled
        ),
        "fleet_dispatch_advanced_intake_interview_voice_enabled": (
            cfg.advanced_intake_interview_voice_enabled
        ),
        "fleet_dispatch_project_memory_enabled": cfg.project_memory_enabled,
        "session_id": _SESSION_ID,
    }


async def main() -> None:
    cfg = load_harness_config()
    harness = DispatchHarness.for_live(**console_gateway_kwargs(cfg))  # type: ignore[arg-type]

    def _light(flag: bool) -> str:
        return "on" if flag else "off"

    print("=" * 62)
    print("  BlarAI Dispatch Console  —  talking to the live assistant")
    print("=" * 62)
    print()
    print(
        f"Shipped posture (read from {cfg.config_path.name}): "
        f"advanced intake {_light(cfg.advanced_intake_enabled)} · "
        f"interview {_light(cfg.advanced_intake_interview_enabled)} · "
        f"playback {_light(cfg.advanced_intake_interview_playback_enabled)} · "
        f"interview voice {_light(cfg.advanced_intake_interview_voice_enabled)} · "
        f"project memory {_light(cfg.project_memory_enabled)}"
    )
    print()
    print("Type a /dispatch line and press Enter. Examples:")
    print("  /dispatch <project> | <what to build>")
    print("  /dispatch advanced <project> | <goal>   (the fuller interview)")
    print("  /dispatch revise <plain-language change to the pending plan>")
    print("  /dispatch approve      /dispatch reject      /dispatch status")
    print()
    print("Type  quit  to leave. A fresh plan can take one to three")
    print("minutes while the model works — the console is not frozen.")

    sid = _SESSION_ID
    while True:
        try:
            line = input("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if line.lower() in ("quit", "exit", "q"):
            break
        if not line:
            continue
        if not line.startswith("/dispatch"):
            print("  (This console only speaks /dispatch lines — start with /dispatch.)")
            continue
        print("  ... working — a fresh plan can take a couple of minutes ...")
        try:
            reply = await harness.send_fn(sid, line)
        except Exception as exc:  # surface, never crash the operator's console
            print(f"\n[error] {type(exc).__name__}: {exc}")
            continue
        print("\nBlarAI>")
        print(reply if reply else "(no reply)")

    print("\nConsole closed. Your pending plan (if any) is still parked safely.")


if __name__ == "__main__":
    asyncio.run(main())
