"""
generate_npu_test_model.py — Create a minimal OpenVINO IR model for NPU scheduling tests.
========================================================================================

This script generates a synthetic transformer-like model in OpenVINO IR format
(.xml + .bin) suitable for NPU scheduling characterization in Gate 1
(VALIDATE_NPU_SCHEDULING).

The model mimics a simplified language model input interface:
  - Input: [batch=1, seq_len=512] int64 token IDs
  - Embedding → 2x Feed-Forward blocks → Output logits
  - Total parameters: ~2M (deliberately small — scheduling test, not accuracy test)

The model is designed to:
  1. Compile on Intel NPU (Lunar Lake) without errors
  2. Accept the same int64 input shape the scheduling script expects
  3. Execute fast enough to complete 100+ iterations in <10 minutes
  4. Be deterministic (no network downloads, no external dependencies)

Usage:
  python phase2_gates/scripts/generate_npu_test_model.py

Output:
  phase2_gates/models/npu_test_model/npu_test_model.xml
  phase2_gates/models/npu_test_model/npu_test_model.bin

Requirements:
  pip install openvino numpy
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np


def generate_model(output_dir: str | Path, seq_len: int = 512, model_name: str = "npu_test_model") -> Path:
    """Generate a minimal transformer-proxy model in OpenVINO IR format.

    Args:
        output_dir: Directory where .xml/.bin files are written.
        seq_len: Static input sequence length (e.g. 512 or 1024).
        model_name: Base name for output files (without extension).

    Returns:
        Path to the saved .xml model file.
    """
    try:
        import openvino as ov
        from openvino.runtime import opset13 as ops
    except ImportError:
        print("ERROR: OpenVINO not installed. Run: pip install openvino")
        sys.exit(1)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Model Architecture ---
    # Embedding dimension and vocab size kept small for scheduling tests
    BATCH = 1
    SEQ_LEN = seq_len
    VOCAB_SIZE = 32000
    EMBED_DIM = 256
    FF_DIM = 512

    np.random.seed(42)  # Deterministic weights

    # Input: token IDs [1, 512] as int64
    input_ids = ops.parameter(
        [BATCH, SEQ_LEN], dtype=np.int64, name="input_ids"
    )

    # Convert int64 → int32 (NPU-compatible) then → float32 for embedding lookup
    input_i32 = ops.convert(input_ids, destination_type=np.int32)
    input_f32 = ops.convert(input_i32, destination_type=np.float32)

    # Simulated embedding: matmul with learned weight matrix
    # input_f32: [1, 512] → clamp to embedding range, then project to EMBED_DIM
    # Use a simple linear projection as embedding proxy
    embed_weight = ops.constant(
        np.random.randn(SEQ_LEN, EMBED_DIM).astype(np.float32) * 0.02,
        name="embed_weight",
    )
    # [1, 512] × [512, 256] → [1, 256]
    embedded = ops.matmul(input_f32, embed_weight, False, False)

    # Feed-Forward Block 1
    ff1_weight = ops.constant(
        np.random.randn(EMBED_DIM, FF_DIM).astype(np.float32) * 0.02,
        name="ff1_weight",
    )
    ff1_bias = ops.constant(
        np.zeros(FF_DIM, dtype=np.float32), name="ff1_bias"
    )
    ff1_out = ops.matmul(embedded, ff1_weight, False, False)
    ff1_out = ops.add(ff1_out, ff1_bias)
    ff1_out = ops.relu(ff1_out)

    # Feed-Forward Block 2 (project back to EMBED_DIM)
    ff2_weight = ops.constant(
        np.random.randn(FF_DIM, EMBED_DIM).astype(np.float32) * 0.02,
        name="ff2_weight",
    )
    ff2_bias = ops.constant(
        np.zeros(EMBED_DIM, dtype=np.float32), name="ff2_bias"
    )
    ff2_out = ops.matmul(ff1_out, ff2_weight, False, False)
    ff2_out = ops.add(ff2_out, ff2_bias)
    ff2_out = ops.relu(ff2_out)

    # Output projection (logits) — EMBED_DIM → small vocab proxy
    OUTPUT_DIM = 128  # Small output for speed
    output_weight = ops.constant(
        np.random.randn(EMBED_DIM, OUTPUT_DIM).astype(np.float32) * 0.02,
        name="output_weight",
    )
    logits = ops.matmul(ff2_out, output_weight, False, False)

    # Wrap output in Result node (required by OV 2024.0 Model constructor)
    result_node = ops.result(logits)

    # Create model
    model = ov.Model(
        results=[result_node],
        parameters=[input_ids],
        name=f"{model_name}_seq{seq_len}",
    )

    # Save as IR
    model_path = output_dir / f"{model_name}.xml"
    ov.save_model(model, str(model_path))

    # Verify round-trip
    core = ov.Core()
    loaded = core.read_model(str(model_path))
    print(f"Model saved to: {model_path}")
    print(f"  Inputs:  {[(i.get_any_name(), i.shape, i.element_type) for i in loaded.inputs]}")
    # Output tensors may not have names — use index-based display
    print(f"  Outputs: {[(idx, o.shape, o.element_type) for idx, o in enumerate(loaded.outputs)]}")

    # Test compilation on available devices
    for device in core.available_devices:
        try:
            compiled = core.compile_model(loaded, device)
            print(f"  Compilation on {device}: SUCCESS")
        except Exception as e:
            print(f"  Compilation on {device}: FAILED — {e}")

    return model_path


def main() -> None:
    base_dir = Path(__file__).resolve().parent.parent / "models" / "npu_test_model"
    print("=" * 60)
    print("Generating NPU scheduling test models (OpenVINO IR)")
    print("=" * 60)

    # --- Policy Agent proxy: [1, 512] static shape ---
    print()
    print("--- Model 1/2: Policy Agent proxy (seq_len=512) ---")
    pa_path = generate_model(base_dir, seq_len=512, model_name="npu_test_model_512")

    # --- Orchestrator proxy: [1, 1024] static shape ---
    print()
    print("--- Model 2/2: Orchestrator proxy (seq_len=1024) ---")
    orch_path = generate_model(base_dir, seq_len=1024, model_name="npu_test_model_1024")

    print()
    print(f"Use with Gate 1:")
    print(f"  python phase2_gates/scripts/validate_npu_scheduling.py \\")
    print(f"    --model-path {pa_path} \\")
    print(f"    --orchestrator-model-path {orch_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
