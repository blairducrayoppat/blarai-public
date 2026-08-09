# DRAFT — Durable Fix Options for the Cert-Remint Race

> **NOT URGENT — decision-prep, not a proposal to act tonight.** The #863 reuse-window
> holds for every dispatch-harness boot as of `047d5dfc` and needs nothing further to
> keep the battery running. This document is the requested next step: lay out DURABLE
> fix options for the race that reuse-window only mitigates, so the LA can decide,
> whenever convenient, what (if anything) comes after it. Nothing here is built. Nothing
> here is ratified. If Option A or B is ever chosen, it becomes its own ADR-026
> Amendment (the second one — see §5, sequenced after the reuse-window's pending
> Amendment 1).

---

## 1. The race, stated precisely

ADR-026's core invariant is that every production boot mints a fresh CA and fresh leaf
certs (`shared/security/cert_provisioning.py`). That is correct for a single boot, one
operator, one session. It becomes a race the moment something re-boots the launcher
*while a prior instance may still be alive* — which is exactly what the overnight
dispatch/battery harness does, deliberately, before every job (`AoReensurer.ensure()`,
`tools/dispatch_harness/battery.py:257-309`).

This is not a single incident — it is a recurring class, with (at minimum) three data
points on disk:

1. **2026-07-06** (first discovery, pre-dates both tickets below). The
   `ao_mtls_healthy()` docstring (`battery.py:159-184`) records the failure mode by name
   — "found live 2026-07-06" — and describes the exact shape: "The launcher mints a
   FRESH per-boot CA into `certs/` on every boot, and an AO holds its minted certs in
   memory for its whole life. If `certs/` is re-minted UNDER a running [AO]…" The
   mitigation shipped then was **detection**, not prevention: `ao_mtls_healthy` lets
   `AoReensurer._ready()` notice a cert-drifted AO and treat it as not-ready so the
   harness re-mints and reboots to one consistent set — a recovery path, not a guarantee.
2. **#805** (2026-07-11, `92958ab9`). An AUDIT-6 efficiency fix cached the `ui_gateway`
   client's mTLS `SSLContext` instead of rebuilding it every message. The 2026-07-11
   journal fragment (`docs/journal_fragments/2026-07-11_805-mtls-cache-poisoning.md`)
   is explicit that the cache didn't cause the race — it removed an *accidental*
   self-healing (the pre-#805 per-message rebuild happened to retry against
   freshly-settled certs) that had been silently surviving the same underlying window.
   Its own **Next** line already named the diagnosis this document works from: *"the
   cert-remint race underneath is the real fragility."*
3. **#863** (2026-07-12, `047d5dfc`). The race itself, finally biting through
   deterministically: a still-live prior AO's in-memory leaf, signed by a CA the next
   boot has already overwritten on disk, fails the gateway→PA handshake
   (`CERTIFICATE_VERIFY_FAILED` / `certificate signature failure`) — six battery jobs
   STALLED in one night (Vikunja #863, read in full: "night-20260711-230000 FAILED —
   all 6 jobs… STALLED"). The shipped fix (documented in
   `docs/adrs/DRAFT_adr026_amendment_cert_reuse_window.md`, this agent's prior draft) is
   a verify-before-reuse mitigation, not a lifecycle fix.

Under the project's own third-instance discipline (`LESSONS.md` curation rules,
`CLAUDE.md` §Build-Journal-Discipline), a class recurring a third time wants a shipped
structural control on the SAME change, not just another tally — and #863 arguably
already clears that bar (the reuse-window *is* a structural, tested control, not a
one-off patch). What follows is offered as the further, root-cause-oriented step beyond
that minimum, for the LA's prioritization — not as evidence the discipline was missed.

### 1.1 What #863 actually fixed, and what it didn't

This is the load-bearing technical point the rest of this document turns on, and it
sharpens the team lead's framing: the reuse-window does not just "mitigate rather than
remove" the race in a vague sense — it specifically **changes which of two failure
shapes the SAME underlying overlap produces**, and only silences one of them.

- **Pre-#863**: prior AO alive + new boot mints fresh → **cert mismatch**
  (`CERTIFICATE_VERIFY_FAILED`).
- **Post-#863**: prior AO alive + new boot finds the on-disk set untouched and
  cryptographically consistent (because the prior AO never wrote anything — it just sat
  there, still listening) → reuse-if-consistent correctly reuses it, so there is **no
  cert mismatch this time** → but the new launcher still has to bind its own listener to
  the AO's port, and **the prior AO is still holding it**. The failure shape becomes a
  **port collision** (or, if the new instance's own single-instance lock check runs
  first, an instance-lock refusal) instead of a cert error.

