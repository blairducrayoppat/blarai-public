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

import json
import logging
import os
import time
from pathlib import Path

from shared.research.docset_index import DocsetIndex, ResearchIndexError
from shared.research.lookup import DocHit, exact_lookup, search_docs

logger = logging.getLogger(__name__)

#: Hard cap on the whole grounding block (mirrors CONTEXT_PACK_MAX_CHARS —
#: an interface card, not documentation).
GROUNDING_MAX_CHARS = 1200

def _default_usage_log() -> Path | None:
    """This machine's usage ledger, under the standard BlarAI state tree, or
    ``None`` when there is no state tree to write into.

    Resolved PER CALL from ``%LOCALAPPDATA%``, the same root
    ``shared/secrets/dpapi_store.py`` and the coordinator store use. Two
    defects this replaces, both found 2026-07-30:

    * it was a hard-coded absolute path into a DIFFERENT repo
      (``agentic-setup/state/``), so this module wrote outside its own tree;
    * because the path was fixed at import and ignored the environment, every
      test and review run that reached ``ground_goal`` without remembering to
      set ``BLARAI_RESEARCH_USAGE_LOG`` appended to the OPERATOR's ledger —
      1,963 records, most of them review traffic, on a capability that is
      stood down. Anyone reading that file to decide whether to re-arm was
      reading us testing it.

    Resolving from ``%LOCALAPPDATA%`` makes the standing
    LOCALAPPDATA-redirect discipline do the isolation structurally, instead of
    depending on each test remembering an env var. Returning ``None`` rather
    than guessing a path keeps the fail-soft posture: no state tree, no record,
    never a write somewhere unintended.
    """
    root = os.environ.get("LOCALAPPDATA", "").strip()
    if not root:
        return None
    return Path(root) / "BlarAI" / "research" / "research-usage.jsonl"


#: ALWAYS-ON usage evidence (#746 maturation): every ground_goal() call appends one
#: JSONL record, so hit rate / block size / outcome are observable without a debug
#: env flag. ``BLARAI_RESEARCH_USAGE_LOG`` overrides the destination; unset uses
#: :func:`_default_usage_log`. Best-effort + fail-soft, same posture as the rest of
#: this module -- a logging failure must never affect grounding.
def _log_usage(
    *,
    goal_len: int,
    outcome: str,
    hits: int,
    block_chars: int,
    rungs: str = "",
) -> None:
    try:
        override = os.environ.get("BLARAI_RESEARCH_USAGE_LOG", "").strip()
        resolved = Path(override) if override else _default_usage_log()
        if resolved is None:
            return
        log_path = resolved
        log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": time.time(),
            "caller": "plan_grounding",
            "goal_len": goal_len,
            "outcome": outcome,  # "no_goal" | "unavailable" | "no_match" | "grounded"
            "hits": hits,
            "block_chars": block_chars,
            # WHICH rungs produced hits, so "the corpus answered" can be told
            # apart from "the corpus answered the way we think it does":
            # "exact" | "search", joined by "+".
            "rungs": rungs,
        }
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 -- a usage-log failure must never affect grounding
        pass

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


def _attribute_rungs(
    kept: list[DocHit], exact: list[DocHit], searched: list[DocHit]
) -> str:
    """Which rungs the RENDERED hits came from — ``"exact"``/``"search"``
    joined by ``+``, in ladder order.

    Attributed from *kept* rather than from what each rung produced, because
    the two differ: the block refit drops trailing hits, so a rung can produce
    a hit that never reaches the prompt. It did not answer, and capability 7
    asks a number to say what it measured.

    A page both rungs found is credited to the FIRST, matching the merge's
    precedence — crediting both would make the field unable to draw the one
    distinction it exists for."""
    origin: dict[tuple[str, str], str] = {}
    for name, rung in (("exact", exact), ("search", searched)):
        for hit in rung:
            origin.setdefault((hit.source, hit.path), name)
    answered = {origin.get((hit.source, hit.path)) for hit in kept}
    return "+".join(name for name in ("exact", "search") if name in answered)


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

    KNOWN LIMIT, measured and deliberate: a goal written in plain English
    grounds on NOTHING, because BM25 normalizes by the mass of the whole query
    so a multi-topic sentence scores every page beneath the floor by
    construction. A per-topic rung was built to close that and REMOVED after
    four independent gates each failed the same way on held-out goals — see
    ``docs/reviews/1204-plan-grounding-salience-disproof-2026-07-31.md``. The
    silence is correct until a semantic instrument replaces the lexical one;
    a wrong page at the head of the planner prompt is worse than no page.

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
        _log_usage(goal_len=len(text), outcome="unavailable", hits=0, block_chars=0)
        return ""

    merged = _merge_hits(exact, searched, k)
    if not merged:
        _log_usage(goal_len=len(text), outcome="no_match", hits=0, block_chars=0)
        return ""

    kept = list(merged)
    while kept:
        for budget in _EXCERPT_BUDGETS:
            block = _render(kept, budget)
            if len(block) <= GROUNDING_MAX_CHARS:
                _log_usage(
                    goal_len=len(text),
                    outcome="grounded",
                    hits=len(kept),
                    block_chars=len(block),
                    rungs=_attribute_rungs(kept, exact, searched),
                )
                return block
        kept.pop()  # drop the weakest (last) hit and refit
    # Unreachable in practice (header+footer alone always fit), but stay
    # fail-closed rather than emit an over-cap block.
    _log_usage(goal_len=len(text), outcome="unreachable_overcap", hits=0, block_chars=0)
    return ""


__all__ = ["GROUNDING_FOOTER", "GROUNDING_HEADER", "GROUNDING_MAX_CHARS", "ground_goal"]
