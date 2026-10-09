# Action-level agent governance beyond the big four: standards, academic work and open-source projects (survey as of 2026-09-16)

## Scope

This is a documentation-level survey, current to 2026-09-16, of standards, academic work and open-source projects that govern what an AI agent is allowed to DO at the action level: a canonical action identity, approval bound to a specific action, verifiable receipts or attestations of decisions, interception seams, and honest coverage disclosure. It deliberately excludes Microsoft (Agent Framework, Agent Governance Toolkit / AGT, Agent Control Specification / ACS), Anthropic, OpenAI and Google, which are surveyed separately; where a Google- or Microsoft-origin artefact is unavoidable for a question (CaMeL, Conseca, AP2, the OWASP-hosted ACS) it is named and marked. The comparison targets are CAVA (hashed canonical action object) and PCAA (five-checkpoint route-review-prove certificate), both by Zexun Wang of Ond Holdings Inc. (affiliation verified on the arXiv HTML of both papers), and Microsoft Agent Framework / AGT / ACS. Every fact below was read from the cited page during this session using web search and fetch; nothing was taken from local files. Where a page could not be read, or a claim rests on a secondary source, it is marked "not verified". Marketing text was discounted in favour of specification text, repository READMEs and paper bodies.

Five criteria used throughout:

1. Action identity: does the artefact define a canonical object or fingerprint for one action (and with what fields)?
2. Approval binding: is a human or policy approval bound to that specific action (how)?
3. Receipt: does it produce a per-decision record, and is it hashed or signed?
4. Enforcement seam: does code sit in the path and block, or is it a document?
5. Local operation: can it run on one machine with no cloud dependency?

## Headline findings

