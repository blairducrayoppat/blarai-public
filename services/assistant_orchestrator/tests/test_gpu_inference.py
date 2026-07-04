"""
GPU Inference Tests — Assistant Orchestrator
===============================================
P1.8: Tests for Orchestrator GPU generation, KV-cache management,
preemption detection, token sampling, and circuit breaker integration.

Test strategy:
  - Unit tests: data classes, softmax, token sampling logic.
  - Integration tests: mocked OpenVINO for full generate() pipeline.
  - Fail-Closed tests: verify behavior when model/OV unavailable.
  - KV-cache tests: session warm/cold tracking.
  - Preemption tests: timing anomaly detection logic.
  - Statistics tests: cumulative token/request counters.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

import hashlib
import json
import os
import tempfile
from pathlib import Path

from services.assistant_orchestrator.src.gpu_inference import (
    GenerationConfig,
    GenerationResult,
    OrchestratorGPUInference,
    PreemptionEvent,
    QWEN3_IM_END_TOKEN_ID,
    _DEFAULT_SYSTEM_PROMPT,
    _sample_token,
    _softmax,
)


# ---------------------------------------------------------------------------
# Test: GenerationResult
# ---------------------------------------------------------------------------


class TestGenerationResult:
    """GenerationResult dataclass validation."""

    def test_success_fields(self) -> None:
        r = GenerationResult(
            tokens=[1, 2, 3],
            text="hello world",
            token_count=3,
            latency_first_token_ms=10.0,
            latency_total_ms=30.0,
            was_preempted=False,
            resume_latency_ms=0.0,
            truncated=False,
        )
        assert r.tokens == [1, 2, 3]
        assert r.text == "hello world"
        assert r.token_count == 3
        assert r.error is None

    def test_error_fields(self) -> None:
        r = GenerationResult(
            tokens=[],
            text="",
            token_count=0,
            latency_first_token_ms=0.0,
            latency_total_ms=0.0,
            was_preempted=False,
            resume_latency_ms=0.0,
            truncated=False,
            error="Model not loaded",
        )
        assert r.error is not None
        assert r.token_count == 0

    def test_frozen_dataclass(self) -> None:
        r = GenerationResult(
            tokens=[],
            text="",
            token_count=0,
            latency_first_token_ms=0.0,
            latency_total_ms=0.0,
            was_preempted=False,
            resume_latency_ms=0.0,
            truncated=False,
        )
        with pytest.raises(AttributeError):
            r.text = "mutated"  # type: ignore[misc]

    def test_preemption_metadata(self) -> None:
        r = GenerationResult(
            tokens=[1],
            text="a",
            token_count=1,
            latency_first_token_ms=5.0,
            latency_total_ms=50.0,
            was_preempted=True,
            resume_latency_ms=42.5,
            truncated=False,
        )
        assert r.was_preempted is True
        assert r.resume_latency_ms == 42.5

    def test_truncated_flag(self) -> None:
        r = GenerationResult(
            tokens=[1] * 4096,
            text="",
            token_count=4096,
            latency_first_token_ms=0.0,
            latency_total_ms=0.0,
            was_preempted=False,
            resume_latency_ms=0.0,
            truncated=True,
        )
        assert r.truncated is True
        assert r.token_count == 4096


# ---------------------------------------------------------------------------
# Test: GenerationConfig
# ---------------------------------------------------------------------------


class TestGenerationConfig:
    """GenerationConfig defaults and customization."""

    def test_defaults(self) -> None:
        c = GenerationConfig()
        assert c.max_new_tokens == 4096
        # ADR-012: Qwen3-14B INT4 deterministic defaults
        assert c.temperature == pytest.approx(0.0)
        assert c.top_k == 0
        assert c.top_p == pytest.approx(1.0)
        assert c.repetition_penalty == pytest.approx(1.0)
        assert c.do_sample is False

    def test_custom_values(self) -> None:
        c = GenerationConfig(
            max_new_tokens=256,
            temperature=0.0,
            top_k=10,
            top_p=0.5,
            do_sample=False,
        )
        assert c.max_new_tokens == 256
        assert c.temperature == 0.0
        assert c.do_sample is False


# ---------------------------------------------------------------------------
# Test: PreemptionEvent
# ---------------------------------------------------------------------------


class TestPreemptionEvent:
    """PreemptionEvent dataclass validation."""

    def test_fields(self) -> None:
        e = PreemptionEvent(
            step_index=10,
            step_latency_ms=50.0,
            median_latency_ms=5.0,
            ratio=10.0,
            timestamp=1234567890.0,
        )
        assert e.step_index == 10
        assert e.ratio == pytest.approx(10.0)

    def test_frozen(self) -> None:
        e = PreemptionEvent(
            step_index=0,
            step_latency_ms=1.0,
            median_latency_ms=1.0,
            ratio=1.0,
            timestamp=0.0,
        )
        with pytest.raises(AttributeError):
            e.step_index = 5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Test: Softmax
# ---------------------------------------------------------------------------


class TestSoftmax:
    """Numerically-stable softmax."""

    def test_uniform(self) -> None:
        logits = np.array([1.0, 1.0, 1.0])
        probs = _softmax(logits)
        np.testing.assert_allclose(probs, [1 / 3, 1 / 3, 1 / 3], atol=1e-7)

    def test_single_peak(self) -> None:
        logits = np.array([0.0, 0.0, 100.0])
        probs = _softmax(logits)
        assert probs[2] > 0.99

    def test_numerical_stability(self) -> None:
        """Large logits should not cause overflow."""
        logits = np.array([1000.0, 1001.0, 1002.0])
        probs = _softmax(logits)
        assert np.all(np.isfinite(probs))
        assert abs(probs.sum() - 1.0) < 1e-7

    def test_sums_to_one(self) -> None:
        logits = np.random.randn(100)
        probs = _softmax(logits)
        assert abs(probs.sum() - 1.0) < 1e-7


# ---------------------------------------------------------------------------
# Test: Token Sampling
# ---------------------------------------------------------------------------


class TestSampleToken:
    """Token sampling strategies."""

    def test_greedy(self) -> None:
        logits = np.array([0.1, 0.3, 0.9, 0.2])
        config = GenerationConfig(do_sample=False)
        token = _sample_token(logits, config)
        assert token == 2  # argmax

    def test_temperature_zero_is_greedy(self) -> None:
        """Low temperature collapses to near-deterministic."""
        logits = np.array([1.0, 10.0, 0.5])
        config = GenerationConfig(temperature=0.01, do_sample=True)
        # With very low temperature, should almost always pick index 1
        results = [_sample_token(logits, config) for _ in range(20)]
        assert all(r == 1 for r in results)

    def test_top_k_filtering(self) -> None:
        """Top-k=1 should always select the highest logit."""
        logits = np.array([0.1, 0.9, 0.5])
        config = GenerationConfig(top_k=1, temperature=1.0, do_sample=True)
        token = _sample_token(logits, config)
        assert token == 1

    def test_top_p_filtering(self) -> None:
        """Top-p filtering with very low p should concentrate sampling."""
        logits = np.array([0.01, 0.01, 100.0, 0.01])
        config = GenerationConfig(
            top_p=0.1, top_k=0, temperature=1.0, do_sample=True,
        )
        token = _sample_token(logits, config)
        assert token == 2  # dominant logit

    def test_returns_int(self) -> None:
        logits = np.random.randn(100)
        config = GenerationConfig()
        token = _sample_token(logits, config)
        assert isinstance(token, int)


# ---------------------------------------------------------------------------
# Test: Fail-Closed Defaults
# ---------------------------------------------------------------------------


class TestFailClosedDefaults:
    """Model not loaded → all methods return Fail-Closed results."""

    def setup_method(self) -> None:
        self.engine = OrchestratorGPUInference(model_dir="/nonexistent")

    def test_generate_not_loaded(self) -> None:
        result = self.engine.generate(input_ids=[1, 2, 3])
        assert result.error is not None
        assert "not loaded" in result.error.lower() or "Fail-Closed" in result.error
        assert result.tokens == []
        assert result.token_count == 0

    def test_generate_text_not_loaded(self) -> None:
        result = self.engine.generate_text("Hello world")
        assert result.error is not None
        assert result.tokens == []

    def test_warm_kv_cache_not_loaded(self) -> None:
        assert self.engine.warm_kv_cache([1, 2, 3]) is False

    def test_warm_kv_cache_text_no_tokenizer(self) -> None:
        assert self.engine.warm_kv_cache_text("hello", "s1") is False

    def test_properties_default(self) -> None:
        assert self.engine.loaded is False
        assert self.engine.integrity_result is None
        assert self.engine.device == "GPU"
        assert self.engine.total_tokens_generated == 0
        assert self.engine.total_requests == 0
        assert self.engine.preemption_events == []


# ---------------------------------------------------------------------------
# Test: KV-Cache Management
# ---------------------------------------------------------------------------


class TestKVCacheManagement:
    """Session-level KV-cache warm/cold tracking."""

    def test_new_session_is_cold(self) -> None:
        engine = OrchestratorGPUInference(model_dir="/test")
        assert engine.is_kv_warm("session_1") is False

    def test_mark_warm_via_internal(self) -> None:
        engine = OrchestratorGPUInference(model_dir="/test")
        engine._kv_warm_sessions.add("s1")
        assert engine.is_kv_warm("s1") is True

    def test_invalidate_single(self) -> None:
        engine = OrchestratorGPUInference(model_dir="/test")
        engine._kv_warm_sessions.add("s1")
        engine._kv_warm_sessions.add("s2")
        engine.invalidate_kv("s1")
        assert engine.is_kv_warm("s1") is False
        assert engine.is_kv_warm("s2") is True

    def test_invalidate_all(self) -> None:
        """None → flush all sessions (Code Agent degradation posture)."""
        engine = OrchestratorGPUInference(model_dir="/test")
        engine._kv_warm_sessions.update({"s1", "s2", "s3"})
        engine.invalidate_kv(None)
        assert engine.is_kv_warm("s1") is False
        assert engine.is_kv_warm("s2") is False
        assert engine.is_kv_warm("s3") is False

    def test_invalidate_nonexistent_session(self) -> None:
        """Invalidating a non-warm session is a no-op."""
        engine = OrchestratorGPUInference(model_dir="/test")
        engine.invalidate_kv("does_not_exist")  # should not raise


# ---------------------------------------------------------------------------
# Test: Statistics
# ---------------------------------------------------------------------------


class TestStatistics:
    """Generation statistics tracking."""

    def test_initial_zeros(self) -> None:
        engine = OrchestratorGPUInference(model_dir="/test")
        assert engine.total_tokens_generated == 0
        assert engine.total_requests == 0

    def test_reset(self) -> None:
        engine = OrchestratorGPUInference(model_dir="/test")
        engine._total_tokens_generated = 100
        engine._total_requests = 5
        engine._preemption_events.append(
            PreemptionEvent(0, 10.0, 1.0, 10.0, 0.0)
        )
        engine.reset_statistics()
        assert engine.total_tokens_generated == 0
        assert engine.total_requests == 0
        assert engine.preemption_events == []


# ---------------------------------------------------------------------------
# Test: Unload
# ---------------------------------------------------------------------------


class TestUnload:
    """Unload clears all state."""

    def test_unload_clears_state(self) -> None:
        engine = OrchestratorGPUInference(model_dir="/test")
        engine._loaded = True
        engine._kv_warm_sessions.add("s1")
        engine._total_tokens_generated = 50
        engine._total_requests = 3

        engine.unload()

        assert engine.loaded is False
        assert engine.integrity_result is None
        assert engine.is_kv_warm("s1") is False
        assert engine.total_tokens_generated == 0
        assert engine.total_requests == 0


# ---------------------------------------------------------------------------
# Test: Preemption Detection Logic
# ---------------------------------------------------------------------------


class TestPreemptionDetection:
    """Timing anomaly detection for GPU preemption (ADR-011: all inference on GPU)."""

    def test_no_detection_below_min_samples(self) -> None:
        engine = OrchestratorGPUInference(model_dir="/test")
        preempted, resume = engine._check_preemption(
            step=1,
            step_ms=100.0,
            step_times=[1.0, 100.0],  # only 2 samples
            already_preempted=False,
            max_resume_ms=0.0,
        )
        assert preempted is False

    def test_detection_on_timing_anomaly(self) -> None:
        engine = OrchestratorGPUInference(model_dir="/test")
        # 4 normal steps + 1 anomalous step (>5× median)
        step_times = [1.0, 1.1, 1.0, 0.9, 50.0]
        preempted, resume = engine._check_preemption(
            step=4,
            step_ms=50.0,
            step_times=step_times,
            already_preempted=False,
            max_resume_ms=0.0,
        )
        assert preempted is True
        assert resume > 0.0
        assert len(engine.preemption_events) == 1
        assert engine.preemption_events[0].step_index == 4

    def test_no_false_positive_on_normal_variation(self) -> None:
        engine = OrchestratorGPUInference(model_dir="/test")
        step_times = [1.0, 1.2, 0.8, 1.1, 1.3]  # normal variation
        preempted, _ = engine._check_preemption(
            step=4,
            step_ms=1.3,
            step_times=step_times,
            already_preempted=False,
            max_resume_ms=0.0,
        )
        assert preempted is False
        assert len(engine.preemption_events) == 0

    def test_preserves_already_preempted(self) -> None:
        engine = OrchestratorGPUInference(model_dir="/test")
        step_times = [1.0, 1.0, 1.0, 1.0, 1.0]  # no anomaly
        preempted, _ = engine._check_preemption(
            step=4,
            step_ms=1.0,
            step_times=step_times,
            already_preempted=True,  # already flagged
            max_resume_ms=10.0,
        )
        assert preempted is True  # stays True


# ---------------------------------------------------------------------------
# Test: Full Generation with Mocked OpenVINO
# ---------------------------------------------------------------------------


class _FakeTokenizer:
    eos_token_id = 2
    pad_token_id = 2

    def __call__(self, text: str, return_tensors: str = "np") -> dict[str, np.ndarray]:
        if return_tensors != "np":
            raise ValueError("Only numpy tensors are supported in tests")

        pieces = [piece for piece in text.split() if piece]
        token_ids: list[int] = []
        for piece in pieces:
            if piece.lstrip("-").isdigit():
                token_ids.append(int(piece))
            else:
                token_ids.append(max(1, len(piece)))

        if not token_ids:
            token_ids = [0]

        input_ids = np.array([token_ids], dtype=np.int64)
        attention_mask = np.ones_like(input_ids, dtype=np.int64)
        return {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
        }

    def decode(self, tokens: list[int], skip_special_tokens: bool = True) -> str:
        _ = skip_special_tokens
        return " ".join(str(token) for token in tokens)


def _make_mock_engine(
    vocab_size: int = 100,
    eos_token_id: int = 2,
    generate_tokens: list[int] | None = None,
) -> OrchestratorGPUInference:
    """Create an OrchestratorGPUInference with mocked OV components.

    Args:
        vocab_size: Vocabulary size for logit output.
        eos_token_id: Token ID that signals end-of-sequence.
        generate_tokens: Sequence of tokens to generate. If provided,
            the mock will produce logits that yield these tokens via argmax.
            After the sequence, EOS is produced.
    """
    engine = OrchestratorGPUInference(model_dir="/mock")
    engine._loaded = True
    engine._eos_token_id = eos_token_id
    engine._tokenizer = _FakeTokenizer()

    _ = vocab_size
    output_tokens = list(generate_tokens or [10, 20, 30])
    engine._pipeline = MagicMock()
    engine._pipeline.generate.return_value = " ".join(str(token) for token in output_tokens)

    return engine


class TestGenerationWithMock:
    """Full generation pipeline with mocked GPU inference."""

    def test_basic_generation(self) -> None:
        engine = _make_mock_engine(generate_tokens=[10, 20, 30])
        config = GenerationConfig(do_sample=False)
        result = engine.generate(
            input_ids=[1, 2, 3],
            config=config,
        )
        assert result.error is None
        assert result.tokens == [10, 20, 30]
        assert result.token_count == 3
        assert result.truncated is False

    def test_eos_stops_generation(self) -> None:
        engine = _make_mock_engine(generate_tokens=[10], eos_token_id=2)
        config = GenerationConfig(do_sample=False)
        result = engine.generate(
            input_ids=[1],
            max_new_tokens=100,
            config=config,
        )
        assert result.error is None
        assert result.tokens == [10]
        assert result.truncated is False

    def test_circuit_breaker_caps_tokens(self) -> None:
        """max_tokens hard cap prevents runaway generation."""
        # Generate tokens that never produce EOS
        long_tokens = list(range(3, 103))  # 100 tokens, none are EOS (2)
        engine = _make_mock_engine(
            generate_tokens=long_tokens, eos_token_id=2,
        )
        engine._max_tokens = 10  # hard cap at 10
        config = GenerationConfig(do_sample=False)
        result = engine.generate(
            input_ids=[1],
            max_new_tokens=10,
            config=config,
        )
        assert result.error is None
        assert result.token_count == 10
        assert result.truncated is True

    def test_statistics_accumulate(self) -> None:
        engine = _make_mock_engine(generate_tokens=[10, 20])
        config = GenerationConfig(do_sample=False)

        engine.generate(input_ids=[1], config=config)
        assert engine.total_tokens_generated == 2
        assert engine.total_requests == 1

        engine.generate(input_ids=[1], config=config)
        assert engine.total_tokens_generated == 4
        assert engine.total_requests == 2

    def test_latency_recorded(self) -> None:
        engine = _make_mock_engine(generate_tokens=[10, 20])
        config = GenerationConfig(do_sample=False)
        result = engine.generate(input_ids=[1], config=config)
        assert result.latency_total_ms > 0.0
        assert result.latency_first_token_ms > 0.0

    def test_pipeline_generate_called(self) -> None:
        """Generate() routes through LLMPipeline."""
        engine = _make_mock_engine(generate_tokens=[10])
        config = GenerationConfig(do_sample=False)
        engine.generate(input_ids=[1], config=config)
        engine._pipeline.generate.assert_called_once()

    def test_generate_text_without_tokenizer(self) -> None:
        engine = _make_mock_engine(generate_tokens=[10])
        engine._tokenizer = None
        result = engine.generate_text("hello")
        assert result.error is not None
        assert "Tokenizer" in result.error

    def test_max_new_tokens_capped_by_max_tokens(self) -> None:
        """max_new_tokens cannot exceed engine's _max_tokens."""
        long_tokens = list(range(3, 53))
        engine = _make_mock_engine(
            generate_tokens=long_tokens, eos_token_id=2,
        )
        engine._max_tokens = 5
        config = GenerationConfig(do_sample=False)
        result = engine.generate(
            input_ids=[1],
            max_new_tokens=50,  # request 50, but engine caps at 5
            config=config,
        )
        assert result.token_count == 5
        assert result.truncated is True


