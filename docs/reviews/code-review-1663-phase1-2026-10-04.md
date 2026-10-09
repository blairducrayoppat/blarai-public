# Code review — #1663 Phase 1 instruments (branch `docs/1610-qwen35-phase1`, HEAD c2dede36)

Independent adversarial review, 2026-10-04. Worktree `C:/Users/mrbla/blarai-wt-qwen35`, compared with `git diff main...HEAD`. Every finding below was reproduced by running something; the command and its output are quoted. No tracked file was edited; no model was loaded; no GPU work was run. Test runs used `C:/Users/mrbla/BlarAI/.venv/Scripts/python.exe` with `LOCALAPPDATA` redirected to `.../scratchpad/localappdata_rev`.

## Verdict

**The engine arm drives the real PA/AO faithfully and the raw measurements are sound, but two analysis-layer silent no-ops (every 4B-vs-14B ratio and the runtime-confound ratio were never computed; the V1 perturbation arm measured nothing on the conversation suite for the 4B) mean the campaign's comparison claims cannot be read off the built summaries as they stand — 2 blocking, 8 should-fix, 5 notes.**

---

## Findings

### F1 — blocking — `analyse_phase1_speed.py:56` — the 14B label never matches its ratio denominators, so every 4B/14B ratio and the D6 runtime-confound ratio are silently absent

`label()` builds `14b-ship@{genai.split('-')[0]}`. The 2026.2.1 interpreter reports `genai_version = "2026.2.1.0-3123-7dea0459b2a"`, so the label is `14b-ship@2026.2.1.0`; the ratio table at lines 131–133 looks for `14b-ship@2026.2.1`. The `if num in arms and den in arms` guard at line 134 then skips every pair silently.

Reproduction:
```
$ python - <<EOF
spec=...load scripts/analyse_phase1_speed.py...
print(aps.label("14b-ship", "2026.2.1.0-3123-7dea0459b2a"))
print([k for k in json.load(open("docs/performance/_run/speed_summary.json"))["ratios"] if "14b" in k])
EOF
label -> 14b-ship@2026.2.1.0 | ratio denominator expects '14b-ship@2026.2.1' | equal: False
ratio keys mentioning 14b: []
```
`docs/performance/_run/speed_summary.json` confirms: `per_protocol_cell_arm` carries `14b-ship@2026.2.1.0` and `14b-ship@2026.4`; the `ratios` block holds 24 entries, none involving the 14B.

Failure: the three headline comparisons the ticket exists for (`4b-mtp-off/14b-ship`, `4b-mtp-on/14b-ship`, `14b-ship@2026.4/14b-ship@2026.2.1`) were never passed through the CV-refusal rule. The D6 control was measured (n=4 per runtime) and never compared. `scripts/build_phase1_dataset.py:27` copies the same `label()` and will carry the mislabel into the public dataset.

### F2 — blocking — `run_evals_instrumented.py:88–93` + `analyse_phase1_quality.py:110–120` — the V1 perturbation is a no-op on the conversation suite for the 4B arms, and the analysis reports it as a tested arm with zero flips

V1 appends one trailing space to `prompt` and each `prior_turns[].content`. The 4B's chat template trims every message body (`B:/models/Qwen3.5-4B-int8-ov/chat_template.jinja` lines 55, 63, 71, 82: `render_content(...)|trim`). The conversation suite renders through `OrchestratorGPUInference._format_chat_prompt` → `tokenizer.apply_chat_template`, so the space never reaches the model. Measured from the io logs (prompt SHA-256 of what was actually sent):

```
== 4b-on conversation ==   V0-r1 vs V1-r1: prompts differing at same idx: 0 of 23
== 4b-off conversation ==  V0-r1 vs V1-r1: prompts differing at same idx: 0 of 23
== 4b-on agentic ==        V0-r1 vs V1-r1: prompts differing at same idx: 23 of 39
```
V2 (double space after a full stop) touches only the prompts that contain `". "`: 4 of 23 conversation calls and 2 of 40 agentic calls. `q4b_on_summary.json` nevertheless reports `"perturbation": {"V1": {"pass_count": 20, "flipped_vs_V0": {}}, "V2": {...}}` with no count of prompts changed.

