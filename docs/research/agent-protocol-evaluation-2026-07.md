# Agent-Protocol Evaluation — Agent Client Protocol (Zed) vs. Agent Communication Protocol (IBM) / A2A

*Status: **APPROVED** — the Lead Architect accepted all three dispositions on 2026-07-07 ("I love your proposal! I accept it!"). Authored 2026-07-07 by a Claude research session (four parallel sub-agents: two web-research, two repo-grounding); approved the same evening. Execution ticket: **Vikunja #759** (ACP driver spike, project 4). Builder brief: `agentic-setup/docs/fleet-builder-brief-acp-driver-spike.md`.*

*Post-approval verification (2026-07-07 evening, on this machine): the §6.1 "after F1/F3" sequencing precondition is already **MET** — F1 (`agentic-setup/configs/opencode-plugins/path-normalize.js`, shipped 2026-06-30) and F3 (`Add-WebHint`, `fleet-lib.ps1:576-597`) are on agentic-setup main; the installed opencode **1.17.8** natively ships an `opencode acp` subcommand; and the Python SDK `agent-client-protocol` **0.11.0** installs and imports cleanly on Python 3.14. The spike is immediately actionable in a free machine window (no battery/dispatch occupying the GPU).*

---

## 1. Verdict summary

Two unrelated protocols share the acronym "ACP." They must never be conflated; they answer different questions, and one of them no longer exists as an independent standard.

| Protocol | What it connects | Status (2026-07-07) | Verdict for us |
|---|---|---|---|
| **Agent Client Protocol** (Zed Industries + JetBrains) | A **harness/editor** ↔ a **coding agent** running as a local subprocess (JSON-RPC over stdio) | Active and healthy: protocol v1 stable, releases as recent as 2026-07-06, co-governed by Zed + JetBrains, ~25+ agents adopted | **One genuine, scoped opportunity** — at the fleet↔opencode seam. **[APPROVED 2026-07-07 → Vikunja #759]** bounded spike; the F1/F3 precondition was verified already met. |
| **Agent Communication Protocol** (IBM Research / BeeAI) | **Agent ↔ agent** over REST/HTTP across vendors and organizations | **Defunct.** Merged into A2A under the Linux Foundation 2025-08-29; GitHub repo archived 2025-08-27; SDK deprecated; adopters told to migrate to A2A | **Do not adopt — it is a dead standard.** Evaluating it today means evaluating A2A. |
| **A2A (Agent2Agent)** — the successor that absorbed IBM's ACP | Agent ↔ agent federation over HTTP (Agent Cards, task lifecycle, OAuth/mTLS, webhooks) | Active: spec v1.0 (v1.0.0 2026-03-12, v1.0.1 2026-05-28), Linux Foundation, 150+ orgs, shipping in Microsoft/AWS/Google clouds | **Watch, don't adopt.** **[APPROVED 2026-07-07]** It solves cross-organization federation — a problem BlarAI deliberately does not have. Two concrete revisit triggers named in §6.2. |

**One-paragraph answer to the headline question:** neither protocol "greatly matures" the system today, and one of them (Agent Communication Protocol) would actively be a mistake to adopt because it was absorbed into A2A eleven months ago. But the research surfaced one high-quality, well-fitted opportunity: the coding fleet's most fragile machinery — per-turn subprocess spawns of opencode plus log-file-regex and file-mtime heuristics to infer progress and detect stalls — is exactly the bespoke layer the Agent Client Protocol standardizes, and **opencode (our coding agent) already ships native Agent Client Protocol support**. A bounded spike there is the prudent move. Everything else — the runtime's named pipe, the mTLS loopback gateway, the AF_HYPERV vsock guest boundary, the file-mediated dispatch hand-off — is bespoke *on purpose*, as a security control, and should stay that way.

---

## 2. The two ACPs, disambiguated (plus the adjacent landscape)

| Name | Origin | Layer | One-line description |
|---|---|---|---|
| **Agent Client Protocol** ("ACP", Zed) | Zed Industries, announced 2025-08-27; now co-governed with JetBrains under the neutral `agentclientprotocol` GitHub org | Harness/editor ↔ coding agent | "LSP for coding agents": a client launches an agent as a subprocess and speaks JSON-RPC 2.0 over stdin/stdout — sessions, prompts, a typed event stream, permission requests, file-system proxying, terminals. Apache-2.0. |
| **Agent Communication Protocol** ("ACP", IBM/BeeAI) | IBM Research, March 2025; donated to Linux Foundation; **merged into A2A August 2025** | Agent ↔ agent (networked) | REST-native agent interop (`GET /agents`, `POST /runs`, sync/stream/async runs, await/interrupt, MIME-multipart messages, offline discovery). Lived ~5 months. |
| **A2A (Agent2Agent)** | Google, April 2025; Linux Foundation project | Agent ↔ agent (networked, cross-org) | Opaque agents discover each other via Agent Cards (`/.well-known/agent-card.json`), exchange Messages/Artifacts through an 8-state task lifecycle over JSON-RPC/gRPC/REST, secured with OAuth2/OIDC/mTLS, with SSE streaming and webhook push. |
| **MCP (Model Context Protocol)** | Anthropic, Nov 2024 | Agent/model ↔ **tools** | The de-facto tool-connectivity standard. Already our chosen tool protocol on the dev side (ADR-022, Vikunja MCP). Complementary to both ACPs, not a competitor. |

The canonical layering, per the A2A project's own docs: an agent uses **MCP inward** (to reach tools and data) and **A2A outward** (to collaborate with other agents it doesn't trust or see inside). The Agent Client Protocol sits at a third, narrower place: between a *local harness* and a *local coding agent process* — "MCP gives an agent tools; ACP gives the agent an editor."

