# Egress Machinery — Activation & Allowlist Guide (ADR-027, STAGED/DORMANT)

**Scope:** the Tier-3 network-egress machinery built in Sprint 17 (Vikunja #628,
criterion C3) to ADR-027. **Status: STAGED / DORMANT.** None of this enforces
anything today — the air-gap stays welded. It activates only when the first web
feature ships under #556, *after* the #598 air-gap GO/NO-GO gate.

This document is the C3 deliverable for stream **H-b** (the PA `DENY_EXTERNAL_NETWORK`
carve-out + the outbound exfil screen). The complementary mechanism — the
`egress_guard` raw-socket allowlist, the `register_screener`/`trip` interface, and
the anomaly auto-trip — is owned by stream **H-a**; this guide cross-references it
where the two meet but does not restate it. See ADR-020 (the kill-switch
mechanism) and ADR-027 (the policy these implement).

---

## 1. What this machinery is (four independent layers, ADR-027)

Once any web feature is enabled, four independent layers govern every outbound
network call. A single failure does not open the door:

1. **Allowlist — deny-by-default** (ADR-027 §1). Nothing reaches the internet
   unless its endpoint is on an explicit allowlist (Kagi first, grown one vetted
   endpoint at a time). *Owned by stream H-a.*
2. **PA approval — auto-approve within the allowlist, log every call**
   (ADR-027 §2). The Policy Agent's deterministic `DENY_EXTERNAL_NETWORK` rule
   gains a carve-out: an allowlisted, PA-adjudicated egress URL is auto-approved
   (no per-call user confirmation) and logged; everything off-list is hard-denied.
   **← this document, §3.**
3. **Kill-switch — default-off, auto-trip on anomaly, LA-only re-arm**
   (ADR-027 §3). *Mechanism owned by stream H-a (`egress_guard`); the exfil screen
   fires the trip — §4 below.*
4. **Exfiltration screening — screen every outbound payload, block on detection**
   (ADR-027 §4). Before any payload leaves — even to an allowlisted endpoint — it
   is screened for secrets and PII; on detection the call is **blocked**
   (fail-closed) and the kill-switch trips. **← this document, §4.**

---

## 2. Why it is dormant right now

The machinery is BUILT but enforces nothing this sprint, exactly like the
manifest-signing mechanism staged in Sprint 16:

- The PA egress allowlist (`DeterministicPolicyChecker._EGRESS_ALLOWLIST`) ships as
  the **EMPTY set**. With an empty allowlist the carve-out never fires — every
  external URL still hits `DENY_EXTERNAL_NETWORK`. The air-gap is welded.
- The raw-socket `egress_guard` allowlist remains **loopback + vsock only**
  (ADR-020 / stream H-a). No external endpoint is reachable at the socket layer.
- The exfil screen (`shared/security/exfil_screen.py`) is importable and fully
  unit-tested, but **nothing calls it in production** until a web feature wires it
  via `egress_guard.register_screener`.

The regression lock `tests/security/test_egress_screen.py::TestPaEgressCarveOutDormant`
fails loudly if the class-default allowlist is ever populated without the gate +
a web feature — the staged-dormant guarantee is enforced in CI.

---

## 3. The PA `DENY_EXTERNAL_NETWORK` carve-out (ADR-027 §2)

**Where it lives:** `services/policy_agent/src/gpu_inference.py`, in
`DeterministicPolicyChecker.check()` — RULE 3. This is the **single source of
truth** for the air-gap deny: the same rule is enforced both at the PA boundary
and at the AO tool loop (`services/assistant_orchestrator/src/entrypoint.py`,
`_adjudicate_tool_dispatch`). The carve-out therefore covers both call sites with
one change.

**Behaviour:**

| Resource | `_EGRESS_ALLOWLIST` (live) | With a populated allowlist |
|---|---|---|
| `https://kagi.com/search` | `DENY_EXTERNAL_NETWORK` (dormant) | **auto-approved** (`None` = allow) + logged |
| `https://off-list.example/x` | `DENY_EXTERNAL_NETWORK` | `DENY_EXTERNAL_NETWORK` (off-list) |
| `ftp://kagi.com/x`, `ws://…`, `gopher://…` | `DENY_EXTERNAL_NETWORK` | `DENY_EXTERNAL_NETWORK` (web-only carve-out) |
| `https://evil.kagi.com.attacker/x` | `DENY_EXTERNAL_NETWORK` | `DENY_EXTERNAL_NETWORK` (no wildcard) |

Design points (all locked by tests):

- **Host-scoped, exact match.** The allowlist holds lowercase hosts (no scheme,
  no port). A subdomain of an allowlisted host is **not** implicitly allowlisted
  — fail-closed, no wildcards.
- **Web schemes only.** Only `http`/`https` are eligible for auto-approval. The
  other schemes RULE 3 blocks — `ftp`/`ftps` (file exfil), `ws`/`wss` (C2),
  `gopher` (SSRF smuggling) — are **never** auto-approved, even to an allowlisted
  host. The allowlist names web endpoints a feature needs, not arbitrary
  protocols.
- **No per-call user confirmation** (ADR-027 §2). The guarantee comes from the
  tight allowlist + the exfil screen + the kill-switch, not user friction.
- **Every auto-approved call is logged** (`logger.info`, "auto-APPROVED" line) —
  the audit trail ADR-027 §2 requires.

### 3.1 How to add an allowlist entry (when a web feature ships)

