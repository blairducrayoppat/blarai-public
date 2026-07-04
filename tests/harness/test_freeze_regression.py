"""Layer A — freeze-regression lock for the image-attach path (#561, #563).

NO models, NO GPU. Runs in the default ``pytest`` suite. Locks the *off-loop*
half of the fix in commit ``f4406c5`` ("perf(ui): move document load/attach off
the event loop"): the dispatcher runs the blocking ``gateway.load_document`` on a
worker thread, not the event-loop thread, so a slow grounding call can never
again freeze voice + chat behind it (BUILD_JOURNAL lessons 24 + 25 — the
~5-minute voice queue the User-Operator hit on the 2026-06-03 live boot).

The *lazy* half (attach does not call the VLM) is already unit-locked in
``services/ui_gateway/tests/test_document_loader_media.py``; this file locks the
complementary off-loop half, which was covered nowhere.

PRIMARY LOCK — ``test_attach_runs_off_the_event_loop_thread`` — asserts the exact
property the fix guarantees and the server's per-connection loop depends on, by
comparing **thread identities**, so it is immune to scheduling jitter. The same
test reconstructs the pre-fix sync-on-loop dispatcher and proves it runs the load
ON the loop thread, so the lock cannot silently rot.

The concurrency probes (``does_not_starve`` / ``does_not_stall``) are
complementary loop-responsiveness checks. NOTE: the real backend serialises
requests per connection (``server.py`` runs one ``run_until_complete`` at a
time); these ``gather``-based probes amplify the contention onto one loop to make
the off-loop benefit observable, and they assert RELATIVE invariants (the
neighbour beat the block by a wide margin) so they survive a uniformly slow CI
box rather than a brittle absolute millisecond budget.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from services.ui_backend.src.dispatcher import RpcDispatcher
from services.ui_backend.src.protocol import ok_response
from tests.harness.driver import InProcessBackend
from tests.harness.fakes import FakeGateway

# Long enough to dwarf scheduling jitter, short enough to keep the suite fast.
BLOCK_S = 0.5


class _OnLoopDispatcher(RpcDispatcher):
    """The pre-``f4406c5`` regression: a blocking load_document run ON the loop."""

    async def _m_load_document(self, rid, params, send) -> None:  # type: ignore[override]
        result = self._gateway.load_document(params["session_id"], params["filename"])
        await send(ok_response(rid, result))


async def test_attach_runs_off_the_event_loop_thread() -> None:
    """PRIMARY LOCK: the blocking load runs OFF the event-loop thread.

    The async test body runs on the loop thread, so its ``get_ident()`` is the
    loop's. The fixed dispatcher must run ``load_document`` on a DIFFERENT thread
    (``asyncio.to_thread``); the reconstructed on-loop dispatcher runs it on the
    SAME thread. Thread identity, not timing — no jitter exposure.
    """
    loop_thread_id = threading.get_ident()

    # Fixed dispatcher (real RpcDispatcher): load must run off the loop thread.
    fixed_gw = FakeGateway(block_s=0.01)
    fixed = InProcessBackend(fixed_gw, session_store=None, voice=None)
    res = await fixed.call("load_document", {"session_id": "s", "filename": "cat.png"})
    assert res.error is None
    assert res.ok_result is not None and res.ok_result["pending_vision"] is True
    assert fixed_gw.load_thread_id is not None
    assert fixed_gw.load_thread_id != loop_thread_id  # OFF the loop thread — the fix

    # Teeth: the pre-fix on-loop dispatcher runs the load ON the loop thread.
    onloop_gw = FakeGateway(block_s=0.01)
    onloop = InProcessBackend(
        onloop_gw, session_store=None, voice=None, dispatcher_cls=_OnLoopDispatcher
    )
    await onloop.call("load_document", {"session_id": "s", "filename": "cat.png"})
    assert onloop_gw.load_thread_id == loop_thread_id  # ON the loop — the regression


async def test_attach_does_not_starve_a_concurrent_request() -> None:
    """A blocking attach must not freeze a concurrent voice_status request.

    Relative invariant: the canary completes at least half the block earlier than
    the attach — only possible if the attach ran off the loop. Survives a
    uniformly slow machine because both timestamps share the slowdown.
    """
    gateway = FakeGateway(block_s=BLOCK_S)
    backend = InProcessBackend(gateway, session_store=None, voice=None)

    attach, canary = await backend.call_concurrent(
        [
            ("load_document", {"session_id": "s", "filename": "cat.png"}),
            ("voice_status", {}),
        ]
    )

    assert gateway.load_calls == [("s", "cat.png")]
    assert attach.elapsed_ms >= BLOCK_S * 1000.0 * 0.8  # the slow load really ran
    assert canary.error is None
    assert canary.ok_result == {"stt": False, "tts": False, "voices": []}
    assert canary.finished_rel_ms < attach.finished_rel_ms - BLOCK_S * 1000.0 * 0.5


async def test_concurrency_probe_has_teeth() -> None:
    """Meta-guard: the relative invariant above DOES fail on a sync-on-loop attach.

    Reconstructs the pre-fix dispatcher and confirms the canary is starved (does
    NOT beat the attach by half the block), so the probe cannot silently rot.
    """
    gateway = FakeGateway(block_s=BLOCK_S)
    backend = InProcessBackend(
        gateway, session_store=None, voice=None, dispatcher_cls=_OnLoopDispatcher
    )

    attach, canary = await backend.call_concurrent(
        [
            ("load_document", {"session_id": "s", "filename": "cat.png"}),
            ("voice_status", {}),
        ]
    )

    # On-loop: the canary cannot finish until the block clears, so it does NOT
    # satisfy the off-loop invariant. (This is exactly what the primary probe
    # forbids — proving that probe has teeth.)
    assert not (canary.finished_rel_ms < attach.finished_rel_ms - BLOCK_S * 1000.0 * 0.5)


async def test_attach_does_not_stall_chat_streaming() -> None:
    """A blocking attach must not stall a concurrent streaming chat turn, and the
    chat's frames keep the contract order ``token* -> pgov -> end``."""
    gateway = FakeGateway(block_s=BLOCK_S, reply="one two three four five", token_delay_s=0.02)
    backend = InProcessBackend(gateway, session_store=None, voice=None)

    attach, chat = await backend.call_concurrent(
        [
            ("load_document", {"session_id": "s", "filename": "cat.png"}),
            ("prompt", {"session_id": "s", "prompt": "hello"}),
        ]
    )

    assert chat.stream_values("token"), "expected streamed tokens"
    assert chat.has_stream("end")

    # Frame-ordering contract: every token precedes pgov, which precedes end.
    kinds = [f["stream"] for f in chat.frames if "stream" in f]
    assert kinds[-2:] == ["pgov", "end"]
    first_pgov = kinds.index("pgov")
    assert all(i < first_pgov for i, k in enumerate(kinds) if k == "token")

    # Not stalled: the chat completed before the attach block cleared.
    assert chat.finished_rel_ms < attach.finished_rel_ms


async def test_attach_returns_lazy_descriptor_through_real_gateway(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end on the REAL dispatcher + gateway + document_loader (no models).

    Proves the whole attach path returns the lazy descriptor with no grounded
    content, and stashes the full ``pending_vision`` descriptor for on-demand
    grounding — the contract the AO relies on.
    """
    import services.ui_gateway.src.document_loader as dl
    from services.ui_gateway.src.transport import TransportGateway

    monkeypatch.setattr(dl, "USERDATA_DIR", tmp_path)
    (tmp_path / "cat.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)

    gateway = TransportGateway(session_store=None, dev_mode=True, port=0)
    backend = InProcessBackend(gateway, session_store=None, voice=None)

    result = await backend.call("load_document", {"session_id": "s", "filename": "cat.png"})

    assert result.error is None
    assert result.ok_result is not None
    assert result.ok_result["media_type"] == "image"
    assert result.ok_result["content"] == ""  # nothing grounded at attach
    assert "ask about it" in result.ok_result["message"]

    pending = gateway._pending_documents["s"]
    assert len(pending) == 1
    assert pending[0]["pending_vision"] is True
    assert pending[0]["image_path"].endswith("cat.png")