# ---------------------------------------------------------------------------
# Test: Inference Error Handling
# ---------------------------------------------------------------------------


class TestInferenceErrors:
    """Inference errors trigger Fail-Closed responses."""

    def test_infer_exception(self) -> None:
        engine = OrchestratorGPUInference(model_dir="/test")
        engine._loaded = True
        engine._eos_token_id = 2
        engine._tokenizer = _FakeTokenizer()
        engine._pipeline = MagicMock()
        engine._pipeline.generate.side_effect = RuntimeError("GPU fault")

        config = GenerationConfig(do_sample=False)
        result = engine.generate(input_ids=[1], config=config)
        assert result.error is not None
        assert "Fail-Closed" in result.error
        assert result.tokens == []


# ---------------------------------------------------------------------------
# Test: Chat Template Formatting (_format_chat_prompt)
# ---------------------------------------------------------------------------


class _ChatTokenizer(_FakeTokenizer):
    """Tokenizer stub with apply_chat_template support."""

    def apply_chat_template(
        self,
        messages: list[dict[str, str]],
        *,
        tokenize: bool = True,
        add_generation_prompt: bool = False,
    ) -> str:
        parts: list[str] = []
        for msg in messages:
            parts.append(f"<|im_start|>{msg['role']}\n{msg['content']}<|im_end|>")
        if add_generation_prompt:
            parts.append("<|im_start|>assistant")
        return "\n".join(parts) + "\n"


