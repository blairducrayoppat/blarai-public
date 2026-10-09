# CAVA and Microsoft Agent Framework: grounding read

*Written 2026-09-16. Grounding only: what each external thing is. The comparison, the PCAA placement and the BlarAI mapping are in the companion documents.*

## What was read

Read in full, not summarised from elsewhere:

- The attached paper, all 35 pages: `CAVA: Canonical Action Verification and Attestation for Runtime Governance of Agentic AI Systems`, arXiv 2607.13716v1, submitted 15 July 2026, sole author Zexun Wang, Ond Holdings Inc. Text extracted locally with pypdf.
- The arXiv abstract page for the same paper, and the arXiv listing of its parent paper, Proof-Carrying Agent Actions (PCAA), arXiv 2606.04104, same author, June 2026.
- Microsoft Learn, Agent Framework documentation: the hub page, the overview, the concepts pages for Harness, Workflows and Middleware, and the capability pages for Security (FIDES), Agent Hooks, Tool Approval, Human-in-the-loop, Checkpoints, Model Providers, and the FAQ.
- The official GitHub repository README and its releases page, the PyPI page for the Python package, and the NuGet page for the .NET package.
- Microsoft's own Agent Framework blog post from BUILD 2026, for the release timeline.
- The CAVA open-core repository, `github.com/OndCo/CAVA`, at its latest commit (6 August 2026): the core package source and tests, the open-core boundary document, the benchmark result file, and the reproducibility artifact for the paper.

Not read: Agent Framework source code. Everything said about the framework below rests on Microsoft's documentation and package registries, not on the code. Per the project's own rule, documentation describes intent, so any later adoption decision will need a read of the source and a local run.

---

## Part 1: CAVA

### One-paragraph version

CAVA is a proposal from a small company (Ond Holdings, product name OSuite) for how to give an agent's *actions* a stable identity, so that when a human approves "push this code" or "refund this payment", the approval is tied to what the action actually means rather than to the exact text the agent happened to produce. The paper's central observation is that the same real-world act can show up as a shell command, a tool call over MCP (Model Context Protocol), a browser click, or a hosted-agent trace, and that rewriting any of those forms can dodge a policy keyed on the literal string. CAVA converts each raw event into a small, versioned, hashable "canonical action" record and binds approvals, receipts and audit evidence to that hash.

### The problem it claims to solve

The paper opens with a governance question: "what action was actually approved, what evidence binds the approval to execution, and can an independent verifier reproduce the same action identity later?" It lists the ways today's systems fail that question:

- **Equivalent syntax bypass.** `git push origin main`, `env X=1 git push origin main`, and `bash -c "git push origin main"` are three strings but one act. A policy matching the first string misses the other two.
- **Wrapper bypass.** `sudo`, `env`, `bash -c`, aliases, helper scripts and SDK indirection hide the real operation behind a harmless-looking first token.
- **Approval drift.** The operator approves one displayed description while a semantically different action executes.
- **Trace ambiguity and evidence laundering.** Observability logs prove something happened, not what was authorised, and downstream systems can produce sanitised after-the-fact records.
- **Parser capture.** One vendor's parser becomes the sole authority on what an action was.

### What CAVA actually is

A seven-stage protocol (the paper says six, then lists seven): Capture, Normalize, Interpret, Fingerprint, Bind, Close, Attest.

The core object is the canonical action, formally `C(a) = (v, r, e, o, k, S, τ, u, m)`: schema version, runtime family, executable or tool identity, normalised operation, risk category, systems touched, reversibility, target or subject, and bounded adapter metadata. The fingerprint is a SHA-256 over a deterministic serialisation of those fields. Approvals and receipts bind to the fingerprint, never to the display text.

Six design properties are named: semantic equivalence, semantic separation, wrapper robustness, approval binding, receipt reproducibility, runtime portability.

On top of canonicalisation sits a **Semantic Pattern Layer** that maps a canonical action plus boundary context (destination visibility, account provenance) plus data context (sensitivity) into seven reusable risk patterns: hidden externality, public persistent egress, security-control weakening, credential exposure, delegated authority mismatch, workflow sink risk, and prompt or rule tampering. The point is that enterprise policy should say "no public persistent egress of sensitive data", not "block file host X".

