"""UAC-free scripted backend for autonomous WinUI front-end tests (#563).

The launcher forces admin + Hyper-V before it brings the backend up (see
`launcher/__main__.py` step 1-2), so the *full* app cannot boot autonomously.
But the WinUI window is a separate de-elevated exe that only needs a named-pipe
backend speaking the RPC protocol (`services/ui_backend/src/protocol.py`). This
module stands up the REAL `NamedPipeServer` + `RpcDispatcher` over a SCRIPTED
fake gateway (the harness fakes — no models, no AO, no Hyper-V, no elevation), so
a UI-Automation test can drive the real window against a backend it fully
controls — including scripting the dropped-terminal-frame bug that froze the
input (`FakeGateway(hang=True)`).

This is the load-bearing discovery for autonomous front-end testing: it removes
the UAC + GPU dependency entirely. Verified by `test_winui_backend.py` (a
named-pipe round-trip, no GUI); the pywinauto layer that drives the real window
on top of this is the live, display-coordinated step.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

from services.ui_backend.src.protocol import encode_frame, read_frame
from services.ui_backend.src.server import DEFAULT_PIPE_NAME, NamedPipeServer
from services.ui_gateway.src.session_store import SessionStore
from tests.harness.fakes import FakeGateway


@contextmanager
def scripted_pipe_backend(
    gateway: Any | None = None,
    pipe_name: str = DEFAULT_PIPE_NAME,
    failsafe_s: float | None = None,
) -> Iterator[NamedPipeServer]:
    """Run the real NamedPipeServer over a scripted fake gateway on a daemon thread.

    No models, no AO, no elevation. The WinUI exe (or a test client) connects to
    ``pipe_name`` and receives the real dispatcher's frames, driven by
    ``gateway`` — default: a ``FakeGateway`` that streams a normal reply; pass
    ``FakeGateway(hang=True)`` to reproduce the dropped-completion freeze.

    ``failsafe_s`` overrides the dispatcher's prompt-stream fail-safe deadline
    (default 90 s) so a test can prove the frozen input recovers in a few seconds
    instead of waiting the full production bound.
    """
    gw = gateway if gateway is not None else FakeGateway()
    store = SessionStore(":memory:")
    server = NamedPipeServer(
        gw, store, pipe_name=pipe_name, voice=None, prompt_stream_failsafe_s=failsafe_s
    )
    thread = threading.Thread(
        target=server.serve_forever, name="winui-test-pipe", daemon=True
    )
    thread.start()
    try:
        yield server
    finally:
        server.stop()
        _unblock_accept(pipe_name)
        store.close()


def _unblock_accept(pipe_name: str) -> None:
    """Wake the server's blocked ``ConnectNamedPipe`` so its daemon thread sees
    the stop flag and exits, instead of leaking a stale pipe instance a later
    test could connect to. Connect+close a throwaway client; best-effort."""
    try:
        import win32file

        handle = win32file.CreateFile(
            pipe_name, win32file.GENERIC_READ, 0, None, win32file.OPEN_EXISTING, 0, None
        )
        win32file.CloseHandle(handle)
    except Exception:  # noqa: BLE001 — best-effort cleanup
        pass
    time.sleep(0.3)  # let the accept loop unwind and the thread exit


def pipe_roundtrip(
    pipe_name: str, request: dict[str, Any], connect_timeout_s: float = 5.0
) -> dict[str, Any] | None:
    """Connect to ``pipe_name`` as a client, send one framed request, return the
    first response frame (or ``None`` if the pipe never came up).

    Mirrors what the WinUI ``BackendClient`` does, so a green round-trip proves
    the scripted backend is reachable exactly as the window would reach it — the
    UAC-free enabler, verified without launching a GUI.
    """
    import pywintypes
    import win32file

    deadline = time.monotonic() + connect_timeout_s
    handle = None
    while time.monotonic() < deadline:
        try:
            handle = win32file.CreateFile(
                pipe_name,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0,
                None,
                win32file.OPEN_EXISTING,
                0,
                None,
            )
            break
        except pywintypes.error:
            time.sleep(0.05)  # server thread may not have created the pipe yet
    if handle is None:
        return None
    try:
        win32file.WriteFile(handle, encode_frame(request))

        def recv_exact(n: int) -> bytes:
            buf = b""
            while len(buf) < n:
                _hr, chunk = win32file.ReadFile(handle, n - len(buf))
                if not chunk:
                    break
                buf += chunk
            return buf

        return read_frame(recv_exact)
    finally:
        win32file.CloseHandle(handle)
