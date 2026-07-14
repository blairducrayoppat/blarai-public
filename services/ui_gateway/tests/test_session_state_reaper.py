"""
#801 — Gateway session-state reaper + PGOV turn-boundary eviction tests.

Locks the three gateway-side lifecycle behaviors:
  1. ``_pgov_cache`` is evicted at the turn boundary (each ``send_prompt``
     drops prior turns' verdicts — bounded O(1), read semantics preserved
     within a turn).
  2. Expired session-keyed transport dicts (pending documents, preview meta)
     are swept at turn start.
  3. The ingest/dispatch coordinators reap their pending slots — the ingest
     reap fires a best-effort REJECT through the AO decision path (cleaning
     the AO pending row + staging blob) and drops the RAM entry even when
     the AO is unreachable.

All expiry is driven through injected clocks/timestamps — no sleeps.
"""

from __future__ import annotations

from typing import Any

import pytest

from shared.ipc import MessageFramer, MessageType
from shared.ttl_dict import TtlDict
from services.ui_gateway.src.dispatch_coordinator import (
    DispatchCoordinator,
    PendingClarification,
    PendingDispatch,
    PendingRequirements,
)
from services.ui_gateway.src.ingest_coordinator import (
    IngestCoordinator,
    PendingIngest,
)
from services.ui_gateway.src.transport import (
    GatewayPGOVResult,
    StartupState,
    TransportGateway,
)
from shared.fleet.dispatch import build_default_config


class _FakeClock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _pgov(request_id: str) -> GatewayPGOVResult:
    return GatewayPGOVResult(
        approved=True,
        sanitized_text="ok",
        reason_codes=[],
        request_id=request_id,
    )


def _pending_ingest(doc_uuid: str = "d" * 32) -> PendingIngest:
    return PendingIngest(
        doc_uuid=doc_uuid,
        source_type="paste",
        source_ref=f"paste:{doc_uuid}",
        title="An Article",
        word_count=10,
        submitted_at="2026-07-11T00:00:00+00:00",
    )


class TestPgovTurnBoundaryEviction:
    """_pgov_cache is turn-scoped: prior turns' verdicts evict at send_prompt."""

    @pytest.mark.asyncio
    async def test_prior_turn_results_evicted_on_next_send(self) -> None:
        gw = TransportGateway()
        gw._state = StartupState.OPERATIONAL
        gw._pgov_cache["req-old-1"] = _pgov("req-old-1")
        gw._pgov_cache["req-old-2"] = _pgov("req-old-2")
        await gw.send_prompt("sess-1", "next turn")
        assert "req-old-1" not in gw._pgov_cache
        assert "req-old-2" not in gw._pgov_cache
        # The evicted entries now default-deny (fail-closed), as any unknown
        # request id always has.
        assert gw.get_pgov_result("req-old-1").approved is False

    @pytest.mark.asyncio
    async def test_result_read_semantics_within_turn_preserved(self) -> None:
        # NOT pop-on-read: within a turn the verdict can be read repeatedly.
        gw = TransportGateway()
        gw._state = StartupState.OPERATIONAL
        await gw.send_prompt("sess-1", "the turn")
        gw._pgov_cache["req-live"] = _pgov("req-live")  # arrives mid-stream
        assert gw.get_pgov_result("req-live").approved is True
        assert gw.get_pgov_result("req-live").approved is True  # re-read OK

    @pytest.mark.asyncio
    async def test_abandoned_turn_verdict_evicted_by_next_turn(self) -> None:
        # A stream-arc timeout can abandon a turn without reading its verdict;
        # the next turn's boundary eviction still bounds the cache.
        gw = TransportGateway()
        gw._state = StartupState.OPERATIONAL
        gw._pgov_cache["req-abandoned"] = _pgov("req-abandoned")
        await gw.send_prompt("sess-1", "later turn")
        assert len(gw._pgov_cache) == 0


