# Web-Search Skill — Method Harvest and Kagi API Evaluation

**Purpose:** W1 research artifact for the Agentic Web-Search Skill (Vikunja #572).
Documents the method harvest from three reference implementations and the full
Kagi API evaluation that informs the W2–W5 design in
`docs/adrs/ADR-024-Agentic-Web-Search-Skill.md`.

**Date:** 2026-06-04
**Author:** Claude Sonnet 4.6 (research-specialist)

---

## Part 1 — Method Harvest

The three projects surveyed are the closest published prior art to BlarAI's
intended agentic loop. None is adoptable wholesale: all carry cloud-LLM
assumptions, framework weight, or supply-chain surface that BlarAI's mandate
(local-only, OpenVINO, Policy-Agent gate, fail-closed egress) cannot accept.
The goal is to extract the *method* — the algorithmic shape — while leaving the
framework and dependency footprint behind.

### 1.1 LearningCircuit / local-deep-research

**What it does.** Multi-strategy research agent using LangGraph orchestration.
Supports Ollama, llama.cpp, and cloud LLMs; 20+ search-engine integrations
including arXiv, PubMed, Brave, SearXNG, Tavily. Claims \~95% on the SimpleQA
benchmark using Qwen3.6-27B on a local GPU.

**How query decomposition works.** The LLM receives the user question and
generates a set of targeted sub-questions, each scoped to a different angle of
the topic (temporal, technical, definitional, etc.). The `AdvancedSearchSystem`
coordinator routes each sub-question to a dynamically chosen search engine
(the agent selects from the available set based on question type — academic
queries go to arXiv/PubMed, current-events go to web engines). The system does
not use a fixed decomposition count; the LLM decides breadth.

**The iterative loop.** Each sub-question drives a search → content-extraction
→ relevance-filter → embedding/index pass. Results are inserted into a
LangChain-compatible vector store (FAISS, Chroma, Pinecone, etc.) that serves
as a compound knowledge base. After the initial sweep, the LLM performs a gap
analysis — comparing what it knows against what the original question requires
— and generates follow-up queries targeting the identified gaps. This gap-driven
second pass is the key insight: the system does not commit to a fixed number of
searches up front; it searches until the LLM judges coverage sufficient or until
a configured time/budget limit fires.

**Stopping criteria.** Four conditions can terminate the loop: (a) the LLM
judges the information complete, (b) source saturation (search results stop
returning new URLs), (c) a maximum research-duration wall-clock timeout (the
documentation cites a 30-second to 30-minute configurable window), or (d) a
token/API cost budget cap. In practice, most runs terminate on (a) or (c).

**Citation and grounding.** Every chunk ingested is stored with its source URL
and, where available, publication date. The final synthesis prompt injects these
citations into the LLM context; the LLM is instructed to produce inline
citations anchored to the indexed sources. The database maintains full source
provenance for every claim.

**What is worth borrowing.**
- The gap-analysis pass as a second query wave rather than a fixed-depth tree.
  This is more token-efficient than GPT-Researcher's recursive branching when
  the answer is shallow, because the gap-analysis step can return "no gaps —
  synthesize now" on easy questions.
- The fail-soft design for engine unavailability: each engine adapter returns an
  empty result set rather than raising, so a missing API key degrades gracefully.
- The SQLCipher encrypted local database pattern for session persistence — not
  needed for W1–W3, but relevant for future history/caching.

**What to leave behind.**
- LangGraph as the orchestration substrate: this is the central framework
  dependency. BlarAI's agentic loop is implemented in plain `asyncio` over the
  existing AO pipeline; bolting in LangGraph would introduce a large graph
  dependency with its own network-call footprint and version-drift risk.
- The multi-engine abstraction layer: BlarAI has exactly one search engine
  (Kagi), period. A multi-engine router adds complexity without value.
- Ollama/llama.cpp LLM abstractions: BlarAI uses OpenVINO GenAI on-device;
  the LLM adapter shim is already implemented.
- The Flask web-UI and REST-API layers: not needed for a TUI-integrated skill.

---

### 1.2 assafelovic / gpt-researcher

**What it does.** Planner-executor-publisher research agent. The standard mode
does a single planning pass (decompose question → generate search queries →
execute searches in parallel → scrape → summarize → generate report). The deep
research mode is architecturally more interesting and maps better to BlarAI's
use case.

**How query decomposition works.** A "planner" LLM call takes the user question
and generates a set of focused investigative sub-questions. For a question like
"what is the state of quantum computing error correction?" it might generate
three sub-questions targeting recent breakthroughs, financial/industry adoption,
and the leading error-correction approaches. Each sub-question gets its own
search-and-scrape pass.

**The deep-research loop (the relevant mode).** This is a breadth-depth
recursive tree. Three configuration parameters govern it: `deep_research_depth`
(default 2), `deep_research_breadth` (default 4), and
`deep_research_concurrency` (default 2). At each tree node:

1. An LLM call (`generate_research_plan`) produces targeted investigative
   questions from the current context.
2. An LLM call (`generate_search_queries`) converts those questions into search
   engine query strings.
3. Searches execute within the concurrency semaphore.
4. An LLM call (`extract key learnings and citations`) distills the raw HTML
   into structured learnings + source URLs.
5. If `depth > 0`, the system recurses — each branch feeds its learnings as
   context into the next depth level's planning step.

Context is trimmed to 25,000 words across the accumulated learnings to prevent
context overflow. Visited URLs are tracked to avoid redundant fetches.

**Stopping criteria.** Recursion terminates when `depth` reaches zero. There is
no LLM-driven gap analysis as a stopping condition; the tree is fully structural.
This is a weakness for BlarAI's use case: a shallow question does the same work
as a deep one, spending budget unnecessarily.

**Citation assembly.** Citations are tracked through the tree at the learning
extraction step. Each learning carries its source URL; the final synthesis LLM
call receives the full set of (learning, source) pairs and is instructed to
produce inline citations. Reports target approximately 2,000 words.

**Latency and cost.** The project's own documentation cites \~5 minutes and
\~$0.40 per deep-research query at depth=2, breadth=4 using o3-mini. This is
with cloud LLMs where the thinking dominates; local inference on 14B is slower
per token but the total is more controllable.

**What is worth borrowing.**
- The learning-extraction step: rather than injecting raw HTML snippets into the
  synthesis context, a dedicated LLM call distills each source into a
  (fact, citation-URL) pair before accumulation. This reduces context pressure
  and improves synthesis quality — the synthesizer reasons over distilled
  learnings rather than noisy scraped text.
- Concurrency limiting via `asyncio.Semaphore` with a configurable ceiling —
  the BlarAI adapter will need exactly this to prevent hammering Kagi.
- The visited-URL deduplication set across loop iterations.

**What to leave behind.**
- Fixed-depth recursion: the tree model over-searches for simple questions and
  under-searches for questions where the key gap is discovered late. The
  gap-analysis model from local-deep-research is a better fit.
- The LangGraph + AG2 multi-agent infrastructure for the planner/executor
  split: this is framework weight on top of what can be a simple async function
  with a state struct.
- The web-scraper/crawler infrastructure: BlarAI uses Kagi's Universal
  Summarizer or raw-fetch to extract source content, not a separate crawler
  agent. The crawler layer in GPT-Researcher is also the primary supply-chain
  surface (dozens of parser dependencies).

---

### 1.3 langchain-ai / open_deep_research

**What it does.** LangGraph state-machine research agent designed to produce
PhD-level research reports. Uses "plan-and-execute" with a compression step.
Primary dependencies: LangGraph, Tavily (default search), and either Anthropic
or OpenAI for inference.

**How query decomposition works.** A plan-generation node produces a structured
outline for the final report — sections, each with its own research focus. Each
section then drives its own search-read-synthesize pass. This is a fundamentally
different shape from the other two: it is outline-first rather than
question-first.

**The loop.** For each section: search → retrieve → LLM-compress results into
findings → move to next section. A reflection pass after each section creates
follow-up sub-queries when the LLM judges coverage incomplete. Final synthesis
assembles the section findings into a coherent report.

**Stopping criteria.** The reflection pass drives stopping: if the LLM produces
no follow-up queries for a section, that section is considered complete. This is
a per-section variant of the gap-analysis model.

**What is worth borrowing.**
- The per-section reflection/gap-detection as a stopping signal: rather than a
  global gap pass, this is more granular. For BlarAI's use case (a direct
  answer rather than a structured report), the equivalent is a global gap pass
  after the first search wave that decides whether a second wave is needed.
