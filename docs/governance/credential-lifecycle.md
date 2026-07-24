---
title: Credential & Certificate Lifecycle Governance
status: living
area: governance
---

# Credential & Certificate Lifecycle Governance

> **Acronyms on first use.** mTLS = mutual Transport Layer Security (both
> ends present a certificate). CA = Certificate Authority. PEM = Privacy-Enhanced
> Mail (the text encoding X.509 certificates and keys are stored in). ECDSA =
> Elliptic Curve Digital Signature Algorithm. P-256 = the NIST secp256r1 curve.
> CN = Common Name. SAN = Subject Alternative Name. EKU = Extended Key Usage.
> TPM = Trusted Platform Module. CNG = Cryptography Next Generation (the Windows
> crypto API). DEK = Data-Encryption Key. HKDF = HMAC-based Key Derivation
> Function. AES-GCM = Advanced Encryption Standard, Galois/Counter Mode. DACL =
> Discretionary Access Control List (the Windows per-file permission list). SID =
> Security Identifier (a Windows account/principal id). JWT = JSON Web Token.
> PA = Policy Agent. AO = Assistant Orchestrator. vsock = virtual socket (the
> host↔guest channel). PCR = Platform Configuration Register (the TPM's
> boot-measurement registers). ADR = Architecture Decision Record. LA = Lead
> Architect. AIGP = Artificial-Intelligence Governance Professional (the
> certification this record supports).

## Status

