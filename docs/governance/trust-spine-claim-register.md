---
title: Trust Spine Claim Register
status: living
area: governance
---

# Trust Spine Claim Register

> **Acronyms on first use.** ADR = Architecture Decision Record. CAR = Canonical
> Action Representation (the structured request every tool call / fetch is reduced
> to before adjudication). PA = Policy Agent. AO = Assistant Orchestrator. JWT =
> JSON Web Token. TPM = Trusted Platform Module. DEK = Data-Encryption Key. mTLS =
> mutual Transport Layer Security. SSRF = Server-Side Request Forgery. TOCTOU =
> Time-Of-Check-To-Time-Of-Use (a race between validating something and using it).
> PGOV = Post-Generation Output Validator. VM = Virtual Machine. DoS = Denial of
> Service. AIGP = Artificial-Intelligence Governance Professional (the
> certification this record supports).

## Status

**LIVE record, as of 2026-09-16.** This is a synthesis document: it does not
introduce a new mechanism, it inventories claims already made — by ADRs, by
runbooks, by this directory's own domain docs, and by the running code and its
tests — and states, per claim, what would have to be true on disk for the claim
to hold. Where an existing domain doc in this directory already owns a claim in
depth ([weight-integrity.md](weight-integrity.md),
[credential-lifecycle.md](credential-lifecycle.md)), this register points at it
rather than re-deriving it. Where no domain doc exists yet (most of the egress
spine), this register is the first place the claim and its limitation are
written down together.

## Audience

**Primary**: auditor — the reason this document exists. Reads claim-by-claim for
what BlarAI's trust spine asserts about itself, what would have to be false on
disk for the assertion to fail, and what is already, honestly, not fully closed.

