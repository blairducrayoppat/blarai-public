# OpenAI and Google: runtime agent-governance surfaces (documentation-level survey, 2026-09-16)

**Scope.** This is a documentation-level survey, current as of 2026-09-16, of what OpenAI and Google publish that governs what an AI agent is allowed to *do* (tool calls, side effects), binds a human approval to a specific action, records a verifiable receipt or audit of decisions, or normalises actions across runtimes. Only official sources were read (OpenAI: platform/developers.openai.com and its redirect hosts, openai.github.io, openai.com, github.com/openai; Google: adk.dev (the redirect target of google.github.io/adk-docs), docs.cloud.google.com / cloud.google.com, github.com/google, a2a-protocol.org, github.com/a2aproject). Nothing was executed against a live SDK; every claim below is what the documentation or the published source code says, with the reading method noted where it matters. The survey exists to be compared against three external designs: **CAVA** (a hashed canonical action object that approvals bind to), **PCAA** (a five-checkpoint route-review-prove certificate: guard, create action, record assumption, wait for approval, update outcome), and **Microsoft's Agent Framework / Agent Governance Toolkit / Agent Control Specification** (eight interception points, allow/deny/transform verdicts, content-bound approval identity). Each item reports: what it is, official URL, status and date, the action identity at the decision point, whether an approval is bound to the specific call and how, whether a decision record is written and in what form, whether it runs locally or needs the vendor's API, and licence. Exact phrasing is quoted where load-bearing. Anything not found is marked as such in the section and collected again at the end.

Three host changes observed today, worth knowing before following any older link: `platform.openai.com/docs/...` now 301-redirects to `developers.openai.com/api/docs/...`; `developers.openai.com/codex/...` now 308-redirects to `learn.chatgpt.com/docs/...` (branded "ChatGPT Learn"); `google.github.io/adk-docs/...` now 301-redirects to `adk.dev/...`.

---

## Sources actually read

Fetched and read (page or raw source):

OpenAI
- https://openai.github.io/openai-agents-python/human_in_the_loop/
- https://openai.github.io/openai-agents-python/guardrails/
- https://openai.github.io/openai-agents-python/tracing/
- https://openai.github.io/openai-agents-python/ref/lifecycle/
- https://openai.github.io/openai-agents-python/ref/tool_guardrails/
- https://openai.github.io/openai-agents-python/ref/run_state/
- https://openai.github.io/openai-agents-python/mcp/
- https://openai.github.io/openai-agents-python/release/
- https://raw.githubusercontent.com/openai/openai-agents-python/main/src/agents/run_state.py
- https://raw.githubusercontent.com/openai/openai-agents-python/main/src/agents/run_context.py
- https://raw.githubusercontent.com/openai/openai-agents-python/main/src/agents/_tool_invocation.py
- https://raw.githubusercontent.com/openai/openai-agents-python/main/src/agents/items.py
- https://raw.githubusercontent.com/openai/openai-agents-python/main/src/agents/tool_context.py
- https://github.com/openai/openai-agents-python (README: licence, provider support)
- https://github.com/openai/openai-agents-python/issues/2775 and /issues/2868
- https://openai.github.io/openai-agents-js/guides/guardrails/
- https://raw.githubusercontent.com/openai/openai-agents-js/main/docs/src/content/docs/guides/human-in-the-loop.mdx (the rendered docs page returned navigation only; the source of the same page was read instead)
- https://raw.githubusercontent.com/openai/openai-agents-js/main/packages/agents-core/src/runState.ts
- https://raw.githubusercontent.com/openai/openai-agents-js/main/packages/agents-core/src/runContext.ts
- https://raw.githubusercontent.com/openai/openai-agents-js/main/packages/agents-core/src/toolInvocation.ts
- https://github.com/openai/openai-agents-js (README: licence)
- https://developers.openai.com/api/docs/guides/tools-connectors-mcp
- https://developers.openai.com/api/docs/guides/agent-builder
- https://developers.openai.com/api/docs/guides/node-reference
- https://developers.openai.com/api/docs/guides/agent-builder/migrate-from-agent-builder
- https://developers.openai.com/api/docs/guides/agent-builder-safety
- https://developers.openai.com/api/docs/guides/agents
- https://developers.openai.com/api/docs/guides/agents/guardrails-approvals
- https://developers.openai.com/api/docs/guides/agents/running-agents
- https://developers.openai.com/api/docs/changelog
- https://developers.openai.com/api/docs/deprecations
- https://developers.openai.com/cookbook/examples/partners/agentic_governance_guide/agentic_governance_cookbook
- https://github.com/openai/openai-guardrails-python
- https://learn.chatgpt.com/docs/agent-approvals-security (redirect target of developers.openai.com/codex/agent-approvals-security)
- https://learn.chatgpt.com/docs/config-file/config-advanced (redirect target of developers.openai.com/codex/config-advanced)
- https://learn.chatgpt.com/docs/sandboxing
- https://learn.chatgpt.com/docs/cloud/internet-access (redirect target of developers.openai.com/codex/cloud/internet-access)
- https://github.com/openai/codex (README: licence)
- https://cdn.openai.com/papers/practices-for-governing-agentic-ai-systems.pdf (text extracted locally with pypdf from the downloaded file)
- https://cdn.openai.com/pdf/e37d949b-8c9f-4d76-b99e-4272f4631a7e/openai-frontier-governance-framework.pdf (text extracted locally with pypdf)

Google
- https://adk.dev/callbacks/types-of-callbacks/
- https://adk.dev/callbacks/design-patterns-and-best-practices/
- https://adk.dev/plugins/
- https://adk.dev/tools-custom/confirmation/ (adk.dev/tools/confirmation/ now redirects here)
- https://adk.dev/runtime/resume/
- https://adk.dev/safety/
- https://adk.dev/agents/models/
- https://github.com/google/adk-python and /releases
- https://raw.githubusercontent.com/google/adk-python/main/src/google/adk/tools/tool_confirmation.py
- https://raw.githubusercontent.com/google/adk-python/main/src/google/adk/flows/llm_flows/functions.py
- https://a2a-protocol.org/latest/specification/
- https://a2a-protocol.org/latest/topics/enterprise-ready/
- https://a2a-protocol.org/latest/
- https://a2a-protocol.org/latest/blog/archive/2026/
- https://a2a-protocol.org/latest/blog/2026/03/12/a2a-protocol-ships-v10-production-ready-standard-for-agent-to-agent-communication/
- https://a2a-protocol.org/latest/blog/2026/08/27/a-new-chapter-for-a2a-joining-the-agentic-ai-foundation/
- https://github.com/a2aproject/A2A
- https://docs.cloud.google.com/security-command-center/docs/model-armor-overview
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/overview
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/semantic-governance-overview
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/configure-semantic-governance
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/configure-iam-policies
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/gateways/agent-gateway-overview
- https://docs.cloud.google.com/agent-builder/agent-engine/agent-identity
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/release-notes (full page, three offsets)
- https://cloud.google.com/blog/products/ai-machine-learning/new-enhanced-tool-governance-in-vertex-ai-agent-builder

