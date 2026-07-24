"""
PR #4139 on-hardware verification — enable_thinking on Qwen3.6-35B-A3B / Arc 140V
=================================================================================
Tests the PR's new GenerationConfig fields (enable_thinking, reasoning_budget_tokens)
against the OFFICIAL OpenVINO 35B-A3B INT4 IR — the exact model of the linked issue
(#3937), untested by the PR author — on real Arc 140V silicon, at the PR's own
baseline (openvino 2026.4 dev nightly, genai wheel built from the fork branch).

Conditions (greedy, 220 new tokens, prompt byte-identical to the standing probes):
  A. default config                     -> expected: thinking (family default ON)
  B. cfg.enable_thinking = False        -> the PR's headline switch
  C. cfg.reasoning_budget_tokens = 32   -> the PR's budget path (bonus datum)

Run inside venv-build AFTER the wheel is installed:
  venv-build\\Scripts\\python.exe probe_pr4139_35b.py
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import openvino
import openvino_genai as ov_genai

try:
    import psutil
except ImportError:
    psutil = None

MODEL_DIR = Path("C:/Users/mrbla/models/qwen36-35b-a3b-int4-ov-OFFICIAL")
PROMPT = "How many bytes are in one kilobyte?"
MAX_TOKENS = 220
OUT_DIR = Path("C:/Users/mrbla/BlarAI/docs/performance")


def classify(text: str) -> dict[str, Any]:
    """Byte-identical heuristics to the standing probes (comparability)."""
    has_close = "</think>" in text
    lead = text.strip()[:80].lower()
    narration = any(
        s in lead
        for s in ("thinking process", "let me think", "the user is asking", "step 1")
    )
    return {
        "thinking_detected": has_close or narration,
        "has_close_think_tag": has_close,
        "leading_narration": narration,
        "first_300": text.strip()[:300],
    }


def main() -> int:
    if psutil is not None:
        avail_gb = psutil.virtual_memory().available / 2**30
        if avail_gb < 20.0:
            print(f"REFUSED: {avail_gb:.1f} GB available < 20 GB floor")
            return 1

    results: dict[str, Any] = {
        "purpose": "openvino.genai PR #4139 on-hardware verification (feeds #3937)",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "hardware": "Intel Core Ultra 7 258V / Arc 140V, driver 32.0.101.8826, Win11 26200",
        "openvino_version": openvino.__version__,
        "openvino_genai_version": ov_genai.__version__,
        "genai_source": "PlanteAmigor/openvino.genai@feat/thinking-suppression (PR #4139), built from source",
        "model": "OpenVINO/Qwen3.6-35B-A3B-int4-ov (official, INT4_ASYM g64, VLMPipeline)",
        "prompt": PROMPT,
        "max_new_tokens": MAX_TOKENS,
        "conditions": {},
    }

    cfg_probe = ov_genai.GenerationConfig()
    new_fields = [a for a in dir(cfg_probe) if "think" in a.lower() or "reasoning" in a.lower()]
    results["generation_config_thinking_fields"] = new_fields
    print("GenerationConfig thinking/reasoning fields:", new_fields, flush=True)
    if not any("enable_thinking" in f for f in new_fields):
        results["verdict"] = "PR fields NOT present in built wheel — build/branch mismatch"
        _write(results)
        return 1

    print("loading VLMPipeline (GPU)…", flush=True)
    t0 = time.perf_counter()
    pipe = ov_genai.VLMPipeline(str(MODEL_DIR), "GPU")
    results["load_seconds"] = round(time.perf_counter() - t0, 1)
    print(f"loaded in {results['load_seconds']}s", flush=True)

    def gen(label: str, mutate) -> None:
        cfg = ov_genai.GenerationConfig()
        cfg.max_new_tokens = MAX_TOKENS
        cfg.do_sample = False
        mutate(cfg)
        t0 = time.perf_counter()
        try:
            text = str(pipe.generate(PROMPT, generation_config=cfg))
        except Exception as exc:  # noqa: BLE001 — a rejected config is a datum
            results["conditions"][label] = {"error": str(exc)[:300]}
            print(f"  {label}: ERROR {str(exc)[:120]}", flush=True)
            return
        out = classify(text)
        out["seconds"] = round(time.perf_counter() - t0, 1)
        # Full-output evidence: byte-identity across conditions must be VERIFIED,
        # never inferred from a prefix (independent-review finding, 2026-07-16).
        import hashlib
        out["full_output_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        out["full_output_len"] = len(text)
        out["full_output"] = text
        results["conditions"][label] = out
        print(f"  {label}: thinking={out['thinking_detected']} sha={out['full_output_sha256'][:12]} ({out['seconds']}s)", flush=True)

    tok_json = json.loads(
        (MODEL_DIR / "tokenizer.json").read_text(encoding="utf-8")
    )
    ids = {t["content"]: t["id"] for t in tok_json.get("added_tokens", [])}
    think_start, think_end = ids.get("<think>"), ids.get("</think>")
    results["think_token_ids"] = {"<think>": think_start, "</think>": think_end}

    def with_ids(c: Any) -> None:
        c.thinking_start_token_id = think_start
        c.thinking_end_token_id = think_end

    gen("A_default", lambda c: None)
    gen("B_enable_thinking_false_no_ids", lambda c: setattr(c, "enable_thinking", False))
    gen("B2_enable_thinking_false_with_ids",
        lambda c: (setattr(c, "enable_thinking", False), with_ids(c)))
    gen("C2_reasoning_budget_32_with_ids",
        lambda c: (setattr(c, "reasoning_budget_tokens", 32), with_ids(c)))

    a = results["conditions"].get("A_default", {})
    b = results["conditions"].get("B_enable_thinking_false_no_ids", {})
    b2 = results["conditions"].get("B2_enable_thinking_false_with_ids", {})
    if a.get("thinking_detected") and b2.get("thinking_detected") is False and "error" not in b2:
        results["verdict"] = (
            "WORKS WITH EXPLICIT TOKEN IDS on Arc 140V / Qwen3.6-35B-A3B official INT4 IR"
            + ("; ID-less enable_thinking=False silently no-ops (accepted, thinking persists)"
               if b.get("thinking_detected") else "")
        )
    elif "error" in b2:
        results["verdict"] = "enable_thinking=False + token IDs RAISED — see condition B2"
    else:
        results["verdict"] = "DOES NOT SUPPRESS on this model even with explicit token IDs — inspect texts"
    print("VERDICT:", results["verdict"], flush=True)
    _write(results)
    return 0


def _write(results: dict[str, Any]) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out = OUT_DIR / f"probe_pr4139_enable_thinking_35b_{stamp}.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"results: {out}")


if __name__ == "__main__":
    raise SystemExit(main())
