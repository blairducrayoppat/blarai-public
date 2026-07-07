# ADR-025: At-Rest Encryption — App-Layer AES-GCM under a TPM-Sealed DEK + Offline Recovery Key

**Status:** ACCEPTED — 2026-06-05 (Sprint 14 / Tier-2; design gate cleared at the LA checkpoint, 2026-06-05)
**Author:** Orchestrator (Claude Opus 4.8, 1M context) for Lead Architect (Blair) review
**Related:** ADR-018 (TPM 2.0 trust root — this **extends** it from sign/verify to seal/unseal),
ADR-021 (TPM-sealed PA JWT key — the ceremony + fail-closed-until-ceremony posture this mirrors),
ADR-016 (Personal Knowledge Substrate — the store being encrypted), ADR-023 (provenance/content-trust).
Roots in the 2026-06-03 security audit **Domain 7** (plaintext data at rest). Tracks Vikunja **#559**
(Tier-2 umbrella), **#598** (GO/NO-GO Decision 2 — TPM-sealed key + offline recovery), the Sprint-14
SDV. Consumes the **EA-1** sealing primitive `shared/security/tpm_sealer.py` (merged `fe9cc6f`).

---

## 1. Context

The 2026-06-03 audit's worst-rated finding (Domain 7) is architectural: the two stores **designed to
hold decades** of the User-Operator's private data — `substrate.db` (the personal knowledge store:
document text + 384-dim embeddings) and `sessions.db` (every conversation turn + the prompt-derived
session titles) — are **plaintext SQLite by design**, with no at-rest protection. Critically, this is a
gap to close **before** real data exists, not an active exposure of it: verified on disk (2026-06-05),
the stores today hold only build-phase **dev/test scaffolding** — `substrate.db` ≈ 107 chunks
(\~400 KB), `sessions.db` ≈ 59 sessions / 376 turns (\~250 KB) — and BlarAI has **never been used in a
daily setting**. There is no "decades of exposed private data on disk" (an earlier premise this ADR,
the SDV, the roadmap, and the review chain all inherited without checking; corrected here).

The value of encrypting **now**, ahead of any real use, is therefore *not* "protect already-exposed
data" — nothing sensitive is exposed yet. It is twofold: (1) build the at-rest control before daily use
begins, so every byte of real data is **born encrypted from its first write — there is never a
plaintext window on disk**; and (2) satisfy the #598 GO/NO-GO criterion ("at-rest encryption on, with a
tested recovery path"). The threat this defends — a stolen disk or a leaked backup yielding readable
content — becomes real the moment real data lands; shipping the control first means it never lands in
the clear. #598 Decision 2 ratified the mechanism: encrypt at rest under a **TPM-sealed key with an
offline recovery key**. The sprint is well-timed, not urgent: with no sensitive data on disk, there is
**zero data-exposure time pressure**, which is exactly why correctness outranks the target date.

EA-1 has already shipped the sealing primitive (`TpmSealer`: a non-exportable RSA-2048 OAEP-SHA256 key
that wraps/unwraps a symmetric key, fail-closed, with a `SoftwareSealer` stub for off-TPM tests —
merged `fe9cc6f`). This ADR records the **envelope and field-cipher design** that EA-2 builds on top of
that primitive, and it is the **design gate**: the cryptographic specifics below (nonce discipline,
recovery-key nature, AAD binding, key separation) are the kind of choices that are silently wrong far
more often than loudly wrong, so they are pinned and LA-reviewed *before* a line of cipher code is
written.

## 2. Decision

