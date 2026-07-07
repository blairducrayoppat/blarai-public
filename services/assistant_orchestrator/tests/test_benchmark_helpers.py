"""
Benchmark Helper Unit Tests
============================
Tests for the pure helper functions in ``scripts/benchmark_gpu_inference.py``:
  - Statistics: compute_mean, compute_median, compute_p95
  - Throughput calculation: tokens_per_sec
  - Markdown entry formatting: format_markdown_entry

No GPU, no model loading, no mock of OrchestratorGPUInference.
The model-loading path is intentionally excluded — it requires real hardware.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Import helpers from scripts/benchmark_gpu_inference.py without executing
# its __main__ block or requiring openvino/gpu_inference to be installed.
# We load the module via importlib so pytest's importlib mode is respected.
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scripts"
_BENCH_PATH = _SCRIPTS_DIR / "benchmark_gpu_inference.py"


def _load_benchmark_module() -> object:
    """Load benchmark_gpu_inference as a module, tolerating missing optional deps."""
    spec = importlib.util.spec_from_file_location(
        "benchmark_gpu_inference", str(_BENCH_PATH)
    )
    if spec is None or spec.loader is None:
        pytest.skip(f"Cannot locate benchmark script at {_BENCH_PATH}")
    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules BEFORE exec_module so that dataclass field-type
    # resolution (which looks up cls.__module__ in sys.modules) succeeds.
    sys.modules["benchmark_gpu_inference"] = module
    try:
        spec.loader.exec_module(module)  # type: ignore[attr-defined]
    except (ImportError, SystemExit) as exc:
        # ImportError: openvino / openvino_genai not installed in test env.
        # SystemExit: only if sys.exit() is called at module level (it isn't).
        sys.modules.pop("benchmark_gpu_inference", None)
        pytest.skip(f"Skipping — cannot import benchmark module: {exc}")
    return module


_bench = _load_benchmark_module()

compute_mean = getattr(_bench, "compute_mean")
compute_median = getattr(_bench, "compute_median")
compute_p95 = getattr(_bench, "compute_p95")
tokens_per_sec = getattr(_bench, "tokens_per_sec")
prefill_tokens_per_sec = getattr(_bench, "prefill_tokens_per_sec")
format_markdown_entry = getattr(_bench, "format_markdown_entry")
AggregateStats = getattr(_bench, "AggregateStats")
SingleRunMetrics = getattr(_bench, "SingleRunMetrics")
aggregate = getattr(_bench, "aggregate")
PrefillStats = getattr(_bench, "PrefillStats")
PrefillRunMetrics = getattr(_bench, "PrefillRunMetrics")
aggregate_prefill = getattr(_bench, "aggregate_prefill")
_derive_model_name = getattr(_bench, "_derive_model_name")


# ---------------------------------------------------------------------------
# Statistics: compute_mean
# ---------------------------------------------------------------------------


class TestComputeMean:
    def test_simple_values(self) -> None:
        assert compute_mean([10.0, 20.0, 30.0]) == pytest.approx(20.0)

    def test_single_value(self) -> None:
        assert compute_mean([42.0]) == pytest.approx(42.0)

    def test_empty_returns_zero(self) -> None:
        assert compute_mean([]) == pytest.approx(0.0)

    def test_float_precision(self) -> None:
        result = compute_mean([1.1, 2.2, 3.3])
        assert result == pytest.approx(2.2, rel=1e-6)


# ---------------------------------------------------------------------------
# Statistics: compute_median
# ---------------------------------------------------------------------------


class TestComputeMedian:
    def test_odd_count(self) -> None:
        assert compute_median([3.0, 1.0, 2.0]) == pytest.approx(2.0)

    def test_even_count(self) -> None:
        # Median of [1, 2, 3, 4] = 2.5
        assert compute_median([4.0, 1.0, 3.0, 2.0]) == pytest.approx(2.5)

    def test_single_value(self) -> None:
        assert compute_median([7.5]) == pytest.approx(7.5)

    def test_empty_returns_zero(self) -> None:
        assert compute_median([]) == pytest.approx(0.0)

    def test_identical_values(self) -> None:
        assert compute_median([5.0, 5.0, 5.0]) == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# Statistics: compute_p95
# ---------------------------------------------------------------------------


class TestComputeP95:
    def test_single_value(self) -> None:
        # P95 of a single element is that element.
        assert compute_p95([100.0]) == pytest.approx(100.0)

    def test_empty_returns_zero(self) -> None:
        assert compute_p95([]) == pytest.approx(0.0)

    def test_twenty_values_sorted(self) -> None:
        # With 20 values [1..20], ceil(0.95 * 20) = 19, so P95 = 19.
        data = [float(i) for i in range(1, 21)]
        assert compute_p95(data) == pytest.approx(19.0)

    def test_unsorted_input(self) -> None:
        # P95 should work regardless of input order.
        data = [10.0, 5.0, 1.0, 8.0, 3.0]
        # sorted: [1, 3, 5, 8, 10]. ceil(0.95*5)=5 -> index 4 -> 10.0
        assert compute_p95(data) == pytest.approx(10.0)

    def test_two_values(self) -> None:
        # ceil(0.95 * 2) = 2, index 1 -> max value
        assert compute_p95([1.0, 100.0]) == pytest.approx(100.0)

    def test_all_same(self) -> None:
        assert compute_p95([42.0, 42.0, 42.0]) == pytest.approx(42.0)


# ---------------------------------------------------------------------------
# tokens_per_sec
# ---------------------------------------------------------------------------


class TestTokensPerSec:
    def test_basic(self) -> None:
        # 100 tokens in 2000ms = 50 tok/s
        assert tokens_per_sec(100, 2000.0) == pytest.approx(50.0)

    def test_zero_latency_returns_zero(self) -> None:
        assert tokens_per_sec(100, 0.0) == pytest.approx(0.0)

    def test_zero_tokens(self) -> None:
        assert tokens_per_sec(0, 1000.0) == pytest.approx(0.0)

    def test_negative_latency_returns_zero(self) -> None:
        # Negative latency is a guard case — should not produce a value.
        assert tokens_per_sec(100, -500.0) == pytest.approx(0.0)

    def test_fractional(self) -> None:
        # 3 tokens in 500ms = 6.0 tok/s
        assert tokens_per_sec(3, 500.0) == pytest.approx(6.0, rel=1e-6)


# ---------------------------------------------------------------------------
# aggregate
# ---------------------------------------------------------------------------


def _make_run(
    tok: int = 100,
    ttft: float = 500.0,
    total: float = 2000.0,
    err: str | None = None,
    p_idx: int = 0,
) -> object:
    tps = (tok / (total / 1000.0)) if total > 0 and err is None else 0.0
    return SingleRunMetrics(
        prompt_index=p_idx,
        token_count=tok,
        latency_first_token_ms=ttft,
        latency_total_ms=total,
        throughput_tok_per_sec=tps,
        error=err,
    )


class TestAggregate:
    def test_all_good(self) -> None:
        runs = [_make_run(100, 500.0, 2000.0), _make_run(200, 600.0, 3000.0)]
        stats = aggregate(runs)
        assert stats.total_runs == 2
        assert stats.error_runs == 0
        assert stats.mean_tps == pytest.approx(
            compute_mean([50.0, 200.0 / 3.0]), rel=1e-4
        )

    def test_with_error_run(self) -> None:
        runs = [
            _make_run(100, 500.0, 2000.0),
            _make_run(0, 0.0, 0.0, err="Model not loaded"),
        ]
        stats = aggregate(runs)
        assert stats.total_runs == 2
        assert stats.error_runs == 1
        # Only the good run contributes to statistics.
        assert stats.mean_tps == pytest.approx(50.0)

    def test_all_errors(self) -> None:
        runs = [
            _make_run(0, 0.0, 0.0, err="err1"),
            _make_run(0, 0.0, 0.0, err="err2"),
        ]
        stats = aggregate(runs)
        assert stats.total_runs == 2
        assert stats.error_runs == 2
        assert stats.mean_tps == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# format_markdown_entry
# ---------------------------------------------------------------------------


def _make_stats(
    tps: float = 40.0,
    ttft: float = 800.0,
    total: float = 5000.0,
) -> object:
    return AggregateStats(
        mean_tps=tps,
        median_tps=tps,
        p95_tps=tps * 0.8,
        mean_ttft_ms=ttft,
        median_ttft_ms=ttft,
        p95_ttft_ms=ttft * 1.2,
        mean_total_ms=total,
        median_total_ms=total,
        p95_total_ms=total * 1.1,
        total_runs=10,
        error_runs=0,
    )


class TestFormatMarkdownEntry:
    """format_markdown_entry produces a well-formed Markdown section."""

    def _stamp(self) -> dict[str, object]:
        return {
            "model_name": "Qwen3-14B",
            "model_dir": "models/qwen3-14b/openvino-int4-gpu",
            "quantization": "INT4",
            "device": "GPU",
            "openvino_version": "2025.0",
            "openvino_genai_version": "2025.0",
            "num_assistant_tokens": 3,
            "draft_model_dir": "models/qwen3-0.6b/openvino-int4-gpu",
            "driver_version": "31.0.101.6122",
            "prompt_set_version": "v1",
        }

    def _entry(self) -> str:
        result = format_markdown_entry(
            timestamp="2026-05-21T14:30:00",
            config_stamp=self._stamp(),
            spec_off_stats=_make_stats(),
            spec_off_load_ms=45000.0,
            spec_on_stats=_make_stats(tps=55.0),
            spec_on_load_ms=60000.0,
            spec_off_achieved=False,
            spec_on_achieved=True,
            num_runs=5,
            num_warmup=2,
        )
        return str(result)

    def test_returns_string(self) -> None:
        assert isinstance(self._entry(), str)

    def test_contains_date(self) -> None:
        assert "2026-05-21" in self._entry()

    def test_contains_model_name(self) -> None:
        assert "Qwen3-14B" in self._entry()

    def test_contains_spec_achieved_labels(self) -> None:
        entry = self._entry()
        # spec-off config achieved=False -> "achieved: off"
        assert "achieved: off" in entry
        # spec-on config achieved=True -> "achieved: on"
        assert "achieved: on" in entry

    def test_contains_throughput_values(self) -> None:
        entry = self._entry()
        # spec_off tps=40.0 should appear
        assert "40.0" in entry
        # spec_on tps=55.0 should appear
        assert "55.0" in entry

    def test_contains_config_stamp_fields(self) -> None:
        entry = self._entry()
        assert "INT4" in entry
        assert "GPU" in entry
        assert "2025.0" in entry

    def test_contains_load_time(self) -> None:
        entry = self._entry()
        # 45000 ms -> "45000" in the entry
        assert "45000" in entry

    def test_no_fake_placeholder_metrics(self) -> None:
        # The template uses explicit placeholder strings; the formatter should
        # not emit them when real stats are passed.
        entry = self._entry()
        assert "XX.X" not in entry
        assert "XXXX" not in entry

    def test_markdown_table_structure(self) -> None:
        entry = self._entry()
        # At least one markdown table row separator must be present.
        assert "|--------|" in entry or "|-------|" in entry

    def test_spec_on_fallback_label(self) -> None:
        # When spec_on_achieved=False, label should say "off (fallback)".
        entry = format_markdown_entry(
            timestamp="2026-05-21T14:30:00",
            config_stamp=self._stamp(),
            spec_off_stats=_make_stats(),
            spec_off_load_ms=45000.0,
            spec_on_stats=_make_stats(),
            spec_on_load_ms=60000.0,
            spec_off_achieved=False,
            spec_on_achieved=False,
            num_runs=5,
            num_warmup=2,
        )
        assert "off (fallback)" in entry


# ---------------------------------------------------------------------------
# prefill_tokens_per_sec (pp / prompt-processing throughput)
# ---------------------------------------------------------------------------


class TestPrefillTokensPerSec:
    def test_basic(self) -> None:
        # 512 input tokens prefilled in 1000ms = 512 tok/s
        assert prefill_tokens_per_sec(512, 1000.0) == pytest.approx(512.0)

    def test_fractional(self) -> None:
        # 480 tokens in 1500ms = 320 tok/s
        assert prefill_tokens_per_sec(480, 1500.0) == pytest.approx(320.0, rel=1e-6)

    def test_zero_time_returns_zero(self) -> None:
        assert prefill_tokens_per_sec(512, 0.0) == pytest.approx(0.0)

    def test_negative_time_returns_zero(self) -> None:
        assert prefill_tokens_per_sec(512, -10.0) == pytest.approx(0.0)

    def test_unmeasured_token_count_returns_zero(self) -> None:
        # -1 (uncounted) must not produce a misleading rate.
        assert prefill_tokens_per_sec(-1, 1000.0) == pytest.approx(0.0)

    def test_zero_tokens_returns_zero(self) -> None:
        assert prefill_tokens_per_sec(0, 1000.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# aggregate_prefill
# ---------------------------------------------------------------------------


def _make_prefill_run(
    tokens: int = 500,
    prefill_ms: float = 1000.0,
    err: str | None = None,
) -> object:
    pp = (
        (tokens / (prefill_ms / 1000.0))
        if tokens > 0 and prefill_ms > 0 and err is None
        else 0.0
    )
    return PrefillRunMetrics(
        input_tokens=tokens,
        prefill_ms=prefill_ms,
        prefill_tok_per_sec=pp,
        error=err,
    )


class TestAggregatePrefill:
    def test_all_good(self) -> None:
        # 500 tok/1000ms = 500 pp ; 600 tok/1000ms = 600 pp -> mean 550
        runs = [_make_prefill_run(500, 1000.0), _make_prefill_run(600, 1000.0)]
        stats = aggregate_prefill(runs)
        assert stats.measured is True
        assert stats.total_runs == 2
        assert stats.error_runs == 0
        assert stats.mean_pp == pytest.approx(550.0)
        assert stats.mean_input_tokens == pytest.approx(550.0)

    def test_error_run_excluded(self) -> None:
        runs = [_make_prefill_run(500, 1000.0), _make_prefill_run(0, 0.0, err="boom")]
        stats = aggregate_prefill(runs)
        assert stats.measured is True
        assert stats.total_runs == 2
        assert stats.error_runs == 1
        assert stats.mean_pp == pytest.approx(500.0)

    def test_uncounted_tokens_not_measured(self) -> None:
        # input_tokens = -1 (tokenizer absent) -> no usable run -> measured False
        runs = [_make_prefill_run(-1, 1000.0), _make_prefill_run(-1, 1200.0)]
        stats = aggregate_prefill(runs)
        assert stats.measured is False
        assert stats.error_runs == 2

    def test_empty_not_measured(self) -> None:
        stats = aggregate_prefill([])
        assert stats.measured is False
        assert stats.total_runs == 0


# ---------------------------------------------------------------------------
# _derive_model_name
# ---------------------------------------------------------------------------


class TestDeriveModelName:
    def test_models_layout_8b(self) -> None:
        assert (
            _derive_model_name("/x/blarai/models/qwen3-8b/openvino-int4-gpu")
            == "qwen3-8b"
        )

    def test_models_layout_14b(self) -> None:
        assert (
            _derive_model_name("models/qwen3-14b/openvino-int4-gpu") == "qwen3-14b"
        )

    def test_fallback_to_parent(self) -> None:
        # No 'models' segment -> parent directory name.
        assert _derive_model_name("/opt/weights/qwen3-8b/ov") == "qwen3-8b"


# ---------------------------------------------------------------------------
# format_markdown_entry — prefill (pp) row
# ---------------------------------------------------------------------------


class TestFormatMarkdownEntryPrefill:
    def _pp(self, measured: bool = True) -> object:
        return PrefillStats(
            mean_pp=300.0,
            median_pp=310.0,
            p95_pp=290.0,
            mean_input_tokens=480.0,
            total_runs=5,
            error_runs=0,
            measured=measured,
        )

    def _stamp(self) -> dict[str, object]:
        return {
            "model_name": "qwen3-8b",
            "model_dir": "models/qwen3-8b/openvino-int4-gpu",
            "quantization": "INT4",
            "device": "GPU",
            "openvino_version": "2026.2",
            "openvino_genai_version": "2026.2",
            "num_assistant_tokens": 3,
            "draft_model_dir": "models/qwen3-0.6b/openvino-int4-gpu",
            "driver_version": "32.0.101.8826",
            "prompt_set_version": "v1",
        }

    def test_pp_row_present_when_measured(self) -> None:
        entry = format_markdown_entry(
            timestamp="2026-06-27T10:00:00",
            config_stamp=self._stamp(),
            spec_off_stats=_make_stats(),
            spec_off_load_ms=18000.0,
            spec_on_stats=_make_stats(tps=14.0),
            spec_on_load_ms=18000.0,
            spec_off_achieved=False,
            spec_on_achieved=True,
            num_runs=5,
            num_warmup=2,
            spec_off_prefill=self._pp(),
            spec_on_prefill=self._pp(),
        )
        assert "Prefill pp (tok/s)" in entry
        assert "300.0" in entry  # mean pp
        assert "llama-bench pp512" in entry  # method note

    def test_pp_row_absent_when_not_provided(self) -> None:
        # Backward-compat: existing callers pass no prefill -> no pp row.
        entry = format_markdown_entry(
            timestamp="2026-06-27T10:00:00",
            config_stamp=self._stamp(),
            spec_off_stats=_make_stats(),
            spec_off_load_ms=18000.0,
            spec_on_stats=_make_stats(),
            spec_on_load_ms=18000.0,
            spec_off_achieved=False,
            spec_on_achieved=True,
            num_runs=5,
            num_warmup=2,
        )
        assert "Prefill pp (tok/s)" not in entry

    def test_pp_row_absent_when_unmeasured(self) -> None:
        entry = format_markdown_entry(
            timestamp="2026-06-27T10:00:00",
            config_stamp=self._stamp(),
            spec_off_stats=_make_stats(),
            spec_off_load_ms=18000.0,
            spec_on_stats=_make_stats(),
            spec_on_load_ms=18000.0,
            spec_off_achieved=False,
            spec_on_achieved=True,
            num_runs=5,
            num_warmup=2,
            spec_off_prefill=self._pp(measured=False),
            spec_on_prefill=self._pp(measured=False),
        )
        assert "Prefill pp (tok/s)" not in entry