Name-collision hygiene note: "ACP" also denotes AGNTCY's Agent Connect Protocol and an unrelated Agentic Commerce Protocol. Any future BlarAI doc referencing these protocols should use the full name on first use, per this document's convention.

---

## 3. State of play, from primary sources (as of 2026-07-07)

### 3.1 Agent Client Protocol (Zed) — active and maturing

- **Design.** JSON-RPC 2.0 over stdio; the client spawns the agent as a subprocess. `initialize` negotiates an integer protocol version (currently **1**) plus capabilities. Sessions: `session/new`, `session/load`, `session/resume`, `session/list`, `session/close`, `session/prompt`, `session/cancel`, `session/set_mode`. The agent streams typed **`session/update` notifications**: `agent_message_chunk`, `agent_thought_chunk`, **`tool_call` / `tool_call_update`** (nine kinds — read/edit/delete/move/search/execute/think/fetch/other — with pending→in_progress→completed/failed status), **`plan`** (structured task plan), `available_commands_update`, `usage_update` (token usage/cost), `session_info_update`. Every prompt turn ends with a **StopReason**: `end_turn`, `max_tokens`, `max_turn_requests`, `refusal`, or `cancelled`. Sensitive operations flow through `session/request_permission` (allow/reject, once/always). The client can proxy file access (`fs/read_text_file` / `fs/write_text_file`) and host terminals. Content types reuse MCP's JSON representations, and `session/new` can hand the agent a list of MCP servers to connect to.
- **Governance/maturity.** Apache-2.0, no CLA. Moved from `zed-industries/…` to the neutral `agentclientprotocol` org; JetBrains is a co-developer (announced 2025-10-23) and ships native support in IntelliJ-family IDEs. An **ACP Registry** (launched 2026-01-28, jointly run by Zed + JetBrains) is the discovery layer. Release cadence is fast: JSON schema at v1.19.0 and the Rust reference crate at v1.4.0 as of 2026-07-06; the crate passed its v1.0.0 stability milestone in late June 2026. A v2 schema is being drafted in the open; v1 is the production line.
- **Adopters.** Clients: Zed, JetBrains IDEs, Neovim (CodeCompanion, avante.nvim), Emacs (agent-shell), marimo. Agents: Gemini CLI (native, the launch partner), Claude Code (via the actively-maintained `@agentclientprotocol/claude-agent-acp` adapter over the Claude Agent SDK — v0.57.0 dated 2026-07-07; **no first-party Anthropic ACP mode exists**), OpenAI Codex CLI (`codex-acp`), GitHub Copilot CLI, **OpenCode (shipping — this is our coding agent)**, Cursor (native), Goose 2.0 (ACP-first as of 2026-04-08), Pi.
- **Headless/orchestrator use is a first-class pattern**, not a hack: the `acpx` CLI (v0.12.0, 2026-07-04 — alpha) exists specifically so "orchestrators can talk to coding agents over a structured protocol instead of PTY scraping," emitting an NDJSON event stream with `--approve-all` for unattended permission grants and crash recovery; the official Python SDK (`agent-client-protocol` on PyPI, ~v0.11, pre-1.0) and Kotlin SDK explicitly support building headless clients.
- **Honest limitations.** (a) **stdio-only today** — remote transports (HTTP/WebSocket) are spec'd but not implemented; the agent must be a local subprocess (which matches our topology exactly). (b) **Windows-specific stdio behavior is undocumented upstream** — a real gap for us on win32; needs empirical validation. (c) The flagship headless tooling is alpha and the Python SDK pre-1.0; v2 churn is coming. (d) The acronym collision pollutes search results.

