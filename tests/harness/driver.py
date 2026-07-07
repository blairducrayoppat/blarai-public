"""In-process backend driver — drive the REAL dispatcher with no GUI.

The named-pipe server (``services/ui_backend/src/server.py``) runs ONE
``run_until_complete`` loop per connection and feeds decoded requests to
:meth:`RpcDispatcher.handle`. This driver does the same thing in-process:
it constructs a real :class:`RpcDispatcher` over an injected gateway/store/voice
and drives ``handle`` directly, collecting frames and timing each call.

The key probe is :meth:`InProcessBackend.call_concurrent`, which runs several
requests on a single event loop the way the server's loop would interleave
them — the measurement that proves a blocking handler does not starve its
neighbours (the freeze regression lock).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from services.ui_backend.src.dispatcher import RpcDispatcher
from tests.harness.fakes import CollectingSend


@dataclass
class CallResult:
    """Frames + timing for a single dispatched request.

    Times are milliseconds relative to a shared start captured by the driver, so
    two concurrent calls can be compared on one timeline.
    """

    method: str
    frames: list[dict[str, Any]] = field(default_factory=list)
    frame_times_ms: list[float] = field(default_factory=list)
    started_rel_ms: float = 0.0
    finished_rel_ms: float = 0.0

    @property
    def elapsed_ms(self) -> float:
        return self.finished_rel_ms - self.started_rel_ms

    @property
    def ok_result(self) -> Any:
        for f in self.frames:
            if f.get("ok") is True:
                return f.get("result")
        return None

    @property
    def error(self) -> dict[str, Any] | None:
        for f in self.frames:
            if f.get("ok") is False:
                return f.get("error")
        return None

    def stream_values(self, kind: str) -> list[Any]:
        return [f["value"] for f in self.frames if f.get("stream") == kind]

    def has_stream(self, kind: str) -> bool:
        return any(f.get("stream") == kind for f in self.frames)


class InProcessBackend:
    """Wrap a real :class:`RpcDispatcher` and drive it in-process.

    Args:
        gateway: A TransportGateway (or compatible fake).
        session_store: A SessionStore (or ``None`` for no persistence).
        voice: A VoiceEngine (or ``None`` for voice-disabled).
        dispatcher_cls: The dispatcher class to instantiate. Defaults to the
            real :class:`RpcDispatcher`; tests can supply a subclass to
            reconstruct a pre-fix regression (e.g. sync-on-loop dispatch).
        prompt_stream_failsafe_s: Override the prompt-stream fail-safe deadline
            on the constructed dispatcher. ``None`` uses the dispatcher's own
            default (module constant). Pass a short value in tests that need the
            fail-safe to fire quickly without waiting 90 s.
    """

    def __init__(
        self,
        gateway: Any,
        session_store: Any | None = None,
        voice: Any | None = None,
        dispatcher_cls: type = RpcDispatcher,
        prompt_stream_failsafe_s: float | None = None,
    ) -> None:
        # dispatcher_cls is injectable so a meta-test can drive a deliberately
        # broken (sync-on-loop) dispatcher and prove the concurrency probe has
        # teeth — see test_freeze_regression.py.
        kwargs: dict[str, Any] = {"voice": voice}
        if prompt_stream_failsafe_s is not None:
            kwargs["prompt_stream_failsafe_s"] = prompt_stream_failsafe_s
        self._dispatcher = dispatcher_cls(gateway, session_store, **kwargs)
        self._rid = 0

    def _next_rid(self) -> int:
        self._rid += 1
        return self._rid

    async def call(self, method: str, params: dict[str, Any] | None = None) -> CallResult:
        """Run one request to completion and return its frames + elapsed time."""
        (result,) = await self.call_concurrent([(method, params or {})])
        return result

    async def call_concurrent(
        self, calls: Sequence[tuple[str, dict[str, Any] | None]]
    ) -> list[CallResult]:
        """Run several requests CONCURRENTLY on one event loop.

        Mirrors how the server's single per-connection loop interleaves
        in-flight work. Each call gets its own ``send`` sink and timestamps
        relative to a shared start, so a blocking handler that starves its
        neighbours is visible as a late ``finished_rel_ms`` on the neighbour.
        """
        t_start = time.perf_counter()

        async def _one(method: str, params: dict[str, Any] | None) -> CallResult:
            send = CollectingSend()
            started = (time.perf_counter() - t_start) * 1000.0
            request = {"id": self._next_rid(), "method": method, "params": params or {}}
            await self._dispatcher.handle(request, send)
            finished = (time.perf_counter() - t_start) * 1000.0
            return CallResult(
                method=method,
                frames=send.frames,
                frame_times_ms=[(t - t_start) * 1000.0 for t in send.times],
                started_rel_ms=started,
                finished_rel_ms=finished,
            )

        return await asyncio.gather(*[_one(m, p) for m, p in calls])
