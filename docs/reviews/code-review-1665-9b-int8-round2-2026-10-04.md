# Independent review, round 2: #1665 Qwen3.5-9B INT8 (2026-10-04)

Tested at `ed094d3b` (branch `feat/1665-qwen35-9b-int8`, base `7ff56bc6`). HEAD moved from `13627366` to `ed094d3b`
during the review; the only change is the added journal fragment, which this review read at `ed094d3b`. No code changed.
No model loaded, no full suite, no upload. The worktree is unmodified apart from this file.
Suites run one file at a time with `LOCALAPPDATA=$(mktemp -d)`:
`test_hf_publish` 78 passed, `test_phase1_review_fixes` 25, `test_phase1_size_parameter` 19,
`test_phase1_speed_exploratory` 8, `test_probe_pa_variants` 21, `test_phase1_launcher_and_analysis` 33.
Mutants ran on a `git archive HEAD` copy in the session scratchpad.
Raw data: `C:/Users/mrbla/blarai-research-data/qwen35-9b-int8-2026-10-04/`.
One read-only network action: `hf datasets ls` plus `hf download` of the two public README files into the scratchpad.

Counts: 2 blocking, 6 should-fix, 6 notes.

---

## Blocking

### G1 BLOCKING (the verdict's "Your decision" section) - the production premise behind both Policy Agent recommendations was not checked, and the code answers it
The verdict says, at lines 81, 91 and 96, that "whether real orchestrator requests ever carry a command under a rejected field
was NOT checked", and that the rate of rejected real requests is still to be evaluated. A grep and one call answer both:
- Every production construction site of a CAR (Canonical Action Representation, the Policy Agent's request object) puts
  arguments under a key the same allowlist rejects:
  - `services/assistant_orchestrator/src/entrypoint.py:401`: `parameters_schema={"args": tool_args}`.
  - `services/ui_gateway/src/url_adjudicator.py:111`: `{"purpose": ..., "method": "GET"}`.
  ```
  validate_parameters_schema({'args': '{"query":"x"}'})  -> (False, 'Disallowed schema key: args')
  ```
  So every argument-bearing real CAR would render as `[SCHEMA_REJECTED: Disallowed schema key: args]`.
- Static search finds no live caller of the GPU classifier. `classify_car` is reached only through
  `HybridAdjudicator.adjudicate_car`, which is reached only through the Policy Agent's IPC handler
  (`policy_agent/src/entrypoint.py:1320`). No production code sends `ADJUDICATION_REQUEST`: `encode_request` has 0 callers.
  The AO (Assistant Orchestrator) tool loop and the URL door both call `DeterministicPolicyChecker.check` only
  (`entrypoint.py` docstring: "the PA's GPU classifier is not invoked here").

What this costs:
- Recommendation 2 ("deterministic DENY whenever the schema is rejected; makes both cases correct for any model") would
  deny every argument-bearing tool dispatch and every URL ingest if it were placed where live requests are adjudicated.
- Recommendation 1 rests on "if a real request ever carries a dangerous command in a rejected field, the 14B refuses".
  V8 shows the 14B DENYs on the marker beside a harmless command. The same property would refuse benign real requests,
  and the live path does not consult the model at all.
- The LA (Lead Architect) is being asked to decide on a premise that the code already settles.

Reproduced: the validator call above, and the grep. "No live caller" is a static finding; no runtime trace was run.
That part is a hypothesis.

### G2 BLOCKING (for the arc's publish step) - the retracted claims are still live on the public Hugging Face card, and the committed 4B folder can no longer pass the publisher
The data went to Hugging Face, not only to the repo. So "retract in the place the claim was made" includes Hugging Face.
Downloaded read-only from `blairducrayoppat/openvino-arc140v-lunarlake`:
```
README.md:700        "MTP made the 4B 1.84x to 2.46x faster ... with byte-identical output on every check"
qwen35_small_2026-10-04/README.md:47-48  "Output bytes were identical with and without MTP ... across all 63 model calls"
qwen35_small_2026-10-04/README.md:55     "both misses are expected-DENY answered ALLOW, byte-identical in 3 of 3 runs"   (see G3)
```
Nothing on the branch plans the public correction. PERFORMANCE_LOG marks only the 9B as "not yet uploaded".
The committed 4B folder also fails the new preflight:
```
hf_publish.py preflight --dir docs/performance/qwen35_small_2026-10-04  -> 30 problem(s)
  (7x 'detail' + 3x long 'description' in each of 4b-on/4b-off/14b all-random-r1 reports)
```
The corrected 4B card therefore cannot go up with the folder under the publisher as written. It needs a README-only
directory, a rebuild, or an argued `--allow-key`. Whichever is chosen, the root `README.md` that the 9B card replaces
must carry the corrected 4B headline.

---

## Should-fix

### G3 SHOULD-FIX - the claim "Policy Agent outputs byte-identical across 3 runs" rests on a hash of the parsed verdict, not of the text (the same class as F2)
`scripts/run_evals_instrumented.py` PA rows set `out_sha = sha(f"{label}|{confidence}|{error}")`; raw text is logged only under
`BLARAI_EVAL_PA_RAW=1`, which ran once. Ticket comment 3854 (5) names this gap. Raw io rows have keys
`['kind','label','out_sha','prompt_len','prompt_sha','tag']` (reproduced on `q9b_on`/`q9b_off`, 3 runs x 13 calls; sequences
equal). The claim is made at:
- PERFORMANCE_LOG.md lines 18 ("byte-identical") and 109.
- The 9B README, line 51.
- The verdict, lines 9-10 and 113 ("identical text").
- The journal fragment, line 13.
- The public 4B card (G2).

What is measured: identical label and confidence in 3 of 3 runs, plus identical raw text in the one raw run and in the probe's
two V0 runs (MTP off only). The agentic and conversation identity claims are fine: those `out_sha` values hash real text.
I checked the V0 r1-r3 sequences and they are equal.

### G4 SHOULD-FIX - the post-hoc exclusion uses one of two readings of "<=72 C before every generation", and the summary says the other rows met the definition
`bench_qwen35_speed.py:781-783`: `wait_for_cold` returns `reached=True` once one poll reads 72 C or less. `gen()` then reads
`thermal_before` immediately before `generate`. Independent recount over A1-A8/B1-B8: 159 cold ok rows. 5 have
`reached=False`. **38 more have `reached=True` with `thermal_before` above 72 C** (72.9 to 76.9; e.g. A2 4b-mtp-on t1: wait
read 69.9, start 75.9). That is 24% of the retained rows. `cold_gate_note` says "a row whose cold_wait.reached is False did
not meet it and is not a cold row", which implies every other row did.

Applying the stricter reading changes these cells:

| cell | n | mean | CV |
|---|---|---|---|
| 9b-mtp-on ao-long | 9 -> 5 | 21.0 -> 21.8 | 14.4% -> 6.5% |
| 9B MTP on/off, ao-long ratio | | 2.173 -> 2.295 | |
| 4b-mtp-on | 6 -> 3 or 4 per cell | | |

The headline 9B-over-14B ratios hold: 1.076/1.715/1.164 becomes 1.077/1.718/1.164.
- The rule is uniform: it is decided on the gate flag only (code read and recount agree).
- The with-rows file keeps the old numbers: re-running with `--include-gate-failures` is byte-identical to the file, and
  diffed against `6213a083:.../speed_summary.json` only the two new keys differ.
- Every human-facing document (verdict, log, README, fragment, roll-up `treatment`) says the exclusion was decided after the
  data was read. The raw `speed_summary.json` `cold_gate_note` does not.
- The decision flipped 10 refused ratios to formed. Two arms land at 14.35% and 14.05% against the 15% limit.

**Required:** name the operationalisation (gate poll, not start temperature) and the 38-row count where the exclusion is
described.

### G5 SHOULD-FIX - the preflight still lets generated text through by key name, container shape and file type (F4 only partly fixed)
Each of these returned `[]` (CLEAN) from `preflight()`, with GEN = about 1,270 chars of prose:
```
{"outs":[GEN]}                     list of strings under any key (lists are never length-checked)
GEN as a bare JSON string line     (.jsonl)
csv column "gen" = GEN             (CSV has no LONG_STRING backstop)
raw/README.md = GEN                (any file named README.md at any depth is exempt from the prose check)
.md wrapped at 199 chars           (PROSE_LINE_MAX 200)
a.yaml / a.tsv / LOG (no ext)      (only identity/secret regexes apply)
{"turns":[{"c": GEN[:400]}]}       (<500 under an unlisted key)
hf_<34 chars>.json, mr.blair.do@gmail.com.json   (file names are checked for identity strings only, not secret/e-mail shapes)
{"k":"mr.blair.do\u0040gmail.com"}, {"k":"hf\u005f..."}, {"k":"NORTHSTAR\u003100"}   (JSON escapes; the scan reads raw text)
```
The module docstring says it "refuses credential and e-mail shapes anywhere in the tree". It does not do so for file names
or escaped JSON. No current dataset is affected: the real 9B dataset passes cleanly by content.

A related case is already in the 9B dataset. `raw/pa_variants/*_rows.jsonl` carry `raw_text`, which is model output
("DECISION: ALLOW\nCONFIDENCE: 0.95", up to 51 chars). It passes because `raw_text` is not a listed key. The README discloses
it, but two other texts say the opposite:
- the builder docstring: "Model OUTPUT TEXT is deliberately not copied";
- the publisher agent rule: "no generated model text".

### G6 SHOULD-FIX - the builder can still write into a committed dataset (F9 only partly fixed)
`--out` is now required, but an explicit existing directory is accepted with `exist_ok=True`:
```
cp -r docs/performance/qwen35_small_2026-10-04 <scratch>/fourb   (180 files)
build_phase1_dataset.py --run-dir <9B run copy> --out <scratch>/fourb  -> 317 files; 4B and 9B summaries, compares, quality reports mixed
```
Nothing refuses a non-empty `--out`. Also confirmed: the 9B rebuild into an empty directory is byte-identical to the
committed folder, except the authored README, and it passes preflight.

### G7 SHOULD-FIX - the Jev research note's evidence does not trace to the rows, and it still carries the retracted framing
`docs/research/jev-policy-agent-ideation-2026-10-04.md:78-81` says: 103 answers, 102 at CONFIDENCE 0.95, "all 10 wrong ALLOWs",
probability 0.34 to 0.81, nine below 0.75, and all 32 correct ALLOWs at 0.968 or above.

From `9b_rows.jsonl` rep 1:

| measure | the note | the rows |
|---|---|---|
| answers | 103 | 104 |
| at CONFIDENCE 0.95 | 102 | 103 |
| wrong ALLOWs | 10 | 11 |
| their top-label probability | 0.34 to 0.81 | 0.356 to 0.815 |
| below 0.75 | 9 | 9 of the 11 |

The 32 correct ALLOWs at 0.968 or above is correct. Leaving out the benign V7 control gives 10 wrong ALLOWs, 0.400 to 0.815,
8 below 0.75. Neither count matches the note. The 0.34 is the V7 pa-mdl-007 DENY.

Two more lines in the note are stale:
- Line 79, "the ANALYSIS.md named in the brief does not exist there": the file now exists.
- Line 69, "the family that ALLOWs the two dangerous cases": this framing has no retraction mark, after the rest of the branch
  retracted it.

The note feeds #1672.

### G8 SHOULD-FIX - there is no disposition record for round 1
`docs/reviews/` has no `*1665*disposition*` file. F1-F11 and N1-N8 are dispositioned only in commit messages, so
`scripts/verify_disposition.py` has nothing to check. F4, F9 and F11 are partial fixes (see below) and need FIXED, DEFERRED or
REJECTED rows. G1-G14 also need rows.

---

## Notes

- **G9** One more MTP on-versus-off divergence exists outside the pinned runs: `9b-on-all-random-r1` ao call, prompt
  `2a556ae813fb04f4`, same prompt, different output. I paired 192 same-prompt calls across the random runs by `prompt_sha`:
  1 differs (the 4B: 0 of 195). The docs list "output identity beyond the pinned runs" as NOT measured, but the data measured
  it once.
- **G10** The speed MTP acceptance "3475 of 4635 over 275 generations" comes from the cumulative pipeline counter, which
  includes the discarded warm-up. Per-row sums are 3445 of 4635 over 265 generations (74.33%). The counter credits 3 accepted
  tokens and 0 drafted per visit, which cannot happen, so the counter itself is suspect. The rounded "75 percent" survives.
- **G11** Wording mismatches:
  - Verdict table: the column "4B with MTP (earlier today)" holds the same-day bridge figures (48.9/36.0/34.7, 4.3 s,
    +9.8 GB), not Study 3's (51.1/37.3/36.6).
  - Journal: "two of them narrowly" — five ratios use the near-limit CVs.
  - Journal: "'identical in every check' was true of the runs I looked at" reads as an endorsement.
  - Speed note: "the shipped 14B ... 2 of its plateau multi-turn cells" — one of the two is `14b-ship@2026.4`, the runtime
    control.
- **G12** `_CONFIG_RE` and `_SEGMENT_RE` use `$`, which matches before a trailing newline. `--path-in-repo $'x\n'` and
  `--config $'c1\n'` are ACCEPTED; the message is protected by its strip check. Also, a refusal message that contains
  non-cp1252 text crashes `print` with UnicodeEncodeError. The run still exits non-zero, so it fails closed, but loudly
  wrong. Option-shaped values are rejected after the fix: `-x`, `a/-x`, U+2010, U+2212, U+FF0D, U+0661, ZWSP, `./x`,
  `a//b`, `C:evil`, `.gitattributes`.
- **G13** Mutants that SURVIVED:
  - Gate exclusion widened to drop `reached is None` (unmeasured) rows: the unmeasured-gate behaviour is unlocked, and keeping
    such rows as cold is itself an absence read as a pass. Incidence 0.
  - The probe's `ClassificationParser.parse` patch not restored: `run_case` has no test at all.

  `probe_pa_variants.py:47,67` hard-codes `C:/Users/mrbla/...`; this is the N8 class again, in a repo the public mirror carries.
- **G14** Prompt identity holds within each model, but the comparison across models is not like-for-like:
  - The 14B classifies a double-templated prompt: `apply_chat_template` stays True for non-multimodal brains
    (`gpu_inference.py:1101-1120`). The Qwen3.5 arms run through `evals.cb_pipeline` with the template off. The 14B's
    marker reaction was measured under that shipped double wrap (hypothesis; not run).
  - 5 of 13 model-mode golden cases carry a rejected schema: 004 `recursive`, 005 `append`, 007, 011 `content`, 013. The
    Qwen3.5 models DENY 3 of them with the marker present. So "the Qwen3.5 models ignore the marker" rests on 007/013 and V4
    only.

---

## Round-1 findings, re-run at `ed094d3b`

| F | status | evidence |
|---|---|---|
| F1 | CONFIRMED FIXED | CLI `upload "--path-in-repo=--delete=*"` and `=--revision=x` -> exit 2, 0 subprocess calls. A clean value produces `[... '--commit-message','m','--',REPO,DIR,'ok/data']` (hf 2.1.1 `upload --help` confirms the positional layout). Mutant (leading `-` allowed) killed. |
| F2 | CONFIRMED FIXED in repo | Recomputed from raw io: 9B pinned 2 of 366 (agentic-V3-r1 calls 10, 26; common prefix 198/152); 4B pinned 1 of 377 (call 17, prefix 402). Retractions are in place in the repo. The public card is not corrected (G2). |
| F3 | CONFIRMED FIXED for builder output | 9B rebuild passes preflight CLEAN with no exemption and is byte-identical to the committed folder; mutant (keep `detail`) killed. The committed 4B folder fails (G2). |
| F4 | PARTIAL | Token, e-mail, USERNAME/COMPUTERNAME and option-shaped messages are caught. Generated-text holes remain (G5). |
| F5 | CONFIRMED FIXED | Mutant `!= MODEL_14B` -> `startswith("4b")` KILLED (2 failed). |
| F6 | CONFIRMED FIXED | `ttft_summary.json` has no `four_b_arms_agree`; mutant (emit 4b/9b always) KILLED. |
| F7 | CONFIRMED FIXED | `mtp_witness` rows carry `arm`. |
| F8 | CONFIRMED FIXED | Notes are computed from the arms that ran; the 14B n_distinct=2 cells match the table. Wording nit in G11. |
| F9 | PARTIAL | No default `--out`; dropped files are printed. An explicit `--out` still mixes (G6). |
| F10 | CONFIRMED FIXED | `compare_9b_vs_14b.json` covers all 12 pinned runs plus `suites_all_random_r1`; the 14B runtime reads "runtime not recorded in these reports". |
| F11 | PARTIAL | Cited keys now exist (`pinned_totals.runs_with_differing_outputs`, `pass_counts`, `runs`, `ratio_pairs_not_formed`, `cv_limit_pct`). Tools are still inherited, so the network boundary is prose (argued in the file). |

## Numbers recomputed independently from raw rows (all match the analyser and the documents)

COLD decode visit-mean (n, mean tok/s, CV%), gate-excluded / pooled:

| arm | pa | ao-long | multiturn:t1 |
|---|---|---|---|
| 9b-mtp-on | 9, 26.608, 2.82 / 10, 25.359, 15.82 | 9, 20.962, 14.35 / 10, 19.597, 26.35 | 9, 24.953, 2.87 / 10, 25.007, 2.78 |
| 9b-mtp-off | 9, 10.307, 1.11 | 9, 9.648, 7.75 | 9, 10.366, 1.03 |
| 14b-ship@2026.2.1 | 8, 24.734, 3.27 | 8, 12.220, 10.92 | 8, 21.436, 2.70 |
| 14b-ship@2026.4 | 9, 24.481, 3.87 / 10, 23.233, 17.42 | 9, 11.006, 14.05 / 10, 10.378, 23.72 | 10, 21.616, 2.89 |

Ratios, gate-excluded:

| cell | 9b-mtp-on / 9b-mtp-off | 9b-mtp-on / 14b-ship@2026.2.1 |
|---|---|---|
| pa | 2.582 | 1.076 |
| ao-long | 2.173 | 1.715 |
| multiturn:t1 | 2.407 | 1.164 |

The exclusion flips exactly 10 decode ratios from refused to formed and none the other way. All five excluded rows are in A6
visit 0.

41 numbers in the documents were traced to raw files. 39 match and 2 differ (G10):
- sampler 3657 samples, CPU 15.8/55.5, Bitdefender 3657 of 3657, OneDrive 0;
- 1429 speed rows;
- cold TTFT 5769/6150/11728/4293 and 1067/1191/1614/964;
- PA 33 of 35 with fails {007, 013} in 3 runs for both arms;
- quality acceptance 7954 of 11011;
- V1/V2/V3 prompt changes 17/38, 3/38, 4/23, 37/38, 22/23, V1-conversation 0;
- 0 XML in 489/488;
- live turn 6: 2148/2214/775/810 and turn 1 605/1083, per-token 42.1/98.0/97.0/53.8.

Also checked:
- memory: 3.1 GB = 17.51 - 14.41;
- Study 3 cross-references: 10.36 [11.3%, 4], 37.3/36.6/51.1;
- all 36 ratio keys in the roll-up JSON equal `speed_summary.json`.

Variant-probe tables (verdict, log, README) match the rows cell for cell for all three models:
- V3 prompt SHA equals V0 on 13 of 13 cases for each model; V1 and V4 change all 13; V2/V6/V7/V8 change the 2 command cases;
- 0 flips among the other 11 cases in every variant;
- the 9B V0 rep 2 is identical to rep 1;
- the 14B has probe_error on 104 of 104 rows; its greedy labels come from `classify_car` before the probe call.

## Verified clean

- The exclusion is applied on `cold_wait.reached is False` only, to every arm, in the cold stats, the ratios and the
  exploratory block. Mutant (never exclude) killed.
- No runtime file changed (`services/`, `shared/`, `launcher/` untouched). No new network code in `scripts/`. Nothing under
  `services/`, `shared/`, `launcher/` or `evals/` imports `hf_publish`, `probe_pa_variants`, `phase1_sizes` or
  `build_phase1_dataset`.
- The probe's `patched_formatter` restores `format_car` and `SYSTEM_PROMPT` (mutants killed). The probe edits no shipped file.
- `pa_raw.jsonl` and campaign logs are not copied into the dataset; the builder names them.
- The new script docstrings and comments carry no current-sprint or wiring-state claims.
- The coder-containment note's checkable citations hold: `default.toml:435` `enabled = true`; agentic-setup `fleet-driver.json`
  `"containment": "off"`; commit `4c91809`; `new-agent-task.ps1:134`. The ideation note on a third-party agent sandbox: its external-source claims were not
  verified.
- Stale-claim grep across the tree at HEAD ("byte-for-byte identical", "63 of 63", "lets two dangerous", "dangerous actions",
  "do not know why", "missing deny example"): every hit in the 4B/9B documents is inside a strike-through or a retraction,
  except `jev-...md:69` (G7). The CPU-overlap explanation is retracted in all four 9B texts.

## Merge read

- Block the verdict going to the LA until G1 is answered from the code. Both recommendations change once it is known that
  real CARs are always schema-rejected and that live adjudication does not consult the model.
- Block the HF publish step on G2.
- The harness and analyser code can merge after G3-G8 are fixed or dispositioned (G8 requires that anyway). G4 and G3 are
  wording plus one disclosed count, not a re-run.
- The notes do not block.
