### 2026-07-31 — The 1.4x / 1.48-1.68x discrepancy was two measurements, not one error

Four public-facing surfaces said speculative decoding gave ~1.4x. The claims register
said 1.48-1.68x sustained. A campaign session flagged this as a possible error I had
introduced in `fe480f24`, since four surfaces agreeing against one register entry
usually means the register is the outlier.

It was not an error. **They are different measurements of different configurations,
and the record was right both times.**

| Date | Draft model | Runtime | Result |
|---|---|---|---|
| 2026-05-21 | Qwen3-0.6B **INT4, unpruned** | OV 2026.0.0 | ~1.25x median, ~1.45x long -> headline **~1.4x** |
| 2026-06-28 | Qwen3-0.6B **pruned-6L INT8** | OV GenAI 2026.1.0 | 14B ~1.54x, 8B ~1.38x |
| 2026-07-10 | Qwen3-0.6B **pruned-6L INT8** | OV 2026.2.1 | short **1.68x**, long **1.48x** |

The 2026-05 walk-back from "~2x" landed on ~1.4x and was correct for that stack.
The 1.48-1.68x range came from an independent July A/B on a different draft two
runtime generations later. The register quotes `PERFORMANCE_LOG.md` line 2483
faithfully. Nothing needed retracting.

TWO THINGS I HAD WRONG IN MY OWN HEAD:

1. **1.4x was never "the long-answer number."** In May, long answers benefited MORE
   (1.45x long vs 1.25x median). By July the ordering had INVERTED — short turns now
   benefit more (1.68x vs 1.48x), because the predictable `<think>` preamble is a
   larger fraction of a short turn. `PERFORMANCE_LOG.md` calls this out explicitly at
   line 2493 as the opposite of the hypothesis.
2. **The HuggingFace card's 1.4x is an 8B figure**, not a stale 14B one. 14B ~1.5x,
   8B ~1.4x. Correct as printed. Its coincidental match to the old 14B number is what
   made this look like a contradiction.

WHAT I FIXED IN THIS COMMIT: the README's inference-stack sentence compressed the May
walk-back and the July measurement into one event, reading as though the walk-back
landed on 1.48-1.68x. It did not. Both entries now name the date, the draft model and
the runtime, so the two figures cannot be mistaken for one figure stated twice.

THE DECK IS NOT WRONG AND SHOULD NOT BE CHANGED. Lessons Deck lesson 7, "A measurement
can flatter you," carries "2x -> 1.4x" and "22 s -> 15 s". That is the May story told
as history, cited to the 2026-05-22 journal entry and commit `b699ad1`. It is a story
about the walk-back moment, not a current throughput claim. A performance surface
carries today's number; a teaching artifact carries the number that was true when the
lesson was learned.

ONE UNRECONCILED ITEM, LEFT OPEN DELIBERATELY: the 2026-07-16 addendum A1 records
spec-OFF 9.1 -> spec-ON 16.0 tok/s on the standing spine harness, which divides out to
**1.76x** — above the 1.68x ceiling the register asserts. The 07-10 interleaved A/B is
the better ratio instrument (lead-swap interleaving is its whole design point) so the
range stands, but the log never reconciles the two and a reader who does the division
will find it. Also note the two harnesses disagree on ABSOLUTE tok/s by roughly 3x
(3.15-5.33 vs 9.1-17.1 on the same model in the same week), explained only as the
throttled-sustained regime. **The ratios are internally consistent and safe to publish.
The absolute tok/s from the 07-10 A/B are not comparable to the dataset-card figures
and must never be mixed with them.**