class TestTransportDictSweep:
    """Expired pending documents / preview meta drop at turn start."""

    @pytest.mark.asyncio
    async def test_expired_pending_documents_swept(self) -> None:
        clock = _FakeClock()
        gw = TransportGateway()
        gw._state = StartupState.OPERATIONAL
        gw._pending_documents = TtlDict(clock=clock)
        gw._pending_documents["stale-sess"] = [{"filename": "a.txt", "content": "x"}]
        clock.advance(gw._session_state_ttl_s + 1.0)
        gw._pending_documents["fresh-sess"] = [{"filename": "b.txt", "content": "y"}]
        await gw.send_prompt("sess-1", "hello")
        assert "stale-sess" not in gw._pending_documents
        assert "fresh-sess" in gw._pending_documents

    @pytest.mark.asyncio
    async def test_expired_preview_meta_swept(self) -> None:
        clock = _FakeClock()
        gw = TransportGateway()
        gw._state = StartupState.OPERATIONAL
        gw._pending_preview_meta = TtlDict(clock=clock)
        gw._pending_preview_meta["stale-sess"] = {"doc_uuid": "d" * 32}
        clock.advance(gw._session_state_ttl_s + 1.0)
        await gw.send_prompt("sess-1", "hello")
        assert "stale-sess" not in gw._pending_preview_meta

    @pytest.mark.asyncio
    async def test_disabled_ttl_sweeps_nothing(self) -> None:
        clock = _FakeClock()
        gw = TransportGateway(session_state_ttl_s=0.0)
        gw._state = StartupState.OPERATIONAL
        gw._pending_documents = TtlDict(clock=clock)
        gw._pending_documents["kept-sess"] = [{"filename": "a.txt", "content": "x"}]
        clock.advance(10_000_000.0)
        await gw.send_prompt("sess-1", "hello")
        assert "kept-sess" in gw._pending_documents

    @pytest.mark.asyncio
    async def test_reaper_failure_never_breaks_the_turn(self) -> None:
        # Fail-soft: a hygiene failure logs and the prompt path proceeds.
        gw = TransportGateway()
        gw._state = StartupState.OPERATIONAL

        class _Boom(TtlDict):  # sweep raises; every dict op still works
            def sweep(self, ttl_s: float, now: float | None = None) -> list[str]:
                raise RuntimeError("hygiene boom")

        gw._pending_documents = _Boom()  # type: ignore[assignment]
        request_id = await gw.send_prompt("sess-1", "still works")
        assert isinstance(request_id, str) and len(request_id) == 36

    def test_fresh_load_restamps_pending_documents(self) -> None:
        # load_document appends in place — the touch must restart the idle
        # clock so a /load late in the TTL window is not swept moments after
        # the operator added a second document to it.
        clock = _FakeClock()
        gw = TransportGateway()
        gw._pending_documents = TtlDict(clock=clock)
        gw._pending_documents["sess-1"] = [{"filename": "a.txt", "content": "x"}]
        clock.advance(100.0)
        gw._pending_documents["sess-1"].append({"filename": "b.txt", "content": "y"})
        gw._pending_documents.touch("sess-1")  # what load_document now does
        assert gw._pending_documents.age_s("sess-1") == 0.0


class TestIngestReapExpired:
    """Expired pending ingests are rejected through the AO path + dropped."""

    def _coordinator(
        self, clock: _FakeClock, transport_result: dict[str, Any] | None = None
    ) -> tuple[IngestCoordinator, list[bytes]]:
        sent: list[bytes] = []
        result = transport_result or {
            "ok": True,
            "doc_uuid": "d" * 32,
            "state": "rejected",
            "chunk_count": 0,
        }

        async def _fake_transport_call(message: bytes) -> dict[str, Any]:
            sent.append(message)
            return dict(result)

        coordinator = IngestCoordinator(
            transport_call=_fake_transport_call,
            cipher_provider=lambda: None,
        )
        coordinator._pending = TtlDict(clock=clock)
        return coordinator, sent

    @pytest.mark.asyncio
    async def test_expired_pending_rejected_and_dropped(self) -> None:
        clock = _FakeClock()
        coordinator, sent = self._coordinator(clock)
        coordinator._pending["stale-sess"] = _pending_ingest()
        clock.advance(1_801.0)
        reaped = await coordinator.reap_expired(1_800.0)
        assert reaped == ["stale-sess"]
        assert coordinator.pending_for("stale-sess") is None
        # Exactly one INGEST_DECISION frame went to the AO carrying reject +
        # the pending doc's uuid — the same path /reject uses, so the AO's
        # pending row and the encrypted staging blob clean up too.
        assert len(sent) == 1
        msg_type, _req_id, payload = MessageFramer().decode(sent[0])
        assert msg_type == MessageType.INGEST_DECISION
        assert payload["decision"] == "reject"
        assert payload["doc_uuid"] == "d" * 32

    @pytest.mark.asyncio
    async def test_transport_failure_still_drops_ram_entry(self) -> None:
        # Fail-soft: the AO being down cannot hold the RAM bound hostage.
        clock = _FakeClock()
        coordinator, sent = self._coordinator(
            clock,
            transport_result={
                "ok": False,
                "doc_uuid": "",
                "state": "error",
                "chunk_count": 0,
                "error_code": "TRANSPORT_ERROR",
                "message": "AO unreachable",
            },
        )
        coordinator._pending["stale-sess"] = _pending_ingest()
        clock.advance(1_801.0)
        reaped = await coordinator.reap_expired(1_800.0)
        assert reaped == ["stale-sess"]
        assert coordinator.pending_for("stale-sess") is None

    @pytest.mark.asyncio
    async def test_fresh_pending_untouched_and_no_reject_sent(self) -> None:
        clock = _FakeClock()
        coordinator, sent = self._coordinator(clock)
        coordinator._pending["fresh-sess"] = _pending_ingest()
        clock.advance(10.0)
        assert await coordinator.reap_expired(1_800.0) == []
        assert coordinator.pending_for("fresh-sess") is not None
        assert sent == []

    @pytest.mark.asyncio
    async def test_disabled_ttl_reaps_nothing(self) -> None:
        clock = _FakeClock()
        coordinator, sent = self._coordinator(clock)
        coordinator._pending["sess"] = _pending_ingest()
        clock.advance(10_000_000.0)
        assert await coordinator.reap_expired(0.0) == []
        assert coordinator.pending_for("sess") is not None


