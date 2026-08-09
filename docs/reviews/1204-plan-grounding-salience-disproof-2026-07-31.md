# #1204 — why plan grounding has no "salient symbol" rung

**Status: DISPROVED and REMOVED.** Four independent gates were built and each was
defeated by the next set of words anyone tried. This is the record, so the next
author who has the idea finds the disproof before building it rather than after.

**Read this first if you are about to make a plain-English goal reach the local
docs corpus.** The idea is good. Every deterministic lexical route to it is
closed, and the reason is structural rather than a matter of tuning.

---

## The defect it was trying to fix (still open, correctly)

`ground_goal` answers exact symbols and error lines and goes **silent** on goals
written in English. That is not a bug in retrieval — it is BM25's normalizer.
A page's score is divided by the mass of every unique query term, so the score is
effectively *what fraction of this sentence does one page cover*. No single
documentation page covers argparse **and** CSV **and** command-line interfaces,
so a multi-topic sentence scores every page beneath `RELEVANCE_FLOOR` **by
construction**.

Measured on the real 2026-07 corpus (13,803 pages):

| goal | top score | floor | best page |
|---|---|---|---|
| `build a CLI using argparse that reads a csv file` | **0.2986** | 0.35 | `library/csv` — the right one |
| junk control: `purple elephant birthday cake recipe` | **0.2643** | 0.35 | MDN example prose |

The retrieval was never wrong. The gate discarded the right answer by five
hundredths — and **lowering the floor is not available**, because the operator's
real goal and pure nonsense score 0.262 and 0.264. There is no threshold on the
number line that admits one and excludes the other.

---

## The four gates, and how each died

The rung pulled "salient" words out of the goal and resolved them as symbols.
Each gate below was added after the previous one was measured to fail.

### Gate 1 — SALIENCE (corpus document frequency ≤ 0.05)

*Is this word rare enough to be a topic rather than sentence scaffolding?*

**1,659 plain lowercase words ≥3 chars pass gates 1+2 on the real corpus.**
No cap separates the classes, because the words that must be rejected are
interleaved with the words that must be admitted:

| must REJECT | df ratio | must ADMIT | df ratio |
|---|---|---|---|
| `track` | .0492 | `title` | .0241 |
| `print` | .0477 | `keyboard` | .0167 |
| `screen` | .0468 | `lock` | .0147 |
| `date` | .0429 | `cursor` | .0140 |
| `header` | .0411 | `marker` | .0139 |

### Gate 2 — SYMBOL (resolves exactly in the docset index)

*Is it a documented thing?*

Ordinary English words **are** docset entries. That is the entire problem, not a
wrinkle in it. `with`, `file` and `type` are all genuine entries; so are
`picture`, `progress`, `link`, `summary` and `big`.

### Gate 3 — CORROBORATION (page in the goal's own top-40 BM25 ranking)

*Does the goal's own ranking point at this page?*

Separated the design set cleanly (library pages ranked 1–27, junk 64–727) and
then failed on held-out goals, because **rank is scale-free and has no notion of
"related at all"**. A SHORT page carrying a rare word ranks HIGH by construction
— BM25 divides by document length, so a short page has to match very little to
place well.

Measured from the exact query, on the real corpus:

| query (verbatim) | page | rank | score | page length |
|---|---|---|---|---|
| `my grandmother baked a big cake for the village fete` | `[html] reference/elements/big` (**deprecated**) | **10** of 13,803 | 0.0783 | **0.55×** average |

Rank 10 sits comfortably inside any usable bound — the shipped one was 40 — so
gate 3 admits a page that a sentence about baking has no business reaching.
Excluding it needs a bound below 10, which also excludes most genuine library
groundings (they ranked 1–27). Independently measured, the classes fully
interleave: library kept at ranks 1..34, junk kept at 1, 1, 3, 4, 13, 18, 39.

> **An unresolved discrepancy, stated rather than smoothed.** The independent
> review reported this page at **rank 1**; re-measuring from the same verbatim
> query gives **rank 10**, with an *identical* score (0.0783) and an identical
> length ratio (0.55×). Identical scores with different ranks means both
> measurements score the same way over a **different ranked population** — most
> plausibly one ranks within a filtered candidate set rather than over every
> scoring page. The conclusion is unaffected (1 and 10 are both far inside the
> bound), so it was not worth a further round; but neither number should be
> quoted onward without saying which population it ranks over. That ambiguity is
> the same family as the truncated-query defect below.

