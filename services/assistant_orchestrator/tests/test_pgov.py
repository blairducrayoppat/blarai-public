"""
PGOV Tests — Assistant Orchestrator
=======================================
Tests for Post-Generation Output Validator: 6-stage pipeline —
PII detection, token budget, delimiter echo, tool-call allowlist,
leakage scoring, and final approval.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.assistant_orchestrator.src.context_manager import (
    CONTEXT_BEGIN,
    CONTEXT_END,
    SYSTEM_BEGIN,
    SYSTEM_END,
)
from services.assistant_orchestrator.src.pgov import (
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    FALLBACK_MESSAGE,
    TOOL_CALL_ALLOWLIST,
    LeakageDetector,
    PGOVResult,
    _luhn_filter,
    _luhn_valid,
    check_delimiter_echo,
    check_leakage,
    check_pii,
    check_tool_calls,
    find_pii_spans,
    set_leakage_detector,
    validate_output,
)


# ───────────────────────────── PGOVResult ─────────────────────────────


class TestPGOVResult:
    """PGOVResult dataclass fields and immutability."""

    def test_approved_fields(self) -> None:
        r = PGOVResult(
            approved=True,
            original_text="Hello",
            sanitized_text="Hello",
            leakage_score=0.1,
            pii_detected=False,
            token_count_valid=True,
        )
        assert r.approved is True
        assert r.delimiter_echo is False
        assert r.tool_call_violation is False
        assert r.violations == []

    def test_frozen_immutable(self) -> None:
        r = PGOVResult(
            approved=True,
            original_text="x",
            sanitized_text="x",
            leakage_score=0.0,
            pii_detected=False,
            token_count_valid=True,
        )
        with pytest.raises(AttributeError):
            r.approved = False  # type: ignore[misc]

    def test_violation_fields_captured(self) -> None:
        r = PGOVResult(
            approved=False,
            original_text="bad",
            sanitized_text=FALLBACK_MESSAGE,
            leakage_score=0.9,
            pii_detected=True,
            token_count_valid=False,
            delimiter_echo=True,
            tool_call_violation=True,
            violations=["v1", "v2"],
        )
        assert r.delimiter_echo is True
        assert r.tool_call_violation is True
        assert len(r.violations) == 2


# ─────────────────────────── PII Detection ────────────────────────────


class TestPIIDetection:
    """Expanded PII / secret pattern matching."""

    def test_ssn_detected(self) -> None:
        matches = check_pii("My SSN is 123-45-6789.")
        assert "SSN" in matches

    def test_email_detected(self) -> None:
        matches = check_pii("Contact user@example.com for details.")
        assert "EMAIL" in matches

    def test_phone_detected(self) -> None:
        matches = check_pii("Call me at (555) 123-4567 please.")
        assert "PHONE_US" in matches

    def test_ipv4_detected(self) -> None:
        matches = check_pii("The server is at 192.168.1.100.")
        assert "IPV4" in matches

    def test_aws_key_detected(self) -> None:
        matches = check_pii("Key: AKIAIOSFODNN7EXAMPLE")
        assert "AWS_KEY" in matches

    def test_bearer_token_detected(self) -> None:
        matches = check_pii("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.token")
        assert "BEARER_TOKEN" in matches

    def test_clean_text_no_pii(self) -> None:
        matches = check_pii("The weather in Seattle is rainy.")
        assert len(matches) == 0

    def test_credit_card_visa_detected(self) -> None:
        matches = check_pii("Charge 4111 1111 1111 1111 to the account.")
        assert "CREDIT_CARD" in matches

    def test_credit_card_amex_detected(self) -> None:
        matches = check_pii("AmEx: 3782-822463-10005 expires soon.")
        assert "CREDIT_CARD" in matches

    def test_hex_secret_detected(self) -> None:
        matches = check_pii(
            "api_key=deadbeefcafebabe0123456789abcdef0123456789abcdef"
        )
        assert "HEX_SECRET" in matches

    def test_short_hex_not_flagged_as_secret(self) -> None:
        """Regression: <32-char hex must NOT trigger HEX_SECRET (too short)."""
        matches = check_pii("Color code #deadbeef is blue.")
        assert "HEX_SECRET" not in matches

    def test_bare_nine_digits_not_flagged_as_passport(self) -> None:
        """Regression: bare 9-digit numbers must NOT trigger PASSPORT_US."""
        matches = check_pii("There are 123456789 stars in the sky.")
        assert "PASSPORT_US" not in matches

    def test_passport_with_context_detected(self) -> None:
        """PASSPORT_US triggers only when preceded by passport-related context."""
        matches = check_pii("My passport number is 123456789.")
        assert "PASSPORT_US" in matches

    def test_multiple_patterns_detected(self) -> None:
        text = "Send to user@example.com with SSN 123-45-6789 from 10.0.0.1"
        matches = check_pii(text)
        assert "EMAIL" in matches
        assert "SSN" in matches
        assert "IPV4" in matches


# ──────────────────── Delimiter Echo Detection ────────────────────────


class TestDelimiterEcho:
    """Context Spotlighting delimiter echo detection."""

    def test_no_delimiters_clean(self) -> None:
        assert check_delimiter_echo("Normal response text.") == []

    def test_context_begin_detected(self) -> None:
        text = f"Some text {CONTEXT_BEGIN} leaked delimiter"
        found = check_delimiter_echo(text)
        assert CONTEXT_BEGIN in found

    def test_context_end_detected(self) -> None:
        text = f"Text {CONTEXT_END} here"
        found = check_delimiter_echo(text)
        assert CONTEXT_END in found

    def test_system_delimiters_detected(self) -> None:
        text = f"{SYSTEM_BEGIN}system leak{SYSTEM_END}"
        found = check_delimiter_echo(text)
        assert SYSTEM_BEGIN in found
        assert SYSTEM_END in found

    def test_all_delimiters_detected(self) -> None:
        text = (
            f"{CONTEXT_BEGIN}{CONTEXT_END}"
            f"{SYSTEM_BEGIN}{SYSTEM_END}"
        )
        found = check_delimiter_echo(text)
        assert len(found) == 4


# ──────────────────── Tool-Call Allowlist ──────────────────────────────


class TestToolCallAllowlist:
    """Deterministic tool-call reference validation."""

    def test_no_tool_calls_clean(self) -> None:
        assert check_tool_calls("Normal response.") == []

    def test_authorized_tool_xml_clean(self) -> None:
        # Only actually-built tools are authorized.
        text = "<tool_call>get_current_time</tool_call>"
        assert check_tool_calls(text) == []

    def test_formerly_allowlisted_unbuilt_tool_now_flagged(self) -> None:
        # "search" was in the old 14-name allowlist but is NOT built.
        # After the Domain 5 prune (2026-06-03) it is now a violation.
        text = "<tool_call>search</tool_call>"
        result = check_tool_calls(text)
        assert "search" in result

    def test_unauthorized_tool_xml_flagged(self) -> None:
        text = "<tool_call>evil_tool</tool_call>"
        result = check_tool_calls(text)
        assert "evil_tool" in result

    def test_authorized_tool_bracket_clean(self) -> None:
        # Only actually-built tools are authorized.
        text = "[TOOL: calculate]"
        assert check_tool_calls(text) == []

    def test_formerly_allowlisted_unbuilt_tool_bracket_now_flagged(self) -> None:
        # "code_agent" was in the old allowlist but is NOT built.
        text = "[TOOL: code_agent]"
        result = check_tool_calls(text)
        assert "code_agent" in result

    def test_unauthorized_tool_bracket_flagged(self) -> None:
        text = "[TOOL: rm_rf]"
        result = check_tool_calls(text)
        assert "rm_rf" in result

    def test_authorized_tool_json_clean(self) -> None:
        # Only actually-built tools are authorized.
        text = '{"tool": "get_current_date"}'
        assert check_tool_calls(text) == []

    def test_formerly_allowlisted_unbuilt_tool_json_now_flagged(self) -> None:
        # "cleaner" was in the old allowlist but is NOT built.
        text = '{"tool": "cleaner"}'
        result = check_tool_calls(text)
        assert "cleaner" in result

    def test_unauthorized_tool_json_flagged(self) -> None:
        text = '{"tool": "delete_all"}'
        result = check_tool_calls(text)
        assert "delete_all" in result

    def test_multiple_unauthorized_flagged(self) -> None:
        text = '<tool_call>hack</tool_call> [TOOL: exploit]'
        result = check_tool_calls(text)
        assert "hack" in result
        assert "exploit" in result

    def test_custom_allowlist(self) -> None:
        custom = frozenset({"my_tool"})
        assert check_tool_calls("<tool_call>my_tool</tool_call>", custom) == []
        assert len(check_tool_calls("<tool_call>other</tool_call>", custom)) > 0

    def test_default_allowlist_is_exactly_four_built_tools(self) -> None:
        """Exact-set assertion: the allowlist equals the 4 implemented tools.

        Lesson 30 (TEETH): if an unbuilt tool name is re-introduced into
        TOOL_CALL_ALLOWLIST without a matching entry in tools._REGISTRY,
        this test fails — preventing the phantom approval surface from
        re-opening. The assertion is intentionally exact, not 'contains',
        so both additions (unbuilt names) and removals (built names) are caught.
        """
        from services.assistant_orchestrator.src.tools import _REGISTRY
        assert TOOL_CALL_ALLOWLIST == frozenset(_REGISTRY.keys()), (
            "TOOL_CALL_ALLOWLIST must equal tools._REGISTRY keys exactly. "
            f"Allowlist: {sorted(TOOL_CALL_ALLOWLIST)!r}, "
            f"Registry: {sorted(_REGISTRY.keys())!r}"
        )

    def test_unbuilt_tools_not_in_allowlist(self) -> None:
        """Regression: formerly pre-approved unbuilt tools must NOT be re-admitted."""
        unbuilt = {
            "search", "code_agent", "cleaner", "substrate_query",
            "calendar_read", "calendar_write", "note_create", "note_search",
            "health_log", "smart_home_control",
        }
        reintroduced = unbuilt & TOOL_CALL_ALLOWLIST
        assert not reintroduced, (
            f"Unbuilt tool name(s) reintroduced into allowlist: {reintroduced!r}. "
            "A tool must be implemented in tools._REGISTRY before its name "
            "may appear on TOOL_CALL_ALLOWLIST."
        )


# ──────────────────── Leakage Detector ────────────────────────────────


class TestLeakageDetectorUnloaded:
    """LeakageDetector Fail-Closed behavior when model not loaded."""

    def test_not_loaded_initially(self) -> None:
        d = LeakageDetector(model_path="nonexistent/model.onnx")
        assert not d.loaded

    def test_fail_closed_returns_one(self) -> None:
        d = LeakageDetector(model_path="nonexistent/model.onnx")
        score = d.check_leakage("text", ["chunk"], 0.85)
        assert score == 1.0

    def test_empty_text_returns_zero(self) -> None:
        d = LeakageDetector()
        assert d.check_leakage("", ["chunk"], 0.85) == 0.0

    def test_empty_chunks_returns_zero(self) -> None:
        d = LeakageDetector()
        assert d.check_leakage("text", [], 0.85) == 0.0

    def test_load_model_nonexistent_returns_false(self) -> None:
        d = LeakageDetector(model_path="nonexistent/model.onnx")
        assert d.load_model() is False
        assert not d.loaded


class TestLeakageDetectorWithMock:
    """LeakageDetector with mocked ONNX Runtime."""

    def _make_mock_detector(self) -> LeakageDetector:
        """Create a LeakageDetector with mocked internals."""
        import numpy as np

        d = LeakageDetector()

        # Mock embedding: returns L2-normalized vectors based on text hash
        def mock_embed(texts: list[str]) -> Any:
            vecs = []
            for t in texts:
                rng = __import__("numpy").random.RandomState(hash(t) % (2**31))
                v = rng.randn(384).astype(np.float32)
                v /= np.linalg.norm(v)
                vecs.append(v)
            return np.stack(vecs)

        d._embed = mock_embed  # type: ignore[assignment]
        d._loaded = True
        return d

    def test_identical_text_high_similarity(self) -> None:
        d = self._make_mock_detector()
        # Same text as chunk → identical embedding → similarity = 1.0
        score = d.check_leakage("exact text", ["exact text"], 0.85)
        assert score >= 0.99

    def test_different_text_lower_similarity(self) -> None:
        d = self._make_mock_detector()
        score = d.check_leakage(
            "completely different content",
            ["unrelated chunk about weather"],
            0.85,
        )
        # Random-seeded vectors for different text should not be ~1.0
        assert score < 0.99

    def test_max_across_multiple_chunks(self) -> None:
        d = self._make_mock_detector()
        score = d.check_leakage(
            "target text",
            ["chunk A", "target text", "chunk C"],
            0.85,
        )
        # The matching chunk should produce sim ~1.0
        assert score >= 0.99

    def test_unload_clears_state(self) -> None:
        d = self._make_mock_detector()
        assert d.loaded
        d.unload()
        assert not d.loaded

    def test_exception_returns_fail_closed(self) -> None:
        d = self._make_mock_detector()

        def fail_embed(_texts: list[str]) -> None:
            raise RuntimeError("embedding crash")

        d._embed = fail_embed  # type: ignore[assignment]
        score = d.check_leakage("text", ["chunk"], 0.85)
        assert score == 1.0


# ─────────────── Module-Level check_leakage ───────────────────────────


class TestModuleLevelLeakage:
    """Module-level check_leakage function with singleton detector."""

    def test_injected_detector_used(self) -> None:
        mock_detector = MagicMock(spec=LeakageDetector)
        mock_detector.check_leakage.return_value = 0.42
        set_leakage_detector(mock_detector)
        try:
            score = check_leakage("text", ["chunk"], 0.85)
            assert score == 0.42
            mock_detector.check_leakage.assert_called_once()
        finally:
            set_leakage_detector(None)  # type: ignore[arg-type]

    def test_unloaded_singleton_returns_one(self) -> None:
        # Reset to a fresh unloaded detector
        fresh = LeakageDetector(model_path="nonexistent/model.onnx")
        set_leakage_detector(fresh)
        try:
            score = check_leakage("text", ["chunk"], 0.85)
            assert score == 1.0
        finally:
            set_leakage_detector(None)  # type: ignore[arg-type]


# ─────────────────────── Token Budget ─────────────────────────────────


class TestTokenBudget:
    """Circuit breaker token cap enforcement via PGOV."""

    def test_within_budget_approved(self) -> None:
        result = validate_output(
            generated_text="Hello world.",
            token_count=100,
            max_tokens=4096,
        )
        assert result.approved
        assert result.token_count_valid

    def test_exceeds_budget_rejected(self) -> None:
        result = validate_output(
            generated_text="Too many tokens.",
            token_count=5000,
            max_tokens=4096,
        )
        assert not result.approved
        assert not result.token_count_valid
        assert result.sanitized_text == FALLBACK_MESSAGE


# ──────────────────── Full PGOV Pipeline ──────────────────────────────


class TestPGOVPipeline:
    """Full 6-stage PGOV pipeline integration."""

    def test_clean_output_approved(self) -> None:
        result = validate_output(
            generated_text="Here is a summary of the meeting notes.",
            token_count=200,
            max_tokens=4096,
        )
        assert result.approved
        assert result.sanitized_text == "Here is a summary of the meeting notes."
        assert result.delimiter_echo is False
        assert result.tool_call_violation is False

    def test_pii_triggers_rejection(self) -> None:
        result = validate_output(
            generated_text="Send to user@example.com with SSN 123-45-6789.",
            token_count=50,
            max_tokens=4096,
        )
        assert not result.approved
        assert result.pii_detected

    def test_pii_off_mode_allows_pii(self) -> None:
        """pii_mode='off' skips PII detection — a response containing a
        phone number is delivered unchanged. Correct posture for a local
        single-user assistant whose job is to manage the user's own data."""
        result = validate_output(
            generated_text="Call the eligibility office at 555-123-4567.",
            token_count=50,
            max_tokens=4096,
            pii_mode="off",
        )
        assert result.approved
        assert result.pii_detected is False
        assert result.sanitized_text == "Call the eligibility office at 555-123-4567."

    def test_pii_block_mode_explicit(self) -> None:
        """pii_mode='block' suppresses a response containing PII."""
        result = validate_output(
            generated_text="Call the eligibility office at 555-123-4567.",
            token_count=50,
            max_tokens=4096,
            pii_mode="block",
        )
        assert not result.approved
        assert result.pii_detected
        assert result.sanitized_text == FALLBACK_MESSAGE

    def test_pii_off_mode_does_not_disable_other_stages(self) -> None:
        """pii_mode='off' is narrow — it disables only the PII stage.
        Delimiter-echo detection (and the other stages) still reject."""
        result = validate_output(
            generated_text=f"Response {CONTEXT_BEGIN}leaked{CONTEXT_END}",
            token_count=10,
            max_tokens=4096,
            pii_mode="off",
        )
        assert not result.approved
        assert result.delimiter_echo is True

    def test_delimiter_echo_triggers_rejection(self) -> None:
        result = validate_output(
            generated_text=f"Response {CONTEXT_BEGIN}leaked{CONTEXT_END}",
            token_count=10,
            max_tokens=4096,
        )
        assert not result.approved
        assert result.delimiter_echo is True
        assert any("Delimiter echo" in v for v in result.violations)

    def test_tool_call_violation_triggers_rejection(self) -> None:
        result = validate_output(
            generated_text='Use {"tool": "evil_tool"} to proceed.',
            token_count=10,
            max_tokens=4096,
        )
        assert not result.approved
        assert result.tool_call_violation is True
        assert any("Unauthorized" in v for v in result.violations)

    def test_authorized_tool_call_passes(self) -> None:
        # Uses a built tool that is actually in TOOL_CALL_ALLOWLIST.
        result = validate_output(
            generated_text='<tool_call>get_current_time</tool_call>',
            token_count=10,
            max_tokens=4096,
        )
        assert result.approved
        assert result.tool_call_violation is False

    def test_formerly_authorized_unbuilt_tool_call_now_blocked(self) -> None:
        """'search' was in the old 14-name allowlist but is not built.
        After Domain 5 prune, PGOV must block it."""
        result = validate_output(
            generated_text='<tool_call>search</tool_call>',
            token_count=10,
            max_tokens=4096,
        )
        assert not result.approved
        assert result.tool_call_violation is True

    def test_leakage_with_injected_detector(self) -> None:
        mock_detector = MagicMock(spec=LeakageDetector)
        mock_detector.check_leakage.return_value = 0.92
        set_leakage_detector(mock_detector)
        try:
            result = validate_output(
                generated_text="Verbatim copied text.",
                token_count=10,
                max_tokens=4096,
                retrieved_chunks=["Verbatim copied text."],
                cosine_threshold=0.85,
            )
            assert not result.approved
            assert result.leakage_score == 0.92
            assert any("Leakage" in v for v in result.violations)
        finally:
            set_leakage_detector(None)  # type: ignore[arg-type]

    def test_leakage_below_threshold_passes(self) -> None:
        mock_detector = MagicMock(spec=LeakageDetector)
        mock_detector.check_leakage.return_value = 0.5
        set_leakage_detector(mock_detector)
        try:
            result = validate_output(
                generated_text="Paraphrased content.",
                token_count=10,
                max_tokens=4096,
                retrieved_chunks=["Original source text."],
                cosine_threshold=0.85,
            )
            assert result.approved
            assert result.leakage_score == 0.5
        finally:
            set_leakage_detector(None)  # type: ignore[arg-type]

    def test_no_chunks_skips_leakage(self) -> None:
        result = validate_output(
            generated_text="No RAG chunks provided.",
            token_count=10,
            max_tokens=4096,
            retrieved_chunks=None,
        )
        assert result.leakage_score == 0.0

    def test_multiple_violations_all_captured(self) -> None:
        mock_detector = MagicMock(spec=LeakageDetector)
        mock_detector.check_leakage.return_value = 0.95
        set_leakage_detector(mock_detector)
        try:
            result = validate_output(
                generated_text=(
                    f"SSN: 123-45-6789 {CONTEXT_BEGIN} "
                    '<tool_call>evil</tool_call>'
                ),
                token_count=9999,
                max_tokens=4096,
                retrieved_chunks=["some chunk"],
                cosine_threshold=0.85,
            )
            assert not result.approved
            assert not result.token_count_valid
            assert result.pii_detected is True
            assert result.delimiter_echo is True
            assert result.tool_call_violation is True
            assert result.leakage_score == 0.95
            assert len(result.violations) >= 4
        finally:
            set_leakage_detector(None)  # type: ignore[arg-type]

    def test_custom_tool_allowlist(self) -> None:
        result = validate_output(
            generated_text='<tool_call>custom_ok</tool_call>',
            token_count=10,
            max_tokens=4096,
            tool_allowlist=frozenset({"custom_ok"}),
        )
        assert result.approved
        assert result.tool_call_violation is False


