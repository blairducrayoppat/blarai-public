# ADR-027 — Egress Policy (Network-Facing Posture)

> **DATED HISTORY (written 2026-06-07 to 2026-07-02; last revised 2026-09-20, commit `ac24330c`).**
> Everything below this block, the header, the Context, the Decision, Amendment 1 and the 2026-07-02
> activation record, is the record of what was decided and true on the dates it carries. It is kept as written. Where a sentence says "NOT YET
> ACTIVE", "air-gapped today", "dormant" or "empty allowlist", it describes the date of that
> section, not today. This block says what has changed since.
>
> **Status as of 2026-10-11** (each point re-read in code on that date; lines can move, so the symbol
> is the pointer):
>
> - **The three base activation gates now all hold.** Gate (a) the #598 air-gap sign-off was
>   recorded 2026-06-10. Gate (b) the Sprint-17 machinery was built. Gate (c) is worded in this
>   ADR as "the policy enforces when the first web feature (W4 Kagi search) ships under #556"
>   (the further conditions, endpoint added to the allowlist and kill-switch armed, are the wording
>   of `docs/security/egress_machinery.md` and `egress_activation.md`, not this ADR); it first held
>   on **2026-07-02** (git: `9a7eed8c` merged the `LiveKagiAdapter` go-live build; `0f578d83`
>   activated the allowlist).
> - **Sequence, from git and the journal:** 2026-06-07 policy accepted and machinery staged.
>   **2026-06-12 first sanctioned external fetch** (`scripts/uc003_live_fetch_smoke.py`, commit
>   `c64f7867`: one hard-registered host, `egress_guard` deliberately not armed, the Lead Architect
>   (LA) present), which ran under Amendment 1's separate four preconditions, not under gate (c).
>   The same day the operator-driven path was built: `c6fe7e97` (operator `/ingest` activation plus an
>   armed-guard egress-door fix) and `f95c0350` (the `--go-live` flag and
>   `scripts/run_winui_golive.bat`). **2026-06-15** the operator ran `/ingest` in the production
>   app (`docs/archive/journal/2026-06.md`, "The door that stayed shut when the wire went dead"):
>   one attempt with the network down was refused fail-closed, and the next widened
>   `www.bleepingcomputer.com:443` for one fetch and revoked it about a second later (Vikunja #659 is
>   the go-live ticket). **2026-07-02 first standing allowlist entry** (`kagi.com`) for the
>   model-callable `web_search`. So the paste path has run more than once, and not only in a
>   disarmed harness.
> - **Live scope today:** `web_search` (configured by `[web_search]` in
>   `services/assistant_orchestrator/config/default.toml`; it registers only when a Kagi key is
>   provisioned). The standing Policy Agent allowlist is the class attribute
>   `DeterministicPolicyChecker._EGRESS_ALLOWLIST` in `services/policy_agent/src/gpu_inference.py`;
>   read that symbol and `docs/runbooks/web_search_go_live.md` for the current contents, not this
>   text.
> - **Socket layer:** the socket-level external allowlist in `shared/security/egress_guard.py` is
>   empty at rest. Its only non-test caller of `allow_external_endpoint` is
>   `shared/security/guarded_fetch.py`, which widens it for one host and port per fetch and revokes
>   in a `finally`. It is a different list from the standing Policy Agent allowlist above.
> - **Operator-pasted URL class (Amendment 1), what holds it shut at rest.** A normal launcher boot
>   never reads `[guest_parser]`: `_maybe_start_guest_parser` in `launcher/__main__.py` has one call
>   site, inside `if _go_live_requested():` (the `--go-live` flag), and that path first sets
>   `BLARAI_GUEST_PARSER_ENABLED=true`, an on-only override in `launcher/guest_parser.py`. So
>   `[guest_parser] enabled = false` closes nothing by itself. At rest the class is closed because
>   the parser is not brought up without `--go-live`, so the capability gate in
>   `ingest_coordinator._handle_url_ingest` refuses before any fetch, plus the fixed fetch purpose
>   (`tests/security/test_purpose_unforgeable.py`).
> - **The adjudicator for that class does not consult the standing list.** The Assistant
>   Orchestrator (AO) registers the request-keyed adjudicator (`make_request_keyed_url_adjudicate`)
>   when `web_search` is enabled, a Kagi key loads and the slot is empty; the launcher registers it
>   when the guest parser reaches READY. For purpose `uc003-url-ingest` it builds the allowlist from
>   the request's own host, so emptying `_EGRESS_ALLOWLIST` does not deny that purpose. The door
>   (`guarded_fetch.fetch_external`) still refuses at step 1 (`_validate_url`: not HTTPS, userinfo in
>   the URL, raw IP (Internet Protocol) host, port other than 443 or 8443) and at step 2.5 (named hosts that resolve to internal
>   ranges). Redesign of the levers that do not control this door is #1751; this documentation fix
>   is #1749.
> - **Exfil screen:** it screens plaintext sockets only and is never invoked for HTTPS (encrypted web traffic) (claim-register
>   row 12). It is wired at every boot by `_arm_egress_guard` in `launcher/__main__.py`.
> - **What `python -m shared.governance.permission_profile` shows:** the live web_search host and
>   the line "Every other outbound address is refused by rule, whatever any setting says." That
>   sentence is universal and is false for the operator-pasted class in a `--go-live` session (a
>   probe with the standing list emptied still let the paste purpose through to a host chosen by the
>   request); it is true at rest. The code line is covered by #1751.

