# CAVA, Microsoft Agent Framework, and BlarAI's trust spine: comparison and mapping

*Written 2026-09-16. Companion to the grounding read in `cava-and-microsoft-agent-framework-grounding-2026-09-16.md`, which says what each external thing is. A third document, `pcaa-placement-and-blarai-mapping-2026-09-16.md`, places PCAA (CAVA's parent paper) against Microsoft's full stack and against BlarAI, and extends the proposed next steps to eleven items. This document says how they relate to each other and to what BlarAI already has on disk. Everything about BlarAI below was read from code and config at commit `0750d506`, with file references, not from memory or doctrine.*

## Outcome first

Three things fall out of the mapping.

1. **CAVA and Agent Framework are not rivals. They sit at different layers.** CAVA is a proposal for *what object* an approval should bind to (a hashed canonical action). Agent Framework is a *runtime* with seams where such a check could run. You could implement CAVA's idea inside Agent Framework's Agent Hooks, or inside BlarAI's tool loop. Comparing them head to head is a category mistake. The useful comparison is each against BlarAI.

2. **BlarAI is structurally stronger than either on the outer perimeter and weaker than both on the inner receipt.** Neither CAVA nor Agent Framework has anything like the process-wide socket guard, the import scan, the single exempted door, or signed weight manifests. Those are structural-absence controls and they are the project's real advantage. But at the point where a human says yes to a risky action, BlarAI binds that yes to a tool *name*, writes no signed receipt, and rests the agreement between its two egress layers on one boot-time check that the code itself labels open (#977). CAVA's entire thesis is about exactly that inner point, and the Agent Framework's FIDES and Hooks both bind approvals to the resolved invocation.

3. **Adopting Agent Framework as BlarAI's runtime is not recommended. Borrowing three ideas is.** The framework is Foundry-first, its two deterministic security layers are Python-only and experimental, it has no OpenVINO provider, and its general-purpose surface area is the opposite of structural absence. The ideas worth taking are CAVA's fingerprint-bound approval lease, FIDES's confidentiality axis, and Agent Hooks' verdict-gated persistence. Each is a hardening of an existing capability, not a new one. They are marked [PROPOSED] in the last section and nothing has been built.

## What was compared

For each of the controls that make up BlarAI's trust spine, the question asked was: what does CAVA say this should look like, what does Agent Framework offer for it, and what does BlarAI actually have. The BlarAI column comes from the code, with the load-bearing lines cited under Sources. The key BlarAI surfaces are:

- The tool-loop dispatch check, `_adjudicate_tool_dispatch` in the Assistant Orchestrator entrypoint, which builds a Canonical Action Representation (CAR) from the tool name plus the canonical JSON of its arguments and runs the Policy Agent's `DeterministicPolicyChecker` in-process before any tool executes.
- The one egress door, `shared/security/guarded_fetch.py`, with a singular adjudicator slot whose input is a URL and a purpose string.
- The per-turn operator envelope, `services/assistant_orchestrator/src/egress_envelope.py`, armed by Windows Hello fingerprint, keyed by session id and a search counter.
- The escalation consent path, `shared/security/escalation_consent.py`, whose context object carries a rule label, a tool name and a human-readable summary by design, and no argument payload.
- The signed, hash-chained audit log, `shared/security/audit_log.py`, with an HMAC or TPM signer.
- The provenance and datamarking layer in `context_manager.py`, with two trusted tiers (local, memory) and three untrusted tiers (external, knowledge, web) and the Layer-3 action lock.
- The armed socket guard, the outbound exfil screen, the import scan, and the signed manifests.
- ADR-041, which states the live boundary: the deterministic plane is live, the Agentic-JWT hybrid adjudicator is built but vestigial.

## CAVA against Agent Framework

| Dimension | CAVA | Agent Framework |
|---|---|---|
| What it is | A paper describing a normalisation-and-hashing layer inside one vendor's product | An open-source runtime SDK from Microsoft, 1.0 since April 2026 |
| Unit of governance | The canonical action: a small record of runtime, tool, operation, category, systems touched, reversibility, target, hashed with SHA-256 | Whatever the developer puts in middleware or an interceptor; the framework hands over tool name and arguments, not a normalised action |
| Approval binding | To the fingerprint. An approval is a lease that expires if target, actor, session, policy or receipt digest changes | Tool approval binds to a specific function call in a session. FIDES consumes a grant once and re-asks if resolved content changes. Hooks re-asks if a transform changes approval-bound arguments |
| Receipt | Deterministic receipt hash, independently recomputable; optional signatures, credentials, ledger anchoring | Audit records from FIDES and Hooks are payload-free decision records; no hashing or signing specified |
| Cross-runtime normalisation | The whole point: shell, MCP, browser, hosted trace all project to one object | None. Hosted tools executed server-side by a provider bypass the tool seams entirely (Hooks page says so) |
| Untrusted content | Boundary and data context feed the Semantic Pattern Layer, but labelling is out of scope | FIDES: two-axis labels (integrity and confidentiality) propagated most-restrictive-wins through tool calls, enforced before sinks run |
| Enforcement depth honesty | Explicit: observe, warn, approval-gate, dual control, quarantine, external assurance; observe-only must never be sold as blocking | Explicit: Hooks has enforce versus evaluate-only and says not to describe evaluate-only as enforced |
| Maturity | Single-author vendor preprint, benchmark authored by the author; the open-core package is about 1,100 lines of JavaScript with seven tests, Apache-2.0 | GA runtime with weekly releases; the security layers specifically are experimental and Python-only |
| What it does not do | Does not decide authority, does not run anything, does not label content | Does not normalise actions across runtimes, does not sign receipts, does not restrict the process's network at all |

The two are complementary. CAVA would be the object type; Agent Framework's Hooks would be one place to compute and check it.

## Mapping against BlarAI's trust spine

Each row is one BlarAI control. The last column is my reading of the gap, if any. "Derived" means I concluded it from the code, not that any document says it.

| BlarAI control | Action identity at the lock | CAVA's view | Agent Framework's nearest equivalent | Gap (derived) |
|---|---|---|---|---|
| Tool-loop dispatch check | Tool name plus canonical sorted-key argument JSON, built into a CAR that defines `canonical_hash()`, which this path never calls | Close to a canonical action already: CAR has source, destination, verb, resource, sensitivity, session. Missing CAVA fields: risk category, systems touched, reversibility, target as a first-class field | Function middleware; Hooks `pre_tool_call` | Small. The CAR is CAVA-shaped. The hash method exists but is never computed on this path, and nothing downstream consumes it (see receipt row) |
| Egress door adjudicator | URL and purpose string only | Too thin. No actor, session, tool, or argument context reaches the door; the adjudicator cannot know which turn or which tool call it is serving | FIDES sink policy (`max_allowed_confidentiality`) sees the full labelled context | Real. The door's action identity is a URL. That is the "display string" CAVA warns against, in a mild form |
| Two egress layers, one slot, first-wins | The agreement that both layers read the same `kagi.com` allowlist rests on one `if active_url_adjudicator() is None` check at boot plus two unit tests of that check | CAVA's "parser capture" and "policy degradation" threats apply directly: which adjudicator holds the slot is not itself a governed, receipted event | Hooks installs agent, chat and function parts as one bundle and rejects stacked bundles, so a partial boundary cannot be configured by accident | Real and already known: #977 OPEN. The doctrine-freshness test says in its own docstring that this composite claim is not mechanically checkable and needs an executable boot-time posture check |
| Per-turn operator envelope | Session id, a counter, a latched-denied flag. The query is *shown* to the operator but not *bound* | CAVA's Action Gate Lease is the same idea done fully: lease bound to fingerprint, actor, session, destination scope, policy version, receipt digest, time window | Harness standing approvals; FIDES single-use grant bound to the resolved invocation | Real. One Hello touch covers up to three searches, and the second and third queries are different strings under the first approval. This is a documented LA decision (N=3, 2026-07-02), so it is a posture choice, not a defect. But the *first* query is not bound either |
| Escalation consent ("ask") | Rule label, tool name, safe summary. Explicitly no arguments, no argument hash, no nonce. Summary is literally `EXECUTE tool:<name>` | This is CAVA's approval-drift case: the operator approves a surface description and a different argument set could execute. CAVA's answer is to bind to a hash of the canonical action, which leaks nothing | Tool approval shows name and arguments to the human and binds the response to that call content; FIDES additionally re-asks if resolved content changes | Real. The no-payload rule is correct and should stay. But a SHA-256 of the canonical arguments is not payload, and the CAR already defines one (`canonical_hash()`), uncalled on this path. Binding the approval to `car_hash` closes drift without showing the operator anything new |
| Signed audit chain | Hash-chained, signed, append-only, fail-closed. Live for ingest. Wired to the hybrid adjudicator, which ADR-041 says is vestigial | This is exactly CAVA's receipt layer, and it is stronger than anything CAVA ships (a TPM signer). CAVA's ablation says removing the receipt verifier collapses the whole claim | Neither FIDES nor Hooks signs anything | Real and the most striking finding: the machinery exists one layer over, and the two *live* doors (tool dispatch, guarded fetch) emit log lines only. No signed record says what was allowed, denied or escalated at runtime |
| Provenance and datamarking | Five-tier provenance (two trusted, three untrusted), per-load random marker prefixing every line, unknown source fails closed to untrusted, Layer-3 lock refuses non-safe tools under untrusted content | Out of CAVA's scope | FIDES is the direct comparison. FIDES has two independent axes; BlarAI has one (integrity). FIDES propagates labels *through tool calls* into results; BlarAI labels *grounded context* and locks the tool loop, but a tool's *result* is not itself labelled and re-propagated | Partial. BlarAI's integrity story is as strong as FIDES's and better on the injection side (datamarking, delimiter neutralisation, injection scan). BlarAI has no confidentiality axis: nothing marks "this came from the encrypted knowledge bank, it must not leave through web_search". Today that is prevented by the exfil screen (pattern-based) and by there being one narrow egress scope. As scopes open, a label-based rule is the deterministic version |
| Socket guard, exfil screen, import scan | Address family, address and port; payload bytes; import names | CAVA has nothing here and explicitly does not assume inline interception | Agent Framework has nothing here. Its own docs say Hooks is "cooperative rather than a process isolation boundary" | None. This is where BlarAI is ahead of both, and by a wide margin |
| Signed weight manifests, at-rest encryption | Per-chip TPM-sealed keys | CAVA's "hardware-rooted" attestation substrates are optional extras; BlarAI has them as boot preconditions | Not in scope for Agent Framework | None |
| Streaming and persistence gating | Tool results are never spliced raw into context; a denied egress ends the turn | Not in CAVA's scope | Hooks buffers the whole response until the output verdict, and gates history persistence on the covering verdict, so a denied output is never persisted | Worth checking, not asserted. I did not trace whether a turn that is denied mid-stream has already persisted partial assistant text to the encrypted session store. If it has, that is the Hooks "verdict-gated persistence" gap |

## What BlarAI has that neither of them has

This deserves its own paragraph because the comparison above could read as a list of deficits. It is not.

- **Structural absence.** The runtime cannot import an HTTP client outside one file. The process cannot open a non-loopback socket outside an allowlist, and name resolution is pinned. Agent Framework is a general SDK whose reference agents talk to Foundry by default. CAVA assumes actions will happen and asks how to describe them. BlarAI assumes most actions cannot happen at all.
- **A single door with an empty-by-default slot.** No adjudicator registered means every fetch is denied. The Agent Framework's equivalent default is "no middleware, everything runs".
- **Hardware-rooted preconditions.** Signed manifests verified at load, TPM-signed audit records, at-rest encryption from creation. CAVA lists these as optional attestation substrates a buyer might add.
- **Datamarking with delimiter neutralisation.** FIDES hides untrusted bytes behind a variable reference, which is stronger in one way (the main model never sees them) and weaker in another (the agent works on summaries from a second model). BlarAI lets the model read the content but marks every line and locks the tool loop. Both are defensible; BlarAI's is cheaper on a 31 GB machine.

## The three gaps, stated plainly

These are the findings a reviewer would put at the top. Each is a hardening of an existing capability, so under the decision boundary they are mine to design and the LA's to accept as posture. None has been built.

**Gap A. Approvals bind a name, not the action.** When the Policy Agent escalates and the operator approves, the approval is for `EXECUTE tool:web_fetch`, not for the specific arguments the model produced. The CAR built at the dispatch check already defines the hash that would bind it (`canonical_hash()`); nothing on the live path computes it, and its only caller is the vestigial hybrid adjudicator. The escalation context's no-payload rule is right and must not change; a hash is not payload. This is CAVA's core claim and both Agent Framework security layers already do it.

**Gap B. The live doors write no receipt.** The tool-dispatch check and the guarded-fetch door log to the application logger. The signed, chained audit log is wired to ingest and to a vestigial path. So there is no tamper-evident record of what the runtime allowed, denied or escalated, which is the one thing CAVA's ablation says you cannot remove. Wiring the two live doors to the existing `AuditLog` with the CAR hash as `car_hash` is plumbing, not design.

**Gap C. The one-slot agreement is not a runtime invariant.** #977 is already open for this. CAVA would call it policy degradation: a change to which adjudicator holds the slot is not itself a governed, receipted event. Agent Framework's Hooks answer is a bundle that cannot be partially installed. BlarAI's own test docstring says the fix is an executable boot-time posture check, not a lint.

A fourth item is a question, not a finding: whether a denied egress mid-turn can leave partial assistant text already persisted. That needs a trace of the session-store write path against the deny branch, which I did not do.

## Should BlarAI adopt Agent Framework as its runtime?

No, and I am reporting this as a settled technical call rather than an option. The reasons, in order of weight:

1. **It contradicts structural absence.** Adopting a general agent SDK brings its whole provider, tool and hosting surface into the runtime tree. The import scan would have to exempt it. That trades a one-file egress exemption for a package-tree exemption.
2. **The security layers that would matter are experimental and Python-only.** FIDES and Agent Hooks both carry experimental warnings and both say their API can change before general availability. BlarAI's controls are gate-locked; building on a moving experimental contract would put the trust spine on someone else's release cadence.
3. **No OpenVINO provider.** The local paths are Ollama, Foundry Local and ONNX Runtime GenAI. BlarAI's brain is OpenVINO GenAI with speculative decoding on Arc. A custom chat client would be needed on day one, which removes most of the value of adopting a framework.
4. **Foundry-first framing.** Every quick-start and the reference harness default to Azure identity and Foundry endpoints. The docs are honest that third-party models are "at your own risk". BlarAI is the third party.
5. **Weekly releases and a wide dependency tree** are the wrong shape for a decades-horizon local system whose gate is measured in the tens of minutes.

Where the framework *is* useful is as a reference for how a mature team designed the same seams: the interception-point list, the buffered-output rule, the verdict-gated persistence rule, the single-bundle rule, and FIDES's two-axis label algebra are all worth reading against BlarAI's code when each of those seams is next touched.

## Should BlarAI adopt CAVA?

Not as software. The open-core package (`github.com/OndCo/CAVA`, Apache-2.0, npm `osuite-cava-core` 0.1.2) is about 1,100 lines of JavaScript with seven tests. BlarAI's runtime is Python. Its receipts are unsigned hashes where BlarAI's are TPM-signed. Its primitives, a canonical hash, receipt verification and approval binding, are ones BlarAI already has or is designing. The benchmark is the author's. Two files are worth reading as references when the receipt work is built: `verify.js`, whose approval binding refuses on hash mismatch, action-id mismatch, semantic-key mismatch or a reusable scope; and `schema.js`, whose required fields are exactly the ones BlarAI's CAR lacks.

The vocabulary and discipline worth taking:

- The canonical action fields BlarAI's CAR lacks. The open package requires `runtime`, `operation`, `category`, `systems_touched` and `reversible`, with `target` optional; BlarAI's CAR has none of `category`, `systems_touched`, `reversible` or `target` as first-class fields. All four already appear in BlarAI's `RiskTier` and tool metadata in some form; lifting them into the CAR makes the hash mean more.
- The action gate lease: an approval bound to fingerprint, actor, session, scope, policy version and a time window, expiring on any change. This is the envelope plus Gap A done properly.
- The claim register: a numbered table of what the trust spine claims, what evidence supports each claim, and the stated limitation. BlarAI's table is `docs/governance/trust-spine-claim-register.md`. This is also the shape a governance-certification portfolio wants.
- The enforcement-depth disclosure: observe, warn, approval-gate, dual control, quarantine, external assurance, carried in the evidence itself. BlarAI's runbooks carry it per scope; the audit record does not carry it per decision.

## [PROPOSED] next steps

Each of these is within an already-approved capability. None opens a door, lowers quality, or changes a posture, so under the decision boundary I could proceed on any of them. They are listed rather than started because together they touch the trust spine, and the order of work is the roadmap's (`docs/ROADMAP.md`).

1. **Wire the two live doors to the signed audit log** (Gap B). Plumbing. Regression lock: a test that drives a real tool dispatch and asserts a chained, signed record with the CAR hash exists. Ticket-sized.
2. **Bind escalation approval to the CAR hash** (Gap A). Add `car_hash` to `EscalationContext` as a descriptor (it leaks nothing), have the tool loop verify the approved hash equals the dispatched hash before execution, and fail closed on mismatch. Regression lock: approve one argument set, dispatch another, assert refusal. Ticket-sized. This does not change N=3 or the envelope's behaviour, which are LA decisions.
3. **Executable boot-time posture check for the adjudicator slot** (Gap C, #977). Already ticketed; this comparison is more evidence for it.
4. **Extend the CAR with CAVA's missing fields** so the hash carries category, systems touched, reversibility and target. Design work; changes what `canonical_hash()` covers, so needs the audit-chain implications thought through before any code.
5. **A confidentiality axis on provenance**, FIDES-style, so knowledge-bank content carries a label that a future egress sink can refuse deterministically. Design work. Becomes important the moment a second egress scope opens; until then the single scope plus the exfil screen hold it.
6. **Trace the deny-mid-stream persistence path** to answer the fourth item. Read-only investigation, one session.
7. **A trust-spine claim register**, CAVA-shaped: landed as `docs/governance/trust-spine-claim-register.md` (#473). Items 1 to 6 are not started; items 1 and 2 are ticketed as #1542 and #1541.

Items 1, 2 and 6 are the ones I would start with if told to proceed. They are cheap, they close the gaps a reviewer would name first, and they do not change any decision the LA has made.

## What was not verified

- Agent Framework's source. Everything about it here is from Microsoft's documentation and package registries.
- Whether BlarAI's session-store write can land partial text before a mid-turn deny.
- The ADR-027 header still reads "NOT YET ACTIVE" against a scope that went live on 2026-07-02. That is a stale-banner defect in the ADR, noted here, not fixed.

  *Note as of 2026-10-11 (the bullet above is kept as written 2026-09-16):* the ADR-027 header text itself is unchanged and is now marked as dated history; a "Status as of 2026-10-11" block at the top of `docs/adrs/ADR-027-Egress-Policy-Network-Facing.md` states that the `web_search` scope has been live since 2026-07-02 and what holds the operator-pasted URL class shut.

## Sources on disk (BlarAI, commit `0750d506`)

`services/assistant_orchestrator/src/entrypoint.py` (dispatch check from line 302, first-wins guard near 6365, tool loop near 6790 to 7000) · `shared/security/guarded_fetch.py` (slot at 376, adjudicate at 615) · `services/assistant_orchestrator/src/egress_envelope.py` · `shared/security/escalation_consent.py` (context at 82) · `shared/security/audit_log.py` (append at 769) · `shared/schemas/car.py` · `services/policy_agent/src/gpu_inference.py` (checker at 349, allowlist at 403) · `services/ui_gateway/src/url_adjudicator.py` · `services/assistant_orchestrator/src/context_manager.py` · `shared/security/egress_guard.py` · `shared/security/exfil_screen.py` · `tests/security/test_no_external_egress.py` · `tests/security/test_doctrine_freshness.py` (lines 33 to 39 on why #977 is not lint-checkable) · `services/assistant_orchestrator/config/default.toml` (`[web_search]`, `[egress]`, `[knowledge]`, `[security]`) · `docs/adrs/ADR-041-Host-Mode-Action-Authorization-Boundary.md` · ADR-013, ADR-020, ADR-021, ADR-023, ADR-027, ADR-029, ADR-039.

External sources are listed in the grounding document.
