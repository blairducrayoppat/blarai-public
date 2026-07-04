# Kagi API Key Handling Design

**Scope:** W2 (Agentic Web-Search Skill, ticket #573) — fork-free pre-work.
**Author:** supply-chain specialist subagent, 2026-06-04
**Status:** DESIGN COMPLETE — implementation pending Lead-Architect approval of W2.

---

## 1. Existing BlarAI Config and Secret Patterns

Before proposing anything new, a survey of how BlarAI already handles config and secrets was conducted across the repo (grep for `api_key`, `secret`, `keyring`, `DPAPI`, `credential`, `token`, config loaders, environ reads).

**What was found:**

1. **Structured TOML config files** (`services/{service}/config/default.toml`, `guest_runtime.toml`) loaded via stdlib `tomllib` in `shared/runtime_config.py` and service entrypoints. Config files live inside the repo tree under each service's `config/` directory. They are committed; they do not carry secrets. Symlinks are explicitly rejected (fail-closed). The resolution chain uses an explicit env-var override (`BLARAI_RUNTIME_MODE`) but no secret injection.

2. **TPM-sealed non-exportable keys** (`shared/security/tpm_signer.py` + `shared/security/provision_signing_key.py`) for the Policy Agent JWT signing key (ADR-021). The private half never leaves the chip. Its public half (`certs/pa_public.pem`) is gitignored and written by a human-run ceremony. This is BlarAI's highest-trust secret pattern — appropriate for a long-lived signing authority.

3. **Gitignored runtime data** in `%LOCALAPPDATA%\BlarAI\` — `services/assistant_orchestrator/src/entrypoint.py` line 948 shows `os.environ.get("LOCALAPPDATA", "")` used to write `substrate.db`. This establishes the pattern: per-user, per-machine runtime data goes to `%LOCALAPPDATA%\BlarAI\`, not into the repo tree.

4. **`.env` file** — listed in `.gitignore` as "Environment secrets (local-only, never commit)." A `.env` file is the repo's acknowledged mechanism for local-only env-var overrides, though no production service currently reads from one (they use TOML + the env-mode override).

5. **No existing secrets manager, keyring, or DPAPI integration** — BlarAI has not yet integrated Python's `keyring` library, Windows CNG DPAPI, or Windows Credential Manager. The TPM path (`tpm_signer.py`) uses `ctypes` / pywin32 CNG calls directly, but it is scoped to signing keys, not general-purpose secret storage.

**Implication:** A Kagi API key is the first short-lived external secret BlarAI needs to store and retrieve at runtime. The design must align with the house pattern without inventing a parallel system.

---

## 2. Requirements

- The key is never in git (non-negotiable).
- Storage is local-stack only — no cloud KMS, no Kagi-hosted vault, no remote fetch.
- The key is readable by the web-search worker process (Python, running as the user) without requiring elevated privileges.
- Dev and test environments must work with a fake key — no real key required for CI or unit tests.
- The storage and retrieval path must be simple enough to audit in a single read.

---

## 3. Options Evaluated

### Option A: Out-of-repo TOML file (`%LOCALAPPDATA%\BlarAI\secrets\kagi.toml`)

A TOML file at a fixed path outside the repository. The web-search worker reads it at startup via `tomllib`. The file is created by the operator once; its path is never committed.

**Security:** TOML plaintext on disk, protected only by NTFS ACLs on the user's profile directory. `%LOCALAPPDATA%` is user-scoped (other local users cannot read it by default), but the file would be readable by any process running as the same user — including a compromised subprocess.

**Complexity:** Minimal. No new dependencies. Aligns with BlarAI's existing `tomllib` config pattern.

**Fit:** Good for config values that are not highly sensitive. Weak for an API key that grants metered search credits and could be exfiltrated by any user-context process.

**Rejected because** the key is a bearer credential with external value (Kagi charges per API call). Storing it as plaintext on disk — even in `%LOCALAPPDATA%` — is one step above committing it to the repo. If the threat model were purely "don't accidentally commit the key," a plaintext file suffices. But BlarAI's privacy mandate and the stated direction toward a network-facing future argue for the weakest-available plaintext surface to be the minimum bar, not the target bar.

### Option B: Windows DPAPI via `pywin32` directly

Windows Data Protection API (DPAPI) encrypts a blob with a key derived from the user's login credential and machine identity. The resulting blob can only be decrypted by the same user on the same machine. Storage: the encrypted blob is written to a file in `%LOCALAPPDATA%\BlarAI\secrets\` (the blob itself is opaque bytes). Retrieval: `CryptProtectData` / `CryptUnprotectData` via `pywin32.win32crypt`.

**Security:** Substantially stronger than plaintext. The key cannot be decrypted without the user's Windows login credential. An offline attacker who copies the blob file cannot decrypt it on another machine.

**Complexity:** Requires `pywin32` (already available in the BlarAI stack — `launcher/process_launch.py` uses it for token operations). No new dependency. One encrypt call at setup, one decrypt call at runtime.

**Fit:** Good. Aligns with the machine-bound, user-scoped philosophy of the TPM path (ADR-021) without requiring TPM involvement for a revocable API key. The TPM pattern is reserved for non-exportable *signing authorities*; DPAPI is the right primitive for a revocable credential that needs to survive a process restart.

**Rejected comparison vs. Windows Credential Manager (Option C):** DPAPI + file achieves the same encryption property with less surface area. Windows Credential Manager (`keyring` backend `WinCred`) wraps DPAPI internally; the difference is an extra name-lookup layer and a new Python dependency (`keyring`). For a single secret with a known name, the `pywin32` + blob-file approach is simpler to audit and has no dependency not already present. See §3.C below.

### Option C: Windows Credential Manager via `keyring`

Python's `keyring` library abstracts over platform secret stores. On Windows, its `WinCred` backend stores to and retrieves from Windows Credential Manager, which encrypts using DPAPI internally.

**Security:** Equivalent to Option B (DPAPI under the hood). Marginally better UX: secrets are visible in the Credential Manager GUI for operator review and deletion.

**Complexity:** Adds `keyring` as a new dependency (not yet in the BlarAI stack). `keyring` is well-maintained (active releases through 2025) but adds ~15 KB of code and a dependency chain. The `WinCred` backend is the Windows-specific adapter; the abstraction adds cross-platform compatibility that BlarAI does not need (this is a single-user Windows system by design for the foreseeable future).

**Rejected because** it adds a dependency (`keyring`) whose only benefit over Option B is GUI discoverability in Credential Manager. BlarAI's operator is technical (the Lead Architect builds the system); he does not need a GUI credential browser. The `pywin32` + blob approach is already present and auditable with fewer moving parts. If BlarAI later moves to a multi-platform deployment or needs to manage many secrets, `keyring` becomes attractive — that is a named future trigger for reconsidering this decision.

### Option D: TPM-sealed key (ADR-021 pattern)

The TPM provisioning ceremony (`provision_signing_key.py`) could be extended to seal an API key inside the TPM, making it non-exportable and machine-bound.

**Security:** Highest possible — the key never leaves the chip in plaintext. This is the same guarantee that protects the PA JWT signing key.

**Complexity:** Significant. The PA JWT key is a *signing authority*: it is provisioned once, lives forever, and its replacement requires a deliberate ceremony. A Kagi API key is a *revocable credential*: it may be rotated, shared across machines for development, or replaced when the subscription changes. TPM sealing the key makes rotation a multi-step ceremony (delete old CNG key, provision new one) and prevents the key from being used on a second development machine without re-provisioning.

**Rejected because** the TPM pattern buys non-exportability at the cost of revocability and portability. For a signing authority held in perpetuity on a single chip, that trade is worth it. For a metered API key that may rotate annually and that a developer might want to test on a second machine, the ceremony overhead is disproportionate. The ADR-021 rationale explicitly calls this out: "Provisioning is a ceremony, not an automatic step" — that discipline is appropriate for signing roots, not for revocable credentials.

---

## 4. Recommended Approach: DPAPI + Blob File (Option B)

**Recommended:** Store the Kagi API key as a DPAPI-encrypted blob at:

```
%LOCALAPPDATA%\BlarAI\secrets\kagi_api_key.dpapi
```

The blob is an opaque binary file (output of `CryptProtectData`). It is per-user, per-machine. No other process on the same machine running as a different user can decrypt it. An attacker who copies the file cannot decrypt it offline without the user's Windows login credential.

**Why this over the alternatives:**

1. **No new dependency.** `pywin32` is already in the stack (`launcher/process_launch.py`). The encrypt/decrypt path is two `win32crypt` calls.

2. **Aligns with the `%LOCALAPPDATA%\BlarAI\` pattern.** The AO already writes `substrate.db` there. The secrets subdirectory is a natural extension of the same tree.

3. **Right-sized for a revocable credential.** DPAPI gives machine+user binding (the same guarantee as Windows Credential Manager) without the ceremony overhead of the TPM path. The key can be re-written (rotated) by overwriting the blob file.

4. **Auditable in 20 lines of code.** The encrypt and decrypt paths are narrow, have no network calls, and can be fully reviewed in a single sitting.

---

## 5. Interface Specification

### 5.1 Secret Storage Helper (to be written at W2 implementation time)

Location: `shared/secrets/dpapi_store.py` (new file, not yet created — this is the design, not the implementation)

```python
# Conceptual interface — exact implementation is W2 scope

SECRETS_DIR: Path = Path(os.environ.get("LOCALAPPDATA", "")) / "BlarAI" / "secrets"
KAGI_KEY_FILE: Path = SECRETS_DIR / "kagi_api_key.dpapi"

def store_kagi_api_key(key: str) -> None:
    """Encrypt key with DPAPI and write to KAGI_KEY_FILE.
    Called once by the operator setup script. Overwrites on rotation.
    Fails closed if pywin32 or DPAPI unavailable."""

def load_kagi_api_key() -> str:
    """Decrypt and return the Kagi API key.
    Raises KagiKeyNotProvisioned if KAGI_KEY_FILE is absent.
    Raises KagiKeyDecryptError if decryption fails (wrong user/machine).
    Never logs the plaintext key."""
```

The runtime calls `load_kagi_api_key()` exactly once at web-search worker startup and passes the result directly to `KagiClient(api_key=...)`. The plaintext string lives only in memory for the duration of the worker process. It is never written to a log, never included in an error message, and never stored in a TOML config section.

### 5.2 Operator Setup

A one-time setup command (to be documented in the W2 runbook):

```
python -m shared.secrets.provision_kagi_key
```

This script prompts the operator for the Kagi API key (stdin, echoing disabled), encrypts it with DPAPI, and writes the blob. It confirms success by immediately decrypting and verifying the round-trip. Analogous to `provision_signing_key.py` for the PA JWT key — a deliberate, human-witnessed step.

### 5.3 Fail-Closed Posture

- If `KAGI_KEY_FILE` does not exist → `KagiKeyNotProvisioned` error; web-search worker refuses to start. No silent fallback.
- If DPAPI decryption fails (wrong user, wrong machine, corrupted blob) → `KagiKeyDecryptError`; same hard failure.
- If `pywin32` is unavailable → import-time failure surfaced to the caller; the worker cannot start.

This mirrors the PA JWT TPM pattern: fail-closed until provisioned; no soft-degradation path that silently runs without the key.

---

## 6. Dev and Test Key Supply

Since the Kagi client is mocked in tests (the runtime is air-gapped; no real HTTP calls), tests must never require a real key. The following pattern is prescribed:

**Unit and integration tests:** Pass a sentinel string directly:

```python
# In tests — always use a sentinel, never read from DPAPI
client = KagiClient(api_key="TEST_FAKE_KEY_DO_NOT_USE")
```

The `KagiClient` constructor accepts the key as a positional argument; no environment variable or disk read occurs when the argument is supplied directly.

**Environment variable escape hatch for CI:** If a test fixture needs to exercise the `load_kagi_api_key()` path itself (e.g., testing the provisioning flow), it should:
1. Set `BLARAI_KAGI_KEY_TEST_OVERRIDE=some_fake_key` in the test environment.
2. The `load_kagi_api_key()` implementation checks this env var first (before DPAPI) when running under `pytest` (detected via `sys.flags.dev_mode` or an explicit test-mode flag).

This is the same dev-mode bypass pattern that PA's `dev_mode = true` uses for the JWT minter (ephemeral in-memory key in dev; TPM key in production). The pattern is established; the web-search skill follows it.

**What tests must never do:** Read from the real `kagi_api_key.dpapi` file, make network calls to `kagi.com`, or require the `KAGI_API_KEY` environment variable to be set in the test environment. The egress guard (`egress_guard.py`) will enforce this at runtime if it is armed during tests — an additional safety net.

---

## 7. What This Design Does Not Cover (Named Gaps for W2)

- **Key rotation runbook.** Rotating the key is `python -m shared.secrets.provision_kagi_key` (overwrites the blob). A formal rotation runbook belongs in `docs/runbooks/` and is W2 scope.
- **Multi-machine development.** The DPAPI blob is machine-bound. A second development machine requires its own provisioning step. If the team ever expands beyond one developer on one machine, this is a friction point. The decision to accept it is recorded here: the trade is correct for a single-user, single-machine personal system.
- **Key expiry / rotation reminder.** Kagi API keys do not carry embedded expiry metadata. A rotation-reminder mechanism (e.g., a dated annotation file written alongside the blob at provisioning time) would be a useful follow-up. Not blocking for W2.
- **Egress guard carve-out for the web-search worker.** As noted in the supply-chain vetting document (§5.6), the web-search worker will be the first process that makes intentional outbound calls. Whether it arms the egress guard, arms it with a `kagi.com` allowlist, or does not arm it at all is an architecture decision for W2 proper. This document does not prescribe that decision.