# ─────────────────── Fail-Closed Error Handling ───────────────────────


class TestFailClosed:
    """PGOV Fail-Closed behavior on internal errors."""

    def test_pipeline_exception_returns_unapproved(self) -> None:
        """If an unexpected exception occurs, PGOV suppresses the response."""
        with patch(
            "services.assistant_orchestrator.src.pgov.check_pii",
            side_effect=RuntimeError("unexpected crash"),
        ):
            result = validate_output(
                generated_text="Some text.",
                token_count=10,
                max_tokens=4096,
            )
            assert not result.approved
            assert result.sanitized_text == FALLBACK_MESSAGE
            assert any("internal error" in v.lower() for v in result.violations)


# ──────────────── Provenance-Aware Redaction (redact mode) ─────────────


class TestProvenanceRedaction:
    """pii_mode='redact' — provenance-aware honest redaction.

    PII traced to the user's own loaded documents/messages is surfaced;
    PII that cannot be traced is replaced with a visible marker and the
    response is still delivered (not suppressed).
    """

    def test_find_pii_spans_locates_positions(self) -> None:
        text = "Reach me at 555-123-4567 today."
        spans = find_pii_spans(text)
        assert len(spans) == 1
        assert spans[0].label == "PHONE_US"
        assert text[spans[0].start:spans[0].end] == spans[0].text == "555-123-4567"

    def test_find_pii_spans_clean_text_empty(self) -> None:
        assert find_pii_spans("The weather is sunny.") == []

    def test_untrusted_pii_redacted_response_still_approved(self) -> None:
        """PII with no provenance is redacted in place; the response is
        delivered, not suppressed — the honest middle ground."""
        result = validate_output(
            generated_text="The number is 555-987-6543.",
            token_count=20,
            max_tokens=4096,
            pii_mode="redact",
            trusted_source="",
        )
        assert result.approved
        assert "555-987-6543" not in result.sanitized_text
        assert "phone number withheld" in result.sanitized_text

    def test_trusted_pii_surfaced(self) -> None:
        """PII that appears in the user's loaded content is surfaced."""
        result = validate_output(
            generated_text="Your sister's number is 555-987-6543.",
            token_count=20,
            max_tokens=4096,
            pii_mode="redact",
            trusted_source="Contacts: sister 555-987-6543; work 555-111-2222",
        )
        assert result.approved
        assert "555-987-6543" in result.sanitized_text
        assert "withheld" not in result.sanitized_text

    def test_provenance_match_ignores_formatting(self) -> None:
        """A number the model reformatted still matches its source."""
        result = validate_output(
            generated_text="Call (555) 987-6543 for details.",
            token_count=20,
            max_tokens=4096,
            pii_mode="redact",
            trusted_source="phone: 555-987-6543",
        )
        assert result.approved
        assert "(555) 987-6543" in result.sanitized_text

    def test_mixed_trusted_and_untrusted(self) -> None:
        """In one response, a trusted number is surfaced and an untrusted
        one is redacted."""
        result = validate_output(
            generated_text="Mine is 555-111-2222; theirs is 555-999-8888.",
            token_count=30,
            max_tokens=4096,
            pii_mode="redact",
            trusted_source="my number is 555-111-2222",
        )
        assert result.approved
        assert "555-111-2222" in result.sanitized_text
        assert "555-999-8888" not in result.sanitized_text
        assert "phone number withheld" in result.sanitized_text

    def test_audit_trail_recorded_without_raw_pii(self) -> None:
        """Every decision is audited; the record never carries the PII value."""
        result = validate_output(
            generated_text="Email evil@example.com about it.",
            token_count=20,
            max_tokens=4096,
            pii_mode="redact",
            trusted_source="",
        )
        assert len(result.pii_redactions) == 1
        record = result.pii_redactions[0]
        assert record["label"] == "EMAIL"
        assert record["action"] == "redacted"
        assert "evil@example.com" not in str(record)

    def test_audit_trail_records_surfaced_decision(self) -> None:
        result = validate_output(
            generated_text="Reach me at user@home.com.",
            token_count=20,
            max_tokens=4096,
            pii_mode="redact",
            trusted_source="contact: user@home.com",
        )
        assert len(result.pii_redactions) == 1
        assert result.pii_redactions[0]["action"] == "surfaced"

    def test_clean_text_unchanged_in_redact_mode(self) -> None:
        result = validate_output(
            generated_text="The weather is sunny today.",
            token_count=20,
            max_tokens=4096,
            pii_mode="redact",
            trusted_source="",
        )
        assert result.approved
        assert result.sanitized_text == "The weather is sunny today."
        assert result.pii_redactions == []

    def test_redact_mode_does_not_disable_other_stages(self) -> None:
        """redact handles PII but the delimiter-echo stage still rejects."""
        result = validate_output(
            generated_text=f"Response {CONTEXT_BEGIN}leak{CONTEXT_END}",
            token_count=20,
            max_tokens=4096,
            pii_mode="redact",
            trusted_source="",
        )
        assert not result.approved
        assert result.delimiter_echo is True


