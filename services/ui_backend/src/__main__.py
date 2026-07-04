"""
UI Backend entrypoint (ADR-014)
================================
    python -m services.ui_backend --stub            # headless echo, in-memory DB
    python -m services.ui_backend --no-model        # REAL sessions.db + echo replies
    python -m services.ui_backend --no-model --pipe \\.\pipe\BlarAI

``--stub``     serves the no-GPU :class:`StubGateway` with an in-memory session
              store — pure transport smoke.
``--no-model`` serves the no-GPU echo gateway but against the REAL session
              database (``SESSION_DB_PATH``), so the WinUI app shows the user's
              actual chat history and persists new turns. This is the backend
              the WinUI surface runs against until the real model is wired
              (the launcher hosting the real gateway behind the pipe in place
              of the TUI). Replies are echoes, not model output.

The default (no flag) mode reports that production serving lands with the
launcher integration and exits rather than pretending to run.
"""

from __future__ import annotations

import argparse
import logging
import sys

from services.ui_backend.src.server import DEFAULT_PIPE_NAME, NamedPipeServer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m services.ui_backend")
    parser.add_argument("--pipe", default=DEFAULT_PIPE_NAME, help="Named pipe path")
    parser.add_argument(
        "--stub",
        action="store_true",
        help="Serve the no-GPU echo backend with an in-memory DB (transport smoke).",
    )
    parser.add_argument(
        "--no-model",
        action="store_true",
        help="Serve echo replies against the REAL session DB (WinUI dev/demo).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    if not args.stub and not args.no_model:
        print(
            "Production backend serving (real gateway behind the pipe) is wired "
            "with the launcher integration. Run with --no-model to drive the "
            "WinUI app against your real chat history with echo replies (no GPU), "
            "or --stub for a pure transport smoke.",
            file=sys.stderr,
        )
        return 2

    from services.ui_backend.src._stub import (
        StubGateway,
        StubVoiceEngine,
        build_stub_backend,
    )

    if args.no_model:
        import os

        from services.ui_gateway.src.constants import SESSION_DB_PATH
        from services.ui_gateway.src.session_store import build_session_store

        # --no-model opens the REAL session DB, so it MUST be encrypted at rest
        # (Sprint 14 EA-4, ADR-025).  dev_mode is inferred from whether
        # BLARAI_DEK_KEYSTORE is set: if the TPM keystore is provisioned we use
        # the production TpmSealer path; otherwise this is a dev/demo session and
        # we use SoftwareSealer + ephemeral keystore (EA-7 MINOR-3 fix -- the
        # dev path must be an explicit opt-in, not the silent default on a missing
        # env var; ADR-025 §2.8(a)).
        _no_model_dev_mode: bool = not bool(os.environ.get("BLARAI_DEK_KEYSTORE", ""))
        db_path = SESSION_DB_PATH or ":memory:"
        gateway, store = StubGateway(), build_session_store(
            db_path, dev_mode=_no_model_dev_mode
        )
        mode = f"no-model (real DB, encrypted: {db_path})"
    else:
        gateway, store = build_stub_backend()
        mode = "stub (in-memory DB)"

    # The --no-model / --stub paths get a no-GPU voice engine (deterministic
    # transcript + sine-tone synth) so the mic/play affordances are exercisable
    # without Whisper/Kokoro loaded (ADR-017 §2.6).
    server = NamedPipeServer(gateway, store, pipe_name=args.pipe, voice=StubVoiceEngine())
    print(f"UI backend [{mode}] listening on {args.pipe} — Ctrl+C to stop.", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.stop()
        print("\nUI backend stopped.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
