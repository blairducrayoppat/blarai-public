# R7 — The relationship to BlarAI: what is extractable, what the product's threat model is, the separate repository, and what must never cross

Study: Vikunja #1549, runtime action governance for AI agents as a Windows product.
Read window: 2026-09-17 02:20–03:05 EDT (machine clock `Get-Date`: 2026-09-17 02:57:20 -04:00).
Source read: `C:\Users\mrbla\BlarAI`, `main` at `cb5d39d4` (`git log --oneline -1 main`). Read-only throughout: no file in the BlarAI tree was edited, no service started, no test run, no database opened.
Evidence grades follow RULES.md: **MEASURED** = I ran it here (command named); **REPORTED** = read in source or a document (path and line named); **derived** = my inference from what I read, labelled as such.

Acronyms, spelled out once: CAR = Canonical Action Representation (the structured record every action request is reduced to before adjudication). PA = Policy Agent. AO = Assistant Orchestrator. TPM = Trusted Platform Module. CNG = Cryptography API: Next Generation (the Windows key-storage API). PCP = Microsoft Platform Crypto Provider (the CNG provider that fronts the TPM). DACL = Discretionary Access Control List (a Windows file permission list). DPAPI = Data Protection API (Windows per-user encryption). HMAC = Hash-based Message Authentication Code. JWT = JSON Web Token. PII = Personally Identifiable Information. PGOV = Post-Generation Output Validator. ADR = Architecture Decision Record. LA = Lead Architect. SSRF = Server-Side Request Forgery. WinRT = Windows Runtime (the modern Windows API surface). AST = Abstract Syntax Tree (a parsed view of source code).

---

## 0. Outcome first

**Nine of the ten named surfaces are extractable; one is not.** Measured, not inferred: importing nine of them from the BlarAI virtual environment loads only the standard library, the named `shared.*` modules and `pydantic` — no service, no model runtime, no network client (§1.0). The tenth, the timeout registry, is a table whose every row names a BlarAI module; only its *pattern* travels.

Per-component verdict (details and line ranges in §1):

| # | Surface | Verdict | The cut, in one line |
|---|---|---|---|
| 1 | `DeterministicPolicyChecker` | **needs-cut** | Lift the 265-line class out of the 1118-line GPU-inference module; replace BlarAI's POSIX rule table and the `kagi.com` allowlist value with the product's own. |
| 2 | `shared/schemas/car.py` (CAR + `canonical_hash`) | **clean** | Copy; rename the `policy_agent` issuer default; nothing else binds. |
| 3 | `shared/security/audit_log.py` | **clean** (primitive) / needs-cut (its tests) | Rename two identity strings (genesis label, TPM key name); keep the signer as the injected interface it already is. |
| 4a | `shared/security/tpm_signer.py` | **clean** | Copy; the product passes its own key names. Machine assumption: Windows + TPM 2.0 via PCP, per-user key store. |
| 4b | `shared/security/hello_verifier.py` | **clean** (+ rebuild the helper exe) | Copy; rename the two dialog strings and the exe; ship the product's own signed `HelloVerify` helper. |
| 5 | `egress_envelope.py` (per-turn lease) | **clean** (manager) / needs-cut (production consent function) | Generalise the consent function from "web_search" to a per-tool label. |
| 6 | `shared/security/escalation_consent.py` | **clean** | Copy as-is; stdlib only, zero BlarAI imports. |
| 7 | `shared/security/egress_guard.py` | **needs-cut** | Drop the Hyper-V vsock allowance; make loopback ports explicit; add an authenticated re-arm; it governs the governor's *own* process only. |
| 8 | `shared/security/exfil_screen.py` | **needs-cut** | Its PII recognizers live inside the 1426-line PGOV module; lift ~270 lines of stdlib `re` code into their own module. Pattern lists contain no personal identifiers (checked). |
| 9 | `shared/timeout_registry.py` | **not-extractable** (data) / pattern extractable | Every row names a BlarAI module; the ~120-line registry mechanism + its gate test carry over empty. |

Two findings that matter beyond the table:

- **The CAR's "never raw user data" property is a caller promise, not a schema property.** `shared/schemas/car.py:78-81` says `parameters_schema` holds "the schema, not the values", but the AO's tool-dispatch builder (`services/assistant_orchestrator/src/entrypoint.py:361`) passes `{"args": tool_args}` — the canonical JSON of the *actual* tool arguments. A product governing third-party agents will see real arguments in every CAR, and every audit record derived from it. The product must decide, per adapter, what of the arguments is stored and what is hashed. (REPORTED, both lines read.)
- **The socket guard is a self-restriction, not a control over other processes.** It rebinds `socket.socket` and `socket.getaddrinfo` inside the process that calls `arm()` (`egress_guard.py:1064-1091`). It cannot see, let alone govern, a Claude Code or Copilot process's TLS session to a cloud model. Its value to the product is exactly that: the governor provably cannot phone home except through one door. Governing *other* processes' network is a different mechanism (Windows Filtering Platform / firewall — P3a's report), not this file.

---

## 1. Extractable components

### 1.0 The measurement behind the table

**MEASURED** (2026-09-17 ~02:50 EDT, `C:\Users\mrbla\BlarAI`, `.venv\Scripts\python.exe` = Python 3.11.9 — note: `CLAUDE.md` says 3.12; the venv on disk says 3.11.9):

```
python -X importtime -c "import shared.schemas.car, shared.security.audit_log, shared.security.escalation_consent, shared.security.egress_guard, shared.security.exfil_screen, shared.security.tpm_signer, shared.security.hello_verifier, shared.timeout_registry, shared.security.ip_block, shared.security.file_dacl; print('ok')"
```

Result: `ok`; the modules loaded from the project were exactly `shared.schemas`, `shared.schemas.car`, `shared.security`, `shared.security.{audit_log, egress_guard, escalation_consent, exfil_screen, file_dacl, hello_verifier, ip_block, tpm_signer}`, `shared.timeout_registry`, plus third-party `pydantic`. Nothing under `services.*`, no `openvino*`, no `httpx`, no `cryptography` was imported. The package `__init__.py` files are docstring-only (`shared/__init__.py`, `shared/security/__init__.py`, `shared/schemas/__init__.py`, `services/*/__init__.py`, `services/*/src/__init__.py` — REPORTED, read).

`services/policy_agent/src/gpu_inference.py` was **not** imported (it would attempt `openvino_genai`); its dependency closure was read statically with an AST scan (MEASURED, `python -c` over `ast.parse` of the twelve files; classification: stdlib / BlarAI-internal / third-party). Third-party licences were read from the venv's package metadata (MEASURED, `importlib.metadata`):

| Package | Version | Licence |
|---|---|---|
| pydantic / pydantic-core | 2.12.5 / 2.41.5 | MIT |
| cryptography | 46.0.5 | Apache-2.0 OR BSD-3-Clause |
| pywin32 | 311 | PSF |
| PyJWT | 2.11.0 | MIT |
| httpx | 0.28.1 | BSD-3-Clause |
| openvino / openvino-genai | 2026.2.1 / 2026.2.1.0 | Apache-2.0 |

First-commit data below is from `git -C C:/Users/mrbla/BlarAI log --format='%h %ad %an %s' --date=short -- <path> | tail -3` (MEASURED). Test counts are `grep -c '^\s*\(async \)\?def test_'` per file (MEASURED); "BlarAI coupling hits" is a grep of each test file for `launcher|default.toml|kagi|LOCALAPPDATA|BlarAI-|from services.|entrypoint` (MEASURED — a proxy for whether the test would move unchanged; I name the actual imports where they decide it).

### 1.1 `DeterministicPolicyChecker` — `services/policy_agent/src/gpu_inference.py:349-613`

| Item | Reading |
|---|---|
| Size | Class: lines 349–613 (265 lines) of an 1118-line module. |
| What it is | A class-method rule table run over one CAR: returns `("DENY", rule)`, `("ESCALATE", rule)` or `None` (proceed). Deny rules run first; any deny short-circuits. Wrapped in `try/except Exception → ("DENY","DENY_EXCEPTION")` (line 612–613). |
| Rules (lines) | `DENY_NULL_CAR` (497); RULE 1 `DENY_RESTRICTED_PATH` over raw + `posixpath.normpath` candidates with prefixes `/proc/ /system/ /etc/ /var/log/`, `/certs/` (with `ESCALATE_CERT_RENEWAL` for `/certs/renew/`), `/home/` outside `/home/user/` (365–367, 519–526); RULE 2 `DENY_EXFILTRATION` — NFKD-normalised parameters containing `/tmp/export/` (529–532); RULE 3 `DENY_EXTERNAL_NETWORK` over `https|http|wss|ws|ftp|ftps|gopher` schemes, with the ADR-027 §2 carve-out: an `http(s)` URL whose host is in the allowlist returns `None` (534–557); RULE 4 `DENY_AUTHORITY_CLAIM` regex (`pre-approved`, `security team author…`, `authorization bypass`) (381–384, 560–561); RULE 5 `ESCALATE_CROSS_AGENT_OWNERSHIP` (564–566); RULE 6 `ESCALATE_INFRA_CONFIG_WRITE` (`/internal/` + WRITE) (569–570); RULE 7 `ESCALATE_LARGE_WRITE` (>100 000 000 bytes) (575–579); RULE 8 `ESCALATE_UNVERIFIED_CODE` (`*_verified: false`) (584–590); RULE 9 `ESCALATE_CRYPTO_MATERIAL` (`/keystore/ /pki/ /tls_config/`, `*.pem`, `*.key`, named key files) (599–607); RULE 10 `ESCALATE_CROSS_AGENT_PATH` (`/<x>-agent|orchestrator/(config|inbox|logs|schedule|pipeline)/`) (613–620 region, 601–610). |
| Inputs | `car: CanonicalActionRepresentation`, keyword `egress_allowlist: frozenset[str] | None` (None → class default `_EGRESS_ALLOWLIST = frozenset({"kagi.com"})`, line 392). |
| Dependencies of the class body | stdlib `re`, `json`, `posixpath`, `unicodedata`, `logging`, `typing.ClassVar`, `urllib.parse.urlsplit` (lazy, 432); BlarAI: `shared.schemas.car` (`ActionVerb`, `CanonicalActionRepresentation`). It uses **nothing else** in its host module — not the constants, not `SharedInferencePipeline`, not OpenVINO. (REPORTED: read 349–613 in full.) |
| Dependencies of the host module | Top-level: `services.policy_agent.src.constants`, `shared.constants` (`DRAFT_MODEL_OV_PATH` …), `shared.inference.shared_pipeline` (→ optional `openvino_genai`), `shared.models.weight_integrity` (→ `manifest_signer` → TPM), plus a guarded `import openvino_genai` (72). This is why the class must be *cut out*: importing it today drags the model-loading stack. |
| Is it separable? | **Yes — cleanly.** Copy lines 349–613 into a new module with `car.py`. What must move *with* it: `car.py`. What must move *and change*: (a) `_EGRESS_ALLOWLIST` — the value `kagi.com` is BlarAI's live posture (activated 2026-07-02, #719) and is pinned by `tests/security/test_doctrine_freshness.py` and eval cases `gov-pf-007/gov-adj-008`; the product's allowlist is user/policy data, never a class constant. (b) `_RESTRICTED_PREFIXES` and the `/home/user/`, `/internal/`, `/certs/` conventions are POSIX paths from BlarAI's guest-VM world; a Windows product needs `C:\Windows\`, `%APPDATA%`, registry hives, `%USERPROFILE%\.ssh`, browser profile dirs, and so on — the *shape* (deny-then-escalate, raw+normalised candidates, fail-closed catch-all) carries; the *table* does not. (c) RULE 5/10's agent-naming convention (`*-agent`, `orchestrator`) is BlarAI's. |
| Callers today | `services/assistant_orchestrator/src/entrypoint.py:303-372` `_adjudicate_tool_dispatch` (builds a CAR per tool call, runs the checker in-process; `web_search` carries the real Kagi endpoint URL as its resource); `services/ui_gateway/src/url_adjudicator.py:197-267` (URL ingest). Both are what the product's per-adapter "hook → CAR → check" path will look like. |
| A sibling worth more to the product | `services/policy_agent/src/rule_engine.py` (355 lines; stdlib + `car.py` + `config_loader.ResourceDenyRule`) is the *data-driven* stage: structural, sensitivity, an ACL matrix, a sliding-window rate limiter, `fnmatch` resource deny lists loaded from `services/policy_agent/config/acl_matrix.toml` and `deny_list.toml`. A product needs policy as data, not as a hard-coded class; the engine shape is there. [PROPOSED aside; not in the question's list.] |
| BlarAI coupling summary | The `kagi.com` value; POSIX path table; agent-name regex; the host module's model stack; the `logger.info` egress carve-out message. No config keys are read by the class itself. |
| Tests that lock it | `services/policy_agent/tests/test_gpu_inference.py::TestDeterministicPolicyChecker` (class at lines 541–1025): **49 tests**; `tests/security/test_egress_screen.py`: 24 tests, 11 calling `DeterministicPolicyChecker.check` (the carve-out / off-list-deny mechanism), imports `build_car` too; `services/ui_gateway/tests/test_url_adjudicator.py` 27 (through the URL adjudicator); `services/assistant_orchestrator/tests/test_retrieval_tools.py` 55 (11 references); `tests/pa_quality_benchmark/test_pa_benchmark.py` 34; `tests/security/test_doctrine_freshness.py` 19 (2 references — pins the kagi posture). |
| Carry-over | The 49 dedicated tests carry with an import-path rewrite **except** those asserting BlarAI values (`kagi.com` default, `/certs/`, `/home/user/`) — roughly the RULE 1 and carve-out-default subsets; the 11 carve-out tests in `test_egress_screen.py` carry once `build_car` moves. Doctrine-freshness and benchmark tests do not carry (they are BlarAI's). |
| First commit | Class introduced `3b6d008f 2026-03-05 Blair "Task 4.9c: deterministic pre-filter + ESCALATE refinement"` (MEASURED, `git log -S`). File: `fdfbf925 2026-02-24 Blair` (ADR-010); 25 commits touch the file. |
| Verdict | **needs-cut** (extract class; replace rule table + allowlist value; keep engine shape and fail-closed contract). |

### 1.2 `shared/schemas/car.py` — the CAR and `canonical_hash()`

| Item | Reading |
|---|---|
| Size | 197 lines. |
| Imports | stdlib `hashlib`, `json`, `datetime`, `enum`, `typing`; third-party `pydantic` (MIT). **Zero** BlarAI-internal imports (MEASURED, AST scan; importtime loads only `pydantic`). |
| Contents | `ActionVerb` (READ/WRITE/EXECUTE/DELETE/QUERY/DISPATCH/EGRESS, 33–45); `Sensitivity` (48–59); `CanonicalActionRepresentation` (62–139): `source_agent`, `destination_service`, `verb`, `resource`, `parameters_schema: dict`, `sensitivity` (required, no default — "UNCLASSIFIED triggers Fail-Closed"), `timestamp`, `request_id`, `session_id`; `canonical_hash()` (111–130): SHA-256 over `json.dumps(sort_keys=True, separators=(",",":"))` of `{source_agent, destination_service, verb, resource, parameters_schema, sensitivity}` — timestamp/request_id/session_id excluded, for replay detection and dedup; `is_complete()` (132–139); `AdjudicationDecision` (142–147); `DecisionArtifact` (150–197) — the JWT payload (`car_hash`, `decision`, `deterministic_pass`, `probabilistic_pass`, `confidence`, `expiry_seconds=5`, `issuer="policy_agent"`). |
| BlarAI coupling | Field-description strings only ("mTLS CN", "NPU probabilistic classifier", issuer default `policy_agent`). The `destination_service` field is microservice-shaped; for a product it maps naturally to "adapter / target application". |
| The caveat that matters | The privacy claim in the module docstring ("CARs never contain raw user data") is not enforced by the type: `parameters_schema: dict[str, Any]` accepts anything, and the AO passes the real tool arguments (§0). `canonical_hash()` therefore hashes user content; fine for dedup, but an audit record that stores the CAR fields stores the arguments. |
| Companion builder | `services/policy_agent/src/car.py` (70 lines; `build_car(...)` mints a `uuid4` request id; imports only `car.py`). Trivially extractable. First commit `650f0363 2026-02-23`. |
| Tests | `shared/tests/test_car.py` **9 tests** (5 references to `canonical_hash`; 0 coupling hits — carries unchanged); `services/policy_agent/tests/test_car.py` 11 (via `build_car`; carries with the builder); `canonical_hash` also exercised in `tests/integration/test_p110_end_to_end.py` (48 tests, 20 references — BlarAI end-to-end, does not carry), `services/policy_agent/tests/test_integration_car_pipeline.py` (24), `test_jwt_minter.py` (38), `shared/tests/test_jwt_validator.py` (53). |
| First commit | `650f0363 2026-02-23 Blair "feat: Phase 3 UI — TUI Shell + Transport Gateway"`; 2 commits total (second: `bd8c3780 2026-04-17`). `canonical_hash` present since the first (MEASURED, `git log -S`). |
| Verdict | **clean.** Copy with a new package name; change the issuer default; decide the arguments-vs-schema policy at the adapter boundary. |

### 1.3 `shared/security/audit_log.py` — hash-chained, segmented, signed audit log

| Item | Reading |
|---|---|
| Size | 1559 lines. |
| Imports | Top-level stdlib only: `gzip`, `hashlib`, `hmac`, `json`, `logging`, `os`, `threading`, `abc`, `datetime`, `pathlib`, `typing`. Lazy BlarAI: `shared.security.tpm_signer` (inside `TpmRecordSigner.sign/verify`, 265, 277) and `shared.security.file_dacl` (inside DACL hardening, 879, 1091 — which itself lazily imports pywin32). No third-party at top level. |
| Signer interface | `RecordSigner` (172–196): `sign(bytes)->bytes`, `verify(bytes, sig)->bool`, `signer_id()->str` (written into every record). `HmacSha256Signer` (198–227): stdlib HMAC-SHA256, `key_id` default `"dev-stub"`. `TpmRecordSigner` (229–288): ECDSA P-256 through `tpm_signer` with key name default `AUDIT_TPM_KEY_NAME = "BlarAI-Audit-Signing-Key-v1"` (114); `ensure_key` lazily on first sign; unavailability raises `TpmRecordSignerError` — never falls back. |
| Chain | `GENESIS_HASH = sha256(b"BlarAI-audit-log-genesis-v1")` (109). `AuditRecord` (299–408) fields: seq, timestamp, `car_hash`, decision, verb, resource, sensitivity, source_agent, request_id, `prev_hash`, `record_hash`, signature, signer_id; `_canonical_bytes` (409–451). Segmented retention (ADR-029): active `audit.jsonl` rotates at 64 MiB / 100 000 records into `audit-{first}-{last}-{UTC}.jsonl.gz`, anchored by `audit-segments.jsonl` (`SegmentEntry` 477–559, signed summary); retention ceilings default off; a prune is itself a signed `RETENTION_PRUNE` record. |
| `verify()` | 1427–1526. Default (fast): verify the signed segment-index anchor chain, then the active segment end-to-end from the last sealed head. `full=True`: additionally gunzip and walk every sealed record. Raises `AuditChainError(index, reason)` at the first break. A `signer=` argument lets a verifier use a different key (rotation). |
| Load path | `AuditLog.__init__` (599–665) → `_load_segment_index` (667) → `_load_existing` (689, reads only the active file; restores chain head from its last record or the index) → DACL-hardens an existing file. `from_path` (1534–1559), `in_memory` (1529). Write: `_write_record` (891–916) appends a JSON line, `flush`+`fsync`, raises `AuditSinkError` on OSError — fail-closed on write. |
| BlarAI coupling | Two identity strings (genesis label, TPM key name); the record vocabulary is the CAR's; the DACL helper needs pywin32 and is fail-safe (never raises, never blocks writes — `file_dacl.py:36-43`, REPORTED). No config keys are read here; the factories read them: PA `services/policy_agent/src/entrypoint.py` ~990–1110 (`[security].audit_log_path`, `audit_max_active_bytes`, `audit_max_active_records`, `audit_archive_max_bytes`, `audit_archive_max_age_days`, `audit_hmac_key_id`, `dev_mode`; production refuses to start without a path or a provisioned TPM key — ADR-025 §2.8(a)); AO ingest log `entrypoint.py:5703-5769` at `%LOCALAPPDATA%\BlarAI\audit\ingest_audit.jsonl`. Dev HMAC key material is *derived*, by design recomputable: `sha256(b"BlarAI-audit-hmac-stub-v1::" + path)` (PA 1095–1099), `b"BlarAI-ingest-audit-hmac-stub-v1"` (AO 5741, 5765). |
| Tests | `shared/tests/test_audit_log.py` **62 tests** — but it imports `HybridAdjudicator`, `build_car` and `gpu_inference` (lines 46–48), so a subset drives the adjudicator seam and does not carry unchanged; `shared/tests/test_tpm_record_signer.py` 27 (1 `@hardware`; 18 coupling hits — key names); `services/policy_agent/tests/test_entrypoint.py` 15 and `tests/integration/test_production_boot_integration.py` 6 exercise the factory (BlarAI's). |
| First commit | `17adf05f 2026-06-05 Blair "tamper-evident hash-chained audit sink"`; TPM signer swap `871ced7b` and refuse-to-start `4c71aad9` the same day; 5 commits. |
| Verdict | **clean** for the primitive (rename two strings, keep the injected signer, keep DACL optional); the product writes its own factory (its own path root, its own key name, its own "no TPM" policy — §2). Tests: carry the pure-primitive subset; rewrite the adjudicator-seam subset against the product's adjudicator. |

### 1.4a `shared/security/tpm_signer.py` — TPM-backed signing

| Item | Reading |
|---|---|
| Size | 307 lines. |
| Imports | Top-level stdlib `hashlib`, `logging`, `sys`, `typing`. Lazy stdlib `ctypes`/`ctypes.wintypes` (`ncrypt.dll`), `struct`. Lazy third-party `cryptography` **only** in `export_public_key_pem` (270–296) to emit a SubjectPublicKeyInfo PEM. Zero BlarAI imports. |
| Windows APIs used (REPORTED, 63–101) | `NCryptOpenStorageProvider("Microsoft Platform Crypto Provider")`, `NCryptCreatePersistedKey(…, "ECDSA_P256", key_name, 0, NCRYPT_OVERWRITE_KEY_FLAG)`, `NCryptFinalizeKey`, `NCryptOpenKey`, `NCryptSignHash`, `NCryptVerifySignature`, `NCryptExportKey("ECCPUBLICBLOB")`, `NCryptDeleteKey`, `NCryptFreeObject`. Flags: `NCRYPT_SILENT_FLAG 0x40`, `NCRYPT_OVERWRITE_KEY_FLAG 0x80`. `NCRYPT_ALLOW_EXPORT` is never set → private key non-exportable (asserted by `shared/tests/test_tpm_signer.py`, per the docstring). No `NCRYPT_MACHINE_KEY_FLAG` is passed → keys land in the **per-user** key store (derived from the flags; Microsoft's documented default). Hardware note in code: PCP rejects `NCRYPT_SILENT_FLAG` on `NCryptDeleteKey` ("verified on hardware", 248–250). |
| Key names | None in this module. Callers name them (all `BlarAI-…`; full list in §4). Signing = SHA-256 then ECDSA; verification uses the persisted key on the same machine; `export_public_key(_pem)` exists for off-box verification. |
| Machine assumptions | Windows (`sys.platform == "win32"`, else `TpmUnavailable`); a TPM 2.0 reachable through PCP; the calling Windows user's key store. On a VM without a virtual TPM, or a PC where PCP is unavailable, `is_available()` is False and every operation raises — fail-closed, by design. **Product consequence:** the product must decide what a no-TPM machine gets (refuse, or a software key that is honestly labelled weaker) — BlarAI's production answer is "refuse to start" (`entrypoint.py:1060-1093`). That is a decision for the LA, not a defect. |
| Tests | `shared/tests/test_tpm_signer.py` 5 (2 `@hardware`), `test_tpm_record_signer.py` 27, `test_tpm_sealer.py` 21, `test_manifest_signer.py` 11, `test_ceremony_preflight.py` 24, `test_provision_signing_key.py` 7 (the latter three are BlarAI ceremony surfaces). The 5 signer tests carry unchanged (1 coupling hit = a key-name string). |
| First commit | `68a12af3 2026-06-03 Blair "TPM 2.0 trust root — ADR-018, hardware-verified signing primitive"`; 2 commits. |
| Verdict | **clean.** |

### 1.4b `shared/security/hello_verifier.py` — Windows Hello presence verifier

| Item | Reading |
|---|---|
| Size | 322 lines (+ helper `tools/hello_verify/Program.cs` 145 lines, `HelloVerify.csproj` targeting `net8.0-windows10.0.19041.0`, `OutputType Exe` — REPORTED). |
| Imports | stdlib `logging`, `pathlib`, `subprocess`, `threading`, `typing`; BlarAI: `shared.security.escalation_consent` (`ApprovalResult`, `EscalationContext`). No third-party, no Python WinRT binding. |
| Windows API | WinRT `Windows.Security.Credentials.UI.UserConsentVerifier.CheckAvailabilityAsync` / `RequestVerificationAsync`, reached by spawning the C# helper with `subprocess.run([exe, message])` (argv form, no shell; `--check` for availability). Exit code is the contract: **0 is the only "yes"**; the helper enumerates `DeviceNotPresent`, `NotConfiguredForUser`, `DisabledByPolicy`, `DeviceBusy`, `Canceled`, `RetriesExhausted`, `UnexpectedError` as distinct non-zero codes (`Program.cs:33-50`). |
| Key names / strings | No keys. Product-identity strings: dialog prefixes `"BlarAI — approve escalated action? …"` / `"BlarAI — allow this outbound web search? …"` (286–288); default exe path `tools/hello_verify/bin/x64/Release/net8.0-windows10.0.19041.0/BlarAI.HelloVerify.exe` (`HELLO_EXE_REL`, 81–84; the launcher passes an absolute path). Timeouts: verify 125 s, check 15 s (92–93) — the outer consent harness bounds at 120 s. |
| Machine assumptions | Hello configured for the *current user* (PIN counts as Hello); the helper exe present and executable; the .NET 8 Windows runtime available to it (whether the helper is published self-contained was **not verified**). `is_available()` is cached per process. |
| Fail-closed paths (REPORTED, 150–225) | Missing exe → deny; timeout → subprocess killed, deny; `OSError`/any exception → deny; any non-zero exit → deny with the code in the reason. |
| Tests | `shared/tests/test_hello_verifier.py` **25 tests** (patches `subprocess.run`; 1 coupling hit — the default path constant) — carries unchanged; `tests/integration/test_no_new_raw_spawn_sites.py` 8 (a BlarAI spawn-site lock). |
| First commit | `b65f1c59 2026-06-09 Blair "[#649] Windows-Hello biometric ESCALATE approval verifier"`; 2 commits. |
| Verdict | **clean** — rename strings and exe; the product must build, sign and ship its own helper (or, if the product shell is .NET, call `UserConsentVerifier` in-process and keep this module's fail-closed mapping). |

### 1.5 `services/assistant_orchestrator/src/egress_envelope.py` — the per-turn lease

| Item | Reading |
|---|---|
| Size | 273 lines. |
| Imports | Top-level stdlib only (`json`, `logging`, `collections`, `dataclasses`, `typing`). Lazy BlarAI: `shared.security.escalation_consent` inside `request_egress_fingerprint` (252). |
| Model (REPORTED, 93–214) | `EgressEnvelopeManager` keyed by session id. `begin_turn(session_id, N)` arms an envelope (N clamped ≥ 1). `gate(session_id, query, consent_fn)`: no envelope → DENY ("wiring bug"); envelope latched denied → DENY without re-prompt; otherwise a fresh consent is required when `searches_since_fingerprint == 0` or `>= N`; `consent_fn` raising or returning falsy → latch denied + DENY; approval opens a window (`=1`); within the window → allow, no re-touch (the caller must disclose each query in chat). `retain_only(active_ids)` (#801) drops envelopes of reaped sessions. `EgressDecision(allowed, fingerprinted, reason)` carries labels only. |
| Production consent function | `request_egress_fingerprint` (227–273): builds an `EscalationContext(rule_label="EGRESS_WEB_SEARCH", action_summary="Search the web: <query> (one approval covers up to N searches…)", tool_name="web_search", source="egress")` and routes through `request_escalation_consent` — one verifier registry, one fail-closed harness. |
| Config keys read (by the AO, not this module) | `[egress].searches_per_fingerprint = 3`, `[egress].fingerprint_timeout_s = 120.0` (`services/assistant_orchestrator/config/default.toml:233-254`; read at `entrypoint.py:2230`, exposed ~479–484; wired 1121, 6793 `begin_turn`, 6910 `gate`). |
| BlarAI coupling | The manager: none. The production consent function: hard-codes BlarAI's single egress tool (`web_search`, "Search the web"). |
| Tests | `services/assistant_orchestrator/tests/test_egress_envelope.py` **23 tests** (import path is the only coupling) — carries with a path rewrite; `test_entrypoint_session_reaper.py` 12 (through the AO entrypoint; does not carry). |
| First commit | `efedf1b8 2026-07-02 Blair "rung 3 — turn-scoped Windows-Hello egress envelope (ADR-023 Am.4, #723)"`; 2 commits. |
| Verdict | **clean** (manager) / **needs-cut** (make the consent function take a per-tool label and summary). The lease semantics — one human touch covers up to N actions of one kind in one turn, refusals latch for the turn, a missing lease denies — are directly the product's "approve once for this task" primitive. |

### 1.6 `shared/security/escalation_consent.py` — escalation consent

| Item | Reading |
|---|---|
| Size | 453 lines. |
| Imports | stdlib `dataclasses`, `logging`, `threading`, `typing` only. **Zero** BlarAI imports, zero third-party. |
| Contents (REPORTED) | `EscalationContext` (74–152; `rule_label`, `action_summary`, `tool_name`, `source`; `from_pa_verdict` accepts safe fields only; `describe()`), `ApprovalResult` (155–187; `approved` is the only allowing value), `ApprovalVerifier` Protocol (194–241), single-verifier registry `register_verifier/clear_verifier/active_verifier` (252–302, lock-guarded module global), `request_escalation_consent` (309–361; no verifier → DENY), `run_verifier_bounded` (364–453: runs `verifier.verify` on a daemon thread, `join(timeout)`; timeout / raise / `None` / non-`ApprovalResult` → DENY; a late answer can never allow). `DEFAULT_CONSENT_TIMEOUT_S = 120.0` (62). |
| Verifiers implementing it | `hello_verifier.BiometricApprovalVerifier`; `services/ui_shell/src/escalation_prompt.py` (Textual TUI); registered by `launcher/__main__.py:845-849, 2379-2392` (Hello if available, else TUI). |
| BlarAI coupling | Docstrings name PA rules and BlarAI surfaces; `source` default `"policy_agent"`. Nothing functional. |
| Tests | `shared/tests/test_escalation_consent.py` **18 tests** (0 coupling hits) — carries unchanged; `test_generation_consent.py` 18 and `test_egress_rearm.py` 11 reuse the harness; `services/ui_shell/tests/test_escalation_prompt.py` 7 (BlarAI's TUI). |
| First commit | `88799c6f 2026-06-09 Blair "[#639] PA ESCALATE consumer — synchronous-inline operator approval"`; 2 commits. |
| Verdict | **clean.** Product note: a single process-global verifier is right for one governor process per Windows user session; on a shared PC the governor runs per user session anyway (§2). |

### 1.7 `shared/security/egress_guard.py` — the process-wide socket guard

| Item | Reading |
|---|---|
| Size | 1121 lines (+ `shared/security/ip_block.py` 121 lines, stdlib `ipaddress` only, first commit `fde8301a 2026-07-10`). |
| Imports | stdlib `errno`, `ipaddress`, `logging`, `socket`, `threading`, `dataclasses`, `typing`; BlarAI `shared.security.ip_block`. No third-party. Import has no side effect (asserted by `test_not_armed_on_import`). |
| Mechanism (REPORTED) | `arm()` (1064–1091) rebinds `socket.socket → _GuardedSocket` (712–833) and `socket.getaddrinfo → _guarded_getaddrinfo` (845–882), then runs registered arm hooks. `_check_connect` (560–593): tripped → refuse; `AF_HYPERV` → allow unconditionally; INET loopback → allow; external `(host, port)` on the widened allowlist (or an IP pinned by an allowlisted name's resolution, 296–365) → allow; anything else → `trip()` + `EgressDenied` (an `OSError` subclass). `_check_bind` (625–651): loopback only. `_guarded_getaddrinfo`: refuses to resolve external names unless allowlisted. `trip/is_tripped/rearm` (429–494): a latched kill-switch; `rearm()` is a bare function with **no authentication** ("Lead-Architect-only" by convention). `register_screener` (883–921) + `_screen_outbound` (671–705): payloads on sockets tagged external-allowlisted are screened; a positive or a raising screener trips. `_alert_operator` (417–426) = `logger.critical`. |
| BlarAI coupling | The `AF_HYPERV` unconditional allowance (the Hyper-V guest vsock — the product has no VM); the loopback allowance is tied to BlarAI's `127.0.0.1:5001` gateway by comment; operator alerting is the launcher's log; re-arm is unauthenticated because the only operator is the LA at the console. |
| Would a product want it? | **Yes, for exactly one purpose: the governor's own process.** It is a self-restriction (it only sees sockets opened *inside* the process that armed it). A governor that ships with this armed can state, and test, that its own process cannot reach the network except through one allowlisted door (the opt-in diagnostics/update path). It **cannot** observe or govern a governed agent's TLS session to a cloud model, and the product must not try to intercept those (§2). |
| Tests | `shared/tests/test_egress_guard.py` **16 tests**, 0 coupling hits (incl. `test_guard_scope_is_sockets_only` — the named-pipe path is untouched; `test_external_hostname_connect_denied`; `test_disarm_restores_socket_and_getaddrinfo`) — carry unchanged; `tests/security/test_egress_core.py` 36 (12 coupling hits), `test_egress_resolution_pinning.py` 25, `test_egress_sandbox_proving.py` 11, `test_egress_screen_wiring.py` 11, `test_ip_block.py` 9, `shared/tests/test_egress_rearm.py` 11. |
| First commit | `65c0a419 2026-06-03 Blair "code-enforced egress kill-switch (Tier 0, ADR-020) (#557)"`; 10 commits. |
| Verdict | **needs-cut**: remove `AF_HYPERV`; make the loopback port allowance explicit configuration; put an authenticated re-arm (Hello-gated through §1.6) in front of `rearm()`; route `_alert_operator` to the product's notification surface. Keep the rebind mechanism, the resolution pins and the trip latch as they are. |

### 1.8 `shared/security/exfil_screen.py` — the outbound exfiltration screen

| Item | Reading |
|---|---|
| Size | 390 lines. |
| Imports | Top-level stdlib `dataclasses`, `logging`, `re`, `typing`. Lazy BlarAI: `services.assistant_orchestrator.src.pgov.find_pii_spans` (199), `shared.security.egress_guard` (332, 381). |
| Contents (REPORTED) | `DetectionSpan` / `Detection` (labels + offsets, never values; 75–130). Secret layer `_SECRET_PATTERNS` (112–147): `PRIVATE_KEY_PEM`, `JWT`, `GITHUB_TOKEN`, `SLACK_TOKEN`, `GOOGLE_API_KEY`, `SECRET_ASSIGNMENT`. `screen(payload)` (215–286): coerces str/bytes/object to text (undecodable bytes → block), runs PGOV PII + secret layers, any error → block. `screen_and_enforce` (289–343) fires `egress_guard.trip`. `wire_into_egress_guard` (346–390) registers via the arm-hook seam (called by `launcher/__main__.py:2480` before `egress_guard.arm()` at 2488). |
| The PII layer it borrows | `services/assistant_orchestrator/src/pgov.py` (1426 lines, first commit `650f0363 2026-02-23`): `_PII_PATTERNS` (116–160: SSN, CREDIT_CARD with Luhn, EMAIL, PHONE_US, IPV4, AWS_KEY, HEX_SECRET (≥32 hex), PASSPORT_US, BEARER_TOKEN), `_CONTEXT_RECOGNIZERS` (302–318: PHONE_LOCAL, AREA_CODE, ACCOUNT_NUMBER, gated by an announcing word), `PIIMatch` (249), `find_pii_spans` (322–382). This span (roughly 116–382) is self-contained stdlib `re`; the rest of `pgov.py` imports `context_manager` at top level (itself stdlib: `re`, `secrets`, `time`) and lazily loads ONNX Runtime / OpenVINO for cosine-similarity leakage detection — which is why the recognizers must be **lifted out**, not the module imported. |
| Personal identifiers in the pattern lists? | **MEASURED: none.** `grep -n -i "blair|ducray|oppat|mrbla|mr\.blair"` over `pgov.py`, `exfil_screen.py`, `injection_scan.py` → zero hits. The lists are generic *formats* (US-centric: SSN, US phone, US passport). They may cross; they also need locale packs for a product. |
| Design choices a product must re-decide | Block-not-redact (`exfil_screen.py:36-43`): a false positive blocks a legitimate agent call and trips the governor's kill-switch. Right for BlarAI's one operator; for a product it is a decision point (block vs. warn-and-require-touch). |
| Tests | `tests/security/test_egress_screen.py` 24 (imports `build_car` and the checker; 20 coupling hits — the carve-out half is the checker's, the screen half carries), `test_egress_screen_wiring.py` 11 (launcher wiring — BlarAI's), `test_egress_sandbox_proving.py` 11. |
| First commit | `1279ca10 2026-06-07 Blair "C3 H-b — exfil screen + PA DENY_EXTERNAL_NETWORK carve-out"`; 4 commits (last `85ef93a6 2026-07-19`, docstring de-dating). |
| Verdict | **needs-cut**: extract the ~270 recognizer lines from `pgov.py` into a standalone module; make the trip sink an injected callable; re-decide block-vs-warn; add locale packs. |

### 1.9 `shared/timeout_registry.py` — and the config loader it depends on

| Item | Reading |
|---|---|
| Size | 1067 lines. |
| Imports | stdlib `importlib`, `inspect`, `dataclasses`, `pathlib`, `typing` only. It depends on **no config loader**: it is "a REGISTRY, not a config source — the live constants stay where their consumers live" (docstring, 13–15). `live_value(entry)` (1030–1062) imports `entry.module` and resolves a module constant, a dataclass field default, or a function-parameter default; `registry_names()` (1065). |
| Contents | `TimeoutEntry` (44–84: name, module, attribute, seconds, surface, role, incident, rationale, review, must_exceed); `ROLES` (87–112: judge / budget / probe / backoff / grain / watchdog); `REGISTRY` (115–953, ~64 rows); `BACKLOG` (955–1027). |
| BlarAI coupling | **Total, by construction.** MEASURED: the rows name 26 distinct modules — `shared.fleet.swap_ops` ×16, `services.ui_gateway.src.constants` ×9, `shared.fleet.swap_driver` ×6, `tools.dispatch_harness.*` ×12, `services.assistant_orchestrator.src.entrypoint` ×3, `launcher.process_launch`, `shared.coordinator.*`, … Every incident string is a BlarAI ticket. |
| Tests | `tests/integration/test_timeout_registry.py` 22 (resolves every row by import; the discovery lock fails on an unregistered production timeout), `tests/security/test_timeout_ordering.py` 6, `test_watchdog_windows_nest.py` 4, `test_execute_budget.py` 7. |
| First commit | `88103be2 2026-07-07 Blair "the timeout registry — the taxonomy of scars, gate-locked (LA-directed)"`; 54 commits (the most-edited file in this set). |
| Verdict | **not-extractable** as data. The **pattern** — ~120 lines (`TimeoutEntry`, `ROLES`, `live_value`, `registry_names`) plus the gate test's discovery lock and the `must_exceed` ordering check — carries over with an empty table and is worth carrying: it is how the product avoids inventing the same inversions BlarAI paid for (#1353, #1359, #1366). |

---

## 2. The product's threat model against BlarAI's

### 2.1 Assumptions, side by side

| Assumption | BlarAI (read from `CLAUDE.md`, `default.toml`, `DATA_MAP.md`, source) | The product |
|---|---|---|
| Who operates it | One Lead Architect at the console, who attends ceremonies and re-arms kill-switches by hand. | Many users, most non-technical, none of whom will attend a ceremony. Every "LA-only" act must become either a Hello-gated user act or a default. |
| Whose machine | The founder's own laptop: dev box = production target, he is admin, he chose every installed program. | Machines the founder does not control: other security software (this machine runs Bitdefender 27.0.60 — RULES.md), corporate policy (WDAC, Hello `DisabledByPolicy`), unknown drivers, shared PCs with several Windows accounts. |
| Network posture | Air-gapped by construction, then opened one door at a time: one `httpx` importer (`guarded_fetch.py`), a process-wide socket guard, a host allowlist (`kagi.com`), an exfil screen, a per-turn Hello lease. | The governed agents **must** talk to cloud models over TLS the product must not intercept. The only network the product can weld shut is its own process's. Everything else is observation and policy at the enforcement seams the platform vendors own (hooks, MCP, OS). |
| The model | Its own Qwen3-14B on its own GPU with TPM-signed weight manifests; a probabilistic classifier behind the deterministic one. | No model of its own. Adjudication is deterministic-first; any "judge" model would be the user's chosen provider or none. `weight_integrity.py`, `manifest_signer.py` and `require_signed_manifest` have nothing to sign. |
| Who the callers are | BlarAI's own services with mTLS identities (`certs/*_client.pem`); CARs are built by BlarAI's code (`build_car`, `_adjudicate_tool_dispatch`). | Third-party agents (Claude Code, Copilot CLI, …) the product does not control. "Source agent" is a hook-payload or process-tree *claim*, not a certificate; the CAR builder is per adapter and the boundary validation (principle 7) is the whole defence. |
| Trust root | Per-user TPM keys via PCP; five named `BlarAI-*` keys; DEK sealed by the TPM. | Same primitive (`tpm_signer.py`), the product's own key names, per Windows user. New questions: no-TPM machines (VMs without vTPM), a local admin who can *delete* (not extract) the keys, key continuity across product reinstalls. |
| Human presence | Hello on one laptop with a fingerprint reader. | Hello may be absent (`DeviceNotPresent`), unconfigured, or policy-disabled; PIN is Hello too. The helper already enumerates these states — the product needs a per-state policy. |
| Attacker | Untrusted content reaching a local model (injection), exfiltration of the operator's data. | The same plus: a prompt-injected agent trying to route around the governor; a local process impersonating an agent; the user switching the governor off; tampering with the audit chain or the policy file; the product's **updater** as the highest-value supply-chain target. |
| Data at rest | Born-encrypted (AES-256-GCM under a TPM-sealed DEK) for sessions, memory, knowledge; audit logs signed, not encrypted; owner-only DACLs (#637). | The audit log holds the user's tool arguments (§0) and is therefore private data. Signed *and* per-user DACL'd at minimum; encryption is a decision (on a shared PC, another admin can read a signed-plaintext chain). Secrets → DPAPI (`dpapi_store.py` pattern). |
| The governor's own egress | None except the one door. | Opt-in diagnostics/update path only — one file may import a network client; the product's own socket guard is armed with that one host allowlisted. |
| Recovery | The LA re-arms. | An authenticated re-arm (Hello) by the user; a documented "governor disabled" state that is loud, never silent. |
| Process/host | Python 3.11 services under a launcher, one Hyper-V VM for untrusted parsing over vsock. | No VM to lean on. Untrusted-input parsing runs in a least-privilege child process or not at all (the governor should parse only structured hook payloads). |

### 2.2 The thirteen security_by_design principles — carry unchanged or restate

Read from `C:\Users\mrbla\BlarAI\CLAUDE.md` `<security_by_design>` (REPORTED).

| # | Principle | Product treatment |
|---|---|---|
| 1 | Fail-closed | **Unchanged.** Every adapter's error path returns "deny" to its host; the consent harness's deny-on-timeout carries as-is. Define "closed" per seam (a hook that returns non-zero, an MCP proxy that refuses). |
| 2 | Deny-by-default, allowlists | **Unchanged in form, restated in scope.** Deny-by-default applies to *dangerous action classes* (egress to non-allowlisted hosts, writes outside the workspace, credential paths, destructive shell). A governor that denies every action on install is uninstalled the same afternoon; the shipped default is a policy file, not a class constant. |
| 3 | Defence-in-depth, independent locks | **Unchanged.** Hook check + OS-level check + audit are independent; never assert a lock count in doctrine. |
| 4 | Structural absence over configuration | **Restated:** "the governor's own process has no network client except the opt-in diagnostics path, enforced by the same single-importer scan pattern (`tests/security/test_no_external_egress.py::test_exactly_one_runtime_module_imports_a_network_client`) and the armed socket guard." Structural absence of *cloud adapters* inside the governor: the product observes agents' cloud traffic only at seams it owns; it ships no model client. |
| 5 | Single adjudication door | **Restated:** one engine, many adapters; no adapter decides. Every adapter reduces to a CAR and calls the one `check`. |
| 6 | Born-encrypted | **Restated:** born-DACL'd and signed for the audit chain; DPAPI for the product's secrets; encryption of the audit chain is a decision (shared PCs). |
| 7 | Validate before trust | **Unchanged and load-bearing:** anchored validation of the hook payload at the adapter boundary, before any policy or store is consulted; the "source agent" claim is provenance-tagged and never gains authority. |
| 8 | Least data across boundaries | **Restated:** the governor stores labels and hashes by default; arguments only where the policy needs them; the diagnostics path carries labels only, never a CAR. |
| 9 | Isolation for untrusted work | **Restated:** there is no VM; the governor parses only structured payloads; any content parsing runs in a low-privilege child process with no network. |
| 10 | Hardware-rooted integrity | **Restated:** sign the audit chain and the policy file with a TPM key when present; the product's binaries are Authenticode-signed; no weight manifests. |
| 11 | Fail-loud | **Unchanged.** A governor that is off must say so on screen. |
| 12 | Every control tested off | **Unchanged.** The `shared/instrument_registry.py` + `tests/security/test_instrument_toggles.py` pair (every registered instrument names a toggle test and a seam test) is the pattern. |
| 13 | Irreversible = ceremony | **Restated:** the user's Hello touch *is* the ceremony; posture flips are per-user, logged, and reversible only through the same touch. There is no LA. |

---

## 3. The separate repository and rulebook [PROPOSED]

Everything in this section is a proposal for the LA's judgment; the technical shape is mine, the go/no-go and the licence are his.

### 3.1 What the product repo takes from BlarAI's (mechanisms, with the file that proves each exists today)

| Need | BlarAI surface it is copied from | Why |
|---|---|---|
| A claim register | `docs/governance/trust-spine-claim-register.md` (LIVE as of 2026-09-16: per claim, what would have to be false on disk, which test re-proves it) | An auditor-facing inventory is the product's security story; it also feeds the AIGP portfolio. |
| A coverage disclosure | `tests/security/test_graders_disclose_what_they_did_not_measure.py` (a module that publishes a count must carry a not-measured vocabulary) + `tools/perf_contrib/schema.py`'s mandatory `not_measured` | The product's "N actions governed" number must say what it did not see. |
| Disposition discipline | `scripts/verify_disposition.py` + `tests/security/test_disposition_discipline.py` (`docs/reviews/*-disposition-*.md`, 68 records on disk) | Every review's findings end FIXED / DEFERRED with an observable predicate / REJECTED with an argument. |
| A standing gate with tests-off toggles | `shared/instrument_registry.py` + `tests/security/test_instrument_toggles.py`; `tests/security/test_secure_defaults.py` (3) and `test_production_posture.py` (13) | Principle 12 in code; secure defaults locked in CI. |
| The single-importer network scan | `tests/security/test_no_external_egress.py` (6 tests; forbidden list includes `openai`, `anthropic`, `cohere`, `boto3`, `requests`, `httpx`, `aiohttp`, `websockets`) | The product's own structural-absence claim. |
| Dependency truth + supply-chain hashes | `tests/security/test_dependency_truth.py` (4), `test_supply_chain_hashes.py` (6), `requirements.*.hashed.lock.txt` | A governor with an undeclared or unpinned dependency is its own supply-chain hole. |
| A security policy | `SECURITY.md` (private reporting, supported versions) | Required for any distributed product. |
| An ADR series + decision register | `docs/adrs/` (37 ADR files; ADR-018/020/023/024/025/027/029 are the trust-spine ones) + `docs/DECISION_REGISTER.md` (same-change indexing rule) | The product's own numbering, starting fresh; BlarAI's ADRs are *references*, not the product's decisions. |
| The timeout-registry pattern | `shared/timeout_registry.py` mechanism + `tests/integration/test_timeout_registry.py` discovery lock | Empty table, same lock. |
| A data map | `docs/security/DATA_MAP.md` shape (roots, stores, sensitivity, at-rest scheme, ACLs) | Written for the product's `%LOCALAPPDATA%\<Product>\` before the first byte is stored. |

### 3.2 What it must NOT inherit

- The air-gap rulebook (`test_no_external_egress.py`'s roots and the "zero external network" mandate) as a *product* posture: the governed agents' network is theirs. The product inherits the *pattern* for its own process only.
- Model-integrity: `shared/models/weight_integrity.py`, `manifest_signer.py`, `require_signed_manifest`, `require_signed_draft_manifest`, the draft/spec-decode machinery — there are no weights.
- The Hyper-V VM, vsock, `AF_HYPERV`, guest provisioning records.
- The launcher, the WinUI face, the TUI, the coder fleet, the battery, the coordinator, Vikunja and the journal *as product process*. The founder's journal and board are his practice and may continue to document the product; they are not the product repo's law.
- `CLAUDE.md`'s LA/agent doctrine (comprehension gates, dormant-merge ceremonies, status snapshot). A product repo needs a short `CONTRIBUTING`/`SECURITY` rulebook, not a 400-line agent doctrine.
- The `LOCALAPPDATA`-redirect rule *as written* (it protects `sessions.db`); the generalised rule "tests never touch the user's real app-data root" is kept.
- The `kagi.com` allowlist and everything Kagi (`shared/secrets/*kagi*`, `services/assistant_orchestrator/src/websearch/`).

### 3.3 Licence — a decision point for the LA

**Facts (MEASURED).** `LICENSE.md` = PolyForm Noncommercial 1.0.0 with `Required Notice: Copyright (c) 2026 Blair DuCray-Oppat (mr.blair.do@gmail.com)`; `COMMERCIAL-LICENSE.md` requires a paid commercial licence from the copyright holder for any commercial use. `git shortlog -sne --all`: 4075 commits `Blair <mr.blair.do@gmail.com>`, 11 `Blair DuCray-Oppat <same>`, 2 `Blair DuCray-Oppat, AIGP <same>`, 2 `Blair <blair@local>`, 5 `blarai <blarai@local>`, 3 `claude <claude@local>`, 1 `rev <r@r>`. No third-party human identity appears. The 11 commits under local-only identities (2026-07-23 merges and ledger notes by `blarai`, 2026-08-08 journal/fix commits by `claude`, one 2026-07-30 merge by `rev`) read as agent sessions on his machine (derived from their messages — gate figures, journal entries in the house style); they are derivative works produced under his direction. **Sole-author fact: confirmed for human authorship; the copyright status of AI-assisted commits is a question for R4-law, not one git can answer.**

**Constraints from components.** All third-party licences in the extractable set are permissive: pydantic (MIT), cryptography (Apache-2.0 OR BSD-3-Clause — carry the NOTICE if Apache is elected), pywin32 (PSF), PyJWT (MIT, only if `DecisionArtifact` minting is taken). None forces a licence on the product. The only constraint is BlarAI's own PolyForm-NC terms on BlarAI's code — which bind third parties, not the copyright holder, who may relicense his own code into the product repo under any terms he chooses.

**Recommendation [PROPOSED]:** open the *engine* (CAR, checker shape, audit chain, consent harness, the tests-off pattern) under Apache-2.0 in the product repo, and keep the product shell (adapters, updater, UI, policy packs) under the product's commercial terms. Alternatives: (a) PolyForm-NC + commercial, as BlarAI — consistent, but it shuts out the community the brief says to borrow vocabulary from (CAVA core is Apache-2.0, the Agent Hooks contract is MIT, the Agent Control Standard is at OWASP); (b) fully proprietary — simplest, and the weakest position for a one-person vendor who needs trust more than secrecy. Trade-off in one line: an open engine is auditable and adoptable; a closed engine is a promise. This choice is his.

---

## 4. What must never cross — concretely

### 4.1 BlarAI → product: never copied, never referenced

All paths MEASURED by directory listing (names and sizes only; no file contents read) at 02:5x EDT unless marked REPORTED.

| Class | Concrete path / symbol | Note |
|---|---|---|
| TPM key names (handles into the chip) | `BlarAI-Audit-Signing-Key-v1` (`shared/security/audit_log.py:114`; `ceremony_preflight.py:41`; `verify_trust_root.py:67`), `BlarAI-PA-JWT-Signing` (`services/policy_agent/src/constants.py:53`; `services/policy_agent/config/default.toml:61`), `BlarAI-DEKSeal` (`shared/security/provision_dek_keystore.py:82` + 6 call sites), `BlarAI-Manifest-Signing` (`shared/models/manifest_signer.py:44`), `BlarAI-Coordinator-Policy-Signing` (`shared/coordinator/policy.py:48`) | The private halves live in the TPM and cannot be exported; the *names* are still BlarAI's identity and must not be reused — a product key named identically on the same PC would open the wrong key. |
| Key material and wraps on disk | `%LOCALAPPDATA%\BlarAI\dek_keystore.json` (480 B), `sessions.keystore.json` (220 B; dev), `substrate.keystore.json` (REPORTED in DATA_MAP; not listed today), `C:\Users\mrbla\BlarAI\certs\` (`ca.pem`, `pa_server_key.pem`, `orch_client_key.pem`, `gateway_client_key.pem`, `router_client_key.pem`, the matching `.pem` certs, `pa_public.pem`, `launcher.lock`) | gitignored; per-boot. |
| HMAC dev keys and chain identity | Derivation labels `b"BlarAI-audit-hmac-stub-v1::<path>"` (`services/policy_agent/src/entrypoint.py:1095-1099`), `b"BlarAI-ingest-audit-hmac-stub-v1"` (`…/assistant_orchestrator/src/entrypoint.py:5741,5765`), `GENESIS_HASH` label `"BlarAI-audit-log-genesis-v1"` (`audit_log.py:109`), key id `"dev-stub"` | Not secrets, but a product chain with BlarAI's genesis would verify against BlarAI's tooling and vice versa. New labels. |
| Session store and memory | `%LOCALAPPDATA%\BlarAI\sessions.db` (749 568 B), `sessions.db.test-damaged.bak`, `substrate.db` (1 662 976 B — the cross-conversation memory, DATA_MAP §3), `knowledge.db` (73 252 864 B), `dispatch_state.db` (+ `-wal`, `-shm`), `ingest_staging\`, `backups\`, `wiped_substrate_backup_2026-07-02*\`, `coordinator\` (shadow-journal.db) | The LA's private data. |
| Audit chains | `%LOCALAPPDATA%\BlarAI\audit\ingest_audit.jsonl` (present); PA adjudication log default `services/policy_agent/data/audit/adjudication_audit.jsonl` (REPORTED in DATA_MAP §2 row 3; the directory does **not** exist on disk today — MEASURED `ls`) | Signed plaintext: contain resource paths and decisions. |
| LA profile / preference data | `substrate.db` rows, `preference_block` rows (`services/assistant_orchestrator/src/preference_block.py`), `ui_prefs.json` (74 B), logs `boot.log` (316 KB), `launcher.log` (14.8 MB), `crash.log`, `launcher-restart-20260810.log` | Logs are diagnostics but may echo prompts; treat as private. |
| Secrets and env | `.env` (gitignored; `.env.example` shows `VIKUNJA_USER`/`VIKUNJA_PASS`), `userdata/` (gitignored), `%LOCALAPPDATA%\BlarAI\secrets\kagi_api_key.dpapi` (present; `shared/secrets/dpapi_store.py:36,54,58`), env override `BLARAI_KAGI_KEY_TEST_OVERRIDE` | The Kagi key is DPAPI-bound to this user+machine and undecryptable elsewhere — still never copied. |
| Model weights, manifests and their signing key | `models/qwen3-14b/openvino-int4-gpu/manifest.json{,.sig,.pub}`, `models/qwen3-0.6b-pruned-6l/openvino-int8-gpu/manifest.json{,.sig,.pub}`, the weights under `models/` (gitignored), `%LOCALAPPDATA%\BlarAI\ov_cache\` (compiled blobs, ~8.48 GB — DATA_MAP §2 row 7), the `BlarAI-Manifest-Signing` key | The product has no weights to sign. |
| Exfil-screen pattern lists | `services/assistant_orchestrator/src/pgov.py:116-160, 302-318`; `shared/security/exfil_screen.py:112-147` | **Checked: no personal identifiers** (MEASURED grep, zero hits). These MAY cross as generic formats. |
| The egress allowlist value | `_EGRESS_ALLOWLIST = frozenset({"kagi.com"})` (`gpu_inference.py:392`), `KAGI_SEARCH_ENDPOINT` (`services/assistant_orchestrator/src/websearch/live_adapter.py`) | BlarAI's live posture; never a product default. |
| `state/` | **No `state/` directory exists at the BlarAI repo root** (MEASURED `ls state/` → nothing). The runtime state root is `%LOCALAPPDATA%\BlarAI\` (DATA_MAP §0, Root B) and the repo trust root is `certs\` (Root A). Everything under both stays. |
| Built helper binaries | `tools/hello_verify/bin/`, `obj/` (`BlarAI.HelloVerify.exe`) | The product builds and signs its own. |

### 4.2 Product → BlarAI: nothing imports back, and the tests that would catch it

Nothing from the product — telemetry paths, an update client, cloud-model adapters, its Hello helper, its policy packs — may be imported into BlarAI's runtime (`shared/`, `services/*/src`, `launcher/`). If someone tried:

| Attempt | The BlarAI control that fires (file :: test) |
|---|---|
| A product module that imports `openai`, `anthropic`, `cohere`, `boto3`, `requests`, `httpx`, `aiohttp`, `websockets`, `urllib.request`, `http.client` lands anywhere in the runtime roots | `tests/security/test_no_external_egress.py::test_runtime_imports_no_external_network_library`; if it imports `httpx` specifically, `::test_exactly_one_runtime_module_imports_a_network_client` (the door must be exactly `shared/security/guarded_fetch.py`); `::test_egress_control_scans_a_meaningful_surface` guards the scan roots themselves. |
| A runtime socket to a telemetry or update host at run time | `shared/security/egress_guard.py::_check_connect` (560–593) refuses and **trips the kill-switch**; locked by `shared/tests/test_egress_guard.py::test_external_hostname_connect_denied`, `::test_external_ipv4_connect_denied`, `::test_external_dns_resolution_denied`, and `tests/security/test_egress_core.py` (36). |
| A new third-party dependency arriving with the product code | `tests/security/test_dependency_truth.py` (every runtime import must be declared, every declaration imported) and `tests/security/test_supply_chain_hashes.py` (every distribution hash-pinned). |
| A config flag flipped to admit it | `tests/security/test_secure_defaults.py` (static) and `tests/security/test_production_posture.py` (runtime resolution of `dev_mode` and the fail-closed behaviours). |
| A cloud adapter registered as a second adjudicator | No single test names this; it violates ADR-020/027 and `CLAUDE.md` `<identity_split>`; the door has one slot (#977 is the open ticket on that very seam). |

The reverse direction also has a human rule: BlarAI's `CLAUDE.md` `<identity_split>` forbids "leaking the workshop into the product"; the product repo's rulebook should carry the mirror sentence, "nothing of BlarAI's runtime state, keys or identity strings enters this repository," with a grep-based gate for the `BlarAI-` key-name prefix and the `%LOCALAPPDATA%\BlarAI` path.

---

## 5. Boundary statement for the Lead Architect

BlarAI and the product are two different things that happen to share a toolbox. BlarAI is your private assistant: one machine, one operator, its own brain, its network welded shut except for the doors you personally opened. The product is a doorman for other people's agents on other people's Windows PCs, and it must let those agents talk to whatever cloud model their owner chose. What can move from one to the other is the *mechanism*, never the *identity or the data*: the way an action is written down (the CAR), the way it is judged (the deterministic checker's shape), the way the judgment is recorded so nobody can quietly edit it (the hash chain and the TPM signature), the way a person is asked and the answer is trusted only if it is a clear yes (the consent harness, the Hello prompt, the per-turn lease), and the way the doorman is stopped from phoning home (the single-importer scan and its own socket guard). What stays behind is everything with your name on it — your TPM key names, your session and memory databases, your audit chains, your Kagi key, your certificates, your model weights and their signatures — and everything built for a world with one operator, such as the air-gap rules and the ceremonies only you attend. The product needs its own house: its own repository, its own decision records numbered from one, its own licence (your decision; the code you wrote you can relicense, the third-party parts are all permissive), and a rulebook that keeps BlarAI's habits of proving controls, disclosing what was not measured, and refusing to defer without naming what would unblock — but drops the parts that only make sense for you at your own console. And the wall runs both ways: BlarAI's runtime already has tests that will fail loudly if a single line of product networking, telemetry or cloud adapter is ever imported into it.

---

## 6. What I did not verify

- I did not run any BlarAI test, start any service, import `gpu_inference.py`, or open any database; the checker's dependency closure is from a static AST scan, not an import.
- Whether `BlarAI.HelloVerify.exe` is present and self-contained on disk was not probed (I read the source and the csproj only).
- The per-user (vs machine) TPM key-store claim is derived from the flags passed (`NCRYPT_MACHINE_KEY_FLAG` absent), not measured against the chip.
- "Would the tests carry over" is judged from imports and grep hits, not by running them in a moved tree.
- The copyright status of the 11 commits under local agent identities is a legal question (R4), not a git fact.
- `CLAUDE.md` says Python 3.12; the venv reports 3.11.9. I report the measurement and did not reconcile it.