### 3.2 Agent Communication Protocol (IBM) → A2A — the sunset and the successor

- **What it was.** IBM Research launched it in March 2025 for the BeeAI platform: REST-native (`GET /agents`, `POST /runs`), Agent Manifest discovery, three run modes (sync / SSE-streamed / async), an await/interrupt pattern, stateful sessions, MIME-typed multipart messages, and — its one genuinely distinctive idea for a system like ours — **"offline discovery"** via agent metadata embedded in distribution packages, aimed at "secure and disconnected environments."
- **What happened to it.** On **2025-08-29** the Linux Foundation's LF AI & Data blog announced *"ACP is officially merging with the A2A under the Linux Foundation umbrella"*; the ACP team is *"winding down active development."* The `i-am-bee/acp` repo was archived (read-only) on 2025-08-27; the npm SDK is deprecated; the project website now carries a banner directing everyone to A2A with a migration guide. It accumulated almost no third-party adoption in its five months of life. **Building on it in 2026 would mean building on an archived standard.**
- **A2A today.** Spec **v1.0** (v1.0.0 on 2026-03-12; patch v1.0.1 on 2026-05-28), governed by a Linux Foundation technical steering committee (Google, Microsoft, AWS, Cisco, Salesforce, ServiceNow, SAP, IBM). Three required-equivalent transports (JSON-RPC 2.0/HTTP, gRPC, REST). Discovery via signed Agent Cards at `/.well-known/agent-card.json`. An 8-state task lifecycle (`submitted`, `working`, `input-required`, `auth-required`, `completed`, `failed`, `canceled`, `rejected`), Message/Part/Artifact data model, SSE streaming, webhook push notifications, OAuth2/OIDC/mTLS security schemes. Real adoption: GA in Microsoft Copilot Studio, Azure AI Foundry, AWS Bedrock AgentCore, and enterprise deployments at SAP/Salesforce/ServiceNow; 150+ member organizations as of 2026-04-09.
- **The critique that matters for us**, from the protocol's own ecosystem: for **single-host, single-trust-domain** multi-agent systems, A2A is widely judged **overkill** — its value (well-known-URI discovery, signed cards, OAuth, webhooks) exists to let agents on *different hosts and organizations that don't trust each other* cooperate. The consistently recommended local pattern is **"agents-as-tools"**: one orchestrator invoking specialist capabilities as in-process or subprocess callables. That is, verbatim, the shape BlarAI already has. No lightweight "local profile" of A2A exists.

---

## 4. What we actually run — the communication map (grounded 2026-07-07)

Two repo-grounding agents mapped every seam in `blarai` and `agentic-setup`, with file:line evidence. The load-bearing summary:

**BlarAI runtime is deliberately a single-process, air-gapped, fail-closed monolith — not a distributed agent system.** The Policy Agent (PA) and Assistant Orchestrator (AO) are *in-process modules* sharing **one** loaded Qwen3-14B via `SharedInferencePipeline` (one `LLMPipeline`, one lock — `shared/inference/shared_pipeline.py:63,193`). The "agent-to-agent" boundaries a protocol could theoretically occupy are, seam by seam:

| # | Seam | Transport today | Why it is the way it is |
|---|---|---|---|
| 1 | WinUI app ↔ backend | Windows **named pipe** `\\.\pipe\BlarAI`, 4-byte length-prefixed JSON, JSON-RPC-like verbs (`services/ui_backend/src/protocol.py:38`) | Kernel object, **zero listening TCP ports**, local-only by construction; survives the elevated/de-elevated integrity split. |
| 2 | Gateway ↔ AO (and PA) | Loopback `127.0.0.1:5001`/`:5000` + **mTLS `CERT_REQUIRED` both directions**, length-prefixed JSON envelope, connection-per-message (`shared/ipc/vsock.py:374,657`) | Designed to survive a future host→guest split; today both ends live in one process. |
| 3 | Host ↔ Hyper-V guest (Alpine, **NIC-less**, zero-adapter-verified at start — `launcher/vm_manager.py:117`) | **AF_HYPERV vsock** (GUID-addressed), base64-chunked length-prefixed JSON parse channel (`shared/ipc/parse_channel.py`), via a Python-3.14 stdio bridge subprocess | The most security-critical boundary in the system. The guest runs **pure-Python HTML parsing only — no model runs inside the VM** (verified: `services/cleaner/guest/parser_service.py`). The #744 guest oracle executor is dormant with `transport=None` — literally no transport registered — and its planned wire is this same vsock corridor. |
| 4 | AO ↔ coder fleet (`fleet_dispatch`) | **Subprocess + files, no network**: enqueue via `add-fleet-task.ps1`, trigger via detached `run-fleet.ps1`, results via `SUMMARY.txt` + `scorecard.json` (`shared/fleet/dispatch.py:311,344`) | The 14B is **released** and the AO process **dies by design** during every run so the Qwen3-Coder-30B can have the GPU (31.323 GB ceiling). A write-ahead swap-state file + the #758 driver-alive reconcile gate exist precisely because no endpoint stays up across a job. |
| 5 | Fleet ↔ opencode.exe (the actual coding agent) | **Per-turn subprocess spawn** `opencode run --dir <worktree> -m local/<id> --format json <prompt>` (`agentic-setup/scripts/fleet-lib.ps1:130-282`); progress inferred by **regexing the JSON transcript log** (`"type":"step_finish"`, tool-write patterns, `:244-259`) | Grew organically; carries three hard-won workarounds (empty-stdin file, argv re-quoting, direct-exe spawn). |
| 6 | Fleet ↔ 30B model | **OpenAI-compatible HTTP**, already standardized: OVMS at `127.0.0.1:8000/v3`, tool-call repair proxy at `:8099/v3`, SSE streaming | This seam is *models-as-inference-endpoints*, and it already speaks the industry-standard wire for that. |
| 7 | Run monitoring / stall detection | **File-mtime polling across seven artifact families + a psutil CPU probe** (`tools/dispatch_harness/monitor.py:91-210`), plus the transcript regex above | Exists **only because there is no structured event channel from the coder** — the doom-detection heuristic infers "is the agent alive?" from filesystem side effects. |
| 8 | Egress | ONE door (`shared/security/guarded_fetch.py`; `httpx` is the sole network client in the runtime), socket-level allowlist + latching kill-switch (`egress_guard.py`), Kagi `web_search` live through it | Not an agent seam at all — vendor-API HTTP under governance. |
| 9 | Dev fleet (Claude sessions) | Vikunja tickets (local MCP), journal fragments, handoff briefs, git branches | Deliberately file-and-ticket-mediated and **human-auditable**, with LA gates. |

**Existing protocol standardization already in place:** OpenAI-compatible HTTP end-to-end on the model-serving path; SSE in the repair proxy; MCP in two narrow dev-side spots. **Zero mentions of A2A, Agent2Agent, or either ACP anywhere in either repo's code or docs** (the only hits are incidental packages inside a captured pip-environment snapshot, `requirements.2026.1.0.lock.txt` — pollution from a dispatch-generated project's environment, not dependencies of anything we run).

---

## 5. The Lead Architect's three questions, answered directly

### 5.1 "Would the Agent Communication Protocol help the fleet communicate better?"

**No — twice over.**

First, the protocol itself is gone: it merged into A2A in August 2025 and its repos are archived. Any adoption conversation is really an A2A conversation.

Second, A2A misfits both of our "fleets":

