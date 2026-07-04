# ADR-020: Code-Enforced Network Egress Kill-Switch (Fail-Closed Allowlist)

**Status:** ACCEPTED — 2026-06-03 (Tier-0 security hardening; LA-approved)
**Author:** Lead Architect (Blair) + Claude Opus 4.8 (1M context)
**Related:** ADR-007 (vsock/mTLS transport this guards), ADR-018 (TPM trust root /
security posture), ADR-019 (de-elevation). Roots in the 2026-06-03 security audit
(`docs/security/audit_2026-06-03/`, privacy-and-network-boundary domain).
BUILD_JOURNAL lesson 22. Tracks Vikunja #557 (Tier 0) under umbrella #555;
internet-facing gate #556/#787.

---

## 1. Context

The security audit's privacy-and-network-boundary domain returned a High:
**there is no code-enforced network block.** BlarAI's "no external network"
guarantee is *environmental* — the machine is air-gapped and the source happens
not to import any HTTP client. The audit confirmed zero
`requests`/`httpx`/`aiohttp`/`urllib` imports in source, and that sockets appear
in exactly two source files (`shared/ipc/vsock.py`, `services/ui_gateway/src/transport.py`).

But "we do not call the network" is an invariant held only by developer
discipline and the *absence* of a network — both of which dissolve the moment
BlarAI goes internet-facing (the stated future, #556) or a dependency or agent
tool introduces an outbound call. The audit's completeness pass sharpened the
point: the runtime `.venv` ships full network stacks (`requests`, `httpx`,
`aiohttp`, `huggingface_hub`, `transformers`, `urllib3`, …) — the guarantee rests
entirely on source not *calling* a capability that is fully loaded in the
process. The air-gap is the only wall, and the LA's hard gate (#787) is that the
walls behind it must be built before the air-gap comes off.

## 2. Decision

Add a **process-wide, fail-closed egress guard** (`shared/security/egress_guard.py`)
that makes the no-external-network invariant code-enforced. It is an
**allowlist**, not a blanket block:

- **Permit** `AF_HYPERV` (host↔guest vsock — cannot route off-box) and
  `AF_INET`/`AF_INET6` **to loopback only** (`127.0.0.0/8`, `::1`, `localhost`).
- **Deny** every other socket family at construction, every non-loopback
  `connect`/`bind`/`sendto`/`sendmsg`, and external-hostname DNS resolution.
- **Fail-closed:** an unparseable or ambiguous address is denied. `EgressDenied`
  subclasses `OSError` so the runtime's existing fail-closed `except OSError`
  paths (the vsock transport, `socket.create_connection`) degrade to a refused
  connection rather than an uncaught crash.

### 2.1 Why an allowlist, not "refuse all outbound sockets"

The runtime's legitimate IPC *is* sockets: the production AF_HYPERV vsock to the
VM, the dev-mode loopback TCP substitute, and the launcher's `127.0.0.1:5001`
gateway path. A blanket socket block would brick launch — and on a GPU-bound,
elevated boot, no headless test would catch it; only the live screen would. So
the guard enumerates the legitimate-allow set, and its test proves **both** that
external egress is denied **and** that the local channels still pass. The named
pipe `\\.\pipe\BlarAI` is a Win32 kernel object, not a socket — outside the
guard's scope by construction; the guard's entire blast radius is two
socket-module symbols (`socket.socket`, `socket.getaddrinfo`), asserted by
`test_guard_scope_is_sockets_only`.

### 2.2 Enforcement layers (defence in depth)

1. **`socket.socket` construction** — deny families outside the allowlist.
2. **`connect` / `connect_ex` / `bind` / `sendto` / `sendmsg`** — deny any
   non-loopback address for `AF_INET`/`AF_INET6`; `AF_HYPERV` permitted.
3. **`socket.getaddrinfo`** — deny resolution of an external *hostname* (a DNS
   query is itself egress, and an exfiltration vector). Numeric literals and the
   loopback names are allowed; an external numeric IP is permitted to *resolve*
   but is still refused at `connect` time by layer 2.

### 2.3 Why the mechanism is monkeypatching `socket.socket`

Both source socket sites create the raw socket, then `connect`/`bind` on it,
**then** mTLS-wrap it (`vsock.py:217–227` client + wrap at `239`; listener binds
at `432`/`439`, wraps at `accept()`). So a guard on the raw socket's
`connect`/`bind` fires on the real egress vector *before* the TLS layer — patching
`socket.socket` with a guarded subclass covers the actual code paths, and
`create_connection` / `socketpair` (the self-pipe asyncio uses on Windows) keep
working because they route through the same patched, loopback-permitted surface.

### 2.4 Where it is armed

At the launcher's **real process entry** — the `if __name__ == "__main__":`
block of `launcher/__main__.py`, before `main()`. Deliberately **not** at module
top-level nor inside `main()`: `launcher/tests/test_launcher.py` imports the
module and calls `main()` directly with mocked dependencies, so arming in either
place would leak the process-wide patch into the test suite and break unrelated
tests. The `__main__` block runs only in the genuine `python -m launcher`
process. Today BlarAI runs **host-single-process** (the audit's "host forces
dev_mode / single-process"), so arming the launcher covers the entire runtime.

### 2.5 Scope deferred to Tier 2 (named, not silent)

When the security-critical services move into the VM guest as separate processes
(Tier-2 isolation, #559), each guest process must arm the guard at its own entry.
For Tier 0 — host single-process — arming the launcher is complete and
sufficient. The guest-process arming is a **tracked Tier-2 follow-up**, not a
silent gap.

## 3. Consequences

**Positive.** The no-external-network invariant is now enforced by code,
fail-closed, with a 16-assertion regression test. A future accidental or
dependency-introduced outbound call is *refused at runtime*, not merely
"unlikely." This is the floor the internet-facing future is built on: the egress
classifier / PGOV output validator will sit **above** this guard, not replace it.
It integrates cleanly with existing fail-closed handling (the `OSError` subclass).

**Limits (on the record).** The guard is a **Python-interpreter-level control**:
it governs this process's `socket` calls. It is a strong floor against accidental
and dependency-introduced egress — not a sandbox against a determined in-process
adversary that re-imports `_socket` directly or issues raw OS syscalls. That
threat is the VM-isolation layer's job (Tier 2), and a complementary
OS-level outbound firewall rule (deny-all-except-Hyper-V) is recommended
defence-in-depth (Tier-3 candidate). Stated plainly so the boundary is not
mistaken for more than it is.

**Follow-up.** Tier 3 adds a suite-level automated egress test (the brief's
"egress test"); this ADR's test proves the *mechanism*, Tier 3 proves the
*property* end-to-end across the running system.

## 4. Verification

- **Headless (done):** `shared/tests/test_egress_guard.py` — 16 tests. External
  IPv4/hostname connect denied; wildcard/external bind denied; disallowed family
  denied; external DNS denied; `create_connection` + UDP `sendto` external
  denied; **loopback TCP round-trip, `socketpair`, AF_HYPERV construction, and
  loopback DNS all pass**; arm idempotent; disarm restores; denial is `OSError`;
  blast radius is exactly two symbols. Full sweep green (no regression).
- **Live (LA, Tier-0 checkpoint):** boot the real `python -m launcher`, confirm
  the runtime comes up with the guard armed (launcher log shows "Egress guard
  ARMED"), the TUI works, a prompt round-trips, and attach/voice/vision still
  function — i.e. the allowlist did not starve any legitimate local channel.