Blocked (HTTP 403 from both fetchers) — content known only from search-result snippets and, where available, the companion PDF:
- https://openai.com/index/introducing-agentkit/
- https://openai.com/index/running-codex-safely/
- https://openai.com/index/openai-frontier-governance-framework/ (PDF read instead)
- https://openai.com/index/practices-for-governing-agentic-ai-systems/ (PDF read instead)
- https://help.openai.com/en/articles/11509118-admin-controls-security-and-compliance-in-apps-enterprise-edu-and-business

---

# Part A — OpenAI

## A1. OpenAI Agents SDK (Python and JS/TS)

**What it is.** Open-source, in-process agent framework. Python: https://openai.github.io/openai-agents-python/ ; JS/TS: https://openai.github.io/openai-agents-js/ . **Licence:** MIT (both repositories). **Status:** pre-1.0. The Python release page documents 0.22.0 as the most recent version and states the policy: "We will increase minor versions `Y` for **breaking changes** to any public interfaces that are not marked as beta." No GA label exists. **Local operation:** the README calls the SDK "provider-agnostic, supporting the OpenAI Responses and Chat Completions APIs, as well as 100+ other LLMs" (optional `any-llm` / LiteLLM extras); guardrails, approvals and hooks execute in the caller's process. The one vendor-bound default is tracing (below).

### Guardrails (input, output, tool; tripwires)

- Input guardrails "run on the initial user input" and "run only for the first agent in the chain." Default is parallel — the guardrail "runs concurrently with the agent's execution"; with `run_in_parallel=False` it "runs and completes _before_ the agent starts."
- Output guardrails "run on the final agent output" and "run only for the agent that produces the final output"; they "always run after the agent completes."
- Tool guardrails "wrap **`FunctionTool` instances** and let you validate or block calls to those tools before and after execution." "Input tool guardrails run before the tool executes" and "Output tool guardrails run after the tool executes." Decorators `@tool_input_guardrail` / `@tool_output_guardrail`; JS equivalents `defineToolInputGuardrail` / `defineToolOutputGuardrail`.
- Verdict type (Python reference, verbatim):
  - `ToolGuardrailFunctionOutput` has `output_info: Any` ("Optional data about checks performed.") and `behavior: RejectContentBehavior | RaiseExceptionBehavior | AllowBehavior`.
  - `allow()` — "Create a guardrail output that allows the tool execution to continue normally."
  - `reject_content(message)` — "Create a guardrail output that rejects the tool call/output but continues execution."
  - `raise_exception()` — "Create a guardrail output that raises an exception to halt execution."
  - There is no *transform* verdict: a tool input guardrail can allow, replace the tool's result with a message, or abort; it cannot rewrite the arguments. (Compare ACS's allow/deny/transform.)
- Tripwires: `tripwire_triggered=True` raises `InputGuardrailTripwireTriggered`, `OutputGuardrailTripwireTriggered`, `ToolInputGuardrailTripwireTriggered`, `ToolOutputGuardrailTripwireTriggered`; "The exception's `guardrail_result` identifies which guardrail triggered it."
- What a tool guardrail sees: `ToolInputGuardrailData(context: ToolContext, agent: Agent)`. `ToolContext` fields (source, verbatim docstrings): `tool_name` — "The name of the tool being invoked."; `tool_call_id` — "The ID of the tool call."; `tool_arguments` — "The raw arguments string of the tool call."; plus `tool_call`, `tool_namespace`, `agent`, `run_config`. So the decision input is name + provider call id + raw argument string; no canonicalised or hashed form is presented to the guardrail.
- Ordering relative to approval: the guardrails page (as surfaced in search) states "If a function tool requires approval, input tool guardrails normally run after approval and immediately before execution." (This sentence was not in the excerpt my fetch returned; treat as page-attributed but not re-verified.)

### Human-in-the-loop tool approval

- Declaration: `@tool(needs_approval=True)` (Python) / `needsApproval: true` (JS), or an async predicate. Python signature as documented: `async def requires_review(_ctx, params, _call_id) -> bool` — the callable receives "the run context, parsed tool parameters, and the tool call ID." Fail-closed detail: if arguments are malformed, missing, empty, or contain non-standard constants like `NaN` or `Infinity`, "the callable is not invoked and the call requires manual approval." JS: "the SDK calls it only after the tool arguments have parsed into an inspectable object."
- Interruption: "the tool call does not execute. Instead, the run records a `RunToolApprovalItem`" (JS); "`RunResult.interruptions` (or `RunResultStreaming.interruptions`) contains `ToolApprovalItem` entries" (Python).
- Resolution: `state.approve(item)` / `state.reject(item)`; Python signatures (source): `approve(self, approval_item: ToolApprovalItem, always_approve: bool = False) -> None`; `reject(self, approval_item, always_reject: bool = False, *, rejection_message: str | None = None) -> None`. `always_approve`/`always_reject` "persist the same decision for future calls to the same tool identity during the rest of the run"; otherwise "Per-call approvals are scoped to the specific call ID." JS: "`{ alwaysApprove: true }` or `{ alwaysReject: true }` if the same tool should stay approved or rejected for the rest of the run"; exact per-call decisions "take precedence" over sticky defaults.
- Official framing (developers.openai.com running-agents guide): "Treat approvals as paused runs, not as new turns. That distinction keeps turn counts, history, and server-managed continuation IDs consistent." and "If the run pauses for approval, resolve `interruptions` and resume from `state` rather than starting a fresh user turn."

### Action identity at the approval point

- The item the human sees: `ToolApprovalItem` (Python source) with `raw_item` ("Raw tool call awaiting approval (function, hosted, shell, etc.)"), `tool_name` ("Tool name for approval tracking; falls back to raw_item.name when absent."), `tool_namespace`, `tool_origin` ("Optional metadata describing where the approved tool call came from."), `tool_lookup_key` ("Canonical function-tool lookup metadata when the approval targets a function tool."), and properties `name`, `qualified_name`, `arguments` ("Return tool call arguments if present on the raw item."), `call_id` ("Return call identifier from the raw item."). Equality is object identity (`__eq__` / `__hash__` return `object.__hash__(self)` to keep "distinct approvals separate").
- The identity used for matching (Python `_tool_invocation.py`): a four-tuple `(invocation_type, call_id, approval_scope, fingerprint)`. The fingerprint is a SHA-256 over a sorted-JSON "semantic payload" that includes the normalised `arguments`: `semantic_payload[field_name] = _normalize_arguments(value) if field_name == "arguments" else _normalize_value(value, exclude_none=True)` and `hashlib.sha256(encoded).hexdigest()`. This is the closest thing in either vendor's stack to a CAVA-style canonical hash — but it is an internal matching key, never surfaced to the approver, never written to a record, and not stable across SDK versions by contract.
- JS (`toolInvocation.ts`): `getToolInvocationFingerprint` returns `stableStringify({ caller, type, toolName, payload })` where `payload` is the arguments (`toolCall.arguments`, or `action`/`operation` for shell/patch/computer calls). Same content-awareness, **no cryptographic hash** — it is a canonical string, not a digest.
- Storage of decisions (both SDKs): a map keyed by tool name (Python: `_approvals: dict[str | HostedMCPApprovalKey, _ApprovalRecord]`, hosted-MCP keys being `("hosted_mcp", server_label, tool_name)`); each record has `approved: bool | list[call_id]` and `rejected: bool | list[call_id]` (JS: `approved: boolean | string[]`, `rejected: boolean | string[]`, optional `messages`, `stickyRejectMessage`). `always_approve` writes the boolean `true`; a per-call approval appends the call id. JS `isToolApproved({toolName, callId, functionTool?, agent?})` returns "true if the tool call has been approved, false if blocked and undefined if not yet approved or rejected."

