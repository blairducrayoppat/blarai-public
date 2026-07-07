"""Unit tests for the pure logic of the KV-cache precision sweep harness
(scripts/benchmark_kv_cache_sweep.py). These cover the sizing/aggregation math
that the long-context fix (Vikunja #709) depends on — no GPU, no model, no
OpenVINO runtime needed (the harness guards those imports).

The live sweep itself is hardware-gated and not exercised here; what we lock is
that cache_size can never regress to the starving production value, that the
analytical KV math matches Qwen3-14B geometry, and that precision/aggregation
helpers behave.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import benchmark_kv_cache_sweep as kv  # noqa: E402

# Qwen3-14B geometry (verified 2026-06-29): 40 layers, 8 KV heads, 128 head_dim.
GEOM = {"num_hidden_layers": 40, "num_key_value_heads": 8, "head_dim": 128}


class TestAnalyticalKv:
    def test_fp16_16k_is_exactly_2p5_gib(self):
        # 2 * 40 * 8 * 128 * 2 bytes/token * 16384 tokens = 2.5 GiB exactly.
        assert kv.analytical_kv_gib(16384, "fp16_unset", GEOM) == pytest.approx(2.5)

    def test_fp16_32k_is_exactly_5_gib(self):
        assert kv.analytical_kv_gib(32768, "fp16_unset", GEOM) == pytest.approx(5.0)

    def test_int8_is_half_of_fp16(self):
        assert kv.analytical_kv_gib(32768, "u8", GEOM) == pytest.approx(2.5)

    def test_int4_is_quarter_of_fp16(self):
        assert kv.analytical_kv_gib(32768, "u4", GEOM) == pytest.approx(1.25)

    def test_unknown_precision_raises(self):
        with pytest.raises(ValueError):
            kv.analytical_kv_gib(16384, "bogus", GEOM)


class TestSizeCache:
    def test_32k_fp16_never_starves_at_3gb(self):
        # The whole point of #709: 32K FP16 (5.0 GiB analytical) must get a budget
        # well above the production cache_size=3 that caused the 310s pathology.
        cache = kv.size_cache_gb(32768, "fp16_unset", GEOM)
        assert cache > 3
        assert cache >= kv.analytical_kv_gib(32768, "fp16_unset", GEOM)  # holds the full prompt

    def test_32k_fp16_is_8gb(self):
        # ceil(5.0 * 1.5) = 8
        assert kv.size_cache_gb(32768, "fp16_unset", GEOM) == 8

    def test_16k_fp16_is_4gb(self):
        # ceil(2.5 * 1.5) = ceil(3.75) = 4
        assert kv.size_cache_gb(16384, "fp16_unset", GEOM) == 4

    def test_small_need_clamps_to_floor(self):
        # 16K INT4 analytical = 0.625 GiB; *1.5 = 0.94 -> floor wins (4).
        assert kv.size_cache_gb(16384, "u4", GEOM) == kv._CACHE_FLOOR_GB

    def test_sizing_is_monotonic_in_context(self):
        a = kv.size_cache_gb(16384, "fp16_unset", GEOM)
        b = kv.size_cache_gb(32768, "fp16_unset", GEOM)
        assert b >= a


class TestKvPrecisionProps:
    def test_fp16_unset_sets_nothing(self):
        assert kv.kv_precision_props("fp16_unset") == {}

    def test_int8(self):
        assert kv.kv_precision_props("u8") == {"KV_CACHE_PRECISION": "u8"}

    def test_int4(self):
        assert kv.kv_precision_props("u4") == {"KV_CACHE_PRECISION": "u4"}

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            kv.kv_precision_props("bogus")


class TestMemStatsDelta:
    def test_per_key_subtraction(self):
        before = {"usm_device": 1000, "usm_host": 50, "cl_mem": 0, "unknown": 0, "usm_shared": 0}
        after = {"usm_device": 3500, "usm_host": 50, "cl_mem": 0, "unknown": 0, "usm_shared": 0}
        d = kv.mem_stats_delta(before, after)
        assert d["usm_device"] == 2500
        assert d["usm_host"] == 0

    def test_missing_keys_default_zero(self):
        d = kv.mem_stats_delta({}, {"usm_device": 42})
        assert d["usm_device"] == 42
        assert d["usm_host"] == 0
        assert set(d) == set(kv._GPU_MEM_KEYS)


class TestAggregate:
    def test_basic(self):
        a = kv.aggregate([10.0, 20.0, 30.0])
        assert a["median"] == 20.0
        assert a["mean"] == 20.0
        assert a["n"] == 3
        assert a["std"] > 0

    def test_empty_is_zeroed(self):
        a = kv.aggregate([])
        assert a == {"median": 0.0, "mean": 0.0, "std": 0.0, "n": 0}

    def test_filters_none(self):
        a = kv.aggregate([None, 5.0, None, 7.0])
        assert a["n"] == 2

    def test_single_value_zero_std(self):
        a = kv.aggregate([42.0])
        assert a["std"] == 0.0
        assert a["median"] == 42.0


class TestComputeTpot:
    def test_basic(self):
        # total 1000ms, ttft 200ms, 9 tokens -> (1000-200)/(9-1) = 100ms/tok
        assert kv.compute_tpot_ms(1000.0, 200.0, 9) == pytest.approx(100.0)

    def test_no_first_token_sentinel(self):
        assert kv.compute_tpot_ms(1000.0, -1.0, 9) == -1.0

    def test_single_token_sentinel(self):
        assert kv.compute_tpot_ms(1000.0, 200.0, 1) == -1.0

    def test_total_less_than_ttft_sentinel(self):
        assert kv.compute_tpot_ms(100.0, 200.0, 9) == -1.0


class TestLoadGeometry:
    def test_fallback_on_missing_config(self):
        geom = kv.load_geometry("/no/such/model/dir")
        assert geom == kv._GEOM_FALLBACK

    def test_reads_real_model_config_if_present(self):
        model_dir = _REPO_ROOT / "models" / "qwen3-14b" / "openvino-int4-gpu"
        if not (model_dir / "config.json").exists():
            pytest.skip("14B model config.json not present in this checkout")
        geom = kv.load_geometry(model_dir)
        assert geom["num_hidden_layers"] == 40
        assert geom["num_key_value_heads"] == 8
        assert geom["head_dim"] == 128


def test_precisions_constant_matches_bytes_table():
    # Guard: every swept precision has a bytes-per-element entry and vice versa.
    assert set(kv.PRECISIONS) == set(kv._PREC_BYTES)
