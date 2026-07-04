# ADR-031 — UC-002 Substrate v2: The Layered Knowledge Bank

**Status:** ACCEPTED 2026-06-10 (Lead-Architect-ratified at the #655 program comprehension gate).
Stage A builds the store, IPC, AO wiring, and retrieval; the ingest front door is ADR-030.
**Deciders:** Lead Architect (blarai); Orchestrator (facilitation).
**Builds on:** ADR-016 (the Substrate MVP this matures — its deferral discipline is the pattern §8
follows), ADR-025 (+ §2.7 amendment — the DEK envelope, field cipher, AAD, and decrypt-quarantine
posture every byte of this store lives under), ADR-023 (provenance is not trust), ADR-013 (the
Layer-1/2 defenses retrieval re-enters through), ADR-029 (the tamper-evident audit primitive L3
instantiates).
**Relates to:** ADR-030 (UC-003 Cleaner v1 — the ingest pipeline that feeds this store), Vikunja
#655 (program), `Use Cases_FINAL.md` §002 (the full Substrate spec this is the second slice of).

## Context

ADR-016 shipped the Substrate MVP: `substrate.db`, chunked + embedded documents and approved turns,
brute-force cosine retrieval, encrypted under ADR-025. It is conversational memory, and it works.
What it is not is a **curated knowledge bank**: it has no provenance column, no approval state, no
source-type, no lexical retrieval, and a known embedding-quality defect — chunks are 2048 chars
(~512 tokens, `substrate.py:79`) but embedded through the PGOV leakage detector's
`max_input_length=128` (`pgov.py:582,680`), so roughly three quarters of every stored chunk does not
inform its vector. bge-small-en-v1.5 natively supports 512 tokens.

UC-003 (ADR-030) needs a destination: a store where externally-sourced documents are held pending,
approved deliberately, retrievable by meaning AND by exact term, and auditable for decades. This ADR
records that store's design — a layer model, a sibling database, the embedding fix, hybrid
retrieval without a plaintext index on disk, and the posture decisions — and names what stays
deferred, following ADR-016 §3's discipline: divergence from the full UC-002 spec is recorded, never
silent.

## Decision

### 1. The layer model (L0–L5)

The knowledge bank is designed as explicit layers, so each future maturation step (multi-VM, ANN,
retention) replaces a layer instead of refactoring a blob:

- **L0 — Quarantine (pending).** A submitted document is a `knowledge_docs` row with
  `approval_state='pending'`: cleaned content + metadata held encrypted, **no chunks, no
  embeddings**, invisible to retrieval. Pending is the ADR-030 §6 ingest-quarantine state; nothing
  is indexed before the operator decides. (Cost accepted: approval pays the chunk+embed work at
  decision time, keeping rejected documents from ever consuming index work.)
- **L1 — Canonical record.** The approved document's cleaned text + metadata is the canonical
  encrypted record: `source_ref`, `title`, `byline`, `content` are AES-256-GCM field-encrypted
  blobs; `source_hash` is a `keyed_index` HMAC for dedup-over-ciphertext (the ADR-025 §2.4 / Sprint-14
  pattern); the at-rest `content_sha256` is stored **keyed** — `cipher.keyed_index` over the digest,
  the same HMAC primitive — never the plaintext digest, because a plaintext content hash in a stolen
  DB is a **membership oracle** (hash a candidate article, compare, confirm what the operator
  stored); together with `cleaner_version` it pins what was approved and what produced it;
  `published_date`, `word_count`, timestamps, and state stay plaintext metadata (the ADR-025
  metadata-plaintext line, unchanged — labels, never content-derived values).
- **L2 — Rebuildable indexes.** Everything derived is rebuildable from L1: the vector index
  (`knowledge_chunks` — encrypted chunk text + encrypted 384-dim embeddings, brute-force cosine over
  the in-RAM decrypted cache, the existing substrate pattern), the **in-memory FTS5 lexical index**
  (§4), and the catalog (`knowledge_meta`: `embed_model`, `embed_dim=384`, `embed_max_tokens` —
  recording the CONFIGURED embed window bound at store construction (512 today) — and
  `schema_version=1`; the ADR-016 §2.4 detectability pattern). A stored-vs-current
  `embed_max_tokens` mismatch on reopen **refuses retrieval loudly** rather than serving
  mixed-depth results. Losing an index loses nothing; L1 rebuilds it.
- **L3 — Provenance + audit.** `source_type` (`'url'|'file'|'paste'`, CHECK-constrained) and the
  `provenance` column record where a document came from — **for the record, never for trust**
  (ADR-023; §5 below). Every submit/approve/reject is appended to an AO-side tamper-evident audit
  chain: the ADR-029 `AuditLog` primitive with its **own file**
  (`%LOCALAPPDATA%\BlarAI\audit\ingest_audit.jsonl`) and own chain — verbs `INGEST_SUBMIT` /
  `INGEST_APPROVE` / `INGEST_REJECT`, resource = `doc_uuid` + a source-hash hex prefix, **labels
  only, never content**. The decision mapping, as implemented: `INGEST_SUBMIT` → **ESCALATE** (the
  document is held for human review), `INGEST_APPROVE` → **ALLOW**, `INGEST_REJECT` → **DENY**.
  Two events
  are deliberately NOT audited (named carve-outs, not omissions): the `already_ingested` dedup
  verdict and the dedup-replace DELETE — neither changes a state decision, and the source's
  original records remain the chain entries for that content. Ordering is **AUDIT-FIRST**: the
  audit record is appended BEFORE the bank mutation commits; a mutation failure after a successful
  append is compensated with a best-effort DENY/`_FAILED` record, so the chain never shows an
  unresolved ALLOW. The `car_hash` field carries the **keyed** content-digest hex (the same
  `cipher.keyed_index` value L1 stores at rest), never the plaintext SHA-256. **Rejected
  alternative, named (LA verdict 2026-06-10):** carrying the plaintext digest under the ADR-029
  ratified-plaintext carve-out — rejected because that carve-out covers action/identity *labels*,
  never content-derived hashes, and a plaintext digest in the audit file would recreate the very
  membership oracle the L1 keying closes. Signer mirrors the PA construction
  (`services/policy_agent/src/entrypoint.py:1086,1101`): `TpmRecordSigner`
  (`'BlarAI-Audit-Signing-Key-v1'`) in production, `HmacSha256Signer` in dev_mode. A separate file
  rather than the PA's adjudication log keeps the PA's chain adjudication-shaped (its schema is
  hash-canonical; ADR-029 warned against casual schema mutation) and gives ingest its own
  independently-verifiable history. This is the AO's **first** audit emission — a deliberate
  precedent, scoped to ingest decisions.
- **L4 — Retrieval surface.** Hybrid retrieval (§5) over `approval_state='approved'` rows ONLY,
  grounded into the prompt via `ContextManager.add_grounded_context`
  (`context_manager.py:225`) **as UNTRUSTED content with datamarking — always**. Stored provenance
  never upgrades trust: an article the operator approved last year is still attacker-authored text
  (ADR-023; BUILD_JOURNAL lesson 13; the ADR-016 §2.3 posture extended to curated knowledge).
  Knowledge retrieval joins the prompt path beside `_substrate_retrieve` (`entrypoint.py:1238`) with
  its own `retrieve_k` budget and the same skip-when-document-loaded heuristic
  (`entrypoint.py:1489`).
- **L5 — Lifecycle.** APPROVE: chunk (2048/256 chars, reusing `substrate.chunk_text`) → embed at 512
  tokens → insert chunks → flip state + `decided_at`. REJECT: flip state, **content retained** as a
  tombstone — what was rejected and when is itself governance evidence; a retention/purge policy for
  tombstones is **deferred-but-named** (it is a destruction-of-evidence decision, ADR-029-shaped,
  for the LA when real usage exists). Re-embed migration: §3. Export/backup tooling:
  **deferred-but-named** (the DEK envelope's recovery key covers key loss; document-level export is
  a future lifecycle feature).

### 2. A sibling `knowledge.db` — not new rows in `substrate.db`

The knowledge bank is a **new sibling encrypted SQLite store** at
`%LOCALAPPDATA%\BlarAI\knowledge.db`, NOT new kinds in `substrate_chunks`:

- `substrate_chunks` has `CHECK(kind IN ('doc','turn'))` — SQLite cannot alter a CHECK constraint, so
  extending it means a full table rebuild of the live store for no structural gain.
- The two stores have **different lifecycles**: substrate rows are disposable conversational memory
  (ADR-016 §2.4 called the side-file "cleanly separable and disposable"); knowledge rows are curated,
  audited, approval-gated documents. Coupling their schema couples their migrations forever.
- The **one-DEK rule holds** (ADR-025 §2.1): `knowledge.db` encrypts under the SAME DEK envelope as
  `sessions.db`/`substrate.db` — same `derive_subkeys`/`FieldCipher` stack
  (`shared/security/field_cipher.py:117,158,280`), AAD per field via
  `make_aad_for('knowledge_docs', column, doc_uuid)` and
  `('knowledge_chunks', column, doc_uuid|chunk_index)` (app-generated `uuid4` PKs, the sessions.db
  stable-identity pattern, since `doc_uuid` is known before insert). No new key, no new ceremony.
- Operationally it registers like every sensitive store: `ensure_owner_only_dacl` immediately after
  creation (#637 pattern, `shared/security/file_dacl.py`) + its own row in
  `docs/security/DATA_MAP.md` §2 (the §8 maintenance rule).
- Read/write posture inherits ADR-025 §2.7 exactly: bulk reads decrypt-quarantine
  (skip-log-never-plaintext), writes hard fail-closed.

### 3. The 128→512 embedding fix, and why PGOV's 128 stays

Knowledge embeddings are produced at **`max_length=512`** — the model's native budget, covering the
full 2048-char chunk — via a **new method** on the shared embedder (e.g. `embed_documents`) rather
than by changing the `LeakageDetector` default. **PGOV's 128-token path is untouched**: the Stage-5
leakage thresholds were calibrated at 128, and byte-identical behavior on that path is a named
regression requirement — an embedding change there silently re-tunes a security control. One model,
one stack (ADR-016 §2.1) is preserved; only the truncation budget differs per consumer.

The **existing `substrate.db`** gets the same quality fix via a **re-embed migration utility**: a
runnable module that decrypts each chunk's text (under the live DEK), re-embeds at 512, re-encrypts
the new vector, and bumps `substrate_meta` (`embed_max_tokens`) so the change is detectable — the
ADR-016 §2.4 mechanism doing exactly the job it was built for. The LIVE substrate's embedding
binding **follows `substrate_meta.embed_max_tokens`**: 128 when the key is absent (pre-ceremony
behavior unchanged), 512 after the re-embed ceremony stamps it — so the single-depth outcome is
self-enforcing rather than a convention; the migration stamps the meta key **only on a zero-error
run** (a partial re-embed never advertises the new depth). The migration is executed **manually
on the live box** by the operator (it needs the real DEK and the real model), never by tests; tests
exercise it with a stub `embed_fn`. Accepted consequence: re-embedding shifts similarity scores, so
retrieval behavior on old memories changes once, deliberately, at migration time — the alternative
(two embedding depths coexisting in one store indefinitely) is a permanent quality fork.

### 4. No plaintext index on disk — in-memory FTS5, rebuilt at unlock

Lexical retrieval is real (exact terms, names, rare tokens — the UC-002 "BM25 lexical fallback"
need), but **FTS5 indexes plaintext, and no plaintext derivative of encrypted content is ever
written to disk** (the Sprint-14 strict-residuals posture; an on-disk FTS5 index would be a
plaintext shadow of the ciphertext store). The decision: an **in-memory SQLite FTS5 index** — a
`':memory:'` connection with an `fts5` virtual table over decrypted chunk text +
`doc_uuid`/`chunk_index` refs — built at DEK-unlock alongside the existing decrypted-embedding boot
cache (the same pattern, extended from vectors to text), and **incrementally updated on approve**.
FTS5 is compiled into the project Python (probe-verified 2026-06-10: SQLite 3.45.1,
`CREATE VIRTUAL TABLE ... USING fts5` succeeds on `.venv`).

**Accepted trade-off:** RAM proportional to the approved corpus and added unlock latency for the
rebuild — both fine at personal scale today, both **measured later on-box** (the
`tests/substrate_benchmark/` instrument + `PERFORMANCE_LOG.md`, per the testing-data rule) rather
than estimated now. Rejected: a plaintext FTS5 file on disk (the posture violation above); a
keyed-token index (HMAC per term — deterministic token-level equality leakage across the whole
corpus, a far worse residual than the existing per-source `keyed_index`, and no BM25 ranking);
encrypted-FTS-page schemes (no in-repo primitive, real complexity, same RAM at query time).

### 5. Hybrid retrieval — reciprocal-rank fusion

A query runs both limbs: brute-force cosine over the in-RAM decrypted embedding cache (the existing
substrate pattern) and FTS5 BM25 over the in-memory lexical index. Results merge by
**reciprocal-rank fusion** (`score = Σ 1/(k + rank)`, **k=60** — the standard constant), top-k
chunks returned with their document metadata. RRF over score-normalization because cosine and BM25
scores are incommensurable; rank fusion needs no calibration, has one transparent constant, and
degrades gracefully when either limb returns nothing. Retrieval reads `approval_state='approved'`
ONLY (L0/tombstone rows are invisible), and everything retrieved enters the prompt as untrusted,
datamarked grounded context (L4).

### 6. The encrypted staging-file handoff — content never rides the IPC frame

The gateway→AO envelope is hard-capped at 64 KB (`DEFAULT_MAX_MESSAGE_BYTES = 65_536`,
`shared/ipc/protocol.py:38`, enforced at encode, send, and receive). Article-sized content does not
ride it. Instead, cleaned content crosses processes via an **encrypted staging file**:
`%LOCALAPPDATA%\BlarAI\ingest_staging\<doc_uuid>.bin` — a `FieldCipher` blob under the SAME DEK,
`aad=make_aad_for('ingest_staging', 'content', doc_uuid)`, DACL'd at creation, size-capped by
`staging_max_bytes`, and **deleted by the AO after the pending row persists**. The IPC layer gains
three message types in the existing `MessageType` + `encode_*`/`decode_*` pattern
(`shared/ipc/protocol.py:41`):

- `INGEST_SUBMIT` (gateway→AO): `doc_uuid`, `source_type`, `source_ref`, `staging_path`,
  `content_sha256` (**REQUIRED — a submit without it is refused, fail-closed**; the frame carries
  the **plaintext** digest in transit — it exists for AO-side integrity verification against the
  staging file, is transient, and is never persisted; every **at-rest** copy is keyed — L1/L3),
  title/byline/date/word-count metadata, `cleaner_version` — small, references the staging file;
- `INGEST_DECISION` (gateway→AO): `doc_uuid`, `approve|reject`;
- `INGEST_RESULT` (AO→gateway): `ok`, `doc_uuid`, `state`, `chunk_count`, error code/message.

The 64 KB envelope is **untouched**. Rejected: raising `max_message_bytes` (config-raisable to 1 MB,
`default.toml:108`) — a transport-wide posture loosened for one feature, paid by every message on
the channel; the staging file keeps bulk content out-of-band (the lazily-staged-image precedent),
encrypted, and integrity-checkable (`content_sha256` verified AO-side before the row persists,
then stored keyed — L1).
Stage A ships the AO read side + a gateway-usable writer helper; the full gateway UX is Stage B.

### 7. Failure posture — feature-level fail-closed, a third named position

The AO builds the knowledge bank via `_build_knowledge_bank` beside `_build_substrate`
(`entrypoint.py:1075`) — the same three-way dev_mode / `TpmSealer` / `StoreProvisioningError` recipe,
the same `has_encryption` regression assert. Its failure posture is a deliberate **middle ground**
between the two existing positions:

- `sessions.db`: **refuse-to-start** (chat without session persistence is not BlarAI);
- `substrate.db`: **silent-degrade** (memory off, AO starts — ADR-016's non-load-bearing call);
- `knowledge.db`: **loud-disable** — a knowledge-bank construction failure (or, in production with
  knowledge enabled, an L3 audit-construction failure) **disables ingest and knowledge retrieval
  LOUDLY** (clear error frames on every ingest attempt, a startup ERROR) **but never blocks AO
  boot** — chat is unaffected.

The trade-off, named: refuse-to-start would make a curated store's absence unmissable but holds the
operator's chat hostage to a feature he may not be using that day; silent-degrade is how a curated
bank quietly stops being curated (the substrate's posture is right for best-effort memory, wrong for
a store the operator deliberately approves documents into). Loud-disable keeps the assistant
available while making the feature's absence impossible to mistake for an empty bank. The
audit-failure case is deliberately strict-side: in production, ingest without its audit trail does
not run (the ADR-025 §2.8(a) symmetry), but it degrades the *feature*, not the *boot* — the PA's
refuse-to-start is the right posture for the component whose whole job is adjudication; ingest is
one feature of the AO.

### 8. Deferred to the multi-VM transition (named, not built — the ADR-016 §3 pattern)

The full UC-002 spec was written for the multi-VM architecture. As ADR-016 did, this ADR defers the
controls whose threat model does not exist in single-process BlarAI, so the divergence is recorded,
not silent:

- **Isochronous retrieval timing** (fixed-deadline release) — defends a co-resident agent observing
  IPC latency; retrieval is an in-process call today. Re-evaluated at the multi-VM transition.
- **PA-JWT-brokered Substrate access** ("no direct API to any agent") — meaningful when the
  Substrate is a standalone VM service with multiple clients; today the AO is the only consumer,
  in-process.
- **The Cleaner three-field signature gate** (content-hash + pipeline-code-hash + timestamp,
  fail-closed at the Substrate boundary) — designed for a Substrate that must verify a *remote*
  Cleaner across a trust boundary. Today's equivalents: `content_sha256` verified at the staging
  handoff, `cleaner_version` recorded on every row, and the approval gate itself. The cryptographic
  gate lands when the boundary does.
- **HNSW/ANN + at-scale lexical** — brute-force cosine + in-RAM FTS5 hold at personal scale; the
  `_search_kind`-style private-seam discipline is kept in the new store so an ANN index slots in
  unchanged (~100K-vector rule of thumb, ADR-016 §2.5).

## Consequences

- **Positive:** BlarAI gains a curated, encrypted, audited knowledge bank with a human approval gate
  and hybrid retrieval; the embedding-truncation defect is fixed for new content and migratable for
  old; every byte at rest is born encrypted under the existing envelope (no new key, no new
  ceremony); the indexes are rebuildable; retrieval stays untrusted-by-default no matter who
  approved what; the AO gets its first tamper-evident audit emission on a precedent-setting,
  contained scope.
- **Negative / accepted trade-offs:** unlock-time index rebuild + corpus-proportional RAM (measured
  later, §4); RRF's k=60 is adopted, not tuned (revisit with real usage data); approve-time
  chunk+embed latency (operator-visible, bounded by article size); rejected tombstones accumulate
  until the deferred retention decision; the loud-disable posture means a broken knowledge bank
  leaves chat running — by design, but the operator must act on the loud signal rather than being
  forced to.
- **Regression requirements (binding on Stage A tests):** PGOV's 128-token embedding path
  byte-identical; retrieval excludes non-approved states; writes hard fail-closed / bulk reads
  decrypt-quarantine; the 64 KB envelope untouched by ingest frames; `has_encryption` asserted on
  the constructed store; tests never touch the real `%LOCALAPPDATA%` (root `conftest.py` redirect)
  and run model-free (stub `embed_fn`).

## References

`Use Cases_FINAL.md` §002; ADR-016, ADR-025 (+ §2.7), ADR-023, ADR-013, ADR-029, ADR-030;
`services/assistant_orchestrator/src/substrate.py` (`chunk_text`, `substrate_meta`, the
encrypted-store recipe), `services/assistant_orchestrator/src/entrypoint.py` (`_build_substrate`,
`_substrate_retrieve`, `_handle_connection`), `services/assistant_orchestrator/src/pgov.py`
(`LeakageDetector`, `max_input_length=128`), `services/assistant_orchestrator/src/context_manager.py`
(`Provenance`, `add_grounded_context`), `shared/security/field_cipher.py`,
`shared/security/file_dacl.py`, `shared/security/audit_log.py`, `shared/ipc/protocol.py`,
`docs/security/DATA_MAP.md` §2/§8; Vikunja #655. DECISION_REGISTER index updated in the same change
(the non-optional maintenance rule).
