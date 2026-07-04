---
sprint_id: 12
sprint_name: "Provenance- and intent-aware content handling"
predecessor_sprint_id: 11
vikunja_tracking_task_id: 587
start_date: "2026-06-04"
target_completion_date: "2026-06-09"   # agent-wall-clock-gated (~2-4 days); LA acceptance now optional ~5 min. Adjust at sign-off.
la_approved_on: "2026-06-04T17:40:08-07:00"
la_approved_by: "blarai"
co_lead_drafted_on: "2026-06-04T16:44:45-07:00"
co_lead_commit_when_drafted: "84f21de"
sdv_version: 4
---

# Strategic Design Vision — Sprint 12: Provenance- and intent-aware content handling

## 1. Executive brief

Today BlarAI treats one crude signal — "a document was loaded this session" — as the trigger for its tool-privilege lock (ADR-013 Layer 3) and, until recently, its output-leakage alarm. That signal is wrong in both directions, and **both controls are paying for it right now**: the action-lock is so frictiony on the user's own files that the shipped config disables it outright (`block_tools_when_documents_loaded = false` in both `default.toml` and `guest_runtime.toml`), and the Stage-5 leakage detector flagged a legitimate document summary as a leak — which is why it sits **inert** on `main` (reverted at `f3754fe`). So BlarAI currently ships with **both** content-security controls effectively off, because the only trigger they have ("a file is loaded") is too crude to be either usable or accurate. Sprint 12 replaces that signal with a **provenance** (where content came from) **+ intent** (what the user is doing with it) model: trusted-local files and trusted-memory recall flow with zero friction; the action-lock, injection-scan, and leakage controls apply only to **untrusted-external** content — which lets both controls be turned back **on** without friction or false alarms. "Done" = on a live elevated boot, daily-driver document and memory use shows zero trust friction and zero false leakage holds; untrusted content (exercised this sprint via pasted-in chat text) automatically engages the controls; `/trust` is retired to a rare manual escape hatch; and the Assistant-Orchestrator (AO) tool loop no longer bypasses the Policy Agent (PA).

## 2. Context

### 2.1 Predecessor sprint outcome

- Predecessor SCR (Strategic Completion Report): `docs/sprints/sprint_11/strategic_completion_report.md`; predecessor SWAGR (Strategic Work Analysis and Gap Report): `docs/sprints/sprint_11/Strategic_Work_Analysis_and_Gap_Report_Sprint_11_20260512_183000.md`.
- Sprint 11 ("Process-Hygiene Backlog Paydown," closed 2026-05-12) was a docs/governance sprint with zero runtime code; it does not drive this sprint. **The fact that drives this sprint**: in the ~3 weeks since, a large body of runtime work shipped to `main` *outside* the formal sprint cadence (the Tier-1 security wave, voice, vision, substrate-perf, speculative-decoding), and that wave's **2026-06-04 live-verify** surfaced the leakage false-positive, the purposeless `/trust`, and the wrong upload metaphor — the three symptoms this sprint unifies. Sprint 12 is the first formal-cadence **code** sprint after that off-cadence run.

### 2.2 Repo state at kickoff

