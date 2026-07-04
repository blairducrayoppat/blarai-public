---
sprint_id: 14
sprint_name: "Tier-2 at-rest encryption + audit-stream TPM signing"
document_type: SWAGR
auditor: "Independent Sprint Auditor (Claude Opus 4.8, 1M context)"
audit_date: "2026-06-05"
main_tip_at_audit: "230bb8b"
scr_under_audit: "docs/sprints/sprint_14/strategic_completion_report.md (v1)"
sdv_under_audit: "docs/sprints/sprint_14/strategic_design_vision.md (v3)"
overall_verdict: "PASS (CONCERNS)"
criteria_summary: "7/7 MET, 0 CRITICAL, 0 MAJOR, 4 MINOR"
test_baseline_reproduced: "2055 passed, 15 deselected, 0 failed (82.38s)"
---

# Strategic Work Analysis & Gap Report — Sprint 14 (Independent Auditor)

**Adversarial, independent, read-only.** Every load-bearing claim below was verified against git
history, the actual source, the live production databases on disk, and an independently-reproduced
test run — *not* against the SCR's prose. Findings are cited with commit SHAs, `file:line`, and test
names.

---

## 0. Overall verdict

**PASS (with CONCERNS).** 7 of 7 SDV §4 criteria are independently judged **MET**. **Zero CRITICAL,
zero MAJOR** findings. The cryptographic core is real, correct against ADR-025, fail-closed, and —
uniquely for this campaign — **live-verified in genuine production posture on the real TPM**: I
independently re-ran the raw-column check on the live `%LOCALAPPDATA%\BlarAI\` databases and confirmed
**0 plaintext** across every sensitive column, and I independently confirmed the production
`dek_keystore.json` is sealed by a **real RSA-2048 TPM key** (it refuses to unseal under the
`SoftwareSealer`). The Sprint-13 "built but wired into nothing" trap did **not** recur: the round-1
EA-4 wiring gap was genuinely caught at the merge gate and the round-2 regression lock exercises the
*real* launcher entry point, not the factory in isolation.

The CONCERNS are **four MINOR findings**, none of which compromises the at-rest confidentiality of the
real production data:
- **MINOR-1** — the SCR overclaims that the ADR-025 §5 trust anchor was *recorded*; it is still a
  placeholder on disk.
- **MINOR-2** — no `docs/ledger/` close entry exists yet (the SCR §4 claims one "as part of this
  close").
- **MINOR-3** — a fail-open *design* seam in the store factories: a missing `BLARAI_DEK_KEYSTORE`
  env var silently selects the public `SoftwareSealer` (`dev_mode=True`) instead of refusing; an
  orphan `substrate.keystore.json` in the production data dir is the visible symptom (the SDV/SCR live
  posture is unaffected, but the *factory* is not fail-closed against this misconfiguration).
- **MINOR-4** — a stray dev/test keystore (`substrate.keystore.json`) sits in the production
  `%LOCALAPPDATA%\BlarAI\` directory; criterion-6's "dev keystore wiped" expectation is not met
  (cosmetic / operator-hygiene; no confidentiality impact — proven below).

A clean pass is only valuable if it is earned. This one is earned on the security substance; the
MINORs are honesty-of-record and operational-hygiene items the Orchestrator should service before the
final close, not security defects.

---

## 1. Independently-reproduced test baseline

Command (exactly as specified, venv py3.11 where `cryptography` is present):

```
C:/Users/mrbla/blarai/.venv/Scripts/python.exe -m pytest shared/ services/ launcher/ \
    -m "not hardware and not winui and not slow" -q
