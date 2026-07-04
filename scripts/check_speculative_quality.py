"""
Speculative Decoding Quality Check — BlarAI
============================================
Loads Qwen3-14B with speculative decoding ENABLED and generates answers
to a set of prompts with known-good answers, so output quality can be
eyeballed before speculative decoding is relied on as the default.

Speculative decoding is exact in theory; on a GPU with f16 verification
it can occasionally diverge from standard greedy decoding. This check
confirms the answers remain correct, coherent, and cleanly terminated.

Usage (from repo root, BlarAI venv):
  .venv\\Scripts\\python.exe scripts\\check_speculative_quality.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from shared.constants import DRAFT_MODEL_OV_PATH, TARGET_MODEL_OV_PATH
from services.assistant_orchestrator.src.gpu_inference import (
    GenerationConfig,
    OrchestratorGPUInference,
)

# Prompts chosen so the answers are easy to judge — a factual lookup, an
# arithmetic check (a sensitive degradation detector), a list, an
# explanation (coherence), and a short creative task.
_PROMPTS = [
    "What is the capital of France?",
    "What is 17 multiplied by 23?",
    "List the three primary colors of light.",
    "Explain what a transformer neural network is, in two or three sentences.",
    "Write a haiku about a quiet morning.",
]

_GEN = GenerationConfig(
    max_new_tokens=256,
    temperature=0.0,
    top_k=0,
    top_p=1.0,
    do_sample=False,
)


def main() -> int:
    model_dir = str((_REPO_ROOT / TARGET_MODEL_OV_PATH).resolve())
    draft_dir = str((_REPO_ROOT / DRAFT_MODEL_OV_PATH).resolve())
    print("=" * 70)
    print("  Speculative Decoding Quality Check — BlarAI Qwen3-14B")
    print("=" * 70)

    engine = OrchestratorGPUInference(
        model_dir=model_dir,
        device="GPU",
        draft_model_dir=draft_dir,
        speculative_decoding_enabled=True,
    )
    print("  [LOAD] loading model with speculative decoding ...")
    if not engine.load_model():
        print("  [LOAD] FAILED — model did not load.")
        return 1
    print(
        f"  [LOAD] done. speculative_decoding_active="
        f"{engine.speculative_decoding_active}\n"
    )
    if not engine.speculative_decoding_active:
        print("  WARNING: speculative decoding did NOT engage — "
              "answers below reflect standard decoding.\n")

    for i, prompt in enumerate(_PROMPTS):
        res = engine.generate_text(prompt=prompt, config=_GEN)
        print(f"--- Prompt {i}: {prompt}")
        print(
            f"  tokens={res.token_count}  truncated={res.truncated}  "
            f"latency={res.latency_total_ms:.0f}ms  error={res.error}"
        )
        print(f"  Answer: {(res.text or '').strip()}")
        print()

    engine.unload()
    print("=" * 70)
    print("  Eyeball the answers: correct? coherent? cleanly terminated")
    print("  (truncated=False means the model stopped on its own)?")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
