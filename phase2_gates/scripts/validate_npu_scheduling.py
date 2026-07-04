"""
VALIDATE_NPU_SCHEDULING — Phase 2 Day-1 Empirical Gate
=======================================================
Red Team Issue: ISSUE-002
Affected Use Cases: [001], [002], [004]

Empirically characterizes the Intel NPU's concurrent scheduling behavior
on the Lunar Lake SoC (Intel Core Ultra 7 258V) to determine whether
dual-model inference (Policy Agent 1.7B INT4 + Orchestrator 1.7B INT4)
is feasible within defined latency budgets.

Requirements:
  - OpenVINO Runtime (pip install openvino)
  - psutil (pip install psutil)
  - A 1.7B INT4 ONNX/OpenVINO IR model (path configured below)
  - Physical Lunar Lake hardware with Intel NPU

Execution:
  python validate_npu_scheduling.py --model-path <path_to_ir_model_dir>

Outputs:
  phase2_gates/evidence/npu_scheduling_report.json

Failure Fingerprinting:
  All failures are captured in structured JSON with disposition and
  escalation instructions. Branch is NEVER deleted on failure.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EFFECTIVE_CEILING_GB: float = 31.323  # Empirical — ADR-005 (was 31.5)
NUM_ITERATIONS: int = 100
PREEMPTION_ITERATIONS: int = 50
POLICY_AGENT_SEQ_LEN: int = 512
ORCHESTRATOR_SEQ_LEN: int = 1024
WARMUP_ITERATIONS: int = 5

# Latency targets (milliseconds) from Use Cases_FINAL.md
PREEMPTION_P95_TARGET_MS: float = 200.0
PREEMPTION_P99_TARGET_MS: float = 500.0
ORCHESTRATOR_RESUME_TARGET_MS: float = 500.0
KV_CACHE_RECONSTRUCT_TARGET_MS: float = 500.0
CONCURRENT_THROUGHPUT_RATIO_MIN: float = 0.60  # 60% of single-model baseline

EVIDENCE_DIR = Path(__file__).resolve().parent.parent / "evidence"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _percentile(data: list[float], p: int) -> float:
    """Return the p-th percentile of a sorted list."""
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * p / 100
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_data) else f
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


def _failure_record(
    gate: str,
    test_id: str,
    metric: str,
    expected: str,
    actual: str,
    disposition: str = "FAIL",
) -> dict[str, Any]:
    return {
        "gate": gate,
        "timestamp": _timestamp(),
        "test_id": test_id,
        "metric": metric,
        "expected": expected,
        "actual": actual,
        "disposition": disposition,
        "escalation": "Lead Architect decision required",
        "branch_preserved": "feature/phase2-scaffolding",
        "evidence_path": str(EVIDENCE_DIR / "npu_scheduling_report.json"),
    }


# ---------------------------------------------------------------------------
# NPU Inference Harness
# ---------------------------------------------------------------------------


def _load_model(core: Any, model_path: str, device: str = "NPU") -> tuple[Any, Any]:
    """Compile an OpenVINO IR model for the given device and return (compiled_model, input_shape)."""
    import openvino as ov  # type: ignore[import-untyped]

    model = core.read_model(model=model_path)
    compiled = core.compile_model(model, device)
    input_layer = compiled.input(0)
    return compiled, input_layer.shape


def _create_synthetic_input(shape: tuple[int, ...], seq_len: int) -> Any:
    """Create a synthetic input tensor of the given sequence length."""
    import numpy as np  # type: ignore[import-untyped]

    # Shape is typically (batch, seq_len) for text models — adjust last dim
    adjusted = list(shape)
    if len(adjusted) >= 2:
        adjusted[-1] = seq_len
    return np.random.randint(0, 30000, size=adjusted, dtype=np.int64)


def _run_inference_batch(
    compiled_model: Any,
    input_tensor: Any,
    iterations: int,
    warmup: int = WARMUP_ITERATIONS,
) -> list[float]:
    """Run N inferences and return per-iteration latency in milliseconds."""
    latencies: list[float] = []

    # Warmup
    for _ in range(warmup):
        compiled_model(input_tensor)

    # Measurement
    for _ in range(iterations):
        t0 = time.perf_counter_ns()
        compiled_model(input_tensor)
        t1 = time.perf_counter_ns()
        latencies.append((t1 - t0) / 1_000_000)  # ns → ms

    return latencies


def _measure_rss_mb() -> float:
    """Return current process RSS in MB."""
    import psutil  # type: ignore[import-untyped]

    return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)


# ---------------------------------------------------------------------------
# Test 1.1 — Single-Model Baseline (Policy Agent Proxy)
# ---------------------------------------------------------------------------


def test_1_1(core: Any, model_path: str) -> dict[str, Any]:
    """Single-model baseline: Policy Agent proxy (512-token input)."""
    print("[Test 1.1] Single-Model Baseline — Policy Agent Proxy (512 tokens)")
    compiled, shape = _load_model(core, model_path)
    input_tensor = _create_synthetic_input(shape, POLICY_AGENT_SEQ_LEN)

    rss_before = _measure_rss_mb()
    latencies = _run_inference_batch(compiled, input_tensor, NUM_ITERATIONS)
    rss_after = _measure_rss_mb()

    result = {
        "test_id": "1.1",
        "description": "Single-model baseline — Policy Agent proxy (512 tokens)",
        "iterations": NUM_ITERATIONS,
        "seq_len": POLICY_AGENT_SEQ_LEN,
        "p50_ms": round(_percentile(latencies, 50), 3),
        "p95_ms": round(_percentile(latencies, 95), 3),
        "p99_ms": round(_percentile(latencies, 99), 3),
        "mean_ms": round(statistics.mean(latencies), 3),
        "stdev_ms": round(statistics.stdev(latencies), 3) if len(latencies) > 1 else 0,
        "peak_rss_mb": round(max(rss_before, rss_after), 1),
        "rss_delta_mb": round(rss_after - rss_before, 1),
    }
    print(f"  P50={result['p50_ms']}ms  P95={result['p95_ms']}ms  P99={result['p99_ms']}ms  RSS={result['peak_rss_mb']}MB")
    return result


# ---------------------------------------------------------------------------
# Test 1.2 — Single-Model Baseline (Orchestrator Proxy)
# ---------------------------------------------------------------------------


def test_1_2(core: Any, model_path: str) -> dict[str, Any]:
    """Single-model baseline: Orchestrator proxy (1024-token input).

    Args:
        model_path: Path to the Orchestrator-sized model (.xml with [1, 1024] static shape).
    """
    print("[Test 1.2] Single-Model Baseline — Orchestrator Proxy (1024 tokens)")
    compiled, shape = _load_model(core, model_path)
    input_tensor = _create_synthetic_input(shape, ORCHESTRATOR_SEQ_LEN)

    rss_before = _measure_rss_mb()
    latencies = _run_inference_batch(compiled, input_tensor, NUM_ITERATIONS)
    rss_after = _measure_rss_mb()

    result = {
        "test_id": "1.2",
        "description": "Single-model baseline — Orchestrator proxy (1024 tokens)",
        "iterations": NUM_ITERATIONS,
        "seq_len": ORCHESTRATOR_SEQ_LEN,
        "p50_ms": round(_percentile(latencies, 50), 3),
        "p95_ms": round(_percentile(latencies, 95), 3),
        "p99_ms": round(_percentile(latencies, 99), 3),
        "mean_ms": round(statistics.mean(latencies), 3),
        "stdev_ms": round(statistics.stdev(latencies), 3) if len(latencies) > 1 else 0,
        "peak_rss_mb": round(max(rss_before, rss_after), 1),
        "rss_delta_mb": round(rss_after - rss_before, 1),
    }
    print(f"  P50={result['p50_ms']}ms  P95={result['p95_ms']}ms  P99={result['p99_ms']}ms  RSS={result['peak_rss_mb']}MB")
    return result


# ---------------------------------------------------------------------------
# Test 1.3 — Dual-Model Concurrent Load
# ---------------------------------------------------------------------------


def test_1_3(
    core: Any,
    pa_model_path: str,
    orch_model_path: str,
    baseline_pa: dict[str, Any],
    baseline_orch: dict[str, Any],
) -> dict[str, Any]:
    """Dual-model concurrent load: two threads submitting inferences simultaneously.

    Args:
        pa_model_path: Path to Policy Agent model ([1, 512] static shape).
        orch_model_path: Path to Orchestrator model ([1, 1024] static shape).
    """
    print("[Test 1.3] Dual-Model Concurrent Load")

    compiled_pa, shape_pa = _load_model(core, pa_model_path)
    compiled_orch, shape_orch = _load_model(core, orch_model_path)
    input_pa = _create_synthetic_input(shape_pa, POLICY_AGENT_SEQ_LEN)
    input_orch = _create_synthetic_input(shape_orch, ORCHESTRATOR_SEQ_LEN)

    pa_latencies: list[float] = []
    orch_latencies: list[float] = []
    barrier = threading.Barrier(2)

    def _worker_pa() -> None:
        barrier.wait()
        pa_latencies.extend(
            _run_inference_batch(compiled_pa, input_pa, NUM_ITERATIONS, warmup=0)
        )

    def _worker_orch() -> None:
        barrier.wait()
        orch_latencies.extend(
            _run_inference_batch(compiled_orch, input_orch, NUM_ITERATIONS, warmup=0)
        )

    # Warmup both
    for _ in range(WARMUP_ITERATIONS):
        compiled_pa(input_pa)
        compiled_orch(input_orch)

    rss_before = _measure_rss_mb()
    t_pa = threading.Thread(target=_worker_pa, daemon=True)
    t_orch = threading.Thread(target=_worker_orch, daemon=True)

    wall_start = time.perf_counter_ns()
    t_pa.start()
    t_orch.start()
    t_pa.join()
    t_orch.join()
    wall_end = time.perf_counter_ns()
    rss_after = _measure_rss_mb()

    wall_ms = (wall_end - wall_start) / 1_000_000

    # Compute throughput ratio
    baseline_total_ms = baseline_pa["mean_ms"] * NUM_ITERATIONS + baseline_orch["mean_ms"] * NUM_ITERATIONS
    concurrent_total_ms = wall_ms
    # If concurrent took less than sum-of-baselines, there's parallelism
    # Ratio = (sum_of_single_baselines / concurrent_actual) — >1 means parallel, ~1 means serial
    parallelism_ratio = baseline_total_ms / concurrent_total_ms if concurrent_total_ms > 0 else 0

    # Throughput ratio as defined in test plan: single-model throughput / concurrent throughput
    # Measured per-model: concurrent mean vs baseline mean
    pa_concurrent_mean = statistics.mean(pa_latencies) if pa_latencies else float("inf")
    orch_concurrent_mean = statistics.mean(orch_latencies) if orch_latencies else float("inf")
    pa_throughput_ratio = baseline_pa["mean_ms"] / pa_concurrent_mean if pa_concurrent_mean > 0 else 0
    orch_throughput_ratio = baseline_orch["mean_ms"] / orch_concurrent_mean if orch_concurrent_mean > 0 else 0

    scheduling_mode = "parallel" if parallelism_ratio > 1.3 else "time-sliced"

    result = {
        "test_id": "1.3",
        "description": "Dual-model concurrent load",
        "iterations_per_model": NUM_ITERATIONS,
        "wall_clock_ms": round(wall_ms, 3),
        "scheduling_mode_observed": scheduling_mode,
        "parallelism_ratio": round(parallelism_ratio, 3),
        "policy_agent_proxy": {
            "p50_ms": round(_percentile(pa_latencies, 50), 3) if pa_latencies else None,
            "p95_ms": round(_percentile(pa_latencies, 95), 3) if pa_latencies else None,
            "p99_ms": round(_percentile(pa_latencies, 99), 3) if pa_latencies else None,
            "mean_ms": round(pa_concurrent_mean, 3),
            "throughput_ratio_vs_baseline": round(pa_throughput_ratio, 3),
        },
        "orchestrator_proxy": {
            "p50_ms": round(_percentile(orch_latencies, 50), 3) if orch_latencies else None,
            "p95_ms": round(_percentile(orch_latencies, 95), 3) if orch_latencies else None,
            "p99_ms": round(_percentile(orch_latencies, 99), 3) if orch_latencies else None,
            "mean_ms": round(orch_concurrent_mean, 3),
            "throughput_ratio_vs_baseline": round(orch_throughput_ratio, 3),
        },
        "peak_combined_rss_mb": round(max(rss_before, rss_after), 1),
        "concurrent_throughput_pass": min(pa_throughput_ratio, orch_throughput_ratio) >= CONCURRENT_THROUGHPUT_RATIO_MIN,
    }

    print(f"  Scheduling: {scheduling_mode} | Parallelism ratio: {result['parallelism_ratio']}")
    print(f"  PA mean: {result['policy_agent_proxy']['mean_ms']}ms | Orch mean: {result['orchestrator_proxy']['mean_ms']}ms")
    print(f"  Concurrent throughput pass: {result['concurrent_throughput_pass']}")
    return result


# ---------------------------------------------------------------------------
# Test 1.4 — Preemption Latency Measurement
# ---------------------------------------------------------------------------


def test_1_4(core: Any, pa_model_path: str, orch_model_path: str) -> dict[str, Any]:
    """Preemption latency: inject Policy Agent inference during Orchestrator generation.

    Args:
        pa_model_path: Path to Policy Agent model ([1, 512] static shape).
        orch_model_path: Path to Orchestrator model ([1, 1024] static shape).
    """
    print("[Test 1.4] Preemption Latency Measurement")

    compiled_pa, shape_pa = _load_model(core, pa_model_path)
    compiled_orch, shape_orch = _load_model(core, orch_model_path)
    input_pa = _create_synthetic_input(shape_pa, POLICY_AGENT_SEQ_LEN)
    input_orch = _create_synthetic_input(shape_orch, ORCHESTRATOR_SEQ_LEN)

    # Warmup
    for _ in range(WARMUP_ITERATIONS):
        compiled_pa(input_pa)
        compiled_orch(input_orch)

    preemption_latencies: list[float] = []
    resume_latencies: list[float] = []
    inject_event = threading.Event()
    pa_done_event = threading.Event()
    orch_running = threading.Event()

    def _orchestrator_background() -> None:
        """Continuously run orchestrator inferences to simulate mid-generation."""
        while not inject_event.is_set():
            orch_running.set()
            compiled_orch(input_orch)
        # After injection, measure resume latency
        pa_done_event.wait(timeout=10)
        t0 = time.perf_counter_ns()
        compiled_orch(input_orch)
        t1 = time.perf_counter_ns()
        resume_latencies.append((t1 - t0) / 1_000_000)

    for i in range(PREEMPTION_ITERATIONS):
        inject_event.clear()
        pa_done_event.clear()
        orch_running.clear()

        t_orch = threading.Thread(target=_orchestrator_background, daemon=True)
        t_orch.start()

        # Wait until orchestrator is actively running
        orch_running.wait(timeout=5)
        # Random small delay to vary injection point
        time.sleep(0.001 * (i % 10))

        # Inject Policy Agent inference
        t0 = time.perf_counter_ns()
        compiled_pa(input_pa)
        t1 = time.perf_counter_ns()
        preemption_latencies.append((t1 - t0) / 1_000_000)

        inject_event.set()
        pa_done_event.set()
        t_orch.join(timeout=10)

    result = {
        "test_id": "1.4",
        "description": "Preemption latency — PA inference during Orchestrator generation",
        "iterations": PREEMPTION_ITERATIONS,
        "preemption_latency": {
            "p50_ms": round(_percentile(preemption_latencies, 50), 3) if preemption_latencies else None,
            "p95_ms": round(_percentile(preemption_latencies, 95), 3) if preemption_latencies else None,
            "p99_ms": round(_percentile(preemption_latencies, 99), 3) if preemption_latencies else None,
            "mean_ms": round(statistics.mean(preemption_latencies), 3) if preemption_latencies else None,
        },
        "orchestrator_resume_latency": {
            "mean_ms": round(statistics.mean(resume_latencies), 3) if resume_latencies else None,
            "max_ms": round(max(resume_latencies), 3) if resume_latencies else None,
        },
        "preemption_p95_pass": (
            _percentile(preemption_latencies, 95) <= PREEMPTION_P95_TARGET_MS
            if preemption_latencies
            else False
        ),
        "preemption_p99_pass": (
            _percentile(preemption_latencies, 99) <= PREEMPTION_P99_TARGET_MS
            if preemption_latencies
            else False
        ),
        "resume_pass": (
            max(resume_latencies) <= ORCHESTRATOR_RESUME_TARGET_MS
            if resume_latencies
            else False
        ),
    }

    if preemption_latencies:
        print(f"  Preemption P50={result['preemption_latency']['p50_ms']}ms  P95={result['preemption_latency']['p95_ms']}ms  P99={result['preemption_latency']['p99_ms']}ms")
    if resume_latencies:
        print(f"  Resume mean={result['orchestrator_resume_latency']['mean_ms']}ms  max={result['orchestrator_resume_latency']['max_ms']}ms")

    return result


# ---------------------------------------------------------------------------
# Test 1.5 — KV-Cache Persistence Across Context Switch
# ---------------------------------------------------------------------------


def test_1_5(core: Any, pa_model_path: str, orch_model_path: str) -> dict[str, Any]:
    """KV-cache persistence: check if outputs diverge after model context switch.

    Args:
        pa_model_path: Path to Policy Agent model ([1, 512] static shape).
        orch_model_path: Path to Orchestrator model ([1, 1024] static shape).
    """
    print("[Test 1.5] KV-Cache Persistence Across Context Switch")

    compiled_pa, shape_pa = _load_model(core, pa_model_path)
    input_pa = _create_synthetic_input(shape_pa, POLICY_AGENT_SEQ_LEN)

    # Warm KV-cache with 10 iterations
    for _ in range(10):
        compiled_pa(input_pa)

    # Record warm-state output (iteration 11)
    warm_output = compiled_pa(input_pa)
    warm_result = warm_output[compiled_pa.output(0)]

    # Load orchestrator to trigger context switch
    compiled_orch, shape_orch = _load_model(core, orch_model_path)
    input_orch = _create_synthetic_input(shape_orch, ORCHESTRATOR_SEQ_LEN)
    for _ in range(10):
        compiled_orch(input_orch)

    # Switch back to Policy Agent model and re-run same input
    post_switch_output = compiled_pa(input_pa)
    post_switch_result = post_switch_output[compiled_pa.output(0)]

    import numpy as np  # type: ignore[import-untyped]

    outputs_match = np.array_equal(warm_result, post_switch_result)
    max_diff = float(np.max(np.abs(warm_result.astype(np.float32) - post_switch_result.astype(np.float32))))

    # If outputs don't match, measure reconstruction latency
    reconstruct_ms: float | None = None
    if not outputs_match:
        # Run 10 warmup iterations to rebuild KV-cache
        t0 = time.perf_counter_ns()
        for _ in range(10):
            compiled_pa(input_pa)
        t1 = time.perf_counter_ns()
        reconstruct_ms = (t1 - t0) / 1_000_000

    result = {
        "test_id": "1.5",
        "description": "KV-cache persistence across context switch",
        "outputs_match": bool(outputs_match),
        "max_output_diff": round(max_diff, 6),
        "kv_cache_persisted": bool(outputs_match),
        "reconstruction_latency_ms": round(reconstruct_ms, 3) if reconstruct_ms is not None else None,
        "reconstruction_pass": (
            reconstruct_ms <= KV_CACHE_RECONSTRUCT_TARGET_MS
            if reconstruct_ms is not None
            else True  # N/A if cache persisted
        ),
    }

    if outputs_match:
        print("  KV-cache PERSISTED across context switch")
    else:
        print(f"  KV-cache EVICTED — reconstruction latency: {reconstruct_ms:.1f}ms")
        print(f"  Reconstruction pass (≤{KV_CACHE_RECONSTRUCT_TARGET_MS}ms): {result['reconstruction_pass']}")

    return result


# ---------------------------------------------------------------------------
# Gate Evaluation
# ---------------------------------------------------------------------------


def evaluate_gate(results: dict[str, Any]) -> dict[str, Any]:
    """Apply the decision tree from Phase_2_Test_Plan.md."""
    failures: list[dict[str, Any]] = []
    warnings: list[str] = []

    test_1_3 = results.get("test_1_3", {})
    test_1_4 = results.get("test_1_4", {})
    test_1_5 = results.get("test_1_5", {})

    # Check concurrent throughput
    if not test_1_3.get("concurrent_throughput_pass", False):
        scheduling = test_1_3.get("scheduling_mode_observed", "unknown")
        if scheduling == "time-sliced":
            warnings.append(
                "NPU is time-sliced. Checking preemption latency for feasibility."
            )
            # Still passable if preemption is within budget
        else:
            failures.append(
                _failure_record(
                    "VALIDATE_NPU_SCHEDULING",
                    "Test 1.3",
                    "concurrent_throughput_ratio",
                    f"≥ {CONCURRENT_THROUGHPUT_RATIO_MIN}",
                    str(min(
                        test_1_3.get("policy_agent_proxy", {}).get("throughput_ratio_vs_baseline", 0),
                        test_1_3.get("orchestrator_proxy", {}).get("throughput_ratio_vs_baseline", 0),
                    )),
                )
            )

    # Check preemption latency
    if not test_1_4.get("preemption_p95_pass", False):
        failures.append(
            _failure_record(
                "VALIDATE_NPU_SCHEDULING",
                "Test 1.4",
                "preemption_p95_ms",
                f"≤ {PREEMPTION_P95_TARGET_MS}",
                str(test_1_4.get("preemption_latency", {}).get("p95_ms", "N/A")),
            )
        )

    if not test_1_4.get("resume_pass", False):
        failures.append(
            _failure_record(
                "VALIDATE_NPU_SCHEDULING",
                "Test 1.4",
                "orchestrator_resume_latency",
                f"≤ {ORCHESTRATOR_RESUME_TARGET_MS}",
                str(test_1_4.get("orchestrator_resume_latency", {}).get("max_ms", "N/A")),
            )
        )

    # Check KV-cache
    if not test_1_5.get("kv_cache_persisted", False):
        if not test_1_5.get("reconstruction_pass", False):
            failures.append(
                _failure_record(
                    "VALIDATE_NPU_SCHEDULING",
                    "Test 1.5",
                    "kv_cache_reconstruction_ms",
                    f"≤ {KV_CACHE_RECONSTRUCT_TARGET_MS}",
                    str(test_1_5.get("reconstruction_latency_ms", "N/A")),
                    disposition="FAIL",
                )
            )
        else:
            warnings.append(
                f"KV-cache evicted on context switch but reconstruction within budget "
                f"({test_1_5.get('reconstruction_latency_ms', 'N/A')}ms ≤ {KV_CACHE_RECONSTRUCT_TARGET_MS}ms). "
                f"CPU-side shadow copy recommended."
            )

    gate_pass = len(failures) == 0
    disposition = "PASS" if gate_pass else "FAIL"

    return {
        "gate": "VALIDATE_NPU_SCHEDULING",
        "disposition": disposition,
        "pass": gate_pass,
        "failures": failures,
        "warnings": warnings,
        "recommendation": (
            "Architecture proceeds as designed."
            if gate_pass
            else "ESCALATE: NPU scheduling does not meet latency budget. "
            "Consider CPU fallback for Policy Agent probabilistic classifier. "
            "Do NOT delete this branch — preserve for audit."
        ),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="VALIDATE_NPU_SCHEDULING — Phase 2 Empirical Gate"
    )
    parser.add_argument(
        "--model-path",
        type=str,
        required=True,
        help="Path to the Policy Agent OpenVINO IR model (.xml) with [1, 512] static shape.",
    )
    parser.add_argument(
        "--orchestrator-model-path",
        type=str,
        default=None,
        help=(
            "Path to the Orchestrator OpenVINO IR model (.xml) with [1, 1024] static shape. "
            "If omitted, --model-path is reused for all tests (requires dynamic-shape model "
            "or matching seq_len)."
        ),
    )
    parser.add_argument(
        "--device",
        type=str,
        default="NPU",
        help="OpenVINO device target (default: NPU). Use CPU for dry-run validation.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run with CPU device for script validation without NPU hardware.",
    )
    args = parser.parse_args()

    device = "CPU" if args.dry_run else args.device
    pa_model_path: str = args.model_path
    orch_model_path: str = args.orchestrator_model_path or args.model_path

    print("=" * 72)
    print("VALIDATE_NPU_SCHEDULING — Phase 2 Day-1 Empirical Gate")
    print(f"Target device:        {device}")
    print(f"PA model path:        {pa_model_path}")
    print(f"Orch model path:      {orch_model_path}")
    print(f"Timestamp:            {_timestamp()}")
    print("=" * 72)

    try:
        import openvino as ov  # type: ignore[import-untyped]
    except ImportError:
        print("ERROR: OpenVINO Runtime not installed. Run: pip install openvino")
        sys.exit(1)

    try:
        import psutil  # type: ignore[import-untyped]  # noqa: F401
    except ImportError:
        print("ERROR: psutil not installed. Run: pip install psutil")
        sys.exit(1)

    try:
        import numpy as np  # type: ignore[import-untyped]  # noqa: F401
    except ImportError:
        print("ERROR: numpy not installed. Run: pip install numpy")
        sys.exit(1)

    core = ov.Core()

    # Verify device availability
    available_devices = core.available_devices
    print(f"Available devices: {available_devices}")
    if device not in available_devices:
        print(f"WARNING: Device '{device}' not available. Available: {available_devices}")
        if not args.dry_run:
            print("Use --dry-run to test on CPU, or ensure Intel NPU driver is installed.")
            sys.exit(1)

    # Run tests
    results: dict[str, Any] = {
        "gate": "VALIDATE_NPU_SCHEDULING",
        "timestamp": _timestamp(),
        "device": device,
        "pa_model_path": pa_model_path,
        "orch_model_path": orch_model_path,
        "effective_ceiling_gb": EFFECTIVE_CEILING_GB,
    }

    print()
    results["test_1_1"] = test_1_1(core, pa_model_path)
    print()
    results["test_1_2"] = test_1_2(core, orch_model_path)
    print()
    results["test_1_3"] = test_1_3(core, pa_model_path, orch_model_path, results["test_1_1"], results["test_1_2"])
    print()
    results["test_1_4"] = test_1_4(core, pa_model_path, orch_model_path)
    print()
    results["test_1_5"] = test_1_5(core, pa_model_path, orch_model_path)
    print()

    # Gate evaluation
    gate_result = evaluate_gate(results)
    results["gate_evaluation"] = gate_result

    # Write evidence
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    output_path = EVIDENCE_DIR / "npu_scheduling_report.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    print("=" * 72)
    print(f"GATE RESULT: {gate_result['disposition']}")
    if gate_result["warnings"]:
        print("WARNINGS:")
        for w in gate_result["warnings"]:
            print(f"  - {w}")
    if gate_result["failures"]:
        print("FAILURES:")
        for fail in gate_result["failures"]:
            print(f"  - {fail['test_id']}: {fail['metric']} expected={fail['expected']} actual={fail['actual']}")
    print(f"Recommendation: {gate_result['recommendation']}")
    print(f"Evidence written to: {output_path}")
    print("=" * 72)

    sys.exit(0 if gate_result["pass"] else 1)


if __name__ == "__main__":
    main()
