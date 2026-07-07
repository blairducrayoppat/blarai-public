"""
Tests — encode_prompt_request documents extension (data pillar v1)

Verifies the backward-compatible documents field added to encode_prompt_request.
"""

from __future__ import annotations

import json

import pytest

from shared.ipc.protocol import MessageFramer, MessageType


_framer = MessageFramer()


class TestEncodePromptRequestDocuments:
    """encode_prompt_request round-trips with and without documents."""

    def test_without_documents_field_omitted(self) -> None:
        """Omitting documents encodes as an empty list — backward compatible."""
        raw = _framer.encode_prompt_request(
            session_id="s1", prompt="hello", request_id="r1"
        )
        envelope = json.loads(raw.decode("utf-8"))
        assert envelope["payload"]["documents"] == []

    def test_with_documents_round_trips(self) -> None:
        """documents list encodes and decodes correctly."""
        docs = [{"filename": "notes.txt", "content": "Some notes here."}]
        raw = _framer.encode_prompt_request(
            session_id="s1",
            prompt="what does it say?",
            request_id="r1",
            documents=docs,
        )
        _msg_type, _rid, payload = _framer.decode(raw)
        assert payload["documents"] == docs

    def test_documents_none_becomes_empty_list(self) -> None:
        """documents=None encodes as an empty list."""
        raw = _framer.encode_prompt_request(
            session_id="s1", prompt="hi", request_id="r1", documents=None
        )
        _msg_type, _rid, payload = _framer.decode(raw)
        assert payload["documents"] == []

    def test_old_style_request_has_empty_documents(self) -> None:
        """A payload without documents key yields [] via payload.get('documents', [])."""
        # Simulate an old-style message that has no 'documents' field.
        import json
        old_envelope = json.dumps({
            "type": MessageType.PROMPT_REQUEST.value,
            "request_id": "r_old",
            "payload": {"session_id": "s_old", "prompt": "legacy", "history": []},
        }).encode("utf-8")
        _msg_type, _rid, payload = _framer.decode(old_envelope)
        assert payload.get("documents", []) == []

    def test_history_still_works_with_documents(self) -> None:
        """Existing history parameter is unaffected by the documents addition."""
        history = [{"role": "user", "content": "prev"}, {"role": "assistant", "content": "ok"}]
        docs = [{"filename": "f.md", "content": "# F"}]
        raw = _framer.encode_prompt_request(
            session_id="s1",
            prompt="continue",
            request_id="r1",
            history=history,
            documents=docs,
        )
        _msg_type, _rid, payload = _framer.decode(raw)
        assert payload["history"] == history
        assert payload["documents"] == docs

    def test_multiple_documents_round_trip(self) -> None:
        """Multiple documents in the list all survive the encode/decode cycle."""
        docs = [
            {"filename": "a.txt", "content": "alpha"},
            {"filename": "b.md", "content": "beta"},
        ]
        raw = _framer.encode_prompt_request(
            session_id="s2", prompt="summarize", documents=docs
        )
        _msg_type, _rid, payload = _framer.decode(raw)
        assert len(payload["documents"]) == 2
        assert payload["documents"][0]["filename"] == "a.txt"
        assert payload["documents"][1]["content"] == "beta"


class TestEncodePromptRequestClearDocuments:
    """encode_prompt_request carries the /unload clear_documents flag."""

    def test_clear_documents_defaults_false(self) -> None:
        """Omitting clear_documents encodes as False — backward compatible."""
        raw = _framer.encode_prompt_request(
            session_id="s1", prompt="hello", request_id="r1"
        )
        _msg_type, _rid, payload = _framer.decode(raw)
        assert payload["clear_documents"] is False

    def test_clear_documents_true_round_trips(self) -> None:
        """clear_documents=True survives the encode/decode cycle."""
        raw = _framer.encode_prompt_request(
            session_id="s1", prompt="hi", request_id="r1", clear_documents=True
        )
        _msg_type, _rid, payload = _framer.decode(raw)
        assert payload["clear_documents"] is True

    def test_old_style_request_clear_documents_absent(self) -> None:
        """A payload without clear_documents yields False via .get default."""
        old_envelope = json.dumps({
            "type": MessageType.PROMPT_REQUEST.value,
            "request_id": "r_old",
            "payload": {"session_id": "s_old", "prompt": "legacy", "history": []},
        }).encode("utf-8")
        _msg_type, _rid, payload = _framer.decode(old_envelope)
        assert payload.get("clear_documents", False) is False
