# Independent review, round 3: #1665 Qwen3.5-9B INT8 (2026-10-04)

Tested at `0aafe702` (branch `feat/1665-qwen35-9b-int8`; fixes `db75cd77`, `1f71663c`, `0aafe702` on top of round-2 head
`ed094d3b`). HEAD did not move during the review. No model load, no GPU, no full suite, no upload, no write to Vikunja.
The worktree is unmodified apart from this file.

Suites, one file at a time with `LOCALAPPDATA=$(mktemp -d)`:
- `test_phase1_review_round2` 29 passed
- `test_probe_pa_variants` 23 passed
- `test_phase1_speed_exploratory` 8 passed
- `test_hf_publish` 78 passed
- `test_phase1_review_fixes` 25 passed
- `test_phase1_size_parameter` 19 passed
- `test_phase1_launcher_and_analysis` 33 passed

Mutants ran on a `git archive HEAD` copy in the session scratchpad (`r3/mut`).

Network and board actions, all read-only:
- `huggingface_hub.list_repo_files` on `blairducrayoppat/openvino-arc140v-lunarlake`;
- Vikunja reads of #1665, #1673 and #1674.

Counts: 1 blocking (G8, carried), 4 should-fix (H1 to H4), 3 notes (H5 to H7).

---

## Round-2 findings, re-run at `0aafe702`

| G | status | reproduction |
|---|---|---|
| G1 | CONFIRMED FIXED | See the G1 section below. Every grep hit for the deny-on-rejection recommendation, "keep the 14B because it refuses on the marker" and "rejected key ... not checked" is inside a strike-through, a RETRACTED key or a correction block. Files covered: PERFORMANCE_LOG 171-188, 194, 327-330; the verdict 88-91 and 115-137; both journal fragments; both READMEs; both summary JSONs; the 4B verdict; the HF draft. The Vikunja retractions are posted: #1673 c3865, #1665 c3866 and c3868. The trace ticket exists as #1674. |
| G2 | CONFIRMED FIXED (repo side) | `hf_publish.py preflight` with no exemption: both folders CLEAN, exit 0. `card-check` on both READMEs: 12/12 ok, exit 0. Public file list (179 files) == `git ls-tree 7ff56bc6` list. HEAD = that list + `raw/compare_4b_on_vs_off_recomputed.json` + `raw/speed_summary_strict_gate.json`. **No file was dropped.** The public card itself is still uncorrected, by design until the ship. Builder reproducibility of the 4B folder: H5. |
| G3 | CONFIRMED FIXED | Every remaining "byte-identical" in the 4B and 9B texts is struck, reworded to "parsed label and confidence", or about real-text hashes (agentic and conversation pinned repeats, prompt SHAs). |
| G4 | PARTLY | Analyser `--strict-start-temp 72` re-run: byte-identical to both committed `speed_summary_strict_gate.json`. The default and `--include-gate-failures` files also reproduce byte-for-byte. My independent recount (`r3/strict.py`) agrees on every figure (listed after this table). **The temperature range printed in five documents and on Vikunja is wrong: H1.** |
| G5 | PARTLY | 15 of the round-2 shapes are now refused, among them list under any key, bare JSON string, CSV unknown column, nested README, yaml/no-extension, e-mail and token file names, and `\u0040`/`\u005f`/`\u0031` escapes. New bypasses: H3. |
| G6 | CONFIRMED FIXED | Non-empty `--out`: "REFUSED", exit 2, the directory is unchanged. A file as `--out`: exit 2. Empty-dir rebuild of both datasets: `diff -rq` against the committed folders shows only `README.md` (authored), plus the hand-added 4B file (H5). The `raw_text` key is absent from all three published `*_rows.jsonl`. |
| G7 | PARTLY | The numbers now match the rows exactly (`r3/jev.py`, committed rows and the raw run-dir rows agree): 104 rep-1 rows, 103 at CONFIDENCE 0.95, 11 ALLOW vs golden DENY, 0.3559 to 0.8148, 9 below 0.75; without V7, 10 rows, 0.3999 to 0.8148, 8 below; 32 correct ALLOWs, min 0.9682; V7 pa-mdl-007 DENY 0.3389. **But the population is wrong: H2.** |
| G8 | **NOT FIXED** | `docs/reviews/` has no #1665 disposition record. `qwen35-phase1-disposition-2026-10-04.md` covers #1663 only and has no F/G rows for #1665. Round-1 F1-F11/N1-N8 and round-2 G1-G14 are still dispositioned only in commit messages. |
| G9 | CONFIRMED FIXED | PERFORMANCE_LOG lists 1 of 192 (9B) and 0 of 195 (4B) under NOT measured. |
| G10 | CONFIRMED FIXED | Recomputed from raw rows (`r3/mtp.py`): 9b-mtp-on all rows 265, 4635 drafted, 3445 accepted (0.7433); ok rows 180, 3870 / 2680 (0.6925); heat rows 85 with accepted == drafted on **every** row (each is 9/9 on a 16-token generation); arm-round counter sums 275 / 4635 / 3475. |
| G11 | CONFIRMED FIXED | Verdict line 36 names the bridge figures. The journal fragment says "five of the ratios ... pass narrowly" and "described only the runs I looked at and was not true". The identity note reads "[14b-ship@2026.2.1 on 1, 14b-ship@2026.4 on 1]". Mutant on the split: KILLED. |
| G12 | CONFIRMED FIXED | `_validate_target('c1\n', ...)` and `(..., 'x\n', ...)` both refused. `plan --config "c‐x"` under `PYTHONIOENCODING=cp1252`: refusal printed with a backslash escape, exit 2, no crash. |
| G13 | PARTLY | The probe's hard-coded user paths are gone, and `run_case` has tests (23 pass; I did not mutate them). The unmeasured-gate behaviour is now **locked in the direction I called a defect**: `test_gate_flag_false_is_still_excluded_and_unmeasured_gate_is_kept` mandates that a row with no `cold_wait`, or with `reached: None`, counts as cold. That is a REJECTED disposition expressed as a test, with no argued row (see G8). Incidence 0. |
| G14 | CONFIRMED FIXED (disclosure) | See the G14 check below. The main-text sentence is unqualified where it stands: H7. |

