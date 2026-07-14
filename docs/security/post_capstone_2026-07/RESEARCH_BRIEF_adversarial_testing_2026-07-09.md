# Research Brief — Adversarial Testing & Agentic Containment (external state-of-practice)

**Gathered:** 2026-07-09 (overnight, by a research specialist subagent) · **For:** #787 Phase 0.
**Status:** external evidence base. The verification flags at the end are load-bearing — read them
before citing any single number or document ID in a governance artifact.

> This is the raw evidence file. The operator-facing decision doc built on it is
> `POST_CAPSTONE_SECURITY_OPTIONS.md` in this directory.

---

## Bottom line up front
1. The frameworks have caught up to exactly BlarAI's shape. OWASP published a *separate* Top 10 for
   **Agentic** Applications (Dec 2025) because agent risks are not LLM risks. Three of its ten —
   **ASI05 Unexpected Code Execution**, **ASI06 Memory & Context Poisoning**, **ASI02 Tool Misuse** —
   name BlarAI's three newest surfaces directly.
2. **The coder fleet is the surface that matters.** An air-gapped *model* is not an air-gapped
   *system* when that model writes code a shell then runs at the operator's own privilege. The egress
   guard adjudicates what the **model** asks for; it does not adjudicate what `node`, `uv`, or `git`
   do once spawned. Those processes use the OS network stack. **Verified against BlarAI disk state
   2026-07-09: the egress guard exists only in the BlarAI runtime; the agentic-setup dispatch fleet
   has zero references to it.**
3. Native Windows is the weakest platform for this. Anthropic's own Claude Code sandbox does not run
   on native Windows at all — it needs macOS Seatbelt, Linux bubblewrap, or WSL2. No drop-in Windows
   equivalent exists.
