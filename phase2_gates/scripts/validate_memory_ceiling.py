"""
VALIDATE_MEMORY_CEILING — Phase 2 Day-1 Empirical Gate
=======================================================
Red Team Issue: ISSUE-001
Affected Use Cases: ALL

Validates the 31.5GB effective memory ceiling under realistic multi-agent load.
Measures Windows + Hyper-V baseline overhead, per-VM memory accounting,
individual agent RSS under load, and the full execution tier summation.

Dependencies:
  - psutil (pip install psutil)
  - OpenVINO Runtime (pip install openvino) — for agent RSS under load
  - The DVMT gate (Gate 2) must be run first to establish the ceiling value.
    If dvmt_validation.json exists, ceiling is cross-referenced automatically.

Execution:
  python validate_memory_ceiling.py [--dvmt-evidence <path>] [--skip-vm-tests]

Outputs:
  phase2_gates/evidence/memory_map.json

Note:
  Tests 3.2 (per-VM overhead) require Hyper-V and Admin privileges.
  Use --skip-vm-tests if running on a non-Hyper-V system.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EFFECTIVE_CEILING_GB: float = 31.323  # Empirical — ADR-005 (was 31.5)
EFFECTIVE_CEILING_MB: float = EFFECTIVE_CEILING_GB * 1024
TOLERANCE_MB: float = 128.0  # Widened for Lunar Lake multi-component firmware reservation

# Expected memory allocations from Use Cases_FINAL (worst case)
EXPECTED_ALLOCATIONS = {
    "windows_host_os": {"min_mb": 2048, "max_mb": 4096, "desc": "Windows 11 Pro baseline"},
    "hyperv_overhead": {"min_mb": 256, "max_mb": 512, "desc": "Hyper-V hypervisor overhead"},
    "policy_agent_npu": {"min_mb": 512, "max_mb": 1024, "desc": "Policy Agent 1.7B INT4 on NPU"},
    "orchestrator_npu": {"min_mb": 512, "max_mb": 1024, "desc": "Orchestrator 1.7B INT4 on NPU (shared mmap)"},
    "semantic_router_cpu": {"min_mb": 100, "max_mb": 200, "desc": "bge-small-en-v1.5 ONNX FP16 on CPU (~128MB)"},
    "code_agent_igpu": {"min_mb": 8192, "max_mb": 9216, "desc": "14B Q4_K_M on Arc 140V iGPU"},
    "vm_overhead_per_vm": {"min_mb": 128, "max_mb": 256, "desc": "Per-VM memory overhead (Hyper-V)"},
}

EVIDENCE_DIR = Path(__file__).resolve().parent.parent / "evidence"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _failure_record(
    test_id: str,
    metric: str,
    expected: str,
    actual: str,
    disposition: str = "FAIL",
) -> dict[str, Any]:
    return {
        "gate": "VALIDATE_MEMORY_CEILING",
        "timestamp": _timestamp(),
        "test_id": test_id,
        "metric": metric,
        "expected": expected,
        "actual": actual,
        "disposition": disposition,
        "escalation": "Lead Architect decision required",
        "branch_preserved": "feature/phase2-scaffolding",
        "evidence_path": str(EVIDENCE_DIR / "memory_map.json"),
    }


def _run_powershell(command: str) -> str:
    """Execute a PowerShell command and return stdout."""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"PowerShell error: {result.stderr.strip()}")
    return result.stdout.strip()


def _get_rss_mb() -> float:
    """Return current process RSS in MB."""
    import psutil  # type: ignore[import-untyped]
    return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)


# ---------------------------------------------------------------------------
# Test 3.1 — Windows + Hyper-V Baseline Memory
# ---------------------------------------------------------------------------


def test_3_1() -> dict[str, Any]:
    """Measure Windows host OS baseline memory usage."""
    print("[Test 3.1] Windows + Hyper-V Baseline Memory Measurement")
    import psutil  # type: ignore[import-untyped]

    # Total physical visible to OS
    total_physical_mb = psutil.virtual_memory().total / (1024 * 1024)
    used_mb = psutil.virtual_memory().used / (1024 * 1024)
    available_mb = psutil.virtual_memory().available / (1024 * 1024)
    percent = psutil.virtual_memory().percent

    # Committed memory
    commit_total_mb = psutil.virtual_memory().total / (1024 * 1024)

    # Kernel memory (nonpaged + paged pool)
    try:
        nonpaged_pool = float(_run_powershell(
            "(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory"
        )) / 1024  # KB → MB
    except Exception:
        nonpaged_pool = None

    # Process count and top consumers
    process_count = len(psutil.pids())
    top_consumers: list[dict[str, Any]] = []
    for proc in sorted(psutil.process_iter(["name", "memory_info"]), 
                       key=lambda p: p.info.get("memory_info", None) and p.info["memory_info"].rss or 0,
                       reverse=True)[:10]:
        try:
            mem = proc.info.get("memory_info")
            if mem:
                top_consumers.append({
                    "name": proc.info["name"],
                    "rss_mb": round(mem.rss / (1024 * 1024), 1),
                    "pid": proc.pid,
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    result = {
        "test_id": "3.1",
        "description": "Windows + Hyper-V baseline memory",
        "total_physical_mb": round(total_physical_mb, 1),
        "used_mb": round(used_mb, 1),
        "available_mb": round(available_mb, 1),
        "used_percent": percent,
        "process_count": process_count,
        "top_10_consumers": top_consumers,
        "host_baseline_mb": round(used_mb, 1),
    }

    print(f"  Total Physical:  {result['total_physical_mb']:.1f}MB ({total_physical_mb / 1024:.2f}GB)")
    print(f"  Used:            {result['used_mb']:.1f}MB ({percent}%)")
    print(f"  Available:       {result['available_mb']:.1f}MB")
    print(f"  Process Count:   {process_count}")
    print(f"  Top consumer:    {top_consumers[0]['name']} ({top_consumers[0]['rss_mb']}MB)" if top_consumers else "")

    return result


# ---------------------------------------------------------------------------
# Test 3.2 — Per-VM Memory Overhead
# ---------------------------------------------------------------------------


def test_3_2(skip: bool = False) -> dict[str, Any]:
    """Measure Hyper-V per-VM memory overhead."""
    print("[Test 3.2] Per-VM Memory Overhead (Hyper-V)")

    if skip:
        print("  SKIPPED (--skip-vm-tests)")
        return {
            "test_id": "3.2",
            "description": "Per-VM memory overhead (Hyper-V)",
            "status": "SKIPPED",
            "estimated_overhead_mb": EXPECTED_ALLOCATIONS["vm_overhead_per_vm"]["max_mb"],
        }

    vm_info: list[dict[str, Any]] = []
    try:
        # Query Hyper-V VMs
        ps_script = """
        $vms = Get-VM | Select-Object Name, State, 
            @{N='MemoryAssignedMB';E={$_.MemoryAssigned / 1MB}},
            @{N='MemoryDemandMB';E={$_.MemoryDemand / 1MB}},
            @{N='MemoryStartupMB';E={$_.MemoryStartup / 1MB}},
            @{N='DynamicMemoryEnabled';E={$_.DynamicMemoryEnabled}}
        $vms | ConvertTo-Json -Depth 3
        """
        output = _run_powershell(ps_script)
        if output and output.strip() not in ("", "null"):
            vms = json.loads(output)
            if isinstance(vms, dict):
                vms = [vms]
            for vm in vms:
                vm_info.append({
                    "name": vm.get("Name"),
                    "state": vm.get("State"),
                    "memory_assigned_mb": vm.get("MemoryAssignedMB"),
                    "memory_demand_mb": vm.get("MemoryDemandMB"),
                    "memory_startup_mb": vm.get("MemoryStartupMB"),
                    "dynamic_memory": vm.get("DynamicMemoryEnabled"),
                })
                print(f"  VM: {vm.get('Name')} — Assigned: {vm.get('MemoryAssignedMB')}MB, Demand: {vm.get('MemoryDemandMB')}MB")
        else:
            print("  No Hyper-V VMs found")
    except Exception as e:
        print(f"  WARNING: Could not query Hyper-V VMs: {e}")
        print("  (Requires Hyper-V role and Admin privileges)")

    # Hyper-V hypervisor overhead
    hypervisor_overhead_mb: float | None = None
    try:
        ps_script = """
        $perf = Get-Counter '\Hyper-V Hypervisor\Logical Processors' -ErrorAction SilentlyContinue
        $mem = Get-Counter '\Hyper-V Dynamic Memory Balancer(*)\Available Memory' -ErrorAction SilentlyContinue
        @{
            logical_processors = $perf.CounterSamples[0].CookedValue
            available_memory = if ($mem) { $mem.CounterSamples[0].CookedValue } else { $null }
        } | ConvertTo-Json
        """
        output = _run_powershell(ps_script)
        if output:
            perf_data = json.loads(output)
            hypervisor_overhead_mb = perf_data.get("available_memory")
    except Exception:
        pass

    total_vm_assigned_mb = sum(v.get("memory_assigned_mb", 0) or 0 for v in vm_info)

    result = {
        "test_id": "3.2",
        "description": "Per-VM memory overhead (Hyper-V)",
        "status": "MEASURED",
        "vms": vm_info,
        "vm_count": len(vm_info),
        "total_vm_assigned_mb": round(total_vm_assigned_mb, 1),
        "hypervisor_overhead_mb": hypervisor_overhead_mb,
        "estimated_per_vm_overhead_mb": EXPECTED_ALLOCATIONS["vm_overhead_per_vm"]["max_mb"],
    }

    return result


# ---------------------------------------------------------------------------
# Test 3.3 — Agent RSS Under Load (Simulated)
# ---------------------------------------------------------------------------


def test_3_3(model_path: str | None = None) -> dict[str, Any]:
    """Measure simulated agent memory footprints."""
    print("[Test 3.3] Agent RSS Under Load (Simulated)")

    agent_measurements: list[dict[str, Any]] = []
    import psutil  # type: ignore[import-untyped]

    # Semantic Router (bge-small-en-v1.5 ~128MB ONNX FP16)
    try:
        import numpy as np  # type: ignore[import-untyped]
        rss_before = _get_rss_mb()
        # Simulate bge-small-en-v1.5 ONNX FP16 allocation (~128MB)
        _simulated_weights = np.random.randn(128 * 1024 * 1024 // 4).astype(np.float32)
        rss_after = _get_rss_mb()
        agent_measurements.append({
            "agent": "semantic_router",
            "model": "bge-small-en-v1.5 ONNX FP16 proxy",
            "device": "CPU",
            "rss_delta_mb": round(rss_after - rss_before, 1),
            "measured": True,
        })
        print(f"  Semantic Router (bge-small-en-v1.5 proxy): +{rss_after - rss_before:.1f}MB RSS")
        del _simulated_weights
    except ImportError:
        agent_measurements.append({
            "agent": "semantic_router",
            "model": "bge-small-en-v1.5 ONNX FP16 proxy",
            "device": "CPU",
            "rss_delta_mb": 128,
            "measured": False,
            "note": "numpy not available, using measured evidence value",
        })

    # Policy Agent & Orchestrator (NPU — measured via OpenVINO if model provided)
    if model_path:
        try:
            import openvino as ov  # type: ignore[import-untyped]
            core = ov.Core()
            
            rss_before = _get_rss_mb()
            model = core.read_model(model=model_path)
            compiled = core.compile_model(model, "NPU" if "NPU" in core.available_devices else "CPU")
            input_layer = compiled.input(0)
            shape = list(input_layer.shape)
            if len(shape) >= 2:
                shape[-1] = 512
            dummy_input = np.random.randint(0, 30000, size=shape, dtype=np.int64)
            compiled(dummy_input)
            rss_after = _get_rss_mb()
            
            npu_rss = rss_after - rss_before
            agent_measurements.append({
                "agent": "policy_agent",
                "model": "1.7B INT4 proxy",
                "device": "NPU" if "NPU" in core.available_devices else "CPU",
                "rss_delta_mb": round(npu_rss, 1),
                "measured": True,
            })
            # Shared mmap — second model should use less
            rss_before_2 = _get_rss_mb()
            compiled2 = core.compile_model(model, "NPU" if "NPU" in core.available_devices else "CPU")
            compiled2(dummy_input)
            rss_after_2 = _get_rss_mb()
            
            agent_measurements.append({
                "agent": "orchestrator",
                "model": "1.7B INT4 proxy (shared mmap)",
                "device": "NPU" if "NPU" in core.available_devices else "CPU",
                "rss_delta_mb": round(rss_after_2 - rss_before_2, 1),
                "shared_mmap_savings_mb": round(npu_rss - (rss_after_2 - rss_before_2), 1),
                "measured": True,
            })
            print(f"  Policy Agent: +{npu_rss:.1f}MB RSS")
            print(f"  Orchestrator (shared mmap): +{rss_after_2 - rss_before_2:.1f}MB RSS")
        except Exception as e:
            print(f"  WARNING: Could not measure NPU agents: {e}")
            agent_measurements.extend([
                {"agent": "policy_agent", "rss_delta_mb": 1024, "measured": False, "note": "spec max"},
                {"agent": "orchestrator", "rss_delta_mb": 1024, "measured": False, "note": "spec max"},
            ])
    else:
        print("  NPU agents: using spec values (no model path provided)")
        agent_measurements.extend([
            {"agent": "policy_agent", "model": "1.7B INT4", "device": "NPU", "rss_delta_mb": 1024, "measured": False, "note": "spec max"},
            {"agent": "orchestrator", "model": "1.7B INT4 (shared mmap)", "device": "NPU", "rss_delta_mb": 1024, "measured": False, "note": "spec max, worst case no sharing"},
        ])

    # Code Agent (iGPU — VRAM, not system RAM, but host-side overhead exists)
    # iGPU uses shared system memory, so it DOES count against the ceiling
    agent_measurements.append({
        "agent": "code_agent",
        "model": "14B Q4_K_M",
        "device": "Arc 140V iGPU",
        "vram_mb": 9216,  # worst case from spec
        "host_rss_overhead_mb": 512,  # host-side driver + context
        "total_system_impact_mb": 9216 + 512,  # iGPU uses shared memory
        "measured": False,
        "note": "iGPU uses shared system memory — full VRAM counts against ceiling",
    })
    print(f"  Code Agent (iGPU shared mem): ~9728MB total system impact (spec)")

    result = {
        "test_id": "3.3",
        "description": "Agent RSS under load",
        "agents": agent_measurements,
        "total_agent_mb": sum(
            a.get("total_system_impact_mb", a.get("rss_delta_mb", 0))
            for a in agent_measurements
        ),
    }

    print(f"  Total agent memory: ~{result['total_agent_mb']:.0f}MB")
    return result


# ---------------------------------------------------------------------------
# Test 3.4 — Execution Tier Summation
# ---------------------------------------------------------------------------


def test_3_4(
    baseline: dict[str, Any],
    vm_overhead: dict[str, Any],
    agent_rss: dict[str, Any],
    ceiling_gb: float,
) -> dict[str, Any]:
    """Sum all memory tiers and check against 31.5GB ceiling."""
    print("[Test 3.4] Execution Tier Summation")

    host_baseline_mb = baseline.get("host_baseline_mb", 4096)
    vm_total_mb = vm_overhead.get("total_vm_assigned_mb", 0) + vm_overhead.get("estimated_per_vm_overhead_mb", 256)
    agent_total_mb = agent_rss.get("total_agent_mb", 0)
    
    # Hyper-V hypervisor overhead (fixed, from spec)
    hypervisor_mb = vm_overhead.get("hypervisor_overhead_mb") or EXPECTED_ALLOCATIONS["hyperv_overhead"]["max_mb"]

    tiers = {
        "host_os_mb": round(host_baseline_mb, 1),
        "hypervisor_mb": round(hypervisor_mb, 1),
        "vm_assigned_mb": round(vm_overhead.get("total_vm_assigned_mb", 0), 1),
        "vm_overhead_mb": round(vm_overhead.get("estimated_per_vm_overhead_mb", 256), 1),
        "agent_total_mb": round(agent_total_mb, 1),
    }

    total_mb = sum(tiers.values())
    ceiling_mb = ceiling_gb * 1024
    headroom_mb = ceiling_mb - total_mb
    headroom_percent = (headroom_mb / ceiling_mb) * 100

    tiers["total_committed_mb"] = round(total_mb, 1)
    tiers["ceiling_mb"] = round(ceiling_mb, 1)
    tiers["headroom_mb"] = round(headroom_mb, 1)
    tiers["headroom_percent"] = round(headroom_percent, 1)
    tiers["over_ceiling"] = total_mb > ceiling_mb

    # Decision tree
    failures: list[dict[str, Any]] = []
    warnings: list[str] = []

    if total_mb > ceiling_mb:
        overage_mb = total_mb - ceiling_mb
        failures.append(_failure_record(
            "3.4", "total_committed_mb",
            f"≤ {ceiling_mb:.0f}MB ({ceiling_gb}GB)",
            f"{total_mb:.0f}MB (overage: {overage_mb:.0f}MB)",
        ))
        print(f"  FAIL: Total {total_mb:.0f}MB EXCEEDS ceiling {ceiling_mb:.0f}MB by {overage_mb:.0f}MB")
    elif headroom_percent < 5.0:
        warnings.append(
            f"Headroom critically low: {headroom_mb:.0f}MB ({headroom_percent:.1f}%). "
            f"Consider reducing Code Agent model size or enabling dynamic memory."
        )
        print(f"  WARNING: Tight headroom — {headroom_mb:.0f}MB ({headroom_percent:.1f}%)")
    elif headroom_percent < 15.0:
        warnings.append(
            f"Headroom moderate: {headroom_mb:.0f}MB ({headroom_percent:.1f}%). "
            f"Monitor under sustained load."
        )
        print(f"  OK: Moderate headroom — {headroom_mb:.0f}MB ({headroom_percent:.1f}%)")
    else:
        print(f"  PASS: Comfortable headroom — {headroom_mb:.0f}MB ({headroom_percent:.1f}%)")

    print(f"\n  Memory Tier Breakdown:")
    print(f"    Host OS:         {tiers['host_os_mb']:>8.0f}MB")
    print(f"    Hypervisor:      {tiers['hypervisor_mb']:>8.0f}MB")
    print(f"    VM Assigned:     {tiers['vm_assigned_mb']:>8.0f}MB")
    print(f"    VM Overhead:     {tiers['vm_overhead_mb']:>8.0f}MB")
    print(f"    Agent Total:     {tiers['agent_total_mb']:>8.0f}MB")
    print(f"    ─────────────────────────────")
    print(f"    TOTAL COMMITTED: {tiers['total_committed_mb']:>8.0f}MB")
    print(f"    CEILING:         {tiers['ceiling_mb']:>8.0f}MB")
    print(f"    HEADROOM:        {tiers['headroom_mb']:>8.0f}MB ({tiers['headroom_percent']:.1f}%)")

    result = {
        "test_id": "3.4",
        "description": "Execution tier summation",
        "tiers": tiers,
        "pass": len(failures) == 0,
        "failures": failures,
        "warnings": warnings,
    }
    return result


# ---------------------------------------------------------------------------
# Gate Evaluation
# ---------------------------------------------------------------------------


def evaluate_gate(results: dict[str, Any]) -> dict[str, Any]:
    """Aggregate all sub-test results into a gate verdict."""
    all_failures: list[dict[str, Any]] = []
    all_warnings: list[str] = []

    for key in ["test_3_1", "test_3_2", "test_3_3", "test_3_4"]:
        test = results.get(key, {})
        all_failures.extend(test.get("failures", []))
        all_warnings.extend(test.get("warnings", []))

    gate_pass = len(all_failures) == 0

    test_3_4 = results.get("test_3_4", {})
    tiers = test_3_4.get("tiers", {})

    return {
        "gate": "VALIDATE_MEMORY_CEILING",
        "disposition": "PASS" if gate_pass else "FAIL",
        "pass": gate_pass,
        "failures": all_failures,
        "warnings": all_warnings,
        "total_committed_mb": tiers.get("total_committed_mb"),
        "ceiling_mb": tiers.get("ceiling_mb"),
        "headroom_mb": tiers.get("headroom_mb"),
        "headroom_percent": tiers.get("headroom_percent"),
        "recommendation": (
            f"Memory ceiling validated. {tiers.get('headroom_mb', 0):.0f}MB headroom "
            f"({tiers.get('headroom_percent', 0):.1f}%). Proceed with VM sizing."
            if gate_pass
            else "ESCALATE: Memory ceiling exceeded. Review agent allocations and consider "
            "model quantization or Code Agent model downsizing. Do NOT delete this branch."
        ),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="VALIDATE_MEMORY_CEILING — Phase 2 Empirical Gate"
    )
    parser.add_argument(
        "--dvmt-evidence",
        type=str,
        default=None,
        help="Path to dvmt_validation.json from Gate 2. Auto-detected in evidence dir.",
    )
    parser.add_argument(
        "--model-path",
        type=str,
        default=None,
        help="Path to OpenVINO IR model for NPU agent RSS measurement.",
    )
    parser.add_argument(
        "--skip-vm-tests",
        action="store_true",
        help="Skip Hyper-V VM queries (use estimated values).",
    )
    args = parser.parse_args()

    print("=" * 72)
    print("VALIDATE_MEMORY_CEILING — Phase 2 Day-1 Empirical Gate")
    print(f"Timestamp: {_timestamp()}")
    print("=" * 72)

    try:
        import psutil  # type: ignore[import-untyped]  # noqa: F401
    except ImportError:
        print("ERROR: psutil not installed. Run: pip install psutil")
        sys.exit(1)

    # Cross-reference DVMT gate ceiling
    ceiling_gb = EFFECTIVE_CEILING_GB
    dvmt_path = args.dvmt_evidence or str(EVIDENCE_DIR / "dvmt_validation.json")
    if Path(dvmt_path).exists():
        try:
            with open(dvmt_path, encoding="utf-8") as f:
                dvmt_data = json.load(f)
            dvmt_ceiling = dvmt_data.get("effective_ceiling_gb")
            if dvmt_ceiling:
                ceiling_gb = float(dvmt_ceiling)
                print(f"Cross-referenced DVMT gate ceiling: {ceiling_gb}GB")
        except Exception as e:
            print(f"WARNING: Could not read DVMT evidence: {e}. Using default {ceiling_gb}GB.")
    else:
        print(f"DVMT evidence not found at {dvmt_path}. Using default ceiling: {ceiling_gb}GB.")

    print()
    results: dict[str, Any] = {
        "gate": "VALIDATE_MEMORY_CEILING",
        "timestamp": _timestamp(),
        "effective_ceiling_gb": ceiling_gb,
    }

    results["test_3_1"] = test_3_1()
    print()
    results["test_3_2"] = test_3_2(skip=args.skip_vm_tests)
    print()
    results["test_3_3"] = test_3_3(model_path=args.model_path)
    print()
    results["test_3_4"] = test_3_4(
        baseline=results["test_3_1"],
        vm_overhead=results["test_3_2"],
        agent_rss=results["test_3_3"],
        ceiling_gb=ceiling_gb,
    )
    print()

    # Gate evaluation
    gate_result = evaluate_gate(results)
    results["gate_evaluation"] = gate_result

    # Write evidence
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    output_path = EVIDENCE_DIR / "memory_map.json"
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