- **The dispatch coder fleet.** Its communication is file-and-subprocess-mediated *because of physics, not immaturity*: the AO process is deliberately killed mid-job so the 30B can occupy the GPU the 14B was using. A2A presumes a persistent HTTP client and server exchanging task state across a live connection; here, the client dies on purpose during every task, which is exactly why the write-ahead swap-state file and the #758 driver-alive reconcile exist. You would have to first eliminate the model swap (the tracked idle-unload/`UNLOADED`-state path, Vikunja #741) before a live session protocol at this seam is even *coherent*. And our result semantics are already **richer** than A2A's: the scorecard verdict set (`GREEN / PARKED-HONEST / STALLED / FALSE-DONE / RECOVERED`, with PLAN/BUILD/VERIFY/HARNESS attribution) distinguishes failure modes A2A's 8 generic task states cannot express. Adopting A2A here would *flatten* information, add an always-on HTTP listener inside the trust domain (the same reason serving the 14B over OVMS was rejected in the fleet brief), and solve nothing on the actual critical path.
- **The Claude dev fleet.** It coordinates through Vikunja tickets, journal fragments, handoff briefs, and git — deliberately slow, file-based, and human-auditable, because the LA's checkpoints *are the governance*. Replacing that with machine-to-machine A2A messaging would remove the audit trail the AIGP portfolio is built on. The maturation path for this fleet is the Anthropic-primitive cycle (teams, subagents, hooks), not a federation protocol.

The fleet's real, named bottleneck (per `fleet-builder-brief-coder-output-reliability.md` and the leverage assessment) is **coder capability and reliability** — Windows-path mangling in the coder's bash tool, offline-correctness of generated tests, the ~30B model's length-dependent success ceiling. That is a layer *below* any protocol; no wire format fixes it.

### 5.2 "Would it help the 14B talk to the Qwen3 VM or 30B coder models better?"

**No, under either reading of "Qwen3 VM":**

