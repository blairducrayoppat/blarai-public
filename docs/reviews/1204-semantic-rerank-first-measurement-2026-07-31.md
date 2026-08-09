# #1204 — the seam the disproof points at sits on the wrong side of the gate

**Status: STRUCTURAL FINDING + a first measurement that is PROMISING, NOT PROVEN.**

evidence:
- `docs/reviews/1204-semantic-rerank-probe-2026-07-31.py` — the probe, verbatim
- `docs/reviews/1204-semantic-rerank-probe-output-2026-07-31.txt` — its raw output
- `docs/reviews/1204-plan-grounding-goal-set-2026-07-31.json` — the goals, with provenance
- `docs/reviews/1204-plan-grounding-salience-disproof-2026-07-31.md` — the four dead gates

---

## 1. The finding that matters (not a measurement — read the code)

The companion disproof concludes: *"The path that remains is a different
instrument, not a fifth gate. `lookup.semantic_rerank` has been a declared seam
since #746 slice 1."*

**That seam cannot fix this defect as specified.**

`search_docs` drops every below-floor page at `lookup.py:375`, and calls
`semantic_rerank` at `:403` — on the survivors. The seam's own contract,
`:441-442`:

> "it may REORDER hits, **never add ones the lexical floor rejected** — the
> RELEVANCE_FLOOR STOP stays authoritative."

Now the defect, from the disproof's own table: the correct page for
`build a CLI using argparse that reads a csv file` is `library/csv` at
**0.2986**, against a floor of **0.35**. The right answer is discarded at
:375, before the seam runs. Reranking an empty list returns an empty list.

The seam is built, wired, and positioned downstream of the gate that causes
the defect. That is this project's recurring shape in a subtler dress than
usual — not built-and-wired-into-nothing, but built, wired, and **unable to
fire**.

**Consequence for the fix:** the deterministic-first contract has to invert.
BM25 becomes RECALL (top-N, no floor); the embedding becomes PRECISION (a
semantic floor replaces the lexical one). A rerank *behind* the lexical floor
is not worth building.

## 2. First measurement — does the embedding separate what four gates could not?

Probe: BM25 top-40 with the floor REMOVED, then bge-small-en-v1.5 cosine of
the goal against each candidate (title + first 1500 chars). Vectors are
L2-normalised, so cosine is a dot product. 13 goals from the salvaged set.

| population | worst `must_ground` | best `must_stay_silent` | separates? |
|---|---|---|---|
| all 13 goals | 0.5898 | **0.6662** (`library/secrets`) | **No** |
| excluding the CONTESTED goal | 0.5898 | **0.5614** (`library/mailbox`) | **Yes**, margin 0.0284 |

The single overlap is `somewhere to keep my secrets safe with a password`,
which the disproof labels junk and then says of it: *"There the page genuinely
earns the score."* That goal is marked CONTESTED in the goal set for exactly
this reason, and any future claim must state which way it scored it.

Two rows worth keeping:

```
build a CLI using argparse that reads a csv file
   -> embedding top:  library/argparse   cosine 0.7197
   -> BM25 top:       library/csv        0.2986   (the RIGHT page, below the 0.35 floor)
      library/argparse BM25 0.2499, rank 14/40  -- NOT the 0.2986 figure
my grandmother baked a big cake for the village fete
   -> animation/play     cosine 0.4432   (the <big> trap that killed gate 3, now last)
```

> **CORRECTED 2026-08-06 (independent review, post-merge).** The first row originally read
> `-> library/argparse cosine 0.7197 BM25 0.2986`, putting **two different pages on one line**:
> 0.2986 is `library/csv`'s BM25 score, not argparse's. The goal-set JSON has always been right
> (`:26` assigns 0.2986 to `library/csv`, "the RIGHT page"), and §1's whole structural argument
> is about `library/csv` being discarded below the floor — so the document contradicted both its
> own evidence file and its own thesis. A reader reproducing "below floor" from that row would
> chase 0.2986 against argparse and never find it. **Measured by the reviewer against the real
> pool: argparse is 0.2499 at rank 14 of 40.** The same misattribution propagated verbatim into
> #1204 ticket comment 2775 §3, corrected there too.
>
> Worth naming plainly: this is a wrong number in the document whose entire argument is that
> numbers must be read rather than narrated. It survived the branch's own §2b self-correction
> pass, which re-checked the *pages* and not the *figures*.

## 2b. CORRECTION — the pages were inspected after §2 was written, and it is worse

§2 measures whether the instrument SPEAKS OR STAYS QUIET. It does not measure
whether it is RIGHT. Resolving each grounded page against the corpus:

| goal | page chosen | what that page is | verdict |
|---|---|---|---|
| `build a CLI using argparse that reads a csv file` | `library/argparse` | argument parsing | **right** |
| B2-shaped word-frequency goal | `library/difflib` | *"Helpers for computing deltas"* — sequence comparison | **wrong** |
| `a web page that renders user comments safely without innerHTML` | `guides/comments` | *"Using HTML comments `<!-- -->`"* | **wrong** |
| `use collections.Counter and itertools.pairwise to count word bigrams` | `library/itertools` | itertools | right — **but already worked** |

**Of the three goals that are broken today, the embedding fixed one and got two
wrong.**

The `guides/comments` failure is the important one: the goal is about
user-submitted comments and injection safety; the page is about HTML comment
SYNTAX. The embedding matched the wrong SENSE of "comments" — which is the
exact root cause the companion disproof names as unsolvable lexically, and the
reason an embedding was proposed as the cure. It was not the cure here.

**Revised verdict: the separation result in §2 is real and is measuring the
wrong thing.** A margin between speaking and staying silent is worthless if the
speech is wrong two times in three. Do not cite §2 without §2b.

## 3. Why this is NOT yet a green light

1. **Four `must_ground` goals.** A 0.0284 margin on n=4. The disproof's own
   central lesson: *a signal that only separates the goals used to design it is
   fitted, not fixed.*
2. **The held-out protocol could not be run.** Sets of 50, 55 and 38 goals were
   never banked (see the goal set's `provenance`). This measurement is over
   exemplars scraped from prose — adversarial to LEXICAL gates, and blind to
   nothing where an embedding is concerned.
3. **Separation is not correctness.** The B2-shaped goal cleared the threshold
   by grounding on `library/difflib` — sequence comparison, not word counting.
   The wanted pages are `Counter` and `pairwise`. It passes the *number* and
   arguably fails the ticket's requirement of a **relevant** symbol. A future
   measurement must score the PAGE, not only the margin.
4. **Not the production device.** Ran `backend='ort-cpu'`. The NPU offload path
   was not exercised; nothing here is a latency or throughput claim.
5. The probe's B2 goal string is a **reconstruction** — ticket #1204 truncates
   that goal with an ellipsis in both places it quotes it, so the ticket's own
   acceptance predicate is not verbatim-recoverable from the ticket.

## 4. What the next attempt should do

- Recover B2's goal text from the battery card, not from the ticket.
- Write a held-out set BEFORE looking at any cosine, and bank it in the goal
  set file the same day it is written.
- Score the grounded PAGE for relevance, not just the separation margin.
- Build against the inverted contract in §1, not behind the existing floor.

**Next:** the evidence-gate that would have prevented the corpus loss is
ticketed separately; it adds tests and must wait for the in-flight #1223/#1244
merges to settle the gate baseline before it lands.
