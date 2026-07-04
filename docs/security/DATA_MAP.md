# BlarAI — Data Map (Sensitive Artifacts, Data Stores & Access Rights)

**Status:** v1 — authored 2026-06-08 as an input to the **#612 security capstone presentation** and the
**#598 air-gap GO/NO-GO** evidence pack. Portfolio surface for the IAPP AIGP track (this *is* a
data-governance "record of processing / data-flow inventory").
**Method:** three independent read-only code sweeps (trust artifacts / data stores / access-control) +
direct disk inspection (`Get-ChildItem`, `icacls`, SID resolution) on the dev box, 2026-06-08.
**Air-gap note:** nothing in this map is network-facing. Every certificate/seam below is for the
*internal* host-loopback / vsock service mesh. The air-gap stays welded; this is an inventory, not a change.

> **How to read the ACL shorthand** (Windows `icacls`): `F` = full control, `RX` = read+execute,
> `W` = write, `M` = modify. `(I)` = **inherited** from the parent folder (not set explicitly on the
> file). `(OI)(CI)` = the entry flows down to files/subfolders. A principal like `BUILTIN\Administrators`
> means *any local administrator account*; `NT AUTHORITY\SYSTEM` is the OS itself.

---

## 0. The two storage roots (at a glance)

BlarAI persists to exactly **two** locations on disk:

