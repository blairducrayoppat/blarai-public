# ADR-030 — UC-003 Cleaner v1: Guest-Homed Ingest Pipeline with Operator Approval

**Status:** ACCEPTED 2026-06-10 (Lead-Architect-ratified at the #655 program comprehension gate);
**activation preconditions reconciled same day (LA verdict 2026-06-10 — see §8)**.
**BUILT BEHIND GLASS** — the fetch limb is DORMANT by **structural absence**: no fetch code exists
until Stage C writes it (stronger than the ADR-024 disabled-machinery precedent — there is no flag
to flip, because there is no limb to flip on). It activates only under the preconditions in §8 /
§Activation; the #598 §5.12 LA sign-off is **RECORDED** (GO, #598 comment 1026, 2026-06-10).
Everything downstream of the fetch (clean, preview, approve, store, retrieve) is live on paste/file
inputs from day one.
**Deciders:** Lead Architect (blarai); Orchestrator (facilitation).
**Builds on:** ADR-013 (document-reading defense-in-depth — the Layer-1/2 primitives the Cleaner's
sanitization stage reuses), ADR-023 (provenance-based trust — retrieved content is untrusted
regardless of approval), ADR-024 (the agentic web-search skill — the build-dormant precedent AND the
W4/W5 fetch/ingestion-defense seams this pipeline is structurally the successor of), ADR-027 +
**Amendment 1** (per-action egress adjudication for operator-pasted URLs — the egress posture this
pipeline's fetch limb runs under), roadmap §6 Decisions 3/4/6/7
(`docs/security/SECURITY_ROADMAP_air_gap_removal.md`).
**Relates to:** ADR-031 (UC-002 Substrate v2 — the knowledge bank this pipeline feeds), Vikunja #655
(program), **#577 comment 1029** (the cross-session `guarded_fetch` integration contract §3
consumes), #613 (the Cleaner re-home this ADR begins delivering), #598 (air-gap gate), #556
(network-facing capability set), #632 (AO→router wiring — stays parked).

## Context

USE-CASE-003 (the Cleaner) is the mandatory preprocessing gate for the Substrate: noise-stripping
first, adversarial sanitization second, fail-closed quarantine for anything that fails either stage
(`Use Cases_FINAL.md` §003). On 2026-06-06 the LA re-homed the Cleaner out of the air-gap campaign
entirely (#613, roadmap §6 Decision 4 amendments) with a ratified framing correction: the Cleaner is
**a data-quality feature first** — its primary purpose is knowledge-store normalization
(anti-"inference pollution") — and a security sanitizer second, because the deterministic
catastrophic-outcome defenses (ADR-013 datamarking, ADR-023 action-lock + provenance, PA egress
mediation, the exfil screen) do not depend on it.

This ADR records the v1 that begins that project. The MVP flow, LA-ratified 2026-06-10 (#655): the
operator pastes a news-article URL in chat → the URL is fetched through the single `guarded_fetch`
egress door and the HTML is parsed **in the Hyper-V guest** (the §3 composition; the fetch limb is
a Stage-C build — dormant today by structural absence, §8) → cleaned to article text + metadata →
previewed in chat → the operator
explicitly approves → the document is stored in the encrypted knowledge bank (ADR-031) → it is
retrievable in later turns. The whole pipeline is buildable and testable NOW: the established pattern
is build-behind-glass (ADR-024 merged the entire web-search skill "mocked and dormant behind the
armed egress guard"; the Tier-3 egress machinery itself was BUILT DORMANT) — only egress *activation*
is gated, not egress *construction*. For the Cleaner the dormancy is stronger still: the fetch limb
is not a disabled code path, it is **unwritten** until Stage C (§8) — absent code cannot be
mis-activated.

## Decision

### 1. Scope and ordering — data-normalizer first, sanitizer second

Cleaner v1's primary deliverable is **normalization for knowledge quality**: boilerplate-stripped
article text with title/byline/date metadata, so the decades-horizon knowledge bank stores signal,
not navigation chrome. Injection sanitization is built in the same pass (§5) but is explicitly
**Layer 1 of 3** — probabilistic, not load-bearing alone — per the #613 framing and roadmap Decision
4. This ordering is the LA's ratified correction of an earlier security-first mis-framing and is
binding on v1's quality bar: a Cleaner that strips injections but stores junk text has failed its
primary purpose.

### 2. The MVP flow — paste-URL ingest with operator approval

`/ingest <url>` → the fetch goes out through `guarded_fetch.fetch_external` (the single PA-gated
egress door, §3 — ADR-027 Amendment 1's INGEST_FETCH adjudication rides it; the fetch limb is
written at Stage C, dormant today by structural absence, §8) → guest-homed HTML parsing +
extraction → cleaned text crosses the
AF_HYPERV vsock boundary to the host → the cleaned document lands as a **pending** row in the
knowledge bank (ADR-031 L0 — content held, no chunks, no embeddings, not retrievable) → preview
rendered in chat → `/approve` chunks + embeds + makes it retrievable; `/reject` tombstones it. No
document reaches retrieval without the explicit approve. The approval is a chat-surface act, not a
Windows Hello prompt (rejected alternative, §Rejected).

**Ingest path scope (accepted residual, LA decision 2026-06-10):** local-file ingest is **KEPT** at
local-absolute-path scope — `/ingest <path>` accepts local absolute paths only, and **UNC paths are
refused** on both the raw operator input AND the resolved path (a local-looking path that resolves
to UNC is refused too). The residual — the gateway will read a local file the operator names — is
accepted as operator-initiated by construction, bounded by these controls: raw+resolved UNC
refusal, extension allowlist, strict UTF-8 decode, size cap, preview + human approval.

### 3. Placement — one host-side egress door; HTML parsing VM-homed from day one

**Integration contract (epic #577 comment 1029, cross-session, LA-relayed 2026-06-10 — supersedes
this ADR's drafted fetch-in-guest wording):** the URL fetch consumes
`shared/security/guarded_fetch.fetch_external(url, purpose, timeout_s)` — the **single
Policy-Agent-gated egress door** W4 ships, carrying SSRF/scheme validation, per-URL PA adjudication
with ESCALATE → Windows-Hello consent, a temporary allowlist widen with a guaranteed revoke, and a
body injection scan. The Cleaner builds **no network path of its own** and never calls
`egress_guard.allow_external_endpoint` directly — one door, shared with W4 `/search`.

The placement composition this yields: the **socket lives host-side inside `guarded_fetch`** (one
door), while the **parsing of the fetched hostile HTML remains guest-homed** per roadmap §6
Decision 3 (HYBRID topology, LA-ratified 2026-06-05) — hostile bytes are handed into the Hyper-V VM
for parsing + extraction and only cleaned text returns to the host, over the AF_HYPERV vsock
channel activated and verified in Sprint 17 (#615). Hostile web bytes are never *parsed* in a host
process. Web-ingest turns set the **untrusted-content turn state** (the content enters as
`UNTRUSTED_EXTERNAL`) and carry the **`<|WEB-{token}|>` datamark** — the same Layer-2 marking the
web-search path uses. Host-side handling is allowed ONLY for (a) operator-pasted
plaintext/markdown (the operator's own clipboard, not a hostile parser input), (b) the pipeline's
pure-text stages (normalization, injection-phrase scan, chunking, embedding — string processing on
already-extracted text), and (c) — a **named interim residual**, §4 — operator-consented LOCAL HTML
files, until the Stage-C guest parser lands.

This is deliberately the more expensive build order: a host-side v1 with a "move it to the VM later"
note would work sooner, but it would put an HTML parser processing hostile web bytes inside the same
process that holds the unsealed DEK and the GPU pipeline — and BUILD_JOURNAL lesson 73 (activating
long-dormant paths is a discovery exercise) says the migration would not be the one-liner the note
implies. The containment boundary is the point of Decision 3; building on the wrong side of it and
promising to move is the named anti-pattern.

### 3a. Considered alternative — NIC'd guest fetch-and-parse (rejected, 2026-06-11)

The §3 placement (host fetches, NIC-less guest parses) is an **inversion** of the originally-drafted
design, in which the guest held a network interface and performed the fetch itself (§8 records the
struck precondition). The rejected alternative — **a NIC'd guest that both fetches and parses, leaving
the host fully air-gapped** — is recorded here with its reasoning, because it is the intuitive design,
it was the first plan, and the governance record should carry the path not taken (LA review 2026-06-11,
closing the #658-item-7 precondition review).

**What the alternative buys:** the host never opens a socket; all network *and* all hostile parsing
live in one disposable VM (the Qubes `sys-net` shape). The appeal is genuine — "the air-gapped machine
stays air-gapped; the VM is the sacrificial network-facing layer."

**Why it was rejected:**
- *Egress control stops being centralized or provable.* BlarAI's mandate is one code-enforced,
  fail-closed, PA-mediated, kill-switchable door — statically provable as "exactly one module imports
  the HTTP client" (`test_no_external_egress`). A guest NIC is a **second egress path** that
  `egress_guard`, the kill-switch, the exfil screen, and PA adjudication do not govern; "one door"
  cannot be proven when one of the doors is a network adapter on a separate OS.
- *The prize for compromising the HTML parser is a network position, not data.* Neither design lets the
  guest hold secrets (no DEK, no GPU pipeline, no databases — verified by the guest's import set). A
  NIC-less guest compromise yields a sealed box that cannot phone home; a NIC'd guest compromise yields
  a live **beachhead** (arbitrary C2 / scanning, outside the kill-switch's reach). NIC-less denies the
  one thing the box could give an attacker who pops `libxml2`.
- *"No NIC" is structurally fail-closed; a locked-down guest NIC is a configuration that must be kept
  correct.* The launcher asserts zero NICs at VM start and refuses otherwise (`verify_vm_zero_nic`) —
  an absence that cannot be misconfigured, not a ruleset that must stay right.

**Accepted residual of the chosen design:** the host *does* open the fetch socket and receive
attacker-controlled bytes — but it runs a memory-managed HTTP client behind SSRF + allowlist + cap
guards, and it **never parses the response** (it streams, charset-decodes, and hands raw bytes to the
guest). The dangerous structured parsing — the historically CVE-prone surface — is exactly what §3
moves off the host. The rejected alternative would eliminate this residual, at the cost of the one-door
property and the beachhead risk above. The trade is judged in favor of provable, centralized egress for
this system's threat model and mandate.

### 4. Extraction — trafilatura, extraction-only, with a named regression lock

HTML→article extraction uses **trafilatura** (LA-approved 2026-06-10: +9 hash-pinned packages via the
`requirements/<feature>.txt` + `docs/research/` vetting-record pattern, the W2/Kagi precedent;
installation is Stage B, not this stage). It is approved for **extraction only**: `extract()` and the
metadata helpers over bytes the guest parser already holds (fetched host-side through the
`guarded_fetch` door, handed in over vsock — §3). Its fetch functions (`fetch_url` /
`fetch_response` / the `trafilatura.downloads` module) are **never** called — fetching belongs to
`guarded_fetch.fetch_external`, the single egress-guarded, PA-adjudicated, exfil-screened door (§3),
not to a library's convenience wrapper that would bypass every control.

**The regression lock (named, required at Stage B):** a static-scan test in `tests/security/`
(extending the `tests/security/test_no_external_egress.py` AST-scan pattern) that fails the standing
gate if any runtime module imports `trafilatura.downloads` or references its fetch functions. The
import-level scan already on the gate catches `requests`/`httpx`/`urllib.request`; this lock closes
the library-internal fetch hole specifically.

**lxml interim residual (named, accepted — LA verdict 2026-06-10):** Stage B host-parses
**operator-consented LOCAL HTML files** (`/ingest <path>` on the operator's own file, under the §2
path-scope controls) while the vetting record's #1 mitigation — guest-homed parsing
(`docs/research/trafilatura_supply_chain_vetting.md` §5.2) — is a **Stage-C deliverable**. This is
an accepted interim for operator-initiated file ingest given the hash-pinned artifacts and the
armed egress locks; hostile *web* bytes never get the interim, because the fetch path does not
exist until Stage C writes it (§8). **Stage C guest-homed parsing is the durable fix.**

### 5. Sanitization — ADR-013-pattern Layer 1, residual risk delegated by design

The Cleaner's adversarial-sanitization stage applies the ADR-013 primitives to ingested content at
the ingest boundary: deterministic forged-delimiter stripping plus the heuristic injection-phrase
scan (the `scan_for_injection` pattern, `services/ui_gateway/src/document_loader.py:522`).
**Residual risk is explicitly delegated to Layers 2/3** — per-load datamarking via
`ContextManager.add_grounded_context`, the ADR-023 action-lock on untrusted content, and PGOV output
validation — which fire on every retrieval of this content forever (ADR-031 L4). UC-003's own text
recognizes the Cleaner as Layer 1 of a mandatory three-layer defense; v1 does not claim more than
that. A heuristic scanner miss at ingest is a degraded-quality event, not a compromise, because the
stored content is never trusted (§ADR-023, BUILD_JOURNAL lesson 13).

### 6. Quarantine — conservative fail-closed, manual review

Every ingested document lands in the **pending** state (ADR-031 L0) and stays there until the
operator decides. There is no auto-approve path, no confidence threshold that skips review in v1, and
no silent ingest — "tunable, start conservative" per roadmap Decision 4. A document that fails
extraction or sanitization checks fails LOUDLY (a clear error in chat) rather than storing a
degraded result. REJECT retains the content as a tombstone (ADR-031 L5); retention/purge of
tombstones is a later lifecycle decision, deliberately deferred-but-named.

Terminology note: this **ingest quarantine** (untrusted content held pending operator review) is a
distinct concept from the ADR-025 §2.7 **decrypt-quarantine** (un-decryptable encrypted rows skipped
on bulk reads). Both exist in this pipeline; they are never conflated in code or docs.

### 7. UX — explicit commands, gateway-parsed; the router stays unwired

Ingest is driven by **explicit commands**: `/ingest <url>` (later: file path / paste), `/approve
<doc>`, `/reject <doc>`. They are parsed **gateway-side** (the `_parse_external_command` pattern,
`services/ui_gateway/src/transport.py`) so both surfaces — WinUI and TUI — get the feature from one
implementation, mirroring `/external`. This matches the deliberate explicit-command egress doctrine
already on the record ("the system reaches the network ONLY when the user explicitly invokes
/search" — `services/assistant_orchestrator/src/websearch/dispatch.py:10-14`): network actions are
never inferred from conversational text. The semantic router stays unwired; #632 stays parked — this
feature does not trigger the router-activation decision.

### 8. The dormant-fetch contract — dormancy is structural absence; what activation requires

*(Reconciled 2026-06-10, LA verdict — supersedes the originally-ratified three-item list, which
named a guest-NIC provisioning step and a `fetch_enabled` config flip. Neither survives: the NIC
precondition is struck and INVERTED below, and no `fetch_enabled` flag exists anywhere — see the
dormancy statement.)*

**Dormancy is the structural ABSENCE of fetch code, not a disabled code path and not a config
flag.** Stages A/B ship **no fetch limb at all** — there is no `fetch_enabled` switch to hunt for,
by design: code that does not exist cannot be mis-flipped on, which is strictly safer than the
ADR-024 disabled-machinery pattern. `/ingest <url>` returns a clear "fetch is dormant pending
activation" error because no fetcher exists to call. Activation therefore requires **WRITING the
fetch limb (Stage C)**, and all of the following:

1. **The #598 §5.12 LA sign-off — RECORDED.** The GO was recorded on **#598 comment 1026,
   2026-06-10** (a governance act, not a build). This precondition is satisfied.
2. **ADR-027 Amendment 1 in force, verified against the real W4 code.** The amendment was ratified
   against the #577 c.1029 *contract*; before the first live `INGEST_FETCH`, it is verified against
   the shipped `guarded_fetch` implementation (W4 shipped it — merged to main `8703dae`,
   2026-06-10).
3. **The Stage-C fetch limb is WRITTEN**, wired through `shared/security/guarded_fetch.fetch_external`
   — the single PA-gated egress door (§3). The Cleaner never grows a network path of its own.
4. **The zero-NIC guest invariant holds.** The guest remains **NIC-less**; the launcher asserts
   zero NICs on the VM at start and **fails closed if one appears** (assertion landed:
   `launcher/vm_manager.py` `verify_vm_zero_nic`, called at VM start). This INVERTS the originally-ratified "guest VM NIC
   provisioning" precondition (struck, LA decision 2026-06-10): that item was ratified under the
   old fetch-in-guest design; under the §3 one-door host-side composition, a guest NIC creates
   exactly the exposure the zero-NIC posture defends.

Until then: paste and local-file ingest work fully; ADR-027 Amendment 1 stays accepted-but-inactive.
The egress kill-switch, auto-trip, and exfil screen (`shared/security/egress_guard.py`,
`shared/security/exfil_screen.py`) apply to the `guarded_fetch` door exactly as ADR-027 rules 3/4
prescribe — unchanged by this ADR.

### 9. Size cap — the 16 KB document-loader cap is deliberately NOT inherited

The `/load` path caps text at 16 KB (`DOCUMENT_MAX_BYTES` / `EXTRACTED_TEXT_MAX_BYTES = 16_384`,
`document_loader.py:59-60`) because it is sized to the AO's per-turn context budget — that cap
conflates "ground this turn" with "store this document." Ingest stores documents for retrieval, not
for whole-document grounding, so it gets its own limit: `staging_max_bytes` (default **262,144** —
roomy for any news article, a hard stop against pathological pages), enforced at the staging-file
boundary (ADR-031 §6). Retrieval returns top-k chunks, never the whole document, so the context
budget is respected at read time, not write time.

### 10. Audit — every ingest decision is recorded

Every submit, approve, and reject is appended to a tamper-evident AO-side audit chain (the ADR-029
primitive; construction and posture specified in ADR-031 L3). The audit record carries labels and
identifiers only — `doc_uuid`, a source-hash prefix, the decision — never content. An ingest pipeline
is a governance-relevant act (external content entering a decades-horizon store on a human decision);
an unaudited approval is an unprovable approval.

## Rejected alternatives

- **Host-side-first placement** (hostile-HTML *parsing* on the host, VM move deferred) — rejected,
  §3: it builds on the wrong side of the Decision-3 containment boundary and turns a ratified
  architecture into a migration promise. (The fetch *socket* is host-side by design — inside the
  single `guarded_fetch` door, per the §3 integration contract; the rejected thing is host-side
  parsing of hostile *web* bytes. The §4 lxml interim — operator-consented local files only, until
  Stage C — is the named, bounded exception, not this rejected alternative.)
- **Static per-domain allowlist for article URLs** — rejected (decided in ADR-027 Amendment 1):
  arbitrary operator-pasted news URLs cannot be enumerated as "named endpoints, one vetted at a
  time"; roadmap Decision 6 anticipated exactly this — "adjudicate the *action* + screen the
  outbound, not allowlist the web."
- **Router-intent detection** ("ingest this" inferred from natural language) — rejected for v1:
  network actions stay explicit-command by doctrine (§7), and the AO→router wiring does not exist
  (#632 — a deliberate built-ahead, parked pending the first skill-dispatch handler decision).
- **justext / stdlib-only extraction** — rejected on quality: justext (+3 packages) does
  paragraph-level heuristics without trafilatura's metadata (title/byline/date) extraction;
  stdlib `html.parser` heuristics (+0) would hand-roll boilerplate removal badly. Extraction quality
  is what the knowledge bank stores for decades — the LA weighed the +9-package supply-chain surface
  against it and chose trafilatura (hash-pinned, vetted, extraction-only) on 2026-06-10.
- **Windows-Hello-gated approval** — rejected for the routine path: the approve/reject is a deliberate
  typed act in chat on content the operator just read; a biometric prompt adds friction, not
  assurance. Hello remains the verifier for PA ESCALATE verdicts and egress re-arm (#639/#649/#653),
  and the ApprovalVerifier seam stays available if a future ingest class warrants it.

## Consequences

- **Positive:** the knowledge bank gains a real ingestion front door with a human decision in the
  loop; hostile web bytes are never parsed on the host — the web path does not exist until Stage C,
  which lands the guest-homed parser (the §4 interim covers operator-consented local files only),
  and the only socket is the one shared `guarded_fetch` door (§3); every control that exists
  today (egress guard, PA adjudication, exfil screen, datamarking, action-lock, PGOV) wraps the new
  path with no weakening; the #598 gate's subject matter is not changed by this build — dormant
  machinery was already the presented posture (ADR-024 precedent).
- **Negative / accepted trade-offs:** the guest-homed build is slower to deliver than a host-side v1
  (two processes, a staging handoff, vsock framing — accepted for the containment boundary); the
  cleaned-article preview echoed in chat is PGOV-validated and persisted as a session turn like any
  assistant output (accepted — display is a turn; the knowledge-bank write is the separate,
  deliberate, audited act); trafilatura adds 9 packages of supply-chain surface (accepted with
  hash-pinning + the vetting record, Stage B).
- **Deliberately deferred (named):** PDF, MIME-email, and CSV/JSON format coverage (UC-003 names
  HTML, PDF, Markdown, plaintext, MIME email, CSV/JSON at launch — v1 is URL + paste + local HTML
  files under the §2 path-scope controls); the Mobile LAN Ingress half of UC-003 (roadmap Decision 7: ingress is
  a separate, later, even-more-gated decision); quarantine-confidence tuning (start conservative);
  the three-field Cleaner signature gate (deferred with the multi-VM transition — ADR-031 §8).

## Activation (not on acceptance)

Build now, behind glass — where "behind glass" means **the fetch limb is not written until Stage C**
(dormancy by structural absence, §8; no activation flag exists). The #598 §5.12 LA sign-off is
**RECORDED** (GO, #598 comment 1026, 2026-06-10); what remains is ADR-027 Amendment 1 in force —
including its verify-against-the-real-W4-code step — plus the Stage-C fetch limb written through
`guarded_fetch.fetch_external` and the zero-NIC guest invariant (launcher assertion, fail-closed).
ADR-027 Amendment 1 governs the path from the first live fetch. Everything else (paste ingest,
local-file ingest, clean, preview, approve/reject, store, retrieve) is live on merge under the
standing gate.

## References

`Use Cases_FINAL.md` §003; `docs/security/SECURITY_ROADMAP_air_gap_removal.md` §6 Decisions 3/4/6/7;
ADR-013, ADR-023, ADR-024, ADR-027 (+ Amendment 1), ADR-031; Vikunja #655, #577 (comment 1029 —
the integration contract), #613, #598, #556, #632;
`services/ui_gateway/src/document_loader.py` (the host-side loader pattern + `scan_for_injection`),
`services/assistant_orchestrator/src/websearch/dispatch.py` (explicit-command doctrine),
`shared/security/guarded_fetch.py` (`fetch_external` — the single egress door; W4 shipped it,
merged to main `8703dae` 2026-06-10),
`shared/security/egress_guard.py`, `shared/security/exfil_screen.py`,
`tests/security/test_no_external_egress.py` (the scan the §4 lock extends). DECISION_REGISTER index
updated in the same change (the non-optional maintenance rule).
