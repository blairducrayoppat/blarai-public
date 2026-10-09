# PCAA: is it a rival to Microsoft Agent Framework, and how does it map to BlarAI

*Written 2026-09-16. Third document in the set. The grounding read covers CAVA and Agent Framework; the comparison covers those two against BlarAI's trust spine. This one places Proof-Carrying Agent Actions (PCAA) against Microsoft's full stack and against BlarAI. BlarAI facts are the ones verified on disk in the comparison document, at commit `0750d506`.*

## What was read

- The attached paper in full, all 25 pages: `Proof-Carrying Agent Actions: Model-Agnostic Runtime Governance for Heterogeneous Agent Systems`, arXiv 2606.04104v1, submitted 2 June 2026, sole author Zexun Wang, Ond Holdings Inc. It is the parent of the CAVA paper.
- Because PCAA names Microsoft's Agent Governance Toolkit (AGT) as a subordinate "external governor", I also read the AGT repository README and FAQ, Microsoft's 14 May 2026 post positioning AGT against Agent Framework, and the 2 June 2026 Agent Control Specification post. AGT's source is read in the fourth document.
- The publisher's public artefacts for PCAA's implementation and corpus: the `osuite` SDK from npm (2.9.9), the `OndCo/OSuite-Governed-Agent-Examples` repository (5 August 2026), and the `OndCo/Agent-Action-Boundary-Benchmark` repository (4 September 2026). Their tests and benchmarks were run locally; the results are in the section on the implementation and the corpus below.

Not read: the OSuite Studio service that the SDK calls. Its repository (`OndCo/osuite`) is private.

## Outcome first

**No, PCAA is not a rival to Agent Framework.** They are two layers apart. Agent Framework builds and runs agents. PCAA is an authority-and-proof layer that sits above *any* runtime and says, in its own words, "PCAA is not a replacement runtime." In PCAA's own taxonomy, Agent Framework is a "framework SDK runtime" with an "inline SDK" adapter mode, meaning it is one of the things PCAA would attach to.

**PCAA's real Microsoft neighbour is the Agent Governance Toolkit**, which Microsoft positions as the "govern and audit" layer above Agent Framework's "build and orchestrate" layer. Even there, PCAA claims to sit one level higher still: it absorbs AGT's stage receipts "without surrendering final authority". So the honest rivalry is PCAA versus AGT on audit, approval and decision records, and PCAA's distinguishing claims are the things AGT does not do: externality context, approval-enforceability classes, proof for actions that never executed, replay with drift detection, and an explicit final-authority field.

**For BlarAI, PCAA is a pattern to borrow, not software to adopt, and it fits better than Agent Framework does.** BlarAI already *is* a deployer-owned route-review-prove loop for one tenant. PCAA describes what BlarAI has built more precisely than BlarAI's own documents do, and it names the parts BlarAI has not built. Neither PCAA's product (a hosted control plane) nor Agent Framework belongs inside the BlarAI runtime. The question "along with or in replacement of Agent Framework" dissolves: Agent Framework was never going in, and PCAA goes in as vocabulary and design, not as a dependency.

## What PCAA is, in its own terms

PCAA treats the **action certificate** as the primary trust object. For a raw action *a*, the certificate is a tuple of: the portable action envelope, runtime-stage receipts, approval receipts, replay-and-proof state, and integrity references. The method is three words: route, review, prove.

The operational form is a **five-checkpoint contract**, each with an SDK method:

| Checkpoint | Method | Purpose |
|---|---|---|
| Pre-action admissibility | `guard` | Allow, warn, block, simulate-first, or approval-gate before side effects |
| Action open | `createAction` | Create the stable trust object everything else attaches to |
| Assumption capture | `recordAssumption` | Preserve what the runtime believed at decision time |
| Approval | `waitForApproval` | Pause execution when policy requires a human |
| Outcome closure | `updateOutcome` | Write result, evidence and closure status for replay |

Three additions the paper says came from deployment:

- **Externality context.** Admissibility depends on the boundary crossed, not just the verb: destination type, visibility and ownership, tenant provenance, account provenance (company, personal, unknown), client provenance, whether it is an external write, sensitive-payload posture, reversibility, and approval enforceability.
- **Approval enforceability classes.** An approval is labelled `pre_execution_gate`, `observe_only`, `delegated_runtime_control`, or `runtime_controlled`, so a reviewer can tell a real fail-closed gate from post-hoc visibility.
- **Non-execution proof.** Blocked, paused and aborted actions still close into a receipt (`non_execution_proof`, `pending_execution_proof`, `partial_execution_proof`), rather than vanishing as missing logs.

Supporting ideas: a **neutral runtime contract** (family, adapter mode, execution boundary, authority split, session and receipt projection) with an honest interception-depth scale from inline SDK (strong) to observer (weak); a **three-way authority split** (workspace, runtime, external governor); **replay with drift checks** that recompute envelope, risk, policy snapshot and manifest and fail on mismatch; and a **receipt completeness** ratio.

### The evidence, and how to weigh it

A protected corpus of 24 seed templates replayed across four runtime families into 96 traces. PCAA scores 1.000 on exact accuracy, macro-F1, severe recall and block precision against static rules (0.583 accuracy) and a scalar heuristic (0.375). Ablations: removing externality context drops accuracy to 0.875; removing enforceability handling to 0.917; removing the integrity lane leaves routing intact but collapses manifest stability to 0 and proof closure to 0.708. Mean latency 0.35 ms.

Read with the same caution as CAVA, and the paper asks for it: the corpus is withheld, the baselines are weak by construction, the author built both the system and the benchmark, and the paper says "some empirical claims should be treated as historical baseline results rather than statements about the current system state." The ablation pattern is the useful part. It shows routing, review and proof are separable failure modes, which is a design argument, not a performance one.

### The implementation and the corpus, verified

The paper's reference implementation is the OSuite product. What is public of it, and what each public piece is, read from source and run locally:

**The SDK is a thin client for a hosted service.** `osuite` on npm (MIT, version 2.9.9, twelve releases since 2.8.0, no dependencies, 519 lines in the main module) exposes the paper's five checkpoint methods by name: `guard`, `createAction`, `recordAssumption`, `waitForApproval`, `updateOutcome`. Every one of them is an HTTP call to a base URL the caller supplies, with an API key: `guard` posts to `/api/guard`, `createAction` to `/api/actions`, `recordAssumption` to `/api/assumptions`, `updateOutcome` patches the action, and `waitForApproval` polls the action until it carries an approver. The only decision logic in the client is recognising a 403 whose body says `block`. Routing, review posture, externality evaluation, enforceability classes, replay and proof closure all happen server-side, in a service whose code is private and whose default endpoint is `studio.osuite.ai`. So the PCAA "reference implementation" cannot be verified from outside beyond its API shape.

**The open reference is small and local.** `OndCo/OSuite-Governed-Agent-Examples` holds a 241-line core (`governed-action-core`, Apache-2.0, no dependencies) that implements the paper's object chain end to end without a server: an action envelope whose `action_hash` is a SHA-256 over a canonicalised action; an approval lease bound to that hash, carrying reviewer, decision, issue time and a time-to-live, itself hashed; an outcome receipt with status `completed`, `failed`, `skipped` or `blocked`, hashed; and a proof bundle whose hash chains the envelope, lease and outcome hashes. `verifyApprovalLease` refuses on hash mismatch, on any decision other than approved, and on expiry. A mock reviewer stands in for the `guard` checkpoint. Its six tests pass locally. This is the five-checkpoint contract and the proof model in minimal form. Absent from it, as from every public piece: the externality context, the approval-enforceability classes, the four non-execution proof types, replay-with-drift checks, and receipt completeness. Those exist only in the paper's description of the hosted product.