**Status:** ACCEPTED 2026-06-07 (Lead-Architect-decided via interactive walkthrough); **Amendment 1
ACCEPTED 2026-06-10** (the held hybrid option adopted for the operator-pasted-URL action class,
implemented as the one-door fetch seam + "URL = authorization" + resolution-pinning + charset-correct
decode — see below; activation preconditions reconciled same day, LA verdict 2026-06-10). **NOT YET
ACTIVE** — this governs the *network-facing era*; the #598 §5.12 LA sign-off is **RECORDED** (GO, #598
comment 1026, 2026-06-10), and the air-gap stays up until the first web feature ships. Implemented in
Sprint 17 (Tier-3 egress); the one-door `guarded_fetch` seam built 2026-06-10 (#577); enforced only when
a caller wires the PA adjudicator and a web feature ships.
**Deciders:** Lead Architect (blarai); Orchestrator (facilitation).
**Builds on:** ADR-020 (code-enforced egress kill-switch — the mechanism this policy governs), ADR-023
(provenance trust model + Policy-Agent tool-dispatch mediation), ADR-018 (TPM trust root).
**Relates to:** #598 (air-gap GO/NO-GO gate), #556 (network capabilities), the W4/W5 web-search work,
`SECURITY_ROADMAP_air_gap_removal.md` §5 (egress gate criteria) + §6 Decision-5 (PII posture).

## Context

BlarAI is air-gapped today: ADR-020's `egress_guard.py` is armed at every boot with a fail-closed
allowlist of **loopback + the Hyper-V vsock channel only**; all other network egress is denied at the
`socket.socket` layer, and `tests/security/test_no_external_egress.py` fails the build on any
external-network import. The platform will eventually gain web abilities (web search via Kagi — the
mandated privacy-respecting search provider — and reading pages) under #556, *after* the #598 air-gap
GO/NO-GO gate. Before that machinery is built (Sprint 17, Tier-3 egress), the policy it must enforce has to
be decided.

This ADR records that policy. **It changes nothing today** — it is the rulebook the Sprint-17 egress build
implements, and it activates only when web features ship. The Lead Architect chose the strict option at
each of four forks in an interactive walkthrough (2026-06-07); the policy is deliberately fail-closed and
privacy-absolute, consistent with BlarAI's identity.

## Decision

Four rules govern all network egress once any web feature is enabled. They are independent layers: a single
failure does not open the door.

### 1. Allowlist — deny-by-default, named endpoints only
Nothing reaches the internet unless it is on an explicit allowlist; everything else is refused. This
extends ADR-020's existing fail-closed allowlist from "loopback + vsock" to "loopback + vsock + the named
external endpoints a live feature requires." The allowlist starts with **Kagi** and grows **one vetted
endpoint at a time**, each added only as the feature that needs it ships, each behind the controls below.
- *Alternative not taken:* a broad "any HTTPS, screened" posture — rejected as incompatible with
  privacy-absolute + fail-closed.

### 2. Approval — the Policy Agent auto-approves within the allowlist, and logs every call
When BlarAI calls an allowlisted endpoint, the Policy Agent (PA) approves it automatically — the
`DENY_EXTERNAL_NETWORK` deterministic rule gains a carve-out for allowlisted, PA-adjudicated egress
(building on ADR-023's PA tool-dispatch mediation). Every call is recorded to the audit stream. Off-list
calls are hard-denied. There is **no per-call user confirmation**: the guarantee comes from the tight
allowlist + the outgoing screen (rule 4) + the kill-switch (rule 3), not from user friction.
- *Alternatives not taken:* per-action user consent for every web call (rejected — friction makes web
  features unusable without adding security when the allowlist is tight); a hybrid (auto for search,
  consent for arbitrary page-fetch) — **held as a future refinement** if a feature warrants it, not the
  default.

### 3. Kill-switch — default-off, auto-trip on anomaly, Lead-Architect-only re-arm
ADR-020's kill-switch (already built + armed) governs the network-facing era as follows: egress stays
**off by default**; a feature's allowlisted endpoint opens only when that feature is explicitly enabled.
The system **automatically trips** — cuts ALL egress and alerts the operator — on a detected anomaly: a
secret/PII detected leaving (rule 4), or an attempt to reach an off-allowlist address. **Only the Lead
Architect can re-arm** egress after a trip, and holds a master off-switch available at all times.
- *Alternatives not taken:* manual-only with no auto-trip (rejected — no automatic defense if something
  misbehaves); default-on once a web feature is enabled (rejected — leaves the door propped open).

### 4. Exfiltration screening — screen every outbound payload, block on detection
Before any payload leaves — even to an allowlisted endpoint — it is screened for secrets and Personally
Identifiable Information (PII). On detection, the call is **blocked** (fail-closed) and the operator is
alerted. This **sharpens `SECURITY_ROADMAP` §6 Decision-5** (previously "redact at the egress boundary") to
**block-on-detection** for the egress path, and resolves the open PII-at-egress posture flagged in
`SECURITY_ROADMAP` §5.10.
- *Alternatives not taken:* redact-and-proceed (rejected — trusts the redactor to catch everything; a miss
  is a leak); no screening (rejected outright).

## Consequences

- **Positive:** the air-gap-removal posture is fail-closed at four independent layers; web features stay
  usable (no per-call nagging); every call is auditable; the operator has a hard stop. Resolves the §5
  "egress allowlist ratified" gate criterion (the *policy* is now ratified) and the §5.10 PII-at-egress
  posture.
- **Negative / accepted trade-offs:** auto-approval within the allowlist means the operator trusts the
  allowlist + the exfil screen rather than vetting each call (mitigated by full logging + the kill-switch);
  block-on-detection can block a legitimate call if the screen false-positives (accepted — fail-closed is
  the mandate; the operator is alerted and can act).
- **Held option:** the hybrid-consent refinement (rule 2 alternative) remains available if a future feature
  warrants per-action consent (e.g. fetching arbitrary user-directed URLs).

## Activation (not on acceptance)

Sequence, each gate independent: (a) **#598** air-gap GO/NO-GO passes (production posture) —
**RECORDED**: the §5.12 LA sign-off landed as GO on #598 comment 1026, 2026-06-10; (b) **Sprint 17**
builds the Tier-3 egress machinery to this policy — the runtime raw-socket guard already exists (ADR-020);
this adds the allowlist-widening mechanism, the PA `DENY_EXTERNAL_NETWORK` carve-out, the anomaly auto-trip,
and the exfil screen; (c) the policy enforces when the first web feature (W4 Kagi search) ships under #556.
Until all three hold, the air-gap stays up and the allowlist remains loopback + vsock only.

## Amendment 1 (2026-06-10) — User-directed URL egress: per-action adjudication via the one-door fetch seam

> **DATED HISTORY (written 2026-06-10 to 2026-07-02; last revised 2026-09-20, commit `ac24330c`).**
> This Amendment, including its "Until these hold, `INGEST_FETCH` does not exist" sentence, the
> 2026-06-12 verification note listing three implementation locks (with the 2026-09-20 note about the
> removed adjudicator symbol inside it) and the 2026-07-02 activation record, is kept as it stood on
> those dates. See the "Status as of 2026-10-11" block at
> the top of this file for what holds today; in particular the `[guest_parser].enabled=false` lock and
> the "adjudicator never registered" lock named in the 2026-06-12 note are no longer a description of
> the live wiring.

**Status:** ACCEPTED 2026-06-10 (Lead-Architect-ratified at the #655 UC-003/UC-002 program
comprehension gate; implementing mechanics built same day under #577 and merged 2026-06-10 — the two
limbs of this amendment were unified into this single record at the UC-002/003 integration merge).
**NOT YET ACTIVE** — same gating as the base policy; activation preconditions below. **Consumed by:**
ADR-030 (UC-003 Cleaner v1 — the paste-URL ingest pipeline this amendment exists for).

**Decision:** the hybrid option rule 2 explicitly **held** ("auto for search, consent for arbitrary
page-fetch... held as a future refinement if a feature warrants it") is now **ADOPTED for exactly one
action class: operator-pasted URLs** (the UC-003 `/ingest <url>` flow). For that class:

- **The paste is the consent — for that ONE URL.** The operator typing `/ingest <url>` is the explicit
  per-action authorization for a single fetch of that single URL. No additional confirmation dialog;
  no standing permission is created for the host, the domain, or any later fetch.
- **The PA adjudicates per-action.** A new **`INGEST_FETCH` action class** is adjudicated by the
  Policy Agent per fetch — the `DENY_EXTERNAL_NETWORK` rule gains a second, *per-action* carve-out
  beside the rule-1 static-allowlist carve-out: an `INGEST_FETCH` carrying an operator-pasted URL is
  approved for that action and **logged to the audit chain**, exactly as rule 2 logs allowlisted
  calls. Anything else aimed at an off-allowlist destination stays hard-denied.
- **GET-only, and no user-content echo in the outbound request.** The fetch issues GET requests only
  (no POST/PUT, no request body), and the outbound bytes carry the URL + minimal protocol headers —
  **never** prompt text, session content, or any user data. This is both an exfiltration control and
  a false-positive hygiene rule: the rule-4 exfil screen blocks-and-trips on PII/secret-shaped
  outbound content, so a request that echoed user content could trip the latched kill-switch on the
  operator's own legitimate data (the screen's fail-closed posture is accepted; the mitigation is
  keeping outbound payloads minimal so a trip is always a real signal).
- **Rules 3 and 4 are unchanged.** The kill-switch (default-off, auto-trip on anomaly, LA-only
  re-arm — now Hello-gated per #653) and the exfil screen (block-on-detection) wrap `INGEST_FETCH`
  exactly as they wrap allowlisted endpoints. This amendment changes *who approves the destination*,
  not what guards the wire.
- **The static allowlist remains the rule for service endpoints.** Kagi (and any future service
  BlarAI itself calls) stays under rule 1's named-endpoint, one-vetted-at-a-time allowlist. The
  per-action class exists because arbitrary news-article URLs structurally cannot be enumerated —
  `SECURITY_ROADMAP` §6 Decision-6 anticipated exactly this: "adjudicate the *action* + screen the
  outbound, not allowlist the web."

**The implementing mechanics (#577, built same day):** building the first consumer forced four
implementation-level decisions, recorded in the subsections below; none of them weakens the four rules
above.

### 1a. One door — `shared/security/guarded_fetch.fetch_external` is THE single external-fetch seam
Every external fetch — UC-003 now, any future web tool (Kagi search, a URL-clean agent) — goes through one
module: `shared.security.guarded_fetch`. It runs the four ADR-027 rules as an ordered, fail-closed pipeline
(SSRF guard → PA adjudication → charset-correct fetch behind a per-fetch allowlist widen/auto-revoke →
injection scan). Nothing else in the runtime opens an external socket: `httpx` (the one network client) is
imported by **exactly that one module**, enforced by `tests/security/test_no_external_egress.py` (the
import-scan control now carries a single-file exemption for the door plus a companion test asserting the
carve-out is one file wide and imports only `httpx`). This makes the air-gap a *door with a guard*, not a
torn-down wall.
- *Alternative not taken:* let each web feature open its own guarded socket — rejected; N doors is N audit
  surfaces and N ways to drift. One door, one guard, one place to reason about egress.

### 1b. "URL = authorization" — the PA verdict governs; ESCALATE (not ALLOW) prompts for consent
This is the verdict-tier mechanics of the per-action decision above. When the operator initiates a fetch,
the PA verdict on that URL governs and that verdict alone: **ALLOW** proceeds with **no extra mandatory
fingerprint** (the operator initiating the fetch *is* the authorization — hence the name); **DENY** blocks;
**ESCALATE** prompts for a Windows-Hello fingerprint
via the #639 consent path (`escalation_consent.request_escalation_consent`), approval proceeding and
denial/timeout/no-verifier falling closed to DENY. So consent is reserved for the ESCALATE tier, not levied
on every ALLOW.
- *Why not a mandatory consent on every ALLOW:* a fingerprint on every fetch trains the operator to
  rubber-stamp, which destroys the signal the ESCALATE tier depends on. Rule 2's "no per-call user
  confirmation within the allowlist" holds; ESCALATE is the deliberate exception, and it is the PA — not a
  blanket policy — that decides when to invoke it.
- *Alternative not taken:* a mandatory fingerprint on every ALLOW (rejected — rubber-stamp training, as
  above); no consent tier at all (rejected — ESCALATE would silently collapse to DENY, the pre-#639 gap).

### 1c. Hostname-resolution pinning — the mechanism that lets rule 1's allowlist work with a real HTTP client
A standard HTTP client resolves a hostname via `socket.getaddrinfo` then connects to the **numeric IP**, which
is off the literal-string allowlist and would AUTO-TRIP the kill-switch (rule 3). `egress_guard` now pins an
allowlisted hostname's resolved IPs (`ip → {hostnames}`) at resolution time, admitting the subsequent numeric
connect **only** at the allowlisted port, and **only** for an IP an allowlisted name actually resolved to.
Deny-by-default (rule 1) is preserved: an IP nobody resolved has no pin and still trips. Pins are dropped on
`revoke_external_endpoint` (that host), `clear_external_allowlist`, and `disarm`. A pinned-IP connect still
tags the socket so the exfil screen (rule 4) fires on real outbound traffic.

### 1d. Charset-correct decode — honor the declared charset, never a blind UTF-8 assume
The fetched body is decoded by its **declared** charset (Content-Type header, then an HTML `<meta charset>`),
falling back to UTF-8-with-replacement only when nothing declared decodes. A page may legitimately send
ISO-8859-1 / Shift_JIS / etc.; a blind UTF-8 decode would mangle it. This is a correctness requirement of the
ingest path, recorded here because it is part of the sanctioned fetch behavior.

**Still dormant in production:** `guarded_fetch` ships WITHOUT a registered PA adjudicator (registering one is
the caller's job — UC-003's wiring), so with nothing wired every fetch DENIES. The allowlist stays loopback +
vsock until a caller widens it per-fetch. This amendment records the *mechanism + posture*; it does not flip
the air-gap. Activation is still gated by the base sequence above and the reconciled preconditions below.

**Implementing mechanism (epic #577 comment 1029, cross-session contract, 2026-06-10):**
`shared/security/guarded_fetch.fetch_external(url, purpose, timeout_s)` — the single
Policy-Agent-gated egress door W4 ships — is the implementing mechanism of this per-action posture:
its **temporary allowlist widen + guaranteed revoke** flow IS the per-action adjudication carve-out
(the destination opens for exactly one adjudicated fetch and is closed again; no standing
permission is ever created). The `INGEST_FETCH` action class therefore **rides the SAME door as W4
`/search`** rather than a parallel PA carve-out — one mechanism (SSRF/scheme validation, per-URL PA
adjudication with ESCALATE → Windows-Hello consent, exfil screening, body injection scan) serves
both classes, so there is one code path to audit and one to trip. Consumers (ADR-030) never call
`egress_guard.allow_external_endpoint` directly. The activation preconditions below were
subsequently reconciled by the 2026-06-10 LA verdict (the NIC-precondition inversion + the
structural-dormancy reframe), not by this note.

**Activation preconditions (reconciled 2026-06-10, LA verdict — supersedes the originally-ratified
three-item list, which named guest-NIC provisioning and a `fetch_enabled` config flip; neither
survives):**
1. the **#598 §5.12 LA sign-off** — **RECORDED**: GO on #598 comment 1026, 2026-06-10 (satisfied);
2. **this Amendment in force, verified against the real W4 code** — Am.1 was ratified against the
   #577 c.1029 *contract*; before the first live `INGEST_FETCH` it is verified against the shipped
   `guarded_fetch` implementation (W4 shipped it — merged to main `8703dae`, 2026-06-10; the
   mechanics subsections above describe the as-merged behavior);
3. **the Stage-C fetch limb is WRITTEN** through `shared/security/guarded_fetch.fetch_external` —
   dormancy today is the **structural ABSENCE of fetch code**, not a config flag: no `fetch_enabled`
   switch exists anywhere, by design (unwritten code cannot be mis-flipped on);
4. **the zero-NIC guest invariant** — the guest remains **NIC-less**; the launcher asserts zero NICs
   on the VM at start and **fails closed if one appears** (assertion landed: `launcher/vm_manager.py`
   `verify_vm_zero_nic`, called at VM start). This INVERTS the struck "guest VM NIC provisioning" precondition, which
   was ratified under the old fetch-in-guest design — under the one-door host-side composition
   (ADR-030 §3), a guest NIC creates exactly the exposure the zero-NIC posture defends.

Until these hold, `INGEST_FETCH` does not exist at runtime and the air-gap posture is unchanged.

### Activation-verification note (2026-06-12) — all four preconditions now MET; door still welded by three implementation locks

The Stage-C fetch limb (precondition 3) is now WRITTEN end to end and merged, and Amendment 1 has
been **verified against the shipped code** (precondition 2) — not just the #577 c.1029 contract. The
operator-directed URL egress path is `services/ui_gateway/src/ingest_coordinator.py` (`/ingest <url>`)
→ `shared/security/guarded_fetch.fetch_external` (the one door, `8703dae`) → the NIC-less guest parser
over vsock → host §5 compose → preview (host glue `75ba1c7`), with PA adjudication via
`services/ui_gateway/src/url_adjudicator.make_deterministic_url_adjudicate` (`be603db`) — **that symbol was removed 2026-09-20 (#1586); the live wiring is `make_request_keyed_url_adjudicate`, which selects the allowlist policy from the request's `purpose`. This line records what was verified in 2026-06 and is kept as history; a reader chasing the live door from here should follow the new name.** Verified faithful
to Amendment 1: **one door** (httpx imported by exactly that module, import-scan-enforced);
**GET-only, no user-content echo** (`client.stream("GET", url)`, no request body — only the URL + protocol
headers cross the wire); the **ordered fail-closed pipeline** (SSRF guard → PA adjudication → per-fetch
allowlist widen/guaranteed-revoke → injection scan); **"URL = authorization"** verdict tiers (ALLOW
proceeds, DENY blocks, ESCALATE → #639 Windows-Hello, already registered at launcher startup); the
**per-action carve-out** realized as the deterministic checker's ADR-027 §2 egress-allowlist populated with
the operator's host for that one fetch and emptied after (no standing permission); **rules 3+4 unchanged**
(the egress-guard kill-switch latch + the socket-tagged exfil screen wrap the widened fetch); the **guest
stays NIC-less** — the fetch is host-side, the guest only parses.

Preconditions 1 (§5.12 sign-off RECORDED) and 4 (zero-NIC invariant asserted at VM start) were already
satisfied; 2 and 3 are satisfied by this verification. **So all four Amendment-1 activation preconditions
are now MET.** The runtime nonetheless stays deny-by-default by **three independent IMPLEMENTATION locks**,
none of which is a precondition above: (i) no PA adjudicator is registered on `guarded_fetch`
(`register_url_ingest_adjudicator` exists but is never called at startup); (ii) `guest_parser.enabled=false`
ships, so the guest parser is not brought up and URL ingest refuses at the availability gate; (iii) the
deterministic checker's egress allowlist is empty, so even a registered adjudicator denies every URL by
policy (RULE 3). Opening the door for a fetch is the operational act of registering the adjudicator with the
operator's host allowlisted (the per-action carve-out above) for exactly one fetch — the
`/ingest <bleepingcomputer-url>` going-live test (#655). Parse-channel mTLS is the named **hard gate** but
governs the on-box host↔guest vsock hop (never a network path); its host-side plumbing is threaded through
and dormant (`[guest_parser].mtls_cert/key/ca` empty → plaintext bring-up), activation being a config-only
guest re-provisioning step.

**Alternatives not taken:**
- **Static per-domain allowlist for article URLs** — rejected: vetting news domains one at a time
  makes the feature unusable (the rule-1 model is built for a handful of service endpoints, not the
  open web), and a domain-grained allowlist is *weaker* than per-action consent — it creates standing
  permissions an injected instruction could ride, where the paste-consent model authorizes exactly
  one fetch of one operator-chosen URL.
- **Windows Hello per fetch** — rejected: a biometric prompt immediately after the operator
  deliberately typed `/ingest <url>` re-confirms intent that was just expressed, adding friction
  without adding information (rule 2's original anti-friction reasoning, applied honestly to this
  class). Hello remains the verifier for PA ESCALATE verdicts and kill-switch re-arm (#639/#649/#653),
  where the action was *not* operator-initiated.

**Consequence:** the "Held option" recorded in Consequences above is hereby exercised for the
operator-pasted-URL class and remains held for any other class; the base policy's four rules are
otherwise unchanged. LA ratification date on the record: **2026-06-10** (Vikunja #655).

### Activation record (2026-07-02) — first standing allowlist entry: kagi.com (web_search go-live, #719)

The §1/§2 rule-1 allowlist mechanism is hereby ACTIVATED with its first standing entry:
`kagi.com`, the single service endpoint the model-callable `web_search` feature (ADR-024 W4)
needs. This is the rule-1 "web endpoints a feature needs" class — a vetted service endpoint —
distinct from Amendment 1's per-action operator-pasted-URL consent class, which remains
per-action (no standing permission). The one populated list is read by BOTH egress layers:
the AO tool loop's D4 dispatch adjudication (#719, LA decision c.1298 — the dispatch CAR
carries the real endpoint URL) and the `guarded_fetch` door — a single source, never a second
list. Every off-list host remains RULE-3 denied (eval pin gov-pf-001); the go-live tripwire
gov-pf-007 flipped to pin the new posture in the same reviewed change, exactly as designed.
Procedure: `docs/runbooks/web_search_go_live.md`. The re-weld path (emptying the entry)
restores the welded air-gap. LA authorization: Part B pre-authorization + ceremony
(2026-07-02, Vikunja #719); DECISION_REGISTER updated in this same change.

## References

ADR-020 (egress kill-switch mechanism), ADR-023 (PA tool-dispatch mediation), ADR-018 (TPM trust root);
`docs/security/SECURITY_ROADMAP_air_gap_removal.md` §5 + §6 Decision-5 + Decision-6; #598, #556, #655,
#577 (comment 1029 — the `guarded_fetch` implementing-mechanism contract);
ADR-030 (Amendment-1 consumer); the Sprint-16 SWAGR (Stream E §5 egress-criteria reconciliation).
DECISION_REGISTER index updated in the same change as Amendment 1 (the non-optional maintenance rule).
