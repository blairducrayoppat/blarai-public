"""Gateway-level tests for the ingest command surface (#655 Stage B).

Covers TransportGateway.handle_ingest_command (interception + informational
turn persistence + the bare-URL nudge), the shared-DEK cipher exposure
(`_session_cipher` reading the session store's `field_cipher`), the
fresh-connection ingest transport call, and the informational-turn exclusion
from the prompt-history budget.  Model-free; no AO; no real %LOCALAPPDATA%.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from services.ui_gateway.src.ingest_coordinator import IngestCoordinator
from services.ui_gateway.src.session_store import (
    INFORMATIONAL_TURN_STATUS,
    EncryptedSessionStore,
    SessionStore,
)
from services.ui_gateway.src.transport import StartupState, TransportGateway
from shared.ipc import MessageFramer
from shared.security.field_cipher import FieldCipher, derive_subkeys

_framer = MessageFramer()


# ---------------------------------------------------------------------------
# Fakes (mirrors the existing _MockTransport / _CapturingTransport patterns)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FakeCleanResult:
    status: str = "clean"
    text: str = "Cleaned informational body."
    title: str | None = "Preview Title"
    byline: str | None = None
    published_date: str | None = None
    word_count: int = 3
    confidence: float = 0.9
    reasons: tuple[str, ...] = ()
    cleaner_version: str = "1.0.0"
    source_format: str = "text"


@dataclass
class FakePipeline:
    result: Any = field(default_factory=FakeCleanResult)

    def loader(self):
        def clean_text(raw: str):
            return self.result

        def clean_html(raw: str, *, source_url: str | None = None):
            return self.result

        return clean_text, clean_html


class FakeTransportCall:
    def __init__(self) -> None:
        self.sent: list[bytes] = []

    async def __call__(self, message: bytes) -> dict[str, Any]:
        self.sent.append(message)
        payload = json.loads(message.decode("utf-8"))["payload"]
        return {
            "ok": True,
            "doc_uuid": payload.get("doc_uuid", ""),
            "state": "pending",
            "chunk_count": 0,
            "error_code": "",
            "message": "",
        }


class _RespondingTransport:
    """Fake VsockTransport: captures send(), replies with scripted receive()."""

    def __init__(self, response: bytes | None) -> None:
        self.sent: list[bytes] = []
        self._response = response
        self.connected = True
        self.closed = False

    def send(self, data: bytes) -> bool:
        self.sent.append(data)
        return True

    def receive(self) -> bytes | None:
        return self._response

    def close(self) -> None:
        self.closed = True


def _cipher() -> FieldCipher:
    return FieldCipher(derive_subkeys(b"\x09" * 32))


def _make_gateway(
    tmp_path: Path, clean_result: Any | None = None
) -> tuple[TransportGateway, EncryptedSessionStore, FakeTransportCall]:
    store = EncryptedSessionStore(db_path=":memory:", cipher=_cipher())
    gw = TransportGateway(session_store=store, dev_mode=True, port=0)
    gw._state = StartupState.OPERATIONAL
    fake_call = FakeTransportCall()
    (tmp_path / "userdata").mkdir(exist_ok=True)
    pipeline = (
        FakePipeline(result=clean_result) if clean_result is not None else FakePipeline()
    )
    gw._ingest_coordinator = IngestCoordinator(
        transport_call=fake_call,
        cipher_provider=gw._session_cipher,
        pipeline_loader=pipeline.loader,
        staging_dir_provider=lambda: tmp_path / "staging",
        userdata_dir=tmp_path / "userdata",
    )
    return gw, store, fake_call


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Interception routing
# ---------------------------------------------------------------------------


class TestHandleIngestCommandRouting:
    def test_normal_prompt_returns_none(self, tmp_path: Path) -> None:
        gw, store, _ = _make_gateway(tmp_path)
        sid = store.create_session("t")
        assert _run(gw.handle_ingest_command(sid, "What is the weather?")) is None
        # Nothing persisted by the interception path.
        assert store.get_session_turns(sid) == []

    def test_url_in_sentence_returns_none(self, tmp_path: Path) -> None:
        gw, store, _ = _make_gateway(tmp_path)
        sid = store.create_session("t")
        reply = _run(gw.handle_ingest_command(
            sid, "Summarize https://example.com/a for me"
        ))
        assert reply is None
        assert store.get_session_turns(sid) == []

    def test_empty_prompt_returns_none(self, tmp_path: Path) -> None:
        gw, store, _ = _make_gateway(tmp_path)
        sid = store.create_session("t")
        assert _run(gw.handle_ingest_command(sid, "   ")) is None

    def test_other_slash_commands_return_none(self, tmp_path: Path) -> None:
        gw, store, _ = _make_gateway(tmp_path)
        sid = store.create_session("t")
        assert _run(gw.handle_ingest_command(sid, "/external some text")) is None
        assert _run(gw.handle_ingest_command(sid, "/load notes.txt")) is None

    def test_ingest_command_is_handled(self, tmp_path: Path) -> None:
        gw, store, fake_call = _make_gateway(tmp_path)
        sid = store.create_session("t")
        reply = _run(gw.handle_ingest_command(sid, "/ingest pasted article body"))
        assert reply is not None
        assert "Ingest preview" in reply
        assert len(fake_call.sent) == 1

    def test_bare_url_gets_nudge_without_model_or_fetch(self, tmp_path: Path) -> None:
        gw, store, fake_call = _make_gateway(tmp_path)
        sid = store.create_session("t")
        reply = _run(gw.handle_ingest_command(sid, "  https://example.com/story  "))
        assert reply is not None
        assert "/ingest https://example.com/story" in reply
        assert fake_call.sent == []  # no IPC, no fetch, no model call


# ---------------------------------------------------------------------------
# Informational-turn persistence
# ---------------------------------------------------------------------------


class TestInformationalTurnPersistence:
    def test_ingest_persists_stub_user_and_informational_turns(
        self, tmp_path: Path
    ) -> None:
        """The persisted USER turn is the labels-only stub (#655 LA verdict
        2026-06-10) — never the raw /ingest argument; the persisted assistant
        turn is the labels-only summary, not the body-bearing preview."""
        gw, store, _ = _make_gateway(tmp_path)
        sid = store.create_session("")
        reply = _run(gw.handle_ingest_command(sid, "/ingest pasted article body"))
        assert reply is not None and "Ingest preview" in reply  # live reply intact

        pending = gw._ingest_coordinator.pending_for(sid)
        assert pending is not None
        turns = store.get_session_turns(sid)
        assert [t.role for t in turns] == ["user", "assistant"]
        assert turns[0].content == (
            f"/ingest <article: 3 words, doc {pending.doc_uuid[:8]}>"
        )
        assert turns[0].pgov_status == "N/A"
        assert turns[1].content != reply  # preview body never persists
        assert "pending your decision" in turns[1].content
        assert turns[1].pgov_status == INFORMATIONAL_TURN_STATUS

    def test_bare_url_nudge_persists_with_marker(self, tmp_path: Path) -> None:
        gw, store, _ = _make_gateway(tmp_path)
        sid = store.create_session("")
        reply = _run(gw.handle_ingest_command(sid, "https://example.com/x"))
        turns = store.get_session_turns(sid)
        assert turns[1].pgov_status == INFORMATIONAL_TURN_STATUS
        assert turns[1].content == reply

    def test_first_command_auto_titles_session(self, tmp_path: Path) -> None:
        gw, store, _ = _make_gateway(tmp_path)
        sid = store.create_session("")
        _run(gw.handle_ingest_command(sid, "/ingest pasted article body"))
        sessions = {s.id: s for s in store.list_sessions()}
        assert sessions[sid].title  # auto-title fired, mirrors send_prompt

    def test_no_store_still_replies(self, tmp_path: Path) -> None:
        gw, _store, _ = _make_gateway(tmp_path)
        gw._session_store = None
        # cipher_provider now returns None -> the coordinator refuses loudly,
        # but the reply text still comes back (no crash, no persistence).
        reply = _run(gw.handle_ingest_command("s", "/ingest pasted"))
        assert reply is not None

    def test_informational_turns_excluded_from_prompt_history(
        self, tmp_path: Path
    ) -> None:
        """Later-prompt history carries the labels-only STUB and nothing
        else from the ingest turn: not the raw paste (the user-turn stub fix,
        #655 LA verdict 2026-06-10) and not the article-sized preview (the
        informational marker keeps assistant turns out)."""
        gw, store, _ = _make_gateway(tmp_path)
        sid = store.create_session("")
        preview = _run(gw.handle_ingest_command(sid, "/ingest pasted article body"))
        assert preview is not None
        pending = gw._ingest_coordinator.pending_for(sid)
        assert pending is not None

        captured: list[Any] = []

        async def _fake_open():
            t = _RespondingTransport(response=None)
            captured.append(t)
            return t

        gw._open_prompt_transport = _fake_open  # type: ignore[method-assign]
        _run(gw.send_prompt(sid, "a follow-up question"))

        payload = json.loads(captured[0].sent[0].decode("utf-8"))["payload"]
        history = payload["history"]
        stub = f"/ingest <article: 3 words, doc {pending.doc_uuid[:8]}>"
        # History contains the stub ONLY — never the raw /ingest message.
        assert any(e["content"] == stub for e in history)
        assert all("pasted article body" not in e["content"] for e in history)
        assert all(e["content"] != preview for e in history)
        assert all(
            e["role"] != "assistant" or e["content"] != preview for e in history
        )


# ---------------------------------------------------------------------------
# Shared-DEK cipher exposure
# ---------------------------------------------------------------------------


class TestSessionCipherProvider:
    def test_encrypted_store_exposes_field_cipher(self) -> None:
        cipher = _cipher()
        store = EncryptedSessionStore(db_path=":memory:", cipher=cipher)
        gw = TransportGateway(session_store=store, dev_mode=True, port=0)
        assert gw._session_cipher() is cipher
        assert store.field_cipher is cipher

    def test_plain_store_has_no_cipher(self) -> None:
        gw = TransportGateway(
            session_store=SessionStore(db_path=":memory:"), dev_mode=True, port=0
        )
        assert gw._session_cipher() is None

    def test_no_store_has_no_cipher(self) -> None:
        gw = TransportGateway(session_store=None, dev_mode=True, port=0)
        assert gw._session_cipher() is None


# ---------------------------------------------------------------------------
# images_enabled weld-lock threading (UC-003 Workstream B #1)
# ---------------------------------------------------------------------------


class TestImagesEnabledWiring:
    """The gateway threads the resolved [knowledge].images_enabled flag into the
    ingest coordinator's image FETCH gate. Default-dormant; the launcher passes
    the AO-resolved value at boot so flipping config actually reaches the gateway."""

    def test_default_construction_is_dormant(self) -> None:
        gw = TransportGateway(dev_mode=True, port=0)
        assert gw._images_enabled is False
        assert gw._ingest_coordinator._images_enabled is False

    def test_images_enabled_true_reaches_coordinator(self) -> None:
        gw = TransportGateway(dev_mode=True, port=0, images_enabled=True)
        assert gw._images_enabled is True
        assert gw._ingest_coordinator._images_enabled is True


# ---------------------------------------------------------------------------
# Fresh-connection ingest transport call
# ---------------------------------------------------------------------------


class TestIngestTransportCall:
    def _gateway(self) -> TransportGateway:
        gw = TransportGateway(dev_mode=True, port=0)
        gw._state = StartupState.OPERATIONAL
        return gw

    def test_round_trip_decodes_ingest_result(self) -> None:
        gw = self._gateway()
        response = _framer.encode_ingest_result(
            ok=True, doc_uuid="d-1", state="pending", request_id="r-1"
        )
        transport = _RespondingTransport(response)

        async def _fake_open():
            return transport

        gw._open_prompt_transport = _fake_open  # type: ignore[method-assign]
        msg = _framer.encode_ingest_decision(doc_uuid="d-1", decision="approve")
        result = _run(gw._ingest_transport_call(msg))
        assert result["ok"] is True
        assert result["state"] == "pending"
        assert transport.sent == [msg]
        assert transport.closed is True  # connection-per-message hygiene

    def test_connect_failure_is_error_shaped(self) -> None:
        gw = self._gateway()

        async def _fake_open():
            return None

        gw._open_prompt_transport = _fake_open  # type: ignore[method-assign]
        result = _run(gw._ingest_transport_call(b"{}"))
        assert result["ok"] is False
        assert result["error_code"] == "TRANSPORT_ERROR"

    def test_no_response_is_error_shaped(self) -> None:
        gw = self._gateway()
        transport = _RespondingTransport(response=None)

        async def _fake_open():
            return transport

        gw._open_prompt_transport = _fake_open  # type: ignore[method-assign]
        result = _run(gw._ingest_transport_call(b"{}"))
        assert result["ok"] is False
        assert result["error_code"] == "TRANSPORT_ERROR"
        assert transport.closed is True

    def test_wrong_frame_type_is_error_shaped(self) -> None:
        gw = self._gateway()
        wrong = _framer.encode_generation_complete(request_id="r")
        transport = _RespondingTransport(wrong)

        async def _fake_open():
            return transport

        gw._open_prompt_transport = _fake_open  # type: ignore[method-assign]
        result = _run(gw._ingest_transport_call(b"{}"))
        assert result["ok"] is False
        assert result["error_code"] == "TRANSPORT_ERROR"

    def test_send_failure_is_error_shaped(self) -> None:
        gw = self._gateway()

        class _SendFailTransport(_RespondingTransport):
            def send(self, data: bytes) -> bool:
                return False

        transport = _SendFailTransport(response=None)

        async def _fake_open():
            return transport

        gw._open_prompt_transport = _fake_open  # type: ignore[method-assign]
        result = _run(gw._ingest_transport_call(b"{}"))
        assert result["ok"] is False
        assert transport.closed is True


# ---------------------------------------------------------------------------
# /ingest paste persistence stub (#655 LA verdict 2026-06-10)
# ---------------------------------------------------------------------------


_RAW_PASTE = (
    "ZEBRA-MARKER raw pre-cleaning web text with boilerplate menus and "
    "cookie banners that must never reach the session store ZEBRA-MARKER"
)


class TestIngestPastePersistenceStub:
    """The raw /ingest argument (up to ~40 KB of pre-cleaning web text) must
    never persist anywhere in sessions.db: persisted user turns are forwarded
    verbatim into later prompt history — an unmarked injection channel
    bypassing every defense the knowledge bank applies to the same content."""

    def test_raw_paste_absent_from_session_store_dump(
        self, tmp_path: Path
    ) -> None:
        cleaned = FakeCleanResult(
            text="GIRAFFE-CLEANED article body of real signal.", word_count=7
        )
        gw, store, _ = _make_gateway(tmp_path, clean_result=cleaned)
        sid = store.create_session("")
        reply = _run(gw.handle_ingest_command(sid, f"/ingest {_RAW_PASTE}"))
        assert reply is not None and "GIRAFFE-CLEANED" in reply  # live preview OK

        # Dump EVERYTHING the store holds for the session: turns + title.
        dump = [t.content for t in store.get_session_turns(sid)]
        dump.extend(s.title for s in store.list_sessions())
        for item in dump:
            assert "ZEBRA-MARKER" not in item, "raw paste persisted!"
            # The cleaned article body must not persist either — it IS the
            # paste, post-boilerplate; the preview is live-display-only.
            assert "GIRAFFE-CLEANED" not in item, "article body persisted!"

    def test_stub_format_locked(self, tmp_path: Path) -> None:
        """Exact stub shape: '/ingest <article: {N} words, doc {uuid8}>' —
        deliberately NO content-hash prefix (orchestrator decision): a
        truncated digest would re-seed the content-fingerprint membership
        oracle into sessions.db."""
        gw, store, _ = _make_gateway(tmp_path)
        sid = store.create_session("")
        _run(gw.handle_ingest_command(sid, f"/ingest {_RAW_PASTE}"))
        pending = gw._ingest_coordinator.pending_for(sid)
        assert pending is not None
        user_turn = store.get_session_turns(sid)[0]
        assert user_turn.content == (
            f"/ingest <article: 3 words, doc {pending.doc_uuid[:8]}>"
        )
        # No content digest anywhere in the stub (the cleaned-content sha).
        cleaned_sha = hashlib.sha256(
            FakeCleanResult().text.encode("utf-8")
        ).hexdigest()
        for prefix_len in (8, 12, 16):
            assert cleaned_sha[:prefix_len] not in user_turn.content

    def test_unsubmitted_ingest_persists_labels_only_stub(
        self, tmp_path: Path
    ) -> None:
        """A refused /ingest (here: the URL limb refused because no guest
        parser is running) still persists a labels-only stub, never the raw
        argument."""
        gw, store, _ = _make_gateway(tmp_path)
        sid = store.create_session("")
        reply = _run(
            gw.handle_ingest_command(sid, "/ingest https://example.com/story")
        )
        assert reply is not None and "unavailable" in reply.lower()
        turns = store.get_session_turns(sid)
        assert turns[0].content == "/ingest <article: 1 words, not submitted>"
        assert "https://example.com/story" not in turns[0].content

    def test_approve_and_reject_turns_unaffected(self, tmp_path: Path) -> None:
        """/approve and /reject persist verbatim — short commands, no content."""
        gw, store, _ = _make_gateway(tmp_path)
        sid = store.create_session("")
        _run(gw.handle_ingest_command(sid, f"/ingest {_RAW_PASTE}"))
        reply = _run(gw.handle_ingest_command(sid, "/approve"))
        assert reply is not None and "Approved" in reply

        turns = store.get_session_turns(sid)
        assert turns[2].role == "user"
        assert turns[2].content == "/approve"
        assert turns[3].content == reply  # decision reply persists as-is

        # And /reject on a fresh session.
        sid2 = store.create_session("")
        _run(gw.handle_ingest_command(sid2, "/ingest different paste text"))
        reply2 = _run(gw.handle_ingest_command(sid2, "/reject"))
        assert reply2 is not None and "Rejected" in reply2
        turns2 = store.get_session_turns(sid2)
        assert turns2[2].content == "/reject"
        assert turns2[3].content == reply2

    def test_untitled_paste_decision_messages_carry_no_content_digest(
        self, tmp_path: Path
    ) -> None:
        """For an untitled paste the pending label falls back to the opaque
        doc handle — never 'paste:<content-sha256>', whose persistence in the
        /approve message would re-seed the membership oracle into sessions.db."""
        cleaned = FakeCleanResult(title=None, text="untitled cleaned body.")
        gw, store, _ = _make_gateway(tmp_path, clean_result=cleaned)
        sid = store.create_session("")
        _run(gw.handle_ingest_command(sid, f"/ingest {_RAW_PASTE}"))
        pending = gw._ingest_coordinator.pending_for(sid)
        assert pending is not None
        assert pending.label == f"pasted article (doc {pending.doc_uuid[:8]})"

        reply = _run(gw.handle_ingest_command(sid, "/approve"))
        assert reply is not None and "Approved" in reply
        cleaned_sha = hashlib.sha256(cleaned.text.encode("utf-8")).hexdigest()
        for item in [t.content for t in store.get_session_turns(sid)]:
            assert cleaned_sha not in item
            assert f"paste:{cleaned_sha}" not in item


# ---------------------------------------------------------------------------
# Editable preview — gateway surface (#663 Workstream A)
# ---------------------------------------------------------------------------


def _make_echo_gateway(
    tmp_path: Path,
) -> tuple[TransportGateway, EncryptedSessionStore, FakeTransportCall]:
    """A gateway whose cleaner ECHOES its input — so an edited body flows
    through the re-clean (the real clean_text re-scans pasted markdown without
    re-extraction; an echo is the faithful stand-in)."""
    store = EncryptedSessionStore(db_path=":memory:", cipher=_cipher())
    gw = TransportGateway(session_store=store, dev_mode=True, port=0)
    gw._state = StartupState.OPERATIONAL
    fake_call = FakeTransportCall()
    (tmp_path / "userdata").mkdir(exist_ok=True)

    def _echo_text(raw: str) -> FakeCleanResult:
        return FakeCleanResult(text=raw, title=None, word_count=len(raw.split()))

    def _echo_html(raw: str, *, source_url: str | None = None) -> FakeCleanResult:
        return _echo_text(raw)

    gw._ingest_coordinator = IngestCoordinator(
        transport_call=fake_call,
        cipher_provider=gw._session_cipher,
        pipeline_loader=lambda: (_echo_text, _echo_html),
        staging_dir_provider=lambda: tmp_path / "staging",
        userdata_dir=tmp_path / "userdata",
    )
    return gw, store, fake_call


class _SubmitOkDecisionFailsTransport:
    """Replies ok/pending to INGEST_SUBMIT but a transient error to a decision —
    so the pending slot survives a decision (decided=False, keep the buttons)."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []

    async def __call__(self, message: bytes) -> dict[str, Any]:
        self.sent.append(message)
        env = json.loads(message.decode("utf-8"))
        payload = env["payload"]
        if env["type"] == "INGEST_DECISION":
            return {
                "ok": False, "doc_uuid": payload.get("doc_uuid", ""),
                "state": "error", "chunk_count": 0,
                "error_code": "TRANSPORT_ERROR", "message": "AO unreachable.",
            }
        return {
            "ok": True, "doc_uuid": payload.get("doc_uuid", ""),
            "state": "pending", "chunk_count": 0, "error_code": "", "message": "",
        }