- The closest published peers to CAVA/PCAA outside the big four are all 2026 arXiv work with small reference implementations: Agent Control Protocol (TraslaIA, Apache-2.0, Go, Ed25519, single-use execution tokens), Open Agent Passport (APort, Ed25519 signed decisions), Agent Passport System (aeoess, Apache-2.0, content-addressed action_ref, three-signature chain, JCS canonicalisation, receipts with an explicit scope_of_claim), Auditable Agents / Aegis (USC, Ed25519-signed SHA-256 hash-chained per-call records plus an "Auditability Card" disclosure), Audita (Duke, MIT, Ed25519 message tuples in a Merkle log), and Pipelock (Apache-2.0 core, Ed25519 mediator-signed receipts over JCS-canonical JSON with allow/block/warn/ask).
- Among standards bodies, nothing yet standardises an action identity or a decision receipt. Two open proposals are the only movement: an in-toto `agent-decision/v0.1` predicate RFC (opened 2026-05-19, no maintainer reply) and an OpenTelemetry GenAI proposal for tool-risk attributes on `execute_tool` spans (opened 2026-07-11, no maintainer reply). OpenTelemetry's GenAI conventions carry tool name, call id, arguments and result, all at Development stability, with no approval or policy attribute.
- OWASP's Agent Control Standard (ACS), unveiled 2026-09-01 as a v0.1 public preview, is the same family as the Microsoft Agent Control Specification: the repository states its reference implementation uses Microsoft's Agent Governance Toolkit, has 16 hooks including `toolCallRequest`, and five dispositions (allow, deny, modify, ask, defer). No page read this session names the donor explicitly; the announcement says only that it was "donated". Treat the Microsoft ACS survey and this entry as one artefact with two homes.
- The MCP specification itself (2025-11-25) is the widest-deployed seam: it says a human "SHOULD always be in the loop with the ability to deny tool invocations", declares tool annotations untrusted, and asks clients to log tool usage, but defines no action identity beyond tool name plus arguments and no receipt.
- Dapr 1.18 (June 2026) is the only mainstream runtime signing execution records: every workflow history event is signed with the sidecar's SPIFFE X.509 key (Ed25519 by default), SHA-256 digests are chained to the previous signature digest, and verification runs on every state load. It is opt-in, and approval events are not specifically addressed.
- The MCP-gateway field is crowded; only three of the credible open-source gateways bind a human decision to an individual call at runtime (MCP Guardian, Pipelock's ask action, the mcpg Slack tool-gate plugin) and only two sign anything per call (Pipelock, mcpkernel). None canonicalises the action beyond JCS of the raw JSON.

## Sources actually read

Standards and frameworks

- https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/
- https://genai.owasp.org/initiatives/agentic-security-initiative/
- https://genai.owasp.org/resource/securing-agentic-applications-guide-1-0/
- https://genai.owasp.org/resource/agent-control-standard-acs/
- https://genai.owasp.org/2026/09/01/owasp-genai-security-project-unveils-2026-top-10-for-llm-applications-new-agent-control-standard-and-sponsors-as-community-tops-30000-members/
- https://github.com/GenAI-Security-Project/agent-control-standard
- https://www.nist.gov/artificial-intelligence/ai-agent-standards-initiative
- https://www.nist.gov/news-events/news/2025/01/technical-blog-strengthening-ai-agent-hijacking-evaluations
- https://www.nist.gov/itl/ai-risk-management-framework
- https://csrc.nist.gov/Projects/cosais/use-cases
- https://github.com/CloudSecurityAlliance/MAESTRO
- https://cloudsecurityalliance.org/artifacts/agentic-ai-identity-and-access-management-a-new-approach
- https://github.com/cosai-oasis/cosai-tsc/blob/main/security-principles-for-agentic-systems.md
- https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/
- https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/
- https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md
- https://github.com/open-telemetry/semantic-conventions-genai/issues/373
- https://github.com/in-toto/attestation/issues/554
- https://github.com/sigstore/sigstore-a2a
- https://next.redhat.com/2026/08/07/supply-chain-provenance-for-ai-agent-identity/
- https://spec.identity.agntcy.org/docs/vc/intro/
- https://github.com/agntcy/identity
- https://github.com/google-agentic-commerce/AP2
- https://modelcontextprotocol.io/specification/2025-11-25/server/tools
- https://a2a-protocol.org/latest/specification/

Open-source projects

- https://www.cncf.io/blog/2026/06/11/introducing-verifiable-execution-in-dapr-1-18/
- https://v1-18.docs.dapr.io/developing-applications/building-blocks/workflow/workflow-history-signing/
- https://github.com/invariantlabs-ai/invariant
- https://github.com/invariantlabs-ai/invariant-gateway
- https://github.com/invariantlabs-ai/mcp-scan
- https://invariantlabs-ai.github.io/docs/mcp-scan/guardrails-reference/
- https://github.com/NVIDIA-NeMo/Guardrails
- https://github.com/guardrails-ai/guardrails
- https://github.com/stacklok/toolhive
- https://github.com/eqtylab/mcp-guardian
- https://github.com/lasso-security/mcp-gateway
- https://github.com/agentgateway/agentgateway
- https://github.com/docker/mcp-gateway
- https://github.com/IBM/mcp-context-forge
- https://github.com/glatinone/pipelock (fork; upstream is https://github.com/luckyPipewrench/pipelock, not read)
- https://github.com/piyushptiwari1/mcpkernel
- https://developer.konghq.com/plugins/ai-mcp-proxy/
- https://docs.litellm.ai/docs/proxy/guardrails/tool_permission
- https://mastra.ai/docs/agents/human-in-the-loop
- https://github.com/mastra-ai/mastra
- https://github.com/aporthq/aport-spec
- https://github.com/chelof100/acp-framework-en
- https://github.com/aeoess/agent-passport-system

Academic

- https://arxiv.org/abs/2607.13716 and https://arxiv.org/html/2607.13716v1 (CAVA)
- https://arxiv.org/abs/2606.04104 and https://arxiv.org/html/2606.04104v1 (PCAA)
- https://arxiv.org/html/2604.05485 (Auditable Agents)
- https://arxiv.org/abs/2603.18829 (Agent Control Protocol)
- https://arxiv.org/abs/2603.20953 (Before the Tool Call / Open Agent Passport)
- https://arxiv.org/abs/2607.25364 (Explanation-Bound Tool Execution)
- https://arxiv.org/html/2609.04017 (A Black Box for Agentic Processes)
- https://arxiv.org/abs/2605.16407 (Proof-Carrying Certificates for LLM Pipelines)
- https://arxiv.org/abs/2510.24383 (Policy Cards)
- https://arxiv.org/abs/2606.25189 (ActPlane)
- https://arxiv.org/html/2608.22160 (Audita)
- https://arxiv.org/abs/2606.19464 (Deontic Policies)
- https://arxiv.org/abs/2604.05229 (From Governance Norms to Enforceable Controls)
- https://arxiv.org/abs/2601.11893 (SEAgent MAC framework)
- https://arxiv.org/abs/2605.17909 (EHV)
- https://arxiv.org/abs/2511.02841 (AI Agents with DIDs and VCs)

Search-result summaries only (page not fetched): Progent (arXiv 2504.11703), AgentSpec (arXiv 2503.18666, github.com/haoyuwang99/AgentSpec), Conseca (arXiv 2501.17070, HotOS 2025), ToolEmu (arXiv 2309.15817, github.com/ryoungj/ToolEmu), LlamaFirewall (arXiv 2505.03574), CaMeL (arXiv 2503.18813, github.com/google-research/camel-prompt-injection), NIST NCCoE concept paper, NIST RFI (Federal Register page redirected to a block page), CSA MAESTRO blog, CSA Red Teaming Guide and Scoping Matrix, IETF drafts, W3C community groups, Lakera, Cloudflare MCP Server Portals, Portkey, Enkrypt, Lunar MCPX, mcpg tool-gate plugin, Kong Tool ACL blog. These are marked "n.v." (not verified) wherever a specific claim depends on them.

---

## Part A. Standards and frameworks

### A1. OWASP Top 10 for Agentic Applications 2026 and the Agentic Security Initiative

What it is: a ranked risk list (ASI01 Agent Goal Hijack, ASI02 Tool Misuse, ASI03 Identity and Privilege Abuse, ASI04 Agentic Supply Chain Compromise, ASI05 Unexpected Code Execution, ASI06 Memory and Context Poisoning, ASI07 Insecure Inter-Agent Communication, ASI08 Cascading Agent Failures, plus ASI09 and ASI10 whose titles were not shown on the page read) from the OWASP GenAI Security Project's Agentic Security Initiative.
URL: https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/
Status and date: published 2025-12-09; v1.0 of the 2026 edition.
Sibling documents from the initiative page: Agentic AI Threats and Mitigations (2025-02), Securing Agentic Applications Guide 1.0 (2025-07-27), OWASP Agentic AI Taxonomy in Action (2025-07), A Practical Guide for Secure MCP Server Development (2026-02), AIUC-1 crosswalk (2026-05), State of Agentic AI Security and Governance 2.01 (2026-06), AI Security Solutions Landscape for Agentic AI Q2 2026, Agent Control Standard (2026-09-01, see A1a).
Action identity: none. Approval binding: none defined; the guide family recommends human-in-the-loop as a mitigation (body of the Securing Agentic Applications Guide not read; only its metadata page). Receipts: none. Seam: document. Licence: CC BY-SA 4.0 (site-wide statement). Local: n/a.
"Control catalogue": the initiative's own summary describes "developer and operator security controls" as one of its five document families; the Securing Agentic Applications Guide is that catalogue. Its control text was not extracted (download-only PDF), so specific control IDs are not verified.

### A1a. OWASP Agent Control Standard (ACS)

What it is: a runtime-enforcement specification hosted by OWASP since 2026-09-01: "defines how agent platforms expose middleware hooks and how safety policies can be enforced through them, enabling declarative controls that are portable across agent frameworks and enforced at runtime."
URL: https://genai.owasp.org/resource/agent-control-standard-acs/ and https://github.com/GenAI-Security-Project/agent-control-standard
Status and date: v0.1.0 shipped, v0.1.1 tagged; v0.2.0 targeted for March 2027; milestones listed to "Day 90 (December 4, 2026)". The announcement says the standard was "donated to the OWASP GenAI Security Project"; the repository states the reference implementation "uses Microsoft's Agent Governance Toolkit (AGT)". No page read names the donor; the AGT dependency and the identical name make it the Microsoft Agent Control Specification in a new home. Treat with the Microsoft survey.
Action identity: request envelopes carry tool name, arguments and parameter values; 44 JSON Schemas under the v0.1.0 namespace. No canonical hash or fingerprint was stated on the pages read.
Approval binding: "Five dispositions: allow, deny, modify, ask (route to human/agent/service approver), or defer." Binding of the approval to a hash of the exact call was not stated.
Receipts: "OpenTelemetry span and an OCSF event" per the Trace pillar; envelope logs as JSONL. No signing stated.
Seam: yes, 16 lifecycle hooks including `toolCallRequest` and `toolCallResult`. Runnable: TypeScript/Bun only; "Python, Go, Rust, and a Codex host shim are open and unclaimed."
Licence: Apache-2.0 (code and schemas), CC BY-SA 4.0 (documentation). Local: yes (a library; no hosted dependency stated).

### A2. NIST: AI 600-1, CAISI, AI Agent Standards Initiative, agent hijacking, COSAIS; ISO/IEC 42001

NIST AI 600-1 (Generative AI Profile). Published 2024-07-26 (https://doi.org/10.6028/NIST.AI.600-1). The PDF could not be parsed by the fetch tool, so its agent-related suggested actions are not verified this session; the AI RMF landing page lists no agent-specific material and notes AI RMF 1.0 is under revision. Document, no action identity, no seam.

Technical Blog: Strengthening AI Agent Hijacking Evaluations. https://www.nist.gov/news-events/news/2025/01/technical-blog-strengthening-ai-agent-hijacking-evaluations. 2025-01-17. AgentDojo evaluation of Claude 3.5 Sonnet (Oct 2024): baseline attacks 11 percent, novel red-team attacks 81 percent, 57 percent single-attempt aggregate, 80 percent at 25 attempts; three new injection tasks (remote code execution via untrusted download, database/cloud exfiltration, automated phishing). Code: https://github.com/usnistgov/agentdojo-inspect (licence not read). No control prescriptions; an evaluation harness, not a seam.

AI Agent Standards Initiative (CAISI). https://www.nist.gov/artificial-intelligence/ai-agent-standards-initiative. Announced 2026-02-17. Three pillars: industry-led standards via gap analyses and voluntary guidelines; community-led protocols; research on agent authentication and security evaluations. Deliverables named on the page: RFI on AI Agent Security (comment deadline March 9; Federal Register page could not be fetched, redirected to a block page) and the NCCoE draft concept paper "Accelerating the Adoption of Software and AI Agent Identity and Authorization" (published 2026-02-05, comments to 2026-04-02; per search summary, its premise is that per-action human authorization is impractical at agent speed and that OAuth, SPIFFE and OIDC should be adapted rather than replaced; not fetched). No action identity, no receipts, documents only.

COSAIS (SP 800-53 Control Overlays for Securing AI Systems). https://csrc.nist.gov/Projects/cosais/use-cases. Five use cases including "Using AI Agent Systems - Single Agent" and "Multi-Agent". Page updated 2026-01-08. Only an annotated outline for the predictive-AI overlay (January 2026) was found; no agent overlay draft was found. Document.

ISO/IEC 42001:2023. AI management system standard (December 2023). No agent-specific clause; no publicly announced SC 42 work item on agentic architectures was found (secondary source: arXiv 2604.04604 states this and that the ISO/IEC 22989 revision may add agent terminology; not verified against iso.org). Relevance to runtime controls is via management-system requirements only; arXiv 2604.05229 (Koch, 2026-04-06) proposes a translation method from ISO/IEC 42001, 23894, 42005, 5338, 38507 and the NIST AI RMF to four control layers (architecture, runtime policy, human escalation, audit) but defines no action identity or receipt.

### A3. Cloud Security Alliance: MAESTRO and agent guidance

MAESTRO (Multi-Agent Environment, Security, Threat, Risk and Outcome). Blog 2025-02-06 (Ken Huang); seven-layer threat model. https://github.com/CloudSecurityAlliance/MAESTRO is an MIT-licensed Next.js/Genkit "threat analyzer" web app that generates threat lists with AI and carries the disclaimer that its output "should not be considered a complete or authoritative security audit". Document plus analysis tool; no action identity, approval, receipt or enforcement.

Agentic AI Identity and Access Management: A New Approach. https://cloudsecurityalliance.org/artifacts/agentic-ai-identity-and-access-management-a-new-approach. 2025-08-18. Proposes DIDs plus Verifiable Credentials for agent identity, JIT narrow time-bound credentials, PDP/ABAC/PBAC evaluation per access request, and a log schema with a `logEntrySignature` field. Document; per-action authorization is advocated, not specified as an object; no canonical action identity.

Also from CSA (search summaries, not fetched): Agentic AI Red Teaming Guide; Agentic AI Security Scoping Matrix (December 2025); a series of 2026 research notes on the NIST initiative, the CISA agentic guide and the Five Eyes joint guidance. All documents.

### A4. OpenTelemetry GenAI semantic conventions

What exists (registry page; all attributes marked Development stability, and the page notes the conventions have moved to https://github.com/open-telemetry/semantic-conventions-genai): `gen_ai.tool.name`, `gen_ai.tool.description`, `gen_ai.tool.type` (function, extension, datastore), `gen_ai.tool.call.id` ("The tool call identifier"), `gen_ai.tool.call.arguments` ("Parameters passed to the tool call"), `gen_ai.tool.call.result`, `gen_ai.tool.definitions`, `gen_ai.agent.id/name/description/version`, `gen_ai.operation.name` with values including `execute_tool`, `invoke_agent`, `invoke_workflow`. The agent-spans document defines create_agent, invoke_agent (client and internal), invoke_workflow, plan, and execute_tool spans; status Development.
Decision/approval attributes: none. No attribute for approval, policy, guardrail, human-in-the-loop, hash or signature exists.
Open proposal: issue #373 (JM-Lab, opened 2026-07-11, revised 2026-07-18, open, no maintainer response) proposes `gen_ai.tool.risk.level`, `gen_ai.tool.risk.override`, `gen_ai.tool.risk.method`, motivated by the fact that "human-approval requirements are driven by risk assessments, yet there is no conventional attribute to carry this information".
Action identity: `gen_ai.tool.call.id` is the provider's call id, not a content hash. Receipt: a span, unsigned. Seam: observability only. Licence: Apache-2.0 (OpenTelemetry). Local: yes.

### A5. Supply-chain attestation applied to agents: in-toto, SLSA, Sigstore

in-toto. RFC issue #554 (https://github.com/in-toto/attestation/issues/554), opened 2026-05-19 by Auxidus Technologies, open with no maintainer response: proposes an `agent-decision/v0.1` predicate carrying the tool requested, a SHA-256 digest of the tool arguments, the policies evaluated with outcomes, the allow/deny decision and rationale, agent id, principal (subject / SPIFFE id), timestamp, optional `traceparent`; DSSE envelope, in-toto Statement v1, modelled on the existing `human-review/v0.1` predicate. This is the only registry-level proposal found for a signed per-decision agent record. Status: proposal only.

sigstore-a2a. https://github.com/sigstore/sigstore-a2a. Apache-2.0. Keyless signing of A2A Agent Cards with SLSA provenance; DSSE bundle with in-toto statement, Fulcio certificate, Rekor inclusion proof. Signs Agent Cards only; no per-action signing. Marked "Prototype code - not for production use"; 27 stars, 79 commits.

Red Hat Emerging Technologies post (2026-08-07) uses sigstore-a2a plus SPIFFE/SPIRE and JCS (RFC 8785) to sign an agent card with build provenance; explicitly build-time only, "no per-action attestations".

An open-source GitHub Action (Apache-2.0) that signs agent instruction files (SKILLS.md, CLAUDE.md) and packages with Sigstore; runtime verification by a companion command-line tool. Provenance of instructions, not of actions. CI-only; 27 stars, 28 commits, v0.0.2.

SLSA itself: no agent-action profile found; used only as the provenance predicate in the above.

### A6. Verifiable Credentials 2.0 applied to agent actions

W3C VC Data Model 2.0 is a Recommendation (2025-05-15; from search summary). Projects found that apply VCs to agents:

- AGNTCY Identity (Cisco-originated, Linux Foundation; https://github.com/agntcy/identity, Apache-2.0): issues Agent Badges and MCP Server Badges as enveloped VCs (JSON-LD, JWKS well-known endpoints); identity-level only, "no evidence of per-action or per-tool-call attestation"; runs locally (CLI, Docker, local vault). Whether the VC is 2.0 or 1.1 is not stated on the pages read.
- CSA Agentic AI IAM (A3): VCs for delegation and JIT capability; document.
- arXiv 2511.02841 (Rodriguez Garzon et al., ICAART 2026): DID-bound VCs for agent authentication and cross-domain trust; identity-level; no code stated.
- Google AP2 (https://github.com/google-agentic-commerce/AP2, Apache-2.0): out of scope by origin; its mandate objects are described elsewhere as verifiable digital credentials binding user intent to a cart and payment, but the repository landing page read here does not state the format, so that claim is not verified.
- Agent Passport System (C10 below) uses VC-like signed receipts but is not stated to be W3C VC 2.0.

No project was found that issues a W3C VC 2.0 credential per agent action.

### A7. Protocol-level seams: MCP, A2A, IETF, W3C, CoSAI

MCP specification 2025-11-25, Tools page. Normative text: "there SHOULD always be a human in the loop with the ability to deny tool invocations"; clients "MUST consider tool annotations to be untrusted unless they come from trusted servers"; clients SHOULD "Prompt for user confirmation on sensitive operations", "Show tool inputs to the user before calling the server", and "Log tool usage for audit purposes". `tools/call` carries only a JSON-RPC id, tool name and arguments; no content hash, no receipt. MCP is hosted by the Linux Foundation's Agentic AI Foundation. Seam by convention on the client; no action identity.

A2A 1.0.0 (joined the Agentic AI Foundation, August 2026): task states `TASK_STATE_INPUT_REQUIRED` and `TASK_STATE_AUTH_REQUIRED` as interrupted states; Agent Card signing via JWS with canonicalisation (section 8.4); no per-task or per-action signing found.

IETF (search summaries only): draft-oauth-ai-agents-on-behalf-of-user (-01/-02, individual draft, adds `requested_actor` and `actor_token`), draft-oauth-transaction-tokens-for-agents-05, draft-klrc-aiagent-auth-03, draft-liu-ai-agent-authorization-integration-00, draft-song-oauth-ai-agent-collaborate-authz-00. All identity/delegation-level, none adopted by a working group as of the search. Background knowledge, not read this session: RFC 9396 (Rich Authorization Requests, 2023) is the existing IETF primitive for binding an OAuth grant to transaction-specific details.

W3C community groups (search summary): AI Agent Protocol CG (171 participants), Agent Trust Protocol CG, Agent Identity Registry Protocol CG (call for participation 2026-04-24). No action-level deliverable found.

CoSAI (OASIS) Principles for Secure-by-Design Agentic Systems, approved 2025-07-14: three principles (Human-governed and Accountable; Bounded and Resilient; Transparent and Verifiable) calling for "comprehensive telemetry of inputs, plans, decisions, communications, and outputs"; no binding of approval to an action, no receipt format, no licence stated. Document.

---

## Part B. Open-source projects

### B1. Dapr 1.18 Verifiable Execution

URL: https://v1-18.docs.dapr.io/developing-applications/building-blocks/workflow/workflow-history-signing/ and CNCF blog 2026-06-11.
What it signs: "Every history event produced during a workflow's lifetime is signed using the sidecar's mTLS identity" - the SPIFFE X.509 SVID private key; Ed25519 by default from 1.18, ECDSA P-256 and RSA supported. Each signature "chains the new digest to the previous signature's digest" (SHA-256), and verification on every state load checks the recomputed events digest, the signature, the certificate chain to the Sentry CA, and that the SPIFFE app identity matches. Opt-in via `features: - name: WorkflowHistorySigning enabled: true`. Companion features: history propagation and workflow attestation ("cryptographically verifiable execution context" tied to workload identities).
Action identity: none at the tool-call level; the unit is the workflow history event. Approval binding: not addressed; whether raise_event or human-approval events are covered is not stated. Receipt: yes, signed and hash-chained. Seam: it records, it does not gate. Licence: Apache-2.0 per CNCF norms (licence file not read this session). Local: yes (sidecar), but requires the Dapr control plane (Sentry) for identities.

### B2. Invariant Labs: Guardrails, invariant-gateway, mcp-scan

invariant (https://github.com/invariantlabs-ai/invariant). Apache-2.0. Rule language over traces, e.g. `raise "Don't use send_email after get_website" if: (output: ToolOutput) -> (call2: ToolCall) output is tool:get_website call2 is tool:send_email`; parameter matching `call is tool:send_email({ to: "alice@mail.com" })`. Enforcement: rules "error out LLM and MCP requests that violate the pattern"; the `invariant-ai` package "runs entirely locally". No signing, receipt or human-approval verdict; the only action is raise/block or log.
invariant-gateway (https://github.com/invariantlabs-ai/invariant-gateway). Apache-2.0. LLM proxy (Docker, port 8005) with "blocking or logging guardrails"; MCP tool calls can be proxied; traces stored in Invariant Explorer (a hosted or self-run service). 349 commits, 80 stars.
mcp-scan (https://github.com/invariantlabs-ai/mcp-scan). Apache-2.0. The README now presents "Agent Scan", a scanner of local agents, skills and MCP servers; the runtime proxy mode described in the older docs is not present in the README read, and enforcement is deferred to "users or enterprise platforms like Snyk Evo" (Invariant Labs was acquired by Snyk, per the Snyk Labs page title in search results). Guardrails reference docs still document the rule syntax.
Action identity: none (pattern match on tool name and arguments). Approval binding: none. Receipt: traces, unsigned. Seam: yes (proxy or in-process). Local: yes for the library and gateway.

### B3. NVIDIA NeMo Guardrails, Guardrails AI, Lakera

NeMo Guardrails (https://github.com/NVIDIA-NeMo/Guardrails). Apache-2.0. Five rail types; execution rails are "applied to input/output of the custom actions" and can reject or alter inputs before an action runs. No human approval, no audit signing. Local: yes (Python, CLI, Docker). Verdict: content and action filtering, not approval binding.
Guardrails AI (https://github.com/guardrails-ai/guardrails). Apache-2.0. Input/output validators and structured-output generation with `OnFailAction`; no tool-call interception or approval binding stated; no signing. Local: yes (Python, or Flask server). As of July 2026 remote inferencing is being discontinued and validators move to PyPI packages.
Lakera Guard (search summaries only; docs.lakera.ai now branded "Check Point AI Security"): a managed SaaS API called per LLM interaction (`POST /v2/guard`), operating on the prompt and completion surface; not open source, not local, no MCP-level seam.
None of the three binds an approval to an action; all filter content.

### B4. Agent firewalls, tool gateways and MCP gateways

Listed with licence, local operation, and the allow/deny/approve/audit semantics found. "Approve" means a human decision on an individual call at runtime.

| Project | Licence | Local | Allow/deny | Approve per call | Audit record | Signed |
|---|---|---|---|---|---|---|
| agentgateway (Linux Foundation; Solo.io; Rust) | Apache-2.0 | yes (standalone binary or k8s) | RBAC with CEL policies, tool-level | not found | OpenTelemetry | no |
| ToolHive (Stacklok) | Apache-2.0 | yes (CLI, desktop, containers, k8s) | policy-based access, tool filters | not found | OTel and Prometheus, "audit logging" | server provenance verification only |
| MCP Guardian (EQTY Lab; Rust) | Apache-2.0 | yes | yes | yes: "Approve and deny individual tool call messages in real time" | message logging | no |
| Lasso mcp-gateway (Python) | MIT | yes (pip, Docker) | content scanning/masking, not call blocking | no | Xetrack plugin, SQLite/DuckDB | no |
| Docker mcp-gateway | MIT | yes | interceptors (per Docker blog; README read shows only "logging and call tracing") | not found | logging | image signature verification |
| IBM ContextForge | Apache-2.0 | yes (PyPI, Docker, k8s) | plugins, JWT/OAuth | not found | OTel, log viewer | no |
| Pipelock (luckyPipewrench; read via fork) | Apache-2.0 core, ELv2 enterprise | yes ("No account and no server") | strict allowlist / balanced / audit modes | "ask" actions for human-in-the-loop | mediator-signed action receipts: verdict, policy hash, transport, scanner layer, correlation id, optional actor and taint | Ed25519 over RFC 8785 JCS |
| mcpkernel (piyushptiwari1) | Apache-2.0 | yes | allow / deny / audit on tool name, argument patterns, taint labels | no | hashed inputs and outputs, signed trace | Sigstore; 2 stars, very early |
| Enkrypt secure-mcp-gateway | Apache-2.0 core, proprietary add-ons (n.v.) | yes (n.v.) | guardrails per server (n.v.) | n.v. | n.v. | n.v. |
| Lunar MCPX | MIT, free for non-production (n.v.) | yes (n.v.) | access control (n.v.) | n.v. | n.v. | n.v. |
| mcpg tool-gate Slack approval plugin | Apache-2.0 (n.v.) | plugin to mcpg (n.v.) | - | yes, via Slack (n.v.) | n.v. | n.v. |
| Kong AI Gateway ai-mcp-proxy | Enterprise tier only | self-hosted allowed | MCP Tool ACL allow/deny, deny precedence; 403 since 3.14 | no | `logging.log_audits: true` | no |
| Cloudflare MCP Server Portals | proprietary cloud | no | per-user server and tool allowlists, DLP policies | no | Zero Trust logs | no |
| Portkey gateway | MIT | yes | MCP guardrails "coming soon" per docs | no | yes | no |
| LiteLLM proxy | MIT core; audit logs in Enterprise | yes | `tool_permission` guardrail: regex allow/deny on tool names with `default_action`; `pre_mcp_call` and `during_mcp_call` hooks | no | Enterprise | no |

None of these defines a canonical action identity; matching is on tool name and raw arguments. Only Pipelock canonicalises (JCS) before hashing, and only Pipelock and mcpkernel sign per call.

### B5. Agent frameworks with approval-to-call binding: Mastra

Mastra human-in-the-loop docs (https://mastra.ai/docs/agents/human-in-the-loop; core Apache-2.0 with an enterprise-licensed `ee/` tree): a `beforeToolCall` hook computes a fingerprint of `{ toolName, args }` (the docs say "in production you should use a stable hash of the tool name and arguments"), and "the approval is consumed once, and only for the same canonical tool arguments that were reviewed"; argument drift blocks with "Tool call blocked: approval did not match". Recommended storage: "durable storage scoped to the user, run, tool call, and policy version". No signing. This is the clearest framework-level statement of single-use approval bound to canonical arguments found outside the big four.

---

## Part C. Academic work

### C1. CAVA (comparison target, for reference)

arXiv 2607.13716, Zexun Wang, Ond Holdings Inc., submitted 2026-07-15, cs.AI. Canonical action object with nine components: `schema_version, runtime, adapter, executable, operation, category, systems_touched, reversible, target/subject`; fingerprint F(a) = H(canon(C(a))) with deterministic serialisation; "local deterministic SHA-256 receipt hashes" as one attestation substrate. Bounded Action Firewall verdicts allow, ask, block, observe, each bound to "canonical fingerprint, policy version, actor identity, runtime session, destination scope, proof receipt, and time window". Receipts carry outcome, evidence, exceptions and side-effect summaries; signed, credential, ledger-anchor or external-verify receipt material is optional. Positioned "below" PCAA. Open-core: "schema constants, deterministic hashing, receipt creation and verification, profile normalization, and runtime-adapter contracts" are in the open package; the rest is not.

### C2. PCAA (comparison target, for reference)

arXiv 2606.04104, Zexun Wang, Ond Holdings Inc. (email jw@nd.im), submitted 2026-06-02, cs.SE/cs.AI/cs.CR. Five checkpoints: pre-action admissibility (guard), action open (createAction), assumption capture (recordAssumption), approval checkpoint (waitForApproval), outcome closure (updateOutcome). Certificate C(a) = envelope E(a), runtime receipts Q_r(a), approval receipts Q_h(a), replay/proof state P(a), integrity projection I(a). No hashing or signature algorithm is specified; no canonical form algorithm; no code released ("the manuscript is intended to support public scrutiny of the control method without turning the benchmark into an implementation playbook"). CAVA is not cited (it postdates PCAA).

### C3. Progent: Programmable Privilege Control for LLM Agents

arXiv 2504.11703, April 2025 (search summary; abstract page not fetched). Tool-level privilege control with a DSL, deterministic per-call policy check, fallback actions, dynamic policy updates; an LLM drafts the initial policy from the task. Reports 0 percent attack success on AgentDojo, ASB, AgentPoison with LangChain and OpenAI Agents SDK integrations. Action identity: tool name plus argument constraints in the DSL; no hash. Approval binding: no human approval; policy allow/deny. Receipts: none stated. Seam: yes (in-process). Code: a repository is expected but its URL and licence were not verified.

### C4. AgentSpec

arXiv 2503.18666 (v1 to v3), 2025; code at https://github.com/haoyuwang99/AgentSpec (licence not verified). A DSL of trigger, predicate and enforcement rules for runtime constraints on code, embodied and driving agents; over 90 percent unsafe-execution prevention in code agents. Action identity: rule triggers on action names; no canonical object. No approval binding, no receipt. Seam: yes (in-process).

### C5. Conseca: Contextual Agent Security: A Policy for Every Purpose

arXiv 2501.17070; HotOS 2025 (Tsai et al., Google). Google-origin, listed because it was asked for. An LLM generates just-in-time, context-specific security policies from trusted context; the policy is then enforced on actions. No action identity, approval binding or receipts stated in the material read; no code found. Document plus prototype.

### C6. ToolEmu

arXiv 2309.15817, ICLR 2024 spotlight; https://github.com/ryoungj/ToolEmu (licence not verified). An LM-emulated sandbox and evaluator for tool-using agents (36 toolkits, 144 test cases; 68.8 percent of identified failures judged valid). Evaluation harness, not enforcement; no action identity, approval or receipt.

### C7. Auditable Agents (arXiv 2604.05485)

Nian, Yuan, Zhang, Li, Zhao (USC); submitted 2026-04-07; accepted to the ACM AI Leadership Summit 2026. Five auditability dimensions with metrics: action recoverability (Action Coverage Rate, Record Fidelity), lifecycle coverage, policy checkability (Structural Policy Decidability Rate, Audit Detection Latency), responsibility attribution, evidence integrity (ordinal Level 0 none to Level 3 digitally signed). Aegis, the pre-execution mediation firewall, records "tool name, full arguments, output, timestamp, and policy decision for each intercepted call", with records "Ed25519-signed, SHA-256 hash-chained"; 8.3 ms median, 23.1 ms P99; blocks all 48 curated attacks with 1.2 percent false positives. The Auditability Card is a six-question coverage disclosure: recorded actions, phases covered, mechanically checkable policies, responsibility chain, integrity protection, behaviour when logs are missing - the most explicit "honest coverage disclosure" artefact found. Code: "are or will be publicly available" (Agent Audit, Aegis, IET); the USC project page could not be fetched (certificate error), so repository URLs and licences are not verified. Action identity: tool name plus full arguments; no canonical hash stated. Approval binding: policy decision per call; human approval not the focus.

### C8. Agent Control Protocol: Admission Control for Agent Actions

arXiv 2603.18829 (v1 2026-03-19, v5 by 2026-04-30), Marcelo Fernandez, TraslaIA; code https://github.com/chelof100/acp-framework-en, Apache-2.0, Go reference (23 packages), plus Python, TypeScript and Rust; 73 signed conformance vectors; OpenAPI 3.1 with 17 endpoints; Docker Compose. Admission invariant `ValidIdentity AND ValidCapability AND ValidDelegationChain AND AcceptableRisk`; Ed25519 (ACP-SIGN-1.0) with hybrid ML-DSA-65 (ACP-SIGN-2.0); single-use Execution Tokens with 300-second validity; a signed Policy Context Snapshot at execution time; hash-chained audit ledger; `PatternKey(agentID, capability, resource)` for history-aware risk scoring at sub-microsecond evaluation. Action identity: capability plus resource plus agent, not a canonical hash of full arguments. Approval binding: execution token per admitted action; human approval is not modelled as a state. Receipts: signed and chained. Seam: yes (gateway). Local: yes.

### C9. Before the Tool Call / Open Agent Passport (OAP)

arXiv 2603.20953, Uchi Uchibeke, submitted 2026-03-21; spec https://github.com/aporthq/aport-spec (v1.0, "draft" and "Stable" badges both present, last updated 2026-02-15). Synchronous pre-execution interception, declarative policy, "cryptographically signed audit record", 53 ms median over 1,000 decisions, 0 percent social-engineering success under a restrictive policy across 879 attempts. Objects: Passport (identity and capabilities), Decision, Proof; Ed25519. Licence discrepancy: the paper says Apache-2.0, the spec repository says MIT. How a Decision binds to the exact arguments (hash or canonicalisation) is not stated on the pages read. Seam: yes. Local: conformance runner and SDKs; hosted APort service exists.

### C10. Agent Passport System (aeoess) - distinct from OAP despite the name

https://github.com/aeoess/agent-passport-system, Apache-2.0, 45 stars, 1,208 commits, 97 percent line coverage, conformance suite. Content-addressed `action_ref`; "3-signature action chain: agent signs intent, policy engine signs evaluation, agent signs execution receipt"; Ed25519 with RFC 8785 JCS canonicalisation; receipt types ActionReceipt, AuthorityBoundaryReceipt, CustodyReceipt, ContestabilityReceipt, PaymentReceipt, APSBundle; each receipt carries `scope_of_claim` stating "what the receipt does and does not prove"; delegation with monotonic narrowing and cascade revocation; in-browser verifier with "nothing uploaded". This is the nearest open implementation to CAVA's canonical-fingerprint plus bound-approval plus receipt design, and its `scope_of_claim` is a coverage-disclosure field at receipt level. Not on arXiv; TypeScript reference.

### C11. Explanation-Bound Tool Execution for AI Agents

arXiv 2607.25364 (2026-07-28, v2 2026-07-29), Zhu, Wang et al.; Accentrust, Georgia Tech, UIUC. Typed action claims bound to server-held facts ("intent, policy, payload, tool, risk, provenance, and freshness"); "conflicts deny, incomplete or uncertain claims review, and only matching claims remain eligible for governed execution"; "minimized audit packets" in a versioned reference profile. Action identity: yes, the typed claim set. Approval binding: review state for uncertain claims. Receipt: audit packets; signing not stated. Code: not indicated.

### C12. A Black Box for Agentic Processes: Blockchain-Anchored Evidence

arXiv 2609.04017, Arslan Brömme, independent researcher, draft v0.9.1.5 dated 2026-09-03. Position and architecture paper. Pipeline "Capture -> Canonicalize -> Hash -> Anchor -> Certify -> Verify" with RFC 8785 JCS canonical JSON and SHA-512 digests; minimal event object with `event_id`, `actor`, `artifact_hash`, `approval_ref`, `sequence_number`, `previous_event_hash`; approvals and subsequent tool parameters anchored separately so that "human approval preceded execution" can be verified. No code; explicitly "does not prevent agent misbehavior or prove semantic truth".

### C13. Proof-Carrying Certificates for LLM Pipelines

arXiv 2605.16407, George Koomullil, 2026-05-13. Lean 4 machine-checked certificates (kernel type-check plus sorry-free axiom audit) in three families including "Hoare-style agent action"; 22 certificate types in a compiled Lean artifact (repository URL not shown). Formal proof rather than cryptographic signature; no canonical action identity stated; not a runtime seam.

### C14. Policy Cards

arXiv 2510.24383, Juraj Mavračić, 2025-10-28; CC BY 4.0; Zenodo 10.5281/zenodo.17391796. Machine-readable, version-controlled deployment-layer allow/deny rules and evidentiary requirements; no approval binding, no signing, no code repository listed. Document plus schema.

### C15. ActPlane: OS-Level Policy Enforcement for Agent Harnesses

arXiv 2606.25189 (2026-06-23, rev. 2026-06-30), Zheng et al.; code https://github.com/eunomia-bpf/ActPlane (licence not verified). eBPF kernel enforcement plus an information-flow DSL over "concrete system actions" that tool-level guardrails miss; 1.9 to 8.4 percent overhead. Action identity at the syscall/event level; no approval binding or receipts stated.

### C16. Audita

arXiv 2608.22160 v2 (2026-08-29), Du and Chen, Duke; code https://github.com/ZhixuDu/audita, MIT. Every inter-agent message is a signed tuple (author, payload, citation set, effect predicate, Ed25519 signature) sealed into an append-only Merkle-committed log; records partition into certified, suspect and missing; counterfactual replay for causal attribution. Message-level identity and effect commitment rather than a canonical action object; no human approval state.

### C17. Other 2026 papers touching the criteria

- Deontic Policies for Runtime Governance of Agentic AI Systems (arXiv 2606.19464, 2026-06-17; Joshi, Finin, Joshi, Kagal): AgenticRei, OWL deontic policies evaluated by a logic engine "entirely outside the LLM"; no action identity, approval binding, attestation or code.
- Taming Various Privilege Escalation in LLM-Based Agent Systems (arXiv 2601.11893, 2026-01-17; Ji et al.): SEAgent, MAC/ABAC over an information-flow graph of agent-tool interactions; no attestation; code not indicated.
- Ethical Hyper-Velocity (arXiv 2605.17909, 2026-05-18/31; Sharma): TEE-attested execution, grammar-constrained decoding, OSCAL-formatted audit logs, TLA+ model checking; no code.
- From Governance Norms to Enforceable Controls (arXiv 2604.05229, 2026-04-06; Koch): standards-to-controls translation method; document.
- CaMeL, Defeating Prompt Injections by Design (arXiv 2503.18813, Google DeepMind/ETH; https://github.com/google-research/camel-prompt-injection): capability labels on data flows enforced at tool-call time; Google-origin, listed for completeness; no receipts.
- LlamaFirewall (arXiv 2505.03574, Meta, in PurpleLlama): PromptGuard 2, AlignmentCheck (chain-of-thought audit), CodeShield; content and reasoning scanning, no approval binding or receipts.
- Agent hijacking literature: the NIST blog (A2) and AgentDojo (ETH Zurich) are the evaluation baseline; arXiv 2602.10453 (prompt-injection taxonomy) and 2604.23280 (AI identity standards survey) surfaced in search but were not read.

---

## Closing table

Legend: Y yes; N no; P partial; n.v. not verified this session. "Type": Doc = guidance document; Spec = specification text; Code = runnable implementation.

| Item | Type | Action identity | Approval bound to action | Receipt (signed / hashed) | Enforcement seam | Local | Licence |
|---|---|---|---|---|---|---|---|
| OWASP Top 10 Agentic 2026 | Doc | N | N | N | N | n/a | CC BY-SA 4.0 |
| OWASP Securing Agentic Applications Guide 1.0 | Doc | N (n.v.) | N (n.v.) | N (n.v.) | N | n/a | CC BY-SA 4.0 |
| OWASP Agent Control Standard v0.1 | Spec + Code (TS) | P (tool name, arguments envelope; no fingerprint stated) | P (ask disposition; hash binding not stated) | P (OTel span, OCSF event, JSONL; unsigned) | Y (16 hooks) | Y | Apache-2.0 / CC BY-SA 4.0 |
| NIST AI 600-1 | Doc | N | N | N | N | n/a | US Gov |
| NIST agent hijacking blog + agentdojo-inspect | Doc + Code (eval) | N | N | N | N (evaluation) | Y | n.v. |
| NIST AI Agent Standards Initiative / NCCoE concept paper / RFI | Doc | N | N | N | N | n/a | US Gov |
| NIST COSAIS agent overlays | Doc (not yet drafted) | N | N | N | N | n/a | US Gov |
| ISO/IEC 42001:2023 | Doc | N | N | N | N | n/a | ISO paid |
| CSA MAESTRO | Doc + Code (analyzer app) | N | N | N | N | Y (app) | MIT (repo) |
| CSA Agentic AI IAM | Doc | N | P (advocates per-action PDP) | P (logEntrySignature field) | N | n/a | n.v. |
| CoSAI Principles | Doc | N | N | N | N | n/a | n.v. |
| OpenTelemetry GenAI conventions | Spec | P (tool name, call id, arguments) | N | P (span, unsigned) | N | Y | Apache-2.0 |
| OTel issue #373 tool risk attrs | Proposal | N | P (risk band only) | N | N | - | - |
| in-toto RFC #554 agent-decision | Proposal | P (tool + SHA-256 args digest) | P (policy decision) | Y (DSSE signed) | N | - | - |
| sigstore-a2a | Code | N (Agent Card) | N | Y for cards only | N | Y | Apache-2.0 |
| open-source instruction-file signing action | Code | N | N | Y for instruction files | N | N (CI) | Apache-2.0 |
| AGNTCY Identity | Spec + Code | N (agent badge) | N | Y for identity VC | N | Y | Apache-2.0 |
| W3C VC 2.0 per-action credentials | - | not found | not found | not found | - | - | - |
| MCP spec 2025-11-25 (tools) | Spec | P (name + arguments) | P (client SHOULD confirm) | N | Y by convention | Y | MIT (spec repo, n.v.) |
| A2A 1.0 | Spec | N | P (input-required state) | Y for Agent Card (JWS) | N | Y | Apache-2.0 (n.v.) |
| IETF OAuth agent drafts | Spec (drafts) | N | N | N | N | - | IETF |
| Dapr 1.18 history signing | Code | N (history event) | N | Y (Ed25519/ECDSA/RSA, SHA-256 chain) | N (records) | Y with control plane | Apache-2.0 (n.v.) |
| Invariant Guardrails / gateway | Code | N | N | P (traces, unsigned) | Y | Y | Apache-2.0 |
| Invariant mcp-scan (Agent Scan) | Code | N | N | N | N (scanner) | Y | Apache-2.0 |
| NeMo Guardrails | Code | N | N | N | Y (execution rails) | Y | Apache-2.0 |
| Guardrails AI | Code | N | N | N | N (I/O only) | Y | Apache-2.0 |
| Lakera Guard | SaaS | N | N | N | Y (content) | N | proprietary |
| agentgateway | Code | N | N | P (OTel) | Y | Y | Apache-2.0 |
| ToolHive | Code | N | N | P (OTel, logs) | Y | Y | Apache-2.0 |
| MCP Guardian | Code | N | Y (human approve/deny per message) | P (log, unsigned) | Y | Y | Apache-2.0 |
| Lasso mcp-gateway | Code | N | N | P (SQLite/DuckDB) | Y (content) | Y | MIT |
| Docker mcp-gateway | Code | N | N | P (logs) | Y (interceptors, n.v.) | Y | MIT |
| IBM ContextForge | Code | N | N | P (OTel) | Y | Y | Apache-2.0 |
| Pipelock | Code | P (JCS canonical JSON, no schema) | Y (ask action; receipt binds verdict + policy hash) | Y (Ed25519 over JCS) | Y | Y | Apache-2.0 core, ELv2 |
| mcpkernel | Code | P (hashed inputs/outputs) | N | Y (Sigstore) | Y | Y | Apache-2.0 |
| Kong ai-mcp-proxy | Code (Enterprise) | N | N | P (audit log) | Y | Y (self-hosted) | proprietary |
| Cloudflare MCP Server Portals | SaaS | N | N | P | Y | N | proprietary |
| Portkey gateway | Code | N | N | P | N (MCP guardrails pending) | Y | MIT |
| LiteLLM tool_permission | Code | N | N | Enterprise | Y | Y | MIT core |
| Mastra beforeToolCall approval | Code | P (fingerprint of tool + args) | Y (single-use, same canonical args) | N | Y | Y | Apache-2.0 + EE |
| CAVA (target) | Spec + open-core Code | Y (nine fields, H(canon(C(a))), SHA-256) | Y (fingerprint + policy version + actor + session + scope + receipt + time window) | Y (hashed; signing optional) | Y (Bounded Action Firewall) | Y | n.v. (open-core) |
| PCAA (target) | Paper | P (envelope E(a); no algorithm) | Y (approval checkpoint, Q_h(a)) | P (certificate; no algorithm) | Y (five checkpoints) | n/a (no code) | arXiv non-exclusive |
| Progent | Paper + Code (n.v.) | P (DSL constraints) | N (policy only) | N | Y | Y | n.v. |
| AgentSpec | Paper + Code | P (rule triggers) | N | N | Y | Y | n.v. |
| Conseca | Paper | N | N | N | Y (prototype) | n.v. | - |
| ToolEmu | Paper + Code | N | N | N | N (eval) | Y | n.v. |
| Auditable Agents / Aegis | Paper + Code (n.v.) | P (name + full args) | P (policy decision per call) | Y (Ed25519, SHA-256 chain) | Y | Y | n.v. |
| Agent Control Protocol (TraslaIA) | Paper + Spec + Code | P (agent, capability, resource; execution token) | Y (single-use 300 s token) | Y (Ed25519 / ML-DSA-65, hash chain) | Y | Y | Apache-2.0 |
| Open Agent Passport (APort) | Paper + Spec + Code | P (Decision object; binding not stated) | P | Y (Ed25519) | Y | Y | MIT (spec) / Apache-2.0 (paper) |
| Agent Passport System (aeoess) | Spec + Code | Y (content-addressed action_ref, JCS) | Y (three-signature chain) | Y (Ed25519; scope_of_claim) | Y (gateway) | Y | Apache-2.0 |
| Explanation-Bound Tool Execution | Paper | Y (typed action claims) | P (review state) | P (audit packets) | Y (mediation) | n.v. | - |
| Black Box for Agentic Processes | Paper | P (event_id, artifact_hash, JCS, SHA-512) | Y (approval_ref precedes execution) | Y (hash, anchored; signing via certify) | N (position) | n/a | - |
| Proof-Carrying Certificates (Lean) | Paper + artifact | N | N | Y (formal proof, not signature) | N | Y | - |
| Policy Cards | Paper + schema | N | N | N | N | n/a | CC BY 4.0 |
| ActPlane | Paper + Code | P (syscall-level) | N | N | Y (eBPF) | Y (Linux) | n.v. |
| Audita | Paper + Code | P (signed message tuple) | P (effect predicate) | Y (Ed25519, Merkle) | N (log) | Y | MIT |
| Deontic Policies (AgenticRei) | Paper | N | N | N | Y (logic engine) | n.v. | - |
| SEAgent MAC | Paper | P (attribute labels) | N | N | Y | n.v. | - |
| EHV | Paper | N | N | P (OSCAL logs, TEE attestation) | Y (design) | n/a | - |
| CaMeL | Paper + Code | P (capabilities on data) | N | N | Y | Y | n.v. |
| LlamaFirewall | Code | N | N | N | Y (content) | Y | n.v. |

## Not found / not verified

- No standards-body artefact (OWASP, NIST, ISO, CSA, OTel, in-toto, W3C, IETF) defines a canonical action identity object; the two nearest are open proposals (in-toto #554, OTel #373) with no maintainer response as of the pages read.
- No W3C VC 2.0 credential issued per agent action was found in any project.
- NIST AI 600-1 body text: PDF unreadable by the fetch tool; agent-related suggested actions not verified.
- NIST RFI (Federal Register, 2026-01-08): page redirected to a block page; questions not read.
- NIST COSAIS agent overlay: no draft found; only the use-case listing.
- ISO/IEC JTC 1/SC 42 agent work item: none found; the 22989-revision claim is from a secondary arXiv source.
- OWASP Securing Agentic Applications Guide 1.0 control text: not extracted (download only).
- OWASP ACS donor: not named on any page read; inferred from the AGT dependency and the name.
- Aegis / Agent Audit repository URLs and licences: USC page fetch failed (certificate error).
- Progent, AgentSpec, ToolEmu, ActPlane, CaMeL, agentdojo-inspect repository licences: not read.
- Dapr licence file: not read (Apache-2.0 assumed from CNCF status).
- Docker mcp-gateway interceptors (block/exec, verify-signatures, block-secrets): described in Docker blog posts surfaced by search; the README fetched shows only "logging and call tracing".
- Enkrypt, Lunar MCPX, mcpg Slack tool-gate, vedantnimbarte/mcp-gateway: licence and semantics from search summaries only.
- Pipelock was read via a fork (glatinone) showing 0 stars; upstream adoption figures not verified.
- OAP licence conflict (paper Apache-2.0 vs repository MIT): unresolved.
- Lakera acquisition by Check Point: search summary and docs branding only.
- AP2 mandates as verifiable credentials: repository landing page does not state it; not verified.
- RFC 9396 relevance: stated from background knowledge, not read this session.
- Whether Dapr history signing covers external/approval events: not stated in the docs read.
- PCAA hashing/signature algorithm and canonical form: not specified in the paper; no code.
- CAVA open package licence: not shown on the arXiv pages read.