Evidence this is not hypothetical: #863's own ticket records that the run's *third*
launcher boot (PID 3128, 23:06:32) ended the night "**LEAKED on :5001 post-run**" — a
launcher process that was still bound to the AO's port when the run gave up. That is
direct, on-disk evidence that "a prior instance outlives the reboot that was meant to
replace it" is a real, observed outcome in this exact codebase, not a theoretical edge
case invented for this document.

**Consequence:** the reuse-window is a complete, sufficient fix for the cert-consistency
question, and it should stay exactly as shipped. It is not, by itself, a complete fix for
the underlying AO-lifecycle-overlap condition — that condition can still stall a job, it
will just do so with a different error message. That is the gap Options A and B below
are two different ways to close.

---

## 2. Option A — Teardown barrier: prove the prior instance is dead before the next mint

**Shape:** before any of the three reboot paths proceeds to mint-or-reuse, positively
confirm the previous holder of the AO's identity (lock + port) is gone — not inferred
from a timeout, not assumed from a lock file being absent, but confirmed by directly
checking the process and the socket.

### 2.1 Where it goes

All three current callers of `boot_launcher_detached()` (`battery.py:206`) —
the battery preflight, `AoReensurer.real()`'s per-job reboot (`battery.py:353`), and the
swap-driver probe's restore step (`tools/dispatch_harness/probe.py:265`) — share **one**
choke point. Consistent with how this codebase already prefers structural guarantees
over per-caller vigilance (the single-instance lock itself is exactly this pattern:
one check, one place, every launcher boot goes through it — `launcher/instance_lock.py`),
Option A's barrier belongs **inside `boot_launcher_detached()` itself**, immediately
before it spawns the replacement process, so all three current callers (and any future
one) are protected automatically rather than depending on each remembering to call a
helper first.

The one call site that most needs this today and currently has *no* equivalent stop-first
step is `AoReensurer.ensure()`'s reboot decision — `battery.py:290-291`
(`self.log(...); self.boot()`). `probe.py`'s restore path is *usually* preceded by an
explicit stop phase for an unrelated reason (freeing GPU headroom before the 30B swap),
so it is accidentally safer today; the battery preflight boots into a normally-empty
`certs/` dir. Putting the barrier inside `boot_launcher_detached()` removes the
dependence on that accident.

### 2.2 How it proves death

Every primitive this needs already exists and is already tested elsewhere in this
codebase — Option A is closer to *composition* than new machinery:

1. **Identify the current holder.** `launcher.instance_lock.lock_path_for_repo(repo_root)`
   + `_read_holder_pid()` (`instance_lock.py:52-54`, `:93-101`) — the same lock file the
   launcher itself already writes at boot.
2. **Confirm it's a live launcher, not a stale or recycled pid.**
   `_is_live_launcher(pid)` (`instance_lock.py:64-81`) — a `psutil` liveness check plus a
   cmdline-marker match (`"-m launcher" in cmdline`), the exact same check the instance
   lock already trusts to decide reclaim-vs-refuse.
3. **If live, tree-kill it.** `shared.procspawn.terminate_process_tree(pid)`
   (`shared/procspawn.py:331-376`) — already does the right thing for a
   **wedged-but-alive** process: `terminate()` on every descendant leaves-first, then the
   root, then a bounded `psutil.wait_procs(timeout=3.0)` grace, then `.kill()` on
   anything still alive (`procspawn.py:362-375`). This is the exact "wedged-but-alive
   AO" failure mode the brief asked about, and it is already handled — a target that is
   hung, deadlocked, or ignoring `SIGTERM` still goes down within the 3-second bound.
   This is directly modeled on (and could literally reuse) `probe.py`'s existing
   `_real_stop_ao()` (`probe.py:212-241`), which already does steps 1-3 for a different
   reason (GPU headroom before a model swap).
4. **Poll for the port to actually go quiet.** `ao_socket_ready(port)`
   (`battery.py:144-156`) polled until it returns `False`, bounded (e.g. 10-15s). This is
   a deliberately separate check from "the pid is gone" — process death and socket
   closure are not guaranteed to be the same instant, and the port-quiet signal is what
   the NEXT boot's own bind actually depends on.
5. Proceed to the existing mint-or-reuse decision exactly as it runs today
   (`provision_per_boot_certs(reuse_if_consistent=...)`).

### 2.3 Failure modes (as asked)

- **Wedged-but-alive AO.** Handled by step 3's existing terminate→3s-grace→kill
  escalation, which does not depend on the target being responsive.
