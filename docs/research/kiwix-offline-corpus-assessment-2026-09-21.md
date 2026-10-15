# Kiwix / ZIM as an offline knowledge and image source for BlarAI

**Assessment date:** 2026-09-21 (local, UTC−04:00)
**Question asked (Lead Architect):** Would it make sense to download Kiwix and use it with
BlarAI? Is it redundant with what Qwen3-14B already knows? Could its images be served inline?
Could it work as retrieval to reduce hallucination — while keeping response times fast?
**Status:** research spike. Nothing was built, nothing was merged, no flag was changed.
**Verdict:** **Adopt it.** Not redundant — the measurement is decisive and is in §1.

---

## Recommendation in one paragraph

Download the full English archive (118.7 GiB) — it is the only practical route to Wikipedia's
images at scale, and the model's own knowledge fails badly outside a narrow popular band. But do
**not** wire the archive into BlarAI as a runtime dependency. Convert it once, in the workshop,
into BlarAI's own read-only corpus, and retrieve **paragraphs, never articles**. That single rule
is the difference between a 0.74-second answer and a 25-second one. Index the text with SQLite
FTS5 — which BlarAI already uses — and embed only the handful of candidates a query actually
returns, rather than pre-embedding millions of chunks. Serve images by reference through the
`blarai-img://` rail that already works, with the picture attached to the paragraph and the
caption, not the pixels, carrying the meaning.

---

## 1. Is it redundant with Qwen3-14B? — No. Measured, not assumed.

### Method

Forty subjects, two strata of twenty, ground truth taken from the live Wikipedia summary endpoint:

- **head** — the most-read English Wikipedia articles for August 2026 (Wikimedia pageviews API).
- **tail** — uniformly random mainspace articles (MediaWiki `list=random`), which is what the mass
  of a 7-million-article encyclopedia actually looks like.

Each subject was put to the resident Qwen3-14B INT4 on the Arc 140V through
`OrchestratorGPUInference` — BlarAI's real engine, not a mock — greedy (temperature 0), 300 new
tokens, reasoning disabled via `/no_think`, with a system prompt instructing the model to reply
`I DO NOT KNOW` when unsure. Answers were graded **by reading them**; the content-word overlap
score in the raw results was only a screen and is not the verdict.

### Result

| | head (n=20) | tail (n=20) |
|---|---|---|
| Declined to answer | **9** | **16** |
| Attempted an answer | 11 | 4 |
| — of those, substantially correct | 5 | 3 |
| — of those, **confidently wrong or stale** | **6** | **1** |

**Across both strata, of the 15 answers the model attempted, 7 carried a confident error.**

### The three failure modes, with the actual output

**Fabrication.** Asked about *I Can See Your House from Here* — a 1979 album by the progressive
rock band Camel — the model replied: *"a 1993 American comedy-drama film directed by Randal
Kleiser. The film stars Patrick Swayze and Daryl Hannah and follows a man who moves into a house
and becomes involved with the mysterious woman who lives across the street."* Year, medium,
director, both stars and the plot were invented. Fluent, specific, and entirely false.

**Conflation.** Wladimir Klitschko was described as *"also a politician, having served…"* — that
is his brother Vitali, the mayor of Kyiv. A plausible neighbouring fact substituted for the real
one.

**Staleness stated as present fact.** Three of the head subjects (Hayden Panettiere, Dolly Parton,
Tim Curry) are described in Wikipedia's 2026 text in the past tense; the model spoke of all three
in the present, one with *"has had a long and influential career."* Dates were wrong in the same
family: `.xxx` was given as introduced in 2005 and `.xyz` in 2017; neither is right. A frozen model
does not merely lack recent facts — it asserts superseded ones with full confidence.

### What this measurement does and does not support

- **Supported, unambiguously:** the long tail is not in the model. Sixteen of twenty randomly
  drawn articles produced nothing usable. No plausible sampling noise turns 16/20 into parity.
- **Supported:** even inside the most-read band, the model's unassisted answers are unreliable at
  a rate that matters — more than half of its attempts contained an error.
- **A caveat that cuts against my own conclusion, stated plainly:** the prompt *explicitly invited*
  the model to say "I DO NOT KNOW." That is the best case for honesty. Ordinary conversation
  carries no such instruction, so the real-world split between refusal and fabrication is
  **worse** than measured here, not better. This probe understates the problem.
