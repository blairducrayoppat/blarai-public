# ADR-026: Per-Boot Ephemeral mTLS Certificates for the Host↔VM vsock Channel

**Status:** ACCEPTED — 2026-06-06 (Sprint 15 / Tier-2 production-posture; EA-1); **Amendment 1 (2026-07-12) — cert reuse-window for dispatch/battery AO reboots, LA-ratified**
**Author:** code-specialist subagent (Claude Sonnet 4.6) for Lead Architect (Blair) review
**Related:** ADR-018 (TPM 2.0 trust root — foundational hardware trust),
ADR-021 (TPM-sealed PA JWT signing key — the per-chip ceremony pattern this mirrors),
ADR-020 (egress kill-switch — already armed; this ADR hardens the vsock channel),
ADR-025 (at-rest encryption — the DEK envelope precedent from Sprint 14).
Tracks Vikunja #598 (air-gap-removal gate, Tier-2 production-posture campaign).
Contributes cert machinery consumed by EA-4 fidelity-2 live-verify.

---

## 1. Context

The vsock channel between the BlarAI host and the Policy Agent VM is the
single trust boundary through which every adjudication request passes.
ADR-007 established mTLS as the mandatory transport-layer authentication
mechanism for this channel; `shared/ipc/vsock.py` has supported
`CERT_REQUIRED` SSL contexts since the P1.6 milestone.

However, as of Sprint 14's closure the cert paths in
`services/policy_agent/config/default.toml` (`[ipc]` section) were
**unprovisioned placeholders** — the files pointed to by
`certs/pa_server.pem`, `certs/pa_server_key.pem`, and `certs/ca.pem` did
not exist.  The production-posture startup (`dev_mode=false`) would
therefore fail at the mTLS context load step, before any service was ever
started in production.

A second gap was present on the **client side**: `TransportGateway._connect_hyperv()`
was constructing a raw AF_HYPERV socket and wrapping it in a `VsockConfig`
with *no cert paths set*.  Even if the PA server had valid certs, the
gateway client would present no client certificate and the handshake would
fail the server's `CERT_REQUIRED` check.

Sprint 15 Tier-2 closes both gaps: generate the certs automatically at
boot, and wire the provisioned paths into both the PA server listener and
the gateway client connector.

## 2. Decision

**Per-boot ephemeral mTLS certificate provisioning** for the vsock channel.

On every production boot (`dev_mode=false`), the launcher calls
`shared.security.cert_provisioning.provision_per_boot_certs()` to generate:

1. A **per-boot Certificate Authority (CA)** — ECDSA P-256, self-signed,
   in-memory private key only (never written to disk).
2. A **PA server certificate** — ECDSA P-256, CN = `blarai-policy-agent-server`,
   SAN = `127.0.0.1` (host-local loopback for fidelity-2 verify), EKU =
   `serverAuth + clientAuth`, signed by the per-boot CA.
3. A **gateway/AO client certificate** — ECDSA P-256, CN = `blarai-gateway-client`,
   SAN = `127.0.0.1`, EKU = `clientAuth + serverAuth`, signed by the per-boot CA.
4. An **orchestrator certificate** — ECDSA P-256, CN = `blarai-orchestrator`,
   SAN = `127.0.0.1`, signed by the per-boot CA (the AO listener + its PA client —
   serverAuth + clientAuth).
5. A **semantic-router client certificate** — ECDSA P-256, CN = `blarai-semantic-router`,
   SAN = `127.0.0.1`, signed by the per-boot CA (clientAuth).