Two further primitives are defined as consumers of CAVA, not part of it:

- **Bounded Action Firewall.** Returns allow, ask, block or observe, and treats a human approval as a *lease* bound to fingerprint, policy version, actor, session, destination scope, receipt and time window. Change any of those and the lease expires. The paper's phrase: approval "is not a broad permission attached to a chat session."
- **Agent Runtime Exposure Graph.** A graph joining agents, adapters, sessions, actions, decisions, destinations and incidents, for blast-radius and incident reconstruction.

Attestation is deliberately layered and optional: local SHA-256 receipts first, then operator signatures, verifiable credentials, in-toto or Sigstore-style attestations, and ledger anchoring last. The paper is explicit that blockchain is an optional substrate and that "If CAVA is defined as blockchain, it becomes narrower and less enterprise-friendly."

### Where it sits relative to PCAA

PCAA (Proof-Carrying Agent Actions), the author's earlier paper, defines the governance *loop*: route the action, review when needed, prove closure, across five checkpoints. CAVA defines the *object* that loop governs. The paper's own summary: PCAA answers who has authority and what proof closes the action; CAVA answers what exactly the authority decision refers to.

### The evidence offered

A 96-seed, 384-variant benchmark across four runtime families (shell hooks, MCP-style tools, browser automation, managed-agent traces), scored on nine properties against two baselines: raw-text matching and first-token rules.

| Metric | Raw text | First token | CAVA |
|---|---|---|---|
| Semantic equivalence recall | 0.000 | 0.000 | 1.000 |
| Semantic separation precision | 1.000 | 0.750 | 1.000 |
| Wrapper-bypass catch rate | 0.000 | 0.000 | 1.000 |
| False-positive control | 0.500 | 0.500 | 1.000 |
| Approval binding correctness | 0.000 | 0.000 | 1.000 |
| Receipt reproducibility | 0.000 | 0.000 | 1.000 |
| Attestation tamper detection | 0.000 | 0.000 | 1.000 |
| Runtime portability convergence | 0.000 | 0.000 | 1.000 |
| Semantic pattern detection | 0.000 | 0.333 | 1.000 |

The per-suite support is small: 12 equivalence variants, 8 separation pairs, 14 wrapper checks, 7 benign-contamination checks, 8 approval-drift checks, 8 receipt checks, 16 runtime projections, 6 pattern cases. The remaining suites (policy degradation, Azure drills, a 24-case red-team casebook) are "structured system-card cases", meaning described rather than scored.

An ablation table says what breaks when each layer is removed: no wrapper parsing scores 0.00 on bypass, no canonical fingerprint scores 0.00 on approval drift, no receipt verifier scores 0.00 on tamper detection, no PCAA binding retains 0.25.

### How to weigh that evidence

The paper is candid about its own limits, and its candour is the most useful thing in it for us. Read these as the author's words, not mine:

- The results "should be read as regression evidence for the representative corpus, not as a universal claim."
- "The most important result is not that CAVA scores 1.0 on a controlled corpus."
- "CAVA will become more credible as soon as the corpus stops being authored only by its creator."
- The production parser packs, policy thresholds and evidence graph are withheld as commercial. The open package holds the schema, hashing, receipt verification, approval binding and adapter contracts, and nothing of the managed layer; the repository's own boundary document draws the same line.
- Known gaps table: opaque private scripts, multi-action commands, vendor schema drift, business-context dependence, benchmark saturation.
- "The deeper risk is overclaiming: selling observer-mode logs as enforcement, selling receipt hashes as judgment."

My own reading, stated as derived: the baselines are straw men by construction. Raw-text matching scoring zero on semantic equivalence is a definition, not a finding. The benchmark demonstrates that CAVA's parser handles the cases CAVA's author wrote. It does not yet demonstrate anything about an adversary who has read the parser. The paper knows this and says so in three places. What the paper does establish is a clear *vocabulary* and a clear *claim register* (11 numbered claims C1 to C11, each with its evidence and its limitation), which is a governance artefact in its own right and matches how this project already thinks.

Two more observations. First, the paper is a single-author preprint from a vendor describing that vendor's product; there is no independent review on record. Second, the open-core repository is also single-author, so the code adds readable primitives but no independent evidence for the paper's claims.