- **If you meant the Hyper-V VM:** no model runs inside the guest at all — it is a 2 GB, NIC-less Alpine VM running a pure-Python HTML parser (and, dormant, a pytest oracle executor). The host↔guest wire is AF_HYPERV vsock with fail-closed, length-prefixed, allowlisted-verb framing — deliberately the *smallest possible* attack surface on the most security-critical boundary in the system. A2A requires HTTP; putting an HTTP agent server astride the guest boundary would strictly add surface and violate the design intent. When the #744 guest oracle goes live, it should ride the existing vsock corridor, exactly as planned.
- **If you meant the Qwen3-VL-8B vision model:** it is a load-on-demand inference pipeline (in-process `VLMPipeline` on the BlarAI side; an OVMS-served model on the fleet side), not an agent. Model↔model coordination is not "agents talking" — and where a wire exists (OVMS), it already speaks the correct standard for inference: the OpenAI-compatible API.
- **14B ↔ 30B specifically:** they are **never in memory at the same time** — the 31.323 GB ceiling forces a full swap, so their "conversation" is necessarily artifact-mediated: the 14B writes grammar-constrained plan JSON, task envelopes, and acceptance oracles (#743/#691/#690); the 30B's work comes back as summaries, scorecards, and merged commits; the 14B critic then reads diffs. A protocol session cannot span a participant that is deliberately not running. The correct maturation of this hand-off is what's already underway: tighter schemas, grammar-constrained generation, and the deterministic gate — the local, richer equivalent of A2A's task/artifact model.

### 5.3 "Where are the opportunities to prudently mature by leveraging these protocols?"

One real one, one watchlist entry, and a set of deliberate non-adoptions — next section.

---

## 6. Opportunities, ranked

### 6.1 [APPROVED 2026-07-07 → Vikunja #759] P1 — Agent Client Protocol spike at the fleet↔opencode seam

**The fit.** Seams 5 and 7 in the table above are, verbatim, the boundary the Agent Client Protocol standardizes — and **opencode already ships ACP support** (it is in the ACP Registry and Zed's agent list). Today the fleet: spawns opencode once per turn with the prompt as one giant argv; works around headless stdin blocking with an empty-stdin file; infers progress by regexing a JSON transcript log; decides idle-vs-ceiling kills from those regex counts; and detects doomed runs by polling file mtimes plus CPU sampling. Under ACP, the same opencode becomes a persistent stdio subprocess speaking JSON-RPC, and the fleet gets, as protocol primitives:

- **Typed live events** (`session/update`: tool calls with status transitions, plans, message/thought chunks, token-usage updates) — replacing the transcript regex and the mtime/CPU doom heuristics with "no event for N seconds" as a *protocol-level* idle signal. This lands squarely on a standing operational lesson: *dev-cycle speed is the constraint; stop doomed runs fast.*
- **Honest terminal semantics** (StopReasons: `end_turn` vs `cancelled` vs `max_tokens`) — the same class of truth-in-labeling that #757 just hand-built for tree-killed timeouts.
- **Cooperative cancellation** (`session/cancel`) before tree-kill as first resort, and a **permission-request channel** the fleet can answer by policy (today's opencode permission config, but auditable per-call).
- **Pluggable coder backends behind one driver** — the strategic option. The named bottleneck is the 30B coder's capability; ACP makes A/B-ing alternatives (opencode vs. Goose vs. Gemini CLI vs. — dev-side, quota permitting — Claude Code via `claude-agent-acp`) a config change instead of a new integration. It also composes with MCP: `session/new` can hand the agent per-task MCP servers (the browser tool already rides MCP inside opencode).
- **A typed progress feed** the WinUI dispatch UI (#712 lineage) could render live, instead of tailing logs.

**The honest caveats.** Windows stdio behavior is undocumented upstream and must be proven empirically; opencode's ACP mode needs verification against our local-provider config (`:8099` repair proxy) on win32; the official Python SDK is pre-1.0 and the `acpx` headless client is alpha; a v2 schema is in flux (v1 negotiation protects us, but churn is real); and the current machinery *works* and embodies hard-won fixes — this is a seam migration, never a rip-and-replace.

**The proposed shape (decision-gated, bounded):** a spike that drives **one** candidate build through opencode's ACP mode on this machine — persistent session, event stream captured — and A/Bs it against the transcript-regex path on: event fidelity (does `tool_call`/`step` activity match reality?), stall detectability, Windows stdio robustness, and wall-clock overhead. Deliverable: a measured go/no-go with the integration cost estimate. **Sequencing:** after the F1/F3 coder-reliability fixes from the bottleneck brief (they are prompt/plugin-level, orthogonal, and gate everything else) — protocol work must not preempt the capability bottleneck. *(Post-approval check, 2026-07-07: F1 and F3 are both already shipped on agentic-setup main — the precondition is met and the spike is actionable now.)* If the spike is green, adoption would slot naturally into the fleet-maturation program (M2, #740) at the driver/monitor layer, most plausibly as a small Python ACP client beside `tools/dispatch_harness/monitor.py` (the Python side is where the monitoring already lives).

### 6.2 [APPROVED 2026-07-07] P2 — A2A: watchlist entry, two concrete revisit triggers

Build nothing now. Record two triggers on which this assessment should be re-run:

1. **The fleet leaves the box.** If a second machine ever runs the coder fleet (e.g., a dedicated build host), the file-queue boundary becomes a network boundary, the "client dies during the swap" constraint disappears (the 14B and the coder no longer share a GPU), and A2A's task lifecycle + push notifications become the right off-the-shelf shape for exactly the queue/summary/scorecard hand-off we already do — through the egress governance stack, with the allowlist and kill-switch unchanged in spirit.
2. **BlarAI federates with an external agent.** The air-gap-removal roadmap (#598 GO) currently ends at vendor APIs (Kagi). If it ever extends to consuming a *networked agent* (opaque peer, not a search API), A2A is the industry standard to speak at that door, and speaking it through `guarded_fetch`-style governance would be the BlarAI-shaped way to do it.

Cost of the watchlist: zero. Optional near-zero-cost alignment: when the scorecard schema next changes anyway, keep its verdicts *mappable onto* A2A task states (ours are a strict superset; a lossy projection `GREEN→completed`, `STALLED/FALSE-DONE→failed`, `PARKED-HONEST→rejected` should stay trivially writable).

### 6.3 [APPROVED 2026-07-07] Deliberate non-adoptions (the paths not taken, named)

- **No protocol at the runtime seams.** The named pipe (zero listening ports), the loopback mTLS gateway (`CERT_REQUIRED` both directions), and the AF_HYPERV vsock guest corridor are each a *security control first* and a transport second. Replacing any of them with an HTTP-based agent protocol adds listeners, dependencies, and discovery surface inside the trust domain and gains no capability. Rejected.
- **No protocol between PA and AO.** They share one process and one model by design (`SharedInferencePipeline`); an agent protocol there would re-introduce the process split the architecture deliberately collapsed. Rejected.
- **No Agent Client Protocol at the WinUI↔backend pipe.** It is the one runtime seam with an editor-client↔agent *shape*, but our pipe protocol carries governance semantics (provenance tiers, PGOV streams, ingest gates, image corridors) no standard covers, and the kernel pipe's zero-port guarantee is worth more than protocol conformance. Rejected.
- **No A2A/ACP for the Claude dev fleet.** Ticket-and-file coordination *is* the audit trail. Rejected.
- **No adoption of the Agent Communication Protocol in any form.** Archived standard. Rejected categorically.

---

## 7. Sources (primary, dated)

**Agent Client Protocol:** agentclientprotocol.com (protocol docs: initialization, prompt-turn, tool-calls, file-system, terminals, session-modes, slash-commands; fetched 2026-07-07) · github.com/agentclientprotocol/agent-client-protocol (schema-v1.19.0, 2026-07-06; Rust crate v1.4.0; 63 releases) · zed.dev/blog/bring-your-own-agent-to-zed (2025-08-27) · zed.dev/blog/acp-registry (2026-01-28) · zed.dev/docs/ai/external-agents (agent list incl. OpenCode; fetched 2026-07-07) · tessl.io JetBrains-joins-ACP (2025-10-23) · blog.jetbrains.com "not playing favorites" (2025-12) + AI Assistant ACP docs · github.com/zed-industries/claude-agent-acp (v0.57.0, 2026-07-07) · github.com/openclaw/acpx (v0.12.0, 2026-07-04) · agentclientprotocol.github.io/python-sdk (~v0.11) · goose 2.0 ACP announcement (2026-04-08) · blog.marcnuri.com ACP introduction (2025-09-10, upd. 2026-04-23; remote-transport limitation).

**Agent Communication Protocol / A2A:** lfaidata.foundation "ACP Joins Forces with A2A" (2025-08-29) · github.com/i-am-bee/acp (archived 2025-08-27) · agentcommunicationprotocol.dev (merge banner; fetched 2026-07-07) · a2a-protocol.org spec v1.0 + "What's New in v1.0" (fetched 2026-07-07) · github.com/a2aproject/A2A releases (v0.3.0 2025-07-30; v1.0.0 2026-03-12; v1.0.1 2026-05-28) · linuxfoundation.org "A2A Surpasses 150 Organizations" (2026-04-09) · Microsoft Copilot Studio / Azure AI Foundry A2A docs (2025-05 → Build 2026) · MCP-vs-A2A layering analyses (TrueFoundry, OneReach, Merge.dev, 2026).

**Internal grounding (file:line evidence throughout §4–§6):** `blarai` — `shared/ipc/{protocol,vsock,parse_channel,oracle_channel}.py`, `services/ui_backend/src/{protocol,server,dispatcher}.py`, `services/ui_gateway/src/{transport,dispatch_coordinator}.py`, `shared/inference/{shared_pipeline,vlm}.py`, `services/policy_agent/src/{adjudicator,gpu_inference}.py`, `services/assistant_orchestrator/src/{entrypoint,tools}.py`, `shared/security/{guarded_fetch,egress_guard}.py`, `shared/fleet/{dispatch,swap_driver,swap_ops,swap_state,guest_oracle,acceptance,critique,plan_graph}.py`, `tools/dispatch_harness/{monitor,config,harness}.py`, `launcher/{vm_manager,guest_parser_invoker}.py`, `services/cleaner/guest/parser_service.py` · `agentic-setup` — `scripts/{fleet-lib,run-fleet,new-agent-task,start-llm}.ps1`, `tools/qwen-proxy.py`, `configs/opencode.json`, `docs/{blarai-headless-coding-agent-brief,fleet-builder-brief-coder-output-reliability}.md` · `blarai/docs/research/{dispatch-capability-and-leverage-assessment-2026-06,fleet-maturation-program-plan-2026-07}.md` · `blarai/docs/handoffs/{695-concurrent-execution-handoff-brief,critical-loops-handoff-brief}.md`.