# ─────────────── Context-Aware Detection (fragmented PII) ──────────────


class TestContextAwareDetection:
    """Context-gated recognizers catch PII fragments that canonical patterns
    miss — e.g. a phone number disclosed across labelled lines."""

    def test_local_phone_with_context_detected(self) -> None:
        spans = find_pii_spans("Phone Number: 555-0198")
        assert any(s.label == "PHONE_LOCAL" and s.text == "555-0198" for s in spans)

    def test_area_code_with_context_detected(self) -> None:
        spans = find_pii_spans("Area Code: 212")
        assert any(s.label == "AREA_CODE" and s.text == "212" for s in spans)

    def test_account_number_with_context_detected(self) -> None:
        spans = find_pii_spans("Your account number is 884213.")
        assert any(s.label == "ACCOUNT_NUMBER" and s.text == "884213" for s in spans)

    def test_bare_number_without_context_not_flagged(self) -> None:
        """Precision: a 7-digit number with no PII-announcing word nearby is
        NOT flagged — context gating prevents a false-positive flood."""
        spans = find_pii_spans("The shipment had 555 0198 units in total.")
        assert spans == []

    def test_context_match_is_medium_confidence(self) -> None:
        spans = find_pii_spans("Phone Number: 555-0198")
        phone = next(s for s in spans if s.label == "PHONE_LOCAL")
        assert phone.confidence == CONFIDENCE_MEDIUM

    def test_canonical_match_is_high_confidence(self) -> None:
        spans = find_pii_spans("Call 555-123-4567 now.")
        phone = next(s for s in spans if s.label == "PHONE_US")
        assert phone.confidence == CONFIDENCE_HIGH

    def test_fragmented_phone_redacted_in_redact_mode(self) -> None:
        """The exact gap from live testing: a number split into 'Area Code'
        and 'Phone Number' fragments (Markdown-formatted) is now fully
        redacted."""
        result = validate_output(
            generated_text="**Area Code:** 212\n**Phone Number:** 555-0198",
            token_count=30,
            max_tokens=4096,
            pii_mode="redact",
            trusted_source="",
        )
        assert result.approved
        assert "212" not in result.sanitized_text
        assert "555-0198" not in result.sanitized_text
        assert "area code withheld" in result.sanitized_text
        assert "phone number withheld" in result.sanitized_text

    def test_fragment_audit_records_medium_confidence(self) -> None:
        result = validate_output(
            generated_text="Phone Number: 555-0198",
            token_count=20,
            max_tokens=4096,
            pii_mode="redact",
            trusted_source="",
        )
        assert result.pii_redactions
        rec = result.pii_redactions[0]
        assert rec["confidence"] == CONFIDENCE_MEDIUM
        assert rec["action"] == "redacted"

    def test_fragment_traced_to_documents_is_surfaced(self) -> None:
        """A fragment that traces to the user's own content is still
        surfaced — provenance still wins over detection."""
        result = validate_output(
            generated_text="Phone Number: 555-0198",
            token_count=20,
            max_tokens=4096,
            pii_mode="redact",
            trusted_source="my landline is 555-0198",
        )
        assert result.approved
        assert "555-0198" in result.sanitized_text