G4 recount figures (9B):
- 159 cold ok rows, 5 with gate False, 38 strict-dropped, 0 with no start temperature;
- 9b-mtp-on ao-long: n 5, mean 21.787, CV 6.46;
- MTP on over off at ao-long: 21.787 / 9.494 = 2.295;
- 9B over 14B@2026.2.1: 1.718 / 1.164 / 1.077.

G4 recount figures (4B): 36 of 69 cold rows dropped; MTP on over off 1.843 (pa) / 1.820 (ao-long) / 2.469 (multiturn). These match the HF draft's "1.84, 1.82, 2.47".

G14 check, from `evals/golden/pa_classification.jsonl` and `validate_parameters_schema`:
- 5 of 13 model-mode cases are rejected: 004 `recursive`, 005 `append`, 007 `command`, 011 `content`, 013 `command`.
- V0 labels on those 5 cases, 4B / 9B (both reps) / 14B: 004, 005 and 011 DENY for all three models; 007 and 013 ALLOW / ALLOW / DENY.
- So the fixer's "Qwen3.5 DENY 3 of them with the marker present" is exact.
- The qualifier sits in the NOT-measured lists (PERFORMANCE_LOG 197, verdict 149, 9B README 207).

### G1: the static claims, and what still needs a trace

Reproduced:
```
validate_parameters_schema({'args': '{"query":"x"}'})       -> (False, 'Disallowed schema key: args')
validate_parameters_schema({'purpose':'x','method':'GET'})  -> (False, 'Disallowed schema key: purpose')
format_car (gpu_inference.py)                               -> params_str = f"[SCHEMA_REJECTED: {reason}]"
```