def _make_failing_decision_gateway(
    tmp_path: Path,
) -> tuple[TransportGateway, EncryptedSessionStore, _SubmitOkDecisionFailsTransport]:
    store = EncryptedSessionStore(db_path=":memory:", cipher=_cipher())
    gw = TransportGateway(session_store=store, dev_mode=True, port=0)
    gw._state = StartupState.OPERATIONAL
    fake_call = _SubmitOkDecisionFailsTransport()
    (tmp_path / "userdata").mkdir(exist_ok=True)
    gw._ingest_coordinator = IngestCoordinator(
        transport_call=fake_call,
        cipher_provider=gw._session_cipher,
        pipeline_loader=FakePipeline().loader,
        staging_dir_provider=lambda: tmp_path / "staging",
        userdata_dir=tmp_path / "userdata",
    )
    return gw, store, fake_call


class TestHandleIngestDecision:
    """The WinUI preview buttons' structured approve|reject channel (#663)."""

    def test_unedited_approve_persists_labels_only(self, tmp_path: Path) -> None:
        gw, store, _ = _make_gateway(tmp_path)
        sid = store.create_session("")
        _run(gw.handle_ingest_command(sid, "/ingest pasted article body"))
        pending = gw._ingest_coordinator.pending_for(sid)
        assert pending is not None

        reply, decided = _run(
            gw.handle_ingest_decision(sid, "approve", pending.cleaned_text)
        )
        assert "Approved" in reply
        assert "curated edit" not in reply  # unchanged → no edit note
        assert decided is True
        assert gw._ingest_coordinator.pending_for(sid) is None

        turns = store.get_session_turns(sid)
        assert turns[-2].role == "user" and turns[-2].content == "/approve"
        assert turns[-1].content == reply
        assert turns[-1].pgov_status == INFORMATIONAL_TURN_STATUS

    def test_reject_persists_labels_only(self, tmp_path: Path) -> None:
        gw, store, _ = _make_gateway(tmp_path)
        sid = store.create_session("")
        _run(gw.handle_ingest_command(sid, "/ingest pasted article body"))
        reply, decided = _run(gw.handle_ingest_decision(sid, "reject"))
        assert "Rejected" in reply
        assert decided is True
        assert gw._ingest_coordinator.pending_for(sid) is None
        turns = store.get_session_turns(sid)
        assert turns[-2].content == "/reject"  # NOT a synthetic prompt bubble
        assert turns[-1].content == reply

    def test_edited_body_never_persists_to_sessions_db(self, tmp_path: Path) -> None:
        """The edited body rides the structured RPC param, never prompt text —
        so the curated article text never lands in sessions.db (the #655
        labels-only stub discipline holds on the approve side too)."""
        gw, store, _ = _make_echo_gateway(tmp_path)
        sid = store.create_session("")
        _run(gw.handle_ingest_command(sid, "/ingest ZEBRA-RAW original article body"))
        edited = "ZEBRA-EDIT curated body, advert line removed"

        reply, decided = _run(gw.handle_ingest_decision(sid, "approve", edited))
        assert "Approved" in reply
        assert "curated edit was stored" in reply
        assert decided is True

        dump = [t.content for t in store.get_session_turns(sid)]
        dump.extend(s.title for s in store.list_sessions())
        for item in dump:
            assert "ZEBRA-EDIT" not in item, "edited body persisted to sessions.db!"
            assert "ZEBRA-RAW" not in item, "original body persisted to sessions.db!"

    def test_no_pending_returns_message(self, tmp_path: Path) -> None:
        gw, store, fake_call = _make_gateway(tmp_path)
        sid = store.create_session("")
        reply, _decided = _run(gw.handle_ingest_decision(sid, "approve", "anything"))
        assert "no ingest is pending" in reply.lower()
        assert fake_call.sent == []

    def test_unknown_decision_refused_without_mutation(self, tmp_path: Path) -> None:
        gw, store, fake_call = _make_gateway(tmp_path)
        sid = store.create_session("")
        _run(gw.handle_ingest_command(sid, "/ingest pasted article body"))
        sent_before = len(fake_call.sent)
        reply, decided = _run(gw.handle_ingest_decision(sid, "delete"))
        assert "not recognized" in reply.lower()
        assert decided is False
        # The pending slot is untouched (no decision frame for the bad verb).
        assert gw._ingest_coordinator.pending_for(sid) is not None
        assert len(fake_call.sent) == sent_before

    def test_transient_failure_keeps_slot_decided_false(self, tmp_path: Path) -> None:
        """A transient decision failure leaves the slot pending → decided=False,
        so the WinUI keeps the preview buttons for a retry (the strand-fix)."""
        gw, store, _ = _make_failing_decision_gateway(tmp_path)
        sid = store.create_session("")
        _run(gw.handle_ingest_command(sid, "/ingest pasted article body"))
        pending = gw._ingest_coordinator.pending_for(sid)
        assert pending is not None

        reply, decided = _run(
            gw.handle_ingest_decision(sid, "approve", pending.cleaned_text)
        )
        assert decided is False
        assert "still pending" in reply.lower()
        assert gw._ingest_coordinator.pending_for(sid) is not None


