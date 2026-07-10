"""
Eval Suite — AO Conversational Answer Quality
==============================================
Scores the Assistant Orchestrator's free-text answers — the answer AS THE
USER SEES IT — against a deterministic rubric (evals/rubric.py): identity,
stable facts, instruction-following format, think-tag / system-prompt /
datamark leakage, grounded-context fidelity, injection resistance, and
uncertainty honesty.

Two case modes (the ``mode`` field of each golden case):

  offline — the case carries a ``fixture_response`` (a recorded or
      representative model output); the rubric scores it after the SAME
      production think-strip the live path uses. Runs anywhere, including
      CI. HONESTY NOTE: offline cases measure the RUBRIC ENGINE and the
      strip wiring, and pin exemplar known-good answers — they do NOT
      measure the live model. Only ``mode: "model"`` cases on hardware do.

  model — the case's ``prompt`` (plus an optional ``grounded_context``
      block, injected through the REAL ``ContextManager`` grounding path —
      datamarking, spotlighting delimiters, provenance tiers — exactly as
      production grounds retrieved content) is driven through the REAL AO
      generation path: ``OrchestratorGPUInference.generate_text`` on the
      Qwen3-14B / Arc 140V with the production system prompt and the
      production speculative-decode configuration, then stripped with the
      production ``_strip_hidden_blocks`` before scoring. These cases are
      SKIPPED unless ``include_hardware=True`` (a CI or builder run never
      loads the model).

Single-source-of-truth wiring (imports, never copies):
  * think-strip:      services.assistant_orchestrator.src.entrypoint
                      ``_strip_hidden_blocks`` — the same function the AO
                      applies before a generation is reused/displayed.
  * system prompt:    applied by ``generate_text`` itself (production
                      ``_format_chat_prompt`` / ``_DEFAULT_SYSTEM_PROMPT``);
                      the leak-check fragments are DERIVED from that
                      imported prompt (see evals/rubric.py).
  * grounding shape:  the REAL ``ContextManager`` (``create_session`` ->
                      ``add_grounded_context`` -> ``add_turn`` ->
                      ``trim_to_budget`` -> ``build_context``), mirroring
                      the entrypoint ``_handle_prompt`` flow.

Golden case schema (evals/golden/answer_quality.jsonl):
  {"id": "aq-fact-001", "description": "...", "category": "factual",
   "mode": "offline" | "model",
   "prompt": "...",                          # required for model mode
   "fixture_response": "...",                # required for offline mode
   "grounded_context": {"chunks": ["..."],   # optional (both modes' twins
                        "provenance": "untrusted_external"},  # document it)
   "checks": {...}}                          # see evals/rubric.py

What this suite does NOT measure (honestly): fluency, helpfulness, depth,
or overall answer QUALITY in the human sense — a deterministic rubric can
only assert containment, absence, format, and length. A local-14B-as-judge
suite is the documented follow-on (see evals/README.md).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from evals.loader import GoldenDataError, golden_path, load_golden
from evals.rubric import score_answer, validate_checks
from evals.types import CaseResult, CaseStatus, SuiteReport

SUITE_NAME: str = "answer_quality"

_VALID_MODES: frozenset[str] = frozenset({"offline", "model"})
_VALID_CATEGORIES: frozenset[str] = frozenset(
    {
        "identity",
        "factual",
        "format",
        "leakage",
        "grounding",
        "injection_resistance",
        "uncertainty",
    }
)

# Generation cap for model-mode cases: ample for a conversational answer,
# bounded for eval-run wall-clock (the format cases need only a few tokens).
_EVAL_MAX_NEW_TOKENS: int = 512

# Session id used for the throwaway per-case ContextManager session.
_EVAL_SESSION_ID: str = "eval-answer-quality"


def _production_strip() -> Callable[[str], str]:
    """Resolve the production think-strip function from its home.

    Single source of truth: this is the AO's own ``_strip_hidden_blocks``
    (services/assistant_orchestrator/src/entrypoint.py) — the function the
    production loop applies before a generation is reused or displayed —
    imported, never copied. The gate test asserts this identity so a future
    rename/move fails loudly instead of silently forking the strip logic.
    """
    from services.assistant_orchestrator.src.entrypoint import (
        _strip_hidden_blocks,
    )

    return _strip_hidden_blocks


def strip_for_display(raw: str) -> str:
    """Strip hidden model blocks the way production does before display."""
    return _production_strip()(raw)


def _valid_provenance_values() -> frozenset[str]:
    """The REAL provenance tiers (imported, not copied)."""
    from services.assistant_orchestrator.src.context_manager import Provenance

    return frozenset(member.value for member in Provenance)


def compose_generation_context(
    prompt: str, grounded_context: dict[str, Any] | None
) -> str:
    """Compose the generation context the way production does.

    Drives the REAL ``ContextManager`` — the same create-session /
    add_grounded_context (datamarking + spotlighting delimiters + provenance)
    / add_turn / trim_to_budget / build_context sequence the AO entrypoint
    runs in ``_handle_prompt`` — so a model-mode case with grounded content
    reads EXACTLY the datamarked, delimited form production feeds the model.

    Raises:
        RuntimeError: If the context build fails (fail-closed — an eval must
            never silently score an un-grounded prompt as a grounded case).
    """
    from services.assistant_orchestrator.src.context_manager import (
        ContextManager,
        Provenance,
    )

    manager = ContextManager()
    manager.create_session(_EVAL_SESSION_ID)
    if grounded_context is not None:
        provenance = Provenance(
            str(grounded_context.get("provenance", "untrusted_external"))
        )
        chunks = [str(chunk) for chunk in grounded_context["chunks"]]
        if not manager.add_grounded_context(
            _EVAL_SESSION_ID, chunks, provenance=provenance
        ):
            raise RuntimeError("grounded-context injection failed (fail-closed)")
    manager.add_turn(
        _EVAL_SESSION_ID, "user", prompt, token_count=max(1, len(prompt) // 4)
    )
    manager.trim_to_budget(_EVAL_SESSION_ID)
    built = manager.build_context(_EVAL_SESSION_ID)
    if built is None:
        raise RuntimeError("context build failed (fail-closed)")
    return built


def default_model_dir() -> Path:
    """Resolve the production AO model directory (repo-root relative).

    The unified Qwen3-14B (ADR-012 §2.1) — the SAME model directory the PA
    classification suite resolves; both services share the one model.
    """
    return (
        Path(__file__).resolve().parents[2]
        / "models"
        / "qwen3-14b"
        / "openvino-int4-gpu"
    )


def production_tool_call_grammar_posture() -> bool:
    """Resolve ``[generation].tool_call_grammar`` from the production TOML.

    The eval must mirror the DECIDED production posture, not the
    ``GenerationConfig`` dataclass default: the two diverged on 2026-07-02
    when the LA flipped the grammar OFF in ``default.toml`` pending the
    #725 xgrammar stop-token crash, while the dataclass default stayed
    ``True`` — and the first hardware eval runs inherited the dataclass
    default, re-enabling a constraint production had turned off (two crash
    reproductions later, the divergence was found). Reading the same TOML
    key the AO entrypoint reads (same ``get`` fallback) keeps the eval
    posture-faithful through any future #725 re-enable, with no copy to
    drift.
    """
    import tomllib

    toml_path = (
        Path(__file__).resolve().parents[2]
        / "services"
        / "assistant_orchestrator"
        / "config"
        / "default.toml"
    )
    with toml_path.open("rb") as fh:
        data = tomllib.load(fh)
    generation = data.get("generation", {})
    return bool(generation.get("tool_call_grammar", True))


def make_real_ao_generator(
    model_dir: Path | None = None,
) -> Callable[[str], str]:
    """Build the model-in-the-loop generator (Arc 140V required).

    Loads the real ``OrchestratorGPUInference`` once (Qwen3-14B, ADR-012;
    the constructor's own defaults carry the production draft-model path
    and speculative-decoding posture — the production loader, not a
    reimplementation) and returns a callable mapping a composed context
    string to the RAW generation text. Greedy decoding (``do_sample=False``,
    the repo's temperature-0 determinism doctrine) so hardware runs are
    reproducible.

    Raises:
        FileNotFoundError: If the model directory is absent (the model is
            gitignored; only the operator's machine has it).
        RuntimeError: If the model fails to load or a generation errors
            (fail-closed).
    """
    from services.assistant_orchestrator.src.gpu_inference import (
        GenerationConfig,
        OrchestratorGPUInference,
    )

    resolved = model_dir or default_model_dir()
    if not resolved.exists():
        raise FileNotFoundError(f"AO model directory not found: {resolved}")
    inference = OrchestratorGPUInference(model_dir=str(resolved))
    if not inference.load_model():
        raise RuntimeError(f"AO model failed to load from {resolved}")

    def generate(composed_context: str) -> str:
        result = inference.generate_text(
            composed_context,
            max_new_tokens=_EVAL_MAX_NEW_TOKENS,
            config=GenerationConfig(
                max_new_tokens=_EVAL_MAX_NEW_TOKENS,
                do_sample=False,  # greedy / temp-0 equivalent — reproducible
                # Production posture from default.toml, never the dataclass
                # default (#725 divergence):
                tool_call_grammar=production_tool_call_grammar_posture(),
            ),
        )
        if result.error:
            raise RuntimeError(f"generation failed: {result.error}")
        return result.text

    return generate


def _validate_case(case: dict[str, Any]) -> str | None:
    """Return an error string if the golden case is malformed, else None.

    Fail-closed: EVERY case is validated before any scoring or skipping —
    a malformed model-mode case is a harness error even in a CI run that
    would only skip it.
    """
    mode = case.get("mode")
    if mode not in _VALID_MODES:
        return f"invalid mode {mode!r} (must be one of {sorted(_VALID_MODES)})"
    category = case.get("category")
    if category not in _VALID_CATEGORIES:
        return (
            f"invalid category {category!r} "
            f"(must be one of {sorted(_VALID_CATEGORIES)})"
        )
    if mode == "offline":
        fixture = case.get("fixture_response")
        if not isinstance(fixture, str) or not fixture:
            return "offline case requires a non-empty 'fixture_response' string"
    else:
        prompt = case.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            return "model case requires a non-empty 'prompt' string"

    grounded = case.get("grounded_context")
    if grounded is not None:
        if not isinstance(grounded, dict):
            return "'grounded_context' must be a JSON object"
        chunks = grounded.get("chunks")
        if not isinstance(chunks, list) or not chunks:
            return "'grounded_context.chunks' must be a non-empty list of strings"
        if not all(isinstance(chunk, str) and chunk for chunk in chunks):
            return "'grounded_context.chunks' must contain only non-empty strings"
        provenance = grounded.get("provenance", "untrusted_external")
        if provenance not in _valid_provenance_values():
            return (
                f"invalid grounded_context.provenance {provenance!r} "
                f"(must be one of {sorted(_valid_provenance_values())})"
            )

    checks_problem = validate_checks(case.get("checks"))
    if checks_problem is not None:
        return checks_problem
    return None


def _score_case(case: dict[str, Any], answer: str) -> CaseResult:
    """Score a stripped answer against the case's rubric checks."""
    case_id = str(case["id"])
    description = str(case.get("description", ""))
    verdict = score_answer(answer, case["checks"])
    if verdict.passed:
        return CaseResult(
            case_id=case_id,
            status=CaseStatus.PASS,
            description=description,
            expected=case["checks"],
            actual=answer,
        )
    return CaseResult(
        case_id=case_id,
        status=CaseStatus.FAIL,
        description=description,
        expected=case["checks"],
        actual=answer,
        detail=f"rubric check '{verdict.failed_check}' failed: {verdict.detail}",
    )


def run_suite(
    golden_file: Path | None = None,
    *,
    include_hardware: bool = False,
    hardware_generator: Callable[[str], str] | None = None,
) -> SuiteReport:
    """Run the answer-quality suite.

    Args:
        golden_file: Override golden path (defaults to
            evals/golden/answer_quality.jsonl).
        include_hardware: When True, model-mode cases run through the real
            AO generation path instead of being skipped. NEVER set this in
            CI (loads the Qwen3-14B on the Arc 140V).
        hardware_generator: Injectable generator for model-mode cases —
            takes the COMPOSED context string (production grounding shape),
            returns the RAW generation text (the suite applies the
            production strip). Built via :func:`make_real_ao_generator`
            when None and ``include_hardware`` is True.

    Returns:
        SuiteReport with one CaseResult per golden case.
    """
    path = golden_file or golden_path(SUITE_NAME)
    cases = load_golden(path)

    report = SuiteReport(suite=SUITE_NAME)
    generator = hardware_generator

    for case in cases:
        problem = _validate_case(case)
        if problem is not None:
            raise GoldenDataError(f"{path.name} case {case.get('id')}: {problem}")

        case_id = str(case["id"])
        description = str(case.get("description", ""))

        if case["mode"] == "offline":
            try:
                answer = strip_for_display(str(case["fixture_response"]))
                report.results.append(_score_case(case, answer))
            except Exception as exc:  # noqa: BLE001 — scoring must not abort the run
                report.results.append(
                    CaseResult(
                        case_id=case_id,
                        status=CaseStatus.ERROR,
                        description=description,
                        detail=f"harness error: {exc}",
                    )
                )
            continue

        # mode == "model"
        if not include_hardware:
            report.results.append(
                CaseResult(
                    case_id=case_id,
                    status=CaseStatus.SKIPPED_HARDWARE,
                    description=description,
                    expected=case["checks"],
                    detail=(
                        "model-in-the-loop case; requires --include-hardware "
                        "on the Arc 140V"
                    ),
                )
            )
            continue

        try:
            if generator is None:
                generator = make_real_ao_generator()
            composed = compose_generation_context(
                str(case["prompt"]), case.get("grounded_context")
            )
            raw = generator(composed)
            answer = strip_for_display(raw)
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
