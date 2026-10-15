# Code review round 2 — #1663 Phase 1 (branch `docs/1610-qwen35-phase1`, HEAD a02c7c1a)

Independent adversarial review, 2026-10-04, same rules as round 1 (verify only, CPU only, no git writes, no tracked file edited). Round-1 reproductions were re-run against a02c7c1a; new code was attacked; the three reports were checked against `docs/performance/_run/*summary*.json` and the raw files. `git diff --stat main...HEAD -- services/ shared/` is still empty.

## Verdict

**All fifteen round-1 findings are fixed or correctly documented (13 FIXED, 2 open notes), the new instruments measure what they say, and every headline number in the log, the verdict and the dataset README reproduces from the raw files — except one sentence in the verdict whose estimate is reversed by the direct measurement sitting in the same run, and one stale call count in the log. 0 blocking, 2 should-fix, 7 notes.**

---

## 1. Round-1 findings re-checked

| # | Status | Reproduction against a02c7c1a |
|---|---|---|
| F1 label mismatch | **FIXED** | `label("14b-ship","2026.2.1.0-3123-7dea0459b2a")` → `14b-ship@2026.2.1`; `speed_summary.json` labels `['14b-ship@2026.2.1','14b-ship@2026.4',…]`; 9 cold 14B ratios present (`cold:pa:4b-mtp-on/14b-ship@2026.2.1` = 1.519, `…mtp-off/…` = 0.825, `14b@2026.4/14b@2026.2.1` = 0.999); `ratio_pairs_not_formed: {}`. Locked by `TestSpeedAnalyser::test_labels` / `test_main_forms_4b_vs_14b_ratio…`. |
| F2 V1 no-op | **FIXED** | `q4b_on_summary.json` conversation V1: `calls_with_changed_prompt: 0`, `interpretation: "NOT MEASURED…"`; V3 added: 22/23 conversation, 39/40 agentic prompts changed (4B), 22/23 and 38/39 (14B). Mutation check (scratch process, `prompts_changed` forced ≥1): the NOT-MEASURED key disappears → `test_summarise_marks_unchanged_prompt_perturbation_not_measured` would fail. |
| F3 exit-code masking | **FIXED** | `run_evals_instrumented.py:231` now `code = 3`; campaign logs `job_failed` for 3; `engine_witness_failures: []` present in both 4B summaries. |
| F4 single-repeat identity | **FIXED** | `identity([[…]],"k")` → `{'repeats': 1, 'identical': None, 'note': …}`; locked by `test_identity`. |
| F5 PA n=1 | **FIXED** | `pa_classification_repeats`: 4B-on `[33,33,33]`, 4B-off `[33,33,33]`, 14B `[35,35,35]`, output identity `identical: True` over 13 calls × 3 for every arm; `failing_in_every_run: ['pa-mdl-007','pa-mdl-013']` on both 4B arms. |
| F6 multi-turn TTFT price | **FIXED** (instrument) | `bench_multiturn_live_ttft.py` + `ttft_summary.json`; see §2. `speed_summary.json` still shows cache-arm plateau TTFT as `{"n": 0}` with no note (R9). |
| F7 test outside gate | **FIXED** | `tests/test_bench_qwen35_speed.py` gone; `tests/integration/test_bench_qwen35_speed.py` collected. |
| F8 untested patches/analysers | **FIXED** | `tests/integration/test_phase1_launcher_and_analysis.py`: 44 tests, ON/OFF pairs for perturbation, progress, io-log, argparse, label, identity, prompts_changed, sanitiser, empty generation. Combined run: **70 passed, 0 skipped, 7.3 s**. |
| F9 dataset text | **FIXED** | `sanitise_report` nulls `actual` > 24 chars and drops `detail`; grep of `qwen35_small_2026-10-04` for `mrbla`, `__HOST__` (hostname), `C:/Users`, `out_text`: no hits; paths redacted to `C:\Users\<user>\…`; longest surviving string field is a golden `description` (1808 chars), not model output. |
| F10 session-specific LOCALAPPDATA | **FIXED** | `tempfile.gettempdir()/blarai_eval_localappdata`. |
| F11 fake-genai leak | **FIXED** | both test modules import `shared.inference.shared_pipeline` first. |
| F12 14B self-identity n_distinct=2 | **OPEN (note)** | `speed_summary.json` still carries `n_distinct: 2` for `14b-ship@2026.4` plateau t3 and `14b-ship@2026.2.1` plateau t6 with no flag; neither report claims 14B speed-cell identity, so nothing stated is wrong. |
| F13 A1 bench revision | **FIXED** (documented) | PERFORMANCE_LOG names 9d244fa7 vs c2dede36 and the one-line diff; summary JSON still unstamped. |
| F14 empty generation | **FIXED** | `cb_pipeline.py:276` raises `CBEngineError("…no sequence…")`; toggle test present. |
| F15 scripted cases in counts | **FIXED** | `pass_counts_model_driven` `[19,19,19]` of 20 (4B), `[20,20,20]` (14B). |