All **nine PEM files** are written to the `certs/` directory (gitignored) and
consumed immediately by service construction: `ca.pem` (the CA *public* cert; the
CA private key stays in memory), plus a cert+key pair each for the PA server,
gateway/AO client, orchestrator, and semantic router
(`pa_server.pem`/`pa_server_key.pem`, `gateway_client.pem`/`gateway_client_key.pem`,
`orch_client.pem`/`orch_client_key.pem`, `router_client.pem`/`router_client_key.pem`).
Zero manual steps per boot (SDV criterion #8 — daily-driver continuity).

*(The orchestrator + semantic-router cert pairs were added in EA-4e (`a410be9`) when
the host-mode mTLS handshake surfaced the need for them during the EA-4 production
live-verify; this §2 inventory was reconciled from five to nine PEM artifacts at the
Sprint-15 close per SWAGR MINOR-1 — the shipped `cert_provisioning.py` always minted
nine, asserted by `test_ipc_transport.py::test_provision_writes_nine_pem_files`.)*

### 2.1 Crypto choices

| Property | Choice | Rationale |
|---|---|---|
| Key algorithm | ECDSA P-256 | Matches `_generate_test_certs()` and `tpm_signer` (P-256 is the project's canonical EC curve); smaller than RSA, faster handshake |
| Certificate lifetime | **24 hours** | Long enough to survive an unclean shutdown without immediate re-issuance; in practice the CA private key is discarded with the process, so the effective lifetime is the boot session |
| CA key persistence | **In-memory only** | CA private key is a Python object that is GC'd at process exit; it is never written to disk, printed, or logged |
| Signing hash | SHA-256 | Standard for P-256 |
| Mutual auth | `CERT_REQUIRED` both directions | ADR-007 requirement; no unauthenticated connections accepted |

### 2.2 Launcher wiring site (confirmed trace)

The mint step fires at `launcher/__main__.py` **after the dev_mode + network_facing
interlock** (\~:476) and **before `PolicyAgentService.from_runtime_mode()` (\~:616)**:

```
:458  _dev_mode = resolve_dev_mode(runtime_mode)
:464  try: assert_dev_mode_network_facing_safe(...)    # interlock
:476  return 1  # on interlock failure
        ↓
[NEW] provision_per_boot_certs(repo_root=...) → PerBootCerts  # ADR-026
        ↓
:616  PolicyAgentService.from_runtime_mode(...)         # reads certs/pa_server.pem etc.
:682  AssistantOrchestratorService.from_runtime_mode(...)
:835  TransportGateway(..., mtls_cert_path=..., ca_cert_path=...)  # client side
```

### 2.3 Cert consumption chain (verified)

**PA server side** (`dev_mode=False`):
`entrypoint.py:611-625` reads `[ipc].mtls_cert_path` / `mtls_key_path` / `ca_cert_path`
→ `VsockConfig` with paths set → `PolicyAgentListener(config, dev_mode=False)`
→ `VsockListener.start()` → `create_server_ssl_context()` → `CERT_REQUIRED` handshake.

**Gateway client side** (`dev_mode=False`):
`TransportGateway(mtls_cert_path=..., ca_cert_path=...)` stores paths on `self`
→ `_connect_hyperv()` checks paths non-empty (fail-closed if absent)
→ `create_client_ssl_context()` → `wrap_socket(server_side=False)` → `CERT_REQUIRED` handshake.

Both sides resolve to the same per-boot CA, ensuring the handshake succeeds
only with freshly-minted, mutually-consistent credentials.

### 2.4 Fail-closed discipline

- `CertProvisioningError` aborts startup before any service is constructed.
- `_connect_hyperv()` returns `None` (Fail-Closed) if cert paths are empty
  strings — a provisioning bypass does not silently degrade to an unauthenticated
  connection.
- `create_server_ssl_context()` / `create_client_ssl_context()` return `None` on
  any cert load failure, which causes `VsockListener.start()` to return `False`
  (existing Fail-Closed path).

## 3. Verification posture (fidelity-2)

Sprint 15 verifies over the **real mTLS code path**: production SSL contexts
(`create_server_ssl_context` / `create_client_ssl_context`), `CERT_REQUIRED` in
both directions, and real per-boot cert material.  A local TCP socket transport
is used in place of AF_HYPERV (the guest↔host boundary is deferred, Vikunja #615);
real mTLS over loopback IS fidelity-2 per the ADR-026 design gate.

The test suite (`shared/tests/test_ipc_transport.py`, Groups J / K / L) covers:
- **Group J** — unit tests: nine PEM files written
  (`test_provision_writes_nine_pem_files`), correct CNs, 24-hour lifetime,
  verify function, fail-closed on unwritable dir.
- **Group K** — fidelity-2 handshake: succeeds with valid per-boot certs, fails
  closed with absent certs, fails closed with wrong-CA cert.
- **Group L** — production-wiring regression lock: asserts `dev_mode=False` startup
  path provisions certs AND `TransportGateway` is constructed with non-empty cert
  paths; `_connect_hyperv()` with empty paths returns `None` (Fail-Closed).

The AF_HYPERV guest↔host boundary handshake is EA-4 territory (on-chip
live-verify against the running VM); this ADR claims SDV Condition 2 (host-local),
not Condition 3 (guest boundary).

## 4. Alternatives considered

### 4.1 Long-lived operator-provisioned certs (ceremony model)

Mirror the TPM JWT key ceremony: a human operator runs a provisioning script
once and the certs live in `certs/` for months or years.

**Rejected**: vsock mTLS is a transport-layer control, not an operator-identity
control.  Long-lived certs accumulate exposure window — a leaked private key file
gives an attacker a long window to replay.  Per-boot certs contain the window to
the current boot session, with the CA private key never surviving the process.

### 4.2 Pluton-sealed CA key (FUT-01 full vision)

Seal the per-boot CA key inside the Pluton enclave so the private key is
bound to the chip and never extractable.

**Deferred** (FUT-01): requires Pluton UEFI subsystem access beyond the current
`ncrypt.dll` CNG path.  Per-boot in-memory generation achieves the key benefit
(no persistent key on disk) without the hardware dependency.

### 4.3 Measured-image CN binding (FUT-02 full vision)

Embed the measured boot image hash in the cert CN so a tampered OS produces a
cert with a verifiably different CN, which the peer can reject.

**Deferred** (FUT-02): requires the boot measurement attestation work tracked in
the measured-boot extension.  See §5 (Known Limitations).

## 5. Known Limitations

### 5.1 Freshness proven; issuer attestation not (FUT-02)

Per-boot certs deliver **freshness** — each boot produces a new, unlinked trust
chain, and the CA private key is discarded at process exit so no prior-boot cert
can be replayed.  They do NOT deliver **measured-image CN binding**: the issuer
name is a fixed constant (`"BlarAI Per-Boot CA"`) regardless of whether the
running image is clean or tampered.  A compromised boot image could mint valid
certs indistinguishable from a clean-boot chain.

The full FUT-02 vision — where the CA issues certs with a CN derived from the
Pluton-measured image hash — is deferred pending the measured-boot attestation
work.  *Freshness proven; issuer attestation not.*

### 5.2 Guest↔host AF_HYPERV boundary not yet verified (Vikunja #615)

The current verification is host-local (fidelity-2).  The actual AF_HYPERV vsock
handshake across the Hyper-V guest↔host boundary is EA-4's live-verify scope and
is tracked separately at Vikunja #615.  The cert machinery this ADR introduces is
the prerequisite that EA-4 consumes.

### 5.3 No revocation or epoch mechanism (FUT-03 / Vikunja #105)

This ADR ships cert issuance; revocation and epoch rotation are deferred.  The
24-hour per-boot lifetime makes revocation low-urgency for the current threat
model (single-user, local-only system), but the ticket is on the radar.

## 6. Gitignore discipline

The nine per-boot cert artifacts are added to `.gitignore`:
`certs/ca.pem`, `certs/pa_server.pem`, `certs/pa_server_key.pem`,
`certs/gateway_client.pem`, `certs/gateway_client_key.pem`,
`certs/orch_client.pem`, `certs/orch_client_key.pem`,
`certs/router_client.pem`, `certs/router_client_key.pem`.

The sole exception to this pattern remains `certs/pa_public.pem` (the TPM JWT
public key from the ADR-021 ceremony), which is intentionally tracked as the
documented trust anchor.

---

## Amendment 1 (2026-07-12) — Cert Reuse-Window for Dispatch/Battery AO Reboots

**Status:** RATIFIED 2026-07-12 by the Lead Architect (plain-language governance call: comfortable letting the battery reuse its certificates within a single night rather than re-minting them every reboot — a slightly longer-lived key in exchange for a stable battery). Implemented + merged ahead of ratification (Vikunja #863, `047d5dfc` merging fix `5168c8cb`) under the LA's "fix it ASAP" directive for a defect that was deterministically STALLing every overnight dispatch job (per `CLAUDE.md` §Proactive Defect-Fixing). Refines §2 (per-boot mint) with one narrowly-scoped, opt-in exception; the base decision — every production boot mints a fresh CA + fresh leaves — is **unchanged** and remains the default on every path except the one named in A1.4.

### A1.1 The defect
The overnight dispatch "battery" (`tools/dispatch_harness/battery.py`) re-boots the Assistant Orchestrator mid-run — a preflight boot and, via `AoReensurer`, a re-boot **before each job** (the #750 fix-2 mitigation). Both go through `boot_launcher_detached()` → a fresh `python -m launcher` in production mode → the §2 cert-mint site (`launcher/__main__.py:~1510-1525`), which unconditionally minted a NEW in-memory CA + new leaves every boot. When a prior AO is still alive/leaked at the next reboot, the new on-disk CA cannot verify the stale AO's in-memory leaf (signed by the now-overwritten CA) → `certificate signature failure`, fail-closed (§2.4 — correct in isolation) → every affected job STALLED. This was the night-20260711 incident.

### A1.2 Decision — opt-in, verify-before-reuse
A `reuse_if_consistent: bool = False` keyword on `provision_per_boot_certs()` (`shared/security/cert_provisioning.py`). When `True` AND an existing on-disk set passes the A1.3 consistency check, it is reused in place of minting a new CA. Every call that leaves the default is byte-for-byte the pre-amendment behavior. Activation is env-gated (`BLARAI_REUSE_CERTS`, read at `launcher/__main__.py:1521`), never a config default; the launcher only reads it, and the only setter is `boot_launcher_detached()` (A1.4).

### A1.3 Trust boundary — why it is safe
`_load_consistent_certs()` reuses a set only when it is CRYPTOGRAPHICALLY PROVEN self-consistent: all nine PEMs present + non-empty; the CA and all four leaves unexpired (a reused set cannot outlive §2.1's 24-hour lifetime); and for each leaf, the ACTUAL ECDSA verification `ca_pub.verify(leaf.signature, leaf.tbs_certificate_bytes, ec.ECDSA(...))` — the same operation the TLS handshake performs, not an approximation. Any failure (missing file, malformed PEM, `InvalidSignature` from a mismatched CA) → not reusable → fall through to a fresh mint. A cross-generation set (a new CA beside old leaves) fails by construction. Regression-locked (`shared/tests/test_cert_provisioning.py`, 4 tests incl. the load-bearing `..._rejects_an_inconsistent_set`).

### A1.4 Scope — three dispatch/swap-harness call sites only
Reachable exclusively through `boot_launcher_detached()`, which sets `BLARAI_REUSE_CERTS=1` unconditionally on the child environment, so all THREE of its callers pick up reuse: the battery preflight boot; `AoReensurer.real()`'s per-job re-ensure; and `tools/dispatch_harness/probe.py:265` `_real_restore()` (the swap-driver probe's restore, ADR-034/035 territory). All three are local, unattended, single-operator dispatch/swap tooling — never a human-facing launch. A normal interactive/production `python -m launcher` never passes through `boot_launcher_detached()`, never sees the env var, and always mints fresh. No egress or air-gap change; `certs/pa_public.pem` (the ADR-021 trust anchor) untouched; the CA-private-key-in-memory-only invariant (§2.1) untouched.

### A1.5 Residual risk — mitigated, not eliminated
This removes the CONSEQUENCE (a torn trust chain) of an AO-lifecycle overlap, not the overlap itself (a prior AO still alive when the next reboot fires). The durable fix — a teardown barrier that proves the prior AO dead before the next boot — is tracked follow-up. NB: reuse **re-shapes** a still-live-prior-AO failure from a cert mismatch into a `:5001` port collision (the same overlap, a different symptom), which the teardown barrier also closes. The incident class reached its **third instance** (a 2026-07-06 discovery in `ao_mtls_healthy`'s docstring + #805 + #863); the teardown barrier is its mandated structural control.

### A1.6 Alternatives rejected
(i) Serialize/mutex the mint — rejected: guards writer-vs-writer racing, not the actual failure (a leaked READER AO outliving the CA it trusts). (ii) Fully persistent certs — rejected: discards §2.1 freshness (a longer key-exposure/replay window); §4.1 already rejected the long-lived ceremony model, and persistent certs would leave the port-collision symptom fully live (they only retire the cert-mismatch costume). (iii) The chosen opt-in verify-before-reuse — accepted.

### A1.7 Relationship to #805
The same night's #805 (`92958ab9`) is an adjacent-LAYER fix — a `ui_gateway` transport-client efficiency change (cache the client `SSLContext` once at first connect instead of rebuilding it per message; cache-miss stays fail-closed). Different layer, different failure shape from #863 (launcher-side cross-boot CA re-mint); both sit on the §2 per-boot design but neither subsumes the other.

---

*Authored 2026-06-06 by code-specialist (EA-1, Sprint 15 Tier-2 production-posture).*
*EA-4 fidelity-2 live-verify is the next gate consuming this machinery.*
