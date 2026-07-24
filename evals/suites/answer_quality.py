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
from evals.model_target import Capability, ModelTarget
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

#: The AO brain's tool-call tag name. Detection requires this tag in the
#: RESOLVED strip binding (the gate lock asserts it against
#: ``resolve_hidden_block_tags``, manifest-aware — a model swap that renames
#: the tag in the manifest fails loudly there instead of silently breaking
#: detection into bare empty-string fails).
_TOOL_CALL_TAG: str = "tool_call"


def _production_tool_call_pattern() -> "re.Pattern[str]":
    """Production's CLOSED-pair tool-call pattern (imported, never copied —
    SSOT). The AO enters the tool loop only on a closed
    ``<tool_call>…</tool_call>`` block (``tools._TOOL_CALL_TAG_PATTERN``);
    a bare marker mention is not a call and must not be detected as one."""
    from services.assistant_orchestrator.src.tools import _TOOL_CALL_TAG_PATTERN

    return _TOOL_CALL_TAG_PATTERN


def is_tool_call_only(raw: str, stripped: str) -> bool:
    """True when a generation was ONLY hidden blocks and contained a CLOSED
    native tool-call block: production would execute the tool loop and show
    the user its final answer; the one-shot harness cannot (#1023), so the
    case is reached but unscorable — ``CaseStatus.TOOL_CALL``, never a bare
    fail on an empty string. Deliberately NOT this status: an all-``<think>``
    empty (production displays the same emptiness) and an UNCLOSED tool-call
    mention (production's parser requires the closed pair, finds none, runs
    no tool — the user sees emptiness) — both stay scoreable failures."""
    return (
        bool(raw.strip())
        and not stripped
        and _production_tool_call_pattern().search(raw) is not None
    )

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


def _default_system_prompt() -> str:
    """The production AO system prompt (imported, never copied — SSOT).

    The LLM path applies this inside ``generate_text`` (system_prompt=None ->
    ``_DEFAULT_SYSTEM_PROMPT``); the VLM path applies the SAME prompt via manual
    ChatML so the two pipelines' parity comparison is apples-to-apples.
    """
    from services.assistant_orchestrator.src.gpu_inference import (
        _DEFAULT_SYSTEM_PROMPT,
    )

    return _DEFAULT_SYSTEM_PROMPT


def make_real_ao_generator(
    model_dir: Path | None = None,
    *,
    target: ModelTarget | None = None,
) -> Callable[[str], str]:
    """Build the model-in-the-loop generator (Arc 140V required).

    Loads the real ``OrchestratorGPUInference`` once (Qwen3-14B, ADR-012;
    the constructor's own defaults carry the production draft-model path
    and speculative-decoding posture — the production loader, not a
    reimplementation) and returns a callable mapping a composed context
    string to the RAW generation text. Greedy decoding (``do_sample=False``,
    the repo's temperature-0 determinism doctrine) so hardware runs are
    reproducible.

    Args:
        model_dir: Legacy explicit model directory override (kept for callers
            that pass a directory directly). Ignored when ``target`` is given.
        target: The #931 OPT-IN hardware model-target override. When ``None``
            (the default), the resolution and construction are BYTE-IDENTICAL to
            the historical default 14B ``LLMPipeline`` path. A ``text-llm``
            target loads its directory through the same ``LLMPipeline`` loader,
            honoring the declared speculative-decode contract. A
            ``multimodal-vlm`` target loads through a ``VLMPipeline`` instead
            (``evals.hardware_pipeline``).

    Raises:
        FileNotFoundError: If the model directory is absent (the model is
            gitignored; only the operator's machine has it).
        RuntimeError: If the model fails to load or a generation errors
            (fail-closed).
    """
    # multimodal-vlm capability -> VLMPipeline arm (the 35B-A3B contract).
    if target is not None and target.capability is Capability.MULTIMODAL_VLM:
        from evals.hardware_pipeline import build_vlm_composed_generator

        return build_vlm_composed_generator(
            target.model_dir,
            max_new_tokens=_EVAL_MAX_NEW_TOKENS,
            system_prompt=_default_system_prompt(),
        )

    from services.assistant_orchestrator.src.gpu_inference import (
        GenerationConfig,
        OrchestratorGPUInference,
    )

    resolved = target.model_dir if target is not None else (model_dir or default_model_dir())
    if not resolved.exists():
        raise FileNotFoundError(f"AO model directory not found: {resolved}")
    # No target => construct EXACTLY as before (byte-identical default). A
    # text-llm override honors its declared speculative-decode contract.
    if target is not None:
        inference = OrchestratorGPUInference(
            model_dir=str(resolved),
            speculative_decoding_enabled=target.speculative_decode,
        )
    else:
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


def _tool_call_result(case: dict[str, Any], raw: str) -> CaseResult:
    """Record a tool-call-only generation as its own honest status.

    ``actual`` carries the raw block (bounded) as evidence — the report must
    show WHAT the model tried to call, or "tool_call" is just a fancier
    silence."""
    return CaseResult(
        case_id=str(case["id"]),
        status=CaseStatus.TOOL_CALL,
        description=str(case.get("description", "")),
        expected=case["checks"],
        actual=raw[:400],
        detail=(
            "model answered with a native tool call; production would run "
            "the tool loop — the one-shot harness cannot (#1023)"
        ),
    )


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
    model_target: ModelTarget | None = None,
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
        model_target: The #931 OPT-IN hardware model-target override. ``None``
            (the default) keeps the byte-identical default 14B ``LLMPipeline``
            path; a target selects that model's directory + pipeline class for
            the default generator (ignored when ``hardware_generator`` is
            injected directly, e.g. by tests).

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
                fixture = str(case["fixture_response"])
                answer = strip_for_display(fixture)
                if is_tool_call_only(fixture, answer):
                    report.results.append(_tool_call_result(case, fixture))
                    continue
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
                generator = make_real_ao_generator(target=model_target)
            composed = compose_generation_context(
                str(case["prompt"]), case.get("grounded_context")
            )
            raw = generator(composed)
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