**Secondary**: developer (any change to a cited source file should update the
claim it backs, in the same commit); incident responder (a claim's Evidence
column names the exact test to re-run to confirm the control still holds);
future agent (read this before asserting anything about what BlarAI's security
posture *is* — per [STYLE.md](STYLE.md) and `CLAUDE.md`'s own `authority_first`
rule, this is the surface that owns the composite claim "the trust spine
does X," even where the underlying fact is owned elsewhere).

## Prerequisites

- [STYLE.md](STYLE.md) — binding governance template; this doc follows its
  six-part structure in full (Audience, Prerequisites, Source References,
  Governance Content, Recovery, Open Questions) — its subject is unusually
  broad (a claim about every other claim in this directory, the ADR corpus,
  and the code), not structurally different from a narrower domain doc.
- [weight-integrity.md](weight-integrity.md) — owns claims 14–15 in depth; this
  register summarizes and points there.
- [credential-lifecycle.md](credential-lifecycle.md) — owns claims 16–19 in
  depth, and is the on-disk source for claim 25 (the vestigial CAR/JWT
  pipeline) — its §9.2 is the most precise existing statement of that finding.
- [context-spotlighting.md](context-spotlighting.md) — owns claims 21–22.
- [pgov-validation.md](pgov-validation.md) — owns claim 23.
- [circuit-breaker.md](circuit-breaker.md) — owns claim 24.
- [ipc-protocol.md](ipc-protocol.md), [rule-engine.md](rule-engine.md) — describe
  the mechanism named in claim 25; both now carry a `## Status` note pointing
  here and at ADR-041, added in the same change as this register.
- [ADR-023](../adrs/ADR-023-Provenance-Based-Trust-Model.md),
  [ADR-020](../adrs/ADR-020-Code-Enforced-Egress-Kill-Switch.md),
  [ADR-027](../adrs/ADR-027-Egress-Policy-Network-Facing.md),
  [ADR-041](../adrs/ADR-041-Host-Mode-Action-Authorization-Boundary.md),
  [ADR-039](../adrs/ADR-039-Coordinator-Self-Governance-Boundary.md) — the
  five ADRs claims 1–13 and 26 trace to; each claim below cites the specific
  section rather than repeating the ADR's own content.
- `docs/runbooks/web_search_go_live.md`, `docs/runbooks/manifest_signing_ceremony.md`,
  `docs/runbooks/at_rest_encryption_ceremony.md`, `docs/runbooks/vm_lifecycle.md`
  — the operator-facing ceremony records; cited per claim.
- `docs/research/cava-vs-microsoft-agent-framework-vs-blarai-trust-spine-2026-09-16.md`
  and its sibling documents (Vikunja **#473** cites this register itself; the
  research set is tracked as its own closed ticket, **#471**, `identifier`
  scheme — see that ticket's description for the four documents' individual
  names) — the source for claims 27–28 (Gap A / Gap B), which are not yet
  written down anywhere else.
- `docs/research/runtime-action-governance-landscape-2026-09-16.md` — the
  landscape compilation (Vikunja **#1540**): every surveyed item scored on the
  five questions this register's claims answer for BlarAI, with BlarAI's own
  row scored from rows 1–14, 16, 18, 20–22 and 27–29 of this table, and the
  source for claim 29 (Gap D). It is where the field's state on each gap
  lives; this register stays the surface that owns what BlarAI claims about
  itself.

## Source References

| Claim group | Primary source(s) | Code |
|---|---|---|
| 1–4 (the adjudication door) | ADR-023 §2.1, ADR-041 | `services/policy_agent/src/gpu_inference.py` (`DeterministicPolicyChecker`), `shared/security/guarded_fetch.py`, `services/assistant_orchestrator/src/entrypoint.py` (`_adjudicate_tool_dispatch`) |
| 5–7 (egress scopes) | ADR-023 Am.2/3, ADR-027, `docs/runbooks/web_search_go_live.md` | `services/assistant_orchestrator/config/default.toml`, `launcher/config/default.toml`, `services/policy_agent/src/gpu_inference.py:403` |
| 8–13 (defense in depth) | ADR-020, ADR-023 Am.4 | `shared/security/egress_guard.py`, `shared/security/exfil_screen.py`, `services/assistant_orchestrator/src/egress_envelope.py`, `shared/security/escalation_consent.py`, `tests/security/test_no_external_egress.py` |
| 14–15 (weight integrity) | [weight-integrity.md](weight-integrity.md) | `shared/models/weight_integrity.py`, `shared/models/manifest_signer.py` |
| 16–17 (transport identity) | [credential-lifecycle.md](credential-lifecycle.md) §3–5 | `shared/security/cert_provisioning.py` |
| 18–19 (at-rest data) | [credential-lifecycle.md](credential-lifecycle.md) §6, ADR-025 | `shared/security/dek_envelope.py`, `shared/security/tpm_sealer.py` |
| 20 (VM isolation) | ADR-007, `docs/runbooks/vm_lifecycle.md` | Hyper-V VM config (no code path — host config) |
| 21–24 (model-facing defenses) | [context-spotlighting.md](context-spotlighting.md), [pgov-validation.md](pgov-validation.md), [circuit-breaker.md](circuit-breaker.md), ADR-013 | `services/assistant_orchestrator/src/context_manager.py`, `services/assistant_orchestrator/src/pgov.py`, `shared/constants.py` (`MAX_OUTPUT_TOKENS`, `MAX_TOOL_CALL_DEPTH`) - `circuit_breaker.py` was DELETED in #1596, having never had a production caller |
| 25 (vestigial pipeline) | ADR-041, [credential-lifecycle.md](credential-lifecycle.md) §9.2 | `services/policy_agent/src/rule_engine.py`, `services/policy_agent/src/adjudicator.py`, `shared/crypto/jwt_validator.py` |
| 26 (coordinator boundary) | ADR-039, `coordinator_graduation_criteria_2026-07-23.md` | `shared/coordinator/policy.py`, `shared/coordinator/boot_canary.py`, `shared/coordinator/config.py` |
| 27–29 (undocumented gaps) | `docs/research/cava-vs-microsoft-agent-framework-vs-blarai-trust-spine-2026-09-16.md` (27–28); `docs/research/runtime-action-governance-landscape-2026-09-16.md` (29) | `shared/schemas/car.py` (`canonical_hash`), `shared/security/audit_log.py` (`append`, `verify`, `_load_existing`) |

## Governance Content

### Methodology — what counts as evidence, and how status is read

This register does not accept a document's description of a control as the
control. Per `CLAUDE.md`'s own testing doctrine and this directory's
**Auditor-first** framing (`STYLE.md` §Voice and Framing), a claim's evidence is
either (a) the source file that implements it, or (b) a runbook's own dated
"EXECUTED" / "NOT YET ACTIVE" banner cross-checked against the config flag it
describes. Documentation that merely *asserts* a control, with no corresponding
source or dated ceremony record, is named as such rather than credited.

Where a control has an on/off toggle, this register additionally states whether
a **block-test** exists (proves the control refuses a forged or disallowed
action while engaged) and an **off-test** exists (proves the disabled state
behaves differently from the enabled state — not merely that it also denies).
Both halves are `CLAUDE.md`'s own bar (`security_by_design` principle 12): a
control that only has a block-test cannot be distinguished from a test that
simply can't reach the control at all. Several controls below are fail-closed
**by construction** — there is no code path that disables them, so their "off"
state is architecturally absent rather than tested; this is noted per claim,
since it is a *stronger* property than a tested toggle, not a weaker one.

Status words follow `STYLE.md`'s vocabulary (**LIVE**, **DESIGN-INTENT**,
**DECLINED**, **DEFERRED**) where they fit cleanly. Six rows below (3, 15,
26, 27, 28, 29) don't fit that four-word vocabulary precisely and are given
exact prose instead, flagged inline, rather than forced into a label that
would mislead.

### The register

| # | Claim | Status | Evidence | Stated limitation |
|---|---|---|---|---|
| 1 | Every tool call and every outbound web fetch is adjudicated in-process by one deterministic checker before it executes, fail-closed on any error. | **LIVE** | `gpu_inference.py:459-613` (`DeterministicPolicyChecker.check`; the class itself opens at `:349`), called from `entrypoint.py:302-372` and `guarded_fetch.py:615-661`. Block-tests: `test_tools.py:2039`, `test_guarded_fetch.py:166,192,203`. | See claims 2–4 below — the door's independence, not its existence, is where the open gaps live. |
| 2 | The egress door (`guarded_fetch.py`) that gates every outbound web fetch has exactly one adjudicator slot. | **LIVE** | `guarded_fetch.py:372-373` (module-level slot), `:376-417` (`register_url_adjudicator`). Off-test: `tests/security/test_guarded_fetch.py::test_no_adjudicator_registered_denies` (an empty slot actually denies a fetch, not just reads as `None`). | The function's own docstring is internally inconsistent: it asserts *"first-wins"* at line 383, then describes replace semantics — *"registering replaces any previously-registered one"* — sixteen lines later at line 399. The function body (`:408-412`) mechanically implements **last-write-wins**, unconditionally overwriting the slot with no `is None` guard. `CLAUDE.md`'s own `<stack>` section and the runbook both inherit the docstring's "first-wins" sentence rather than the code's actual behavior. One production call site exists today (`launcher/__main__.py:1112-1115`), so the distinction has no live consequence — but no test exercises two sequential registrations to confirm which one would actually win if a second caller were ever added. |
| 3 | The tool-dispatch checkpoint (claim 1's `DeterministicPolicyChecker`) and the egress-door checkpoint read the same allowlist, so a request denied by one is denied by both. | **LIVE for every purpose but operator-paste** (#977 CLOSED 2026-09-20 by #1586; was PARTIAL/open, Gap C in the 2026-09-16 research set) | `shared/security/guarded_fetch.py` `register_url_adjudicator` docstring — rewritten 2026-09-20: the slot is LAST-write-wins (the function overwrites unconditionally; the AO guards its own call, the launcher does not), and which adjudicator holds it no longer decides policy. `services/ui_gateway/tests/test_url_adjudicator_both_postures.py` is the control. **The old evidence line cited a docstring that still said "#977 OPEN" for hours after the fix landed — a row pointing at stale evidence reads as confirmation.** | **A RUNTIME INVARIANT SINCE 2026-09-20 (#1586/#977) — for every purpose except operator-paste, which authorizes its own host BY DESIGN.** Previously not an invariant at all: the door had one adjudicator slot and two components registered different policies into it, so whichever won decided the policy for both. The superseded text of this cell, kept because the wrong version is the useful one: *"The agreement holds only because exactly one adjudicator is registered today ... in a session booted with `--go-live` (URL ingest), the launcher fills that slot first with the operator 'paste = consent' factory... the door layer no longer checks against `_EGRESS_ALLOWLIST`... the claim that both layers read the same allowlist is FALSE."* There is now ONE adjudicator (`make_request_keyed_url_adjudicate`) and the REQUEST selects the allowlist policy from its `purpose`, so both registration sites build the same callable and startup order decides nothing. **The honest residual, stated rather than dropped:** the two layers do NOT read the same allowlist for a paste purpose, and never could — paste-is-consent means the request authorizes its own host, so "the same allowlist" is the wrong frame there. That branch is reachable only by a purpose named in `PASTE_IS_CONSENT_PURPOSES`, it is unreachable in the live runtime today (`[guest_parser].enabled = false`, and the ingest coordinator refuses before the fetch), and its safety rests on `purpose` being unforgeable from the model side — proved continuously by `tests/security/test_purpose_unforgeable.py`, which fails CLOSED on any indirection it cannot resolve. Control: `services/ui_gateway/tests/test_url_adjudicator_both_postures.py` drives both postures through ONE adjudicator, 7 of 7 mutants killed. **Also corrected here: "empty allowlist = every URL denied" was cited as a lock on URL ingest and never bound the paste path in any process.** |
| 4 | The egress door's SSRF guard resolves a URL's host before fetching and refuses a request that resolves to a blocked (internal/loopback) range. | **LIVE, residual acknowledged** | `guarded_fetch.py`, the pre-fetch resolve-and-recheck step. Block-test: `test_guarded_fetch.py` `TestSsrfGuard.test_ssrf_rejected_urls_never_fetch:296`. | **DNS rebinding (TOCTOU) not fully closed**, named in the module's own docstring (`guarded_fetch.py:51-59`): *"the pre-fetch resolve-and-recheck and httpx's OWN resolution at connect time are two separate lookups; a rebinding attacker can answer the check with a good public IP and answer httpx's connect with a bad internal IP."* The robust fix — a transport that validates the peer IP actually connected to — is named as a deliberate follow-up with no ticket number. |
| 5 | Web search (Kagi) is the only live, populated destination on the network allowlist; every other destination is denied by default. | **LIVE** since 2026-07-02 | `_EGRESS_ALLOWLIST = frozenset({"kagi.com"})`, `gpu_inference.py:403`. `services/assistant_orchestrator/config/default.toml:214` (`[web_search].enabled = true`). `docs/runbooks/web_search_go_live.md` banner: *"THIS CEREMONY HAS ALREADY BEEN PERFORMED — 2026-07-02 (#719)."* Config and runbook agree. | Scoped to `web_search` only — the runbook's own "Out of scope" list (lines 322-334) explicitly excludes URL-ingest, display-images, and the agentic multi-step search loop's own injection defenses ("W5 defenses not yet live"). |
| 6 | Fetching a URL a user directly pastes (`/ingest <url>`) is switched off — not merely unconfigured, but structurally unreached. | **DESIGN-INTENT** | `launcher/config/default.toml:29` (`[guest_parser].enabled = false`). Header comment: *"until the controlled activation session proves the deploy channel + the guest service end-to-end, the launcher skips the guest parser entirely."* | No dedicated go-live runbook exists yet in `docs/runbooks/` for this ceremony (a gap in the runbook set, not in the control). The host↔guest mTLS channel for this path is separately dormant (`launcher/config/default.toml:97-111`, all three cert paths empty). |
| 7 | Fetching and displaying a remote image is switched off, independent of the web-search and URL-ingest flags. | **DESIGN-INTENT** | `services/assistant_orchestrator/config/default.toml:196` (`[knowledge].images_enabled = false`). | No dedicated go-live runbook exists for this ceremony either. Do not confuse with `[image_generation].enabled = true` (a different, already-live, purely local capability with no egress component — the two flags share the word "image" and are easy to conflate in a citation). |
| 8 | A response from the live web-search scope is capped in byte size and JSON-nesting depth, as a check independent of the wire-level cap. | **LIVE**, no disable flag | `default.toml:227-231` (`max_response_bytes = 2097152`, `max_parse_depth = 12`). Config's own comment: *"a SECOND, INDEPENDENT lock DOWNSTREAM of the egress door's 8 MiB on-the-wire byte cap."* | No runbook documents this lock at all — its only documentation is the config comment itself. |
| 9 | Every outbound call in a turn additionally requires a one-time human-presence check (Windows Hello); there is no unattended egress. | **LIVE**, no disable flag (ADR-023 Am.4) | `services/assistant_orchestrator/src/egress_envelope.py:93` (`EgressEnvelopeManager`), `:149-202` (`gate`). Wired: `entrypoint.py:1121,6793`. Block-test: `test_egress_envelope.py:78,92`. Off-test: `test_egress_envelope.py:44` (no `begin_turn` call → deny). | **EVERY outbound query raises its own Hello touch** (`searches_per_fingerprint = 1`, #1594, 2026-09-19) — measured through the real tool loop: three queries in a turn produce three prompts and three chat disclosures; identical repeated queries are NOT deduplicated, within a turn or across turns. **SUPERSEDED, kept because the reasoning matters:** this row previously read *"One Hello touch covers up to three searches in the same turn (`default.toml:250`, `searches_per_fingerprint = 3`); only the first is the one the operator actually approved — the second and third are disclosed in chat, not re-approved … 'consented' covers a window, not each individual call."* That was an accurate description of a sound 2026-07-02 LA decision (the tool loop caps a turn at `_TOOL_LOOP_MAX = 3`, so N=3 meant at most one prompt per turn). It was retired because chat disclosure is PASSIVE and the fingerprint is the AFFIRMATIVE act. Raising N again is a posture loosening and is the LA's call; `test_websearch_golive_wiring.py` fails if the shipped value changes. **No line number is cited for the value on purpose** — the citation above was correct until the commit that changed the value added comment lines above it, which is how a line citation fails. |
| 10 | A separate, general escalation-consent mechanism blocks any of seven other rule classes (cert renewal, cross-agent ownership, infra config writes, large writes, unverified code, crypto material, cross-agent paths) pending human approval. | **LIVE**, fail-closed by construction | `shared/security/escalation_consent.py`. Module docstring: *"no verifier configured → DENIED... any exception/timeout/None-result → DENIED."* | No runbook documents this control; only the ADR (ADR-024 §2.5) and the code itself. Distinct from claim 9 — this is the general PA `ESCALATE` consumer, not the egress-specific Hello envelope. |
| 11 | A process-wide guard intercepts every low-level network-socket call; once armed, only loopback and the one virtual-machine channel can be reached. | **LIVE**, armed unconditionally at process start | `shared/security/egress_guard.py`, `arm()` (`:1064`), `_check_connect()` (`:560`). Armed at `launcher/__main__.py:2488`. Block-test: `test_egress_sandbox_proving.py::test_offlist_non_loopback_connect_denied_and_auto_trips:243` (a real, non-loopback OS-level connection attempt, not a mock). Off-test: same file, `TestSandboxMechanism.test_same_host_round_trip_works_disarmed:596` — the identical connection **succeeds** once the guard is disarmed. This is the one control in this register with a textbook disarm-and-compare proof. | Named in its own authoring ADR (ADR-020): *"a Python-interpreter-level control... not a sandbox against a determined in-process adversary that re-imports `_socket` directly or issues raw OS syscalls."* An OS-level outbound firewall rule is named as complementary defense-in-depth, not yet built, no ticket number. |
| 12 | ~~Every outbound payload to an allowlisted external destination is scanned for secrets and personal data before it leaves the host, and blocked on detection.~~ **CORRECTED 2026-09-18 (#1592): the screen is a control against PLAINTEXT-socket exfiltration. It is never invoked for HTTPS, and every production egress path is HTTPS.** | **LIVE for the traffic it can see, and that traffic is not produced by the runtime.** Measured: 0 screener calls on a real TLS request; the planted secret left the process with the real screen wired exactly as production wires it. | `shared/security/exfil_screen.py`, `screen()` (`:226`), wired via `wire_into_egress_guard()` at `launcher/__main__.py:2480`. Block-tests: `test_egress_screen.py:81-114` (secrets, PII), `test_egress_screen_wiring.py` (real wiring, non-mocked send). Fail-closed-on-error: `test_egress_screen.py:128`. **Off-test (#1580):** `test_egress_screen_wiring.py::TestTheScreenIsTestedOff` — the identical planted secret on the identical external-tagged socket DELIVERS with no screener registered and is BLOCKED with one, holding the destination scoping fixed and varying only the registration. **Tagging locks (#1580 review):** `TestTheExternalTagIsEarnedNotAssumed` covers the decision and the `connect()` wiring separately, unconditionally — previously only `test_egress_sandbox_proving.py` held the tagger, and its module-level `skipif` disables it on a loopback-only box. | **Two fail-opens were found by the #1580 review and FIXED in the same commit; both had delivered a planted secret with no screen, no trip and no log.** (a) `_as_payload_bytes` recognised only `bytes`/`bytearray`/`memoryview` and the caller SKIPPED screening for anything else, so `sendall(array.array("B", secret))` left the host — the buffer is now normalised through `memoryview(...).cast("B")` and an unmaterialisable payload trips instead of passing. (b) `socket.dup()` of a connected, external-tagged socket returned an untagged socket on the same connection — `dup()` now carries the tag. Locked by `TestEveryBufferShapeIsScreened` and `TestADuplicatedSocketKeepsItsTag`, each mutation-killed. **THE CONTROL DOES NOT REACH REAL EGRESS (#1592, measured 2026-09-18 with positive controls).** `ssl.SSLSocket._create` (CPython `ssl.py:1039-1041`) constructs a NEW object from `fileno=sock.fileno()` and then calls `sock.detach()`. That object inherits from the real `socket.socket` captured at `ssl` import, so it carries neither `_GuardedSocket.sendall` nor the external-screen tag. The tag IS set correctly at connect — observed `true` at the moment of the wrap — and the wrap discards it. `guarded_fetch` refuses any non-HTTPS scheme (`_ALLOWED_SCHEME = "https"`, `guarded_fetch.py:152`), so there is no plaintext egress path in the runtime at all. Five arms against a self-signed loopback listener: raw `sendall` on a tagged guarded socket → 1 screener call, secret seen; `httpx` over plain HTTP → 2 calls, secret seen; `httpx` over real TLS → **0 calls, secret delivered**; the same TLS request with the real `exfil_screen.screen` wired as production wires it → nothing tripped, secret delivered; real screen over plain HTTP → kill-switch tripped, secret blocked. The three plaintext arms are the positive controls that make the zero a finding rather than a broken harness. **What this control positively is:** a live, fail-closed defence against plaintext-socket exfiltration by in-process Python code reaching an allowlisted external endpoint — a real mechanism with no production caller for the traffic that actually leaves this machine. **Standing limit, unchanged:** this is a Python-interpreter-level screen (ADR-020's own words), not a defence against code that re-imports `_socket` or issues raw syscalls. |
| 13 | Exactly one file in the entire runtime is permitted to import the network-fetching library (`httpx`); an automated scan enforces this, not convention. | **LIVE**, structural | `tests/security/test_no_external_egress.py`. `_EGRESS_DOOR_EXEMPTION` is the one-file carve-out; `test_runtime_imports_no_external_network_library` is the gate's own assertion and `test_exactly_one_runtime_module_imports_a_network_client` asserts the importer set equals exactly that one file. Both route through the shared `_unexempted_violations` / `_network_client_importers` collectors, so the off-test drives the SAME code the gate runs — cited by NAME, not line number, because the previous line citations were invalidated by the commit that wrote them. | **Off-test (#1585):** `TestTheScanIsTestedOff` plants a real second `httpx` importer in a synthetic tree and requires the scan to FAIL and NAME it, with the same tree minus the plant as the control — one condition varied. Synthetic rather than real, because proving the control fires must not require committing an `httpx` import to the runtime. **The roots were also wrong, and that was the larger half.** `_RUNTIME_ROOTS` was nine hand-listed directories, which is a list of what to LOOK AT — a blocklist of everything unlisted. It missed `services/ui_shell/src` (7 shipped runtime modules) and `services/voice/src` (2), and any NEW service would have been invisible to it from the day it was created, silently, with the suite still green. It is now the three runtime trees themselves (`services`, `shared`, `launcher`) with a two-name exclusion set, so a new service is covered the moment it exists: **220** files scanned before, **240** after — 20 newly covered, none lost, one importer in both runs: the sanctioned door. (An earlier version of this row said "231 measured". It was 240 minus the nine ui_shell/voice modules, i.e. arithmetic presented as a measurement, and it undercounted — the eleven `services/*/__init__.py` package markers were invisible to the old list too. The widening is larger than first claimed.) Both exclusion rules carry their own plant, because the first fixture put the dev-tier file where BOTH rules covered it and a mutant deleting the directory rule outright survived. **Stated limitations, which the first version of this row omitted entirely:** (a) the scan is STATIC and AST-based, so it catches every import form a developer plausibly writes — `import x`, `import x as y`, `from x import y`, function-local, class-body, `try/except ImportError`, `TYPE_CHECKING`-guarded, all verified — but NOT `importlib.import_module("httpx")`, `__import__`, `exec`, or a `getattr` lookup, which are genuinely dynamic; (b) the single-door property is enforced only WITHIN `services/`, `shared/` and `launcher/`, and one sanctioned runtime module reaches `urllib.request` by delegating into `tools/` (`shared/fleet/vikunja_bridge.py:168-172`), argued in ADR-039 §222-228 and pinned by `test_dependency_truth.py` — an AST sweep of all 240 scanned files found exactly one such delegation, and it is that one. |
| 14 | The two weight sets that can directly produce a security verdict or a generated image (the resident 14-billion-parameter model and the two Stable-Diffusion image models) are cryptographically signed, and the signature is checked before every load and at every boot. | **LIVE** | Full detail: [weight-integrity.md](weight-integrity.md) §2–4. `require_signed_manifest = true` in both the Policy Agent and Assistant Orchestrator configs. Block/off-tests: `test_manifest_signing_mechanism.py:265` (tampered → refuse), `:94` (flag off → same artifact accepted with a mandatory warning — a genuine two-state proof on the same file). | See claim 15. |
| 15 | (Limitation, not a fresh claim) Signing coverage is not universal across BlarAI's models, and the pre-ceremony sanity check is weaker than it looks. | **PARTIAL, by design** | [weight-integrity.md](weight-integrity.md) §4, §6. | Three models (speculative-decode draft, pruned draft, fallback) are hash-checked but **not signed**; four (embeddings, speech-to-text, text-to-speech, vision-language) carry **no manifest at all**. Separately, ticket **#943**: `shared/security/ceremony_preflight.py` checks that a `.sig` file *exists*, not that it *verifies* — the real cryptographic check happens later, at boot, but the preflight's "OK" reads stronger than it is. |
| 16 | Every internal service-to-service connection is mutually authenticated with a certificate minted fresh at boot and discarded when the process exits — nothing persists to leak, nothing to rotate manually. | **LIVE** | Full detail: [credential-lifecycle.md](credential-lifecycle.md) §3. `shared/security/cert_provisioning.py::provision_per_boot_certs`. Fail-closed discipline: §3.4 (a provisioning failure aborts startup before any service is constructed). | 24-hour nominal lifetime, no revocation or epoch-rotation mechanism exists (ADR-026 §5.3, ticket **#105**, unbuilt) — accepted as low-urgency because the next boot's fresh mint already supersedes a compromised credential. |
| 17 | (Limitation, not a fresh claim) The per-boot certificates prove freshness but not that the boot image itself is untampered. | **DEFERRED** | [credential-lifecycle.md](credential-lifecycle.md) §9.1 ("FUT-02"). | *"The per-boot certs deliver freshness... but **not** issuer attestation — the issuer name is a fixed constant regardless of image integrity."* Deferred pending measured-boot work that was separately declined in scope (see claim 20's neighbor, ADR-028). |
| 18 | Session and knowledge data are encrypted from creation; the encryption key is protected by the TPM with an offline paper backup; there is no plaintext fallback if both are unavailable. | **LIVE**, executed | Full detail: [credential-lifecycle.md](credential-lifecycle.md) §6. `docs/runbooks/at_rest_encryption_ceremony.md` banner: *"EXECUTED — Verified 2026-07-19."* Fail-closed: no code path in `build_session_store()` returns an unencrypted store in production. Block-test: `test_session_store_encryption.py::TestRawFileNoCleartext.test_turn_content_is_not_plaintext_on_disk:134` (reads the raw file bytes directly). | The 64-character offline recovery key is **never digitized** — lose it and the chip dies, and the data is unrecoverable by design, not by omission. |
| 19 | (Limitation, not a fresh claim) The decryption key and decrypted data necessarily exist in ordinary process memory while BlarAI runs. | **DEFERRED, named honestly** | ADR-025 "Limits (on the record)"; `shared/security/dek_envelope.py:264-267`. | *"out of scope for that model by design, not dismissed"* — tracked as ticket **#611**, revisited when the threat model extends past a single local operator (**#556**). A companion honest note in `provision_dek_keystore.py:358-365`: Python strings/bytes are immutable, so true in-memory zeroization of a secret is not achievable in this language. |
| 20 | Any component doing guest-side (isolated) work runs inside one Hyper-V virtual machine with no network adapter, reachable only over a virtual socket — hostile input parsed there never touches the host directly. | **LIVE**, structural | ADR-007. `docs/runbooks/vm_lifecycle.md` §3 (`AutomaticStartAction = Nothing`, set 2026-06-10 — a leaked-running VM cannot silently resurrect at host boot), §5 (Dynamic Memory 512MB–2GB, since #661), §6 (`AutomaticCheckpointsEnabled = False`, since #661 — prevents an accidental checkpoint-revert from silently undoing a guest re-provision). | §5's memory-growth ceiling was never exercised in practice — measured demand never even reached the 512MB floor, so the 2GB ceiling's protective value rests on an assumed hot-add path, not a measured one. |
| 21 | Content retrieved from outside the conversation (documents, search results) is wrapped in reserved delimiter tags and a fresh, unguessable per-load marker, so the model is told structurally which text is data versus instruction. | **LIVE** | Full detail: [context-spotlighting.md](context-spotlighting.md) §2, §10. Delimiters pinned at `context_manager.py:33-36`. Forged-marker neutralization tested: `test_context_manager.py::TestDatamarking`. | Datamarking raises the signal-to-noise ratio; it does not make the model immune to ignoring the instruction. The deterministic guarantee against a bad *action* (not bad *words*) is claim 22, a separate layer. |
| 22 | When UNTRUSTED content enters a conversation, non-SAFE tool calls are refused for the rest of that session unless the user explicitly types an override — enforced outside the model, so it holds even if the model is fully fooled. **Three carve-outs, each named below.** | **LIVE** (ADR-013, amended 2026-05-22) | Full detail: [context-spotlighting.md](context-spotlighting.md) §11. `entrypoint.py` tool-call loop, **SIX**-condition gate (the row said three until 2026-09-20; ADR-023 Am.1/#593 added the tier condition and Am.4/#723 added rungs 1 and 3). Block-test: `test_tools.py::TestToolCallLoop::test_tool_call_refused_when_document_in_context` (a real `PROMPT_REQUEST` carrying documents and an injection-style payload). Eval mirror, current and stating all six: `evals/suites/governance.py`. Row lock: `tests/security/test_claim_register_row22_layer3_gate.py`. | **CORRECTED 2026-09-20 (#1595). The previous wording overstated this control in four ways, all in the reassuring direction**, and is kept here because the wrong version is the useful one: *"When any document is loaded into a conversation, every tool call is refused for the rest of that conversation … Scope is per-turn only that the document is present."* (1) **Not documents — UNTRUSTED PROVENANCE.** The trigger is `has_untrusted_content`, which is false for a `TRUSTED_LOCAL` document, so loading a document the operator attached does NOT lock anything. It is true for web results, knowledge recall and pasted external text. (2) **Not every tool call.** SAFE-tier tools are never locked; `search_knowledge` is lock-EXEMPT by tool (Am.4 rung 1, bounded danger); and **egress tools — today `web_search` — are exempt by design** (Am.4 rung 3), because their own untrusted results would otherwise lock the next search, and because the refusal text itself was poisoning the chat (#726). A GUARDED tool is also unlocked when the session has trusted documents for tools. (3) **Not per-turn — per SESSION.** Grounded provenance lives on the session and is cleared only by an explicit `/unload` or by a fresh document attachment on a later turn (`clear_grounded_context`, one production caller in `entrypoint.py`). Nothing clears it at turn end. (4) The `/trust` behaviour described is unchanged and still accurate. **Why it matters beyond wording:** the exemption in (2) is exactly what makes a provenance-based constraint on outbound search a re-litigation rather than an addition — see #1595. |
| 23 | Every model response is checked at six separate stages before the user sees it (token budget, PII/secrets, delimiter echo, tool-call allowlist, retrieval-leakage similarity, aggregate gate); any single failure replaces the whole response with one fixed refusal message. | **LIVE** | Full detail: [pgov-validation.md](pgov-validation.md). Six-stage dispatch: `pgov.py:537-601`. Leakage threshold 0.85 cosine similarity (`shared/constants.py:218`). Fail-closed on every internal error path (`pgov.py:522-534`, `:412-416`). | No per-violation disclosure to the operator — deliberate information-hiding, so triage requires enabling debug logging. Audit-trail retention for denied output is deferred (referenced as GOV-12 in that doc, not yet authored). |
| 24 | A single conversational turn is hard-capped at 4096 generated tokens and **3** chained tool calls; nothing in the request can relax either cap. | **LIVE** | Full detail: [circuit-breaker.md](circuit-breaker.md). **Both caps are enforced, and neither is enforced where this row used to say.** TOKENS: `MAX_OUTPUT_TOKENS = 4096` is the `max_new_tokens` default in `services/assistant_orchestrator/src/gpu_inference.py`. DEPTH: `MAX_TOOL_CALL_DEPTH = 3` bounds the AO tool loop in `entrypoint.py` — `for _tool_iter in range(_TOOL_LOOP_MAX)`, where `_TOOL_LOOP_MAX` now READS that constant. Row lock: `tests/security/test_claim_register_row24_tool_call_cap.py`. | **CORRECTED 2026-09-20 (#1596), and the correction is larger than a number.** The superseded row, kept because the wrong version is the useful one: *"hard-capped at 4096 generated tokens and 5 chained tool calls … `MAX_TOOL_CALL_DEPTH = 5` (`shared/constants.py:135,138`). Breaker-evaluation errors themselves trip the breaker."* **(1) The number was wrong**: the effective bound is 3, and had been for as long as the loop existed. **(2) The cited mechanism was DEAD.** `CircuitBreaker` — both its breakers — was imported by nothing but its own test; its only in-source construction was inside a docstring; `record_tool_call` was called by nothing. The row said LIVE, and the effect it claimed was true only because a different, unregistered literal happened to enforce it. **The row would have read identically if nothing bounded the loop at all.** **(3) So "breaker-evaluation errors trip the breaker" described a fail-closed path that never executed.** The class is DELETED rather than wired (wiring it would have added a second mechanism for a limit already enforced, which is the drift this fixes), `MAX_TOOL_CALL_DEPTH` now says 3 and the loop reads it, and the row is locked to the code. UNCHANGED and still accurate: no runtime override surface exists at all — deliberate, since an OWASP LLM04 mitigation a request can disable is not a mitigation. No aggregated trip-rate dashboard exists; incident response relies on log greps. |
| 25 | A cryptographic-receipt adjudication pipeline exists in the codebase — a 5-stage rule engine, a CAR schema, a JWT-signed `DecisionArtifact` with nonce/epoch replay protection — fully built and tested. | **DESIGN-INTENT, not the live boundary** | `services/policy_agent/src/rule_engine.py::run_rule_engine`, called from `adjudicator.py:328` (served over vsock by the Policy Agent's own listener) — the production path. It is **also** called from `evals/suites/pa_classification.py`, `tests/integration/test_p110_end_to_end.py`, `tests/pa_quality_benchmark/harness.py`, and `phase2_gates/scripts/run_p5_feasibility_002.py` — none of them a live request path; all are evaluation, test, and feasibility tooling. No production caller outside `services/policy_agent/` exists. | **This is not claim 1.** Per ADR-041 (2026-07-15) and [credential-lifecycle.md](credential-lifecycle.md) §9.2: *"no live code sends a Canonical Action to the PA over vsock, no JWT is minted for a real request, and no destination validates a receipt... slated for removal as dead code (#910)."* [rule-engine.md](rule-engine.md) and [ipc-protocol.md](ipc-protocol.md) document this pipeline in full technical depth without that caveat — both now carry a short `## Status` note added in the same change as this register, pointing here and at ADR-041. A reader who opens either doc alone, without this register, would reasonably conclude the JWT pipeline is the live adjudication boundary; it is not. |
| 26 | The autonomous coordinator that helps triage BlarAI's own project work has no write access to anything that governs BlarAI itself — its own code, configuration, security policy, or model weights — enforced structurally, and everything it produces is advisory only. | **PARTIALLY LIVE** | ADR-039 (seven structural controls). `[coordinator].enabled = true` since 2026-07-15 (#843/#878) grants **read-only** status access only, per the config's own comment. Heartbeat live in shadow mode (`shadow_mode = true`) — output stays in an encrypted internal journal, not surfaced to the operator. | **The ADR's own claim discipline caps this** (§2.17, quoted): *"the self-governance boundary is safe under expert operation... explicitly not yet claimed safe to hand to a non-technical operator."* Control 7 (cryptographic verification of the coordinator's own policy file at boot) **is built and tested** — confirmed directly against code (`shared/coordinator/policy.py`, `boot_canary.py`, block-test `test_coordinator_boot_canary.py::TestCanaryFailsLoud::test_tampered_policy_refuses_start`) — but ships **disabled** (`require_signed_policy = false`, `default.toml:1147`; off-path: `policy.py:183-186`, proceeds on unsigned defaults with a warning). The ADR's own body text states plainly, at line 742, *"Control 7 is not yet built"* — and returns to the same point, in less direct phrasing ("until control 7 ships," "ahead of control 7 shipping"), at several other points in the document; that framing is now stale relative to the code. `docs/DECISION_REGISTER.md`'s Amendment-2 row is the accurate summary: *"the seven controls are now IMPLEMENTED (DORMANT, `[coordinator]` flags)."* This discrepancy is not yet corrected in ADR-039 itself (out of this register's approved scope; see Open Questions). |
| 27 | (Undocumented elsewhere) When an escalated action is approved by a human, the approval is bound to the action's name and category. | **Gap A — ticketed (#1541), design-only** | `docs/research/cava-vs-microsoft-agent-framework-vs-blarai-trust-spine-2026-09-16.md`; the field's state on this question is in `docs/research/runtime-action-governance-landscape-2026-09-16.md` ("BlarAI against the field", question 2). | The approval is **not** bound to the specific arguments that end up executing — the CAR's own `canonical_hash()` (`car.py:112-130`) is defined but never computed on the live path (its only caller is the vestigial hybrid adjudicator, `adjudicator.py:493`), and nothing downstream checks the executing action's hash against what the human actually saw. A design for the fix exists (`docs/research/acs-vocabulary-adoption-design-2026-09-16.md`, binding the approval to the CAR hash); ticketed as #1541, no code written. |
| 28 | (Undocumented elsewhere) Neither claim-1 checkpoint (tool dispatch, egress door) writes to BlarAI's tamper-evident, signed audit chain. | **Gap B — ticketed (#1542), design-only** | `docs/research/cava-vs-microsoft-agent-framework-vs-blarai-trust-spine-2026-09-16.md`; `shared/security/audit_log.py` (the chain exists and is wired to ingest and to claim 25's vestigial JWT path); the field's state on this question is in `docs/research/runtime-action-governance-landscape-2026-09-16.md` ("BlarAI against the field", question 3). | Both live doors log to the ordinary application logger only. A denial or an escalation today produces no forensically durable record — only a log line, at whatever retention the launcher log happens to have. Ticketed as #1542. |
| 29 | (Undocumented elsewhere) The signed audit chain's own integrity check, `AuditLog.verify()`, is never invoked on the live path: a chain is opened by restoring its head from the last record on disk, with no hash recomputed and no signature checked. | **Gap D — CLOSED in code (#1543, sprint 19)** | `shared/security/audit_log.py`: `verify()` (`:1427`) walks the chain and checks every record signature; `__init__` (`:599-660`) calls only `_load_segment_index` and `_load_existing`; `_load_existing` (`:689-729`) restores `_prev_hash` / `_seq` from the last record. Callers of `verify()` at `12e3b651`: `shared/tests/test_audit_log.py`, `shared/tests/test_tpm_record_signer.py`, `tests/integration/test_security_cascade.py`, `services/policy_agent/tests/test_entrypoint.py` — test files only; neither production constructor (`services/policy_agent/src/entrypoint.py:987`, `services/assistant_orchestrator/src/entrypoint.py:5703`) verifies. Found 2026-09-16 while scoring BlarAI's row for `docs/research/runtime-action-governance-landscape-2026-09-16.md` ([PROPOSED] item 12). | The chain is tamper-**evident** (a later `verify()` would detect an edit) but not tamper-**refusing**: no boot path, health check or ceremony invokes `verify()`, so a tampered active segment would be extended, not refused. **BUILT 2026-09-17 (#1543).** `verify()` now runs inside BOTH production constructors (`services/policy_agent/src/entrypoint.py::_build_audit_log`, `services/assistant_orchestrator/src/entrypoint.py::_build_ingest_audit_log`) and the chain is REFUSED rather than extended: the PA raises `AuditProvisioningError` and refuses to start, the ingest sink raises so its caller disables the knowledge feature loudly. The boot budget is registered in `shared/timeout_registry.py` and coupled by test to a reduced production active-segment ceiling (ADR-029 Amendment 2026-09-17). Locks: `tests/security/test_audit_verify_on_load.py` (tampered active segment refused, tampered sealed segment refused, both baselines construct, a toggle-test, and a `dev_mode=False` arm through the real constructor) and `tests/security/test_audit_verify_budget.py`. **The production arm exists because the first version of the fix did not have it:** the PA's production branch returned before the verify was reached, so the control ran in dev and nowhere in production, and every lock passed because none entered that branch. Independent adversarial review caught it pre-merge; the constructor now has one construction site and one exit so a branch cannot skip the check by returning early. Design borrowed from Dapr 1.18's verify-on-load pattern, read from source at `dapr/dapr@d31c4a642b60a18da8fc24cd93c910b0b2fafc43`. |

### Notes on rows that are limitations rather than fresh claims (15, 17, 19)

Three rows in the table above do not name a new mechanism — they name the
honest boundary of the mechanism named in the row above them (14→15, 16→17,
18→19). They are numbered as their own rows, not folded into the "Stated
limitation" cell of the claim they qualify, because each is independently
substantial enough to be found on its own and independently citable — folding
them in would have made those two cells the longest in the table and the
easiest to skim past.

## Recovery — how a reader re-verifies a claim here

This register is a snapshot; the underlying controls move faster than any
document about them. To re-verify a specific row:

1. **Read the cited source file at the cited symbol**, not just the line
   number — line numbers drift, symbol names are the durable anchor (per
   `STYLE.md` §Source Anchoring).
2. **Re-run the cited test file.** Every LIVE claim above names at least a
   block-test; most name an off-test too. A claim whose cited test no longer
   exists, or no longer passes, is the clearest signal this register itself
   has gone stale.
3. **For a config-gated claim (5, 6, 7, 26), read the live `default.toml`
   directly — never trust this register's characterization of a flag's
   current value.** `CLAUDE.md` is explicit that LIVE vs DORMANT is read from
   config, never from memory or from a docstring; that rule applies to this
   document as much as to any other.
4. **For ticket status** (#977, #910, #943, #611, #105, #556, Gap A #1541,
   Gap B #1542, Gap D #1543),
   confirm against Vikunja directly — every reference in this register is
   sourced to what is written on disk, not to a live ticket-tracker read, and
   a ticket referenced here as OPEN may have closed since.

There is no other recovery path — this document does not gate or block
anything at runtime; getting a row wrong here does not change what BlarAI
does, only what a reader believes about it. That asymmetry is exactly why
every claim above is source-anchored rather than asserted.

## Open Questions / Deferred Items

- **ADR-039's body text vs. its own control-7 code (claim 26).** The ADR
  states nine times that control 7 "is not yet built." Direct code
  inspection for this register found it built, tested, and wired into the
  boot canary — just shipped with its strictest setting off. The ADR itself
  was not edited as part of this change (out of the approved scope for this
  register, which was to build the claim table and two small, pre-approved
  cross-reference fixes — not to sweep every ADR this table touches). A
  follow-up to correct ADR-039's body text, or to add a dated amendment note
  the way ADR-032's Amendment 1 corrected its own "four independent locks"
  claim, is the natural next step.
- **The last-wins vs. first-wins wording (claim 2).** `CLAUDE.md`'s `<stack>`
  section and this directory's own runbook both say the door's adjudicator
  slot is "first-wins" — language that traces back to the same function's own
  docstring, which asserts "first-wins" in one sentence and then describes
  replace semantics sixteen lines later. The function body mechanically
  implements last-write-wins. Both describe the same current reality today
  (exactly one production caller), so this is a wording precision issue, not
  a live gap — but the wording is repeated in a standing-instructions file
  that gets loaded into every session, and in its own source docstring, so a
  future reader has better than even odds of picking the sentence that
  describes the mechanism backwards.
- **Gap A and Gap B (claims 27–28) are ticketed (#1541, #1542), design-only.**
  When this register was first written they had no ticket and were sourced
  only to a same-day research document; the tickets were opened the same
  evening and the rows now cite them. The remaining open question is the
  order of that work against `docs/ROADMAP.md`, which is the operator's.
- **Whether this register itself should be added to `docs/governance/README.md`'s
  inventory.** It was, in the same change (see the two adjacent fixes noted
  in this ticket's Vikunja description) — flagged here only so a future
  reader auditing README.md's staleness (the same defect this register's own
  authoring found twice already) checks this entry specifically.

## Verified against

- `services/policy_agent/src/gpu_inference.py:349-578` (`DeterministicPolicyChecker`, `_EGRESS_ALLOWLIST` at `:403`).
- `shared/security/guarded_fetch.py:51-59` (DNS-rebinding residual), `:132` (httpx import), `:372-434` (adjudicator slot), `:615-661` (`_adjudicate`), `:1322-1407` (`fetch_external`).
- `services/assistant_orchestrator/src/entrypoint.py:302-372` (`_adjudicate_tool_dispatch`), `:1121,6793` (egress envelope wiring), `:6865` (tool-dispatch call site).
- `services/assistant_orchestrator/src/egress_envelope.py:93-274`.
- `shared/security/egress_guard.py:429,560,625,1064,1093,1119`.
- `shared/security/exfil_screen.py:139-167,226,303,351`.
- `shared/security/audit_log.py:599-660` (`__init__`), `:689-729` (`_load_existing`), `:1427` (`verify`), read 2026-09-16 at `12e3b651` for row 29.
- `tests/security/test_no_external_egress.py:47-195`.
- `tests/security/test_guarded_fetch.py:148-296`.
- `services/ui_gateway/tests/test_url_adjudicator.py` (`TestGoLiveRegistration`, `TestDeterministicUrlAdjudicate`).
- `services/assistant_orchestrator/tests/test_tools.py:1375-2061`.
- `services/assistant_orchestrator/tests/test_egress_envelope.py:44-274`.
- `tests/security/test_egress_screen.py:69-267`, `test_egress_screen_wiring.py:187-269`, `test_egress_sandbox_proving.py:243-617`.
- `shared/tests/test_manifest_signing_mechanism.py:94-290`.
- `shared/coordinator/policy.py:170-187`, `boot_canary.py:178-184`, `config.py:195-200,320-323`, `shared/tests/test_coordinator_boot_canary.py:113-123`, `shared/tests/test_coordinator_config.py:32-83`.
- `services/assistant_orchestrator/config/default.toml:196,214,227-231,250,1145-1150`; `launcher/config/default.toml:29,97-111`.
- `docs/runbooks/web_search_go_live.md` (Known gap: #977 section, "Out of scope" section, activation banner).
- `docs/runbooks/manifest_signing_ceremony.md`, `docs/runbooks/at_rest_encryption_ceremony.md`, `docs/runbooks/vm_lifecycle.md` (banners and dated sections cited per-claim above).
- `docs/adrs/ADR-020-Code-Enforced-Egress-Kill-Switch.md:108-119`.
- `docs/adrs/ADR-025-At-Rest-Encryption-DEK-Envelope.md:234-249`.
- `docs/adrs/ADR-039-Coordinator-Self-Governance-Boundary.md` (§2.17; line 742's direct "Control 7 is not yet built" statement, echoed less directly at several other points in the document).
- `docs/adrs/ADR-041-Host-Mode-Action-Authorization-Boundary.md`.
- `docs/governance/weight-integrity.md`, `docs/governance/credential-lifecycle.md`, `docs/governance/context-spotlighting.md`, `docs/governance/pgov-validation.md`, `docs/governance/circuit-breaker.md` (read in full for this register).
- `docs/research/cava-vs-microsoft-agent-framework-vs-blarai-trust-spine-2026-09-16.md` (Gap A, Gap B).
- `tests/security/test_doctrine_freshness.py:33-39` (the #977 composite-claim honest limit).
- Vikunja **#1537** (`identifier` #471, closed 2026-09-16) — the research set claims 27–28 trace to. Vikunja **#1539** (`identifier` #473) — this register's own tracking ticket.