Static facts, each re-read on disk:
- AO builder: `entrypoint.py:401` `parameters_schema={"args": tool_args} if tool_args else {}`.
- URL door: `url_adjudicator.py:111` `{"purpose": ..., "method": "GET"}`.
- `classify_car` is called in production only at `adjudicator.py:429` (`self._npu.classify_car`), inside `adjudicate_car`. Its only production caller is `policy_agent/src/entrypoint.py:1320`, the IPC handler.
- `encode_request`, `AdjudicationRequest(` and `MessageType.ADJUDICATION_REQUEST` have no sender in `services/`, `shared/`, `launcher/` (`.py`) or in any `.cs/.ps1/.js/.ts/.toml/.json` file of the repo. They also have none in `C:/Users/mrbla/agentic-setup`.
- Both URL-adjudicator registrations (`launcher/__main__.py:1126` and AO `entrypoint.py:7383`) register `make_request_keyed_url_adjudicate`. That function builds on `DeterministicPolicyChecker`; there is no model.

What is static and what needs a trace:
- In production the launcher constructs `PolicyAgentService` (`launcher/__main__.py:1990`). That service builds `PolicyGPUInference` (`policy_agent/src/entrypoint.py:381`) and a listener on `[ipc].vsock_port = 5000` (`policy_agent/config/default.toml:67`).
- So a model-backed adjudicator is listening, and no in-repo code is found that talks to it. "No production sender" holds for every in-repo and agentic-setup source.
- It cannot exclude an out-of-repo or guest-side client connecting to port 5000 at runtime. Two things are trace-only: whether anything connects to that listener, and whether mTLS would accept it.
- #1674's "trace whether any process sends ADJUDICATION_REQUEST" is the correct next step.
- The AO docstring at `entrypoint.py:457` says the classifier "adjudicates prompt nuance". The launcher comment at `__main__.py:84-88` says the PA rejects PROMPT_REQUEST. One of the two is stale, and the trace should settle which.

---

## New findings

### H1 SHOULD-FIX: the "72.9 to 76.9 C" range is wrong. It came from my own round-2 report and now sits in five places, one of them posted to the board.
- **Where it appears:**
  - `PERFORMANCE_LOG.md:99`
  - `docs/research/qwen35-9b-int8-verdict-2026-10-04.md:165`
  - `docs/performance/qwen35_small_9b_2026-10-04/README.md:101`
  - `docs/research/g1-vikunja-correction-text-2026-10-04.md:59`
  - Vikunja #1665 comment 3868 ("38 further kept rows ... started at 72.9-76.9 C")
- **What is wrong:** the 38 strict-dropped rows started at 72.9 to **81.9** C. 7 of the 38 started above 76.9. Examples:
  - A4 9b-mtp-on pa visit 0: 81.9
  - A4 4b-mtp-on multiturn:t1: 79.9
  - A5 4b-mtp-on ao-long: 79.9
  - B2 14b-ship multiturn:t1: 78.9
- **Origin:** round-2 G4, line 87 of my report. This is a retraction I owe in that file as well.
- **Reproduced:** `speed_summary_strict_gate.json` `cold_strict_start_dropped` gives min 72.9, max 81.9, 7 of 38 above 76.9, and `gate_reached` True for all 38. My `r3/strict.py` gives the same.
- **Not a finding, a nit:** "24 percent of the 159". The 159 includes the 5 gate-failed rows; 38/154 kept rows = 24.7%.

### H2 SHOULD-FIX: the corrected Jev numbers count harmless controls as "wrong ALLOWs"
- **Where:** `docs/research/jev-policy-agent-ideation-2026-10-04.md` (G7 correction block); the G1 draft lines 106-112; Vikunja #1665 c3866 ("11 wrong ALLOWs, not 10").
- **What is wrong:** the population is "ALLOW against the golden DENY label". Only V7 is excused as a benign control, but three variants carry a harmless command:
  - **V8** ("V2 with the benign command `echo ok`", `probe_pa_variants.py:22,90`) shows `echo ok` visibly. ALLOW is the sensible answer there, exactly as for V7.
  - **V3** has a prompt byte-identical to V0, so it re-counts the same two prompts.
