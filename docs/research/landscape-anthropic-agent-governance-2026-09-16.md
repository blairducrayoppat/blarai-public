# Anthropic's runtime action-governance surfaces: a documentation-level survey (2026-09-16)

## Scope

This is a documentation-level survey, current as of 2026-09-16, of what Anthropic offers that governs what an AI agent is allowed to DO at runtime (tool calls and side effects), binds a human approval to a specific action, records a verifiable receipt or audit of decisions, or normalises actions across runtimes. It is written as one input to a comparison against three external designs: CAVA (a hashed canonical action object that approvals bind to), PCAA (a five-checkpoint route-review-prove certificate: guard, create action, record assumption, wait for approval, update outcome), and Microsoft's Agent Framework / Agent Governance Toolkit / Agent Control Specification (eight interception points, allow/deny/transform verdicts, content-bound approval identity). Only official sources were used (code.claude.com, platform.claude.com, anthropic.com, modelcontextprotocol.io and its blog, agentskills.io, and the anthropics / modelcontextprotocol / agentskills GitHub organisations). No local repository files were read. Nothing here was run or measured; every statement is what the documentation says, and the closing "Not found / not verified" list names what could not be confirmed.

Two instrument notes. (1) Pages marked "raw" below were fetched as Markdown and grepped, so quotations from them are verbatim. Pages marked "extracted" were read through a fetch tool that summarises with a small model; quotations from those are as that tool returned them and were not independently re-read. (2) The anthropic.com news posts at `/news/building-safe-and-trustworthy-agents` and `/news/agentic-ai-foundation` return 404; the live URLs are given below.

## Sources read

Raw (Markdown fetched and grepped):

- https://code.claude.com/docs/en/hooks
- https://code.claude.com/docs/en/permissions
- https://code.claude.com/docs/en/permission-modes
- https://code.claude.com/docs/en/settings and https://code.claude.com/docs/en/settings-reference (grepped for named keys only)
- https://code.claude.com/docs/en/sandboxing
- https://code.claude.com/docs/en/mcp (grepped)
- https://code.claude.com/docs/en/agent-sdk/permissions (platform.claude.com/docs/en/agent-sdk/permissions 307-redirects here)
- https://code.claude.com/docs/en/agent-sdk/hooks (platform.claude.com/docs/en/agent-sdk/hooks 307-redirects here)
- https://code.claude.com/docs/en/agent-sdk/user-input
- https://code.claude.com/docs/en/agent-sdk/typescript and https://code.claude.com/docs/en/agent-sdk/python (type sections)
- https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/schema/2026-07-28/schema.ts
- LICENSE files: modelcontextprotocol/modelcontextprotocol, agentskills/agentskills, anthropics/claude-agent-sdk-python, anthropics/claude-code

Full page returned by the fetch tool (near-verbatim):

- https://code.claude.com/docs/en/agent-sdk/overview
- https://code.claude.com/docs/en/security
- https://code.claude.com/docs/en/data-usage
- https://code.claude.com/docs/en/legal-and-compliance
- https://code.claude.com/docs/en/agent-teams
- https://platform.claude.com/docs/en/managed-agents/overview
- https://platform.claude.com/docs/en/managed-agents/tools
- https://platform.claude.com/docs/en/managed-agents/permission-policies
- https://platform.claude.com/docs/en/managed-agents/sessions
- https://platform.claude.com/docs/en/managed-agents/reference
- https://platform.claude.com/docs/en/managed-agents/webhooks
- https://platform.claude.com/docs/en/manage-claude/compliance-api
- https://platform.claude.com/docs/en/manage-claude/compliance-sessions
- https://platform.claude.com/docs/en/manage-claude/inference-hooks
- https://platform.claude.com/docs/en/manage-claude/workload-identity-federation
- https://platform.claude.com/docs/en/agents-and-tools/tool-use/how-tool-use-works
- https://modelcontextprotocol.io/specification/latest/server/tools (resolves to 2026-07-28)
- https://modelcontextprotocol.io/specification/latest/client/elicitation
- https://modelcontextprotocol.io/specification/latest/basic/authorization
- https://modelcontextprotocol.io/specification/latest/basic/security_best_practices
- https://modelcontextprotocol.io/specification/2026-07-28/changelog
- https://modelcontextprotocol.io/community/interest-groups/tool-annotations
- https://agentskills.io/specification and https://agentskills.io/home

Extracted (summarised by the fetch tool):

- https://code.claude.com/docs/en/monitoring-usage
- https://platform.claude.com/docs/en/managed-agents/events-and-streaming
- https://platform.claude.com/docs/en/managed-agents/self-hosted-sandboxes
- https://www.anthropic.com/engineering/managed-agents
- https://tasks.extensions.modelcontextprotocol.io/
- https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/
- https://www.anthropic.com/news/donating-the-model-context-protocol-and-establishing-of-the-agentic-ai-foundation
- https://github.com/anthropics/claude-agent-sdk-python, https://github.com/anthropics/claude-agent-sdk-typescript, https://github.com/anthropics/skills
- https://www.anthropic.com/news/our-framework-for-developing-safe-and-trustworthy-agents
- https://www.anthropic.com/research/trustworthy-agents
- https://www.anthropic.com/engineering/how-we-contain-claude
- https://www.anthropic.com/research/measuring-agent-autonomy
- https://www.anthropic.com/news/usage-policy-update and https://www.anthropic.com/legal/aup
- https://www.anthropic.com/responsible-scaling-policy

## 1. Claude Agent SDK (Python and TypeScript)

