"""Unit tests for the pure logic of the VLMPipeline long-context decode-curve
harness (scripts/benchmark_vlm_longcontext.py) — #932 / #930.

No GPU, no model load, no openvino runtime: the harness guards those imports, so
its prompt-construction, KV-geometry, and memory-ceiling-projection helpers are
importable and testable on their own. What we lock here is the part a reviewer
must trust BEFORE any number is taken:

  * the memory-ceiling STOP condition counts only the hybrid 35B's FULL-attention
    layers (a naive all-40-layers projection would over-estimate KV by ~4x and
    could falsely skip a feasible 32K band);
  * the analytical KV math matches the measured Qwen3.6-35B geometry;
  * plan_bands admits feasible bands, refuses over-ceiling / over-context bands,
    and STOPS monotonically at the first breach;
  * the coherence prompt keeps its invariants (needle at the start, question at
    the end) at every band length.

The live sweep is hardware-gated and not exercised here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import benchmark_vlm_longcontext as lc  # noqa: E402

# Measured Qwen3.6-35B-A3B geometry (config.json text_config, 2026-07-17):
# 40 layers, of which 10 are full_attention (KV-growing); 2 KV heads; head_dim
# 256; 256K trained window.
GEOM_35B = {
    "num_hidden_layers": 40,
    "full_attention_layers": 10,
    "num_key_value_heads": 2,
    "head_dim": 256,
    "max_position_embeddings": 262144,
    "layer_types_present": True,
}


class FakeTokenizer:
    """Whitespace tokenizer — enough to exercise build_band_prompt's invariants
    without the real HF tokenizer/model files."""

    def __call__(self, text: str) -> dict[str, list[str]]:
        return {"input_ids": text.split()}

    def decode(self, ids: list[str], skip_special_tokens: bool = True) -> str:
        return " ".join(ids)


class TestKvLayerCount:
    def test_prefers_full_attention_count(self) -> None:
        assert lc.kv_layer_count(GEOM_35B) == 10

    def test_falls_back_to_total_when_layer_types_absent(self) -> None:
        geom = {**GEOM_35B, "full_attention_layers": None}
        assert lc.kv_layer_count(geom) == 40


class TestAnalyticalKv:
    def test_35b_32k_is_exactly_0p625_gib(self) -> None:
        # 10 full-attn layers * 2 KV heads * 256 head_dim * 2 (K+V) * 2 bytes
        # = 20480 bytes/token; * 32768 / 1024^3 = 0.625 GiB exactly.
        assert lc.analytical_kv_gib(32768, GEOM_35B) == pytest.approx(0.625)

    def test_35b_16k_is_half_of_32k(self) -> None:
        assert lc.analytical_kv_gib(16384, GEOM_35B) == pytest.approx(0.3125)

    def test_hybrid_is_a_quarter_of_the_naive_dense_projection(self) -> None:
        # The load-bearing correctness point: counting only full-attention layers
        # (10) vs all layers (40) is a 4x difference in the projected KV term.
        dense = {**GEOM_35B, "full_attention_layers": None}  # -> 40 layers
        assert lc.analytical_kv_gib(32768, dense) == pytest.approx(2.5)
        assert lc.analytical_kv_gib(32768, GEOM_35B) == pytest.approx(2.5 / 4)

    def test_kv_scales_linearly_with_context(self) -> None:
        a = lc.analytical_kv_gib(8192, GEOM_35B)
        b = lc.analytical_kv_gib(16384, GEOM_35B)
        assert b == pytest.approx(2 * a)


class TestProjectPeak:
    def test_is_additive(self) -> None:
        proj = lc.project_peak_used_gib(19.0, 32768, GEOM_35B, working_margin_gib=2.0)
        assert proj == pytest.approx(19.0 + 0.625 + 2.0)


class TestPlanBands:
    def test_all_feasible_bands_admitted_at_realistic_residency(self) -> None:
        plans = lc.plan_bands([2048, 8192, 16384, 32768], GEOM_35B, used_after_load_gib=19.0)
        assert all(p.admitted for p in plans)
        assert [p.target_tokens for p in plans] == [2048, 8192, 16384, 32768]

    def test_over_max_context_band_is_skipped(self) -> None:
        plans = lc.plan_bands([2048, 300000], GEOM_35B, used_after_load_gib=19.0)
        by_band = {p.target_tokens: p for p in plans}
        assert by_band[2048].admitted
        assert not by_band[300000].admitted
        assert by_band[300000].skip_reason == "over_max_context"

    def test_memory_ceiling_stops_monotonically(self) -> None:
        # used=27.6 GiB resident: 8192 fits under the 31.323-1.5 GiB guard,
        # 16384 breaches it, and 32768 is skipped as a consequence of the prior.
        plans = lc.plan_bands([2048, 8192, 16384, 32768], GEOM_35B, used_after_load_gib=27.6)
        by_band = {p.target_tokens: p for p in plans}
        assert by_band[2048].admitted
        assert by_band[8192].admitted
        assert not by_band[16384].admitted
        assert by_band[16384].skip_reason == "memory_ceiling"
        assert not by_band[32768].admitted
        assert by_band[32768].skip_reason == "memory_ceiling_after_prior"

    def test_bands_are_processed_ascending(self) -> None:
        plans = lc.plan_bands([32768, 2048, 16384, 8192], GEOM_35B, used_after_load_gib=19.0)
        assert [p.target_tokens for p in plans] == [2048, 8192, 16384, 32768]


class TestBuildBandPrompt:
    def test_needle_answer_is_present(self) -> None:
        prompt, _actual, answer = lc.build_band_prompt(FakeTokenizer(), 500)
        assert answer == lc._NEEDLE_ANSWER
        assert lc._NEEDLE_ANSWER in prompt

    def test_question_is_at_the_end(self) -> None:
        prompt, _actual, _answer = lc.build_band_prompt(FakeTokenizer(), 500)
        assert prompt.rstrip().endswith(lc._QUESTION)

    def test_needle_precedes_the_filler_body(self) -> None:
        prompt, _actual, answer = lc.build_band_prompt(FakeTokenizer(), 800)
        # The needle sits in the head, before the corpus filler and the question.
        assert prompt.index(answer) < prompt.index(lc._QUESTION)

    def test_actual_token_count_hits_the_target(self) -> None:
        tok = FakeTokenizer()
        head_tail = lc._count_tokens(tok, lc._PREAMBLE + "\n\n" + lc._NEEDLE + "\n\n\n\n" + lc._QUESTION)
        target = head_tail + 300  # comfortably above the fixed head/tail cost
        _prompt, actual, _answer = lc.build_band_prompt(tok, target)
        assert actual == target

    def test_tiny_target_still_yields_needle_and_question(self) -> None:
        # A target below the fixed head/tail cost yields no filler, but the probe
        # is still well-formed (needle + question present).
        prompt, _actual, answer = lc.build_band_prompt(FakeTokenizer(), 5)
        assert answer in prompt
        assert lc._QUESTION in prompt


class TestCheckNeedle:
    def test_recall_is_case_insensitive(self) -> None:
        assert lc.check_needle("...the code is meridian-2718-anchor.", lc._NEEDLE_ANSWER)

    def test_absent_needle_is_false(self) -> None:
        assert not lc.check_needle("I do not recall any code.", lc._NEEDLE_ANSWER)

    def test_empty_output_is_false(self) -> None:
        assert not lc.check_needle("", lc._NEEDLE_ANSWER)


class TestLoadGeometry:
    def test_fallback_on_missing_config(self) -> None:
        geom = lc.load_geometry("/no/such/model/dir")
        assert geom == lc._GEOM_FALLBACK
        assert geom["full_attention_layers"] == 10

    def test_reads_real_35b_config_if_present(self) -> None:
        model_dir = Path("C:/Users/mrbla/models/qwen36-35b-a3b-int4-ov-OFFICIAL")
        if not (model_dir / "config.json").exists():
            pytest.skip("35B official IR config.json not present in this environment")
        geom = lc.load_geometry(model_dir)
        assert geom["num_hidden_layers"] == 40
        assert geom["full_attention_layers"] == 10
        assert geom["num_key_value_heads"] == 2
        assert geom["head_dim"] == 256
        assert geom["max_position_embeddings"] == 262144
        assert geom["layer_types_present"] is True


class TestParseBands:
    def test_parses_and_ignores_blanks(self) -> None:
        assert lc._parse_bands("2048, 8192 ,16384,") == [2048, 8192, 16384]