**The paper's corpus is not public, and the public corpus is a different one.** Nothing matching the paper's 24 seeds, 96 traces, four runtime families and 24/20/28/24 decision buckets exists in any public repository, and the paper says it is protected. What the publisher released instead, three months after the paper, is `OndCo/Agent-Action-Boundary-Benchmark`: a thirteen-record hand-written approval-execution-drift set (eight runtimes, outcomes allow, require review or block, each with named drift classes) and a 6,000-record synthetic corpus generated deterministically from a seed across twenty runtime surfaces, 46 scenario families, six locales and ten obfuscation styles. The benchmark cites PCAA once, as related research; it does not claim to reproduce the paper's tables, and its metrics (exact match, risky protection, safe-baseline allow) are not the paper's (macro-F1, severe recall, review burden, manifest stability, receipt completeness).

**What running it shows.** Both benchmarks reproduce their published numbers exactly on this machine: 13 of 13 and 6,000 of 6,000 exact matches for the reference runner, and the four baselines at 16.7, 76.3, 60.8 and 71.9 percent exact match. The reason the runner scores 100 is visible in the code: the generator assigns each record's expected control from a fixed table keyed by mutation class, and the runner classifies by detecting drift over the same six material fields (runtime, operation, resource, effect, destination, identity). The labels and the classifier are separate files but one design. The repository's README says this itself: the point is not that the runner beats labels built for its own task, but that tool name, runtime label and partial resource matching are not substitutes for an action-boundary object. That is a fair statement of what the benchmark demonstrates, and it is the same demonstration the CAVA paper makes.

**Net.** The PCAA paper's implementation is a hosted product with a public API shape and a small open reference of its object chain; its corpus is private and has no public counterpart. The paper's quantitative claims therefore remain unverifiable from outside. Its design claims are verifiable and hold: the object chain, the hash-bound lease with expiry, the outcome receipt for blocked actions, and the proof bundle all exist as running code, and they are the parts this document maps onto BlarAI.

## Placement against Microsoft's stack

Microsoft now has three named layers plus a specification:

| Layer | Microsoft artefact | What it owns | Status |
|---|---|---|---|
| Build and orchestrate | Agent Framework | Agents, tools, sessions, workflows, middleware seams | 1.0 GA, April 2026 |
| Govern and audit | Agent Governance Toolkit (AGT) | Deterministic policy on tool calls and messages, zero-trust identity, sandboxing rings, kill switch, hash-chained audit, `require_approval` gates | "production-quality public preview", MIT, runs fully offline, five languages |
| Interception contract | Agent Control Specification and Agent Hooks | Eight interception points, canonical policy input, Rego policies | Open spec, June 2026; Hooks experimental in Agent Framework |
| Tenant-visible authority and proof | none | | |

PCAA claims the empty fourth row. The paper reserves "a first-class projection for Microsoft Agent Governance Toolkit" and lists what AGT contributes: runtime-stage receipts at pre-input, pre-tool, post-tool and pre-output, approval receipts, and trust-boundary stages. It then says PCAA "absorbs those receipts without surrendering final authority."

Where the overlap is real: AGT has approval gates, decision records, and a Merkle-chained audit trail. PCAA has approval receipts, action envelopes, and proof bundles with manifest digests. A buyer choosing one for audit would compare these directly. Where PCAA is distinct: AGT's documentation, as read, does not define externality context, enforceability classes, non-execution proof, replay drift checks, or a final-authority field. The Agent Control Specification post explicitly does not discuss action identity, approval binding, or receipt format. Those are the gaps PCAA and CAVA are written to fill.

Where AGT is stronger: it exists as installable, multi-language, Microsoft-stewarded code with six framework integrations, and it runs in-process without cloud. PCAA is one vendor's control plane described in one preprint.

## Mapping PCAA onto BlarAI

BlarAI is a single-tenant, single-operator system, so PCAA's multi-tenant and buyer-facing parts collapse. What remains maps almost one-to-one, and the mapping shows the same three gaps the CAVA comparison found plus two new ones.