### The open-core repository

`github.com/OndCo/CAVA`, Apache-2.0, published to npm as `osuite-cava-core` 0.1.2. No runtime dependencies; one dev dependency (vitest); a CI workflow; one test file with seven tests, one of which asserts that the open package never references the commercial product's internals. The core package is about 1,100 lines of JavaScript in twelve files. What it provides:

- **Canonical action schema.** Required fields: `runtime`, `operation`, `category`, `systems_touched`, `reversible`. Optional: `executable`, `target`, `subject`, `adapter`, `metadata`. This is Table 1 of the paper as code.
- **CAVA-IR**, a normalised intermediate form with actor, runtime, operation, resource, effect, authority boundary and data boundary, whose `semantic_key` is a hash over those parts.
- **Hashing.** A hand-written SHA-256 over a stable sorted-key serialisation, so the fingerprint is reproducible in any JavaScript environment without a crypto library.
- **Receipts.** A receipt is the canonical fingerprint, the canonical action, a profile, a decision, a policy id and an optional attestation reference, all hashed into `receipt_hash`; verification recomputes the hash. Receipts are unsigned.
- **Approval binding.** A binding carries the action id, the semantic key, the approver, the policy, a decision time and a scope marked single-action and non-reusable, hashed into `binding_hash`. Verification refuses on hash mismatch, action-id mismatch, semantic-key mismatch, or a reusable scope. This is the paper's lease idea in its minimal form.
- **Adapter and parser-pack contracts**, reference parser packs, locale-aware risk hints for non-English operator intent, and projection helpers to OpenTelemetry and in-toto shapes.

The repository also carries the paper source, a reproducibility artifact for arXiv 2607.13716 (the benchmark harness, its latest and publication-profile outputs, a snapshot verifier, and a frozen copy of the library the paper ran against), and a second, later benchmark result dated 18 July 2026: ten scenarios across ten action families, scoring the full method 100 on four metrics against two ablations and four baselines. That second corpus is smaller than the paper's 96 seeds and is, like the first, the author's own.

Run locally: the core package's seven tests pass, and the reproducibility artifact recomputes the paper's Table 5 exactly (96 seeds, 384 variants, four runtime families; raw text 0/1/0/0.5/0/0/0/0/0, first token 0/0.75/0/0.5/0/0/0/0/0.333, CAVA 1.0 on all nine) plus six further metrics the paper does not tabulate and the six ablations. The artifact reproduces the author's harness against the author's corpus; it establishes that the numbers are deterministic and honestly reported, not that they generalise.

Not in the repository, as the paper says: production parser packs, PCAA routing, action gate leases, the exposure graph, signers, credentials, ledger anchoring, or any managed connector.

### What CAVA is not

The paper says this itself, and it is worth repeating because the name invites confusion. CAVA is not a model-alignment method, not an observability product, not a policy engine, not a replacement for enterprise policy, and not a blockchain system. It is a normalisation-and-hashing layer that other things sit on.

---

## Part 2: Microsoft Agent Framework

### One-paragraph version

Microsoft Agent Framework is Microsoft's open-source SDK (software development kit) for building AI agents and multi-agent workflows. It is the declared successor to two earlier Microsoft projects, Semantic Kernel and AutoGen, built by the same teams. It ships for Python, .NET (C#) and Go, under the MIT licence, and reached its 1.0 general-availability release on 2 April 2026. Current stable versions are Python 1.18.0 (10 September 2026) and .NET 1.21.0 (11 September 2026); Go is in public preview. It is a general-purpose agent construction kit: model clients, tools, sessions, memory, middleware, graph workflows, checkpointing, human-in-the-loop, observability, plus a growing security layer.

### Lineage and positioning

Microsoft's own words: "Agent Framework combines AutoGen's simple agent abstractions with Semantic Kernel's enterprise features — session-based state management, type safety, middleware, telemetry — and adds graph-based workflows for explicit multi-agent orchestration." Migration guides exist from both predecessors.

The documentation is Foundry-first. Every quick-start defaults to a Microsoft Foundry endpoint and Azure credentials. Other providers are supported but secondary in the docs' framing. A prominent legal notice states that anything touching "non-Azure Direct models" is used at your own risk and is your responsibility to review.

