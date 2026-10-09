"""
Eval Harness — MULTI-TURN conversation suite (#1621)
=====================================================
Every other model-in-the-loop suite in this repo is SINGLE TURN. `answer_quality`
opens a fresh session, adds one user turn, scores the reply, and throws the
session away — forty times. Nothing anywhere asks a second question.

That blind spot let a model reach live validation while being unusable as a
chat assistant. The Qwen3.6-35B-A3B scored 38/40 on `answer_quality` and then,
on the operator's FIRST real prompt, answered a question from earlier in the
conversation instead of the one he had just asked. The suite could not have
caught it: a model that answers the wrong turn scores perfectly on a set that
only ever has one.

This suite exists so that class of failure is measurable. It covers both
directions, which is the point:

- **History must not HIJACK the answer** (`conv-stale-*`, `conv-topic-*`,
  `conv-inj-*`, `conv-nocarry-*`). An earlier turn — especially one left
  unanswered — must not be answered in place of the current question.
- **History must still be USED** (`conv-ref-*`, `conv-instr-*`). A model that
  simply ignores everything before the last message would sail through the
  first group. These are the positive controls that stop that (lesson 222:
  negative controls catch false green; only a positive control catches false
  red, and a suite made only of "must not" cases measures nothing).

Scoring, the rubric, the production think-strip and the tool-call handling are
reused verbatim from `answer_quality` — this suite differs only in how the
CONTEXT is built, via `compose_conversation`, which hands the model REAL turns
instead of a flattened "role: content" transcript.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from evals.loader import GoldenDataError, load_golden
from evals.model_target import ModelTarget
from evals.suites.answer_quality import (
    _score_case,
    _tool_call_result,
    _validate_case,
    brain_uses_real_turns,
    compose_for_brain,
    compose_with_manager,
    is_tool_call_only,
    strip_for_display,
)
from evals.types import CaseResult, CaseStatus, SuiteReport

SUITE_NAME = "conversation"


def golden_path_for(golden_dir: Path | None = None) -> Path:
    from evals.loader import GOLDEN_DIR

    return (golden_dir or GOLDEN_DIR) / f"{SUITE_NAME}.jsonl"


def run_suite(
    golden_file: Path | None = None,
    *,
    include_hardware: bool = False,
    hardware_generator: Callable[..., str] | None = None,
    model_target: ModelTarget | None = None,
) -> SuiteReport:
    """Run the multi-turn conversation suite.

    ``hardware_generator`` takes ``(prompt, prior_turns)`` — this suite cannot
    use the single-argument generator the other suites share, because for a
    brain that ships real turns the history travels as STRUCTURE rather than
    being folded into the prompt string.

    WHICH SHAPE IS NOT THIS SUITE'S CHOICE. The entrypoint builds real turns
    only for a multimodal brain; the 14B gets the flattened transcript as its
    prompt. Measuring the incumbent on the other shape made one arm of a
    two-arm comparison a configuration that does not ship (#1622, lesson 372),
    so the gate is mirrored and the shape is recorded on every result.
    """
    path = golden_file or golden_path_for()
    cases = load_golden(path)
    report = SuiteReport(suite=SUITE_NAME)
    generator = hardware_generator

    # The shape THIS BRAIN ships, read from the model dir, never assumed.
    use_real_turns = brain_uses_real_turns(
        getattr(model_target, "model_dir", None) if model_target else None
    )

    for case in cases:
        problem = _validate_case(case)
        if problem is not None:
            raise GoldenDataError(f"{path.name} case {case.get('id')}: {problem}")

        case_id = str(case["id"])
        description = str(case.get("description", ""))

        if case["mode"] != "model":
            report.results.append(
                CaseResult(
                    case_id=case_id,
                    status=CaseStatus.ERROR,
                    description=description,
                    detail="conversation cases are model-mode only",
                )
            )
            continue

        if not include_hardware:
            report.results.append(
                CaseResult(
                    case_id=case_id,
                    status=CaseStatus.SKIPPED_HARDWARE,
                    description=description,
                    expected=case["checks"],
                    detail=(
                        "multi-turn model case; requires --include-hardware "
                        "on the Arc 140V"
                    ),
                )
            )
            continue

        try:
            if generator is None:
                generator = _build_multiturn_generator(model_target)
            manager, session_id = compose_with_manager(
                case.get("prior_turns"),
                str(case["prompt"]),
                case.get("grounded_context"),
            )
            prior, current = compose_for_brain(
                manager, session_id, use_real_turns=use_real_turns
            )
            raw = generator(current, prior or [])
            answer = strip_for_display(raw)
            if is_tool_call_only(raw, answer):
                report.results.append(_tool_call_result(case, raw))
                continue
            report.results.append(_score_case(case, answer))
        except Exception as exc:  # noqa: BLE001 — scoring must not abort the run
            report.results.append(
                CaseResult(
                    case_id=case_id,
                    status=CaseStatus.ERROR,
                    description=description,
                    expected=case["checks"],
                    detail=f"generation/harness error: {exc}",
                )
            )

    return report


def _build_multiturn_generator(
    target: ModelTarget | None,
) -> Callable[[str, list[dict[str, str]]], str]:
    """A generator that carries prior turns the way THIS BRAIN ships.

    The entrypoint builds ``prior_turns`` only for a multimodal brain; the 14B
    receives the flattened transcript, and the entrypoint says in its own
    comment that changing that is a quality change belonging to the operator.
    Passing real turns unconditionally measured the incumbent arm of a two-arm
    comparison on a configuration that does not ship (#1622, lesson 372), so
    the gate is mirrored here, read from the model directory, never assumed.
    """
    from evals.suites.answer_quality import (
        _EVAL_MAX_NEW_TOKENS,
        _default_system_prompt,
        default_model_dir,
        production_tool_call_grammar_posture,
    )
    from services.assistant_orchestrator.src.gpu_inference import (
        GenerationConfig,
        OrchestratorGPUInference,
        _brain_is_multimodal,
    )

    resolved = target.model_dir if target is not None else default_model_dir()
    if not resolved.exists():
        raise FileNotFoundError(f"AO model directory not found: {resolved}")
    ships_real_turns = bool(_brain_is_multimodal(resolved))
    # A MULTIMODAL brain cannot be served by the standalone construction: that
    # path builds an LLMPipeline and every generation dies with "Port for
    # tensor name input_ids was not found" (#1625). load_model() ATTACHES a
    # pipeline when one is supplied, so build it the way the launcher does.
    shared = None
    if target is not None and target.uses_cb_engine:
        # #1663: a continuous-batching engine arm supplies the attached pipeline.
        from evals.cb_pipeline import get_engine_pipeline

        shared = get_engine_pipeline(resolved, target.engine)
    elif ships_real_turns:
        from shared.inference.shared_pipeline import build_shared_pipeline

        built = build_shared_pipeline(
            model_dir=resolved,
            draft_model_dir=None,  # VLMPipeline has no speculative decoding
            enable_prefix_caching=True,
            device="GPU",
            target_manifest_path=resolved / "manifest.json",
            draft_manifest_path=None,
        )
        if not built.ok:
            raise RuntimeError(
                f"shared pipeline build failed for {resolved}: {built.error}"
            )
        shared = built.pipeline

    inference = OrchestratorGPUInference(
        model_dir=str(resolved),
        speculative_decoding_enabled=(
            target.speculative_decode if target is not None else True
        ),
        shared_pipeline=shared,
    )
    if not inference.load_model():
        raise RuntimeError(f"AO model failed to load from {resolved}")

    # DISCARD THE FIRST GENERATION AFTER A LOAD. `evals/hardware_pipeline.py`
    # carries this control with a comment recording that the cold generation
    # once FLIPPED A SECURITY VERDICT: on an injection case the cold answer
    # quoted the injected text while explaining the refusal, and the warm one
    # refused without quoting it. The control was wired into one suite of three
    # - this is the second; the throughput benchmarks have always done it.
    # Cheap (8 tokens) and unconditional, because a warm-up you have to
    # remember to enable is not a control.
    try:
        inference.generate_text(
            "Say OK.",
            max_new_tokens=8,
            config=GenerationConfig(max_new_tokens=8, do_sample=False),
            system_prompt=_default_system_prompt(),
            prior_turns=None,
        )
    except Exception as exc:  # noqa: BLE001 - a failed warm-up must not abort a run
        logging.getLogger(__name__).warning(
            "Eval warm-up generation failed (%s); the FIRST scored case may be "
            "judged under cold-start conditions.",
            exc,
        )

    def generate(prompt: str, prior_turns: list[dict[str, str]]) -> str:
        # A brain that does not ship real turns must not be handed them here.
        turns = prior_turns if ships_real_turns else None
        result = inference.generate_text(
            prompt,
            max_new_tokens=_EVAL_MAX_NEW_TOKENS,
            config=GenerationConfig(
                max_new_tokens=_EVAL_MAX_NEW_TOKENS,
                do_sample=False,
                tool_call_grammar=production_tool_call_grammar_posture(),
            ),
            system_prompt=_default_system_prompt(),
            prior_turns=turns,
        )
        if result.error:
            raise RuntimeError(f"generation failed: {result.error}")
        return result.text

    return generate
