---
title: Disposition — adversarial review of the OpenVINO 2026.4 + brain-consolidation plan
date: 2026-09-21
area: substrate
---

# Disposition record — adversarial review of the 2026.4 program plan (2026-09-21)

**Reviewed artifact:** the session plan `twinkly-watching-puffin.md` (the program behind
`docs/research/openvino-2026.4-relevance-assessment-2026-09-21.md`).
**Reviewer:** an independent read-only session (`plan-adversarial-sequencer`), 25 findings,
HIGH/MED/LOW. **Author of this record:** the planning session (author ≠ reviewer). Every FIXED row
below names the docs branch that carries the corrected plan/report; every load-bearing citation
the reviewer made was re-verified on disk before it was accepted, and one HIGH finding (2) was
found to rest on a number a later log entry had already corrected — recorded as such, not quietly.

```disposition
# finding | status | evidence-or-predicate
1 HIGH — the driver anchor moved (8826 → 8991 → 8831) and nobody recorded it; every comparison crosses it | FIXED | docs/openvino-2026.4-program — plan §3.10 + report §2: the sequence is now recorded with the two JSON citations (`coder_offload_ab_2026-09-01.json:21`, `audit_chain_verify_cost_2026-09-17_22-50-00.json:9`) and the event log (six driver configurations 08-26..09-14); controls on today's driver are S0a, the first GPU step; #1449 gets a CURRENT STATE comment stating its premise is false
2 HIGH — "fits resident" is a July claim; the 35B's weights sit on the 17.98 GiB budget cliff and MTP adds a pool | FIXED | docs/openvino-2026.4-program — accepted and then corrected by a later record the reviewer had not reached: PERFORMANCE_LOG 2026-09-01 shows the 17.85 GiB budget was a registry percentage (57) written on 08-26 and restored to 87 on 09-01; the LIVE read on 09-21 16:48 shows the real key is back at 57 (written 09-14 23:08:17 by the driver install). Plan §0/§3.9 and report §2 carry the mechanism, the timeline and decision 0; S0a records both keys; S2b checks weights+pool against the REAL budget before any run; offload is mandatory only under 57; #37736 is a stop condition when offload is load-bearing
3 HIGH — S2/S3/S4 had no 2026.4 runtime before Ceremony 1 | FIXED | docs/openvino-2026.4-program — assumption 4 + S-1: a dev-side `.venv-2026.4` (never wired into the launcher) carries all measurement; the production venv waits for Ceremony 1; `.export-venv-2026.4` built 2026-09-21 (OV 2026.4.0, NNCF 3.4.0, optimum-intel 2.2.0, transformers 5.2.0)
4 HIGH — S0 omitted the production prefill recipe and its eval leg could not exercise arms A/B (the #931 harness builds ChatML by hand; think ids cannot be stop targets when in the input) | FIXED | docs/openvino-2026.4-program — S0c is now D (prefill via `wrap_chatml` WITH `apply_chat_template=False`, the blueprint's double-wrap finding) / A / B on both runtimes, C only if all fail; the rendered prompt is dumped first; the gate asserts first generated token ≠ 248068 in ≥39/40
5 HIGH — the protocol could not decide the S2 gate (≈40% between-pass variance, sequential arms, no session-age stamp) | FIXED | docs/openvino-2026.4-program — plan §3.11 + S2e/S3/§9: reboot first, interleaved arms, uptime + run-index stamp ported into the VLM bench (S-1), minimum detectable effect stated before running, a winner only when the margin exceeds that day's spread; applied to S0, S1, S2, S3, S4b
6 HIGH — an overnight full export collides with the battery and pages the volume it reads; no surface refuses a gate or battery launch while a 19 GB model is resident | FIXED | docs/openvino-2026.4-program — S2c(ii) runs only in a daytime slot or a night the LA explicitly parks the battery; every window is announced on the epic (#1610) with start/end; the missing machine-checkable guard is named as a gap in §7 (the bench's Available-RAM refusal is the only control today) rather than claimed
7 MED — "2026.4 switches Qwen3.5/3.6 to the PA backend" over-reads an llm_bench bullet | FIXED | docs/openvino-2026.4-program — §1 now says llm_bench's default moved and VLMPipeline tries PA first with SDPA fallback (read at the tag); S0b measures which backend is taken here and what the pool costs
8 MED — genai #4483 is a discrete Battlemage card; the prefix-caching constraint attaches to the MTP verifier, not to prefix caching | FIXED | docs/openvino-2026.4-program — §2 row 1 labels the card and cites the watch addendum's expected-gain caveat; §3.5 separates the two constraints and S2e is a 2×2 (spec on/off × prefix on/off)
9 MED — S1's acceptance omitted the eval-suite cross-check doctrine requires on a substrate change | FIXED | docs/openvino-2026.4-program — S1 live acceptance now runs `evals.run --suite all` on the 14B with any transition judged before it is written
10 MED — S1's ship motion incomplete; the named fail-loud fix never scheduled | FIXED | docs/openvino-2026.4-program — S1 fixes all three `except TypeError` retries plus the broad-except and streaming fallbacks with regression locks, pauses the fleet for the merge, closes #1455 citing the SHA, comments #725/#1456, and ships a journal fragment in the same motion
11 MED — runtime imports and the tokenizer path under-specified | FIXED | docs/openvino-2026.4-program — S1 names the three `AutoTokenizer` sites that stay and the AST sweep that drops the fork and torch; the blueprint's CPU probe confirmed the 35B tokenizer loads under transformers 5.0.0; S5.3 makes the tokenizer load an acceptance check
12 MED — S4's PA gate had no number and the #931 follow-on had no ticket named | FIXED | docs/openvino-2026.4-program — §5b: PA ≥0.90 on the 256-case corpus, 35/35 pa_classification, 0/4 injected commands obeyed, ≤2 echoes, answer quality ≥35/37; the follow-on is #933 (open), cited in S4a and re-scoped to production loaders
13 MED — the 2026-08-29 precedent report is untracked 23 days later | FIXED | docs/openvino-2026.4-program — committed in this branch beside the 09-21 report (its only prior appearance is a WIP snapshot commit `a012f93b`, never on main)
14 MED — offload semantics unstated; the open hang under-weighted; #1461 overdue | FIXED | docs/openvino-2026.4-program — §3.4/S3c: ratio direction read at the 2026.4 tag before any sweep, #37736 reproduced on 2026.4 as a stop condition whenever offload is load-bearing; #1461 gets a CURRENT STATE comment resetting its due date
15 MED — the incumbent enters Ceremony 3 without its best path measured | FIXED | docs/openvino-2026.4-program — S3½ re-tests the June EAGLE-3 conversion mismatch under optimum-intel 2.2 (a failure the ticket never cited) and runs #1456's chain arm if it converts; otherwise the asymmetry is printed on the page
16 MED — Gemma's cheap half should precede the 35B head export; a Gemma brain supersedes the Qwen3-locked rows | FIXED | docs/openvino-2026.4-program — S0d (Gemma cheap arm right after S0) and S5's Gemma skeleton naming the ADR-011/012 supersession and the fleet-profile edits
17 MED — compiled-blob cache posture and reboot discipline unstated | FIXED | docs/openvino-2026.4-program — every stamp states `CACHE_DIR` (cold by default) and the boot it ran on; the cache is cleared on every substrate or driver change (§9, S3a)
18 MED — deferral discipline: no disposition record; Kokoro as a ticket | FIXED | docs/openvino-2026.4-program — this record; Kokoro-via-GenAI stays a sentence in the report, not a ticket
19 LOW — "dormant" needs an operational definition; Ceremonies 1 and 2 can be one sitting | FIXED | docs/openvino-2026.4-program — assumption 5 and S1's ceremony line
20 LOW — ADR-012's LOCKED "INT8 KV ruled out" row not cited beside ADR-040 | FIXED | docs/openvino-2026.4-program — §3.3 carries both, plus the finding that ADR-040's named gate (#715) is the telemetry pass, not an answer-quality A/B
21 LOW — DEC-06 register row still says prefix caching OFF | FIXED | docs/openvino-2026.4-program — §3.5 cites the launcher line and S5.10 corrects the row
22 LOW — row 7 "Qwen3 template patch" is not in the 2026.4.0.0 release body | REJECTED | The release body read through the GitHub API on 2026-09-21 lists "Patch Qwen3 chat template with unsupported syntax by @yatarkan" among the 2026.4.0.0 changes, so the row's phrase names a real changelog entry; the plan now quotes that title verbatim so the citation can be checked rather than argued
23 LOW — CLAUDE.md says Python 3.12 services; both venvs are 3.11.9 | FIXED | docs/openvino-2026.4-program — the stack section's Python line corrected to 3.11 in this branch (a factual defect in an always-loaded file, not a doctrine change)
24 LOW — Ceremony 3 must arrive as a recommendation with alternatives | FIXED | docs/openvino-2026.4-program — S4c/§6 say "led by a recommendation, alternatives named"
25 LOW — journal obligation named only for S0 | FIXED | docs/openvino-2026.4-program — S1's atomic motion includes a fragment; this branch carries the fragment for the day's judgments
```

## Verification

`python scripts/verify_disposition.py docs/reviews/openvino-2026.4-plan-review-disposition-2026-09-21.md`
run on this branch before it was presented (see the commit that lands this file).

## What the review changed, in one paragraph

Two HIGH findings reshaped the program: controls on today's machine come before any new number,
and measurement runs on a side copy of the new runtime so no ceremony stands in front of it. The
memory-budget finding was correct about the mechanism and out of date about the number; chasing its
citation to the 1 September entry and then to the live registry produced the program's first
decision (the key reads 57 today). The reviewer's rewritten gates were adopted almost verbatim.