| PCAA element | BlarAI today | Fit |
|---|---|---|
| `guard` (pre-action admissibility) | `_adjudicate_tool_dispatch` runs the deterministic Policy Agent checker before any tool executes; the guarded-fetch door adjudicates every URL. Both fail closed | Strong. Enforceability class is genuinely `pre_execution_gate`: the tool loop breaks on deny |
| Route outcomes: allow, warn, block, simulate-first, approval-gate, observe-only | Allow, deny, escalate | Partial. No `simulate-first`, no `warn` as a route. Observe-only does not exist by design, which is correct for BlarAI |
| `createAction` (stable trust object) | A CAR is built per dispatch and discarded after the verdict; its `canonical_hash()` is never computed on this path | Weak. The object exists but is ephemeral. Nothing later can refer to it |
| `recordAssumption` (decision basis) | Nothing. The provenance list and the tool's risk tier exist in memory but are not captured with the decision | Missing |
| `waitForApproval` | Escalation consent (Windows Hello, or the TUI prompt where Hello is unavailable) and the per-turn egress envelope | Strong on enforceability, weak on binding: approval binds a tool name and rule label, not the CAR hash (Gap A in the comparison) |
| `updateOutcome` (closure) | Ingest audit closes with a signed record. The two live doors write log lines | Missing at the doors (Gap B). PCAA sharpens it: a DENY should also close into a receipt |
| Externality context | Destination is encoded as a one-host allowlist plus a scheme carve-out. Sensitive-payload posture is computed by the exfil screen but not attached to any decision. Reversibility, visibility, external-write are not fields | Partial. Adequate while one scope is open. Becomes the deciding factor when a second scope opens |
| Approval enforceability class | Not recorded. It is uniformly `pre_execution_gate` in fact, but nothing says so per decision | Missing as a field; present as a property |
| Authority split | Workspace authority is the LA, exercised through ceremonies, `default.toml` flags and the decision register. Runtime authority is the Assistant Orchestrator. There is no external governor, and ADR-039 forbids BlarAI governing itself | Strong and cleaner than PCAA's model. Authority is recorded per ceremony, not per action |
| Neutral runtime contract and coverage disclosure | Runbooks disclose live versus dormant per scope. There is no per-runtime-family table saying which of BlarAI's execution surfaces (tool loop, egress door, coder-fleet dispatch, vsock services) has inline interception and which does not | Missing as an artefact. I have not traced the coder-fleet dispatch path's interception depth and am not asserting it |
| Replay with drift checks | The audit log verifies chain integrity. Nothing recomputes a decision from stored inputs, because inputs are not stored. The config that produced a decision is not bound into it | Missing |
| Receipt completeness | Not computed | Missing, and low value for a single runtime family |
| Accountability chain | Collapses to LA, LA, AO, LA. The one field that varies, verifier identity (Hello versus the TUI prompt), is captured in the approval result but not persisted to a signed record | Partial |
| Integrity lanes | TPM-signed audit records, signed weight manifests, at-rest encryption | Stronger than PCAA's fast-commitment lane. PCAA's portable and future lanes are irrelevant to a system that never exports proof |

Two observations from the table.

First, **BlarAI is a PCAA loop with the proof half missing at the live doors.** The route and review halves are as strong as anything PCAA describes, and structurally stronger because of the outer perimeter. The prove half is built (the signed audit log) but wired to ingest and to a vestigial path. PCAA's ablation result is the exact prediction for this state: removing the integrity lane leaves routing perfect and collapses proof closure.

Second, **PCAA's non-execution proof is the sharpest new idea for BlarAI.** Today a denied tool call produces a warning log line. The most security-relevant events in the system, the refusals, are the ones with no tamper-evident record. CAVA argued approvals should bind to a hash; PCAA argues denials should close into receipts too.

## Answering the question as asked

**Is PCAA a rival to Agent Framework?** No. Agent Framework is a runtime; PCAA is an authority layer that would sit above it and classifies it as an inline-SDK runtime family. PCAA's actual Microsoft counterpart is the Agent Governance Toolkit, and PCAA positions itself above that too.

**How does it map to BlarAI along with Agent Framework?** Agent Framework does not map to BlarAI as software; the comparison document records the settled call not to adopt it. If one wanted the two together in some other system, Agent Framework would be the runtime, AGT or Agent Hooks the interception seams, and PCAA the certificate that closes each action. BlarAI already has its own versions of the first two, built to a stricter perimeter.

