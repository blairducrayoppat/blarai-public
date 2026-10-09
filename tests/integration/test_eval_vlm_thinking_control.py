"""
Eval Harness — the VLM arm must never open a reasoning block (#1618, lesson 369)
================================================================================
The 2026-07-17 answer-quality run scored the Qwen3.6-35B-A3B at 22/40 and its
10 ``no_think_tags`` failures were read as proof the model could not suppress
reasoning. That verdict gated #930 for two months and was an artifact of THIS
harness.

The mechanism, in one paragraph. The Qwen3.5/3.6 chat template emits the closed
empty block ``<think>\\n\\n</think>\\n\\n`` only when ``enable_thinking`` is
defined AND false; **in every other case it emits a bare opening ``<think>\\n``**.
Undefined takes the else branch, so omission is not a neutral default — it is an
instruction to start reasoning. ``build_vlm_composed_generator`` hand-built its
ChatML, left ``GenerationConfig.apply_chat_template`` at its default ``True``,
and set ``enable_thinking`` nowhere, so the template appended a bare opener to
every prompt. The eval opened a reasoning block and then scored the model for
continuing it.

WHY NO EXISTING TEST COULD HAVE CAUGHT IT (the reason this file exists):
``test_eval_model_target.py``'s ``_FakeGenConfig`` carries only
``max_new_tokens`` and ``do_sample``. The real ``ov_genai.GenerationConfig`` has
``apply_chat_template``, defaulting to True. The fake's shape diverged from the
real object exactly at the field that mattered, so no assertion about it was
even expressible — the canonical mock-shape-divergence failure. The fakes here
therefore model the real defaults, and the config fake REFUSES unknown
attributes, so a future field rename fails loudly instead of silently passing.

These locks are deliberately GPU-free and weight-free: the render they assert is
reproducible from the tokenizer IR alone, which is the whole point — the check
that would have caught this in July costs about a minute and no hardware.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

EMPTY_THINK_BLOCK = "<think>\n\n</think>\n\n"
BARE_THINK_OPEN = "<think>\n"
ASSISTANT_HEADER = "<|im_start|>assistant\n"


def _make_vlm_dir(root: Path, name: str = "qwen3.6-35b-a3b") -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "openvino_language_model.xml").write_text("<net/>", encoding="utf-8")
    return d


class _RealShapeGenConfig:
    """A GenerationConfig fake that matches the REAL object's surface.

    ``apply_chat_template`` defaults to True exactly as ov_genai's does — that
    default is the defect. ``__setattr__`` refuses unknown attributes so a
    renamed field surfaces as an error rather than as a silently-ignored
    assignment (the divergence that hid this bug for two months).
    """

    _KNOWN = {"max_new_tokens", "do_sample", "apply_chat_template"}

    def __init__(self) -> None:
        object.__setattr__(self, "max_new_tokens", 0)
        object.__setattr__(self, "do_sample", True)
        object.__setattr__(self, "apply_chat_template", True)

    def __setattr__(self, name: str, value: object) -> None:
        if name not in self._KNOWN:
            raise AttributeError(
                f"GenerationConfig has no attribute {name!r} — the fake models the "
                "real surface on purpose; update both together."
            )
        object.__setattr__(self, name, value)


class _RecordingVLMPipeline:
    """Records what the harness actually handed the runtime."""

    last_prompt: object = None
    last_config: object = None
    last_was_history: bool = False

    def __init__(self, model_dir: str, device: str) -> None:
        self.model_dir = model_dir
        self.device = device

    def generate(self, prompt: object, **kwargs: object) -> str:
        cls = type(self)
        cls.last_prompt = prompt
        cls.last_config = kwargs.get("generation_config")
        cls.last_was_history = not isinstance(prompt, str)
        return "an answer"

    def set_chat_template(self, template: str) -> None:  # pragma: no cover
        pass


class _FakeChatHistory:
    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.extra_context: dict = {}

    def append(self, message: dict) -> None:
        self.messages.append(message)

    def set_extra_context(self, extra_context: dict) -> None:
        self.extra_context = dict(extra_context)

    def get_extra_context(self) -> dict:
        return dict(self.extra_context)


def _install_fake_ov_genai(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.ModuleType("openvino_genai")
    fake.VLMPipeline = _RecordingVLMPipeline  # type: ignore[attr-defined]
    fake.GenerationConfig = _RealShapeGenConfig  # type: ignore[attr-defined]
    fake.ChatHistory = _FakeChatHistory  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openvino_genai", fake)


def _build(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from evals.hardware_pipeline import build_vlm_composed_generator

    _install_fake_ov_genai(monkeypatch)
    _RecordingVLMPipeline.last_prompt = None
    _RecordingVLMPipeline.last_config = None
    _RecordingVLMPipeline.last_was_history = False
    gen = build_vlm_composed_generator(
        _make_vlm_dir(tmp_path), max_new_tokens=64, system_prompt="SYSTEM-PROMPT"
    )
    gen("composed grounded context")
    return _RecordingVLMPipeline.last_prompt, _RecordingVLMPipeline.last_config


class TestVlmArmNeverOpensAReasoningBlock:
    """The property, asserted three independent ways.

    Any of the sanctioned arms satisfies all three: the hand-built prefill with
    ``apply_chat_template=False`` (what the Policy Agent ships), or a
    ``ChatHistory`` carrying ``enable_thinking=False``. The tests assert the
    OUTCOME, not one implementation, so adopting either arm keeps them green.
    """

    def test_template_is_not_allowed_to_wrap_a_hand_built_prompt(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A hand-built ChatML string with apply_chat_template=True is wrapped
        a second time, and the second wrap appends a bare reasoning opener."""
        prompt, config = _build(monkeypatch, tmp_path)
        if not isinstance(prompt, str):
            pytest.skip("ChatHistory arm in use — the template renders it; see the sibling test")
        assert config is not None, "no GenerationConfig reached the pipeline"
        assert config.apply_chat_template is False, (
            "apply_chat_template was left at its default True on a HAND-BUILT "
            "ChatML string. The template will wrap it again and append a bare "
            "'<think>' opener, which is what produced the July 22/40. Set it to "
            "False explicitly, or pass a ChatHistory instead."
        )

    def test_the_prompt_carries_a_closed_empty_block_not_a_bare_opener(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Whatever reaches the runtime must say 'do not think' explicitly."""
        prompt, _ = _build(monkeypatch, tmp_path)

        if isinstance(prompt, str):
            assert prompt.count(ASSISTANT_HEADER) == 1, (
                f"expected exactly one assistant turn, found "
                f"{prompt.count(ASSISTANT_HEADER)} — a double wrap"
            )
            assert EMPTY_THINK_BLOCK in prompt, (
                "the prompt does not carry the closed empty think block; without "
                "it the export's template opens a reasoning block by default"
            )
            assert not prompt.rstrip().endswith("<think>"), (
                "the prompt ends on a BARE reasoning opener — this asks the model "
                "to think, and then the eval scores it for thinking"
            )
        else:
            assert prompt.get_extra_context().get("enable_thinking") is False, (
                "a ChatHistory reached the runtime without "
                "enable_thinking=False; undefined takes the template's ELSE "
                "branch, which emits a bare '<think>' opener"
            )

    def test_enable_thinking_is_never_passed_as_a_generation_kwarg(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The 2026-07-09 upstream comment measured this mistake.

        ``enable_thinking`` is a chat-template variable, not a GenerationConfig
        field. Passing it to generate() is silently dropped, so a probe built
        that way reports 'the switch has no effect' when nothing was switched.
        """
        _, config = _build(monkeypatch, tmp_path)
        assert not hasattr(config, "enable_thinking"), (
            "enable_thinking was set on the GenerationConfig, where the runtime "
            "ignores it. It belongs in the template render (extra_context) or in "
            "a hand-built prefill."
        )


class TestTheStripCannotRescueAPromptOpenedBlock:
    """Why this presented as a model defect rather than an obvious bug."""

    def test_orphaned_closing_tag_survives_the_production_strip(self) -> None:
        from services.assistant_orchestrator.src.entrypoint import (
            _strip_hidden_blocks,
        )

        matched = "<think>\nreasoning\n</think>\n\nThe answer."
        assert _strip_hidden_blocks(matched) == "The answer."

        orphan = "reasoning about it\n</think>\n\nThe answer."
        assert "</think>" in _strip_hidden_blocks(orphan), (
            "an orphaned </think> must be understood to SURVIVE the strip — the "
            "regex needs a matched pair. This is why a prompt-opened block "
            "reached the rubric and looked like a model defect."
        )

    def test_a_no_think_tags_pass_is_not_evidence_of_suppression(self) -> None:
        """The check named after the property cannot witness the property.

        A model that reasons inside a WELL-FORMED block has it stripped before
        scoring and passes. Any claim that thinking was suppressed must rest on
        the first generated token, never on this rubric check going green.
        """
        from evals.suites.answer_quality import strip_for_display

        thought_hard = "<think>\nlots of reasoning\n</think>\n\nYes."
        assert strip_for_display(thought_hard) == "Yes.", (
            "a well-formed reasoning block is stripped before scoring, so "
            "no_think_tags passing says nothing about whether the model thought"
        )