- **Main branch HEAD**: `84f21de` (`Merge feat/substrate-perf`).
- **Most recent ledger entry**: `docs/ledger/20260604_184221_iss1-spec-decode-closure.md` (Q1-1 per-file; the monolithic ledger remains frozen at Entry 52).
- **Open Vikunja `Gate:Pending-Human` gates affecting this scope**: 0 (Project 6 swept at kickoff).
- **Test baseline**: **1714 passed, 3 skipped** at `84f21de` (the `~1442` from the 2026-06-03 audit and the `1001` in `CLAUDE.md` are both stale — the recurring Active-State drift). Re-measured at the EA-2 foundation increment.
- **Security control state (the spine of §3)**: ADR-013 Layer 3 ships **disabled** — `block_tools_when_documents_loaded = false` at `default.toml:65` and `guest_runtime.toml:53` (2026-06-03 audit, Domain-4) — so the action-lock does not currently fire. The Stage-5 retrieval-leakage detector is **inert** (`retrieved_chunks=[]` since `f3754fe`). The AO tool loop dispatches the four built tools (time/date/day/calculate, all network-free) **without Policy-Agent adjudication** (#570). The secure-by-default the ADR designed (flag default `true`) was overridden to `false` in shipped config to escape the friction — the misconfiguration-vs-usability tension this sprint resolves.

### 2.3 External inputs driving this sprint

- **LA asks / discovery**: the 2026-06-04 security-hardening session produced epic **#580** + children **#581–#586**, plus **#579** (Stage-5 leakage redesign) and **#570** (AO tool-loop bypasses the Policy Agent). LA scope decisions (2026-06-04): full three-tier model including untrusted-external (Q1-B), build the #570 mediation fix now (Q2-B), direct-execution increments (Q3-B), one live-verify at end (Q4 — superseded in v3 by per-increment real-model/real-UI automation; see §4).
- **Stakeholder concerns**: a security control (Stage-5) is currently disabled and so is the action-lock (Layer 3, by config); daily-driver friction from `/trust`; the cloud-borrowed "upload" metaphor is wrong for a local system.
- **Relevant ADR / decision items**: this sprint authors **ADR-023** (next free BlarAI ADR number; `docs/adrs/` runs to ADR-022), revising ADR-013's gate condition; ADR-023 **supersedes the held decision #558** ("re-enable the old block-tools gate + fix /trust"). The user-memory `project-network-facing-future` and the 2026-06-03 security hard-gate (#556 / the #787 GO/NO-GO gate: no internet-facing capability until security Tiers 0–3 are complete and verified) bound the untrusted-external work.

## 3. Sprint purpose

BlarAI's content-trust posture is built on a category error: it asks "is a document loaded?" when the security-relevant question is "where did this content come from, and what is the user trying to do with it?" The cost is visible in the shipped state. The action-lock's only mode is the on-any-document, `/trust`-to-escape lock — frictiony enough on the user's own files that the shipped config turned it **off** (`block_tools_when_documents_loaded = false`), leaving the tool-privilege control a no-op. The leakage detector's only mode is cosine-similarity against all grounded content — which flags a legitimate summary, because a summary is similar to its source *by design* (#579), so it was reverted to **inert**. And the input model is conceptually wrong for a local machine — there is nothing to "upload"; the file is already on disk.

These are not three problems. They are one: BlarAI has no provenance dimension, so its only trigger is the crude "a file is loaded," which is simultaneously too aggressive (it locks and scans the user's own material → disabled to stop the friction) and too blunt (it cannot tell a summary from a leak). Sprint 12 builds the missing dimension. A provenance tier (`trusted-local`, `trusted-memory`, `untrusted-external`) is threaded through every grounded chunk, set at ingest by source, and read by the Layer-3 action-lock and the leakage/injection controls. The controls stop firing on the user's own material and start firing on content from the outside world — which lets them be turned back **on**, secure-by-default, without the friction or false alarms that forced them off.

Why now, and why the full model including the untrusted tier (LA decision Q1-B): the network-facing future is on the roadmap but **hard-gated** behind the security tiers, and the provenance model *is* part of what makes it safe to eventually remove the air-gap. Building the untrusted-content machinery now — tagging, action-lock, injection-scan, and leakage control on untrusted-provenance content, exercised against the one untrusted channel that exists today (pasted-in chat text) — means the trust substrate is in place and verified before web-navigation goes live (the web-search skill is already in active development — §8.2), not improvised under deadline alongside it. The same logic closes #570 now (Q2-B): the AO tool loop bypasses every Policy-Agent deny rule, harmless while the four tools are network-free but the exact hole a future `web_fetch` tool would fall through.

If we skip this sprint: both content-security controls stay off (security debt in plain sight), the daily-driver friction that disabled the action-lock persists, and the eventual web-nav build inherits an unprincipled "loaded = unsafe / fetched = unguarded" trust model with no provenance to reason over.

## 4. Success criteria

> **Amendment (v4, 2026-06-04, post-SWAGR) — verification-method deviation recorded.** The binding verification method specified below and in §6/§10 — per-increment **real-model (Layer B) / real-UI (Layer C, pywinauto) automated tests** — was **NOT delivered** for any criterion; no Layer-B/C automated harness was built. Sprint 12's actual verification was (a) the headless **mocked-model** suite — the deterministic controls (gate, leakage feed, #570 deny) are model-INDEPENDENT and proven by `call_count` / `retrieved_chunks` teeth-tests regardless of the model — plus (b) the LA's **manual live-verify** on the real elevated runtime, which caught real regressions (the EA-7 referent bug, the EA-6a layer miss). **Residual risk (honest):** there is no automated real-model/real-UI regression *gate*, so the §6 "mocked-CI-slips-a-regression" risk is only partially mitigated — the human caught this sprint's, but that is not repeatable CI. The harness is ticketed **#592**. This amendment is recorded per the amend-the-SDV-before-claiming-PASS discipline; the SCR's PASS verdicts are claimed against THIS amended standard, not the unmet v3 one. (SWAGR MAJOR-1.)

1. **Provenance foundation.** Every grounded chunk in the AO's ContextManager carries a provenance tier (`trusted-local` / `trusted-memory` / `untrusted-external`), set at ingest by source, readable by Layer 3 and the PGOV (Policy-Governor output) pipeline. *Verification: per-tier unit tests pass; `git diff` shows the enum threaded through ContextManager and consumed by the gate + the validator; an unset/unknown provenance resolves to `untrusted-external` (fail-closed).*
2. **ADR-023 ratified.** A tight, ~20-minute-ratifiable ADR-023 establishes "trust follows provenance," defines the provenance taxonomy, specifies how Layer 3 reads it, states `/trust`'s fate, names the #570 mediation design (with enforcement), and records the path-not-taken (keep per-document `/trust`; re-enable the old gate). It explicitly **supersedes #558**. *Verification: `docs/adrs/ADR-023-*.md` on main; LA-authored/approved sign-off commit; `docs/DECISION_REGISTER.md` updated.*
3. **Provenance-driven action-lock (re-enabled, secure-by-default).** The Layer-3 gate is turned back **on** but now reads provenance: (a) with only trusted-local and/or trusted-memory content present, tools fire with **no block and no `/trust`**; (b) with untrusted-external content present, the action-lock engages and injection-scanning applies. The broken `/unload` restore (observed 2026-05-26) is fixed. *Verification: a real-model (Layer B) / real-UI (Layer C) automated test in the same increment (load local docs → tool fires; pasted untrusted text → tool blocked; `/unload` restores cleanly) + headless tool-call-loop tests for both halves and the fail-closed default (unknown provenance ⇒ locked); LA end live-verify optional.*
4. **Leakage control redesigned.** The Stage-5 detector no longer suppresses legitimate grounded answers (summary or recall over trusted content), honors the previously-vestigial `leakage_detection_enabled` config flag, and fires only on untrusted-provenance content. *Verification: a real-model (Layer B) automated test in the same increment proving summary + recall produce no false hold and an untrusted leak is still caught; the 8 accessor unit tests + 1 previously-skipped wiring test in `test_pgov_leakage_wiring.py` re-enabled and green; a test asserts the config flag is now honored.*
5. **Workspace-folder input.** The user can drop files into a permitted workspace folder and ask about them by name/description without an explicit upload step; folder scope is limited to permitted folders (not the whole disk); an explicit focus/pin affordance survives. *Verification: a real-UI (Layer C, pywinauto) automated test in the same increment + headless folder-read path feeding provenance=`trusted-local`; scope-limit test.*
6. **Intent disambiguation.** A turn whose reference (`"summarize this"`) matches more than one high-relevance candidate yields a one-line clarification rather than a confused multi-referent answer; a turn with one clear referent answers directly (freshest pin wins by default). *Verification: a real-model (Layer B) automated test for the two-referent and one-referent cases in the same increment.*
7. **#570 closed (enforced, not relocated).** AO tool dispatch is adjudicated by the Policy Agent per ADR-023's chosen mediation design; the P-004 external-network deny rule is enforced at the AO tool loop, not only at the PA boundary; the registration-time approval for fixed-action tools is a **real enforced check** against a PA-approved manifest, not a convention. *Verification: a real-model (Layer B) automated test in the same increment that a deny-class/unapproved tool action is refused at the AO loop and an allowed tool round-trip still works; headless test of the manifest check.*

**Verification standard for the user-facing criteria (#3–#7).** Each ships with a **real-model (Layer B — real Qwen3 on the Arc 140V, the harness today's substrate benchmark used) and/or real-UI (Layer C — pywinauto over the WinUI surface) automated test, authored in the same increment as the behavior**, GPU-serialized and human-free. The default 1714-test suite *mocks the model* — and that mocking is exactly why the Stage-5 leakage false-positive slipped past CI and only the human caught it on the live screen. Real-model/real-UI coverage is therefore a deliverable, not optional: the headless mocked suite stays green-before-commit, but the user-facing security behavior is proven against the real model and UI before the increment lands. This drops the LA end live-verify (§11) from binding constraint to an **optional ~5-minute final acceptance** on the security-critical changes.

## 5. Scope

### 5.1 In-scope

1. **Provenance tagging foundation (#582)**: a provenance enum carried on grounded context in ContextManager, set at ingest by source, queryable by the gate and the validator. Extends the existing `#543` `source=` (document-vs-memory) seam into a fuller dimension. The foundation every other item builds on.
2. **ADR-023 — provenance trust model (#581)**, a **tight decision doc** (ratifiable in ~20 minutes), folding in the **untrusted-detection spike (#586)** as its up-front design-resolution step (what marks content untrusted; where the boundary with #570/egress sits; whether a light provenance tag can precede the full Cleaner). Decision gate; LA-ratified.
3. **Trust / Layer-3 redesign (#584)**: re-implement the action-lock to read provenance — trusted → pass, untrusted → lock; retire `/trust` to a rare escape hatch; fix `/unload` restore.
4. **Stage-5 leakage redesign (#579)**: replace cosine-against-all-grounded with a provenance+intent-aware control; honor `leakage_detection_enabled`; re-enable on the untrusted path only.
5. **Untrusted-content path + #570 mediation (#570, untrusted half of #586)**: tag pasted-in chat text as `untrusted-external` at ingest, injection-scan it, and route AO tool dispatch through Policy-Agent adjudication (CAR submission) per ADR-023, with the fixed-tool registration-time approval enforced against a manifest and tested. Security-critical increment.
6. **Workspace-folder input UX (#583)**: a permissioned workspace-folder read path feeding provenance=`trusted-local`, retiring the upload metaphor; keep a focus/pin affordance.
7. **Intent disambiguation (#585)**: a cheap disambiguation step at prompt-assembly when >1 high-relevance candidate exists.

### 5.2 Out-of-scope (deliberately deferred)

1. **Web-navigation / live `web_fetch`** — hard-gated behind security Tiers 0–3 per #556/#787. The web-search skill is in active development and may be *built ahead*, but it stays **gated (not live)** until the tiers — including this sprint — are complete and verified (§8.2). This sprint builds the untrusted *machinery* and exercises it via pasted text; the web-fetch source is wired to it later, when the gate opens.
2. **The full Cleaner (UC-003) classifier + three-field signature gate** — a larger build (security Tier 2). Sprint 12 ships a lighter provenance tag + injection-scan; the spike (in EA-1) confirms the tag can precede the full Cleaner.
3. **Encryption-at-rest, VM/mTLS isolation, dependency pinning** — other security-roadmap tiers, not content-provenance.
4. **Deleting `/trust` entirely** — kept as a rare manual escape hatch (§13).

### 5.3 Scope boundaries and edge cases

- **Untrusted source this sprint = pasted-in chat text only.** Per the LA's Q1-B decision, the untrusted tier is built in full — but the only untrusted *channel* that exists today is pasted text (the audit flagged it is never injection-scanned). Web-fetch is the future source; it is the one untrusted piece deferred (§5.2 #1). The gate, the injection-scan, and the leakage control on untrusted are all built and verified now.
- **#570 mediation design is a Co-Lead recommendation inside ADR-023**, ratified by the LA at ADR sign-off. Leaning hybrid: fixed-action-class tools (time/date/calculate) are approved at **registration time** against a Policy-Agent-approved tool manifest checked at AO startup; variable-action-class tools (a future `web_fetch`, whose URL varies per call) submit a per-call **CAR (Canonical Action Representation — the object `shared/schemas/car.py` already has the PA adjudicate)**. So cheap fixed tools pay no per-call latency while the boundary stays tight where the action varies. **The registration-time approval is a real enforced check, not a convention**: a tool absent from the PA-approved manifest cannot dispatch, and a test asserts a deny-class/unapproved tool is refused at the AO loop — otherwise the bypass is merely relocated, not closed.
- **Fail-closed is non-negotiable.** A chunk whose provenance is unset/unknown is treated as `untrusted-external`, never as trusted. The redesigned gate keeps the secure-by-default posture: a provenance-read bug must lock, not unlock.
- Adjacent-module edits are minimal-and-only-if-required; the working set is the AO (`context_manager.py`, `entrypoint.py`, PGOV pipeline, config TOMLs), the Policy Agent boundary for #570, and the WinUI input path for #583.

## 6. Deliverable summary

| Deliverable | Type | Target location | Success criterion |
|---|---|---|---|
| Provenance enum + tagging on grounded context | code | `services/assistant_orchestrator/src/context_manager.py` | #1 |
| Provenance unit tests (per tier + fail-closed default) | test | `services/assistant_orchestrator/tests/test_context_manager.py` | #1 |
| ADR-023 — provenance trust model (tight: taxonomy + Layer-3 read rule + `/trust` fate + #570 mediation + path-not-taken) | doc | `docs/adrs/ADR-023-Provenance-Based-Trust-Model.md` | #2 |
| DECISION_REGISTER update (supersede #558) | doc | `docs/DECISION_REGISTER.md` | #2 |
| Provenance-driven Layer-3 gate + `/unload` fix | code | `services/assistant_orchestrator/src/entrypoint.py` | #3 |
| Redesigned Stage-5 leakage control + honored flag | code | `services/assistant_orchestrator/src/` (PGOV) + AO config TOMLs | #4 |
| Re-enabled leakage tests | test | `services/assistant_orchestrator/tests/test_pgov_leakage_wiring.py` | #4 |
| Workspace-folder read path + pin affordance | code | AO input path + WinUI surface | #5 |
| Intent-disambiguation step at prompt-assembly | code | `services/assistant_orchestrator/src/` | #6 |
| AO→PA tool-dispatch mediation (CAR) + enforced fixed-tool manifest | code | `services/assistant_orchestrator/src/entrypoint.py` + PA boundary | #7 |
| **Real-model (Layer B) / real-UI (Layer C) automated tests, one per user-facing criterion, in-increment** | test | `services/assistant_orchestrator/tests/` (real-model) + WinUI/pywinauto test harness | #3–#7 |
| BUILD_JOURNAL entry per substantive increment | doc | `BUILD_JOURNAL.md` | all |
| One sprint-close ledger index entry (Q1-1) | doc | `docs/ledger/` | all |

## 7. EA milestone plan

Direct-execution increments (per Q3-B) under the SDV/SCR/SWAGR governance wrapper — the same model that shipped the Tier-1 security wave, not the autonomous SDO→EA-Code→Co-Lead chain. "EA-#" labels are retained for template/SCR/SWAGR parity. The shape is **decision-gate → foundation → fan-out**, not a flat parallel set.

| EA-# | Working title | One-sentence purpose | Depends on | Approx size |
|---|---|---|---|---|
| EA-1 | ADR-023 + spike resolution | Author the provenance trust model (tight, ~20-min ratifiable), resolve the #586 untrusted-boundary questions, recommend the enforced #570 mediation design; LA ratifies | main | M (doc) |
| EA-2 | Provenance tagging foundation | Thread the provenance enum through grounded context; set at ingest; readable by gate + PGOV; per-tier tests | EA-1 | M (code) |
| EA-3 | Trust / Layer-3 redesign | Gate reads provenance (trusted→pass, untrusted→lock); retire `/trust`; fix `/unload` | EA-1, EA-2 | L (code, real-model+UI test) |
| EA-4 | Stage-5 leakage redesign | Provenance+intent-aware leakage control; honor the config flag; re-enable on untrusted only | EA-2 | M (code, real-model test) |
| EA-5 | Untrusted path + #570 mediation | Tag pasted text untrusted + injection-scan; route AO tool dispatch through PA adjudication (CAR) with enforced + tested fixed-tool manifest | EA-1, EA-2, EA-3 | L (code, real-model test, security-critical) |
| EA-6 | Workspace-folder input UX | Permissioned folder read → provenance=trusted-local; retire upload metaphor; keep pin | EA-2 | M (code, real-UI test) |
| EA-7 | Intent disambiguation | One-line clarification on ambiguous referents; freshest pin wins | EA-2, EA-6 | S–M (code, real-model test) |

**First visible running slice (LA directive).** Right after EA-2 lands the foundation, **EA-3's trusted half is the first demoable behavior** — load a local file, use a tool, no lock, no `/trust` — surfaced *before* the more invisible plumbing (leakage redesign, untrusted path). The workspace drop-a-file-and-ask-by-name (EA-6) is the second visible win. The point is that a running, user-visible behavior appears early, not after all the security wiring.

Increments are collapsible if execution proves them small (e.g. EA-6 + EA-7 as one input/intent increment; EA-3 + EA-5 as one gate-and-untrusted increment). Each increment lands green-before-commit on **both** the headless mocked suite **and** its real-model (Layer B) / real-UI (Layer C) automated test (§4), with a BUILD_JOURNAL entry; the LA's end live-verify drops to an optional ~5-minute final acceptance on the security-critical changes.

## 8. Dependencies and prerequisites

### 8.1 Upstream dependencies

- **ADR-023 ratified (EA-1)** before the untrusted reasoning in EA-3/EA-4/EA-5 is committed (the ticket guidance: run the spike before committing the untrusted half).
- **Provenance foundation (EA-2)** before EA-3/4/5/6/7 — all read the tier.
- The existing **`#543` `source=` seam** must still be on `main` (verified at EA-2 start; provenance extends it rather than inventing a parallel dimension).

### 8.2 External dependencies

- **Arc 140V GPU + WinUI elevated boot available** for the per-increment real-model (Layer B) and real-UI (Layer C) automated tests, GPU-serialized; and for the optional LA end-acceptance.
- AO + OpenVINO runtime stable on the Lunar Lake target; Vikunja MCP server running for tracking.
- **Web-search coupling (active development — coordinate).** §8.2's old "air-gap means no web capability exists" assumption is no longer true: the **web-search skill is in active development**. This sprint's #570 mediation + untrusted-provenance tagging is precisely the substrate a `web_fetch` must flow through. Coordination requirement: web-search must **not** ship a PA-bypassing `web_fetch` before #570 lands, and the skill stays **gated (built-ahead OK, not live)** until the security tiers — including this sprint — are complete **and** verified per #556 / the #787 GO/NO-GO gate.

### 8.3 Assumed invariants

- Fail-closed posture is preserved and strengthened: the provenance gate locks on unknown provenance; secure-by-default (`block_tools_when_documents_loaded`-equivalent, but now provenance-driven) survives the redesign — and is turned back **on**, unlike the current shipped state.
- Layers 1 + 2 (delimiter neutralization + heuristic phrase scanner) and per-load datamarking from ADR-013 remain in force — Sprint 12 changes the *trigger*, not these defenses.
- The web-search skill stays **gated (built-ahead, not live)** for this sprint's duration; no live `web_fetch` reaches the AO tool loop before #570 lands.
- No production source outside the named AO / PA / WinUI working set is touched except minimal-and-required edits.

### 8.4 Parallel-Sprint Authorization & Shared-Artifact Audit

**N/A — serial kickoff (no other sprint active).** `docs/active_tasks.yaml` roster is empty at kickoff; no concurrent *sprint* overlaps this one. `set_parallel_sprints_authorized` is not invoked.

**Session-coordination note (the real concurrency risk here).** While no concurrent *sprint* runs, concurrent *sessions* (e.g. this governance session + a security-orchestration session + the web-search workstream) edit the **same AO working set** — `context_manager.py`, `entrypoint.py`, the PGOV pipeline. Mitigation: **one session drives the AO files at a time** (single-writer); any second session uses `git worktree add`, never `git checkout`/`switch` on the shared tree. (The 2026-05-22 model-sharing race — two sessions on one tree via checkout — cost a branch landing; worktree-not-checkout is the standing rule.)

## 9. Risks and unknowns

### 9.1 Known risks

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Security-critical regression slips past mocked CI (as the Stage-5 false-positive did — caught only by the human) | med → low | high | Per-increment real-model (Layer B) + real-UI (Layer C) automated tests are the binding gate, authored in the same increment; the headless mocked suite stays green too; LA acceptance optional |
| Threading the provenance enum through the ContextManager hot path regresses grounded-context assembly | med | med | Foundation (EA-2) lands isolated with per-tier unit tests before any consumer; the real-model test confirms assembly |
| Provenance unset/unknown silently treated as trusted (fail-OPEN) | low | high | Explicit invariant + test: unknown provenance ⇒ `untrusted-external`; gate default is lock |
| #570 fix implemented as a convention (comment / name-only allowlist) rather than enforcement → bypass relocated, not closed | med | high | Registration-time approval is a real check against a PA-approved manifest at AO startup + a test asserting a deny-class/unapproved tool is refused at the AO loop (ADR-023 specifies both) |
| Web-search skill ships a PA-bypassing `web_fetch` before #570 lands | low | high | Coordinate (§8.2): web-search stays gated (built-ahead, not live) until the tiers incl. this sprint complete + verified per #556/#787; #570 mediation is the gate `web_fetch` must flow through |
| Retiring `/trust` breaks flows/muscle-memory that relied on it | low | med | Keep `/trust` as a rare manual escape hatch (not deleted); `/unload` restore fixed; ADR records the reduced role |
| #570 per-call CAR adds latency to every tool call | med | med | Hybrid design (registration-time manifest approval for fixed-action tools; per-call CAR only for variable-action tools) — recommended in ADR-023 |
| Untrusted-ingest point for pasted text is messier than expected | med | med | Spike (EA-1) resolves the ingest seam before EA-5 builds; pasted-text is the only channel, bounding the surface |

### 9.2 Known unknowns

1. The exact ingest point where pasted-in chat text is tagged `untrusted-external` (vs. where a future web-fetch result would be) — resolved by the EA-1 spike.
2. How workspace-folder file-selection disambiguates a by-name reference to the right file (feeds EA-7's intent step).
3. Whether the lighter provenance tag fully suffices ahead of the full Cleaner (UC-003), or whether injection-scan-on-untrusted needs a minimum signature check now — spike call.

### 9.3 Unknown unknowns posture

This is the first formal-cadence sprint to touch the AO's security-critical output path (PGOV + the tool-call gate) since that path was last reworked off-cadence in the Tier-1 wave. We are likely under-estimating coupling between the leakage redesign and the gate redesign (both read provenance, both sit near the tool loop), and the WinUI input path may carry assumptions about the upload metaphor that the workspace-folder model exposes only at the UI layer. The mocked-CI gap that let the Stage-5 false-positive through is now directly mitigated by the per-increment real-model/real-UI tests (§4) rather than relying on a human to catch it — which is the single biggest unknown-unknown reducer this sprint adds. If something still surfaces beyond that net, it becomes a Sprint 13 carry-over rather than a forced same-sprint fix.

## 10. Alignment to long-term roadmap

- **Project phase alignment**: Phase 5 (Post-Operational Development). The first Phase-5 sprint to advance a Use Case rather than harden process — answering the standing Sprint 9/10/11 SWAGR recommendation to "advance one UC."
- **Use Case alignment**: advances **UC-003 (The Cleaner)** by building its provenance/trust substrate (spec'd-but-unbuilt), and hardens **UC-004 (Assistant Orchestrator)** by making its tool-gate and leakage controls provenance-aware.
- **ADR alignment**: authors **ADR-023**, which revises ADR-013's Layer-3 gate condition and supersedes held decision #558. Complements the network/boundary controls from the Tier-1 wave (ADR-020 egress kill-switch, ADR-021 TPM-sealed signing key, ADR-022 untrusted-image isolation) — provenance is the *content-trust* complement to those.
- **DEC alignment**: supersedes #558; no change to the locked BlarAI DEC-01..10 production config. (BlarAI's `docs/adrs/` numbering is a separate namespace from the devplatform cf-program ADR-013..026.)
- **Largest scale**: provenance is the trust substrate the **network-facing future (#556, hard-gated)** requires. Building and verifying the untrusted tier now — even via pasted text — is direct progress toward the conditions under which the air-gap can eventually come down, without touching the air-gap today.

**Security-tier map (toward the #787 GO/NO-GO internet-facing gate).** Where this sprint sits in the security roadmap the #787 gate tracks:

| Bucket | Items (tickets) |
|---|---|
| **Completes — Tier-1 UC-004 content-trust (#558)** | re-enable the tool-privilege gate, provenance-driven (#584); redesign + re-enable Stage-5 leakage (#579); enforce P-004 at the AO tool loop via #570 |
| **Reaches into Tier 2 (#559)** | injection-scan on untrusted (pasted) content (full Cleaner + signature gate stays deferred to Tier 2) |
| **Builds new (enabler, not a prior tier item)** | provenance foundation (#582) + two UX features: workspace input (#583), disambiguation (#585) — not tier items |
| **Already banked (Tier-1 wave)** | manifest signing, allowlist prune, error sanitization |
| **Still remaining for #787 after this sprint** | **Tier 1**: guest `dev_mode` hardening, tamper-evident audit stream, measured-boot attestation, PII-filter posture. **Tier 2**: full Cleaner + signature gate, at-rest DB encryption, run-in-VM / mTLS / per-boot certs. **Tier 3**: dependency pinning + hash-verify, integrity-verify ALL model weights, automated egress test. |

## 11. Roles and accountability

| Role | Responsibility this sprint | Budget |
|---|---|---|
| LA (Lead Architect) | **ADR-023 ratification** (the security-capability gate) + an **optional ~5-minute final acceptance** on the security-critical changes — the per-increment real-model/real-UI automated tests are the binding verification, not the human | ~20–35 min total (~20–30 min ADR + optional ~5 min acceptance) |
| Co-Lead Architect | Authors + peer-reviews the direct-execution increments under governance; spot-checks security-critical claims; authors the lightweight completion record | Autonomous per DEC-11 §1.1 |
| SDO / EA Code | **Not engaged this sprint** — direct-execution increments per Q3-B (rows kept for template parity) | n/a |
| Sprint Auditor | Produces the SWAGR independently after the completion record lands | Autonomous per DEC-15 sprint_auditor_role_spec |

**Governance wrapper (lightened per LA, 2026-06-04).** This is security-critical, so we **KEEP**: ADR-023, the independent SWAGR, a BUILD_JOURNAL entry per substantive increment (the portfolio surface — NON-NEGOTIABLE per CLAUDE.md), and an LA acceptance step (now optional ~5 min). **Verification moves *left*** — per-increment real-model (Layer B) / real-UI (Layer C) automated tests are the binding gate (they would have caught the leakage false-positive the mocked suite missed), so the LA live-verify is no longer the binding constraint. We **LIGHTEN**: the SCR is reduced to a **lightweight completion record** — the success-criteria verdict table + scope-delivered/deferred status + carry-overs — not the full retrospective (roles-actual, duration narrative, and process observations live in the BUILD_JOURNAL, not a duplicate doc); and the ledger is **one sprint-close index entry** (Q1-1, DEC-17-compliant) pointing at the journal arc, not one entry per increment. The SWAGR audits against the completion record + the commits. (If any performance test runs, the community-grade perf-capture rule still applies — `PERFORMANCE_LOG.md` + `docs/performance/` JSON.)

## 12. Estimated effort

- **Rough duration**: 7 increments (3 doc-light/foundation, 4 code-heavy, each carrying its own real-model/real-UI test). **With per-increment real-model/real-UI automated verification (§4, §6), the binding constraint is the agent wall-clock — ~2–4 days — not LA availability**; the LA end acceptance is an optional ~5 min. The lightened wrapper (§11) removes roughly one increment of doc overhead versus recent sprints. Calendar target **2026-06-09**.
- **LA active-time expectation**: ~20–35 min total — ADR-023 ratification + an optional ~5-minute final acceptance.
- **Confidence in estimate**: **medium.** Authoring the real-model/real-UI tests adds work per increment, but it removes the late-surprise risk that drove v2's medium-low; the §9.2 unknowns (untrusted-ingest seam, workspace file-selection, Cleaner precedence) are now the main variance.

## 13. Deliberate non-goals

1. **Re-enabling the old block-tools-when-documents-loaded gate as-is** — **rejected**: #558 wanted exactly that. We instead replace its *trigger* with provenance and re-enable the provenance-aware gate. (The old gate currently ships off; we are not flipping it back on unchanged.)
2. **A cosine-similarity threshold tweak on the leakage detector** — **rejected**: #579 establishes that raising 0.85 either still flags summaries or stops catching real leaks; the fix needs provenance+intent, not a score.
3. **Building web-navigation / live `web_fetch`** — **rejected for this sprint**: hard-gated behind security Tiers 0–3 (#556/#787). Only the untrusted machinery is built (exercised via pasted text); web-search may be built-ahead but stays gated until the tiers, including this sprint, are complete and verified.
4. **Building the full Cleaner (UC-003) classifier + three-field signature gate** — **rejected for this sprint**: larger build (Tier 2); a lighter provenance tag suffices now (spike-confirmed).
5. **Deleting `/trust` outright** — **rejected**: retained as a rare manual escape hatch so no legitimate edge flow is stranded.
6. **Touching the air-gap / network posture** — **rejected**: the air-gap is the only real wall today and stays absolute.

## 14. Sign-off

### Lead Architect

> I, blarai (Lead Architect), have reviewed this SDV on `<date>`. I approve the
> sprint scope, success criteria, and risk posture as stated. I accept that the
> work will proceed as direct-execution increments under this governance wrapper
> within these bounds, that per-increment real-model/real-UI automated tests are the
> binding verification, and that I will ratify ADR-023 and may perform an optional
> end-of-sprint acceptance. I will read the completion record and SWAGR when produced.

_(Signed via the frontmatter field `la_approved_on` above. A commit authored by LA on main is the durable signature.)_

### Co-Lead Architect

> Co-Lead acknowledges the LA-signed SDV and will drive the increment sequence
> (decision-gate → foundation → fan-out) under the lightened SDV/SWAGR governance
> wrapper, with real-model/real-UI automated verification in every user-facing
> increment. Any scope deviation arising during execution will be flagged to the LA
> or escalated for adjudication.

_(Signed via the frontmatter field `co_lead_drafted_on` + the git commit by [agent:co_lead] that lands this SDV on main.)_

---

## Appendix A — SDV revision log

| Version | Date | Changed by | Change summary |
|---|---|---|---|
| 1 | 2026-06-04 | Co-Lead (Sprint 12 kickoff) | Initial draft for LA review. Encoded the four LA scope decisions (full three-tier incl. untrusted Q1-B; #570 fix Q2-B; direct-execution Q3-B; end live-verify Q4) and the two Co-Lead-owned interpretations (untrusted source = pasted text; #570 mediation design recommended in ADR-023). |
| 2 | 2026-06-04 | Co-Lead (LA code-grounded review, round 1) | Applied LA corrections verified against main @ `84f21de`: §2.2 corrected (Layer 3 ships OFF, `false` both configs) + §1/§3 re-grounded; baseline → `1714 passed, 3 skipped`; CAR expanded correctly as Canonical Action Representation (`shared/schemas/car.py`); #570 registration-time approval specified as enforced + tested; §8.4 session-coordination note; §7 first-visible-slice front-loaded; governance wrapper lightened (SCR → completion record, ledger → one entry, ADR tight); §2.1 trimmed; §11 SDO/EA rows collapsed. |
| 3 | 2026-06-04 | Co-Lead (LA review, round 2) | Three additions, then sign-off-ready: (1) **§10 security-tier map** toward the #787 GO/NO-GO gate (Completes Tier-1 UC-004 #558 / Reaches Tier 2 #559 / Builds-new / Already-banked / Still-remaining). (2) **Verification-automation deliverable** — each user-facing criterion (#3–#7) ships a real-model (Layer B, Arc) / real-UI (Layer C, pywinauto) automated test in the same increment (the mocked 1714-suite is why the leakage bug slipped past CI); §4, §6, §7, §9 updated; §11/§12 reframed so LA live-verify is optional ~5-min acceptance and the calendar is computed off the ~2-4 day agent wall-clock (target 2026-06-09). (3) **§8.2 web-search coupling note** — the skill is in active development; its `web_fetch` must flow through this sprint's #570 mediation + untrusted tagging; stays gated (built-ahead, not live) until the tiers incl. this sprint are complete + verified; §8.3 invariant + §9.1 risk row added. |
| 4 | 2026-06-04 | Co-Lead (post-SWAGR amendment) | **§4 verification-method deviation recorded** (SWAGR MAJOR-1): the Layer-B/C automated harness was not built; verification was the deterministic mocked suite + the LA's manual live-verify; harness ticketed **#592**; residual risk named. Honest record per the amend-before-claiming-PASS discipline. No success-criterion text changed; the verification *method* is what deviated. |