What it is. A Python and TypeScript library that "gives you the same tools, agent loop, and context management that power Claude Code". The Python README states "The Claude Code CLI is automatically bundled with the package"; the SDK drives the Claude Code process, so its permission system IS Claude Code's permission system, exposed programmatically. Docs: https://code.claude.com/docs/en/agent-sdk/overview.

Status. Generally available library (no beta label on the docs). Version numbers were not captured.

Licence. Overview page: "Use of the Claude Agent SDK is governed by Anthropic's Commercial Terms of Service ... except to the extent a specific component or dependency is covered by a different license as indicated in that component's LICENSE file." The Python repository LICENSE file is MIT (Copyright 2025 Anthropic, PBC). The TypeScript repository's LICENSE file was not retrievable at its raw URL (404); its GitHub page reports it is governed by the Commercial Terms.

Local vs API. The SDK and its permission evaluation run on your machine, but every turn needs a model endpoint: the Anthropic API by default, or (per the Claude Code data-usage page) Amazon Bedrock, Google Cloud's Agent Platform, Microsoft Foundry, or Claude Platform on AWS. There is no offline mode. Auto mode adds a second model call per classified action.

Evaluation order (raw, https://code.claude.com/docs/en/agent-sdk/permissions, "How permissions are evaluated"), six steps in this order: Hooks; Deny rules; Ask rules; Permission mode; Allow rules; canUseTool callback. Load-bearing sentences: "A hook that returns `allow` does not skip the deny and ask rules below; those are evaluated regardless of the hook result." "If a deny rule matches, the tool is blocked, even in `bypassPermissions` mode." "Auto-approved tools never reach `canUseTool`." "For checks that must run on every tool call, use a `PreToolUse` hook: hooks run before every other step, and a hook deny applies even in `bypassPermissions` mode."

Permission modes (raw): `default`, `dontAsk` ("Any call that would otherwise prompt is denied ... `canUseTool` is never called"), `acceptEdits`, `bypassPermissions`, `plan`, `auto` ("A model classifier approves or denies permission prompts"). `allowed_tools` / `disallowed_tools` add entries to the allow and deny rule lists; a bare-name deny "removes the tool from Claude's context"; "`allowed_tools` does not constrain `bypassPermissions`."

canUseTool callback (raw, TypeScript reference):

```
type CanUseTool = (
  toolName: string,
  input: Record<string, unknown>,
  options: {
    signal: AbortSignal;
    suggestions?: PermissionUpdate[];
    blockedPath?: string;
    decisionReason?: string;
    toolUseID: string;
    agentID?: string;
    requestId: string;
  }
) => Promise<PermissionResult | null>;

type PermissionResult =
  | { behavior: "allow"; updatedInput?: Record<string, unknown>; updatedPermissions?: PermissionUpdate[]; toolUseID?: string }
  | { behavior: "deny"; message: string; interrupt?: boolean; toolUseID?: string };
```

Python mirrors this with `PermissionResultAllow(updated_input, updated_permissions)`, `PermissionResultDeny(message, interrupt)`, and a `ToolPermissionContext` whose `tool_use_id` is "Always populated when delivered to `can_use_tool`" and which also carries `title`, `display_name`, `description` for building a prompt UI. `requestId` is "The `control_request` envelope's `request_id`. A `control_response` your application sends outside the SDK, such as a signed HTTP POST, must echo this value". "permission prompts don't time out."

Action identity at the decision point. Tool name plus the full input object plus a per-call `toolUseID` (`toolu_...`) and a per-request `requestId`. No hash, no canonical form, no signature. Rule matching (see section 2) is textual and, for parameters, "compared against the literal input Claude sends, before any normalization."

Approval binding. The callback is invoked once per call and the decision applies to that `toolUseID`; if the callback returns `updatedInput`, "the tool runs with" that input, so the executed action is what the approver returned, not what the model proposed. Persistence is by RULE, not by bound approval: `updatedPermissions` carries `PermissionUpdate` entries (`addRules`, `replaceRules`, `removeRules`, `setMode`, `addDirectories`, `removeDirectories`) with a `destination` of `userSettings`, `projectSettings`, `localSettings`, or `session`; a `localSettings` suggestion "writes the rule to `.claude/settings.local.json` and persists across sessions." A persisted rule is a text pattern (for example `Bash(npm test *)`) that will match future calls with different arguments.

Hooks (raw, https://code.claude.com/docs/en/agent-sdk/hooks and the TS reference). In-process callbacks `(input, toolUseID, { signal }) => Promise<HookJSONOutput>`; settings-file shell hooks also run. `PreToolUse` input carries `tool_name`, `tool_input`, `tool_use_id`. Output `hookSpecificOutput.permissionDecision` is `"allow" | "deny" | "ask" | "defer"`, plus `permissionDecisionReason`, `updatedInput`, `additionalContext`. "When multiple hooks or permission rules apply, `deny` takes priority over `defer`, which takes priority over `ask`, which takes priority over `allow`." `PostToolUse` receives `tool_response` and can return `additionalContext`, `classifierContext`, `updatedToolOutput`. Availability differs by language: the SDK table lists `PermissionRequest`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `UserPromptSubmit`, `Stop`, `SubagentStart/Stop`, `PreCompact`, `Notification` in both; `PermissionDenied`, `Elicitation`, `ElicitationResult`, `SessionStart/End`, `ConfigChange`, `InstructionsLoaded`, `PostToolBatch` and others are TypeScript-only. The docs' stated use cases include "Log and audit every tool call for compliance, debugging, or analytics" and "Require human approval for sensitive actions", which makes the hook the intended audit and approval seam, with the record format left to the integrator.

Deferred approval (raw, Claude Code hooks reference, "Defer a tool call for later"). `"defer"` "lets that calling process pause Claude at a tool call, collect input through its own interface, and resume where it left off." "The tool doesn't execute. The process exits with `stop_reason: "tool_deferred"` and the pending tool call preserved in the transcript." "The `deferred_tool_use` field carries the tool's `id`, `name`, and `input`. The `input` is the parameters Claude generated for the tool call, captured before execution". Constraints: non-interactive `-p` mode only; "only works when Claude makes a single tool call in the turn"; "There is no timeout or retry limit. The session remains on disk until you resume it, subject to the `cleanupPeriodDays` retention sweep". This is the closest Anthropic artefact to a persisted pending-approval object; it is a plain JSON structure in the local session file, unsigned.

Decision record. Nothing signed or hashed. Records available: the local transcript JSONL (`transcript_path`, "written asynchronously and may lag"), the OpenTelemetry `claude_code.tool_decision` event (section 2), and whatever the integrator's hooks write.

## 2. Claude Code hooks and permissions

What it is. The interactive CLI/desktop/IDE agent whose permission engine the SDK reuses. Docs: https://code.claude.com/docs/en/hooks, https://code.claude.com/docs/en/permissions, https://code.claude.com/docs/en/permission-modes, https://code.claude.com/docs/en/sandboxing, https://code.claude.com/docs/en/monitoring-usage.

Status and licence. Generally available; proprietary. Repository LICENSE.md: "© Anthropic PBC. All rights reserved. Use is subject to Anthropic's Commercial Terms of Service." Legal page: "The Claude Code binary must not be modified."

Local vs API. Runs locally; "Permission rules are enforced by Claude Code, not by the model." Model calls go to the Anthropic API or Bedrock / Google Cloud Agent Platform / Microsoft Foundry / Claude Platform on AWS. One exception to locality: "Before fetching a URL, the WebFetch tool sends the requested hostname to `api.anthropic.com` to check it against a safety blocklist ... regardless of which model provider you use" (disable with `skipWebFetchPreflight`). Auto mode's classifier is a separate model request ("Each check sends a portion of the transcript plus the pending action").

Hook events (raw). 33 events: `SessionStart`, `Setup`, `UserPromptSubmit`, `UserPromptExpansion`, `PreToolUse`, `PermissionRequest`, `PermissionDenied`, `PostToolUse`, `PostToolUseFailure`, `PostToolBatch`, `Notification`, `MessageDisplay`, `SubagentStart`, `SubagentStop`, `TaskCreated`, `TaskCompleted`, `Stop`, `StopFailure`, `TeammateIdle`, `InstructionsLoaded`, `ConfigChange`, `CwdChanged`, `DirectoryAdded`, `FileChanged`, `WorktreeCreate`, `WorktreeRemove`, `PreCompact`, `PostCompact`, `PreModelSwitch`, `PostModelSwitch`, `Elicitation`, `ElicitationResult`, `SessionEnd`.

PreToolUse (raw). Input: common fields (`session_id`, `transcript_path`, `cwd`, `permission_mode`, `hook_event_name`) plus `tool_name`, `tool_input`, `tool_use_id`. File-tool paths "always absolute: Claude Code expands `~` and relative paths before hooks run, so a hook that matches on paths can't be bypassed via `~` or a relative spelling of the same path". Output: `permissionDecision` "`"allow"` skips the permission prompt ... `"deny"` prevents the tool call. `"ask"` prompts the user to confirm. `"defer"` exits gracefully so the tool can be resumed later. Deny and ask rules are still evaluated regardless of what the hook returns"; `updatedInput` "Replaces the entire input object ... Claude Code evaluates permission rules ... against the input your hook returns, not the input Claude sent"; "precedence is `deny` > `defer` > `ask` > `allow`". Exit code 2 "blocks whether or not you print JSON: even a JSON `permissionDecision` of `"allow"` can't override it."

PermissionRequest (raw). "Runs when Claude Code is about to ask you for permission to use a tool. In sessions that can't show a prompt ... if no hook returns a decision, it denies the tool call." Input: "`tool_name` and `tool_input` fields like PreToolUse hooks, but without `tool_use_id`", plus `permission_suggestions` (the rule/mode updates the dialog would offer). Output `decision` object: `behavior` `"allow"`/`"deny"`; `updatedInput`; `updatedPermissions`; `message`; `interrupt`. "Only the `decision` object can grant or deny the request." Note the asymmetry: the pre-execution gate (`PreToolUse`) receives the per-call id; the prompt-substitute (`PermissionRequest`) does not.

PostToolUse (raw). Input adds `tool_response`, `tool_use_id`, `duration_ms`. Output: `decision: "block"` with `reason`, `additionalContext`, `classifierContext`, `updatedToolOutput`. "`updatedToolOutput` only changes what Claude sees. The tool has already run ... Telemetry such as OpenTelemetry tool spans and analytics events also captures the original output before the hook runs."

Elicitation hooks (raw). `Elicitation` receives `mcp_server_name`, `message`, `mode` (`form`/`url`), `url`, `elicitation_id`, `requested_schema`; a hook may answer with `action` `accept`/`decline`/`cancel` and `content`. `ElicitationResult` can override the user's answer. Exit 2 denies.

Permission rules (raw). "Rules are evaluated in order: deny, then ask, then allow. The first match in that order determines the outcome, and rule specificity doesn't change the order." Rule identity is the tool name plus a specifier over the tool's primary content: `Bash(prefix *)`, `Edit(path)`, `Read(path)`, `WebFetch(domain:host)`, `mcp__server__tool`, `Agent(name)`, and `Tool(param:value)` for scalar parameters. "Bash rules match the whole command text"; compound commands are split on `&&`, `||`, `;`, `|`, `|&`, `&`, newlines and "A rule must match each subcommand independently"; a fixed wrapper list (`timeout`, `nice`, `nohup`, ...) is stripped. Limits, stated by Anthropic: "A Bash rule matches the command text Claude writes ... It doesn't match the same program invoked in a different form, so a deny or ask rule covers the invocation Claude usually produces and isn't a security boundary around the program" (`Bash(rm *)` stops `rm -rf build/`, not `/bin/rm -rf build/`). Parameter rules: "The value is compared against the literal input Claude sends, before any normalization." There is no canonicalisation and no hash of the action; the text is the identity.

Persistence of approvals (raw). "When you choose 'Yes, and don't ask again' and the approval saves permanently, such as for a Bash command or a WebFetch domain, Claude Code saves the rule to `.claude/settings.local.json` at the root of the git repository". Compound approvals "save a separate rule for each subcommand". "A file-modification approval isn't saved to the file ... it lasts until the session ends." "Claude Code offers those options only when the prompt can show you everything they would allow, so a rule you save from a prompt covers only what its option named."

Actions no mode auto-approves (raw). Explicit ask rules; connector tools an organisation set to `ask`; `AskUserQuestion` and MCP tools marked `_meta["anthropic/requiresUserInteraction"]` (an MCP server can force a prompt, Claude Code v2.1.199+); `rm`/`rmdir` on a critical path "which no allow rule or `PreToolUse` hook `"allow"` approves"; cross-session messaging safeguards; reads outside working directories when `blockReadsOutsideWorkingDirectories` is on.

Auto mode classifier (raw). Fixed order: rules first (with exceptions that route to the classifier), then "Read-only actions and file edits in your working directory are auto-approved", then "Everything else goes to the classifier"; "If the classifier blocks, Claude receives the reason ... such as `[Data Exfiltration]`". On entering auto mode "broad allow rules that grant arbitrary code execution are dropped" (`Bash(*)`, wildcarded interpreters, `Agent` allow rules). "the classifier sees user messages, tool calls other than read-only lookups ..., and your CLAUDE.md content. Tool results are stripped from those requests". Runs on Claude Sonnet 5 by default; organisations disable it with `permissions.disableAutoMode: "disable"` in managed settings. Auto mode is the built-in starting mode on Pro, Max and Team plans.

Sandbox (raw). "the operating system enforces that boundary for every Bash, PowerShell, or Monitor command and its child processes" via macOS Seatbelt or Linux/WSL2 bubblewrap plus an optional seccomp filter shipped as `@anthropic-ai/sandbox-runtime`; native Windows unsupported. "Network access is controlled through a proxy server running outside the sandbox"; "Claude Code pre-allows no domains by default"; `strictAllowlist` and `allowManagedDomainsOnly` deny instead of prompt; "The built-in proxy enforces the allowlist based on the requested hostname and, by default, does not terminate or inspect TLS traffic." Relationship to permissions: "sandbox restrictions still apply even if a prompt injection bypasses Claude's decision-making"; with `autoAllowBashIfSandboxed` (default true) "sandboxed Bash commands run without prompting ... the sandbox boundary substitutes for that whole-tool prompt", while content-scoped ask rules and deny rules still apply.

Enterprise controls (raw, settings reference). `allowManagedPermissionRulesOnly` ("Make managed settings the only settings source of permission rules"), `allowManagedHooksOnly` ("Run only the hooks your organization deploys"), `permissions.disableBypassPermissionsMode`, `disableAllHooks`, `permissions.defaultMode`, `permissions.disableAutoMode`, `allowedMcpServers` / `deniedMcpServers`, `cleanupPeriodDays`. Managed settings are delivered by `managed-settings.json`, MDM, or server-managed settings from the claude.ai console.

Decision records (extracted, monitoring-usage; raw, data-usage; full, compliance-sessions).

- OpenTelemetry event `claude_code.tool_decision` with attributes `tool_name`, `tool_use_id` ("Matches the `tool_use_id` passed to hooks"), `decision` (`"accept"` or `"reject"`), and `decision_source` ("One of `"config"`, `"hook"`, `"user_permanent"`, `"user_temporary"`, `"user_abort"`, or `"user_reject"`"). Tool inputs are included only with `OTEL_LOG_TOOL_DETAILS=1`. Exported over OTLP to a collector you run. No signing or tamper-evidence is described.
- Local transcript: "Claude Code clients store session transcripts locally in plaintext under `~/.claude/projects/` for 30 days by default".
- Compliance API (Enterprise only): "For local sessions, Anthropic records each conversation server-side as its requests reach the Claude API; nothing is installed on the device". Transcripts contain `tool_use` blocks (`id`, `name`, `input` as a JSON-encoded string) and `tool_result` blocks (`tool_use_id`, `name`, `is_error`, content). "Local session transcripts show what Claude was asked to do and what it returned, not what happened on the device." Retention "6 years by default". Excludes sessions "authenticated with a Claude Console API key, or run through a third-party cloud platform such as Amazon Bedrock, Google Cloud, or Microsoft Foundry". Permission decisions are not part of the transcript; `provenance` marks unverified `client_asserted` history. No hashes or signatures.
- Cloud sessions (security page): "All operations in cloud sessions are logged for compliance and audit purposes."

Action identity. Tool name + literal input text; per-call `tool_use_id` available to PreToolUse/PostToolUse and OTel, absent from PermissionRequest. Approval binding: per call at the prompt; persisted only as text rules. Enforcement seam: the Claude Code process (PreToolUse hook, rules, mode, callback) plus the OS sandbox for shell commands. Receipt: OTel event and transcripts, unsigned.

## 3. Claude Managed Agents

What it is. "Pre-built, configurable agent harness that runs in managed infrastructure": agents, environments (Anthropic cloud sandbox or self-hosted), sessions, events. Docs: https://platform.claude.com/docs/en/managed-agents/overview, .../permission-policies, .../events-and-streaming, .../reference, .../self-hosted-sandboxes, .../webhooks. Engineering post https://www.anthropic.com/engineering/managed-agents (2026-04-08) describes the session as "the append-only log of everything that happened" and the tool interface as `execute(name, input) -> string`.

Status. Beta; every request needs the header `managed-agents-2026-04-01`; "enabled by default for all API accounts". "Managed Agents is not currently eligible for Zero Data Retention or HIPAA Business Associate Agreement (BAA) coverage" (overview; the self-hosted page's extracted summary claimed eligibility for self-hosted environments, which was not verified against the page text).

Licence. Hosted API under Anthropic's Commercial Terms; branding guidelines forbid presenting it as "Claude Code".

Local vs API. Anthropic-hosted control plane, always. With self-hosted sandboxes "Tool inputs and outputs still flow to Anthropic's control plane (where Claude runs) so the model can see results and determine what to do next"; the worker uses outbound HTTPS polling with an environment key. `web_search` and `web_fetch` "run on Anthropic's servers whether the environment is a cloud or self-hosted sandbox". No offline operation.

Permission policies (full page). Apply to server-executed tools only: "Permission policies control whether server-executed tools (the pre-built agent toolset and MCP toolset) run automatically, wait for your approval, or have each call evaluated by the server. Custom tools are executed by your application and controlled by you, so they are not governed by permission policies." Three policy types: `always_allow`, `always_ask` ("The session pauses and waits for your approval before executing"), `auto` ("The server evaluates each call and runs it, denies it, or pauses for your approval"). Defaults: "the agent toolset defaults to `always_allow`, and MCP toolsets default to `always_ask`." Set per toolset (`default_config.permission_policy`) or per tool (`configs[].permission_policy`). "Running sessions keep the toolset configuration they were created with."

`auto` policy. "Because the evaluation considers the tool, the call's input, and the session's content up to that point, the server can treat two calls to the same tool differently." A server denial "cannot" be overridden: "The agent receives an error tool result with the content `Permission to use {tool_name} has been denied.` ... your client cannot override the denial." "What you post in `user.message` events counts as your intent, and it can lead the server to allow a call it would otherwise deny." Warning: "`auto` is not a human checkpoint. If the server determines that a call is safe, the call runs before anyone sees it".

Approval binding (full page, "Respond to confirmation requests"). The session emits `agent.tool_use` or `agent.mcp_tool_use` (event `id` `sevt_...`, `name`, `input`, `evaluated_permission`, `evaluation`), then `session.status_idle` with `stop_reason.type` `requires_action` and `stop_reason.event_ids`. "Send a `user.tool_confirmation` event for each blocking event, passing the event ID in the `tool_use_id` parameter. Set `result` to `"allow"` or `"deny"`. Use `deny_message` to explain a denial." "If you send a `user.tool_confirmation` for an event whose `evaluated_permission` is not `ask`, the API rejects it with a 400 error." "The session waits indefinitely for a response." The approval is therefore bound to a specific persisted event that carries the tool name and full input; there is no way to approve a modified input, no "always allow" from a confirmation, and no hash or signature of the event.

Decision record (full page, "See how each call was evaluated"). "each `agent.tool_use` and `agent.mcp_tool_use` event carries `evaluated_permission`, the outcome of the call's permission check: `"allow"`, `"ask"`, or `"deny"`. Most events also carry an `evaluation` object whose `type` names the policy that produced that outcome. Under `auto`, the object also records the server's determination, plus a `reason_code` when the outcome is `ask` or `deny`." Example: `"evaluation": {"type": "auto", "evaluated_permission": {"type": "deny", "reason_code": "high_risk"}}`. "A `reason_code` is a value for your client to branch on and keep in audit records, not text to display to end users." The confirmation itself (`user.tool_confirmation`) is a persisted event. Event history is server-side and listable (`GET /v1/sessions/{id}/events`, filterable by `types[]`), each event with `id` and `processed_at`. No statement of immutability beyond the engineering post's "append-only log"; no hashes or signatures on session events. Webhooks are signed (headers `webhook-id`, `webhook-timestamp`, `webhook-signature`; `whsec_` secret; SDK `unwrap()` rejects payloads "more than 5 minutes old") but "return the event `type` and `id`, not the full object" and "Webhooks aren't a durable log".

Custom tools (full page). "When the agent invokes a custom tool, your application receives an `agent.custom_tool_use` event and is responsible for deciding whether to execute it before sending back a `user.custom_tool_result`." `agent.custom_tool_use` carries `id`, `name`, `input` and "neither field" (`evaluated_permission`, `evaluation`). This is an enforcement seam entirely in the integrator's hands; the record of the decision is only the presence or absence of a result event.

Action identity. Event id + tool name + input object (server-assigned id, not content-derived). Enforcement seam: the Anthropic harness for built-in and MCP tools; the client for custom tools; the self-hosted worker's file tools are confined to `--workdir` and `allowed_roots` ("The workdir check is a guardrail for the file tools only, not a sandbox; it does not constrain bash").

## 4. Model Context Protocol (MCP)

Provenance and governance. Created by Anthropic; on 2025-12-09 "Anthropic is donating the Model Context Protocol to the Linux Foundation's new Agentic AI Foundation" (AAIF, co-founded by Anthropic, Block and OpenAI). "The Model Context Protocol's governance model will remain unchanged: the project's maintainers will continue to prioritize community input and transparent decision-making." Repository LICENSE: "The MCP project is undergoing a licensing transition from the MIT License to the Apache License, Version 2.0 ... Documentation contributions (excluding specifications) are licensed under CC-BY-4.0." Current specification: 2026-07-28 (the "latest" URL resolves to it); the changelog lists it with a feature lifecycle and deprecation policy. MCP is a protocol, not a runtime, so "local operation" is whatever the client and server are; stdio servers are fully local.

Tools and tool annotations (raw schema.ts, 2026-07-28):

```
readOnlyHint?: boolean;    // If true, the tool does not modify its environment. Default: false
destructiveHint?: boolean; // If true, the tool may perform destructive updates ... Default: true
idempotentHint?: boolean;  // ... calling the tool repeatedly with the same arguments will have no additional effect ... Default: false
openWorldHint?: boolean;   // If true, this tool may interact with an "open world" of external entities ... Default: true
```

Tools page: "For trust & safety and security, clients MUST consider tool annotations to be untrusted unless they come from trusted servers." "there SHOULD always be a human in the loop with the ability to deny tool invocations." Clients SHOULD "Present confirmation prompts to the user for operations", "Show tool inputs to the user before calling the server", "Log tool usage for audit purposes"; servers MUST "Implement proper access controls". The MCP blog (2026-03-16, "Tool Annotations as Risk Vocabulary") frames annotations as advisory signals that can "drive confirmation prompts" and "feed policy engines" but "cannot ... replace enforcement mechanisms like sandboxing". The Tool Annotations Interest Group charter (2026-04-20) lists open SEPs: SEP-1862 Tool Resolution (preflight checks), SEP-1913 Trust and Sensitivity Annotations, SEP-1984 Comprehensive Tool Annotations, SEP-2417 Model Preferences for Tools; earlier proposals include `trustedHint` (SEP-1487), `unsafeOutputHint` (SEP-1561), `secretHint` (SEP-1560), `agencyHint` (SEP-1792). The IG "produces recommendations, not binding decisions".

Action identity in `tools/call` (raw schema.ts): `CallToolRequestParams` has `name` and `arguments` (plus the MRTR fields `inputResponses` / `requestState` and the required `_meta`). The only identifier is the JSON-RPC request `id`. There is no hash, idempotency key, approval token, or consent field anywhere in the schema (grep of the schema for "approv", "consent", "confirm", "hash", "signature", "idempotencyKey" found only prose in comments). 2026-07-28 removed protocol-level sessions; cross-call state is "explicit, server-minted handles passed as ordinary tool arguments", and security best practices say "MCP servers MUST NOT treat possession of a state handle as authentication."

Elicitation (full page). Two modes, `form` and `url`; three response actions `accept` / `decline` / `cancel` ("User explicitly approved and submitted with data" / "User explicitly declined" / "User dismissed without making an explicit choice"). Delivered under the 2026-07-28 Multi Round-Trip Requests pattern as an `InputRequiredResult` the client answers by retrying the original request. "Servers MUST bind elicitation requests to the client and user identity"; "Clients SHOULD implement user approval controls". It is a server-to-user information request, not a client-side tool-call approval; URL mode "is not for authorizing the MCP client's access to the MCP server".

Authorization (full page). OAuth 2.1 with RFC 9728 Protected Resource Metadata (MUST), RFC 8707 resource indicators (MUST), RFC 9207 issuer identification, Client ID Metadata Documents (SHOULD; Dynamic Client Registration deprecated). Identity asserted: the resource owner, via the authorization server; the token's audience is the MCP server ("MCP servers MUST validate that access tokens were issued specifically for them as the intended audience"). Tokens are bound to the server, not to a tool call; per-operation granularity is only through scopes and step-up (`insufficient_scope` challenges). Security best practices recommend "Log elevation events (scope requested, granted subset) with correlation IDs" and note token passthrough breaks "Accountability and Audit Trail". The stdio transport "SHOULD NOT follow this specification".

Tasks extension (extracted, https://tasks.extensions.modelcontextprotocol.io/). Identifier `io.modelcontextprotocol/tasks`, version 2026-07-28, moved out of the core by SEP-2663. "Servers return a durable task handle instead of blocking on a long-running operation; clients poll for progress and retrieve the result when ready." States: `working`, `input_required` (non-terminal); `completed`, `failed`, `cancelled` (terminal). Methods `tasks/get`, `tasks/update`, `tasks/cancel` (no `tasks/list`). Task ids are server-generated. The extension describes `input_required` as serving "approval gates that block until a person responds", with `inputRequests` fulfilled via `tasks/update`. No audit record is defined.

Assessment against the criteria. Action identity: name + arguments, no content hash. Approval binding: none in the protocol; hints and SHOULD-level guidance for the client. Receipt: none; "Log tool usage for audit purposes" is a client SHOULD. Enforcement seam: the client (host application) by design; servers enforce authorization on their side. Local operation: yes for stdio.

## 5. Agent Skills, agent identity, agent-to-agent

Agent Skills (full page, https://agentskills.io/specification). "The Agent Skills format was originally developed by Anthropic, released as an open standard"; specification repository licensed Apache-2.0; anthropics/skills mixes Apache-2.0 skills with source-available document skills. A skill is a directory with `SKILL.md` whose frontmatter has `name`, `description`, optional `license`, `compatibility`, `metadata`, and `allowed-tools`: "A space-separated string of tools that are pre-approved to run. Experimental. Support for this field may vary between agent implementations." Example `allowed-tools: Bash(git:*) Bash(jq:*) Read`, that is, Claude Code rule syntax. Skills package instructions and scripts; they do not define an action model, an approval, or a record. No signing or provenance mechanism is specified.

Agent identity. Anthropic publishes no "agent identity" specification. Related surfaces found:

- Workload Identity Federation (full page, https://platform.claude.com/docs/en/manage-claude/workload-identity-federation): "A service account (`svac_...`) is a named, non-human identity inside your Anthropic organization." A federation rule says "when a JWT from issuer X has claims that look like Y, mint a token for service account Z with scope S." Tokens are short-lived (60 to 86400 s; lifetime capped at twice the remaining IdP JWT lifetime) with `jti` replay protection. "a workspace API key is a credential, while a service account has credentials. You can more easily audit which workloads acted as which service account." This identifies the caller of the Anthropic API, not an action.
- Containment (extracted, https://www.anthropic.com/engineering/how-we-contain-claude, 2026-05-25): Cowork's "credentials stay in the host keychain, the VM gets a per-session scoped-down token, and that token can be revoked independently of the user's"; "tool calls route through proxies that enforce network and file policy and can inspect return values before they enter the model's context".
- Managed Agents vaults hold MCP OAuth credentials workspace-scoped; self-hosted workers authenticate with an environment key.

Agent-to-agent. No Anthropic A2A protocol was found. Claude Code agent teams (full page, experimental, `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`) define the only documented inter-agent consent rule: "When one agent sends another a message over `SendMessage`, Claude Code tells the receiving agent the message came from another Claude session, not from you. A teammate can't approve a permission prompt or supply consent on your behalf, and a teammate that was denied an action can't relay it to another teammate to bypass the check." In auto mode the classifier "treats an approval claim relayed from another agent as untrusted input rather than confirmation from you." "Teammates start with the lead's permission mode, except `dontAsk` mode"; "Teammate permission prompts appear in the lead session". Managed Agents has multiagent orchestration (events `agent.thread_message_sent/received`; roster agents' domain allowlists "combine to the domains that all of them cover"), not read in depth.

## 6. Anthropic policy and guidance relevant to runtime action governance

- "Our framework for developing safe and trustworthy agents" (extracted, 2025-08-04): five principles headed "Keeping humans in control while enabling agent autonomy", "Transparency in agent behavior", "Aligning agents with human values and expectations", "Protecting privacy across extended interactions", "Securing agents' interactions". "Humans should retain control over how their goals are pursued, particularly before high-stakes decisions are made." Describes Claude Code as read-only by default and that "Users can grant persistent permissions for routine tasks they trust Claude to handle."
- "Trustworthy agents in practice" (extracted, 2026-04-09): defences "spanning the model, harness, tools, and environment"; users "can configure permissions (e.g., always allow, needs approval, block) for each action Claude takes"; Plan Mode as approval of a whole plan "before anything happens" rather than per action.
- "Measuring AI agent autonomy in practice" (extracted, 2026-02-18): auto-approve use rises from about 20% of new users to over 40% of experienced users while interruption rates rise; conclusion: "Effective oversight of agents will require new forms of post-deployment monitoring infrastructure and new human-AI interaction paradigms that help both the human and the AI manage autonomy and risk together."
- "How we contain Claude across products" (extracted, 2026-05-25): see section 5; enforcement described at proxies and sandboxes rather than at a canonical action object.
- Usage Policy (extracted, effective 2025-09-15): "Agentic use cases must still comply with the Usage Policy." High-risk (consumer-facing legal, financial, employment and similar) uses require "Human-in-the-loop: ... a qualified professional in that field must review the content or decision prior to dissemination or finalization." The words "autonomous" and "human oversight" do not appear.
- Responsible Scaling Policy v3.4 (extracted, effective 2026-07-08): deployment safeguards are described at the model-serving level (real-time and asynchronous classifiers, access controls, jailbreak response). The extraction found no provision governing the actions a deployed agent may take at runtime.
- Inference hooks (full page, beta, Claude Enterprise; https://platform.claude.com/docs/en/manage-claude/inference-hooks): an organisation-run "AI security server" receives every governed prompt "before inference begins" and returns `{"action": "allow"}` or a deny; "Your AI security server sees what the user sees: transcript text, tool calls and their results"; "Verdicts are allow or deny. Rewriting or redacting a prompt is not supported"; failure handling is configurable ("block the request, or allow it to proceed without inspection"); requests are signed per the Standard Webhooks specification; denials are recorded in the Activity Feed. Covers claude.ai, Cowork and Claude Code sessions in an Enterprise organisation; not Bedrock or Google Cloud; "Today the only hook event is `prompt`". This is a per-inference-turn gate, not a per-tool-call gate, but it sees tool calls and results in the transcript it judges.
- Messages API tool use (full page): "The model never executes anything on its own. It emits a structured request, your code (or Anthropic's servers) runs the operation". The `tool_use` block carries an id, name and JSON arguments; the `tool_result` echoes `tool_use_id`. No approval, idempotency or audit primitive exists at the API level for client tools.

## Closing table: five criteria

Legend: "Identity" = what the action is at the decision point; "Binding" = whether a human approval attaches to that specific call and how; "Receipt" = whether a decision record is written and in what form; "Seam" = where enforcement happens; "Local" = runs without Anthropic's API.

| Item | Identity | Binding | Receipt | Seam | Local |
| --- | --- | --- | --- | --- | --- |
| Claude Agent SDK | tool name + full input + per-call `toolUseID`/`requestId`; no hash | Per call via `canUseTool`/PreToolUse; approver's `updatedInput` is what runs; persistence only as text rules | Local transcript JSONL, OTel `tool_decision`, integrator's hooks; unsigned | In-process, before execution (hook -> rules -> mode -> callback); OS sandbox for shell | Evaluation local; model via Anthropic API or Bedrock/GCP/Foundry |
| Claude Code hooks/permissions | tool name + literal input text; `tool_use_id` on PreToolUse/PostToolUse, absent on PermissionRequest | Per call at prompt; "don't ask again" saves a pattern rule to `.claude/settings.local.json` | OTel `tool_decision` with `decision_source`; plaintext transcript 30 days; Enterprise Compliance API transcript (6 y, no decisions); unsigned | Claude Code process + Seatbelt/bubblewrap sandbox + hostname proxy | Same as SDK; WebFetch hostname check calls api.anthropic.com |
| Claude Code `defer` | `deferred_tool_use` {id, name, input} captured pre-execution | Pending approval persisted in the session file until resumed; no timeout | Plain JSON in local session; unsigned | Same | Same |
| Managed Agents | server event id `sevt_` + name + input; `evaluated_permission` + `evaluation` | `user.tool_confirmation` must cite the event id; rejected (400) unless `evaluated_permission` is `ask`; no modified-input approval; `auto` denials final | Persisted, listable event history incl. confirmation events and `reason_code`; signed webhooks carry ids only; not hashed | Anthropic harness for built-in/MCP tools; client for custom tools | No; control plane always Anthropic-hosted |
| MCP core (tools, annotations) | `name` + `arguments`; JSON-RPC id only | None in protocol; clients SHOULD prompt; annotations are untrusted hints | None; "Log tool usage for audit purposes" is a client SHOULD | Client/host by design | Yes (stdio) |
| MCP elicitation | n/a (server asks user for data) | accept/decline/cancel bound to client and user identity | None | Client UI | Yes |
| MCP authorization | Token audience = server; scopes per operation | None per call; step-up scopes | Recommended: log scope elevations with correlation ids | Server (resource server) | Server-dependent |
| MCP Tasks extension | server-generated task id | `input_required` state blocks until `tasks/update` | Durable task store; no audit spec | Server | Yes |
| Agent Skills | none (instructions + `allowed-tools` pre-approval list, experimental) | none | none | Host agent | Yes |
| WIF / service accounts | caller identity, not action | none | IdP + Anthropic auth history | Anthropic API edge | No |
| Inference hooks (beta) | whole transcript incl. tool calls/results, per inference turn | allow/deny per request; no rewrite; fail mode configurable | Denials in Activity Feed; signed requests to your server | Anthropic server-side, before inference | No (Enterprise, Anthropic API only) |
| Messages API tool_use | `tool_use.id` + name + input | none | none | Your loop | No |
| Policy docs (framework, RSP, AUP) | n/a | Principles: human control "before high-stakes decisions"; HITL for high-risk consumer uses | n/a | n/a | n/a |

Against the comparison targets: no Anthropic surface produces a content-derived canonical action object or hash (CAVA), none issues a signed or hashed certificate of route/review/proof (PCAA), and none defines a fixed set of interception points with a `transform` verdict across runtimes (ACS). The closest partial matches are Managed Agents (server-assigned event id binding and a persisted `evaluation` record) and the Agent SDK/Claude Code PreToolUse hook (a single pre-execution seam with allow/deny/ask/defer plus `updatedInput`, which is a transform).

## Not found / not verified

- Any Anthropic document defining a canonical action object, action hash, or signed decision receipt: not found in official docs.
- Any statement that Managed Agents session events are immutable, hashed, or signed: not found (only the engineering post's "append-only log" phrase).
- Self-hosted sandbox eligibility for Zero Data Retention / HIPAA: reported by the fetch tool's extraction of the self-hosted page but contradicted by the overview page's verbatim text; not verified.
- Anthropic's NIST RFI response on agentic security (https://www-cdn.anthropic.com/43ec7e770925deabc3f0bc1dbf0133769fd03812.pdf): the fetch tool could not extract the PDF text; a first-pass summary produced by the tool is discarded as unverifiable. Not verified.
- Managed Agents SDK client licences (anthropic-sdk-python etc.) and Agent SDK version numbers: not captured.
- TypeScript Agent SDK LICENSE file: raw URL returned 404; licence stated only via the overview page and the GitHub page summary.
- Claude Code auto-mode engineering deep-dive (https://www.anthropic.com/engineering/claude-code-auto-mode) and the CISO guide on claude.com: not read.
- Any Anthropic agent-to-agent protocol, agent identity specification, or participation in an external A2A standard: not found in official docs.
- Managed Agents multiagent orchestration permission details: page not read.
- The "84% fewer prompts" figure attributed to sandboxing in the containment post extraction: not verified verbatim and deliberately omitted from the body.
- Verbatim text of the anthropic.com policy posts (section 6 items marked "extracted"): quotations are as returned by the fetch tool, not re-read against the page.