### Can an approval be replayed for different arguments?

- Per-call approval: no — it is bound to the provider call id (and, in Python, matched through the argument-inclusive fingerprint). A different call with different arguments is a new interruption.
- `always_approve` / `alwaysApprove`: yes, by design — the record becomes `approved: true` for the tool name for the rest of the run, so any later arguments to that tool pass without a further pause. The docs describe this as intended ("stay approved ... for the rest of the run"); nothing narrows it to an argument pattern.
- Derived, not documented: because the run state is unsigned JSON (next section), the approvals map is only as trustworthy as whatever stores it; nothing in the SDK detects an edited `approved` list on resume.

### Run state: serialised, not signed

- Python: `to_string()` is `json.dumps(self.to_json(...), indent=2)`; `from_json()` runs `_validate_run_state_schema_version(...)` and structural validation; `CURRENT_SCHEMA_VERSION = "1.17"`; "older SDKs reject newer or unsupported versions." No HMAC, signature, or encryption anywhere in the file.
- JS: `CURRENT_SCHEMA_VERSION = '1.20'`; serialisation is `toString()` / `JSON.stringify(result.state)`; `RunState.fromString(agent, serializedState)`. "Sticky decisions created with `{ alwaysApprove: true }` or `{ alwaysReject: true }` are stored in the run state, so they survive `toString()` / `fromString()`."
- Documented caveats: "Serialized run state includes your app context plus SDK-managed runtime metadata such as approvals, usage, serialized `tool_input`..."; "treat `RunContextWrapper.context` as persisted data and avoid placing secrets there unless you intentionally want them to travel with the state."; "If approvals may sit for a while, store a version marker for your agent definitions or SDK alongside the serialized state" (Python); JS: "store your serialized state in a database, or along with your request" and, for version skew, "we currently recommend for you to implement your own branching logic by installing two versions of the Agents SDK in parallel."
- Verdict on the question asked: **merely serialised**. Integrity of a pending approval rests entirely on the application's store.

### Tracing (the only receipt)

- Automatic spans: `agent_span()`, `generation_span()` ("inputs/outputs of the LLM generation"), `function_span()` ("inputs/outputs of function calls"), `guardrail_span()`, `handoff_span()`, `transcription_span()`, `speech_span()`; JS additionally has `GuardrailSpanData`.
- Destination: the default `BackendSpanExporter` sends "traces to OpenAI's backend in batches." Disable with `OPENAI_AGENTS_DISABLE_TRACING=1`, `set_tracing_disabled(True)`, or `RunConfig.tracing_disabled`; redact with `RunConfig.trace_include_sensitive_data`; redirect with `add_trace_processor()` ("an **additional** trace processor") or `set_trace_processors()` ("**replace** the default processors with your own"). "**_Tracing is unavailable for organizations that use OpenAI's APIs under a Zero Data Retention (ZDR) policy._**"
- Form: plain span records. No signing, hashing, or tamper-evidence is documented. **Not found:** any span or event type that records the approval decision itself (who approved, when, against which call id); the trace captures the tool execution, not the approval.

### Hooks

`RunHooks` and `AgentHooks` expose `on_llm_start`, `on_llm_end`, `on_agent_start`/`on_start`, `on_agent_end`/`on_end`, `on_handoff`, `on_tool_start` ("immediately before a local tool is invoked"), `on_tool_end` ("immediately after a local tool is invoked"). All are async observers; the reference documents no return value that blocks, vetoes, or modifies a tool call. Enforcement lives in tool guardrails and `needs_approval`, not hooks.

### Community signal on the repository

Two 2026 issues on `openai/openai-agents-python` argue the gap this survey is probing, and both are closed with no maintainer response visible in the fetched excerpts: #2775 (2026-03-25, "Runtime governance guardrails for OpenAI Agents SDK": existing guardrails cover "prompt/output safety" but not "runtime governance (which tools can be called, by which agents, with what permissions)"; proposes the Agent Governance Toolkit's middleware) and #2868 (2026-04-09, "Per-tool authorization middleware for agent tool calls": "Guardrails check content. Authorization checks permission. Both are needed but they solve different problems."; proposes ALLOW/DENY/MODIFY/DEFER/STEP_UP verdicts plus structured audit logging). These are third-party filings on an official repository, not OpenAI positions.

## A2. AgentKit (Agent Builder, ChatKit, Connector Registry, Guardrails)

**What it is.** The DevDay 2025 (changelog: "Oct 6 - Feature: Launched ChatKit") bundle. The announcement page https://openai.com/index/introducing-agentkit/ returned HTTP 403; the statements below attributed to it come from search-result snippets of that page: Guardrails "is an open-source, modular safety layer that helps protect agents against unintended or malicious behavior"; "Connector Registry is beginning its beta rollout to some API, ChatGPT Enterprise and Edu customers with a Global Admin Console (where Global Owners can manage domains, SSO, multiple API orgs)."

**Agent Builder — deprecated.** Official: "OpenAI is deprecating Agent Builder. Existing users can continue using it during the transition window, and the product is scheduled to shut down on November 30, 2026." Deprecations page: "On June 3, 2026, we notified developers using Agent Builder that the product is being deprecated." Successors: "Agents SDK: Best for building agents through code." and "ChatGPT Workspace Agents: Best for building agents through natural language and sharing them with teams." "ChatKit remains available." The Evals platform and reusable prompt objects were deprecated the same day (evals read-only 2026-10-31, shutdown 2026-11-30).

While it lasts, its governance nodes (node reference, verbatim):
- Human approval node: "Defer to end-users for approval. Useful for workflows where agents draft work that could use a human review before it goes out." Example: a node "configured to ask, 'Would you like me to send this email?' and, if approved, proceeds to an MCP node that connects to Gmail." **Action identity:** whatever the preceding node emitted (an email widget in the example); the reference does not say the node binds to a specific tool call or its arguments. **Not found:** any record of the approval beyond the workflow trace.
- Guardrails node: "Set up input monitors for unwanted inputs such as personally identifiable information (PII), jailbreaks, hallucinations, and other misuse." "Guardrails are pass/fail by default, meaning they test the output from a previous node, and you define what happens next."
- Publishing: "When you're happy with your workflow, publish it to create a new major version that acts as a snapshot."

**Safety guidance for builders** (developers.openai.com agent-builder-safety): "always enable tool approvals so end users can review and confirm every operation, including reads and writes"; guardrails are "not foolproof" but "an effective first wave of protection."

**Guardrails library** (github.com/openai/openai-guardrails-python; MIT). Checks: Keyword Filter, Competitors, Moderation, URL Filter, Secret Keys, Contains PII, Hallucination Detection, Jailbreak, Prompt Injection Detection, NSFW Text, Off Topic Prompts, Custom Prompt Check. Integrates with the Agents SDK via `GuardrailAgent`. **Not local for most checks:** "Guardrails calls paid OpenAI APIs, and developers are responsible for associated charges." It is content classification; it has no notion of tool authorization.

