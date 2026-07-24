"""
Eval Harness — VLMPipeline Arm of the Hardware Model-Target Override (#931)
==========================================================================
The default hardware eval path drives its target through an OpenVINO GenAI
``LLMPipeline`` (the production ``OrchestratorGPUInference`` /
``PolicyGPUInference`` loaders, Qwen3-14B contract). When a ``--model-dir``
override declares the ``multimodal-vlm`` capability (see
``evals/model_target.py``), the target is a natively multimodal checkpoint that
OpenVINO GenAI serves through a ``VLMPipeline`` instead — so the hardware
generator must construct THAT pipeline class. This module is that arm.

Text-only generation is faithful to ``scripts/benchmark_vlm_text_inference.py``
and the 2026-07 head-to-head probes: ``ov_genai.VLMPipeline(dir, "GPU")``,
greedy decode (temperature-0 determinism), no image tensors. The BlarAI
production system prompt is applied via the SAME manual Qwen ChatML wrapping the
AO's ``_format_chat_prompt`` falls back to — imported at call time, never copied
— so a parity run measures the real injection geometry.

Fail-closed: ``openvino_genai`` absent, a model-load failure, or a generation
error raises ``RuntimeError`` — a silent empty answer is never scored as a real
one.

Ceremony-calibration note (out of scope for #931; belongs to the #930 hardware
ceremony): a ``VLMPipeline`` may re-apply its own chat template to a plain
string. Whether the manual ChatML wrap here composes correctly with the 35B-A3B
tokenizer's template, or should instead be passed as structured chat, is
validated against the REAL model at the ceremony. The mechanism (selecting and
loading the VLMPipeline) is what #931 delivers; the exact prompt framing is a
one-line change here once the ceremony observes the real model.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


def wrap_chatml(system_prompt: str, user_content: str) -> str:
    """Wrap ``user_content`` in manual Qwen ChatML with ``system_prompt``.

    Byte-identical to ``OrchestratorGPUInference._format_chat_prompt``'s
    tokenizer-less fallback, so the VLM parity run reads the same system/user
    framing the 14B ``LLMPipeline`` path builds.
    """
    return (
        f"<|im_start|>system\n{system_prompt}<|im_end|>\n"
        f"<|im_start|>user\n{user_content}<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )


def build_vlm_composed_generator(
    model_dir: Path,
    *,
    max_new_tokens: int,
    system_prompt: str,
    device: str = "GPU",
) -> Callable[[str], str]:
    """Build a VLMPipeline-backed text generator (Arc 140V required).

    Loads the real ``ov_genai.VLMPipeline`` once and returns a callable mapping
    a COMPOSED context string (the answer-quality suite's production grounding
    shape) to the RAW generation text — the same contract as the LLM path's
    generator, so the suite applies the identical production think-strip and
    rubric afterwards. Greedy decoding (``do_sample=False``) for reproducibility.

    Args:
        model_dir: The VLM model directory (verified against the declared
            capability by ``resolve_model_target`` before this is reached).
        max_new_tokens: Generation cap (the suite's per-answer budget).
        system_prompt: The production system prompt to apply (imported by the
            caller from the AO, never copied).
        device: OpenVINO device string (default ``"GPU"``).

    Raises:
        FileNotFoundError: If the model directory is absent.
        RuntimeError: If ``openvino_genai`` is unavailable, the pipeline fails
            to load, or a generation errors (fail-closed).
    """
    if not model_dir.exists():
        raise FileNotFoundError(f"VLM model directory not found: {model_dir}")

    try:
        import openvino_genai as ov_genai  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "OpenVINO GenAI is not available — cannot load a VLMPipeline for the "
            "eval hardware run (fail-closed)."
        ) from exc

    try:
        pipe: Any = ov_genai.VLMPipeline(str(model_dir), device)
    except Exception as exc:  # noqa: BLE001 — surface the load failure fail-closed
        raise RuntimeError(f"VLMPipeline failed to load from {model_dir}: {exc}") from exc

    logger.info("Eval VLM generator: loaded %s on %s", model_dir.name, device)

    def generate(composed_context: str) -> str:
        prompt = wrap_chatml(system_prompt, composed_context)
        cfg = ov_genai.GenerationConfig()
        cfg.max_new_tokens = max_new_tokens
        cfg.do_sample = False  # greedy / temperature-0 equivalent — reproducible
        try:
            result = pipe.generate(prompt, generation_config=cfg)
        except Exception as exc:  # noqa: BLE001 — fail-closed on a generation error
            raise RuntimeError(f"VLM generation failed: {exc}") from exc
        return str(result)

    return generate
