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


# The closed EMPTY reasoning block: the Qwen3.5/3.6 render of "do not think".
# Its absence is not neutrality — see the comment in ``generate`` below and the
# FIELD_NOTES entry "Qwen3.5/3.6 chat templates open a <think> block unless you
# say otherwise" (2026-09-22).
EMPTY_THINK_BLOCK = "<think>\n\n</think>\n\n"


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
    on_first_token: Callable[[str], None] | None = None,
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
        on_first_token: Optional observer receiving the FIRST generated chunk
            of every generation. Opt-in because it attaches a streamer, which
            the plain parity path does not need. Pass it when a run must
            evidence that reasoning was suppressed: a ``no_think_tags`` rubric
            pass is NOT such evidence, since a well-formed hidden block is
            stripped before scoring (#1618, lesson 369).

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

    # WARM-UP — not a nicety, a CONTROL (#930, measured 2026-09-22).
    # On this VLMPipeline the FIRST generation after a load produces different
    # text from every subsequent one, for a byte-identical greedy prompt. The
    # effect is not noise: probing one case 4x across 2 independent loads gave
    # exactly 2 distinct outputs, with the split always at generation 1 vs 2+,
    # and the two loads agreed with each other byte for byte
    # (`docs/performance/probe_35b_greedy_determinism_*.json`).
    #
    # It flipped a SECURITY verdict. On an injection case the cold answer
    # refused the embedded instruction but quoted the canary while explaining
    # the refusal; the warm answer refused without quoting it. The rubric's
    # `must_not_contain` scores those opposite ways, so whichever case happened
    # to land first after a load was judged under different conditions than the
    # rest of the set.
    #
    # One discarded generation costs a few seconds and removes the variable.
    # The throughput benchmarks have always done this (`--warmup 2`); the eval
    # path never did, which is why nobody had seen it.
    try:
        _warm_cfg = ov_genai.GenerationConfig()
        _warm_cfg.max_new_tokens = 8
        _warm_cfg.do_sample = False
        _warm_cfg.apply_chat_template = False
        pipe.generate(
            wrap_chatml(system_prompt, "warmup") + EMPTY_THINK_BLOCK,
            generation_config=_warm_cfg,
        )
        logger.info("Eval VLM generator: warm-up generation discarded (#930).")
    except Exception as exc:  # noqa: BLE001 — logged, never silent
        # Fail-soft on the WARM-UP only: a failure here does not invalidate the
        # scored run, but it does mean the first scored case is cold, and a
        # reader of the results must be told rather than left to assume.
        logger.warning(
            "Eval VLM generator: WARM-UP FAILED (%s: %s) — the first scored case "
            "will run cold, and on this pipeline a cold generation can differ "
            "from a warm one. Treat the first case's verdict with suspicion.",
            type(exc).__name__,
            exc,
        )

    def generate(composed_context: str) -> str:
        # #1618 / lesson 369 — BOTH lines below are load-bearing, and the bug
        # they fix cost a two-month false verdict on this model.
        #
        # The Qwen3.5/3.6 chat template has NO neutral setting: it emits the
        # closed empty block only when ``enable_thinking`` is defined AND
        # false, and a BARE OPENING ``<think>\n`` in every other case. Leaving
        # the flag unset is therefore not "no opinion", it is an instruction to
        # start reasoning. Until 2026-09-22 this function left
        # ``apply_chat_template`` at its default True on an ALREADY hand-built
        # ChatML string, so the template wrapped it a second time and appended
        # that bare opener to all 40 golden prompts — the eval opened a
        # reasoning block and then scored the model for continuing it.
        #
        # The fix is the production recipe, byte-identical to what the Policy
        # Agent ships on the 14B today
        # (``policy_agent/src/gpu_inference.py`` ``_build_prompt``): carry the
        # closed empty block in the prompt ourselves, and forbid the template
        # from touching it.
        prompt = wrap_chatml(system_prompt, composed_context) + EMPTY_THINK_BLOCK
        cfg = ov_genai.GenerationConfig()
        cfg.max_new_tokens = max_new_tokens
        cfg.do_sample = False  # greedy / temperature-0 equivalent — reproducible
        cfg.apply_chat_template = False  # the prompt IS the template output

        first_chunk: list[str] = []

        def _streamer(chunk: str) -> Any:
            # The first generated token is the ONLY sound witness that thinking
            # was suppressed: a rubric check for hidden-block markers cannot
            # see it, because a WELL-FORMED ``<think>…</think>`` in the output
            # is stripped before scoring and passes silently. VLMDecodedResults
            # exposes no raw token ids, so the streamer's first chunk stands in
            # — the probe that established this proves the equivalence first
            # (``encode("<think>") == [248068]``, ``decode([248068])`` round
            # trips), and ``scripts/probe_35b_thinking_control.py`` is the
            # reference implementation.
            if not first_chunk:
                first_chunk.append(chunk)
            return ov_genai.StreamingStatus.RUNNING

        try:
            if on_first_token is not None:
                result = pipe.generate(
                    prompt, generation_config=cfg, streamer=_streamer
                )
            else:
                result = pipe.generate(prompt, generation_config=cfg)
        except Exception as exc:  # noqa: BLE001 — fail-closed on a generation error
            raise RuntimeError(f"VLM generation failed: {exc}") from exc

        if on_first_token is not None:
            on_first_token(first_chunk[0] if first_chunk else "")
        return str(result)

    return generate
