"""
Eval Harness — Hardware Model-Target Override (#931)
====================================================
The default hardware eval path (``--include-hardware``) drives the resident
Qwen3-14B: every model-in-the-loop suite resolves its own ``default_model_dir()``
(``models/qwen3-14b/openvino-int4-gpu``) and loads it through an OpenVINO GenAI
``LLMPipeline``. This module adds an OPT-IN override so a run can target an
arbitrary OpenVINO model directory and declare that model's CAPABILITY CONTRACT
— which pipeline class it loads through (``LLMPipeline`` vs ``VLMPipeline``) and
whether speculative decoding applies — so the hardware generator selects the
right pipeline.

The concrete unblock is the 35B-A3B consolidation quality-parity gate (#930):
the 35B-A3B is a NATIVELY MULTIMODAL checkpoint that OpenVINO GenAI serves
through a ``VLMPipeline`` (no draft-model speculative decoding for that family —
see ``scripts/benchmark_vlm_text_inference.py`` / ``docs/MODEL_EVALUATION_QWEN36_27B.md``),
so it cannot be quality-gated through the 14B's ``LLMPipeline`` path.

Design posture (security_by_design):
  * OPT-IN — no override resolves to ``None`` and every suite's default 14B
    ``LLMPipeline`` path (and its committed baselines) stays byte-identical.
  * FAIL-CLOSED — a nonexistent directory, a missing/unknown capability, or a
    directory whose contents do not match the declared capability raises
    ``ModelTargetError`` (mapped to the harness-error exit code, exit 2). The
    override is NEVER silently ignored and the pipeline class is NEVER guessed.
  * FAIL-LOUD — a capability contract supplied without a target directory is a
    mistake, not a no-op, and raises.

The #834 model-profiles manifest (``shared/fleet/model_profiles.py``) is a
DORMANT reference-data loader whose only live consumer today is the AO's
hidden-block strip tags; it carries no pipeline-class field and no VLM/LLM
selector, so this override is a small, self-contained addition rather than an
extension of that loader. When a later ticket promotes a ``pipeline_class`` /
``multimodal`` field into the manifest, ``resolve_model_target`` is the single
place to source the capability from it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping


class Capability(str, Enum):
    """The pipeline-class capability contract a target model is loaded under.

    ``text-llm`` — a dense text model served through ``ov_genai.LLMPipeline``
        with the pruned-draft speculative decoding of the Qwen3-14B contract
        (ADR-012). This is the DEFAULT contract (the resident 14B).
    ``multimodal-vlm`` — a natively multimodal model served through
        ``ov_genai.VLMPipeline`` (e.g. the 35B-A3B consolidation candidate).
        Speculative decoding does not exist for this pipeline class/model
        family on OpenVINO GenAI as of 2026-07, so the contract is structurally
        spec-decode-absent.
    """

    TEXT_LLM = "text-llm"
    MULTIMODAL_VLM = "multimodal-vlm"


#: argparse ``choices`` for the ``--capability`` flag (stable string values).
CAPABILITY_CHOICES: tuple[str, ...] = tuple(c.value for c in Capability)

#: Env overrides (parity with ``BLARAI_MODEL_PROFILES_PATH``); a scheduled or
#: headless parity run can point the harness at a model without CLI edits.
ENV_MODEL_DIR: str = "BLARAI_EVAL_MODEL_DIR"
ENV_CAPABILITY: str = "BLARAI_EVAL_CAPABILITY"
ENV_NO_SPECULATIVE: str = "BLARAI_EVAL_NO_SPECULATIVE"

#: The OpenVINO IR filename each capability's directory MUST contain — the
#: contract check that a declared capability actually matches the directory.
#: An ``LLMPipeline`` model exports ``openvino_model.xml`` (see
#: ``shared/inference/shared_pipeline.py``); a ``VLMPipeline`` model exports the
#: split language tower as ``openvino_language_model.xml`` (see
#: ``shared/inference/vlm.py`` / ``scripts/benchmark_vlm_text_inference.py``).
_CAPABILITY_MODEL_FILE: dict[Capability, str] = {
    Capability.TEXT_LLM: "openvino_model.xml",
    Capability.MULTIMODAL_VLM: "openvino_language_model.xml",
}

#: Human-readable pipeline class per capability, for error messages.
_PIPELINE_NAME: dict[Capability, str] = {
    Capability.TEXT_LLM: "LLMPipeline",
    Capability.MULTIMODAL_VLM: "VLMPipeline",
}

_TRUE_TOKENS: frozenset[str] = frozenset({"1", "true", "yes", "on"})


class ModelTargetError(Exception):
    """The hardware model-target override is malformed or unresolvable.

    Raised for a nonexistent/mis-typed directory, an absent/unknown capability,
    or a directory that does not match its declared capability. The runner maps
    this to the harness-error exit code (2, fail-closed) — an uncomparable or
    mis-pipelined run is never a silent success.
    """


@dataclass(frozen=True)
class ModelTarget:
    """A resolved, validated hardware eval target and its capability contract.

    Attributes:
        model_dir: The OpenVINO model directory to load (verified to exist and
            to contain the declared capability's IR file).
        capability: Which pipeline class the model loads through.
        speculative_decode: Whether speculative decoding applies. Always
            ``False`` for ``multimodal-vlm`` (structural); for ``text-llm`` it
            follows the ``--no-speculative`` flag (default ``True`` — the 14B
            contract).
    """

    model_dir: Path
    capability: Capability
    speculative_decode: bool

    @property
    def uses_vlm_pipeline(self) -> bool:
        """True iff this target loads through ``ov_genai.VLMPipeline``."""
        return self.capability is Capability.MULTIMODAL_VLM


def parse_capability(value: str) -> Capability:
    """Parse a capability string, raising ``ModelTargetError`` on an unknown one.

    argparse ``choices`` already rejects an unknown CLI value; this guards the
    env-variable path (``BLARAI_EVAL_CAPABILITY``), which bypasses argparse.
    """
    try:
        return Capability(value)
    except ValueError:
        raise ModelTargetError(
            f"unknown eval capability {value!r} "
            f"(must be one of: {', '.join(CAPABILITY_CHOICES)})"
        ) from None


def _env_flag(value: str | None) -> bool:
    return value is not None and value.strip().lower() in _TRUE_TOKENS


def resolve_model_target(
    *,
    model_dir: "str | Path | None",
    capability: str | None,
    no_speculative: bool = False,
    env: "Mapping[str, str] | None" = None,
) -> "ModelTarget | None":
    """Resolve the hardware model-target override from CLI values (+ env fallback).

    CLI values take precedence; the ``BLARAI_EVAL_*`` environment variables fill
    any left unset. Returns ``None`` when no override is requested — the caller
    then keeps every suite's byte-identical default 14B ``LLMPipeline`` path.

    Args:
        model_dir: Target model directory (or ``None`` for the default 14B path).
        capability: Declared capability string (see :class:`Capability`).
        no_speculative: When True, a ``text-llm`` target loads WITHOUT the
            speculative draft (ignored for ``multimodal-vlm``, which has none).
        env: Environment mapping (defaults to ``os.environ``; injectable for
            tests).

    Returns:
        A validated :class:`ModelTarget`, or ``None`` when no override is set.

    Raises:
        ModelTargetError: Fail-closed on any malformed override — a capability
            without a directory, a nonexistent/non-directory path, a missing or
            unknown capability, or a directory whose IR file does not match the
            declared capability.
    """
    environ = env if env is not None else os.environ

    resolved_dir = model_dir if model_dir is not None else (environ.get(ENV_MODEL_DIR) or None)
    resolved_cap = capability if capability is not None else (environ.get(ENV_CAPABILITY) or None)
    resolved_nospec = no_speculative or _env_flag(environ.get(ENV_NO_SPECULATIVE))

    if resolved_dir is None:
        # A capability contract (or --no-speculative) with no target model is a
        # mistake, not a silent no-op — fail loud rather than quietly running
        # the default 14B while the operator believes an override is in effect.
        if resolved_cap is not None or resolved_nospec:
            raise ModelTargetError(
                "an eval capability contract (--capability / --no-speculative or "
                "their BLARAI_EVAL_* env vars) was supplied without --model-dir "
                "(BLARAI_EVAL_MODEL_DIR) — a contract with no target model is a "
                "mistake (fail-closed)."
            )
        return None

    path = Path(resolved_dir).expanduser()
    if not path.exists():
        raise ModelTargetError(
            f"eval --model-dir does not exist: {path} "
            "(fail-closed; the override is never silently ignored)."
        )
    if not path.is_dir():
        raise ModelTargetError(f"eval --model-dir is not a directory: {path}")

    if resolved_cap is None:
        raise ModelTargetError(
            "eval --model-dir requires --capability "
            f"(one of: {', '.join(CAPABILITY_CHOICES)}) — the pipeline class is "
            "never guessed (fail-closed)."
        )

    capability_enum = parse_capability(resolved_cap)

    expected_file = _CAPABILITY_MODEL_FILE[capability_enum]
    if not (path / expected_file).exists():
        raise ModelTargetError(
            f"eval --model-dir {path} was declared '{capability_enum.value}' but its "
            f"expected OpenVINO IR file '{expected_file}' is absent — the directory "
            f"does not match the declared capability contract "
            f"({_PIPELINE_NAME[capability_enum]}). Point --model-dir at the correct "
            "model, or fix --capability (fail-closed; a mismatched pipeline is never "
            "loaded)."
        )

    if capability_enum is Capability.MULTIMODAL_VLM:
        # VLMPipeline has no draft-model speculative decoding for this model
        # family on OpenVINO GenAI (2026-07) — the contract is structurally
        # spec-decode-absent regardless of --no-speculative.
        speculative = False
    else:
        speculative = not resolved_nospec

    return ModelTarget(
        model_dir=path,
        capability=capability_enum,
        speculative_decode=speculative,
    )
