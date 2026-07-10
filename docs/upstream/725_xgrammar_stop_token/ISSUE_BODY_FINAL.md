**Describe the bug**

When a triggered structural-tags (xgrammar) grammar is attached to a request's `GenerationConfig` and the pipeline runs with speculative decoding (a `draft_model`), generation intermittently aborts at end-of-sequence:

```
grammar_matcher.cc:627: Check failed: (!IsStopTokenAccepted()) is false: GrammarMatcher has terminated after accepting the stop token, but is trying to find the next token mask
```

The generation raises and the result is lost. It is intermittent (~1–5% of generations on my workload) and nondeterministic across identical greedy runs — a different prompt aborts each time.

It disappears entirely when speculative decoding is removed (draft model detached), with the grammar and everything else unchanged — this is the key isolating result (see the table below).

A companion non-fatal warning fires at the same site with an ordinary vocabulary token id (not a grammar/control token):

```
grammar_matcher.cc:493: Warning: The matcher has terminated after accepting the stop token, but is trying to accept new token with id 498.
```

**Likely root cause**

The `GrammarMatcher` accepts the stop token and terminates. The speculative-decoding path then asks the terminated matcher for a next-token mask — to validate/mask the draft model's proposed tokens past the stop position — which trips the `!IsStopTokenAccepted()` assertion.

Two observations point at the draft proposals rather than the grammar body:

1. The `cc:493` warning feeds the terminated matcher ordinary word-piece token ids (e.g. `498`) — i.e. whatever the draft proposed after the stop, not a token the constrained region required.
2. I captured 57 generations token-by-token with streaming: none emitted the grammar's trigger tag in the output (the grammar body never engaged), yet the equivalent non-streamed runs still crashed. So the grammar *firing* is not a precondition — a configured-but-untriggered grammar + a draft model + end-of-sequence is sufficient. This appears to be structured output under speculative decoding in general, not specific to any grammar or to tool-calling.