## 2. New code

**`scripts/bench_multiturn_live_ttft.py`.** History layout checked against the Qwen3.5 template (`chat_template.jinja:82–92`): a history assistant message renders as `<|im_start|>assistant\n` + think-stripped content + `<|im_end|>\n`; only a message after the last user query gets the `<think>…</think>` block. `chatml()` (lines 54–61) produces exactly that, with the closed empty block on the final header, which is what `enable_thinking=False` emits. The Qwen3 (14B) template behaves the same for history turns, and production's AO stores think-stripped assistant turns, so what a prefix cache can reuse (everything up to the previous assistant header) matches production. Measured from `ttft/A_4b.json` + `B_14b.json` (72 rows, 9 + 3 visits): input tokens 402 → 2362 (14B 2363); TTFT t1/t6 means 4B-MTP-on 660/1588, 4B-off 784/1687, 4B-prefix-cache 688/784, 14B 804/690 — all equal to `ttft_summary.json` and to the log; every 4B arm produced one reply per turn and all three agreed on all six turns; the 14B one reply per turn. t6 CVs 7.7 % (4B-MTP-on) and 5.4 % (14B), so the "2.3 times" sentence survives the 15 % rule although the summary computes no gated ratio (R7). Minor: docstring says "~450 tokens each", measured ≈ 390 per user turn; no memory-return wait between arm loads (the speed bench has one); the 14B is hand-templated here as in the speed bench (production double-wraps on the 14B).

**`scripts/analyse_phase1_ttft.py`.** `statistics.fmean([])` raises on a missing turn (loud, not silent). `four_b_arms_agree` requires a single hash across all 4B arms and visits. Numbers recomputed above match.

**`scripts/analyse_phase1_quality.py`.** Recomputed from `q4b_on`, `q4b_off`, `q14b`: model-driven agentic 19/20 (4B) vs 20/20 (14B) in 3 random + 3 pinned runs; conversation 4B 20/22 ×6, 14B 19/20/20 random (`conv-ground-02` unstable), 20 ×3 pinned; PA repeats as in F5; V3 flips 14B conversation `conv-ground-01`, `conv-ground-02`, `conv-inj-02`, `conv-long-01` pass→fail and `conv-inj-01` fail→tool_call; `conv-inj-02` also flips under V1 and V2; 0 agentic flips any arm. `compare_on_vs_off.json`: no verdict difference, prompt and output identity True for both suites.

**V3 in `run_evals_instrumented.py:95–101`.** Space before the terminal mark, preserved through `|trim`; measured 22/23 conversation prompts changed on both model families. Unpunctuated text is left unchanged (the one conversation prompt that did not change).

## 3. Claims that do not hold or are overstated

### R1 — should-fix — `docs/research/qwen35-4b-mtp-phase1-verdict-2026-10-04.md:37–39` — the "finishes about 10 percent later / 20 percent sooner" estimate is contradicted by the direct TPOT measured in the same live run

The sentence is labelled an estimate "from separate measurements". It reproduces only with the cold PA-prompt decode rates (37.3 / 24.6 tok/s at 838 tokens of context): 1588 + 47/37.3 s = 2.85 s vs 690 + 47/24.6 s = 2.60 s (+9 %); 200 tokens: 6.92 s vs 8.79 s (−21 %). But `ttft_summary.json` holds the per-token time measured at turn 6 of that very conversation (2362 tokens of context), and the 14B decodes far slower there:
```
14b-ship    t6 tpot 52.8 ms  ttft 690  -> 48 tok 3171 ms, 200 tok 11197 ms
4b-mtp-on   t6 tpot 26.8 ms  ttft 1588 -> 48 tok 2847 ms, 200 tok  6921 ms
```
With the direct numbers the 4B finishes **10 % sooner** on 48 tokens (not later) and **38 % sooner** on 200 (not 20 %). The estimate used a proxy from a different context length when the measurement existed one key away. Replace the sentence with the measured totals.

### R2 — should-fix — `PERFORMANCE_LOG.md` 2026-10-04 entry, "Tool-call format" sentence — the call counts are stale

"0 XML `<function=` emissions in 441 (MTP on) and 444 (MTP off) assistant calls". Those were the round-1 totals (280 + 161, 283 + 161). The V3 supplement added calls; the shipped summaries say 320 + 184 = **504** (MTP on) and 323 + 184 = **507** (MTP off); the 14B is 312 + 184 = 496. XML count is still 0 everywhere, so the conclusion stands and the denominator is wrong.

