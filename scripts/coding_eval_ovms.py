"""
Long-context coding accuracy eval for the 30B MoE flag A/B (Session-2 §4).
==========================================================================
The MOE_USE_MICRO_GEMM_PREFILL=0 flag is documented to RECOVER accuracy that
Qwen3-MoE INT4 can lose on LONG prompts (the repo-context case), at a TTFT cost.
The TTFT cost is measured by benchmark_ovms_http.py; THIS measures the accuracy
side with a DEFINED, reproducible, ground-truth eval:

A long synthetic Python module (~hundreds of deterministic functions, large token
context) is generated, then the model is asked factual questions whose answers are
known by construction (function count, a specific function's return constant, a
specific function's parameter count, which functions call a given helper). Greedy
(temperature=0) so outputs are deterministic. Run once per arm (MoE flag on/off,
controlled by which OVMS is up); grade = does the known answer appear in the reply.
A divergence in score (or in the raw greedy answers) between arms IS the accuracy
signal.

Usage (OVMS coder-30b must be running on :8000):
  .venv/Scripts/python.exe scratchpad/coding_eval_ovms.py --arm moe_on
  .venv/Scripts/python.exe scratchpad/coding_eval_ovms.py --arm moe_off
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if not (_REPO_ROOT / "shared").exists():
    _REPO_ROOT = Path.cwd()

ENDPOINT = "http://127.0.0.1:8000/v3/chat/completions"
MODEL = "coder-30b"

# Deterministic synthetic module. Each func_i takes (i % 4)+1 params and returns
# the constant (i*7 + 3). func_i calls helper_a iff i % 5 == 0. Known by construction.
N_FUNCS = 200


def build_module() -> tuple[str, dict]:
    lines = ["def helper_a(x):", "    return x + 1", "",
             "def helper_b(x):", "    return x * 2", ""]
    callers_of_a = []
    returns = {}
    params = {}
    for i in range(N_FUNCS):
        nparams = (i % 4) + 1
        ret = i * 7 + 3
        args = ", ".join(f"p{j}" for j in range(nparams))
        params[i] = nparams
        returns[i] = ret
        body = []
        if i % 5 == 0:
            body.append("    _ = helper_a(p0)")
            callers_of_a.append(i)
        body.append(f"    return {ret}")
        lines.append(f"def func_{i}({args}):")
        lines.extend(body)
        lines.append("")
    module = "\n".join(lines)
    facts = {"n_funcs": N_FUNCS, "n_helpers": 2, "total_defs": N_FUNCS + 2,
             "returns": returns, "params": params, "callers_of_a": callers_of_a}
    return module, facts


def ask(question: str, context: str, max_tokens: int = 200) -> tuple[str, float]:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "You are a precise code analysis assistant. Answer concisely."},
            {"role": "user", "content": f"Given this Python module:\n\n```python\n{context}\n```\n\n{question}"},
        ],
        "temperature": 0.0, "max_tokens": max_tokens, "stream": False,
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(ENDPOINT, data=data, headers={"Content-Type": "application/json"})
    t = time.perf_counter()
    with urllib.request.urlopen(req, timeout=180) as resp:
        body = json.loads(resp.read())
    dt = time.perf_counter() - t
    return body["choices"][0]["message"]["content"], dt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, help="moe_on | moe_off")
    args = ap.parse_args()

    module, facts = build_module()
    approx_tokens = len(module) // 4
    print(f"== 30B coding accuracy eval == arm={args.arm} (context ~{approx_tokens} tokens)")

    questions = [
        ("Q1_func_count",
         "How many functions are defined in total (including helpers)? Answer with just the number.",
         str(facts["total_defs"])),
        ("Q2_return_const",
         "What integer does the function func_23 return? Answer with just the number.",
         str(facts["returns"][23])),
        ("Q3_param_count",
         "How many parameters does func_47 take? Answer with just the number.",
         str(facts["params"][47])),
        ("Q4_return_deep",
         "What integer does the function func_188 return? Answer with just the number.",
         str(facts["returns"][188])),
        ("Q5_calls_helper",
         "Does func_25 call helper_a? Answer yes or no.",
         "yes" if 25 in facts["callers_of_a"] else "no"),
    ]

    rows = []
    correct = 0
    for key, q, expected in questions:
        try:
            ans, dt = ask(q, module)
        except Exception as exc:  # noqa: BLE001
            ans, dt = f"<error: {exc}>", 0.0
        hit = expected.lower() in ans.lower()
        correct += int(hit)
        rows.append({"key": key, "expected": expected, "answer": ans.strip()[:300],
                     "correct": hit, "wall_s": round(dt, 2)})
        print(f"  {key}: expected={expected} correct={hit} ({dt:.1f}s) :: {ans.strip()[:80]!r}")

    score = f"{correct}/{len(questions)}"
    print(f"\n  SCORE arm={args.arm}: {score}")

    out = {"eval": "coding_accuracy_30b", "arm": args.arm, "model": MODEL,
           "context_approx_tokens": approx_tokens, "n_funcs": N_FUNCS,
           "score": score, "correct": correct, "total": len(questions), "rows": rows}
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    outpath = _REPO_ROOT / "docs" / "performance" / f"coding_eval_30b_{args.arm}_{ts}.json"
    outpath.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"[SAVE] {outpath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