This is the same shape as a fixed bug in sglang — [sgl-project/sglang#14464](https://github.com/sgl-project/sglang/pull/14464) (merged 2025-12-06): identical "GrammarMatcher has terminated after accepting the stop token" under speculative decoding + grammar, fixed by implementing `is_terminated` so the terminated matcher is not queried. Since OpenVINO GenAI vendors xgrammar (`_deps/xgrammar-src`) and drives it from its own continuous-batching speculative path, a similar guard on the OV side of the matcher call may be what's needed. (Related sglang reports: #15050 grammar × EagleWorker, #14462 spec-decode guided-decoding data race.)

**To Reproduce**

Self-contained, OpenVINO-GenAI-only (no application code). Point `MODEL`/`DRAFT` at any OV LLM export + a compatible draft export, then run:

```python
import json
import openvino_genai as ov_genai

MODEL = r"<path-to-target-ov-model-dir>"   # e.g. Qwen3-14B OpenVINO INT4
DRAFT = r"<path-to-draft-ov-model-dir>"    # e.g. Qwen3-0.6B OpenVINO INT8

def build_pipe(use_draft: bool):
    sched = ov_genai.SchedulerConfig()
    sched.cache_size = 3
    sched.enable_prefix_caching = True
    kw = dict(scheduler_config=sched, PERFORMANCE_HINT="LATENCY",
              INFERENCE_PRECISION_HINT="f16",
              GPU_ENABLE_SDPA_OPTIMIZATION="ON", CACHE_DIR="")
    if use_draft:
        kw["draft_model"] = ov_genai.draft_model(
            DRAFT, "GPU", PERFORMANCE_HINT="LATENCY",
            INFERENCE_PRECISION_HINT="f16",
            GPU_ENABLE_SDPA_OPTIMIZATION="ON", CACHE_DIR="")
    return ov_genai.LLMPipeline(MODEL, "GPU", **kw)

def build_cfg(use_draft: bool):
    cfg = ov_genai.GenerationConfig()
    cfg.max_new_tokens = 512
    cfg.do_sample = False
    if use_draft:
        cfg.num_assistant_tokens = 3
    tags = ov_genai.StructuralTagsConfig(
        structural_tags=[ov_genai.StructuralTagItem(
            begin="<tool_call>",
            schema=json.dumps({
                "type": "object",
                "properties": {"name": {"type": "string"},
                               "arguments": {"type": "object"}},
                "required": ["name", "arguments"]}),
            end="</tool_call>")],
        triggers=["<tool_call>"])
    structured = ov_genai.StructuredOutputConfig()
    structured.structural_tags_config = tags
    cfg.structured_output_config = structured
    return cfg

SYS = "You are a helpful assistant. Answer concisely and truthfully."
QUESTIONS = [
    "Who are you and where do you run?",
    "What is the capital of France?",
    "What is 17 multiplied by 23?",
    "Convert 26.2 miles to kilometers.",
    "Answer with exactly one word: what color is a ripe banana?",
    "Reply as a numbered list of exactly 3 items: name three primary colors.",
    "Answer yes or no only: is 7 a prime number?",
    "What is the hostname of a typical home NAS device?",
    "When was the Eiffel Tower completed?",
    "Summarize this note: the budget review meeting moved to Friday.",
    "What does photosynthesis do, in two sentences?",
    "What year did the first human walk on the moon?",
    "Name the largest planet in the solar system.",
    "How many continents are there?",
    "What is the boiling point of water at sea level in Celsius?",
]
PROMPTS = [f"<|im_start|>system\n{SYS}<|im_end|>\n<|im_start|>user\n{q}<|im_end|>\n<|im_start|>assistant\n"
           for q in QUESTIONS]

USE_DRAFT = True          # set False for the control run (crash disappears)
pipe = build_pipe(USE_DRAFT)
cfg = build_cfg(USE_DRAFT)

gens = crashes = 0
for _pass in range(6):
    for p in PROMPTS:
        gens += 1
        try:
            pipe.generate(p, cfg)
        except Exception as e:
            if "GrammarMatcher" in str(e):
                crashes += 1
                print(f"REPRODUCED (gen {gens}): {str(e)[:200]}")
            else:
                print(f"other error (gen {gens}): {str(e)[:200]}")
    print(f"pass done: {gens} generations, {crashes} crashes")
```

1. Run as-is (`USE_DRAFT = True`): crashes roughly 1 in 20–75 generations. Because it is intermittent, let it run a few passes; re-run if a short pass happens to be clean.
2. Control — set `USE_DRAFT = False` (drops the draft model and `num_assistant_tokens`, keeps the grammar): **0 crashes** over the same passes.

I reproduced with Qwen3-14B-INT4 (target) + Qwen3-0.6B-INT8 (draft), both on GPU, but the crash is at the matcher/speculative seam and does not appear model-specific — any target+draft pair on GPU should serve.

**Expected behavior**

Generation completes normally when a structural-tags grammar and speculative decoding are used together. The grammar matcher should not be queried for a next-token mask after it has accepted the stop token (whether from the main model's stop or from draft-proposed tokens past the stop).

**Evidence** (same machine, same prompts, greedy `do_sample=False`, grammar configured throughout)

| Configuration | Crashes / generations |
|---|---|
| Speculative decoding ON, non-streamed | crashes every run (e.g. 1/76, 1/57, 2/38) — ~1–5% |
| Speculative decoding ON, streamed | 0 / 57 (small sample; a real crash in my app *was* streamed, so I do **not** claim streaming avoids this — likely undersampled) |
| Speculative decoding OFF (no draft), non-streamed | **0 / 57** |
| Grammar not attached at all | 0 / 19 |

**Environment**

```
OpenVINO GenAI : 2026.2.1.0-3123-7dea0459b2a  (win_amd64, cp311 wheel)
OpenVINO       : 2026.2.1-21919-ede283a88e3-releases/2026/2
xgrammar       : vendored in the GenAI build (_deps/xgrammar-src)
Python         : 3.11.9
OS             : Windows 11 Pro (build 26200)
CPU            : Intel Core Ultra 7 258V (Lunar Lake)
GPU            : Intel Arc 140V (Xe2 integrated), driver 32.0.101.8826
Target model   : Qwen3-14B OpenVINO INT4, device GPU
Draft model    : Qwen3-0.6B (pruned 6-layer) INT8, device GPU, num_assistant_tokens=3
Decode         : greedy (do_sample=False), max_new_tokens=512, prefix caching ON
```

**Root cause confirmed + fix (with verification numbers)**

I traced this to `XGrammarLogitsTransformer::apply()` in
`src/cpp/src/sampling/structured_output/xgrammar_backend.cpp`:

```cpp
// BEFORE
void XGrammarLogitsTransformer::apply(Logits& logits) {
    m_grammar_matcher.FillNextTokenBitmask(m_token_bitmask.get());
    if (m_grammar_matcher.IsTerminated()) {
        return;
    }
    ...
```

`FillNextTokenBitmask()` is called *before* the `IsTerminated()` check — but
`FillNextTokenBitmask` is exactly the call that asserts
`!IsStopTokenAccepted()`. Under non-speculative decoding the matcher
terminates on the final token and `apply()` is never invoked again, so the
mis-ordering never bites. Under speculative decoding the draft model
proposes tokens *past* the accepted stop, so `apply()` runs one more time on
an already-terminated matcher and the `CHECK` fires. Swapping the two lines
(check termination first, only then fill the bitmask) fixes the crash and is
semantically identical on the non-terminated path. I'm opening a PR with the
fix alongside this issue.

I also added the equivalent guard to `accept_tokens()`, which silences the
companion non-fatal `grammar_matcher.cc:493` warning from the same root
cause (the draft's post-stop tokens being fed to the terminated matcher).

**Verification:** rebuilt from source at the exact commit the crashing wheel
was built from (`7dea045`, `releases/2026/2`), so this is a same-commit
before/after comparison. Baseline (unpatched, same commit) on GPU (Arc 140V,
the originally-affected device): 1 crash / 95 generations, same case and
same assertion as this report. Patched build: since the official Python
`.pyd` is ABI-locked to the exact release build (a `.dll`-only swap fails
DLL load, and a from-source Python-bindings rebuild against my local
OpenVINO checkout has no linked GPU plugin), I verified the patched build
with a standalone C++ reproducer against the same patched library on CPU
instead — the bug is a sampler state-machine ordering error, device-
independent, so CPU is a valid substitute for proving the fix. Result: 0
crashes / 95 generations, same sample size as the baseline. Full methodology
and numbers are in the attached PR's description.

**Is this a supported combination?**

I wasn't able to find documentation on whether structured output / structural-tags grammars are meant to be used together with speculative decoding — the docs describe token-level structured output and speculative decoding as separate features, so I may have simply missed guidance on combining them. If this pairing isn't currently supported, that's completely understandable, and a note to that effect would be genuinely useful. In that case the one thing I'd gently flag is that it currently surfaces as an internal `Check failed` assertion rather than a clear message, so a graceful error would make the limitation easier to discover. Happy to be pointed at the right docs if I've missed them.

**Additional context**

- Workaround in place: disable the structural-output grammar and rely on parse-time JSON-schema validation instead — zero crashes since.
- Happy to test on additional configurations (streaming on/off, different `num_assistant_tokens`) on this Lunar Lake / Arc 140V machine if a maintainer wants more data before merging the linked PR.

---

*AI assistance disclosure (per the OpenVINO AI Usage Policy): this report was drafted with AI assistance. The underlying observations are first-hand and reproducible — the crash, the four-configuration isolation runs, the token-level capture, and the environment were all produced on the hardware described above and reproduced multiple times, and the reproduction script in this issue was run verbatim and confirmed to crash before filing.*
