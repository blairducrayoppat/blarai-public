# PR #4139 cycle-3 measurement record — head `cea6c5f2` vs prior head `8cf5e450`

Date: 2026-07-23. Operator: LA (blairducrayoppat), measurements executed by Claude
(AI-assisted, human-directed). Status: **complete, verified**.

## Context

Same-day author response cycle: after LA's cycle-2 comment (`5054376503`), the author
pushed two commits and re-requested LA's review; apaniukov left a second inline suggestion
(reverse prompt scan), which the author implemented within ~1 hour.

- `edbd2428` — "Extend auto-detect thinking token IDs to cover reasoning_budget_tokens"
  (Python bindings only: `py_llm_pipeline.cpp`, `py_vlm_pipeline.cpp`; 3 call sites;
  new comments written in Chinese).
- `cea6c5f2` — "Address review: reverse scan prompt_ids with trailing token count"
  (`logit_transformers.hpp` only): reverse scan, last think-token wins;
  `start_id` → COUNTING with `m_count` = number of prompt tokens after it;
  `end_id` → DONE; neither → IDLE; `budget==0` still overrides to FORCING.

## Provenance

- Hardware: Intel Arc 140V iGPU (Lunar Lake, Core Ultra 7 258V, 32 GB LPDDR5X), Windows 11.
- Model: `OpenVINO/Qwen3.6-35B-A3B-int4-ov` (official IR), `VLMPipeline`, device GPU, greedy.
- Wheels built from source at each commit (py-build-cmake, MSVC 2022 + Ninja, openvino
  2026.4 dev nightly): new head `2026.4.0.0-52-cea6c5f2690`, prior
  `2026.4.0.0-50-8cf5e4502f3` (cycle-2 JSON reused; same probe, same prompt, greedy).
- Probe: `probe_pr4139_35b_v2.py --conditions full` (exact streamed token IDs via
  StreamerBase; sha256 over full output; full ID arrays in JSON).
- Raw JSONs (`BlarAI/docs/performance/`):
  - new: `probe_pr4139_v2_2026.4.0.0-52-cea6c5f2690-feat-thinking-suppression_2026-07-23_07-22-56.json`
  - old: `probe_pr4139_v2_2026.4.0.0-50-8cf5e4502f3-*_2026-07-22_20-24-08.json`

## Results — per-condition, full generated-ID-sequence comparison old vs new

| condition | old (8cf5e450) | new (cea6c5f2) | verdict |
|---|---|---|---|
| A default (220) | sha `492c6a247f87` | same sha | **ID-identical** |
| B enable=False, no ids (220) | forced 248069 @0, `c24d78c8f169` | same | **ID-identical** |
| B2 enable=False, explicit ids | ≡ B | ≡ B | **ID-identical** |
| C0 budget=32, NO ids (300) | **validate() error** (ids required) | **clean run**, `87805ecb5e1f` | **CHANGED — the only delta** |
| C8 / C32 / C128 explicit ids (300) | `87805ecb5e1f`, never fires | same sha, never fires | **ID-identical** |
| D closed-block + budget 32 (300) | clean passthrough `77c19e99743c` | same | **ID-identical** |
| E closed-block + enable=False (300) | forced @0, `a1f2087181cd` | same | **ID-identical** |

Cross-checks at new head: C0 ≡ C8 ≡ C32 ≡ C128 (full-ID equality); A(220) is an exact
prefix of every C(300); 248068 (`<think>`) never generated in any condition.

## Findings

- **F8 — §4b fix confirmed on hardware:** budget-without-ids no longer raises; auto-detect
  resolves 248068/248069 and the run is ID-identical to explicit-ids. Loud-error → silent
  no-op on this path (see F9).
- **F9 — VLM non-chat budget no-op unchanged:** all budget runs remain byte-identical to
  default. Neither commit touched the VLM prompt_ids path; scope question to apaniukov
  stands exactly as posed. Note C0's failure mode changed from loud error to silent no-op —
  worth one line in the thread.
- **F10 — reverse scan observationally invisible on this path** (empty prompt_ids → IDLE
  under both old and new scan). Its real semantics are pinned at unit level instead (below).
- **F11 — C++ unit tests updated to the new semantics, 11/11 green** at `cea6c5f2`
  (`build-tests/`, `tests_continuous_batching.exe`): trailing prompt tokens pre-count
  against the budget; last think-token wins; closed-block → DONE with re-arm on new
  `<think>`; budget==0/closed-block pinned as author-confirmed-deliberate.
  Full suite: **564 passed / 2 failed**, both failures = uninstantiated parameterized
  suites gated on `CACHE_TYPES_CSV` (local env, not code). The 13 `AddSecondInputTest`
  failures seen first were local DLL discovery (fixed via `OPENVINO_TOKENIZERS_PATH_GENAI`);
  3 scheduler/blockmanager failures in the first full run passed in isolation and in the
  final full run (order/load-dependent flakes, pre-existing).
- **F12 — un-pinned edge, flagged not tested:** if the trailing count already ≥ budget at
  construction, COUNTING still admits one generated token before FORCING (the check only
  runs in `accept_token`). Left un-pinned deliberately; flag to author as a question.

## Not measured

- Any LLMPipeline path (model ships as VLM IR only) — trailing-count budget shift
  (fires `budget - trailing` after generation start) is NOT hardware-verified here,
  unit-level only.
- VLM chat path (`start_chat()` history) at new head.
- Whether `get_prompt_ids()` is empty vs pad-filled on this path (author reports empty
  from a debug print; our cycle-2 reading said pad-filled tensor — not yet reconciled).