- The use of a compression/summarization step before context injection — the
  "Summarizer" model is separate from the "Planner" model. In BlarAI this maps
  to: use Kagi Universal Summarizer (or local fetch+extract) to compress source
  pages before injecting them as context for the 14B synthesizer.

**What to leave behind.**
- LangGraph state-machine as the implementation substrate: same objection as
  with local-deep-research. BlarAI's loop is a plain Python async function with
  a typed state struct; a graph framework adds nothing but dependency surface.
- The outline-first report structure: BlarAI answers questions, it does not
  produce Wikipedia-style structured reports. The outline-first shape is
  optimized for a different output format.
- Tavily as the search engine: Kagi is the mandated, privacy-respecting choice.

---

### 1.4 Cross-Project Method Synthesis

The three implementations converge on a common algorithmic skeleton despite
their architectural differences:

```
1. Query decomposition: user question → N targeted sub-questions (LLM call)
2. For each sub-question: query string(s) → search → retrieve results (N=3–10)
3. Source triage: rank/filter results by relevance; select M sources (M <= N)
4. Content extraction: fetch selected sources; extract/compress text (LLM call or API)
5. Learning accumulation: (extracted text, source URL) → structured learning (LLM call)
6. Gap analysis: accumulated learnings vs original question → gaps identified? (LLM call)
7. If gaps exist and budget permits: generate follow-up queries (LLM call) → goto 2
8. Final synthesis: learnings + sources → cited answer (LLM call)
```

