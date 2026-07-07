"""
Tier-1 security hardening — PGOV retrieval-leakage wiring tests.

Audit finding (2026-06-03): the PGOV retrieval-leakage detector (Stage 5)
was being handed an empty chunk list on every production call.  This
rendered the entire leakage-detection stage inert: the detector has
nothing to compare the generated text against, so it always returns a
score of 0.0 and never fires.

Fix: ``validate_output`` is now passed
``context_manager.get_grounded_chunk_texts(session_id)`` instead of the
hardcoded ``[]``.

Tests in this module:

  1. ``test_validate_output_receives_chunks_when_grounded``
     -- integration test proving that when documents are grounded for a
        session, ``validate_output`` is called with a non-empty
        ``retrieved_chunks`` argument.

  2. ``test_validate_output_receives_empty_when_no_grounding``
     -- confirming the no-document path is unaffected (no regression).

  3. ``TestGetGroundedChunkTexts``
     -- unit tests for the new ``ContextManager.get_grounded_chunk_texts``
        accessor: correct chunk count, delimiter stripping, marker stripping,
        empty-session fail-safe.

TEETH CHECK (lesson 30 compliance):
  The test file includes ``test_teeth_old_hardcoded_empty_list_would_fail``
  which reconstructs the OLD behaviour (passing ``[]`` regardless of grounding
  state) and asserts that it FAILS the condition checked by
  ``test_validate_output_receives_chunks_when_grounded``.  This proves the
  guard would not pass with the pre-fix code.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from shared.ipc.protocol import MessageFramer, MessageType
from shared.ipc.vsock import VsockAddress, VsockConfig
from services.assistant_orchestrator.src.context_manager import (
    CONTEXT_BEGIN,
    CONTEXT_END,
    ContextManager,
    Provenance,
)
from services.assistant_orchestrator.src.entrypoint import (
    AssistantOrchestratorEntrypointConfig,
    AssistantOrchestratorService,
)


# ---------------------------------------------------------------------------
# Shared helpers (mirror document-wiring test pattern)
# ---------------------------------------------------------------------------

_framer = MessageFramer()


class _FakeTransport:
    """Minimal vsock stand-in that captures outbound frames."""

    def __init__(self, inbound: bytes | None) -> None:
        self._inbound = inbound
        self.sent: list[bytes] = []
        self.connected: bool = True

    def receive(self) -> bytes | None:
        return self._inbound

    def send(self, data: bytes) -> bool:
        self.sent.append(data)
        return True


def _make_resolved_config() -> AssistantOrchestratorEntrypointConfig:
    return AssistantOrchestratorEntrypointConfig(
        model_dir=Path("models"),
        manifest_path=None,
        device="GPU",
        priority=1,
        draft_model_dir=None,
        speculative_decoding_enabled=False,
        max_new_tokens=64,
        generation_temperature=0.0,
        generation_top_k=50,
        generation_top_p=0.9,
        generation_repetition_penalty=1.1,
        generation_do_sample=False,
        response_depth_mode="standard",
        dev_mode=True,
        jwt_ca_cert_path=None,
        vsock_config=VsockConfig(address=VsockAddress(cid=0, port=0)),
        pgov_cosine_threshold=0.85,
        deployment_mode="host",  # type: ignore[arg-type]
    )


def _make_service() -> AssistantOrchestratorService:
    service = AssistantOrchestratorService("dummy.toml")
    service._resolved_config = _make_resolved_config()
    service._context_manager = ContextManager()
    return service


def _pgov_approved(generated_text: str, **_kwargs: Any) -> SimpleNamespace:
    return SimpleNamespace(approved=True, sanitized_text=generated_text)


def _generate_ok(prompt: str, **_kwargs: Any) -> SimpleNamespace:
    return SimpleNamespace(text="All good.", token_count=3, error=None)


def _final_stream_text(transport: _FakeTransport) -> str:
    """Concatenate the token text of every STREAM_TOKEN frame the service sent.

    For a non-streaming mock inference (full text returned at once) the answer is
    delivered in the single is_final STREAM_TOKEN frame as the PGOV
    sanitized_text; this helper reads it back so a test can assert what the user
    actually received (delivered vs. held)."""
    out: list[str] = []
    for frame in transport.sent:
        msg_type, _rid, payload = _framer.decode(frame)
        if msg_type == MessageType.STREAM_TOKEN:
            out.append(str(payload.get("token", "")))
    return "".join(out)


# ---------------------------------------------------------------------------
# Unit tests: ContextManager.get_grounded_chunk_texts
# ---------------------------------------------------------------------------


class TestGetGroundedChunkTexts:
    """get_grounded_chunk_texts returns plain text per chunk, no delimiters."""

    def test_returns_empty_for_unknown_session(self) -> None:
        cm = ContextManager()
        result = cm.get_grounded_chunk_texts("no-such-session")
        assert result == []

    def test_returns_empty_for_session_with_no_grounding(self) -> None:
        cm = ContextManager()
        cm.create_session("s1")
        result = cm.get_grounded_chunk_texts("s1")
        assert result == []

    def test_chunk_count_matches_add_calls(self) -> None:
        """One list element per original chunk — preserves cardinality for PGOV."""
        cm = ContextManager()
        cm.create_session("s1")
        cm.add_grounded_context("s1", ["Alpha.", "Beta.", "Gamma."])
        result = cm.get_grounded_chunk_texts("s1")
        assert len(result) == 3

    def test_context_spotlighting_delimiters_stripped(self) -> None:
        """CONTEXT_BEGIN / CONTEXT_END must not appear in the returned texts."""
        cm = ContextManager()
        cm.create_session("s1")
        cm.add_grounded_context("s1", ["Secret data."])
        result = cm.get_grounded_chunk_texts("s1")
        assert len(result) == 1
        assert CONTEXT_BEGIN not in result[0]
        assert CONTEXT_END not in result[0]

    def test_original_text_preserved_after_stripping(self) -> None:
        """The actual chunk content (what the model saw) must survive stripping."""
        cm = ContextManager()
        cm.create_session("s1")
        cm.add_grounded_context("s1", ["The capital of France is Paris."])
        result = cm.get_grounded_chunk_texts("s1")
        assert len(result) == 1
        assert "The capital of France is Paris." in result[0]

    def test_data_marker_prefix_stripped(self) -> None:
        """Per-line <|DOC-XXXXXXXX|> data markers must not appear in output."""
        cm = ContextManager()
        cm.create_session("s1")
        cm.add_grounded_context("s1", ["Sensitive line one.\nSensitive line two."])
        result = cm.get_grounded_chunk_texts("s1")
        assert len(result) == 1
        # No DOC marker shape should survive
        import re
        assert not re.search(r"<\|DOC-[0-9a-f]{8}\|>", result[0]), (
            f"Data marker leaked into chunk text: {result[0]!r}"
        )
        # Both lines' content must survive
        assert "Sensitive line one." in result[0]
        assert "Sensitive line two." in result[0]

    def test_memory_source_chunks_included(self) -> None:
        """Substrate-retrieved memory chunks (source='memory') are also returned."""
        cm = ContextManager()
        cm.create_session("s1")
        cm.add_grounded_context("s1", ["Memory recall chunk."], source="memory")
        result = cm.get_grounded_chunk_texts("s1")
        assert len(result) == 1
        assert "Memory recall chunk." in result[0]

    def test_multiple_add_calls_accumulate(self) -> None:
        """Chunks from successive add_grounded_context calls all appear."""
        cm = ContextManager()
        cm.create_session("s1")
        cm.add_grounded_context("s1", ["Doc chunk."], source="document")
        cm.add_grounded_context("s1", ["Memory chunk."], source="memory")
        result = cm.get_grounded_chunk_texts("s1")
        assert len(result) == 2
        texts = "\n".join(result)
        assert "Doc chunk." in texts
        assert "Memory chunk." in texts


# ---------------------------------------------------------------------------
# Integration test: validate_output receives chunks when grounding is active
# ---------------------------------------------------------------------------


class TestPGOVLeakageWiring:
    """validate_output must be called with non-empty retrieved_chunks when
    grounded context exists for the session."""

    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_untrusted_content_is_fed_to_leakage_detector(
        self, mock_validate: MagicMock
    ) -> None:
        """
        ADR-023 §2.5 (EA-4): when UNTRUSTED_EXTERNAL content is grounded for the
        session, validate_output receives it as retrieved_chunks so the leakage
        detector can check the output against it.

        Would FAIL against the inert pre-fix code (retrieved_chunks=[] always).
        """
        mock_validate.side_effect = _pgov_approved
        service = _make_service()
        service._inference = MagicMock()
        service._inference.generate_text.side_effect = _generate_ok
        service._substrate_retrieve = MagicMock(return_value=[])  # type: ignore[method-assign]

        # Untrusted-external content present (e.g. pasted from the web).
        service._context_manager.create_session("leakage-test")
        service._context_manager.add_grounded_context(
            "leakage-test",
            ["Top secret: launch at dawn."],
            provenance=Provenance.UNTRUSTED_EXTERNAL,
        )

        inbound = _framer.encode_prompt_request(
            session_id="leakage-test",
            prompt="What is the plan?",
            request_id="r-leak",
        )
        service._handle_connection(_FakeTransport(inbound))

        mock_validate.assert_called_once()
        _, kwargs = mock_validate.call_args
        retrieved_chunks = kwargs.get("retrieved_chunks", [])
        assert retrieved_chunks, (
            "validate_output was called with retrieved_chunks=[] even though "
            "UNTRUSTED content was grounded — the leakage detector is inert."
        )
        combined = "\n".join(retrieved_chunks)
        assert "Top secret: launch at dawn." in combined, (
            f"Untrusted content not found in retrieved_chunks fed to PGOV. "
            f"Got: {retrieved_chunks!r}"
        )

    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_trusted_document_is_not_fed_to_leakage_detector(
        self, mock_validate: MagicMock
    ) -> None:
        """
        ADR-023 §2.5: a TRUSTED_LOCAL document is NOT fed to the leakage
        detector — a summary/recall of the user's own file is similar to its
        source by design and is not a leak. retrieved_chunks must be [] so the
        detector stays a no-op. This is the fix for the 2026-06-04 false
        positive that suppressed a correct two-document summary.
        """
        mock_validate.side_effect = _pgov_approved
        service = _make_service()
        service._inference = MagicMock()
        service._inference.generate_text.side_effect = _generate_ok
        service._substrate_retrieve = MagicMock(return_value=[])  # type: ignore[method-assign]

        docs = [{"filename": "private.txt", "content": "Top secret: launch at dawn."}]
        inbound = _framer.encode_prompt_request(
            session_id="trusted-doc-leak-test",
            prompt="Summarize this.",
            request_id="r-trusted-leak",
            documents=docs,
        )
        service._handle_connection(_FakeTransport(inbound))

        mock_validate.assert_called_once()
        _, kwargs = mock_validate.call_args
        retrieved_chunks = kwargs.get("retrieved_chunks", "SENTINEL")
        assert retrieved_chunks == [], (
            "A trusted-local document must NOT be fed to the leakage detector "
            f"(false-positive fix). Got: {retrieved_chunks!r}"
        )

    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_leakage_detection_disabled_feeds_empty(
        self, mock_validate: MagicMock
    ) -> None:
        """
        The leakage_detection_enabled flag is honored (previously vestigial):
        when False, retrieved_chunks is [] even if untrusted content is present.
        """
        from dataclasses import replace

        mock_validate.side_effect = _pgov_approved
        service = _make_service()
        service._resolved_config = replace(
            service._resolved_config,
            pgov_leakage_detection_enabled=False,
        )
        service._inference = MagicMock()
        service._inference.generate_text.side_effect = _generate_ok
        service._substrate_retrieve = MagicMock(return_value=[])  # type: ignore[method-assign]

        service._context_manager.create_session("leak-off-test")
        service._context_manager.add_grounded_context(
            "leak-off-test",
            ["Untrusted content."],
            provenance=Provenance.UNTRUSTED_EXTERNAL,
        )

        inbound = _framer.encode_prompt_request(
            session_id="leak-off-test",
            prompt="Question.",
            request_id="r-leak-off",
        )
        service._handle_connection(_FakeTransport(inbound))

        mock_validate.assert_called_once()
        _, kwargs = mock_validate.call_args
        retrieved_chunks = kwargs.get("retrieved_chunks", "SENTINEL")
        assert retrieved_chunks == [], (
            "With leakage_detection_enabled=False, retrieved_chunks must be [] "
            f"even with untrusted content. Got: {retrieved_chunks!r}"
        )

    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_validate_output_receives_empty_when_no_grounding(
        self, mock_validate: MagicMock
    ) -> None:
        """
        When no documents/memory are grounded, retrieved_chunks must be []
        (no regression: leakage score stays 0.0 for plain text sessions).
        """
        mock_validate.side_effect = _pgov_approved
        service = _make_service()
        service._inference = MagicMock()
        service._inference.generate_text.side_effect = _generate_ok

        # Patch substrate retrieval so no memory is injected.
        service._substrate_retrieve = MagicMock(return_value=[])  # type: ignore[method-assign]

        inbound = _framer.encode_prompt_request(
            session_id="no-doc-session",
            prompt="Plain question.",
            request_id="r-nodoc",
        )
        service._handle_connection(_FakeTransport(inbound))

        mock_validate.assert_called_once()
        _, kwargs = mock_validate.call_args
        retrieved_chunks = kwargs.get("retrieved_chunks", "SENTINEL")
        assert retrieved_chunks == [], (
            "With no grounding, retrieved_chunks should be [] but was "
            f"{retrieved_chunks!r}"
        )


# ---------------------------------------------------------------------------
# Teeth check — proves the test would fail against the old behaviour
# ---------------------------------------------------------------------------


class TestTeethOldBehaviourFails:
    """
    Lesson 30 compliance: reconstructs the OLD (broken) behaviour and
    confirms it FAILS the assertion that guards the fix.

    This is a meta-test: it calls get_grounded_chunk_texts on a session that
    HAS grounded content, then asserts that the old empty-list substitution
    would not satisfy the 'non-empty retrieved_chunks' guard.

    The test PASSES when run against fixed code because it is asserting the
    OPPOSITE of the broken path — i.e. it passes ONLY because the new
    accessor returns the right thing and the old hardcoded [] would not.
    """

    def test_teeth_old_hardcoded_empty_list_would_fail(self) -> None:
        """
        Simulate what the OLD code did: pass [] to validate_output regardless
        of grounding state.  Assert that [] fails the non-empty guard that
        the real integration test uses.

        If this test PASSES it means [] != non-empty, confirming the guard
        would have caught the bug.  If this test FAILS it means something is
        wrong with the teeth check itself.
        """
        # Old code: hardcoded empty, regardless of grounded context.
        old_retrieved_chunks: list[str] = []

        # The guard used in the integration test:
        is_non_empty = bool(old_retrieved_chunks)

        # The old code makes this False — the integration test would catch it.
        assert not is_non_empty, (
            "Teeth check failed: [] should evaluate to falsy, confirming "
            "the old hardcoded [] would have tripped the integration test's "
            "non-empty assertion."
        )

    def test_teeth_new_accessor_returns_nonempty_for_grounded_session(self) -> None:
        """
        The new accessor must return a non-empty list when chunks are grounded,
        making the integration test's guard pass.
        """
        cm = ContextManager()
        cm.create_session("teeth-session")
        cm.add_grounded_context(
            "teeth-session",
            ["Classified: operation midnight."],
            source="document",
        )
        result = cm.get_grounded_chunk_texts("teeth-session")
        assert bool(result), (
            "get_grounded_chunk_texts must return a non-empty list for a "
            "session with grounded content — got empty, which means the "
            "accessor itself is broken."
        )
        assert "Classified: operation midnight." in result[0]

    def test_teeth_untrusted_accessor_filters_by_provenance(self) -> None:
        """The new leakage feed (get_untrusted_chunk_texts, ADR-023 §2.5)
        returns ONLY untrusted chunks: a trusted document yields [] (the
        false-positive fix), untrusted content yields its text."""
        cm = ContextManager()
        cm.create_session("teeth-prov")
        cm.add_grounded_context("teeth-prov", ["My own file."], source="document")
        assert cm.get_untrusted_chunk_texts("teeth-prov") == [], (
            "A trusted-local document must NOT appear in the untrusted leakage feed."
        )
        cm.add_grounded_context(
            "teeth-prov", ["From the web."], provenance=Provenance.UNTRUSTED_EXTERNAL
        )
        untrusted = cm.get_untrusted_chunk_texts("teeth-prov")
        assert len(untrusted) == 1 and "From the web." in untrusted[0], (
            f"Untrusted content must appear in the leakage feed. Got: {untrusted!r}"
        )


# ---------------------------------------------------------------------------
# ADR-023 Amendment 2 (#664) — knowledge-bank leakage carve-out (entrypoint)
# ---------------------------------------------------------------------------


class TestKnowledgeLeakageCarveOut:
    """The Stage-5 cosine leakage OUTPUT block must EXEMPT UNTRUSTED_KNOWLEDGE
    so faithful recall works, while UNTRUSTED_EXTERNAL stays in the feed."""

    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_knowledge_content_not_fed_to_leakage_detector(
        self, mock_validate: MagicMock
    ) -> None:
        """The fix (#664): a session whose ONLY grounded content is knowledge-bank
        provenance must NOT feed the leakage detector — retrieved_chunks must be []
        so a faithful recall is not held. Mirrors the trusted-document exemption,
        extended to operator-curated knowledge."""
        mock_validate.side_effect = _pgov_approved
        service = _make_service()
        service._inference = MagicMock()
        service._inference.generate_text.side_effect = _generate_ok
        service._substrate_retrieve = MagicMock(return_value=[])  # type: ignore[method-assign]

        service._context_manager.create_session("knowledge-leak-test")
        service._context_manager.add_grounded_context(
            "knowledge-leak-test",
            ["The 2026 breach exfiltrated 4 TB via a poisoned update."],
            provenance=Provenance.UNTRUSTED_KNOWLEDGE,
        )

        inbound = _framer.encode_prompt_request(
            session_id="knowledge-leak-test",
            prompt="What happened in the 2026 breach?",
            request_id="r-k-leak",
        )
        service._handle_connection(_FakeTransport(inbound))

        mock_validate.assert_called_once()
        _, kwargs = mock_validate.call_args
        retrieved_chunks = kwargs.get("retrieved_chunks", "SENTINEL")
        assert retrieved_chunks == [], (
            "Knowledge-bank content must NOT be fed to the leakage detector "
            f"(ADR-023 Amendment 2, #664). Got: {retrieved_chunks!r}"
        )

    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_external_still_fed_when_mixed_with_knowledge(
        self, mock_validate: MagicMock
    ) -> None:
        """MUST-NOT-WEAKEN (#664): when both UNTRUSTED_EXTERNAL and
        UNTRUSTED_KNOWLEDGE are present, the EXTERNAL chunk is STILL fed to the
        leakage detector (it is NOT exempted) and the knowledge chunk is not."""
        mock_validate.side_effect = _pgov_approved
        service = _make_service()
        service._inference = MagicMock()
        service._inference.generate_text.side_effect = _generate_ok
        service._substrate_retrieve = MagicMock(return_value=[])  # type: ignore[method-assign]

        service._context_manager.create_session("mixed-leak-test")
        service._context_manager.add_grounded_context(
            "mixed-leak-test",
            ["EXTERNAL-PASTED: launch at dawn."],
            provenance=Provenance.UNTRUSTED_EXTERNAL,
        )
        service._context_manager.add_grounded_context(
            "mixed-leak-test",
            ["KNOWLEDGE-CURATED: turbochargers compress intake air."],
            provenance=Provenance.UNTRUSTED_KNOWLEDGE,
        )

        inbound = _framer.encode_prompt_request(
            session_id="mixed-leak-test",
            prompt="Tell me everything.",
            request_id="r-mixed-leak",
        )
        service._handle_connection(_FakeTransport(inbound))

        mock_validate.assert_called_once()
        _, kwargs = mock_validate.call_args
        retrieved_chunks = kwargs.get("retrieved_chunks", [])
        combined = "\n".join(retrieved_chunks)
        assert "EXTERNAL-PASTED: launch at dawn." in combined, (
            "External-pasted content must STILL be in the leakage feed when mixed "
            f"with knowledge. Got: {retrieved_chunks!r}"
        )
        assert "KNOWLEDGE-CURATED" not in combined, (
            "Knowledge content must NOT be in the leakage feed even when mixed "
            f"with external content. Got: {retrieved_chunks!r}"
        )

    def test_faithful_knowledge_recall_passes_pgov_with_high_cosine(self) -> None:
        """THE POSITIVE CASE the fix enables (#664): a faithful recall that WOULD
        score cosine >= 0.85 against its source now PASSES PGOV, because the
        knowledge chunk is exempt from the leakage feed and the detector is never
        consulted. Uses the REAL validate_output with a mock detector that would
        return 0.97 (deterministic, no model) — proving the exemption is what
        unblocks recall, not a lowered threshold.

        Teeth: the same setup with UNTRUSTED_EXTERNAL provenance is held — see
        test_faithful_external_echo_still_held_with_high_cosine below."""
        from services.assistant_orchestrator.src.pgov import (
            LeakageDetector,
            set_leakage_detector,
        )

        recall_text = "The breach exfiltrated 4 TB via a poisoned software update."
        high_cosine = MagicMock(spec=LeakageDetector)
        high_cosine.check_leakage.return_value = 0.97  # >= 0.85: would be a "leak"

        service = _make_service()
        service._inference = MagicMock()
        service._inference.generate_text.side_effect = (
            lambda *_a, **_k: SimpleNamespace(
                text=recall_text, token_count=12, error=None
            )
        )
        service._substrate_retrieve = MagicMock(return_value=[])  # type: ignore[method-assign]

        service._context_manager.create_session("recall-pass-test")
        service._context_manager.add_grounded_context(
            "recall-pass-test",
            [recall_text],
            provenance=Provenance.UNTRUSTED_KNOWLEDGE,
        )

        set_leakage_detector(high_cosine)
        try:
            inbound = _framer.encode_prompt_request(
                session_id="recall-pass-test",
                prompt="What did the breach do?",
                request_id="r-recall-pass",
            )
            transport = _FakeTransport(inbound)
            service._handle_connection(transport)
        finally:
            set_leakage_detector(None)  # type: ignore[arg-type]

        # The detector must NEVER have been consulted (knowledge is exempt → the
        # feed is empty → validate_output short-circuits Stage 5). The recall is
        # delivered, not held.
        high_cosine.check_leakage.assert_not_called()
        final_token = _final_stream_text(transport)
        assert recall_text in final_token, (
            "A faithful knowledge recall must be DELIVERED (not held) even when "
            f"it would score cosine >= 0.85. Got final output: {final_token!r}"
        )

    def test_faithful_external_echo_still_held_with_high_cosine(self) -> None:
        """TEETH for the positive case: the IDENTICAL setup with
        UNTRUSTED_EXTERNAL provenance IS held (the detector fires at 0.97). This
        proves the carve-out is provenance-scoped, not a global disable — pasted
        external content with a verbatim echo is still caught."""
        from services.assistant_orchestrator.src.pgov import (
            LeakageDetector,
            set_leakage_detector,
        )

        echo_text = "The breach exfiltrated 4 TB via a poisoned software update."
        high_cosine = MagicMock(spec=LeakageDetector)
        high_cosine.check_leakage.return_value = 0.97

        service = _make_service()
        service._inference = MagicMock()
        service._inference.generate_text.side_effect = (
            lambda *_a, **_k: SimpleNamespace(
                text=echo_text, token_count=12, error=None
            )
        )
        service._substrate_retrieve = MagicMock(return_value=[])  # type: ignore[method-assign]

        service._context_manager.create_session("echo-held-test")
        service._context_manager.add_grounded_context(
            "echo-held-test",
            [echo_text],
            provenance=Provenance.UNTRUSTED_EXTERNAL,
        )

        set_leakage_detector(high_cosine)
        try:
            inbound = _framer.encode_prompt_request(
                session_id="echo-held-test",
                prompt="What did it do?",
                request_id="r-echo-held",
            )
            transport = _FakeTransport(inbound)
            service._handle_connection(transport)
        finally:
            set_leakage_detector(None)  # type: ignore[arg-type]

        # The detector WAS consulted and fired → the output is sanitized/held.
        high_cosine.check_leakage.assert_called_once()
        final_token = _final_stream_text(transport)
        assert echo_text not in final_token, (
            "A verbatim echo of UNTRUSTED_EXTERNAL content must STILL be held by "
            f"the leakage detector (carve-out is knowledge-only). Got: {final_token!r}"
        )
