"""
OpenVINO 2026.2 upgrade knobs — regression tests (A1 + A3)
==========================================================
Fast, deterministic unit tests (no real models, no GPU) for the two
config knobs added with the OpenVINO / OpenVINO-GenAI 2026.2 upgrade:

  A1 — ``min_p`` nucleus-sampling floor for the Assistant Orchestrator
       (GenAI 2026.2, PR #3752). Default ``0.0`` = disabled, so the greedy
       production default is byte-identical to the pre-2026.2 behaviour.

  A3 — ``KV_CACHE_PRECISION`` GPU KV-cache quantization hint threaded into
       ``build_shared_pipeline``. Default-unset = the runtime default (FP16),
       so the unset path is byte-identical to today.

These lock the wiring (dataclass field → ov_genai config; build param →
LLMPipeline property) and the critical default-off invariant. The mocking
style mirrors ``test_gpu_inference.py`` (patch the module-level ``ov_genai``).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from unittest.mock import patch

import pytest

from services.assistant_orchestrator.src.entrypoint import (
    AssistantOrchestratorEntrypointConfig,
)
from services.assistant_orchestrator.src.gpu_inference import (
    GenerationConfig,
    OrchestratorGPUInference,
)
from shared.inference.shared_pipeline import build_shared_pipeline


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _FakeOvGenConfig:
    """Stand-in for ``ov_genai.GenerationConfig``.

    Exposes ``min_p`` (and the other sampler attributes) so the
    ``hasattr``-guards in ``_build_generation_config`` fire. A plain mutable
    object — the remaining attributes (``max_new_tokens``, ``do_sample``,
    ``stop_token_ids``, …) are assigned dynamically just like the real one.
    """

    def __init__(self) -> None:
        self.temperature: float = 0.0
        self.top_k: int = 0
        self.top_p: float = 1.0
        self.repetition_penalty: float = 1.0
        self.min_p: float = 0.0


def _make_model_dir(base: Path, name: str) -> Path:
    """Create a minimal OV model dir so the file-existence guards pass."""
    model_dir = base / name
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "openvino_model.xml").write_text("<xml/>")
    (model_dir / "openvino_model.bin").write_bytes(b"weights")
    return model_dir


# ---------------------------------------------------------------------------
# A1 — min_p sampling knob (Assistant Orchestrator)
# ---------------------------------------------------------------------------


class TestMinPKnob:
    """A1: the ``min_p`` field exists, defaults off, and is wired into the
    OpenVINO GenAI generation config."""

    def test_generation_config_has_min_p_default_zero(self) -> None:
        """``GenerationConfig.min_p`` exists and defaults to 0.0 (disabled)."""
        assert GenerationConfig().min_p == pytest.approx(0.0)

    def test_build_generation_config_sets_min_p_from_config(self) -> None:
        """``_build_generation_config`` copies ``config.min_p`` onto the
        ov_genai gen_config (when the runtime exposes the attribute)."""
        engine = OrchestratorGPUInference(model_dir="/mock")
        fake_gen_config = _FakeOvGenConfig()

        with patch(
            "services.assistant_orchestrator.src.gpu_inference.ov_genai"
        ) as mock_ov_genai:
            mock_ov_genai.GenerationConfig.return_value = fake_gen_config
            engine._build_generation_config(
                max_new_tokens=128,
                config=GenerationConfig(min_p=0.1, do_sample=True),
            )

        assert fake_gen_config.min_p == pytest.approx(0.1)

    def test_build_generation_config_default_min_p_is_zero(self) -> None:
        """The default config leaves ``min_p`` at 0.0 on the gen_config —
        the greedy production default is unchanged."""
        engine = OrchestratorGPUInference(model_dir="/mock")
        fake_gen_config = _FakeOvGenConfig()

        with patch(
            "services.assistant_orchestrator.src.gpu_inference.ov_genai"
        ) as mock_ov_genai:
            mock_ov_genai.GenerationConfig.return_value = fake_gen_config
            engine._build_generation_config(
                max_new_tokens=128,
                config=GenerationConfig(),
            )

        assert fake_gen_config.min_p == pytest.approx(0.0)

    def test_entrypoint_config_has_generation_min_p_default_zero(self) -> None:
        """``AssistantOrchestratorEntrypointConfig.generation_min_p`` exists
        with a 0.0 default (resolved from ``[generation].min_p``)."""
        fields_by_name = {
            f.name: f
            for f in dataclasses.fields(AssistantOrchestratorEntrypointConfig)
        }
        assert "generation_min_p" in fields_by_name
        assert fields_by_name["generation_min_p"].default == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# A3 — KV_CACHE_PRECISION knob (shared LLMPipeline)
# ---------------------------------------------------------------------------


class TestKvCachePrecisionKnob:
    """A3: ``kv_cache_precision`` is threaded into the LLMPipeline target
    config ONLY when set — unset/empty is byte-identical to today (FP16)."""

    def test_set_value_passes_property(self, tmp_path: Path) -> None:
        """A non-empty value adds ``KV_CACHE_PRECISION`` to the LLMPipeline
        kwargs."""
        target_dir = _make_model_dir(tmp_path, "target")
        draft_dir = _make_model_dir(tmp_path, "draft")

        with patch(
            "shared.inference.shared_pipeline._OV_GENAI_AVAILABLE", True
        ), patch(
            "shared.inference.shared_pipeline.ov_genai"
        ) as mock_ov_genai:
            result = build_shared_pipeline(
                model_dir=target_dir,
                draft_model_dir=draft_dir,
                enable_prefix_caching=True,
                device="GPU",
                kv_cache_precision="u8",
            )

        assert result.ok is True
        mock_ov_genai.LLMPipeline.assert_called_once()
        call_kwargs = mock_ov_genai.LLMPipeline.call_args.kwargs
        assert call_kwargs.get("KV_CACHE_PRECISION") == "u8"

    def test_none_default_omits_property(self, tmp_path: Path) -> None:
        """The default (``None``) leaves ``KV_CACHE_PRECISION`` ABSENT —
        byte-identical to the pre-2026.2 build."""
        target_dir = _make_model_dir(tmp_path, "target")
        draft_dir = _make_model_dir(tmp_path, "draft")

        with patch(
            "shared.inference.shared_pipeline._OV_GENAI_AVAILABLE", True
        ), patch(
            "shared.inference.shared_pipeline.ov_genai"
        ) as mock_ov_genai:
            result = build_shared_pipeline(
                model_dir=target_dir,
                draft_model_dir=draft_dir,
                enable_prefix_caching=True,
                device="GPU",
            )

        assert result.ok is True
        mock_ov_genai.LLMPipeline.assert_called_once()
        call_kwargs = mock_ov_genai.LLMPipeline.call_args.kwargs
        assert "KV_CACHE_PRECISION" not in call_kwargs

    def test_empty_string_treated_as_unset(self, tmp_path: Path) -> None:
        """An empty string is falsy → treated as unset (the launcher passes
        ``""`` through as 'leave default'); the property stays ABSENT."""
        target_dir = _make_model_dir(tmp_path, "target")
        draft_dir = _make_model_dir(tmp_path, "draft")

        with patch(
            "shared.inference.shared_pipeline._OV_GENAI_AVAILABLE", True
        ), patch(
            "shared.inference.shared_pipeline.ov_genai"
        ) as mock_ov_genai:
            result = build_shared_pipeline(
                model_dir=target_dir,
                draft_model_dir=draft_dir,
                enable_prefix_caching=True,
                device="GPU",
                kv_cache_precision="",
            )

        assert result.ok is True
        mock_ov_genai.LLMPipeline.assert_called_once()
        call_kwargs = mock_ov_genai.LLMPipeline.call_args.kwargs
        assert "KV_CACHE_PRECISION" not in call_kwargs
