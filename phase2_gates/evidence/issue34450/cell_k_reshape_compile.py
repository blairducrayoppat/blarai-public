"""Cell K: Reshape Cell B IR to static shapes, then compile_model on NPU.

Tests whether the standard documented workaround for the NPU "static shapes only"
limitation (Model.reshape with fixed dims) lets Qwen3-0.6B INT4 compile via the
direct NPU plugin path. Two attempts:

  K1: reshape with batch=1, seq_len=1024, head_dim derived from model
  K2: reshape with batch=1, seq_len=1 (single-token decode shape)

Outputs JSON: cell_k_result.json
"""
from __future__ import annotations
import json
import sys
import time
import traceback
from pathlib import Path

EVIDENCE = Path(__file__).parent
IR_DIR = EVIDENCE / "exports" / "cell_b"
OUT = EVIDENCE / "cell_k_result.json"


def describe_inputs(model) -> list[dict]:
    out = []
    for inp in model.inputs:
        names = list(inp.get_names())
        ps = inp.get_partial_shape()
        out.append({
            "names": names,
            "partial_shape": str(ps),
            "rank": ps.rank.get_length() if ps.rank.is_static else None,
        })
    return out


def attempt_reshape_compile(label: str, batch: int, seq_len: int) -> dict:
    import openvino as ov
    core = ov.Core()
    xml = IR_DIR / "openvino_model.xml"
    print(f"\n=== {label}: batch={batch} seq_len={seq_len} ===", flush=True)
    model = core.read_model(str(xml))
    inputs_before = describe_inputs(model)
    print(f"inputs (before reshape):", flush=True)
    for d in inputs_before:
        print(f"  {d['names']} -> {d['partial_shape']}", flush=True)

    # Build a reshape map from input name -> static shape.
    # Strategy: replace every dynamic dim with a sensible constant.
    # Common LLM input names: input_ids, attention_mask, position_ids,
    # past_key_values.{i}.{key,value}
    reshape_map: dict[str, list[int]] = {}
    head_dim = None
    num_kv_heads = None
    num_layers = 0

    # First pass: discover head_dim / num_kv_heads from any past_key_values input.
    for d in inputs_before:
        for n in d["names"]:
            if "past_key_values" in n and (".key" in n or ".value" in n):
                num_layers += 1 if ".key" in n else 0
                # partial shape like [-1,?,-1,?] -> [B, num_kv_heads, past_len, head_dim]
                ps_str = d["partial_shape"].strip("[]")
                parts = [p.strip() for p in ps_str.split(",")]
                if len(parts) == 4:
                    # try to read static dims
                    try:
                        if num_kv_heads is None and ".." not in parts[1] and parts[1] != "?":
                            num_kv_heads = int(parts[1])
                    except ValueError:
                        pass
                    try:
                        if head_dim is None and ".." not in parts[3] and parts[3] != "?":
                            head_dim = int(parts[3])
                    except ValueError:
                        pass

    # Fallback: Qwen3-0.6B-Chat has 16 KV heads, head_dim 128 (per HF config).
    if num_kv_heads is None:
        num_kv_heads = 16
    if head_dim is None:
        head_dim = 128

    print(f"derived: num_layers={num_layers} num_kv_heads={num_kv_heads} "
          f"head_dim={head_dim}", flush=True)

    # past_kv_len = seq_len - 1 for prefill-style decode at position seq_len-1,
    # but for a pure compile-time reshape we just pin past_kv_len to seq_len-1
    # for K1 (prefill 1024, no past) or 0 for K2 (single-token, no past).
    past_kv_len = max(0, seq_len - 1) if seq_len > 1 else 0

    for d in inputs_before:
        primary = d["names"][0] if d["names"] else ""
        if primary in ("input_ids", "attention_mask", "position_ids"):
            reshape_map[primary] = [batch, seq_len]
        elif "past_key_values" in primary and (".key" in primary or ".value" in primary):
            reshape_map[primary] = [batch, num_kv_heads, past_kv_len, head_dim]
        elif primary == "beam_idx":
            reshape_map[primary] = [batch]
        else:
            # Unknown input; try [batch, seq_len] as a default.
            reshape_map[primary] = [batch, seq_len]

    print(f"reshape map (showing first 6):", flush=True)
    for i, (k, v) in enumerate(reshape_map.items()):
        if i < 6:
            print(f"  {k} -> {v}", flush=True)
    print(f"  ... ({len(reshape_map)} total)", flush=True)

    result: dict = {
        "label": label,
        "batch": batch,
        "seq_len": seq_len,
        "past_kv_len": past_kv_len,
        "num_kv_heads": num_kv_heads,
        "head_dim": head_dim,
        "num_layers_observed": num_layers,
        "inputs_before": inputs_before,
        "reshape_map_preview": dict(list(reshape_map.items())[:6]),
        "reshape_map_size": len(reshape_map),
    }

    # Step 1: reshape
    t0 = time.monotonic()
    try:
        model.reshape({k: ov.PartialShape(v) for k, v in reshape_map.items()})
    except BaseException as exc:  # noqa: BLE001
        result["stage_failed"] = "reshape"
        result["exception_class"] = type(exc).__name__
        result["exception_msg"] = str(exc)[:500]
        result["traceback_tail"] = traceback.format_exc().splitlines()[-15:]
        result["elapsed_seconds"] = round(time.monotonic() - t0, 2)
        result["outcome"] = "reshape_failed"
        print(f"RESHAPE FAILED: {type(exc).__name__}: {str(exc)[:200]}", flush=True)
        return result

    inputs_after = describe_inputs(model)
    result["inputs_after"] = inputs_after
    print(f"inputs (after reshape, all should be static):", flush=True)
    all_static = True
    for d in inputs_after:
        ps = d["partial_shape"]
        is_static = "?" not in ps and ".." not in ps
        if not is_static:
            all_static = False
        print(f"  {d['names']} -> {ps} {'(STATIC)' if is_static else '(STILL DYNAMIC)'}",
              flush=True)
    result["all_inputs_static"] = all_static

    # Step 2: compile on NPU
    print(f"compiling on NPU...", flush=True)
    t1 = time.monotonic()
    try:
        _cm = core.compile_model(model, "NPU")
    except BaseException as exc:  # noqa: BLE001
        result["stage_failed"] = "compile"
        result["exception_class"] = type(exc).__name__
        result["exception_msg"] = str(exc).replace("\n", " | ")[:1500]
        result["traceback_tail"] = traceback.format_exc().splitlines()[-25:]
        result["compile_elapsed_seconds"] = round(time.monotonic() - t1, 2)
        result["elapsed_seconds"] = round(time.monotonic() - t0, 2)
        result["outcome"] = "compile_failed"
        print(f"COMPILE FAILED: {type(exc).__name__}: {str(exc)[:300]}", flush=True)
        return result

    result["compile_elapsed_seconds"] = round(time.monotonic() - t1, 2)
    result["elapsed_seconds"] = round(time.monotonic() - t0, 2)
    result["outcome"] = "ok"
    print(f"OK compiled in {result['compile_elapsed_seconds']}s", flush=True)
    return result


def main() -> int:
    if not (IR_DIR / "openvino_model.xml").exists():
        print(f"FATAL: IR missing at {IR_DIR}", file=sys.stderr)
        return 2

    results = []
    for label, batch, seq_len in (("K1", 1, 1024), ("K2", 1, 1)):
        try:
            r = attempt_reshape_compile(label, batch, seq_len)
        except BaseException as exc:  # noqa: BLE001
            r = {
                "label": label, "batch": batch, "seq_len": seq_len,
                "outcome": "harness_error",
                "exception_class": type(exc).__name__,
                "exception_msg": str(exc)[:500],
                "traceback_tail": traceback.format_exc().splitlines()[-15:],
            }
            print(f"HARNESS ERROR: {exc}", flush=True)
        results.append(r)

    out = {
        "issue": "openvinotoolkit/openvino#34450",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ir_dir": str(IR_DIR),
        "results": results,
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nwrote: {OUT}")
    for r in results:
        print(f"{r['label']}: outcome={r.get('outcome')} "
              f"stage_failed={r.get('stage_failed')} "
              f"exc={r.get('exception_class')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
