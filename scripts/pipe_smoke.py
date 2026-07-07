"""
Named-pipe bridge smoke test (ADR-014, Phase 1).
=================================================
Starts the stub UI backend on a private dev pipe in a background thread,
connects a Python client, and runs a full round-trip — create a session,
send a prompt, stream the reply, read the persisted turns back. Prints a
single PASS / FAIL line.

This proves the named-pipe transport + RPC dispatch work end-to-end on THIS
Windows machine without needing the GPU, admin, or the Hyper-V VM. The real
chat path (real model behind the same pipe) is verified once the WinUI app
connects in a later phase.

Run from the repo root:
    .venv\\Scripts\\python.exe scripts\\pipe_smoke.py
"""

from __future__ import annotations

import os
import sys
import threading
import time

# Make the repo root importable when run as a plain script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.ui_backend.src._stub import build_stub_backend  # noqa: E402
from services.ui_backend.src.client import PipeClient  # noqa: E402
from services.ui_backend.src.server import NamedPipeServer  # noqa: E402

PIPE = r"\\.\pipe\BlarAI-smoke"


def main() -> int:
    gateway, store = build_stub_backend()
    server = NamedPipeServer(gateway, store, pipe_name=PIPE)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.3)  # let the first pipe instance be created

    try:
        with PipeClient(PIPE) as client:
            # 1. create a session
            created = client.call("create_session", title="Smoke session")
            sid = created["session_id"]
            print(f"  created session {sid}")

            # 2. send a prompt and stream the reply
            reply_parts = []
            pgov_seen = False
            for frame in client.prompt(sid, "ping the pipe"):
                if frame["stream"] == "token":
                    reply_parts.append(frame["value"]["token"])
                elif frame["stream"] == "pgov":
                    pgov_seen = True
            reply = "".join(reply_parts)
            print(f"  streamed reply: {reply!r}")

            # 3. read persisted turns back
            turns = client.call("get_turns", session_id=sid)
            roles = [t["role"] for t in turns]

        ok = (
            "ping the pipe" in reply
            and pgov_seen
            and "assistant" in roles
        )
        print("\nPASS — named-pipe bridge round-trip works." if ok
              else "\nFAIL — round-trip did not complete as expected.")
        return 0 if ok else 1
    except Exception as exc:  # noqa: BLE001
        print(f"\nFAIL — {type(exc).__name__}: {exc}")
        return 1
    finally:
        server.stop()


if __name__ == "__main__":
    sys.exit(main())