**Connector Registry / admin controls.** The help-centre article (HTTP 403) is known only through snippets: "All apps are disabled by default, and workspace owners can control which apps are enabled in Workspace settings → Apps, as well as assign app specific roles through RBAC"; "if the app supports action controls, admins can also review the app's actions before making the app available." This is workspace-level enablement of connectors, not per-call governance. **Not found:** any 2026 changelog or deprecations entry for Connector Registry, Guardrails, or ChatKit; the registry's status beyond "beta rollout" (Oct 2025) could not be confirmed from an official page.

## A3. Codex CLI / Codex cloud

**What it is.** OpenAI's coding agent (CLI, IDE, cloud). Repository https://github.com/openai/codex, **Apache-2.0**. Docs now live at learn.chatgpt.com (redirects from developers.openai.com/codex/...).

**Approval policies** (agent-approvals-security page): `on-request` — commands the sandbox allows run without approval; approval is required for sandbox escalations, network access, and destructive operations; `never` — "Codex makes a best effort within the constraints you set"; and a granular policy that lets selected categories (sandbox approvals, rules, MCP prompts, permission requests, skill scripts) stay interactive while others auto-reject. The page marks `approval_policy = "untrusted"` as no longer supported. Approval triggers listed: editing outside the workspace, network access, sandbox escalations, destructive app/MCP tool calls, and `request_permissions` prompts.

**Sandbox modes:** `read-only` ("Codex can read files and run commands within the read-only sandbox."), `workspace-write` (default; "read files, make edits, and run commands in the workspace."), `danger-full-access` (alias `--yolo`; "No sandbox; no approvals _(not recommended)_"). Mechanism per OS: macOS "uses Seatbelt policies and runs commands using `sandbox-exec`"; Linux "uses `bwrap` plus `seccomp` by default" (with a bundled fallback helper); Windows uses a native sandbox under PowerShell or the Linux path under WSL2. Network: "By default, the agent runs with network access turned off."

**Codex cloud:** "By default, Codex blocks internet access during the agent phase"; "Setup scripts still run with internet access so you can install dependencies." Allowlist presets None / Common dependencies / All; requests can be limited to "GET, HEAD, and OPTIONS"; "Agent internet access is configured on a per-environment basis." Prompt-injection warning: "Point Codex only to trusted resources and keep internet access as limited as possible."

**Audit (the most concrete decision record either vendor ships).** OpenTelemetry export is "Disabled by default; opt in via `[otel]`" (`exporter = "none"` by default; `otlp-http` / `otlp-grpc`; `log_user_prompt = false`). Events include `codex.tool_decision` (approved/denied, whether the decision came from `config` vs `user`, tool name), `codex.tool_result` (duration, success, output snippet), `codex.user_prompt`, `codex.sse_event`, `codex.api_request`. "Event metadata includes service name, CLI version, env tag, conversation id, model, sandbox/approval settings, and per-event fields." "If `exporter = "none"` Codex records events but sends nothing." These are plain OTLP log records — no hash or signature. **Not found:** whether `codex.tool_decision` carries the command text/arguments or a call id that would let the decision be joined to the executed action.

**"Running Codex safely at OpenAI"** (2026-05-08; HTTP 403; snippets only): OpenAI runs a managed network policy that "allows expected destinations, blocks destinations they do not want Codex reaching, and requires approval for unfamiliar domains"; command rules so that "Common benign commands ... are allowed without approval outside of the sandbox and specific dangerous commands can be blocked or require approval"; and it "preserves agent-native telemetry so they can understand and audit what the agent did."

**Action identity / binding / local.** The action is the concrete shell command or tool call shown in the interactive prompt; approval is per-invocation (or rule-based), with no hash or canonical object. Enforcement is the OS sandbox plus the approval gate in the CLI. The CLI, sandbox and OTel pipeline run locally; model inference uses OpenAI's API.

## A4. Policy-level publications relevant to runtime agent governance

