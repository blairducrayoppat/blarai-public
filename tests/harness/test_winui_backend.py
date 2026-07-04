"""Verify the UAC-free scripted backend enabler (no GUI, no models, no admin).

Proves a client can connect to the scripted `NamedPipeServer` over the real
named-pipe RPC protocol and get a correct response — i.e. the WinUI window CAN be
driven by a deterministic backend with no launcher, no elevation, no Hyper-V, and
no GPU. That is the foundation the pywinauto front-end harness stands on.

Uses a UNIQUE pipe name so it never collides with a running BlarAI instance.
Windows-only (named pipes + pywin32); skips elsewhere.
"""

from __future__ import annotations

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="named pipes are Windows-only")

# Distinct pipe name per test: the server's accept loop leaves a daemon thread
# blocked on its pipe name after the client disconnects, so reusing one name
# could let a later test connect to a stale (closed-store) instance.
_PIPE_BASE = r"\\.\pipe\BlarAI-harness-test"


def test_scripted_backend_answers_over_the_real_pipe() -> None:
    from tests.harness.winui_backend import pipe_roundtrip, scripted_pipe_backend

    pipe = _PIPE_BASE + "-sessions"
    with scripted_pipe_backend(pipe_name=pipe):
        resp = pipe_roundtrip(pipe, {"id": 1, "method": "list_sessions", "params": {}})

    assert resp is not None, "scripted backend did not accept a pipe connection"
    assert resp["id"] == 1
    assert resp["ok"] is True
    assert resp["result"] == []  # in-memory store starts empty


def test_scripted_backend_streams_a_prompt_turn() -> None:
    """A prompt over the pipe begins streaming token frames — the contract the
    WinUI relies on (full multi-frame drive is the pywinauto layer's job)."""
    from tests.harness.winui_backend import pipe_roundtrip, scripted_pipe_backend

    pipe = _PIPE_BASE + "-prompt"
    with scripted_pipe_backend(pipe_name=pipe):
        resp = pipe_roundtrip(
            pipe,
            {"id": 7, "method": "prompt", "params": {"session_id": "s", "prompt": "hi"}},
        )

    assert resp is not None
    assert resp["id"] == 7
    assert resp.get("stream") == "token"  # streaming began over the real pipe
