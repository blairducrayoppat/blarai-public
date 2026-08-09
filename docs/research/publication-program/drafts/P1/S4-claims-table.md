---
title: "P1-S4 claims table (AUTHOR_KIT §A)"
status: companion-to-S4-draft-v2
area: research
piece: P1-S4
prepared: 2026-07-19
---

# S4 claims table — every factual claim, typed

Types per AUTHOR_KIT §A: **MEASURED** (number from a recorded run, cited with
conditions) · **DOCUMENTED-EVENT** (happened, evidenced on disk / on GitHub) ·
**INTERPRETATION** (our reading, marked and hedged in the draft). Sources are
given as the primary artifact; "log" = PERFORMANCE_LOG.md dated entry; "JSON" =
docs/performance/xgrammar_stop_token_fix_verify_2026-07-05_15-34-27.json;
"journal" = BUILD_JOURNAL.md dated entry (both arc entries also appear verbatim
in docs/BUILD_JOURNAL_ANTHOLOGY.md); "API" = GitHub REST API read on
2026-07-19. Local Vikunja ticket #725 is an internal corroborating source only
(not cited in print).

| # | Claim in draft | Type | Source (exact) |
|---|---|---|---|
| 1 | A live generation crashed on 2026-07-02 with the `grammar_matcher.cc:627` / `IsStopTokenAccepted` assertion | DOCUMENTED-EVENT | Ticket #725 description (live crash 2026-07-02 15:22:38, verbatim launcher.log excerpt); journal 2026-07-04 "The crash that only happens when two right things run together" (go-live crash referenced); assertion text quoted from live issue #4081 body (API, 2026-07-19) |
| 2 | Fail-closed handling discarded the turn; the assistant answered again without the tool; nothing corrupted | DOCUMENTED-EVENT | Ticket #725 description consequence chain ("turn discarded, no output corruption, no egress … app retry answered without the tool") |
| 3 | Grammar constraint switched off in production the same evening (2026-07-02), pending diagnosis | DOCUMENTED-EVENT | Ticket #725 ("[generation].tool_call_grammar flipped OFF … flip merged ad05047"); journal 2026-07-04 correction paragraph ("production had turned the grammar OFF on 2026-07-02 (the #725 flip, ad05047)") |
| 4 | Stack context: Qwen3-14B INT4 target + pruned Qwen3-0.6B draft, spec-decode, on Arc 140V; triggered structural-tags grammar for tool calls | DOCUMENTED-EVENT | JSON `models` + `environment`; log 2026-07-05 entry methodology; live issue #4081 Environment block (API) |
| 5 | Features were composition-probed offline + one clean live tool turn before the crash | DOCUMENTED-EVENT | Journal 2026-07-01 "Retiring the homemade dialect…" (6-leg compose probe); log 2026-07-02 "First grammar-constrained tool call…" (live round-trip 4795.8 ms); ticket #725 "NOT deterministic-always" paragraph |
| 6 | Isolation table row: spec-decode ON, non-streamed — crashes every run, e.g. 1/76, 1/57, 2/38 (~1–5%) | MEASURED | Live issue #4081 Evidence table (API 2026-07-19; figures originate from the 2026-07-04 characterization runs; journal 2026-07-04 gives ~1–2% for the generic-set runs — the draft carries the issue's ~1–5% envelope, which spans all listed runs incl. 2/38) |
| 7 | Isolation table row: spec-decode ON, streamed — 0/57, explicitly undersampled | MEASURED (with stated limit) | Live issue #4081 Evidence table + its caveat line (quoted verbatim in draft) |
| 8 | Isolation table row: spec-decode OFF — 0/57 | MEASURED | Live issue #4081 Evidence table; journal 2026-07-04 ("went 0-for-57") |
| 9 | Isolation table row: grammar not attached — 0/19 | MEASURED | Live issue #4081 Evidence table |
| 10 | 57 token-by-token streamed generations: none emitted the `<tool_call>` trigger, yet non-streamed equivalents crashed → un-fired grammar sufficient | MEASURED + DOCUMENTED-EVENT | Journal 2026-07-04 (finding 1); live issue #4081 "Two observations" item 2 |
| 11 | Companion cc:493 warning names ordinary word-piece token ids (e.g. 498) | DOCUMENTED-EVENT | Journal 2026-07-04 (finding 2); live issue #4081 warning block (token id 498) |
| 12 | Reframe to "structured output under speculative decoding in general, not tool-calling-specific" | INTERPRETATION (marked in draft: "reframe … suggested") | Journal 2026-07-04; issue #4081 states the same reading ("appears to be structured output under speculative decoding in general") |
| 13 | Original production crash WAS streamed; no "streaming is safe" claim | DOCUMENTED-EVENT (quote) | Live issue #4081, quoted verbatim in draft (em-dash form from live body; local ISSUE_BODY_FINAL.md matches modulo dash encoding) |
| 14 | First reproducer draft embedded the 841-token production system prompt; rebuilt around the COMMITTED generic reproducer — 19 prompts (repro_prompts_generic.json) + two-tool enum schema (get_current_time, search_notes) — and re-proven to crash. The ISSUE's inline script is a SEPARATE artifact: 15 questions, single generic schema, no tool enum; the draft keeps the two distinct | DOCUMENTED-EVENT | Journal 2026-07-04 ("nearly filed with the 841-token production system prompt… rebuilt a generic prompt set with a stock two-tool schema and proved *that* crashes too"); committed repro_prompts_generic.json (19 prompts; every isolation figure a multiple of 19); issue #4081 inline reproducer (15 QUESTIONS, counted) |
| 15 | Characterization/verification arms used 19 generic prompts, 5 passes = 95/arm | MEASURED (methodology) | JSON `methodology.prompt_set` ("19 generic conversational prompts") + `results[].passes/generations`; log 2026-07-05 entry |
| 16 | sglang precedent: sgl-project/sglang#14464, same failure signature, merged 2025-12-06 | DOCUMENTED-EVENT | GitHub API read 2026-07-19: state closed, merged true, merged_at 2025-12-06T14:15:22Z; title carries the identical assertion string |
| 17 | Root cause: `FillNextTokenBitmask()` called before `IsTerminated()` in `XGrammarLogitsTransformer::apply()` (openvino.genai `xgrammar_backend.cpp`); draft proposes past-stop tokens → apply() on terminated matcher | DOCUMENTED-EVENT (+ mechanism reasoning as stated upstream) | Live issue #4081 "Root cause confirmed + fix" section (code block quoted verbatim); log 2026-07-05 entry "What changed" |
| 18 | Fix = swap the two lines + equivalent guard in `accept_tokens()`; silences companion warning | DOCUMENTED-EVENT | Live issue #4081 root-cause section; journal 2026-07-05 "The fix that couldn't be proven…" |
| 19 | Net diff +4/−1 lines, one file (`src/cpp/src/sampling/structured_output/xgrammar_backend.cpp`) | DOCUMENTED-EVENT | API 2026-07-19: `pulls/4082` additions=4 deletions=1 changed_files=1; `pulls/4082/files` filename confirmed |
| 20 | "Bug is in the integration layer, not xgrammar itself" | INTERPRETATION (grounded) | The fixed file lives in openvino.genai's source tree (API files list); the assertion fires inside vendored xgrammar but the mis-ordered call is OV-side — issue #4081 says "a similar guard on the OV side of the matcher call" |
| 21 | ABI wall 1: DLL-only swap into the venv fails ("DLL load failed: The specified procedure could not be found") | DOCUMENTED-EVENT | Journal 2026-07-05; JSON `environment.note_on_devices`; issue #4081 verification paragraph |
| 22 | ABI wall 2: local from-source checkout never linked its GPU plugin | DOCUMENTED-EVENT | Journal 2026-07-05; JSON note_on_devices ("GPU plugin not linked in this local checkout"); corroborated by log 2026-07-06 GPU-plugin entry ("the GPU plugin had never been linked") |
| 23 | Device-independence argument (sampler state-machine ordering error; no GPU numerics) → CPU valid substitute for proving the fix | INTERPRETATION (disclosed as the substitution's reasoning, as it was upstream) | JSON note_on_devices (verbatim reasoning); issue #4081 verification paragraph; journal 2026-07-05 |
| 24 | Rebuild at `7dea045` = exact commit of installed wheel 2026.2.1.0-3123-7dea0459b2a → same-commit before/after | DOCUMENTED-EVENT | JSON `environment.openvino_genai_baseline` + `openvino_genai_source_commit`; log 2026-07-05 methodology |
| 25 | Baseline: 1 crash / 95 generations, GPU, unpatched official wheel; same case + assertion as original report (case generic-11) | MEASURED | JSON results[0] (passes 5, generations 95, crashes 1, crash_case generic-11, signature matches); log 2026-07-05 results table |
| 26 | Patched: 0 crashes / 95 generations, CPU, matched sample size | MEASURED | JSON results[1]; log 2026-07-05 results table |
| 27 | Control: patched, spec-decode OFF, 0/19 | MEASURED | JSON results[2] |
| 28 | ~53 s/generation CPU (time-budgeting note, not a throughput claim); planned 323-generation run truncated to 95 to match baseline | MEASURED (elapsed) + DOCUMENTED-EVENT (judgment) | JSON results[1].elapsed_s = 5075.9 → 5075.9/95 = 53.4 s/gen; log 2026-07-05 notes (same derivation + "not a throughput claim" framing); journal 2026-07-05 (17 passes/323 planned; ~17 min first pass; truncation decision) |
| 29 | Issue #4081 filed 2026-07-05 (23:01:19Z); PR #4082 filed five minutes later (23:06:08Z) | DOCUMENTED-EVENT | API 2026-07-19: issues/4081 created_at; pulls/4082 created_at |
| 30 | The PR is DCO-signed (commit-level Signed-off-by on 4c797722); BOTH issue and PR carry an explicit AI-assistance disclosure. (DCO sign-off is commit-level — the issue has a disclosure, not a sign-off; the draft states exactly this) | DOCUMENTED-EVENT | API 2026-07-19: pulls/4082/commits (Signed-off-by on 4c797722); live issue #4081 disclosure paragraph; VERIFIED_FACTS row (PR DCO-signed, AI-assistance disclosed, verified 2026-07-19) |
| 31 | "Is this a supported combination?" courtesy framing in the issue | DOCUMENTED-EVENT (paraphrase, marked) | Live issue #4081 section of the same name (draft paraphrases; direct quotes avoided except the streaming line) |
| 32 | Automated reviewer nit (brittle vendored file/line reference in a code comment) fixed in a follow-up commit | DOCUMENTED-EVENT | API 2026-07-19: pulls/4082/comments (Copilot, 2026-07-05T23:08:57Z, body excerpt); pulls/4082/commits (5200f1eb "Potential fix for pull request finding") |
| 33 | First approval apaniukov 2026-07-06 (07:54:06Z); second approval pavel-esir 2026-07-08 (11:09:06Z) | DOCUMENTED-EVENT | API 2026-07-19: pulls/4082/reviews (states APPROVED with timestamps) |
| 34 | CI triage 1: GGUF-reader wheel test cancelled at 1-hour timeout while downloading a model; unrelated path; triaged in a PR comment 2026-07-06 | DOCUMENTED-EVENT | API 2026-07-19: issues/4082/comments (blairducrayoppat 2026-07-06T17:41:52Z, body excerpt) |
| 35 | CI triage 2: merge queue ejected PR 2026-07-07 09:21 UTC on required-status error; 2 of 8 Jenkins builds (Windows VS 2022 release+debug) failed; triaged in a PR comment | DOCUMENTED-EVENT | API 2026-07-19: issues/4082/comments (blairducrayoppat 2026-07-07T17:02:13Z, body excerpt naming 6/8 passed + the two failures + merge-group commit 6aec8ba) |
| 36 | Merged to master 2026-07-08T13:07:36Z; issue auto-closed as completed at 13:07:38Z | DOCUMENTED-EVENT | API 2026-07-19: pulls/4082 (merged=true, merged_at, base=master, merge_commit_sha eed42c806b70…); issues/4081 (closed_at, state_reason=completed) |
| 37 | ~62 hours filing→merge; six calendar days first-crash→merge | DOCUMENTED-EVENT (derived arithmetic) | 2026-07-05T23:06:08Z → 2026-07-08T13:07:36Z = 62h01m ("about 62 hours"); 2026-07-02 → 2026-07-08 = 6 calendar days |
| 38 | NOT in any published release as of 2026-07-19; latest release 2026.2.1.0 published 2026-06-17 | DOCUMENTED-EVENT (volatile — re-verify at publish) | API 2026-07-19: releases list (2026.2.1.0, published_at 2026-06-17T15:15:48Z, newest); tags list (no tag newer than 2026.2.1.0); compare 2026.2.1.0...eed42c80 = diverged (not contained); compare master...eed42c80 = behind/ahead_by 0 (contained in master) |
| 39 | Production posture unchanged: grammar off; re-enable criterion = fix in pinned release + 20/20 boundary soak + one live tool turn | DOCUMENTED-EVENT | Ticket #725 work-item 3 (revisit criterion); journal 2026-07-05 **Next:** block (same criterion) |
| 40 | From-source GPU plugin build completed 2026-07-06, opening a local GPU re-verify path | DOCUMENTED-EVENT | Log 2026-07-06 "The GPU plugin, built from source at last" (+ its **Next:** naming the #4082 GPU re-verify unlock) |
| 41 | Prior-work positioning: fix write-ups common; debugging narratives WITH false leads visible are celebrated genre staples (500-mile email, marcan's Go-runtime hunt) — narrative honesty is NOT claimed as the gap; the claimed gap is the committed machine-readable artifact trail (verification JSON + sanitized reproducer + matched-condition dataset, public repo, cross-linked to issue/PR), scoped "in a written scan of the genre we could not find it done end-to-end" | INTERPRETATION (positioning; scoped to the written scan) | S4-novelty-pass.md (GO/NO-GO, 2026-07-19: 8 named genre instances, access-dated); P1-verdict §1 prior-art map (B, C, D) + §2 gap item 4; the chain items are claims 1–38 above |
| 42 | "In this project we treat that chain as the product" | INTERPRETATION (explicitly ours) | Program doctrine (README §0.5 verifiability strategy); n=1 framing per AUTHOR_KIT §E |
| 43 | Hardware/software/model/workload spec block in Methods | DOCUMENTED-EVENT / MEASURED (as recorded) | JSON `environment` + `models` + `methodology` verbatim fields; log 2026-07-05 entry |
| 44 | "What was not measured" items (no patched-GPU run; no perf deltas; rate beyond n=95; streaming undersampled) | DOCUMENTED-EVENT (limits recorded at run time) | JSON `not_measured` array (THREE items: patched-GPU perf, throughput/latency deltas, rate beyond n=95 — re-read 2026-07-19) + issue #4081 streaming caveat (the fourth limit; not in the JSON — the draft's methods lead-in sources it to the issue) |
| 45 | Series/context claims: personal research project; long-term local AI system; n=1 single-project case corpus | Framing per standing doctrine | AUTHOR_KIT §D/§E; VERIFIED_FACTS standing framing facts |
| 46 | "A day of controlled elimination bought a one-minute source read" | DOCUMENTED-EVENT (derived duration) | All documented elimination runs are dated 2026-07-04 (journal 2026-07-04 "The crash that only happens…" — the single characterization entry); journal 2026-07-05 ("Reading the vendored source confirmed it in under a minute") |
| 47 | An unfixed build would come up clean across 95 generations "roughly 15–38% of the time" at the ~1–2% measured rate | INTERPRETATION (derived arithmetic) | (1−p)^95 for p ∈ [0.01, 0.02] → 0.385 / 0.147; rate source: journal 2026-07-04 (~1–2% on the 19-prompt generic set — the same configuration as the 95-generation arms) |

## Notes for the fact auditor

- Claim 6 carries BOTH published envelopes deliberately: the journal's ~1–2%
  (19-prompt generic-set runs) and the issue's ~1–5% (all runs incl. 2/38). The
  draft quotes the issue's envelope with the issue's own example fractions, so
  print matches the public artifact exactly.
- Claim 14: the *filed* inline reproducer uses a 15-question set; the
  *committed* repro_prompts_generic.json used for the measured arms has 19
  prompts. Do not merge them. (v1's prose violated this note — panel RED R2;
  v2 states both artifacts explicitly and separately in "A reproducer strangers
  can run.")
- Claim 38 is the volatile row: re-verify tags/releases on the day of the LA
  ceremony AND on the day of any actual posting; the draft's sentence is
  access-dated for this reason.
- The draft nowhere claims the fix "shipped," nowhere names a future release
  version, and nowhere claims GPU verification of the patched build.
- Fork-branch commit SHA `4c797722` (VERIFIED_FACTS row) is deliberately NOT
  printed in the draft — the PR URL + merge state carry the citation; one less
  volatile SHA to maintain. (API pulls/4082/commits confirmed it 2026-07-19
  regardless.)
