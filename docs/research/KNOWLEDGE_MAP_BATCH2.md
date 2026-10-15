---
title: BlarAI Knowledge Map, topic cards batch 2
status: living
area: research
---

# Knowledge Map batch 2: four topic cards

Drafted 2026-10-11 from the main checkout `C:/Users/mrbla/BlarAI`. Read-only: no repository edit, no git, no Vikunja call. Same schema as `docs/research/KNOWLEDGE_MAP.md` section 1: (a) question; (b) current answer and status; (c) evidence table; (d) layers of zoom; (e) open questions with the observable that closes each; (f) decisions made and waiting; (g) tickets; (h) raw sources. Acronyms are spelled out on first use inside each card. Grades: **M** measured on this machine; **S** read from source or a primary artifact; **V** vendor documentation only; **R** reasoning or design. "Not verified" marks anything I did not check. Every repository path below was checked with `ls`. Ticket numbers are copied from the cited files; no ticket text was read.

Direct checks I ran today (2026-10-11, this machine) and so grade **M**: `python -m shared.governance.permission_profile` (prints what BlarAI may do; read-only), the contents of the OpenVINO telemetry consent file, line counts and line numbers of `services/policy_agent/src/gpu_inference.py`, the on-disk presence of the vestigial token-signing files.

Cards in this batch:
- Card A: The single adjudication door: Policy Agent and egress
- Card B: Egress, search and the ceremonies
- Card C: Inference, model and performance on the Arc and NPU
- Card D: Memory, knowledge ingestion and born-encrypted storage

---

## Card A. The single adjudication door: Policy Agent and egress