**LIVE software posture, as of 2026-07-16.** This record describes the
credential and certificate machinery that **actually ships and runs** on the
BlarAI host. Every mechanism below is labelled **LIVE** (wired into a real boot
or dispatch path and exercised), **DESIGN-INTENT** (code present but reached by
nothing live), or **DECLINED / DEFERRED** (a hardware-trust ambition the LA has
ruled out or postponed). The hardware-rooted-trust design the original planning
ticket (#14) assumed — a Pluton-sealed CA, per-agent-VM certificate issuance,
measured-image CN binding, and a live nonce/epoch JSON-Web-Token revocation
fabric — is **not** the shipped posture; it is confined to §9 (Declined &
deferred scope) and is not woven through the live runbook.

## Audience

**Primary**: auditor / governance reviewer — reads the end-to-end lifecycle of
every credential the running system depends on (transport certificates,
at-rest encryption keys, TPM-resident signing keys), the fail-closed boundary
each sits behind, and the exact line where the declined hardware-trust scope
begins.

**Secondary**: incident responder — follows §8 (Operational runbooks) to
inspect certificate state, rotate a suspected-compromised credential, and
understand what the system does when the Policy Agent is unreachable.
Operator — runs the LA-present provisioning ceremonies referenced in §7.
Developer — reads §3–§6 for the contract any change to the boot, transport, or
dispatch path must preserve.

## Prerequisites

- [ADR-026](../adrs/ADR-026-Per-Boot-mTLS-Ephemeral-Certificates.md) — Per-boot
  ephemeral mTLS certificates for the host↔vsock channel. The core live design
  this record documents. Amendment 1 (2026-07-12) adds the dispatch/battery
  cert-reuse window.
- [ADR-025](../adrs/ADR-025-At-Rest-Encryption-DEK-Envelope.md) — At-rest
  encryption under a TPM-sealed, dual-wrapped DEK with an offline recovery key.
  The encryption-key half of the credential inventory (§6).
- [ADR-021](../adrs/ADR-021-TPM-Sealed-PA-JWT-Signing-Key.md) — The TPM-sealed
  Policy-Agent signing key + provisioning ceremony. Its public half
  (`certs/pa_public.pem`) is the sole git-tracked certificate (§2).
- [ADR-018](../adrs/ADR-018-TPM-Trust-Root-SGX-Replacement.md) — The TPM 2.0
  trust root. The non-exportable-key primitive that ADR-021/ADR-025 sign and
  seal on; supersedes the SGX-attestation premise the old ticket inherited.
- [ADR-028](../adrs/ADR-028-Measured-Boot-Attestation-Scope.md) — Measured-boot
  attestation **scope**. Amendment 1 (2026-06-10) records that production
  trust-root keys are **not** PCR-bound. The on-disk anchor for §9.
- [ADR-041](../adrs/ADR-041-Host-Mode-Action-Authorization-Boundary.md) — The LA
  decision (2026-07-15) naming the live host-mode authorization boundary and
  ruling the Agentic-JWT credential fabric **vestigial** (§9.2).
- [ADR-007](../adrs/ADR-007-iGPU-Trust-Boundary-Software-Fallback.md) — The
  original mandate that the vsock channel is mTLS-authenticated with
  `CERT_REQUIRED` in both directions.
- Peer governance docs: [weight-integrity.md](weight-integrity.md)
  (the TPM manifest-signing gate that shares the trust root, §7),
  [configuration-management.md](configuration-management.md)
  (the config surface that selects production vs dev posture).

## Source References

| Artifact | Path | Notes |
|---|---|---|
| Per-boot cert mint + reuse-window | `shared/security/cert_provisioning.py` | `provision_per_boot_certs`, `_load_consistent_certs`, `verify_per_boot_certs_exist`, `CERT_LIFETIME_HOURS`, the CN constants |
| mTLS SSL-context factories | `shared/ipc/vsock.py` | `create_server_ssl_context` / `create_client_ssl_context` (`CERT_REQUIRED`, TLS 1.2 floor); `VsockConfig` cert paths |
| Launcher mint site + single-instance guard | `launcher/__main__.py`, `launcher/instance_lock.py` | Step-1.5 `provision_per_boot_certs(...)` before service construction; per-checkout PID lock in `certs/launcher.lock` |
| Client-context cache follows re-mint | `services/ui_gateway/src/transport.py` | `_cert_generation_fingerprint`, `_client_ssl_context`, the bounded verify-failure retry in `_connect_host_loopback_mtls` / `_connect_hyperv` |
| Dispatch/battery reboot lifecycle | `tools/dispatch_harness/battery.py` | `boot_launcher_detached` (sets `BLARAI_REUSE_CERTS`), `run_teardown_barrier`, `AoReensurer` |
| DACL hardening | `shared/security/file_dacl.py` | `strip_foreign_sids_from_dir` — every-boot cert-dir ACL hygiene (#637) |
| At-rest DEK envelope | `shared/security/dek_envelope.py`, `shared/security/tpm_sealer.py` | dual-wrap create/load/`unseal_dek`; `dek_keystore.json` |
| TPM signing primitive | `shared/security/tpm_signer.py` | non-exportable ECDSA P-256 CNG keys via `ncrypt.dll`; the PA JWT + manifest signing key |
| Agentic-JWT layer (DESIGN-INTENT) | `shared/crypto/jwt_validator.py`, `services/policy_agent/src/jwt_minter.py` | The nonce/epoch/receipt fabric — reached by nothing live; slated for removal (#910) |
| Config surface | `services/policy_agent/config/default.toml`, `services/assistant_orchestrator/config/default.toml` | `[ipc]` cert paths, `dev_mode`, `[security].require_signed_manifest`, the TPM key names |
| Trust anchor (tracked) | `certs/pa_public.pem` | The only git-tracked certificate; ADR-021 ceremony output |

---

## Governance Content

### 1. Purpose — one trust boundary, credentials that never outlive a boot

Every risky action in BlarAI crosses exactly one transport boundary: the
mutual-TLS channel between the host-side services (Assistant Orchestrator, UI
Gateway, Semantic Router) and the Policy Agent that adjudicates them. A
credential that authenticates that channel is therefore as load-bearing as the
adjudication itself — an attacker who could present a valid client certificate
would speak to the single adjudication door as a trusted peer.

The governing design choice is that **these credentials never outlive a boot**.
On every production start the launcher mints a brand-new Certificate Authority
in memory and issues a fresh set of leaf certificates from it; the CA private
key is discarded when the process exits and is never written to disk. There is
no long-lived certificate to leak, no operator-managed key file to rotate, and
no certificate database to revoke against — the exposure window of any single
credential is bounded to one boot session. This record documents that lifecycle
end to end, plus the two other credential families the running system depends
on: the at-rest Data-Encryption Key (§6) and the TPM-resident signing keys (§7).

### 2. Credential inventory & trust anchors

| Credential | Kind | Lifetime | Storage | Tracked in git? |
|---|---|---|---|---|
| Per-boot CA private key | ECDSA P-256, in-memory | One boot session (discarded at process exit) | RAM only — **never** on disk | No (cannot be) |
| Per-boot CA public cert (`ca.pem`) | X.509 | 24 h nominal / boot session effective | `certs/` | No (gitignored) |
| PA server + gateway/orchestrator/router leaf certs & keys (8 PEMs) | ECDSA P-256 | 24 h nominal / boot session effective | `certs/` | No (gitignored) |
| At-rest DEK (master) | AES-256, dual-wrapped | Decades (re-key designed-for, not built) | Wrap records in `dek_keystore.json`; DEK itself never on disk in clear | No |
| Offline recovery key | 256-bit random | Decades (break-glass) | **Off-box**, held by the LA (printed / USB) | No (never on disk) |
| TPM manifest-signing key | Non-exportable ECDSA P-256 (CNG) | Persistent, TPM-resident | Inside the TPM; public half exportable | No (key), public verified on checkout |
| PA JWT signing key (`BlarAI-PA-JWT-Signing`) | Non-exportable ECDSA P-256 (CNG) | Persistent, TPM-resident | Inside the TPM | Public half → `certs/pa_public.pem` (**tracked**) |
| At-rest DEK seal key (`BlarAI-DEKSeal`) | Non-exportable RSA-2048 (TPM) | Persistent, TPM-resident | Inside the TPM | No |

**The single git-tracked certificate is `certs/pa_public.pem`** — the public
half of the ADR-021 TPM-sealed Policy-Agent signing key, committed deliberately
as the documented trust anchor. Everything else in `certs/` is a per-boot,
gitignored artifact (ADR-026 §6). The DEK keystore's dual-wrap records are
anchored by the SHA-256 recorded at the ADR-025 ceremony (ADR-025 §5).

### 3. The per-boot mTLS certificate lifecycle (LIVE)

#### 3.1 Issuance — one mint call, nine PEMs

On every production boot (`dev_mode=false`) the launcher calls
`provision_per_boot_certs(repo_root=…)` at Step 1.5 — **after** the
network-facing safety interlock and **before** any service is constructed
(`launcher/__main__.py`). The call:

1. Generates a fresh **ECDSA P-256 self-signed CA** in memory (CN
   `"BlarAI Per-Boot CA"`). The CA private key is a Python object that is
   garbage-collected at process exit; it is **never written to disk, printed,
   or logged**.
2. Issues four leaf certificates signed by that CA, each ECDSA P-256, SAN
   `127.0.0.1`, signed with SHA-256:
   - **PA server** — CN `blarai-policy-agent-server`, EKU serverAuth+clientAuth.
   - **Gateway/AO client** — CN `blarai-gateway-client`, EKU clientAuth+serverAuth.
   - **Orchestrator** — CN `blarai-orchestrator` (its own listener cert *and* its
     PA-client cert), EKU serverAuth+clientAuth.
   - **Semantic Router** — CN `blarai-semantic-router`, EKU clientAuth+serverAuth.
3. Writes **nine PEM files** to `certs/` (gitignored): `ca.pem` (CA public cert
   only) plus a cert+key pair for each of the four leaves.

The peer identity is carried by the **CN** — the PA's mutual-TLS verification
accepts any leaf signed by the current per-boot CA, and the CN distinguishes
which service is speaking. Both sides resolve to the same in-memory CA of the
current boot, so a handshake succeeds only with freshly-minted, mutually
consistent credentials.

#### 3.2 Consumption — CERT_REQUIRED, both directions

The launcher threads the written paths into service construction. The PA server
reads its `[ipc]` cert paths and builds a `CERT_REQUIRED` server context
(`create_server_ssl_context` — TLS 1.2 floor, verifies the client cert against
`ca.pem`). The UI Gateway / AO client builds the mirror-image `CERT_REQUIRED`
client context (`create_client_ssl_context` — same CA, `check_hostname=False`
because the channel is addressed by loopback/GUID, not hostname). In the default
**host-mode** topology the channel is `AF_INET` loopback (127.0.0.1) wrapped in
mTLS; loopback traffic never leaves the machine.

#### 3.3 Validity window & "renewal"

The nominal certificate lifetime is **24 hours** (`CERT_LIFETIME_HOURS = 24`) —
long enough that an unclean shutdown does not force immediate re-issuance. In
practice the CA private key dies with the process, so the **effective** lifetime
is the boot session. There is **no in-session renewal path and no need for one**:
renewal *is* the next boot's fresh mint. Re-calling `provision_per_boot_certs`
produces certificates with different serial numbers, public keys, and signatures
from the previous call — that is the rotation mechanism (§8.2). A session that
somehow ran past 24 hours would hit expiry; the dispatch reuse window (§4.2)
explicitly re-checks expiry so a reused set can never outlive the 24-hour bound.

#### 3.4 Fail-closed discipline

Every error path denies:
- `CertProvisioningError` aborts startup before any service is constructed — a
  provisioning failure never degrades to an unauthenticated start.
- A connector with empty cert paths refuses the connection (returns `None`)
  rather than falling back to plaintext.
- An SSL-context load failure returns `None`, which fails the listener/connector
  closed.

The **sole** production no-mTLS exception is the explicit
`allow_plaintext_hyperv` guest bring-up opt-in (#655) — never a default, logged
loudly when taken, and irrelevant to the live host-mode topology.

### 4. The reboot / re-mint lifecycle (LIVE)

Because credentials are per-boot, anything that reboots a service re-mints — and
the system has three live mechanisms that keep re-minting safe when reboots
overlap. This is the hardest-won part of the lifecycle; every mechanism below
traces to a real overnight-dispatch incident.

#### 4.1 Single-instance guard — no concurrent cert-stomp

`provision_per_boot_certs` **overwrites** the shared `certs/` dir on every mint.
Two launchers on the same checkout would stomp each other's CA, so a leaf signed
by one boot's CA would be presented to a peer trusting a different boot's CA —
`CERTIFICATE_VERIFY_FAILED`, fail-closed. `launcher/instance_lock.py` acquires a
**per-checkout PID lock** (`certs/launcher.lock`) *before* cert provisioning; a
second launcher on the same checkout refuses cleanly without ever touching the
certs dir. The lock is keyed to the certs dir it protects, so launchers in
separate worktrees (separate certs dirs) never collide. A holder is confirmed to
actually be a live `python -m launcher` before a refusal, so a recycled PID after
a crash is reclaimed rather than falsely refusing.

#### 4.2 The dispatch/battery cert-reuse window (#863, ADR-026 Amendment 1)

The overnight dispatch battery re-boots the AO before each job. Under a
still-alive or leaked prior AO, an unconditional fresh mint rotates the CA out
from under the prior AO's in-memory leaf → `CERTIFICATE_VERIFY_FAILED` → a
deterministic per-job stall (the night-20260711 incident). The fix is an
**opt-in, verify-before-reuse** window:

- `provision_per_boot_certs(reuse_if_consistent=True)` reuses an existing on-disk
  set **only when it is cryptographically proven self-consistent** —
  `_load_consistent_certs` requires all nine PEMs present and non-empty, the CA
  and all four leaves unexpired, and, for each leaf, an actual ECDSA verification
  that the on-disk CA signed it (the exact operation the TLS handshake performs).
  Any failure — missing file, malformed PEM, or a cross-generation set — falls
  through to a fresh mint.
- Activation is **env-gated** (`BLARAI_REUSE_CERTS`), never a config default. The
  only setter is `boot_launcher_detached` in the dispatch harness, which sets it
  on the child environment for the battery preflight boot, the per-job
  `AoReensurer` re-ensure, and the swap-probe restore. A normal interactive or
  production `python -m launcher` never passes through that path, never sees the
  env var, and **always mints fresh** — the base per-boot design (§3) is
  unchanged on every human-facing launch.

This narrows the CA-private-key exposure from "one boot" to "one dispatch night"
on the dispatch path only; the LA ratified that trade explicitly (ADR-026
Amendment 1).

#### 4.3 The teardown barrier — prove the prior instance dead before re-mint

The reuse window fixes cert *agreement* between successive boots but leaves the
other shape of an AO-lifecycle overlap open: a still-live prior AO still holds
the AO's port when the replacement tries to bind it. `run_teardown_barrier`
(`tools/dispatch_harness/battery.py`) runs inside `boot_launcher_detached`
**before** the replacement is spawned. It composes only already-audited
primitives — the instance-lock's own liveness check, the tree-kill escalation
the swap probe already uses, and a bounded port-quiet poll:

1. Identify the current lock holder; confirm it is a live launcher.
2. If live, tree-kill it (`terminate_process_tree`: leaves-first terminate, ~3 s
   grace, then kill anything still alive).
3. Poll until the port is actually quiet (bounded at 15 s). **Fail-closed**:
   raise `TeardownBarrierError` naming the PID and port rather than booting a
   replacement onto a port a prior instance may still hold.

If there is no live holder it returns immediately without touching the port.

#### 4.4 mTLS-health re-ensure — re-boot a cert-orphaned AO

Before each battery job, `AoReensurer` treats readiness as **socket liveness AND
a real mTLS handshake** (`probe_ao_mtls`). An AO whose socket is up but whose
leaf no longer verifies against the current on-disk CA — the 2026-07-06
cert-drift trap — is **re-booted, not reused**. When the certs are absent
(never true in production, where the launcher mints them at boot) readiness
degrades to socket-only rather than looping on a reboot it cannot cure.

### 5. Long-lived clients follow the re-mint (#805 / #906 / #907, LIVE)

The UI Gateway builds the client mTLS `SSLContext` once and caches it, so the
per-message connection-per-request architecture does not re-read the PEMs and
rebuild the context on every turn (#805). But "once" is scoped to the **cert
generation, not the process lifetime**: the battery runner holds one gateway all
night, outliving AO launcher reboots, and a swap-restore relaunch re-mints
`certs/` underneath it. A context cached across that re-mint verifies against the
now-superseded CA and the next connect dies `CERTIFICATE_VERIFY_FAILED`
(night-20260714).

Two mechanisms keep the cached client credential correct:

- **Generation fingerprint (#906):** `_cert_generation_fingerprint` reads
  `(st_mtime_ns, st_size)` for the client cert, key, and CA — three `os.stat`
  calls per connect. `_client_ssl_context` compares this at every connect and
  rebuilds the context on a **provable** change (a re-mint rewrites all three
  files). An *unknown* generation (files absent or mid-mint) keeps serving the
  cached context rather than failing on unreadable files.
- **Bounded verify-failure retry (#906 host / #907 guest):** on an
  `SSLCertVerificationError` specifically — never a timeout or refusal, so no
  timeout doubling — the client drops the cache, rebuilds from the current
  on-disk set, and retries **once**. A genuine trust mismatch stays a loud
  failure, never a loop; verification is never relaxed (the retry re-verifies
  against the freshly-read CA). #906 covers the host loopback path; #907 extends
  the identical guard to the guest `AF_HYPERV` path.

Fail-closed is preserved exactly: a rebuild failure returns `None` (the caller
refuses the connection) and is not cached, so the next connect retries rather
than being permanently poisoned.

### 6. At-rest key lifecycle — the DEK envelope (ADR-025, LIVE)

The at-rest encryption key is the second credential family. A single 256-bit
random **DEK** encrypts every sensitive field across `sessions.db`,
`substrate.db`, `knowledge.db`, and the generated-image store. The DEK is
**dual-wrapped** into two independent wrap records that each unwrap the *same*
DEK:

1. **TPM wrap (daily path):** the DEK sealed under a non-exportable RSA-2048
   OAEP-SHA-256 TPM key (`BlarAI-DEKSeal`). The private key never leaves the chip.
2. **Recovery wrap (break-glass):** the DEK encrypted under the 256-bit offline
   recovery key, generated once at the ceremony and held **off-box** by the LA.

Lifecycle facts an auditor needs:
- The DEK is **never written to disk in clear**. Only the two wrap records live
  on disk (`%LOCALAPPDATA%\BlarAI\dek_keystore.json`).
- On boot the DEK is unwrapped TPM→recovery in order; the derived subkeys
  (`k_enc` for AES-256-GCM field encryption, `k_idx` for the index HMAC) come via
  HKDF-SHA256 so the sealed master is never used directly.
- **Fail-closed boot gate:** if the TPM cannot unseal the DEK **and** no recovery
  key is supplied, the store refuses to open. There is no plaintext fallback,
  ever. The dev-only `SoftwareSealer` is banned from the production factory.
- **Recovery (dead chip):** on a new machine the operator supplies the recovery
  key → it unwraps the DEK → the stores decrypt → the DEK is re-sealed to the new
  TPM. The ceremony runbook (ADR-025 §2.5) specifies the non-developer steps.
- **Rotation** is *designed-for, not built* — each wrap record and field blob
  carries a version byte so a future DEK rotation is a format-compatible
  migration. The documented re-key trigger (~2³² encryptions under one key) is
  effectively never reached at single-user scale.
- **Bulk-read quarantine (§2.7 amendment):** a single un-decryptable row in a
  bulk read is quarantined (omitted + logged with a stable code), never returned
  as plaintext; single-record reads keep hard fail-closed. This keeps one legacy
  or tampered row from denying access to an entire store.

### 7. TPM-resident signing keys & the model-integrity gate (LIVE)

`shared/security/tpm_signer.py` binds to the real TPM 2.0 through the Windows
CNG `ncrypt.dll` (Microsoft Platform Crypto Provider), creating **non-exportable
ECDSA P-256** keys and signing/verifying via `NCryptSignHash` /
`NCryptVerifySignature`. This is **software-invoked signing over a
hardware-held, non-exportable key** — it is live, and it is distinct from the
declined *hardware-sealed / PCR-bound* key model in §9.

Two live consumers:
- **Model manifest signing** — `[security].require_signed_manifest = true` (a
  real config default) makes the boot cascade verify a TPM signature over the
  weight manifest before the model loads, fail-closed on a missing or invalid
  `.sig`. Documented in full in [weight-integrity.md](weight-integrity.md);
  the signing key is a sibling of the credentials here.
- **PA JWT signing key** (`BlarAI-PA-JWT-Signing`, ADR-021) — TPM-sealed,
  non-exportable, fail-closed-until-provisioned. Its public half
  (`certs/pa_public.pem`) is the sole git-tracked certificate and the documented
  trust anchor. **Honest status note:** the key and its boot path are
  production-real, but the token layer it signs is currently reached by nothing
  live (§9.2). The audit-signing key (`BlarAI-Audit-Signing-Key-v1`) is
  provisioned; the PA uses the dev HMAC signer until the dev-mode-off flip (ADR-025
  §2.8(a)).

Re-provisioning any TPM-resident key is an **LA-present ceremony**
(`docs/runbooks/manifest_signing_ceremony.md` is the pattern), never an
autonomous step.

### 8. Operational runbooks

#### 8.1 Storage locations & DACL hardening (LIVE, #637)

| Location | Contents |
|---|---|
| `certs/` (gitignored) | The nine per-boot PEMs + `launcher.lock` (the live launcher PID) |
| `certs/pa_public.pem` (**tracked**) | The ADR-021 TPM JWT public trust anchor |
| `%LOCALAPPDATA%\BlarAI\dek_keystore.json` | The DEK dual-wrap records (DEK never in clear) |

Every boot, inside `provision_per_boot_certs` (both the fresh-mint and the reuse
branch), `strip_foreign_sids_from_dir` (`shared/security/file_dacl.py`) walks the
`certs/` DACL and removes only **orphaned / foreign** access-control entries —
SIDs that are not the current user, not a well-known/builtin or AppContainer SID,
and not resolvable to a live local account (the observed cross-machine
`S-1-5-21-76345465-…` entry carried in from repo history). It is owner-preserving,
idempotent, Windows-only, and **fail-safe**: it never raises and never blocks
provisioning, and is a no-op on a clean directory or a non-Windows host. The
remediation is self-healing — no manual operator step.

#### 8.2 Manual certificate-state inspection

- **Presence check:** `verify_per_boot_certs_exist(certs)` returns whether all
  nine PEMs are present and non-empty (a lightweight sanity check; it does not
  validate cryptographic content — the SSL context does that at load).
- **Content inspection (dev-side):** `openssl x509 -in certs/ca.pem -noout -text`
  and the leaves — confirm issuer CN `BlarAI Per-Boot CA`, the expected subject
  CNs (§3.1), the 24-hour not-before/not-after window, and that serial numbers
  **differ across boots** (proof the mint rotated).
- **Consistency check:** `_load_consistent_certs` performs the same
  CA-signed-this-leaf ECDSA verification the handshake performs — a pass proves a
  set will complete the handshake.
- **Live health probe:** `probe_ao_mtls` / `ao_mtls_healthy` drive a real mTLS
  handshake against a running AO, distinguishing "socket up but cert-orphaned"
  from "healthy" (§4.4).
- **Who holds the launcher:** `certs/launcher.lock` records the live launcher PID.

#### 8.3 Compromise recovery & rotation

- **Rotate the transport credentials:** the per-boot design makes rotation
  routine — **reboot the launcher and the entire chain re-mints** (new CA, new
  leaves, old CA private key discarded). To force a clean slate, stop BlarAI,
  delete the nine per-boot PEMs from `certs/` (**leave `pa_public.pem`**, the
  tracked anchor), and reboot; an absent set falls through to a fresh mint
  (§4.2). A leaked per-boot key is already contained to its boot session (24-hour
  cap; the CA private key never survives the process). If a stale AO is still
  running, stop it first — otherwise the single-instance guard (§4.1) or the
  teardown barrier (§4.3) will refuse or reclaim, by design.
- **Recover at-rest data after chip loss:** use the offline recovery key
  break-glass (§6 / ADR-025 §2.5 ceremony) — unwrap the DEK, decrypt, re-seal to
  the new TPM.
- **Suspected TPM-key compromise:** the JWT, audit, and DEK-seal keys are
  non-exportable and fail-closed-until-provisioned; re-provisioning is an
  LA-present ceremony (§7). There is no self-service rotation of a TPM-resident
  key.

#### 8.4 Fallback when the Policy Agent is unreachable (LIVE, fail-closed)

The gateway's Boot-Phase-3 handshake (`check_pa_status`) retries on a
capped-exponential backoff whose sleeps sum to `PA_HANDSHAKE_BUDGET_S` (180 s,
the documented cold-14-billion-parameter-load ceiling). On budget exhaustion it
transitions to `FAILED` and returns false — **fail-closed**. A
*structurally-absent* precondition — missing per-boot mTLS cert paths, or no
configured endpoint — raises `HandshakeConfigurationError` and fails
**immediately** without retries: patience cannot mint a certificate or a port.
Production always requires mTLS; the connect helpers refuse a bare connection.
There is no unauthenticated fallback to the PA.

### 9. Declined & deferred scope

This section confines the hardware-rooted-trust ambition the original ticket
(#14) described. None of it is live; each item is either an LA decision against
it or a tracked deferral.

#### 9.1 Hardware-rooted trust — declined / deferred

- **Pluton-sealed CA key** (ADR-026 §4.2, "FUT-01"): sealing the per-boot CA key
  inside the Pluton enclave. **Deferred** — per-boot in-memory generation already
  achieves the key benefit (no persistent key on disk) without the hardware
  dependency.
- **Measured-image CN binding** (ADR-026 §4.3 / §5.1, "FUT-02"): deriving the
  certificate CN from a measured boot-image hash so a tampered image mints a
  verifiably different cert. **Deferred.** The per-boot certs deliver
  *freshness* (each boot is a new, unlinked chain) but **not** issuer
  attestation — the issuer name is a fixed constant regardless of image
  integrity. *Freshness proven; issuer attestation not.*
- **PCR-binding of trust-root keys** (ADR-028 Amendment 1, 2026-06-10):
  **decided against.** Informed by an on-chip PCR-seal proof-of-concept
  (2026-06-09) that proved it feasible, the LA ruled that production trust-root
  keys stay **TPM-resident + non-exportable + DACL-locked, not PCR-gated**.
- **True TPM PCR measured-boot attestation** (ADR-028, #627): firmware /
  bootloader / OS boot-chain integrity checking. **Deferred** post-gate
  hardening, threat-orthogonal to the current single-user local threat model.
- **Broader "no full hardware-rooted trust" posture** (LA decision 2026-07-15):
  the system documents and ships the **live software posture** — signed weight
  manifests, TPM-resident (non-sealed) signing keys, per-boot mTLS, and at-rest
  encryption — and declines full hardware-rooted sealing/measured-boot. A boot
  step historically named "verify TPM/Pluton attestation" performs software-only
  validation. Decision-register reconciliation for this 2026-07-15 posture is
  tracked (#908); the PCR-key half is already anchored by ADR-028 Amendment 1.

#### 9.2 The Agentic-JWT authorization fabric — DESIGN-INTENT, vestigial (#910)

The original ticket assumed a live cryptographic-receipt layer: the Policy Agent
mints a short-lived JSON-Web-Token per adjudication, and every destination
enforces a five-stage gate (ES256 signature, expiry, an **epoch** counter for
lazy revocation, a **nonce**-seen set for single-use, and a Canonical-Action
hash match). That code **exists** — `shared/crypto/jwt_validator.py`
(`AgenticJWTValidator`, `NonceStore`, `EpochTracker`) and
`services/policy_agent/src/jwt_minter.py` — and is well-tested.

It is **not the live authorization boundary.** Per ADR-041 (LA decision
2026-07-15): the live host-mode boundary is the in-process
`DeterministicPolicyChecker` + the fixed tool allowlist + the structural egress
spine + per-boot mTLS + at-rest encryption. The Agentic-JWT fabric was designed
for a per-agent-VM topology that is **foreclosed** — the model runs only on the
host GPU, unreachable from a Hyper-V guest (ADR-011) — so no live code sends a
Canonical Action to the PA over vsock, no JWT is minted for a real request, and
**no destination validates a receipt**. The layer is **slated for removal as
dead code (#910)**. The nonce/epoch/receipt-lifecycle content the old ticket
description assumed live is documented here, in the declined section, precisely
because it is not the shipped posture.

#### 9.3 Certificate revocation & epoch rotation — deferred (ADR-026 §5.3, #105)

The per-boot certificates ship with **no revocation list and no epoch-rotation
mechanism**. The 24-hour per-boot lifetime (§3.3) makes revocation low-urgency
for the current single-user, local-only threat model — a compromised credential
is superseded by the next boot's fresh mint. The ticket is on the radar (#105)
but unbuilt.

---

## Cross-reference index

| Topic | ADR / decision | Ticket(s) | Code |
|---|---|---|---|
| Per-boot mTLS certs | ADR-026 | #598 | `shared/security/cert_provisioning.py`, `shared/ipc/vsock.py` |
| Cert reuse window | ADR-026 Am. 1 (2026-07-12) | #863 | `provision_per_boot_certs(reuse_if_consistent=…)`, `battery.py` |
| Teardown barrier | — (ADR-026 Am. 1 §A1.5 follow-up) | #863 | `battery.py::run_teardown_barrier` |
| Client-context cache follows re-mint | — | #805, #906, #907 | `services/ui_gateway/src/transport.py` |
| DACL hardening | — | #637 | `shared/security/file_dacl.py` |
| At-rest DEK envelope | ADR-025 (+§2.7) | #559, #598 | `shared/security/dek_envelope.py`, `tpm_sealer.py` |
| TPM manifest signing | ADR-018, ADR-021 | #106 | `shared/security/tpm_signer.py`; [weight-integrity.md](weight-integrity.md) |
| Host-mode authorization boundary | ADR-041 (2026-07-15) | #910 | `services/policy_agent/src/entrypoint.py` (`DeterministicPolicyChecker`) |
| Declined PCR key-binding | ADR-028 Am. 1 (2026-06-10) | #627 | — |
| No full hardware-rooted trust | LA decision 2026-07-15 | #908 | — |
| Agentic-JWT fabric (vestigial) | ADR-041 | #910 | `shared/crypto/jwt_validator.py`, `services/policy_agent/src/jwt_minter.py` |
| Cert revocation / epoch (deferred) | ADR-026 §5.3 | #105 | — |