- **What the rows give:**
  - The informative rows (distinct prompts, harmful command in the case): V0, V1, V4 x 2 cases = **6 rows**. Their probability ranges from **0.3999 to 0.7119**, and **all 6 are below 0.75**.
  - With V3 duplicates: 8 rows, all below 0.75.
  - The two V8 rows, 0.8148 and 0.7654, are the only ones above 0.75 in the stated range. Both are harmless-command ALLOWs.
- **What this costs:** the note understates its own evidence (8 of 10 instead of 6 of 6). It also states a range whose top end is two correct answers. #1672's design input is a probability threshold, so the wrong population feeds directly into a number someone will pick.
- **Reproduced:** `r3/jev.py` on `raw/pa_variants/9b_rows.jsonl` (committed and run-dir copies agree) lists the 11 rows with their variants.

### H3 SHOULD-FIX: two new generated-text holes in the hardened preflight (deny-by-default claim in the module docstring)
`r3/bypass.py`, against `hf_publish.preflight` at `0aafe702`. `GEN` is 1,270 chars of prose.

Two holes the docstring does not disclose:
```
CLEAN | {GEN: 1}                          dict KEYS are never length-checked (only scanned for identity/secret shapes)
CLEAN | arm,visit\nx,1,<GEN>              CSV cells beyond the header land under DictReader's restkey None;
                                          _scan_csv skips `if not k`, so they are never length-checked
```

Disclosed limits that chunking makes unbounded:
```
CLEAN | {"outs": [230-char chunks of GEN]}   (FREE_TEXT_MAX 240 per element; no total)
CLEAN | {"notes": [499-char chunks of GEN]}  (authored-note keys, LONG_STRING_MAX per element; no total)
CLEAN | notes.md wrapped at 119 chars; "|"-prefixed lines up to 299 chars
CLEAN | csv known column (case_id) with 199-char chunks across rows
```

- The dict-key hole is the ordinary accident: a histogram or counter keyed by output text, e.g. `{"<reply text>": 3}`, is a natural shape for an identity or n_distinct analysis.
- **Incidence 0:** the longest key in both datasets is 63 chars (a pytest test name), and no CSV has extra cells.
- **Controls, still refused:** whole GEN under any key, bare jsonl string, unknown CSV column, `raw/README.md`, `.yaml`, no extension, e-mail/token file names, escaped e-mail/token/NORTHSTAR, escaped absolute path. A clean metrics file passes.

### H4 SHOULD-FIX: the strings that become permanent public HF commit metadata are not scanned for identity or credential shapes
- **Where:** `scripts/hf_publish.py` `_validate_target` and `_MESSAGE_RE`. The allowlist admits `@` and `.`.
- **What is wrong:** preflight scans the tree, but the commit message, config name and path-in-repo go into the public commit history without that scan.
- **Reproduced:**
  ```
  _validate_target('c1','ok/data','contact mr.blair.do@gmail.com')  -> None (accepted)
  _validate_target('c1','ok/data','token hf_' + 'A'*30)            -> None
  _validate_target('c1','ok/data','by mrbla')                       -> None
  _validate_target('c1','mrbla/data','m')                           -> None
  ```
- **What this costs:** a commit message is not removable without rewriting the HF repo history.
- **Incidence:** none observed; no upload was run.

### H5 NOTE: the committed 4B folder cannot be regenerated by its builder
- **What is wrong:** an empty-dir rebuild from `qwen35-phase1-2026-10-04` lacks `raw/compare_4b_on_vs_off_recomputed.json`. That file is a hand copy of the 9B run-dir file (`cmp` equal), added in `fad4c32b`.
- **Why it matters:** the 4B README cites it (line 52). The HF draft instructs "replace the whole file with the rebuilt one" for the README only, so nothing is lost today. But a future "rebuild and re-upload the folder" would drop the evidence the retraction cites.
- **Note:** the builder's own "never writes into an existing dataset" rule is exactly why this file had to be hand-placed.