class TestFormatChatPrompt:
    """Validate _format_chat_prompt wraps prompts correctly."""

    def _make_engine(self, tokenizer: object | None = None) -> OrchestratorGPUInference:
        engine = OrchestratorGPUInference(model_dir="/test")
        engine._loaded = True
        engine._eos_token_id = 2
        engine._tokenizer = tokenizer
        engine._pipeline = MagicMock()
        return engine

    def test_uses_apply_chat_template(self) -> None:
        """When the tokenizer has apply_chat_template, it should be used."""
        tok = _ChatTokenizer()
        engine = self._make_engine(tok)
        result = engine._format_chat_prompt("Hello")
        assert "<|im_start|>system" in result
        assert _DEFAULT_SYSTEM_PROMPT in result
        assert "<|im_start|>user\nHello<|im_end|>" in result
        assert "<|im_start|>assistant" in result

    def test_manual_fallback_no_tokenizer(self) -> None:
        """With no tokenizer, falls back to manual ChatML format."""
        engine = self._make_engine(tokenizer=None)
        result = engine._format_chat_prompt("hi")
        assert "<|im_start|>system" in result
        assert _DEFAULT_SYSTEM_PROMPT in result
        assert "<|im_start|>user\nhi<|im_end|>" in result
        assert result.endswith("<|im_start|>assistant\n")

    def test_manual_fallback_template_error(self) -> None:
        """If apply_chat_template raises, falls back to manual format."""
        tok = _ChatTokenizer()
        tok.apply_chat_template = MagicMock(side_effect=TypeError("bad template"))
        engine = self._make_engine(tok)
        result = engine._format_chat_prompt("test")
        assert "<|im_start|>system" in result
        assert "<|im_start|>user\ntest<|im_end|>" in result

    def test_explanatory_prompt_standard_mode_not_augmented(self) -> None:
        """Standard mode (the default) never appends a format scaffold."""
        engine = self._make_engine(_ChatTokenizer())
        result = engine._format_chat_prompt("Tell me about machine learning")
        assert "Response format requirements:" not in result

    def test_factual_question_standard_mode_not_inflated(self) -> None:
        """A plain question must not be inflated into an essay scaffold.

        Regression: "what is" is a substring of "what is your name?", which
        previously triggered the format scaffold in standard mode.
        """
        engine = self._make_engine(_ChatTokenizer())
        result = engine._format_chat_prompt("What is your name?")
        assert "Response format requirements:" not in result

    def test_explanatory_prompt_detailed_mode_gets_stronger_guidance(self) -> None:
        engine = self._make_engine(_ChatTokenizer())
        result = engine._format_chat_prompt(
            "Tell me about machine learning",
            response_depth_mode="detailed",
        )
        assert "Provide 6-9 key concepts as numbered points." in result
        assert "Include at least two short practical examples." in result

    def test_explanatory_prompt_concise_mode_skips_guidance(self) -> None:
        engine = self._make_engine(_ChatTokenizer())
        result = engine._format_chat_prompt(
            "Tell me about machine learning",
            response_depth_mode="concise",
        )
        assert "Response format requirements:" not in result

    def test_invalid_mode_falls_back_to_standard(self) -> None:
        """An unrecognized depth mode behaves like standard — no scaffold."""
        engine = self._make_engine(_ChatTokenizer())
        result = engine._format_chat_prompt(
            "Tell me about machine learning",
            response_depth_mode="unknown",
        )
        assert "Response format requirements:" not in result

    def test_simple_prompt_not_augmented(self) -> None:
        engine = self._make_engine(_ChatTokenizer())
        result = engine._format_chat_prompt("Ping")
        assert "Response format requirements:" not in result

    def test_system_prompt_always_english(self) -> None:
        """System prompt must instruct English responses."""
        assert "English" in _DEFAULT_SYSTEM_PROMPT
        engine = self._make_engine(_ChatTokenizer())
        result = engine._format_chat_prompt("任意のプロンプト")
        assert "English" in result

    def test_system_prompt_contains_all_blocks(self) -> None:
        """Validate the layered structure: identity, privacy, context, capabilities,
        constraints, tool-use directive, thinking mode.

        Block 4 was updated by the Domain 6 audit (2026-06-03): unbuilt capabilities
        (Search, Code Agent, Cleaner) have been removed. The assertions for those
        names are now inverted — they must NOT appear in the prompt.
        """
        # Block 1 — Identity
        assert "BlarAI" in _DEFAULT_SYSTEM_PROMPT
        assert "privacy-first" in _DEFAULT_SYSTEM_PROMPT
        # Block 2 — Privacy mandate (post-air-gap since the 2026-07-02
        # web_search go-live: the ONE sanctioned channel is named; the
        # air-gap-era "fully offline" identity is retired — it made the
        # model refuse to use the live web_search tool, the go-live
        # ceremony's third fix)
        assert "PRIVACY MANDATE" in _DEFAULT_SYSTEM_PROMPT
        assert "air-gapped" not in _DEFAULT_SYSTEM_PROMPT, (
            "the air-gap-era identity teaches the model to refuse the live "
            "web_search channel"
        )
        assert "ONE sanctioned path" in _DEFAULT_SYSTEM_PROMPT
        assert "web_search" in _DEFAULT_SYSTEM_PROMPT
        assert "refuse" in _DEFAULT_SYSTEM_PROMPT  # fail-closed shape kept
        # Block 3 — Context Spotlighting (Layer 2.5)
        # Delimiters are NOT included literally in the system prompt to
        # prevent PGOV Stage 3 delimiter echo false positives.
        assert "GROUNDED CONTEXT" in _DEFAULT_SYSTEM_PROMPT
        assert "grounded-context" in _DEFAULT_SYSTEM_PROMPT or "grounded context" in _DEFAULT_SYSTEM_PROMPT.lower()
        assert "GROUNDED_CONTEXT_BEGIN" not in _DEFAULT_SYSTEM_PROMPT, (
            "Literal delimiter must not appear in system prompt — causes echo"
        )
        # Block 4 — Capability scope (Domain 6 prune, 2026-06-03)
        # Unbuilt subsystems must NOT be advertised to the model.
        assert "CAPABILITIES" in _DEFAULT_SYSTEM_PROMPT
        assert "Code Agent" not in _DEFAULT_SYSTEM_PROMPT, (
            "'Code Agent' is unbuilt — must not be advertised in the system prompt"
        )
        # Search became a BUILT capability at #719 (search_knowledge +
        # web_search are in tools._REGISTRY + TOOL_CALL_ALLOWLIST), so the
        # Domain-6 posture now REQUIRES advertising it — the assertion flipped
        # exactly as TestSystemPromptCapabilityScope's docstring prescribed
        # ("must be updated when a capability is actually built and wired").
        assert "search_knowledge" in _DEFAULT_SYSTEM_PROMPT, (
            "Built tool 'search_knowledge' (#719) must be advertised"
        )
        assert "web_search" in _DEFAULT_SYSTEM_PROMPT, (
            "Built tool 'web_search' (#719) must be advertised"
        )
        assert "Cleaner" not in _DEFAULT_SYSTEM_PROMPT, (
            "'Cleaner' is unbuilt — must not be advertised in the system prompt"
        )
        # Block 4.5 — Tool governance (ADR-023 Am.4 #723 / #726): the model must
        # not adjudicate tool permissions or imitate a prior /trust refusal (the
        # live-verify chat-poisoning fix). Regression-lock the load-bearing shape.
        assert "TOOL GOVERNANCE" in _DEFAULT_SYSTEM_PROMPT
        assert "Never refuse to use a tool" in _DEFAULT_SYSTEM_PROMPT
        assert "never tell the user to type /trust" in _DEFAULT_SYSTEM_PROMPT
        # Block 4.6 — reading noisy search results (accuracy nudge).
        assert "READING SEARCH RESULTS" in _DEFAULT_SYSTEM_PROMPT
        # Block 5 — Operational constraints
        assert "CONSTRAINTS" in _DEFAULT_SYSTEM_PROMPT
        assert "English" in _DEFAULT_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Test: Thinking Mode (ADR-012 §2.4)
