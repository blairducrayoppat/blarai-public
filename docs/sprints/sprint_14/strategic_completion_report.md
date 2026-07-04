---
sprint_id: 14
sprint_name: "Tier-2 at-rest encryption + audit-stream TPM signing"
predecessor_sprint_id: 13
vikunja_tracking_task_id: 609
start_date: "2026-06-05"
sprint_completed: "2026-06-05"
sdv_path: "docs/sprints/sprint_14/strategic_design_vision.md"
sdv_version_at_completion: 3
orchestrator_authored_on: "2026-06-05"
main_tip_at_completion: "e9c7c26"
test_baseline_at_kickoff: "1883 passed, 0 failed (Layer-A, -m 'not hardware and not winui and not slow')"
test_baseline_at_completion: "2055 passed, 0 failed, 15 deselected (same selection)"
total_ea_milestones: 8
scr_version: 1
---

# Strategic Completion Report — Sprint 14: Tier-2 at-rest encryption + audit-stream TPM signing

## 1. Executive summary

Sprint 14 opened **Tier 2** of the air-gap-removal campaign: it encrypts the two SQLite stores that
hold the user's data — `substrate.db` (knowledge store) and `sessions.db` (conversation history) — **at
rest**, and lands the machinery for a TPM-signed audit stream. Encryption is app-layer **AES-256-GCM**
under a **TPM-sealed Data-Encryption Key (DEK)** dual-wrapped with an **offline recovery key** (ADR-025;
no new dependency — `cryptography` was already present). Executed as a per-tier DEC-15 fleet wave: eight
worktree-isolated builder subagents (model sonnet), the Orchestrator holding the merge gate; builders
never merged to `main` and never touched `BUILD_JOURNAL.md`.

