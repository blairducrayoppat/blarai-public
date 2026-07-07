# ADR-021: TPM-Sealed Policy Agent JWT Signing Key + Provisioning Ceremony

**Status:** ACCEPTED — 2026-06-03 (Tier-0 security hardening; LA-approved)
**Author:** Lead Architect (Blair) + Claude Opus 4.8 (1M context)
**Related:** ADR-018 (TPM 2.0 trust root — the non-exportable-signing primitive
this consumes), ADR-012 §1–§5 (the Agentic JWT this signs), ADR-020 (the
egress kill-switch — the other half of Tier 0). Roots in the 2026-06-03 security
audit (`docs/security/audit_2026-06-03/`, the single **Critical**). BUILD_JOURNAL
lessons 18 (verify the silicon) and the 2026-06-03 rotation entries. Tracks
Vikunja #557 (Tier 0) under umbrella #555; internet-facing gate #556/#787; Tier-1
`dev_mode` flip #558.

---

## 1. Context

The security audit returned one **Critical**: the Policy Agent's JWT signing key,
`certs/pa_private.pem`, is an unencrypted ES256 (ECDSA P-256) private key
**committed to git in cleartext** — and it is the *configured production key*
(`config/default.toml:26`). The Policy Agent's entire job is to authorize actions
by minting signed tokens that every other service trusts; whoever holds that key
can forge an ALLOW for any action. A signing authority living in cleartext in the
repository (and its history) is the highest-severity finding the audit produced.

The fix is tractable because the contract is **asymmetric**: a JWT is signed by
one party and verified by many against a *public* key. Only the signing side must
change. ADR-018 established — and proved on the reference unit's actual silicon —
that this machine has a TPM 2.0 (STMicroelectronics; Pluton present but not the
active TPM) reachable through the Windows CNG *Microsoft Platform Crypto
Provider*, capable of generating a **non-exportable** ECDSA P-256 key that cannot
leave the chip even by the creating process. That primitive (`shared/security/
tpm_signer.py`) is what this ADR consumes.

The mechanism was built and proven on-chip in a prior increment (the hand-built
JOSE `_mint_tpm` path + `from_tpm` factory + a five-stage on-chip test:
provision → TPM-sign → export public → validate through the real production
validator). What that increment deliberately did **not** do is flip production
over. This ADR records the decision that completes the rotation: switch the
configured production path to the TPM key, generate its public half through a
ceremony, and remove the cleartext key.

## 2. Decision

Make the Policy Agent's production JWT signing key a **non-exportable TPM key**,
established by a **one-time human-run provisioning ceremony**, and **remove the
cleartext key** from the tree.

- **Signing (production):** `AgenticJWTMinter.from_tpm("BlarAI-PA-JWT-Signing")`
  (`PA_JWT_TPM_KEY_NAME`). The private key is generated inside the TPM and never
  exported; minting builds the JWS by hand and signs the signing-input via
  `tpm_signer.sign`.
