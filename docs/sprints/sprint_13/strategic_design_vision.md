---
# Strategic Design Vision (SDV) — BlarAI Sprint 13
#
# This file is an LA-facing strategic document. It is authored
# interactively at sprint start by Co-Lead Architect (Orchestrator) +
# Lead Architect. It is the baseline against which the end-of-sprint SCR
# and SWAGR measure success and gap.
---
sprint_id: 13
sprint_name: "Tier-1 security finishers"
predecessor_sprint_id: 12
vikunja_tracking_task_id: 604
start_date: "2026-06-05"
target_completion_date: "2026-06-06"
la_approved_on: "2026-06-05T19:53:58Z"
la_approved_by: "blarai"
co_lead_drafted_on: "2026-06-05T19:53:58Z"
co_lead_commit_when_drafted: "56703cd"
sdv_version: 1
---

# Strategic Design Vision — Sprint 13: Tier-1 security finishers

## 1. Executive brief

Sprint 13 finishes the **no-ceremony remainder of Tier 1** in the air-gap-removal
campaign — three disjoint, deterministic security fixes the 2026-06-03 audit named, none
of which needs a hardware step from the Lead Architect (LA) to *build*. We do this now
because the campaign's main blocker — the eight §6 decisions — was **ratified 2026-06-05**,
and these three are the furthest-reaching work that requires no on-chip ceremony, so they
parallelize cleanly as the campaign's **first fleet wave** (and a low-risk proving ground
for the build→review→merge vehicle before the heavier Tier-2 lift). "Done" = three changes
on `main`, each Layer-A-tested **with teeth**: (1) the PII credit-card detector fires only
on **Luhn-valid** numbers instead of any long digit run; (2) **every** Policy-Agent
authorization decision is persisted to a **hash-chained, tamper-evident** audit log instead
of being discarded; and (3) a **fail-closed interlock** refuses to run dev-mode while
network-facing, and dev-mode is now **loud** instead of the silent default. The
production-posture live-verify of each (real keys, `dev_mode=false`) remains the LA's
per-tier step and is **not** claimed complete by this sprint.

## 2. Context

### 2.1 Predecessor sprint outcome

