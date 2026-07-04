---
sprint_id: 13
sprint_name: "Tier-1 security finishers"
predecessor_sprint_id: 12
vikunja_tracking_task_id: 604
start_date: "2026-06-05"
sprint_completed: "2026-06-05"
sdv_path: "docs/sprints/sprint_13/strategic_design_vision.md"
sdv_version_at_completion: 1
orchestrator_authored_on: "2026-06-05"
main_tip_at_completion: "aa41a0e"
test_baseline_at_kickoff: "1797 passed, 0 failed (Layer-A, -m 'not hardware and not winui and not slow')"
test_baseline_at_completion: "1883 passed, 0 failed, 98 deselected (same selection)"
total_ea_milestones: 3
scr_version: 1
---

# Strategic Completion Report — Sprint 13: Tier-1 security finishers

## 1. Executive summary

Sprint 13 shipped the **three no-ceremony Tier-1 security finishers** of the air-gap-removal
campaign, executed as the campaign's **first fleet wave**: three disjoint builder subagents in
parallel worktrees (model sonnet), with the Orchestrator holding the merge gate. Each finisher
closes a specific, verified finding from the 2026-06-03 audit, and each landed on `main` under a
recorded merge-gate review verdict. Full Layer-A suite on the integrated tree: **1883 passed, 0
failed** (up from the 1797 kickoff baseline; ~+86 from the finishers' own tests, zero regressions).

The three:
- **EA-1 / #601 — PII credit-card Luhn fix** (audit Domain 5). The `CREDIT_CARD` detector claimed
  "Luhn-plausible" in a comment but ran no checksum; it now gates on a real mod-10 checksum in both
  detection paths (`check_pii` → `find_pii_spans`). `pii_mode` unchanged (`off`, DEC-05) — accuracy
  fix only. Merge `d910739`.
- **EA-3 / #603 — dev-mode interlock + loud opt-in** (audit Domain 1/2/6, Decision 8). A fail-closed
  interlock refuses `dev_mode ∧ network_facing`; dev-mode now emits a loud INSECURE banner instead of
  the silent default. The running-default flip to `dev_mode=false` was **deliberately not made** (no
  production certs exist — Tier-2-gated); HOST still resolves to dev-mode, loudly and behind the
  interlock. Merge `ea879ed`.
- **EA-2 / #602 — tamper-evident audit stream** (audit Domain 7). A hash-chained, append-only sink
  persisting every Policy-Agent decision, behind a pluggable signer (HMAC stub now, TPM swap is the
  LA ceremony). Merge `a8284d1`, **two rounds** — see §6.

**The defining moment was the merge gate, not the build.** EA-2's first round built a correct,
38-test-green tamper-evident sink and dependency-injected it into the adjudicator — but the
*production* Policy Agent factory constructed the adjudicator without passing the sink, so the live
PA would have persisted **zero** records: the 2026-06-03 audit's own "built but wired into nothing"
anti-pattern recurring inside the sprint built to close it. A fully green suite hid it. Reading the
production construction site caught it; the send-back activated the sink and added a regression test
locking `has_audit_log == True` at the boot factory. This is BUILD_JOURNAL lesson 46.

**Verification posture (honest, per Sprint-12 SWAGR MAJOR-1):** all three finishers are deterministic
and model/UI-independent, so the binding automated gate is **Layer-A tests with teeth** — and that is
exactly what was promised in the SDV §4 and delivered. No Layer-B/Layer-C was promised or needed. The
**production-posture live-verify** (`dev_mode=false`, real keys/certs) is the LA's per-tier step
(TEST_GOVERNANCE §2.5) and is **not** claimed complete here.

## 2. Context at completion

### 2.1 Repo state

- **BlarAI main HEAD**: `aa41a0e` (`docs(journal): fold Sprint 13 Tier-1-finishers arc … (lessons 46-47)`).
- **Test baseline**: kickoff `1797 passed`; completion **`1883 passed, 0 failed, 98 deselected`**
  (`pytest shared services launcher tests/integration tests/harness -m "not hardware and not winui and not slow"`).
  `test_launcher.py` is 19/19 on the models-bearing tree including `test_production_happy_path` —
  confirming EA-3's `#588` note (that failure is model-less-worktree-only) and zero launcher regression.
- **Open Vikunja `Gate:Pending-Human`** carried into the next sprint: 0.
- **Branches**: `feat/s13-pii-luhn` (`41cd757`), `feat/s13-devmode-interlock` (`27612b4`),
  `feat/s13-audit-stream` (`17adf05`→`42b3e56`) all merged to `main` (`--no-ff`). Branches kept
  (no destructive git); their leftover worktrees under `.claude/worktrees/agent-*` are removable.

### 2.2 Increment commits

| Commit | Increment | Ticket | Notes |
|---|---|---|---|
| `bf91e2e` | Sprint 13 SDV (LA-delegated authority) | #604 | — |
| `cd4c945` | ACTIVE_SPRINT pointer → Sprint 13 | — | — |
| `41cd757` → merge `d910739` | **EA-1** PII Luhn fix | #601 | 107 pgov tests; teeth meta-test |
| `27612b4` → merge `ea879ed` | **EA-3** dev-mode interlock + loud opt-in | #603 | 22 tests; running-default NOT flipped |
| `17adf05` → `42b3e56` → merge `a8284d1` | **EA-2** tamper-evident audit stream | #602 | 2 rounds (merge-gate catch); 41 tests |
| `aa41a0e` | Journal fold (lessons 46-47) | — | fragment folded + deleted |

### 2.3 Antecedent

- `d3e5af7` `[sprint:13][#593]` (DANGEROUS fail-closed) — a pre-kickoff commit provisionally tagged
  `sprint:13`, folded in as a Tier-0/SWAGR-closure antecedent of this sprint (closed Sprint-12 SWAGR
  MAJOR-2). Not separate work.

## 3. SDV success-criteria disposition

| # | Criterion (SDV §4) | Verdict | Evidence |
|---|---|---|---|
| 1 | PII credit-card detector is Luhn-correct (both paths; `pii_mode` unchanged) | **MET** | `pgov.py` Luhn gate in `find_pii_spans` (covers `check_pii`); 107 tests incl. order-number teeth meta-test; `pii_mode` untouched |
| 2 | Tamper-evident audit stream live in code (every decision persisted; pluggable signer) | **MET** | Sink wired into all 3 `adjudicate_car` returns AND activated at the production factory (`_build_adjudicator`); `has_audit_log` True regression test; 41 tests. *Real non-forgeability awaits the TPM signer ceremony (stub signer ships)* |
| 3 | dev-mode interlock + loud opt-in built (running-default NOT flipped) | **MET** | Interlock fires before service construction; loud banner; HOST still dev-mode (flip deferred — boundary honored); 22 tests incl. silent-collapse teeth; `test_secure_defaults` green |
| 4 | Fleet vehicle proven (parallel builders, orchestrator-only merges, fragments) | **MET (1 minor deviation)** | 3 parallel worktree builders; all merges orchestrator-only `--no-ff`; no builder touched `main`. *Deviation: EA-2 wrote its journal fragment as a file rather than reporting text — harmless (didn't touch `BUILD_JOURNAL.md`); reconciled at the fold* |
| 5 | Suite green + live baseline recorded | **MET** | 1883 passed / 0 failed on integrated `main`; baseline 1797→1883 recorded here |

**5 of 5 criteria MET.** No CRITICAL/MAJOR self-identified gaps; one MINOR process deviation (criterion
#4). The Sprint Auditor's independent SWAGR follows this record.

## 4. Live verification (production posture) — DEFERRED to the LA

Per Decision 8 / TEST_GOVERNANCE §2.5, the production-posture live-verify (`dev_mode=false`, real
keys/certs, real boot) is the LA's per-tier acceptance step and is **not** claimed here. For Tier-1,
the batched LA steps are:
- **The TPM signing ceremony** for the audit stream (swap `HmacSha256Signer` → a TPM-sealed signer,
  mirroring `_build_jwt_minter`), which upgrades the audit log from tamper-*evident* (chain) to
  tamper-*evident + non-forgeable* (chip-bound signature).
- **One production-posture live-verify** confirming the live PA writes a verifying audit chain and the
  dev-mode banner/interlock behave on the real boot.

These are batched with the other Tier-2 ceremonies (encryption key + offline recovery key + mTLS
certs) so the LA runs one consolidated on-chip session, not one-offs.

## 5. Carry-overs

| Carry-over | Tier / owner | Note |
|---|---|---|
| TPM signer swap for the audit stream | Tier-2 ceremony (LA) | Stub `HmacSha256Signer` → TPM-sealed signer; drop-in at `_build_audit_log`. New ticket recommended. |
| dev-mode running-default flip (`dev_mode=false` for HOST) | Tier-2 (cert-gated) + LA live-verify | Blocked on per-boot cert provisioning (audit Domain 3); the interlock already guards the transition. |
| Audit-stream retention/rotation | Sprint 14 operational hardening | `on_rotate` hook is a stub; no cap enforced (append-only/unbounded default by design). |
| Audit-stream **tail-deletion** limitation | follow-up | The hash chain detects middle tamper/removal/reorder but NOT truncation of the newest records; counter is an external record-count attestation / WAL. Documented in the module; recommend a tracked ticket. |
| Measured-boot attestation (4th Tier-1 item) | ceremony-bound | Deferred from this no-ceremony wave; needs on-chip attestation + LA live-verify. |

## 6. Process notes

- **The merge gate earned its existence.** EA-2's built-but-inert sink (round 1) passed a full green
  suite and was one un-passed argument (`audit_log=`) away from silently shipping a tamper-evident
  audit log that recorded nothing. A diff review against the audit finding — not the test output —
  caught it. Round 2 activated it + added the `has_audit_log` regression lock. (Lesson 46.)
- **A git-topology quirk, diagnosed without data loss.** Launching the background worktree-agents moved
  the Orchestrator shell's cwd *into* the first agent's worktree, so an initial `git merge` ran as a
  no-op there. Diagnosed via `git worktree list` + `rev-parse --show-toplevel`; all branches/commits
  were healthy (`main` never moved); merges re-run via `git -C <main-worktree>`. No history touched.
- **Verification honesty held.** Unlike Sprint-12 (SWAGR MAJOR-1, where a heavier verification method
  was promised and not delivered), Sprint 13 promised exactly the Layer-A-with-teeth coverage these
  deterministic items warrant, and delivered it; production-posture is named as the LA's step, not
  claimed.
- **Builder fragment deviation** (criterion #4): EA-2 wrote a journal fragment file instead of reporting
  text. Harmless; folded + deleted. Future dispatches reiterate "report text, don't write the file."

## 7. Disposition

**COMPLETE (build scope).** The three Tier-1 finishers are built, tested (1883 green on integrated
`main`), and merged under the merge gate; SDV criteria 5/5 MET. The **production-posture live-verify**
and the **TPM signing ceremony** are the LA's batched Tier-2 steps and are explicitly deferred (§4).
The air-gap stays up; #598 remains the go/no-go. The Sprint Auditor's independent SWAGR follows.

## 8. Post-SWAGR reconciliation (2026-06-05)

The independent Sprint Auditor's SWAGR
(`docs/sprints/sprint_13/Strategic_Work_Analysis_and_Gap_Report_Sprint_13_20260605_205834.md`)
returned **PASS — 5 MET / 0 PARTIAL / 0 FAIL, 0 CRITICAL, 0 MAJOR, 4 MINOR**. It independently
reproduced `1883 passed, 0 failed` and verified every load-bearing claim against git/tests, not
prose — confirming (against commit history) that EA-2 round 1 was genuinely built-but-inert and
round 2 (`42b3e56`) wired + regression-locked the live sink, that `verify()` has real
tamper/removal/reorder/forgery teeth, and that the dev-mode running-default was **not** flipped. No
CRITICAL/MAJOR; no SDV amendment required; the verification-method honesty claim (deterministic work
→ Layer-A-with-teeth, production posture named as the LA's step) is upheld — "the honest inverse of
Sprint 12."

The 4 MINORs and their dispositions:
- **MINOR-1** — pre-existing CREDIT_CARD false-negative (a valid PAN embedded in a >19-digit run is
  not caught — the dual of the false-positive #601 closed; off-path since `pii_mode='off'`):
  **ticketed #608** for detector completeness when redact-at-egress activates. Not introduced by
  this sprint, not in scope for the accuracy fix.
- **MINOR-2** — EA-2's "41 tests" is an un-itemised aggregate: itemised here as **38** in
  `shared/tests/test_audit_log.py` + **3** in `services/policy_agent/tests/test_entrypoint.py`. No
  action.
- **MINOR-3** — the HMAC stub's forgeability is disclosed in prose, not encoded as an assertion:
  inherent to the stub and resolved by the TPM swap (**#605**); disclosure is in the module docstring
  + lesson 46. Folded into #605's acceptance; no source change.
- **MINOR-4** — SCR §5 said "recommend a ticket" while the carry-over tickets **#605/#606/#607** were
  already filed (the favorable direction): corrected — they exist and are open.

**Disposition unchanged: COMPLETE (build scope), PASS.** The production-posture live-verify + the TPM
signer ceremony remain the LA's batched Tier-2 steps; #598 remains the go/no-go.