# ---------------------------------------------------------------------------


class TestThinkingMode:
    """ADR-012 §2.4: AO thinking mode — stop tokens, strip, streamer.

    Qwen3 emits reasoning wrapped in literal ``<think>`` / ``</think>``
    tags (angle brackets — verified against live model output and the
    Policy Agent's QWEN3_THINK_START_TOKEN_ID). These tests must use that
    exact tag form: an earlier pipe-delimited tag form was fictional and
    let a real stripping bug pass green (test-as-oracle drift).
    """

    def test_system_prompt_no_think_default(self) -> None:
        """AO system prompt must contain /no_think as the default thinking mode.

        ADR-012 §2.4 (updated): AO defaults to non-thinking mode for low-latency
        conversational responses. Users may append /think per-turn for complex
        reasoning tasks. Think blocks are stripped before UI delivery.
        /think activation is UAT-gated — production signoff requires non-dev
        UAT on a live production-candidate system.
        """
        assert "/no_think" in _DEFAULT_SYSTEM_PROMPT

    def test_qwen3_im_end_constant(self) -> None:
        assert QWEN3_IM_END_TOKEN_ID == 151_645


# ---------------------------------------------------------------------------
# Test: Domain 6 security hardening — system prompt capability scope
# ---------------------------------------------------------------------------


