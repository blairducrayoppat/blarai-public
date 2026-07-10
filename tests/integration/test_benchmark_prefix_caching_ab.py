"""Offline unit tests for the prefix-caching A/B harness
(scripts/benchmark_prefix_caching_ab.py, #711). No GPU, no model, no OpenVINO
runtime needed — the harness guards those imports (same pattern as
test_benchmark_kv_cache_sweep.py).

What these lock, ahead of the daylight GPU window:
  * prompt-builder shapes — S8 block byte-stability across renders, the
    exactly-one-line edit contract, fixed block position, no cross-size or
    cross-angle token-prefix sharing;
  * config/arg parsing (defaults per the LA-approved plan: runs=5, warmup=2,
    cache_size=3, output docs/performance/);
  * the refuse-to-start guard (a real listener socket fakes a held AO port;
    fake process lists fake a live OVMS) and the cleanliness gate;
  * the community-grade JSON schema shape incl. the explicit not_measured
    list, and the PERFORMANCE_LOG-ready summary block.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import benchmark_prefix_caching_ab as ab  # noqa: E402


# ---------------------------------------------------------------------------
# Angle selection / arg parsing
# ---------------------------------------------------------------------------

class TestParseAngles:
    def test_default_spec_selects_all_eight(self):
        assert ab.parse_angles(",".join(ab.ANGLES)) == ab.ANGLES

    def test_subset_returned_in_canonical_order(self):
        assert ab.parse_angles("S8,S1,S3") == ("S1", "S3", "S8")

    def test_case_insensitive_and_whitespace_tolerant(self):
        assert ab.parse_angles(" s1 , S8 ") == ("S1", "S8")

    def test_duplicates_collapse(self):
        assert ab.parse_angles("S1,S1,S1") == ("S1",)

    def test_unknown_angle_raises(self):
        with pytest.raises(ValueError, match="S9"):
            ab.parse_angles("S1,S9")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            ab.parse_angles("  ,  ")


class TestArgParser:
    def test_plan_locked_defaults(self):
        args = ab.build_arg_parser().parse_args([])
        assert args.runs == 5            # plan: N >= 5
        assert args.warmup == 2          # plan: >= 2 discarded
        assert args.cache_size == 3      # production primary
        assert args.output_dir == "docs/performance"
        assert args.angles == ",".join(ab.ANGLES)
        assert args.steady_state is False
        assert args.model_dir == ab.DEFAULT_MODEL_DIR
        assert args.draft_model_dir == ab.DEFAULT_DRAFT_MODEL_DIR

    def test_angles_subset_round_trips_through_parse_angles(self):
        args = ab.build_arg_parser().parse_args(["--angles", "S1,S3"])
        assert ab.parse_angles(args.angles) == ("S1", "S3")

    def test_cache_size_override(self):
        args = ab.build_arg_parser().parse_args(["--cache-size", "8"])
        assert args.cache_size == 8

    def test_runs_override(self):
        args = ab.build_arg_parser().parse_args(["--runs", "7"])
        assert args.runs == 7


# ---------------------------------------------------------------------------
# Aggregation math (median/std/p95 — the plan-locked aggregate shape)
# ---------------------------------------------------------------------------

class TestAggregate:
    def test_basic_shape_includes_p95(self):
        a = ab.aggregate([10.0, 20.0, 30.0])
        assert a["median"] == 20.0
        assert a["mean"] == 20.0
        assert a["n"] == 3
        assert a["std"] > 0
        assert "p95" in a

    def test_p95_linear_interpolation(self):
        # 0..100 in steps of 1: p95 of [0..100] is exactly 95.
        a = ab.aggregate([float(i) for i in range(101)])
        assert a["p95"] == 95.0

    def test_empty_is_zeroed(self):
        assert ab.aggregate([]) == {
            "median": 0.0, "mean": 0.0, "std": 0.0, "p95": 0.0, "n": 0,
        }

    def test_filters_none(self):
        assert ab.aggregate([None, 5.0, None, 7.0])["n"] == 2

    def test_single_value(self):
        a = ab.aggregate([42.0])
        assert a["median"] == 42.0
        assert a["std"] == 0.0
        assert a["p95"] == 42.0


class TestPercentile:
    def test_interpolates_between_points(self):
        assert ab.percentile([0.0, 10.0], 50.0) == 5.0

    def test_empty_is_zero(self):
        assert ab.percentile([], 95.0) == 0.0

    def test_unsorted_input_ok(self):
        assert ab.percentile([30.0, 10.0, 20.0], 100.0) == 30.0


class TestComputeTpot:
    def test_basic(self):
        assert ab.compute_tpot_ms(1000.0, 200.0, 9) == pytest.approx(100.0)

    def test_sentinels(self):
        assert ab.compute_tpot_ms(1000.0, -1.0, 9) == -1.0
        assert ab.compute_tpot_ms(1000.0, 200.0, 1) == -1.0
        assert ab.compute_tpot_ms(100.0, 200.0, 9) == -1.0


# ---------------------------------------------------------------------------
# Prompt builders — S1/S2/S3/S6
# ---------------------------------------------------------------------------

class TestS1Builders:
    def test_prefix_byte_stable_across_renders(self):
        assert ab.build_s1_prefix(3072) == ab.build_s1_prefix(3072)

    def test_all_prompts_share_the_exact_prefix(self):
        prefix = ab.build_s1_prefix(3072)
        for q in ab.build_s1_queries(6):
            assert ab.build_s1_prompt(prefix, q).startswith(prefix)

    def test_queries_are_distinct(self):
        qs = ab.build_s1_queries(12)
        assert len(set(qs)) == 12


class TestS2Builders:
    def test_each_turn_extends_the_previous_prompt(self):
        # The reuse contract prefix caching exploits: prompt_i literally
        # begins with prompt_{i-1} (history grows, prefix stays).
        prompts = ab.build_s2_turns(10, session_tag="t")
        assert len(prompts) == 10
        for prev, cur in zip(prompts, prompts[1:]):
            assert cur.startswith(prev)

    def test_sessions_are_token_disjoint(self):
        a = ab.build_s2_turns(3, session_tag="a")[0]
        b = ab.build_s2_turns(3, session_tag="b")[0]
        assert a.splitlines()[1] != b.splitlines()[1]  # tag line differs

    def test_deterministic(self):
        assert ab.build_s2_turns(5, session_tag="x") == ab.build_s2_turns(5, session_tag="x")

    def test_zero_turns_raises(self):
        with pytest.raises(ValueError):
            ab.build_s2_turns(0)


class TestS3Builders:
    def test_every_prompt_has_a_unique_leading_nonce(self):
        prompts = ab.build_s3_prompts(8)
        first_lines = [p.split("\n", 1)[0] for p in prompts]
        assert len(set(first_lines)) == 8

    def test_pairwise_distinct(self):
        prompts = ab.build_s3_prompts(8)
        assert len(set(prompts)) == 8

    def test_deterministic(self):
        assert ab.build_s3_prompts(4) == ab.build_s3_prompts(4)


class TestS6Builders:
    def test_fixed_set_is_deterministic(self):
        assert ab.build_s6_prompt_set() == ab.build_s6_prompt_set()

    def test_at_least_five_prompts(self):
        assert len(ab.build_s6_prompt_set()) >= 5


# ---------------------------------------------------------------------------
# S8 — the pinned operator-preference-block builders (the new angle)
# ---------------------------------------------------------------------------

class TestS8Block:
    def test_byte_stable_across_renders(self):
        # THE S8 contract: the block is byte-identical on every render — a
        # warm turn re-sends the exact bytes, so a prefix-cache hit is
        # structurally possible.
        for n in ab.S8_BLOCK_SIZES:
            assert ab.build_s8_block(n) == ab.build_s8_block(n)

    def test_all_four_plan_sizes_supported(self):
        assert ab.S8_BLOCK_SIZES == (256, 512, 1024, 2048)

    def test_unknown_size_raises(self):
        with pytest.raises(ValueError):
            ab.build_s8_block(300)

    def test_larger_target_yields_strictly_more_lines(self):
        counts = [len(ab.build_s8_block(n).split("\n")) for n in ab.S8_BLOCK_SIZES]
        assert counts == sorted(counts)
        assert len(set(counts)) == len(counts)

    def test_sizes_never_share_a_token_prefix(self):
        # Cross-size cache hits would corrupt the cost curve: the FIRST line
        # must already differ between any two sizes (size tag baked in).
        firsts = [ab.build_s8_block(n).split("\n", 1)[0] for n in ab.S8_BLOCK_SIZES]
        assert len(set(firsts)) == len(ab.S8_BLOCK_SIZES)


class TestS8Edit:
    def test_edit_changes_exactly_one_line(self):
        for n in ab.S8_BLOCK_SIZES:
            block = ab.build_s8_block(n)
            edited = ab.edit_s8_block(block)
            a = block.split("\n")
            b = edited.split("\n")
            assert len(a) == len(b), "edit must not add/remove lines"
            diffs = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
            assert len(diffs) == 1, f"expected exactly one changed line, got {diffs}"

    def test_edit_is_deterministic(self):
        block = ab.build_s8_block(512)
        assert ab.edit_s8_block(block) == ab.edit_s8_block(block)

    def test_edited_block_differs_from_original(self):
        block = ab.build_s8_block(256)
        assert ab.edit_s8_block(block) != block

    def test_edit_position_is_fixed_mid_block(self):
        block = ab.build_s8_block(1024)
        lines = block.split("\n")
        edited_lines = ab.edit_s8_block(block).split("\n")
        k = len(lines) // 2
        assert lines[k] != edited_lines[k]


class TestS8Prompt:
    def test_block_sits_at_a_fixed_early_position(self):
        # The block's byte offset is constant: len(preamble), every render,
        # every query — the FIXED-early-position requirement of the angle.
        preamble = ab.s8_preamble()
        for n in ab.S8_BLOCK_SIZES:
            block = ab.build_s8_block(n)
            for query in ("q one", "another q"):
                prompt = ab.build_s8_prompt(block, query)
                assert prompt.startswith(preamble)
                assert prompt.index(block) == len(preamble)

    def test_warm_prompts_share_the_full_block_prefix(self):
        block = ab.build_s8_block(512)
        p1 = ab.build_s8_prompt(block, "warm turn 0")
        p2 = ab.build_s8_prompt(block, "warm turn 1")
        shared = ab.s8_preamble() + block
        assert p1.startswith(shared) and p2.startswith(shared)
        assert p1 != p2


# ---------------------------------------------------------------------------
# Refuse-to-start guard + cleanliness gate
# ---------------------------------------------------------------------------

class TestRefuseToStartGuard:
    def test_held_ao_port_is_a_reason(self):
        # Fake the AO with a REAL listener on an ephemeral port.
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            reasons = ab.gpu_hold_reasons(ao_port=port, process_names=[])
            assert len(reasons) == 1
            assert str(port) in reasons[0]
            assert "AO" in reasons[0]
        finally:
            listener.close()

    def test_free_port_and_no_ovms_is_clear(self):
        # Grab a free ephemeral port number, release it, probe it.
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        assert ab.gpu_hold_reasons(ao_port=port, process_names=[]) == []

    def test_ovms_process_is_a_reason(self):
        reasons = ab.gpu_hold_reasons(
            ao_port=1,  # unused
            process_names=["python.exe", "ovms.exe"],
            port_probe=lambda _p: False,
        )
        assert len(reasons) == 1
        assert "ovms.exe" in reasons[0]

    def test_ovms_match_is_case_insensitive(self):
        assert ab.ovms_process_names(["OVMS.EXE", "notepad.exe"]) == ["OVMS.EXE"]

    def test_both_conditions_yield_two_reasons(self):
        reasons = ab.gpu_hold_reasons(
            ao_port=1,
            process_names=["ovms.exe"],
            port_probe=lambda _p: True,
        )
        assert len(reasons) == 2

    def test_main_refuses_and_exits_2_when_gpu_held(self, monkeypatch):
        # The harness must FAIL LOUD (exit 2) without touching any model
        # machinery when the AO/app appears to hold the GPU.
        monkeypatch.setattr(
            ab, "gpu_hold_reasons",
            lambda *a, **k: ["port 5001 (AO loopback) is responding — fake"],
        )
        assert ab.main([]) == 2

    def test_ao_port_constant_matches_the_canonical_5001(self):
        # = launcher.__main__.ORCHESTRATOR_HOST_LOOPBACK_PORT (see the
        # conftest.py leak-detector precedent for hardcoding + pointer).
        assert ab.AO_LOOPBACK_PORT == 5001


class TestCleanlinessGate:
    def test_below_floor_returns_reason(self):
        reason = ab.cleanliness_gate(10.0, 20.0)
        assert reason is not None
        assert "10.0" in reason

    def test_at_or_above_floor_is_clear(self):
        assert ab.cleanliness_gate(20.0, 20.0) is None
        assert ab.cleanliness_gate(28.5, 20.0) is None


# ---------------------------------------------------------------------------
# JSON schema shape + summary block
# ---------------------------------------------------------------------------

def _sample_output() -> dict:
    config = {
        "angles": ["S1", "S8"], "runs": 5, "warmup": 2, "cache_size": 3,
        "gen_tokens": 128, "s2_turns": 10, "s5_gen_tokens": 256,
        "prefix_tokens": 3072, "cooldown_s": 120.0, "steady_state": False,
        "model_dir": "models/qwen3-14b/openvino-int4-gpu",
        "draft_model_dir": "models/qwen3-0.6b-pruned-6l/openvino-int8-gpu",
    }
    env = {
        "cpu": "Intel Core Ultra 7 258V", "gpu": "Arc 140V",
        "gpu_driver": "32.0.x", "openvino_version": "2026.2.1",
        "openvino_genai_version": "2026.2.1", "total_ram_gib": 31.6,
        "mem_ceiling_gib": 31.323,
    }
    results = [
        {
            "angle": "S1", "description": ab.ANGLE_DESCRIPTIONS["S1"],
            "off": {"ttft_cold_first_ms": 900.0,
                    "ttft_warm_ms": ab.aggregate([850.0, 860.0, 870.0])},
            "on": {"ttft_cold_first_ms": 910.0,
                   "ttft_warm_ms": ab.aggregate([420.0, 430.0, 440.0])},
        },
        {
            "angle": "S8", "description": ab.ANGLE_DESCRIPTIONS["S8"],
            "off": {"error": "RuntimeError: boom"},
            "on": {"sizes": []},
        },
    ]
    return ab.assemble_output(
        config=config, environment=env, results=results,
        not_measured=ab.default_not_measured(["S1", "S8"], steady_state=False),
    )


class TestOutputSchema:
    REQUIRED_TOP_LEVEL = (
        "harness", "schema_version", "plan", "vikunja", "generated_utc",
        "environment", "methodology", "config", "results", "not_measured",
    )

    def test_required_top_level_keys(self):
        out = _sample_output()
        for key in self.REQUIRED_TOP_LEVEL:
            assert key in out, f"missing top-level key {key!r}"

    def test_identity_fields(self):
        out = _sample_output()
        assert out["harness"] == "prefix_caching_ab"
        assert out["plan"].endswith("prefix_caching_ab_validation_plan.md")
        assert out["vikunja"] == "#711"

    def test_not_measured_is_a_nonempty_list_of_strings(self):
        out = _sample_output()
        assert isinstance(out["not_measured"], list)
        assert out["not_measured"], "not_measured must never be empty (honest-coverage mandate)"
        assert all(isinstance(x, str) for x in out["not_measured"])

    def test_methodology_names_the_per_arm_flip_and_the_seam(self):
        m = _sample_output()["methodology"]
        assert "PER ARM" in m["ab_protocol"]
        assert "build_shared_pipeline" in m["pipeline"]

    def test_memory_caveat_carried(self):
        m = _sample_output()["methodology"]
        assert "blind" in m["memory_instruments"]["caveat"]

    def test_json_serializable(self):
        import json
        json.dumps(_sample_output())


class TestDefaultNotMeasured:
    def test_hit_savings_caveat_always_present(self):
        nm = ab.default_not_measured(list(ab.ANGLES), steady_state=True)
        assert any("blind" in x for x in nm)

    def test_unselected_angles_are_named(self):
        nm = ab.default_not_measured(["S1"], steady_state=False)
        assert any("S2" in x and "not selected" in x for x in nm)

    def test_s7_sdxl_pairing_named_when_s7_selected(self):
        nm = ab.default_not_measured(["S7"], steady_state=False)
        assert any("SDXL" in x for x in nm)

    def test_steady_state_gap_named_when_not_run(self):
        nm = ab.default_not_measured(["S1"], steady_state=False)
        assert any("steady-state" in x for x in nm)
        nm2 = ab.default_not_measured(["S1"], steady_state=True)
        assert not any("--steady-state" in x for x in nm2)


class TestFormatSummary:
    def test_summary_contains_angles_and_arms(self):
        text = ab.format_summary(_sample_output())
        assert "PERFORMANCE_LOG-ready summary" in text
        assert "S1" in text and "S8" in text
        assert "OFF:" in text and "ON :" in text

    def test_summary_surfaces_arm_errors_loudly(self):
        text = ab.format_summary(_sample_output())
        assert "ERROR: RuntimeError: boom" in text

    def test_summary_lists_not_measured(self):
        text = ab.format_summary(_sample_output())
        assert "Not measured:" in text

    def test_summary_carries_medians(self):
        text = ab.format_summary(_sample_output())
        assert "med=430.0" in text  # the ON warm median from the sample


class TestPostProcess:
    def test_s1_warm_ratio_computed(self):
        rec = {
            "angle": "S1",
            "off": {"ttft_warm_ms": ab.aggregate([800.0, 820.0, 840.0])},
            "on": {"ttft_warm_ms": ab.aggregate([400.0, 410.0, 420.0])},
        }
        ab._post_process("S1", rec)
        assert rec["warm_ttft_on_over_off"] == pytest.approx(0.5, abs=0.01)

    def test_s6_identical_outputs_flagged_true(self):
        off = {"outputs": [{"prompt_index": 0, "sha256": "aa"},
                           {"prompt_index": 1, "sha256": "bb"}]}
        on = {"outputs": [{"prompt_index": 0, "sha256": "aa"},
                          {"prompt_index": 1, "sha256": "bb"}]}
        rec = {"angle": "S6", "off": off, "on": on}
        ab._post_process("S6", rec)
        assert rec["outputs_identical"] is True

    def test_s6_drift_flagged_false(self):
        off = {"outputs": [{"prompt_index": 0, "sha256": "aa"}]}
        on = {"outputs": [{"prompt_index": 0, "sha256": "zz"}]}
        rec = {"angle": "S6", "off": off, "on": on}
        ab._post_process("S6", rec)
        assert rec["outputs_identical"] is False

    def test_errored_arm_skips_derivations(self):
        rec = {"angle": "S6", "off": {"error": "x"}, "on": {"outputs": []}}
        ab._post_process("S6", rec)
        assert "outputs_identical" not in rec


# ---------------------------------------------------------------------------
# Module import hygiene
# ---------------------------------------------------------------------------

def test_angle_registry_covers_all_angles():
    assert set(ab._ANGLE_RUNNERS) == set(ab.ANGLES)
    assert set(ab.ANGLE_DESCRIPTIONS) == set(ab.ANGLES)


def test_module_importable_without_openvino():
    # The guarded-import contract: this test file imported the module on
    # whatever machine runs the standing gate; the pure helpers must work
    # even when ov/ov_genai are None.
    assert hasattr(ab, "build_s8_block")