**"Practices for Governing Agentic AI Systems"** (Shavit, Agarwal, Brundage, Adler et al.; white paper; still hosted at https://cdn.openai.com/papers/practices-for-governing-agentic-ai-systems.pdf and still surfaced in search beside the 2026 agent guides; the PDF body carries no date — the December 2023 date comes from the announcement page, which returned 403). Seven practices, verbatim section titles: 4.1 Evaluating Suitability for the Task; 4.2 Constraining the Action-Space and Requiring Approval; 4.3 Setting Agents' Default Behaviors; 4.4 Legibility of Agent Activity; 4.5 Automatic Monitoring; 4.6 Attributability; 4.7 Interruptibility and Maintaining Control. Load-bearing passages:
- 4.2: "Requiring a user to proactively authorize these actions, thus keeping a 'human-in-the-loop', is a standard way to limit egregious failures of agentic AI systems." "This raises the key challenge of how a system deployer should ensure that the user has enough context to sufficiently understand the implications of the action they're approving. This is also made harder when the user must approve many decisions and thus must make each approval quickly, reducing their ability to meaningfully consider each one." Also: agents can "periodically 'time out' until a human reviews and reauthorizes them"; "System deployers can bound this problem by ensuring strong network controls to limit agents' interactions with the outside world except through monitored channels."
- 4.4: "It could be useful for system deployers to expose all details of the agents' interactions, such as any inputs it receives from tool-use API calls or interactions with other agents." "Actions that can only be reviewed after the fact should be more easily reversible than those that require approval."
- 4.6: "One idea for such a system of attribution is to have each agentic AI instance assigned a unique identifier, similar to business registrations, which contains information on the agent's user-principal and other key accountability information."
This is the only OpenAI document that names action-approval, action ledgers and agent attribution as governance primitives; it prescribes none of the mechanics (identity, binding, receipt form).

**Frontier Governance Framework** (published 2026-05-28 per search snippets; 22-page PDF read). Sections: systemic risk assessment and mitigation (risk tiers for Cyber offense, CBRN, Harmful manipulation, Loss of control), safety mitigations, critical safety incident response, security risk management, model reporting, external experts, allocation of responsibility, change management. It defines "Loss of control" as "risks arising from humans losing the ability to reliably direct, modify, or shut down a model." The extracted text contains zero occurrences of "agentic" or "runtime" and nothing on approval, audit, or governance of individual agent actions; it is model-level, law-facing (TFAIA, EU AI Act Code of Practice) governance. **Not relevant to runtime action governance** — recorded here so the negative is on file.

**Developer-guide guidance that does speak to runtime mechanics** (developers.openai.com):
- Guardrails and human review: tool guardrails and approval interruptions enforce scope "at the boundary where side effects occur"; for cybersecurity workflows, "Check the proposed target, action, tool arguments, calling identity, and engagement window against the approved scope" and "record decisions and execution outcomes, and fail closed if review times out or becomes unavailable." (Guidance to the developer; the SDK does not itself record decisions.)
- Running agents: "Treat approvals as paused runs, not as new turns."
- Partner cookbook "Building Governed AI Agents" (author not named on the page): "Define policies as code that version, travel, and deploy alongside your applications."; uses `GuardrailsOpenAI`, `GuardrailAgent`, `trace()`; recommends sending spans to internal systems under ZDR. No signing or hashing of audit records is prescribed.

## A5. MCP with approval semantics (Responses API hosted MCP; Agents SDK)

**Responses API hosted MCP tool** (https://developers.openai.com/api/docs/guides/tools-connectors-mcp). `require_approval` takes `"always"`, `"never"`, or an object such as `{"never": {"tool_names": ["ask_question", "read_wiki_structure"]}}`. When approval is needed the response contains:

```json
{
  "id": "mcpr_68a619e1d82c8190b50c1ccba7ad18ef0d2d23a86136d339",
  "type": "mcp_approval_request",
  "arguments": "{\"diceRollExpression\":\"2d4 + 1\"}",
  "name": "roll",
  "server_label": "dmcp"
}
```

and the caller answers with:

```json
{
  "type": "mcp_approval_response",
  "approve": true,
  "approval_request_id": "mcpr_682d498e3bd4819196a0ce1664f8e77b04ad1e533afccbfa"
}
```

chained via `previous_response_id` ("we're using the `previous_response_id` parameter to chain this new Response, with the previous Response that generated the approval request"). `allowed_tools` restricts which server tools are exposed. Warnings: "A malicious server can exfiltrate sensitive data from anything that enters the model's context."; "It is your responsibility to ensure that the MCP server also adheres to any Zero Data Retention or Data Residency requirements."

**Action identity and binding.** The identity is the server-issued `mcp_approval_request.id` (`mcpr_...`); the approver sees `name`, `arguments` (JSON string) and `server_label`. The approval references only the id, so it is bound to that request and cannot be re-used for other arguments, but the caller has no way to assert *what* it approved (no hash of arguments travels with the response); the binding is trusted to OpenAI's server state. **Not documented:** whether the executed call is re-checked against the displayed arguments (it is the same server-side request, so implicitly yes; no statement found). **Receipt:** the request/response items persist in the Response objects; no signed record. **Local:** no — hosted MCP executes on OpenAI's servers.

**Agents SDK.** `HostedMCPTool` takes `require_approval` and an `on_approval_request` callback receiving `MCPToolApprovalRequest` (example inspects `request.data.name`; returns `{"approve": True}` or `{"approve": False, "reason": "Escalate to a human reviewer"}`). Local servers (`MCPServerStdio`, `MCPServerSse`, `MCPServerStreamableHttp`) accept `require_approval` as `"always"`/`"never"`/`True`/`False`, a per-tool map (`{"delete_file": "always", "read_file": "never"}`), or a grouped object; these then flow through the same `needs_approval` interruption path as function tools. Tool exposure is an allowlist: `create_static_tool_filter(allowed_tool_names=[...], blocked_tool_names=[...])` or a dynamic filter over `ToolFilterContext` (`run_context`, `agent`, `server_name`).

---

# Part B — Google

## B6. Agent Development Kit (ADK)

**What it is.** Open-source agent framework (Python, plus TypeScript, Go, Java, Kotlin ports). Docs https://adk.dev/ ; repo https://github.com/google/adk-python , **Apache 2.0**; latest release v2.9.1 (2026-09-15). **Local operation:** model-agnostic — the models page lists LiteLLM, Ollama, vLLM and LiteRT-LM hosting and says "You instantiate a specific wrapper class, such as `ApigeeLlm` or `LiteLlm`, and pass this object as the `model` parameter to your `LlmAgent`." Callbacks, plugins, confirmation and `InMemorySessionService` run in-process with no Google API.

### Callbacks

Six lifecycle callbacks plus error hooks: `before_agent_callback`, `after_agent_callback`, `before_model_callback`, `after_model_callback`, `on_model_error_callback`, `before_tool_callback`, `after_tool_callback`, `on_tool_error_callback`. Python parameter names are fixed: `before_tool_callback(tool, args, tool_context)`; `after_tool_callback(tool, args, tool_context, tool_response)`. Semantics: a `before_tool_callback` that returns a non-empty value short-circuits — the returned dict becomes the tool result and the tool does not run; with several callbacks "ADK invokes them in the order listed and stops at the first one that returns a result." Design-patterns page, verbatim: "Use `before_tool_callback` to inspect tool arguments - If a policy violation is detected... Return a predefined response (`LlmResponse` or `dict`/`Map`) to block the operation" and "`before_tool_callback`: Modify the tool `args` dictionary (or Map in Java)". So ADK's pre-tool seam supports allow, deny-with-substitute-result, and **transform** (mutating `args`) — the same three verdicts as ACS, expressed as return-value conventions rather than a typed verdict.

### Plugins

`BasePlugin` hooks: `on_user_message_callback`, `before_run_callback`, `after_run_callback`, `before_agent_callback`, `after_agent_callback`, `before_model_callback`, `after_model_callback`, `on_model_error_callback`, `before_tool_callback`, `after_tool_callback`, `on_tool_error_callback`, `on_event_callback`. Scope: plugins "Apply to all agents/tools/LLMs in the `Runner`" (agent callbacks "Apply only to the specific agent instance"); plugins run before agent callbacks and "if a Plugin-level agent callback returns any value, and not an empty (`None`) response, the Agent, Model, or Tool-level callback is _not executed_ (skipped)." Listed use cases include "Policy enforcement" and "Logging and tracing." Built-ins: Logging ("Log important information at each agent workflow callback point"), BigQuery Agent Analytics, Reflect and Retry Tools, Context Filter, Global Instruction, Save Files as Artifacts. Supported from Python v1.7.0+, TypeScript v0.2.5+, Go v0.4.0+, Java v0.3.0+, Kotlin v0.7.0+; no experimental marker.

### Tool confirmation (human-in-the-loop)

- "The _Tool Confirmation_ feature in the Agent Development Kit (ADK) allows an ADK Tool to pause its execution and interact with a user or other system for confirmation or to gather structured data before proceeding." Status: "The Tool Confirmation feature is experimental and has some known limitations. We welcome your feedback!" Not supported with `DatabaseSessionService` and `VertexAiSessionService`. `ToolConfirmation` is decorated `@experimental(FeatureName.TOOL_CONFIRMATION)`.
- Declaration: `FunctionTool(reimburse, require_confirmation=True)` or a predicate over the tool's own arguments: `async def confirmation_threshold(amount: int, tool_context: ToolContext) -> bool: return amount > 1000`. Advanced form: `tool_context.request_confirmation(hint="...", payload={...})`; the tool later reads `tool_context.tool_confirmation.confirmed` / `.payload`.
- `ToolConfirmation` fields (source): `hint` ("The hint text for why the input is needed."), `confirmed` ("Whether the tool execution is confirmed."), `payload` ("The custom data payload needed from the user to continue the flow.").
- **Action identity.** The agent emits a function call named `adk_request_confirmation` (`REQUEST_CONFIRMATION_FUNCTION_CALL_NAME = 'adk_request_confirmation'` in `flows/llm_flows/functions.py`) whose args are `'originalFunctionCall': original_function_call.model_dump(exclude_none=True, by_alias=True)` and `'toolConfirmation': tool_confirmation.model_dump(by_alias=True, exclude_none=True)`. The original call (id, name, args) is therefore embedded verbatim in the request the human sees.
- **Binding.** The user replies with a `function_response` whose `id` "must match the `function_call_id` from the pending confirmation request" (`name: "adk_request_confirmation"`, `response: {"confirmed": true, "payload": {...}}`); the runtime resolves the pending call by `fc.id == function_call_id` and then executes the original call as recorded. With the Resume feature, "you also must include the Invocation ID (`invocation_id`) parameter with the confirmation response. The Invocation ID you provide must be the same invocation that generated the confirmation request, otherwise the system starts a new invocation with the confirmation response." Binding is by opaque ids to a stored original call; there is no hash, and no argument-level re-check is documented beyond re-executing the stored call.
- **Record.** The request and response are ordinary session events persisted by the configured session service (plain, unsigned). Resume (docs list ADK Python v1.16.0 / Kotlin v0.1.0) replays from `runner.run_async(user_id=..., session_id=..., invocation_id='invocation-123')`.
- Vertex AI Agent Builder blog (2025-12-18) framing: "You can now pause for human input anywhere, even inside complex workflows. ADK automatically remembers exactly where the agent stopped and resumes immediately after approval."

### Safety guidance

adk.dev/safety: two identity models — agent-auth ("The tool interacts with external systems using the agent's own identity") and user-auth (the tool uses "the identity of the controlling user"); "Design tools defensively, using developer-set tool context to enforce policies"; the Before Tool Callback validates against "the agent's state, the requested tool and parameters"; "Sandboxing must be used to prevent model-generated code to compromise the local environment."; a Model Armor plugin "Queries the Model Armor API to check for content safety violations at specified execution points." The page does not prescribe human approval for high-risk actions or any audit format.

## B7. Agent-to-Agent protocol (A2A)

**What it is.** Wire protocol for agent interoperability. Spec https://a2a-protocol.org/latest/specification/ , version **1.0.0**, shipped 2026-03-12 ("A2A Protocol Ships v1.0: Production-Ready Standard for Agent-to-Agent Communication"). **Licence:** "The A2A Protocol is licensed under the Apache License 2.0". **Governance:** "A2A was originally developed by Google and donated to the Linux Foundation."; on 2026-08-27 it was "officially accepted as a Growth Stage project at the Agentic AI Foundation (AAIF)" — "By operating under the Linux Foundation-directed AAIF alongside sibling projects like MCP, goose, and AGENTS.md, A2A is protected from single-vendor constraints." Technical Steering Committee: "AWS, Cisco, Google, IBM Research, Microsoft, Salesforce, SAP, and ServiceNow". **Local:** a protocol; implementations run anywhere.

**Authorization.** The Agent Card declares `securitySchemes` (API key, HTTP basic/bearer, OAuth 2.0 authorization-code / client-credentials / device-code, OpenID Connect, mutual TLS). "Clients sending requests must authenticate using one of the schemes declared in the public AgentCard.securitySchemes and AgentCard.security fields."; servers must "reject requests with invalid or missing authentication credentials" and "return an authorization error when the authenticated client lacks required permissions." Enterprise-ready topic: "Identity is established at the transport/HTTP layer"; authorization is at skill granularity — "specific OAuth scopes should grant an authenticated client access to invoke certain skills but not others"; implementers must apply "the Principle of Least Privilege". v1.0 adds "Signed Agent Cards" giving "cryptographic verification of agent identity and metadata" (spec section 8.4 Agent Card Signing, JWS with canonicalisation).

**Approvals / human-in-the-loop.** The protocol is "Designed for (potentially very) long-running tasks and human-in-the-loop interactions." The only primitives are two interrupted task states: `TASK_STATE_INPUT_REQUIRED` — "Indicates that the agent requires additional user input to proceed. This is an interrupted state."; `TASK_STATE_AUTH_REQUIRED` — "Indicates that authentication is required to proceed. This is an interrupted state." There is no approval message type, no action object, and no binding of an approval to a specific action; "approval" is whatever the remote agent asks for in an input-required turn.

**Audit.** Guidance only: "audit significant events, such as task creation, critical state changes, and agent actions, especially when involving sensitive data or high-impact operations"; logs "should capture" "taskId, sessionId, correlation IDs, and trace context"; participate in OpenTelemetry distributed tracing. No receipt format is defined. The repository README still lists as future work: "Formalize inclusion of authorization schemes and optional credentials directly within the `AgentCard`".

## B8. Google Cloud: Gemini Enterprise Agent Platform governance (Agent Identity, Agent Gateway, Agent Registry, IAM access policies, semantic governance policies, Model Armor, Agent Observability)

**Naming.** On 2026-04-22 Google renamed Vertex AI to "Agent Platform" within the Gemini Enterprise Agent Platform; the release-note table maps "Vertex AI Agent Engine → Agent Runtime", "Vertex AI Studio → Agent Studio", "Vertex AI → Agent Platform". All of the following are Google Cloud managed services — **none runs locally**, and semantic governance explicitly "does not support VPC-SC". Documentation pages are CC-BY 4.0; the services are proprietary.

**Agent Identity** (https://docs.cloud.google.com/agent-builder/agent-engine/agent-identity). GA 2026-04-22 ("Release Agent Identity for General Availability. Agent Identity helps let your agent securely authenticate to MCP servers, cloud resources, endpoints, and other agents, either acting as itself or acting on behalf of the end user."); the new Agent Identity API (`agentidentity.googleapis.com`) entered Preview 2026-06-18. It provides "a strongly attested, cryptographic identity for each agent that is based on the SPIFFE standard" with X.509 certificates. Division of labour, verbatim: "Agent Identity provisions cryptographic identities and manages credentials, Agent Registry catalogs the tools and destinations in your environment, and Agent Gateway enforces access policies." Audit: it "integrates with audit logging to ensure accountability and provide clear audit logs both when the agent is acting as itself and when it is acting on behalf of an end user." With the gateway, end-user credentials "are encrypted by the auth manager and decrypted at the gateway, ensuring that the agent can never access the raw credential."

**Agent Gateway** (https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/gateways/agent-gateway-overview). Private Preview 2026-04-22; **GA 2026-06-18**. Ingress ("secure communications between clients (such as Cursor, Claude Code, Gemini CLI) and agents") and egress ("secure communications between agents running on Google Cloud and servers, agents, tools, or APIs running anywhere"). Enforces IAM ("restricts agents to specific tools or methods based on the agent's identity (SPIFFE ID)"), optional Model Armor, semantic governance ("context-aware controls on your agent's execution such as protections against toxic combinations of tools"), and Service Extensions "for custom authorization engines". Telemetry: it "generates observability telemetry for all agent interactions at the network layer and exports it to Agent Observability" via Cloud Logging and Cloud Trace. Runtimes: Agent Runtime (ingress + egress) and Gemini Enterprise (egress only). Later additions: VPC-SC perimeter enforcement (2026-09-09), up to two registries per gateway (2026-09-09). This is the enforcement seam: a network proxy between agent and model and between agent and tools.

**IAM Unified Access Policies** (configure-iam-policies). **GA 2026-08-31**: "Multiple allow and deny rules within a single Access policy to establish fine-grained behavioral guardrails."; "Common Expression Language (CEL) conditions in rules to enforce access criteria based on tool names, read-only constraints, HTTP methods, and URL path attributes."; "Dry-run and enforcement modes to validate and audit policy evaluation before blocking agent traffic."; "End-to-end agent identity authentication and authorization using mutual TLS (mTLS) and Context-Aware Access (CAA) with Demonstrating Proof of Possession (DPoP)." Policies bind to agent principals such as `principal://agents.global.org-123456789012.system.id.goog/resources/aiplatform/projects/...`; example rule "Allow AE Agent Read-Only Egress to GitHub MCP server". Enforced by "Identity-Aware Proxy (IAP)" at the gateway. The MCP-server authentication section is marked Preview. **Action identity:** tool name + request attributes (read-only flag, HTTP method, URL path) evaluated per request; deterministic. **Approval:** none — allow/deny only.

**Semantic governance policies** (semantic-governance-overview, configure-semantic-governance). **Preview since 2026-06-29** (Pre-GA terms): "evaluates an AI agent's proposed tool calls against user intent and organizational business rules at runtime"; "Layered Intent Gating: Intercepts agent tool calls at runtime to verify alignment with trusted user intent and prevent unauthorized actions, rogue tool use, and data exfiltration." Rules are Natural Language Constraints — "Provide your business rules in plain English (up to 5,000 characters)" — "evaluated semantically by a Large Language Model (LLM) at runtime", scoped agent-wide or per tool/MCP server. Inputs: the user prompt, constraints, tools manifest with tool-specific constraints, chat history, and the model's suggested tool invocations. Enforcement point: "the Agent Gateway, which acts as a runtime enforcement point, intercepting communication between the agent and its model, and also between the agent and any tools." Output: "Overall decision, either `ALLOW` or `DENY`." with, on DENY, "a structured denial response containing a human-readable rationale". Caveat, verbatim: "Verdicts may not be accurate". **Record:** Cloud Logging under `logName="projects/PROJECT_ID/logs/semantic-governance-policy"` with verdict, per-tool evaluations, rationales and token usage; Dry Run Mode to observe verdicts "before enforcing them on active traffic"; Cloud Monitoring metrics in Preview since 2026-08-15 (verdict distribution ALLOW vs DENY, latencies, token consumption). Also "Agent Skills Lifecycle Governance" over dynamically loaded skills. **No human-in-the-loop outcome** appears in any policy page — the engine allows or denies. (A Google blog-level search snippet claims policies "can mandate human-in-the-loop (HITL) approvals for sensitive actions"; the documentation read does not support that; recorded as unverified below.)

**Model Armor** (model-armor-overview). GA (image screening Preview). Screens "incoming prompts" and "generated responses" for prompt injection / jailbreak, responsible-AI categories, sensitive data (via Sensitive Data Protection), and malicious URLs; integrations listed include Agent Platform, Apigee, Gemini Enterprise, Agent Gateway ("Model Armor for Agent Gateway in General Availability", 2026-06-24), Google and Google Cloud MCP servers, and LangChain. "Model Armor sends detailed description of triggered and untriggered filters in the response," with Cloud Logging. It does not evaluate tool calls as actions — content only.

**Agent Registry** GA 2026-06-18 ("a centralized catalog for discovering and registering agents and Model Context Protocol (MCP) servers", with A2A v1.0 support). **Agent Observability** GA 2026-06-18 ("Default-On Tracing: OpenTelemetry tracing is now enabled by default for newly deployed Agent Development Kit (ADK) agents on Agent Engine"); since 2026-05-27 prompt/response logging can include `user.id` "to allow better tracking of anomalous tool interactions." The "Govern your agents" page also cites "maintaining a rigorous audit trail of data access and request-response logs." All records are Cloud Logging / Cloud Trace entries — no signing or hashing is described.

---

# Closing tables

Cells are deliberately short; "none" means the documentation defines no such thing, "n/a" means the criterion does not apply to that surface.

## OpenAI

| Item | Action identity | Approval binding | Receipt | Enforcement seam | Local operation |
|---|---|---|---|---|---|
| A1 Agents SDK guardrails | `tool_name` + `tool_call_id` + raw `tool_arguments` string | n/a (allow / reject_content / raise; no transform) | `guardrail_span` in trace; unsigned | In-process, before/after each `FunctionTool` | Yes; tracing defaults to OpenAI unless replaced |
| A1 Agents SDK `needs_approval` | Call id; internal SHA-256 fingerprint over name+args (Python) / stable JSON string (JS) — not surfaced | Per-call bound to call id; `always_approve` widens to tool name for the run | None beyond run state; state is plain JSON, schema-versioned, unsigned | In-process interruption before tool execution | Yes |
| A1 Tracing / hooks | Span per tool call with inputs/outputs | n/a; hooks are observe-only | Plain spans; no approval-decision span found | Exporter/processor | Local only if processors replaced; unavailable under ZDR |
| A2 AgentKit / Agent Builder | Node output (e.g. drafted email); not a tool-call object | Human approval node gates the next node; binding to a call not documented | Workflow trace only | Hosted workflow; shuts down 2026-11-30 | No (hosted) |
| A2 Guardrails library / Connector Registry | Content, not actions / connector enablement | n/a / workspace-level RBAC | None / admin settings | Client wrapper / admin console | Mostly no (paid OpenAI APIs) / no |
| A3 Codex CLI + cloud | Concrete command or tool call in the prompt | Per-invocation interactive approval or config rules | `codex.tool_decision` + `codex.tool_result` OTLP logs, opt-in, unsigned | OS sandbox (Seatbelt / bwrap+seccomp / Windows) + approval gate; network off by default | CLI, sandbox, OTel local; inference via OpenAI |
| A4 Policy publications | Practices paper names approval, ledger, attribution as practices; FGF silent on agents | Prescribed as principle only | "ledger of actions" as principle; no format | Guidance only | n/a |
| A5 Hosted MCP `require_approval` | `mcp_approval_request.id` + name + arguments string + server_label | Response references request id only; bound server-side | Request/response items in the Response object; unsigned | OpenAI-side before server tool call | No (hosted); local MCP servers via SDK use A1 path |

Ten-line summary, OpenAI: (1) The only real action-level primitive is the Agents SDK's `needs_approval` interruption; everything else is content guardrails, sandboxing, or guidance. (2) Action identity at the approval point is tool name + provider call id + argument string; Python internally fingerprints name+arguments with SHA-256, JS with a canonical JSON string, but neither exposes or records that fingerprint. (3) Per-call approvals are bound to the call id and cannot be replayed for other arguments; `always_approve` deliberately unbinds arguments for the rest of the run. (4) Run state is `json.dumps` with a schema version — no signature, no HMAC, no encryption — so the integrity of a pending approval is the application's problem. (5) No decision record exists in the SDK; tracing captures tool inputs/outputs as plain spans and, by default, ships them to OpenAI. (6) Hooks observe; they cannot veto or transform; tool guardrails allow/reject/raise but never transform arguments. (7) Codex is the only OpenAI surface that emits a decision record (`codex.tool_decision`, opt-in OTLP), and it is unsigned and, as documented, without call id or argument text. (8) Hosted MCP approvals bind by opaque request id with arguments shown but not attested. (9) Agent Builder, the one product with a human-approval node, is deprecated (shutdown 2026-11-30). (10) The 2023 Practices paper articulates approval, action ledgers and attribution as goals; the 2026 Frontier Governance Framework does not mention agents at all; two closed 2026 repository issues document the runtime-authorization gap without a maintainer reply.

## Google

| Item | Action identity | Approval binding | Receipt | Enforcement seam | Local operation |
|---|---|---|---|---|---|
| B6 ADK callbacks / plugins | `tool` object + `args` dict + `tool_context` | n/a (allow / deny-with-substitute / mutate args) | Only what a plugin writes (e.g. Logging, BigQuery plugin); unsigned | In-process before/after tool, model, agent; plugins global | Yes (LiteLLM, Ollama, vLLM) |
| B6 ADK tool confirmation | `adk_request_confirmation` call embedding `originalFunctionCall` (id, name, args) | Bound to function call id (+ invocation id under Resume); original call re-executed as stored | Session events via session service; unsigned; experimental; two session services unsupported | In-process pause before tool execution | Yes |
| B7 A2A | Task / skill; no action object | None — only `INPUT_REQUIRED` / `AUTH_REQUIRED` interrupted states | None defined; audit "significant events" is guidance | Transport auth + skill-level scopes at the server | Yes (protocol) |
| B8 Agent Identity | SPIFFE ID / X.509 per agent | n/a (identity, not approval) | Cloud Audit Logs with agent-as-self vs on-behalf-of | Credentials never reach the agent when gateway used | No |
| B8 IAM access policies (GA 2026-08-31) | Tool name, read-only flag, HTTP method, URL path via CEL | None — allow/deny | Dry-run + enforcement logs (Cloud Logging) | Agent Gateway via IAP, mTLS + DPoP | No |
| B8 Semantic governance (Preview) | Proposed tool call + prompt + history, judged by an LLM | None — ALLOW/DENY with rationale; "Verdicts may not be accurate" | Cloud Logging `semantic-governance-policy` entries with verdict + rationale; unsigned | Agent Gateway intercepting agent-model and agent-tool traffic | No; no VPC-SC |
| B8 Model Armor | Prompt / response content | n/a | Filter results in response + Cloud Logging | Gateway / API / Apigee / MCP servers | No |

Ten-line summary, Google: (1) ADK gives the richest in-process seam of the surveyed frameworks: `before_tool_callback` sees the tool, the args and the context and can allow, substitute a result, or mutate the args; plugins apply the same hooks globally and run first. (2) ADK tool confirmation binds a human decision to a specific pending call by function-call id, with the original call (name and args) embedded verbatim in the confirmation request and re-executed as stored. (3) It is explicitly experimental, unsupported with the database and Vertex session services, and produces only ordinary session events — no hash, no signature. (4) Neither ADK nor the cloud stack canonicalises or hashes an action; identities are opaque ids (ADK) or SPIFFE agent identities plus request attributes (cloud). (5) A2A 1.0 (Apache 2.0, AAIF/Linux Foundation, TSC of eight vendors) governs *who* may call a skill, adds signed Agent Cards, and defines two interrupted states — but has no approval message, no action object, and no audit format. (6) Google Cloud's enforcement seam is a network proxy — Agent Gateway (GA 2026-06-18) — that intercepts agent-to-model and agent-to-tool traffic under a per-agent cryptographic identity (Agent Identity, GA 2026-04-22). (7) Deterministic tool-level allow/deny arrived as IAM Unified Access Policies (GA 2026-08-31) with CEL over tool names, read-only flags, HTTP methods and URL paths, plus dry-run. (8) Intent-level control is the LLM-judged semantic governance policy engine (Preview since 2026-06-29), whose own docs warn verdicts "may not be accurate"; it allows or denies and has no human-approval outcome. (9) Receipts across the cloud stack are Cloud Logging / Cloud Trace / Cloud Audit Logs entries — structured, but not hashed or signed. (10) None of the cloud controls runs locally (semantic governance does not even support VPC-SC); only ADK and the A2A protocol are usable offline.

---

# Not found / not verified

1. `https://openai.com/index/introducing-agentkit/`, `/running-codex-safely/`, `/openai-frontier-governance-framework/`, `/practices-for-governing-agentic-ai-systems/` and the help-centre admin-controls article all returned HTTP 403 to both fetchers; statements attributed to them are from search-result snippets (dates: Running Codex safely 2026-05-08; FGF 2026-05-28) or from their companion PDFs, which were read.
2. The Practices paper's publication date (December 2023) is not printed in the PDF; it rests on the blocked announcement page and third-party indexes.
3. Whether current OpenAI developer documentation still links to the Practices paper: not established (it is still hosted and search-adjacent; no 2026 page fetched cites it).
4. Agents SDK: no span, event, or field that records the approval decision (approver, time, call id) was found in the tracing docs; the trace records the tool execution only.
5. Agents SDK guardrails page sentence "If a function tool requires approval, input tool guardrails normally run after approval and immediately before execution" was seen only in a search snippet attributed to that page, not in the fetched excerpt.
6. JS SDK version number was not captured; Python's 0.22.0 is the latest documented on the release page (no date given).
7. Codex `codex.tool_decision`: whether it carries the command text/arguments or a call id linking it to `codex.tool_result` is not documented on the page read. Whether Codex can run against a local/non-OpenAI model was not checked.
8. Hosted MCP: no statement that the executed call is re-validated against the arguments displayed in `mcp_approval_request`; the binding is by request id on OpenAI's side.
9. Agent Builder human-approval node: no documentation that it binds to a specific tool call or records the decision anywhere but the workflow trace.
10. Connector Registry: no official 2026 status update found beyond the Oct 2025 "beta rollout" statement; the changelog and deprecations pages have no entry for it, ChatKit or Guardrails.
11. GitHub issues #2775 and #2868: closed; any maintainer response was not visible in the fetched excerpts, so "no response" is not asserted.
12. Google blog snippet claiming semantic governance policies "can mandate human-in-the-loop (HITL) approvals for sensitive actions": contradicted by every policy documentation page read (ALLOW/DENY only); unresolved.
13. Agent Gateway overview: the search snippet phrase that the gateway "intercepts" the model's suggested tool call and "sends the tool suggestion, policies, and chat history, to the policy engine" did not appear in the fetched overview excerpt; the equivalent statement was verified on the semantic-governance overview page instead.
14. ADK tool confirmation: mechanism of state persistence across the pause with the two unsupported session services (Database, VertexAi) is stated as a limitation without explanation; the Resume page does not itself state the invocation-id matching rule (that sentence is from the confirmation page via search snippet).
15. A2A: the specification page gives no publication date or licence inline (both were taken from the project home page, the 2026-03-12 announcement and the repository README); no approval primitive, audit format or signed-record scheme exists to report.
16. Google release notes were read in full for the platform (2026-03-31 to 2026-09-15); Agent Identity's original GA and Agent Gateway's private preview both appear in the 2026-04-22 "Initial release" entry, so earlier Vertex-era preview dates were not traced.
17. No live SDK or API was exercised; every "bound" / "unsigned" / "plain" verdict above is read from documentation and published source, not observed at runtime.