class TestSystemPromptCapabilityScope:
    """Domain 6 audit (2026-06-03): system prompt must not advertise unbuilt tools.

    Telling the model it can 'dispatch to Search, Code Agent, Cleaner' causes it
    to emit <tool_call> tags for those names. Those tags either (a) pass an
    over-broad PGOV allowlist (phantom approval surface) or (b) are caught as
    PGOV violations and suppress valid responses. Neither is acceptable.

    TEETH: These tests fail if an unbuilt tool name is re-introduced into the
    system prompt. They must be updated when a capability is actually built and
    wired into tools._REGISTRY + TOOL_CALL_ALLOWLIST.
    """

    # "Search" was removed from this list at #719: search_knowledge +
    # web_search are now BUILT and wired to tools._REGISTRY +
    # TOOL_CALL_ALLOWLIST, so advertising them is the required posture (this
    # class's docstring prescribed exactly this update when a capability is
    # built). The remaining names stay unbuilt and stay banned.
    _UNBUILT_CAPABILITY_NAMES: list[str] = [
        "Code Agent",
        "Cleaner",
        "substrate_query",
        "calendar_read",
        "calendar_write",
        "note_create",
        "note_search",
        "health_log",
        "smart_home_control",
    ]

    def test_built_search_tools_advertised_in_system_prompt(self) -> None:
        """#719 flipped the search assertion: search_knowledge and web_search
        are BUILT (registry + allowlist), so the model MUST be told about them
        — an advertised-but-refused tool degrades gracefully via its
        deterministic notice; an unadvertised tool is unreachable capability."""
        from services.assistant_orchestrator.src.pgov import TOOL_CALL_ALLOWLIST
        from services.assistant_orchestrator.src.tools import _REGISTRY

        for built_search_tool in ("search_knowledge", "web_search"):
            assert built_search_tool in _REGISTRY
            assert built_search_tool in TOOL_CALL_ALLOWLIST
            assert built_search_tool in _DEFAULT_SYSTEM_PROMPT, (
                f"Built tool '{built_search_tool}' (#719) must be advertised "
                "in the system prompt."
            )

    def test_unbuilt_code_agent_not_in_system_prompt(self) -> None:
        """'Code Agent' must not appear in the system prompt."""
        assert "Code Agent" not in _DEFAULT_SYSTEM_PROMPT, (
            "Unbuilt capability 'Code Agent' is advertised in the system prompt."
        )

    def test_unbuilt_cleaner_not_in_system_prompt(self) -> None:
        """'Cleaner' must not appear in the system prompt."""
        assert "Cleaner" not in _DEFAULT_SYSTEM_PROMPT, (
            "Unbuilt capability 'Cleaner' is advertised in the system prompt."
        )

    def test_system_prompt_tool_use_block_lists_only_built_tools(self) -> None:
        """The TOOL USE block in the system prompt must enumerate only built tools.

        All four registry keys must appear in the prompt's TOOL USE section.
        No unbuilt tool names may appear anywhere in the prompt.
        """
        from services.assistant_orchestrator.src.tools import _REGISTRY

        # Every built tool must be mentioned.
        for tool_name in _REGISTRY:
            assert tool_name in _DEFAULT_SYSTEM_PROMPT, (
                f"Built tool '{tool_name}' is not mentioned in the system prompt. "
                "The model needs to know which tools it can invoke."
            )

        # No unbuilt tool name may appear.
        for unbuilt in self._UNBUILT_CAPABILITY_NAMES:
            assert unbuilt not in _DEFAULT_SYSTEM_PROMPT, (
                f"Unbuilt capability name '{unbuilt}' found in system prompt. "
                "This must not be advertised to the model."
            )

    def test_thinking_block_stripped_from_output(self) -> None:
        """Complete thinking blocks removed from final text."""
        engine = _make_mock_engine()
        engine._pipeline.generate.return_value = (
            "<think>internal reasoning</think>The actual answer"
        )
        config = GenerationConfig(do_sample=False)
        result = engine.generate(input_ids=[1], config=config)
        assert result.error is None
        assert "<think>" not in result.text
        assert "</think>" not in result.text
        assert "internal reasoning" not in result.text
        assert "actual answer" in result.text

    def test_unclosed_thinking_block_stripped(self) -> None:
        """Unclosed trailing thinking block stripped."""
        engine = _make_mock_engine()
        engine._pipeline.generate.return_value = (
            "<think>reasoning without close tag"
        )
        config = GenerationConfig(do_sample=False)
        result = engine.generate(input_ids=[1], config=config)
        assert "<think>" not in result.text
        assert "reasoning without close" not in result.text

    def test_no_thinking_block_passthrough(self) -> None:
        """Output without thinking blocks passes through unchanged."""
        engine = _make_mock_engine()
        engine._pipeline.generate.return_value = "plain answer text"
        config = GenerationConfig(do_sample=False)
        result = engine.generate(input_ids=[1], config=config)
        assert result.error is None
        assert "plain answer text" in result.text

    def test_streamer_suppresses_thinking_callback(self) -> None:
        """Stream callback must NOT receive thinking tokens."""
        engine = _make_mock_engine()
        received: list[str] = []

        def callback(chunk: str) -> bool:
            received.append(chunk)
            return True

        def fake_generate(prompt: str, gen_config: object, streamer_fn: object = None) -> str:
            if callable(streamer_fn):
                streamer_fn("<think>")
                streamer_fn("reasoning step 1")
                streamer_fn("reasoning step 2")
                streamer_fn("</think>")
                streamer_fn("visible answer")
            return "<think>reasoning step 1reasoning step 2</think>visible answer"

        engine._pipeline.generate.side_effect = fake_generate
        config = GenerationConfig(do_sample=False)
        result = engine.generate_text(
            "test prompt",
            config=config,
            stream_callback=callback,
        )
        assert "visible answer" in result.text
        assert "<think>" not in result.text
        # Verify callback received only visible content
        assert any("visible answer" in c for c in received)
        assert not any("<think>" in c for c in received)
        assert not any("reasoning step" in c for c in received)