4. Classifier defenses against memory poisoning are demonstrated to fail; structural ones work.
   Directly load-bearing for the incoming preference-memory tier (#770).

---

## 1. Taxonomy for a novice
Structural reference: **NIST SP 800-115** (review → scanning → validation).

| Activity | What it finds | Cost | When appropriate |
|---|---|---|---|
| Vulnerability scanning | Known CVEs, misconfig | Hours | Continuously; hygiene floor |
| Penetration test | Exploitable vulns, breadth-first; validates real; business-logic flaws | Days–weeks (human) | After build, before trust |
| Red-team engagement | Whether a *specific objective* is achievable; depth-first, stealthy, defenders unaware | Weeks; most expensive | Only once detection/response exists to test |
| Purple team | Whether defensive controls actually *emit signals* to detect an attack | Days | Have controls, no proof they fire |
| AI / adversarial red teaming | Model+system behavior under adversarial input | Days–weeks, manual | Any system where model output drives actions |
| Automated adversarial eval | Regression: does a fixed weakness stay fixed? | Hours to build | Immediately after any finding |

A red team is **not** a better pen test. Pen test asks "what is broken?"; red team asks "can defenders
stop me?" A system that's never had a pen test has nothing to red-team.

**Single-operator local system:** a red-team engagement is the wrong instrument (no defenders to
surprise). The missing middle rung is a **pen test of the live system + AI red teaming of the agentic
surfaces**, every finding converted into an automated eval so it's a permanent regression lock. The
purple-team question ("does the Policy Agent actually log and refuse when attacked?") is answerable in
a day and is likely highest value per hour.

## 2. AI/LLM-specific frameworks
**OWASP Top 10 LLM Apps 2025 v2.0:** LLM01 Prompt Injection · LLM02 Sensitive Info Disclosure ·
LLM03 Supply Chain · LLM04 Data & Model Poisoning · LLM05 Improper Output Handling · LLM06 Excessive
Agency · LLM07 System Prompt Leakage · LLM08 Vector/Embedding Weaknesses · LLM09 Misinformation ·
LLM10 Unbounded Consumption.

**OWASP Agentic (ASI) — two distinct artifacts, often conflated:**
- *Threats & Mitigations v1.0* (17 Feb 2025) — **T1–T15**: T1 Memory Poisoning, T2 Tool Misuse,
  T3 Privilege Compromise, T4 Resource Overload, T5 Cascading Hallucination, T6 Intent Breaking,
  T7 Misaligned/Deceptive Behaviors, T8 Repudiation, T9 Identity Spoofing, T10 Overwhelming HITL,
  T11 Unexpected RCE, T12 Agent Comm Poisoning, T13 Rogue Agents, T14 Human Attacks on MAS,
  T15 Human Manipulation.
- *Top 10 for Agentic Applications 2026* (9 Dec 2025) — **ASI01–ASI10**: ASI01 Agent Goal Hijack ·
  ASI02 Tool Misuse & Exploitation · ASI03 Agent Identity & Privilege Abuse · ASI04 Agentic Supply
  Chain · ASI05 Unexpected Code Execution · ASI06 Memory & Context Poisoning · ASI07 Insecure
  Inter-Agent Comms · ASI08 Cascading Agent Failures · ASI09 Human-Agent Trust Exploitation ·
  ASI10 Rogue Agents. **(Confirm exact titles against the OWASP PDF before citing — see flags.)**

**NIST:** AI RMF 1.0 (Govern/Map/Measure/Manage); Generative AI Profile AI 600-1 (Jul 2024);
AI 100-2e2025 adversarial-ML taxonomy (24 Mar 2025, extended to LLM/RAG/agents). **MITRE ATLAS** —
attacker's-eye technique KB; 2025 added RAG poisoning + agent techniques (w/ Zenity Labs, Oct 2025).

**Single-operator:** ASI05 / ASI06 / ASI02 map one-to-one onto the coder fleet, preference memory,
and tool dispatch. LLM01/LLM06 remain the right frame for the Policy Agent. NIST = reporting
vocabulary (portfolio); ATLAS = test-case vocabulary.

## 3. LLM-written code executed locally (the core surface)
Claude Code's documented sandbox is the reference: writes confined to working dir + temp; default-deny
network allowlist via an out-of-sandbox proxy; **explicit credential-file denial** (`~/.ssh`, `~/.aws`,
tokens) *because the default read policy still allows reading them*. Mechanisms: Seatbelt / bubblewrap /
WSL2 — **native Windows unsupported**. Anthropic's own caveats: the proxy doesn't inspect TLS (broad
allowlist entries abusable via domain fronting); "not a complete isolation boundary."

**Realistic threat — Willison's "lethal trifecta"** (16 Jun 2025): an agent becomes an exfiltration
pipe the moment it has (1) private-data access + (2) untrusted-content exposure + (3) external
communication. Any two is safe.

**Documented incidents:**
- **s1ngularity / Nx (26 Aug 2025)** — attackers compromised the `nx` npm package; its postinstall
  script **invoked the developer's installed AI CLIs (Claude Code, Gemini, Amazon Q) as the recon
  engine** to hunt credentials, exfiltrating to attacker repos in victims' own GitHub. ~190 orgs,
  ~3,000 repos (Wiz). First documented weaponization of AI coding agents by a supply-chain compromise.
- **Supabase MCP / Cursor (Jul 2025)** — agent with a `service_role` key read a support-ticket whose
  text contained instructions; SELECTed a private tokens table, INSERTed it into a customer-visible
  thread. Textbook trifecta.
- **EchoLeak CVE-2025-32711** (M365 Copilot, Jun 2025) — zero-click exfil via one email.

**Structural defenses:** CaMeL (arXiv:2503.18813) — extract control+data flow from the *trusted*
query so untrusted data can't influence program flow (a reference monitor for tool calls);
arXiv:2506.08837 generalizes to six patterns. Both concede: general-purpose agents cannot currently
offer reliable safety guarantees; the productive question is what *constrained* agents still do useful
work.

**Single-operator (the #1 finding):** BlarAI's egress guard controls the **model's tool calls**, not
the **processes those calls spawn**. `npm install` in a worktree reaches the internet via the Windows
network stack, not BlarAI's adjudicator. s1ngularity is the exact shape. The coder fleet completes the
trifecta by itself: reads the operator's repos (private data) + ingests task text & third-party deps
(untrusted content) + subprocesses have unrestricted network.

## 4. Windows containment options

| Option | Contains | Does NOT | Setup | Toolchain damage |
|---|---|---|---|---|
| Restricted local user | File ACLs; distinct SID | Weak boundary; target user's own files stay read/writable; no network confinement | Low | Low (reinstall/PATH-share; GPU ok) |
| Job Objects | CPU/mem/wall-clock/proc-count; kills tree | **Not a security boundary** (MS: resource mgmt). No FS/network confinement | Low | None (but no containment) |
| AppContainer / low-IL | Kernel object isolation, low IL | Per-capability grants; most dev tools not written for it | High | Severe (compilers, git hooks, native modules) |
| Windows Sandbox | Hypervisor-isolated kernel; discards state | **No persistence/snapshots**; vGPU shared not passthrough | 1 click | Severe (reinstall each launch; no worktree persistence) |
| Hyper-V VM | **Real boundary: separate kernel, controllable/absent NIC, snapshot+rollback** | Escapes rare/expensive; costs RAM | Med–high | Manageable; GPU-PV fragile on Arc (coder needs no GPU if model stays host-side) |
| Container (Windows) | Process-level; Hyper-V-isolated mode stronger | Process-isolated shares host kernel | Medium | Moderate |

Clean read: **Job Objects = resource control, zero security.** A restricted user gives real ACL
separation cheapest, but no network containment and no survival against an attacker content to trash
that account's data. **A Hyper-V VM is the only option containing all three of filesystem + network +
kernel** — and BlarAI already runs a NIC-less Hyper-V Alpine guest over vsock, precisely this pattern.

**Single-operator:** highest-leverage/lowest-cost = a **restricted local user + deny-by-default
outbound firewall rule scoped to that user's SID** — breaks the trifecta at leg (3) without touching
the toolchain. Architecturally-correct = run the coder fleet inside the **existing NIC-less guest**,
model host-side over vsock. Trade-off: the guest can't reach the internet, so `npm install`/`uv sync`
must be pre-staged or proxied — a feature given s1ngularity.

## 5. Persistent-memory poisoning
**MINJA** (arXiv:2503.03704, NeurIPS 2025) — poisons an agent's memory bank using only ordinary
queries + observed outputs (no write access): bridging steps + indication prompt + progressive
shortening so the malicious record is later retrieved against a *different* victim query. ~98.2%
injection / ~76.8% attack success (reported). On defenses the 2026 literature is blunt: five of six
defense classes fail; only *tool-layer memory restriction* is structural. Perplexity filters, distilled
classifiers, LLM "memory auditors" all underperform — a well-crafted poisoned record is fluent and
semantically indistinguishable from a legit one. Certified defense (SMSR) needs **write-time HMAC
provenance + randomized ablation**; provenance-free defenses cannot certify against adaptive injection.

**You cannot classify your way out of memory poisoning. Restrict what memory can influence, or
cryptographically bind memory to its writer at write time.**

**Single-operator:** an operator-preference memory injected **verbatim into the system prompt every
turn** is the maximum-severity ASI06/T1 configuration — it grants memory system-prompt trust. Two
structural controls (neither a classifier): (a) **write-time provenance** — entries only writable
through an operator-initiated path, dropped-not-flagged on verification failure; (b) **capability
restriction** — memory-originated content marked untrusted data, unable by construction to authorize a
tool call. **BlarAI already has the vocabulary for (b): the `UNTRUSTED_KNOWLEDGE` provenance tier
(ADR-023 Am.2).** The #770 M1 review already found the write path is structurally operator-only (P8) —
this is the same instinct; Phase 3 hardens and tests it. If preference memory ever ingests anything the
*model* wrote, MINJA applies in full.

## 6. Practical adversarial testing of a single-box system
**Scaffolding, in order:** (1) full **disk image** before anything (restorable offline, not a file
backup — testing a code-executing agent *will* run destructive code); (2) test against a **clone, not
production data** (the encrypted stores + real repos are irreplaceable); (3) written **rules of
engagement** even for an audience of one (scope, tools, abort condition — the artifact that turns
"I poked at it" into portfolio evidence); (4) **network isolation** for the destructive tier
(host-only, never bridged to the home LAN).

**Safe vs destructive:** *safe against production* — injection probes vs the PA, system-prompt-leak
attempts, refusal-boundary probes, egress-guard denial *logging* verification, memory-poisoning vs a
**cloned** store. *Destructive, clone only* — anything letting the coder execute attacker-influenced
code, dependency-confusion simulation, secure-delete/key-rotation paths, anything touching sessions.db.

**Tooling (honest limits):** garak (NVIDIA — 120+ static model probes; weak on agentic/RAG),
PyRIT (MS — multi-turn orchestration framework, not a scanner; needs Python fluency),
promptfoo (YAML/CI — best as a **regression harness**, coverage shallow by design; ships lethal-trifecta
scaffolding), Burp (only for the loopback HTTP surfaces :5001 / OVMS). Converged practice:
**garak + PyRIT for discovery, promptfoo for regression.** None test "does the coder's `npm install`
reach the internet?" — that's a firewall/process-monitor question (Sysmon, per-SID Windows Firewall).

**Single-operator:** reproducibility compounds. Given BlarAI's ~5,900-test gate + 4-suite eval harness,
the correct output of an adversarial campaign is **N new gate tests, not a PDF.**

---

## Verification flags (read before citing anything narrow)
- **ASI01–ASI10 exact wording** from a secondary source (DeepTeam); Palo Alto renders ASI03/ASI04
  differently. **Confirm titles against the OWASP PDF before a governance doc cites them.**
- **MITRE ATLAS "16 tactics / 84 techniques" (v5.1.0, Nov 2025)** — vendor page; atlas.mitre.org
  didn't render. Counts approximate.
- **"NIST AI 100-5 agentic profile"** — could NOT verify it exists; the agentic RMF profile located is
  **CSA's, not NIST's.** Do not cite AI 100-5 without checking csrc.nist.gov.
- **"Sandboxed agents reduce incidents ~90%"** — vendor blog, no primary study. **Do not repeat.**
- **A "Claude Code source leak (Mar 2026)" / Oasis "Claudy Day"** — single low-quality aggregator, no
  corroboration. **Not asserted; excluded.**
- **CVE-2025-53773** (Copilot RCE via PR-description injection, CVSS 9.6) — secondary only, no primary
  advisory reached.
- **2026 memory-poisoning defense preprints** (2606.04329, 2606.12703) not peer-reviewed; their central
  claim aligns with MINJA (NeurIPS) + CaMeL, so moderate-to-high confidence. The "five of six fail"
  ratio is single-source.
- **Pen-test / red-team dollar costs** — NOT researched; the cost column is relative effort, not price.
- **Windows Sandbox nested virtualization** — could not confirm either way.

## Sources
(Full URL list preserved in the subagent transcript; primary anchors:)
NIST SP 800-115 · NIST AI 100-2e2025 · NIST AI RMF GenAI Profile (AI 600-1) · OWASP Top-10 LLM 2025 ·
OWASP Agentic Threats & Mitigations v1.0 · OWASP Top-10 Agentic 2026 · MITRE ATLAS · Claude Code
Sandboxing docs · Willison lethal-trifecta · Wiz s1ngularity · General Analysis Supabase-MCP · CaMeL
(2503.18813) · Design Patterns (2506.08837) · MS Learn (AppContainer / Job Objects / Windows Sandbox) ·
MINJA (2503.03704) · SMSR (2606.12703) · promptfoo / PyRIT / garak comparisons · SANS pen→red/purple.
