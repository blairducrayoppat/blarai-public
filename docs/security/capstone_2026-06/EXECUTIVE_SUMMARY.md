# Executive Summary — Air-Gap Removal Go/No-Go (#598)

**Date:** 2026-06-08 · **For:** the Lead Architect's #598 decision · **Companion to:** the #612 capstone
security deck (`capstone_presentation.html`). **Basis:** a disk-rooted reconciliation of the 2026-06-03
security audit — every claim below was verified against the current code, not inherited from a narrative.

---

## Recommendation: NO-GO — not yet.

**Do not remove the air-gap now.** Remove it only after a short, defined finish-list — and the
encouraging part is that **most of that list is wiring and *exercising* controls that are already built**,
plus two governance acts. This is a finish, not a re-architecture.

The decision itself is yours (the §5.12 sign-off). This is the informed recommendation you asked the
capstone to produce.

---

## Why not now — and why "go now" is the wrong call

The air-gap is, today, the control actually doing the outbound-protection work. The controls *designed to
replace it* — the egress guard, the kill-switch, the exfil-screen, the outbound PII/secret screen — are
all **BUILT but DORMANT**: they have never run against real external traffic, and the exfil-screen is not
even connected to the live guard (its screener is never registered, so even if traffic flowed, nothing
would inspect it). Two governance steps are also still open: this deep-dive's sign-off, and a data-
retention decision.

**The rejected alternative — "go now":** one could argue the heavy hardening is done, the removal is
egress-only (no inbound listener is added), and deny-by-default is active. That argument fails on one
point: removing the air-gap *now* would trade a **proven** control (no network, enforced by absence + an
import-scan + an armed socket guard) for **unproven** ones (an egress stack that has only ever seen
loopback, and a payload screen that isn't wired in). You would be relying, on day one online, on controls
that have been *compiled, not proven*. That is the exact "safe in the mock, unsafe in production" trap the
project has already been bitten by once. The honest line: **the hardening is real; the specific controls
that make "online" safe have not yet been exercised.**

---

## The strong base — what is already done, by construction (not by environment)

This is not a weak posture. Of ~55 audit findings + 12 headline attack paths, **24 are fixed by
construction** and both of the audit's Critical issues are closed:

- **The forgeable-authorization Critical is closed** — the signing key was rotated off-disk onto the
  non-exportable TPM (TPM = Trusted Platform Module, a tamper-resistant chip); there is no on-disk key to
  steal (commit `23b2802`).
- **Your data is encrypted at rest** — conversation history and the assistant's memory are both AES-256-GCM
  encrypted under a TPM-sealed key, with a tested offline recovery path. A stolen disk yields ciphertext.
- **The trust root is real and wired** — four TPM-sealed keys (token-signing, data-key-sealing,
  audit-signing, manifest-signing); the model's integrity is verified against a TPM-signed manifest at
  boot, fail-closed.
- **The authorization choke-point holds** — every action runs through the Policy Agent; its deny machinery
  is genuinely fail-closed and verified; mutual-TLS is now active in the production posture.
- **The injection action-lock is ON** (it shipped OFF at the audit), the output leakage detector is wired
  in, the tamper-evident audit log is live, and client-facing errors are sanitized.

The remaining gap is narrow and specific: **the egress-era controls, plus a few governance acts.**

---

## What to do first — the prioritized finish-list

### Tier A — gate-blocking: finish before allowlisting the first external endpoint
*(This is the real "go" moment — the first time an outside address is reachable.)*

1. **Wire and verify the exfil-screen onto the armed egress guard (#634).** It is built and unit-tested but
   never registered (`register_screener` has no runtime caller), so nothing screens outbound payloads
   today. This is the single sharpest gap — a flagship egress control that is structurally disconnected.
2. **Turn on outbound PII/secret screening at the egress boundary.** It ships off by decision (a local
   assistant shows you your own data); it must be on *and verified* before anything leaves the machine.
3. **Exercise the entire egress stack against real (sandboxed) external traffic.** The guard, kill-switch,
   allowlist, and exfil-screen have only ever seen loopback. In the dev-mode sandbox (throwaway data + keys
   per the ratified Decision 8 — never the real memory), allowlist one test endpoint and prove:
   deny-by-default holds for everything else, the kill-switch auto-trips on an off-allowlist attempt, and
   the exfil-screen blocks a planted secret. *"Air-gapped because a control proves it"* must become
   *"egress-safe because the controls proved it."*

### Tier B — governance + hardening: before the §5.12 sign-off

4. **Complete this #612 deep-dive and the explicit §5.12 sign-off.** These are governance acts, not builds —
   the sign-off is your informed go/no-go, and #598 explicitly gates on it.
5. **Decide audit-log + memory retention (#607).** Both grow unbounded today; the retention/rotation policy
   is an open decision (and a data-governance item for the AIGP portfolio).
6. **Harden the guest-profile file.** It still literally carries `dev_mode=true`; the runtime interlock
   neutralizes the dangerous path, but the file-level fix the audit asked for is owed — a reviewer will
   flag a committed `dev_mode=true`.
7. **Tighten token containment.** The capability-token lifetime is 30s vs the 5s spec (the one control that
   fails *open*, not safe), and revocation/single-use are not wired — so a leaked token is bounded only by
   its lifetime. Tighten before a multi-process online world.

### Tier C — immediate post-online roadmap (not gate-blocking by design)

8. **Live-memory hardening (#611).** Decrypted data and the key live in RAM at runtime; this only becomes
   *remotely* reachable once online, so by design it graduates from acknowledged to actively-mitigated
   (Intel Key Locker; minimized key residency) on day one online — not a pre-gate blocker.
9. **A full dependency lockfile + hash-pinning.** Upper bounds are in place; a lockfile + hash-verify closes
   the supply-chain vector.
10. **Draft-model manifest signing; the low-severity doc/logging residuals.**

---

## The bottom line

BlarAI is **a short, mostly-wiring finish-list away** from a safe air-gap removal — not a rebuild. The
heavy lifting (encryption, the hardware trust root, mutual-TLS, the authorization choke-point, the
tamper-evident audit, the closed Criticals) is done and verified. The one thing standing between here and
"go" is that the controls meant to replace the air-gap have been **built but never exercised** — so the
move is to **wire them (Tier A.1–2), prove them (Tier A.3), complete the governance gate (Tier B), and then
remove the air-gap with controls that have actually run.** Do Tier A and Tier B first; bring Tier C onto
the day-one-online roadmap.

*Take the air-gap down when "no network" is no longer the only thing keeping you safe — when the controls
that take its place have been proven, not just compiled.*
