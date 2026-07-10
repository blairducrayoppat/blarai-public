"""#746 research substrate (slice 1) — plan-time grounding for decompose.

Before (or while) the 14B decomposes a fleet goal, the orchestration layer can
retrieve the top-k most relevant LOCAL doc excerpts for the goal and hand the
model a small, bounded grounding block — so the plan is written against what
the platform actually provides (real API names, real semantics) instead of
recalled approximations.

PULL not PUSH: :func:`ground_goal` renders the block and RETURNS it — the
CALLER decides whether to include it, and an empty string means "the corpus
holds nothing above the relevance floor for this goal" (include nothing;
never pad a prompt with weak matches). The block is hard-capped at
:data:`GROUNDING_MAX_CHARS` (~1200 chars), deliberately mirroring the context
-pack cap in ``shared/fleet/context_pack.py`` — a grounding block is an
interface card, not documentation, and an over-stuffed prompt degrades the
planner.

Degrade-gracefully (the one consumer with this posture): a missing/unbuilt
corpus makes this function return ``""`` after logging a warning — plan
grounding is enrichment, and its absence must never break decompose. (The
coder-facing ``lookup`` API takes the opposite posture and raises loudly;
see its module docstring.)

INTEGRATION SEAM (deliberately NOT wired in this slice, per #746): the
integration point is ``shared/fleet/decompose.py`` — ``decompose_request``
assembles the decompose prompt, and the integrator prepends/attaches
``ground_goal(<goal text>)`` output there AFTER independent verification of
this slice. Nothing imports this module yet; wiring it is the integrator's
explicit, reviewable step.
"""

from __future__ import annotations

import logging

from shared.research.docset_index import DocsetIndex, ResearchIndexError
from shared.research.lookup import DocHit, exact_lookup, search_docs

logger = logging.getLogger(__name__)

#: Hard cap on the whole grounding block (mirrors CONTEXT_PACK_MAX_CHARS —
#: an interface card, not documentation).
GROUNDING_MAX_CHARS = 1200

GROUNDING_HEADER = "--- Research grounding (local docs) ---"
GROUNDING_FOOTER = "--- End research grounding ---"

#: Descending per-hit excerpt budgets tried until the block fits the cap.
_EXCERPT_BUDGETS = (280, 200, 140, 90)


def _merge_hits(
    exact: list[DocHit], searched: list[DocHit], k: int
) -> list[DocHit]:
    """Exact hits first, then search hits, de-duplicated per PAGE, capped at k.

    An exact hit's path is ``page#fragment`` over a stored DevDocs page path
    of ``page``, so it reserves BOTH keys (the search copy of the same page is
    a duplicate). Search-hit paths are compared exactly as stored — zip
    SECTION pages legitimately carry ``#section-id`` in their stored path,
    and two sections of one document are DISTINCT hits (regression-locked)."""
    merged: list[DocHit] = []
    seen: set[tuple[str, str]] = set()
    for hit in exact:
        keys = {(hit.source, hit.path), (hit.source, hit.path.partition("#")[0])}
        if keys & seen:
            continue
        seen.update(keys)
        merged.append(hit)
        if len(merged) >= k:
            return merged
    for hit in searched:
        if len(merged) >= k:
            break
        if (hit.source, hit.path) in seen:
            continue
        seen.add((hit.source, hit.path))
        merged.append(hit)
    return merged


def _render(hits: list[DocHit], excerpt_budget: int) -> str:
    lines: list[str] = [GROUNDING_HEADER]
    for hit in hits:
        lines.append(f"[{hit.source}] {hit.title} — {hit.path}")
        excerpt = hit.excerpt[:excerpt_budget].rstrip()
        if excerpt:
            lines.append(f"  {excerpt}")
    lines.append(GROUNDING_FOOTER)
    return "\n".join(lines)


def ground_goal(
    goal: str, k: int = 3, *, index: DocsetIndex | None = None
) -> str:
    """Bounded grounding block for a decompose *goal*, or ``""``.

    Retrieval ladder (deterministic-first, same as the reactive path): exact
    symbol hits for any identifiers the goal names, then floor-gated BM25
    search; merged (exact first), de-duplicated per page, capped at *k* hits.
    Returns ``""`` when nothing clears :data:`~shared.research.lookup.
    RELEVANCE_FLOOR` — the pull-not-push contract: the caller includes the
    block only when it exists, and a weak match is the same as no match.

    The rendered block is deterministically fitted to
    :data:`GROUNDING_MAX_CHARS`: per-hit excerpt budgets shrink first, then
    trailing hits drop, and the footer line always survives.
    """
    text = str(goal or "").strip()
    if not text or k <= 0:
        return ""
    try:
        exact = exact_lookup(text, index=index)
        searched = search_docs(text, k=k, index=index)
    except ResearchIndexError as exc:
        logger.warning("plan grounding unavailable (%s); continuing ungrounded", exc)
        return ""

    merged = _merge_hits(exact, searched, k)
    if not merged:
        return ""

    kept = list(merged)
    while kept:
        for budget in _EXCERPT_BUDGETS:
            block = _render(kept, budget)
            if len(block) <= GROUNDING_MAX_CHARS:
                return block
        kept.pop()  # drop the weakest (last) hit and refit
    # Unreachable in practice (header+footer alone always fit), but stay
    # fail-closed rather than emit an over-cap block.
    return ""


__all__ = ["GROUNDING_FOOTER", "GROUNDING_HEADER", "GROUNDING_MAX_CHARS", "ground_goal"]
