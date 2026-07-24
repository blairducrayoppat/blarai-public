# POSTED 2026-07-16 (LA-directed) → https://github.com/openvinotoolkit/openvino.genai/issues/3937#issuecomment-4998836610

> Companion to the #36270 comment (same measurement session, same box). Post from the
> operator's account (blairducrayoppat) after his review. Engagement-first: this is a
> comment on the existing genai #3937 thread, not a new issue.

---

A backend-isolation datapoint that may help scope this issue.

**Setup:** Qwen3.6-35B-A3B (unsloth UD-IQ4_XS) and Qwen3.6-27B (unsloth IQ4_NL) under
llama.cpp b9957 (`llama-server`, Vulkan, Arc 140V/Lunar Lake, all layers on GPU), probed on
the OpenAI-compatible endpoint with greedy decoding, 220-token cap, one prompt — the same
prompt we previously used to probe this behaviour under OpenVINO GenAI 2026.2.1.

**Findings (the usable evidence is the 35B-A3B — the 27B produced degenerate output in
every condition on this endpoint, see 3):**

1. **The `/no_think` half of this issue appears to be documented model behavior, not an
   OpenVINO defect** — the official Qwen3.6 model card states: "Qwen3.6 does not
   officially support the soft switch of Qwen3, i.e., `/think` and `/nothink`", and names
   `enable_thinking` (via chat-template parameters) as the supported control. Our probe
   matches: on the 35B-A3B under llama.cpp the switch is ignored exactly as under GenAI
   (coherent thinking consumed the entire token budget with the switch present).

2. **The template-level control does work under llama.cpp, on the 35B-A3B:** passing
   `chat_template_kwargs: {"enable_thinking": false}` on the request cleanly disabled
   thinking and produced a coherent answer (greedy, single sample).

3. **Caveat on the 27B:** under this build's /v1/chat/completions path the 27B GGUF
   degenerated (repeated filler tokens) in all three conditions, so it offers no usable
   toggle signal in either direction — notably the same file was coherent on the raw
   completion path in our earlier benchmarks, which points at a chat-template/server
   interaction rather than the model weights.

4. **How this lines up with the issue and with PR #4139:** in our own GenAI probe
   (2026-07-08, GenAI 2026.2.1) `generate(enable_thinking=False)` was ACCEPTED without
   error and had no effect — matching this issue's report — and `GenerationConfig`
   introspection showed no thinking-related field. Since the model card names the
   template-level switch as the family's supported thinking control (and the soft
   switches as unsupported), the direction PR #4139 takes (first-class
   `enable_thinking` in `GenerationConfig`) looks like the right resolution path to us;
   the llama.cpp datapoint above is evidence the control works when it genuinely
   reaches the template.

Happy to share the raw probe JSON (per-condition outputs and token counts) if useful.

---

## Internal notes (strip before posting)

- Evidence: `docs/performance/probe_thinking_toggle_llamaserver_2026-07-16_19-39-33.json`
  + the 2026-07-08 OV probe `docs/performance/qwen36_27b_thinking_toggle_probe_2026-07-08.json`.
- Detection rule: heuristic (</think> tag + leading narration) OR the server's parsed
  `reasoning_content` present — the server strips tags into that field, which the bare
  heuristic misses (caught during tonight's run; recorded in PERFORMANCE_LOG).
- ADR-012 §2.4 impact (internal): on the OpenVINO substrate NEITHER Qwen3.6 model has a
  working thinking-disable today — the model-swap watch blocker stands unchanged.
- Post AFTER (or together with) the #36270 comment per the LA's sequencing call.