**The architectural divergence is in step 6.** GPT-Researcher uses a structural
recursion (depth parameter governs when to stop, not the LLM's judgment).
Local-deep-research and open_deep_research use LLM-driven gap detection (stop
when coverage is judged complete). The LLM-driven model is more efficient on
easy questions and more expensive on hard ones; the structural model is
predictable but wastes budget on simple questions.

**BlarAI's choice:** LLM-driven gap detection, capped by a hard maximum
iteration count (2 passes by default). This gets the efficiency benefit for
simple questions (most real queries are simple) while bounding the worst case.

**The content extraction seam is the main design decision** for BlarAI's W2/W3:
whether to use Kagi's Universal Summarizer (server-side, $0.03/1k tokens) or
local fetch + extraction (no cost, but requires an HTTP fetch capability that
W4 gates). This is resolved by the W4 security gate design: W1–W3 mock the
fetch; W4 wires the real Kagi calls through the egress proxy and Policy Agent.

---

## Part 2 — Kagi API Evaluation

### 2.1 API Inventory and Pricing

All four Kagi APIs are relevant to the BlarAI web-search skill. Here they are
with their properties:

**Search API**
- Endpoint: `GET https://kagi.com/api/v0/search?q={query}&limit={n}`
  (v1 endpoint also available; v0 is the documented production path)
- Authentication: `Authorization: Bot {TOKEN}` header
- Response: JSON with `meta` (id, node, ms, api_balance) and `data` array.
  Each result object: `t` (type: 0=result, 1=related), `rank`, `url`, `title`,
  `snippet`, `published` (ISO date where available), `thumbnail` (url/w/h).
- Pricing: **$12 per 1,000 queries** ($0.012 per query) as of 2026. Pay-per-use.
- Latency: No published SLA; Kagi's own user-facing search targets sub-second.
  API calls from the same node infrastructure. Expect 300–800 ms round-trip in
  practice.
- Notes: Respects account-level personalization (site blocking/promoting, snippet
  length). The `limit` parameter caps the result count (10 is a reasonable
  ceiling for the agentic loop; 5 for follow-up queries).

**Universal Summarizer**
- Endpoint: `GET/POST https://kagi.com/api/v0/summarize`
- Input: `url` parameter (Kagi fetches and summarizes the page server-side) OR
  `text` parameter (submit raw text). Additional optional params: `engine`
  (Cecil/Agnes consumer-grade, Muriel enterprise), `summary_type`,
  `target_language`, `cache` (free cache retrieval).
- Response: `{ output: "<summary text>", tokens: N }`. Token count covers both
  input and output.
- Pricing: Consumer (Cecil/Agnes): **$0.030 per 1,000 tokens**; with Kagi
  Ultimate subscription: $0.025/1k tokens. Enterprise (Muriel): **$1.00 flat
  per summary** regardless of document length. Cached summaries are free.
  Practical cost for a 5,000-word web article (approx. 6,500 tokens): \~$0.20
  per summary at consumer tier, $1.00 at Muriel. For a lean loop using 5
  sources per query, the Summarizer is $0.10–$1.00 per research question at
  consumer tier — potentially more expensive per search than the Search API.
- Latency: Varies by engine and document complexity. Not published; Muriel
  (enterprise) will be slower than Cecil/Agnes.
- Handles: text, PDFs, PowerPoint, Word, audio (mp3/wav), scanned PDFs (OCR),
  YouTube videos (experimental).
- Role in the agentic loop: content extraction step — replaces local fetch +
  parser for non-trivial sources. Deferred to W4 (live calls gated); W1–W3 mock
  it.

**FastGPT**
- Endpoint: `POST https://kagi.com/api/v0/fastgpt`
- Request: `{ query: "...", cache: true, web_search: true }`
- Response: `{ output: "<answer>", references: [{title, snippet, url}], tokens: N }`
- Pricing: **$0.015 per query** ($15 per 1,000 queries) with web search enabled.
  Cached responses are free.
- Latency: Example response time published in docs: \~7,943 ms (approximately
  8 seconds). This is the end-to-end wall-clock for a live search + synthesis
  call.
- What it does: Kagi's servers search the web, then a Kagi-hosted LLM synthesizes
  the answer, then the synthesized text plus source URLs are returned. The entire
  query-decompose / search / synthesize loop runs on Kagi's infrastructure.
- Privacy implication: The user's query leaves the device, the full synthesis
  reasoning happens on Kagi's servers, and only the result returns. BlarAI's
  data stays within the Kagi privacy model (Kagi does not sell data to
  advertisers and does not train models on query data), but the *thinking* is
  not on-device.
- Role in the agentic loop: A potential full-loop shortcut — one call replaces
  steps 1–8. See the A-vs-B decision in the ADR.

**Enrichment APIs (Teclis / TinyGem)**
- Endpoints: `GET https://kagi.com/api/v0/enrich/web?q={query}` (Teclis — web)
  and `GET https://kagi.com/api/v0/enrich/news?q={query}` (TinyGem — news).
- Response: Same structure as Search API — array of result objects with title,
  URL, snippet, published date, rank.
- Pricing: **$0.002 per query** ($2 per 1,000 queries). Only billed when the
  result set is non-empty. Volume discounts available.
- What they cover: Teclis is Kagi's *non-commercial* web index — independent
  blogs, personal sites, GitHub projects, academic discussions, "small web"
  content that mainstream search engines deprioritize. TinyGem is the equivalent
  for news from non-mainstream, independent sources.
- Restrictions: Non-commercial use only (per Kagi documentation). BlarAI is
  personal/private-use — this is within scope. Any commercial deployment would
  need to re-evaluate.
- Role in the agentic loop: Optional supplementary source for technical or
  niche questions where mainstream search results are dominated by SEO content.
  A second pass with Teclis on technical queries (e.g., OpenVINO optimization,
  local AI hardware) may surface higher-quality sources than the main Search API
  at 1/6th the cost. Not in the W3 MVP; a follow-up enhancement.

---

### 2.2 Comparative Cost Model

A representative BlarAI research answer — one user question, four search
queries (1 initial decomposition + 1 follow-up wave of 3 sub-queries), and 4
source summaries — breaks down as follows under each option:

**Option A (Search API + local-14B synthesis):**
- 4 Search API calls at $0.012 each: $0.048
- 4 Universal Summarizer calls at \~$0.20 each (consumer, 5k-word pages): $0.80
  OR: skip the Summarizer, fetch raw text locally and extract with the 14B
  (zero marginal API cost, but more 14B context tokens consumed).
- 14B synthesis: zero marginal cost (local GPU).
- Total with Summarizer: \~$0.85 per answer. Without Summarizer: \~$0.05.
- The Summarizer is optional in W3: the W3 design can use local fetch+extract
  as the default and offer the Summarizer as a quality upgrade. The W4 gate
  wires either path through the egress proxy.

**Option B (FastGPT):**
- 1 FastGPT call: $0.015
- Zero other API costs.
- Zero local inference cost (no 14B used).
- Total: \~$0.015 per answer.

FastGPT is substantially cheaper per answer at this scale. The cost difference
inverts at high volume, but at personal-assistant usage (10–50 searches per day),
neither cost is significant. The decision rests on privacy, control, and the
architectural seam, not on cost.

---

### 2.3 Latency Comparison

**Option A:** The loop latency is dominated by the number of serial search +
extract rounds. With one decomposition pass (3 searches, 3 extractions), one
gap-fill pass (2 searches, 2 extractions), and a final synthesis:
- 5 search calls at \~500 ms each: 2,500 ms (parallelizable within one pass)
- 5 Summarizer calls at \~2,000 ms each: 10,000 ms (can be parallelized)
- 14B synthesis at \~8,000 ms (cold, \~3,000 ms warm): 3,000–8,000 ms
- End-to-end estimate: 10–20 seconds with parallelized fetches, dominated by
  content extraction.

**Option B:** FastGPT latency: \~8 seconds (from Kagi documentation example).
This is fixed per query; it does not scale with question complexity.

For BlarAI's use case (a single user at a personal workstation), 10–20 seconds
is acceptable. Option A's end-to-end is in the same range as FastGPT with
careful parallelism.

---

### 2.4 Privacy Analysis

**Option A.** The only data that leaves the device is: (a) the search query
strings (decomposed sub-questions, not the raw user text unless the 14B
formulates them that way), and (b) the URLs of selected sources passed to the
Summarizer. The full conversation context, all intermediate reasoning, and the
final synthesized answer stay on-device. Kagi's privacy policy prohibits selling
query data or training models on it.

**Option B.** The user's question (or a rephrased version) leaves the device
and the synthesis happens on Kagi's servers. The answer and source URLs return
to BlarAI. The user's data is within Kagi's privacy model but the reasoning is
not local. For BlarAI's privacy mandate, this is a philosophically significant
difference — even though Kagi is a privacy-respecting service, the *design
principle* is that the user's thinking happens on the user's hardware.

---

## Part 3 — Reference Links (Sources)

- LearningCircuit/local-deep-research: https://github.com/LearningCircuit/local-deep-research
- local-deep-research FAQ: https://github.com/LearningCircuit/local-deep-research/blob/main/docs/faq.md
- assafelovic/gpt-researcher: https://github.com/assafelovic/gpt-researcher
- GPT-Researcher deep research mode: https://deepwiki.com/assafelovic/gpt-researcher/4.3-deep-research-mode
- GPT-Researcher deep research blog: https://docs.gptr.dev/blog/2025/02/26/deep-research
- langchain-ai/open_deep_research: https://github.com/langchain-ai/open_deep_research
- Kagi API overview: https://help.kagi.com/kagi/api/overview.html
- Kagi Search API: https://help.kagi.com/kagi/api/search.html
- Kagi FastGPT: https://help.kagi.com/kagi/api/fastgpt.html
- Kagi Universal Summarizer: https://help.kagi.com/kagi/api/summarizer.html
- Kagi Enrichment API: https://help.kagi.com/kagi/api/enrich.html
- Kagi API Python client: https://github.com/kagisearch/kagiapi
- Kagi API pricing: https://kagi.com/api/pricing
