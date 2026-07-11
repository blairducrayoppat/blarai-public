# Assistant-Memory Reference Study — external designs vs the BlarAI substrate

**Status:** research study, 2026-07-10 — input to the #770 M2/M3 iteration plan
(`docs/research/preference_memory_m2_m3_iteration_plan_2026-07.md`). No build.
**Author:** research + design specialist session (dev-side, internet-permitted).
**Relationship to prior work:** this study EXTENDS `docs/LEARNING_LOOPS_PROGRAM_DESIGN.md`
Appendix A (the 2026-07-09 research pass that locked P1–P9). It does not re-litigate
those positions. What it adds: (1) **OpenClaw** as the primary new reference — the
appendix never covered it; (2) the memory-plugin ecosystem (opencode-agent-memory,
Supermemory, the local-MCP-memory class, Letta's 2026 sleep-time shape); (3) the
salience/decay/poisoning literature the appendix named but never fetched (SAGE,
FadeMem, MemGuard, SMSR, MEMSAD) — now verified, with one lead retired as
unverifiable. **Method:** three parallel dev-side research passes (2026-07-10),
sources fetched and cited per claim; grounding reads of the shipped M1 code
(`preference_block.py`, `preferences_coordinator.py`, `shared/preference_budgets.py`,
`knowledge_bank.py` §operator_preferences + §hybrid-retrieval).

---

## 1. The reference frame — what any idea must survive

Every external idea below is judged against BlarAI's hard constraints and against
what is **already on disk**, because the cheapest design is the one whose mechanism
already shipped (lesson C8):

| Constraint / existing mechanism | Consequence for memory design |
|---|---|
| Absolute runtime air-gap (ADR-020 kill-switch; egress allowlist = `kagi.com` only) | Any cloud-API memory service is reference-only. Embeddings, extraction, consolidation must all run on-box. |
| Local inference only: Qwen3-14B (OpenVINO, Arc 140V); bge-small-en-v1.5 embeddings (NPU-offloaded, 13.6× at 512-token windows) | The extractor/consolidator is a 14B — P2 (verbatim, never paraphrase) stands; the embedding budget is real but cheap and local. |
| Born-encrypted stores (ADR-025 DEK envelope; FieldCipher, AAD-bound rows); fail-closed | Plaintext markdown stores are reference-only as *storage*. Their transparency ideas port; their bytes-on-disk do not. |
| 31.323 GB ceiling; prefix-cache economics measured (#711 S8: warm-hit flat ~0.4–0.8 s; edits/cold ~4.4 ms/token) | Injected memory is byte-budgeted (P4/P9). Any always-in-context idea pays the S8 curve. |
| Provenance/datamark model (ADR-023, five tiers; grounded data is never instruction — lesson C10) | Recalled memory is an injection surface regardless of origin. Every new memory class needs a provenance tier decision. |
| P8 sole-committer (operator is the only writer to anything auto-injected) | Any design where the model edits its own durable memory is structurally rejected for the injected tier. |
| **Already built:** hybrid retrieval — cosine + FTS5 BM25 fused by RRF (k=60), in-RAM rebuildable index (ADR-031 L2/L4, `knowledge_bank.py:2228`); per-prompt auto-recall (4 chunks) + GUARDED `search_knowledge` | "Hybrid recall" is not an adoption question here — it is an *extension-of-scope* question. |
| **Already built (M1, #770):** `operator_preferences` tier — verbatim, encrypted, P8-locked, byte-stable pinned block at a fixed system-prompt slot, measured budgets (1024-tok block / 500-char body / 64 rows), deliberately NOT a retrieval surface | The pinned-index half of the index-plus-body pattern (P3) exists. The open questions are the *episodic* half, curation, and Loop 2. |

Verdict vocabulary used below: **ALREADY BUILT** (BlarAI has it; note the mapping),
**ADOPT** (take the idea for M2/M3), **ADAPT** (take the shape, change the mechanism),
**LATER** (right idea, belongs to the episodic-tier / implicit-lane phase, own ADR),
**REFERENCE-ONLY** (assumes cloud/plaintext/multi-user; keep for language and evidence),
**REJECT** (conflicts with a locked position; named reason).

---

## 2. OpenClaw — the primary reference

OpenClaw (formerly Clawdbot/Moltbot; Peter Steinberger's open-source personal
assistant) is the closest *product* analogue to BlarAI's assistant ambition: a
single-operator, long-lived personal agent whose memory design was reverse-engineered
and heavily security-analyzed in 2026. It is cloud-connected and plaintext-on-disk —
the extraction here is design ideas, never the product.

### 2.1 Its shape, in one paragraph

Markdown files are the authoritative store: `MEMORY.md` is a **compact curated
layer** ("durable facts, preferences, and decisions" — explicitly *not* a transcript)
loaded at session start; `memory/YYYY-MM-DD.md` daily notes are the **raw working
layer**, auto-loaded only for today/yesterday and otherwise reached through search
tools. A per-agent SQLite index (chunks embedded at 400 tokens / 80 overlap, versioned
chunk IDs, 1.5 s debounced reindex) is a **derivative** of the files — "the vector
index is not the source of truth; the files are." Recall is **hybrid**: BM25 via
SQLite FTS5 + vector cosine, weighted ~0.7 vector / 0.3 text, with an MMR diversity
pass (λ=0.7), a min-score floor (0.35), and a **retrieval-time temporal boost**
(half-life ~30 days). If `MEMORY.md` outgrows the bootstrap budget, the *injected
copy* is truncated while the disk file stays whole. An optional background
"**dreaming**" process promotes daily-note material into `MEMORY.md`, gated on
"score, recall-frequency, and query-diversity," staging candidates for human review
in `DREAMS.md`. The governing transparency statement: *"The model only remembers
what gets saved to disk; there is no hidden state."*

### 2.2 Idea-by-idea verdicts

**(a) Two-layer memory: curated always-loaded index + searchable raw archive —
ALREADY BUILT (half) / LATER (half).** The curated layer IS the M1 pinned block
(P3), with BlarAI's version strictly stronger: byte-stable rendering for prefix-cache
reuse, measured caps, and a write door that refuses before truncation is reachable —
where OpenClaw truncates the injected copy silently, BlarAI's operator is told at
write time that the tier is full. The searchable raw layer (daily notes) is the
**episodic tier** the program design deferred to "Later." OpenClaw's strongest
argument for building it eventually: the curated layer stays clean *because* there
is somewhere else for raw material to live. Without an episodic tier, pressure will
grow to stuff situational facts into the preference tier, and the 64-row cap becomes
a fight instead of a comfort.

**(b) Store-authoritative, index-derivative — ALREADY BUILT.** OpenClaw's
"files are canonical, SQLite is rebuildable" is exactly ADR-031 L2 (encrypted rows
canonical; vectors + in-RAM FTS5 rebuilt at DEK-unlock). The convergence from an
independent design is validation, not news. One refinement worth taking
(**ADOPT, small**): OpenClaw versions every chunk ID with the *embedding model
version* and, on provider failure, **pauses vector search rather than silently
re-embedding with a different model** ("index identity"). BlarAI's substrate already
stamps `embed_max_tokens` in `substrate_meta`; adding an embedding-model/version
stamp with a fail-closed mismatch check is the same discipline (C5 — what you
configure is not what runs) applied to the vector limb, and it becomes load-bearing
the day the bge-small model is ever upgraded.

**(c) Hybrid recall (vector + keyword) — ALREADY BUILT; two candidate refinements.**
BlarAI fuses by RRF (k=60), OpenClaw by weighted score (0.7/0.3). Keep RRF: it fuses
on ranks, sidestepping the BM25-vs-cosine score-compatibility problem, and the IR
literature (see §4.2) supports it; weighted fusion needs score normalization that
drifts with corpus statistics. Two OpenClaw retrieval refinements are worth
evaluating **when the episodic tier exists** (they are tuning, not architecture):
an **MMR diversity pass** (top-k from one document crowding out breadth is a real
failure shape at k=4) and a **min-score floor** (returning nothing beats returning
noise — and abstention quality is precisely where a 14B needs help, per the
LongMemEval abstention axis already in the eval suite). A **retrieval-time temporal
boost** is the third refinement — see the decay discussion in §4.1 for why
retrieval-boost is acceptable where storage decay is not. (Confidence note: the
exact OpenClaw defaults — 0.35 floor, λ=0.7, 30-day half-life — come from a single
config-reference fetch; treat the *mechanisms* as verified, the numbers as
directional.)

**(d) Bootstrap-budget truncation — ALREADY BUILT, BlarAI stronger.** Noted above;
no action. The M1 write-door pre-check (`block_fits_budget`) is the superior
mechanism because the operator learns of the limit at the moment they can act on it.

**(e) Pre-compaction memory flush ("silent turn reminding the agent to save
context before compaction") — REFERENCE-ONLY today, LATER seed.** BlarAI sessions
persist verbatim in the encrypted `sessions.db`; there is no lossy compaction step
to protect against, so the mechanism has no current target. It becomes relevant iff
a session-summarization feature ever lands: the idea to keep is *flush durable facts
to an explicit store before any lossy summarization*, because post-hoc extraction
from a summary is exactly the small-model information-loss trap P2 exists to avoid.

**(f) Dreaming — background consolidation with promotion gates and staged human
review — ADAPT for M3; REJECT its writer.** The *shape* is precisely the program's
locked propose → verify → land: candidates mined in the background, forced through
gates (OpenClaw: score, recall-frequency, query-diversity), staged for human review
(`DREAMS.md`), never landing silently. That three-gate idea maps directly onto the
M3 lesson-candidate miner's deterministic pre-filter (recurrence count ≥ N; novelty
vs existing lessons; evidence-diversity so one bad day doesn't mint a lesson — see
the plan doc §3). What is rejected is the writer: in OpenClaw **the agent edits its
own memory files** and the dreaming process auto-promotes into the always-loaded
`MEMORY.md`. That is the exact self-modification surface P8 forbids and that
OpenClaw's own security record indicts (below).

**(g) "No hidden state — only what's on disk" — ADOPT the principle at the UX
layer.** BlarAI cannot adopt the plaintext-files mechanism (born-encrypted mandate),
but the *auditability property* — the operator can enumerate, read, and edit
everything the model remembers, and nothing outside the enumerable store shapes
behavior — is already half-true (`/preferences` lists the injected tier verbatim;
the pinned block is deterministic from those rows) and should be kept true as tiers
grow: every future memory class ships with its listing/inspection command in the
same change (the M3 miner's candidates are a *file* the operator reads; an episodic
tier ships `/memories`-class listing). OpenClaw also exposes *injection observability*
(`/context detail` — raw vs injected sizes, truncation status); a debug-grade
"what is in my context and why" surface is a worthwhile Later item for exactly the
reason lesson C17 names: the injected prompt is a layer you cannot unit-test live.

**(h) Action-sensitive memory annotations ("approval or permission requirements,
temporary constraints, … expiry conditions") — ADOPT the *scoped-preference* idea as
an M2/Later option.** OpenClaw's convention that a memory recording *authority to
act* must carry its expiry maps to a real BlarAI gap: an operator preference like
"answer in French until Friday" currently has no expiry field — P6 (no decay) is
about the *system* never aging facts out, but an **operator-stated** scope is not
decay, it is part of the verbatim instruction. A deterministic, operator-authored
`expires` field (rendered until the date passes, then dropped from the render and
flagged in `/preferences`) preserves P6's spirit (the system never decides to
forget) while honoring the operator's own stated bound. Capability choice →
flagged as a [DECISION] in the plan doc.

**(i) OpenClaw's security record — the cautionary half of the reference.** The
2026 analyses are unusually direct: "Taming OpenClaw" (arXiv:2603.11619) names
**agent-editable memory as a critical attack surface** — an attacker with initial
access poisons the store to steer decisions across sessions; Unit 42 frames
persistent memory as an accelerant for **stateful, delayed-execution attacks**
(time-shifted payloads that fire days later); Zenity demonstrated indirect injection
via fetched content landing in memory notes; CVE-2026-25253 (CVSS 8.8) chained a
crafted email through the assistant to session-cookie exfiltration. OpenClaw's own
docs concede the design stance: memory "does not enforce policy… use approval
settings and sandboxing for hard operational controls." The lesson is structural
and it is the one BlarAI already committed to: **the write path to anything
auto-injected is the security boundary, and it must be structural (P8), not
behavioral.** Every M2 red-team case class in the plan doc derives from an attack
here or in §5's taxonomy.

---

## 3. The ecosystem survey — plugins, platforms, and the 2026 field

| System | Design in one line | BlarAI verdict |
|---|---|---|
| **opencode-agent-memory** (Letta-style blocks for the opencode agent) | Always-in-context markdown blocks (global + per-project, YAML frontmatter) written by the agent via `memory_set`/`memory_replace` tools; journal searched via local MiniLM embeddings | REFERENCE-ONLY. The block/journal split re-validates P3; agent-writable blocks violate P8. Its `read_only` flag per block is a thin gesture at what BlarAI enforces structurally. Fully-local embedding path confirms the pattern is viable off-cloud. |
| **Hindsight (Vectorize)** | Hosted retain/recall/reflect with hooks: recall on session start, retain on idle, survive compaction | REFERENCE-ONLY (hosted). The *hook placement* vocabulary (session-start recall; idle-time retain) is useful naming for where BlarAI's seams already are. |
| **Supermemory** | Memory-as-a-service router proxying LLM traffic and injecting context transparently; OSS core can run fully local w/ Ollama | REJECT the router pattern (a transparent proxy that silently mutates prompts is the opposite of the no-hidden-state property and of P9 byte-stability); the local-binary existence proof is noted. |
| **agentmemory (elizaOS) / local MCP memory servers** (`ai-memory-mcp`, `sqlite-memory`, `mcp-local-memory`, etc.) | A commodity class: local SQLite/Chroma + vector (+ sometimes FTS5) memory CRUD exposed as tools | ALREADY BUILT, better. BlarAI's substrate is this class plus encryption, provenance, budgets, and gates. Useful only as evidence that local-first memory is now table stakes. |
| **Letta (MemGPT) 2026** | Memory blocks in-context + archival via pgvector; **sleep-time compute**: a *separate background agent owns the memory-editing tools*; the user-facing agent cannot rewrite its own core memory | ADAPT the separation. The 2026 evolution moved *toward* BlarAI's posture: memory curation off the response path, in a differently-privileged actor. Maps to M3's miner (post-pass job, not the AO) and to any future implicit-extraction lane (a distinct job whose output is proposals, never writes). |
| **LangMem / LangGraph** | Semantic / episodic / **procedural** memory types; hot-path tools + background managers | REFERENCE-ONLY; adopt the *taxonomy word* "procedural" — Loop 2's lesson deltas are procedural memory, and naming the M3 artifact class that way keeps the literature legible. Pre-1.0 maturity noted. |
| **Anthropic memory tool (2026 GA)** | Client-side file CRUD under `/memories`; capture agent-driven, always-view-first; **all safety host-side** (path canonicalization, size caps, expiry, sensitive-data stripping) | ALREADY ALIGNED in spirit — "the host owns the controls, the model only requests" is P8's cousin. Its documented host-side control list (path traversal, size caps, view caps) reads as a checklist BlarAI's equivalents already pass via the anchored-id gates + budgets. |
| **mem0 (Apr 2026)** | Single-pass hierarchical extraction; dropped external graph stores for built-in **entity linking** (semantic + BM25 + entity-match scoring) | REFERENCE-ONLY. ~7k tokens/retrieval remains a cloud budget. Entity linking is a plausible far-future retrieval refinement; not worth a new index today (P7). |
| **Zep / Graphiti, Cloudflare Agent Memory** | Temporal knowledge graph; managed cloud memory | REFERENCE-ONLY / N-A (cloud, multi-tenant, graph ops surface BlarAI cannot spare — reaffirms the Appendix-A verdict). |

The one field-level fact worth recording: **the 2026 consensus moved beyond pure
vector similarity — hybrid (vector + keyword, often + entity) is now the norm.**
BlarAI got there in June (#655, ADR-031 L4) ahead of most of the surveyed field.
The differentiated position BlarAI holds and no surveyed system does: **a structural,
operator-only write path to injected memory.** Every surveyed system either lets
the agent write its own memory (OpenClaw, Letta blocks, opencode plugin, Anthropic
tool) or interposes an LLM extractor (mem0, Supermemory, LangMem background
managers). That difference is the security posture §5 says actually works.

---

## 4. The literature — salience, decay, hybrid evidence, consolidation risk

### 4.1 Salience and decay (SAGE, FadeMem, multi-factor value models)

Verified since the Appendix-A pass (which named these as un-fetched leads):

- **SAGE** (arXiv:2605.30711) — a **write-side novelty gate**: a closed-form von
  Mises–Fisher density estimate over existing memory embeddings scores each candidate;
  high-novelty auto-adds, low-novelty auto-rejects, only ambiguous cases pay an LLM
  call. Cuts write-side LLM calls ~32% at slightly *better* recall F1.
- **FadeMem** (arXiv:2601.18642) — adaptive exponential decay modulated by semantic
  relevance, access frequency, and temporal pattern; **82% retention of critical
  facts at 55% of the storage**.
- **Multi-factor value model** (arXiv:2606.12945) — recency/frequency/importance/
  emotional-significance weights *learned* (CMA-ES); the cleanest published evidence
  that multi-factor salience beats pure recency — but the gains are single-digit,
  and the honest reading across this literature is that the **storage/cost wins are
  robust while the quality wins are modest and measured on large hosted models.**

**BlarAI verdicts.** For the **preference tier: P6 stands, reinforced.** Nothing
here argues for decaying "call me Blair"; decay literature is about episodic clutter
at scales (thousands of auto-captured memories) the explicit-capture P1 posture never
produces. For a **future episodic tier**: prefer OpenClaw's **retrieval-time temporal
boost** (recency as a *ranking signal*, store intact — reversible, tunable, honest)
over FadeMem-style **storage decay** (deletes/compresses — irreversible, and the
54→45% storage saving solves a cost BlarAI's text-scale stores don't have). Storage
decay is REFERENCE-ONLY. **SAGE's novelty gate is the sleeper ADOPT-candidate**, in
two places where it is *not* a decay mechanism at all: (1) the M3 miner's dedup
filter — "is this candidate lesson genuinely new vs LESSONS.md?" is exactly a
novelty-vs-corpus scoring problem, computable on-box with bge-small, replacing an
LLM judgment with a deterministic-ish signal (final say stays with the deterministic
recurrence rules + the operator); (2) a smarter M2 near-duplicate signal beside the
existing Jaccard probe (advisory only — the locked behaviour, REQUIRES_CONFIRMATION,
is untouched; see plan doc §2).

### 4.2 Hybrid retrieval — the evidence, honestly

RRF's rank-based fusion has solid general-IR wins (e.g., NDCG 0.7068 vs 0.6983 BM25
/ 0.6953 KNN on WANDS; keyword-set recall@100 0.38 vs 0.32/0.27) — but there is
**no rigorous published head-to-head of hybrid-vs-pure-vector on an agent-memory
benchmark specifically**; the transfer is an inference. Two consequences: (1) BlarAI's
RRF choice is well-supported and should not churn; (2) since the substrate already
runs both limbs, BlarAI can *measure* the hybrid-vs-vector delta on its own recall
evals nearly for free — a small, publishable community contribution (the operator is
an OpenVINO upstream contributor; local-hardware agent-memory retrieval numbers are
exactly the data the community lacks). Filed as an optional ticket.

### 4.3 Consolidation ("sleep-time compute") with a small model — the risk register

The 2026 literature is now explicit about what BlarAI's M3/implicit-lane design must
respect:

- **SSGM** (arXiv:2603.11768): evolving memory has three failure points — poisoning
  at ingest, **semantic drift at consolidation**, conflict/hallucination at retrieval —
  and unlike static RAG it is an *error-accumulating feedback loop*.
- **Memory Contagion** (arXiv:2606.23195): evaluator/length bias propagates
  *cross-temporally* through memory and is **model-dependent** — weaker models are
  more exposed. A 14B consolidator is the exposed case, directly.
- **Remembering More, Risking More** (arXiv:2605.17830): longitudinal safety-risk
  growth in memory-equipped agents.
- Sleep-time compute (arXiv:2605.26099, 2606.03979) shows the *cost* upside is real
  (consolidate at idle; one result: baseline accuracy at 11k tokens vs 20k).

**BlarAI verdict:** the program's propose → verify → land shape is exactly the
published mitigation set, and the literature sharpens three M3 requirements the plan
doc encodes: candidates must carry **verbatim evidence quotes** (P2 extended to
Loop 2 — the miner may select and count, never paraphrase the evidence it cites);
the miner's output is **report-only** (drift cannot accumulate through a store the
miner cannot write); and consolidation runs **off the response path** in a
differently-privileged actor (the Letta sleep-time convergence).

### 4.4 The retired lead

**MEMSAD could not be verified** — no paper, benchmark, or system by that name
surfaced under multiple query framings. It should be treated as a garbled citation
from the 2026-07-09 pass and dropped from future reference lists (plausible
confusions: MPBench, Memora/FAMA, SSGM). Recorded here so the correction is on disk
(C8 — verify the premise before building on it).

---

## 5. Memory poisoning — the attack state of the art, and what M2 must test

### 5.1 Attacks and defenses since MINJA

The lineage: AgentPoison (arXiv:2407.12784) → MINJA (arXiv:2503.03704, >95%
injection success, query-only) → 2026 variants (MemoryGraft, Sleeper Memory,
Forged Reasoning Attacks — arXiv:2607.05029). OWASP's Agentic Top-10 2026 codifies
the class as **ASI06**, with cross-session persistence as the differentiator from
plain prompt injection. On defenses:

- **SMSR** (arXiv:2606.12703) — a *certified* defense: (1) write-time HMAC-SHA256
  provenance (**0% attack success on all unsigned-write variants**); (2) query-time
  randomized ablation + majority voting bounding even *authenticated* adversaries
  to 8% ASR. The certified result restates BlarAI's own bet in cryptographic form:
  **authenticate the write path and the injection class dies.** BlarAI's analogue
  is stronger than an HMAC — the write path *does not exist* for the model (P8
  structural absence, lock-tested), and rows are AAD-bound at rest (ADR-025).
  Component (2) (ablation voting) is REFERENCE-ONLY: it defends *extracted* memories
  of uncertain provenance, a store class BlarAI refuses to have.
- **A-MemGuard** (arXiv:2510.02373) — consensus-based validation across related
  memories + a dual-store distilling detected failures into consulted "lessons";
  >95% ASR reduction. REFERENCE-ONLY for the preference tier (consensus across a
  64-row operator-authored tier is meaningless), but its *failure-lessons-as-
  separate-store* idea is, amusingly, the M3 miner's exact shape on the fleet side.
- The systematic study's defense list — scope-limited write policies, source
  isolation, provenance-tracked retrieval, compaction source-filtering — reads as
  a checklist BlarAI passes by construction. The one it must *keep* passing as M2
  adds the propose flow: **source isolation between the proposal channel and the
  write channel.**

### 5.2 The test taxonomy M2 should build on (the study's most actionable find)

*From Untrusted Input to Trusted Memory* (arXiv:2606.04329) + **MPBench** (3,240
adversarial / 2,997 benign cases) give a ready-made red-team frame:

- **Four write channels:** C1 explicit-instruction ("remember that…" in content),
  C2 policy-driven (content shaped to satisfy an auto-capture policy), C3
  compaction-driven (poison survives/steers summarization), C4
  experience-to-procedure (poisoned outcomes become learned rules).
- **Six attack classes by signal strength** — the finding that matters: a
  commercial prompt-injection screen caught **84.4% of strong-signal** attacks
  (explicit/conditional commands) but only **42.5% of weak-signal** ones
  (policy-conformant fact injection, false precedents, procedure insertion) —
  weak-signal content is semantically indistinguishable from legitimate memory.
  **Classifier defenses cannot close the gap; write-path structure can** — the
  MINJA authors' conclusion, now measured.
- **Three objectives per test case:** trigger a write, control the content,
  trigger retrieval — with ASR (write success) and RSR (retrieval-given-write)
  as the metrics.

**Mapping to BlarAI surfaces** (the plan doc turns this into eval case classes):
channel C1/C2 → the M2 `propose_preference` surface and the ingest corridor
(a document attempting to plant or *induce* a proposal); C3 → structurally absent
today (no consolidation) — the eval asserts the absence and the class arms when
any summarization lands; C4 → the M3 miner (a poisoned scorecard attempting to
mint a lesson). BlarAI's M2 suite should deliberately include **weak-signal cases**
(a perfectly plausible "preference" a hostile document nudges the model to propose)
because those are the ones a card-reading operator is the last line against —
which is why the card must carry provenance ("proposed after reading document X")
and verbatim text, never a paraphrase.

### 5.3 Benchmarks for the eval suite's vocabulary

**Memora + FAMA** (Microsoft Research, 2026) is the first benchmark that rewards
correct use of valid memory *and penalizes reliance on superseded/deleted memory* —
exactly the last-writer-wins + audit-history semantics M1 shipped (eval class
`update_contradiction`). Worth citing as the external validation frame for eval
cases, and worth borrowing its negative-reliance framing: an M2/M3 eval case where
the model must NOT apply a *superseded* preference is currently implicit (the old
form is absent from the render) — FAMA suggests also testing the confabulation path
(model recalls the superseded value from conversation history and applies it anyway).
Also on the watchlist: MPBench (above), MemGym (arXiv:2605.20833), Supersede
(arXiv:2606.27472), From Recall to Forgetting (arXiv:2604.20006).

---

## 6. Consolidated verdict table

| # | Idea | Source | Verdict | Lands where |
|---|---|---|---|---|
| 1 | Curated pinned index + searchable episodic archive (two-layer) | OpenClaw, Letta, opencode plugin | ALREADY BUILT (pinned half) / LATER (episodic tier, own ADR) | Later phase |
| 2 | Store-authoritative, rebuildable index | OpenClaw ↔ ADR-031 L2 | ALREADY BUILT (validation) | — |
| 3 | Embedding-model/version stamp + fail-closed identity check on the vector limb | OpenClaw "index identity" | ADOPT (small hardening) | ticket (optional, any sprint) |
| 4 | RRF hybrid recall | already shipped (#655) | ALREADY BUILT; do not churn to weighted fusion | — |
| 5 | MMR diversity + min-score floor + retrieval-time temporal boost | OpenClaw retrieval config | LATER (episodic-tier tuning; floor also aids abstention) | Later phase |
| 6 | Hybrid-vs-vector measured A/B on own recall evals (community-grade data) | §4.2 literature gap | ADOPT (optional, measurement-only) | ticket (optional) |
| 7 | Write-door budget refusal vs silent injected-copy truncation | BlarAI M1 vs OpenClaw | ALREADY BUILT, BlarAI stronger | — |
| 8 | Pre-lossy-step memory flush | OpenClaw | REFERENCE-ONLY (no lossy step exists) | note only |
| 9 | Background consolidation w/ promotion gates + staged human review | OpenClaw dreaming, Letta sleep-time | ADAPT — shape only (propose→verify→land); model-as-writer REJECTED (P8) | M3 miner |
| 10 | Consolidator in a separate, differently-privileged actor, off the response path | Letta sleep-time | ADOPT (M3: post-pass job, not the AO) | M3 |
| 11 | No-hidden-state transparency: every memory class ships its listing surface; injection observability | OpenClaw | ADOPT (principle; `/preferences` already conforms) | M2/M3 rule + Later debug surface |
| 12 | Operator-stated expiry on a preference (scoped instruction ≠ decay) | OpenClaw action-sensitive annotations | [DECISION] for the LA | plan doc §2 (M2 option) |
| 13 | Storage decay (FadeMem-class) on preferences | FadeMem | REJECT (P6 reaffirmed) | — |
| 14 | Retrieval-time recency boost on episodic memories | OpenClaw / lit. | LATER (with episodic tier) | Later phase |
| 15 | SAGE-style vMF novelty gate (advisory dedup signal) | SAGE | ADOPT-candidate — M3 miner dedup; advisory beside M2's Jaccard | M3 (+M2 option) |
| 16 | Signed/authenticated write path as THE poisoning defense | SMSR (certified), MINJA | ALREADY BUILT structurally (P8 + AAD); keep as invariant across M2 | M2 red-team asserts it |
| 17 | MPBench 4-channel / 6-class / ASR-RSR red-team taxonomy incl. weak-signal cases | arXiv:2606.04329 | ADOPT — the M2 eval-case-7 frame | M2 |
| 18 | FAMA negative-reliance metric (penalize using superseded memory) | Memora/FAMA | ADOPT — extra eval case class | M2 eval |
| 19 | Proposal cards carry provenance + verbatim text | derived (§5.2) | ADOPT — M2 card requirement | M2 |
| 20 | Entity linking, temporal knowledge graphs, memory-router proxies, ablation-voting retrieval | mem0/Zep/Supermemory/SMSR-c2 | REFERENCE-ONLY / REJECT (named per row above) | — |

---

## 7. Sources

**OpenClaw:** docs.openclaw.ai (concepts/memory, concepts/memory-builtin,
reference/memory-config); github.com/openclaw/openclaw docs; Zilliz/Milvus
"memsearch" reverse-implementation (milvus.io blog, 2026-02-13); PingCAP local-first
RAG analysis; "Taming OpenClaw" arXiv:2603.11619; Imperva message-object injection
write-up; CVE-2026-25253; openclawpulse.com security guide 2026; manthanguptaa.in +
gaodalie.substack.com memory-system analyses. *(Confidence: layout, 70/30 hybrid,
400/80 chunking, files-authoritative, dreaming gates corroborated across docs +
independent reverse-engineering; fine config defaults single-sourced.)*

**Ecosystem:** github.com/joshuadavidthomas/opencode-agent-memory;
hindsight.vectorize.io; supermemory.ai docs + github.com/supermemoryai/supermemory;
github.com/elizaOS/agentmemory + the local-MCP-memory server class (sqlite-memory,
mcp-local-memory, ai-memory-mcp); letta.com blog (sleep-time compute, agent memory)
+ docs.letta.com; langchain.com/blog/langmem-sdk-launch;
platform.claude.com/docs memory-tool + anthropic.com/news/context-management;
mem0.ai/blog/state-of-ai-agent-memory-2026; blog.cloudflare.com agent-memory;
graphlit.com framework survey.

**Literature:** SAGE arXiv:2605.30711; FadeMem arXiv:2601.18642 (+FSFM
arXiv:2604.20300); A-MemGuard arXiv:2510.02373; MemGuard-contamination
arXiv:2605.28009; SMSR arXiv:2606.12703; multi-factor value model arXiv:2606.12945;
AdaMem arXiv:2606.21144; storage-to-experience survey arXiv:2605.06716; sleep-time
arXiv:2605.26099 + arXiv:2606.03979; SSGM arXiv:2603.11768; Memory Contagion
arXiv:2606.23195; Remembering More, Risking More arXiv:2605.17830; untrusted-input
taxonomy + MPBench arXiv:2606.04329; Forged Reasoning Attacks arXiv:2607.05029;
AgentPoison arXiv:2407.12784; MINJA arXiv:2503.03704; OWASP Agentic Top-10 2026
(ASI06); LongMemEval arXiv:2410.10813; Memora+FAMA (MSR 2026); MemGym
arXiv:2605.20833; Supersede arXiv:2606.27472; From Recall to Forgetting
arXiv:2604.20006. **Retired:** MEMSAD (unverifiable — see §4.4).
