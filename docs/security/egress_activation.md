# Egress Activation — what turns the ADR-027 machinery on, and how to add an allowlist entry

**Status (2026-06-07, Sprint 17):** the egress machinery is **BUILT and DORMANT**. It changes
**no** external-egress behavior today. The active allowlist is **loopback + AF_HYPERV only**; the
external allowlist is **empty**; the kill-switch is **default-off**; and **no outbound-payload
screener is registered** in runtime code. The air-gap stays welded.

This document is the operator/builder reference for the question *"what activates this, and how do
I add a vetted endpoint when the time comes?"* It is the companion to **ADR-027** (the policy) and
`shared/security/egress_guard.py` (the mechanism). Read ADR-027 first — it is the rulebook; this is
the runbook.

---

## 1. What is built (the dormant machinery)

`shared/security/egress_guard.py` carries four things on top of the ADR-020 fail-closed baseline:

| Piece | ADR-027 | Public API | Dormant state this sprint |
|---|---|---|---|
| **Allowlist-widening mechanism** | §1 (rule 1) | `allow_external_endpoint(host, port="*")`, `revoke_external_endpoint(...)`, `external_allowlist()` | list is **empty** — no caller widens it |
| **Anomaly auto-trip kill-switch** | §3 (rule 3) | `trip(reason)`, `rearm()`, `is_tripped()`, `trip_reason()` | **default-off** (not tripped); auto-trips on an anomaly but nothing reaches one in the air-gapped posture |
| **Outbound-payload screening seam** | rule 4 (the trip it fires) | `register_screener(screener)`, `register_arm_hook(hook)` | **no screener registered** — the H-b exfil-screen module is the screener; it registers here when it ships |
| **Live-at-boot wiring** | — | `launcher.__main__._arm_egress_guard()` | runs on **every** production boot; arms the baseline guard + runs arm-hooks |

The baseline (ADR-020) is unchanged and always-on once armed: only loopback (`127.0.0.0/8`, `::1`)
and `AF_HYPERV` (the Hyper-V vsock to the guest VM) may open a socket; every other outbound
socket, bind, `sendto`, and external DNS resolution is refused.

### Why dormant-but-wired