- Predecessor SCR: `docs/sprints/sprint_12/strategic_completion_report.md`
- Predecessor SWAGR: `docs/sprints/sprint_12/Strategic_Work_Analysis_and_Gap_Report_Sprint_12_20260605_061513.md`
- Sprint 12 ("Provenance- and intent-aware content handling," closed 2026-06-05) shipped a
  provenance-based trust model + a mid-sprint capability-scoped redesign (ADR-023 +
  Amendment 1), verdict **PASS-WITH-GAPS** (5 PASS / 2 PARTIAL; 0 CRITICAL, 3 MAJOR). Its
  carry-overs are ticketed (#590, #592–#595). One of them — **#593 DANGEROUS fail-closed**
  (commit `d3e5af7`) — was already landed under a provisional `[sprint:13]` tag and is
  treated here as a **pre-kickoff antecedent** of this sprint, not separate work.
- The single most important inherited lesson is the SWAGR's **MAJOR-1**: Sprint 12 promised
  in-increment real-model/real-UI tests, delivered mocked-headless tests + a manual
  live-verify, and claimed PASS without amending the SDV. Sprint 13 will **not** repeat that:
  §4 promises only the verification it will actually deliver (see §4 preamble).

### 2.2 Repo state at kickoff

- **Main branch HEAD**: `56703cd` (`docs(journal): fold air-gap-decisions + briefs-relocation
  fragments into BUILD_JOURNAL (lessons 43-45)`).
- **Most recent ledger entry**: `docs/ledger/20260605_061513_sprint12_scr_provenance-intent.md`
  (Q1-1 per-file; monolithic ledger frozen at Entry 52).
- **Open Vikunja `Gate:Pending-Human` gates affecting scope**: 0 (per Sprint 12 SCR §2.1).
- **Known feature branches**: the merged `feat/tier1-*`, `feat/543`, `feat/5`, `feat/566`,
  `feat/551`, `feat/security-*` (all `rev-list main..<branch> == 0`); their worktrees are
  leftover and removable via `git worktree remove` — branches are **left**, never deleted
  (destructive-git standing rule).
- **Test baseline**: predecessor reproduced **1661 passed, 2 skipped** (`-m 'not slow'`,
  `pytest services shared launcher tests`); the security handoff brief recorded **1501** on a
  different suite scope (`shared services launcher tests/integration tests/harness`). Both are
  point-in-time env snapshots. The live count is **re-measured at first merge** on a
  models-bearing tree and recorded in the SCR (baseline-drift discipline; CLAUDE.md Active
  State note).

### 2.3 External inputs driving this sprint

- **The air-gap-removal campaign**: roadmap `docs/security/SECURITY_ROADMAP_air_gap_removal.md`
  (#597); GO/NO-GO gate **#598**; the **8 LA-ratified decisions** (2026-06-05) — binding,
  not re-litigated. This sprint advances Tier 1 toward §5 of the gate.
- **The 2026-06-03 disk-rooted audit** (`docs/security/audit_2026-06-03/`): the authoritative
  finding set. The three finishers map to Domain 5 (PII Luhn), Domain 7 + the "Erase the
  evidence" attack path (audit stream), and Domain 1/2/6 "the worst default" (dev-mode).
- **LA autonomy grant (2026-06-05)**: proceed autonomously through the build; run the kickoff
  myself; build to code-complete against a software-stub TPM, then batch the LA's hardware
  steps. Binding constraints: never commit to main directly (branch + orchestrator-merge);
  no destructive git; a real product bug → STOP and report (do not fix unreviewed); only the
  production posture counts as "works" for the gate.
- **User memories**: mature-not-minimal; local-stack only (no cloud KMS / no new dependency
  without approval); committed ≠ done until verified + merged; escalate quality/capability/
  security decisions, decide pure mechanics.

## 3. Sprint purpose

The air-gap is BlarAI's foundational security property, and the LA has ratified that it comes
down **only** when all four tiers are complete and verified (Decision 1, FULL bar). Tier 0 is
done and most of Tier 1 is merged; what remains in Tier 1 splits into work that needs a
hardware ceremony (measured-boot attestation, deferred to a ceremony batch) and work that does
not. **This sprint is the second category** — the three finishers that can be built to
code-complete, headlessly, today. Doing them now banks real Tier-1 progress against the #598
gate and proves the fleet vehicle on disjoint, low-conflict work before Tier 2's heavier,
decision-dense lift.

Each finisher closes a specific, verified audit finding. The PII detector today flags **any**
13–19 digit run as a credit card (Domain 5) — a false-positive engine that would make the
ratified redact-at-egress posture (Decision 5) noisy and untrustworthy the moment it activates;
fixing the Luhn checksum now makes the detector honest before it is ever switched on. The
Policy Agent produces a "complete audit record" per decision and then **discards** it (Domain
7) — leaving no durable, tamper-evident answer to "what was authorized, when, and why," which
is both a forensic gap and, for the AIGP governance portfolio, a governance finding in its own
right. And the launcher **silently** forces dev-mode (no mTLS, throwaway keys) for every HOST
launch (Domain 1/2/6, "the worst default") — the LA named the consequence worse than the
security one: with dev-mode the silent default, **every "BlarAI works" report validated a
configuration that would never ship**. The interlock + loud opt-in makes the insecure posture
impossible to enter silently or accidentally while network-facing.

If we skip this sprint: Tier 1 stays incomplete (blocking #598); the audit-trail gap persists
(no reliable forensic record — an AIGP governance hole); the false-positive PII detector ships
as-is into the eventual egress path; and the silent-dev-mode trap that repeatedly produced
"works" reports against a never-ship posture stays unaddressed.

## 4. Success criteria

> **Verification standard (read first).** All three finishers are **deterministic and
> model-independent** — a pure-function Luhn check, a hash chain, and launcher/config logic.
> The binding automated gate is therefore **Layer-A tests with teeth** (lesson 30: every guard
> is reconstructed and proven to FAIL against the exact bug it guards), **not** real-model
> (Layer B) or real-UI (Layer C) tests — which would add **no signal** for code that never
> touches the model or the screen. Promising Layer-B/C here would repeat Sprint-12 SWAGR
> **MAJOR-1** in reverse (claiming a heavier method than the work needs). The **production
> posture** (`dev_mode=false`, real keys/certs) is the only thing that counts as "works" for
> the #598 gate (TEST_GOVERNANCE §2.5); for these items the production-posture live-verify is
> the **LA's per-tier step** and is named as such in each criterion below — this sprint does
> **not** claim it.

1. **PII credit-card detector is Luhn-correct.** `pgov.py`'s `CREDIT_CARD` detection fires only
   on digit strings that pass the **Luhn checksum**, in both the block path (`check_pii`) and
   the redact path (`find_pii_spans`); arbitrary 13–19-digit runs no longer false-positive.
   The shipped `pii_mode` value is **unchanged** (stays `off` per Decision 5 — accuracy fix
   only). *Verification: Layer-A teeth tests — Luhn-valid cards (incl. spaced/dashed) detected,
   non-Luhn strings not flagged, and a meta-test that fails against the old no-checksum
   behavior; full suite green.*
2. **Tamper-evident audit stream is live in code.** Every adjudication decision (ALLOW **and**
   DENY) produced by `HybridAdjudicator.adjudicate_car` is persisted to an **append-only,
   hash-chained** sink (each record bound to the prior, so altering/removing one breaks the
   chain), behind a **pluggable signer** (software-stub now; TPM-sealed later via the LA's
   ceremony). *Verification: Layer-A teeth tests — a clean chain verifies, a tampered field is
   detected, a removed/reordered record is detected, ALLOW+DENY both persist, sink-error is
   fail-closed/explicit; full suite green. (Real TPM signing + production-posture = LA ceremony,
   explicitly out of this sprint.)*
3. **dev-mode interlock + loud opt-in built (running-default NOT flipped).** A fail-closed
   guard **refuses** to run when `dev_mode` and `network_facing` are both true (deny-by-default;
   `network_facing` is a new config bool defaulting **False**), and dev-mode emits a prominent
   **INSECURE banner** on every boot instead of running silently. The running default is
   **deliberately not flipped** to `dev_mode=false` for HOST (no production certs exist —
   Domain 3 — so the flip is Tier-2-gated). *Verification: Layer-A teeth tests — interlock
   refuses `(dev_mode=True, network_facing=True)`, allows the two safe combinations (one with a
   loud warning), and the silent-collapse it prevents is reconstructed; `test_secure_defaults.py`
   stays green; full suite green. (Production-posture HOST boot at `dev_mode=false` = the LA's
   Tier-2 live-verify, not this sprint.)*
4. **The fleet vehicle is proven.** The three finishers were built by **parallel
   worktree-isolated builder subagents**; **no builder merged to `main`** and **no builder
   touched `BUILD_JOURNAL.md`**; the orchestrator reviewed each diff against its audit finding
   and merged only green branches; journal entries landed as **fragments** folded by the
   orchestrator. *Verification: branch topology + merge commits on `main`; `docs/journal_fragments/`
   shows orchestrator-folded entries; no builder commit on `main` predates orchestrator review.*
5. **Suite green + live baseline recorded.** The full Layer-A suite passes on a models-bearing
   tree at sprint end, the count is recorded in the SCR (superseding the stale 1501/1661
   snapshots), and the four Tier-1-finisher guard tests are additive-green. *Verification: pytest
   output in the SCR; delta vs. the kickoff baseline explained.*

## 5. Scope

### 5.1 In-scope

1. **EA-1 / #601 — PII Luhn fix** (`services/assistant_orchestrator/src/pgov.py` + its tests):
   a real Luhn validator gating `CREDIT_CARD` matches in both detection paths. Pure code.
2. **EA-2 / #602 — Tamper-evident audit stream** (a new append-only hash-chained sink + a
   pluggable software-stub signer, modeled on `shared/security/tpm_signer.py`, wired into
   `services/policy_agent/src/adjudicator.py`'s `adjudicate_car`): every decision persisted,
   tamper-detectable.
3. **EA-3 / #603 — dev-mode interlock + loud opt-in** (`launcher/__main__.py` + the relevant
   `shared` config surface): the fail-closed `network_facing ∧ dev_mode → refuse` guard, the
   loud dev-mode banner, and the explicit/centralized override resolution — **without** flipping
   the running default.
4. **Journal fragments** (`docs/journal_fragments/`, one per landed finisher) folded into
   `BUILD_JOURNAL.md` by the orchestrator at a quiet tree; **SCR**; a **ledger** entry; this
   **SDV**.

### 5.2 Out-of-scope (deliberately deferred)

1. **Measured-boot attestation** (the 4th Tier-1 audit item) — needs real on-chip attestation;
   ceremony-bound, deferred to a batched LA hardware step, not this no-ceremony wave.
2. **The TPM signing ceremony** for the audit stream (and the running-default `dev_mode=false`
   flip) — these are the LA's on-chip / production-posture steps by design; EA-2/EA-3 build to a
   software stub and the launcher stays HOST-functional today.
3. **All of Tier 2 / Tier 3** — the Cleaner (UC-003), at-rest encryption, VM/mTLS hybrid,
   dependency pinning, all-weights integrity (FUT-04 ceremony), the runtime raw-socket egress
   guard. Each is a later DEC-15 sprint, several decision-gated.
4. **Making PII block locally** — Decision 5 ratifies off-local / redact-at-egress; this sprint
   does not change `pii_mode` or wire the egress redaction (that activates with the network
   features).
5. **The non-security Sprint-12 carry-overs** — #594 (disambiguation clarification step), #595
   (retire `/external`), #583 (WinUI workspace UX) — product polish, not Tier-1 security; out of
   this sprint's theme.

### 5.3 Scope boundaries and edge cases

- **Disjoint working sets, enforced.** EA-1 touches the AO PGOV module; EA-2 the Policy Agent +
  a new `shared` sink; EA-3 the launcher + a `shared` config bool. The only possible overlap is
  the `shared` config surface (EA-2's signer config, EA-3's `network_facing` bool) — builders
  add **new** keys in **distinct** files/sections; the orchestrator resolves any config-file
  collision at merge. No builder edits another's primary module.
- **Real product bug → STOP and report.** If a builder's tests expose a pre-existing product bug
  (not its own scope), it stops and reports to the orchestrator rather than fixing it unreviewed
  (LA binding constraint).
- **No new runtime dependency.** The audit-stream hash chain and stub signer use the standard
  library (`hashlib`/`hmac`); no package install. Any temptation to add one → escalate first.
- **`network_facing` is inert today.** BlarAI is air-gapped, so the interlock never trips in the
  current run; it is built and tested as the control that becomes load-bearing when egress lands.
- **Adjacent-module edits minimal-and-only-if-required.**

## 6. Deliverable summary

| Deliverable | Type | Target location | Success criterion |
|---|---|---|---|
| Luhn-gated `CREDIT_CARD` detection + teeth tests | code + test | `services/assistant_orchestrator/src/pgov.py`, `…/tests/test_pgov.py` | #1 |
| Hash-chained append-only audit sink + pluggable stub signer | code + test | `shared/security/<audit_log>.py`, `shared/tests/…` | #2 |
| Audit-sink wiring into the adjudicator | code | `services/policy_agent/src/adjudicator.py` | #2 |
| dev-mode interlock + loud banner + `network_facing` config | code + test | `launcher/__main__.py`, `shared/<config>.py`, tests | #3 |
| Three journal fragments → folded into `BUILD_JOURNAL.md` | doc | `docs/journal_fragments/`, `BUILD_JOURNAL.md` | #4 |
| SCR + ledger entry | doc | `docs/sprints/sprint_13/`, `docs/ledger/` | #5 |

## 7. EA milestone plan

| EA-# | Working title | One-sentence purpose | Depends on | Approx size |
|---|---|---|---|---|
| EA-1 (#601) | PII Luhn fix | Gate `CREDIT_CARD` detection on a real Luhn checksum in both PGOV paths | main | S |
| EA-2 (#602) | Tamper-evident audit stream | Hash-chained append-only sink + stub signer, wired into `adjudicate_car` | main | M |
| EA-3 (#603) | dev-mode interlock + loud opt-in | Fail-closed `network_facing ∧ dev_mode` refuse + loud dev-mode, default not flipped | main | M |

**Concurrency:** all three are **PARALLEL** — disjoint working sets, and **none loads a real
model or drives the screen**, so the GPU/display/GUI singleton-serialization constraint does not
apply (unlike Sprint 12). They run as three simultaneous worktree-isolated builders; the
orchestrator serializes only the **merges**.

## 8. Dependencies and prerequisites

### 8.1 Upstream dependencies

- `main` @ `56703cd` (clean tree apart from the always-leave dirty files).
- The 8 ratified §6 decisions (esp. Decision 5 PII, Decision 8 dev-mode) and the audit findings.

### 8.2 External dependencies

- Vikunja running (tracking #604 + #601/#602/#603).
- A **software-stub TPM** suffices to build EA-2 (real on-chip signing is the deferred ceremony).
- Python 3.11 test environment; the models-bearing main working tree for the final suite run.

### 8.3 Assumed invariants

- The `pgov.py` PII-detection structure, the `adjudicator.py` `adjudicate_car` contract, and the
  launcher's deployment-mode resolution are stable for the sprint's duration.
- No concurrent sprint mutates these modules.

### 8.4 Parallel-Sprint Authorization & Shared-Artifact Audit

**N/A — serial kickoff (no other sprint active).** `docs/active_tasks.yaml` is empty at kickoff;
no parallel-sprint overlap audit is required. (Intra-sprint parallelism is across builder
*worktrees* within this one sprint, governed by §5.3's disjoint-working-set rule, not by §8.4's
cross-*sprint* authorization.)

## 9. Risks and unknowns

### 9.1 Known risks

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Audit-sink wiring adds latency to the PA hot path (`adjudicate_car` runs per authorization) | med | med | Keep persistence cheap (append + in-process hash); measure; if non-trivial, make the write non-blocking. No per-request full re-hash. |
| EA-3 mis-scoped → breaks Blair's daily HOST launch | low | high | Explicit boundary: HOST stays functional (resolves to dev, loudly + interlocked); a Layer-A test pins "today's HOST path still starts"; running-default flip is out-of-scope. |
| Parallel builders collide on the `shared` config surface | low | low | Distinct new keys in distinct files/sections; orchestrator resolves at merge (§5.3). |
| Over/under-claiming verification (the Sprint-12 MAJOR-1 trap) | low | med | §4 preamble fixes the standard to Layer-A-with-teeth + names production-posture as the LA's step; SWAGR audits it. |
| A finisher surfaces a real product bug mid-build | med | med | STOP-and-report contract; orchestrator triages (fix as a reviewed follow-up, not silently). |

### 9.2 Known unknowns

1. The exact record shape the audit sink should persist (which `AdjudicationContext` fields are
   forensically load-bearing vs. noise) — resolved by EA-2 reading the dataclass.
2. The best home for the `network_facing` config bool (a `shared` runtime-config field vs. a
   launcher-local flag) — resolved by EA-3 against the existing config resolution path.
3. Whether the audit stream warrants its own short ADR (a tamper-evident-log design record) —
   the orchestrator decides at review; if yes, it is authored with the merge (§10).

### 9.3 Unknown unknowns posture

These are small, deterministic, well-bounded changes against code the audit already mapped — the
risk surface is narrow. The likeliest miss is a subtle interface assumption (e.g., a PGOV detection
path the Luhn gate must also cover, or an adjudicator early-return that skips the sink) that the
teeth-tests don't think to reconstruct. The mitigation is the orchestrator's diff review against
the audit finding + the SWAGR's independent adversarial pass — the same net that caught Sprint 12's
silently-dropped scope.

## 10. Alignment to long-term roadmap

- **Project phase alignment**: Phase 5 Post-Operational Development; the air-gap-removal campaign
  (#597), Tier-1 finishers toward the #598 GO/NO-GO gate.
- **Use Case alignment**: UC-001 (Policy Agent — the audit stream and the dev-mode interlock both
  harden the authorization spine) and UC-004 (Assistant Orchestrator — the PII detector lives in
  the PGOV output path).
- **ADR alignment**: confirms ADR-020 (egress kill-switch — the interlock complements it),
  ADR-021/ADR-018 (TPM trust root — the audit-stream signer is the next consumer to be wired to
  it via the ceremony). A new short ADR for the tamper-evident audit log may be authored at EA-2
  merge if the design warrants a durable record (§9.2.3).
- **DEC alignment**: implements ratified **Decision 5** (PII accuracy-first) and **Decision 8**
  (dev-mode production-by-default + interlock); advances the §5 gate criteria "tamper-evident
  audit stream live" and "guest dev_mode interlock."

## 11. Roles and accountability

| Role | Responsibility this sprint | Budget |
|---|---|---|
| LA (Lead Architect) | SDV visibility read; the batched on-chip ceremonies + one production-posture live-verify per tier; #598 sign-off | \~10–15 min |
| Orchestrator (Co-Lead) | This SDV; dispatch + adversarial review + merge of the 3 builders; journal-fragment fold; SCR | Autonomous (LA-delegated) |
| Builder subagents (×3) | Execute EA-1/2/3 in isolated worktrees (model sonnet); Layer-A teeth tests; report journal text; never merge / never touch BUILD_JOURNAL | Autonomous, per dispatch |
| Sprint Auditor | Independent SWAGR after the SCR | Autonomous per DEC-15 |

## 12. Estimated effort

- Rough duration: **\~1 day fleet-time**, 3 parallel EA milestones + merge + journal fold + SCR.
- LA active-time expectation: **\~10–15 min** now (SDV visibility), plus a later **batched** hardware
  session (ceremonies + per-tier live-verify) shared across tiers.
- Confidence: **high** — deterministic, audit-mapped, well-bounded, disjoint working sets.

## 13. Deliberate non-goals

1. **Flip the running `dev_mode` default to `false` for HOST** — *rejected this sprint* because no
   production certs exist (Domain 3); the flip is Tier-2-cert-gated and needs an LA production-posture
   live-verify.
2. **Make PII block locally** — *rejected* per Decision 5 (off-local / redact-at-egress); this sprint
   fixes detector accuracy only.
3. **Perform the TPM signing ceremony / measured-boot attestation** — *rejected this wave*; on-chip,
   the LA's by design; EA-2 ships a software-stub signer.
4. **Author Layer-B (real-model) / Layer-C (real-UI) automated tests for these three items** —
   *rejected* because all three are deterministic and model/UI-independent; Layer-B/C would add no
   signal and would be the inverse of the Sprint-12 MAJOR-1 honesty miss.

## 14. Sign-off

### Lead Architect

> Approved via the **LA autonomy grant of 2026-06-05** ("Confirmed — proceed, autonomously, until
> the build work is done … Run /sprint-kickoff yourself … Post each sprint's SDV … for visibility,
> non-blocking"), which establishes standing sign-off authority for the ratified air-gap-removal
> campaign within the §6 decisions and the binding constraints in §2.3. This SDV is posted to the LA
> for visibility; it does not block the build. Durable signature: the `[sprint:kickoff]` commit on
> `main`.

### Co-Lead Architect (Orchestrator)

> The Orchestrator authored this SDV from the ratified campaign decisions and the 2026-06-03 audit,
> will dispatch the three finishers as parallel worktree-isolated builders, hold the merge gate, fold
> the journal fragments, and author the SCR. Any scope deviation surfaced during execution is flagged
> to the LA (one decision at a time, non-blocking to the other workstreams).

---

## Appendix A — SDV revision log

| Version | Date | Changed by | Change summary |
|---|---|---|---|
| 1 | 2026-06-05 | Orchestrator (LA-delegated authority) | Initial authoring + commit under the 2026-06-05 autonomy grant; posted to LA for visibility, non-blocking. Scope: the three no-ceremony Tier-1 finishers (#601/#602/#603) as a parallel fleet wave; verification fixed to Layer-A-with-teeth per Sprint-12 SWAGR MAJOR-1; production-posture live-verify named as the LA's per-tier step. |
