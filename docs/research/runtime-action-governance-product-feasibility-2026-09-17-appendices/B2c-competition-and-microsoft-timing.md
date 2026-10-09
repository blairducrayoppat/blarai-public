# R2-C — Competition and timing risk (web-only; 2026-09-17)
(Persisted by the compiler from the sub-agent's returned text; content unchanged.)

**Headline.** Microsoft already owns the two seams the proposed product would sit on, and is using both — but only for enterprises. (1) Microsoft Defender for Endpoint (MDE) has shipped, in public preview since June 2026, exactly the mechanism the product would use: it hooks Claude Code, Codex CLI, GitHub Copilot CLI and the Copilot app through their vendor hook interfaces, inspects prompt / pre-tool / post-tool events, and blocks — gated behind MDE Plan 2 / Microsoft 365 E5 / Agent 365 / E7. (2) Windows itself has a consumer-visible per-agent permission page (Settings > System > AI components > Agents > [agent] > Files, Allow always / Ask every time / Never) since December 2025, but it governs only agents that run inside Microsoft's agent workspace / on-device registry model — today Copilot Actions and MCP connectors — not Claude Code or Codex running as ordinary user processes. Nothing found says Microsoft will bring the Defender hook-based enforcement to consumers or to Windows Security; nothing found says third-party CLI agents will appear in the consumer Agents page. The startup field is almost entirely hosted enterprise control planes; the only shapes that resemble the brief are open-source individual projects (Rampart, Hazmat, Trollbridge, Pipelock) and Solo.io's Apache-2.0 "agentdesktop" (2026-09-03).

Grading: REPORTED = read at the cited URL (Learn pages carry their `ms.date`); GUESSED = my estimate with reasoning. Vendor prose was discounted where an artefact (GitHub API, npm registry, Learn page) was available.

## 1. Microsoft's own agent-governance surfaces

### 1a. Microsoft Defender for Endpoint — local AI agent discovery + AI agent runtime protection (REPORTED)
- Ignite 2025 (2025-11-18): Defender posture management + threat protection for AI agents entered preview for cloud agents only (Microsoft Foundry, Copilot Studio). No endpoint-agent coverage was announced then. Security Copilot bundled into M365 E5 (400 SCUs/1,000 licences).
- 2026-05-01 (Agent 365 GA blog): "With Microsoft Defender and Intune, organizations will be able to discover and manage local AI agents running on Windows devices, starting with OpenClaw agents"; Copilot CLI and Claude Code "coming soon"; Intune policies to block OpenClaw run methods GA; asset context mapping + policy controls + runtime blocking → public preview June 2026.
- MDE "New features" (ms.date 2026-06-22, updated 2026-09-09): June 2026 (Preview) Local AI agent discovery on onboarded Windows devices — coding agents, IDE extensions, desktop AI assistants, local runtimes, agent platforms; appear in AI agent inventory, exposure map, advanced hunting. Same month: macOS support + more agents. June 2026 (Preview) Local AI agent runtime protection — "inspects the agent loop (user prompts, tool calls, and tool responses) and can block risky activity before it executes". July 2026 (Preview) runtime-protection update: agent-native inspection adds Codex CLI and the GitHub Copilot app; network inspection added for OpenClaw and "similar Node.js-based Claw agents".
- Supported agents (local-agent-discovery-overview, ms.date 2026-05-27): CLI: Claude Code, Codex CLI, Gemini CLI, GitHub Copilot CLI, Junie CLI, Kiro CLI, OpenCode, Warp, Antigravity CLI. Desktop: ChatGPT, Claude, Codex, Goose, Hermes Agent, Ollama, Perplexity, Poe. IDEs: Cursor, Devin/Windsurf, Kiro, Antigravity. VS Code extensions: Claude Code, Cline, Codex, Gemini Code Assist, GitHub Copilot, Roo Code. Claw-based: OpenClaw, Clawpilot, QClaw, Claw/Nanobot. Also discovers local + remote MCP server configurations. An "agent" = user + device + agent type.
- Mechanism (ai-agent-runtime-protection-overview, ms.date 2026-09-16): two approaches. Agent-native event inspection uses "vendor-supported event interfaces" — it links directly to Claude Code hooks, Codex CLI hooks, GitHub Copilot CLI hooks and Copilot app hooks — receiving payloads at user-prompt, pre-tool-call and post-tool-response, with audit or block per event. Network inspection for agents without hooks (OpenClaw); does not support certificate pinning or HTTP/3. Modes Disabled/Audit/Block; setting is tamper-protected; block shows an in-terminal message plus a Windows toast; detections listed under Windows Security > Virus & threat protection > Protection history.
- Licence and knobs (configure-ai-agent-runtime-protection, ms.date 2026-09-16): requires Defender for Endpoint Plan 2, Microsoft 365 E5, Microsoft Agent 365, or Microsoft 365 E7, device onboarded to MDE, Defender Antivirus active, signature ≥ 1.451.224.0. Enabled by `Set-MpPreference -AiAgentProtection <Audit|Block>` and `-AiAgentNetworkInspection`, or an Intune Antivirus profile named "Microsoft Defender AI agent runtime protection". Enterprise-only by licence; the cmdlet lives in the Defender Antivirus platform, but no page says the consumer Defender exposes it (a read-only `Get-MpPreference` on this machine would settle whether the property exists on a non-onboarded install — not probed; web-only).
- Defender XDR what's new (ms.date 2026-09-08): July 2026 (Preview) AI agent posture risk "including … local agents discovered on endpoint devices"; July 2026 (GA) real-time protection for Agent 365 tooling servers; new `AgentsInfo` hunting table covers "endpoint-discovered agents". defender-security-for-ai (ms.date 2026-08-07): "When you enable an Agent 365 license, Microsoft Defender integrates with Agent 365 to secure all managed agents, including local AI agents on supported endpoints."

### 1b. Microsoft Agent 365 (REPORTED)
- Announced Ignite 2025-11-18. Tech Community post 2026-03-09 announced GA for 2026-05-01 at $15/user/month; also inside Microsoft 365 E7 ($99/user/month — SAMexpert, secondary). Prerequisite base licence (E5 / Defender+Purview Suite / Business Premium) — SAMexpert, secondary. Licensed per user, not per agent. Build 2026 security blog (2026-06-02): registry "supports more than 20 types of local agents" and tracks local and remote MCP servers; Agent 365 SDK GA; Windows 365 for Agents GA. Enterprise-only.

### 1c. Microsoft Entra Agent ID (REPORTED)
- GA 2026-05-01 (whats-new-agent-id, ms.date 2026-05-01): agent identities, blueprints, sidecar Auth SDK, Conditional Access templates for agents, third-party patterns, migration from app registrations and Copilot Studio; agent registry UX converging into Agent 365. Tenant (work/school) identity only — no Microsoft-account (consumer) surface is mentioned on any page fetched (REPORTED absence).

### 1d. Purview / Defender for Cloud Apps (REPORTED)
- Build 2026 security blog (2026-06-02): Purview "controls to prevent data exfiltration, DSPM risk discovery, and agentic risk detection for coding agents" naming Claude Code, GitHub Copilot, OpenAI Codex, OpenClaw (preview). The Purview overview page (ms.date 2026-05-27) does not yet mention coding agents. Defender for Cloud Apps release notes (ms.date 2026-06-14): no 2026 agent-specific entry.

### 1e. Windows agent workspace / agent account / Copilot Actions (REPORTED)
- 2025-10-16 Windows Experience Blog (Dana Huang, CVP Windows Security): "agent workspace", "agent accounts", toggle at Settings > System > AI components > Agent tools > Experimental agentic features, off by default; access outside Documents/Downloads/Desktop/Pictures needs explicit authorisation; "the Windows platform and its security controls will be available for other developers in private preview soon."
- 2025-11-17 Windows Insider Blog: Copilot Actions rolling out to Insiders (Copilot app 1.25112.74+), all Insider channels, EEA excluded, Copilot Labs experimental.
- 2025-11-18 Ignite Windows post: agent workspace (preview), agent connectors (preview, MCP, "any AI agents, first or third party"), Windows 365 for Agents (preview); partners Manus and Claude named.
- support.microsoft.com "Experimental agentic features" (editor's note 2025-12-05): admin-only, device-wide toggle at Settings > System > AI Components > Experimental agentic features; each agent runs under its own agent account in a separate workspace; six known folders; per-agent page Settings > System > AI Components > Agents > [agent] > Files with Allow Always / Ask Every Time / Never Allow; "preview builds 26100.7344+". Consumer-facing documentation, not edition-gated in text.
- Build placement (derived, not verified): the Windows 11 release-information page (ms.date 2026-09-14) shows GA-channel builds 26200.7309 (2025-12-01) and 26200.7462 (2025-12-09); 7344 sits between them, so the per-agent consent plumbing is in the production servicing branch since the December 2025 update, behind the toggle (and probably controlled feature rollout). A Settings check on this 26200.x machine would settle it.
- No GA announcement found: the 26H2 Release Preview post (2026-08-27, build 26300.9278) and the IT Pro "Get ready for 26H2" post contain no agent workspace / connector / MCP mention. Production-branch agent items that did ship: Agent Launchers framework (Dev/Beta 26220.7523, 2025-12-19) and "Agents on Taskbar" monitoring for first- and third-party apps via `Windows.UI.Shell.Tasks` (Release Preview 26100/26200.8313, 2026-04-17).
- Policy CSP "WindowsAI" (ms.date 2026-06-22): AgentConnectorAccessPolicy, AgentConnectorMinimumPolicy (0 user in control / 1 restricted / 2 bypass), AgentConsentDuration (default 720 h), ConfigureAgentConnectors, DisableAgentConnectors, DisableAgentWorkspaces, DisableRemoteAgentConnectors, DisableSettingsAgent, OnDeviceRegistryLoggingLevel — every one marked Pro ❌, Enterprise/Education/IoT ✅, "Windows Insider Preview". The lockdown policies are enterprise-only; the user-facing feature is not documented as edition-limited.

### 1f. MCP on Windows / on-device registry (ODR) and Windows AI Foundry consent (REPORTED)
- 2025-05-19 (David Weston, Build 2025): proxy-mediated MCP traffic; tool-level authorisation — "users must explicitly approve each client-tool pair, with support for per-resource granularity"; runtime isolation; mandatory code signing; central registry; private developer preview post-Build.
- 2025-12-05 Insider build 26220.7344 (KB5070316, Dev + Beta): native MCP support, ODR, File Explorer connector, Windows Settings connector.
- Learn mcp/overview (ms.date 2025-12-06): "users and IT admins can control access to MCP servers for each agent by using Windows Settings and … Intune"; logging/audit; `odr.exe`. mcp-containment (ms.date 2025-11-11): contained servers run in a separate Windows session under a separate agent user account; require MSIX package identity + manifest; file permissions are granted per host app, not per server; MCPB bundles cannot run contained; "Reduce protections for agent connectors" switch exists.
- Build 2026 (2026-06-02): Microsoft Execution Containers (MXC) SDK early preview; GitHub Copilot CLI adopted MXC process isolation; OpenClaw, Hermes Agent, NVIDIA OpenShell, Manus, OpenAI/Codex integrating; Claude Code "expanding soon" for Agent 365 discovery. Artefacts: `microsoft/mxc` (MIT, 1,337 stars, created 2026-02-06, pushed 2026-09-17); npm `@microsoft/mxc-sdk` 0.1.6 (2026-04-30) → 0.8.0 (2026-08-22), "Windows 11 24H2+". GitHub docs: Copilot CLI local sandboxing on Windows "requires a Windows Insiders build".
- Microsoft statements about a consumer per-agent permission manager: the Agents settings page above is the only one; no statement found that third-party agents (Claude Code, Codex) will appear in it.

## 2. MCP-gateway and endpoint agent-security field

| Vendor | Shape | Target | Windows? | Funding / date | Pricing public? | Grade |
|---|---|---|---|---|---|---|
| Lasso Security | Hosted platform + OSS mcp-gateway (MIT, 388★, last push 2026-01-22) | Enterprise/dev | No endpoint agent found | Seed $6M 2023-11-20; Series A $30M 2026-09-02 | No | REPORTED |
| Pipelock / PipeLab | Local Go binary firewall (Apache-2.0 core, ELv2 enterprise); fleet control plane paid | Dev → enterprise | Yes (windows_amd64/arm64, v3.5.0 2026-09-01); 876★ | No funding disclosed | Pricing page exists | REPORTED |
| Zenity | Hosted control plane + Zenity Labs (ACS author) | Enterprise | Browser/M365/SaaS agents; not endpoint CLI | Series C $125M 2026-08-03 | No | REPORTED |
| Noma Security | Hosted platform | Enterprise | No | Series B $100M 2025-07-31; total $132M | No | REPORTED |
| Prompt Security | Hosted + browser ext/desktop monitoring; now SentinelOne "Prompt AI Agent Security" (2026-03-23) | Enterprise | Employee devices (browser); MCP visibility | Acquired by SentinelOne 2025-08-05 (~$250M announced; ~$180M paid) | No | REPORTED |
| Invariant Labs | mcp-scan → `snyk/agent-scan` (Apache-2.0, 3,058★, v0.6.3 2026-09-10) + Guardrails | Dev/enterprise | CLI scanner | Acquired by Snyk 2025-06-24 | n/a | REPORTED |
| Cloudflare | Hosted MCP Server Portals (Cloudflare One) | Enterprise | n/a | Open beta 2025-08-26 | Yes (50 free) | REPORTED |
| Obot AI | OSS gateway (MIT, 1,019★) + hosted/K8s enterprise | Enterprise | Server-side | Seed $35M 2025-09-23 | No | REPORTED |
| MintMCP | Hosted MCP gateway | Startups/enterprise | Server-side | $3.8M | Not checked | REPORTED (secondary) |
| Pomerium | OSS identity-aware proxy (Apache-2.0, 5,007★) w/ MCP support | Enterprise/dev | Go binary | — | n/a | REPORTED |
| Runlayer | Hosted enterprise MCP control plane | Enterprise | No | Seed $11M 2025-11; Series A $30M 2026-06-24; total $42M | No | REPORTED |
| Aim Security | Hosted; acquired by Cato Networks | Enterprise | Browser/SASE | 2025-09-03 (~$350M reported) | n/a | REPORTED |
| Protect AI → Palo Alto Prisma AIRS 3.0 | Hosted; AIRS 3.0 scans "endpoint agents (including vibe coding agents) running on developer systems" | Enterprise | Not stated | closed 2025-07-22; AIRS 3.0 2026-03-23 | No | REPORTED |
| HiddenLayer | Hosted; "Agentic Runtime Security", "Agent Harness Security" for coding agents | Enterprise | Not stated | Series B $100M 2026-09-02 | No | REPORTED |
| Straiker | Hosted | Enterprise | Not stated | Series A $64M 2026-06-29; total $85M | No | REPORTED |
| Operant AI | Hosted/Kubernetes; MCP Gateway (2025-06), Agent Protector (2026-02), ScopeGuard (2026-03) | Enterprise | No | Series A $10M 2024-09-12 | No | REPORTED (secondary) |
| Acuvity | Hosted shadow-AI/DLP; acquired by Proofpoint 2026-02-12 | Enterprise | Employee endpoints via Proofpoint | Seed $9M 2024-09 | n/a | REPORTED |
| Lakera | Hosted guardrails; acquired by Check Point 2025-10-01 (~$300M) | Enterprise | No | — | n/a | REPORTED |
| CalypsoAI | Hosted; acquired by F5 2025-09-11 ($180M) | Enterprise | No | — | n/a | REPORTED |
| Enkrypt AI | Hosted; acquired by Anaconda 2026-08-04 | Enterprise | No | — | n/a | REPORTED |
| Cisco AI Defense | Hosted; RSAC 2026-03-23: Identity Intelligence for agents, DefenseClaw OSS scanners, Secure Access MCP policy enforcement; acquired Astrix 2026-05-04, Galileo 2026-04-09, WideField 2026-06-18 | Enterprise | Network/SSE; scanners are dev-time | Public co. | Partly | REPORTED |
| CrowdStrike Falcon | Endpoint sensor: shadow-AI discovery incl. LLM runtimes + MCP servers, runtime detection of agent process activity, prompt-layer protection for desktop AI apps (RSA 2026-03-23/24) | Enterprise | Yes (Falcon sensor) | Public co. | No | REPORTED |
| SentinelOne | Prompt AI Agent Security (control plane, MCP visibility/enforcement), 2026-03-23, preview | Enterprise | Singularity agent | Public co. | No | REPORTED |
| Zscaler | AI Broker (A2A/MCP, agent registry) + Endpoint AI Security ("local AI tools"), 2026-06-09; no GA/pricing | Enterprise | Client Connector (implied) | Public co. | No | REPORTED |
| 1Password | Secure Agentic Autofill (early access 2025-10-08); Unified Access (2026-03-17) discovers "agent activity across endpoints, browsers, and local environments", names Claude Code, Cursor, MCP gateways; business/enterprise only | Business | Yes | Private | No | REPORTED |
| Endor Labs | Hooks-based coding-agent governance (Claude Code, Cursor); local `endorctl ai-audit` streams to hosted policy backend; 29 default policies (2026-05-12, upd. 2026-07-30) | Enterprise | Not stated | Private | Pricing page | REPORTED |
| Solo.io agentdesktop | Desktop governance for "Claude Code, Codex, and other general-purpose agents": inventory of harness/model/MCP/skills, central config, NHI identity, opt-in telemetry; standalone or fleet mode; Apache-2.0 (2026-09-03) | Enterprise platform/security teams | Not stated; repo not located | Private | No | REPORTED |
| Consumer-facing products | None found. Closest: 1Password (agent features business-only); OpenClaw ecosystem tools (ClawSecure 2026-03-26, clawmoat.com, Carapace scanner) | Consumers/hobbyists | Mixed | None | — | REPORTED (absence) |

## 3. Open-source governors and standards (GitHub API read 2026-09-17)

| Project | Licence | Stars | Last release / push | Windows | Notes | Grade |
|---|---|---|---|---|---|---|
| Portmaster (Safing) | GPL-3.0 | 13,732 | v2.2.3 2026-08-14; push 2026-09-10 | Yes (WFP kernel driver) | Per-app network firewall; no agent awareness | REPORTED |
| Pipelock | Apache-2.0 (ELv2 enterprise) | 876 | v3.5.0 2026-09-01 | Yes | Egress firewall for HTTP/MCP/A2A/WS; Ed25519-signed action receipts | REPORTED |
| OWASP Agent Control Standard | Apache-2.0 per repo LICENSE; Zenity's post (2026-09-10) says "MIT" — discrepancy | 127 | created 2026-04-10; push 2026-09-15; OWASP page 2026-09-01; v0.1 public preview | n/a (spec) | "a hook only exists if the platform builds it"; no adopters named | REPORTED |
| CAVA (OndCo/CAVA) | Apache-2.0 | 2 | created 2026-07-15; push 2026-08-05 | n/a | arXiv 2607.13716 (2026-07-15, Ond Holdings); open schema vs "OSuite" managed layer (hosted); no MIT "Agent Hooks contract" repo found | REPORTED |
| NeMo Guardrails (NVIDIA) | Apache-2.0 | 7,151 | v0.24.1 2026-09-16 | Python | Dialogue/LLM rails, not OS action control | REPORTED |
| Guardrails AI | Apache-2.0 | 7,424 | v0.11.0 2026-08-14 | Python | Output validation | REPORTED |
| Claude Code sandbox-runtime | Apache-2.0 | 5,257 | push 2026-09-16 | No native Windows ("macOS, Linux, and WSL2") | Seatbelt / bubblewrap; hooks are the governance seam | REPORTED |
| OpenAI Codex CLI Windows sandbox | proprietary | n/a | March 2026 native Windows launch; design post 2026-05 | Yes, native: elevated mode = dedicated low-privilege sandbox users + firewall rules + private desktop; unelevated = restricted token + ACLs; offline by default | Codex also exposes hooks (developers.openai.com/codex/hooks) | REPORTED |
| GitHub Copilot CLI | proprietary | n/a | docs July 2026 | Local sandbox on Windows needs Insider build (MXC); permission layers: trusted dirs, tool allow/deny, path/URL checks, hooks, secret redaction | Public preview | REPORTED |
| Docker MCP Gateway | MIT | 1,567 | v0.43.3 2026-07-16 | Yes | interceptors: signature verify, secret block, call log | REPORTED |
| mcp-guardian (eqtylab) | Apache-2.0 | 200 | push 2025-08-08 (stale) | Rust | Proxy/manage MCP servers | REPORTED |
| agentgateway (Solo.io → LF / AAIF) | Apache-2.0 | 4,889 | v1.5.0 2026-08-27 | Yes | Rust data plane for MCP/A2A/LLM; LF acceptance 2025-09-02 | REPORTED |
| ToolHive (Stacklok) | Apache-2.0 | 2,182 | v0.49.0 2026-09-11 | Yes | Containerised MCP servers | REPORTED |
| Rampart (peg/rampart) | Apache-2.0 | 84 | created 2026-02-10; push 2026-09-12 | Yes (PowerShell installer) | "Policy engine that audits and controls what OpenClaw, Claude Code, Cursor, Codex, and any AI tool can do on your machine": native Claude Code/Codex hooks, OpenClaw plugin, MCP stdio proxy, shell-wrapper fallback; YAML allow/ask/deny; hash-chained local audit. Individual project — closest analogue to the brief | REPORTED |
| Hazmat | MIT | 174 | created 2026-03-27; push 2026-09-11 | macOS only | User isolation, sandbox, firewall, TLA+ verified | REPORTED |
| Trollbridge | MIT | n/a | HN 2026-07-14 | Windows via WSL2/Hyper-V only | Egress HTTP proxy with allow/deny + TUI approval | REPORTED |
| Microsoft MXC | MIT | 1,337 | npm 0.8.0 2026-08-22 | Windows 11 24H2+ | Sandbox SDK agents opt into; not a governor | REPORTED |

## 4. Signals that Microsoft will ship a consumer per-agent permission surface

| Date | Signal | Source | What it means |
|---|---|---|---|
| 2025-05-19 | MCP on Windows security model: proxy, per client-tool consent, isolation, signing, registry | Windows Experience Blog (D. Weston) | Microsoft claimed the MCP seam a year before any startup shipped a Windows gateway |
| 2025-10-16 | Agent workspace, agent accounts, experimental toggle off by default; third-party developers "private preview soon" | Windows Experience Blog (D. Huang) | Consumer-editions Settings surface designed in from day one; third parties invited into Microsoft's model, not governed from outside |
| 2025-11-17 | Copilot Actions to all Insider channels (EEA excluded) | Windows Insider Blog | Microsoft's own agent live on consumer Insider PCs |
| 2025-11-18 | Ignite: agent connectors "first or third party"; Agent 365; Windows 365 for Agents | Windows blogs | Enterprise control plane; Windows connectors open to third parties |
| 2025-12-05 | Build 26220.7344: native MCP, ODR, connectors; support page: per-agent Files consent "26100.7344+" | Windows Insider Blog; support.microsoft.com | The consumer per-agent permission page exists — for agents in the workspace/ODR model |
| 2025-12-09 (derived) | GA-channel build 26200.7462 > 7344 | Learn release-information (ms.date 2026-09-14) | Consent plumbing likely in production servicing branch behind toggle; not verified |
| 2025-12-19 | Agent Launchers; invoke agents from taskbar | Insider build 26220.7523 | Registry of agents becomes an OS concept |
| 2026-04-17 | "Agents on Taskbar" for first- and third-party apps ships to Release Preview 26100/26200.8313 | Windows Insider Blog | Agent-aware shell reaches production branch |
| 2026-05-01 | Agent 365 GA; Defender+Intune discover/manage local agents (OpenClaw now; Copilot CLI, Claude Code "soon") | Microsoft Security Blog | Enterprise governance of third-party local agents begins |
| 2026-06-02 | Build 2026: MXC SDK; Copilot CLI adopts it; Purview coding-agent risk detection | Windows Developer Blog; Security Blog | Third-party agents enter Windows containment by vendor opt-in, not OS imposition |
| 2026-06 | MDE local AI agent discovery + runtime protection (Preview), hooks-based, block mode, toast UI | Learn MDE what's new | The exact mechanism of the proposed product, built by Microsoft, enterprise-licensed |
| 2026-06-22 | WindowsAI CSP agent policies, Enterprise/Education only, Insider | Learn Policy CSP | Admin lockdown enterprise-only; user control everywhere |
| 2026-07 | Runtime protection adds Codex CLI, Copilot app, OpenClaw network inspection | Learn MDE / XDR what's new | Coverage widening monthly |
| 2026-08-27 | 26H2 Release Preview: no agent workspace / MCP GA mention | Windows Insider Blog | No consumer GA yet |
| 2026-11-17→20 | Ignite 2026 scheduled | event listing | No public previews found as of 2026-09-17 |

Not found: any Microsoft statement about bringing MDE agent runtime protection to consumer Defender or the Windows Security app; any plan to list Claude Code/Codex in the consumer Agents page; job postings.

## 5. Window estimate (GUESSED)

(a) Microsoft's own agents (Copilot Actions, connectors): 0–6 months, median ~4. The consumer surface already exists in preview and has been in Copilot Labs for ten months. For a product whose value is governing Microsoft's agents, the effective window is zero — Microsoft owns the seam and the UI.

(b) Third-party agents on the PC (Claude Code, Codex, Copilot CLI): 9–24 months, median ~15 (≈ Q4 2027), for a native consumer per-agent action-governance surface. Reasoning: (i) the hard technical dependency — vendor cooperation — is already satisfied: all three expose hooks and Microsoft consumes them today in MDE; (ii) the engine ships in the Defender Antivirus platform (`Set-MpPreference -AiAgentProtection`), so a consumer port is a licensing/product decision, not engineering; (iii) but Microsoft's stated third-party path is MXC opt-in + Agent 365/Intune, all enterprise, and its consumer per-agent page is bound to the workspace/ODR model, which Claude Code and Codex do not use; (iv) Microsoft's consumer AI cadence has been Insider-first and slow to GA (Recall, Copilot Actions). Earlier is possible (a coarse "block this agent" within ~9 months); a full per-action vocabulary across vendors for consumers is the far end. Confidence low — one Ignite announcement would collapse the range.

Key structural read: Microsoft's per-agent consent is per host app for MCP servers, defaults to 30-day durable consent, and covers only its own containment model; the third-party seam it actually enforces on (hooks + network inspection) is enterprise-gated. That gap — hooks-based, local-only, signed record, consumer/prosumer — is where Rampart, Pipelock, Hazmat and agentdesktop sit today, none funded, none Windows-first.

## Sources (URL — date read as shown on page)
- blogs.windows.com/windowsexperience/2025/05/19/securing-the-model-context-protocol-… — 2025-05-19
- blogs.windows.com/windowsexperience/2025/10/16/securing-ai-agents-on-windows/ — 2025-10-16
- blogs.windows.com/windows-insider/2025/11/17/copilot-on-windows-copilot-actions-… — 2025-11-17
- blogs.windows.com/windowsexperience/2025/11/18/ignite-2025-windows-at-the-frontier-of-work/ — 2025-11-18
- microsoft.com/en-us/security/blog/2025/11/18/ambient-and-autonomous-security-for-the-agentic-era/ — 2025-11-18
- blogs.windows.com/windows-insider/2025/12/05/announcing-windows-11-insider-preview-build-26220-7344-… — 2025-12-05
- blogs.windows.com/windows-insider/2025/12/19/announcing-windows-11-insider-preview-build-26220-7522-… — 2025-12-19
- support.microsoft.com/en-us/windows/ai/ai-features/experimental-agentic-features — updated 2025-12-05
- learn.microsoft.com/en-us/windows/ai/mcp/overview — ms.date 2025-12-06
- learn.microsoft.com/en-us/windows/ai/mcp/servers/mcp-containment — ms.date 2025-11-11
- learn.microsoft.com/en-us/windows/ai/agent-launchers/ — ms.date 2025-01-05 (updated 2025-12-12)
- learn.microsoft.com/en-us/windows/client-management/mdm/policy-csp-windowsai — ms.date 2026-06-22
- learn.microsoft.com/en-us/windows/release-health/windows11-release-information — ms.date 2026-09-14
- blogs.windows.com/windows-insider/2026/04/17/releasing-windows-11-builds-26100-8313-and-26200-8313-… — 2026-04-17
- blogs.windows.com/windows-insider/2026/08/27/releasing-windows-11-version-26h2-to-the-release-preview-channel/ — 2026-08-27
- blogs.windows.com/windowsdeveloper/2026/06/02/windows-platform-security-for-ai-agents/ — 2026-06-02
- blogs.windows.com/windowsdeveloper/2026/06/02/build-2026-furthering-windows-as-the-trusted-platform-for-development/ — 2026-06-02
- microsoft.com/en-us/security/blog/2026/06/02/microsoft-build-2026-securing-code-agents-and-models-… — 2026-06-02
- microsoft.com/en-us/security/blog/2026/05/01/microsoft-agent-365-now-generally-available-… — 2026-05-01
- microsoft.com/en-us/security/blog/2026/03/20/secure-agentic-ai-end-to-end/ — 2026-03-20
- techcommunity.microsoft.com/discussions/agent-365-discussions/agent-365-will-be-generally-available-on-may-1-2026/4500380 — 2026-03-09
- learn.microsoft.com/en-us/entra/agent-id/whats-new-agent-id — ms.date 2026-05-01
- learn.microsoft.com/en-us/defender-endpoint/whats-new-in-microsoft-defender-endpoint — ms.date 2026-06-22
- learn.microsoft.com/en-us/defender-endpoint/local-agent-discovery-overview — ms.date 2026-05-27
- learn.microsoft.com/en-us/defender-endpoint/ai-agent-runtime-protection-overview — ms.date 2026-09-16
- learn.microsoft.com/en-us/defender-endpoint/configure-ai-agent-runtime-protection — ms.date 2026-09-16
- learn.microsoft.com/en-us/defender-xdr/whats-new — ms.date 2026-09-08
- learn.microsoft.com/en-us/defender-xdr/security-for-ai/defender-security-for-ai — ms.date 2026-08-07
- learn.microsoft.com/en-us/purview/ai-microsoft-purview — ms.date 2026-05-27
- registry.npmjs.org/@microsoft/mxc-sdk; api.github.com/repos/microsoft/mxc — 2026-09-17
- sentinelone.com/press (2026-03-23; Prompt Security 2025-08-05); sdxcentral.com (CrowdStrike 2026-03-24); siliconangle.com (Zscaler 2026-06-09; Cato/Aim 2025-09-03); newsroom.cisco.com (2026-03-23); paloaltonetworks.com/blog (AIRS 3.0 2026-03-23); businesswire.com (Zenity 2026-08-03); prnewswire.com (Noma 2025-07-31); snyk.io/news (2025-06-24); runlayer.com/blog (2026-06-24); hiddenlayer.com/news (2026-09-02); straiker.ai/blog (2026-06-29); lasso.security (2026-09-02); f5.com (CalypsoAI 2025-09-11); anaconda.com/press (Enkrypt 2026-08-04); proofpoint.com (Acuvity 2026-02-12); cyberscoop.com (Lakera 2025-10-01); obot.ai/blog (2025-09-23); blog.cloudflare.com (2025-08-26); 1password.com/press (2025-10-08; 2026-03-17); endorlabs.com/learn (2026-05-12); globenewswire.com (Solo.io 2026-09-03, 2026-09-10)
- genai.owasp.org/resource/agent-control-standard-acs/ — 2026-09-01; labs.zenity.io/post/the-agent-control-standard-lands-at-owasp — 2026-09-10; api.github.com/repos/GenAI-Security-Project/agent-control-standard
- arxiv.org/abs/2607.13716 (CAVA) — 2026-07-15; api.github.com/repos/OndCo/CAVA
- docker.com/blog/docker-mcp-gateway-secure-infrastructure-for-agentic-ai/ — 2025-07-09
- code.claude.com/docs/en/sandboxing; api.github.com/repos/anthropic-experimental/sandbox-runtime
- learn.chatgpt.com/docs/windows/windows-sandbox (Codex); winbuzzer.com/2026/05/14/…codex… — 2026-05-14
- docs.github.com/en/copilot/concepts/agents/copilot-cli/understanding-local-sandboxing
- api.github.com/repos/… for: safing/portmaster, docker/mcp-gateway, stacklok/toolhive, agentgateway/agentgateway, invariantlabs-ai/mcp-scan (→ snyk/agent-scan), eqtylab/mcp-guardian, NVIDIA/NeMo-Guardrails, guardrails-ai/guardrails, lasso-security/mcp-gateway, luckyPipewrench/pipelock, obot-platform/obot, pomerium/pomerium, peg/rampart (+README), dredozubov/hazmat, golf-mcp/golf-scanner, newtro/ClawGuard, CoChatAI/openclaw-carapace, ContextFort-AI/Runtime-Controls — all read 2026-09-17
- huggingface.co/meta-llama/Llama-Guard-4-12B; trollbridge.dev; pipelab.org/about/; hn.algolia.com API queries — 2026-09-17

Could not find / did not verify: a Release Preview post for build 7344; any Microsoft consumer-Defender or Windows Security roadmap for agent runtime protection; Windows edition gating of the Agents settings page; the "Agent Hooks contract (MIT)" repo; Solo.io agentdesktop's repo; Pomerium funding; whether HiddenLayer/Straiker/Zscaler ship Windows endpoint components; Ignite 2026 previews; Microsoft job postings. WebSearch budget ran out mid-task; later lookups used direct URLs, GitHub/npm APIs, HN Algolia and Brave (rate-limited).
