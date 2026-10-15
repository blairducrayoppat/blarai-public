---
title: BlarAI Knowledge Map batch 5 
status: living
area: research
---

# Knowledge Map batch 5: five topic cards

Drafted 2026-10-11 from `C:/Users/mrbla/BlarAI` (main). Covers the 13 entries that `docs/research/knowledge_map_unmapped.yaml` lists as unmapped. Same schema as `docs/research/KNOWLEDGE_MAP.md` section 1: (a) question; (b) current answer and status; (c) evidence table graded M (measured on this machine), S (read from source or a primary artifact), V (vendor or paper documentation only), R (reasoning); (d) layers of zoom; (e) open questions with the observable that would close each; (f) decisions made and waiting for the Lead Architect (LA); (g) tickets; (h) raw sources. Acronyms are spelled out on first use. Every path below was checked with `ls`. Where I only read part of a file, the row says so.

## Summary (10 lines)

1. Thirteen studies are not yet on the map. They sort into five topics: governing agent actions as a product idea (3 files), agent protocols and the coder's review loop (2), the machine's memory headroom (2), web-search method and the Kagi service (1), and how the record corrects and maintains itself (2 correction texts, 1 audit folder, 2 orphan asset folders).
2. The product-idea files (concept spec, feasibility brief) are inputs to a study whose answer is already recorded elsewhere: the LA said NO-GO on 2026-09-18 and the venture was cancelled (ADR-042), then reopened on a narrower claim (ADR-049) per batch 4. The concept spec's own banner mentions only the cancellation. See card M.
3. The confidentiality-axis note is a design that deliberately contains no design. It says a label-based confidentiality control makes web search unrunnable because BlarAI has one model that reads everything, and it names the one question that decides whether such a control is possible at all. See card M.
4. Agent protocols: the 2026-07-07 evaluation approved one narrow spike (Agent Client Protocol at the coder-to-opencode seam, ticket #759), put the cross-organisation protocol A2A on a watchlist with two named triggers, and rejected the dead IBM protocol and any protocol at the runtime seams. See card N.
5. The coder-loop research (2026-06-26) says: an AI reviewer's opinion is a signal, not the judge; only execution results (tests, builds) correct code reliably; keep fix loops to 2 passes (cap 3). See card N.
6. Memory: the firmware-reserved 692.8 MB cannot be recovered; about 1.5 to 3 GB of background software could be, and the LA approved a batch on 2026-07-15 (Edge preload, Copilot autostart, Game Bar capture, Intel Endurance Gaming, fixed 24 GB pagefile, three Bitdefender exceptions). The after-reboot measurement was still pending in the file. See card O.
7. Web search: the harvest compared three open research agents and Kagi's four interfaces; ADR-024 adopted "Option A" (search service plus the local 14B model for synthesis) over Kagi's hosted answer service. See card P.
8. Two correction texts (2026-10-04) withdraw recommendations and numbers from the Qwen3.5 arcs. One withdrawn recommendation, "deny whenever the schema is rejected", could have denied every tool call that has arguments. See card Q.
9. The two "Publication Program ... _files" folders each hold only a web-runtime script in git (identical bytes in both); the rendered pages are ignored by git. Recommendation: delete the folders (section "The two asset folders" at the end of card Q). Nothing was deleted.
10. Not verified by me: Vikunja ticket text (no ticket was read), whether the posted/unposted state of the correction comments changed after 2026-10-04, the outcome of the #759 spike, the post-reboot memory numbers, and the 50-plus papers cited by the coder-loop research (I read none of them).

---

## Card M. Governing agent actions: the product idea, the concept spec and the confidentiality axis

**Summary.**
1. The question: could a Windows application govern what any AI agent does on a PC, and could BlarAI label data by confidentiality so private data cannot leave in a web search?
2. The product idea was tested by the #1549 feasibility study and cancelled by the LA on 2026-09-18 (ADR-042); batch 4 records the narrower reopening (ADR-049).
3. The two input files here (concept spec, brief) are hypotheses and a question list, kept as written on purpose.
4. The confidentiality note says the obvious label design fails for architectural reasons, and it asks one question: can BlarAI produce search terms without the model seeing operator data?
5. Status: product idea decided (cancelled, then narrowed); confidentiality axis open and blocked on that one question.

### (a) The question
Two linked questions. (1) Is a "one place to say what AI agents may do on a PC" product feasible and worth building? (2) Inside BlarAI, can data carry a confidentiality label that stops private content riding out inside an allowed web search?

### (b) Current answer and status
- *Product idea: decided.* The study answered; the LA said NO-GO on 2026-09-18; ADR-042 cancels the venture and keeps the capabilities inside BlarAI (as recorded in batch 4, card I; I did not re-read ADR-042 or ADR-049 for this card beyond confirming the files exist). The concept spec's banner says "CANCELLED (ADR-042, #1590) ... not deferred, no check-back"; batch 4 records that ADR-049 reopened a narrower claim on 2026-10-05. The banner in the spec does not mention that reopening (see Corrected claims).
- *Confidentiality axis: open, no design.* The note `docs/research/confidentiality-axis-design-2026-09-17.md` says "Design only; nothing is built" and refuses to propose an implementation because its first draft was refuted by independent review the same day.
- Deciding documents: ADR-042, ADR-049, and the disposition record `docs/reviews/1546-confidentiality-axis-disposition-2026-09-17.md`.

### (c) Studies, measurements and decisions

| Date | Document path | What it found, one plain line | Grade | Confidence note |
|---|---|---|---|---|
| 2026-09-17 | `docs/research/runtime-action-governance-product-concept-spec-2026-09-17.md` | States the product hypothesis: inventory what agents can reach, one profile governs all agents, enforce where a control point exists and only observe elsewhere, keep a signed local record, ask the person rarely, send nothing out. Sixteen requirements (R1 to R13 in the brief, R14 to R16 here), eight scenarios (S1 to S8), three personas. | R | A hypothesis document by design; the header says every item is a claim the study confirms, revises or rejects. |
| 2026-09-17 | `docs/research/runtime-action-governance-product-feasibility-brief-2026-09-17.md` | The study's brief: the idea in the LA's words, what the landscape work already established, 13 product requirements, the questions Q1 to Q9 with what "answered" looks like, the list of Windows control points to probe, the evidence standard, six decisions for the LA. I read the first 120 lines and the headings; the seam inventory and method sections were not read in full. | R + S | Warns of a framing bias: the five scoring questions resemble the CAVA and PCAA papers, so those score well by construction. |
| 2026-09-17 | `docs/research/confidentiality-axis-design-2026-09-17.md` fact 1 | A confidentiality field already exists: `Sensitivity` (PUBLIC / INTERNAL / SENSITIVE / UNCLASSIFIED) is required on every Canonical Action Request in `shared/schemas/car.py`. Any future work extends it rather than inventing a parallel vocabulary. | S | The note itself adds that the rule-engine path is recorded elsewhere as unreachable in production; I did not check that. |
| 2026-09-17 | same note, fact 2 | The outbound content screen blocked an email address and an AWS key and allowed a project-budget sentence, a private medical note and an operator legal matter. | M (with controls, per the note) | The screen matches secret-shaped and personal-data-shaped spans, not ordinary private prose. I did not re-run it. |
| 2026-09-17 | same note, fact 3 | ADR-023 Amendment 4 exempts egress tools from the untrusted-content lock (`entrypoint.py:6996`, per the note), on purpose, so web search works with the knowledge bank on. | S | Line number as quoted; not re-checked by me. |
| 2026-09-17 | same note, "Why the obvious design fails" | Most-restrictive-wins labelling makes every session operator-level within a turn or two, so search (public-only) never runs. Labelling the query instead does not escape it, because the 14B model writes the query from the same context. | R | The prior art (CaMeL, FIDES) is described, not verified: CaMeL's repository was not read, FIDES is documentation-level. |

### (d) Layers of zoom
1. **Why at all.** People do not trust AI on their machine; BlarAI wants private data never to leave by accident.
2. **Two projects, one vocabulary.** The product idea reuses BlarAI's trust ideas (canonical action, approval bound to the exact action, signed receipts) for other people's PCs; the confidentiality axis is the same family of idea applied inside BlarAI.
3. **The product's shape (concept spec).** Inventory, profile, enforce-or-observe, signed record, rare questions, nothing leaves. Non-goals include judging what a model says and any cloud service.
4. **What the brief asks.** Q1 Windows control points, Q2 deep integration, Q3 universal profiles, Q3a the antivirus interaction model (the LA's direction: set up once, work in the background, interrupt only when needed), Q4 coverage screen, Q5 commercial path, Q6 open specification, Q7 what is extractable from BlarAI, Q8 go or no-go.
5. **Where the confidentiality design breaks.** One model reads everything, so a label that follows the data reaches the search query. A separate "quarantined" model that never sees private data would escape it; BlarAI has none.
6. **Smallest detail.** `entrypoint.py:6996` carries `and not tools.is_egress_tool(...)`, the one-line exemption that makes web search usable.

### (e) Open questions and the observable that closes each
- *Can BlarAI have a query-generation path that never sees operator data?* Closes when someone builds a small pass that turns the question into search terms without the grounded context and measures whether the resulting searches are good enough (the quality judgement is the LA's, per the note).
- *Does the "unreachable in production" status of the Canonical Action Request path still hold?* Closes by reading the current adjudication path (the batch 2 card A and the G1 correction text in card Q point at the same question).
- *What does the exfil screen miss now?* The note says "improving the exfil screen's coverage now that its real limits are measured" is part of the fallback; closes with a dated re-run of the same five probes plus a ticket for each gap. I found no ticket named for this in the files read.

### (f) Decisions made / waiting for the LA
- *Made:* NO-GO on the venture (2026-09-18, ADR-042); narrower reopening (ADR-049, per batch 4).
- *Waiting for the LA:* whether a context-free query pass is acceptable quality for web search. If not, the note says label-based egress control "is not available to BlarAI at all" and the work moves to keeping the egress surface narrow.

### (g) Tickets
#1546 (confidentiality axis, from the note's header), #1549 (feasibility study), #1540, #1537, #1541 to #1548 (landscape and proposed items), #1590 (cancellation record). Ticket text not read.

### (h) Raw sources
In repo: the three files above; `docs/research/runtime-action-governance-landscape-2026-09-16.md`; `docs/research/runtime-action-governance-product-feasibility-2026-09-17.md` (150,818 bytes; cited in batch 4, not read for this card); `docs/research/trust-spine-proposed-items-index.md`; `docs/reviews/1546-confidentiality-axis-disposition-2026-09-17.md`.

**Connects to existing cards:** batch 4 card I (the landscape and the venture) is the direct parent; batch 2 card A (the single adjudication door) owns the `Sensitivity` field and the exfil screen; batch 2 card B (egress, search and ceremonies) owns the web-search exemption in point 3 of the table.

---

## Card N. Agent protocols and the review loop for AI-written code

**Summary.**
1. The question: should the coder fleet or BlarAI adopt an agent-communication protocol, and what makes an AI code-and-review loop trustworthy on one model-at-a-time hardware?
2. Protocols (2026-07-07, LA-approved): one narrow spike with the Agent Client Protocol; watch A2A (Agent2Agent) with two triggers; reject IBM's protocol (merged into A2A, archived); no protocol at any runtime seam.
3. Review loop (2026-06-26, design [PROPOSED]): execution results are the judge; the 14B reviewer is a signal; 2 fix passes by default, cap 3; no debate panels.
4. Evidence is documentation and published papers (V), plus repo reading (S); nothing here was measured on this machine.
5. Status: protocols decided with a spike pending in the file; loop design proposed, build is "the next focused effort" per the file.

### (a) The question
Would an agent protocol make the coder fleet more reliable or let the models talk better, and what loop design lets a local 30B coder and a 14B reviewer produce code that can be trusted without a human reading it?

### (b) Current answer and status
- *Protocols: decided (LA, 2026-07-07, quoted in the evaluation header).* Approved: a bounded spike of the Agent Client Protocol (Zed and JetBrains) between the fleet and opencode (Vikunja #759). Watch-only: A2A. Not adopted: the IBM Agent Communication Protocol (merged into A2A 2025-08-29, repository archived). Deliberately no protocol at the named pipe, the loopback mTLS gateway, the host-to-guest virtual socket, between the Policy Agent and the Assistant Orchestrator, or for the Claude development fleet.
- *Review loop: proposed.* `docs/research/agentic-code-design-quality-loops-2026-06.md` has status "research DONE; design [PROPOSED]". Whether the build happened is in tickets #687 and #685, which I did not read.
- Outcome of the #759 spike: **not verified**. The journal anthology (`docs/BUILD_JOURNAL_ANTHOLOGY.md`) records that the spike's first recon step found both coder-fleet opencode plugins silently dead since 2026-06-30; whether the live comparison was later run I did not trace.

### (c) Studies, measurements and decisions

| Date | Document path | What it found, one plain line | Grade | Confidence note |
|---|---|---|---|---|
| 2026-07-07 | `docs/research/agent-protocol-evaluation-2026-07.md` section 1 to 2 | Two unrelated protocols share the initials ACP; one is active (Agent Client Protocol: a harness talking to a local coding agent over standard input/output), one is defunct (IBM's, absorbed into A2A). A2A is for agents in different organisations that do not trust each other. | V | Primary web sources dated 2026-07-07; the file lists them in section 7. |
| 2026-07-07 | same, section 4 | Maps nine communication seams in BlarAI and the fleet with file and line evidence (named pipe, loopback gateway with mutual TLS, virtual-socket guest corridor, subprocess-and-files for the coder, OpenAI-compatible HTTP to the 30B, file-timestamp stall detection). Zero mentions of A2A or either ACP in either repository's code or docs. | S | Line numbers as quoted, not re-checked. |
| 2026-07-07 | same, section 5 | The 14B and 30B are never in memory together (31.323 GB ceiling), so their hand-off is artifact-based; a protocol session cannot span a participant that is deliberately not running. | R | Sound reasoning from the stated memory ceiling. |
| 2026-07-07 | same, section 6.1 | The Agent Client Protocol could replace log-file pattern matching and file-timestamp polling with typed live events and stop reasons; opencode (installed 1.17.8) already ships `opencode acp`. Caveats: Windows behaviour of the standard-input transport is undocumented upstream; Python SDK pre-1.0; headless tool alpha. | V + S | Post-approval check in the file: the "after F1/F3" precondition was met; Python SDK 0.11.0 imports on Python 3.14. |
| 2026-06-26 | `docs/research/agentic-code-design-quality-loops-2026-06.md` Q1 | A model correcting itself without a new outside signal does not reliably improve and often degrades; what works for code is execution feedback (cited: +12 percent with unit-test feedback). | V (published papers) | I read none of the cited papers; numbers are as quoted in the file. |
| 2026-06-26 | same, Q2 | AI judges have measured biases (favouring their own output, position, length; a planted "verified" comment swings verdicts by 26 to 35 points as quoted). The strongest levers are a different model as judge and grounding in execution. | V | One 2026 paper is flagged single-source by the file itself. |
| 2026-06-26 | same, Q3 to Q5 | Tests written against buggy code bake the bug in; write tests from the specification without showing the code; property-based tests and mutation scoring are cheap; large best-of-N and multi-round debate do not fit one-model-at-a-time hardware. | V | Constraint-fit statements are the author's reasoning. |
| 2026-06-26 | same, Q6 | The 8B vision model is weak at perception (counting, position); use it as a signal compared against a reference render, never the gate; anchor on deterministic geometry checks. | V | Same caveat. |
| 2026-06-26 | same, "Timing and liveness" | Every long step gets two clocks: a short progress clock (no new output means hung) and a generous ceiling clock. | R | Flagged in the file as an LA-raised axis. |

### (d) Layers of zoom
1. **Why at all.** The fleet's weakest part is the coder's reliability, and its supervision is built from workarounds.
2. **Protocol landscape.** Four layers: tools (MCP), agent-to-agent across organisations (A2A), editor-to-coding-agent (Agent Client Protocol), and BlarAI's own intentionally bespoke seams.
3. **The one adoption.** Per-turn process launch plus log-file pattern matching plus file-timestamp polling would become a persistent session with typed events.
4. **Why not the others.** The coder client process is killed on purpose during every model swap; the dev fleet's ticket-and-file trail is the audit record.
5. **Loop design.** Deterministic gate first (build, tests, property tests, mutation score), then one 14B review pass as signal, then execution-grounded fixes, bounded.
6. **Smallest detail.** Scorecard verdicts (GREEN / PARKED-HONEST / STALLED / FALSE-DONE / RECOVERED) should stay mappable onto A2A task states (the file's stated near-zero-cost alignment).

### (e) Open questions and the observable that closes each
- *Does the Agent Client Protocol path work on Windows with the local-provider configuration?* Closes when the #759 spike's measured go/no-go is on file; I found no such file in the two documents read.
- *Did the review-loop design get built, and does the 14B-as-critic reduce false merges?* Closes by a measured comparison on the coder fleet's scorecard before and after; not found in the files read. Batch 3 card E owns the measurement problem.
- *Do the A2A triggers fire?* Closes if a second machine ever runs the fleet, or BlarAI is asked to consume a networked agent (the two triggers in section 6.2).

### (f) Decisions made / waiting for the LA
- *Made:* all three dispositions accepted 2026-07-07 (the file quotes the LA's acceptance). 
- *Waiting:* if the spike is green, "scope the driver integration as a follow-up LA decision" (per the anthology's "Next" line).

### (g) Tickets
#759 (spike), #687 (critical coding loop), #685 (design-loop rigor), #670 (headless dispatch), #682, #688, #757, #758, #741, #744 (as cited in the files). Ticket text not read.

### (h) Raw sources
In repo: the two files; `docs/BUILD_JOURNAL_ANTHOLOGY.md` (the #759 entries); `docs/adrs/ADR-045-Coder-Containment-Account-Level-Fused-Leg-and-WFP-Egress-Block.md` (mentions #759). Outside the repo: `agentic-setup/docs/fleet-builder-brief-acp-driver-spike.md` (named in the evaluation; existence not checked).

**Connects to existing cards:** batch 3 card E (the coder fleet and the measurement problem) is the parent of the loop research; batch 3 card F (Coordinator) uses the same file-and-ticket coordination the evaluation defends; `docs/research/KNOWLEDGE_MAP.md` card on containing the coder touches the same fleet-to-opencode seam.

---

## Card O. The machine's memory headroom

**Summary.**
1. The question: where can usable memory be recovered on the 32 GB laptop without weakening security?
2. The firmware-reserved 692.8 MB is normal and cannot be changed; do not spend effort there.
3. About 1.5 to 3 GB is recoverable from background software; the LA approved a batch on 2026-07-15 and the apply log records every original value and a one-line undo.
4. The largest BlarAI-side lever, compressing the model's conversation memory (KV cache), was left to a quality-gated live flip (#899); a possible failure to give GPU memory back after unloading is tracked in #900.
5. Status: batch applied; after-reboot measurement and the two BlarAI levers were open in the files.

### (a) The question
How much of the 31.323 GB effective memory ceiling can be freed for model loads, which are the memory-scarce moments, and at what cost?

### (b) Current answer and status
- *Decided and applied (LA, 2026-07-15, in chat per the apply log):* Edge login-time preload off, Copilot autostart off, Game Bar background capture off, Intel Endurance Gaming autostart off, fixed 24,576 MB pagefile, and three Bitdefender on-access exceptions entered by the LA the same day (models, the OpenVINO cache, the `.venv`). Widgets was already off. OneDrive deliberately untouched.
- *Open:* post-reboot after-measurement, watching one Windows/Edge/Intel update cycle for re-added autostarts, the quiet-morning true-idle baseline, #899 and #900. All are unchecked boxes or "pending" in the apply log and assessment. I did not re-measure.
- *Rejected (assessment 5.3):* disabling Virtualization-Based Security (reclaims about 100 to 300 MB, removes a firmware-level root of trust).
- Current configuration check: `services/assistant_orchestrator/config/default.toml` line 37 reads `kv_cache_precision = ""` on 2026-10-11. I did not verify what the empty value means at runtime.

### (c) Studies, measurements and decisions

| Date | Document path | What it found, one plain line | Grade | Confidence note |
|---|---|---|---|---|
| 2026-07-15 | `docs/research/ram-headroom-assessment-2026-07.md` section 2 | Census: 16.31 GB in use near idle with dev sessions, 28.23 GB under build plus model load (3.10 GB available); the resident 14B holds about 9.7 GB of system memory; Edge 149 background processes, about 3.0 GB; Bitdefender about 1.0 GB. | M | Taken with a concurrent test run live for part of it; the file says a true zero-load baseline is unmeasured. Data in `docs/performance/ram_census_2026-07-15.json` (existence checked, contents not read). |
| 2026-07-15 | same, section 3 | The 692.8 MB reservation is the firmware default band; no BIOS setting, no boot-configuration cap, no surviving driver override on this machine (four checks). | M + S | The default-band figure is inferred (about 512 MB framebuffer) per the file. |
| 2026-07-15 | same, section 4 | Memory compression off and SysMain off are correct for this workload; Windows Search already narrow at 22 MB; the parser VM is off at 0 MB. | M + R | Standing rule: never run "RAM cleaner" purges. |
| 2026-07-15 | same, section 6 | KV cache costs 160 KB per token at full precision (about 1.3 GB at 8K, about 5 GB at 32K); 8-bit halves it, 4-bit about a third. This chip is reported to hold GPU memory after unloads. | V (upstream reports) | The file says the retention claim is "not yet independently verified on our hardware"; #900 is the verification. |
| 2026-07-15 | `docs/research/ram-headroom-apply-log-2026-07.md` | Before: in use 8.61 GB, available 22.71 GB, Edge 149 processes at 3,049 MB. After (same session, pre-reboot): in use 7.54 GB, available 23.78 GB, about 1.1 GB returned by stopping the running Edge tree. | M, n=1 | One before/after pair, one session; the full effect "shows from the next sign-in". |

### (d) Layers of zoom
1. **Why at all.** Model loads spike committed memory by 10 to 20 GB; failures show up as abrupt out-of-memory.
2. **Three kinds of memory.** Fixed by firmware (closed), background software (recoverable, an LA yes/no), and BlarAI's own (KV cache, eviction).
3. **The batch.** Seven apply-log items, each with its original value and a revert command.
4. **The honest boundary.** Savings per lever are researched or derived, not yet measured here; each applied lever needs its own before/after.
5. **Smallest detail.** The pagefile is 24 GB fixed because disk is tight until a new drive arrives; the commit limit becomes about 56 GB (32 GB RAM plus 24 GB).

### (e) Open questions and the observable that closes each
- *Did the batch hold after reboot?* Closes when the apply log's own unchecked items are filled: idle In-Use, Edge/Copilot process check, pagefile allocation equal to 24,576 MB, recorded in the log and `PERFORMANCE_LOG.md`.
- *Do updates re-add the autostart entries?* Closes by checking the three removal sites after the next Windows, Edge and Intel update.
- *Does eviction return memory on this chip?* Closes with #900's instrumented load-unload cycles.
- *Does 4-bit KV cache keep answer quality?* Closes with the quality-gated evaluation #899 and the earlier A/B #715 (the latter named in batch 2).

### (f) Decisions made / waiting for the LA
- *Made:* the batch above; accept Bitdefender's footprint; no change to Virtualization-Based Security.
- *Waiting:* the KV-compression live flip is a quality-gated change, which is the LA's by the quality rule; I found no recorded decision in these files.

### (g) Tickets
#897 (this study), #899 (KV cache), #900 (eviction), #564 (standing memory ticket; its "3 GB KV cache is fixed" note was annotated stale), #661 (parser VM memory). Ticket text not read.

### (h) Raw sources
In repo: the two files; `docs/performance/ram_census_2026-07-15.json`; `PERFORMANCE_LOG.md` entry of 2026-07-15 (named in the file; not read). Registry values are on the machine, not in the repo.

**Connects to existing cards:** batch 2 card C (inference and performance on the Arc and NPU) and card D (memory, ingestion and storage); batch 4 card L (host environment and operations) for the Bitdefender and pagefile facts; batch 4 card J (the models) because the Qwen3.5 9B "uses 3.1 GB less memory" than the 14B (stated in the HF correction text, card Q).

---

## Card P. Web search: method and the Kagi service

**Summary.**
1. The question: how should BlarAI search the web with a local 14B model, and which Kagi interface should it use?
2. Three open research agents were read; their shared eight-step loop is the template; BlarAI chose model-judged "gaps" with a hard cap of 2 passes.
3. Kagi has four interfaces; the Search interface at $12 per 1,000 queries plus local synthesis was adopted (ADR-024 "Option A") over Kagi's hosted answer service at $15 per 1,000.
4. Privacy is the deciding reason: with Option A only search terms leave the device; with the hosted answer service the thinking happens on Kagi's servers.
5. Status: decided and ADR-024 is accepted; live status of the search scope is read from config and runbooks, not from this card.

### (a) The question
What loop and which paid interface give BlarAI useful web answers without moving its reasoning off the device?

### (b) Current answer and status
Decided. `docs/adrs/ADR-024-Agentic-Web-Search-Skill.md` status line: ACCEPTED, "Option A adopted; W1 to W3 implemented and merged; W4 to W5 remain security-gated" as of 2026-06-05. That status line is a 2026-06 snapshot. Whether search is live today must be read from `services/assistant_orchestrator/config/default.toml` and `docs/runbooks/` (CLAUDE.md rule), which I did not do for this card; batch 2 card B owns it.

### (c) Studies, measurements and decisions

| Date | Document path | What it found, one plain line | Grade | Confidence note |
|---|---|---|---|---|
| 2026-06-04 | `docs/research/websearch_method_harvest.md` Part 1 | Local Deep Research, GPT-Researcher and Open Deep Research share one eight-step loop (decompose, search, triage, extract, accumulate, gap analysis, follow-up, synthesise); they differ at the stop rule. BlarAI's choice: model-judged gaps, capped at 2 passes. | S/V | The projects are described from their public material; I read headings and about the first 120 lines of Part 1, not all of it. |
| 2026-06-04 | same, Part 2.1 | Kagi Search $12 per 1,000 queries; Universal Summarizer $0.030 per 1,000 tokens (about $0.20 for a 5,000-word page) or $1.00 per summary on the enterprise engine; FastGPT $0.015 per query with about 8 s latency in Kagi's own example; Teclis and TinyGem enrichment $0.002 per query, non-commercial use only. | V | Prices as of 2026-06; not re-checked. |
| 2026-06-04 | same, Part 2.2 to 2.4 | Cost per answer about $0.85 with the Summarizer or about $0.05 without (Option A) versus about $0.015 (Option B); latency 10 to 20 s versus about 8 s; privacy: Option A sends search strings and chosen URLs only. | V + R | Estimates, not measured. |

### (d) Layers of zoom
1. **Why at all.** A local model without current information is limited; search is the first egress door.
2. **The loop.** Decompose, search, extract, check gaps, synthesise.
3. **The two options.** A: Kagi Search plus local synthesis. B: Kagi's FastGPT does all of it remotely.
4. **Why A.** The 14B stays the brain; the loop is controllable; only search terms leave.
5. **Smallest detail.** Teclis and TinyGem are "non-commercial use only" in the file; BlarAI is personal use, so allowed, but any commercial deployment would need a re-check.

### (e) Open questions and the observable that closes each
- *Does the shipped loop match the harvest's "2 passes with model-judged gaps"?* Closes by reading the web-search code and its tests; not done here.
- *Did measured cost and latency match the estimates?* Closes with a dated measurement in `PERFORMANCE_LOG.md`; none found by me in the files read.
- *Do the query strings leak operator data?* This is card M's open question: the 14B writes the search terms from its full context.

### (f) Decisions made / waiting for the LA
Made: Option A (the file points to the ADR; the ADR text calls it the LA's first decision gate; I did not read the LA's recorded answer). Going live is a per-scope ceremony (batch 2 card B).

### (g) Tickets
#572 (web-search skill, W1 to W5), #598 (air-gap removal GO). Ticket text not read.

### (h) Raw sources
In repo: the harvest; `docs/adrs/ADR-024-Agentic-Web-Search-Skill.md`; `docs/security/SECURITY_ROADMAP_air_gap_removal.md`.

**Connects to existing cards:** batch 2 card B (egress, search and the ceremonies) is the parent; card M above (the query-leak question); batch 4 card K (upstream and community) because the harvest's source projects are public open-source projects.

---

## Card Q. How the record corrects and maintains itself

**Summary.**
1. The question: how are wrong published claims retracted, and how was the documentation system itself audited and restructured?
2. Two correction texts (2026-10-04) withdraw a recommendation, reword two claims and recompute several numbers from the Qwen3.5 arcs, for a ticket and a public Hugging Face dataset card.
3. The July 2026 audit pack measured what loads into every session and found frozen documents with retired owners; it fed decisions D1 to D10 (DEC-11).
4. Two orphan asset folders hold only a web-runtime script in git.
5. Status: corrections drafted, with part posted (file states which); audit executed; asset folders await a delete-or-map decision.

### (a) The question
When a measurement or recommendation turns out wrong, where is it corrected, and what keeps the repository's own instructions and logs from silently going stale?

### (b) Current answer and status
- *Corrections:* the rule is correct in place, keep the wrong version visible (user memory `feedback_replace_wrong_statements_in_docs.md` and ADR-047 per batch 3). The two texts follow it. State as written in `docs/research/g1-vikunja-correction-text-2026-10-04.md`: posted are #1673 comment c3865, #1665 comments c3866 and c3868, new ticket #1674; **not yet posted** at the time of the file: the follow-up for the strict-gate range (H1), the recomputed population (H2) and the qualifier (H7). Whether it was posted since I did not check. `docs/research/hf-root-card-correction-2026-10-04.md` says "Nothing here has been uploaded" at drafting time; the live card state was not checked.
- *Documentation audit:* executed. `docs/DECISION_REGISTER.md` row DEC-11 records archive-first documentation infrastructure (monthly rotation, LESSONS three-tier, the 64-gem anthology, rewritten sprint surfaces). The audit folder README says it was evidence only and the restructure waited for LA triage of D1 to D10.

### (c) Studies, measurements and decisions

| Date | Document path | What it found, one plain line | Grade | Confidence note |
|---|---|---|---|---|
| 2026-10-04 | `docs/research/g1-vikunja-correction-text-2026-10-04.md` | Withdraws "deny whenever the schema is rejected" (#1673): every Assistant Orchestrator tool call with arguments puts them under the key `args`, which the validator rejects (run: `(False, 'Disallowed schema key: args')`); the URL door's `purpose` and `method` are rejected too; so such a rule could deny all of them. | S + reproduced | Static reading; a runtime trace is the new ticket #1674. The file labels each fact static, reproduced or not established. |
| 2026-10-04 | same | No production path was found that sends a request to the model-backed classifier; the tool loop and URL door call the rule checker in process. | S (grep) | "A search, not a trace", per the file. |
| 2026-10-04 | same | Reworded: "byte-identical across 3 runs" means parsed label and confidence identical in 3 of 3 runs; raw text compared for one run only. | S | The comparison hashed `label|confidence|error`. |
| 2026-10-04 | same | Cold-gate sensitivity: 38 of 154 kept cold rows (24.7 percent) started at 72.9 to 81.9 C (7 above 76.9); the headline 9B-over-14B ratios move from 1.715/1.164/1.076 to 1.718/1.164/1.077. | M (recomputed from raw rows) | Round-3 review corrected the earlier range 72.9 to 76.9. |
| 2026-10-04 | same (Jev numbers) | The ideation note's counts were recomputed: 104 answers, 103 at confidence 0.95; the informative population is 6 rows (variants V0, V1, V4 on two cases), all ALLOW against the golden DENY, top probability 0.3999 to 0.7119. | M | Valid only on a prompt that does not show the command; #1672 matters only if the model path is live. |
| 2026-10-04 | `docs/research/hf-root-card-correction-2026-10-04.md` | "Byte-identical output on every check" for the 4B with MTP is replaced by: outputs differed in 1 of 377 calls (9B: 2 of 366). The 4B's two policy misses are not dangerous actions let through: the command field was rejected so no model saw the command. | M | Drafted for the lead to merge; strike-through form used. |
| 2026-10-04 | same | New "Study 4" text for the 9B: MTP gives 2.17 to 2.58 times decode speed; 3.1 GB less memory than the 14B; but 2.65 times the first-token wait at turn 6, because MTP needs prefix caching off. | M | Conditions and limits are in the dataset README (`docs/performance/qwen35_small_9b_2026-10-04`, existence checked). |
| 2026-07-18 | `docs/research/doc-infrastructure-audit-2026-07/README.md` | Evidence pack: about 14.5K tokens auto-inject into every session and subagent (CLAUDE.md about 9.6K plus memory index about 4.9K; about 11M lifetime tokens across 771 transcripts); the sprint file was force-read each session with about 80 percent of its active claims false; three always-on files held three different gate counts. | M (measured from transcripts, per the README) | I read the README fully; the other 16 files in the folder only by name and size. |
| 2026-07-18 | same | Root cause: every frozen doctrine file names a retired role as its maintenance owner; healthy ones have a living owner. A freshness check must enforce what vigilance cannot. | R + M | Fed D8. |
| 2026-07-18 | same | Journal mining of 465 entries (62 keep-hot gems, six cross-era threads) and a 284-lesson disposition; the LESSONS tiering cuts the mandatory pre-mint search to at most 7K tokens (minus 91 percent). | M/R | Numbers as stated in the README. |

### (d) Layers of zoom
1. **Why at all.** A public dataset card and the tickets are read by people who act on them; a wrong sentence there outlives the session.
2. **A correction has parts.** What is withdrawn, the evidence label for each fact, the replacement text, and where it must be posted.
3. **The G1 finding.** The evaluation prompt differs from what live requests carry; a result true of the first is not shown to be true of the second.
4. **The audit.** Costs measured first (what loads, what is read), then per-file staleness verdicts, then ten decisions.
5. **Smallest detail.** A corrected number was itself corrected in round 3 (72.9 to 76.9 became 72.9 to 81.9).

### (e) Open questions and the observable that closes each
- *Are the round-3 corrections (H1, H2, H7) posted to #1665 and #1672?* Closes by reading the ticket comments; not done.
- *Does the live Hugging Face card still carry the retracted sentences?* Closes by downloading the card read-only and searching for "byte-identical".
- *Does a live tool call reach the model-backed classifier, and what does it see?* Closes with the #1674 trace.
- *Has any frozen surface re-frozen since DEC-11?* Closes by running the freshness gate (`docs/governance/doc-lifecycle.md` is the standing policy; the gate itself I did not locate).

### (f) Decisions made / waiting for the LA
- *Made:* withdrawal of the deterministic-DENY recommendation (the file records it as a correction, with the design decision left to the LA after the trace); D1 to D10 triage (DEC-11 row).
- *Waiting for the LA:* whether the model should see tool-call arguments, and under which keys (a Policy Agent security-posture call, per the new-ticket text).

### (g) Tickets
#1673, #1665, #1672, #1674 (new ticket, as numbered in the file), #1664, #1663; #945 (audit decisions D1 to D10), #267 (April archive-not-delete decision). Ticket text not read.

### (h) Raw sources
In repo: the three paths above; `docs/research/jev-policy-agent-ideation-2026-10-04.md`; `docs/research/qwen35-9b-int8-verdict-2026-10-04.md`; `docs/adrs/ADR-044-Policy-Agent-Model-Path-and-Tool-Call-Arguments.md`; `docs/adrs/ADR-047-Model-Evaluation-Protocol-Cold-Gate-Pre-Registration-and-Visible-Retractions.md`. The audit folder holds: `README.md` (5,199 bytes), `archivists_report.html` (60,647), `claude_md_memory_assessment.md`, `crossrepo_sweep.md`, `doctrine_audit.md`, `journal_mine_chunk_1.md` to `journal_mine_chunk_7.md`, `lessons_mine.md`, `logs_archives_audit.md`, `mine_transcripts.py`, `synthesis_journal_gems.md`, `transcript_read_patterns.txt`. The README links an external claude.ai artifact copy of the report; I did not open it.

### The two asset folders (report requested; nothing deleted)

| Folder | File | Size (bytes) | In git? |
|---|---|---|---|
| `docs/research/Publication Program — Ceremony Read_ P1-S4 & P2_files/` | `frame-shell-C55DDsTl_MV0O.js` | 21,925 | yes |
| same | `a_MV0O.htm` | 110,513 | no (ignored by `.gitignore` line 21, `*.htm`) |
| `docs/research/Publication Program — Editorial Board Report_files/` | `frame-shell-C55DDsTl_1MBd.js` | 21,925 | yes |
| same | `a_1MBd.htm` | 35,340 | no (same rule) |

- What they are: browser "save page" asset folders. Each `a_*.htm` is a rendered Claude page (its title tag reads "Publication Program — Ceremony Read: P1-S4 & P2" and "Publication Program — Editorial Board Report"). Each `.js` is a minified web-page runtime; `cmp` reports the two `.js` files byte-identical. The matching top-level page files `docs/research/Publication Program — Ceremony Read_ P1-S4 & P2.htm` (159,041 bytes) and `docs/research/Publication Program — Editorial Board Report.htm` (158,837 bytes) exist on this disk but are ignored by git, so the repository (and any other clone) holds only the two scripts. I did not reproduce page content.
- What the pages are about (from titles only): the publication-program Editorial Board session and a ceremony read for P1-S4 and P2. The program's tracked record is `docs/research/publication-program/` (its README section 2 mentions the Editorial Board session that ran 2026-07-19). Whether the pages say anything the tracked files do not: **not verified**.
- **Recommendation: delete the two folders from the tracked tree** (a normal commit; history keeps them). Reason: the only tracked content is an identical generic script, not research; mapping them would need a card that cites nothing. Keep or discard the ignored local `.htm` files at the LA's choice; if the pages matter, the right home is a short note in `docs/research/publication-program/`. Alternative if the LA prefers no deletion: keep them listed in `docs/research/knowledge_map_unmapped.yaml` with the reason already there.

**Connects to existing cards:** batch 3 card H (measurement discipline and the evidence system) owns the visible-retraction rule and ADR-047; batch 2 card A owns ADR-044 and the Policy Agent model path; batch 4 card J (models) owns the Qwen3.5 arcs these texts correct; batch 4 card K (upstream and community, publication programme) owns the Hugging Face dataset and the publication-program folder.

---

## Connections (all [PROPOSED]; each pairs two real documents; none is tested)

1. **The search-query leak and the harvest's privacy section.** `docs/research/confidentiality-axis-design-2026-09-17.md` (the 14B writes the query from its full context) with `docs/research/websearch_method_harvest.md` section 2.4 (Option A sends decomposed sub-questions "not the raw user text unless the 14B formulates them that way"). The harvest's privacy claim for Option A assumes the model writes harmless queries; the note shows that is the unresolved question. A test: log what a day of real searches sent and read it against the knowledge bank.
2. **Two-clock liveness and the typed event stream.** `docs/research/agentic-code-design-quality-loops-2026-06.md` ("Timing and liveness": progress clock plus ceiling clock) with `docs/research/agent-protocol-evaluation-2026-07.md` section 6.1 (no event for N seconds as a protocol-level idle signal). The first asks for a progress signal at every level; the second says a protocol could supply it for the coder step.
3. **A verdict on a prompt the live system never sends.** `docs/research/g1-vikunja-correction-text-2026-10-04.md` (the 14B DENYs because of the rejection marker on the evaluation prompt) with `docs/research/agentic-code-design-quality-loops-2026-06.md` Q1 (self-correction gains came from an outside crutch that disappears in practice). Same pattern: agreement that could not have disagreed. Any evaluation that reports a model's judgement should say which prompt the live path builds.
4. **Honest coverage and the exfil screen.** `docs/research/runtime-action-governance-product-concept-spec-2026-09-17.md` (scenario S8 and "never claims coverage it does not have") with `docs/research/confidentiality-axis-design-2026-09-17.md` fact 2 (ordinary private prose passes the screen). BlarAI's own coverage statement for egress should say what the screen does not hold.
5. **Memory saved versus memory spent.** `docs/research/ram-headroom-assessment-2026-07.md` (recoverable range 1.5 to 3 GB, KV-cache compression 0.6 to 0.9 GB at typical context) with `docs/research/hf-root-card-correction-2026-10-04.md` (the 9B with MTP uses 3.1 GB less than the 14B but waits 2.65 times as long for its first token). Compare the three levers on one table: GB freed, speed cost, quality gate.
6. **Frozen-document root cause and unposted corrections.** `docs/research/doc-infrastructure-audit-2026-07/README.md` (ownerless documents freeze) with `docs/research/g1-vikunja-correction-text-2026-10-04.md` (part of the correction was "NOT yet posted"). A drafted correction with no named poster and no observable is the same shape; the file's own "posted since" line is the only trace. A test: every correction text carries an owner and a "posted" checkbox that the freshness gate can read.
7. **Autostart drift and the freshness gate.** `docs/research/ram-headroom-apply-log-2026-07.md` (updates may silently re-add the removed autostart entries; check three sites after each update) with the audit README's decision D8 (re-own and gate-check always-loaded files). Both are "state that drifts back"; a small periodic check script could cover the registry entries the way the freshness gate covers documents.
8. **Cost of the protocol decision and the cancelled venture.** `docs/research/runtime-action-governance-product-feasibility-brief-2026-09-17.md` (Q2: what only Microsoft can do) with `docs/research/agent-protocol-evaluation-2026-07.md` section 6.2 (A2A trigger: BlarAI consumes a networked agent). If the narrower ADR-049 claim proceeds, the second may become relevant to the first; both documents agree that governance only covers what passes through it.

## Corrected claims (for these topics)

| Claim as first made | What replaced it | Where |
|---|---|---|
| "The exfil screen plus one egress scope hold operator data today" (premise of the first draft of the confidentiality note) | The screen allowed a medical note, a legal matter and a budget sentence in the probe | `docs/research/confidentiality-axis-design-2026-09-17.md`, `docs/reviews/1546-confidentiality-axis-disposition-2026-09-17.md` |
| "Labelling the query instead of the context escapes the collapse" (first draft) | It does not: the query is written by the same model from the same context | same |
| Product venture: hypothesis document | Tested; NO-GO 2026-09-18; cancelled (ADR-042); narrowed reopening (ADR-049, per batch 4). The concept spec's banner does not mention the reopening | concept spec banner; batch 4 card I |
| "Deny whenever the schema is rejected; I recommend yes" (#1673) | Withdrawn 2026-10-04; build nothing until the #1674 trace | `docs/research/g1-vikunja-correction-text-2026-10-04.md` |
| "Byte-identical across 3 runs" (Policy Agent) | Parsed label and confidence identical in 3 of 3 runs; raw text compared once | same |
| "Output identical on every check" for MTP | Differed in 1 of 377 (4B) and 2 of 366 (9B) calls | `docs/research/hf-root-card-correction-2026-10-04.md` |
| Strict-gate start range "72.9 to 76.9 C" | 72.9 to 81.9 C, 7 rows above 76.9 | g1 correction text, follow-up comment |
| Jev note: "103 answers, 102 at 0.95, all 10 wrong ALLOWs" | 104 answers, 103 at 0.95; population narrowed in a second correction to 6 informative rows | g1 correction text |
| "The 14B refuses on the marker, so keep it" | Describes the evaluation prompt; live path not shown | same |
| "The agentic-setup coder brief loads per dispatch" (earlier audit claim) and "docs/security 290 MB is content" | Brief is a build spec; the 290 MB is git-ignored vendored node_modules | audit README, headline 8 |
| Standing memory ticket #564: "3 GB KV cache is fixed" | Annotated stale | `docs/research/ram-headroom-assessment-2026-07.md` section 6 |

## What I could not verify

- Vikunja ticket text for every ticket named (no ticket read); whether the round-3 correction comments were posted; whether the live Hugging Face card was updated.
- The outcome of the #759 spike and whether the review-loop design (#687, #685) was built.
- The 50-plus papers cited by the coder-loop research and the web sources in the protocol evaluation (documentation grade).
- Post-reboot memory numbers; the contents of `docs/performance/ram_census_2026-07-15.json`; what `kv_cache_precision = ""` means at runtime; current live status of web search.
- The 16 other files in `docs/research/doc-infrastructure-audit-2026-07/` (read only the README and the first lines of one); the claude.ai artifact copy of the report.
- Whether the two ignored publication-program pages say anything not already in `docs/research/publication-program/`.
- Line-number citations quoted from the studies (`entrypoint.py:6996`, `entrypoint.py:401` and similar): copied, not re-checked.