A note that cost a round: the fixture's only gate-3 negative control was
engineered **48× average document length** so length-normalisation would push it
past the bound. That made every short page in the fixture a positive case, and a
29/36-mutant suite sat green over the real defect. **A short off-topic negative
control cannot be constructed** — that impossibility *is* the finding, and it is
recorded here rather than as a test, because with gate 3 deleted such a test
would assert properties of a fixture no shipping code consumes.

A second note, on the honesty of that lock while it briefly existed: its fixture
page shared the goal's **entire content vocabulary** (`small`, `tool`, `file`,
`records`), so its rank-1 result was **over-determined** — plain vocabulary
overlap produced it, and the test still passed with the trap word removed
entirely. It would have passed on a fixture where the phenomenon it named did
not exist. The claim it made is independently true (a page sharing *only* the
rare word, still short, still ranks top-10), but the instrument was measuring
something broader than its name. Same class as everything else in this record,
found in the test written to lock an honest finding.

### Gate 4 — LIBRARY (module pages only, `library/<name>`, no fragment)

*Is the page a library, rather than a markup element or a style property?*

Fixed the element class completely on the set that motivated it (15/15 library
goals kept, 10 of 12 dropped hits junk) and **moved the defect one namespace
over**. **163 plain-lowercase words resolve to a module page and pass gates
1+2+4** — overwhelmingly stdlib module names, and exactly the vocabulary a
non-technical operator writes:

> `calendar, socket, queue, site, copy, email, random, signal, platform,
> secrets, wave, turtle, glob, enum, locale, webbrowser` — all 16 confirmed
> present in the passing set.

*(The independent review reported 153 for this population; re-measuring gives
163. The gap is small and does not move the conclusion, but the number recorded
here is the one measured by the method stated at the top of this section:
`^[a-z]+$`, length ≥ 3, df ratio ≤ 0.05, resolving to a `library/<name>` symbol
row with no fragment.)*

On 30 blind goals using those words in their everyday sense, only 10 stayed
silent. Every goal below is the **exact string measured**, and every rank/score
is the resolved page's, under that whole goal:

| goal (verbatim) | grounded on | rank | score | what that module actually is |
|---|---|---|---|---|
| `make a copy of my important documents every friday` | `library/copy` | 25 | 0.1679 | object copying — steers the planner away from `shutil` |
| `manage the queue at my barber shop on a saturday` | `library/queue` | 15 | 0.1273 | thread-safe queues |
| `build a site for my running club` | `library/site` | 36 | 0.1982 | `sys.path` configuration |
| `an app for the operator of the village bus` | `library/operator` | 9 | 0.1734 | functional operators |
| `tell me the stat for how many miles I cycled` | `library/stat` | 17 | 0.1503 | file-status constants |
| `keep a mailbox of notes from my grandchildren` | `library/mailbox` | 2 | 0.2788 | mbox file formats |

### Candidate 5 — the corroborating page's SCORE (measured, rejected)

A six-point sample suggested junk topped out at 0.1588 and good bottomed out at
0.2985. Measured under a tune/test split over 164 goals it **failed on the
tuning set before reaching the test set**:

| set | GOOD min | JUNK max | separates? |
|---|---|---|---|
| TUNE (design + held-out 1, 71 goals) | 0.2016 | **0.3279** | **No** |
| TEST (held-out 2 + 3, 93 goals, blind) | 0.2503 | **0.4284** | **No** |

Why the small sample looked separable: every junk example in it was a word
*incidental* to a long goal. The cases that break it are goals whose **subject**
is the word — `somewhere to keep my secrets safe with a password` resolves
`library/secrets` at **0.4284**, higher than 17 of 23 genuine library
groundings. There the page genuinely earns the score.

### Candidate 6 — naming context ("use X", "the X module") — measured, rejected

Keeps 22/27 genuine goals but **loses `csv`, `sqlite3`, `datetime` and
`zipfile`** — the exact goals #1204 was raised about — while still leaking 5
traps. It is also the maintained English word list the whole design set out to
avoid.

