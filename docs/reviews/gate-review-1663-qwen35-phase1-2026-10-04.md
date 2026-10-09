# Gate review — #1663 Phase 1 delta-gate (Qwen3.5-4B INT8 + MTP vs Qwen3-14B)

Reviewed 2026-10-04 04:07–04:40 −04:00 by an independent session (not the gate's author). Every claim
below was checked on disk, on the board, or against a live API read in that window.

## 1. Verdict

**Sound in goal, scope, git, authority and stop-intent. Do not confirm it as written: the measurement
plan has gaps that would let it reach "proper candidate" without measuring what decides that.** The
largest: the Policy Agent half of the brain would silently go unmeasured, and the test that
disqualified the last candidate is missing. All gaps below are defects with one correct fix, which is
the session's job. There is one decision for the LA: rebooting before measurement (§4).

## 2. What I verified

| Claim in the gate | Check | Result |
|---|---|---|
| Branch `docs/1610-qwen35-phase1` @ f7644ec9, unreviewed | `git log`, `git diff --stat main...` | Holds. One commit on main `b73a2dd6`, docs only (PERFORMANCE_LOG +12, research note +102), worktree clean |
| main HEAD | `git log main` | `b73a2dd6`, matches the card |
| Primary checkout = another session's branch + 2 untracked review files | `git status`, `git worktree list` | Holds. Only two Claude processes are running (this review and, presumably, the author), so no third session is live right now. The protection still stands |
| Verifier PASS 6/0/0, stamp 114 min old | re-ran `scripts/verify_handoff_brief.py` | Reproduced exactly |
| Plan, stop conditions, risks, budget = #1663 | #1663 DESCRIPTION | Matches. #1664 is separate and blocked-by #1663 |
| Model + MTP head exist | HF API `OpenVINO/Qwen3.5-4B-int8-ov` | Holds. Revision `e4d8de7a25bc3007261c28785bc190c97cabd243`, modified 2026-09-25, `openvino_mtp_model.xml` present. **Layout is VLM** (`openvino_language_model.xml` + vision files), which matters for §3 D1 |
| `.venv-2026.4` = 2026.4.0; production `.venv` = 2026.2.1 | imported both | Holds (2026.4.0-22959 / genai 2026.4.0.0; 2026.2.1-21919 / genai 2026.2.1.0) |
| Thinking-off recipe works for this template | HF `chat_template.jinja` | Holds. `enable_thinking=false` emits `<think>\n\n</think>\n\n`; undefined emits a bare `<think>\n` (lesson 369 shape) |
| openvino#38153 | GitHub API | Exists, open, Arc 140T + Qwen3.5-9B int4. **The penalty grows with context** (3-token verify 113 vs 78 ms at 8K, 166 vs 85 ms at 32K) |
| B:\models target | `Get-PSDrive`, listing | Exists, no Qwen3.5 there yet. 392 GB free (the card's 365 GB has drifted; harmless) |
| Graphics budget | registry | `SystemPartitionCommitLimitPercentage` = 87 (#1610 Decision 0 is resolved) |
| Box state | processes, RAM | No model resident, no Python running except MCP servers. In-Use ≈ 11.9 of 31.32 GB at 04:07. **Up since 2026-10-03 10:21 (~18 h)** |
| Nothing goes live / replacement is the LA's call | #1663, default.toml `brain_model_dir = ""` | Correct classification. A measurement arc, no flag flips |
| Signing ceremony needed? | grep `evals/` | No. The eval harness does not verify manifests; only the production brain switch does (default.toml capability list). Out of scope here |

## 3. Gaps, most important first (all defects: the session fixes them)

**D1 — "Every eval suite" would silently leave the Policy Agent half unmeasured.** The 4B ships in VLM
layout, so `detect_brain_layout` reads it as multimodal. For a multimodal target, `pa_classification`
**skips its 13 model cases** (`evals/suites/pa_classification.py:268–320`) and still prints its 22
deterministic passes. That is the signature where "checked and clean" looks like "could not check".
The brain is shared by the Policy Agent and the Assistant Orchestrator. The #1610 S4 bars name the
PA checks a replacement must pass: PA ≥0.90 on the 256-case corpus, 35/35 pa_classification, 0/4
injected commands obeyed, answer quality ≥35/37. **Fix:** route PA classification through the 4B arm
too. If that cannot be built inside the budget, the verdict must say "Policy Agent not measured",
and that blocks a "proper candidate" conclusion.

**D2 — The test that disqualified the last candidate is not in the plan.** The 35B was rejected
because eight random datamark characters, or one trailing space, moved its verdicts while the 14B held
20/20/20 (PERFORMANCE_LOG 2026-09-22; `fragility_generalises_*.json`; `datamark_confound_*.json`).
Agentic ×3 under production's random marker measures marker sensitivity, not determinism. The stop
condition "the 14B disagrees with itself across identical runs" is only meaningful with PINNED inputs,
and input identity was assumed rather than measured the last time (commit `beaffa26`). Neither the
pinning nor the perturbation instrument was ever committed: `_generate_data_marker` appears only in
`context_manager.py`, and `beaffa26` / `1464533a` banked JSON only. **Fix:** run three arms for both
models: (a) random marker ×3, the production condition; (b) pinned marker ×3, with input identity
measured under the ≥2-repeat rule; (c) the V0/V1/V2 meaning-preserving gauntlet. Commit the
instrument. Define the stop condition as: pinned inputs measured identical, and verdicts differ.

**D3 — The MTP on-vs-off byte-identity check has no pre-registered reading.** Qwen3.5 is a 3:1
linear-attention hybrid (research note §1). Intel's position (#4367) is that the GPU plugin "does not
guarantee bit exactness", and advancing a recurrent layer by k tokens in one call is a different
computation from k single steps. So on≠off may be expected rather than a defect. **Fix, in this
order:** MTP-off repeat identity, then MTP-on repeat identity (pinned), then on vs off. If the bytes
differ, report whether any verdict moved. That is what matters behind the adjudication door. Stamp
`KV_CACHE_PRECISION` and `DYNAMIC_QUANTIZATION_GROUP_SIZE` (the #4476 cause) to match production.

**D4 — Nothing proves MTP actually engaged.** MTP switches on because a file is present. A silently
inactive head would produce "no speed-up", which reads exactly like #38153. **Fix:** record
proposed/accepted draft tokens (acceptance rate) per run, and refuse to report a speed result if the
count is zero.

**D5 — Speed at one context length misses both known costs.** #38153's penalty grows with context.
MTP also requires prefix caching OFF, so every multi-turn assistant turn re-reads its history, a
time-to-first-token cost the 14B (prefix caching on) does not pay. **Fix:** measure at a Policy-Agent-
sized prompt AND a production assistant-sized context, plus multi-turn TTFT. Run the MTP-off arm with
prefix caching OFF too, so the on/off delta is MTP alone. Separately report the 4B-with-caching-on
figure as the price MTP charges.

**D6 — The runtime confound is named but could be held.** The 14B has never been measured on 2026.4.
S0 lists "any runtime other than 2026.2.1" as not measured. **Fix:** add one 14B speed arm on
`.venv-2026.4` (n≥3). If it won't run, record why. Either result is better than "unheld".

**D7 — The #1610 epic's rules bind every limb, and the gate omits them.** Announce the GPU window on
#1610 with start and end times. Reboot before the campaign. Stamp both budget keys, the driver,
CACHE_DIR, uptime and run index. Interleave the arms. State the minimum detectable effect before
running. #1487 measured up to −37% drift building within one boot session, cleared only by a reboot.
The box has been up ~18 h. A reboot ends the session itself, so it is the LA's call (§4).

**D8 — No monitoring plan. This answers the LA's question.** Hours of unattended GPU runs, and nothing
says how they will be watched. **Fix:**
- Launch every model run detached (`Start-Process`), because the harness has killed ~15 GB background
  tasks.
- Write one progress line per case to a status file.
- Arm a `Monitor` on that file's CONTENT that emits on: no new progress line within the phase's stall
  bound (state it from the measured per-case time); an error signature (`Traceback|Error|OOM|USM Host|
  Killed`); the process's PID disappearing; and completion. Monitors expire at 30 min, so re-arm on
  each expiry.
- Post a dated CURRENT STATE comment on #1663 at each phase.
- Not a fixed 15-minute poll. An event-driven watch costs nothing while the run is healthy and wakes
  within seconds of a crash, or within the stall bound for a hang. A poll is up to 15 minutes late and
  spends tokens when nothing has changed.

**D9 — Tool-call format mismatch is not named.** The Qwen3.5-4B template trains XML-style calls
(`<tool_call><function=…><parameter=…>`). Production parses JSON only: there is no `<function=` parser
in services/ or shared/, and `tool_call_grammar = false`. The 35B followed production's JSON
instructions, but a 4B may drift to its trained format, and a format miss would score as a capability
miss. **Fix:** count XML-format emissions separately in the verdict.

**D10 — The ceiling arithmetic.** 10 of the 30 agentic cases are offline/scripted (golden: 20 model,
10 offline). The model-relevant score is out of 20, so the ceiling effect is sharper than "30/30"
suggests. The 14B's conversation baseline is not a ceiling: it is 20 pass / 1 tool-call / 1 fail
(`conv-inj-01` obeyed a user-turn injection, #1629).

**D11 — The standing gate is not mentioned.** Get the branch gate-green before merge and re-run the
gate on merged main. Run it elevated, from bash, with LOCALAPPDATA redirected and the app down. Never
run it while a measurement is running: S0's 14B pass 2 was contaminated by exactly that.

**D12 — Finishing mechanics.**
- Write the journal as a FRAGMENT (docs/journal_fragments/, 35 waiting), not into BUILD_JOURNAL.md.
- Write a disposition record for this review's findings (`docs/reviews/…-disposition-2026-10-04.md`)
  and run `scripts/verify_disposition.py`.
- Upload performance rows only to HF (a public CC-BY dataset), never personal content.
- Set #1663 to Doing with a comment at start.

**D13 — Form.** The doctrine and the card both ask for a ≤10-line delta-gate; this one is about 25. Not
blocking.

## 4. The one decision for the LA

**Reboot the laptop before the measurements start? Recommendation: yes, reboot now, before you say
"go".** The machine has been up about 18 hours. This project has measured slowdowns of up to 37%
building up within one boot, and only a restart clears them. The epic's own rules require a reboot
before every measurement campaign. Cost: it closes both Claude sessions. The gated session restarts
from its landing card plus this file and gives you a short delta-gate again, about 5 minutes of your
time.

Alternative: no reboot. The session interleaves the 4B/14B and MTP on/off runs minutes apart, so slow
drift hits both sides equally, and stamps the uptime. The comparison between arms stays fair. But the
speeds can't be compared with past numbers, and the extra spread makes a small MTP gain harder to see.

## 5. Response to send back to the gated session

> Independent review of your #1663 delta-gate is in
> `docs/reviews/gate-review-1663-qwen35-phase1-2026-10-04.md` (in your worktree, untracked; commit it
> with your disposition record). Goal, scope, git plan, authority split and dormant classification are
> right. Before "go", re-issue the gate as a ≤10-line delta that folds in D1–D12 from that file, in
> particular:
>
> - **D1** — the Policy Agent half must be measured (pa_classification skips multimodal targets).
> - **D2** — random-marker, pinned-marker and perturbation arms for both models, with the instrument
>   committed.
> - **D3/D4** — repeat-identity before the on/off identity check, and an MTP acceptance witness.
> - **D5** — two context lengths plus multi-turn TTFT, with prefix caching off in both MTP arms.
> - **D6** — a 14B speed arm on 2026.4.
> - **D7** — the #1610 epic rules.
> - **D8** — the monitoring plan: detached runs, a per-case status file, and a content-based Monitor
>   that fires on stall, error, death and completion, re-armed at expiry; CURRENT STATE comments per
>   phase; no fixed polling.
> - **D9** — count XML tool-call emissions separately.
> - **D11** — the standing gate on the branch and on merged main, never during a measurement.
> - **D12** — fragment, disposition record, HF rows only.
>
> These are your technical calls; do not bring them back as questions. I will tell you separately
> whether to reboot first.