- **A confound named:** August 2026's most-read articles are dominated by 2026 events
  (*Deaths in 2026*, *The Odyssey (2026 film)*, *Spider-Man: Brand New Day*). The head stratum
  therefore measures recency as much as popularity. That is a genuine finding about what people
  actually read, but it means "head" here is not a clean popularity probe.
- **Not established:** the precise rates. n=20 per arm, one deterministic run each. The direction
  is beyond doubt; the percentages are indicative.
- **Conditions:** the 119 GiB archive download was running concurrently (network and B: disk).
  This affects the latency column of the raw results, which is not used for any claim here. It
  does not affect answer content.

Raw results, including every verbatim answer:
`scratchpad/probe_results.json` (40 rows; scratch, not committed).

---

## 2. What the archives actually are

Read from the live Kiwix index and OPDS catalogue on 2026-09-21, not from memory.

| Archive | Size | Entries | Images | What it contains |
|---|---|---|---|---|
| `wikipedia_en_all_maxi_2026-08` | **118.7 GiB** | 21,673,012 | 8,469,385 | full text + images |
| `wikipedia_en_all_nopic_2026-06` | 49.1 GiB | 19,191,219 | 515,775 | full text, no images |
| `wikipedia_en_top1m_maxi` | 46.0 GiB | 5,918,856 | 3,677,489 | top 1M articles + images |
| `wikipedia_en_all_mini_2026-09` | 13.4 GiB | 18,095,848 | 33,992 | lead sections only |
| `wikipedia_en_top_maxi_2026-09` | 6.5 GiB | 877,754 | 618,143 | most-read articles + images |

Entry counts include redirects; English Wikipedia holds roughly 7 million real articles.
Exact target size from the metalink: **127,418,087,648 bytes**, SHA-256
`34162d18…854aa6`, verified on completion.

Other corpora exist in the same format and the same way: Wiktionary 8.5 GB, Wikibooks 5.8 GB,
Wikisource 18 GB, Stack Overflow 107 GB, Project Gutenberg 206 GB, a medical corpus at 2.1 GB.
None is needed to answer this question; all are available later at no new engineering cost.

**Disk.** B: (`AI`, Crucial P310 NVMe) had 645.9 GB free. The full archive leaves ~518 GB.
C: has only 62.3 GB free and is not a candidate.

---

## 3. Speed — the archive is free; the context is the entire budget

Measured on this machine, with BlarAI's own tokenizer and the engine's published prefill rate.

**Reading from the archive is negligible.** On a sample archive with a warm cache:
full-text search **0.06 ms**, article fetch **2.03 ms** (median, n=40), image fetch **0.03 ms**,
title suggestion 0.20 ms. Archives ship their own Xapian full-text index; no index needs building
to search them.

**Feeding the model is the whole cost.** Wikipedia tokenizes at **3.09 characters per token**
(measured with the Qwen3-14B tokenizer over three full articles — denser than ordinary prose,
because of proper nouns). Against the 1,960 tok/s prefill recorded for Qwen3-14B INT4 on the
Arc 140V in `PERFORMANCE_LOG.md`:

| Injected context | Tokens | Added latency |
|---|---|---|
| 3 paragraphs × 800 chars | 777 | **+0.40 s** |
| 5 paragraphs × 800 chars | 1,295 | **+0.66 s** |
| 3 paragraphs × 1,500 chars | 1,457 | **+0.74 s** |
| 5 paragraphs × 3,000 chars | 4,855 | +2.48 s |
| **one whole article** (mean 48,342 tok) | 48,342 | **+24.7 s** |
| three whole articles | 145,026 | +74 s |

**The design rule falls straight out: retrieve paragraphs, never articles.** On a 466 ms baseline
TTFT, three good paragraphs are an imperceptible change and one whole article is a broken product.

**BlarAI already enforces close to the right budget, and this is worth knowing before anything is
built.** The existing retrieval tool caps a result at `RETRIEVAL_RESULT_MAX_CHARS = 4000`
(`tools.py:213`) across `retrieve_k = 4` chunks (`default.toml:196`, clamped 1–8 on the tool path),
with chunks cut at 2048 characters and 256 overlap (`substrate.py:109-110`). Four thousand
characters is **~1,294 tokens ≈ +0.66 s** — squarely inside the recommended band. The cap was set
for a 15-chunk store, but it happens to be the right cap for an encyclopedia too.

