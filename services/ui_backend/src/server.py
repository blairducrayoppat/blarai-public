"""
UI Backend Named-Pipe Server (ADR-014)
=======================================
A blocking, single-user named-pipe server (pywin32) that hosts the RPC
:class:`RpcDispatcher`. One client (the WinUI 3 app) connects at a time; the
server loops to accept reconnections. Each accepted connection runs its own
asyncio event loop so the dispatcher's async gateway calls (``send_prompt`` /
``stream_tokens``) execute, while pipe reads/writes are synchronous pywin32
calls bridged into that loop.

Privacy posture (ADR-014 / ADR-009):
  - A named pipe is a kernel object, NOT a TCP/IP socket — zero listening
    network port, consistent with the no-external-network mandate.
  - ``PIPE_REJECT_REMOTE_CLIENTS`` refuses any over-the-network pipe client,
    so the bridge is reachable only by a local process.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import threading
from typing import Any

import pywintypes
import win32api
import win32file
import win32pipe
import win32security

from services.ui_backend.src.dispatcher import RpcDispatcher
from services.ui_backend.src.protocol import (
    ProtocolError,
    encode_frame,
    error_response,
    read_frame,
)

logger = logging.getLogger(__name__)

DEFAULT_PIPE_NAME: str = r"\\.\pipe\BlarAI"

# pywin32 constant not always surfaced by name across versions.
_PIPE_REJECT_REMOTE_CLIENTS: int = 0x00000008
_ERROR_BROKEN_PIPE: int = 109
_ERROR_PIPE_NOT_CONNECTED: int = 233
_READ_CHUNK: int = 65536

_pipe_sa: Any | None = None
_pipe_sa_built: bool = False


def _pipe_security_attributes() -> Any | None:
    """SECURITY_ATTRIBUTES letting a Medium-integrity client of the current user
    open this pipe (ADR-019).

    The WinUI UI now runs de-elevated (Medium integrity) while the launcher that
    serves this pipe stays elevated (High) for Hyper-V. A pipe created by a High
    server with *default* security denies a Medium client ("Access to the path is
    denied"), which the UI surfaces as "backend not running". This grants the
    current user + SYSTEM full access and labels the pipe Medium (no-write-up) so
    the client is not blocked by the mandatory-integrity policy. Built once and
    cached. Returns None on any failure — the caller then falls back to default
    security (same-integrity clients still work; only the de-elevated path needs
    this), so this can never make the pipe fail to come up.
    """
    global _pipe_sa, _pipe_sa_built
    if _pipe_sa_built:
        return _pipe_sa
    _pipe_sa_built = True
    try:
        token = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(), win32security.TOKEN_QUERY
        )
        user_sid = win32security.GetTokenInformation(
            token, win32security.TokenUser
        )[0]
        user_sid_str = win32security.ConvertSidToStringSid(user_sid)
        # DACL: protected, grant the current user + SYSTEM full access.
        # SACL: Medium mandatory label, no-write-up — so a Medium client of the
        # same user is not blocked by the integrity policy.
        sddl = "D:P(A;;FA;;;%s)(A;;FA;;;SY)S:(ML;;NW;;;ME)" % user_sid_str
        sd = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
            sddl, win32security.SDDL_REVISION_1
        )
        sa = win32security.SECURITY_ATTRIBUTES()
        sa.SECURITY_DESCRIPTOR = sd
        _pipe_sa = sa
        logger.info(
            "Pipe security: explicit SD (current user + SYSTEM, Medium label) "
            "for de-elevated UI access"
        )
    except Exception as exc:  # noqa: BLE001 — never block the pipe coming up
        logger.warning(
            "Pipe security: SD construction failed (%s); using default security",
            exc,
        )
        _pipe_sa = None
    return _pipe_sa


class NamedPipeServer:
    """Serve an :class:`RpcDispatcher` over a Windows named pipe.

    Args:
        gateway: TransportGateway (or compatible) for the dispatcher.
        session_store: SessionStore (or compatible), or None.
        pipe_name: Full pipe path (default ``\\\\.\\pipe\\BlarAI``).
        voice: VoiceEngine (or compatible) for STT/TTS, or None (voice disabled).
    """

    def __init__(
        self,
        gateway: Any,
        session_store: Any | None = None,
        pipe_name: str = DEFAULT_PIPE_NAME,
        voice: Any | None = None,
        prompt_stream_failsafe_s: float | None = None,
    ) -> None:
        self._dispatcher = RpcDispatcher(
            gateway,
            session_store,
            voice=voice,
            prompt_stream_failsafe_s=prompt_stream_failsafe_s,
        )
        self._pipe_name = pipe_name
        self._stop = threading.Event()

    def stop(self) -> None:
        """Signal the accept loop to exit after the current connection."""
        self._stop.set()

    # ── Accept loop ───────────────────────────────────────────────────

    def serve_forever(self) -> None:
        """Accept and service connections until :meth:`stop` is called."""
        logger.info("UI backend listening on %s", self._pipe_name)
        while not self._stop.is_set():
            handle = self._create_instance()
            try:
                win32pipe.ConnectNamedPipe(handle, None)
            except pywintypes.error as exc:
                logger.warning("ConnectNamedPipe failed: %s", exc)
                win32file.CloseHandle(handle)
                continue
            logger.info("UI backend client connected")
            try:
                self._serve_connection(handle)
            except Exception as exc:  # noqa: BLE001 — never let one client kill the server
                logger.error("connection handler crashed: %s", exc, exc_info=True)
            finally:
                self._close(handle)
                logger.info("UI backend client disconnected")

    def _create_instance(self) -> Any:
        return win32pipe.CreateNamedPipe(
            self._pipe_name,
            win32pipe.PIPE_ACCESS_DUPLEX,
            (
                win32pipe.PIPE_TYPE_BYTE
                | win32pipe.PIPE_READMODE_BYTE
                | win32pipe.PIPE_WAIT
                | _PIPE_REJECT_REMOTE_CLIENTS
            ),
            win32pipe.PIPE_UNLIMITED_INSTANCES,
            65536,  # out buffer
            65536,  # in buffer
            0,      # default timeout
            _pipe_security_attributes(),  # explicit SD so the de-elevated (Medium) UI can connect (ADR-019)
        )

    def _close(self, handle: Any) -> None:
        try:
            win32file.FlushFileBuffers(handle)
        except pywintypes.error:
            pass
        try:
            win32pipe.DisconnectNamedPipe(handle)
        except pywintypes.error:
            pass
        try:
            win32file.CloseHandle(handle)
        except pywintypes.error:
            pass

    # ── Per-connection servicing ──────────────────────────────────────

    def _serve_connection(self, handle: Any) -> None:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)

            def recv_exact(n: int) -> bytes:
                return self._read_exact(handle, n)

            async def send(frame: dict[str, Any]) -> None:
                # Synchronous pipe write bridged into the running loop. Quick
                # enough for a single connection that blocking the loop here
                # is acceptable.
                win32file.WriteFile(handle, encode_frame(frame))

            while not self._stop.is_set():
                try:
                    request = read_frame(recv_exact)
                except ProtocolError as exc:
                    cid = secrets.token_hex(4)
                    logger.warning(
                        "protocol error [cid=%s]: %s — closing connection", cid, exc
                    )
                    try:
                        loop.run_until_complete(
                            send(
                                error_response(
                                    None, "protocol_error",
                                    f"protocol error [{cid}]",
                                )
                            )
                        )
                    except pywintypes.error:
                        pass
                    return
                if request is None:
                    return  # clean EOF
                loop.run_until_complete(self._dispatcher.handle(request, send))
        finally:
            asyncio.set_event_loop(None)
            loop.close()

    def _read_exact(self, handle: Any, n: int) -> bytes:
        """Read exactly *n* bytes from the pipe, or b"" at EOF / broken pipe."""
        buf = bytearray()
        while len(buf) < n:
            want = min(_READ_CHUNK, n - len(buf))
            try:
                hr, chunk = win32file.ReadFile(handle, want)
            except pywintypes.error as exc:
                if exc.winerror in (_ERROR_BROKEN_PIPE, _ERROR_PIPE_NOT_CONNECTED):
                    return bytes(buf)  # peer closed
                raise
            if not chunk:
                return bytes(buf)
            buf.extend(chunk)
        return bytes(buf)


def serve_forever(
    gateway: Any,
    session_store: Any | None = None,
    pipe_name: str = DEFAULT_PIPE_NAME,
    voice: Any | None = None,
) -> NamedPipeServer:
    """Construct a :class:`NamedPipeServer` and run it (blocks).

    Returns the server instance after the accept loop exits (e.g. on stop).
    """
    server = NamedPipeServer(gateway, session_store, pipe_name, voice=voice)
    server.serve_forever()
    return server