---

## The root cause

**A large fraction of the identifiers in any documentation corpus are ordinary
English words.** Deciding whether "copy" means duplicate-a-file or the `copy`
module is **word-sense disambiguation**. It is semantic; both senses live in the
same corpus and often in the same sentence; and no lexical statistic *derived
from that corpus* can separate them.

Four thresholds, one structural reason. Each round's "fix" was the previous
round's defect wearing new vocabulary.

---

## Validation protocol (what made the disproof trustworthy)

The first three gates each passed the goals they were designed against. What
broke them was validating on goals written **after** the design was frozen.

- **Design set** — 21 goals. Used to build gates 1–3.
- **Held-out 1** — 50 goals, written after gates 1–3 froze. Broke them; used to
  design gate 4, which makes it development data from that point on.
- **Held-out 2** — 55 goals, written blind after gate 4, aimed at the direction
  gate 4 opened. Broke gate 4.
- **Held-out 3** — 38 goals, fresh vocabulary, written **before any score was
  measured**, so the score candidate had an uncontaminated test set.

A signal that only separates the goals used to design it is **fitted, not
fixed**. That distinction is the reusable part of this record.

### The recording rule, learned the expensive way

**A measurement whose input is abbreviated in the record is unreproducible by
construction.** Cite the query VERBATIM — no ellipsis, ever, in a line that
carries a number.

This cost two agents a round each. A docstring recorded a rank against
`"read a json config file..."`, with a literal ellipsis. An independent reviewer
could not know the input, guessed a plausible completion, measured **45 and 14**,
and reported the recorded **69 and 27** as a defect. Both parties were measuring
correctly; only the record was ambiguous. The four numbers in the same docstring
that reproduced first time all cited their full query; the two that "failed" both
cited a truncated one.

Two corollaries this record then had to apply to itself:

1. **State the population, not just the statistic.** "Rank 1" and "rank 10" for
   `<big>` come from identical scores over different ranked sets. A rank without
   its population is as ambiguous as a query with an ellipsis.
2. **Re-measure a number before quoting it onward**, even from a source you
   trust. Two figures inherited from review (`<big>` rank 1, 153 module names)
   did not reproduce here (10, and 163). They were corrected rather than
   repeated — repeating an unverified number is the same defect as recording an
   unreproducible one, moved one hop downstream.

---

## What is true and bankable

The **library class is real**: goals that say "use X" ground correctly and
robustly — **12/12 and 15/15 on two independent blind sets**, every named module
leading its block. The win is not imaginary; the *guessing* is what fails.

**The path that remains is a different instrument, not a fifth gate.**
`lookup.semantic_rerank` has been a declared seam since #746 slice 1. An
embedding answers *"is this page about this goal"* **directly**, where all four
gates above answered a proxy question. It should start from that seam, not from
these gates — which is why the gates are deleted rather than left dormant
(`security_by_design` principle 4: the strongest dormancy is code that isn't
there).

---

## Current shipped behaviour

`ground_goal` = exact symbol hits, then floor-gated BM25 search. Identical to
`main`. A plain-English goal grounds on **nothing**, and that silence is
deliberate: a wrong page at the head of the planner prompt silently bends the
plan, and the operator cannot see which he got.

Locked by `shared/tests/test_plan_grounding_salience.py`, which asserts the rung
is absent and that the limit still holds.

## Also landed on this branch (independent of the rung)

- **`BLARAI_RESEARCH_CORPUS_DIR` and `BLARAI_RESEARCH_INDEX_DIR` removed.** Both
  let an ambient variable relocate the trust root for text rendered into the
  planner prompt as local documentation. The corpus one needed no crafted
  SQLite — `ensure_index()` builds from whatever it is aimed at. SHA-256 pins
  prove the bytes match the manifest shipped beside them; they cannot prove the
  manifest is one we trust.
- **`load_index` refuses when it cannot verify a manifest** (was: treated
  "no manifest" as "nothing to check").
- **Usage ledger** resolves per call under `%LOCALAPPDATA%/BlarAI/research/`
  instead of a hard-coded path into another repo, so the standing
  LOCALAPPDATA-redirect discipline isolates test traffic structurally.
