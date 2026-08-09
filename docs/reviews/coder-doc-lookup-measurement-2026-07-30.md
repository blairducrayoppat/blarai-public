---
title: What the coder's local doc lookup actually returns — measured before arming
status: evidence
area: reviews
date: 2026-07-30
---

# Coder doc-lookup retrieval quality, measured

**Why this exists.** On the morning of 2026-07-30 the *planner's* local-corpus grounding was
armed and stood back down the same evening, because the go-live had rested on the corpus being
staged and the code being tested — which are different claims from *"the pages it retrieves are
the right ones"*. This file is the measurement that was missing, taken for the **other** rung
(#1206 / #746 rung 2, the coder's build/fix-time lookup) **before** arming it rather than after.

It is deliberately NOT the planner's measurement re-used. The planner asks a whole goal
(*"build me a website where I can track my water intake"*); the coder asks a concrete named gap
mid-build — an error string, an API name, a "how do I X". #746's own design calls this **PULL not
PUSH**: research fires only on a concrete named gap, never speculatively. Inheriting the planner's
5-of-9-wrong result would be the *documentation is not evidence* mistake aimed inward.

## Method

- **Corpus:** `models/docsets/index/docset_index.sqlite3`, **13,803 pages**, hash-verified against
  `models/docsets/MANIFEST.sha256.json` (staged 2026-07-06, 15 artifacts, 134.6 MB). Zero egress.
- **Code:** `shared.research.lookup.search_docs` + `exact_lookup` on main `4aea785a` — the same two
  rungs `agentic-setup/tools/search_docs.py` wraps. `RELEVANCE_FLOOR = 0.35`.
- **Queries:** 19, in four classes, written before the results were seen.
- **Scoring:** by hand. No pass/fail is computed by the script, because whether a page is ABOUT a
  question is a human judgement, and a script that scored itself here would be exactly the vacuous
  instrument this project keeps finding.
- **Run:** 2026-07-30 pm, `LOCALAPPDATA` redirected, primary checkout, read-only.

## Results

| class | queries | correct | verdict |
|---|---|---|---|
| **A. pasted error text** | 4 | **2** | the weak class — and the one this rung exists for |
| **B. API names** | 6 | **6** | the deterministic-first rung works |
| **C. "how do I X"** (named gap) | 6 | **5** | good; the one miss is security-adjacent |
| **D. controls** (must stay silent) | 3 | **3** | including a plausible-but-absent library |

### A. Pasted error text — 2/4

| query | exact rung | top ranked page | ok? |
|---|---|---|---|
| `TypeError: unsupported operand type(s) for +: 'int' and 'str'` | `TypeError` ✓ | 0.402 *"typing" — Support for type hints* | ranked WRONG |
| `AttributeError: 'NoneType' object has no attribute 'get'` | `AttributeError` ✓ | 0.575 *Bug Fixes* | ranked JUNK |
| `json.decoder.JSONDecodeError: Expecting value` | — | **nothing above floor** | MISS |
| `fixture 'tmp_path' not found` | — | 0.669 *Parametrization with multiple fixtures* (correct page 2nd) | adjacent |

**The pattern:** the EXACT rung carries this class and the RANKED rung actively degrades it. A
pasted traceback is mostly punctuation, quoted values and operator symbols, so the few real tokens
(`type`, `object`, `attribute`) are precisely the high-document-frequency scaffolding words that
match changelogs. #746 specifies the missing piece — *"exact error text → exact-match lookup in the
local docset/error index"* — and that error index was never built.

### B. API names — 6/6

`json.dumps` → exact + 0.719 json module · `pathlib.Path.read_text` → exact ·
`argparse.ArgumentParser.add_subparsers` → exact + 0.452 argparse · `unittest.mock.patch` → exact +
0.755 unittest · `hypothesis.given` → 0.768 *@given* · `pytest.raises` → **0.909 pytest.raises**.

Four resolve exactly; the two without an exact entry still land the right page at high score.

### C. "How do I X" — 5/6

csv module 0.854 · argparse 0.503 · tempfile 0.610 · subprocess 0.612 · *Sorting HOW TO* 0.570.

**The miss, and it matters:** `escape html in a template` → **0.820 *Template literals (Template
strings)*** — JavaScript string interpolation, not HTML escaping. A coder asking how to escape HTML
and being handed template literals is pointed at the mechanism that CAUSES injection rather than
the one that prevents it. High score, wrong page, on a question that touches capability 3 (secure
websites). Word collision on "template".

### D. Controls — 3/3 silent

`purple elephant birthday cake recipe` → nothing. `how do I change the oil in a 1998 Honda Civic`
→ nothing. **`django queryset annotate` → nothing** — the last is the one that matters: django is
absent from the corpus, and the retrieval declines to invent a plausible substitute rather than
returning the nearest Python-shaped page.

## What this decides, and what it does not

**It supports arming this rung, and does not support arming the planner's.** The difference is
structural, not a matter of degree:

- the planner's grounding block is prefixed **above** the planner's own instructions
  (`decompose.py:1230`), so a wrong page silently biases the plan at the highest-leverage point in
  the prompt, and nothing downstream can tell
- the coder's lookup is **pull** — fired on a concrete gap, returned as a tool result the coder
  reads and can discard

#746's contract is met on its own terms: deterministic-first works (B, 6/6), attempts are bounded,
and it parks honestly when there is no high-value match (D, 3/3) rather than spinning.

## What was NOT measured

- **End-to-end through the coder's actual tool.** This drove the two Python rungs directly. The
  `search_docs.js` → `tools/search_docs.py` seam is verified separately on `feat/1206-arm-coder-doc-lookup`.
- **Whether a retrieved page changes what the coder builds.** Retrieval quality is not the same as
  outcome improvement; #746's own DoD asks for a before/after on the battery solve rate, and that is
  unmeasured.
- **Any non-Python / non-web surface.** The corpus is Python + web only, by design (#746 scopes the
  partial-corpus ceiling as a feature).
- **Latency and memory.** Not captured this run.

## Residuals raised

- **#1217** — error-text is the weak class (2/4), and `escape html in a template` leads with
  JavaScript template literals. Predicate on the ticket.