**The budget is not new, and it is already spent every turn.** A per-prompt auto-recall calls
`_knowledge_retrieve` on every user message with no model decision (`entrypoint.py:7542`),
suppressed only when a document was loaded that same turn, and `context_manager.trim_to_budget`
makes room by dropping older conversation. This happens today, against a 15-chunk store that has
almost nothing to give. An encyclopedia does not introduce a context cost — it fills a budget the
system already allocates and already pays.

**But that path has a defect that must be fixed before an encyclopedia joins it**, and the
obvious fix does not work. See §7b, which supersedes an earlier draft of this paragraph that
claimed two cheap controls would close it. They would not.

**The remaining ceiling is a decision rather than a defect.** The Assistant
Orchestrator runs a `max_context_tokens = 4096` window (`default.toml:125`,
`context_manager.py:213`). A full 4,000-character retrieval consumes about **a third of the entire
window**, competing with the system prompt and the conversation so far. Wikipedia does not strain
the disk or the prefill; it strains *that budget*. Raising the window is possible — the model
supports far more — but this machine's own measurements show long contexts are expensive here
(prefill at 16K measured in the tens of seconds), and raising it changes memory behaviour and
answer quality. **That is a capability decision for the Lead Architect, not a technical one, and
it is flagged rather than assumed.** The recommendation below is deliberately sized to fit inside
4,096 tokens unchanged.

*Not yet measured:* cold-cache retrieval from the full 118.7 GiB archive, which cannot be held in
32 GB of RAM the way the sample can. That measurement is queued against the real artifact; the
expected effect is one or two NVMe reads — immaterial beside a 0.4 s prefill, but it will be
measured rather than assumed.

---

## 4. Images — your instinct is right, with one correction

**87% of Wikipedia figures carry a real caption.** Sampled across three articles: 77 `<figure>`
blocks, 67 with a non-empty `<figcaption>`, median 91 characters, specific and descriptive — e.g.
*"From space, the Moon's shadow during the solar eclipse of March 9, 2016 appears as a dark spot
moving across Earth."* Alt text is effectively absent (1 of 77). Images are already
web-optimised: `image/webp` in current builds, median a few KiB, addressed as
`_assets_/<hash>.<ext>` relative to the article.

**The correction: a vector database of images needs no image model.** Embed the **captions** with
the bge-small encoder BlarAI already runs on the NPU, and attach the picture to the text chunk by
reference. That is cheaper than embedding pixels and more accurate for this corpus, because a
caption states what a picture is *for*.

It also happens to satisfy a constraint BlarAI's own code already insists on — see §5.

---

## 5. What BlarAI already has (the genuine surprise)

There is **no prior mention of Kiwix, ZIM or Wikipedia anywhere in the repository** — no ADR, no
ticket, no journal entry. This has never been considered. But the ground is better prepared than
that suggests.

**A complete article-image pipeline exists, built and welded shut, with zero rows in it.**
`knowledge_images` (`knowledge_bank.py:193-206`) carries encrypted bytes, AAD-bound metadata,
keyed-hash deduplication, an approval lifecycle, MIME re-validation, a decompression-bomb ceiling,
orphan refusal, and a 20-images-per-article cap. `store_image`, `get_images_for_doc`,
`get_knowledge_image` and `image_count` are all implemented. Alt-text escaping is always-on.

Its schema comment states the design constraint in one line:
*"These rows are NEVER chunked / embedded / indexed / sent to any model."*
**The caption-embedding design in §4 satisfies this exactly** — text is embedded, pixels are not.

**Four locks hold it shut, and only one is a flag:**

1. `[knowledge] images_enabled = false` (`default.toml:210`).
2. An egress purpose-deny on `uc003-image-ingest` in the shared Policy-Agent adjudicator, whose
   lifting is a separate ceremony (ADR-032 Am.1).
3. The only writer is bound to URL ingest, itself dormant at rest because a normal boot never starts the guest parser (only `--go-live` does).
4. **Structural:** `bank.get_display_image_by_id` does not exist. `generated_image_resolver.py:101`
   probes for it by `getattr`, receives `None`, and line 102 never runs. Flip every flag and a
   stored image still cannot reach the screen.

**Locks 2 and 3 are not on a Kiwix path at all.** They exist because article images were designed
to be fetched *from the internet*. An image read out of a local archive file crosses no network
door, invokes no `guarded_fetch`, and needs no egress ceremony. That removes the two hardest locks
from the problem by construction — an example of the structural-absence principle working in our
favour rather than against us.