The *enforcement* of external-egress rules only matters once a web feature adds an external
endpoint (post-#556). But the **arm/registration wiring runs on every boot** — so it is exercised
and tested now, and the #598 air-gap GO/NO-GO is a scripted audit rather than a from-scratch build.
This is the same staged pattern as manifest signing (built default-off, flipped at a ceremony).

---

## 2. The three independent activation gates (ADR-027 §"Activation")

The machinery enforces external egress **only** when **all three** hold. Each is a separate gate;
a single one does not open the door:

1. **#598 air-gap GO/NO-GO passes** — the production-posture gate (Sprint 18 + the LA sign-off).
2. **The Sprint-17 egress machinery is complete** — this stream (H-a) + H-b (the exfil-screen
   module + the PA `DENY_EXTERNAL_NETWORK` carve-out). Built this sprint, dormant.
3. **The first web feature ships under #556** — W4 Kagi search is first. Only then does an external
   endpoint get added to the allowlist.

Until all three hold, the allowlist stays loopback + vsock only.

---

## 3. How to add an allowlist entry (when a web feature ships)

> **Do NOT do this in Sprint 17.** The live list stays empty this sprint. This is the procedure
> for the future moment a vetted feature ships post-#556. Each addition is a **governance act**
> (an ADR-027 §1 "one vetted endpoint at a time" decision), recorded with a journal entry + the
> owning feature ticket.

ADR-027 §1 is deny-by-default: nothing reaches the internet unless it is on the explicit allowlist,
added **one vetted endpoint at a time**, each behind the controls below.

### 3.1 The call

```python
from shared.security import egress_guard

# One vetted endpoint. host is a numeric IP or a DNS name; port is the TCP port,
# or "*" for any port on that host.
egress_guard.allow_external_endpoint("kagi.com", 443)
```

Constraints (the mechanism enforces these):
- **External only.** A loopback host (`127.0.0.1`, `localhost`) is rejected with `ValueError` —
  loopback is already permitted; the widener is for *external* endpoints.
- **Exact match.** `allow_external_endpoint("kagi.com", 443)` permits exactly `kagi.com:443`. A
  different host or port stays denied (and auto-trips). Use the `"*"` port wildcard only when a
  feature genuinely needs any port on a host (rare).
- **One at a time.** Add the single endpoint a feature needs as that feature ships — never a range
  or a category. ADR-027 §1 rejected the broad "any HTTPS, screened" posture.

### 3.2 The controls that still apply to a widened endpoint

Adding an endpoint does **not** open an unguarded pipe. All ADR-027 layers still apply:
- **PA adjudication (rule 2 — H-b's carve-out):** the Policy Agent auto-approves the call *within
  the allowlist* and logs every call; off-list calls are hard-denied.
- **Exfil screening (rule 4 — H-b's screener):** every outbound payload is screened for
  secrets/PII before it leaves, even to an allowlisted endpoint; a detection **blocks** the call
  and trips the kill-switch.
- **Kill-switch (rule 3):** any anomaly cuts ALL egress; re-arm is LA-only.

### 3.3 Removing an endpoint

```python
egress_guard.revoke_external_endpoint("kagi.com", 443)   # the door re-closes
```

---

## 4. The kill-switch (ADR-027 §3)

### 4.1 What trips it (automatically)

The guard **auto-trips** — cuts ALL egress (loopback and vsock included) and alerts the operator —
on a detected anomaly:
- a `connect`/`bind`/`sendto`/`getaddrinfo` to an **off-allowlist address**, or
- a registered screener's **positive detection** of a secret/PII in an outbound payload, or
- an **internal failure** of the screening/wiring path (a screener or arm-hook that raises — fails
  closed rather than leaving an un-screened path open).

### 4.2 The latch + re-arm (LA-only)

A trip is **latched**: once tripped, *every* egress operation raises `EgressTripped` (a subclass of
`EgressDenied`/`OSError`, so existing fail-closed `except OSError` paths degrade gracefully). There
is **no automatic recovery** — the safe state on an anomaly is "nothing leaves."

Only the Lead Architect clears it:

```python
from shared.security import egress_guard
egress_guard.rearm()   # releases the latch; normal allowlist enforcement resumes
```

`rearm()` does **not** widen the allowlist or clear screeners — it only releases the latch. It is a
deliberate operator action, never on any automatic path. The LA also holds a master off-switch at
all times: `egress_guard.trip("operator master-off")`.

### 4.3 Operator alerts

A trip emits a `CRITICAL` log (`shared.security.egress_guard`), which the launcher writes to the log
file the operator reads and surfaces on-screen. When the network-facing UI lands post-#556,
`_alert_operator()` is the seam an operator-facing notification hooks onto.

---

## 5. The screener seam (how H-b's exfil-screen module wires in)

The exfil screen (stream H-b — `shared/security/exfil_screen` + the PA carve-out + the PGOV PII
path) is the *screener*; `egress_guard` is the *enforcement point*. They are connected by a
**registration pattern** so there is **no circular import**: the screen module imports
`egress_guard`; `egress_guard` never imports the screen module.

### 5.1 The interface anchor (exact signatures — H-a ships these; H-b integrates against them)

```python
def trip(reason: str) -> None: ...
def register_screener(screener: OutboundScreener) -> None: ...

# where:
OutboundScreener = Callable[[bytes], ScreenResult | bool | None]

@dataclass(frozen=True)
class ScreenResult:
    detected: bool
    reason: str = "exfil screener positive detection"
```

A screener receives the outbound bytes and returns:
- a `ScreenResult(detected=True, reason=...)` (or a bare `True`) to **block** (fires `trip`), or
- `None`/`False` (or `ScreenResult(detected=False)`) to pass.

The `reason` must name only the *kind* of anomaly — **never** the matched secret itself.

### 5.2 The arm-hook (run screener-registration at arm() time)

The launcher arms the guard at boot. H-b's module registers its screener at arm() time via an
arm-hook, so screening is live from the first armed socket:

```python
# in shared/security/exfil_screen.py (H-b — illustrative, not built by H-a):
from shared.security import egress_guard

def _wire() -> None:
    egress_guard.register_screener(_screen_outbound_payload)

egress_guard.register_arm_hook(_wire)   # runs when the launcher calls arm()
```

`launcher.__main__._arm_egress_guard()` imports `shared.security.exfil_screen` (if present) so its
arm-hook is registered, then calls `egress_guard.arm()`, which runs every hook. If the module is
absent on a checkout, the baseline guard still arms (fail toward the more restrictive posture); if a
hook raises, the kill-switch trips (an un-screened path is an open door).

---

## 6. Quick reference — the full public API

| Function | Purpose |
|---|---|
| `arm()` / `disarm()` / `is_armed()` | install / remove / query the process-wide guard (ADR-020) |
| `allow_external_endpoint(host, port="*")` | widen the allowlist by one vetted external endpoint (ADR-027 §1) |
| `revoke_external_endpoint(host, port="*")` | remove a widened endpoint |
| `external_allowlist()` | snapshot of the widened external allowlist (empty == dormant) |
| `trip(reason)` | cut ALL egress + alert (ADR-027 §3) — the interface anchor |
| `rearm()` | LA-only: clear a tripped kill-switch |
| `is_tripped()` / `trip_reason()` | query the kill-switch state |
| `register_screener(screener)` | register an outbound-payload screener (ADR-027 rule 4) — the interface anchor |
| `register_arm_hook(hook)` | register setup to run at arm() time (the no-circular-import seam) |

Test locks: `tests/security/test_egress_core.py` (this machinery), `shared/tests/test_egress_guard.py`
(the ADR-020 baseline), `tests/security/test_no_external_egress.py` (the import-scan air-gap proof).

---

**References:** ADR-027 (egress policy); ADR-020 (the egress kill-switch mechanism); ADR-023 (PA
tool-dispatch mediation — rule 2); `docs/security/SECURITY_ROADMAP_air_gap_removal.md` §5.2/§5.3/§5.10;
#598 (air-gap GO/NO-GO), #556 (network capabilities); `shared/security/egress_guard.py`;
`launcher/__main__.py::_arm_egress_guard`.