class TestIngestPreviewMetaStash:
    """The one-shot editable-preview signal the dispatcher attaches to the
    preview frame (#663) — set only on a NEW preview, popped once."""

    def test_new_preview_sets_meta_then_pop_on_read(self, tmp_path: Path) -> None:
        gw, store, _ = _make_gateway(tmp_path)
        sid = store.create_session("")
        assert gw.ingest_preview_meta(sid) is None  # nothing pending yet

        _run(gw.handle_ingest_command(sid, "/ingest pasted article body"))
        meta = gw.ingest_preview_meta(sid)
        assert meta is not None
        assert meta["editable_body"] == FakeCleanResult().text
        assert meta["source_type"] == "paste"
        assert meta["doc_uuid"] == gw._ingest_coordinator.pending_for(sid).doc_uuid
        # Pop-on-read: a second read is empty (never leaks onto a later turn).
        assert gw.ingest_preview_meta(sid) is None

    def test_refused_ingest_sets_no_meta(self, tmp_path: Path) -> None:
        gw, store, _ = _make_gateway(tmp_path)
        sid = store.create_session("")
        # URL with no guest parser → refused → no preview created.
        _run(gw.handle_ingest_command(sid, "/ingest https://example.com/x"))
        assert gw.ingest_preview_meta(sid) is None

    def test_approve_clears_meta(self, tmp_path: Path) -> None:
        gw, store, _ = _make_gateway(tmp_path)
        sid = store.create_session("")
        _run(gw.handle_ingest_command(sid, "/ingest pasted article body"))
        _run(gw.handle_ingest_command(sid, "/approve"))
        assert gw.ingest_preview_meta(sid) is None

    def test_second_pending_refusal_sets_no_new_meta(self, tmp_path: Path) -> None:
        gw, store, _ = _make_gateway(tmp_path)
        sid = store.create_session("")
        _run(gw.handle_ingest_command(sid, "/ingest first article body"))
        assert gw.ingest_preview_meta(sid) is not None  # first preview's meta
        # A second /ingest while one is pending is refused → no new meta.
        _run(gw.handle_ingest_command(sid, "/ingest second article body"))
        assert gw.ingest_preview_meta(sid) is None