# ─────────────── Luhn Checksum — Credit Card Detector Accuracy ────────────────


class TestLuhnChecksum:
    """Luhn (mod-10) checksum validation for CREDIT_CARD detection.

    The 2026-06-03 Domain 5 audit found that the CREDIT_CARD regex matched
    ANY 13-19 digit run without a checksum, producing false positives on
    order numbers, account IDs, and other long digit strings.  These tests
    verify that the fix:
      (a) accepts known-valid Primary Account Numbers (PANs), and
      (b) rejects non-Luhn digit strings — including the exact false-positive
          the old code produced.
    """

    # -- _luhn_valid unit tests ------------------------------------------------

    def test_luhn_valid_visa_test_pan(self) -> None:
        """Canonical Visa test PAN 4111111111111111 passes Luhn."""
        assert _luhn_valid("4111111111111111") is True

    def test_luhn_valid_mastercard_test_pan(self) -> None:
        """Canonical Mastercard test PAN 5500005555555559 passes Luhn."""
        assert _luhn_valid("5500005555555559") is True

    def test_luhn_valid_amex_test_pan(self) -> None:
        """Canonical AmEx test PAN 378282246310005 passes Luhn."""
        assert _luhn_valid("378282246310005") is True

    def test_luhn_valid_discover_test_pan(self) -> None:
        """Canonical Discover test PAN 6011111111111117 passes Luhn."""
        assert _luhn_valid("6011111111111117") is True

    def test_luhn_rejects_visa_bad_checksum(self) -> None:
        """Visa PAN with last digit incremented by 1 fails Luhn."""
        assert _luhn_valid("4111111111111112") is False

    def test_luhn_rejects_all_same_digit(self) -> None:
        """1111111111111 (13 ones) fails Luhn."""
        assert _luhn_valid("1111111111111") is False

    def test_luhn_rejects_sequential_digits(self) -> None:
        """1234567890123 — a typical order-number shape — fails Luhn."""
        assert _luhn_valid("1234567890123") is False

    # -- _luhn_filter unit tests (strips separators before checking) -----------

    def test_luhn_filter_strips_spaces_visa(self) -> None:
        """Spaced Visa '4111 1111 1111 1111' is accepted after space-strip."""
        assert _luhn_filter("4111 1111 1111 1111") is True

    def test_luhn_filter_strips_dashes_amex(self) -> None:
        """Dashed AmEx '3782-822463-10005' is accepted after dash-strip."""
        assert _luhn_filter("3782-822463-10005") is True

    def test_luhn_filter_rejects_non_luhn(self) -> None:
        """Plain 13-digit non-Luhn string is rejected."""
        assert _luhn_filter("1234567890123") is False

    def test_luhn_filter_rejects_too_short(self) -> None:
        """A 12-digit Luhn-valid prefix is too short to be a PAN."""
        # Truncate a valid PAN to 12 digits — must be rejected on length
        assert _luhn_filter("411111111111") is False

    # -- check_pii / find_pii_spans integration --------------------------------

    def test_luhn_valid_spaced_visa_detected_check_pii(self) -> None:
        """Spaced Visa PAN triggers CREDIT_CARD in check_pii (block mode)."""
        matches = check_pii("Charge 4111 1111 1111 1111 to the account.")
        assert "CREDIT_CARD" in matches

    def test_luhn_valid_dashed_amex_detected_check_pii(self) -> None:
        """Dashed AmEx PAN triggers CREDIT_CARD in check_pii."""
        matches = check_pii("AmEx card: 3782-822463-10005 expires 12/28.")
        assert "CREDIT_CARD" in matches

    def test_luhn_valid_mastercard_detected_check_pii(self) -> None:
        """Compact Mastercard PAN triggers CREDIT_CARD in check_pii."""
        matches = check_pii("Payment via 5500005555555559.")
        assert "CREDIT_CARD" in matches

    def test_non_luhn_order_number_not_flagged_check_pii(self) -> None:
        """A 13-digit order ID that fails Luhn must NOT trigger CREDIT_CARD."""
        matches = check_pii("Order 1234567890123 has been shipped.")
        assert "CREDIT_CARD" not in matches

    def test_non_luhn_16_digit_id_not_flagged_check_pii(self) -> None:
        """A 16-digit non-Luhn ID must NOT trigger CREDIT_CARD."""
        matches = check_pii("Reference ID: 1234567890123456")
        assert "CREDIT_CARD" not in matches

    def test_luhn_valid_visa_detected_find_pii_spans(self) -> None:
        """find_pii_spans locates the spaced Visa span with CREDIT_CARD label."""
        text = "Charge 4111 1111 1111 1111 to the account."
        spans = find_pii_spans(text)
        cc_spans = [s for s in spans if s.label == "CREDIT_CARD"]
        assert len(cc_spans) >= 1
        # Verify the matched text contains the PAN digits
        assert "4111" in cc_spans[0].text

    def test_non_luhn_string_not_in_find_pii_spans(self) -> None:
        """find_pii_spans returns no CREDIT_CARD for a non-Luhn 13-digit run."""
        spans = find_pii_spans("Track number: 1234567890123")
        cc_spans = [s for s in spans if s.label == "CREDIT_CARD"]
        assert cc_spans == []

    # -- Teeth test: reconstruct the exact pre-fix false positive --------------

    def test_meta_old_code_false_positive_no_longer_fires(self) -> None:
        """TEETH: prove the old no-checksum behavior has been closed.

        The old code (regex-only, no Luhn gate) would match any 13-19 digit
        run as CREDIT_CARD.  '1234567890123' is a 13-digit string that fails
        Luhn — the old code would flag it as a card number, making the egress
        redaction pipeline noisy and untrusted.

        This test reconstructs that false-positive scenario and asserts the
        new code does NOT fire on it.  It also verifies that the same code
        DOES fire on the legitimate Visa PAN, so we are not accidentally
        testing a broken detector.
        """
        false_positive_text = "Order ID: 1234567890123"
        true_positive_text = "Card: 4111111111111111"

        # Old behavior: both would return CREDIT_CARD. New behavior: only the
        # legitimate PAN triggers the detector.
        assert "CREDIT_CARD" not in check_pii(false_positive_text), (
            "REGRESSION: '1234567890123' (non-Luhn order number) is being "
            "flagged as CREDIT_CARD. The Luhn gate is not working."
        )
        assert "CREDIT_CARD" in check_pii(true_positive_text), (
            "REGRESSION: '4111111111111111' (Luhn-valid Visa PAN) is NOT "
            "being flagged as CREDIT_CARD. The detector is broken."
        )

    # -- Both paths covered: validate_output (block + redact) -----------------

    def test_luhn_valid_pan_blocked_in_block_mode(self) -> None:
        """A valid PAN in block mode triggers rejection via check_pii."""
        result = validate_output(
            generated_text="Card on file: 4111111111111111.",
            token_count=20,
            max_tokens=4096,
            pii_mode="block",
        )
        assert not result.approved
        assert result.pii_detected

    def test_non_luhn_digit_string_not_flagged_as_credit_card_block_mode(self) -> None:
        """A non-Luhn 13-digit string does NOT trigger CREDIT_CARD detection.

        Note: a long digit run may still match PHONE_US (a 10-digit suffix
        can look like a US phone number).  The assertion here is specifically
        that CREDIT_CARD is absent — the Luhn gate closed the false-positive
        surface for card detection, which is what the audit finding required.
        """
        matches = check_pii("Order 1234567890123 shipped to customer.")
        assert "CREDIT_CARD" not in matches

    def test_luhn_valid_pan_redacted_in_redact_mode(self) -> None:
        """A valid PAN in redact mode is redacted (not in trusted source)."""
        result = validate_output(
            generated_text="Your card 4111111111111111 was charged.",
            token_count=20,
            max_tokens=4096,
            pii_mode="redact",
            trusted_source="",
        )
        assert result.approved
        assert "4111111111111111" not in result.sanitized_text
        assert "credit card number withheld" in result.sanitized_text

    def test_non_luhn_digit_string_not_flagged_as_credit_card_find_pii_spans(self) -> None:
        """find_pii_spans returns no CREDIT_CARD span for a non-Luhn 13-digit run.

        Uses find_pii_spans directly so we can assert specifically that
        CREDIT_CARD is absent without the test depending on whether other
        patterns (e.g. PHONE_US) also fire on the same text.
        """
        spans = find_pii_spans("Package tracking: 1234567890123 is en route.")
        cc_spans = [s for s in spans if s.label == "CREDIT_CARD"]
        assert cc_spans == []
