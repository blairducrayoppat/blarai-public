# A.3 — Controlled Sandboxed Egress Exercise — Formal Run Record (2026-06-10)

**Result: 11/11 PASSED.** The #598-gate "controlled sandboxed egress exercise" (Tier-A A.3) was run deliberately, in isolation, as the formal gate-evidence run.

```
pytest tests/security/test_egress_sandbox_proving.py -v
... 11 passed in 4.16s
```

## What was exercised (against real NON-LOOPBACK traffic, air-gap-safe)

The harness (`tests/security/test_egress_sandbox_proving.py`, Vikunja **#643**, merged `14d21c3` 2026-06-09) stands up a throwaway TCP endpoint on **the box's own LAN IP** (a non-loopback address that round-trips *same-host* — no router hop, no internet) and exercises the real, armed egress stack end-to-end:

- **Proof 1 — deny-by-default + auto-trip.** A connect to a non-loopback address NOT on the allowlist raises `EgressDenied` and **auto-trips the kill-switch** (`is_tripped()` → True); after the trip, ALL egress is latched-cut, even the allowlisted endpoint (`EgressTripped`).
- **Proof 2 — allowlisted endpoint permitted.** A real same-host connect to the allowlisted endpoint succeeds and does NOT trip; the **destination-scoped screen tag fires by itself** (no forced flag) because the destination is genuinely non-loopback INET.
- **Proof 3 — exfil-screen blocks a planted secret.** A payload carrying a planted fake PEM-private-key header (and, separately, a fake SSN) sent to the allowlisted endpoint **trips the kill-switch**; the trip reason carries the detection LABEL, never the raw secret value; and the secret **never reaches the listener** (block-before-send).
- **Proof 4 — clean payload round-trips.** A benign payload passes the wired screen, is delivered to the listener over the real OS network stack, and does NOT trip.
- Plus a sandbox-mechanism self-check (the discovered address is non-loopback; same-host round-trip works disarmed).

## Air-gap safety (by construction)
The endpoint is the box's own LAN IP, which the OS loops back locally — **no real external connection is ever attempted.** A fully air-gapped box (loopback only) SKIPS gracefully, never fails. Secrets are throwaway fixtures (a fake PEM header label, a fake SSN), never real credentials. Every test resets the guard before+after (`_pristine_guard`); the root conftest redirects `%LOCALAPPDATA%`. **Nothing about BlarAI's runtime posture changed: the production external allowlist stays empty; the air-gap is up.**

## Reconciliation (the finding)
The #612 deep-dive's residual register (`deep_dive_log.md`, A.3) graded this **"BUILT-DORMANT — GATE-BLOCKING — the one remaining proof."** On disk it is **built AND passing** in the standing gate. The "the one remaining proof" grade is **currency drift** — the component-level exercise is done. (Folds into the #654 doc-sync.)

## The genuine residual (what this exercise does NOT cover)
This proves the **egress guard + exfil screen** behave correctly on real traffic, exercised **directly**. It does NOT exercise the **full AO-tool-driven chain** (Flow 3 hops 4-7: an AO tool requests egress → PA mediation → guard → exfil screen) end-to-end, because **no egress tool exists yet** (the four shipped AO tools never egress; web-search/Kagi W4 is not wired to the live AO). That integrated run is **not exercisable until the first egress tool ships** — and the first egress tool *is* the deliberate going-online act. Requiring it pre-gate is circular.

## Gate-scope question (for the LA)
Is A.3's gate bar **(rec)** the component-level proof — guard + screen proven on real traffic (DONE here) — with the integrated AO-driven chain a **day-one-online** requirement (the first egress tool's bring-up exercises hops 4-7 under observation)? Or must the gate hold for the full AO-driven chain, which cannot run until an egress tool exists? See the response + #598.

**Refs:** #643 (`14d21c3`); `tests/security/test_egress_sandbox_proving.py`; #598; ADR-020/027; `deep_dive_log.md` A.3; #654 (doc-sync).