### The four primary areas, per the overview

1. **Agents.** Single agents that call a model, invoke tools and MCP servers, and return responses.
2. **Harness Agent.** An opinionated, "batteries-included" agent for long multi-step work: planning and todo tracking, context compaction, file memory and file access, standing tool approvals, observability, optional shell execution, background child agents, bounded looping. Python's factory is released; background agents, file access and looping remain experimental. No packaged Go harness.
3. **Workflows.** Graph-based (all languages) and functional (Python, experimental) execution over typed executors and edges. Executes in supersteps. Built-in orchestrations: sequential, concurrent, handoff, group chat, Magentic. A workflow can be wrapped as an agent and nested.
4. **Integrations.** Model providers, agent services, tools, context providers, middleware, evaluation, UI frameworks.

### Model providers

From the provider matrix: Azure OpenAI, OpenAI, Microsoft Foundry, Anthropic, Ollama, Foundry Local, Amazon Bedrock, Google Gemini, ONNX, Dapr, Mistral. Local inference paths are Ollama (function tools and structured output supported), Foundry Local (function tools only, Python only), and ONNX Runtime GenAI (.NET, listed with no tool or structured-output support). There is no OpenVINO provider. In .NET, anything implementing `IChatClient` can back an agent, which is the general extension point; Python exposes provider-specific chat clients behind one agent interface.

### The control surfaces that matter for governance

These are the parts of the framework that decide *what is allowed to happen*, as distinct from what the model decides to do.

**Middleware.** Three types in Python and .NET: agent-run middleware (wraps a whole run), function middleware (wraps each tool call), chat middleware (wraps each model call). Middleware can inspect, modify, or terminate. Termination in Python is by setting a result and raising `MiddlewareTermination`. The docs warn that terminating a function-call loop in .NET can leave chat history inconsistent. Ordering: agent-level wraps run-level.

**Tool approval.** Per-tool: `approval_mode="always_require"` in Python, `ApprovalRequiredAIFunction` wrapper in .NET, `tool.ApprovalRequiredFunc` in Go. The run returns an approval request instead of a result; the caller shows it to a human and sends back approve or reject in a new run against the same session. The Harness adds standing "always approve" rules, request queuing, and optional heuristic auto-approval callbacks, all on by default in the Harness and all separately disableable. The docs note that disabling harness auto-approval does not remove a tool's approval requirement.

**Human-in-the-loop in workflows.** A `RequestPort` (or `ctx.request_info()` in Python) pauses the workflow, emits a request event, and resumes when a response is supplied. Pending requests are saved inside checkpoints and re-emitted on restore.

**Checkpoints.** Taken at every superstep boundary, capturing executor state, pending messages, pending requests, and shared state. Storage: in-memory, local file, Azure Cosmos DB (Python); the .NET docs show in-memory. The security section states plainly: "Checkpoint storage is a trust boundary." Python checkpoints use pickle with a restricted unpickler and an explicit type allow-list; the docs say that is a mitigation, not a guarantee, and offer in-memory storage for threat models that forbid pickle.

**FIDES (Flow Integrity Deterministic Enforcement System).** Python-only, experimental, shipped in the core package. Information-flow control as middleware, based on a 2025 paper by Costa et al. Every content item carries an integrity label (trusted or untrusted) and a confidentiality label (public, private, user-identity). Labels propagate through tool calls by a most-restrictive-wins rule. Sink tools declare `accepts_untrusted: False` or `max_allowed_confidentiality`, and the policy middleware refuses the call before it runs. Default for an unlabelled tool result is untrusted plus public, so a forgotten annotation fails closed. Optional variable indirection hides untrusted bytes from the main model entirely and routes processing through a tool-free "quarantined" model. Approvals are bound to the exact resolved invocation in one session and consumed once; if the resolved content changes, a fresh approval is required. Stated limitations: labels are opt-in per source, propagation is conservative, approvals are coarse, the quarantined model is single-turn, and MCP-supplied labels are subordinate to local policy unless the server is explicitly trusted.

