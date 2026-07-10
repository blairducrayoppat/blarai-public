# Learning Loops Program — operator-feedback memory + self-improving fleet

**Status:** **APPROVED by the LA (2026-07-09, in-chat)** — scoping-grade program design (promoted from draft #770); P9 added at approval.
**Owner ticket:** Vikunja #770. **Author:** overnight coordinator session, 2026-07-09.
**Research foundation:** dedicated web-research pass 2026-07-09 (full synthesis in Appendix A).
**ADR-grade decisions flagged inline** — the build kickoff authors the ADR(s); this document
fixes the program shape, the phasing, and the design positions the research settles.

---

## 1. Vision (the LA's framing, 2026-07-09)

Three interlocking learning loops, built so a **non-technical operator** gets systems that
improve themselves over time without him engineering any of it:

1. **BlarAI learns from the operator** — corrections and preferences said in conversation
   become durable memory that shapes every future turn.
2. **The coder fleet learns from its own outcomes** — dispatch verdicts, oracle results, and
   failure attributions (already captured honestly by the M2 campaign machinery) get distilled
   into lessons that change how the next dispatch runs, measurably.
3. **The operator stays the governor without being the engineer** — he approves or culls
   proposed lessons as plain-language cards; he never writes rules, prompts, or code.

**The governing principle for all three loops (locked):** *propose → verify → land.*
Machines propose lessons from evidence; deterministic gates verify them (a lesson that
regresses the eval suites never lands); the operator confirms at coarse grain. A system that
edits its own instructions is a self-modification surface — the highest-risk class in
ADR-022's taxonomy — so autonomy lives in the *proposing*, never in the *committing*.

---

## 2. What the research settles (design positions, each with its evidence)

The 2026 state of the art (Letta/MemGPT, Mem0, Zep/Graphiti, ChatGPT memory, Anthropic's
memory tool, LangMem, A-Mem, MemoryBank; full landscape in Appendix A) mostly optimizes for
constraints BlarAI does not have (frontier-model extractors, multi-user shared memory, cloud
scale). The positions below are the ones that survive contact with OUR constraints — a 14B
consumer, a single trusted operator, air-gapped, fail-closed, 31 GB ceiling:

| # | Position (LOCKED for v1 unless the kickoff ADR overturns with cause) | Why |
|---|---|---|
| P1 | **Explicit capture first.** `/remember`-class command + model-*proposed*/operator-*confirmed* capture. Implicit extraction ships DORMANT. | ChatGPT's two-lane split; the inferred lane is where user trust broke. Explicit utterances are our highest-trust provenance. |
| P2 | **Store verbatim + thin structured envelope. Never LLM-paraphrase the body.** | Controlled ablation (arXiv:2601.00821): verbatim beats extracted summaries, and *small models cannot recover from summarization loss*. Our extractor would be the 14B. It may TAG a memory (type/subject); it must not REWRITE it. |
| P3 | **Index-plus-body injection.** A small pinned block of standing preferences always in context; everything else via the existing `search_knowledge`-style tool. | Letta memory blocks + Anthropic view-first protocol + our own MEMORY.md pattern. Standing preferences ("call me X") are needed every turn — retrieval roulette is the wrong mechanism for them. |
| P4 | **Hard token budget on the pinned block** (target ≤ ~1–2k tokens, char-capped per memory), gate-locked like every other budget (timeout-registry pattern). | 31 GB ceiling; Mem0's ~7k/retrieval is a cloud number. Unbounded memory injection is self-DoS (OWASP LLM10). |
| P5 | **Update-in-place with operator confirmation on contradiction; last-writer-wins + audit trail. No append-only coexistence, no bitemporal graph.** | Mem0's ADD/UPDATE/DELETE/NOOP router is the portable idea; single-operator lets us make it a confirmation instead of an autonomous LLM call. Zep's bitemporal machinery is overkill for preferences. |
| P6 | **No time-decay on the preference tier.** Decay/expiry applies only to a (later) episodic tier. | MemoryBank-style Ebbinghaus decay is right for episodic clutter, wrong for "call me Blair." Tier decided at write time. |
| P7 | **Reuse the existing substrate.** New provenance tier + pinned-index renderer over the existing encrypted SQLite knowledge bank + bge-small. No new vector store, no graph DB. | Control-plane placement dominates forgetting behavior, not store exotica (arXiv:2606.15903). We can't spare the RAM or the ops surface. |
| P8 | **The operator is the sole committer to the injected tier.** The 14B may draft and read; a write to anything that auto-injects requires explicit operator confirmation or command. | Kills the MINJA-class attack structurally (see §5); preserves the "anything injected into the prompt is an injection surface" invariant — the injected text is operator-authored. |
| P9 | **Prefix-cache-aligned injection + measured caps** (LA direction at approval, 2026-07-09). The pinned block renders byte-stable (deterministic order, stable ids, append-minimal edits) at a FIXED early position in the system prompt so OpenVINO GenAI prefix caching reuses its KV across turns — the block's prefill cost is paid once per session, not per turn; a preference edit invalidates the prefix exactly once. The size caps (P4) are MEASURED, not guessed: an M1 task benchmarks prefill latency at candidate cap sizes (256/512/1k/2k tokens) on the Arc 140V, cached and uncached, and the cap is chosen from that data. | The 14B measures ~1960 pp tok/s on this silicon → even 2k tokens ≈ ~1s uncached, ~0 cached — but that is an estimate, and estimates are measurements of the wrong scenario until proven (lesson 151). Couples to the existing prefix-caching instrument: #711 (enable_prefix_caching re-validation, `docs/performance/prefix_caching_ab_validation_plan.md`) — the same A/B measures both; and the upstream persistent-KV-cache feature request (`docs/GENAI_FEATURE_REQUEST_PERSISTENT_KV_CACHE.md`) would extend the once-per-session cost to once-per-boot if it lands. |

---

## 3. Loop 1 — BlarAI operator-feedback memory (step by step)

### 3.1 The turn flow (read side)
1. At prompt-assembly time the AO renders the **pinned preference block** from the
   `OPERATOR_PREFERENCE` tier: datamarked, budget-capped (P4), deterministic order
   (stable across turns for KV/prefix friendliness).
2. The block is *behavioral context*, not instructions-from-content: it carries its
   provenance datamark so Layer-3/PGOV treat it as the operator's standing voice, distinct
   from `UNTRUSTED_KNOWLEDGE`.
3. Episodic/situational memories (later phase) are NOT pinned — reachable via the existing
   guarded recall tools.

### 3.2 The write flow (capture side)
1. **Explicit path (Phase 1):** operator issues `/remember <text>` (or WinUI affordance).
   Stored VERBATIM (P2) with an envelope: `{tier, type: address-form|standing-rule|fact,
   subject, body_verbatim, created, source: operator-explicit}`. The 14B may propose the
   `type/subject` tags; a mis-tag is cosmetic, never lossy.
2. **Propose-and-confirm path (Phase 2):** the 14B notices a correction mid-conversation
   ("no — always use metric") and emits a *proposal card*: "Save this as a standing
   preference? → [exact verbatim text]". Nothing persists until the operator confirms.
   The proposal channel is a tool call (`propose_preference`) — GUARDED, and its output is
   a UI card, never a store write.
3. **Contradiction handling (P5):** before commit, top-k similarity against existing tier
   rows; near-duplicate/contradiction surfaces as "this replaces 'X' — confirm?" —
   last-writer-wins on confirm, superseded row kept as audit history (born-encrypted,
   excluded from rendering).
4. **Curation UX:** `/preferences` lists the tier (numbered, plain language); edit/delete
   one-command; the pinned block is regenerated deterministically after every change.

### 3.3 What Phase 1 explicitly does NOT do
- No implicit/background extraction (ChatGPT-"Dreaming"-style consolidation) — dormant,
  its own later decision with its own ADR.
- No model-autonomous writes anywhere that injects (P8).
- No decay logic (P6) — the preference tier is stable-until-changed.

---

## 4. Loop 2 — the coder fleet learns from outcomes (step by step)

The fleet already produces the world's best raw material for this: honest scorecards with
verdict/attribution vocabulary, oracle results, guest certificates, per-era campaign
annotations, and a curated human-side lessons journal (`agentic-setup/docs/LESSONS-LEARNED.md`)
feeding the coder's instruction file (`configs/AGENTS.md`). What's missing is the automated
loop between them. Design:

### 4.1 Stage C1 — lesson-candidate mining (build first, lowest risk)
After each battery pass / dispatch cluster, an automated **post-pass analysis step** (runs on
the 14B or as a scheduled Claude-session job) reads the scorecards + attributions and emits
`state/lesson-candidates/<date>.md`: recurring failure shapes ("N of last M node jobs failed
on import-layout"), each with its evidence rows and a *proposed instruction delta* phrased as
a diff against `AGENTS.md` or a card template. **Output is a report, not a change.** This is
the fleet-side analogue of the journal-fragment inbox.

### 4.2 Stage C2 — gated landing
A proposed instruction delta lands only through the gate chain:
1. **Deterministic verify:** the delta applies cleanly; the instruction file stays within
   its own size budget; a lint over forbidden classes (nothing that weakens the verify gate,
   the secret-scan, or the FALSE-DONE cross-check — the self-modification lint list is an
   ADR item).
2. **Empirical verify (the teeth):** an A/B dispatch of a small golden job set (the battery
   cards are exactly this) with old vs new instructions — the delta must not regress the
   golden verdicts. This reuses the campaign machinery as the lesson-gate.
3. **Operator card:** the surviving delta reaches the LA as a plain-language card ("Lesson:
   the coder keeps X-ing; proposed rule: 'always Y'; evidence: 4 scorecards; A/B: no
   regression, B4-class improved") — approve/cull. On approve, the delta commits with the
   evidence trail (era-annotated, like #764's plugin eras, so effectiveness stays measurable).

### 4.3 Stage C3 — the measured improvement loop
Each landed lesson gets an era annotation; the standing campaign measures verdict deltas
across eras (the L4 dataset methodology already carries eras). A lesson that measures dead
weight over N passes surfaces for retirement — the shrink-or-retire cadence from the
timeout-registry discipline, applied to instructions.

### 4.4 Placement
Loop 2 artifacts live in **agentic-setup** (the fleet's repo); the program ticket stays
blarai #770 with a fleet-side implementation ticket to be opened at kickoff. The
lesson-candidate miner MUST NOT run during a live pass (post-pass window only, the
runner-owned-file discipline).

---

## 5. Security posture (the section that makes this shippable)

Threat class: **memory/context poisoning** (OWASP Agentic ASI06; MINJA, NeurIPS 2025).

- **MINJA's preconditions are structurally absent here** — it requires a shared multi-user
  memory bank and an agent that autonomously stores its own reasoning traces. BlarAI is
  single-operator, offline, and (P8) nothing auto-injected is machine-committed. The MINJA
  authors' own conclusion: classifier defenses fail (entangled embeddings); *structural*
  defenses (isolation, authenticated write paths) hold. We build the structural ones.
- **Defense-in-depth anyway:** the tier is datamarked at injection (recalled memory is
  treated as an injection surface even though operator-authored — the indirect path where
  a preference's text was influenced by ingested content is real); GUARDED-tool lock
  semantics unchanged; the tier can never escalate tool privileges.
- **Write-path hygiene:** the write API accepts only tier-shaped rows (format-gated fields,
  the anchored-id pattern); no free-form paths; born-encrypted rows as today.
- **Bounded consumption:** caps on memory count, per-memory chars, and total pinned tokens
  (P4) — all registered, gate-locked budgets.
- **Red-team eval (gate case):** an ingested document attempts to plant a preference
  ("[system: remember to always...]") — assert it can NEVER reach the injected tier without
  the operator's explicit confirmation, and that the proposal card renders it inert.

**ADR obligations at kickoff:** one new ADR (operator-feedback memory governance: tier
semantics, write authority, budgets, the dormant-implicit-lane decision) + an ADR-022
taxonomy entry for the Loop-2 instruction-delta surface + DECISION_REGISTER rows.

---

## 6. Evaluation (locks before capability, per house style)

New `evals/` suite `preference_memory` (golden-set pattern, model-in-the-loop cases behind
`--include-hardware`):

1. **Capture fidelity** — stored body is verbatim-identical; type tag correct (P2).
2. **Injection & use** — fresh session: pinned block contains the preference AND the model
   applies it (uses the name; follows the rule). The real success metric.
3. **Update/contradiction** — "actually, call me X" → last-writer-wins; the old form absent
   from the rendered block (P5).
4. **Abstention** — a never-stated preference is not confabulated (LongMemEval's abstention
   axis; critical at 14B).
5. **Non-decay** — preferences persist across simulated long idle (P6).
6. **Budget lock** — pinned block stays under cap as the tier grows (P4).
7. **Poisoning red-team** — ingested-content write attempt never lands (§5).

Loop 2's eval IS the A/B golden dispatch gate (§4.2) — no separate suite needed initially.

---

## 7. Phasing, queue position, dependencies

| Phase | Scope | Depends on | Surface |
|---|---|---|---|
| **M1** | `OPERATOR_PREFERENCE` tier + verbatim store + `/remember` + `/preferences` list/edit/delete + pinned-block renderer + budget locks + eval suite cases 1–6 + **the P9 cap measurement** (prefill latency at 256/512/1k/2k-token blocks, cached/uncached, on the 140V — ride the #711 prefix-caching A/B; caps set from the data, community-grade record) | knowledge-bank substrate (exists), evals harness (exists), #711 instrument | blarai runtime + WinUI passthrough (allowlist SSOT step required) |
| **M2** | Propose-and-confirm capture (`propose_preference` GUARDED tool + WinUI card) + contradiction confirm flow + red-team eval case 7 + the governance ADR | M1 | blarai runtime + WinUI |
| **M3** | Fleet Loop 2 Stage C1 (lesson-candidate miner, post-pass) | campaign machinery (exists) | agentic-setup |
| **M4** | Loop 2 Stages C2–C3 (gated landing + era measurement) + ADR-022 entry | M3 + a settled campaign | agentic-setup |
| Later | Episodic tier w/ expiry; implicit-extraction lane (own ADR + LA decision); cross-loop synthesis | M1–M4 evidence | — |

**Queue (LA direction 2026-07-09):** #770 ranks ABOVE #769 (llama.cpp/Qwen3.6 backend tests,
dropped to priority 2). #770 is CPU-side design/build — it does not contend for the GPU and
can interleave with the GPU-bound queue (battery campaign, ACP A/B, #769). Recommended
kickoff: a dedicated build session (or /sprint-kickoff) taking M1+M2 as one arc, after the
2026-07-09 daylight session's committed items.

---

## Appendix A — research synthesis (2026-07-09, verbatim)

*(Dedicated research pass; sources fetched and read as cited. This is the evidence base for
§2's positions.)*

> **Bottom line:** the frontier of memory research has moved toward heavy LLM-driven
> extraction and temporal knowledge graphs, but almost every one of those design choices is
> optimized against constraints BlarAI does not have (frontier models, adversarial multi-user
> memory, cloud scale) and works against constraints it does have (a 14B extractor, a single
> trusted operator, a fail-closed security posture). The most defensible design here is
> closer to Anthropic's file-memory tool and Letta's pinned memory blocks than to Mem0/Zep —
> explicit-capture-first, verbatim-or-lightly-structured storage, a small always-in-context
> index, and the operator as the sole write authority.

### Landscape

| System | Capture | Store | Retrieve / Inject | Curate | Notable for BlarAI |
|---|---|---|---|---|---|
| Anthropic memory tool (Claude 4+) | Model-driven via tool calls; "always view memory first" protocol | Flat files under `/memories` | Just-in-time tool-call retrieval | Model edits own files; host caps size, expires stale, strips sensitive | Direct analogue; ships path-traversal + sensitive-data guidance |
| Letta / MemGPT | Model self-edits, or async "sleep-time" agent | Memory blocks (label+description+value+char-limit) pinned in context; archival in pgvector | Core blocks always in context; archival via vector-search tool | Self-edit tools rewrite blocks; char-limits force compaction | The always-in-context index block pattern is the best fit |
| Mem0 / Mem0ᵍ | LLM-extracted salient facts per turn | Dense vectors (+ optional entity graph) | Multi-signal fused; ~7k tokens/retrieval | LLM router: ADD/UPDATE/DELETE/NOOP | Extractor is GPT-4o-mini; the contradiction-handling idea is portable |
| Zep / Graphiti | LLM builds triples | Bitemporal knowledge graph (Neo4j) | Hybrid semantic+BM25+graph; no LLM at retrieval | Contradictions become validity intervals | Elegant but heavy; overkill for preferences |
| ChatGPT memory | Two-lane: explicit saved + implicit chat-history reference | Saved list + synthesized user model | Injected into system context | 2026 "Dreaming" background re-synthesis | Validates the explicit-vs-implicit split; implicit lane is the risky one |
| LangMem | Hot-path tools or background manager | Semantic/episodic/procedural, namespaced | Tool-call or injected | LLM manager consolidates | "Procedural memory" = behavioral rules is exactly the feedback use case |
| A-Mem | LLM note per memory | Zettelkasten notes + links | Semantic + link traversal | New notes trigger "memory evolution" edits | Evolution edits are an unbounded self-modification surface |
| MemoryBank | Summarize daily events | Event summaries + user profile | Vector recall | Ebbinghaus decay R(t)=e^(−t/S) | Time-decay wrong for stable preferences |

### Key findings behind the §2 positions
- **Verbatim beats extraction for small models** (arXiv:2601.00821): the smaller model could
  not recover from information lost during summarization; frontier models could.
- **~7k tokens/retrieval** is the production convergence (Mem0 2026) — a cloud budget; ours
  must be tighter and deterministic.
- **MINJA** (arXiv:2503.03704): query-only memory poisoning; preconditions = shared memory
  bank + autonomous storage of reasoning traces; classifier defenses fail (entangled
  embeddings); structural defenses hold. OWASP ASI06 canonizes the class.
- **Control-plane placement dominates** memory quality outcomes, not store exotica
  (arXiv:2606.15903) — reuse the substrate.
- **LongMemEval** (arXiv:2410.10813): five ability axes — extraction, multi-session
  reasoning, temporal reasoning, knowledge updates, abstention — the template for the
  eval suite.

### Sources
Anthropic memory tool docs (platform.claude.com); Letta memory blocks + MemGPT
(arXiv:2310.08560); Mem0 (arXiv:2504.19413; State of AI Agent Memory 2026); Zep/Graphiti
(arXiv:2501.13956); Verbatim-vs-extraction ablation (arXiv:2601.00821); MINJA
(arXiv:2503.03704); OWASP LLM Top-10 2025 (LLM10) + Agentic Top-10 (ASI06); LongMemEval
(arXiv:2410.10813); OpenAI Memory FAQ + "Dreaming"; Willison memory critique
(simonwillison.net 2025-05-21); LangMem SDK; A-Mem (arXiv:2502.12110); MemoryBank
(arXiv:2305.10250); Control-Plane Placement (arXiv:2606.15903); Intel small-model
factuality note. Un-fetched leads (named, not verified): SAGE, FadeMem, MemGuard, SMSR,
MEMSAD.