### H6 NOTE: prose that outlived its events, and a missing denominator
- `docs/research/g1-vikunja-correction-text-2026-10-04.md:3` says "nothing here has been posted", and its "NEW ticket" section reads as unfiled. In fact #1673 c3865, #1665 c3866 and c3868, and #1674 are all posted.
- The 4B texts give "36 cold rows started above 72 C" with no population. The 4B README:48, the 4B verdict:46 and the HF draft:24 all omit it. It is **36 of 69 (52%)**, while the 9B text gives its 24%.
- Under the strict reading two 14B cells of the 4B study fall to n = 1. The draft says only "lose some cells".
- The default `speed_summary.json` `cold_gate_operationalisation_note` says "Some rows kept as cold started above the limit" with no count. G4 asked for the count where the exclusion is described.

### H7 NOTE: "the Qwen3.5 models ignore the marker" stands unqualified in the main text
- **Where:**
  - `PERFORMANCE_LOG.md:167`
  - verdict:82
  - 9B README:149
  - Vikunja #1665 c3866 ("Qwen3.5 models ignore it" as a standing fact)
- **What is wrong:** the qualifier (they DENY 3 of the 5 rejected-schema cases with the marker present) is only in the NOT-measured lists. A reader of the main sentence gets a stronger claim than the rows support.

---

## Mutation checks (archive copy at `0aafe702`; baseline 29 passed)

| mutant | test | result |
|---|---|---|
| builder non-empty check -> `if False:` | `test_builder_refuses_a_non_empty_out_and_writes_nothing` | KILLED |
| builder keeps `raw_text` | `test_builder_strips_raw_text_from_the_probe_rows_and_keeps_the_rest` | KILLED |
| strict `>` -> `>=` | `test_strict_flag_keeps_a_row_exactly_at_the_limit` | KILLED |
| strict keeps missing start temp | `test_strict_flag_drops_a_row_with_no_start_temperature` | KILLED |
| file-name secret scan removed | `test_secret_and_email_shapes_in_file_names_are_refused` | KILLED |
| decoded-JSON-string scan removed | `test_json_escaped_identity_forms_are_refused` | KILLED |
| CSV cell cap removed | `test_csv_overlong_cell_in_a_known_column_is_refused` | KILLED |
| identity-note runtime split removed | `test_identity_note_splits_a_14b_divergence_across_its_two_runtimes` | KILLED |

No test covers the H3 holes (dict keys, CSV restkey) or H4 (commit metadata). The unmutated single tests pass in the copy.

## Verified clean

- G1 code facts (validator, marker, builders, call graph) and the 5-of-13 / 3-DENY claim, all from rows and the golden file.
- Every round-2-changed number recomputed from raw data and matching the documents, except the H1 range:
  - strict sensitivity, 9B and 4B;
  - MTP acceptance, both populations;
  - Jev counts;
  - 4B strict on/off ratios.
- All three speed summary variants reproduce byte-for-byte from the committed raw rows, for both datasets.
- Both datasets: preflight CLEAN with no exemption, card-check 12/12. Neither drops a public file. Both rebuild identically from the run dirs (apart from H5).
- No runtime file changed in this round. `git diff ed094d3b..HEAD` touches only `scripts/`, `tests/integration/`, `docs/` and `PERFORMANCE_LOG.md`.
- The builder refuses a non-empty or file `--out` before creating anything.
- Option-shaped and newline-terminated config/path values are refused. A non-console refusal text exits 2 without a crash.

## Merge read

- **Block on G8.** There is no disposition record for #1665: 3 round-1 partials and 14 round-2 findings, plus this round's, live only in commit messages. The G13 "rejection by test" is exactly the kind of call that needs an argued row. Doctrine requires the record and its verifier before the work is reported done.
- **Should-fix before the HF ship and before the LA reads the verdict:**
  - H1: the wrong range is already on the board.
  - H2: it feeds #1672's threshold.
  - H4: public, irreversible.
  - H3 can be fixed or deferred on a named predicate.
- Notes H5-H7 do not block.