**Agent Hooks.** Python-only, experimental. Implements a framework-neutral contract (AGENT-HOOKS-0.1, hosted by a "responsibleai" GitHub organisation) with eight interception points: agent startup, input, pre and post model call, pre and post tool call, output, agent shutdown. Each interceptor returns allow, deny, transform, or escalate-to-approval. The docs claim five runtime guarantees: fail closed on any interceptor or enforcement failure; transforms are written back into what actually executes; streaming is buffered so nothing reaches the caller before the output verdict; persistence waits for the covering verdict; and the agent, chat and function parts install as one bundle so a partial boundary cannot be configured by accident. Stated limits: cooperative not sandboxed, hosted tools executed server-side by a provider bypass the tool seams, and interceptor failure blocks the action by design.

**Safety guidance.** A separate Agent Safety page (not read) holds the heuristic best practices; FIDES and Hooks are positioned as the deterministic complements.

### Release status and cadence

| Surface | Status | Evidence |
|---|---|---|
| 1.0 general availability | 2 April 2026 | Microsoft Agent Framework blog, BUILD 2026 post dated 3 June 2026 |
| Python `agent-framework` | 1.18.0, 10 Sep 2026, Production/Stable, Python 3.10 to 3.14 | PyPI |
| .NET `Microsoft.Agents.AI` | 1.21.0, 11 Sep 2026, stable, .NET 8/9/10, netstandard2.0, net472 | NuGet |
| Go | public preview; declarative agents, RAG, CodeAct, functional workflows not yet available | Learn overview |
| FIDES, Agent Hooks | Python-only, experimental | Learn security and hooks pages |
| Harness background agents, file access, looping | experimental | Learn harness page |

Release cadence from the GitHub releases page: roughly weekly, alternating Python and .NET, through August and September 2026. The FAQ page still says only .NET and Python are supported, which is stale against the overview's Go pivot; the FAQ's own date is February 2026.

Announced at BUILD 2026 (June): Hosted Agents on Foundry, CodeAct (multi-step tool calls compiled into a single Python programme run inside Hyperlight micro-VMs; Microsoft quotes 52.4 percent faster and 63.9 percent fewer tokens on its own benchmark), GitHub Copilot SDK integration.

### How to weigh this

Everything above is from Microsoft's documentation and package metadata, which describe intent and API surface. Three things I would want to see on disk before relying on any of it: whether the Python function-middleware seam really is the only path a tool call can take (the Hooks page already admits hosted tools bypass it); how the FIDES label store behaves under the local model providers rather than Foundry; and how large the dependency tree is for the core package versus the extras. The docs are unusually honest about limits, which is a good sign, but honesty in docs is still docs.

---

## Sources

- CAVA paper, local PDF, arXiv 2607.13716v1: https://arxiv.org/abs/2607.13716
- PCAA paper listing: https://arxiv.org/abs/2606.04104
- Agent Framework documentation hub: https://learn.microsoft.com/en-us/agent-framework/
- Overview: https://learn.microsoft.com/en-us/agent-framework/overview/agent-framework-overview
- Harness: https://learn.microsoft.com/en-us/agent-framework/concepts/harness
- Workflows: https://learn.microsoft.com/en-us/agent-framework/concepts/workflows/
- Middleware: https://learn.microsoft.com/en-us/agent-framework/concepts/agents/middleware/
- Security with FIDES: https://learn.microsoft.com/en-us/agent-framework/agents/security
- Agent Hooks: https://learn.microsoft.com/en-us/agent-framework/agents/agent-hooks
- Tool approval: https://learn.microsoft.com/en-us/agent-framework/agents/tools/tool-approval
- Human-in-the-loop: https://learn.microsoft.com/en-us/agent-framework/workflows/human-in-the-loop
- Checkpoints: https://learn.microsoft.com/en-us/agent-framework/workflows/checkpoints
- Model providers: https://learn.microsoft.com/en-us/agent-framework/integrations/by-component/model-providers/
- FAQ: https://learn.microsoft.com/en-us/agent-framework/support/faq
- GitHub repository: https://github.com/microsoft/agent-framework
- Releases: https://github.com/microsoft/agent-framework/releases
- PyPI: https://pypi.org/project/agent-framework/
- NuGet: https://www.nuget.org/packages/Microsoft.Agents.AI
- BUILD 2026 announcement post: https://devblogs.microsoft.com/agent-framework/microsoft-agent-framework-at-build-2026-announce/
