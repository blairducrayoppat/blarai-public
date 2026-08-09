# End-to-end device probe — PR #4139 commit 4c0e8d6d, before vs after

Run 2026-07-23 ~21:20-21:28 local, Blair's box, GPU free (he cleared it explicitly).
Probe script: `scratchpad/device_probe2.py`. Raw results:
`scratchpad/device_probe_BEFORE-cea6c5f2.json`, `device_probe_AFTER-4c0e8d6d.json`.

## Why a device run was needed at all

The unit tests pin the state machine, but they cannot show that the transform is
actually constructed with a populated `prompt_ids` on the real LLM path — which matters
here, because the whole VLM branch of this PR exists precisely because `get_prompt_ids()`
comes back EMPTY on the PA/CB adapter path. A device run closes that gap.

## Setup

- Qwen3-14B INT4, `openvino-int4-gpu`, device `GPU` (Arc 140V / Lunar Lake), greedy
  (`do_sample=False`), `max_new_tokens=20`.
- The fix only engages when the PROMPT already carries an open think block. Qwen3's
  template with thinking ENABLED does not emit `<think>` itself, so the prefill shape was
  built explicitly: raw prompt ending `...<|im_start|>assistant\n<think>\n`, fed as an
  encoded tensor. Measured: `prompt_ids` = 17 tokens, last `<think>` at index 15,
  **trailing_after_think = 1** (the `\n`).
- `thinking_start_token_id`/`thinking_end_token_id` set explicitly (151667 / 151668) so
  the probe doesn't depend on auto-detect. CORRECTION (adversary-logic): auto-detect DOES
  run on the encoded-tensor path — the block at `py_llm_pipeline.cpp:69-81` sits before
  the `std::visit` and is input-type agnostic. It simply no-ops once the IDs are already
  set. An earlier draft of this file said it "does not run"; that was wrong.
  The run self-validates those IDs anyway: forcing happened at all, which requires 151667
  to be the token actually at index 15, and the block closed, which requires 151668 to be
  the real `</think>`.
- Prompt geometry captured to `scratchpad/prompt_geometry.json` (17 tokens, last `<think>`
  at index 15, trailing 1) — originally only printed to console, per adversary-facts.
- Script `device_probe2.py` mtime 21:22:07, BEFORE json 21:22:31, AFTER json 21:28:40 —
  the same script text ran both times, unedited between runs.

## Result — exactly one cell changes

| `reasoning_budget_tokens` | BEFORE (cea6c5f2) | AFTER (4c0e8d6d) |
|---|---|---|
| 0  | 0 generated before `</think>` | 0 — same |
| **1** | **1 generated** (`Okay`) — over budget | **0 generated** — FIXED |
| 2  | 1 generated (`Okay`) | 1 — same |
| 3  | 2 generated (`Okay,`) | 2 — same |
| -1 | never closes | never closes — same |

Token sequences on every unchanged row are byte-identical between builds.

**The giveaway:** before the fix, `budget=1` and `budget=2` produced *identical* output
(`[32313, 151668, ...]` = "Okay</think>"), because the prompt's trailing `\n` had already
consumed the budget of 1 yet one more token was still admitted. After the fix, `budget=1`
matches `budget=0` (`[151668, ...]`) and the think block holds exactly `budget` tokens.

Also confirmed incidentally: `prompt_ids` IS populated on this LLM path — the reverse
scan found the `<think>` at index 15 and counted the trailing token. The empty-prompt_ids
problem is specific to the other path, as traced.

## Build provenance — and one wart to be careful about

- BEFORE = the wheel already installed in `venv-build`, built at `cea6c5f2`. Verified
  `git diff cea6c5f2 92e6281 -- logit_transformers.hpp` is EMPTY, so it is a faithful
  pre-fix baseline.
- AFTER = `openvino_genai.dll` + `py_openvino_genai.pyd` rebuilt from the working tree
  with `4c0e8d6d`'s header restored (grep confirmed the fix present immediately before
  the build; build9_dll.log BUILD_EXIT=0; artifacts timestamped after the checkout),
  copied over the installed ones, then the originals restored afterwards.
- `git diff cea6c5f2 4c0e8d6 -- src/` = the 5-line fix PLUS comment-only translation
  churn in `py_llm_pipeline.cpp` / `py_vlm_pipeline.cpp` (87acf7b8). **No other code
  differs**, so the behavioural delta isolates the fix.
- **WART, do not misreport:** the AFTER run printed version
  `2026.4.0.0-50-8cf5e4502f3`. That string is baked at CMake *configure* time (the
  build dir was configured at 8cf5e450) and does NOT reflect the working-tree source.
  The evidence the fix was in the binary is the header grep + the behavioural change at
  exactly the predicted cell — not the version string. Never cite that string as proof.

## State left behind

`venv-build` restored to its original cea6c5f2 binaries (verified: reports
`2026.4.0.0-52-cea6c5f2690`). Working tree header back at 4c0e8d6d. Backups kept at
`scratchpad/venv_backup/`.
