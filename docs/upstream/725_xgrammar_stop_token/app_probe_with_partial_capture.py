"""#725 gap-closing probe — xgrammar stop-token crash characterization.

Leg A (--mode specdecode): grammar ON + speculative decoding ON, streaming
    partials captured, so a crash records WHAT the model had emitted (did the
    <tool_call> trigger fire?).
Leg B (--mode plain): grammar ON + speculative decoding OFF — the control
    isolating the spec-decode interaction.

Reuses the answer_quality eval's 19 model-case prompts + the production
context composition, the production loader (OrchestratorGPUInference), and
greedy decoding. Emits one JSON line per generation to --out.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(r"C:\Users\mrbla\blarai")
sys.path.insert(0, str(REPO))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("specdecode", "plain"), required=True)
    ap.add_argument(
        "--no-stream",
        action="store_true",
        help="Match the eval runs exactly: no stream_callback (loses partial capture).",
    )
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--stop-after-crashes", type=int, default=2)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    from evals.loader import load_golden, golden_path
    from evals.suites.answer_quality import (
        SUITE_NAME,
        compose_generation_context,
        default_model_dir,
    )
    from services.assistant_orchestrator.src.gpu_inference import (
        GenerationConfig,
        OrchestratorGPUInference,
    )

    cases = [
        c
        for c in load_golden(golden_path(SUITE_NAME))
        if c.get("mode") == "model"
    ]
    print(f"[probe] {len(cases)} model cases; mode={args.mode}", flush=True)

    inference = OrchestratorGPUInference(
        model_dir=str(default_model_dir()),
        speculative_decoding_enabled=(args.mode == "specdecode"),
    )
    t0 = time.time()
    if not inference.load_model():
        print("[probe] MODEL LOAD FAILED", flush=True)
        return 2
    print(f"[probe] model loaded in {time.time()-t0:.1f}s", flush=True)

    crashes = 0
    gens = 0
    with args.out.open("a", encoding="utf-8") as fh:
        for pass_n in range(1, args.passes + 1):
            for case in cases:
                composed = compose_generation_context(
                    str(case["prompt"]), case.get("grounded_context")
                )
                chunks: list[str] = []

                def cb(piece: str) -> bool:
                    chunks.append(piece)
                    return False  # never stop early

                t1 = time.time()
                result = inference.generate_text(
                    composed,
                    max_new_tokens=512,
                    config=GenerationConfig(
                        max_new_tokens=512,
                        do_sample=False,
                        tool_call_grammar=True,  # deliberately ON — the probe
                    ),
                    stream_callback=None if args.no_stream else cb,
                )
                gens += 1
                partial = "".join(chunks)
                crashed = bool(result.error) and "GrammarMatcher" in str(
                    result.error
                )
                other_error = bool(result.error) and not crashed
                rec = {
                    "mode": args.mode,
                    "pass": pass_n,
                    "case": case["id"],
                    "gen_index": gens,
                    "crashed": crashed,
                    "other_error": (
                        str(result.error)[:200] if other_error else None
                    ),
                    "elapsed_s": round(time.time() - t1, 2),
                    "partial_len": len(partial),
                    "trigger_seen": "<tool_call>" in partial,
                    "partial_tail": partial[-400:] if crashed else None,
                }
                fh.write(json.dumps(rec) + "\n")
                fh.flush()
                if crashed:
                    crashes += 1
                    print(
                        f"[probe] CRASH #{crashes} pass={pass_n} case={case['id']} "
                        f"partial_len={len(partial)} trigger={'YES' if rec['trigger_seen'] else 'NO'}",
                        flush=True,
                    )
                if crashes >= args.stop_after_crashes:
                    print(
                        f"[probe] stop-after-crashes reached ({crashes}) at gen {gens}",
                        flush=True,
                    )
                    print(f"[probe] DONE mode={args.mode} gens={gens} crashes={crashes}", flush=True)
                    return 0
            print(f"[probe] pass {pass_n} complete: {gens} gens, {crashes} crashes", flush=True)
    print(f"[probe] DONE mode={args.mode} gens={gens} crashes={crashes}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
