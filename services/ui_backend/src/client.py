"""
Synchronous named-pipe client (ADR-014) — Python side.
=======================================================
The production front end is the C# WinUI app (``NamedPipeClientStream``); this
Python client exists for the smoke harness and any Python-side tooling/tests
that need to drive the backend over a real pipe. It speaks the same
length-prefixed JSON framing as :mod:`services.ui_backend.src.protocol`.
"""

from __future__ import annotations

import itertools
from typing import Any, Iterator

import pywintypes
import win32file

from services.ui_backend.src.protocol import (
    ProtocolError,
    encode_frame,
    read_frame,
)
from services.ui_backend.src.server import DEFAULT_PIPE_NAME

_ERROR_BROKEN_PIPE = 109


class PipeClientError(Exception):
    """Raised when the backend returns an error frame or the pipe fails."""


class PipeClient:
    """Blocking client for the UI backend named pipe."""

    def __init__(self, pipe_name: str = DEFAULT_PIPE_NAME) -> None:
        self._pipe_name = pipe_name
        self._handle: Any = None
        self._ids = itertools.count(1)

    def connect(self) -> None:
        self._handle = win32file.CreateFile(
            self._pipe_name,
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            0,
            None,
            win32file.OPEN_EXISTING,
            0,
            None,
        )

    def close(self) -> None:
        if self._handle is not None:
            try:
                win32file.CloseHandle(self._handle)
            except pywintypes.error:
                pass
            self._handle = None

    def __enter__(self) -> "PipeClient":
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ── Framing ───────────────────────────────────────────────────────

    def _recv_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            try:
                _hr, chunk = win32file.ReadFile(self._handle, n - len(buf))
            except pywintypes.error as exc:
                if exc.winerror == _ERROR_BROKEN_PIPE:
                    return bytes(buf)
                raise
            if not chunk:
                return bytes(buf)
            buf.extend(chunk)
        return bytes(buf)

    def _send(self, frame: dict[str, Any]) -> None:
        win32file.WriteFile(self._handle, encode_frame(frame))

    def _read(self) -> dict[str, Any] | None:
        return read_frame(self._recv_exact)

    # ── RPC ───────────────────────────────────────────────────────────

    def call(self, method: str, **params: Any) -> Any:
        """Call a non-streaming method; return its result or raise on error."""
        rid = next(self._ids)
        self._send({"id": rid, "method": method, "params": params})
        frame = self._read()
        if frame is None:
            raise PipeClientError("pipe closed before response")
        if not frame.get("ok", False):
            err = frame.get("error", {})
            raise PipeClientError(f"{err.get('code')}: {err.get('message')}")
        return frame.get("result")

    def prompt(self, session_id: str, text: str) -> Iterator[dict[str, Any]]:
        """Call the streaming ``prompt`` method; yield each stream frame."""
        rid = next(self._ids)
        self._send({"id": rid, "method": "prompt", "params": {"session_id": session_id, "prompt": text}})
        while True:
            frame = self._read()
            if frame is None:
                raise PipeClientError("pipe closed mid-stream")
            if "stream" in frame:
                yield frame
                if frame["stream"] == "end":
                    return
            elif not frame.get("ok", True):
                err = frame.get("error", {})
                raise PipeClientError(f"{err.get('code')}: {err.get('message')}")
            else:
                # Unexpected non-stream ok frame — stop defensively.
                raise ProtocolError("expected stream frames for prompt")
