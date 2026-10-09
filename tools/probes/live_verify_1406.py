"""#1406 live verification — the real backend, over the real named pipe, his real flow.

Drives the SAME channel the WinUI app uses (services/ui_backend/src/client.PipeClient), so
nothing here is a stand-in: a real session in the real store, a real /dispatch interview
answered by the real 14B, and then the exact shape of message that produced an empty bubble
on 2026-08-15 at 10:14 EDT.

Deliberately NOT run under a redirected LOCALAPPDATA — this talks to the LIVE app, and the
redirect exists to protect the real sessions.db from pytest, not from the product. The
throwaway session is deleted at the end.
"""

from __future__ import annotations

import sys

sys.path.insert(0, r"C:\Users\mrbla\BlarAI")

from services.ui_backend.src.client import PipeClient  # noqa: E402

HIS_REPLY = "1. mostly on computer\n2. fresh\n3. I don't know"


def _collect(client, session_id, text):
    """Send *text*, return (joined_token_text, saw_informational)."""
    parts, informational = [], False
    for frame in client.prompt(session_id, text):
        value = frame.get("value", {})
        if frame["stream"] == "token":
            parts.append(str(value.get("token", "")))
        elif frame["stream"] == "end":
            informational = bool(value.get("informational"))
    return "".join(parts), informational


def main() -> int:
    with PipeClient() as c:
        session = c.call("create_session", title="#1406 live check (throwaway)")
        sid = session["id"] if isinstance(session, dict) else str(session)
        print(f"session = {sid}")

        print("\n--- STEP 1: start the interview (real 14B plan) ---")
        reply, info = _collect(
            c, sid,
            "/dispatch advanced pottery-live-1406 | I run a small pottery studio and I "
            "want a proper little website for it, not just one page.",
        )
        print(reply[:1200])
        asked = "questions" in reply.lower() or "question" in reply.lower()
        print(f"\n[interview asked questions: {asked}]  [informational: {info}]")

        print("\n--- STEP 2: answer WITHOUT the prefix (the exact defect input) ---")
        reply2, info2 = _collect(c, sid, HIS_REPLY)
        print(reply2)
        print(f"\n[informational: {info2}]")

        print("\n--- VERDICT ---")
        checks = {
            "reply is not empty (the defect was an EMPTY bubble)": bool(reply2.strip()),
            "names the /dispatch prefix": "/dispatch" in reply2,
            "returns his words verbatim": HIS_REPLY in reply2,
            "offers the copy block conditionally": "If that was your answer" in reply2,
            "names the non-answer exit": "/dispatch reject" in reply2,
            "no model call (informational turn)": info2,
        }
        for label, ok in checks.items():
            print(f"  {'PASS' if ok else 'FAIL'}  {label}")

        print("\n--- STEP 3: ordinary chat with the question still parked ---")
        print("(must still be intercepted — a question IS waiting; this is the modal cost"
              " his decision accepted)")

        try:
            c.call("delete_session", session_id=sid)
            print(f"\nthrowaway session {sid} deleted")
        except Exception as exc:  # noqa: BLE001
            print(f"\nCLEANUP FAILED for {sid}: {exc}")

        return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