Failure: D2's "one trailing space" arm — the perturbation that disqualified the 35B — is structurally unmeasurable on the 4B conversation suite, and the comparison is asymmetric: the Qwen3-14B template has no `trim` (0 occurrences in its `tokenizer_config.json` template), so the 14B will face a real V1 while the 4B does not. The analysis must report `prompts_changed` per variant (from `prompt_sha` V0 vs Vx) and refuse a "no flips" line when it is 0, and V1 needs a perturbation the template cannot erase (for example a space before the final punctuation).

### F3 — should-fix — `run_evals_instrumented.py:220` + `analyse_phase1_quality.py:138–142` — an MTP-not-engaged witness failure is masked on every 4B quality job

`code = code or 3` only changes the exit code when the eval exited 0. Every 4B quality job exits 1 (the baselines are the 14B's):
```
$ grep -o '"job_end": "[^"]*", "exit": [0-9]*' campaign_q.jsonl | ... | sort | uniq -c
     30 1
```
```
eval exit 1 + witness failure -> process exit 1
```
`run_phase1_campaign.py:115` treats 1 as "baseline regression (data, not a crash)". `analyse_phase1_quality.py` then copies `*_engine.json` into `engine_witness` without inspecting `witness_error`. Failure: a run whose MTP head silently never engaged (D4's named hazard) would be indistinguishable from a normal run in the status file, the campaign exit, and the summary. (The witness in fact engaged on every job this time: 615–1834 accepted tokens per job.)

### F4 — should-fix — `analyse_phase1_quality.py:47–65` — `identity()` reports `identical: True` for a single repeat

```
>>> apq.identity([[{"prompt_sha": "a"}, {"prompt_sha": "b"}]], "prompt_sha")
{'repeats': 1, 'calls_per_repeat': [2], 'same_call_count': True, 'identical': True, 'mismatched_calls': 0}
```
Not triggered in the current data (3 pinned repeats were present for both suites), but a partial campaign (one job failed, or `--only` used) would print "input identity: identical" over one observation. Return `identical: None` when `repeats < 2`.

### F5 — should-fix — `run_phase1_campaign.py:41,54–65` — the Policy Agent half is measured once per arm

`MODEL_SUITES = ("agentic", "conversation")`; `pa_classification` and `answer_quality` run only inside the single `all-random-r1` job. The two PA regressions the 4B produced (`pa-mdl-007`, `pa-mdl-013`: DENY→ALLOW, from `q4b_on/4b-on-all-random-r1.out`) rest on n=1 per arm, and `analyse_phase1_quality.py` has no PA repeat or identity block. The PA prompt carries no datamark, so a repeat costs 13 generations; D1 asked for the PA bar to be measured, and the standing rule is no conclusion from one observation per arm.

### F6 — should-fix — `analyse_phase1_speed.py:110–118` — the D5 "multi-turn TTFT price MTP charges" is not produced; cache arms show `ttft n: 0` in every plateau cell with no statement why

The rule "cache-arm TTFT from the cold protocol only" is correct for repeated identical prompts, but the only cells where prefix caching could help a NEW turn (t3, t6) exist solely in the plateau protocol, where the rule discards them. Recomputed from the raw rows (rep 0 = first exposure of that turn's prompt in the visit):
```
multiturn:t3  4b-mtp-off      rep0 n=5 ttft_mean=378.1   4b-prefix-cache rep0 n=5 ttft_mean=334.9
multiturn:t6  4b-mtp-off      rep0 n=5 ttft_mean=437.1   4b-prefix-cache rep0 n=5 ttft_mean=438.4
```
The bench's scripted assistant replies diverge from the cached generation at the assistant header, so the cache hit at t3/t6 rep 0 is partial by construction — the instrument cannot measure the production warm-history case. That is a real limit and must be stated in the summary; as built, `speed_summary.json` shows `"ttft_ms_visit_means": {"n": 0}` and refused ratios with no explanation.

### F7 — should-fix — `tests/test_bench_qwen35_speed.py` sits outside the standing gate

The gate selection (`docs/TEST_GOVERNANCE.md:22`) is `shared/ services/ launcher/ tests/integration/ tests/security/`; this file is at `tests/` root and is never collected by the gate. The 13 tests pass when run directly (below) but protect nothing on merge.

### F8 — should-fix — no test exercises the launcher's measurement patches or either analysis script

```
$ grep -rl "analyse_phase1\|_install_perturbation\|_install_io_log\|_absolutize_report_path\|_install_progress" tests/ evals/ shared/ services/
tests/integration/test_eval_cb_engine.py   (matches only the file's own _load_launcher path string)
```
`TestLauncherControls` tests `_perturb_text` (the pure helper) and `_pin_marker` (the symbol), not `_install_perturbation` (key names `prompt`/`prior_turns`, patch ordering), `_install_io_log`, `_install_progress`, or `_absolutize_report_path`. Deleting any of those four functions leaves every test green. `analyse_phase1_speed.py` and `analyse_phase1_quality.py` have zero tests; F1 is a one-assertion test (`label("14b-ship", "2026.2.1.0-3123-x") == "14b-ship@2026.2.1"`), F2 a one-assertion test on `prompts_changed`.

### F9 — should-fix — `scripts/build_phase1_dataset.py` (untracked) copies model output text while its docstring says it does not

Docstring: "Model OUTPUT TEXT is deliberately not copied (io logs are reduced to hashes and format flags)". The io logs are reduced, but `*_report.json` is copied verbatim (`shutil.copy(rep, ...)`, line ~101), and `CaseResult.to_dict` (`evals/types.py:66–75`) serialises `actual`, the model's answer:
```
cases: 22 | cases whose 'actual' is >40 chars of text: 7
sample actual[:120]: 'I am BlarAI, a privacy-first AI assistant that runs entirely on your local hardware. Your data stays on your device, and'
dataset copy exists: True | contains same text: True
```
`docs/performance/qwen35_small_2026-10-04/raw/quality/` already holds these. Nothing personal is in the eval prompts, but the dataset's own statement of what it contains is false, and D12 says performance rows only.

### F10 — should-fix — `scripts/run_phase1_campaign.py:36–39`, `run_phase1_speed_campaign.py:25` — `LOCALAPPDATA` sandbox is a hard-coded path into one session's scratchpad

`.../claude/C--Users-mrbla/51ec994f-.../scratchpad/localappdata`. The path is created on demand so the scripts run, but the sessions DB of any future campaign lands in a directory tied to a session id that will not exist. Use a path under the repo-ignored run directory or `tempfile`.

### F11 — note — `tests/integration/test_eval_cb_engine.py:221` — the fake `openvino_genai` leaks into `shared.inference.shared_pipeline` if that module is first imported inside the fake window

`CBEnginePipeline.try_run_exclusive` (`evals/cb_pipeline.py:223`) imports `shared.inference.shared_pipeline` lazily; that module binds `ov_genai` at import (`shared_pipeline.py:52`). Reproduced:
```
shared_pipeline.ov_genai is the fake after the window closed: True | _OV_GENAI_AVAILABLE: True
```
In the standing gate `services/*/tests` are collected first and import it with the real module, so the leak is benign there; in a solo run of this file it occurs at `test_raw_handle_generates_without_reacquiring_the_lock`. Import `shared_pipeline` at the top of the test module to pin the order.

### F12 — note — the shipped 14B is not byte-stable with itself in 2 of 16 (arm × cell) plateau combinations; the summary records `n_distinct: 2` and nothing flags it

```
IDENTITY plateau:multiturn:t3: ... 14b@2.4 distinct=2
IDENTITY plateau:multiturn:t6: ... 14b@2.2.1 distinct=2
```
(`speed_summary.json` lines 640, 716.) This qualifies any "identical outputs" sentence: it holds for the three 4B arms (F-claims below), not for the incumbent on long multi-turn prompts.

### F13 — note — invocation A1 ran a different revision of the bench than A2–A4

`speed_summary.json` → `arm_errors: ["A1-2026.4.json 14b-ship visit 0: AttributeError: 'str' object has no attribute 'perf_metrics'"]`. `git diff 9d244fa7 c2dede36 -- scripts/bench_qwen35_speed.py` changes one line in `LLM14Arm.generate` only (`generate(prompt, cfg)` → `generate([prompt], cfg)`), so A1's 4B rows are from an equivalent instrument and are correctly pooled; the 14B@2026.4 arm has n=4 from three invocations (A4 holds visits 0 and 1). The summary should stamp the script revision per invocation; it stamps nothing.

### F14 — note — `evals/cb_pipeline.py:275–276` returns `""` for an empty `m_generation_ids`, contrary to the module docstring's "nothing degrades to a silent empty answer"

`text = texts[0] if texts else ""`. A pipeline that returns no sequence yields an empty `CBText` with a stats row; the AO then fails closed on its own, the PA parses "" to DENY. Raise `CBEngineError` there instead.

### F15 — note — `analyse_phase1_quality.py:92` counts the 10 scripted agentic cases in `pass_counts` (D10)

`29/30` is `19/20` model-relevant; the summary does not separate `scripted` cases.

---

## Checked and found sound

**Attack 1 — adapter vs. the 14B path.** `CBEnginePipeline` presents `generate(prompt, generation_config=, streamer=)`, `try_run_exclusive`, `raw`, `is_loaded`, `get_tokenizer`; the real `PolicyGPUInference` and `OrchestratorGPUInference` attach through `shared_pipeline=` and `load_model()` (`evals/cb_pipeline.py:398–431`). The config the consumers build is passed through untouched except `num_assistant_tokens=3` / `assistant_confidence_threshold=0.0` on the MTP arm (`:252–254`). Prompt format: both consumers set `apply_chat_template=False` for a multimodal directory (`policy_agent/src/gpu_inference.py:1119`, `assistant_orchestrator/src/gpu_inference.py:1529`), which the CB string path honours; the AO renders with `enable_thinking=False` (`:1316`), so `_prompt_opened_hidden_block` is False and the think-strip contract is the 14B's. Stop tokens: the PA resolves `<|im_end|>` through `turn_end_token_id_from_pipeline` → `raw.get_tokenizer()` (`shared/fleet/model_profiles.py:341–357`); the run logs carry no "could not resolve" warning. Greedy: PA `do_sample=False`, AO temperature 0 / top_k 0 / top_p 1 / do_sample False; both `speculative_decoding_enabled=False` so neither sets its own draft knobs. `max_new_tokens` passes through (PA 24, AO `_EVAL_MAX_NEW_TOKENS`). Streamer: forwarded, its `StreamingStatus` returned (`:258–264`); the AO's `_IncrementalVisibleText` is chunk-size agnostic. Lock: `generate` holds the lock for the call; `try_run_exclusive` is non-blocking and hands an `_Unlocked` view, matching `SharedInferencePipeline`. Empirical: ON vs OFF pinned-V0 prompts byte-identical 40/40 (agentic) and 23/23 (conversation); outputs byte-identical 40/40 and 23/23.

**Attack 2 — launcher patches.** `allow_abbrev=False` + `parse_known_args` (`run_evals_instrumented.py:176`): `--engine` is not swallowed by `--engine-summary`. `_pin_marker` patches the symbol that the production call site reads at call time (`context_manager.py:333` inside `add_grounded_context`), and the data show it works: random r2 vs r3 prompts differ (agentic 26 of 41 indices, conversation 2 of 23 = the two `grounded_context` cases); pinned r1/r2/r3 are byte-identical (40/40, 23/23) on both arms. `_install_perturbation` wraps `evals.loader.load_golden` before `evals.run` is imported, and `evals/suites/__init__.py:86` imports suite modules lazily via `importlib.import_module`, so every suite binds the wrapped function (V2 diffs prove it reaches both suites). `_install_io_log` wraps `_generate_from_prompt` (every AO path: `generate`, `generate_text`, `try_generate_text_exclusive`) and `classify_car`; the `all-random-r1` io log holds exactly 13 PA rows = the 13 model-mode PA cases, so prefilter short-circuits do not inflate the count. `_install_progress`: no suite uses `results.extend`/`+=`/reassignment, `SuiteReport.to_dict`/`case_statuses` iterate the list, `evals/baseline.py` uses neither `asdict` nor `replace`. Paths: `--report`, status, io-log, engine-summary and `BLARAI_EVAL_CB_STATS` are made absolute before `os.chdir`; golden and baseline dirs are `Path(__file__)`-relative (`evals/loader.py:20`, `evals/baseline.py:59`), so the worktree's data is read after the chdir into the main checkout.

**Attack 3 — arithmetic, recomputed from raw JSON.** Visit means from `speed/[AB]*.json` match `speed_summary.json` to three decimals: cold:pa 4b-mtp-off 20.270 (n=5, sd 0.734), 4b-mtp-on 37.296 (n=5, sd 2.668), 14b-ship@2026.2.1 24.560 (n=4, sd 0.851), 14b-ship@2026.4 24.529 (n=4); plateau:pa 4b-mtp-off 20.790, 4b-mtp-on 48.283. Keys are `(label, protocol, cell, file, visit)` so visits never collide across invocations. Plateau and cold are never pooled. The CV-refusal rule refuses correctly (e.g. `plateau:multiturn:t6:4b-prefix-cache/4b-mtp-off`, CV 15.58 %). MTP witness per visit 27 generations / 504 drafted / 348 accepted in all five visits, matching the summary.

**Attack 4 — tests.** `tests/integration/test_eval_cb_engine.py` (26) + `tests/integration/test_eval_model_target.py` (30) + `tests/test_bench_qwen35_speed.py` (13): **69 passed, 0 skipped, 36.8 s**, CPU only. Toggle pairs present: `assert_mtp_engaged` refuses at 0 accepted and passes at 5; `cb-mtp-on` without the head refuses at both `resolve_model_target` and `CBEnginePipeline`; a CB target reaches the PA builder with `engine="cb-mtp-on"` while a plain VLM target is still skipped; the three arms differ in exactly draft-present / prefix-caching. No test reads a file outside the repo (the fake VLM dirs are `tmp_path`; `_load_launcher` resolves inside the repo).

**Attack 5 — production surface.** `git diff --stat main...HEAD` touches nothing under `services/` or `shared/`; `git status` shows only untracked `docs/performance/_run/`, `docs/performance/qwen35_small_2026-10-04/`, `scripts/build_phase1_dataset.py`. No network client is added (`watch_eval_run.py` uses `tasklist`; `sample_system.py` uses `typeperf`/`psutil`; `bench` uses PowerShell CIM locally). The launcher's `chdir` into `C:/Users/mrbla/BlarAI` wrote nothing there: `find C:/Users/mrbla/BlarAI -newermt "2026-10-04 05:00"` (excluding `.git`, `models`, venvs, `__pycache__`) returned no files, and the same `find` on the worktree returns today's edits, so the probe works. `LOCALAPPDATA` is redirected by both campaign runners. `evals/cb_pipeline.py` is eval-only and registered nowhere in production.

**Attack 6 — ticket claims against `speed_summary.json` and raw rows.**

| Claim | Holds? | Evidence |
|---|---|---|
| cold decode tok/s, 4B MTP-off ≈ 20 (pa) | yes | 20.27, n=5 visits, CV 3.6 % |
| cold decode tok/s, 4B MTP-on ≈ 37 (pa) | yes | 37.30, n=5, CV 7.2 %; ratio on/off 1.84 (passes the 15 % rule) |
| 14B shipped ≈ 24.6 (pa, cold) | yes | 24.56 on 2026.2.1, n=4, CV 3.5 % (24.53 on 2026.4). **No ratio to the 4B was ever computed** (F1) |
| MTP acceptance 348/504 | yes | identical in all 5 MTP-on visits (27 generations each, warm-up and heat rows included) |
| output bytes identical across arms | yes for the three 4B arms in all 8 protocol × cell combinations (one hash each, union = 1); the 14B differs from itself in 2 of 16 arm × cell combinations (F12); 4B vs 14B outputs are not comparable (different models, and the ao-long prompt is calibrated per tokenizer) | raw `output_sha256` sets |

**Gate-review D1–D12, as built.** D1 measured (PA 35/35 evaluated on both 4B arms; 13 model cases through the real `classify_car`), but n=1 (F5). D2 random ×3, pinned ×3 with identity measured, instrument committed (de0d2b72); perturbation arm defective (F2). D3 order followed; off-repeat, on-repeat and on-vs-off identity all hold; `KV_CACHE_PRECISION`/`DYNAMIC_QUANTIZATION_GROUP_SIZE` stamped on both 4B arms, left at plugin default on the 14B (recorded in the 14B header; a named confound of the 4B-vs-14B comparison, not of on-vs-off). D4 witness present and tested ON/OFF; exit-code masking (F3). D5 two context lengths + multi-turn present; the multi-turn price is not produced (F6). D6 run (n=4), never compared (F1). D7 uptime 0.68 h at A1 (rebooted), driver 32.0.101.8831, `CACHE_DIR=""`, interleaved with ABA bracketing, MDE formula pre-registered in `bench_qwen35_speed.py:56`. D8 content-based watcher with stall/error/death/done. D9 XML count present: 0 XML, 133 JSON (agentic). D10 not separated (F15). D11–D12 outside this review's scope except F7/F9.
