"""
The turn-end stop token is a PER-MODEL fact, and it must actually be SET (#930)
==============================================================================
Two defects found together on 2026-09-22, both in the same four lines.

**1. The id was compiled in.** ``QWEN3_IM_END_TOKEN_ID = 151_645`` is correct
for Qwen3-14B and wrong for every other vocabulary; the Qwen3.6 family uses
248046. Both measured on the real tokenizers. A wrong stop id does not crash —
generation simply runs past the turn boundary to the token cap.

**2. The assignment never worked AT ALL, on any model.** OpenVINO GenAI's
binding accepts only ``Set[SupportsInt]`` for ``stop_token_ids``. The code
assigned a LIST, which raises ``TypeError``, inside a bare ``except: pass``.
So the "dual stop token IDs (ADR-012 §2.4)" defense-in-depth described in the
Policy Agent's own module docstring was **inert for its entire life**, and the
``stop_strings`` text fallback silently carried the whole job.

The second defect is the more instructive one and is why these locks exist: a
control that is configured but never engaged looks exactly like a control that
works, because the fallback beside it keeps the system correct. Nothing failed.
The only way to see it was to read back what was actually set.

These locks are tokenizer-only — no GPU, no weights beyond the tokenizer IR.
"""

from __future__ import annotations

import pytest

from shared.fleet.model_profiles import (
    QWEN3_TURN_END_TOKEN_ID,
    TURN_END_TOKEN_TEXT,
    resolve_turn_end_token_id,
    turn_end_token_id_from_pipeline,
)

ov_genai = pytest.importorskip(
    "openvino_genai", reason="OpenVINO GenAI required for the tokenizer/config locks"
)

QWEN3_14B_DIR = "models/qwen3-14b/openvino-int4-gpu"
QWEN36_35B_DIR = "B:/models/Qwen3.6-35B-A3B-int4-ov"


class TestTheAssignmentActuallyTakes:
    """Defect 2: a list raises and a bare except hid it for the module's life."""

    def test_a_set_assignment_is_readable_back(self) -> None:
        cfg = ov_genai.GenerationConfig()
        assert cfg.stop_token_ids == set(), "expected an empty default"
        cfg.stop_token_ids = {248046}
        assert cfg.stop_token_ids == {248046}, (
            "the stop id must be readable back after assignment — if this is "
            "empty, the control is configured but inert"
        )

    def test_a_list_assignment_raises_which_is_why_it_must_not_be_used(self) -> None:
        """Pin the exact failure the production code used to swallow.

        If a future GenAI accepts a list, this test fails LOUDLY and someone
        re-reads the production sites deliberately, rather than a silent
        `except: pass` deciding it for them.
        """
        cfg = ov_genai.GenerationConfig()
        with pytest.raises(TypeError):
            cfg.stop_token_ids = [248046]  # type: ignore[assignment]


class TestTheIdComesFromTheModel:
    """Defect 1: the id was a constant, so it was right for exactly one model."""

    @pytest.mark.parametrize(
        ("model_dir", "expected"),
        [
            pytest.param(QWEN3_14B_DIR, 151_645, id="qwen3-14b"),
            pytest.param(QWEN36_35B_DIR, 248_046, id="qwen3.6-35b-a3b"),
        ],
    )
    def test_resolved_from_the_real_tokenizer(self, model_dir: str, expected: int) -> None:
        from pathlib import Path

        if not Path(model_dir).exists():
            pytest.skip(f"model directory absent (gitignored weights): {model_dir}")
        tokenizer = ov_genai.Tokenizer(model_dir)
        token_id, resolved = resolve_turn_end_token_id(tokenizer, model_label=model_dir)
        assert resolved is True, f"{TURN_END_TOKEN_TEXT} must resolve for {model_dir}"
        assert token_id == expected

    def test_the_two_vocabularies_genuinely_differ(self) -> None:
        """The whole point: a constant cannot serve both."""
        from pathlib import Path

        if not (Path(QWEN3_14B_DIR).exists() and Path(QWEN36_35B_DIR).exists()):
            pytest.skip("both model directories required for the contrast")
        a, _ = resolve_turn_end_token_id(ov_genai.Tokenizer(QWEN3_14B_DIR))
        b, _ = resolve_turn_end_token_id(ov_genai.Tokenizer(QWEN36_35B_DIR))
        assert a != b, (
            "if these ever coincide this lock is no longer measuring anything — "
            "re-derive it rather than deleting it"
        )
        assert a == QWEN3_TURN_END_TOKEN_ID, "the compiled-in default is the 14B's"


class TestFailureIsReportedNotGuessed:
    """`resolved=False` is the signal the caller must log loudly."""

    def test_absent_tokenizer_reports_unresolved(self) -> None:
        token_id, resolved = resolve_turn_end_token_id(None)
        assert (token_id, resolved) == (QWEN3_TURN_END_TOKEN_ID, False)

    def test_broken_tokenizer_reports_unresolved_and_never_raises(self) -> None:
        class Broken:
            def encode(self, _text: str) -> object:
                raise RuntimeError("tokenizer exploded")

        token_id, resolved = resolve_turn_end_token_id(Broken())
        assert (token_id, resolved) == (QWEN3_TURN_END_TOKEN_ID, False)

    def test_multi_token_text_is_refused_rather_than_truncated(self) -> None:
        """A text that is not ONE special token in this vocabulary is exactly
        the case a caller must not paper over."""

        class MultiToken:
            def encode(self, _text: str) -> list[int]:
                return [1, 2, 3]

        _, resolved = resolve_turn_end_token_id(MultiToken())
        assert resolved is False

    def test_resolves_through_the_shared_pipeline_wrapper(self) -> None:
        """The PA holds no tokenizer; it must reach one via the pipeline."""
        from pathlib import Path

        if not Path(QWEN36_35B_DIR).exists():
            pytest.skip("35B weights absent (gitignored)")

        class RawPipe:
            def __init__(self, tok: object) -> None:
                self._tok = tok

            def get_tokenizer(self) -> object:
                return self._tok

        class Wrapper:
            def __init__(self, raw: object) -> None:
                self.raw = raw

        wrapper = Wrapper(RawPipe(ov_genai.Tokenizer(QWEN36_35B_DIR)))
        token_id, resolved = turn_end_token_id_from_pipeline(wrapper)
        assert (token_id, resolved) == (248_046, True)

    def test_pipeline_without_a_tokenizer_reports_unresolved(self) -> None:
        class NoTokenizer:
            pass

        token_id, resolved = turn_end_token_id_from_pipeline(NoTokenizer())
        assert (token_id, resolved) == (QWEN3_TURN_END_TOKEN_ID, False)