- **A mint that races a slow teardown (TOCTOU).** Even after steps 1-4, there is an
  irreducible gap between "confirmed quiet" and "the next process actually binds." A
  third actor — e.g., the operator manually launching an interactive session in that
  exact window — could still collide. This is the *same class* of residual
  `instance_lock.py` already names and explicitly accepts for a single-user box ("two
  launches reclaiming the SAME stale lock within the same millisecond… not worth an
  atomic compare-and-swap here"). Option A does not claim to close this to zero; it
  claims to close the *specific, observed* failure — the harness's own sequential reboot
  logic racing itself — which is what actually happened in #863.
- **GPU state after a forced kill.** The AO holds the resident 14B model on GPU.
  `step_aside.py`'s own history (its "run-2" fix) shows that a bare forced exit leaves
  GPU context cleanup to OS timing rather than guaranteeing it — the earlier swap-driver
  runs "fit by timing luck" before that fix added a bounded graceful GPU-unload ahead of
  the hard exit. A forceful tree-kill under Option A has the same property: it is a good
  guarantee of *process* death, not a guarantee of *graceful GPU release*. See the open
  question in §6.2.
- **Kill-authorization boundary.** `_is_live_launcher`'s identity check is a
  cmdline-substring match. This is the *same* trust boundary the instance lock already
  relies on for a reclaim decision — Option A adds no new trust assumption — but it's
  worth the LA noting explicitly that the consequence of that check being wrong changes
  from "a boot is incorrectly refused" (today) to "a process is killed" (Option A):
  same check, higher-stakes use.

---

## 3. Option B — Persistent certs: stop re-minting across a session

**Framing, stated plainly:** this is not a new idea. It is ADR-026 §4.1's "long-lived
operator-provisioned certs (ceremony model)" alternative — already considered and
**rejected** at ADR-026's original authoring — being reconsidered now under operational
pressure (the reboot race) rather than new security reasoning. That history matters to
how the LA should weigh it, so this section names it up front rather than presenting
persistence as a fresh proposal.

### 3.1 What ADR-026 invariant changes

§2's "every production boot mints a fresh CA and fresh leaves" becomes: **the first boot
(or the first boot after an explicit rotation) mints; every subsequent boot reuses**,
verified by the same cryptographic check `#863` already built and shipped.

This is mechanically smaller than "persistent certs" might sound. `_load_consistent_certs`
only ever needs the CA's **public** certificate plus the already-issued leaf cert+key
pairs — all of which are *already* written to disk every single boot today, just
overwritten on the next one. Nothing about Option B requires inventing machinery to
persist the CA **private** key or to re-sign a new leaf under an existing CA. If
"rotate" is simply defined as "delete `certs/`, let the next boot mint fresh" — which is
*exactly* what `_load_consistent_certs` already falls through to on an absent set, with
zero new code — Option B reduces to: **flip `reuse_if_consistent` from an opt-in,
dispatch-only exception to the default for every boot, interactive included.**

### 3.2 The detail the "just flip the default" framing understates

`CERT_LIFETIME_HOURS = 24` (`cert_provisioning.py:74`) is a wall-clock constant that is
currently near-moot, because a fresh mint on every boot always beats it. Under Option B
it becomes the **active** constraint: the system would still force a re-mint once every
24 hours regardless of reuse — which does not achieve "stop re-minting across a session"
for anything longer than a day, undershooting what the operator's remembered instinct
was reaching for. **Extending `CERT_LIFETIME_HOURS` to a persistence-appropriate horizon
is a required companion change**, and it is itself a security parameter, not an
implementation detail — see §6.5.

### 3.3 Rotation policy (proposed, for LA disposition)

- **Automatic on expiry**: already free. `_load_consistent_certs` already refuses an
  expired set and falls through to a fresh mint; only the lifetime *value* is a new
  decision (§6.5).
- **Manual/explicit**: "delete `certs/`, reboot" is already the de facto rotation
  procedure given the existing fall-through behavior; could be formalized as a documented
  operator action.
- **Revocation**: out of scope, unchanged. ADR-026 §5.3 already named this as deferred
  (FUT-03 / Vikunja #105); Option B does not revisit that.

### 3.4 At-rest protection and the actual trade-off

The mechanism is unchanged — leaf private keys remain unencrypted PEM files on disk with
the same DACL hardening already in place (#637). What changes is the **exposure
window**: from "this boot session" to "up to the new lifetime horizon." This is a
genuine trade-off, not a new category of exposure. Framed against the actual threat
model: these certs authenticate **host-loopback-only** connections between BlarAI's own
components (gateway/AO/PA/router) — never exposed off-box; the air-gap invariant is
untouched by either option. The relevant threat is therefore a *local* actor (another
local account, malware, or an already-compromised local process) who can read `certs/` —
not a remote network attacker. Whether that already-narrow threat model makes a longer
window an acceptable price for fewer reboot races is exactly the kind of risk-acceptance
call this document surfaces rather than resolves (§6.5).

### 3.5 Composability with reuse-if-consistent

Total. Option B does not replace or conflict with #863 — it **promotes** the same
mechanism from an opt-in, dispatch-scoped exception to the steady-state default. Nothing
about the cryptographic verify-before-reuse check changes; only its default and the
lifetime constant would.

### 3.6 What Option B does NOT fix

This is the reason Option B is not recommended as a substitute for Option A (§4). Option
B removes exactly one of the two failure shapes named in §1.1 — the cert **mismatch** —
because under persistent certs there is only ever one CA generation to agree on, so
reuse never has anything inconsistent to reject. It does **not** remove the AO-lifecycle
overlap itself. A leaked or wedged prior AO under Option B no longer produces a
cert-verify failure, but it can still produce the **other** shape already observed in
#863's own log (the PID-3128 leak) — a port-bind collision, or an instance-lock refusal
— when the replacement tries to boot. Persistent certs change the symptom's costume, not
its cause.

---

## 4. Recommendation

**Recommend Option A** as the durable fix for the class of incident #805/#863 represent.
**Recommend against Option B as a substitute** for that purpose — while leaving it open
as a separate, later decision on its own merits (reboot latency/friction, simplicity),
decoupled from this incident.

Reasoning, rejected alternative visible:

- **Option A closes the actual root cause** the brief named — the AO lifecycle overlap
  — directly. Option B changes which symptom that overlap produces (§3.6) but does not
  remove the overlap itself.
- **Option A requires zero change to ADR-026's core security invariant** (per-boot
  freshness) and reopens no previously-settled trade-off. Option B explicitly reopens
  ADR-026 §4.1's already-rejected ceremony-model alternative — a heavier governance lift,
  for a fix that (per the point above) does not fully close the stated problem on its
  own.
- **Option A is buildable almost entirely from existing, already-tested, already-proven
  primitives** in this exact codebase: the instance lock's liveness check, `procspawn`'s
  tree-kill-with-escalation, `battery.py`'s own socket-readiness poll, and `probe.py`'s
  `_real_stop_ao` as a near-complete template. The net-new work is composition and one
  new choke-point call, not new cryptography or a new trust model.
- **Option A composes with, rather than competes with, the shipped #863 reuse-window.**
  The barrier shrinks the TOCTOU gap; reuse-if-consistent's cryptographic check is what
  makes the remaining sliver of that gap safe-by-construction instead of failure-prone.
  They are complementary controls at two different layers (process lifecycle vs. cert
  consistency), not alternative fixes for the same layer.

**Rejected**: adopting Option B in place of Option A on the appeal that fewer reboots
sounds operationally simpler. That appeal is real, but it does not close the incident
class this document was asked to address, and it reopens a security trade-off ADR-026
already decided against once, on operational rather than security grounds. If the LA
wants Option B for reasons independent of #863 — that is legitimate, but it should be
decided as that question, explicitly, not backed into as a side effect of fixing a
reboot race.

---

## 5. Cross-references — including two corrections

- **#863** (Vikunja, read in full) — the incident. Its own "(a) leftover state, or (b) a
  live race?" open question is resolved by §1.1/§3.6's port-collision reasoning above:
  the reuse-window (already shipped) forecloses (a)-shaped failures; the PID-3128
  "LEAKED on :5001" evidence in the same ticket is direct support for (b) as the
  mechanism this document's Option A targets.
- **#104 / FUT-02** (Vikunja, read in full) — **correction to the brief's framing.** The
  brief cites this as "the operator's original instinct" for persistent certs. Read
  directly, #104 asks for the **opposite**: measured-image CN binding with certs
  explicitly "not reusable across reboots," "expired on shutdown," Pluton-sealed
  (depends on FUT-01, not yet built), and scoped to a **guest VM's** boot cycle — the
  same "FUT-02" label ADR-026 §4.3/§5.1 already uses for measured-image CN binding
  (confirmed identical, not a coincidental number collision). #104 also predates the
  current host-mode-default topology (the AO runs host-side today, not guest-side), so
  its guest-centric framing is architecturally stale as written. If anything, #104 is a
  future data point for a more-identity-bound *variant* of a teardown control (Option A,
  hardened), not evidence for Option B.
- **#14 / GOV-01** (Vikunja, read in full) — **correction to the brief's framing.** This
  is a documentation ticket (asks for a consolidated
  `docs/CREDENTIAL_LIFECYCLE_GOVERNANCE.md`), not a technical proposal for persistence.
  Its body references SGX attestation — superseded by ADR-018's TPM trust root — and a
  PA-hosted-CA-in-the-guest model consistent with #104's stale guest-centric framing.
  Whichever option the LA eventually picks, #14 could become the right home for the
  resulting operational runbook (lifecycle, rotation, compromise recovery) — but its
  existing body should be refreshed against ADR-018 and the host-mode topology before
  being treated as settled context.
- **The operator's remembered instinct** ("didn't we have an effort to make the certs
  not re-minted every session?" — recorded verbatim in the 2026-07-11 journal fragment)
  is real signal, but it is separate from what #104/#14's actual ticket text says. It
  more plausibly recalls ADR-026 §4.1's ceremony-model alternative — which *was*
  discussed and rejected at ADR-026's authoring — than either ticket. Worth surfacing
  this distinction to him directly: the two cited tickets carry less weight toward
  Option B than their citation implied.
- **`docs/adrs/DRAFT_adr026_amendment_cert_reuse_window.md`** (this agent, prior task) —
  the reuse-window this document treats as the current baseline mitigation, itself still
  PENDING-LA-RATIFICATION. If Option A is chosen, it is a natural, smaller Amendment 2
  on top of that one. If Option B is ever chosen, it is a larger Amendment 2 that
  promotes Amendment 1's mechanism to the default — sequence ratification of the two
  drafts accordingly; Option B should not be folded in ahead of Amendment 1 being
  decided, since it depends on Amendment 1's mechanism already being accepted.

---

## 6. PENDING-LA-DECISION — explicit list

1. **Priority/timing.** Whether to schedule Option A now, later, or not at all. This
   document is decision-prep only, per the brief. §1 names the three-instance pattern as
   input to that judgment, not as a forcing function — the reuse-window already holds.
2. **Kill strategy within Option A.** Immediate tree-kill (recommended here — mirrors
   `probe.py`'s existing `_real_stop_ao`, no new cross-process signaling needed) versus a
   graceful-signal-first + bounded-forceful-backstop pattern mirroring `step_aside.py`
   (heavier: no cross-process graceful-shutdown signal exists today for the AO; one
   would need to be added). The GPU-release residual named in §2.3 is why this isn't a
   trivial choice — a forced kill is a good process-death guarantee but not a graceful
   GPU-release guarantee.
3. **Structural placement.** Whether the barrier lives inside `boot_launcher_detached()`
   itself (recommended — protects all current and future callers with one change) or is
   left as a helper each caller must remember to invoke.
4. **Whether Option B is worth pursuing at all**, for reasons independent of fixing
   #863's class (e.g., reboot latency, boot-time friction). Recommended, if pursued, to
   decouple that decision explicitly from this incident rather than let it inherit
   #863's urgency.
5. **If Option B is ever pursued**: the specific extended `CERT_LIFETIME_HOURS` value and
   the rotation cadence/trigger. These are genuine new security parameters the LA should
   set explicitly — not inherited defaults, not implementation detail (§3.2, §3.4).
6. **Kill-authorization trust boundary.** Whether `_is_live_launcher`'s cmdline-substring
   identity check is robust enough to authorize *killing* a process (Option A), given
   that today the same check only authorizes *refusing a boot* — same mechanism, a
   higher-stakes use if adopted.

---

*Drafted 2026-07-12 by a design specialist, for Lead Architect decision-prep — not for
ratification as written; no code, ADR, or register file was modified to produce this
document. Evidence base: `shared/security/cert_provisioning.py`,
`launcher/instance_lock.py` (read in full), `launcher/step_aside.py` (read in full),
`shared/procspawn.py:331-400` (read in full), `tools/dispatch_harness/battery.py:144-357`
and `:1855-1875`, `tools/dispatch_harness/probe.py:210-270`,
`launcher/__main__.py:1150-1195` and `:1470-1534`,
`docs/adrs/ADR-026-Per-Boot-mTLS-Ephemeral-Certificates.md` (read in full, §4.1/§5.3
cited), `docs/journal_fragments/2026-07-11_805-mtls-cache-poisoning.md` and
`2026-07-12_863-cert-reuse-window.md` (read in full), Vikunja #863/#104/#14 (fetched and
read in full via MCP), and this agent's own prior draft
`docs/adrs/DRAFT_adr026_amendment_cert_reuse_window.md`.*
