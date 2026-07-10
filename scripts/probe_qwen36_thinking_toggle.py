"""One-off probe: can thinking be disabled on Qwen3.6-27B via OpenVINO GenAI? (#768 / genai #3937)

Three conditions against the resident-on-disk official INT4 build:
  A. plain prompt                      -> expected: thinking trace (model default ON)
  B. prompt + '/no_think' soft switch  -> the production PA mechanism (ADR-012 s2.4)
  C. any enable_thinking control the GenAI API exposes (introspected, attempted, reported)

Detection: '</think>' in output (the applied chat template opens the think block;
the model closes it — matches the benchmark captures), plus a leading-narration check.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import openvino_genai as ov_genai

MODEL_DIR = Path("C:/Users/mrbla/blarai/models/qwen3.6-27b-int4-ov")
PROMPT = "How many bytes are in one kilobyte?"
OUT = Path(__file__).with_suffix(".results.json")

results: dict = {"model": MODEL_DIR.name, "genai_version": ov_genai.__version__, "conditions": {}}


def gen(pipe, prompt: str, max_tokens: int = 220) -> str:
    cfg = ov_genai.GenerationConfig()
    cfg.max_new_tokens = max_tokens
    cfg.do_sample = False
    return str(pipe.generate(prompt, generation_config=cfg))


def classify(text: str) -> dict:
    has_close = "</think>" in text
    lead = text.strip()[:80].lower()
    narration = any(s in lead for s in ("thinking process", "let me think", "the user is asking", "step 1"))
    return {"thinking_detected": has_close or narration, "has_close_think_tag": has_close,
            "leading_narration": narration, "first_200": text.strip()[:200]}


print("loading pipeline (cached compile expected)...", flush=True)
t0 = time.perf_counter()
pipe = ov_genai.VLMPipeline(str(MODEL_DIR), "GPU")
print(f"loaded in {time.perf_counter() - t0:.1f}s", flush=True)

# Introspection: what thinking/template control does this API surface actually expose?
pipe_attrs = [a for a in dir(pipe) if "template" in a.lower() or "chat" in a.lower()]
cfg_attrs = [a for a in dir(ov_genai.GenerationConfig()) if "think" in a.lower()]
tok_attrs = []
try:
    tok = pipe.get_tokenizer()
    tok_attrs = [a for a in dir(tok) if "template" in a.lower() or "think" in a.lower()]
except Exception as exc:  # noqa: BLE001
    tok_attrs = [f"get_tokenizer failed: {exc}"]
results["introspection"] = {"pipe": pipe_attrs, "generation_config_think": cfg_attrs, "tokenizer": tok_attrs}
print("introspection:", json.dumps(results["introspection"]), flush=True)

# A — plain
text_a = gen(pipe, PROMPT)
results["conditions"]["A_plain"] = classify(text_a)
print("A done:", results["conditions"]["A_plain"]["thinking_detected"], flush=True)

# B — /no_think soft switch (production PA mechanism)
text_b = gen(pipe, PROMPT + " /no_think")
results["conditions"]["B_no_think_switch"] = classify(text_b)
print("B done:", results["conditions"]["B_no_think_switch"]["thinking_detected"], flush=True)

# C — kwarg / template control, attempted in order of plausibility
c_result: dict = {"attempted": []}
cfg = ov_genai.GenerationConfig()
cfg.max_new_tokens = 220
cfg.do_sample = False
attempted = False
# C1: generate(..., enable_thinking=...) kwarg
try:
    text_c = str(pipe.generate(PROMPT, generation_config=cfg, enable_thinking=False))
    c_result["attempted"].append("generate(enable_thinking=False): ACCEPTED")
    c_result.update(classify(text_c))
    attempted = True
except TypeError as exc:
    c_result["attempted"].append(f"generate(enable_thinking=False): rejected ({exc})")
except Exception as exc:  # noqa: BLE001
    c_result["attempted"].append(f"generate(enable_thinking=False): error ({type(exc).__name__}: {exc})")
# C2: GenerationConfig attribute
if not attempted and any("think" in a.lower() for a in cfg_attrs):
    try:
        setattr(cfg, cfg_attrs[0], False)
        text_c = gen(pipe, PROMPT)
        c_result["attempted"].append(f"GenerationConfig.{cfg_attrs[0]}=False: ACCEPTED")
        c_result.update(classify(text_c))
        attempted = True
    except Exception as exc:  # noqa: BLE001
        c_result["attempted"].append(f"GenerationConfig think attr: error ({exc})")
# C3: empty-think-prefix emulation — what the HF template's enable_thinking=False produces.
# The template normally appends an empty <think>\n\n</think> block; we emulate by instructing
# via a system-style leading directive is NOT equivalent, so instead append the closed block
# to the user text and see whether the model re-opens thinking anyway (the #3937 symptom).
if not attempted:
    text_c = gen(pipe, PROMPT + "\n<think>\n\n</think>\n")
    c_result["attempted"].append("emulated empty-think prefix in user text (approximation)")
    c_result.update(classify(text_c))
results["conditions"]["C_enable_thinking_control"] = c_result
print("C done", flush=True)

OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
print("results ->", OUT, flush=True)
print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "first_200"}
                  for k, v in results["conditions"].items()}, indent=2), flush=True)