### Summary (5 lines)
1. Every tool call and every outbound web fetch is judged by ONE plain function, `DeterministicPolicyChecker.check`, running inside the program. It uses no model and no network. This is the live door (ADR-041, 2026-07-15).
2. The Policy Agent as a separate service, its model-based classifier and its signed-token ("JWT", JSON Web Token) receipts are built and tested but are not on the live path; the receipt machinery is formally "vestigial, slated for removal" (ADR-041; ticket #910).
3. Around the door sit independent locks: a socket guard, a one-file network-library rule, a per-turn fingerprint check, a response-size cap and a payload screen. The payload screen is blind to encrypted (HTTPS) traffic, a finding corrected in 2026-09 (claim register row 12).
4. Microsoft's open-source Agent Governance Toolkit (AGT) was read twice (2026-09-16 and 2026-10-11) and judged neither a better adjudicator nor a better foundation; what it does better is small and copyable. It is also the nearest rival to the Governator's hook layer.
5. Open and the LA's: whether the model classifier is wired in or retired (#1683), whether the Governator may observe the door in shadow, and what the Governator does about AGT. Not verified: any ticket's current state.

### (a) The question
When BlarAI is about to run a tool or fetch a web address, what single piece of code decides yes or no, what stops anything else from deciding or bypassing it, and how does that compare with the off-the-shelf alternative and with the Governator?

### (b) Current answer and status
**Decided and live; with named gaps.**
- *Decided* (LA, 2026-07-15, ADR-041): the live host-mode boundary is per-boot mutual TLS (mTLS, certificates minted fresh at each start) plus a fixed tool allowlist plus the in-process `DeterministicPolicyChecker` plus the output validator (PGOV, Post-Generation Output Validator) plus the egress spine plus at-rest encryption plus signed model weights. Principle recorded: the model is untrusted; the probabilistic layer "may only tighten a deterministic ALLOW, never loosen a DENY".
- *Decided* (session technical call, ADR-044, 2026-10-05): the Policy Agent's model never sees tool-call arguments; the deterministic checker judges them; a field the judge cannot see whole is a deterministic deny, never a truncation. The model-backed classifier "is on no live path in the shipped configuration (static evidence; the live trace is still to run, #1683)".
- *Read today*: `services/policy_agent/src/rule_engine.py`, `jwt_minter.py`, `adjudicator.py` still exist on main. Whether #910 (removal) is open or done is not verified.
- *Decided by the LA* (ADR-049, 2026-10-05): the Governator venture is reopened on a narrower claim; this changes no BlarAI runtime.
- Deciding documents: ADR-041, ADR-044, ADR-049; `docs/governance/trust-spine-claim-register.md` (the surface that owns the composite claim "the trust spine does X").

### (c) Evidence table
| Date | Document path | What it found, one plain line | Grade | Confidence note |
|---|---|---|---|---|
| 2026-07-15 | `docs/adrs/ADR-041-Host-Mode-Action-Authorization-Boundary.md` | The signed-receipt design (every action carries a single-use JWT; every destination rejects without one) is built and tested but not driven in host mode; it was designed for one-VM-per-agent, which this hardware cannot host because the language models run only on the host GPU. | S + decision | Authoritative. Review finding GP-1 in `docs/design/july.15.2026/`. |
| 2026-07-15 | `Use Cases_FINAL.md` (USE-CASE-001, the ADR-041 amendment block near line 133) | The vision document was amended to say the signed-receipt boundary is vestigial. Earlier text of the same use case still describes it as live and says every Substrate operation needs a JWT. | S | The amendment is in the same file as the original text; read both. |
| 2026-09-16 | `docs/research/agt-vs-policy-agent-adjudicator-verdict-2026-09-16.md` | Source-level comparison at AGT commit `c63c51e8`: "No to both questions" (not a better adjudicator, not a better foundation). The running Policy Agent service "adjudicates nothing"; one function does, with 49 tests (figures from the file; I did not recount). | S | No tests run, no wheel built (its own words). The "150 lines" figure is superseded, see Corrected claims. *As of 2026-10-11: counted again, the class `DeterministicPolicyChecker` spans lines 578-866 of `gpu_inference.py` (about 289) and its `check` method 712-866 (about 155); the AGT verdict now carries a dated note saying so.* |
| 2026-09-16 | `docs/governance/trust-spine-claim-register.md` rows 1, 2, 3, 11, 13, 22, 25, 27-29 | Claim by claim: what is live, what it is tested against, what is open. Row 25: the signed-receipt pipeline is "DESIGN-INTENT, not the live boundary". Row 27 (approval binding) and row 28 (decisions not written to the audit chain) are ticketed design-only gaps; row 29 (chain never verified on load) is closed in code (#1543). | S | Line numbers in the evidence column are stale, see Corrected claims. |
| 2026-09-20 | same, row 3; ticket #1586 / #977 | Both egress checkpoints now register one request-keyed adjudicator, so they agree for every purpose except operator-paste. Before that, whichever component registered last decided the policy for both. | S | Door slot is last-write-wins (claim register); Governator ADR-004 calls it "singular first-wins". |
| 2026-09-18 | same, row 12 (#1592) | The outbound payload screen is never invoked for HTTPS and every production egress path is HTTPS. Measured: 0 screener calls on a real encrypted request. | M (per the register) | Two further fail-opens found by the #1580 review were fixed in the same commit. |
| 2026-10-05 | `docs/adrs/ADR-044-Policy-Agent-Model-Path-and-Tool-Call-Arguments.md` | Trace of both production doors: both call the checker in-process; 0 `Adjudication <uuid>` lines in a 102,513-line launcher log against about 4,998 Assistant Orchestrator lines; the 25 empty-schema and 10 rejected-schema golden rows mean the model's judgement of visible arguments was never measured. | S + reproduced | Live trace still NOT ESTABLISHED (#1683). |
| 2026-10-05 | `docs/adrs/ADR-049-Governator-Venture-Reopened.md` | The reopening rests on a raw packet-filter block keyed to an account (3 of 3 runs) and states its limits exactly: one dimension, one machine, IPv4 TCP port 443 only, seconds-long windows, not per-action governance. | decision | Candidate product claim is the session's reading, not adopted. |
| 2026-10-11 | `docs/research/GOVERNATOR_BRIDGE.md` sections 2-3 and 5 | Wall rules between the repositories; decisions D1-D6 waiting for the LA; connection 2 (Policy Agent as adjudicator behind a Governator-style vocabulary) is a hypothesis needing D3. | S + R | Ticket text and the Governator git history were not read by its author. |
| 2026-10-11 | `docs/research/OFFTHESHELF_VS_BLARAI.md` sections 1, 5, 7 | AGT 5.0.0 (Public Preview, MIT licence, created 2026-03-02) ships Claude Code and Codex plugins that check each tool call before it runs and keep a hash-chained log: the Governator's main mechanism. "Nothing surveyed sits in this position (inside a local-only system)". Corrects the checker size to about 300 lines. | S (source read, not run) | Skeptic-checked; four observable tests proposed in section 7, none run. |
| 2026-10-11 | `python -m shared.governance.permission_profile`, run by me today | Lists 5 capabilities on, 3 off, and one outbound destination (web search to kagi.com only); "Every other outbound address is refused by rule". | M | Reads `default.toml` and code at run time; it is a statement, not a control. |
| 2026-10-11 | `services/policy_agent/src/gpu_inference.py` (my line count) | `DeterministicPolicyChecker` runs from line 578 to line 873 of a 1,473-line file (about 296 lines); its `check` method starts at line 712; the allowlist constant `frozenset({"kagi.com"})` is at line 656. | M | Counted by reading line numbers today; confirms OFFTHESHELF's "about 300". |
| 2026-09-16 | `docs/research/cava-vs-microsoft-agent-framework-vs-blarai-trust-spine-2026-09-16.md`, `docs/research/trust-spine-proposed-items-index.md` | Fifteen proposed trust-spine items; gaps A (approval binding), B (receipts at the doors), C (two egress layers; now closed), D (chain never verified on load; closed). | R + S | Documentation-level for the vendor rows. |
| 2026-10-04 | `docs/research/jev-policy-agent-ideation-2026-10-04.md` | Ideas for a "second judge" using the model's own confidence; the 9B evidence was retracted twice. | V + M (9B data) | Retractions are visible in the file. |

### (d) Layers of zoom
1. **Why one door.** A risky action reaching a tool without passing a check is the failure the whole security design exists to prevent (`CLAUDE.md` principle 5: "Never add a side door, a bypass, or a second adjudicator").
   1. **What the door is today.** One function judges every tool call (Assistant Orchestrator) and every outbound web address (the gateway's URL door). Both import and call it directly; there is no network hop (ADR-041, ADR-044).
      - The tool allowlist: the assistant can call 11 named tools; anything else is refused by name; an unclassified tool is treated as dangerous (my run of the permission profile today).
      - The shared allowlist: one list (`kagi.com` only) is read by both egress layers (claim register rows 3, 5).
   2. **What the door is not.** The Policy Agent service, its classification model and its signed receipts. They boot, verify weights and bind a socket but receive no live traffic (ADR-041; AGT verdict "Outcome first").
2. **Locks around the door** (each tested off per principle 12; read the register for the evidence column, not this card):
   1. Socket guard: once armed only loopback and the Hyper-V channel can be reached (row 11).
   2. One-file rule: only one source file may import the network library (row 13).
   3. Turn-scoped human presence: a Windows Hello fingerprint check before each outbound search (row 9; `searches_per_fingerprint = 1` in `services/assistant_orchestrator/config/default.toml`).
   4. Response cap: byte size and JSON depth capped as a second lock downstream of the wire cap (row 8).
   5. Payload screen: plaintext sockets only (row 12, corrected).
   6. Untrusted-content action lock: after outside content enters a session, non-safe tools are refused unless the user types an override (row 22).
3. **What was learned by comparing.** AGT's name-brand features are thinner than the names (privilege rings are integers; identity is in-memory keys); its decision engine is a separate alpha crate; its core package requires two network libraries, which BlarAI's one-file rule would reject (AGT verdict). Its better ideas are small and copyable: the allow/deny/transform verdict set and a conformance suite.
4. **The Governator comparison.** AGT already ships the hook seam the Governator planned; what is left for the Governator is a person-owned record, an honest coverage screen and a cross-agent view (OFFTHESHELF section 7). Four tests would decide whether finishing it is worth it.
5. **Smallest details.** A rejected field is echoed in a deny reason only if it is one of nine allowed keys (ADR-044 decision 2); the control-token list is 33 entries read from four tokenizer files; the schema cap is 16384 serialised characters (ADR-044).

### (e) Open questions and the observable that closes each
| Question | Observable that would close it |
|---|---|
| Is the Policy Agent's model classifier wired into the door, or retired? | #1683's outcome; first, the live trace: launch the launcher, make one tool call with arguments and one `/ingest <url>`, then read the launcher log for `Adjudication` lines and `adjudication_audit.jsonl` (ADR-044 "NOT ESTABLISHED"). |
| Are the signed-receipt files actually removed? | #910 closed and `services/policy_agent/src/jwt_minter.py` / `rule_engine.py` absent or marked removed (both present on main today). |
| Does AGT's plugin behave like the Governator's hook client on this machine? | Run it through the Governator's own P1-P6 tests (OFFTHESHELF section 7(a)); not run. |
| Do a person's approvals bind to the exact action (gap A, row 27)? | #1541 built and a test where an approval for one action name with changed arguments is refused. |
| Do the two checkpoints write to the signed audit chain (gap B, row 28)? | #1542 built; a chain record exists per adjudication. |
| Does the payload screen see encrypted traffic? | A design that screens before encryption; today measured 0 calls on a real HTTPS request (row 12). |
| Is the door-slot description consistent across documents? | Governator ADR-004 ("singular first-wins"), the landscape, and `CLAUDE.md` (request-keyed, both sites since #1586) reconciled in writing (GOVERNATOR_BRIDGE connection 2). |

### (f) Decisions
Made: ADR-041 posture framing (LA 2026-07-15); ADR-044 argument path (session 2026-10-05); ADR-049 reopening (LA 2026-10-05); searches per fingerprint 3 to 1 (#1594, 2026-09-19, delegated by the LA to the session).
Waiting for the LA: whether a model classifier ever joins the door (a changed Policy Agent posture is a go-live ceremony per ADR-044); D3 (may the Governator observe BlarAI's door in shadow); D1 and D2 in the bridge; Governator direction after the four AGT tests (OFFTHESHELF section 10 item 1); whether to keep the Governator name in public documents beyond decision 3a.

### (g) Tickets (from cited files; text not read)
#910 (remove receipt machinery) · #1683 (wire or retire classifier) · #1672 (probability-gated escalation, blocked-by #1683) · #1673, #1684, #1685, #1688 (ADR-044 follow-ons) · #1586 / #977 (one adjudicator for both layers) · #1592 / #1580 (payload screen) · #1541, #1542, #1543 (trust-spine gaps A, B, D) · #1544 (proposed-items index) · #1693 (Governator scoping) · #1549, #1590 (feasibility, cancellation) · #1748 (telemetry finding in the off-the-shelf study).

### (h) Raw sources
In repo: the files in table (c); tests named in the register (for example `tests/security/test_no_external_egress.py`, `tests/security/test_guarded_fetch.py`). Outside the repo: `C:/blarai-spike-1740-mxc/study-offshelf/` (the five studies and skeptic checks behind OFFTHESHELF; existence not checked by me). Governator repository `C:/Users/mrbla/governator` (read through GOVERNATOR_BRIDGE only).

---

## Card B. Egress, search and the ceremonies

### Summary (5 lines)
1. BlarAI is no longer air-gapped, but exactly one outbound door is open: the model-callable web search to `kagi.com`. A live run of the permission profile today lists no other destination.
2. Every other door ("scope") is welded shut until its own ceremony (*status note 2026-10-11: the paste-a-URL door is the exception in kind: closed at rest, reachable by the shipped `--go-live` flag, and exercised on 2026-06-12 by a smoke harness with the Lead Architect present, and run by the operator in the production app on 2026-06-15*): pasting a URL to ingest (closed at rest because a normal boot never starts the guest parser, so the ingest coordinator refuses before any fetch; `[guest_parser].enabled = false` is overridden by the `--go-live` boot flag and is not the lock), fetching remote images (`images_enabled = false`), and any future scope. A live scope never implies a neighbour is live.
3. Search is held by several independent locks (allowlist, tool-loop check, door check, fingerprint per query, size caps, socket guard, one-file network-library rule); the payload screen cannot see encrypted traffic.
4. Several documents still describe the egress machinery as dormant or the allowlist as empty; they pre-date the 2026-07-02 go-live and are listed under Corrected claims.
5. The coder's separate egress block (a packet-filter rule keyed to the `blarai-coder` account, ADR-045) is a different control on a different program; it is built, measured for seconds, and switched off.

### (a) The question
What may leave this machine, to where, through which door, behind which locks, who opened each door and how, and what would re-close it?

### (b) Current answer and status
**Decided; one scope live; others welded.**
- *Decided* (LA, 2026-06-10): open selective, policy-gated egress, one named door at a time, each behind an LA-present go-live ceremony (`CLAUDE.md` blarai_identity; `docs/adrs/ADR-027-Egress-Policy-Network-Facing.md` with Amendment 1).
- *Live*: `web_search` to Kagi since the 2026-07-02 ceremony (#719; `docs/runbooks/web_search_go_live.md`). `[web_search] enabled = true`, allowlist `kagi.com` only (`services/assistant_orchestrator/config/default.toml`; `gpu_inference.py` line 656).
- *Welded, read today*: URL ingest (closed at rest because a normal launcher boot never starts the guest parser, `launcher/__main__.py` `_maybe_start_guest_parser` runs only under `--go-live`; the `launcher/config/default.toml` `[guest_parser] enabled = false` line is overridden by that flag); remote images (`default.toml` `images_enabled = false`, line 241 today).
- *Coder egress*: separate decision (LA, 2026-07-10, ticket #787) and ADR-045; `containment` is `off` per the docs dated 2026-10-09 (flag file not re-read by me).
- Rule for readers: never state which scopes are live from memory or a docstring; run `python -m shared.governance.permission_profile` and read `default.toml` and `docs/runbooks/`.

### (c) Evidence table
| Date | Document path | What it found, one plain line | Grade | Confidence note |
|---|---|---|---|---|
| 2026-06-03 | `docs/adrs/ADR-020-Code-Enforced-Egress-Kill-Switch.md` | The air-gap becomes code: only loopback and the Hyper-V channel may open a socket; everything else is refused and a kill-switch latches. | S + decision | Accepted, LA-approved. |
| 2026-06-05 | `docs/security/SECURITY_ROADMAP_air_gap_removal.md` | Campaign map and decision list toward removing the air-gap. | R | Header says it removes nothing itself. |
| 2026-06-07 | `docs/adrs/ADR-027-Egress-Policy-Network-Facing.md` | Four layers: deny-by-default allowlist, auto-approval within it with logging, kill-switch with human re-arm, payload screening. Amendment 1 (2026-06-10) adds the one-door fetch seam. Activation record appended 2026-07-02. | S | The status header still says "NOT YET ACTIVE", see Corrected claims. *As of 2026-10-11: a "Status as of 2026-10-11" block and a dated-history banner now sit above that header, which is kept as written.* |
| 2026-06-10 | `docs/security/egress_exercise_2026-06-10.md` | The controlled egress exercise on the machine's own LAN address: 11 of 11 passed; proves deny-by-default and kill-switch latching. | M | Harness `tests/security/test_egress_sandbox_proving.py`; skips on a loopback-only box. |
| 2026-06-04 | `docs/adrs/ADR-024-Agentic-Web-Search-Skill.md`, `docs/research/kagi_key_handling_design.md`, `docs/research/kagiapi_supply_chain_vetting.md` | Web-search design; key sealed with the Windows data-protection facility (DPAPI); the vendor package was vetted. | S + R | Vetting is "pending approval" in its own header; the live adapter is a stdlib adapter per `default.toml`. |
| 2026-07-02 | `docs/runbooks/web_search_go_live.md` | Procedure of record and the re-weld path (flag false; empty the allowlist; delete the key blob; each independently sufficient). First live request happened 2026-07-02. | S | Banner says do not re-run as pending. |
| 2026-07-02 | `docs/DECISION_REGISTER.md` (row "Updated 2026-07-02") | The allowlist is activated with `kagi.com` as sole entry, read by both egress layers. | S | |
| 2026-09-16 | `docs/governance/trust-spine-claim-register.md` rows 2-9, 11-13 | Per-lock evidence and limits: SSRF guard with a residual; response caps (2 MiB, depth 12); fingerprint per outbound call; screen blind to HTTPS (row 12, corrected 2026-09-18). | S | Line numbers stale. |
| 2026-09-18 | `docs/design/1592-outbound-content-control-design-2026-09-18.md`, `docs/design/1595-provenance-constrained-egress-design-2026-09-20.md` | Designs answering the HTTPS-blind payload screen (#1592) and constraining what content may leave by provenance (#1595). | R | Whether built or shipped is not verified. |
| 2026-09-19 | `docs/DECISION_REGISTER.md` (row "Updated 2026-09-19", #1594) | `searches_per_fingerprint` 3 to 1: "An approval nobody gave is not an approval". | S + decision | The LA delegated the call. `default.toml` reads 1 today. |
| 2026-10-11 | `python -m shared.governance.permission_profile` (run today) | "web_search - and only to kagi.com. Every other outbound address is refused by rule, whatever any setting says." | M | |
| 2026-06-12 | `docs/security/guest_parser_provisioning_record.md`, `docs/security/uc003_live_fetch_proof_2026-06-12.md` | URL-ingest limb proven end to end in the guest, then left switched off. | M | `enabled = false` read today. |
| 2026-10-05 | `docs/adrs/ADR-045-Coder-Containment-Account-Level-Fused-Leg-and-WFP-Egress-Block.md` | Coder egress block is a Windows Filtering Platform rule keyed to the `blarai-coder` account; it is a dynamic session that vanishes when its script exits; persistent version not built (#1682). | S + decision | Different control from the runtime guard. |
| 2026-10-04/09 | `docs/research/account-level-containment-evidence-2026-10-05.md` claims C1, C7, C8 | Block stopped the coder account's connect to 1.1.1.1:443 in 3 of 3 runs under the installed security suite; loopback permit on versus off, 3 of 3 each. | M, n=3 | Windows of seconds; IPv4 TCP 443 only; one machine. |
| 2026-07-10 | `docs/security/post_capstone_2026-07/PHASE1_DISPATCH_THREAT_MODEL.md` | Honest residuals of the coder floor; hybrid VM direction. | R | Section 5.1 pre-dates the security-suite finding. |
| 2026-10-11 | `docs/research/OFFTHESHELF_VS_BLARAI.md` section 3 | Of the products whose source was read, several phone home by default; BlarAI's own build environment had Google Analytics enabled by the OpenVINO tooling (Card C). | S | Closed-source products not auditable. |
| 2026-06-05..11 | `docs/adrs/ADR-030-Cleaner-v1-Guest-Homed-Ingest-Pipeline.md` | The host fetches through the single door and never parses; a guest with a network adapter was rejected as a second egress path. | R | See the existing Knowledge Map card "Isolating untrusted input". |
| ongoing | `docs/security/egress_machinery.md`, `docs/security/egress_activation.md` | Builder guides for the machinery. | S | Both still say "STAGED / DORMANT" in their headers. |

### (d) Layers of zoom
1. **Why per-scope.** One global "network on" switch would let one mistake open every door. Each scope (a purpose plus a destination) is a separate decision with its own ceremony (`CLAUDE.md`).
2. **The live scope, step by step** (runbook and register): the model asks for a search; the tool loop's dispatch check judges the web address against the allowlist; the Windows Hello fingerprint is required for that query; the one egress door (`shared/security/guarded_fetch.py`) re-checks, resolves the host and refuses internal ranges (SSRF, Server-Side Request Forgery guard); the reply is size- and depth-capped; the result enters the conversation tagged untrusted and datamarked (ADR-023; the `UNTRUSTED_WEB` tier exempts only the leakage output block).
3. **Independent locks** (register rows): allowlist; tool-loop check; door check; fingerprint (`[egress]` table); response caps (`[web_search]` table); socket guard armed at start; one-file network-library scan; payload screen (plaintext only); latched kill-switch.
4. **Welded scopes**, and why each is its own ceremony:
   1. URL ingest of a pasted page: the guest parser exists and is proven; flag off; the register marks it design-intent with no go-live runbook (row 6).
   2. Remote images: display-only design (ADR-032); flag off; no runbook (row 7).
   3. Coder egress: separate account-level control (ADR-045); flag off.
5. **Re-weld path.** Flip `[web_search].enabled` false and restart; empty the allowlist; delete the sealed key blob. Each alone is sufficient (runbook).
6. **Small details.** The loopback permit in the coder block is load-bearing: without it the same request fails with Windows error 10013 (evidence C8). The coder block's filters used weights 0x1000 (block) and 0x2000 (permit) in a top-weight sublayer (ADR-045 decision 4, as quoted in the existing map).

### (e) Open questions and the observable that closes each
| Question | Observable |
|---|---|
| Is the payload-screen blind spot closed? | #1592 design shipped and a test where a planted secret in an HTTPS body is refused before encryption. |
| Does an unconditional ceremony exist for URL ingest and images? | A go-live runbook file under `docs/runbooks/` for each (none today per register rows 6 and 7). |
| Is the HTTPS-capable provenance design (#1595) built? | Code path present and a test that fails with the lock off; not checked by me. |
| Does the coder egress block hold beyond seconds, across reboot, IPv6, UDP, DNS? | Persistent filter (#1682) plus long-hold and reboot arms listed NOT RUN in `docs/research/containment-evidence-2026-10-05/ARMS_HANDOFF.md`. |
| Did data leave through OpenVINO tooling before the opt-out? | Not knowable from disk: "no network capture was made" (OFFTHESHELF section 6). |
| Are the stale "dormant" banners fixed? | The listed headers read the live state or point to `default.toml`. |

### (f) Decisions
Made: open selective egress (LA 2026-06-10); `kagi.com` activation (LA ceremony 2026-07-02, #719); fingerprint per query (#1594, delegated); Kagi as search provider; coder floor and accepted egress gap (LA 2026-07-10).
Waiting for the LA: ceremonies for URL ingest and images (each its own); coder containment flip (#775); relaxing the fingerprint count is a posture loosening and is his call (`default.toml` comment).

### (g) Tickets (from cited files; text not read)
#719 (web_search go-live) · #556, #598 (air-gap removal and its GO/NO-GO) · #577, #572, #573 (web-search epic and pre-work) · #643 (egress sandbox proving) · #655 (Cleaner) · #663 (images) · #1580, #1592, #1594, #1595, #1586 · #775, #787, #1671, #1682 (coder block) · #1748.

### (h) Raw sources
In repo: runbooks `web_search_go_live.md`, `kagi_key_provisioning.md`, `what_blarai_is_allowed_to_do.md`; `docs/security/egress_*.md`; `docs/research/containment-evidence-2026-10-05/` (scripts and result JSON). Outside the repo: `C:/Users/mrbla/blarai-research-data/` (not opened by me).

---

## Card C. Inference, model and performance on the Arc and NPU

### Summary (5 lines)
1. All language-model inference runs on the Intel Arc 140V graphics chip through OpenVINO GenAI; the NPU (neural processing unit) was retired for language models in 2026-02 (ADR-011) and now does embedding encoding.
2. The resident brain is Qwen3-14B with a small pruned draft model for speculative decoding (ADR-012). Measured speed-up on this machine is 1.25x to 1.6x, not "about 2x" (Corrected claims).
3. PERFORMANCE_LOG.md holds 68 dated entries in the `###` form and 23 in the `##` form (counted today) and `docs/performance/` holds 201 JSON files (counted today). Sustained decoding throttles by about 3x; the project's cold gate (thermal zone at or below 72 C) is the protocol (ADR-047).
4. Qwen3-14B stays. A 35B mixture-of-experts candidate is 2.4x faster but its thinking blocker was withdrawn as a test artefact; the swap waits on named upstream signals. No speed ordering against other products is established.
5. New today: the OpenVINO tooling sent Google Analytics by default on this machine; the local consent file was set to declined on 2026-10-11 and reads `0` now. Permanent control: #1748, open.

### (a) The question
How fast and how well does the local brain run on this specific chip, what governs which model and device is used, how is that measured honestly, and what would change the choice?

### (b) Current answer and status
**Decided (stack and model); measurement protocol decided; upgrade watch open.**
- *Decided* (ADR-011, 2026-02-27): all language-model inference on the GPU; NPU retired for it, because the earlier studies showed the GPU 4-5x faster (36-53 versus 3-14 tokens per second).
- *Decided* (ADR-012, locked): Qwen3-14B, speculative decoding with a pruned Qwen3-0.6B INT8 draft, three assistant tokens per step.
- *Decided* (ADR-040, 2026-07-15): key-value cache precision; the 14B INT8 flip is gated on the #715 answer-quality test.
- *Decided* (ADR-047, 2026-10-05): cold-gate protocol, pre-registered limits, visit means, visible retractions, published data. It decides nothing about replacing the brain.
- *Open*: the model-upgrade watch. `docs/research/openvino-2026.4-relevance-assessment-2026-09-21.md` records that the watch's own first trigger fired (the Multi-Token Prediction pull requests merged and shipped 2026-09-17); `docs/MODEL_EVALUATION_QWEN36_27B.md` carries a partial retraction (trigger 4, the thinking-toggle blocker, withdrawn 2026-09-22).
- `CLAUDE.md` status snapshot (as of 2026-08-15 header, with later edits): 35B-A3B (#930) brain switch DORMANT.

### (c) Evidence table
| Date | Document path | What it found, one plain line | Grade | Confidence note |
|---|---|---|---|---|
| 2026-02-27 | `docs/adrs/ADR-011-All-LLM-Inference-GPU-NPU-Retirement.md` | NPU 3-14 tokens/s versus GPU 36-53 (studies P5-004); NPU also forced a weak production model; all LLMs to the GPU. | S | Early-2026 stack; figures are the ADR's table. |
| 2026-02-28 | `docs/adrs/ADR-012-Qwen3-14B-Model-Selection-Speculative-Decoding.md` | Qwen3-14B plus draft; "measured: ~2-3 tps solo vs ~10 tps with draft at 4K context" (March stack, older INT4 28-layer draft). | S | Superseded by later entries for the speed-up figure. |
| 2026-05-21 | `PERFORMANCE_LOG.md` entry "Speculative decoding fixed and measured" | Standard 9.9 mean / 10.6 median tokens per second; speculative 11.9 mean / 13.2 median; about 1.25x median, about 1.45x on long generations; an earlier "~2x" "was an overstatement". 5 measured plus 2 warmup runs, 90 s cooldown. | M | Raw: `docs/performance/benchmark_2026-05-21_23-44-08.json`. Streaming does not occur under speculative decoding. |
| 2026-06-05 | `PERFORMANCE_LOG.md` entry "Spec-decode survives 16K now" | Acceptance 0.472 / 0.575 / 0.457 at 2K / 8K / 16K; 4.94 tokens/s at 16K (about 2.3x the March figure); peak memory about 12.7 GB. | M | `specdecode_16k_recheck_2026-06-05_07-12-46.json`; 20K band not measured. |
| 2026-06-27 | `PERFORMANCE_LOG.md` entry "Cross-runtime comparison ... vs community llama.cpp/SYCL" and 2026-06-28 refresh | Dense prefill about 1960 tokens/s, about 3.7x a community llama.cpp 7B figure on the same chip; 14B speculative 17.1 tokens/s. | M + comparison | Comparison is to other people's numbers; the 06-27 entry is analysis, not a run. |
| 2026-06-29 | `PERFORMANCE_LOG.md` entries on OpenVINO 2026.1.0 to 2026.2.1 | 14B and 8B: version change is a no-op; CPU-draft is a clean negative; prefill and vision are the real wins. | M | |
| 2026-07-01 | `PERFORMANCE_LOG.md` entry "KV-cache precision at long context" | INT8 key-value cache is the sweet spot; "the fanless chip has two thermal tells". | M | Gate on #715 remains. |
| 2026-07-02 | `PERFORMANCE_LOG.md` entry "The idle NPU earns the embedding job" | NPU embedding encoding is 13.6x the CPU path on document-window texts; Whisper speech-to-text on the NPU hangs the device, so it stays on the GPU. | M | `embedding_device_2026-07-02_00-10-26.json`, `whisper_device_2026-07-02_00-13-38.json`. Device is requested NPU; hybrid-retrieval run on 2026-07-10 was served by CPU because of contention. |
| 2026-08-31 | `PERFORMANCE_LOG.md` entries 2026-08-31 (decay, 97% GPU budget, offload) | A reboot clears a session-accumulated throughput decay; elapsed session time moves a figure by about 40%. | M | The reason for interleaved arms and reboot-first protocols. |
| 2026-09-22 | `PERFORMANCE_LOG.md` entry "S0: the 35B is 2.4x faster" | 35B: 33.18 and 33.29 median tokens/s on two passes (0.3% apart); 14B speculative off 8.72, on 13.94 (1.60x, clean pass); second pass 1.48x was contaminated by a test run and is recorded. | M | Driver 32.0.101.8831, OpenVINO 2026.2.1, graphics-memory budget keys both 87. |
| 2026-09-22 | `PERFORMANCE_LOG.md` entry "first honest quality comparison of the two brains" | Brains tie on conversation; the 14B is slightly better at tool use; an earlier "three security holes" result was a test that had switched the protection off. | M | Retraction attributed (#1622; lessons 371-372 per the snapshot). |
| 2026-10-04 | `PERFORMANCE_LOG.md` entry "Qwen3.5-4B INT8 with Multi-Token Prediction", `docs/research/qwen35-4b-mtp-phase1-verdict-2026-10-04.md`, `qwen35-9b-int8-verdict-2026-10-04.md` | Small model with MTP is 1.5-3.5x faster than the shipping 14B at about half the memory; the "lets two dangerous actions through" claim was corrected (the command was never shown to any model). | M | Instrument had to be fixed three ways first. |
| 2026-10-05 | `docs/adrs/ADR-047-Model-Evaluation-Protocol-Cold-Gate-Pre-Registration-and-Visible-Retractions.md` | Sustained decode throttles (48 ms to about 160 ms per token after about two minutes on the 4B); protocol: thermal zone at or below 72 C before each generation; decode differences under about 5% are not findings. | M + protocol | 5 of 159 cold rows excluded and disclosed. |
| 2026-10-11 | `docs/research/OFFTHESHELF_VS_BLARAI.md` section 5 | 14B with speculative decoding 13.9 tokens/s, without 8.7, 10.4 at a 6,000-token prompt; the "25 tokens/s" figure was a 16-token short-prompt run; "No speed ordering is established in either direction." | M + S | |
| 2026-10-11 | `docs/research/OFFTHESHELF_VS_BLARAI.md` section 6; the file `%LOCALAPPDATA%\Intel Corporation\openvino_telemetry` read by me today | The `openvino-telemetry` package defaults to Google Analytics when no consent file exists; a client-id file existed from 2025-10-20; consent file now contains `0`, last written 2026-10-11 1:22:47 PM local. | S (study) + M (file read today) | Past transmission unknown; permanent control is #1748. |
| 2026-07-08 | `docs/MODEL_EVALUATION_QWEN36_27B.md` | Qwen3.6-27B dense fits but runs at half the bandwidth-math speed; "NOT RECOMMENDED YET" with revisit triggers; trigger 4 withdrawn 2026-09-22. | M + S | Partial retraction banner at the top. |
| 2026-09-21 | `docs/research/openvino-2026.4-relevance-assessment-2026-09-21.md` | The graphics-memory budget key governs everything; the watch's first trigger fired with the 2026-09-17 releases. | S | Production stays on 2026.2.1. |

### (d) Layers of zoom
1. **Why this stack.** Memory is the scarcest resource (31.323 GB effective); one resident model is shared by the Policy Agent and the Assistant Orchestrator (`CLAUDE.md` stack; ADR-012).
   1. **Device split.** Language models: GPU. Embeddings (bge-small-en-v1.5): NPU, 13.6x the CPU path. Speech-to-text (Whisper): GPU. Image generation (SDXL): GPU, load on demand.
   2. **Speculative decoding.** A small draft model proposes tokens, the big model verifies them. Measured 1.25-1.6x on the 14B (table above); it survives 16K context with acceptance 0.46-0.58; it stops live token streaming.
2. **How numbers are made trustworthy.**
   1. Cold gate: wait for the thermal zone at or below 72 C before each generation (ADR-047).
   2. Reboot first; interleave arms across session time (2026-08-31 and 2026-09-22 entries).
   3. State the minimum detectable effect before running (the 2026-09-22 S0a gate was plus or minus 15%).
   4. Record contaminated passes rather than hide them.
3. **Where the records live.** `PERFORMANCE_LOG.md` (narrative, community-grade), `docs/performance/*.json` (201 files), `docs/performance/community_export/` (csv/jsonl for the Hugging Face dataset), `docs/performance/_invalid/` (kept bad runs). Every measurement arc ships data to the public Hugging Face dataset `openvino-arc140v-lunarlake` per `CLAUDE.md`/memory rules; upload status is not verified here.
4. **Upgrade watch.** Revisit triggers are named upstream changes, not a calendar. The first fired 2026-09-17; the thinking-toggle blocker was a self-inflicted test artefact (retracted); the 35B is 2.4x faster but swap waits on quality evidence and the LA's ceremony.
5. **Telemetry opt-out.** The package defaults to on; the official opt-out command may itself send an event, so the file was written directly; both Python environments read declined (OFFTHESHELF section 6). The `%LOCALAPPDATA%\Intel Corporation` folder also holds `openvino_ga_cid` and `stats` (names read today; contents not opened).

### (e) Open questions and the observable that closes each
| Question | Observable |
|---|---|
| Is a permanent opt-out check in place? | #1748 closed with a check that fails when any build environment lacks the opt-out; today only the one-off file value is verified. |
| Did the OpenVINO telemetry transmit data before? | Not recoverable; would need a capture of the tooling run. |
| Which of the 14B-versus-35B quality gaps remain? | A like-for-like run under ADR-047 with the 35B (the `agentic` suite numbers for the 14B are recorded as retracted and attributed). |
| What is the speed ordering against other products? | A same-chip, same-model-size run of each product with the cold gate; OFFTHESHELF says none exists. |
| Does speculative decoding speed-up hold on the current driver (8831)? | Interleaved on/off pairs on the production runtime; the 09-22 pass-1 figure is one clean pass. |
| Is the 14B INT8 KV flip safe? | The #715 answer-quality test (ADR-040). |
| Where did the 06-27 comparison's community numbers come from? | Not verified by me. |

### (f) Decisions
Made: ADR-011, ADR-012, ADR-040, ADR-047 (see (b)); Qwen3-14B stays (LA, watch record); opt-out of OpenVINO telemetry (session, 2026-10-11, reported; the "no big-tech services without approval" rule supports it).
Waiting for the LA: any brain switch (go-live ceremony); whether to make the telemetry check permanent (recommended, OFFTHESHELF section 10 item 3); the 14B INT8 KV flip after #715.

### (g) Tickets (from cited files; text not read)
#1748 · #930, #1610, #1611, #1618, #1622, #1624 (35B and brain comparison) · #1663, #1664, #1665 (Qwen3.5 arcs; #1665 still open for INT4 arms) · #715 (KV INT8 answer-quality A/B) · #709 (KV sweep) · #720 (NPU embeddings) · #1501, #1485, #1487 (memory budget and decay) · #1699, #1707 (gate runtime) · #1740 (probe entries in the log).

### (h) Raw sources
In repo: `PERFORMANCE_LOG.md`, `docs/performance/` (README_coresident_ut.md, README_vlm_longcontext.md, JSON files), `docs/MODEL_EVALUATION_QWEN36_27B.md`, `docs/research/openvino-2026.3-relevance-assessment-2026-08-29.md`, `docs/research/openvino-2026.4-relevance-assessment-2026-09-21.md`, `docs/research/qwen35-small-models-specdec-multimodal-2026-10-03.md`, `docs/upstream/` (contribution drafts), `docs/guide-workstreams/openvino-contribution-npu-int8-guard/` (the only repository hit when I searched for "openvino-telemetry"; contents not read). Outside the repo: Hugging Face dataset (not checked); `%LOCALAPPDATA%\Intel Corporation\`.

---

## Card D. Memory, knowledge ingestion and born-encrypted storage

### Summary (5 lines)
1. BlarAI keeps three kinds of memory: the conversation store (`sessions.db`), the assistant's cross-conversation memory and the knowledge bank (`substrate.db`). The two real databases are encrypted from creation with AES-256-GCM under a key sealed in the machine's TPM (Trusted Platform Module), with an offline recovery key.
2. The ceremony was executed on 2026-06-05; an independent scan found 0 plaintext in the real databases. Deleted rows are zeroed (`secure_delete=ON`) in the stores I checked.
3. Ingest (UC-003, "the Cleaner") works on pasted files and text today; fetching a page by URL is welded off and the guest parser is dormant. Retrieval over the bank is a hybrid of vector and keyword search.
4. Known limits on the record: keys and decrypted text exist in memory while running; row metadata stays plaintext; an equality-leaking index exists; a deliberate public-corpus tier is signed but not encrypted (DEC-13).
5. Untrusted image decoding is not isolated: ADR-022 is Proposed and deferred until images arrive from the network. Not verified: the current contents or size of the real databases.

### (a) The question
Where does BlarAI keep what the operator tells it and what it ingests, how is that protected on disk and in use, how does new material get in safely, and what is still unprotected?

### (b) Current answer and status
**Decided and executed for storage; ingestion live for local inputs; image isolation deferred.**
- *Decided and executed* (ADR-025, ceremony 2026-06-05): application-layer AES-GCM field encryption under a TPM-sealed data-encryption key (DEK), plus an offline recovery key (stored off-box by the LA), for `sessions.db` and `substrate.db`; no plaintext fallback.
- *Decided and built* (ADR-016 MVP 2026-06-02; ADR-031 Substrate v2 and ADR-030 Cleaner v1, 2026-06-10): the layered knowledge bank with operator approval of each ingested item.
- *Decided* (ADR-036, 2026-07-10): feedback-memory governance; the preference tier is governed by proposals the operator confirms.
- *Decided* (DEC-13): an offline Wikipedia-snapshot corpus is a read-only retrieval tier, integrity-signed but not encrypted (public content), a scoped deviation from the born-encrypted principle.
- *Deferred* (ADR-022, Proposed, LA-directed 2026-06-04, #562): isolate image decoding/inference; leaning to decode in a sandbox; trigger is images arriving from the network.
- Live check I ran: `PRAGMA secure_delete=ON` is set in `services/ui_gateway/src/session_store.py` (two places), `services/assistant_orchestrator/src/substrate.py` and `knowledge_bank.py`, plus the coordinator and dispatch stores (read from source today).

### (c) Evidence table
| Date | Document path | What it found, one plain line | Grade | Confidence note |
|---|---|---|---|---|
| 2026-06-02 | `docs/adrs/ADR-016-Personal-Knowledge-Substrate-MVP.md` | First slice of UC-002: persistent semantic memory across sessions, in one process. | S + decision | |
| 2026-06-05 | `docs/adrs/ADR-025-At-Rest-Encryption-DEK-Envelope.md` | Born-encrypted design; limits on the record: plaintext in RAM (deferred, with Intel Key Locker named as a candidate), plaintext metadata, equality-leaking keyed hash index. Section 5: both stores ciphertext at rest, 0 plaintext found by an independent raw-column scan. | S + M (ceremony) | Trust-anchor identifiers recorded at the ceremony. |
| 2026-06-05 | `docs/runbooks/at_rest_encryption_ceremony.md` | Ceremony executed; "DO NOT RUN IT AGAIN"; do not delete either database. Verified 2026-07-19: keystore provisioned; `substrate.db` 843,776 bytes and `sessions.db` 331,776 bytes at that date. | S | Sizes are 2026-07-19 figures from the runbook, not today's. |
| 2026-06-05 | `PERFORMANCE_LOG.md` entry "Sprint 14 EA-4: sessions.db at-rest encryption overhead" | Field encrypt/decrypt costs about 0.7-1.2 microseconds for fields up to about 1 KB; CPU-only microbenchmark. | M | Not measured: disk I/O and key-unseal latency at start. |
| 2026-06-06 | `PERFORMANCE_LOG.md` entry "AES-256-GCM substrate encryption overhead" | About 0.1 ms per query; 1.5 ms for the boot-time embedding-cache decrypt (107 embeddings then). | M | Raw: `docs/performance/benchmark_2026-06-06_02-15-23.json`; `sessions_encryption_overhead_2026-06-05.json` also exists. |
| 2026-06-08 | `docs/security/DATA_MAP.md` | Two storage roots: the repo certificates folder and `%LOCALAPPDATA%\BlarAI\`; plus the TPM and the signed manifest. A data-flow inventory for the AI-governance certification. | S | Authored 2026-06-08; paths in it can drift. |
| 2026-06-10 | `docs/adrs/ADR-030-Cleaner-v1-Guest-Homed-Ingest-Pipeline.md`; `docs/adrs/ADR-031-Substrate-v2-Layered-Knowledge-Bank.md` | Ingest flow: clean, preview, operator approve, store; the guest-homed parser is the planned hostile-HTML path. | S + decision | |
| 2026-06-10 | `PERFORMANCE_LOG.md` entry "Cleaner v1 clean_html: ~15 ms per 7-fixture corpus pass, CPU-only" | HTML clean-up is cheap: about 15 ms per pass of 7 fixtures. | M | |
| 2026-06-11 | `PERFORMANCE_LOG.md` entry "First live ingest+retrieval on the merged knowledge bank" | `/ingest` 1.14 s, `/approve` 1.21 s (3 chunks), grounded first token 24.5 s, answer 64.3 s; n=1, cold recompile boot 145.3 s. | M, n=1 | Not a benchmark; driver 8826. |
| 2026-06-14 | `docs/adrs/ADR-032-UC-003-Display-Only-Images.md`; `docs/adrs/ADR-023-Provenance-Based-Trust-Model.md` | Images stored encrypted under the same DEK; remote image fetch is a separate welded scope. Provenance tiers (`UNTRUSTED_KNOWLEDGE`, `UNTRUSTED_WEB`) exempt only the leakage block. | S | |
| 2026-06-04 | `docs/adrs/ADR-022-Isolate-Untrusted-Image-Handling.md` | Image decoders are a CVE-rich surface; no confidential-GPU boundary on this silicon; lean: decode in a sandbox, keep the vision model host-side. | R + M (Gate 4 finding, cited) | Proposed, deferred. Do not confuse with devplatform's ADR-022 (self-modification taxonomy), cited in ADR-036. |
| 2026-07-10 | `PERFORMANCE_LOG.md` entry "#795 Hybrid-vs-vector-vs-BM25 retrieval A/B" | On 35 docs and 24 queries vector-only R@4 = 1.000, hybrid 0.917, keyword-only 0.917; two queries demoted to ranks 18 and 22 by common-word noise. | M (small corpus) | Raw: `hybrid_vs_vector_795_2026-07-10_17-13-30.json`. |
| 2026-07-21 | `PERFORMANCE_LOG.md` entry "2026-07-21 #795 stopword-filter re-measurement" | After the stopword fix hybrid R@4 0.917 to 1.000, tying vector-only at the depth production reads. | M | Encoder requested NPU, served CPU in both runs. |
| 2026-09-21 | `PERFORMANCE_LOG.md` (retrieval scaling entry), `docs/performance/knowledge_retrieve_scaling_2026-09-21.json` | Retrieval is linear: 0.23 ms at 100 chunks, 775.42 ms at 200,000; warning threshold now 25,000 chunks; the live store measured 15 chunks. | M (random vectors) | Not measured with real embeddings or a resident model. |
| 2026-09-21 | `docs/research/kiwix-offline-corpus-assessment-2026-09-21.md`; `docs/research/corpus-extraction-contract-2026-09-23.md`; `docs/DECISION_REGISTER.md` DEC-13 | Offline corpus: extraction ran 2026-09-23 (7,341,217 articles, 68,374,765 chunks); signed not encrypted; its own tier. | S | The contract was revised after a review found 19 defects; section 7 retracts length-floor justifications. |
| 2026-07-10 | `docs/adrs/ADR-036-Operator-Feedback-Memory-Governance.md`; `docs/research/assistant_memory_reference_study_2026-07.md`; `docs/research/preference_memory_m2_m3_iteration_plan_2026-07.md` | Preference memory: proposals channel, operator confirmation, a miner that stays dormant until quality is proven. | S + decision | |
| 2026-06 | `docs/security/guest_parser_provisioning_record.md`; `launcher/config/default.toml` | Parser provisioned and proven; `enabled = false` read today. | M + S | See existing card "Isolating untrusted input". |
| ongoing | `docs/governance/trust-spine-claim-register.md` rows 18, 19 | Row 18 LIVE (born encrypted, TPM-sealed key, no plaintext fallback); row 19 DEFERRED (key and data in RAM while running). | S | |
| 2026-10-11 | `python -m shared.governance.permission_profile` (run today) | Lists "Read your own documents" as on; two knowledge-bank tools (move files, erase documents) and "Rehearse an action" as switched off. | M | Erase is irreversible and "needs the rehearsal switch on as well". |

### (d) Layers of zoom
1. **Why encrypt at creation.** A stolen disk should yield only ciphertext, and there should never be a plaintext window (ADR-025 consequences).
   1. **What is encrypted:** document text, embeddings, filenames, conversation text, session titles. **What is not:** row IDs, timestamps, `kind`, `chunk_index`, `role`, `pgov_status`, `is_active` (ADR-025 limits).
   2. **The key:** a DEK sealed by the TPM (RSA seal key `BlarAI-DEKSeal`, non-exportable); the recovery key is printed once and stored off-box. Without the TPM or the recovery key the databases cannot be read, by design.
   3. **Deletion:** `secure_delete=ON` zeroes freed pages; knowledge-bank erasure cascades chunks and images (source comments in `knowledge_bank.py`).
2. **How material gets in** (UC-003): input (file or pasted text today) to cleaning (noise strip, then adversarial sanitisation) to a preview the operator approves to chunking, embedding (NPU) and encrypted storage. URL fetch and image fetch are separate welded scopes (Card B).
3. **How memory gets out:** retrieval is vector plus keyword (BM25, a keyword-ranking method) with reciprocal-rank fusion; retrieved text is wrapped as untrusted data before the model sees it (claim register rows 21, 22).
4. **Limits.** Plaintext in memory while running (deferred; candidate mitigations named); keyed-hash index leaks equality; scaling is linear (warning at 25,000 chunks); the isochronous-retrieval timing defence described in USE-CASE-002 is a design statement whose implementation I did not check.
5. **Smallest detail.** Hybrid retrieval OR-joins every query token including stopwords, which caused the 2026-07-10 demotions; the stopword filter merged as `da9f7b87` (cited in the 2026-07-21 entry).

### (e) Open questions and the observable that closes each
| Question | Observable |
|---|---|
| How big are the real stores today and are all content columns ciphertext? | A fresh raw-column scan of the real databases (read-only), as ADR-025 section 5 did on 2026-06-05; not run by me. |
| Is `secure_delete` on for every store that holds content? | A grep for the pragma across every `sqlite3.connect` site; I found it in session, substrate, knowledge bank, coordinator and dispatch stores only. |
| When is ADR-022 decided? | The first image from the network, or a decode-only probe under an AppContainer-class container (Knowledge Map existing card, open question 3). |
| Does retrieval hold at real scale with real embeddings? | The re-measure named in the 2026-09-21 entry ("Next:"). |
| Is the in-RAM plaintext risk acceptable once egress widens? | ADR-025 revisits when the threat model extends; candidate: Intel Key Locker. No date. |
| Is the DEC-13 deviation (signed, not encrypted) still wanted? | LA reading of DEC-13 at the next corpus ceremony. |

### (f) Decisions
Made: ADR-025 ceremony (LA 2026-06-05); recovery key stored off-box (LA); DEC-13 (decided per the register); ADR-036 D-0..D-7 (LA 2026-07-10).
Waiting for the LA: ADR-022 timing; ceremonies for URL ingest and images; erasure/organise tools stay switched off until a ceremony.

### (g) Tickets (from cited files; text not read)
#559 (at-rest encryption origin) · #611 (memory-resident keys roadmap) · #562 (ADR-022) · #655 (Cleaner program) · #663 (images) · #664 (knowledge-bank leakage tier) · #770, #792, #793, #796, #795 (memory learning loops and retrieval A/B) · #1616, #1641, #1648 (reference corpus) · #1567, #1568 (curate/organise tools).

### (h) Raw sources
In repo: `substrate`/`knowledge_bank` source under `services/assistant_orchestrator/src/`; `services/ui_gateway/src/session_store.py`; `docs/security/DATA_MAP.md`; performance JSON listed above. The real databases live under `%LOCALAPPDATA%\BlarAI\` (not opened; never in git).

---

## Connections (all [PROPOSED]; each pairs two real documents; none is tested)

1. **[PROPOSED] Payload-screen blind spot + provenance-constrained egress design.** `docs/governance/trust-spine-claim-register.md` row 12 (screen never invoked for HTTPS) and `docs/design/1595-provenance-constrained-egress-design-2026-09-20.md`. Idea: confirm in writing whether #1595's constraint sits before encryption; if so, row 12's open gap has a named owner. Hypothesis: I did not read the design body.
2. **[PROPOSED] ADR-044's "field the judge cannot see whole is denied" + the Knowledge Map's open question on unscoped network rules.** `docs/adrs/ADR-044-Policy-Agent-Model-Path-and-Tool-Call-Arguments.md` and `docs/research/GOVERNATOR_BRIDGE.md` (E5, E17). The same deny-rather-than-truncate rule is the right shape for any governor adapter that parses a command string it cannot parse whole.
3. **[PROPOSED] Door-slot wording drift.** `docs/research/GOVERNATOR_BRIDGE.md` section 7.3 (ADR-004 calls the slot "singular first-wins") and `docs/governance/trust-spine-claim-register.md` row 3 (last-write-wins, request-keyed since #1586). One reconciled sentence should be owned by the register; the bridge's drift check should read it.
4. **[PROPOSED] AGT test (a) + the Governator's P1-P6 tests.** `docs/research/OFFTHESHELF_VS_BLARAI.md` section 7 and `docs/research/GOVERNATOR_BRIDGE.md` section 3(e). Both name running AGT's plugin through the Governator's hook tests; do it once and record the result in both places. Observable: a plugin run that fails open on timeout or does not.
5. **[PROPOSED] Telemetry opt-out check + the existing "doctrine freshness" gate pattern.** `docs/research/OFFTHESHELF_VS_BLARAI.md` section 6 (#1748, permanent control) and `docs/TEST_GOVERNANCE.md` (gate tests that fail on drift). A tiny test that fails if the OpenVINO consent file is absent or not `0` in any build environment would be a "tested off" control; the file value is `0` today (I read it).
6. **[PROPOSED] Cold gate protocol + the encryption microbenchmarks.** `docs/adrs/ADR-047-Model-Evaluation-Protocol-Cold-Gate-Pre-Registration-and-Visible-Retractions.md` and the 2026-06-05/06 encryption entries in `PERFORMANCE_LOG.md`. The 2026 encryption numbers state no variance or thermal condition; a re-run under ADR-047 would make them comparable with later entries. Low cost: they are CPU-only.
7. **[PROPOSED] Welded-scope readers + the permission profile.** `docs/runbooks/what_blarai_is_allowed_to_do.md` and the claim register rows 6, 7. Make the permission profile also print each welded scope and the file that welds it, so the Knowledge Map can quote a live statement instead of a docstring. Observable: profile output lists URL ingest and images as "welded" with `enabled = false` paths.
8. **[PROPOSED] Corpus accuracy programme + hybrid-retrieval A/B.** `docs/research/corpus-extraction-contract-2026-09-23.md` and the 2026-07-10 and 2026-07-21 entries in `PERFORMANCE_LOG.md`. The corpus tier needs "purpose-built candidate generation", not the exact scan, but the A/B lesson (common-word noise buries gold hits) applies to its keyword limb; measure it with the same 24-query method on a corpus slice.
9. **[PROPOSED] NPU embedding device + the contention caveat.** `PERFORMANCE_LOG.md` 2026-07-02 entry (13.6x on the NPU) and the 2026-07-10 hybrid-retrieval entry (served on CPU because of live-AO NPU contention). Idea: log, at app start, which device actually served the embedder, so no future retrieval measurement silently runs on the wrong device. Hypothesis: fail-soft to CPU may happen in production too; I did not check.
10. **[PROPOSED] Egress block for the coder + the egress guard.** `docs/adrs/ADR-045-Coder-Containment-Account-Level-Fused-Leg-and-WFP-Egress-Block.md` and `docs/adrs/ADR-020-Code-Enforced-Egress-Kill-Switch.md`. Same rule shape (loopback permitted, rest denied) at two layers by two mechanisms; the existing map already notes this (its connection 5). Add to the Card B table of locks a column "enforced by OS or by program" (lesson 236 vocabulary).
11. **[PROPOSED] Vestigial receipt code + the image-isolation deferral.** `docs/adrs/ADR-041-Host-Mode-Action-Authorization-Boundary.md` and `docs/adrs/ADR-022-Isolate-Untrusted-Image-Handling.md`. Both record "built or designed for a topology that is not live"; add a "what has to be true for this to wake up" line to each, with an observable, so neither silently rots into an unreachable control.

## Corrected claims (for these topics)

| What was claimed | What replaced it | Where (status) |
|---|---|---|
| The deterministic checker is "150 lines" | About 300 lines: class spans lines 578-873 of `gpu_inference.py` (my count today, about 296); the OFFTHESHELF study says "about 300 lines, not 150" | `docs/research/OFFTHESHELF_VS_BLARAI.md` section 5; the AGT verdict (2026-09-16) still says 150 and the shipped file has grown since. *As of 2026-10-11 (my recount): class lines 578-866, about 289; `check` 712-866, about 155.* |
| Claim register evidence cites `gpu_inference.py:349`, `:459-613`, `:403` | Class now opens at 578, `check` at 712, allowlist constant at 656 | `docs/governance/trust-spine-claim-register.md` rows 1 and 5; line numbers stale (a row pointing at stale evidence is the failure the register itself warns of, row 3). |
| `[knowledge].images_enabled = false` is at `default.toml:196` and `[web_search].enabled` at `:214` | Line 241 and line 259 today | Claim register rows 5 and 7; stale line numbers. |
| The outbound payload screen guards all allowlisted outbound payloads | It is a control against plaintext-socket exfiltration only; never invoked for HTTPS; two fail-opens found and fixed | Claim register row 12 (corrected 2026-09-18, #1592). |
| The two egress layers read the same allowlist because exactly one adjudicator is registered | A runtime invariant since 2026-09-20 for every purpose but operator-paste | Claim register row 3 (#977 CLOSED by #1586; superseded text kept visible). |
| The Policy Agent signed-receipt boundary is the live root of trust | Vestigial; slated for removal; the live boundary is the deterministic plane | ADR-041; USE-CASE-001 amendment; claim register row 25. The earlier text of USE-CASE-001 remains in the same file. |
| The Policy Agent's model judged the dangerous cases on the 4B/9B arms | No model was ever shown the command (schema check rejected the field) | ADR-044; `docs/research/qwen35-9b-int8-verdict-2026-10-04.md`; `PERFORMANCE_LOG.md` 2026-10-04 entry has a visible correction. |
| "Egress machinery is BUILT and DORMANT; external allowlist is empty" | Allowlist holds `kagi.com` since 2026-07-02; `web_search` is LIVE | `docs/security/egress_activation.md` and `docs/security/egress_machinery.md` headers (still dormant wording); ADR-027 header "NOT YET ACTIVE" with the activation record appended at line 264. Status: stale text in repository. *As of 2026-10-11 the ADR-027 header and both guides carry a dated status block and a dated-history banner; the original text is kept.* |
| Speculative decoding is "~2x throughput" | Measured 1.25x median (2026-05-21, correcting an earlier "~2x" as overstatement), 1.60x clean pass (2026-09-22), 1.48x contaminated pass; March figure 2-3 versus about 10 tokens/s was an older stack and draft | `CLAUDE.md` stack section says "~2× throughput"; `PERFORMANCE_LOG.md` entries above. Not edited here. |
| The 14B is faster than competitors' 7B to 9B models (25 tokens/s) | 25 tokens/s was a 16-token short-prompt run; like-for-like 13.9 and 8.7; competitor figures are from other chips; no ordering established | `OFFTHESHELF_VS_BLARAI.md` section 5. |
| OpenClaw has about 3,600 security advisories | 722 in about nine months (the first count read the same 100 records 36 times) | `OFFTHESHELF_VS_BLARAI.md` section 4. |
| The Qwen3.6-27B/35B "thinking toggle" is the hardest swap blocker | Withdrawn: the probe's chat template caused the behaviour | `docs/MODEL_EVALUATION_QWEN36_27B.md` banner (2026-09-22); status snapshot in `CLAUDE.md`. |
| 14B injection numbers (agentic suite) | RETRACTED and ATTRIBUTED (#1622) | `CLAUDE.md` status snapshot; PERFORMANCE_LOG 2026-09-22 evening entry. |
| Past: 3 searches per fingerprint | 1 per fingerprint since 2026-09-19 | `docs/DECISION_REGISTER.md` (#1594); `default.toml` reads 1. |
| Past: the Alpine guest is dormant infrastructure | The guest oracle is live; the parser is dormant | `docs/research/encryption-and-isolation-evaluation-2026-07-20.md` section 3.3 (as quoted in the existing map). |
| ADR-022 as "self-modification taxonomy" | That is devplatform's ADR-022; BlarAI's ADR-022 is image-handling isolation | Number collision noted in ADR-036 ("cross-repo"); always repo-qualify. |
| A hybrid (vector plus keyword) retrieval always beats vector-only | On 35 docs hybrid was below vector-only until the stopword fix; at the consumed depth (top 4) they now tie | `PERFORMANCE_LOG.md` 2026-07-10 and 2026-07-21 entries. |
| The claim "Policy Agent adjudicates every action" | The service adjudicates nothing on the live path; the in-process function does | AGT verdict "Outcome first"; ADR-041. |

## What I could not verify
- Any Vikunja ticket's text or current state (#910, #1683, #1748, #1682 and others are cited from files only).
- Whether #910's removal has happened beyond the files still being present today.
- The body of `docs/design/1592-outbound-content-control-design-2026-09-18.md` and `1595-provenance-constrained-egress-design-2026-09-20.md` (only their file names and the register's references).
- Hugging Face dataset upload status for the performance data.
- Current sizes and content of `sessions.db` and `substrate.db` (never opened).
- Whether `docs/INDEX.md` lists any of the files cited here.
- The origin of the community llama.cpp figures in the 2026-06-27 entry.
- That the isochronous-retrieval timing defence in USE-CASE-002 is implemented.