**In replacement of Agent Framework?** There is nothing to replace. But if the question is "which of these should shape BlarAI's next hardening work", the answer is PCAA plus CAVA, not Agent Framework. They describe the governance object; BlarAI's gaps are all in the governance object. Agent Framework describes a runtime; BlarAI's runtime is not the problem.

**Should AGT be looked at?** As a reference only; the fourth document reads its code. It runs offline, is MIT-licensed, and has a hash-chained audit trail and approval gates, so it is the closest shipping artefact to what BlarAI's doors lack. But importing it would add a second adjudicator next to the Policy Agent, which the single-door principle forbids, and a package tree the import scan would have to exempt. Reading its audit-record schema and decision-record shape before designing BlarAI's is worth one session. Adopting it is not proposed.

## [PROPOSED] additions to the next-steps list

The comparison document lists seven proposed items. PCAA adds three. None is started. Items 8 and 9 are hardening within approved capability and are ticketed together with the comparison's items 1 and 2 as #1542 and #1541; item 10 is an investigation; item 11 is a capability change and therefore the LA's.

8. **Close denials and escalations into the signed audit log, not only allows.** Extends item 1 (wire the live doors) so that every verdict, including DENY, produces a chained record with the CAR hash, the rule that fired, and the enforceability class. This is PCAA's non-execution proof.
9. **Attach decision basis to each record**: the exfil-screen detection labels, the provenance set active at the time, the tool's risk tier, and a hash of the effective config. This is `recordAssumption` and makes replay-with-drift possible later without storing payload.
10. **Write the coverage-disclosure table** for BlarAI's execution surfaces: the tool loop, the egress door, coder-fleet dispatch, and the vsock services, each with its interception depth. Read-only. Its main value is finding any surface that is observer-only without anyone having said so.
11. **`simulate-first` as a route outcome.** Some BlarAI tools could support a dry run before a gated execution. This changes what the assistant can do and belongs to the LA.

Items 1, 2, 6 from the comparison and 8, 9 here form one coherent piece of work: give the two live doors a signed, hash-bound, verdict-complete receipt. It is the single change that moves BlarAI from "PCAA loop with the proof half missing" to a complete one, and it changes no decision the LA has made.

## What was not verified

- The OSuite Studio service. Its code is private; only the SDK's API shape and the open reference core were read and run.
- The paper's own corpus and its Tables 8 to 10. No public artefact reproduces them.
- The interception depth of BlarAI's coder-fleet dispatch path and vsock services.
- Whether the audit log's record shape can carry a rule label and enforceability class without a schema change; `append` today takes CAR fields, decision, `rule_engine_passed` and confidence.

## Sources

- PCAA paper, local PDF and https://arxiv.org/abs/2606.04104
- Agent Governance Toolkit repository: https://github.com/microsoft/agent-governance-toolkit
- AGT FAQ: https://github.com/microsoft/agent-governance-toolkit/blob/main/docs/FAQ.md
- Agent Framework and AGT "better together", 14 May 2026: https://devblogs.microsoft.com/agent-framework/governance-at-the-speed-of-agents-microsoft-agent-framework-and-agent-governance-toolkit-better-together/
- Agent Control Specification, 2 June 2026: https://commandline.microsoft.com/agent-control-specification-runtime-governance/
- `osuite` SDK 2.9.9: https://www.npmjs.com/package/osuite (tarball read; `osuite.js`, `cli.js`, `reviewSurface.js`)
- Governed-agent examples: https://github.com/OndCo/OSuite-Governed-Agent-Examples at `fc7a03c` (`packages/governed-action-core/src/index.js`, its tests, `docs/what-this-repo-does-not-open-source.md`)
- Agent Action Boundary Benchmark: https://github.com/OndCo/Agent-Action-Boundary-Benchmark at `85bd2a4` (`benchmarks/`, `lib/boundary-core.mjs`, `lib/corpus-generator.mjs`, `docs/runtime-boundary-benchmark-methodology.md`, `reports/`)
- BlarAI surfaces: as listed in the comparison document, verified at `0750d506`.
