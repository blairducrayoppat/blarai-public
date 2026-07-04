# ADR-016: Personal Knowledge Substrate — MVP (single-process slice of USE-CASE-002)

**Status:** ACCEPTED — 2026-06-02
**Author:** Lead Architect (Blair) + Claude Opus 4.7
**Scope:** The first real slice of USE-CASE-002 (the Substrate) — persistent
semantic memory across sessions — built into the current single-process
architecture, not the long-term multi-VM stack.

---

## 1. Context

USE-CASE-002 specifies a locally-hosted, semantically-indexed knowledge base —
HNSW + BM25 + an embedding pipeline — that accumulates the user's data over time
and is the authoritative data layer for the Assistant. Until now the "data
pillar" was only `/load` over flat files in `userdata/`: documents had to be
re-loaded every session, nothing was searchable, and nothing survived a restart.
"What did I tell you last week about my sister?" could not work, because last
week's turn was gone the moment it left the context window.

This ADR records the decisions for the MVP that makes that question work, while
deliberately *not* building the parts of the spec that defend a threat model
single-process BlarAI does not yet have.

## 2. Decisions

### 2.1 Reuse the embedding model — do not add a second stack

The Substrate embeds with the **same bge-small-en-v1.5 ONNX model** the output
validator already loads (PGOV Stage 5 leakage detector, `pgov.py`
`LeakageDetector`). The store takes an injected `embed_fn`; the Orchestrator
passes the detector's embedder. One model, one stack, no extra resident memory.
384-dim, L2-normalised, CPU — identical to the Semantic Router and the leakage
detector.

### 2.2 What is indexed

- **Documents** — every loaded PDF/txt/md (and the picker/drag-drop path),
  chunked (~512 tokens ≈ 2048 chars, ~64-token ≈ 256-char overlap) and embedded.
  Re-loading a filename replaces its prior chunks.
- **Conversation turns** — every **PGOV-approved** user+assistant pair, embedded
  as one unit, keyed idempotently by `(session_id, turn_index)`. This is what
  gives memory across sessions. Denied turns are never indexed.

### 2.3 What is retrieved, and how it is treated

On each prompt the user's text is embedded and the top-K chunks are retrieved —
default **K=6, split 2 documents + 4 past turns**. Turns from the *current*
session are excluded (they are already in the live window; re-retrieving wastes
budget). Retrieved chunks are injected through the Orchestrator's existing
`ContextManager.add_grounded_context`, so they receive **Layer 1 + Layer 2**
defences (forged-delimiter neutralisation + per-load datamarking) exactly like a
freshly-loaded document. This is the load-bearing security decision: **retrieved
history is untrusted text** — the user's own past words can still carry an
injection that was stored before it was understood as one — and it is defended
identically, not trusted because it came from "us."

### 2.4 Storage

A side SQLite file, `substrate.db`, beside `sessions.db` in
`%LOCALAPPDATA%\BlarAI\`. One `substrate_chunks` table holds the vector (float32
BLOB) with its source metadata (`kind`, `source`, `session_id`, `chunk_index`,
`text`, `created_at`); a `substrate_meta` table records the embedding dimension
and model name so a future model change is detectable. A side file (rather than
new tables in `sessions.db`) keeps the memory index cleanly separable and
disposable without touching the session store.

### 2.5 Vector index: brute-force cosine now, ANN-swappable later

The planned index was **hnswlib**. It ships no wheel for this Python/platform
and fails to build from source (no C++ toolchain), so the MVP uses **brute-force
cosine** — a single numpy matrix multiply over L2-normalised vectors. At a single
user's scale (thousands of 384-dim vectors) this is sub-millisecond and adds **no
dependency**, which is more in keeping with BlarAI's minimal-surface, no-network
posture than a compiled extension would be. The search is isolated behind a
private method (`_search_kind`), so an approximate-nearest-neighbour index can
replace it unchanged if the corpus ever grows past the point where brute force is
adequate (rule of thumb: ~100K vectors). **Trade-off accepted:** O(N) query cost
vs. a build dependency and added surface; for the realistic horizon, brute force
wins.

## 3. Deferred (named, not built)

- **Isochronous retrieval timing (Use Cases §002 ISSUE-007).** The spec calls
  for fixed-deadline release of retrieval results so a compromised co-resident
  agent cannot infer index metadata from IPC latency. That threat — an adversary
  observing inter-VM round-trip times — **does not exist in single-process
  BlarAI**, where retrieval is an in-process function call. Building it now would
  be defending a boundary that is not there: the exact Layer-3-over-build mistake
  this project already paid for once. **Deferred until the multi-VM architecture
  lands**, at which point it is re-evaluated alongside the rest of the vsock IPC
  hardening.
- **BM25 lexical fallback.** Semantic-only retrieval is sufficient for the MVP;
  `rank_bm25` can be added later if recall on rare exact terms proves weak.
- **HNSW / ANN index** — see §2.5; deferred until scale demands it.
- **Cleaner (USE-CASE-003) sanitization at ingest, vector compaction, time-decay
  weighting, manual "forget this," named memory slots.** Real next-push items;
  none load-bearing for "BlarAI remembers what I told it" working at all.

## 4. Consequences

- BlarAI gains persistent cross-session memory: past documents and past
  conversations are retrievable by meaning, surviving restarts.
- The retrieved-history-is-untrusted decision means the injection-defence surface
  grows to cover memory, not just freshly-loaded files — the right posture, and a
  governance point worth its place in the portfolio.
- One embedding model serves routing, leakage detection, and the Substrate.
- The brute-force index is a documented, swappable simplification, not a
  permanent ceiling.

## 5. Implementation

- `services/assistant_orchestrator/src/substrate.py` — `SubstrateStore`
  (SQLite + brute-force cosine), `chunk_text`, `RetrievedChunk`.
- `services/assistant_orchestrator/tests/test_substrate.py` — chunking, ingest,
  retrieval, cross-session recall, session exclusion, dedup, persistence (18
  tests, deterministic fake embedder).
- Orchestrator wiring (retrieve-into-grounded-context on each prompt; ingest
  documents on load; ingest approved turn pairs) — `entrypoint.py`.

## 6. Related

- **USE-CASE-002** (the full Substrate this is the MVP of): `Use Cases_FINAL.md`.
- **ADR-013** — the Layer 1+2 datamarking / delimiter defences retrieved chunks
  reuse.
- **ADR-014** — the named-pipe surface that drives the prompts retrieval runs on.