| Root | Path | Holds | Backed up by git? |
|---|---|---|---|
| **A — Repo trust dir** | `C:\Users\mrbla\BlarAI\certs\` | mTLS certificates + private keys, the PA JWT public key | No (gitignored; regenerated per boot) |
| **B — Runtime data dir** | `%LOCALAPPDATA%\BlarAI\` → `C:\Users\mrbla\AppData\Local\BlarAI\` | conversation history, the assistant's cross-conversation memory, the root key-store, logs, the model cache | No (user data, never in git) |

Plus two **non-file** stores:
- **The TPM 2.0 chip** — holds the *private* key material (never on disk, non-exportable).
- The **signed model manifest** lives beside the model weights under `C:\Users\mrbla\BlarAI\models\…`.

The runtime resolves Root B from the `LOCALAPPDATA` environment variable
(`services/assistant_orchestrator/src/entrypoint.py:1059-1064`; `services/ui_gateway/src/constants.py:16-27`).
The test suite redirects `LOCALAPPDATA`/`HOME`/`XDG_DATA_HOME` to a throwaway temp dir and unsets
`BLARAI_DEK_KEYSTORE` at `conftest.py:78-83`, so tests can never touch the real Root B (the guard added
after the lesson-55 incident — see §6).

---

## 1. Trust & security artifacts (Root A + TPM + manifest)

### 1a. mTLS certificates — `C:\Users\mrbla\BlarAI\certs\` (disk-verified, 10 files)

Mutual-TLS secures the internal service seam (UI Gateway ↔ Policy Agent ↔ Assistant Orchestrator ↔
Semantic Router). Certs are **regenerated every boot** from an in-memory CA whose private key is discarded
after issuance (24-hour cert lifetime) — `shared/security/cert_provisioning.py:245-390`. The producer is the
launcher's provisioning step; consumers are the per-service vsock/loopback TLS contexts
(`shared/ipc/vsock.py:181-230`).

| File (on disk) | Bytes | Role | Used by (which side presents it) |
|---|---|---|---|
| `ca.pem` | 514 | Per-boot CA public cert (validates all others) | Every service, to verify its peer |
| `pa_server.pem` / `pa_server_key.pem` | 587 / 227 | **Policy Agent server** cert+key | PA listener (the server every client connects to) |
| `orch_client.pem` / `orch_client_key.pem` | 579 / 227 | **Assistant Orchestrator client** cert+key | AO → PA |
| `gateway_client.pem` / `gateway_client_key.pem` | 579 / 227 | **UI Gateway client** cert+key | Gateway → PA |
| `router_client.pem` / `router_client_key.pem` | 583 / 227 | **Semantic Router client** cert+key | Router → PA |
| `pa_public.pem` | 178 | PA's **JWT verification** public key (ECDSA P-256) | AO + Router validate PA-minted JWTs |

Config keys: `[ipc].mtls_cert_path` / `mtls_key_path` / `ca_cert_path` per service
(`services/policy_agent/config/default.toml:38-40`, AO `:86-87`, Router `:24-25`); `[security].jwt_ca_cert_path`
→ `pa_public.pem` (AO `:76`, Router `:19`).
*The `*_key.pem` files are private keys — their contents are never read or displayed; only filenames/paths/ACLs are inventoried.*

### 1b. TPM-sealed private keys (in the chip — never on disk)

Four named keys live in the hardware TPM 2.0, non-exportable. The private halves never touch the filesystem;
only their *public* counterparts (e.g. `pa_public.pem`) or *sealed wraps* (the DEK keystore, §1d) are on disk.

| TPM key name | Purpose | Signs/seals | Public/disk counterpart |
|---|---|---|---|
| `BlarAI-PA-JWT-Signing` | Mints capability JWTs for every policy decision | ECDSA P-256 | `certs/pa_public.pem` |
| `BlarAI-DEKSeal` | Seals the Data Encryption Key (RSA-2048 OAEP) | RSA wrap | `dek_keystore.json` (the sealed wrap) |
| `BlarAI-Audit-Signing-Key-v1` | Signs each tamper-evident audit record (separate key = separation of duties) | ECDSA P-256 | — |
| `BlarAI-Manifest-Signing` | Signs the model-weight manifest (FUT-04) | ECDSA P-256 | `manifest.json.pub` |

### 1c. Signed model manifest — `C:\Users\mrbla\BlarAI\models\qwen3-14b\openvino-int4-gpu\` (disk-verified)

The integrity anchor for the model weights (FUT-04 / `require_signed_manifest=true`, live since Sprint 17).

| File | Bytes | Meaning |
|---|---|---|
| `manifest.json` | 344 | SHA-256 digests of the weight files |
| `manifest.json.sig` | 88 | ECDSA P-256 signature (created 2026-06-07 20:14 — the Sprint-17 on-chip signing ceremony) |
| `manifest.json.pub` | 178 | Public key for off-box cross-verification |

Verification: `shared/models/manifest_signer.py` → `shared/models/weight_integrity.py:load_manifest_verified()`
(double gate: signature, then digest). Fail-closed when `[security].require_signed_manifest=true`
(PA `default.toml:26`, AO `:81`).
**Coverage note:** only the **14B target model** carries a `.sig`/`.pub`. The draft models
(`qwen3-0.6b-pruned-6l/…`, `qwen3-0.6b/…`) and the legacy `qwen2.5-1.5b` each have an *unsigned*
`manifest.json` (digests but no signature) — integrity-without-authenticity for the speculative-decode draft.
This is an **accepted trust boundary**: the draft only *proposes* tokens that are verified against the signed
14B target's logits before acceptance (a tampered draft can only degrade throughput, not change the output),
and real draft-manifest signing is **deferred to #106 (FUT-04)**. *(Trust boundary documented under #637 —
see §7 item 3.)*

### 1d. Key-store files (the sealed DEK wraps) — Root B

| File (in `%LOCALAPPDATA%\BlarAI\`) | Bytes | What it is | Security boundary |
|---|---|---|---|
| `dek_keystore.json` | 480 | **Production** Data Encryption Key, **dual-wrapped**: TPM RSA-2048-OAEP **+** an offline recovery-key AES-256-GCM wrap. Never holds the plaintext DEK. | **Real** (TPM-bound) |
| `sessions.keystore.json` | 220 | **Dev-mode** ephemeral keystore for the session DB (`SoftwareSealer`) | **NOT a boundary** (stdlib obfuscation only) |
| `substrate.keystore.json` | 220 | **Dev-mode** ephemeral keystore for the memory DB (`SoftwareSealer`) | **NOT a boundary** |

Path set by `BLARAI_DEK_KEYSTORE` (default `_default_keystore_path()`,
`shared/security/provision_dek_keystore.py:93-106`). **The dev SoftwareSealer keystores are reachable ONLY in
explicit `dev_mode=True`.** In production (`dev_mode=False`) an unset `BLARAI_DEK_KEYSTORE` is a *loud
refuse-to-start* (`StoreProvisioningError`), NOT a silent fall-back to the weak path — the SoftwareSealer
branch is gated behind `elif dev_mode:` in both store factories, and `build_envelope` independently rejects a
SoftwareSealer outside dev_mode (`DevModeSealerError`). *(Sprint-18 C5 asserts the DBs open under the TPM DEK;
#637 confirmed the two refuse-to-start guards are sufficient and added no third — see §7 item 4.)*

---

## 2. Sensitive data stores (Root B)

| # | Store | Path | Contains | Sensitivity | Encrypted at rest? | Scheme + key |
|---|---|---|---|---|---|---|
| 1 | **Session store** | `%LOCALAPPDATA%\BlarAI\sessions.db` (SQLite) | Full conversation history — every user prompt + assistant reply, per session, with PGOV status | **CRITICAL** | **Yes** | Field-level **AES-256-GCM**, row-UUID bound into AAD; DEK from `dek_keystore.json`. `EncryptedSessionStore` (ADR-025 §2.1). Fail-closed (no plaintext fallback). |
| 2 | **Knowledge substrate = the assistant's long-term memory** | `%LOCALAPPDATA%\BlarAI\substrate.db` (SQLite) | Semantic chunks + embeddings of (a) ingested documents and (b) PGOV-approved past conversation turns — **the cross-conversation memory** (see §3) | **HIGH** | **Yes** | Per-field **AES-256-GCM** (text, embedding, source); filenames stored as a keyed HMAC-SHA256 hash so dedup works on ciphertext; same DEK. `EncryptedSubstrateStore` (`services/assistant_orchestrator/src/substrate.py:362+`). |
| 3 | **Adjudication audit log** | `services/policy_agent/data/audit/adjudication_audit.jsonl` (default; `[security].audit_log_path` override) | Every policy decision (CAR hash, verb, resource, sensitivity, ALLOW/DENY/ESCALATE), hash-chained | **CRITICAL** (forensic) | **No — signed, not encrypted** | Tamper-evident chain: SHA-256(canonical‖prev) + **ECDSA P-256 TPM** signature (prod) / HMAC-SHA256 (dev). `shared/security/audit_log.py`. **Disk note:** file **absent** today → no adjudications persisted yet. |
| 4 | **Secrets store (Kagi key)** | `%LOCALAPPDATA%\BlarAI\secrets\kagi_api_key.dpapi` | The Kagi web-search API key | **HIGH** (credential) | **Yes** | Windows **DPAPI** (machine+user bound; undecryptable off-box). `shared/secrets/dpapi_store.py:54`. **Disk note:** `secrets\` dir **absent** today → web-search key **not provisioned**. |
| 5 | **UI prefs** | `%LOCALAPPDATA%\BlarAI\ui_prefs.json` (57 B) | UI preferences | LOW | No | Plaintext (non-sensitive) |
| 6 | **Logs** | `boot.log` (245 KB), `launcher.log` (1.3 MB), `crash.log` (1 KB) | Service start/diagnostic output | LOW | No | Plaintext diagnostics |
| 7 | **OpenVINO model cache** | `%LOCALAPPDATA%\BlarAI\ov_cache\{assistant_orchestrator,policy_agent}\…` | Compiled model blobs — incl. two \~**8.48 GB** Qwen3-14B `.blob`s + GPU kernel caches | Medium (model IP, not user data) | No | Plaintext compiled weights. **Not covered by the signed manifest** (the manifest signs the *source* weights; the compiled cache is derived, regenerated from them, and invalidated on driver/model change). Separate cache signing **rejected** (heavy + fragile). *(Trust boundary documented under #637 — §7 item 5.)* |
| 8 | **Knowledge bank (UC-002 v2, #655)** | `%LOCALAPPDATA%\BlarAI\knowledge.db` (SQLite, WAL) | Operator-curated, approval-gated knowledge documents (cleaned articles) + chunks/embeddings of APPROVED docs — pending rows hold content only; rejected rows are content-retained tombstones | **HIGH** | **Yes** | Per-field **AES-256-GCM** (`source_ref`, `title`, `byline`, `content`, chunk `text`+`embedding`); AAD binds each field to `knowledge_docs`/`knowledge_chunks` + doc_uuid (+ chunk_index); source dedup via keyed HMAC `source_hash` and the content fingerprint stored as keyed HMAC `content_sha256_keyed` — **never the plaintext content SHA-256, which was a membership oracle** (#655 LA verdict 2026-06-10; equality-leak residual accepted, ADR-025 §3). Plaintext metadata columns are deliberate and **enumerated in full below this table** (the prior "published_date is the one plaintext column" claim was false). **Same DEK** as sessions/substrate (ADR-025 §2.1); own `ensure_owner_only_dacl` at creation. Lexical index is **in-RAM FTS5 only** — never on disk. `EncryptedKnowledgeBank` (`services/assistant_orchestrator/src/knowledge_bank.py`). |
| 9 | **Ingest staging handoff** | `%LOCALAPPDATA%\BlarAI\ingest_staging\<doc_uuid>.bin` | Cleaned article content in transit gateway → AO (the IPC frame carries labels only) | **HIGH** (transient) | **Yes** | Single **AES-256-GCM** FieldCipher blob, same DEK, AAD bound to the doc_uuid (not replayable under another doc identity); dir + file DACL'd at creation; **deleted by the AO after the pending row persists** — a handoff, not a store. `shared/security/ingest_staging.py`. |
| 10 | **Ingest audit log** | `%LOCALAPPDATA%\BlarAI\audit\ingest_audit.jsonl` | Every ingest governance event (INGEST_SUBMIT→ESCALATE / INGEST_APPROVE→ALLOW / INGEST_REJECT→DENY), hash-chained; resource = doc_uuid + source-hash prefix; `car_hash` = the **KEYED content digest** (HMAC over the plaintext sha hex — never the plaintext content SHA-256, which would recreate the membership oracle in this signed-plaintext file; #655 LA verdict 2026-06-10) — **labels only, never content, never a content-derived plaintext hash** | **CRITICAL** (forensic) | **No — signed, not encrypted** (the ADR-029 ratified plaintext exception — it covers action/identity labels, never content-derived hashes) | ADR-029 primitive, **own file + own chain** (separate from the PA's adjudication log): SHA-256 chain + **ECDSA P-256 TPM** signature (`BlarAI-Audit-Signing-Key-v1`) in production / HMAC-SHA256 stub in dev; #637 owner-only DACL via the AuditLog write path. Production audit-construction failure **disables the knowledge feature loudly** (never boot-blocking). |

**Knowledge-bank plaintext columns — the complete, honest enumeration (#655 LA verdict 2026-06-10).**
Every column of `knowledge_docs` that is NOT AES-256-GCM ciphertext, each with its rationale — the earlier
claim that `published_date` was "the one deliberate plaintext metadata column" was false and is withdrawn:

| Column (`knowledge_docs`) | Form on disk | Rationale |
|---|---|---|
| `id` | Plaintext INTEGER | SQLite rowid — pure storage mechanics, carries no content. |
| `doc_uuid` | Plaintext TEXT | Random v4 UUID minted at ingest — an opaque handle, content-independent; needed plaintext for joins, AAD binding, and audit cross-reference. |
| `source_type` | Plaintext TEXT | One of `url`/`file`/`paste` — a 3-value category; reveals the ingest mode, never the source or content. |
| `provenance` | Plaintext TEXT | Trust-class label (`untrusted_external`) — for the record only; retrieval grounds everything UNTRUSTED regardless (ADR-023). |
| `approval_state` | Plaintext TEXT | `pending`/`approved`/`rejected` lifecycle state — must be queryable without the DEK (list/count/triage paths); reveals governance state, not content. |
| `published_date` | Plaintext TEXT | Deliberate: future date-scoped retrieval filtering needs it queryable; an article's publication date is weak metadata (accepted residual). |
| `word_count` | Plaintext INTEGER | Coarse size metadata for preview/listing; a rounded magnitude, not a fingerprint (accepted residual: leaks approximate document length — as does the ciphertext length itself). |
| `cleaner_version` | Plaintext TEXT | Tooling version stamp — needed for re-clean migrations; says which cleaner ran, nothing about what it cleaned. |
| `created_at` / `decided_at` | Plaintext TEXT | Lifecycle timestamps — governance evidence (when submitted/decided); reveal operator activity times, not content (same residual as every log line). |
| `source_hash` | **Keyed** HMAC-SHA256 BLOB | Dedup-over-ciphertext index — deterministic equality is the function; unforgeable/unguessable without `k_idx` (ADR-025 §3 equality-leak residual accepted). |
| `content_sha256_keyed` | **Keyed** HMAC-SHA256 BLOB | Content fingerprint, keyed form ONLY — the plaintext SHA-256 here was a membership oracle (hash any public article through the deterministic cleaner, test membership). The plaintext digest lives only in RAM for the staged-content integrity cross-check. |

`knowledge_chunks` honesty: `text` + `embedding` are AES-256-GCM ciphertext; `id` (rowid), `doc_uuid`
(opaque handle, see above) and `chunk_index` (ordinal position — reveals approved-document chunk counts,
i.e. coarse length, an accepted residual) are plaintext by the same mechanics rationales.

**Quarantine policy (not a separate store):** the encrypted DBs apply a *bulk-read soft-quarantine* — a row
that fails to decrypt (e.g. written under an old dev key) is excluded from results and logged
(`SESSION_ROW_DECRYPT_QUARANTINE` / `SUBSTRATE_ROW_DECRYPT_QUARANTINE` /
`KNOWLEDGE_ROW_DECRYPT_QUARANTINE`), never returned as plaintext, while
single-record writes stay hard-fail-closed (ADR-025 §2.7). Availability-preserving without leaking.

---

## 3. The cross-conversation memory — answered explicitly

**There is no separate "memory" module. The assistant's cross-conversation memory IS `substrate.db`**
(store #2 above), and it is **encrypted at rest** (AES-256-GCM under the TPM-sealed DEK).

How it works:
- **Within one conversation**, recent turns are held in a RAM context window
  (`services/assistant_orchestrator/src/context_manager.py`) — ephemeral, gone when the session closes.
- **Across conversations**, every PGOV-approved turn (and every ingested document) is chunked, embedded with
  `bge-small-en-v1.5` (384-dim), and written to `substrate.db`. On each new prompt, the substrate is searched
  by semantic similarity; the top matches are decrypted and re-injected as grounding context.
- So "what the assistant remembers about you between chats" = the encrypted rows of `substrate.db`. Decrypt
  requires the DEK, which requires the TPM (or the offline recovery key). The embeddings are decrypted once
  at boot into a RAM-only cache for fast search; nothing is written back in plaintext.

There is **no cloud sync, no vector DB service, no second copy** — single file, single user, on your disk.

---

## 4. Access rights — who can read these, and how it's enforced

### 4a. The actual ACLs on disk (disk-verified 2026-06-08)

| Object | Principals with access | Inherited? | Notes |
|---|---|---|---|
| **Runtime data dir** `%LOCALAPPDATA%\BlarAI\` | `SYSTEM` (F), `BUILTIN\Administrators` (F), `NORTHSTAR100\mrbla` (F) | yes | **Clean** — exactly the three expected principals |
| `dek_keystore.json` (root key) | same three (F) | yes | Readable by any local admin — but contents are TPM-wrapped (file access ≠ key access) |
| `sessions.db` (history) | same three (F) | yes | Clean |
| `substrate.db` (memory) | same three (F) | yes | Clean |
| **Repo trust dir** `…\BlarAI\certs\` + `ca.pem` + keys | the three above **PLUS an orphaned foreign SID** `S-1-5-21-76345465-2051216645-4251589009-2931813655` with **`RX,W`** | yes | ⚠️ See §4c |

**Plain-English bottom line:** your conversation history, your assistant's memory, and the root key-store are
readable by **(1) your user account, (2) any administrator on this PC, and (3) the operating system** — the
standard single-user Windows posture. Confidentiality of the *data* rests on the **encryption** (TPM-sealed
DEK), not on the file permissions, which are permissive-to-admins by default.

### 4b. Process identity (who runs the code that opens these files)

- **Host-mode (default topology):** services run as **the logged-in Windows user** (`NORTHSTAR100\mrbla`).
- **Launcher** runs **elevated (Administrator)** — `launcher/__main__.py:726`.
- **The UI child process is deliberately de-elevated to Medium integrity** (drops admin via
  `CreateRestrictedToken` + `CreateProcessWithTokenW`, `launcher/process_launch.py:184-237`, ADR-019) so the
  UI can do cloud-file/drag-drop and can't wield admin rights.
- The Policy Agent and Assistant Orchestrator do **not** drop privilege in code — they inherit the launcher
  context and rely on the mTLS + encryption boundaries rather than OS-level privilege separation.
- **Guest-mode (dormant, #615):** the Alpine Hyper-V VM would run services as a non-root user, isolated, with
  the host seam over `AF_HYPERV` vsock. Not active today.

### 4c. ⚠️ Critical finding — no code-level file-permission hardening *(RESOLVED for the sensitive files — #637, 2026-06-09)*

> **Update (#637, 2026-06-09):** this finding is now **resolved for the four sensitive files**. BlarAI sets
> an explicit owner-only DACL (current user + SYSTEM, inheritance severed) on `sessions.db`, `substrate.db`,
> `dek_keystore.json`, and the audit log at their creation sites, and strips orphaned foreign SIDs from
> `certs\` at every boot — both via `shared/security/file_dacl.py` (`SetNamedSecurityInfo`-based, owner-
> preserving + fail-safe). See §7 items 1–2. The text below is the *original* as-found finding (2026-06-08),
> retained for the record; the remaining open part is the **broader `%LOCALAPPDATA%\BlarAI\` dir-tree
> lock-down** (deferred to the pre-internet-facing / post-#556 pass), not the per-file ACLs.

**[As-found 2026-06-08] No code anywhere in BlarAI sets explicit ACLs / permissions on its sensitive files**
(verified: no `icacls`, `chmod`, `os.chmod`, `SetNamedSecurityInfo`, `FileSystemAccessRule`, `CreateFile`-with-SD in
production code). Every key, keystore, and database **inherits** the ACL of its parent directory.

Two consequences:
1. **Permissive-by-inheritance:** all sensitive files are readable by any local **Administrator** and by
   `SYSTEM`, not just by `mrbla`. On a single-user box this is functionally fine; on a shared/multi-user or
   compromised-admin scenario it is not a real confidentiality boundary. The **encryption layer is what
   actually protects the data** — the ACLs do not.
2. **Orphaned foreign principal on the cert keys:** the `certs\` tree (private keys included) carries an ACL
   entry for a SID whose domain (`76345465-2051216645-4251589009`) is **not this machine** (this box is
   `4125655822-2918122917-2734753367`; `mrbla` is `…-1001`). It **does not resolve** to any live account, so
   it grants nothing today — but it has `RX,W` and is an ACL-hygiene defect carried in from the repo's
   history. It is **absent** from the runtime data dir (which is clean). *(REMEDIATED by #637, 2026-06-09:
   `cert_provisioning.py` now strips orphaned foreign SIDs from `certs\` at every boot — §7 item 2. The next
   real boot performs the live strip; the #637 build itself did not mutate the live dir.)*

---

## 5. Encryption architecture (the key chain)

```
TPM 2.0 (hardware, non-exportable)
  └─ BlarAI-DEKSeal (RSA-2048)  ──seals──▶  dek_keystore.json  (also an offline recovery-key AES-GCM wrap)
                                                   │
                                          unseal at boot
                                                   ▼
                                   DEK (AES-256, RAM only, never written in clear)
                                                   │  HKDF-SHA256(salt="BlarAI-field-cipher", info=label)
                                                   ▼
                                   per-field subkeys ──▶ AES-256-GCM (per-field nonce + row-UUID AAD)
                                                   ▼
                                  encrypts:  sessions.db   substrate.db
