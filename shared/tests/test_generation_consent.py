r"""Unit tests for the per-generation-batch approval seam (ADR-023 Am.4, #723 rung 2).

Covers the generation-consent registry + request function + arg extractor, and the
one-click SystemConfirmApprovalVerifier — all WITHOUT a desktop (the confirm dialog
is injected / the verifier is a stub). The seam is DORMANT (no real generator tool
routes here today); these lock the infrastructure so it is correct the day one is.
"""

from __future__ import annotations

from typing import Any

import pytest

from shared.security.escalation_consent import ApprovalResult, EscalationContext
from shared.security.generation_consent import (
    active_generation_verifier,
    clear_generation_verifier,
    extract_generation_request,
    register_generation_verifier,
    request_generation_consent,
)
from shared.security.system_confirm_verifier import SystemConfirmApprovalVerifier


@pytest.fixture(autouse=True)
def _isolate_gen_verifier() -> Any:
    saved = active_generation_verifier()
    clear_generation_verifier()
    yield
    clear_generation_verifier()
    if saved is not None:
        register_generation_verifier(saved)


class _RecordingVerifier:
    def __init__(self, approved: bool) -> None:
        self._approved = approved
        self.seen: list[Any] = []

    def verify(self, context: Any) -> ApprovalResult:
        self.seen.append(context)
        return (
            ApprovalResult.allow(verifier_identity="mock")
            if self._approved
            else ApprovalResult.deny("no", verifier_identity="mock")
        )


class TestRequestGenerationConsent:
    def test_no_verifier_is_denied_fail_closed(self) -> None:
        # Dormant default (the shipped posture) → DENY.
        assert request_generation_consent("a cat", 1, timeout_s=1.0) is False

    def test_approved_verifier_allows_and_context_is_generation_shaped(self) -> None:
        v = _RecordingVerifier(approved=True)
        register_generation_verifier(v)
        assert request_generation_consent("a red bicycle", 2, timeout_s=1.0) is True
        ctx = v.seen[0]
        assert ctx.source == "generation"
        assert ctx.tool_name == "generate_image"
        assert "a red bicycle" in ctx.action_summary
        assert "Generate 2 images" in ctx.action_summary

    def test_denied_verifier_denies(self) -> None:
        register_generation_verifier(_RecordingVerifier(approved=False))
        assert request_generation_consent("x", 1, timeout_s=1.0) is False

    def test_singular_wording_for_one_image(self) -> None:
        v = _RecordingVerifier(approved=True)
        register_generation_verifier(v)
        request_generation_consent("x", 1, timeout_s=1.0)
        assert "Generate 1 image:" in v.seen[0].action_summary

    def test_register_requires_verify_method(self) -> None:
        with pytest.raises(TypeError):
            register_generation_verifier(object())  # type: ignore[arg-type]


class TestExtractGenerationRequest:
    def test_prompt_and_default_count(self) -> None:
        assert extract_generation_request('{"prompt":"a dog"}') == ("a dog", 1)

    def test_count_field(self) -> None:
        assert extract_generation_request('{"prompt":"a dog","count":3}') == ("a dog", 3)

    def test_num_images_field(self) -> None:
        assert extract_generation_request('{"prompt":"a dog","num_images":4}') == ("a dog", 4)

    def test_missing_prompt(self) -> None:
        assert extract_generation_request('{"count":2}') == ("(prompt unavailable)", 2)

    def test_malformed_json(self) -> None:
        assert extract_generation_request("nope") == ("(prompt unavailable)", 1)

    def test_bool_count_ignored(self) -> None:
        # A JSON true is an int subclass in Python; it must NOT be read as a count.
        assert extract_generation_request('{"prompt":"a","count":true}') == ("a", 1)

    def test_nonpositive_count_falls_back_to_one(self) -> None:
        assert extract_generation_request('{"prompt":"a","count":0}') == ("a", 1)

    def test_long_prompt_capped(self) -> None:
        prompt, _ = extract_generation_request('{"prompt":"' + "z" * 900 + '"}')
        assert len(prompt) == 300


class TestSystemConfirmApprovalVerifier:
    def test_confirm_yes_allows(self) -> None:
        v = SystemConfirmApprovalVerifier(confirm_fn=lambda t, m: True)
        result = v.verify(EscalationContext("GENERATE_IMAGE", "Generate 1 image: a cat", source="generation"))
        assert result.approved is True
        assert result.verifier_identity == "system-confirm"

    def test_confirm_no_denies(self) -> None:
        v = SystemConfirmApprovalVerifier(confirm_fn=lambda t, m: False)
        assert v.verify(EscalationContext("GENERATE_IMAGE", "x")).approved is False

    def test_confirm_raise_is_fail_closed(self) -> None:
        def _boom(t: str, m: str) -> bool:
            raise RuntimeError("no gui")

        v = SystemConfirmApprovalVerifier(confirm_fn=_boom)
        assert v.verify(EscalationContext("GENERATE_IMAGE", "x")).approved is False

    def test_message_carries_the_prompt(self) -> None:
        seen: list[str] = []

        def _cap(title: str, message: str) -> bool:
            seen.append(message)
            return True

        v = SystemConfirmApprovalVerifier(confirm_fn=_cap)
        v.verify(EscalationContext("GENERATE_IMAGE", "Generate 1 image: a lighthouse", source="generation"))
        assert "a lighthouse" in seen[0]

    def test_end_to_end_through_request(self) -> None:
        register_generation_verifier(SystemConfirmApprovalVerifier(confirm_fn=lambda t, m: True))
        assert request_generation_consent("a cat", 1, timeout_s=2.0) is True
        clear_generation_verifier()
        register_generation_verifier(SystemConfirmApprovalVerifier(confirm_fn=lambda t, m: False))
        assert request_generation_consent("a cat", 1, timeout_s=2.0) is False
