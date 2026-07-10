"""#746 research substrate (slice 1) — LOCAL docset retrieval for the coding fleet.

Two research points, both PULL-not-PUSH and 100% local-disk (zero egress):

  * plan-time grounding — :func:`shared.research.plan_grounding.ground_goal`
    renders a bounded grounding block for a decompose goal (the caller decides
    whether to include it);
  * build/fix-time reactive lookup — :func:`shared.research.lookup.exact_lookup`
    (deterministic-first: exact symbol/error-token match, no model, no fuzz)
    then :func:`shared.research.lookup.search_docs` (deterministic BM25 lexical
    ranking over the local page store, gated by ``RELEVANCE_FLOOR`` — nothing
    above the floor means no high-value answer: STOP, return nothing).

The corpus is the LA-approved, hash-pinned docset staging under
``models/docsets/`` (``scripts/stage_docsets.py`` provisions it at build/dev
time; the runtime NEVER fetches). The index is a derived, gitignored SQLite
file under ``models/docsets/index/``.
"""

from __future__ import annotations

from shared.research.docset_index import (
    CorpusIntegrityError,
    CorpusMissingError,
    DocsetIndex,
    IndexNotBuiltError,
    ResearchIndexError,
    StaleIndexError,
    build_index,
    ensure_index,
    load_index,
)
from shared.research.lookup import (
    RELEVANCE_FLOOR,
    DocHit,
    exact_lookup,
    search_docs,
    semantic_rerank,
)
from shared.research.plan_grounding import ground_goal

__all__ = [
    "RELEVANCE_FLOOR",
    "CorpusIntegrityError",
    "CorpusMissingError",
    "DocHit",
    "DocsetIndex",
    "IndexNotBuiltError",
    "ResearchIndexError",
    "StaleIndexError",
    "build_index",
    "ensure_index",
    "exact_lookup",
    "ground_goal",
    "load_index",
    "search_docs",
    "semantic_rerank",
]