**The rail to the screen is already live.** `/illustrate` (UC-010, live since 2026-06-16) returns
a `blarai-img://<uuid>` reference inside ordinary markdown in the reply text; the client then
fetches the pixels on a separate `IMAGE_RESOLVE_REQUEST` RPC, base64-chunked under a hard 2 MiB
cap, and renders them inline. No image bytes ever ride the token stream, and no file is written to
disk. An encyclopedia image can use this rail unchanged. The missing piece is the one resolver
function in lock 4.

**What can be reused: the tool surface.** `search_knowledge` is already registered as the one
retrieval tool the model may call (`tools.py:797`, runner at `entrypoint.py:7104`), and it returns
plain labelled text — `[From your knowledge bank: '<label>']\n<chunk>` (`entrypoint.py:6875`).
An encyclopedia tier fits that shape exactly, labelled `[From Wikipedia (2026-08 snapshot):
'<article title>']`, which gives citation for free and keeps provenance visible to both the model
and the reader. There is also a per-prompt auto-recall that retrieves with no model decision
(`entrypoint.py:7542`); whether Wikipedia joins that path or stays behind the explicit tool is a
latency-versus-grounding trade, and the safe default is the explicit tool first.

**What cannot be reused: the knowledge bank's storage and search.** It decrypts every approved
chunk into RAM at construction, rebuilds an in-memory FTS5 index from scratch at every boot, and
does brute-force cosine over a matrix rebuilt per query. It holds 8 documents and 15 chunks today.
Four independent walls stand between that and an encyclopedia:

1. Boot decrypts the whole corpus into RAM (`knowledge_bank.py:2625-2703`) — no lazy load, no cap.
2. Every query rebuilds the full vector matrix with `np.vstack` from N small arrays
   (`:2578-2581`) — ~1.5 GB copied per retrieval at 1M chunks.
3. Every query does a full `argsort` over all N scores and materialises N tuples in Python
   (`:2582`) to serve a budget of four; `argpartition` appears nowhere.
4. **The lexical limb has no `LIMIT` and calls `fetchall()`** (`:2586-2592`), then fuses both
   complete rankings before slicing. This is the one that fails first, because it is triggered by
   an ordinary common word rather than by corpus size — a single frequent term against millions of
   paragraphs returns millions of rows into a Python list.

A Wikipedia corpus must therefore be a **separate, read-only tier** with its own on-disk index —
not an enlargement of the knowledge bank. Pouring 7 million articles into it would break the
surface BlarAI actually depends on today.

---

## 6. Licensing — the one decision that is genuinely yours

**The Python reader for these archives is GPL-3.0-or-later.** Confirmed directly from the
installed package's own metadata (`License-Expression: GPL-3.0-or-later`, full GPLv3 text
bundled), not from a badge. So is every other reader that can query the embedded Xapian index;
a researcher checked the alternatives and the permissively-licensed readers (Rust `zim`,
Apache-2.0/MIT; Go `gozim`, MIT) can read the format but **cannot use the shipped search index** —
they would require building a second index from scratch. No linking exception, FAQ answer or
carve-out is published by the openZIM or Kiwix projects; the one on-point GitHub issue has no
maintainer response.

**BlarAI ships under PolyForm Noncommercial 1.0.0 with a separate commercial licence.** That is
GPL-incompatible for distribution, and the project has already made this call once: ADR-009
rejected PyQt6 partly on GPL risk.

**This does not block adoption.** It decides *where the reader runs*:

| Route | GPL in shipped source? | New attack surface? | Keeps Xapian? |
|---|---|---|---|
| **A. Workshop conversion (recommended)** | **No** | **None** | No — replaced by FTS5 |
| B. Local `kiwix-serve` process over loopback | No (arm's length) | **Yes — an HTTP listener** | Yes |
| C. Import the reader into the runtime | **Yes — conflicts** | None | Yes |

**Recommended: A.** It is the identity-split principle applied exactly — a GPL tool used in the
workshop to produce data, with nothing GPL in the product. The archive becomes a *delivery
format*, read once during conversion and never again at runtime. It adds no listening socket, no
new adjudication door, and no licence entanglement. The cost is that we build our own index
instead of inheriting Xapian — and since BlarAI already uses SQLite FTS5 with BM25 for the lexical
limb of its hybrid search, that is a shape the project has already proven rather than a new one.

*Content licence:* Wikipedia text is CC BY-SA (dual-licensed GFDL). For a personal, non-published
local system this is unproblematic; attribution matters if any output is republished, which is a
reason to carry the source article title into citations regardless.

---

## 7. Proposed design

1. **Corpus.** `wikipedia_en_all_maxi` (118.7 GiB) on B:, SHA-256 verified.
2. **One-time workshop conversion.** Extract article text, section structure, figure captions and
   images into BlarAI's own read-only container: zstd-compressed paragraph blobs, images kept as
   the webp bytes they already are, both content-addressed. The archive is then archival, not
   operational, and could be deleted.
3. **Retrieval, in two cheap stages.** SQLite FTS5 / BM25 over paragraph chunks — **with a `LIMIT`,
   unlike the knowledge bank's** — returns ~50 candidates; bge-small embeds **only those 50** at
   query time on the NPU and re-ranks; the top 3 are injected. **This avoids pre-embedding millions
   of chunks entirely** — the cost that would otherwise dominate the build, in both hours and tens
   of gigabytes of vectors. Results are presented through the existing `search_knowledge` shape,
   labelled with the article title and the snapshot date, and sized to the existing 4,000-character
   cap so nothing about the 4,096-token window has to change.
4. **Images.** Caption indexed as text alongside its paragraph; picture attached by reference and
   served through the existing `blarai-img://` rail once the missing resolver lands. Pixels never
   enter the model's context, honouring the constraint already written into the schema.
5. **Provenance.** Ingested as `untrusted_external`, datamarked, never granted instruction
   authority — the same posture as any other third-party text.
6. **Governance.** A new capability, so it merges **dormant** behind a config flag and waits for
   your ceremony. No egress is involved at any point.

**Costs, stated honestly:** roughly 120–250 GB of disk depending on whether the archive is kept
after conversion; one overnight conversion run; and a staleness property — a snapshot ages, so
refreshing means re-downloading periodically. Against that, the corpus is genuinely offline,
genuinely private, and the only route to Wikipedia's images that exists at all: Wikimedia
publishes no bulk image dump, and the request for one has been open upstream for years.

---

## 7b. Robustness — what "a relevance floor" actually requires

The Lead Architect's instinct that two controls would not be enough was correct, and the reason is
sharper than "more is safer": **the obvious fix is arithmetically impossible as the code stands.**

### The blocker: the fused score carries no relevance information

`knowledge_bank.py:2599-2604`:

```python
fused[key] = fused.get(key, 0.0) + 1.0 / (RRF_K + rank + 1)
top = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:k]
```

Reciprocal-rank fusion scores **position, not similarity**. The top hit scores `1/61 = 0.0164`
for a perfect match and `1/61` for garbage, on every query, always. There is no threshold that
distinguishes them because the number does not vary with quality. Any "minimum relevance score"
applied to this value is decoration.

Worse and better at once: **the calibrated signal is computed and then thrown away.** Line 2581
computes `scores = matrix @ q_vec` — the actual similarity of every chunk to the query — and
line 2582 immediately reduces it to an `argsort` ordering. The number needed for a real floor
already exists and survives for one statement.

### The ten controls a durable version needs

**C1 — Carry the real scores through fusion.** Keep the cosine value from the vector limb and the
BM25 value from the lexical limb alongside the fused rank. Threshold on those, never on the fused
score. **Shipped for the knowledge bank in #1617.**

> **Correction (2026-09-21, same day).** This control originally also recommended bounding both
> limbs — `argpartition` plus a lexical `LIMIT` — as free wins "required at scale anyway." That
> was attempted and **reverted after independent review measured it.** Bounding a limb does not
> trim the result, it *perturbs* it: a chunk already inside the budget that falls outside one
> limb's pool loses that limb's entire contribution at the boundary, a discontinuous drop of
> 1/261. Measured: a chunk at lexical rank 8 of 3,000 evicted from the top 4 because its vector
> rank was 251 rather than 199. Truncation also manufactures exact ties, which the stable sort
> then resolves by document-approval order — divergence from N=300.
>
> **The lesson for the corpus tier, which is the part that matters here:** candidate generation
> at seven million chunks cannot be bolted on as a truncation of an exact ranker. It has to be
> designed as approximate retrieval from the start — the union of both limbs' candidates fused
> with a *defined* treatment of the missing limb (a rank floor, not omission), and the
> approximation error measured rather than assumed. The knowledge bank keeps exact ranking
> because at curation scale exactness is free; the corpus cannot, and must not inherit this code
> path. Retrieval cost was measured across store sizes to place the boundary between the two
> regimes — `docs/performance/knowledge_retrieve_scaling_2026-09-21.json`.

**C2 — Measure the threshold; do not pick one.** A guessed cut-off is the same mistake in a new
place. Sweep it against a held-out set of factual questions and a matched set of prompts that
need no retrieval, and choose the point that admits the first and rejects the second. Record the
sweep.

**C3 — A margin test, because an absolute floor is fragile at this scale.** With seven million
articles *something* always matches tolerably; the encyclopedia will answer "what is 2+2" with a
passable paragraph about arithmetic. The discriminating signal is shape, not height: a query the
corpus genuinely covers produces a sharp peak, one it does not produces a flat field of mediocre
matches. Require the top hit to beat the k-th by a margin. This is the control aimed specifically
at the failure mode that only appears at encyclopedia scale.

**C4 — Gate before scoring, not only after.** A deterministic pre-filter that skips retrieval for
greetings, arithmetic, pure writing and formatting tasks, and follow-ups about the conversation
itself ("say that again, shorter"). Cheapest and most robust of all: keep the encyclopedia behind
the explicit `search_knowledge` tool, so the model reaches for it only when it decides it needs a
fact. Do both.

**C5 — A new provenance tier, leak-exempt, argued on the web-search precedent.**

> **Retracted (2026-09-21, same day).** An earlier version of this control recommended *against*
> a Stage-5 leakage exemption, on the grounds that the existing one was justified by "operator
> approval curated it into the bank" and a bulk import is not curated. The Lead Architect
> overruled it. **He was right, and the wrong version is left visible here because the reason I
> was wrong is the useful part.** I reasoned from the *rationale recorded for one tier* instead
> of reading what the control actually defends.

`context_manager.py:94-150` states it plainly: the Stage-5 cosine block is an **exfiltration**
control — *"a verbatim echo of content from outside the trust boundary is a leak."* It is not an
injection defence. Injection defence is the **Layer-3 action lock plus datamarking, which all
three untrusted tiers carry and which no exemption touches.** A prompt injection hidden in a
vandalised Wikipedia article still cannot fire a tool, and is still delimiter-wrapped and
per-line marked, exemption or not. My concern was aimed at the wrong control.

And the precedent is not the knowledge bank — it is **`UNTRUSTED_WEB`** (ADR-023 Amendment 3,
#719), exempted because *"a faithful relay of public web-search results back to the operator who
asked for them is the intended behaviour, not exfiltration."* **An offline encyclopedia is that
case, only more so:** the content is unambiguously public, and unlike web search it never left
the machine to be fetched. Without the exemption every faithful recall trips the detector and the
corpus is write-only — precisely the failure Amendment 2 was written to prevent.

**Therefore, and matching the pattern the codebase has already used twice:** mint a **fourth
distinct tier** — `UNTRUSTED_CORPUS` — with leak-exempt-but-untrusted semantics, as
**ADR-023 Amendment 4**. Distinct rather than reusing `UNTRUSTED_KNOWLEDGE` for the reason the
existing code gives for keeping web separate: *"the audit trail and any future per-source policy
must be able to tell them apart."* A bulk encyclopedia and the operator's hand-curated bank
should never be indistinguishable in an audit, even while they gate identically today.

**Decided by the Lead Architect, 2026-09-21: the exemption is granted.**

What remains true from the original concern, and is handled elsewhere rather than here: a ZIM
snapshot freezes whatever a page said at scrape time, vandalism included, across seven million
documents. That is an *injection* surface, and it is answered by the Layer-3 action lock,
datamarking and delimiter-neutralisation — all of which apply in full.

**C6 — Extraction quality is the biggest single lever, and it is measurable.** A naive HTML strip
of the Nelson Mandela article yielded 194,570 characters / 64,106 tokens; the actual prose is a
fraction of that, the rest being navigation, reference lists and table scaffolding. Retrieval
quality is bounded by what is in the chunks. Strip navboxes, reference lists and "See also";
keep prose and figure captions; chunk on paragraph boundaries *within* sections; and carry
`article title › section heading` into every chunk so a retrieved paragraph is self-describing
and citable without a second lookup.

**C7 — Return candidate titles, not just text.** So the model can notice it asked about an album
and received a film. My own probe produced exactly that confusion from parametric memory; a
retrieval system that hides its sources rebuilds the failure somewhere new.

**C8 — Label the snapshot date on every chunk.** The measured failure in §1 was the model stating
superseded facts in the present tense. A frozen corpus can reproduce that failure faithfully
unless its age travels with its content.

**C9 — Engineering hygiene the house rules already require.** On-disk index (SQLite FTS5, mmap),
never a RAM-resident matrix — Wall 1 must not be rebuilt in a new tier. A signed manifest over
the converted corpus, verified at load (principle 10). The retrieval budget registered in
`shared/timeout_registry.py`, and on timeout inject nothing rather than delay the answer.

**C10 — Fail loudly, and make "did this help" measurable.** If the corpus is missing, corrupt or
unverified, retrieval returns nothing and says so; it never degrades silently into an unmarked
parametric answer (principle 11). And the 40-item head/tail probe from §1 should be frozen as a
committed eval with a baseline, joined by a "should not retrieve" set — so the improvement is a
measured number in `PERFORMANCE_LOG.md`, not a claim. Every fix ships its regression lock.

### One posture question this raises

The corpus is **public data**. Encrypting 120 GB of Wikipedia buys no confidentiality — the
content is on the open internet — and costs decryption on every read. The recommendation is
**integrity-signed but not encrypted**, with everything *derived* from it (what was asked, what
was retrieved, what was answered) staying in the existing encrypted session store. That is a
deliberate deviation from the born-encrypted default (principle 6), so it is raised as a decision
rather than taken quietly. See §8.

---

## 8. Decisions

### Settled by the Lead Architect, 2026-09-21

**D1 — At rest: integrity-signed, NOT encrypted.** The corpus is public data; encrypting 120 GB
of Wikipedia buys no confidentiality and costs decryption on every read. A signed manifest is
verified at load and the corpus refuses to serve if it does not verify (principle 10 + fail-closed).
Everything *derived* from it — what was asked, what was retrieved, what was answered — stays in
the existing encrypted session store, so nothing about the operator's use of it is in the clear.
A deliberate, recorded deviation from the born-encrypted default (principle 6), scoped to public
third-party content only. *Matches the standing recommendation.*

**D2 — The Stage-5 leakage exemption is GRANTED.** Implemented as a new fourth provenance tier
`UNTRUSTED_CORPUS` under **ADR-023 Amendment 4**, on the `UNTRUSTED_WEB` precedent rather than
the knowledge-bank one: relaying public reference content back to the operator who asked for it
is the intended behaviour, not exfiltration. Kept a distinct tier from `UNTRUSTED_KNOWLEDGE` and
`UNTRUSTED_WEB` so the audit trail can tell a bulk encyclopedia from the operator's curated bank.
**Layer-3 action lock, datamarking and delimiter-neutralisation still apply in full** — the
exemption touches the leakage feed and nothing else. *Overrides the standing recommendation; the
recommendation was wrong and the reasoning is retracted in C5.*

Both require an ADR amendment, a `DECISION_REGISTER.md` row and a journal entry in the same
change that implements them.

### Still open

**D3 — The GPL route** (§6). Recommended: workshop conversion, so nothing GPL ships and no new
listener appears. Alternatives named in the table. *Awaiting a decision; the recommendation
stands and work can proceed on it.*

**D4 — Whether to raise `max_context_tokens` beyond 4,096** (§3). The proposal is built to *not*
require it. A larger window would let the corpus supply more grounding per answer, at a cost in
memory and latency this machine has already been measured paying. Best decided later against
evidence from a working system, rather than now.

**D5 — The go-live ceremony**, once the work is built and proven dormant.

## 9. What is not settled

- Cold-cache retrieval latency on the full 118.7 GiB archive — queued, will be measured.
- Measured bge-small throughput on the NPU, needed to cost the re-rank stage precisely.
- Final size of the converted corpus and its FTS5 index — estimable, not yet measured.
- Whether `wikipedia_en_all_mini` (13.4 GiB, every article's lead section) would capture most of
  the benefit at a tenth of the disk. Worth measuring against the full archive before committing
  to a refresh cadence; it does not change the recommendation to take the full one now.
