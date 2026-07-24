# ADR-041 — Host-Mode Action-Authorization Boundary: Deterministic Plane Live, Agentic-JWT Vestigial (Slated for Removal)

**Status:** Accepted (LA decision 2026-07-15). Documentation + security-posture-framing correction; **no runtime change.**
**Date:** 2026-07-15
**Deciders:** LA (posture framing); technical analysis via the 2026-07 whole-system design review (`docs/design/july.15.2026/`, GP-1 / internal security audit C1)
**Related:** USE-CASE-001 (`Use Cases_FINAL.md`, now amended — the ADR-041 amendment block) · ADR-018 (TPM trust root) · ADR-023 (provenance trust model) · ADR-025 (at-rest encryption) · ADR-026 (per-boot mTLS) · ADR-011 (all LLM inference on the host GPU — the constraint that forecloses the multi-VM topology) · #910 (removal of the vestigial JWT AAB machinery) · #615 (the guest↔host *parser* boundary — CPU-only, unrelated to the JWT AAB)

## Context

USE-CASE-001 specifies an **Agentic-JWT "Action Authorization Boundary" (AAB)**: every approved action carries an unforgeable, single-use, nonce-bound JWT minted by the Policy Agent after a dual (deterministic + probabilistic) gate; every destination microservice hard-rejects any request lacking a valid receipt. It is presented as the system's live root of trust.

The 2026-07 design review (finding GP-1) found this mechanism **built, tested, and instantiated as a Policy-Agent vsock service — but not driven in the shipped host-mode default**: no live code sends a Canonical Action Representation to the Policy Agent over vsock, no JWT is minted for a real request, no destination validates a receipt, and the probabilistic GPU classifier scores no live action. This is the project's own named "built-but-wired-into-nothing" seam class, sitting in its most load-bearing document.

It is **not an open hole** — the real live enforcement (below) is sound and fail-closed — but the vision presented an un-driven mechanism as the live root of trust, which is misleading for a system whose documented journey is portfolio-grade (design-review finding GX-2, doc/reality drift).

## Decision

1. **Record, formally, the live host-mode action-authorization boundary as it actually ships:** per-boot ephemeral **mTLS** (ADR-026) + a **fixed tool allowlist** + the **in-process `DeterministicPolicyChecker`** (fail-closed, authoritative, single source of truth, no GPU/vsock) + **PGOV** (leakage detection, datamarking, untrusted-content action-lock, ADR-023) + the **structural egress spine** (`egress_guard` deny-by-default + latched kill-switch, the one `guarded_fetch` door, the Windows-Hello turn envelope) + **at-rest encryption** (ADR-025) + **weight-integrity verification at model load** (ADR-018 posture).
2. **The Agentic-JWT / dual-gate cryptographic-receipt AAB is built, tested, regression-locked — and VESTIGIAL.** It was designed as the cross-VM authorization boundary for the original per-agent-VM topology (every LLM agent in its own Hyper-V VM, with mTLS + JWT receipts between them). **That topology is foreclosed on this hardware:** LLM inference runs only on the host-resident Arc 140V iGPU (ADR-011), and a Hyper-V guest VM cannot reach that GPU, so the LLM agents can never run in separate VMs and the cross-agent-VM receipt boundary can never become live. It is **slated for removal as dead code (LA decision 2026-07-15; tracked #910)**, not reserved, and is not the live host-mode root of trust.
3. **USE-CASE-001 is amended** (the ADR-041 amendment block) to match. The **code docstrings** that over-describe the JWT AAB as live are a **companion cleanup, ticketed separately** (it touches code and must run the standing test gate — out of scope for this docs-only decision).

## Alternatives considered

- **Option A — wire the full receipt path into host-mode now** (mint a JWT per action, validate at a destination shim). **Rejected:** in the single-process host-mode topology the issuer (Policy Agent) and the destination run in one address space, so a cryptographic receipt crosses no trust boundary — it adds latency and ceremony without adding a real check. The deterministic plane + the structural egress guard already provide fail-closed enforcement proportionate to the fixed tool surface. The receipt earns its keep only across a real cross-VM boundary between LLM agents — and there is no future topology that provides one (the LLM runs only on the host GPU, unreachable from a Hyper-V guest), so the mechanism is **vestigial, not reserved**, and is slated for removal (#910).
- **Option B — record the deterministic-plane boundary as the host-mode reality, mark the JWT AAB as vestigial (its per-agent-VM topology is foreclosed) and slate it for removal, and amend the vision to match. (CHOSEN.)**

## Consequences

- **No runtime change** — the controls are byte-identical. This is a documentation + decision-record correction.
- The vision now **honestly describes what protects the operator**, closing the GP-1 / GX-2 divergence.
- The JWT AAB machinery is **vestigial** — its per-agent-VM topology is foreclosed (the LLM runs only on the host GPU, unreachable from a Hyper-V guest) — and is **slated for removal as dead code (#910)**; until removed it remains inert, with no live caller. (Only the *deterministic* controls above are load-bearing.)
- Records the design principle the whole review converged on: **the model is untrusted; action-authorization trust lives in the deterministic, non-model plane; the probabilistic layer may only tighten a deterministic ALLOW, never loosen a DENY.**

## Evidence

`docs/design/july.15.2026/` (GP-1 + the internal security audit's C1) · `Use Cases_FINAL.md` USE-CASE-001 (amended) · shipped controls: `services/policy_agent/src/gpu_inference.py` (`DeterministicPolicyChecker`), `services/assistant_orchestrator/src/entrypoint.py` (`_adjudicate_tool_dispatch`, PGOV), `services/ui_gateway/src/{url_adjudicator,transport}.py`, `shared/security/{dek_envelope,egress_guard,guarded_fetch}.py`.
