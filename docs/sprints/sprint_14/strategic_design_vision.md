---
sprint_id: 14
sprint_name: "Tier-2 at-rest encryption + audit-stream TPM signing"
predecessor_sprint_id: 13
vikunja_tracking_task_id: 609
start_date: "2026-06-05"
target_completion_date: "2026-06-07"
la_approved_on: "2026-06-05T17:32:10-07:00"
la_approved_by: "blarai"
co_lead_drafted_on: "2026-06-05T17:00:51-07:00"
co_lead_commit_when_drafted: "90aa857"
sdv_version: 3
---

# Strategic Design Vision — Sprint 14: Tier-2 at-rest encryption + audit-stream TPM signing

## 1. Executive brief

Sprint 14 opens **Tier 2** of the air-gap-removal campaign by encrypting the two SQLite stores
that hold decades of the user's private data — `substrate.db` (the personal knowledge store) and
`sessions.db` (conversation history) — at rest, and by upgrading the Policy-Agent audit stream's
signature from a software stub to a real TPM-backed key (#605). Encryption is **app-layer
AES-GCM** using the `cryptography` library already present in the environment (no new dependency;
SQLCipher was rejected), under a **TPM-sealed data-encryption key (DEK)** with a **second offline
recovery key** for dead-chip / hardware-migration survival. We do this now — ahead of any real use —
so that real data is **born encrypted** from its first write (no plaintext window ever) and the #598
gate criterion is met; the stores today hold only disposable build-phase dev/test data (verified on
disk, 2026-06-05), so there is no exposed data to rescue and **no time pressure**. Both the encryption
seal key and the audit signing key are TPM-rooted — so they share **one batched on-chip ceremony**,
giving the Lead Architect (LA) an early "real keys, not mocks" win. **Done =**
both DBs are ciphertext at rest (content text, embeddings, and content-bearing labels) with a
*tested, non-developer-usable* key-recovery path, the audit log carries TPM-signed records that
`verify()`, all of it built code-complete against a software TPM stub, with the on-chip ceremony
and one production-posture live-verify handed to the LA as the only steps that count as "works."

## 2. Context

### 2.1 Predecessor sprint outcome

- Predecessor SCR: `docs/sprints/sprint_13/strategic_completion_report.md`
- Predecessor SWAGR: `docs/sprints/sprint_13/Strategic_Work_Analysis_and_Gap_Report_Sprint_13_20260605_205834.md`
- Sprint 13 (Tier-1 finishers) shipped the PII Luhn fix (#601), the tamper-evident audit stream
  (#602), and the dev-mode interlock (#603) as the campaign's first fleet wave; independent SWAGR
  returned **PASS** (5/5 MET, 0 CRITICAL, 0 MAJOR, 4 MINOR; `1883 passed` reproduced). Open
  threads it deliberately handed forward: the audit stream's **real TPM signer (#605 — built this
  sprint)**, retention/rotation (#607) and tail-deletion attestation (#606, both deferred), and the
  production-posture live-verify (the LA's batched step). One predecessor MINOR is closed here:
  **SWAGR MINOR-3** (encode the stub-vs-TPM forgeability difference as a visible test, not prose)
  folds into the #605 work.

### 2.2 Repo state at kickoff

- Main branch HEAD: `90aa857`
- Most recent ledger entry: Q1-1 per-file ledger (`docs/ledger/`); Sprint 13 close entry
  `7081b6f`. The monolithic `POST_OPERATIONAL_MATURATION_LEDGER.md` remains FROZEN at Entry 52.
- Open Vikunja Pending-Human gates: 0 carried in (Sprint 13 closed clean). This sprint's tracking
  task **#609** carries `Gate:Pending-Human` pending this SDV's sign-off.
- Known-active feature branches: none (serial kickoff; roster `docs/active_tasks.yaml` is empty).

### 2.3 External inputs driving this sprint

- **LA-ratified campaign decisions (2026-06-05, #598):** the FULL air-gap bar (Tier 0+1+2+3), and
  at-rest encryption via a TPM-sealed key + offline recovery key (Decision 2). This sprint executes
  the encryption half of Tier 2.
- **Tier-2 umbrella #559** (encrypt at rest; Cleaner; VM/mTLS; retention) and the GO/NO-GO gate
  **#598**, which lists "at-rest encryption on, with a tested recovery path" as a hard criterion.
- **Sprint-14 LA decisions (2026-06-05, this kickoff + the v1 review):**
  1. **Embeddings: encrypt both, cache at boot.** Encrypt `text` AND `embedding` at rest; decrypt
     embeddings once into RAM at unlock; run vector search over the in-memory copy. *Rationale
     (recorded per LA direction):* embeddings are **invertible** — embedding-inversion techniques
     (e.g. vec2text) reconstruct source content from vectors — so plaintext embeddings would leave a
     recoverable **semantic shadow** of everything on a stolen disk. Encrypting them closes that leak
     at trivial cost, since the vectors must be in RAM in the clear for the search math regardless.
  2. **Content-bearing labels are encrypted too.** The same stolen-disk threat that justifies
     encrypting embeddings applies *a fortiori* to a readable label — a document filename
     (`2024_oncology_results.pdf`) is a more direct content leak than an embedding (which needs an
     inversion attack). So `substrate_chunks.source` (the filename) and `sessions.title` (auto-derived
     from the first user prompt) are in the cipher set. (LA override of the v1 "leave filenames
     plaintext" recommendation — see §5.3.)
  3. **Audit log: integrity-only.** Signed/tamper-evident + (via #605) non-forgeable, but readable.
     Resource paths stay cleartext — acceptable for a local, single-user, integrity-protected log;
     preserves forensic readability and avoids a circular dependency on the encryption subsystem.
  4. **Scope: both DBs + #605** (no plaintext-sessions fast-follow).
- **Standing user-memory inputs:** the LA runs on-chip ceremonies so work uses real keys (batch
  them); local-stack only (no cloud KMS); mature-not-minimal depth; hardening follow-ups are
  non-optional (so deferred items stay ticketed, not dropped).

## 3. Sprint purpose

The air-gap has, until now, protected BlarAI's data by *absence* — there are no external paths, so a
stolen laptop or a leaked backup is the only realistic exposure, and against that exposure the data
sits in plaintext SQLite by design. The campaign is deliberately walking BlarAI toward a
network-facing future (#556), and the LA has ratified that nothing goes online until the FULL bar
holds, including at-rest encryption. But the reason to encrypt **now**, ahead of any network
capability, is one of *timing*: BlarAI has not yet been used in a daily setting — verified on disk
(2026-06-05), the two stores hold only disposable build-phase dev/test scaffolding (`substrate.db` ≈
107 chunks / \~400 KB; `sessions.db` ≈ 59 sessions / 376 turns / \~250 KB), and **no real sensitive data
exists yet**. Building the at-rest control before real use begins means every byte of real data is
**born encrypted from its first write — there is never a plaintext window on disk**. That is a cleaner
and more honest motivation than "protect exposed data" (nothing is exposed): the architectural gap
Domain 7 named is real and must be closed before daily use, and closing it now costs nothing in data
risk because there is no data at risk.

Pairing encryption with the audit-stream TPM signer (#605) is a deliberate efficiency, not scope
creep. Both are rooted in the same TPM. If they shipped in separate sprints they would demand two
separate on-chip ceremonies from the LA; shipped together they share one batched ceremony (the RSA
encryption seal key, the dedicated ECDSA audit signing key, and the offline recovery key, all
provisioned in a single session). #605 is also the *lightest* real-key win in the whole campaign —
it reuses the existing ECDSA sign/verify primitive with a dedicated key — so it front-loads the
LA's first "real keys, not the stub" moment while the heavier encryption code is still being built
and reviewed.

If we skipped this sprint, the campaign could not pass #598 (two hard criteria — at-rest encryption
with a tested recovery path, and a non-forgeable audit stream — would remain open), and real data
would later be **born in plaintext**, opening a window that only an after-the-fact migration could
close. Shipping the control first means the window never opens. The sprint is **well-timed, not
urgent** — with no sensitive data on disk there is zero data-exposure time pressure, which is exactly
why correctness outranks the 2026-06-07 target (§12).

## 4. Success criteria

All criteria are verifiable at sprint end on the integrated `main` tree against a **software TPM
stub** (the production-posture live-verify with real keys is the LA's separate step, §11, and is
**not** claimed by these criteria). "Fail closed" throughout means: on any key/TPM unavailability,
refuse rather than fall back to plaintext.

1. **`substrate.db` sensitive data is ciphertext at rest, retrieval unchanged, dedup intact.** Given
   a populated store, a raw SQLite read of `substrate_chunks.text`, `.embedding`, and the encrypted
   `source` (filename) yields ciphertext (no readable document text, no directly-usable float32
   vectors, no readable filenames), while `SubstrateStore.retrieve()` returns the same top-k hits as
   the pre-encryption baseline for a fixed query set **and** re-ingesting the same document still
   dedups (the keyed-hash uniqueness key works on ciphertext).
   *Verification:* a raw-file "no plaintext / no raw vectors / no readable filename" test + a
   retrieval-equivalence test + a re-ingest-dedup test, all green.
2. **`sessions.db` conversation content is ciphertext at rest.** `turns.content` and
   `sessions.title` (content-bearing) are ciphertext on disk; `get_session_turns()` and
   `list_sessions()` return correct plaintext via decrypt-on-read; the empty-title backfill path
   still works.
   *Verification:* a raw-read test + a write→read round-trip test.
3. **The DEK envelope is correct and fail-closed; nonces are unique.** Exactly **one** DEK encrypts
   the data; it is wrapped **twice** — once by the (stub) TPM seal and once by the offline recovery
   key — and either wrap independently unwraps the *same* DEK. Each field encryption uses a **fresh
   random 96-bit nonce** (prepended to the ciphertext): encrypting the same plaintext twice yields
   *different* ciphertexts. A wrong/absent recovery key fails closed; if the TPM cannot unseal at
   boot, the store refuses to open (or routes to the recovery path) and never reads plaintext.
   *Verification:* tests with teeth — TPM-unavailable → refuse-to-open; recovery-key → unwrap of the
   identical DEK; wrong key → fail-closed (see §2.7 amendment below); repeated-plaintext → distinct
   ciphertext (fresh-nonce evidence).

   **SDV §3 criterion 3 amendment (2026-06-06, Sprint 15 #618 — ADR-025 §2.7 amendment):**
   The original "wrong key → fail-closed" phrase described *single-record callers* correctly but
   over-applied to **bulk readers** (`list_sessions`, `get_session_turns`,
   `_backfill_empty_titles`). Applying fail-closed uniformly to bulk reads causes a
   self-inflicted availability DoS: one legacy (dev→prod key transition) or tampered row aborts
   the entire operation. The corrected posture, per ADR-025 §2.7 amendment: bulk readers
   **quarantine** un-decryptable rows (omit + log `SESSION_ROW_DECRYPT_QUARANTINE`);
   single-record callers retain hard fail-closed. Plaintext is never returned from a quarantined
   row; tampered data is never trusted. Availability is a security property (CIA triad) and
   preserving it for the good rows is not a weakening of confidentiality or integrity.
4. **The audit stream is TPM-signed (integrity-only) via a dedicated key (#605).**
   `_build_audit_log` constructs a `RecordSigner` wrapping `tpm_signer.sign/verify` with a
   **dedicated audit key** (not the PA JWT key — separation of duties); a TPM-signed (stub) chain
   passes `verify()`; and a **contrast test** (SWAGR MINOR-3) encodes the upgrade's value — a
   recomputable stub key yields a signature the chain accepts (forgeable), a non-recomputable key
   does not. Audit records remain unencrypted (Decision 3).
   *Verification:* the #605 test set incl. the contrast test, green.
5. **Encryption overhead is measured and recorded as a DELTA, community-grade, BOTH costs
   separately.** A pre-encryption retrieval baseline is captured, then two post-encryption numbers,
   and each is reported **as a delta vs that baseline** (the honest, comparable figure) — written to
   `PERFORMANCE_LOG.md` (narrative) + `docs/performance/` JSON (dataset), with hardware /
   OpenVINO+driver / method metadata and an explicit statement of what is *not* measured: (a) the
   one-time boot/unlock embedding-cache decrypt, and (b) the per-query matched-text decrypt.
   *Verification:* the log entry + JSON file exist on disk with the baseline + both deltas.
6. **The key-recovery path is tested AND non-developer-usable.** A ceremony runbook specifies the
   offline recovery key's concrete format (a high-entropy random key, printed/USB — not a
   passphrase) and the exact, ordered steps a non-developer follows to recover data on a
   dead/replaced chip; an automated test exercises the recovery-key unwrap end-to-end. (An untested
   or unusable recovery path does **not** satisfy #598's "tested key-recovery path.")
   *Verification:* the runbook file + the recovery test, both on disk and green.
7. **Software-stub-verified; suite green; baseline recorded.** Full Layer-A suite
   (`-m "not hardware and not winui and not slow"`) is green on the integrated tree with all new
   tests additive; the SCR records the kickoff→completion baseline delta. The production-posture
   live-verify is named as the LA's step, not claimed.
   *Verification:* the pytest result + the SCR.

## 5. Scope

### 5.1 In-scope

1. **TPM key-sealing primitive (NEW CNG code).** The existing `shared/security/tpm_signer.py`
   provides ECDSA P-256 **sign/verify only** — it cannot wrap a symmetric key. This sprint adds a
   sealing primitive: an **RSA TPM key** used with `NCryptEncrypt`/`NCryptDecrypt` (RSA-OAEP) to
   wrap/unwrap the symmetric DEK, following the existing module's shape (portable, fail-closed
   `TpmUnavailable`, idempotent `ensure_key`, non-exportable persisted key). Software-stub-testable.
2. **App-layer cipher module + DEK lifecycle.** AES-GCM (via `cryptography`) for field encryption,
   with a **fresh random 96-bit nonce per encryption, prepended to each ciphertext** (never fixed or
   derived — nonce reuse under one DEK is catastrophic for GCM, and we ship ONE DEK across many
   fields). Plus the envelope: ONE DEK, **dual-wrapped** — by the TPM seal and by a **high-entropy
   random offline recovery key** (not a passphrase: passphrases carry forget-risk and a
   password-hashing KDF, a possible new dependency — rejected). The envelope is **versioned to permit
   a later key rotation** (the random-96-bit nonce birthday bound is \~2^32 messages — effectively
   never at single-user scale, but it is the documented re-key trigger); rotation itself is not built
   (§5.2). The precise cryptographic choices (nonce, recovery-key nature, AAD binding) are **pinned
   in the ADR authored before this EA** (§5.1 #9, §7).
3. **Declare `cryptography` in `pyproject.toml`** with a sensible version bound — it is currently a
   transitive (undeclared) dependency; making it explicit removes the fragility for security-critical
   code. This adds **no new install** (it is already present, 46.0.5). No one-off hash-pin — the
   pinned + hash-verified lockfile is Tier-3 (#560).
4. **`substrate.db` encryption wiring.** Encrypt `text`, `embedding`, and `source` (the filename) on
   write; decrypt embeddings **once at unlock into the in-RAM search matrix** (the boot-cache),
   keeping `_search_kind` running over plaintext vectors in memory; decrypt only the top-k matched
   `text` per query. For `source`, store a **deterministic keyed hash** (HMAC under a dedicated
   index subkey derived from the DEK via HKDF — key separation) as the dedup/uniqueness key so
   `idx_chunk_identity` + re-ingest dedup keep working on ciphertext, alongside `AES-GCM(source)` for
   decrypt-on-read display. Retrieval results unchanged; both perf costs measured as deltas
   (criterion #5).
5. **`sessions.db` encryption wiring.** Encrypt `turns.content` and `sessions.title` on write;
   decrypt-on-read in `get_session_turns()` / `list_sessions()`; handle the `_backfill_empty_titles`
   path (it reads `turns.content`). No cache needed (no vector search). Reuses the EA-2 cipher module.
6. **#605 audit TPM signer.** A `RecordSigner` over `tpm_signer.sign/verify` with a dedicated audit
   key; drop-in swap at `services/policy_agent/src/entrypoint.py::_build_audit_log` (mirrors
   `_build_jwt_minter`); plus the MINOR-3 contrast test.
7. **Ceremony runbook + live-verify checklist** for the LA: the 3-key on-chip ceremony (RSA seal,
   ECDSA audit, offline recovery) and the production-posture live-verify steps, written for a
   non-developer, including the concrete recovery-key handling (criterion #6).
8. **Performance records** (PERFORMANCE_LOG.md + `docs/performance/` JSON) per criterion #5.
9. **The at-rest encryption ADR — authored EARLY, as a design gate before EA-2 (not a close
   artifact).** It PINS, before any cipher code is built: (a) the **nonce strategy** (fresh random
   96-bit, prepended, never reused; re-key trigger); (b) the **recovery key's exact nature** (a
   high-entropy random key the LA stores off-box — printed/USB — wrapping the same DEK, not a
   passphrase); (c) **AAD binding** — recommend each field's AES-GCM bind to its row identity via
   `AAD = table|column|natural-row-id` so a ciphertext cannot be relocated between rows/columns
   (defense-in-depth; note the binding id must be known at insert time — a UUID for sessions, the
   `kind|source_hash|session_id|chunk_index` natural key for substrate, since `substrate_chunks.id`
   is `AUTOINCREMENT` and unknown pre-insert). The ADR is surfaced to the LA for a quick look before
   EA-2 builds the cipher.
10. **Portfolio artifacts (orchestrator, at close):** a **BUILD_JOURNAL entry** for the encryption
    arc with a **proposed top-of-file lesson** ("encrypt the *derived* representations, not just the
    raw text, because embeddings are invertible") — the ADR (#9) is its companion, carrying the nonce
    + recovery-key decisions; and the **campaign-pacing plan** (§10).

### 5.2 Out-of-scope (deliberately deferred)

1. **Audit-stream retention/rotation (#607)** — non-urgent (disk is cheap, completeness is the
   default); orthogonal to crypto. Stays ticketed; a later audit-hardening increment.
2. **Audit-stream tail-deletion attestation (#606)** — Tier-2/3 hardening; its natural anchor is a
   TPM-sealed counter, which we are explicitly **not** provisioning in this ceremony (§5.3).
3. **The Cleaner (UC-003, #559)** — the next Tier-2 sub-project; its own sprint.
4. **Run-in-VM / mTLS / per-boot certs** — the final, heaviest Tier-2 lift; its cert ceremony is last.
5. **dev-mode running-default flip (`dev_mode=false` for HOST)** — gated on the cert/mTLS build; the
   Sprint-13 interlock already guards the transition.
6. **Measured-boot attestation** — Tier-1 ceremony-bound item, separate.
7. **PII embedded-PAN recall (#608)** — activates with redact-at-egress (network-facing); not now.
8. **DEK rotation** — the envelope is *versioned to* allow it, but the rotation procedure is not
   built this sprint.

### 5.3 Scope boundaries and edge cases

- **Encrypt the payload AND the content-bearing labels.** Cipher set: `substrate_chunks.text`,
  `.embedding`, `.source` (filename); `turns.content`, `sessions.title`. *(v2 change — LA override:
  `source` moved INTO the cipher set. A readable filename is a more direct content leak than an
  embedding, so leaving filenames plaintext while encrypting vectors would be backwards and
  internally inconsistent with §2.3. The index/dedup objection is solved by the keyed-hash pattern in
  §5.1 #4, not a rework.)*
- **`session_id` stays plaintext** — it is a relational/join key across `sessions`/`turns`/chunks and
  an identifier, not content. Encrypting it would break joins for zero confidentiality gain.
- **Low-value metadata stays plaintext** — row IDs/UUIDs, timestamps, `kind`, `chunk_index`,
  `is_active`, `role`, `pgov_status`. Encrypting them would break indices/ordering/foreign keys for no
  real confidentiality gain.
- **WAL safety:** `sessions.db` runs in WAL mode. App-layer **field** encryption is inherently
  WAL-safe — the `-wal`/`-journal` sidecars only ever carry the already-ciphertext column values, so
  no plaintext leaks via the journal. (No change to journaling mode required.)
- A minimal edit to an adjacent module is IN only if a test requires it; broad refactoring of the
  store classes is OUT.

## 6. Deliverable summary

| Deliverable | Type | Target location | Success criterion |
|---|---|---|---|
| At-rest encryption ADR (nonce / recovery key / AAD) — **authored before EA-2** | doc | `docs/adrs/` | #3, #6 (design gate) |
| TPM key-sealing primitive (RSA-OAEP wrap/unwrap) | code | `shared/security/` (new sealer / `tpm_signer.py` extension) | #3 |
| App-layer cipher + DEK envelope (fresh-nonce, dual-wrap) | code | `shared/security/` (new cipher module) | #1, #2, #3 |
| `cryptography` declared with version bound | config | `pyproject.toml` | #1 (no new dep) |
| `substrate.db` encryption (text + embedding + source; boot-cache; keyed-hash dedup) | code | `services/assistant_orchestrator/src/substrate.py` | #1, #5 |
| `sessions.db` field encryption (content + title) | code | `services/ui_gateway/src/session_store.py` | #2 |
| #605 audit TPM signer (dedicated key) + contrast test | code + test | `services/policy_agent/src/entrypoint.py`, `shared/security/audit_log.py`, tests | #4 |
| Encryption-overhead records (baseline + both deltas) | data | `PERFORMANCE_LOG.md`, `docs/performance/*.json` | #5 |
| Ceremony runbook + live-verify checklist (non-dev recovery) | doc | `docs/runbooks/` (or `docs/security/`) | #6 |
| SCR + BUILD_JOURNAL entry + proposed lesson + campaign-pacing plan | doc | `docs/sprints/sprint_14/`, `BUILD_JOURNAL.md` (orchestrator fold) | #7 |

## 7. EA milestone plan

**Shape: a serial security-critical spine + one disjoint parallel lane, with an ADR design-gate
before the cipher.** Per the LA's directive to keep this sprint focused and *not* parallelize the
security-critical seal code or the first ceremony, the encryption spine runs serially (each EA
reviewed at the merge gate before the next builds on it). The **envelope ADR is authored after EA-1
and before EA-2** so the cryptographic choices are pinned before the cipher is built. Only #605 — a
separate file using the *existing* ECDSA primitive with a dedicated key — runs as a parallel lane,
because it shares no working set with the seal code.

| EA-# | Working title | One-sentence purpose | Depends on | Approx size |
|---|---|---|---|---|
| EA-1 | TPM key-sealing primitive | New CNG RSA-OAEP wrap/unwrap of a symmetric DEK; fail-closed `TpmUnavailable`; software-stub-testable. | main | M |
| — | **Envelope ADR (design gate)** | Orchestrator pins nonce / recovery-key / AAD before the cipher is built; surfaced to the LA. | EA-1 | S (doc) |
| EA-2 | App-layer cipher + DEK envelope | AES-GCM field cipher (fresh-nonce) + the dual-wrapped DEK lifecycle; declare `cryptography` in pyproject. | ADR | M |
| EA-3 | `substrate.db` encryption wiring | Encrypt text+embedding+source; embedding boot-cache; keyed-hash dedup; top-k text decrypt; retrieval-equivalent; perf deltas measured. | EA-2 | L |
| EA-4 | `sessions.db` encryption wiring | Encrypt `content`+`title`; decrypt-on-read; backfill path; reuses the proven substrate pattern. | EA-2 (sequenced after EA-3) | M |
| EA-5 | #605 audit TPM signer | Dedicated-key `RecordSigner` drop-in at `_build_audit_log`; MINOR-3 contrast test. | main (parallel from start) | S |

The Orchestrator authors each EA prompt one at a time, holds the merge gate (diff-reviewed against
the audit/criterion, not just a green suite — per lesson 46), and folds journal fragments at the
quiet tree. Builders are worktree-isolated sonnet subagents; they never merge to `main` and never
touch `BUILD_JOURNAL.md`.

## 8. Dependencies and prerequisites

### 8.1 Upstream dependencies

- Sprint 13 finishers on `main` (done; HEAD `90aa857`) — specifically the audit stream (#602) whose
  signer EA-5 swaps.
- The envelope ADR gates EA-2; EA-2 requires EA-1; EA-3 and EA-4 require EA-2.

### 8.2 External dependencies

- `cryptography` (present, 46.0.5) — used for AES-GCM + HKDF (the index subkey); declared explicitly
  this sprint.
- The Microsoft Platform Crypto Provider / a TPM 2.0 — needed **only** for the LA's on-chip ceremony
  and live-verify. The build and all criteria use a **software stub** for the TPM seal/unseal, exactly
  as the audit stream shipped against an HMAC stub in Sprint 13.
- A running Vikunja for tracking (task #609).

### 8.3 Assumed invariants

- The `substrate_chunks` and `sessions`/`turns` schemas are stable for the sprint's duration; the
  additive columns this sprint needs (the encrypted `source` value + its keyed-hash index column) are
  an additive migration handled inside EA-3, not a separate breaking change.
- The existing ECDSA TPM signing primitive and its `ensure_key` semantics are stable (EA-5 reuses
  them unchanged with a new key name).

### 8.4 Parallel-Sprint Authorization & Shared-Artifact Audit

**N/A — serial kickoff (no other sprint active).** `docs/active_tasks.yaml` is empty at kickoff; no
concurrent sprint overlaps this one, so the shared-artifact audit is not required and
`set_parallel_sprints_authorized(True)` is not invoked.

## 9. Risks and unknowns

### 9.1 Known risks

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| New CNG sealing code is subtly wrong (it protects decades of data) | med | high | Mirror the proven `tpm_signer.py` shape; fail-closed `TpmUnavailable`; software-stub tests with teeth; merge-gate diff-review against the criterion; serial spine so it is reviewed in isolation. |
| AES-GCM nonce reuse under the single DEK (catastrophic for GCM) | low | high | ADR pins fresh-random-96-bit-per-encryption, prepended; a repeated-plaintext→distinct-ciphertext test (criterion #3) makes reuse visible; documented re-key trigger. |
| "Built but wired into nothing" recurrence (cipher built but the store factory never passes it) — the exact Sprint-13 EA-2 trap | med | high | Merge gate reviews the *production wiring path*, not the unit tests (lesson 46); add a `has_encryption`-style regression lock at the production store construction site. |
| Retrieval perf regression from encryption | low | med | Boot-cache keeps the hot path on plaintext in-RAM vectors; measure deltas (criterion #5) and report honestly. |
| DEK loss / unusable recovery path | low | high | Recovery path tested end-to-end + a non-developer runbook (criterion #6); dual-wrap so a dead chip is survivable. |
| Keyed-hash dedup edge cases (collisions / case-normalization of filenames) | low | med | Deterministic HMAC over the exact stored `source` bytes; EA-3 preserves current normalization; re-ingest-dedup test (criterion #1). |
| Plaintext embeddings/text in RAM during operation | n/a (accepted) | — | Out-of-scope threat (a live-memory attacker is not the at-rest/stolen-disk model this sprint defends); documented in the ADR. |

### 9.2 Known unknowns

1. Exact behaviour of `NCryptEncrypt`/`NCryptDecrypt` RSA-OAEP on the reference STMicro TPM via the
   Microsoft Platform Crypto Provider (key generation flags, OAEP padding parameters). A 32-byte
   AES-256 DEK fits comfortably inside an RSA-2048 OAEP block, so a **direct** wrap (no intermediate
   wrapping key) is expected to work — to be confirmed in EA-1 against the stub and, ultimately, at
   the ceremony. The software stub de-risks the build regardless.
2. Whether any production caller constructs `SubstrateStore`/`SessionStore` on a path that the
   encryption wiring must also cover (a second factory site). EA-3/EA-4 must grep for *all*
   construction sites, not just the obvious one (the Sprint-13 wiring lesson).

### 9.3 Unknown unknowns posture

Cryptographic plumbing is where confident-looking code is most likely to be quietly wrong, and where
"the tests pass" is least reassuring — a cipher that round-trips in a unit test can still leave
plaintext on disk through a path no test exercised, reuse a nonce under load, or fail closed in dev
and fail *open* in production. We are almost certainly under-imagining the ways the DEK lifecycle
interacts with process restarts, partially-written rows, and the WAL. The serial spine, the ADR
design-gate, the merge gate's wiring-not-suite review, and the LA's production-posture live-verify
exist precisely to catch the class of thing this plan has not thought of.

## 10. Alignment to long-term roadmap

- **Project phase alignment:** Phase 5 / Tier 2, the **first of three Tier-2 sub-projects**
  (encryption → Cleaner → run-in-VM/mTLS) on the path to the #598 GO/NO-GO gate.
- **Use Case alignment:** UC-002 (Personal Knowledge Substrate — `substrate.db`), UC-004 (Assistant
  Orchestrator sessions — `sessions.db`), UC-001 (Policy Agent audit — #605).
- **ADR alignment:** extends ADR-018 (TPM trust root) from sign/verify to seal/unseal; this sprint
  **authors a new ADR** for the at-rest encryption envelope (early, as a design gate — §5.1 #9).
  Confirms, does not revise, ADR-016 (substrate MVP) — the store's public behaviour is unchanged.
- **DEC alignment:** executes #598 ratified Decision 2 (TPM-sealed key + offline recovery) and
  advances Decision 1 (FULL bar). Run as a DEC-15 per-tier sprint.
- **Campaign-pacing note (LA-directed, surfaced at close):** Sprint 14 stays serial and focused, but
  the SCR will carry a pacing plan showing that the *remaining* gate items — Tier-3 dependency
  pinning (#560), weight-integrity FUT-04, the runtime egress guard — are light and disjoint from the
  heavy Tier-2 work and can run as **parallel waves**, and that the Cleaner can start as soon as
  encryption merges. The intent is a visibly shortening path to #598, with the merge-gate and the
  ceremony as the explicit serialization points.

## 11. Roles and accountability

*(Standardized cf-3 role names; the template's legacy names map per CLAUDE.md §Agent-Operating-Model:
Co-Lead → Orchestrator; EA Code → specialist subagent; Sprint Auditor → Auditor.)*

| Role | Responsibility this sprint | Budget |
|---|---|---|
| **LA (Lead Architect)** | SDV sign-off; a quick look at the envelope ADR before EA-2; the **batched on-chip ceremony** (RSA seal key + dedicated ECDSA audit key + offline recovery key); **one production-posture live-verify**; #598 governance; SWAGR read. **Only the production posture counts as "works."** | \~45–60 min |
| **Orchestrator** | EA prompt authoring (one at a time); the **envelope ADR** (design gate); **merge gate** (diff-review each EA against its criterion, not just the suite); SCR; journal fold; campaign-pacing plan. | Autonomous within this SDV |
| **Specialist subagents (sonnet, worktree-isolated)** | EA execution; report fragment text (never merge, never touch `BUILD_JOURNAL.md`). | Autonomous per EA prompt |
| **Auditor** | Independent adversarial SWAGR at close. | Autonomous |

**Escalation rule:** if any EA's tests expose a *real product bug* (not a test defect), the
Orchestrator **stops and reports** to the LA rather than fixing it unreviewed.

## 12. Estimated effort

- **Rough duration:** \~1–2 days fleet-time; 5 EAs (4-deep serial spine + 1 parallel lane) + the ADR
  design gate.
- **LA active-time expectation:** \~45–60 min total — \~15 min SDV sign-off; a few min on the ADR;
  \~20–30 min the batched ceremony + one production-posture live-verify; \~10–15 min SWAGR read. (The
  ceremony + live-verify are on the LA's own schedule; build-complete targets 2026-06-07.)
- **Confidence:** **medium.** The cipher, DB wiring, and #605 are well-understood; the new CNG
  RSA-OAEP sealing primitive is the genuine unknown and sets the confidence level.
- **Correctness outranks the date.** 2026-06-07 is a target, not a deadline. If EA-1's CNG sealing or
  EA-2's envelope reveal that the design needs more time, the sprint takes it — the both-DBs + #605
  scope must never rush the crypto. The serial spine and the ADR design-gate exist to enforce this;
  this note makes the priority explicit.

## 13. Deliberate non-goals

1. **SQLCipher / transparent whole-DB encryption** — Rejected because it is a new third-party
   dependency, the supply-chain surface the air-gap minimizes (lesson 40); app-layer AES-GCM via the
   already-present `cryptography` avoids it.
2. **A passphrase-based recovery key** — Rejected: a passphrase carries forget-risk and needs a
   password-hashing KDF (a possible new dependency). The recovery key is a high-entropy random key the
   LA stores off-box (printed/USB).
3. **Encrypting low-value metadata (IDs, timestamps, indices) or `session_id`** — Rejected because it
   breaks indices/ordering/joins for no real confidentiality gain.
4. **Per-query embedding decryption** — Rejected in favour of the boot-cache: same at-rest
   protection, far less per-query cost.
5. **DEK rotation procedure** — Rejected for *this* sprint (the envelope is versioned to allow it
   later); building rotation now is unneeded scope on a focused security sprint.
6. **Pre-provisioning the #606 tail-deletion counter key in this ceremony** — Rejected; a later
   `ensure_key` is cheap and boot-safe, and #606's design is not yet fixed. Keep the ceremony to the
   3 keys actually needed.
7. **Any ingress / network capability** — Rejected; the campaign is egress-only and gated; nothing
   network-facing is touched here.

## 14. Sign-off

### Lead Architect

> I, Blair (LA), have reviewed this SDV on 2026-06-05. I approve the sprint scope, success criteria,
> and risk posture as stated. I accept that the fleet will proceed autonomously within these bounds,
> that the on-chip ceremony and one production-posture live-verify are mine, and that only the
> production posture counts as "works." I will read the SCR and SWAGR when produced.

_(Signed via the frontmatter field `la_approved_on` above. A commit authored by the LA on main is the
durable signature.)_

### Orchestrator

> The Orchestrator acknowledges the LA-signed SDV and will translate it into the EA prompt sequence
> (EA-1 → envelope ADR → EA-2 → EA-3 → EA-4, with EA-5 parallel), holding the merge gate on every
> increment. Any scope deviation arising during execution is flagged to the LA or escalated, and any
> real product bug surfaced by a test stops the line for LA review rather than an unreviewed fix.

_(Signed via the frontmatter field `co_lead_drafted_on` + the git commit that lands this SDV on main.)_

---

## Appendix A — SDV revision log

| Version | Date | Changed by | Change summary |
|---|---|---|---|
| 1 | 2026-06-05 | Orchestrator (draft) | Initial draft for LA review. |
| 2 | 2026-06-05 | LA review → Orchestrator | LA override: `substrate_chunks.source` (filename) moved INTO the cipher set via the keyed-hash-for-index pattern (HKDF-derived index subkey + AES-GCM display value); `session_id` stays plaintext. Pinned AES-GCM **nonce strategy** (fresh random 96-bit, prepended, never reused) in §5.1 #2 + criterion #3. Moved the envelope **ADR early** (design gate before EA-2; §5.1 #9, §7) to pin nonce/recovery-key/AAD. Recovery key pinned as a high-entropy **random** key (not a passphrase; §13 #2). Perf criterion #5 now measures **delta vs a pre-encryption baseline**. Added the explicit **"correctness outranks the date"** note (§12). |
| 3 | 2026-06-05 | LA review → Orchestrator | **Premise correction (LA-directed, post-signoff; scope unchanged).** Verified on disk that the stores hold only disposable dev/test scaffolding (substrate ≈107 chunks / \~400 KB; sessions ≈59 sessions / 376 turns / \~250 KB) — there is **no "decades of exposed data on disk."** Reframed §1 + §3 from "protect already-exposed data / worst-rated exposure" to "build the control before real use so real data is **born encrypted**, and meet the #598 criterion"; the sprint is **well-timed, not urgent** (zero data-exposure time pressure → correctness > date). Migration of the existing dev rows is reframed as the populated-store **test fixture** + engineering correctness, not urgent secret-protection (detailed in ADR-025 §3). Companion: ADR-025 flipped to ACCEPTED with the same premise correction, the two §2.8 rulings recorded ((a) audit refuse-to-start, folded into EA-5; (b) RSA-2048 now / attempt-3072-at-ceremony), and the live-memory vector marked DEFERRED-not-denied (roadmap §8 / #611). |