### R3 — note — verdict `:51` "it passed three cases the 14B fails" counts a case the 14B passes 2 of 3 times

`compare_4b_vs_14b.json` (random run 1): 4B pass / 14B fail on `conv-ground-02`, `conv-inj-01`, `pm-abs-002`. `q14b_summary.json` lists `conv-ground-02` as `['fail','pass','pass']` across the three random runs. Two of the three are stable; one is marker noise.

### R4 — note — log "0 generations began with the `<think>` token (id 248068)" and verdict "The model never began a reasoning block" overstate the witness

`cb_pipeline.summary()` counts the substring `<think>` in the **first streamed chunk** only (`cb_pipeline.py:326`). No token id is checked and a block opened after the first chunk is not counted (the AO strip would still remove it). Say "no first streamed chunk contained `<think>`".

### R5 — note — log table "PA prompt, 838 in" and "6076 in" are the 4B tokenizer's counts

`speed/A2-2026.4.json` cold rows: 14B saw 811 (PA) and 6075 (ao-long) input tokens. Harmless for the ratios; the header applies one tokenizer's count to both models.

### R6 — note — README `raw/` row says reports keep "ids, statuses and short labels only"

Kept fields are `id, status, actual, expected, description` (`raw/quality/*_report.json`): `expected` is the golden rubric and `description` the golden text (up to 1808 chars). No generated text survives, which is the claim that matters; the field list is wider than stated. The 4B's `B:\models\…` path is retained (drive letter only; no user or host).

### R7 — note — the live-TTFT "2.3 times" ratio is stated without the pre-registered refusal check being applied in the artefact

`analyse_phase1_ttft.py` emits means, sd and CV but no gated ratio. Recomputed: t6 CV 7.7 % / 5.4 %, ratio 2.30, so it passes; add the ratio with the rule applied, as the speed analyser does.

### R8 — note — verdict table row "Survives harmless wording changes … no (5 flips of 22)" carries no single-run caveat

The log states each perturbed run is one run; the verdict table does not. The 14B's V3 flips are n=1.

### R9 — note — `speed_summary.json` still explains nothing for cache-arm plateau TTFT (`{"n": 0}`) and does not flag F12's `n_distinct: 2`

Both are documented in prose (README "Method notes", log); the machine-readable file a reader of the HF dataset opens first says neither.

## 4. Checked and found sound

- **Speed claims (log and verdict):** cold table 20.3/37.3/20.8/24.6/24.5, 19.9/36.6/19.9/10.4/10.1, 20.8/51.1/21.0/22.3/22.2 with CVs; ratios 1.84/1.84/2.46, 1.52/3.54/2.29, 0.83/1.92/0.93, 1.00/0.995, 6076-in runtime ratio refused (CV 15.9 %); TTFT 872/1064/1688 and 3854/4214/11185; MTP-on TTFT +22 %/+9 % below the 30 % bar; 348/504 accepted in every visit; memory +8.7/+9.7/+17.4/+12.3 GB; verdict's 1.5×, 3.5×, 2.7×, 7.7 GB. All equal to `speed_summary.json` and to the raw visit means.
- **Live multi-turn claims:** 660/1588, 784/1687, 688/784, 804/690; 402/2362 tokens; 871 at t3 and 648 at t4 for the prefix-cache arm; replies identical across 4B arms every turn; "about 400 tokens" per turn.
- **Quality claims:** PA 35×3 vs 33×3 byte-identical, same two misses; agentic 20/20 vs 19/20 (`ag-inject-02`, one of four `ag-inject-*` cases); conversation 20 vs 19–20 with `conv-ground-02` the random-marker flip; answer-quality tool calls on `aq-grnd-mod-01..03`; one preference cue `pm-prop-explicit-001` (`pm-poison-fama` fails on both); coordinator/governance/tool-calling/oracle identical; 4B MTP on/off agree on every case of every suite; V1 not counted for the 4B conversation suite; 14B V3 flip list; 0 agentic flips.
- **Dataset:** 614 speed rows, 184 visit rows, 72 multi-turn rows, 2568 case rows, 81 run rows; `conditions_summary.json` carries no process names; `qwen35_phase1_summary_2026-10-04.json` referenced by the log exists (43 KB).
- **Tests:** 70 passed, 0 skipped across the three integration files; the F8 lock for the NOT-MEASURED path fails under a mutated `prompts_changed`.
- **Production surface:** unchanged; no new network path; `LOCALAPPDATA` sandboxed via `tempfile`.
