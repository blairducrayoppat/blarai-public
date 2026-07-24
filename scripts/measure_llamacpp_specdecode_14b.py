"""
llama.cpp spec-decode equalization for the Qwen3-14B row (#769 item 1 addendum)
===============================================================================
The production-models bench compared a DRAFTLESS llama.cpp 14B (tg128 7.52
Vulkan) against OpenVINO's spec-decode-ON production baseline — an asymmetry the
record names. This harness closes it: the same llama-server (b9957 win-vulkan,
-ngl 99) measured with and without a Qwen3-0.6B Q8_0 draft (`-md`, fully
offloaded), so the spec-decode delta is internally controlled (same server,
same endpoint, same prompts).

Throughput source: the server's own `timings.predicted_per_second` from
/v1/completions (raw completion endpoint — no chat template, so no thinking
consumes the budget), greedy, 256 new tokens, prompt set v1's four prompts +
one repeat (5 runs/arm, medians).

Usage (box lean, BlarAI down):
  .venv\\Scripts\\python.exe scripts\\measure_llamacpp_specdecode_14b.py
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from shared.perf_env_capture import capture_box_state  # noqa: E402

BASE = Path("C:/Users/mrbla/models/gguf-769")
SERVER = BASE / "llamacpp-vulkan" / "llama-server.exe"
MODEL = BASE / "Qwen3-14B-IQ4_NL.gguf"
DRAFT = BASE / "Qwen3-0.6B-Q8_0.gguf"
PORT = 8089
URL = f"http://127.0.0.1:{PORT}"

# Prompt set v1 (scripts/benchmark_gpu_inference.py) — byte-identical texts.
PROMPTS = [
    "What is the capital city of France?",
    "How many bytes are in one kilobyte?",
    "Explain what a transformer neural network is in plain language.",
    "What is quantization in the context of machine learning models, "
    "and why does it help with inference speed?",
]
MAX_TOKENS = 256


def _wait_health(deadline_s: float = 240.0) -> bool:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < deadline_s:
        try:
            with urllib.request.urlopen(f"{URL}/health", timeout=3) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(3)
    return False


def _completion(prompt: str) -> dict[str, Any]:
    body = {"prompt": prompt, "max_tokens": MAX_TOKENS, "temperature": 0}
    req = urllib.request.Request(
        f"{URL}/v1/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=900) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    wall = time.perf_counter() - t0
    timings = data.get("timings", {})
    return {
        "predicted_per_second": timings.get("predicted_per_second"),
        "predicted_n": timings.get("predicted_n"),
        "draft_n": timings.get("draft_n"),
        "draft_n_accepted": timings.get("draft_n_accepted"),
        "wall_seconds": round(wall, 1),
    }


def run_arm(label: str, extra_args: list[str]) -> dict[str, Any]:
    log_path = BASE / "results" / f"specdecode_{label}.log"
    log_file = open(log_path, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        [str(SERVER), "-m", str(MODEL), "-ngl", "99", "--host", "127.0.0.1",
         "--port", str(PORT), "-v", *extra_args],
        cwd=str(SERVER.parent),
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    arm: dict[str, Any] = {"label": label, "server_args": extra_args, "log": str(log_path)}
    try:
        if not _wait_health():
            arm["error"] = "server never became healthy"
            return arm
        offload = [
            ln for ln in log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            if "offloaded" in ln
        ]
        arm["offload_evidence"] = offload[-2:]
        _completion(PROMPTS[0])  # warmup, discarded
        runs = [_completion(p) for p in [*PROMPTS, PROMPTS[0]]]
        arm["runs"] = runs
        tps = [r["predicted_per_second"] for r in runs if r.get("predicted_per_second")]
        arm["median_tps"] = round(statistics.median(tps), 2) if tps else None
        accepted = [r for r in runs if r.get("draft_n")]
        if accepted:
            arm["draft_acceptance"] = round(
                sum(r["draft_n_accepted"] for r in accepted)
                / max(1, sum(r["draft_n"] for r in accepted)),
                3,
            )
        for r in runs:
            print(f"  [{label}] {r}", flush=True)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_file.close()
        time.sleep(8)
    return arm


def main() -> int:
    results: dict[str, Any] = {
        "ticket": "#769 item 1 addendum (spec-decode equalization)",
        "date": datetime.now().isoformat(timespec="seconds"),
        "llamacpp_build": "b9957 official win-vulkan-x64",
        "model": MODEL.name,
        "draft": DRAFT.name,
        "methodology": (
            "llama-server /v1/completions (raw endpoint, no chat template), greedy, "
            f"{MAX_TOKENS} new tokens, prompt set v1 (4 prompts + 1 repeat = 5 runs/arm, "
            "1 discarded warmup), throughput = the server's own timings.predicted_per_second, "
            "medians; same server/settings both arms; draft fully offloaded (-ngld 99)."
        ),
        "environment": {"box_state_at_start": capture_box_state()},
        "arms": {},
    }
    print("=== ARM 1: draftless control ===", flush=True)
    results["arms"]["draftless"] = run_arm("draftless", [])
    print("=== ARM 2: spec-decode (-md 0.6B Q8_0, --spec-type draft-simple) ===", flush=True)
    # b9957 requires an explicit implementation via --spec-type (default 'none' —
    # the first run's draft loaded but never engaged; the server log's
    # "no implementations specified" line was the tell). draft-simple with the
    # default 3-token draft budget mirrors production OV's NUM_ASSISTANT_TOKENS=3.
    results["arms"]["spec_decode"] = run_arm(
        "specdecode", ["-md", str(DRAFT), "-ngld", "99", "--spec-type", "draft-simple"]
    )

    out = _REPO_ROOT / "docs" / "performance" / (
        f"llamacpp_specdecode_14b_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"
    )
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"medians: draftless={results['arms']['draftless'].get('median_tps')} "
          f"spec={results['arms']['spec_decode'].get('median_tps')} "
          f"acceptance={results['arms']['spec_decode'].get('draft_acceptance')}")
    print(f"results: {out}")
    return 0 if results["arms"]["draftless"].get("median_tps") else 1


if __name__ == "__main__":
    sys.exit(main())