- **Verifying (unchanged):** every service still loads a public key from a file
  and validates against it. The file moves from the old `certs/ca.pem` to
  `certs/pa_public.pem` (the TPM key's exported public half) in the PA, Assistant
  Orchestrator, and Semantic Router JWT-validator configs. The mTLS `ca.pem`
  references (`[ipc]`) are a *different* trust chain and are **left untouched**
  (Tier 2, #559).
- **Removal:** `certs/pa_private.pem` is removed from the working tree. It remains
  in git history (it is not, and cannot be, scrubbed from a non-rewritten
  history) — see §2.5 for why that is acceptable.

### 2.1 Provisioning is a ceremony, not an automatic step

`python -m shared.security.provision_signing_key` — run **once, by the operator,
on the deployment host**. It asserts a TPM is present (fail-closed otherwise),
idempotently creates the non-exportable key, exports its public half to
`certs/pa_public.pem`, and prints the public key's **SHA-256 (SubjectPublicKeyInfo
DER) fingerprint** with the key name and date.

**Rejected alternative — auto-provision at first boot.** Establishing a signing
authority is a trust-rooting act; making it an automatic side-effect of startup
would mint keys on dev and CI machines that nobody audits, and would blur the one
moment a human should witness ("this chip, this key, this fingerprint, this
date"). The ceremony makes provisioning a deliberate, observable, recordable
event. The cost — production cannot sign until the operator runs it — is accepted
and is itself the security posture (§2.3).

### 2.2 The trust anchor is the fingerprint, recorded in git — not the key

`certs/pa_public.pem` is **gitignored, never committed**. A TPM key is
non-exportable and *machine-bound*: its public half is specific to one chip, not
a portable constant. Committing it would bake one machine's key into a repository
framed for "decades across hardware generations," and every hardware migration
would silently carry a stale anchor. Instead the ceremony prints the canonical
`SHA-256(SPKI DER)` fingerprint — independently reproducible with
`openssl pkey -pubin -in pa_public.pem -outform DER | openssl dgst -sha256` —
and *that* is recorded in git (this ADR / the rotation journal entry) as the
auditable trust anchor. The public key is documented without committing one
chip's bytes.

**Rejected alternative — commit `pa_public.pem`.** Tempting for single-machine
convenience, but wrong for a per-chip, decades-spanning artifact; the fingerprint
gives auditability without the stale-anchor liability.

### 2.3 The `dev_mode` interlock and the fail-closed-until-ceremony posture

This is the governance decision an auditor should look for, so it is stated
plainly:

- The host runs **`dev_mode = true`** today (PA/AO `guest_runtime.toml`). In dev
  mode the minter uses an **ephemeral in-memory key** and **never touches the
  TPM**. So the *running* runtime is unaffected by this change — it does not yet
  exercise the TPM key at all.
- This increment makes the TPM key **the configured production key** and removes
  the cleartext one. The runtime only *uses* the TPM key once **Tier 1 (#558)**
  flips `dev_mode` off. Until then the new path is configured-but-dormant.
- After this increment, **production preflight is fail-closed until the ceremony
  has been run** on the host: with `dev_mode = false` and the key unprovisioned
  (or the TPM unavailable), `PolicyAgentService` refuses to start
  (`PA_CFG_JWT_TPM_KEY_NOT_PROVISIONED` / `PA_CFG_JWT_TPM_UNAVAILABLE`) rather
  than fall back to a software key. There is no silent-fallback path — that
  absence *is* the control.

In one sentence for the handoff: **after this increment the Critical is closed in
the tree, but the TPM key is not yet live; it goes live when Tier 1 turns
`dev_mode` off, and production is fail-closed until the operator runs the ceremony
on that host.**

### 2.4 Why the slowness is the security property

Measured on the reference TPM (recorded in `PERFORMANCE_LOG.md` /
`docs/performance/tpm_signing_latency_2026-06-03.json`): a signature ≈ **94 ms**,
a key-existence check ≈ **3 ms**, one-time provisioning ≈ **248 ms**. The
boot-attributable cost is the 3 ms check — negligible beside the 14B compile that
owns \~53% of boot. The 94 ms is a *runtime, per-authorization* cost, one token
per gated action, well under ADR-012's 750 ms approval budget. It is \~900× slower
than signing in software, and that slowness *is* the property being bought: a key
that never leaves the chip.

### 2.5 Why the old key stays in history (no rewrite)

**Rejected alternative — rewrite history to purge `pa_private.pem`.** History
rewriting is destructive (invalidates every downstream clone/SHA, risks the audit
trail) and, more to the point, **unnecessary**: the rotation makes the old key
*worthless*. Production will trust only the new TPM key's public half; a forger
holding the old private key can sign tokens that no validator accepts. The honest
record — "this key was cleartext, here is the commit, here is how it was rotated
out" — is more valuable to the portfolio and the audit than a sanitized history.
The removal from the working tree closes the exposure going forward; the history
entry documents the lesson.

## 3. Consequences

**Positive.** The audit's single Critical is closed in the tree: the key the
authorization model trusts is no longer a file in the repository — it is a
non-exportable key sealed in the platform TPM, and production cannot sign with
anything weaker (fail-closed, no software fallback). The validator side did not
have to change, so the two-sided sign/verify contract never disagreed about which
key is real.

**Limits (on the record).** The TPM protects the *private key's
non-exportability*; it does not by itself prove *which process* is allowed to ask
the TPM to sign. On a single-process host that is the host's own boundary; when
the Policy Agent moves into the VM guest (Tier 2, #559) the right-to-sign must be
bound to the guest's identity, and the ceremony may need to run guest-side. That
is a named Tier-2 follow-up, not a silent gap. Likewise, the `guest_runtime.toml`
profiles keep empty/dev key fields today; giving the guest production TPM parity
is Tier-2-adjacent and deferred.

**Operational.** A fresh checkout has no `pa_public.pem` and cannot run production
JWT validation until the ceremony runs — by design (§2.3). Dev mode is unaffected
(ephemeral keys), so the test suite and local development need no TPM.

## 4. Verification

- **Headless (done):** `services/policy_agent/tests/test_entrypoint.py` — the
  production-config success path (TPM key stubbed present, validator loads a real
  public key) and a parametrized **fail-closed preflight** test proving startup
  refuses when the key is unprovisioned *and* when the TPM is unavailable.
  `shared/tests/test_provision_signing_key.py` — the ceremony writes the public
  PEM, prints the canonical fingerprint, is idempotent, and refuses fail-closed
  without a TPM. `services/policy_agent/tests/test_jwt_minter.py` Group F — the
  hand-built JOSE path validates through the real validator with a software TPM
  stand-in. Full sweep green (no regression).
- **On-chip (`@slow`, done by the implementing session):**
  `test_jwt_minter.py` Group G (provision → TPM-sign → export → validate on the
  real chip) and `test_provision_signing_key.py::TestProvisionCeremonyOnChip`
  (the ceremony writes a public key the production validator loads, and the
  exported public half verifies a real TPM signature — key correspondence).
- **Live (LA, Tier-0 checkpoint):** run the provisioning ceremony on the chip;
  confirm `certs/pa_public.pem` is written and a sign→validate round-trips on the
  real TPM; confirm the printed fingerprint is recorded here as the trust anchor.
  On green (with the egress guard armed in a real boot), Tier 0 merges to main and
  the `dev_mode` flip moves to Tier 1 (#558).

## 5. Trust anchor (recorded)

The provisioning ceremony was run on the reference host on **2026-06-04**, and a
production sign→validate round-trip with this key passed on the real TPM at that
time (real TPM key signs; `certs/pa_public.pem` validates; decision `ALLOW`). The
Policy Agent's production JWT public key — the anchor every validator checks
against — has:

```
key name           : BlarAI-PA-JWT-Signing
SHA-256 (SPKI DER) : 2df651d3fc0bd059c363575113a3bb068d6f70c012abcafa95ef585de4793c60
provisioned (UTC)  : 2026-06-04T04:52:13Z
```

Reproduce with `openssl pkey -pubin -in certs/pa_public.pem -outform DER | openssl dgst -sha256`.
This fingerprint is **per-deployment**: it identifies *this* host's TPM key. A
re-provision on different hardware mints a different key and a different
fingerprint, which is then recorded here in its place. The private half is
non-exportable and never left the chip; `pa_public.pem` is per-chip and
gitignored.