> Do this only **after** #598 passes **and** the feature that needs the endpoint
> is being enabled. Adding an entry while the air-gap is meant to be up defeats
> the dormancy guarantee (and breaks the dormant-posture lock in CI).

The carve-out reads its hosts from `DeterministicPolicyChecker._EGRESS_ALLOWLIST`.
The **live** allowlist source — how that set is populated at boot from the
ADR-020 `egress_guard` allowlist that stream H-a owns — is defined by H-a's
allowlist-widening mechanism (see H-a's egress-core doc / `egress_guard`). The PA
carve-out is the *consumer*; H-a's mechanism is the *source*. To add an endpoint:

1. Vet the endpoint (it must be the minimum the feature requires; Kagi is the
   first and the model).
2. Add the **host** (e.g. `kagi.com`) to the egress allowlist via H-a's
   allowlist-widening mechanism — that is the one place an endpoint is named, so
   the socket-layer guard (`egress_guard`) and the PA carve-out stay in lockstep.
3. Confirm the feature wires the exfil screen (§4) on its send path.
4. The kill-switch (`egress_guard`, default-off) is armed for that feature per
   ADR-027 §3 (LA-only).

`check()` also accepts a keyword-only `egress_allowlist=` override; it exists so
tests can exercise the auto-approve path with a TEST host without touching the
live (empty) default. **Production passes no override** — it uses the empty class
default, i.e. stays denied.

---

## 4. The outbound exfil screen (ADR-027 §4)

**Where it lives:** `shared/security/exfil_screen.py`. Self-contained, stdlib +
the in-tree PGOV recognizers, no new dependencies, no import side effects.

**Contract:**

```python
from shared.security.exfil_screen import screen, screen_and_enforce

detection = screen(payload)          # Detection(blocked, labels, spans, reason)
if detection.blocked:
    ...                              # refuse the egress (fail-closed)

# or, the block→trip handshake in one call:
detection = screen_and_enforce(payload)   # fires egress_guard.trip() on a block
```

- `screen(payload)` runs two recognizer layers and returns a `Detection`:
  - the **reused PGOV PII path** (`services.assistant_orchestrator.src.pgov.find_pii_spans`
    — the single source of truth: SSN, credit-card [Luhn-gated], email, phone,
    IPv4, AWS key, long hex secret, passport, bearer token); and
  - a thin **secret-credential layer** for high-value formats PGOV does not
    target (PEM private keys, JWTs, GitHub/Slack/Google tokens, generic
    `key=value` secret assignments).
- **Block, not redact** (ADR-027 §4, sharpening SECURITY_ROADMAP §6 Decision-5):
  any hit blocks the whole call. Redact-and-proceed trusts the redactor to catch
  everything; one miss is an unrecoverable leak.
- **Fail-closed:** an undecodable payload or any recognizer error yields
  `blocked=True` — a payload that cannot be proven clean is treated as a leak.
- **No raw values escape:** `Detection` carries labels + offsets only, never the
  matched secret — an alert/audit record must not itself become the leak.

### 4.1 Wiring it into the egress path (when a web feature ships)

The screen plugs into stream H-a's `egress_guard` via its public interface only
(H-b never edits `egress_guard` internals):

1. At the feature's startup, register the screen so the armed egress path invokes
   it on every outbound payload:
   ```python
   from shared.security import egress_guard
   from shared.security import exfil_screen
   egress_guard.register_screener(exfil_screen.screen)
   ```
2. On a blocked detection, the kill-switch trips — cutting ALL egress until the
   LA re-arms (ADR-027 §3). `exfil_screen.screen_and_enforce()` performs that
   block→`egress_guard.trip(reason)` handshake; the seam is locked by
   `tests/security/test_egress_screen.py::TestExfilScreenSeamToEgressGuard`.

---

## 5. Activation sequence (ADR-027 "Activation")

Each gate is independent; all must hold before any of this enforces:

1. **#598** air-gap GO/NO-GO passes (production posture verified).
2. **Sprint 17** builds this machinery to ADR-027 (done — STAGED/DORMANT).
3. The first web feature (W4 Kagi search) ships under **#556**: its endpoint is
   added to the allowlist (§3.1), the exfil screen is wired (§4.1), and the
   kill-switch is armed for it (ADR-027 §3).

Until all three hold, the allowlist stays loopback + vsock only and every
external URL is denied — the air-gap is up.

---

## 6. Tests (the C3 mechanism + seam locks, H-b share)

`tests/security/test_egress_screen.py`:

- `TestExfilScreenBlocksOnDetection` — the screen blocks on secret/PII payloads
  (fail-closed), passes clean payloads, blocks undecodable bytes, never fails
  open on a recognizer error, and exposes offsets-not-values.
- `TestPaEgressCarveOut` — allowlisted egress auto-approved + logged; off-list,
  subdomain, and non-web-scheme egress hard-denied.
- `TestPaEgressCarveOutDormant` — the live (empty) default denies every external
  URL; the staged-dormant guarantee.
- `TestExfilScreenSeamToEgressGuard` — a simulated detection fires
  `egress_guard.trip()` over H-a's real wiring (skips cleanly until H-a's
  interface merges; runs-and-passes at the H-b merge-gate).

**Refs:** ADR-020, ADR-027; `docs/security/SECURITY_ROADMAP_air_gap_removal.md`
§5/§6; `docs/runbooks/kagi_key_provisioning.md` (the W-series web-search work);
#598, #556, #628.