```

**Result: `2055 passed, 15 deselected, 2 warnings in 82.38s` — exit code 0, 0 failed.**

This matches the SCR's claim (`2055 passed / 0 failed / 15 deselected`) **exactly**. The 2 warnings
are SWIG `DeprecationWarning`s from a transitive C-extension, unrelated to this sprint. Baseline arc
1883 (kickoff) → 2055 (completion) confirmed against the kickoff frontmatter.

---

## 2. Per-criterion disposition (independent)

| # | SDV §4 criterion | Auditor verdict | Evidence (independent) |
|---|---|---|---|
| 1 | `substrate.db` sensitive data ciphertext at rest; retrieval unchanged; dedup intact | **MET** | Live DB raw-column scan: `substrate_chunks` 5 rows, `text`/`source`/`embedding` **all CIPHERTEXT(0x01)**, 0 plaintext. Tests: `test_retrieve...same top-k` (test_substrate_encryption.py:260), `test_reingest_same_doc_replaces_not_duplicates` (:364), `test_dedup_works_with_different_cipher_instances_same_dek` (:380), `test_whole_file_no_plaintext_after_migration` (:476). Runtime regression lock `assert store.has_encryption is True` at `entrypoint.py:1089`. |
| 2 | `sessions.db` conversation content ciphertext at rest | **MET** | Live DB raw-column scan: `turns.content` 8/8 CIPHERTEXT(0x01); `sessions.title` 2/2 CIPHERTEXT(0x01); 0 plaintext. `EncryptedSessionStore` (session_store.py:532); WAL-sidecar test + round-trip in `test_session_store_encryption.py` (13 tests green). |
| 3 | DEK envelope correct + fail-closed; nonces unique | **MET** | `field_cipher.py:234` fresh `os.urandom(12)` per encryption; HKDF split `k_enc`/`k_idx` (`derive_subkeys`, :117); AAD via `make_aad_for` (:158); ONE DEK dual-wrapped via `_wrap_dek_dual` (dek_envelope.py:200); version byte `0x01`. Production factory refuses `SoftwareSealer`: `build_envelope` raises `DevModeSealerError` (dek_envelope.py:551) — and `reseal_dek` carries the same guard (:613). Test `test_same_plaintext_different_ciphertexts` (test_field_cipher_and_dek_envelope.py:157). **No nonce-reuse / key-reuse path found.** (One fail-OPEN *factory-selection* seam — see MINOR-3 — is a posture-selection gap, not a cipher defect.) |
| 4 | Audit stream TPM-signed (integrity-only) via dedicated key (#605) | **MET (code); live activation honestly deferred** | `TpmRecordSigner` wraps `tpm_signer.sign/verify` with dedicated `AUDIT_TPM_KEY_NAME = "BlarAI-Audit-Signing-Key-v1"` (audit_log.py:158, 65), separated from the PA JWT key. Wired at `_build_audit_log` (entrypoint.py:1020). Contrast test `test_stub_key_is_recomputable_and_forgeable` + mirror (per EA-5 fragment). The SCR's "MET (code); live activation deferred to dev-mode flip" wording is **honest, not an overclaim** — I confirmed the current boot runs dev-mode, so the audit log is hash-chained + HMAC-stub-signed (the `_build_audit_log` dev branch at entrypoint.py:1028-1031 selects `HmacSha256Signer`). See §3. |
| 5 | Encryption overhead measured as a DELTA, both costs separately | **MET** | `PERFORMANCE_LOG.md` entry "2026-06-06 — AES-256-GCM substrate encryption overhead" (+0.124 ms/query median; 1.45 ms one-time boot-cache for 107 emb) + `docs/performance/benchmark_2026-06-06_02-15-23.json` (3107 bytes) both on disk; names what is NOT measured (boot-cache decrypt, per-query matched-text decrypt). |
| 6 | Key-recovery path tested AND non-developer-usable | **MET** | `provision_dek_keystore.py` one-command ceremony + `--recover`; recovery uses **public `unseal_via_recovery`** (provision:408) + **`reseal_dek`** (:431), NO `_recovery_wrap` import (confirmed by grep — only a *comment* matches), NO `SoftwareSealer` in `recover()`. Dead-chip SUCCESS test `_DeadSealer` (test_field_cipher...:763) whose `unseal()` always raises, proving the DEK came from the recovery wrap and the sealer's `unseal` is never called (:789-808). Runbook `docs/runbooks/at_rest_encryption_ceremony.md` (9361 bytes). **The LA ran the real ceremony** — proven on disk (§4). |
| 7 | Software-stub-verified; suite green; baseline recorded; production-posture is the LA's step | **MET** | 2055 green reproduced; baseline 1883→2055 recorded in SCR frontmatter. The production-posture live-verify (named as the LA's step) was actually **performed and passed** for encryption (§4) — the SCR's "exceeded" framing is justified for the encryption half. |

**7 of 7 MET.** Criterion #4's scope boundary (audit TPM-signing activates at the later dev-mode-off
flip) is honestly named in both the SCR and the code docstring, not hidden.

---

## 3. Verification detail by prompt item

### (1) Encryption real + production-wired — the Sprint-13 trap did NOT recur — **CONFIRMED**

- `build_session_store` is constructed at the **real production sites**:
  - `launcher/__main__.py:757` (Step 5) — `_session_store = build_session_store(db_path)` with
    fail-closed handling (no plaintext fallback; `DekEnvelopeError` propagates to refuse startup).
  - `services/ui_backend/src/__main__.py:75` — the `--no-model` real-DB path uses
    `build_session_store` (added in EA-4 round 2).
- `EncryptedSubstrateStore` is constructed at `entrypoint.py::_build_substrate` (:1083) with a
  **runtime** regression lock `assert store.has_encryption is True` (:1089).
- **The regression lock exercises the REAL entry point, not the factory in isolation.** Test
  `test_launcher_builds_encrypted_session_store` (test_launcher.py:283) runs the real `main_mod.main()`
  with `build_session_store` **deliberately un-mocked** (:345) and asserts `_session_store` is an
  `EncryptedSessionStore` (:353). This is the precise lesson-46 correction.
- **Round-1 → round-2 gap genuinely caught:** `git diff f7b541e bf79c0d` touches
  `launcher/__main__.py`, `services/ui_backend/src/__main__.py` and `_stub.py` (+213/-22) — the
  production-wiring fix. The round-1 commit `f7b541e` is in the git history with its merge-gate
  rejection recorded in the EA-4 fragment; round-2 `bf79c0d` merged as `1d218c2`. The diff is exactly
  "wire the launcher + a teeth-bearing lock," confirming the SCR/fragment narrative.

### (2) DEK envelope correctness — **CONFIRMED, no fail-OPEN cipher path**

- AES-256-GCM (`AESGCM`), fresh CSPRNG nonce per encryption (`os.urandom(_NONCE_BYTES)` field_cipher
  :234; `os.urandom(_RECOVERY_NONCE_BYTES)` for the recovery wrap dek_envelope:144). HKDF-split
  subkeys (info strings `blarai-field-enc-v1` / `blarai-index-mac-v1`). AAD binding present and
  enforced (decrypt raises `FieldCipherError` on AAD/tag mismatch, field_cipher:272-278). ONE DEK,
  dual-wrapped (`_wrap_dek_dual`, the single source of truth shared by `create` and `reseal_dek`).
  Version byte `0x01` on every field blob and wrap record.
- Production factory refuses `SoftwareSealer`: `build_envelope` (dek_envelope:551) **and** `reseal_dek`
  (:613) both raise `DevModeSealerError` when `not dev_mode and isinstance(sealer, SoftwareSealer)`.
- **No nonce-reuse or key-reuse found** anywhere in the cipher or envelope. The only fail-open vector
  is at the *factory-selection* layer (MINOR-3), not in the cryptography.

### (3) Fail-closed posture — refuse-to-start genuinely HALTS — **CONFIRMED**

- No plaintext fallback in any store. `build_session_store` production path uses `TpmSealer` +
  `DekEnvelope.load` (session_store:1206-1209); `_build_substrate` likewise (entrypoint:1074-1077).
  Both raise on DEK failure.
- **PA refuse-to-start verified by call-path trace, not asserted:** `_build_audit_log` (entrypoint
  :923) raises `AuditProvisioningError` in production on (a) `audit_log_path is None` (:972), (b) audit
  key unprovisioned (:995), (c) TPM unavailable (:1008). It is invoked from `_build_adjudicator`
  (:1048), which runs inside the `_phase_rules_load` measured-boot step. In `boot.py:130-136` the step
  loop wraps `step.action()` in `try/except Exception`, and on any raise sets `all_steps_passed=False`
  and `break`s; `state.ready` is only set `True` when all steps pass (:148). The listener-start step
  (step 5) is never reached → the PA never accepts requests. **The halt is real.**
- `_build_jwt_minter` divergence is **intentional and documented**: it `return None`s on a missing key
  (entrypoint:1070/1078/1081 — degrade-to-None), while `_build_audit_log` raises. The divergence is
  spelled out in the `_build_audit_log` docstring (:943-959) and ratified by ADR-025 §2.8(a). Correct.

### (4) Recovery path correct-by-DESIGN — **CONFIRMED**

- `recover()` (provision_dek_keystore:293) uses the **public `unseal_via_recovery`** (:408,
  recovery-only — never touches the TPM path) + **`reseal_dek`** (:431). The module imports
  (`:66-74`) do **not** include `_recovery_wrap`; a grep for `_recovery_wrap|SoftwareSealer` in the
  file returns only a single **comment** line (:380) affirming "there is no SoftwareSealer anywhere in
  recover()". A real `TpmSealer` is provisioned first (:391).
- **`build_envelope`/`create` and `reseal_dek` share ONE wrap implementation** (`_wrap_dek_dual`,
  dek_envelope:200) — `create` calls it at :307, `reseal_dek` at :625 — so the on-disk record format
  cannot diverge between the two paths. Test `test_reseal_record_format_matches_create` (:891) locks
  this.
- **Dead-chip SUCCESS test genuinely proves DEK-from-recovery:** `_DeadSealer.unseal()` always raises
  `TpmSealingError` (test_field_cipher...:763-774); the test asserts `unseal_via_recovery(rk)` returns
  the DEK **and** that the sealer's `unseal` is never invoked (:789-808). A sealer whose unseal always
  raises cannot have produced the DEK — so the DEK provably came from the recovery wrap.
- **Round-1 → round-2 fix confirmed:** `git diff 3896f1f 0e698b0` touches `dek_envelope.py` (+148),
  `provision_dek_keystore.py`, and adds 159 + 137 lines of tests — consistent with introducing the
  public `unseal_via_recovery`/`reseal_dek` and the dead-chip test, replacing the round-1
  "recovery-by-accident + private `_recovery_wrap` import + SoftwareSealer placeholder" path.

### (5) Criteria 7/7 + criterion-#4 scrutiny — **HONEST, not an overclaim**

The SCR's criterion-#4 wording — "MET (code); live activation deferred to dev-mode flip" — is
accurate. I confirmed against the running system that the current boot is **dev-mode**: there is no
`dev_mode=False` profile active, the launcher.log shows the encryption path live but the PA audit
signer in dev-mode selects `HmacSha256Signer` (entrypoint:1028-1031). So the audit log today is
**hash-chained + dev-stub-signed**, exactly as the SCR's "Verification posture (honest)" paragraph
states. The TPM audit *key is provisioned* (proven in §4) but the *signer* only engages at
`dev_mode=False`, which is gated on the later Tier-2 VM/mTLS build. No overclaim.

### (6) Production-posture live-verify — INDEPENDENTLY RE-RUN — **0 plaintext CONFIRMED**

I re-ran a raw-column classification against the live databases at `%LOCALAPPDATA%\BlarAI\`
(`text_factory=bytes`; classify: bytes-starting-`0x01` = ciphertext, str = plaintext, 1536-byte blob =
plaintext float32 embedding else ciphertext). **Counts (no content):**

| DB / column | rows | classification |
|---|---|---|
| `substrate_chunks.text` | 5 | 5 CIPHERTEXT(0x01), 0 plaintext |
| `substrate_chunks.source` | 5 | 5 CIPHERTEXT(0x01), 0 plaintext |
| `substrate_chunks.embedding` | 5 | 5 CIPHERTEXT(0x01), 0 plaintext (no 1536-byte float32 blobs) |
| `turns.content` | 8 | 8 CIPHERTEXT(0x01), 0 plaintext |
| `sessions.title` | 2 | 2 CIPHERTEXT(0x01), 0 plaintext |

**0 plaintext across all sensitive columns — the SCR's live-verify claim is independently confirmed.**

- `dek_keystore.json` **EXISTS** (480 bytes; keys `tpm_wrap_v1`, `recovery_wrap_v1`). I confirmed its
  `tpm_wrap` is **257 bytes (1 version byte + a 256-byte RSA-2048 OAEP block)** and that it **refuses
  to unseal under `SoftwareSealer`** (raises `DekEnvelopeError`). This proves the keystore is sealed by
  a **genuine non-exportable TPM RSA-2048 key**, not the software stub — the production posture is real.
- **`substrate.keystore.json` is NOT absent** (220 bytes) — see MINOR-3 / MINOR-4. I proved it does
  **not** bind to the production `substrate.db`: 0 of 5 substrate rows decrypt under the DEK that
  keystore wraps (the SoftwareSealer dev DEK), and the launcher.log records **0** "created ephemeral
  DEK keystore" warnings. So `substrate.db` is encrypted under the **production TPM DEK**; the dev
  keystore is an orphan test/dev artifact with no relationship to the real data. The criterion-6
  "wiped" expectation is unmet, but **no confidentiality impact**.

### (7) Premise correction — **ACCURATE + CONSISTENTLY APPLIED**

The "no decades of data on disk" correction is applied consistently across ADR-025 §1/§3 and SDV v3
§1/§3 (the corrected "born encrypted / well-timed, not urgent / disposable dev scaffolding" framing
appears 5× in each). My own live count (substrate 5 active chunks; sessions 2 sessions / 8 turns —
note these are *fresh* born-encrypted rows after the LA wiped the legacy dev data per SCR §4, smaller
than the pre-wipe \~107/376 figures) is consistent with the premise: this is disposable build-phase
data, not decades of secrets. The premise-verification journal lesson (verify on disk, don't inherit
through the review chain) is well-founded.

### (8) Git hygiene — **CLEAN + CORRECT; worktree-quirk recovery lost nothing**

- `main` HEAD is `230bb8b` (the SCR commit), with `e9c7c26` (SCR-claimed tip / ceremony runbook) an
  ancestor — consistent with the SCR frontmatter ("the SCR … land on top").
- The Cleaner-deferral content **is on main**: I verified it in the roadmap §2/§4/§5/§6, and both the
  original `6d01796` (which rode in via the EA-4 merge `1d218c2`) and the cherry-pick `4e58a8b` are
  ancestors of main with **identical content** (empty `git diff 6d01796 4e58a8b`). The "duplication"
  is the benign two-path landing the worktree-quirk recovery produced; nothing lost, nothing wrong.
- `wip/s14-ea4-staged-reversal-artifact` exists at `14d8a7b` (artifact preserved, never discarded).
- Working-tree dirt is **pre-existing and unrelated to Sprint 14**: the modified
  `docs/guide-workstreams/README.md` belongs to the `agent:guide_11` openvino-upstream workstream
  (commit 8b47358), and the 10 untracked `benchmark_2026-05-2x-*.json` files date from May 21-22.
  Neither is a Sprint-14 artifact.

---

## 4. Findings (CRITICAL / MAJOR / MINOR)

### CRITICAL — none.

### MAJOR — none.

### MINOR-1 — SCR overclaims the ADR-025 §5 trust anchor was recorded

**Evidence.** SCR §4 states: *"Trust anchor (ADR-025 §5): the key fingerprints are recorded into
ADR-025 §5 + a `docs/ledger/` entry as part of this close (no secrets; public-key SHA-256 + names +
date)."* On disk, ADR-025 §5 (lines 234-239) is **still the unfilled placeholder**: *"To be filled
when the LA runs the batched ceremony … Until then this ADR is the design record; the keys are not yet
live."* The ceremony demonstrably **was** run (real TPM keystore, §4), so the §5 anchor *should* be
filled — but the SCR claims a recording that does not exist.

**Disposition.** Fill ADR-025 §5 with the real `SHA-256(SPKI DER)` fingerprints of `BlarAI-DEKSeal`
and `BlarAI-Audit-Signing-Key-v1`, plus the recovery-key-stored confirmation and date (no secrets) —
the SCR already promises exactly this content. Until then, soften the SCR §4 wording from "are
recorded" to "to be recorded at close." This is an honesty-of-record gap on the IAPP-portfolio
surface, which is precisely where the project's standard is strictest.

### MINOR-2 — No `docs/ledger/` Sprint-14 close entry exists

**Evidence.** `docs/ledger/` contains only `…sprint12…` and `…sprint13…` entries; there is no
Sprint-14 entry, though SCR §4 references one "as part of this close." Per CLAUDE.md (DEC-17, permanent
rule) all new ledger entries land in `docs/ledger/` per-file.

**Disposition.** Likely benign sequencing — the SWAGR runs *before* the Orchestrator's final close
commits, and SCR §8 ("post-SWAGR reconciliation") is explicitly deferred. Add the Sprint-14 ledger
close entry (with the trust-anchor fingerprints, resolving MINOR-1 in the same stroke) as part of the
post-SWAGR close. Flagged so it is not dropped.

### MINOR-3 — Store factories fail OPEN (to the public SoftwareSealer) on a missing `BLARAI_DEK_KEYSTORE`

**Evidence.** `build_session_store` (session_store.py:1179-1209) and `_build_substrate`
(entrypoint.py:1046-1077) select the sealer by **env-var presence**: if `BLARAI_DEK_KEYSTORE` is unset
(or `db_path == ":memory:"`), they construct a `SoftwareSealer()` and pass `dev_mode=True` to
`build_envelope` — which therefore **bypasses** the `DevModeSealerError` production guard. So a real
production deployment that boots with `BLARAI_DEK_KEYSTORE` accidentally unset does **not** refuse to
start; it silently writes data encrypted under the hard-coded public key
`b"SOFTWARE-SEALER-NOT-A-SECRET-KEY"` — i.e. effectively plaintext to anyone with the source. ADR-025
§2.7 requires the production factory to "refuse to construct with a `SoftwareSealer` … outside an
explicit, loud dev/test mode"; here the dev/test mode is *inferred from env absence*, not asserted —
so a misconfiguration reads as "dev mode" rather than "fail closed."

This is a **design seam**, not an exploited defect: the actual production boot did set the env var
(proven — the live DBs are TPM-encrypted, §4), so no real data is exposed today. But the factory's
fail-open-on-misconfiguration posture is a latent foot-gun on a security-critical path, and is exactly
the class of "fail closed in dev, fail open in production" the SDV §9.3 warned about.

**Disposition.** Tie the dev/SoftwareSealer path to an **explicit, loud** signal (e.g. require
`BLARAI_DEV_ENCRYPTION=1` or a `dev_mode=True` argument from a dev-only caller) rather than inferring
it from `BLARAI_DEK_KEYSTORE` being unset; in the production deployment path (launcher Step 5 /
ui_backend / AO entrypoint with a non-`:memory:` real DB), a missing keystore env var should
**refuse to start**, symmetric with the audit refuse-to-start. File a Stage-6.7.5-pattern hardening
ticket (non-optional per project doctrine). This is the one finding with genuine security weight, held
at MINOR only because the live posture is correct and no data is exposed.

### MINOR-4 — Orphan dev keystore (`substrate.keystore.json`) in the production data dir

**Evidence.** `%LOCALAPPDATA%\BlarAI\substrate.keystore.json` (220 bytes, mtime 2026-06-05 22:47) is a
`SoftwareSealer` dev keystore sitting beside the real `dek_keystore.json`. It is the visible symptom
of MINOR-3 (a dev/test boot or a test run with `LOCALAPPDATA` pointed at the real dir created it). I
proved it does **not** bind to the production `substrate.db` (0/5 rows decrypt under its DEK; 0
"ephemeral DEK keystore" warnings in launcher.log), so there is **no confidentiality impact** — but
criterion #6's expectation that the dev keystore be wiped is **unmet**, and a future operator could be
confused by two keystore files (or, worse, a future rotation/recovery tool could pick the wrong one).

**Disposition.** Remove `substrate.keystore.json` from the production data dir as part of the close
(operator action — *not* an auditor action; I am read-only). Additionally, prevent tests from writing
keystores into the real `%LOCALAPPDATA%\BlarAI\` (a test-hygiene fix; `test_substrate_encryption.py:590`
manipulates `LOCALAPPDATA`/`BLARAI_DEK_KEYSTORE` and should always target a `tmp_path`). Fold into the
MINOR-3 hardening ticket.

---

## 5. What was checked and found solid (no finding)

- The CNG RSA-2048 sealing primitive (`tpm_sealer.py`): non-exportable key (no `NCRYPT_ALLOW_EXPORT`),
  OAEP-SHA256, input-length cap, fail-closed `TpmUnavailable` off-Windows, `SoftwareSealer` clearly
  marked "NOT A SECURITY BOUNDARY."
- The audit chain (`audit_log.py`): hash-chained, fail-closed-on-write, deterministic canonical bytes,
  TPM/HMAC signer split, genesis constant.
- AAD natural-key construction for substrate (`_natural_row_id`, substrate.py:339 — `kind|source_hash_hex|
  session_id|chunk_index`, AUTOINCREMENT id correctly excluded per ADR-025 §2.4); UUID-as-identity for
  sessions.
- Nonce-uniqueness, dead-chip-recovery, reseal-format, dual-unwrap, wrong-key-fail-closed,
  prod-refuses-SoftwareSealer test set — all present with teeth.
- The keyed-hash dedup-on-ciphertext (`keyed_index` / `source_hash`) and its documented
  equality-leakage residual.

---

## 6. Recommended overall disposition

**PASS (CONCERNS).** Accept the sprint as **COMPLETE — and live-verified for encryption** (the
security substance is real and earns the pass). Before the final close, the Orchestrator should:

1. Resolve **MINOR-1 + MINOR-2** together: fill ADR-025 §5 with the real key fingerprints and author
   the `docs/ledger/` Sprint-14 close entry (the SCR already specifies the content).
2. File a **non-optional hardening ticket** for **MINOR-3** (factory fail-open on missing keystore env
   var — make the dev path an explicit loud opt-in; production refuse-to-start), and fold **MINOR-4**
   (remove the orphan dev keystore + test-hygiene fix) into it.
3. Append the SCR §8 post-SWAGR reconciliation referencing this report.

None of the MINORs blocks the #598 at-rest-encryption criterion, which is genuinely **MET in
production posture** on the real TPM.

---

*Independent Sprint Auditor — read-only. This report was written to
`docs/sprints/sprint_14/Strategic_Work_Analysis_and_Gap_Report_Sprint_14_20260605_swagr.md`; the
Auditor did not modify source, did not commit, and did not merge.*