Full Layer-A suite on the integrated tree: **2055 passed, 0 failed** (1883 kickoff → 2055; ~+172 from
the sprint's own tests, zero regressions across the whole arc).

**This is the first piece of the campaign that is real on the user's hardware.** Unlike Sprint 13
(everything deferred to a future LA ceremony), the LA ran the **batched on-chip ceremony** and the
**production-posture live-verify** during this sprint: the three keys were provisioned on the real TPM
(`BlarAI-DEKSeal` RSA seal key, `BlarAI-Audit-Signing-Key-v1` ECDSA audit key, the offline recovery
key), `BLARAI_DEK_KEYSTORE` was set, and BlarAI booted on the production encrypted path. The live-verify
**confirmed ciphertext at rest** (a raw-column check: 0 plaintext across `turns.content`,
`sessions.title`, `substrate_chunks.text/.source/.embedding` on the fresh databases), with the app fully
functional through it (history, assistant, the time tool, vision on a never-seen image). The at-rest
encryption #598 criterion — *encryption on, with a tested recovery path* — is **MET in production
posture**, not against a mock.

The eight EAs:
- **EA-1 TPM key-sealing primitive** (`shared/security/tpm_sealer.py`) — RSA-2048 OAEP-SHA256 seal/unseal + `SoftwareSealer` stub. Merge `fe9cc6f`.
- **EA-2 cipher + DEK envelope** (`field_cipher.py`, `dek_envelope.py`) — AES-256-GCM fresh-CSPRNG-nonce; HKDF-split `k_enc`/`k_idx`; AAD; ONE DEK dual-wrapped; production factory refuses `SoftwareSealer`. Merge `18bafe7`.
- **EA-3 substrate.db encryption** — text + embedding + filename; keyed-hash dedup; embedding boot-cache; idempotent migration + VACUUM; perf deltas. Merge `9807237`.
- **EA-4 sessions.db encryption** — `turns.content` + `sessions.title`; decrypt-on-read; WAL-safe. **Two rounds** (§6). Merge `1d218c2`.
- **EA-5 / #605 audit TPM signer** — `TpmRecordSigner` + dedicated key (separation of duties) + MINOR-3 contrast test. Merge `274afe3`.
- **EA-5b audit refuse-to-start** (key/TPM unavailable in prod). Merge `8fa8384`.
- **EA-5c audit-path refuse-to-start** (`audit_log_path=None` in prod; LA ruling). Merge `52b3374`.
- **EA-6 ceremony tooling + recovery hardening** (`provision_dek_keystore.py`, one-command 3-key ceremony + `--recover`). **Two rounds** (§6). Merge `6017e5c`.

**The defining moments were both at the merge gate.** Twice, a builder returned a fully green suite that
hid a real defect, and reading the diff against the criterion — not the test output — caught it
(§6). This is the Sprint-13 lesson (46) holding under repetition.

**Verification posture (honest):** the deterministic crypto is gated by Layer-A tests with teeth (2055
green). The at-rest **encryption** is additionally **live-verified in production posture** by the LA
(above). The audit stream's **TPM-signing and the JWT key are code-complete and the keys are
provisioned, but activate only at the dev-mode-off flip** — which is gated on the later Tier-2
VM/mTLS build and is **not** claimed live here (the current boot runs dev-mode, so the audit log is
hash-chained but dev-stub-signed). This split is by design: encryption is env-gated (`BLARAI_DEK_KEYSTORE`),
the PA signing keys are `dev_mode`-gated.

## 2. Context at completion

### 2.1 Repo state
- **BlarAI main HEAD**: `e9c7c26` (ceremony runbook). The SCR, trust-anchor recording, and Vikunja close land on top.
- **Test baseline**: kickoff `1883 passed`; completion **`2055 passed, 0 failed, 15 deselected`** (`pytest shared/ services/ launcher/ -m "not hardware and not winui and not slow"`, venv py3.11 where `cryptography` is present). Arc: 1883 → 1920 (EA-1+5) → 1947 (EA-2+5b) → 1981 (EA-3) → 2023 (EA-4) → 2025 (EA-5c) → 2055 (EA-6).
- **Open Vikunja `Gate:Pending-Human`** carried forward: 0.
- **Branches**: all eight feat branches merged `--no-ff`; kept (no destructive git). A `wip/s14-ea4-staged-reversal-artifact` branch preserves a recovered git artifact (§6); leftover `.claude/worktrees/agent-*` are removable.

### 2.2 Key commits
| Commit | Increment | Notes |
|---|---|---|
| `9d33687` | Sprint 14 SDV (signed) | v3 after premise correction |
| `fe9cc6f` | EA-1 TPM sealer | RSA-2048 OAEP |
| `274afe3` | EA-5 audit TPM signer (#605) | dedicated key + contrast test |
| `804a0ef` | **ADR-025 ACCEPTED** + premise correction + roadmap §8 (#611) | live-memory deferred-not-denied |
| `18bafe7` | EA-2 cipher + DEK envelope | prod refuses SoftwareSealer |
| `8fa8384` | EA-5b audit refuse-to-start | — |
| `f087b57` | roadmap §9 (#612 capstone presentation) | — |
| `9807237` | EA-3 substrate.db | 2 rounds: see §6 (EA-4 was the recurrence; EA-3 clean) |
| `1d218c2` | EA-4 sessions.db (2 rounds) | round-1 wiring gap caught |
| `4e58a8b` | roadmap Cleaner deferral (#613) | cherry-picked during git recovery (§6) |
| `52b3374` | EA-5c audit-path refuse-to-start | — |
| `6017e5c` | EA-6 ceremony tooling + recovery hardening (2 rounds) | round-1 recovery-by-accident caught |
| `e9c7c26` | ceremony runbook | non-developer 3-key ceremony |

### 2.3 Premise correction (load-bearing)
The SDV/ADR/roadmap initially asserted "decades of private data already on disk" as the urgency. The LA
**verified on disk** that the stores held only disposable dev/test scaffolding (~107 chunks, ~59
sessions / 376 turns). ADR-025 §1/§3 + SDV v3 §1/§3 were corrected: the value is **born-encrypted before
first real use** + meeting the #598 criterion; the sprint is **well-timed, not urgent**. Captured as a
journal lesson (verify a load-bearing premise on disk, don't inherit it through the review chain).

## 3. SDV success-criteria disposition

| # | Criterion (SDV §4) | Verdict | Evidence |
|---|---|---|---|
| 1 | `substrate.db` sensitive data ciphertext at rest; retrieval unchanged; dedup intact | **MET** | EA-3 raw-read/retrieval-equivalence/re-ingest-dedup tests; **live-verified** (0 plaintext on the production DB) |
| 2 | `sessions.db` conversation content ciphertext at rest | **MET** | EA-4 raw-read + round-trip + WAL-sidecar tests; **live-verified** (0 plaintext) |
| 3 | DEK envelope correct + fail-closed; nonces unique | **MET** | EA-2 dual-unwrap / fresh-nonce / AAD / prod-refuses-SoftwareSealer tests (55) |
| 4 | Audit stream TPM-signed (integrity-only) via dedicated key (#605) | **MET (code); live activation deferred to dev-mode flip** | EA-5/5b/5c: `TpmRecordSigner` wired at `_build_audit_log`, dedicated key, contrast test, refuse-to-start (key+path). Audit key provisioned at the ceremony; the PA uses it only when `dev_mode=False` (later-tier flip) — current boot is dev-mode (hash-chained, stub-signed) |
| 5 | Encryption overhead measured as a DELTA, both costs separately | **MET** | EA-3: +0.124 ms/query median, 1.45 ms one-time boot-cache (107 emb) → PERFORMANCE_LOG + `docs/performance/benchmark_2026-06-06_02-15-23.json`; EA-4 session read-path addendum |
| 6 | Key-recovery path tested AND non-developer-usable | **MET** | EA-6 `provision_dek_keystore.py` (one command) + `--recover` + dead-chip SUCCESS test (recovery via `unseal_via_recovery`, TPM provably dead); runbook `docs/runbooks/at_rest_encryption_ceremony.md`; **the LA ran the real ceremony successfully** |
| 7 | Software-stub-verified; suite green; baseline recorded; production-posture is the LA's step | **MET — and exceeded** | 2055 green; baseline 1883→2055 recorded. The production-posture live-verify (named in the SDV as the LA's step) was **performed and passed this sprint** for the encryption |

**7 of 7 criteria MET.** Criterion #7 was *exceeded* (the production-posture live-verify was actually
performed, not merely deferred). One scope boundary on #4 (audit TPM-signing activates at the later
dev-mode flip) is honestly named, not a gap. The independent SWAGR follows this record.

## 4. Live verification (production posture) — PERFORMED for encryption; partial for the PA signing keys

The LA ran the batched on-chip ceremony and the production-posture live-verify this sprint:
- **Ceremony:** `python -m shared.security.provision_dek_keystore` provisioned `BlarAI-DEKSeal` (RSA seal), `BlarAI-Audit-Signing-Key-v1` (ECDSA audit), created the dual-wrapped DEK keystore, and surfaced the **offline recovery key** (the LA stored it off-box; confirmed). `BLARAI_DEK_KEYSTORE` set persistently.
- **Live-verify (encryption) — PASS:** the production boot used the encrypted stores (logs: `EncryptedSubstrateStore`/`EncryptedSessionStore`, "ready (encrypted)"); a raw-column check showed **0 plaintext** across all sensitive columns on the fresh DBs; the app worked end-to-end (history, assistant, time tool, vision). The live-verify **caught** that the pre-existing dev data was still plaintext at rest (the encrypted stores read legacy plaintext rows as-is); per the LA's decision the disposable dev DBs were **wiped** (the real keystore retained), and a re-verify confirmed the fresh DBs are 0-plaintext, born-encrypted. This is exactly why "only the production posture counts as works."
- **Deferred to the dev-mode-off flip (later Tier-2 VM/mTLS, not this sprint):** the audit stream's live TPM-signing and the PA JWT key. The keys are provisioned; the PA uses them only when `dev_mode=False`. The current boot runs dev-mode (expected at this stage per roadmap §6 Decision 8).

**Trust anchor (ADR-025 §5):** the key fingerprints are recorded into ADR-025 §5 + a `docs/ledger/`
entry as part of this close (no secrets; public-key SHA-256 + names + date).

## 5. Carry-overs

| Carry-over | Tier / owner | Note |
|---|---|---|
| Audit TPM-signing + JWT key **live** + dev-mode-off running-default flip | Tier-2 (VM/mTLS) + LA live-verify | Keys provisioned; activate when `dev_mode=False`. Gated on per-boot cert/mTLS. |
| Audit-stream retention/rotation | #607 | Deferred operational hardening. |
| Audit-stream tail-deletion attestation | #606 | TPM-sealed counter; deferred. |
| Live-memory attacker (DEK + decrypted fields in RAM) | #611 (roadmap §8) | Deferred-not-denied; Intel Key Locker + minimized key residency when network-facing (#556). |
| The Cleaner (UC-003) | #613 | **DEFERRED from the #598 gate** to a post-gate fast-follow (LA 2026-06-05); roadmap §2/§4/§5/§6 amended. |
| Capstone post-hardening security presentation | #612 | At/after #598. |
| Embedded-PAN PII recall | #608 | Activates with redact-at-egress. |

## 6. Process notes

- **The merge gate earned its existence — twice.**
  - **EA-4 round 1** built a correct `EncryptedSessionStore` (40 green tests) but wired `build_session_store` into nothing — the live launcher (`launcher/__main__.py:742`) still constructed the **plaintext** `SessionStore`, so production sessions would have shipped plaintext despite the green suite. The Sprint-13 "built but wired into nothing" trap, recurring. The construction site lived in a *different package* (`launcher/`) than the store (`ui_gateway/`), defeating a service-scoped grep, and the regression lock only tested the factory in isolation. Round 2 wired the launcher + `--no-model` real-DB path and added a lock that runs the real Step-5 and asserts the store is encrypted. (Lesson: grep the *whole repo* for construction sites; lock the real entry point.)
  - **EA-6 round 1** built a working recovery path that reached the recovery key only *by accident* — it loaded the keystore with a `SoftwareSealer` placeholder and relied on `unseal_dek`'s catch-order + the stub raising a specifically-caught exception, and imported a private `_recovery_wrap`; the recovery-SUCCESS path was untested (SoftwareSealer on both ends masked it). Round 2 added public `unseal_via_recovery` (recovery-only) + `reseal_dek` to `dek_envelope.py`, rewrote `recover()` to use them, and added a dead-chip SUCCESS test (a `DeadSealer` makes the TPM path provably dead, so the DEK can only come from the recovery wrap). A break-glass path must be correct-by-design + dead-chip-tested, not working-by-accident.
- **The live-verify caught a real at-rest gap.** The functional smoke test (app works) passed, but the raw-column verification caught that the legacy data was still plaintext — corrected by the wipe. "Works" is the production posture measured at the bytes, not the UI.
- **A worktree-cwd quirk recurred, worse, and was recovered non-destructively.** Launching the background worktree builders switched the **main checkout itself** onto a feature branch, so an Orchestrator commit (the Cleaner-deferral roadmap edit) landed on that branch, not `main`, and the index held a staged reversal artifact. Recovery (LA-directed: preserve, don't discard): the artifact was committed to `wip/s14-ea4-staged-reversal-artifact`, the main checkout switched back to `main`, and the deferral cherry-picked (`4e58a8b`). New guard: verify `git branch --show-current == main` (not just the path) before every main-tree commit — applied on every subsequent commit.
- **Premise verified on disk** (§2.3) — the urgency claim was false; corrected before it propagated further.
- **Builder fragment deviation** (recurring MINOR): EA-6 wrote its journal fragment as a file rather than reporting text. Harmless (different filename, no `BUILD_JOURNAL.md` collision); owned + expanded at the fold.

## 7. Disposition

**COMPLETE — and live-verified (encryption).** All eight EAs are built, tested (2055 green on
integrated `main`), and merged under the merge gate; SDV criteria 7/7 MET. Uniquely for this campaign,
the **production-posture live-verify for the at-rest encryption was performed and passed** this sprint
(ceremony run, ciphertext-at-rest confirmed, recovery key stored, dev data wiped + re-verified clean).
The audit TPM-signing + JWT live activation remain gated on the later Tier-2 dev-mode-off flip and are
honestly named, not claimed. The air-gap stays up; #598 remains the GO/NO-GO. The independent Sprint
Auditor's SWAGR follows this record.

## 8. Post-SWAGR reconciliation

The independent Auditor's SWAGR returned **PASS (CONCERNS) — 7/7 criteria MET, 0 CRITICAL, 0 MAJOR,
4 MINOR**. All four MINOR findings are now dispositioned and closed:

- **MINOR-1 — trust anchor not recorded.** ADR-025 §5 filled post-ceremony with public fingerprints
  (DEK keystore SHA-256 `23a7454866e23ffc7c3daebad9f25db86e40266f63126fa354e254215e0b7448`; audit-key
  SPKI SHA-256 `d0b25ce119b2533b6948301ca4d3ce79843c527960abf8865ffa55e16bd5a5d6`); SCR §4 softened to
  match. Commit `54572a1`. Public fingerprints only — no secret material recorded.
- **MINOR-2 — no ledger close entry.** `docs/ledger/20260606_010000_sprint14_scr_at-rest-encryption.md`
  written. Commit `526f9e9`.
- **MINOR-3 — store factories fail-open to SoftwareSealer on a missing keystore.** EA-7: production now
  refuses to start (session store) / degrades loudly (substrate) when `BLARAI_DEK_KEYSTORE` is absent;
  the weak SoftwareSealer posture is an explicit `dev_mode=True` opt-in. Merged `6e6a0c6`.
- **MINOR-4 — the test suite could write to the real `%LOCALAPPDATA%`.** Confirmed real — it had
  corrupted the operator's live `sessions.db` mid-sprint (`[7199c5ab]` refuse-to-start). Fixed in two
  layers: EA-8 package-level autouse fixtures (`dabb712`) + EA-9 a root `conftest.py` redirecting the
  user-data env vars at module load, before the import-time `SESSION_DB_PATH` constant resolves
  (`e08a7db`), with a regression lock. The real user-data dir is now untouched by the suite by default,
  verified byte-for-byte before/after. Recorded as TEST_GOVERNANCE §2.6.

Two further close artifacts followed the audit: the **journal fold** (8 new top-of-file lessons 48–55 +
9 dated entries; commit `4b99bf5`) and a **doctrine codification** the LA requested — *Proactive
Defect-Fixing* added to `CLAUDE.md` + `.github/copilot-instructions.md` (`f7723ca`), capturing the
fix-what's-found behavior the gate exercised on MINOR-3/MINOR-4 while preserving the
escalate-genuine-decisions boundary.

Final disposition stands **COMPLETE — live-verified (encryption)**. Audit-TPM-signing + JWT live
activation remain honestly gated on the later dev-mode-off flip (Tier-2 VM/mTLS). The air-gap stays up;
#598 remains the GO/NO-GO.