```

- **Two break-glass paths to the DEK:** the TPM (normal, machine-bound) or the **offline recovery key** (held
  by the operator off-box, for hardware migration). The plaintext DEK is never persisted.
- **Audit log** is the exception — **signed, not encrypted** (forensic records need to be *verifiable*, not
  secret): ECDSA P-256 via a *separate* TPM key (`BlarAI-Audit-Signing-Key-v1`), hash-chained.
- **Kagi key** uses **DPAPI** (Windows-native, machine+user bound) rather than the DEK chain.

---

## 6. Disk-vs-design reconciliation (what is actually provisioned)

| Claim | Code/design | On disk today | Verdict |
|---|---|---|---|
| mTLS certs present | yes | 10 files, regenerated 2026-06-08 08:55 | ✅ live (per-boot) |
| Signed manifest (14B) | FUT-04 | `.json`+`.sig`+`.pub` present (signed 2026-06-07) | ✅ provisioned |
| Production DEK keystore | TPM dual-wrap | `dek_keystore.json` (480 B) present | ✅ provisioned |
| Dev SoftwareSealer keystores | dev fallback | `sessions/substrate.keystore.json` (220 B) present | ⚠️ present — confirm prod posture doesn't use them (Sprint-18 C5) |
| Audit log | `…/data/audit/…jsonl` | **absent** | ▫️ empty (no adjudications persisted yet) |
| Kagi DPAPI secret | `…/secrets/…dpapi` | **absent** | ▫️ web-search key not provisioned |
| Test isolation guard | `conftest.py:78-83` | redirects LOCALAPPDATA/HOME/XDG + unsets BLARAI_DEK_KEYSTORE | ✅ active |
| **Stale artifact** | — | `sessions.db.test-damaged.bak` (32 KB) present | ⚠️ leftover from the lesson-55 test-damage incident (housekeeping — §7) |

---

## 7. Findings & hardening candidates (for the #612 capstone — LA decisions)

These are **decisions**, surfaced not silently actioned (each changes posture / has a trade-off).
**Disposition status is tracked on Vikunja #637.** The 2026-06-09 #637 build serviced items 1, 2, 4 and
documented items 3, 5 (the per-item LA disposition is recorded below). All remain *defense-in-depth on top of
the at-rest encryption* — the encryption (TPM-sealed DEK, §5) is the confidentiality boundary; none of these
is a hole in it.

1. **No explicit DACL hardening on Root A/B.** Candidate: lock `%LOCALAPPDATA%\BlarAI\` and `certs\` to
   `mrbla` only (`icacls … /inheritance:r /grant:r mrbla:F`). **Trade-off:** must not break the de-elevated
   Medium-integrity UI's access, the launcher (SYSTEM/admin), or hardware-migration. Defense-in-depth on top
   of encryption, not a replacement.
   **→ DONE (#637, 2026-06-09) — code-level, owner-preserving, fail-safe.** A new helper
   `shared/security/file_dacl.py::ensure_owner_only_dacl(path)` sets a *protected* (inheritance-severed) DACL
   granting full control to ONLY the current user + `SYSTEM` and removing every inherited / other ACE. It is
   invoked at each sensitive file's creation site: `sessions.db` (`session_store.py`, both store variants),
   `substrate.db` (`substrate.py`, both variants), `dek_keystore.json` (`dek_envelope.py::DekEnvelope.save`,
   the single chokepoint for every keystore write incl. the provisioning + recovery ceremonies), and the
   adjudication audit log (`audit_log.py`, once on first write). **Two load-bearing guarantees:**
   *owner-preserving* — the helper only ever removes access for *other* principals, so the running app (which
   runs as the current user) can never be locked out of its own files (this is what makes "no live-verify"
   safe); and *fail-safe* — on any failure (non-Windows, pywin32 missing, permission error, bad input) it
   LOGS a warning and returns `False`, never raising and never blocking file access (the file then keeps its
   prior inherited ACL, the pre-#637 behaviour). Scope note: the helper hardens *individual files* at their
   creation sites; it does **not** re-DACL the parent `%LOCALAPPDATA%\BlarAI\` dir tree (the original
   `icacls /inheritance:r` candidate) — that broader dir-tree lock-down, which must be reconciled against the
   de-elevated Medium-integrity UI + launcher SYSTEM/admin access, is **deferred to the pre-internet-facing /
   post-#556 hardening pass** where file-perm hygiene matters more. Unit-tested against TEMP files/dirs only
   (`shared/tests/test_file_dacl.py`, 30 tests) — never run against live `%LOCALAPPDATA%` data.
2. **Orphaned foreign SID on `certs\`** (`S-1-5-21-76345465-…`, `RX,W`, non-resolving). Candidate: strip the
   orphaned ACE. Low risk (grants nothing live), but it's an audit-trail blemish a reviewer will flag.
   **→ DONE (#637, 2026-06-09) — code-level, owner-preserving, fail-safe.**
   `shared/security/file_dacl.py::strip_foreign_sids_from_dir(dir)` removes ACEs whose SID is neither the
   current user, nor a well-known/builtin principal (SYSTEM, LOCAL/NETWORK SERVICE, Administrators, Users,
   Everyone, CREATOR OWNER, Authenticated Users, AppContainer `S-1-15-*`), nor resolvable to a live local
   account via `LookupAccountSid` — i.e. it strips an orphaned foreign SID while preserving every legitimate
   principal (same owner-preserving + fail-safe invariant as item 1; it does *not* sever inheritance, only
   removes the foreign ACEs — least surprise for the cert tree). It is wired into
   `cert_provisioning.py::provision_per_boot_certs`, which runs every boot, so the remediation is
   **self-healing** without a manual operator step. Unit-tested against a temp dir carrying a synthetic
   `S-1-5-21-76345465-…` ACE (`test_file_dacl.py`) — the live `certs\` dir was **not** mutated by this build
   (the next real boot's cert-provisioning step performs the live remediation).
3. **Draft-model manifests unsigned.** Only the 14B target is signature-covered; the spec-decode draft
   (`qwen3-0.6b-pruned-6l`) has digests but no `.sig`. Candidate: extend FUT-04 signing to the draft.
   **→ TRUST BOUNDARY DOCUMENTED (#637, 2026-06-09); signing DEFERRED to #106 (FUT-04).** The draft model's
   integrity rests on the **SHA-256 digests in its (unsigned) `manifest.json`** — *integrity without
   authenticity*. The threat this leaves open is narrow: an attacker who can already write to the model
   directory could substitute a draft with matching-but-malicious content only if they also rewrote the
   unsigned digest file. **Why this is acceptable today:** (a) the speculative-decode draft only *proposes*
   tokens — every draft token is verified against the signed 14B target model's logits before acceptance, so
   a tampered draft cannot change the output distribution, only degrade throughput (a correctness-preserving
   role, not an authority role); (b) the box is air-gapped and single-user, so write access to the model dir
   already implies host compromise; (c) extending the on-chip ECDSA P-256 manifest-signing ceremony to the
   draft (+ legacy) models is exactly the scope of **#106 (full FUT-04 weight integrity)** and belongs with
   that work, not bolted on here. **No signing implemented** by #637.
4. **Dev SoftwareSealer keystores coexist with the production DEK.** If `BLARAI_DEK_KEYSTORE` is unset at
   runtime, the *weak* dev keystores (`sessions/substrate.keystore.json`, stdlib obfuscation) could become the
   active path. **Sprint-18 C5 (production posture) asserts the on-disk DBs open under the TPM DEK, not the
   SoftwareSealer** — this map turned that into a concrete C5 check.
   **→ MITIGATION CONFIRMED (#637, 2026-06-09); no new guard added — would be redundant.** The
   production-posture guard already exists, **fail-closed, in two independent places**, and is tested:
   (a) **the store factories refuse to start** — `session_store.py::build_session_store` /
   `make_encrypted_session_store` and `entrypoint.py`'s substrate factory both raise `StoreProvisioningError`
   when `dev_mode=False` AND `BLARAI_DEK_KEYSTORE` is unset (a non-`:memory:` db_path); the SoftwareSealer
   path is gated behind an explicit `elif dev_mode:` branch and is unreachable in production (ADR-025 §2.8(a));
   (b) **`dek_envelope.py::build_envelope` / `DekEnvelope.create`** independently raise `DevModeSealerError` if
   a `SoftwareSealer` is passed without `dev_mode=True`. So a missing keystore in production is a *loud refuse*,
   never a silent fall-back to the weak path. Tests: `tests/security/test_production_posture.py` (in the
   standing gate) executes the runtime divergence — production raises, dev succeeds with a SoftwareSealer —
   plus the per-store `test_session_store_encryption.py` / `test_substrate_encryption.py` /
   `test_field_cipher_and_dek_envelope.py` locks. **A third guard was deliberately NOT added** (over-engineering
   — the LA disposition was "add one only if low-risk; otherwise document why the existing C5 assertion is
   sufficient"). The residual is purely the *coexistence* of the dev keystore files on disk, which is harmless
   given the two refuse-to-start guards. *(The dev `*.keystore.json` files are SoftwareSealer artefacts — NOT
   a security boundary; see §1d. They are inventory-only, not deleted, per the never-destructive rule.)*
5. **OpenVINO cache holds compiled weights unsigned** (`ov_cache\…\*.blob`, \~8.48 GB each). The signed
   manifest covers source weights, not the derived compiled cache. Candidate: document the trust boundary
   (cache is regenerated from verified source) or extend integrity to the cache.
   **→ TRUST BOUNDARY DOCUMENTED (#637, 2026-06-09); separate signing REJECTED (heavy + fragile), DEFERRED.**
   The OpenVINO compiled cache is a **derived artifact**: it is regenerated by the OpenVINO runtime from the
   **signed source weights** (the 14B manifest's `.sig`, §1c) on first load, and the runtime **invalidates and
   rebuilds it on any driver-version or model change**. Its integrity therefore *derives* from the
   source-manifest signature plus the deterministic rebuild — a tampered cache blob is either (a) rebuilt away
   on the next driver/model delta, or (b) at worst a denial-of-service / crash, not a path to executing
   attacker-chosen weights (the source weights are signature-gated). **Separately signing the cache is
   rejected:** it is heavy (two \~8.48 GB blobs to hash/sign on every rebuild), fragile (the cache key is
   opaque to us and changes with driver/runtime internals, so a signature would constantly invalidate), and
   buys little over the source-manifest gate. **No signing implemented** by #637; revisit only if the cache
   ever moves off the air-gapped single-user box.
6. **Housekeeping (not a posture decision):** `sessions.db.test-damaged.bak` is a leftover from the lesson-55
   incident; the audit log + Kagi secret are simply not provisioned yet. Inventory only — **not deleted**
   (cleanup = document, per the never-destructive rule); the operator decides removal.

---

## 8. Scope & maintenance

**Covered:** every on-disk persistence location for trust artifacts and user data, their access rights
(actual ACLs), process identity, and the encryption chain, as of 2026-06-08.
**NOT covered (named, not implied):** in-RAM secrets during runtime (the unsealed DEK, the decrypted embedding
cache) are out of scope for an *at-rest* data map; the TPM's internal key hierarchy is hardware-attested, not
file-inspectable; network data-in-transit is N/A (air-gapped, internal mTLS only). Multi-machine/migration
posture is a forward concern (the recovery-key path exists but no rotation procedure is deployed).
**Maintenance:** regenerate from the same method (3 sweeps + `icacls`) whenever a store, key, or path changes;
this doc is a #598/#612 evidence artifact — keep it in sync the way `SECURITY_ROADMAP` and `TEST_GOVERNANCE`
are kept in sync.

**Refs:** `shared/security/file_dacl.py` (#637 — owner-only DACL + foreign-SID strip),
`shared/security/cert_provisioning.py`, `shared/security/dek_envelope.py`,
`shared/security/provision_dek_keystore.py`, `shared/security/audit_log.py`,
`services/ui_gateway/src/session_store.py`, `services/assistant_orchestrator/src/substrate.py` &
`…/entrypoint.py:1050-1138`, `shared/secrets/dpapi_store.py`, `conftest.py:78-83`;
`shared/tests/test_file_dacl.py` (#637 tests); `tests/security/test_production_posture.py` (C5 / §7-item-4
guard); ADR-018 (signing), ADR-019 (de-elevation), ADR-025 (at-rest encryption). Gate: **#598**;
presentation: **#612**.
