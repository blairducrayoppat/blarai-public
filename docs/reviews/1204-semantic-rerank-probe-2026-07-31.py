"""#1204 probe — can an embedding do what four lexical gates could not?

Decisive experiment, NOT shipping code. Question: with BM25 used only for
RECALL (top-N, no floor) and bge-small cosine used for PRECISION, do the
GOOD goals and the JUNK goals separate on the number line?

All four disproved gates answered a PROXY question ("is this word rare",
"is it a symbol", "does the ranking point here", "is it a module page").
An embedding answers the question directly: is this page about this goal?

Goals are quoted VERBATIM from docs/reviews/1204-plan-grounding-salience-
disproof-2026-07-31.md and ticket #1204 — per that document's own recording
rule, no ellipsis in any line carrying a number.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve()
for parent in REPO.parents:
    if (parent / "shared" / "research" / "lookup.py").exists():
        sys.path.insert(0, str(parent))
        break
else:
    sys.path.insert(0, "C:/Users/mrbla/BlarAI")

import numpy as np  # noqa: E402

from shared.research import lookup as LK  # noqa: E402

# Verbatim. Expectation is the disproof's, not mine.
MUST_GROUND = [
    "build a CLI using argparse that reads a csv file",
    "a toolkit that reads text and reports how often each word appears, and "
    "which pairs of neighbouring words show up together most",
    "a web page that renders user comments safely without innerHTML",
    "use collections.Counter and itertools.pairwise to count word bigrams",
]

MUST_STAY_SILENT = [
    "make a copy of my important documents every friday",
    "manage the queue at my barber shop on a saturday",
    "build a site for my running club",
    "an app for the operator of the village bus",
    "tell me the stat for how many miles I cycled",
    "keep a mailbox of notes from my grandchildren",
    "my grandmother baked a big cake for the village fete",
    "purple elephant birthday cake recipe",
    "somewhere to keep my secrets safe with a password",
]

TOP_N = 40
PAGE_CHARS = 1500


def bm25_candidates(idx, query: str, n: int):
    """lookup.search_docs's scorer with the RELEVANCE_FLOOR removed.

    The floor is the thing under test: library/csv scores 0.2986 against a
    0.35 floor, so the right page is discarded BEFORE semantic_rerank can
    ever see it. Here BM25 is recall only.
    """
    text = str(query or "")[: LK._MAX_QUERY_CHARS]
    terms, seen = [], set()
    for term in LK.tokenize(text):
        if term not in seen:
            seen.add(term)
            terms.append(term)
        if len(terms) >= LK._MAX_QUERY_TERMS:
            break
    if not terms:
        return []
    k1, b = LK._BM25_K1, LK._BM25_B
    idfs = {t: LK._idf(idx.df(t), idx.n_pages) for t in terms}
    max_mass = sum(i * (k1 + 1.0) for i in idfs.values())
    if max_mass <= 0.0:
        return []
    scores: dict[int, float] = {}
    for term in terms:
        idf = idfs[term]
        if idf <= 0.0:
            continue
        for pid, tf in idx.postings(term):
            ln = 1.0 - b + b * (idx.doc_length(pid) / idx.avgdl)
            scores[pid] = scores.get(pid, 0.0) + (
                idf * (tf * (k1 + 1.0)) / (tf + k1 * ln)
            )
    ranked = sorted(
        ((s / max_mass, pid) for pid, s in scores.items()),
        key=lambda it: (-it[0], it[1]),
    )
    return ranked[:n]


def main() -> int:
    sys.path.insert(0, "C:/Users/mrbla/BlarAI/services/assistant_orchestrator/src")
    from pgov import LeakageDetector

    det = LeakageDetector()
    if not det.load_model():
        print("FAILED: embedding model would not load")
        return 2
    print(f"embedder loaded: backend={det._backend!r}")

    idx = LK._get_index(None)
    print(f"corpus: {idx.n_pages} pages, avgdl={idx.avgdl:.1f}")
    print(f"RELEVANCE_FLOOR (lexical, current gate) = {LK.RELEVANCE_FLOOR}\n")

    rows = []
    for label, goals in (("GOOD", MUST_GROUND), ("JUNK", MUST_STAY_SILENT)):
        for goal in goals:
            cands = bm25_candidates(idx, goal, TOP_N)
            if not cands:
                rows.append((label, goal, 0.0, 0.0, "<no candidates>"))
                continue
            texts, metas = [], []
            for bm_score, pid in cands:
                page = idx.page(pid)
                if page is None:
                    continue
                title = LK._clean_title(page.title) or page.path
                texts.append(f"{title}\n{page.text[:PAGE_CHARS]}")
                metas.append((bm_score, page.source, title, page.path))
            if not texts:
                rows.append((label, goal, 0.0, 0.0, "<no pages>"))
                continue
            vecs = det.embed_documents(texts, max_length=512)
            qv = det.embed_documents([goal], max_length=512)[0]
            # embed_documents returns L2-normalised vectors -> cosine == dot
            sims = np.asarray(vecs) @ np.asarray(qv)
            best = int(np.argmax(sims))
            bm_top = max(m[0] for m in metas)
            rows.append(
                (label, goal, float(sims[best]), bm_top,
                 f"{metas[best][3]} ({metas[best][1]})")
            )
            print(f"[{label}] cos={sims[best]:.4f}  bm25_top={bm_top:.4f}  "
                  f"{metas[best][3]}\n        goal: {goal}")

    good = [r[2] for r in rows if r[0] == "GOOD"]
    junk = [r[2] for r in rows if r[0] == "JUNK"]
    print("\n" + "=" * 68)
    print(f"GOOD cosine  min={min(good):.4f}  max={max(good):.4f}  n={len(good)}")
    print(f"JUNK cosine  min={min(junk):.4f}  max={max(junk):.4f}  n={len(junk)}")
    sep = min(good) > max(junk)
    print(f"\nSEPARATES ON COSINE? {'YES' if sep else 'NO'}")
    if sep:
        print(f"  any threshold in ({max(junk):.4f}, {min(good):.4f}] admits all "
              f"GOOD and rejects all JUNK")
    else:
        print(f"  overlap: worst GOOD {min(good):.4f} <= best JUNK {max(junk):.4f}")
        print("  -> same failure shape as the four lexical gates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