class TestDispatchReapExpired:
    """Expired pending plans/clarifications/action-signals drop (implicit reject)."""

    def _coordinator(self, clock: _FakeClock) -> DispatchCoordinator:
        coordinator = DispatchCoordinator(
            config=build_default_config(),
            enabled=True,
        )
        coordinator._pending = TtlDict(clock=clock)
        coordinator._clarifying = TtlDict(clock=clock)
        coordinator._requirements = TtlDict(clock=clock)
        coordinator._last_action = TtlDict(clock=clock)
        return coordinator

    def test_expired_slots_dropped(self) -> None:
        clock = _FakeClock()
        coordinator = self._coordinator(clock)
        coordinator._pending["s-plan"] = PendingDispatch(
            run_id="r1", repo="repo", goal="goal"
        )
        coordinator._clarifying["s-question"] = PendingClarification(
            run_id="r2", repo="repo", goal="goal"
        )
        coordinator._requirements["s-req"] = PendingRequirements(
            run_id="r3", repo="repo", goal="goal"
        )
        coordinator._last_action["s-action"] = "dispatch_plan"
        clock.advance(1_801.0)
        reaped = coordinator.reap_expired(1_800.0)
        assert reaped == {
            "pending": ["s-plan"],
            "clarifying": ["s-question"],
            "requirements": ["s-req"],
            "last_action": ["s-action"],
        }
        assert coordinator.pending_for("s-plan") is None
        assert coordinator.pending_clarification_for("s-question") is None
        assert coordinator.pending_requirements_for("s-req") is None
        assert coordinator.pop_action_kind("s-action") == ""

    def test_fresh_slots_survive(self) -> None:
        clock = _FakeClock()
        coordinator = self._coordinator(clock)
        coordinator._pending["s-plan"] = PendingDispatch(
            run_id="r1", repo="repo", goal="goal"
        )
        clock.advance(10.0)
        reaped = coordinator.reap_expired(1_800.0)
        assert reaped == {"pending": [], "clarifying": [], "requirements": [], "last_action": []}
        assert coordinator.pending_for("s-plan") is not None

    def test_disabled_ttl_reaps_nothing(self) -> None:
        clock = _FakeClock()
        coordinator = self._coordinator(clock)
        coordinator._pending["s-plan"] = PendingDispatch(
            run_id="r1", repo="repo", goal="goal"
        )
        clock.advance(10_000_000.0)
        reaped = coordinator.reap_expired(-1.0)
        assert reaped == {"pending": [], "clarifying": [], "requirements": [], "last_action": []}
        assert coordinator.pending_for("s-plan") is not None


class TestGatewayCoordinatorWiring:
    """The turn-start sweep reaches both coordinators through the gateway."""

    @pytest.mark.asyncio
    async def test_send_prompt_drives_coordinator_reaps(self) -> None:
        clock = _FakeClock()
        gw = TransportGateway()
        gw._state = StartupState.OPERATIONAL

        # Real coordinators on injected clocks, wired exactly as production
        # (the ingest transport_call is faked so no AO is needed).
        async def _fake_transport_call(message: bytes) -> dict[str, Any]:
            return {"ok": True, "doc_uuid": "d" * 32, "state": "rejected",
                    "chunk_count": 0}

        gw._ingest_coordinator = IngestCoordinator(
            transport_call=_fake_transport_call,
            cipher_provider=lambda: None,
        )
        gw._ingest_coordinator._pending = TtlDict(clock=clock)
        gw._ingest_coordinator._pending["stale-ingest"] = _pending_ingest()
        gw._dispatch_coordinator._pending = TtlDict(clock=clock)
        gw._dispatch_coordinator._pending["stale-plan"] = PendingDispatch(
            run_id="r1", repo="repo", goal="goal"
        )
        clock.advance(gw._session_state_ttl_s + 1.0)

        await gw.send_prompt("sess-1", "hello")

        assert gw._ingest_coordinator.pending_for("stale-ingest") is None
        assert gw._dispatch_coordinator.pending_for("stale-plan") is None