# ---------------------------------------------------------------------------
# Shared-pipeline attach path (ADR-012 §2.1, Phase 2 refactor)
# ---------------------------------------------------------------------------


def _write_ao_manifest(digests: dict[str, str]) -> str:
    """Write a manifest JSON and return the path."""
    data = {"version": "1.0.0", "digests": digests}
    fd, path = tempfile.mkstemp(suffix=".json")
    os.write(fd, json.dumps(data).encode("utf-8"))
    os.close(fd)
    return path


class TestSharedPipelinePath:
    """When a SharedInferencePipeline is injected, load_model() attaches it
    instead of compiling a standalone LLMPipeline. The default (None) keeps
    the standalone behaviour exercised by the rest of this file.
    """

    def test_load_model_with_shared_pipeline_skips_compile(
        self, tmp_path: Path,
    ) -> None:
        """Injecting a shared pipeline must skip ov_genai.LLMPipeline()."""
        xml_path = tmp_path / "openvino_model.xml"
        bin_path = tmp_path / "openvino_model.bin"
        xml_path.write_text("<xml>")
        bin_content = b"shared-path AO weights"
        bin_path.write_bytes(bin_content)

        digest = hashlib.sha256(bin_content).hexdigest()
        manifest_path = _write_ao_manifest({"openvino_model.bin": digest})

        shared = MagicMock(name="SharedInferencePipeline")

        try:
            engine = OrchestratorGPUInference(
                model_dir=str(tmp_path),
                device="CPU",
                manifest_path=manifest_path,
                draft_model_dir=str(tmp_path),
                shared_pipeline=shared,
            )
            with patch(
                "services.assistant_orchestrator.src.gpu_inference._OV_GENAI_AVAILABLE",
                True,
            ), patch(
                "services.assistant_orchestrator.src.gpu_inference.ov_genai",
            ) as mock_ov_genai:
                result = engine.load_model()

            assert result is True
            assert engine.loaded is True
            assert engine.speculative_decoding_active is True
            # Crux: the standalone compile path did NOT run.
            mock_ov_genai.LLMPipeline.assert_not_called()
            mock_ov_genai.draft_model.assert_not_called()
            # AO's pipeline attribute points at the injected wrapper.
            assert engine._pipeline is shared
            # Integrity check still ran — defence in depth at the consumer.
            assert engine.integrity_result is not None
            assert engine.integrity_result.verified is True
        finally:
            os.unlink(manifest_path)