**App-layer AES-256-GCM field encryption** of the sensitive columns, under a **single
Data-Encryption Key (DEK)** that is **dual-wrapped** (TPM seal + offline recovery key), with
**HKDF-separated subkeys** and **per-field fresh-nonce + AAD** discipline. No new dependency
(`cryptography`, already present, provides AES-GCM + HKDF; the TPM path is EA-1's stdlib-CNG sealer).

### 2.1 One DEK, dual-wrapped (the envelope)

A single high-entropy random **DEK** (256-bit, from a CSPRNG) encrypts every at-rest field across both
DBs. The DEK is wrapped **twice**, producing two independent wrap records that each unwrap the *same*
DEK:

1. **TPM wrap (daily path):** `TpmSealer.seal(DEK)` — RSA-2048 OAEP-SHA256 against the non-exportable
   TPM key (EA-1). The private key never leaves the chip.
2. **Recovery wrap (break-glass):** the DEK encrypted under the **offline recovery key** (§2.5).

On boot the DEK is unwrapped via the TPM. If the chip/key is unavailable (dead chip, hardware
migration), the recovery key unwraps the same DEK. The DEK is **never** written to disk in cleartext.

**Rejected alternative — per-DB or per-field keys.** A key-management explosion (multiple wraps,
multiple ceremony artifacts) with no real benefit at single-user scale; one DEK with disciplined
subkey derivation (§2.2) gives separation without the bookkeeping.

### 2.2 The sealed DEK is a pure master — subkeys via HKDF

The DEK is **never used directly** for any cryptographic operation. Two purpose-bound subkeys are
derived from it with **HKDF-SHA256** (in `cryptography`; no new dependency):

- `k_enc = HKDF(DEK, info="blarai-field-enc-v1")` — the AES-256-GCM field-encryption key.
- `k_idx = HKDF(DEK, info="blarai-index-mac-v1")` — the HMAC key for deterministic index/dedup columns
  (the keyed-hash-for-index pattern, §2.4 / SDV §5.1 #4).

A weakness or misuse confined to one role cannot cross to the other, and the sealed master stays clean.

**Rejected alternative — use the raw DEK for both AES-GCM and the index HMAC.** Key reuse across two
purposes is the kind of thing an auditor flags on sight; HKDF separation is free here.

### 2.3 Field cipher: AES-256-GCM, fresh CSPRNG nonce per encryption

Every field encryption is AES-256-GCM under `k_enc` with a **fresh random 96-bit nonce drawn from a
CSPRNG** (`os.urandom` / `secrets.token_bytes`) — **never** the stdlib `random` module, never a fixed,
counter, or derived nonce. The blob is self-describing: `nonce(12) || ciphertext || tag(16)`.

This is the single most load-bearing rule in the ADR. **GCM nonce reuse under one key is
catastrophic** — it breaks confidentiality *and* authentication simultaneously. Because we ship ONE
DEK (hence one `k_enc`) across many thousands of fields, nonce uniqueness is the entire safety margin,
and the *source* of randomness — a CSPRNG, not `random` — is the guarantee. The
repeated-plaintext→distinct-ciphertext test (EA-2) is supporting evidence, not the guarantee.

**Re-key trigger (documented):** the birthday bound for random 96-bit nonces is ≈ 2³² encryptions
under one key before collision probability becomes non-negligible. At single-user scale
(thousands–low-millions of fields across decades) this is effectively never; it is nonetheless the
documented threshold to rotate the DEK. The envelope is versioned to allow that (§2.6).

**Rejected alternatives.** A fixed/derived/counter nonce (reuse risk — the catastrophe above).
ChaCha20-Poly1305 (cryptographically fine, but AES-GCM via the already-present `cryptography`, with
AES-NI on the Lunar Lake CPU, is the natural choice; no reason to diverge).

### 2.4 AAD binds each ciphertext to its row identity

Each AES-GCM encryption sets **AAD = `table | column | natural-row-identity`**, so a ciphertext
authenticated for one (row, column) cannot be silently relocated to another — a cut-and-paste / swap
attack on the raw DB is detected as an authentication failure.

The binding identity **must be known at insert time**. For `sessions.db` that is the row UUID (the
turn id / session id, generated before insert). For `substrate.db`, `substrate_chunks.id` is
`AUTOINCREMENT` (unknown pre-insert), so AAD binds to the **natural key**
`kind | source_hash | session_id | chunk_index`.

**Recommend ADOPT** (cheap defense-in-depth; lower priority than the nonce). **Floor / fallback:** if
EA-2/EA-3 hit a case where a stable row identity is genuinely unavailable at insert, the documented
fallback is column-level AAD (`table | column`) — still better than none. **Rejected:** no AAD (leaves
ciphertext relocatable between rows/columns).

### 2.5 The offline recovery key: high-entropy random, off-box, not a passphrase

The recovery key is a **high-entropy random key** (256-bit) generated during the ceremony, surfaced
**once**, and stored **off-box by the LA** (printed and/or on a USB) — never on the running disk. It
wraps the *same* DEK as a second, independent unwrap path: the break-glass for a dead chip or a
hardware migration, which is the decades-lifespan guarantee #598 Decision 2 demands.

**Recovery (dead chip):** on a new machine the operator supplies the recovery key → it unwraps the DEK
→ the DBs decrypt → the DEK is re-sealed to the new TPM. The **ceremony runbook** (EA-2 / ceremony
deliverable, SDV criterion #6) specifies the exact non-developer steps and the key's printed format.
A recovery path that is untested or unusable by a non-developer does **not** satisfy #598's "tested
key-recovery path" — so the runbook + an automated recovery-unwrap test are gating, not optional.

**Rejected — a passphrase.** A passphrase needs a password-hashing KDF (Argon2/scrypt — a likely new
dependency, which the whole approach exists to avoid) and carries forget-risk over a decades horizon.
#598 Decision 2 already chose "offline recovery key"; a random key is its faithful, dependency-free
realization. **Rejected — TPM-only (no recovery):** chip death = total, irreversible data loss;
excluded by Decision 2.

### 2.6 Rotation is designed-for, not built

Each wrap record and each field blob carries a **version byte** (envelope-version / cipher-version) so
a future DEK rotation or algorithm change is a format-compatible migration rather than a break.
Building the rotation *procedure* is out of scope this sprint (SDV §5.2); the version field is the only
rotation cost paid now.

### 2.7 Fail-closed posture — the control is the absence of a fallback

Mirrors ADR-021 §2.3 exactly:

- If the TPM cannot unseal the DEK at boot **and** no recovery key is supplied → the store **refuses to
  open**. There is **no plaintext fallback**, ever. That absence *is* the control.
- The `SoftwareSealer` (EA-1) is a **dev/test stub only**. The production store factory **must refuse**
  to construct with a `SoftwareSealer` outside an explicit, loud dev/test mode (EA-2 enforces this —
  EA-1 deliberately left the enforcement to the consuming factory and said so in its docstring).
- Like ADR-021, the path is **configured-but-dormant** until the ceremony: production fail-closed until
  the operator provisions the keys on the host.

**§2.7 Amendment — Bulk-read quarantine posture (2026-06-06, Sprint 15 #618)**

The original posture above — "fail-closed on any decrypt failure" — was correct for the
*boot gate* (refuse to start without a valid DEK) and for *single-record callers* (a user
explicitly requested one record; a loud failure is right). But applied uniformly to **bulk
reads** (`list_sessions`, `get_session_turns`, `_backfill_empty_titles`), it produces a
**self-inflicted availability DoS**: one legacy or tampered row aborts the entire operation,
denying access to every other session in the store. Availability is a security property
(CIA triad); treating it as subordinate to an over-applied fail-closed rule is itself a
security defect.

**Corrected posture — differentiated by read shape:**

- **BULK reads** — **session store** (`list_sessions`, `get_session_turns`,
  `_backfill_empty_titles`) and **substrate store** (`_load_embed_cache`,
  `_search_kind` text + source decrypt): when a per-row decrypt fails, the row is
  **quarantined** — excluded from the result set, and a `WARNING`-level structured log
  event with a stable code is emitted (row id + reason). Session store uses
  `SESSION_ROW_DECRYPT_QUARANTINE`; substrate store uses
  `SUBSTRATE_ROW_DECRYPT_QUARANTINE`. After each loop, if ≥1 row was quarantined, a
  count-summary `WARNING` is emitted. Plaintext is **never** returned from a bad row;
  tampered data is **never** trusted. The quarantine event makes a bad row *more* visible
  than a store-wide crash (greppable, auditable, countable) while preserving access to all
  good rows. For the substrate embedding cache specifically, a quarantined row is absent
  from `_embed_cache` and therefore never scored in any subsequent query.

- **SINGLE-RECORD callers** — session store (`set_title_if_empty`, `update_session_title`,
  the leaf helpers `_dec_session_title` / `_dec_turn_content`) and substrate store
  (ingest/write paths, any single-record decrypt): **retain hard fail-closed**. The caller
  named that one record explicitly; a loud RuntimeError or `FieldCipherError` is the
  correct signal. This differentiates transient/legacy-key bulk noise from a targeted
  single-record operation where the error is actionable.

**Typical trigger for this path:** the dev→production key transition. Practice-era sessions
were encrypted under the dev SoftwareSealer key; the production TPM-sealed DEK correctly
refuses them with AES-GCM InvalidTag. Without this amendment the first `list_sessions`
call after the key rotation bricks the app on every boot. With the amendment those legacy
rows are silently quarantined while the production rows (and all new rows) are served
normally.

**What does NOT change:**
- The boot gate: if the DEK cannot be unsealed, the store refuses to open.
- The SoftwareSealer production ban.
- The no-plaintext-fallback rule: a quarantined row is simply absent, not decrypted under
  a fallback key or returned as garbage.
- Single-record hard fail-closed.

### 2.8 LA decisions — ruled at this gate (2026-06-05)

Both items were ruled by the LA at the design-gate checkpoint:

- **(a) Production audit-log posture — RULED: REFUSE-TO-START.** In production, if the audit TPM key is
  unprovisioned or the TPM is unavailable, the Policy Agent **refuses to start** rather than running
  without an audit log. Rationale (LA): a PA authorizing actions with **no audit trail** in production
  is a governance hole; "tamper-evident audit stream live" is a #598 criterion; and this makes the
  audit log **symmetric** with the encryption fail-closed posture (§2.7) — fail-closed-loud, not
  silent-degrade. This makes the audit path intentionally *stricter* than `_build_jwt_minter`'s
  degrade-to-None; the divergence is deliberate. It never falls back to the forgeable stub in
  production. **Placement: folded into the #605 / audit work (EA-5), not the cipher EA.**
- **(b) RSA seal key size — RULED: RSA-2048 in code now; attempt RSA-3072 at the ceremony, adopt if the
  chip supports it.** EA-1 shipped **RSA-2048** (112-bit; universally TPM-supported; secure through
  \~2030+); RSA-3072 (128-bit) is more future-proof *if* the reference STMicro TPM supports it (not
  universal across TPM 2.0 chips). On the record (LA): the RSA size is a **minor knob, not the
  decades-hedge** — it only **wraps** the DEK. Long-term confidentiality rests on the **AES-256 DEK**
  (a large margin even against Grover) and the **versioned envelope's ability to re-wrap the DEK under a
  stronger or post-quantum algorithm later** (§2.6). Adopting 3072 at the ceremony is a one-line
  `_RSA_KEY_BITS` change + OAEP-max recompute.

## 3. Consequences

**Positive.** Because the control ships **before BlarAI's first real use**, every byte of real data is
**born encrypted** — there is never a plaintext window on disk. A stolen disk yields **pure ciphertext**
for the high-value content — document text, embeddings (closing the embedding-inversion / vec2text
semantic-shadow leak), filenames, conversation text, and session titles. The decades-lifespan data
survives chip death via the recovery key. No new dependency is added (the supply-chain surface the
air-gap minimizes stays flat). The trust root (ADR-018) extends naturally from signing to sealing.

**Limits (on the record).**
- **Plaintext in RAM during operation — DEFERRED, not denied.** The DEK and decrypted fields (and the
  embedding search-matrix) necessarily live in memory while the app runs, so code-execution on the live
  machine or a cold-boot RAM extraction could read them. This is a *different* threat from the at-rest /
  stolen-disk model this ADR defends — out of scope for that model **by design, not dismissed**. It is
  captured on the long-term roadmap (`SECURITY_ROADMAP_air_gap_removal.md` §8 / Vikunja #611) and is
  revisited when the threat model extends (post-network-facing, #556). Candidate mitigations to evaluate
  then: **Intel Key Locker** (AES keys held as CPU-internal handles, available on the Lunar Lake class)
  and **minimized key residency** (zeroize keys/fields after use; unload the embedding-cache when idle).
- **Metadata and `session_id` stay plaintext** (row IDs, timestamps, `kind`, `chunk_index`, `role`,
  `pgov_status`, `is_active`). Low value; encrypting them breaks indices/ordering/joins for no real
  confidentiality gain.
- **The keyed-hash index leaks equality.** `HMAC(k_idx, source)` is deterministic, so two identical
  filenames produce the same index value. This reveals "these two chunks share a source," not the
  source itself — an accepted, documented residual (it is the price of keeping uniqueness/dedup working
  on ciphertext).

**Operational.** Boot pays a one-time DEK unseal + a one-time embedding-cache decrypt (both measured —
SDV criterion #5, recorded to `PERFORMANCE_LOG.md` + `docs/performance/` as deltas vs the
pre-encryption baseline). A fresh machine cannot read the DBs until the ceremony runs (or the recovery
key is supplied) — by design (§2.7).

**Migration of existing rows (right-sized, not urgent).** The dev/test rows already on disk (§1) are
**encrypted in place** as the natural populated-store fixture for the verification (§4 / SDV criterion
#1): encrypt the existing \~107 chunks + 376 turns, then prove raw-read = ciphertext, retrieval
equivalence, dedup-on-ciphertext, and a whole-file scan finding **no leftover plaintext** (a
VACUUM/scrub after the in-place rewrite). This exercises the migration path as **engineering
correctness and a free real-shaped test**, *not* urgent secret-protection — there is no sensitive data
to rescue (§1). The same migration logic is what a future real toggle or DEK rotation (§2.6) would use.
Because the dev data is disposable, the LA may alternatively choose to **wipe the dev DBs and start
fresh born-encrypted** when daily use begins; either path is valid and the migration logic exists
regardless (a non-blocking LA call, surfaced at the ceremony).

## 4. Verification

- **Headless (EA-2/3/4, software-stub sealer, default suite):** raw-file no-plaintext (text /
  embedding / filename) + retrieval-equivalence vs the pre-encryption baseline + re-ingest-dedup on
  ciphertext + repeated-plaintext→distinct-ciphertext (fresh-nonce) + DEK dual-unwrap (TPM stub and
  recovery key unwrap the *same* DEK) + wrong-key / TPM-unavailable fail-closed + recovery-path
  round-trip + the production factory refusing a `SoftwareSealer`. Full suite green.
- **On-chip (`@slow`):** real-TPM seal/unseal of the DEK; RSA key provisioned non-exportable.
- **Live (LA, Tier-2 checkpoint — the only "works"):** the batched ceremony provisions the RSA seal
  key + the dedicated audit key + generates and the LA stores the offline recovery key; one
  production-posture boot (`dev_mode=false`, real keys) confirms the DBs are ciphertext at rest +
  decrypt live, the recovery key decrypts on a simulated dead-chip, and the audit chain TPM-verifies.
  dev-mode green never counts (TEST_GOVERNANCE §2.5).

## 5. Trust anchor (recorded at ceremony — 2026-06-05)

The batched on-chip ceremony was run by the LA on the deployment host (Intel Lunar Lake, real TPM 2.0)
on 2026-06-05, and the production-posture live-verify passed: both stores are ciphertext at rest (an
independent raw-column scan found 0 plaintext on the real DBs), the recovery key was generated once and
stored off-box, and the app is functional through decrypt-on-read. Trust anchor (public material +
identifiers only — no secrets):

- **RSA seal key** `BlarAI-DEKSeal` — present and non-exportable on the TPM (confirmed via
  `tpm_sealer.key_exists`). `tpm_sealer` exposes no public-key export, so a direct SPKI fingerprint is
  not recorded for the seal key; the DEK keystore hash below anchors the envelope it produced.
- **DEK keystore** (`%LOCALAPPDATA%\BlarAI\dek_keystore.json`) — SHA-256
  `23a7454866e23ffc7c3daebad9f25db86e40266f63126fa354e254215e0b7448` (the dual-wrap records; the DEK
  itself is never written in clear).
- **Audit signing key** `BlarAI-Audit-Signing-Key-v1` — public SPKI SHA-256
  `d0b25ce119b2533b6948301ca4d3ce79843c527960abf8865ffa55e16bd5a5d6`.
- **Offline recovery key** — generated once, surfaced once, stored off-box by the LA (confirmed);
  never written to disk or recorded here.
- Recorded 2026-06-06 at sprint close.

Note: the audit key is provisioned, but the Policy Agent uses the dev HMAC signer until the
dev-mode-off flip (a later Tier-2 step); the at-rest **encryption** is the production-live piece this
sprint delivered.
